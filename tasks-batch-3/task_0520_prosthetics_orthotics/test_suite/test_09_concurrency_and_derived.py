"""Optimistic concurrency control, version increments, Rx-window temporal boundary,
and derived-field reconciliation.

Covers Queue B (Corner) section: cross_cutting_complexity_layers. The
consistency_model instance is an excluded_because stub (owned by Difficulty/
dual_variant_calc/order_allowed_total_estimate_vs_ledger) and is not translated.
"""
from test_helpers import validate_success, validate_error
from test_helpers.test_users import TEST_USERS, make_practitioner_headers
from test_helpers.factories import deliver_payload, resubmit_payload
from test_helpers.fixtures import (
    setup_order_at_intake, add_milestone, set_clock, create_physician, create_supplier,
    create_patient, create_signed_prescription, setup_order_auth_pending,
)
from test_helpers.api_client import api_client
from test_helpers.factories import create_device_order_payload


# ─── OCC: deliver with stale order version ───────────────────────────

def test_deliver_with_stale_order_version_rejected(api):
    """PRD §2.6: "A cascaded milestone completion or a claim-line change can move the
    order forward and bump its `version`; if the supplied `expected_device_order_version`
    does not equal the order's current `version`, delivery is rejected with
    `ERR_STALE_ORDER_VERSION` and HTTP status 412, preventing the client from acting on
    an order it has not observed in its current form."

    Design: Corner/cross_cutting_complexity_layers/occ_deliver_stale_order_version_rejected
    """
    cast = setup_order_at_intake()
    ms = add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=1)
    started = validate_success(
        api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"])), 200)
    stale_v = started["version"]  # version the client last observed
    # Completing the final milestone cascades the order to READY_FOR_FITTING and bumps
    # its version, making stale_v stale.
    api.complete_milestone(ms["id"], make_practitioner_headers(cast["fit_id"]))
    res = api.deliver_order(cast["ord_id"], deliver_payload(stale_v),
                            make_practitioner_headers(cast["fit_id"]))
    validate_error(res, "ERR_STALE_ORDER_VERSION")
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order["status"] == "READY_FOR_FITTING"


def test_resubmit_with_stale_auth_version_rejected(api):
    """PRD §2.6: "If a clock sweep advanced the authorization's bookkeeping, or another
    resubmission already fired, the `version` will have moved; if the supplied
    `expected_prior_auth_version` does not equal the authorization's current `version`,
    the resubmission is rejected with `ERR_STALE_AUTH_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_resubmit_stale_auth_version_rejected
    """
    cast = setup_order_auth_pending()  # SUBMITTED PriorAuth
    pended = validate_success(
        api.pend_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"]), 200)
    stale_pa_v = pended["version"]  # client's last observed version
    # First resubmit succeeds and advances the version.
    validate_success(
        api.resubmit_prior_auth(cast["pa_id"], resubmit_payload(stale_pa_v),
                                TEST_USERS["billing_headers"]), 200)
    # Pend again, then resubmit carrying the now-stale version.
    api.pend_prior_auth(cast["pa_id"], TEST_USERS["compliance_headers"])
    res = api.resubmit_prior_auth(cast["pa_id"], resubmit_payload(stale_pa_v),
                                  TEST_USERS["billing_headers"])
    validate_error(res, "ERR_STALE_AUTH_VERSION")


def test_order_version_increments_on_submit_auth(api):
    """PRD §2.4: "`version`: an integer that starts at 1 and increments by exactly 1 on
    every mutation."
    PRD §3.4: "Submission cascades the creation of a `PriorAuth` in `SUBMITTED` status
    whose `device_order_id` is the order, with `submission_round` of 1 and a
    `decision_deadline` set to the logical clock plus fourteen days, and it increments
    the order's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_write
    """
    cast = setup_order_at_intake(device_category="LOWER_LIMB_PROSTHETIC",
                                 diagnosis="Z89.511", medicare=True)
    assert cast["order"]["version"] == 1
    api.submit_auth(cast["ord_id"], TEST_USERS["billing_headers"])
    order = validate_success(api.get_device_order(cast["ord_id"], TEST_USERS["billing_headers"]), 200)
    assert order["version"] == 2


def test_rx_window_inclusive_at_six_month_boundary(api):
    """PRD §3.3: "The logical clock must fall at or before the prescription's
    face-to-face date plus six months; ordering against a prescription past that validity
    window is rejected with `ERR_RX_EXPIRED`."
    PRD §3.3: "Order creation also consumes the prescription as described in §3.2,
    advancing it from `SIGNED` to `CONSUMED` and incrementing the prescription's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_rx_window_boundary
    """
    set_clock("2026-05-20T00:00:00Z")
    rx_phys = create_physician(pecos=True, npi="1111111111", name="Dr Rx")
    fit = create_physician(pecos=True, npi="2222222222", name="Tech Fit")
    supplier = create_supplier()
    patient = create_patient(medicare=False)
    rx = create_signed_prescription(patient["id"], rx_phys["id"],
                                    "LOWER_EXTREMITY_ORTHOSIS", "M21.6X1",
                                    face_to_face_date="2026-05-20")
    # Advance to exactly +6 calendar months (2026-11-20): still in-window (inclusive).
    set_clock("2026-11-20T00:00:00Z")
    order = validate_success(api.create_device_order(
        create_device_order_payload(rx["id"], supplier["id"], fit["id"]),
        TEST_USERS["billing_headers"]), 201)
    assert order["status"] == "INTAKE"
    consumed = validate_success(api.get_prescription(rx["id"], TEST_USERS["billing_headers"]), 200)
    assert consumed["status"] == "CONSUMED"


def test_milestone_progress_reconciled_after_partial_completion(api):
    """PRD §3.4: "the progress percentage is the sum of the `weight` of completed
    milestones, multiplied by 100, divided by the sum of the `weight` of all milestones
    for the order, rounded half up to a whole percent; when the order has no milestones
    at all the percentage is 0."

    Design: Corner/cross_cutting_complexity_layers/derived_field_milestone_progress_reconciled_on_add
    """
    cast = setup_order_at_intake()
    ms1 = add_milestone(cast["ord_id"], cast["fit_id"], step="CASTING", weight=2)
    add_milestone(cast["ord_id"], cast["fit_id"], step="ASSEMBLY", weight=3)
    api.start_fabrication(cast["ord_id"], make_practitioner_headers(cast["fit_id"]))
    api.complete_milestone(ms1["id"], make_practitioner_headers(cast["fit_id"]))
    order = validate_success(
        api.get_device_order(cast["ord_id"], make_practitioner_headers(cast["fit_id"])), 200)
    # round_half_up(2 * 100 / 5) = 40; not yet all complete -> still FABRICATION.
    assert order["milestone_progress_pct"] == 40
    assert order["status"] == "FABRICATION"
