"""Issuing a prescription: gates, seeding, supersession and discontinuation."""

from test_helpers import (
    assert_prescription,
    book_consult,
    close_consult,
    create_prescription_payload,
    enroll_patient,
    make_patient_headers,
    make_provider_headers,
    open_screening,
    patient_version,
    platform_admin_headers,
    read_patient,
    register_clinician,
    set_clock,
    setup_active_prescription,
    setup_prescribing_consult,
    setup_shipped_order,
    submit_screening,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_prescription_defaults_units_per_cycle_to_four(api):
    """PRD §3.4: "An optional `units_per_cycle` states how many pens are dispensed
    per thirty-day cycle; it must be an integer from 1 through 4 inclusive and
    defaults to 4 when omitted."
    PRD §3.5: "For `TIRZEPATIDE` it runs 2.5 mg at rung 1, 5.0 mg at rung 2, 7.5 mg
    at rung 3, 12.5 mg at rung 4 and 15.0 mg at rung 5."
    PRD §3.4: "Its `active_route_mode` is seeded from the member's `payment_mode`,
    so an `INSURANCE` member's prescription starts on the insurance fork and a
    `CASH` member's starts on the cash fork."
    PRD §3.4: "A prescription's `supersedes_prescription_id` is null unless it
    displaced a predecessor."

    Design: Corner/entities/prescription_units_per_cycle_defaults_to_four
    """
    scenario = setup_prescribing_consult(
        patient={"email": "corner6@example.com", "full_name": "Corner Six", "payment_mode": "CASH"}
    )

    response = api.create_prescription(
        {
            "patient_id": scenario["patient"]["id"],
            "consult_id": scenario["consult"]["id"],
            "prescriber_provider_id": scenario["clinician"]["id"],
            "screening_id": scenario["screening"]["id"],
            "drug_family": "TIRZEPATIDE",
            "expected_patient_version": patient_version(scenario["patient"]["id"]),
        },
        make_provider_headers(scenario["clinician"]["id"]),
    )
    prescription = validate_success(response, 201)

    assert_prescription(prescription)
    assert prescription["units_per_cycle"] == 4
    assert prescription["dose_level"] == 1
    assert prescription["dose_mg"] == 2.5
    assert prescription["clinical_status"] == "ACTIVE"
    assert prescription["fulfillment_status"] == "UNROUTED"
    assert prescription["active_route_mode"] == "CASH"
    assert prescription["supersedes_prescription_id"] is None


def test_prescription_without_drug_family_is_refused(api):
    """PRD §3.4: "The request names the `patient_id`, the `consult_id` of the
    consult that authorised it, the `prescriber_provider_id` of the clinician of
    record, the `screening_id` of the frozen screening whose band gates the issue,
    a `drug_family` of either `SEMAGLUTIDE` or `TIRZEPATIDE`, and the
    `expected_patient_version` described in §2.8."
    PRD §2.7: "**Body shape.** Every required field is present, every value matches
    its declared type, every enum value is a declared member"

    Design: Corner/entities/prescription_missing_required_field_returns_validation
    """
    scenario = setup_prescribing_consult(
        patient={"email": "corner5@example.com", "full_name": "Corner Five"}
    )

    response = api.create_prescription(
        {
            "patient_id": scenario["patient"]["id"],
            "consult_id": scenario["consult"]["id"],
            "prescriber_provider_id": scenario["clinician"]["id"],
            "screening_id": scenario["screening"]["id"],
            "units_per_cycle": 2,
            "expected_patient_version": patient_version(scenario["patient"]["id"]),
        },
        make_provider_headers(scenario["clinician"]["id"]),
    )
    validate_error(response, "ERR_VALIDATION")

    rows, meta = validate_paginated(
        api.list_prescriptions(
            platform_admin_headers(), params={"patient_id": scenario["patient"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_new_prescription_supersedes_the_standing_active_one(api):
    """PRD §3.4: "When a prescription is issued for a member who already holds a
    prescription whose `clinical_status` is `ACTIVE`, that standing prescription is
    discontinued as a side effect of the issue: its `clinical_status` moves
    `ACTIVE → DISCONTINUED`, its `discontinue_reason` is set to `SUPERSEDED`, the
    new prescription's `supersedes_prescription_id` is set to the superseded
    prescription's `id`, and every pharmacy order of the superseded prescription
    still sitting in `CREATED` or `RESERVED` is cancelled with `cancel_reason`
    `CLINICAL_HOLD` — which, for the reserved ones, returns their units to the
    lot's `available_units` under §2.10."

    Design: Corner/state_machines/new_prescription_supersedes_prior_active_one
    """
    scenario = setup_prescribing_consult(
        patient={"email": "sm6@example.com", "full_name": "Sm Six"}
    )
    member, clinician = scenario["patient"], scenario["clinician"]
    second_consult = book_consult(
        member["id"],
        clinician["id"],
        scheduled_start_at="2026-06-02T17:00:00Z",
        scheduled_end_at="2026-06-02T17:30:00Z",
    )
    close_consult(second_consult["id"], clinician["id"], "PRESCRIBE")

    first = validate_success(
        api.create_prescription(
            create_prescription_payload(
                member["id"],
                scenario["consult"]["id"],
                clinician["id"],
                scenario["screening"]["id"],
                patient_version(member["id"]),
                drug_family="SEMAGLUTIDE",
                units_per_cycle=2,
            ),
            make_provider_headers(clinician["id"]),
        ),
        201,
    )

    second = validate_success(
        api.create_prescription(
            create_prescription_payload(
                member["id"],
                second_consult["id"],
                clinician["id"],
                scenario["screening"]["id"],
                patient_version(member["id"]),
                drug_family="TIRZEPATIDE",
                units_per_cycle=2,
            ),
            make_provider_headers(clinician["id"]),
        ),
        201,
    )

    assert second["supersedes_prescription_id"] == first["id"]
    assert second["clinical_status"] == "ACTIVE"
    assert second["dose_mg"] == 2.5

    superseded = validate_success(
        api.get_prescription(first["id"], platform_admin_headers())
    )
    assert superseded["clinical_status"] == "DISCONTINUED"
    assert superseded["discontinue_reason"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api.list_prescriptions(
            platform_admin_headers(), params={"supersedes_prescription_id": first["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_below_band_screening_is_adjudicated_ineligible(api):
    """PRD §3.2: "**Below band.** Otherwise the screening lands in `INELIGIBLE`
    with `decision_reason` set to `BMI_BELOW_BAND`."
    PRD §3.2: "Every submission mirrors its outcome onto the member:
    `eligibility_status` on the Patient row is set to `ELIGIBLE`, `INELIGIBLE` or
    `DEFERRED` to match, and the member's `version` is incremented by one."

    Design: Difficulty/cross_entity_state_dependency/prescription_creation_requires_eligible_screening
    """
    set_clock("2026-06-01T00:00:00Z")
    member = enroll_patient(
        email="wren@example.com", full_name="Wren Diaz", weight_kg=77.0, comorbidity_codes=[]
    )
    clinician = register_clinician()
    screening = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=77.0,
        egfr=88.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )

    decided = submit_screening(screening["id"], clinician["id"])

    assert decided["assessed_bmi"] == 26.6
    assert decided["status"] == "INELIGIBLE"
    assert decided["decision_reason"] == "BMI_BELOW_BAND"
    assert read_patient(member["id"])["eligibility_status"] == "INELIGIBLE"


def test_prescription_citing_an_ineligible_screening_is_refused(api):
    """PRD §3.4: "The cited screening must currently be in `ELIGIBLE` status and
    must name the same `patient_id` as the prescription request; a screening that
    is `DRAFT`, `DEFERRED` or `INELIGIBLE`, or one belonging to a different member,
    is rejected with `ERR_SCREENING_NOT_ELIGIBLE` (409)."

    Design: Difficulty/cross_entity_state_dependency/prescription_creation_requires_eligible_screening
    """
    scenario = setup_prescribing_consult(
        patient={"email": "wren2@example.com", "full_name": "Wren Diaz", "weight_kg": 95.0}
    )
    member, clinician = scenario["patient"], scenario["clinician"]

    later = open_screening(
        member["id"],
        clinician["id"],
        recorded_weight_kg=95.0,
        egfr=25.0,
        lab_collected_at="2026-05-20T00:00:00Z",
    )
    later = submit_screening(later["id"], clinician["id"])
    assert later["status"] == "INELIGIBLE"

    response = api.create_prescription(
        create_prescription_payload(
            member["id"],
            scenario["consult"]["id"],
            clinician["id"],
            later["id"],
            patient_version(member["id"]),
            drug_family="SEMAGLUTIDE",
            units_per_cycle=2,
        ),
        make_provider_headers(clinician["id"]),
    )
    validate_error(response, "ERR_SCREENING_NOT_ELIGIBLE")

    rows, meta = validate_paginated(
        api.list_prescriptions(platform_admin_headers(), params={"patient_id": member["id"]})
    )
    assert meta["total_count"] == 0


def test_stale_member_version_rejects_the_prescription_create(api):
    """PRD §2.8: "A `POST /glp1/prescriptions` request must carry
    `expected_patient_version`, a non-optional integer field holding the client's
    last observed `version` of the Patient named by `patient_id`. If that value
    does not equal the Patient's current `version`, the request is rejected with
    `ERR_STALE_PATIENT_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_patient_version_rejects_prescription_create
    """
    scenario = setup_prescribing_consult(
        patient={"email": "occ1@example.com", "full_name": "Occ One"}
    )
    member, clinician = scenario["patient"], scenario["clinician"]
    stale_version = patient_version(member["id"])

    api.update_patient_vitals(
        member["id"], {"weight_kg": 93.0}, make_provider_headers(clinician["id"])
    )

    refused = api.create_prescription(
        create_prescription_payload(
            member["id"],
            scenario["consult"]["id"],
            clinician["id"],
            scenario["screening"]["id"],
            stale_version,
            drug_family="SEMAGLUTIDE",
            units_per_cycle=2,
        ),
        make_provider_headers(clinician["id"]),
    )
    validate_error(refused, "ERR_STALE_PATIENT_VERSION")

    rows, meta = validate_paginated(
        api.list_prescriptions(platform_admin_headers(), params={"patient_id": member["id"]})
    )
    assert meta["total_count"] == 0

    refreshed_version = patient_version(member["id"])
    accepted = api.create_prescription(
        create_prescription_payload(
            member["id"],
            scenario["consult"]["id"],
            clinician["id"],
            scenario["screening"]["id"],
            refreshed_version,
            drug_family="SEMAGLUTIDE",
            units_per_cycle=2,
        ),
        make_provider_headers(clinician["id"]),
    )
    prescription = validate_success(accepted, 201)
    assert prescription["clinical_status"] == "ACTIVE"
    assert patient_version(member["id"]) == refreshed_version + 1


def test_discontinuation_reduces_the_due_rung_and_ends_the_prescription(api):
    """PRD §3.4: "The transition is permitted from either `ACTIVE` or `HELD` — only
    an already-`DISCONTINUED` prescription refuses it, with `ERR_INVALID_STATE`
    (409). The reason from the request body is recorded; every pharmacy order for
    that prescription in `CREATED` or `RESERVED` is cancelled with `cancel_reason`
    `CLINICAL_HOLD`, releasing any reserved units back to the lot; and — unlike the
    supersession path — every titration rung of that prescription in `DUE` or
    `HELD` is moved to `REDUCED` with its `administered_at` set to the clock."

    Design: Corner/state_machines/discontinued_prescription_is_terminal_and_locks_refill
    """
    scenario = setup_active_prescription(
        patient={"email": "sm5@example.com", "full_name": "Sm Five"}
    )
    member = scenario["patient"]

    ended = validate_success(
        api.discontinue_prescription(
            scenario["prescription"]["id"],
            {"discontinue_reason": "PATIENT_REQUEST"},
            make_patient_headers(member["id"]),
        )
    )

    assert ended["clinical_status"] == "DISCONTINUED"
    assert ended["discontinue_reason"] == "PATIENT_REQUEST"
    assert ended["fulfillment_status"] == "UNROUTED"

    rung = validate_success(
        api.get_titration_step(scenario["step"]["id"], platform_admin_headers())
    )
    assert rung["status"] == "REDUCED"


def test_refill_request_on_a_discontinued_prescription_is_refused(api):
    """PRD §3.4: "A member or clinician may then request a refill, advancing it
    `DISPENSED → REFILL_DUE`; this requires the axis to currently read `DISPENSED`
    and requires the clinical axis to read `ACTIVE`, and a held or discontinued
    prescription is refused with `ERR_PRESCRIPTION_NOT_ACTIVE` (409)."

    Design: Corner/state_machines/discontinued_prescription_is_terminal_and_locks_refill
    """
    scenario = setup_shipped_order(
        patient={"email": "sm5b@example.com", "full_name": "Sm Five B"}
    )
    member = scenario["patient"]

    dispensed = validate_success(
        api.get_prescription(scenario["prescription"]["id"], platform_admin_headers())
    )
    assert dispensed["fulfillment_status"] == "DISPENSED"

    validate_success(
        api.discontinue_prescription(
            scenario["prescription"]["id"],
            {"discontinue_reason": "CLINICAL"},
            make_patient_headers(member["id"]),
        )
    )

    response = api.request_refill(
        scenario["prescription"]["id"], {}, make_patient_headers(member["id"])
    )
    validate_error(response, "ERR_PRESCRIPTION_NOT_ACTIVE")
