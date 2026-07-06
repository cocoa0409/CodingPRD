"""State-machine transitions: invalid transitions, terminal lockdown, initial state,
clock-sweep expiry, milestone bubble-up, milestone precondition, and replacement.

Covers Queue B (Corner) section: state_machines.
"""
from test_helpers import validate_success, validate_error, is_valid_uuid
from test_helpers.assertions import assert_same_instant
from test_helpers.test_users import TEST_USERS, make_physician_headers, make_practitioner_headers
from test_helpers.factories import create_physician_payload, create_patient_payload, create_prescription_payload
from test_helpers.fixtures import (
    set_clock, setup_order_at_intake, setup_order_auth_pending, add_milestone,
    setup_repair_reported, assess_repair, deliver,
)


def test_sign_already_signed_prescription_invalid_state(api):
    """PRD §3.10: "State legality is checked fifth: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/sign_prescription_from_signed_invalid_state
    """
    phys = validate_success(api.create_physician(
        create_physician_payload(full_name="Dr A", npi="1111111111", pecos_enrolled=True),
        TEST_USERS["compliance_headers"]), 201)
    patient = validate_success(api.create_patient(
        create_patient_payload(full_name="Pat S", payer_type="COMMERCIAL"),
        TEST_USERS["billing_headers"]), 201)
    rx = validate_success(api.create_prescription(
        create_prescription_payload(patient["id"], phys["id"],
                                    device_category="SPINAL_ORTHOSIS",
                                    primary_diagnosis_code="M54.5",
                                    face_to_face_date="2026-04-20"),
        make_physician_headers(phys["id"])), 201)
    api.sign_prescription(rx["id"], make_physician_headers(phys["id"]))
    res = api.sign_prescription(rx["id"], make_physician_headers(phys["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_deliver_from_intake_invalid_state(api):
    """PRD §3.5: "The delivery attestation is performed by a `Practitioner` on an order
    in `READY_FOR_FITTING`, advancing it to the terminal `DELIVERED` state."
    PRD §3.10: "State legality is checked fifth: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/deliver_from_intake_invalid_state
    """
    from test_helpers.factories import deliver_payload
    cast = setup_order_at_intake()
    res = api.deliver_order(cast["ord_id"], deliver_payload(cast["order"]["version"]),
                            make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_cancel_cancelled_order_terminal_lockdown(api):
    """PRD §3.3: "Cancellation is available to a `BillingSpecialist` while the order is
    in either `INTAKE` or `AUTH_PENDING`, moving it to the terminal `CANCELLED` state and
    incrementing the order's `version`."
    PRD §3.10: "State legality is checked fifth: a transition not defined from the
    resource's current state yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_state_lockdown_cancelled_order
    """
    cast = setup_order_at_intake()
    validate_success(api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    res = api.cancel_order(cast["ord_id"], TEST_USERS["billing_headers"])
    validate_error(res, "ERR_INVALID_STATE")


def test_priorauth_initial_state_on_submit(api):
    """PRD §3.4: "Submission cascades the creation of a `PriorAuth` in `SUBMITTED` status
    whose `device_order_id` is the order, with `submission_round` of 1 and a
    `decision_deadline` set to the logical clock plus fourteen days, and it increments
    the order's `version`."

    Design: Corner/state_machines/initial_state_priorauth_submitted
    """
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    pa = validate_success(api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"]), 201)
    assert pa["status"] == "SUBMITTED"
    assert pa["submission_round"] == 1
    # clock 2026-06-01 + 14 days = 2026-06-15.
    assert_same_instant(pa["decision_deadline"], "2026-06-15T00:00:00Z")


def test_priorauth_auto_expires_on_clock_sweep(api):
    """PRD §3.9: "Advancing the clock has two cascading effects. First, every `PriorAuth`
    still in `SUBMITTED` or `PENDED` whose `decision_deadline` now lies in the past —
    that is, whose deadline the clock has passed — is swept to `EXPIRED`."

    Design: Corner/state_machines/priorauth_auto_expire_on_clock_sweep
    """
    cast = setup_order_auth_pending()  # SUBMITTED PriorAuth, deadline 2026-06-15
    set_clock("2026-06-16T00:00:00Z")  # past the deadline
    pa = validate_success(api.get_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    assert pa["status"] == "EXPIRED"


def test_bubble_up_fabrication_to_ready_on_last_milestone(api):
    """PRD §3.4: "When the recomputation finds that every milestone for the order is
    complete, the progress reaches 100 and the order cascades from `FABRICATION` to
    `READY_FOR_FITTING`, with the order's `version` incrementing on the cascade."

    Design: Corner/state_machines/bubble_up_fabrication_to_ready_on_last_milestone
    """
    cast = setup_order_at_intake()
    ms1 = add_milestone(cast["ord_id"], cast["fit_id"], step="CASTING", weight=2)
    ms2 = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=3)
    api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    api.complete_milestone(ms1["id"], make_practitioner_headers(cast["fit_id"]))
    api.complete_milestone(ms2["id"], make_practitioner_headers(cast["fit_id"]))
    order = validate_success(
        api.get_device_order(cast["ord_id"], make_practitioner_headers(cast["fit_id"])), 200)
    assert order["milestone_progress_pct"] == 100
    assert order["status"] == "READY_FOR_FITTING"


def test_start_fabrication_requires_milestone(api):
    """PRD §3.4: "For an order that does not require prior authorization, a `Practitioner`
    starts fabrication directly, advancing the order from `INTAKE` to `FABRICATION`. This
    is permitted only when `requires_prior_auth` is false and at least one fabrication
    milestone already exists for the order; an attempt with no milestone defined is
    rejected with `ERR_MILESTONE_REQUIRED`."

    Design: Corner/state_machines/start_fabrication_requires_milestone
    """
    cast = setup_order_at_intake()  # no milestones
    res = api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_MILESTONE_REQUIRED")


def test_replacement_in_warranty_rejected(api):
    """PRD §3.8: "Alternatively, a `ComplianceOfficer` authorizes a replacement,
    permitted only when `warranty_applies` is false — in-warranty failures are repaired,
    not replaced, under the five-year reasonable-useful-lifetime rule, and an attempt
    while warranty still applies is rejected with `ERR_REPLACEMENT_IN_WARRANTY`."

    Design: Corner/state_machines/replacement_in_warranty_rejected
    """
    # Orthosis delivered 2026-06-01 -> warranty 2027-06-01. Repair reported and assessed
    # at 2026-09-01 (in warranty -> warranty_applies true).
    cast, rr = setup_repair_reported(delivered_clock="2026-06-01T00:00:00Z",
                                     report_clock="2026-09-01T00:00:00Z",
                                     supplier_overrides={"accreditation_expiry": "2028-01-01T00:00:00Z",
                                                         "surety_bond_active": True})
    assess_repair(rr["id"], cast["fit_id"], parts_cents=5000)
    res = api.authorize_replacement(rr["id"], TEST_USERS["compliance_headers"])
    validate_error(res, "ERR_REPLACEMENT_IN_WARRANTY")


def test_replacement_authorized_spins_off_new_order(api):
    """PRD §3.8: "Authorizing a replacement advances the request from `ASSESSED` to
    `REPLACEMENT_AUTHORIZED`, cascades the creation of a new `DeviceOrder` in `INTAKE`
    that clones the original order's `prescription_id` and `supplier_id`, sets the
    request's `replaces_order_id` to that new order's `id` — a self-referential link back
    into the device-order population — and increments the request's `version`."

    Design: Corner/state_machines/replacement_authorized_spins_off_new_order_cascade
    """
    # Out-of-warranty: delivered 2026-06-01 (warranty 2027-06-01), repair assessed
    # 2027-09-01 (after warranty -> warranty_applies false).
    cast, rr = setup_repair_reported(delivered_clock="2026-06-01T00:00:00Z",
                                     report_clock="2027-09-01T00:00:00Z",
                                     supplier_overrides={"accreditation_expiry": "2030-01-01T00:00:00Z",
                                                         "surety_bond_active": True})
    assess_repair(rr["id"], cast["fit_id"], parts_cents=8000)
    authorized = validate_success(
        api.authorize_replacement(rr["id"], TEST_USERS["compliance_headers"]), 200)
    assert authorized["status"] == "REPLACEMENT_AUTHORIZED"
    assert authorized["replaces_order_id"] is not None
    assert is_valid_uuid(authorized["replaces_order_id"])
    assert authorized["replaces_order_id"] != cast["ord_id"]
