"""The five-deep validation cascade, the survey-posture ladder it drives, and the
root cause analysis that has to finish before anything downstream may close."""
from test_helpers import (
    as_instant,
    assign_consult,
    create_candidate_nurse,
    create_certified_nurse,
    create_consult,
    create_order,
    create_patient,
    create_product,
    create_surface,
    create_unit,
    file_assessment,
    find_case_for_assessment,
    get_success_data,
    read_unit_version,
    triage_consult,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import (
    make_director_headers,
    make_materials_headers,
    make_nurse_headers,
)


DIRECTOR = make_director_headers()
MATERIALS = make_materials_headers()


def _one_open_rca_a_pending_second_and_a_requested_order(api, second_admitted_at):
    """Unit 7W already carrying one hospital-acquired case, one still-`REQUESTED`
    rental order raised while the posture was `OPEN`, and a second pending staging
    on a different patient and a different body site."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    omar = create_certified_nurse(unit, api=api, full_name="Omar Verify", ce_credits=30)
    first_patient = create_patient(
        unit,
        api=api,
        mrn="MRN-H1",
        admitted_at="2026-07-20T00:00:00Z",
        comorbidity_count=0,
        device_related_risk=False,
    )
    second_patient = create_patient(
        unit,
        api=api,
        mrn="MRN-H2",
        admitted_at=second_admitted_at,
        comorbidity_count=0,
        device_related_risk=False,
    )
    first_consult = create_consult(
        unit,
        first_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_3",
        clinical_note="Sacral wound, full thickness.",
    )
    triage_consult(first_consult, nina, api=api)
    assign_consult(first_consult, nina, api=api)
    first_assessment = file_assessment(
        first_consult,
        first_patient,
        nina,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_3",
        measured_area_cm2=12,
        observed_at="2026-08-01T00:00:00Z",
    )
    validate_success(
        api.validate_skin_assessment(
            first_assessment["id"],
            {"confirmed_stage": "STAGE_3", "present_on_admission_confirmed": False},
            make_nurse_headers(omar["id"]),
        )
    )
    first_case = find_case_for_assessment(first_assessment["id"], api=api)
    assert first_case["status"] == "RCA_REQUIRED"

    surface = create_surface(
        api,
        asset_tag="BED-010",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )
    order = create_order(
        unit,
        first_patient,
        surface,
        api=api,
        rental_start="2026-08-10T00:00:00Z",
        rental_end="2026-08-13T00:00:00Z",
        authorized_days=3,
        consult_request_id=first_consult["id"],
    )
    assert order["requires_director_override"] is False, (
        "at open_hapi_rca_count 1 the posture is still OPEN, so nothing is held"
    )
    assert order["posture_hold_applied_at"] is None

    second_consult = create_consult(
        unit,
        second_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_4",
        clinical_note="Heel wound with exposed bone.",
    )
    triage_consult(second_consult, nina, api=api)
    assign_consult(second_consult, nina, api=api)
    return {
        "unit": unit,
        "omar": omar,
        "second_patient": second_patient,
        "first_case": first_case,
        "order": order,
        "second_consult": second_consult,
        "second_assessment_inputs": (second_consult, second_patient, nina),
    }


def test_one_validation_walks_five_hops_out_to_a_rental_order(api):
    """Each hop is caused by the hop before it, and the last lands on an unnamed row.

    PRD §3.5: "Validation then runs a five-deep cascade, each hop caused by the hop
    before it."
    PRD §3.5: "The fifth hop follows from the fourth, but only when that
    re-derivation actually changed `survey_posture` to `RESTRICTED` or `FROZEN`:
    every rental order on that unit whose `fulfillment_status` is still `REQUESTED`
    has `requires_director_override` set to true and `posture_hold_applied_at`
    stamped with the logical clock, and each such order is versioned."
    PRD §3.5: "A single staging validation therefore ends four hops away, holding
    rental orders that have nothing to do with the patient assessed."
    PRD §3.8: "The order starts with `fulfillment_status` `REQUESTED` and
    `billing_status` `UNBILLED`, and no money moves at creation — creation is a
    costing exercise, not a ledger event."

    Design: Difficulty/transitive_cascade/validate_hapi_cascades_case_rca_unit_posture_and_order_hold
    """
    scenario = _one_open_rca_a_pending_second_and_a_requested_order(
        api, second_admitted_at="2026-07-20T00:00:00Z"
    )
    unit, omar, order = scenario["unit"], scenario["omar"], scenario["order"]
    second_consult, second_patient, nina = scenario["second_assessment_inputs"]
    assessment = file_assessment(
        second_consult,
        second_patient,
        nina,
        api=api,
        anatomic_location="HEEL_LEFT",
        observed_stage="STAGE_4",
        measured_area_cm2=8,
        observed_at="2026-08-01T00:00:00Z",
    )
    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["status"] == "OPEN"

    hop_one = validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_4", "present_on_admission_confirmed": False},
            make_nurse_headers(omar["id"]),
        )
    )
    assert hop_one["validation_status"] == "VALIDATED"
    assert hop_one["confirmed_stage"] == "STAGE_4"
    assert hop_one["validated_by_user_id"] == omar["id"]
    assert hop_one["poa_determination"] == "HAPI", (
        "the only documentation of the heel is 2026-08-01T00:00:00Z, past the window "
        "end of 2026-07-21T00:00:00Z"
    )
    assert (
        get_success_data(api.get_patient(second_patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is False
    ), "only a present-on-admission verdict sets that flag"

    after_consult = get_success_data(
        api.get_consult_request(second_consult["id"], DIRECTOR)
    )
    assert after_consult["acuity_score"] == 80.0, (
        "(80 stage + 0 comorbidity + 0 device + min(15, floor(8 / 10) * 5)) * 1.00"
    )
    assert after_consult["priority_band"] == "P1"
    assert as_instant(after_consult["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z")

    after_case = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert after_case["classification"] == "HAPI", "hop 2"
    assert after_case["status"] == "RCA_REQUIRED", "hop 3, off the back of hop 2"
    assert as_instant(after_case["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z"), "the clock plus 72 hours"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 2, "hop 4"
    assert after_unit["survey_posture"] == "RESTRICTED", (
        "2 is at the RESTRICTED floor and below the FROZEN floor of 4"
    )

    after_order = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert after_order["requires_director_override"] is True, (
        "hop 5 reached an order the validate call never named"
    )
    assert as_instant(after_order["posture_hold_applied_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert after_order["fulfillment_status"] == "REQUESTED", (
        "the posture hold moves neither state dimension"
    )
    assert after_order["billing_status"] == "UNBILLED"
    assert after_unit["rental_encumbered_cents"] == 0, "the hold moves no money"

    untouched_case = get_success_data(
        api.get_pressure_injury_case(scenario["first_case"]["id"], DIRECTOR)
    )
    assert untouched_case["status"] == "RCA_REQUIRED", (
        "only the case belonging to the validated assessment was reclassified"
    )


def test_a_present_on_admission_verdict_stops_the_cascade_after_two_hops(api):
    """Hops 3, 4 and 5 exist only downstream of `CLASSIFIED_HAPI`.

    PRD §3.5: "The third hop fires only when the second hop reached
    `CLASSIFIED_HAPI`: that case immediately moves `CLASSIFIED_HAPI →
    RCA_REQUIRED` and its `rca_due_at` is set to the logical clock plus 72 hours."
    PRD §3.6: "A case classified present-on-admission takes `classification` `POA`
    and lands in `CLASSIFIED_POA`; its unit's `open_hapi_rca_count` is explicitly
    *not* touched and no investigation is opened, because a wound the patient
    arrived with is not this hospital's incident."
    PRD §3.5: "The first hop is the assessment's own mutation just described, plus,
    when `poa_determination` came out `POA`, setting the patient's
    `poa_skin_assessment_documented` to true and versioning the patient."

    Design: Difficulty/transitive_cascade/validate_hapi_cascades_case_rca_unit_posture_and_order_hold
    """
    scenario = _one_open_rca_a_pending_second_and_a_requested_order(
        api, second_admitted_at="2026-07-31T12:00:00Z"
    )
    unit, omar, order = scenario["unit"], scenario["omar"], scenario["order"]
    second_consult, second_patient, nina = scenario["second_assessment_inputs"]
    assessment = file_assessment(
        second_consult,
        second_patient,
        nina,
        api=api,
        anatomic_location="HEEL_LEFT",
        observed_stage="STAGE_4",
        measured_area_cm2=8,
        observed_at="2026-08-01T00:00:00Z",
        present_on_admission_claimed=True,
    )
    case = find_case_for_assessment(assessment["id"], api=api)

    hop_one = validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_4", "present_on_admission_confirmed": True},
            make_nurse_headers(omar["id"]),
        )
    )
    assert hop_one["validation_status"] == "VALIDATED"
    assert hop_one["poa_determination"] == "POA", (
        "the observation at 2026-08-01T00:00:00Z is inside the window ending "
        "2026-08-01T12:00:00Z"
    )
    assert (
        get_success_data(api.get_patient(second_patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is True
    )

    after_case = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert after_case["classification"] == "POA", "hop 2 still runs"
    assert after_case["status"] == "CLASSIFIED_POA", "and it terminates there"
    assert after_case["rca_due_at"] is None, "hop 3 never fired"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 1, (
        "hop 4 never fired, so the counter still shows only the earlier case"
    )
    assert after_unit["survey_posture"] == "OPEN"
    assert after_unit["rental_encumbered_cents"] == 0

    after_order = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert after_order["requires_director_override"] is False, (
        "hop 5 never fired because the posture did not change"
    )
    assert after_order["posture_hold_applied_at"] is None
    assert after_order["version"] == order["version"], "the order was not versioned"

    untouched_case = get_success_data(
        api.get_pressure_injury_case(scenario["first_case"]["id"], DIRECTOR)
    )
    assert untouched_case["status"] == "RCA_REQUIRED"


def test_a_case_cannot_be_closed_from_the_middle_of_its_analysis(api):
    """Closure is reachable from two states, and `RCA_IN_PROGRESS` is not one.

    PRD §2.10 rung 14: "The pressure injury case's `status` is a legal starting
    state: rca-start requires `RCA_REQUIRED`, rca-complete requires
    `RCA_IN_PROGRESS`, close requires either `RCA_COMPLETE` or `CLASSIFIED_POA` —
    `ERR_CASE_INVALID_STATE` (409), on
    `POST /pressure-injury-cases/{case_id}/rca-start`, `/rca-complete` and
    `/close`."
    PRD §3.6: "From `RCA_COMPLETE`, the case moves `RCA_COMPLETE → CLOSED` with
    `closed_at` stamped from the logical clock, and it then reverses the validation
    cascade precisely: the unit's `open_hapi_rca_count` falls by 1,
    `survey_posture` is re-derived on the same three-rung ladder, the unit is
    versioned, and — only when that re-derivation returns `survey_posture` all the
    way to `OPEN` — every rental order on that unit whose `fulfillment_status` is
    still `REQUESTED` has `requires_director_override` reset to false and
    `posture_hold_applied_at` cleared to null, with each such order versioned."
    PRD §3.6: "The case moves `RCA_IN_PROGRESS → RCA_COMPLETE` with both fields
    stored."

    Design: Corner/state_machines/close_case_during_rca_in_progress_rejected
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    omar = create_certified_nurse(unit, api=api, full_name="Omar Verify", ce_credits=30)
    patient = create_patient(unit, api=api, mrn="MRN-H3", admitted_at="2026-07-20T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_3",
        clinical_note="New sacral breakdown on day 12.",
    )
    triage_consult(consult, nina, api=api)
    assign_consult(consult, nina, api=api)
    assessment = file_assessment(
        consult,
        patient,
        nina,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_3",
        measured_area_cm2=12,
        observed_at="2026-08-01T00:00:00Z",
    )
    validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_3", "present_on_admission_confirmed": False},
            make_nurse_headers(omar["id"]),
        )
    )
    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["classification"] == "HAPI"
    assert as_instant(case["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    after_validation = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_validation["acuity_score"] == 65.0, (
        "(60 stage + 0 comorbidity + 0 device + min(15, floor(12 / 10) * 5)) * 1.00"
    )
    assert after_validation["priority_band"] == "P2"
    assert as_instant(after_validation["sla_due_at"]) == as_instant("2026-08-02T00:00:00Z")

    started = validate_success(
        api.rca_start(case["id"], {"rca_lead_nurse_id": omar["id"]}, DIRECTOR)
    )
    assert started["status"] == "RCA_IN_PROGRESS"

    validate_error(
        api.close_pressure_injury_case(
            case["id"],
            {"closure_note": "Closing without finishing the analysis."},
            DIRECTOR,
        ),
        "ERR_CASE_INVALID_STATE",
        expected_status=409,
    )
    mid_analysis = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert mid_analysis["status"] == "RCA_IN_PROGRESS"
    assert mid_analysis["closed_at"] is None
    assert (
        get_success_data(api.get_unit(unit["id"], DIRECTOR))["open_hapi_rca_count"] == 1
    ), "the counter stays elevated until a real close decrements it"

    completed = validate_success(
        api.rca_complete(
            case["id"],
            {
                "root_cause_category": "REPOSITIONING",
                "contributing_factors": [
                    "Turn schedule missed on nights",
                    "Support surface ordered late",
                ],
            },
            make_nurse_headers(omar["id"]),
        )
    )
    assert completed["status"] == "RCA_COMPLETE"
    assert completed["root_cause_category"] == "REPOSITIONING"
    assert len(completed["contributing_factors"]) == 2

    closed = validate_success(
        api.close_pressure_injury_case(
            case["id"],
            {"closure_note": "RCA complete; turn-schedule audit added."},
            DIRECTOR,
        )
    )
    assert closed["status"] == "CLOSED"
    assert as_instant(closed["closed_at"]) == as_instant("2026-08-01T00:00:00Z")
    reversed_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert reversed_unit["open_hapi_rca_count"] == 0
    assert reversed_unit["survey_posture"] == "OPEN"


def test_a_second_hospital_acquired_case_revokes_an_approval_already_earned(api):
    """The approval body never changes; the unit's posture does.

    PRD §2.10 rung 58: "The unit's `survey_posture` is not `FROZEN` when a rental
    order is created, and an order whose `requires_director_override` is true is
    only approved when `director_override` is supplied as true —
    `ERR_UNIT_POSTURE_RESTRICTED` (409), on `POST /support-surface-orders` and
    `POST /support-surface-orders/{order_id}/approve`."
    PRD §3.8: "The fee percentage is keyed on the **pre-fee**
    `projected_cost_cents`, never on the post-fee total: the percentage is 8
    percent when `projected_cost_cents` is below 50000 cents, 5 percent when it is
    at least 50000 and below 200000, and 3 percent when it is 200000 or more."
    PRD §3.8: "Approval moves `fulfillment_status` `REQUESTED → APPROVED` and, in
    the same breath, `billing_status` `UNBILLED → ENCUMBERED`."

    Design: Corner/validations/restricted_posture_flag_rejects_approval_without_director_override
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=200000,
    )
    nina = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    surface = create_surface(
        api,
        asset_tag="BED-201",
        surface_class="LOW_AIR_LOSS",
        daily_rate_cents=10000,
        vendor_name="AirBeds Inc",
    )
    first_patient = create_patient(
        unit, api=api, mrn="MRN-V1", admitted_at="2026-07-30T00:00:00Z"
    )
    second_patient = create_patient(
        unit, api=api, mrn="MRN-V2", admitted_at="2026-07-30T00:00:00Z"
    )
    assessments = []
    consults = []
    for patient in (first_patient, second_patient):
        consult = create_consult(
            unit,
            patient,
            api=api,
            consult_type="WOUND",
            reported_stage="STAGE_2",
            clinical_note="New sacral breakdown on day three.",
        )
        triage_consult(consult, nina, api=api)
        assign_consult(consult, nina, api=api)
        consults.append(consult)
    for consult, patient in zip(consults, (first_patient, second_patient)):
        assessments.append(
            file_assessment(
                consult,
                patient,
                nina,
                api=api,
                anatomic_location="SACRUM",
                observed_stage="STAGE_2",
                measured_area_cm2=6,
                observed_at="2026-08-01T00:00:00Z",
            )
        )

    validate_success(
        api.validate_skin_assessment(
            assessments[0]["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    after_first = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_first["open_hapi_rca_count"] == 1
    assert after_first["survey_posture"] == "OPEN"

    order = create_order(
        unit,
        first_patient,
        surface,
        api=api,
        rental_start="2026-08-01T00:00:00Z",
        rental_end="2026-08-04T00:00:00Z",
        authorized_days=3,
        consult_request_id=consults[0]["id"],
    )
    assert order["requires_director_override"] is False, "created while the posture was OPEN"
    assert order["billable_days"] == 3, "72 whole hours divided by 24"
    assert order["projected_cost_cents"] == 30000, "three days inside the full-price tier"
    assert order["vendor_service_fee_cents"] == 2400, "8 percent of a pre-fee 30000"
    assert order["authorized_cost_cents"] == 32400

    validate_success(
        api.validate_skin_assessment(
            assessments[1]["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    after_second = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_second["open_hapi_rca_count"] == 2
    assert after_second["survey_posture"] == "RESTRICTED"
    held = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert held["requires_director_override"] is True, "hop 5 back-stamped the pending order"
    assert as_instant(held["posture_hold_applied_at"]) == as_instant("2026-08-01T00:00:00Z")

    unit_version = read_unit_version(unit["id"], api=api)
    validate_error(
        api.approve_support_surface_order(
            order["id"], {"expected_unit_version": unit_version}, MATERIALS
        ),
        "ERR_UNIT_POSTURE_RESTRICTED",
        expected_status=409,
    )
    refused = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
    assert refused["fulfillment_status"] == "REQUESTED"
    assert refused["billing_status"] == "UNBILLED"
    unchanged_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert unchanged_unit["rental_encumbered_cents"] == 0
    assert unchanged_unit["version"] == unit_version, (
        "the refused approval did not move the unit, so the same version is still current"
    )

    approved = validate_success(
        api.approve_support_surface_order(
            order["id"],
            {"expected_unit_version": unit_version, "director_override": True},
            MATERIALS,
        )
    )
    assert approved["fulfillment_status"] == "APPROVED"
    assert approved["billing_status"] == "ENCUMBERED"
    assert approved["requires_director_override"] is True, (
        "the override does not clear the flag; it remains as an audit trail"
    )
    charged = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert charged["rental_encumbered_cents"] == 32400
    assert charged["rental_available_cents"] == 167600, "200000 cap less 32400 encumbered"
    assert (
        get_success_data(api.get_support_surface(surface["id"], MATERIALS))["status"]
        == "IN_USE"
    )


def test_starting_the_analysis_is_not_enough_to_release_the_consult(api):
    """The consult's own preconditions are met; a downstream case blocks it anyway.

    PRD §3.4: "Closure is gated on adjudication: every pressure injury case
    originating from any of this consult's skin assessments must have a `status` of
    `CLASSIFIED_POA`, `RCA_COMPLETE`, `CLOSED` or `RECLASSIFIED`, and any case
    still `OPEN`, `CLASSIFIED_HAPI`, `RCA_REQUIRED` or `RCA_IN_PROGRESS` blocks the
    close with `ERR_RCA_NOT_COMPLETE`."
    PRD §3.4: "Closing moves the consult `PLAN_ACTIVE → CLOSED` and reaches into
    the assigned nurse's record in three ways at once: `active_consult_load` falls
    by 1, `mentored_consult_count` rises by 1, and
    `certification_eligibility_score` is recomputed from the new mentored count,
    with the nurse row versioned for all three."
    PRD §3.6: "The nominated lead, and only the nominated lead, completes the
    analysis: the acting `X-User-ID` must equal the case's `rca_lead_nurse_id`."

    Design: Corner/validations/consult_close_rejected_until_hapi_rca_complete
    """
    unit = create_unit(
        api, unit_code="3E", name="Three East", bed_count=18, rental_budget_cap_cents=0
    )
    nina = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    omar = create_certified_nurse(unit, api=api, full_name="Omar Lead", ce_credits=30)
    product = create_product(
        api,
        sku="DRSG-20",
        name="Foam dressing 15x15",
        category="FOAM",
        unit_cost_cents=1000,
        formulary_tier="RESTRICTED",
    )
    patient = create_patient(unit, api=api, mrn="MRN-AA1", admitted_at="2026-07-30T00:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="New sacral breakdown on hospital day three.",
    )
    triage_consult(consult, nina, api=api)
    assign_consult(consult, nina, api=api)
    assessment = file_assessment(
        consult,
        patient,
        nina,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-08-01T00:00:00Z",
    )
    validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    protocol = validate_success(
        api.create_dressing_protocol(
            {
                "consult_request_id": consult["id"],
                "formulary_product_id": product["id"],
                "change_frequency_hours": 24,
                "units_per_change": 1,
            },
            make_nurse_headers(nina["id"]),
        ),
        expected_status=201,
    )
    assert protocol["changes_per_week"] == 7, "floor(168 / 24) = 7"
    assert protocol["weekly_cost_cents"] == 7000, (
        "7 changes * 1000 cents * 1 unit; a RESTRICTED tier carries no surcharge"
    )
    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["status"] == "RCA_REQUIRED"
    assert as_instant(case["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["status"]
        == "PLAN_ACTIVE"
    )

    nurse_headers = make_nurse_headers(nina["id"])
    validate_error(
        api.close_consult_request(
            consult["id"],
            {
                "closing_summary": (
                    "Attempting closure with the root cause analysis still outstanding."
                )
            },
            nurse_headers,
        ),
        "ERR_RCA_NOT_COMPLETE",
        expected_status=409,
    )
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["status"]
        == "PLAN_ACTIVE"
    )
    assert (
        get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))["active_consult_load"] == 1
    ), "no side effect leaked from the refused close"

    started = validate_success(
        api.rca_start(case["id"], {"rca_lead_nurse_id": omar["id"]}, DIRECTOR)
    )
    assert started["status"] == "RCA_IN_PROGRESS"
    assert started["rca_lead_nurse_id"] == omar["id"]

    validate_error(
        api.close_consult_request(
            consult["id"],
            {"closing_summary": "Attempting closure with the analysis merely started."},
            nurse_headers,
        ),
        "ERR_RCA_NOT_COMPLETE",
        expected_status=409,
    )

    completed = validate_success(
        api.rca_complete(
            case["id"],
            {
                "root_cause_category": "SUPPORT_SURFACE",
                "contributing_factors": [
                    "Specialty surface upgrade delayed by 36 hours",
                    "Turn schedule not documented on nights",
                ],
            },
            make_nurse_headers(omar["id"]),
        )
    )
    assert completed["status"] == "RCA_COMPLETE"
    assert completed["root_cause_category"] == "SUPPORT_SURFACE"
    assert len(completed["contributing_factors"]) == 2

    closed = validate_success(
        api.close_consult_request(
            consult["id"],
            {
                "closing_summary": (
                    "Sacral HAPI adjudicated; barrier protocol handed off to the unit."
                )
            },
            nurse_headers,
        )
    )
    assert closed["status"] == "CLOSED"
    assert closed["closing_summary"] == (
        "Sacral HAPI adjudicated; barrier protocol handed off to the unit."
    )
    after_nurse = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert after_nurse["active_consult_load"] == 0
    assert after_nurse["mentored_consult_count"] == 1
    assert after_nurse["certification_eligibility_score"] == 66.0, (
        "0.4 * 100 + 0.4 * min(60, 2 * 30) + 0.2 * (10 * min(4, 1)) = 40 + 24 + 2"
    )


def test_the_posture_ladder_flips_only_at_the_second_and_fourth_open_analysis(api):
    """Both floors of the three-rung ladder, and the no-change step between them.

    PRD §2.4: "A unit's `survey_posture` is always re-derived from its
    `open_hapi_rca_count` on every change to that count, using a three-rung ladder:
    `FROZEN` when the open-RCA count is at least 4, otherwise `RESTRICTED` when it
    is at least 2, otherwise `OPEN`."
    PRD §3.5: "The fifth hop follows from the fourth, but only when that
    re-derivation actually changed `survey_posture` to `RESTRICTED` or `FROZEN`:
    every rental order on that unit whose `fulfillment_status` is still `REQUESTED`
    has `requires_director_override` set to true and `posture_hold_applied_at`
    stamped with the logical clock, and each such order is versioned."
    PRD §3.8: "Creation is nevertheless refused outright with
    `ERR_UNIT_POSTURE_RESTRICTED` when the unit's `survey_posture` is `FROZEN`, and
    when the posture is `RESTRICTED` at creation time the order is created with
    `requires_director_override` already true."

    Design: Corner/cross_cutting_complexity_layers/posture_ladder_flips_at_the_second_and_fourth_cumulative_open_rca
    """
    unit = create_unit(
        api,
        unit_code="THR-U1",
        name="Threshold Probe Med-Surg",
        bed_count=30,
        rental_budget_cap_cents=500000,
    )
    nurse = create_certified_nurse(
        unit,
        api=api,
        full_name="Tess Threshold",
        ce_credits=30,
        cert_expires_at="2027-08-01T00:00:00Z",
    )
    assert nurse["max_consult_load"] == 8

    patients = [
        create_patient(
            unit,
            api=api,
            mrn=f"THRMRN000{index}",
            admitted_at="2026-07-30T00:00:00Z",
            comorbidity_count=0,
            device_related_risk=False,
            ostomy_present=False,
        )
        for index in (1, 2, 3, 4)
    ]
    assessments = []
    cases = []
    for index, patient in enumerate(patients, start=1):
        consult = create_consult(
            unit,
            patient,
            api=api,
            consult_type="WOUND",
            reported_stage="STAGE_2",
            clinical_note=f"Sacral partial-thickness loss, patient {index}.",
        )
        triage_consult(consult, nurse, api=api)
        assign_consult(consult, nurse, api=api)
        assessment = file_assessment(
            consult,
            patient,
            nurse,
            api=api,
            anatomic_location="SACRUM",
            observed_stage="STAGE_2",
            measured_area_cm2=6.0,
            observed_at="2026-08-01T00:00:00Z",
            present_on_admission_claimed=False,
        )
        assessments.append(assessment)
        cases.append(find_case_for_assessment(assessment["id"], api=api))

    surfaces = [
        create_surface(
            api,
            asset_tag=f"THR-S{index}",
            surface_class="LOW_AIR_LOSS",
            daily_rate_cents=10000,
            vendor_name="Probe Rentals",
        )
        for index in (1, 2, 3)
    ]
    first_order = create_order(
        unit,
        patients[0],
        surfaces[0],
        api=api,
        rental_start="2026-08-02T00:00:00Z",
        rental_end="2026-08-05T00:00:00Z",
        authorized_days=3,
    )
    assert first_order["requires_director_override"] is False
    assert first_order["posture_hold_applied_at"] is None
    assert first_order["version"] == 1

    def declare_hospital_acquired(assessment):
        return validate_success(
            api.validate_skin_assessment(
                assessment["id"],
                {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
                DIRECTOR,
            )
        )

    declare_hospital_acquired(assessments[0])
    first_case = get_success_data(api.get_pressure_injury_case(cases[0]["id"], DIRECTOR))
    assert first_case["classification"] == "HAPI"
    assert first_case["status"] == "RCA_REQUIRED"
    assert as_instant(first_case["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    ladder = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ladder["open_hapi_rca_count"] == 1
    assert ladder["survey_posture"] == "OPEN"
    untouched_order = get_success_data(
        api.get_support_surface_order(first_order["id"], MATERIALS)
    )
    assert untouched_order["requires_director_override"] is False
    assert untouched_order["posture_hold_applied_at"] is None
    assert untouched_order["version"] == 1, "the posture did not change, so hop 5 was silent"

    declare_hospital_acquired(assessments[1])
    ladder = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ladder["open_hapi_rca_count"] == 2
    assert ladder["survey_posture"] == "RESTRICTED", "the RESTRICTED floor is 2"
    stamped_order = get_success_data(
        api.get_support_surface_order(first_order["id"], MATERIALS)
    )
    assert stamped_order["requires_director_override"] is True
    assert as_instant(stamped_order["posture_hold_applied_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert stamped_order["version"] == 2

    second_order = validate_success(
        api.create_support_surface_order(
            {
                "patient_id": patients[1]["id"],
                "unit_id": unit["id"],
                "support_surface_id": surfaces[1]["id"],
                "rental_start": "2026-08-02T00:00:00Z",
                "rental_end": "2026-08-05T00:00:00Z",
                "authorized_days": 3,
            },
            MATERIALS,
        ),
        expected_status=201,
    )
    assert second_order["requires_director_override"] is True, (
        "at RESTRICTED creation is permitted but is born already held"
    )
    assert second_order["authorized_cost_cents"] == 32400
    assert second_order["version"] == 1

    declare_hospital_acquired(assessments[2])
    ladder = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ladder["open_hapi_rca_count"] == 3
    assert ladder["survey_posture"] == "RESTRICTED", "3 is still short of the FROZEN floor"
    assert (
        get_success_data(api.get_support_surface_order(second_order["id"], MATERIALS))[
            "version"
        ]
        == 1
    ), "the posture did not change, so hop 5 did not re-fire"
    assert (
        get_success_data(api.get_support_surface_order(first_order["id"], MATERIALS))[
            "version"
        ]
        == 2
    )

    declare_hospital_acquired(assessments[3])
    ladder = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert ladder["open_hapi_rca_count"] == 4
    assert ladder["survey_posture"] == "FROZEN"
    for order, expected_version in ((first_order, 3), (second_order, 2)):
        refired = get_success_data(api.get_support_surface_order(order["id"], MATERIALS))
        assert refired["version"] == expected_version, "hop 5 re-fired on the posture change"
        assert refired["requires_director_override"] is True
        assert as_instant(refired["posture_hold_applied_at"]) == as_instant("2026-08-01T00:00:00Z")

    validate_error(
        api.create_support_surface_order(
            {
                "patient_id": patients[2]["id"],
                "unit_id": unit["id"],
                "support_surface_id": surfaces[2]["id"],
                "rental_start": "2026-08-02T00:00:00Z",
                "rental_end": "2026-08-05T00:00:00Z",
                "authorized_days": 3,
            },
            MATERIALS,
        ),
        "ERR_UNIT_POSTURE_RESTRICTED",
        expected_status=409,
    )
    _orders, meta = validate_paginated(
        api.list_support_surface_orders(MATERIALS, {"unit_id": unit["id"]})
    )
    assert meta["total_count"] == 2, "at FROZEN the third order was never created"

    final_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert final_unit["version"] == 5, (
        "1 at creation plus one hop-4 versioning per hospital-acquired verdict; "
        "the three order operations never touched the unit"
    )
    assert final_unit["rental_encumbered_cents"] == 0, "nothing was approved"
    assert final_unit["rental_available_cents"] == 500000
    for case in cases[1:]:
        assert (
            get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))["status"]
            == "RCA_REQUIRED"
        )


def test_every_hop_of_the_cascade_is_readable_the_moment_the_call_returns(api):
    """Four entities move in one request and all four are immediately consistent.

    PRD §2.4: "Those secondary mutations are not optional, are applied inside the
    same request, and each of them bumps the `version` and refreshes the
    `updated_at` of every row it touches — not merely of the row the caller
    addressed."
    PRD §2.4: "A caller who reads a unit immediately after validating a skin
    assessment on one of its patients must see the unit's counters and `version`
    already moved."
    PRD §3.5: "Alongside it, the consult's `acuity_score` is recomputed under the
    assessed-final variant using the newly pinned `confirmed_stage` — not
    `observed_stage` — together with `measured_area_cm2`, and `priority_band` and
    `sla_due_at` are re-derived and the consult versioned."
    PRD §3.4: "Whenever `priority_band` later changes, `sla_due_at` is re-derived
    from the same `triaged_at` with the new band's allowance; `triaged_at` itself is
    not moved by a recompute."

    Design: Corner/consistency_model/every_cascade_hop_is_visible_in_the_same_response_and_the_next_read
    """
    unit = create_unit(
        api,
        unit_code="IMM-U1",
        name="Immediate Probe Med-Surg",
        bed_count=18,
        rental_budget_cap_cents=100000,
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="IMMMRN0001",
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=2,
        device_related_risk=True,
        ostomy_present=False,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Ida Immediate", ce_credits=30)
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Device-related sacral breakdown under the immobiliser.",
    )
    triaged = triage_consult(consult, nurse, api=api)
    assert triaged["acuity_score"] == 55.0, "(35 stage + 10 comorbidity + 10 device) * 1.00"
    assert triaged["acuity_variant"] == "INTAKE_PROVISIONAL"
    assert triaged["priority_band"] == "P2"
    assert as_instant(triaged["triaged_at"]) == as_instant("2026-08-01T00:00:00Z")
    assert as_instant(triaged["sla_due_at"]) == as_instant("2026-08-02T00:00:00Z")
    assign_consult(consult, nurse, api=api)
    assessment = file_assessment(
        consult,
        patient,
        nurse,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=12.0,
        observed_at="2026-08-01T00:00:00Z",
        present_on_admission_claimed=False,
    )
    after_filing = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_filing["acuity_score"] == 60.0, "the assessed-final variant adds the 5 area points"
    assert after_filing["priority_band"] == "P2"
    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["classification"] == "UNDETERMINED"
    assert case["status"] == "OPEN"

    nurse_headers = make_nurse_headers(nurse["id"])
    body = validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_3", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    assert body["validation_status"] == "VALIDATED", "hop 1 is in the trigger's own body"
    assert body["confirmed_stage"] == "STAGE_3"
    assert body["poa_determination"] == "HAPI"
    assert body["validated_by_user_id"] == "op-director-1"
    assert body["version"] == 2

    consult_read = get_success_data(api.get_consult_request(consult["id"], nurse_headers))
    assert consult_read["acuity_score"] == 85.0, (
        "the pinned STAGE_3 weight 60 + 10 comorbidity + 10 device + 5 area, times 1.00"
    )
    assert consult_read["acuity_variant"] == "ASSESSED_FINAL"
    assert consult_read["priority_band"] == "P1", "the band moved up from P2"
    assert as_instant(consult_read["triaged_at"]) == as_instant("2026-08-01T00:00:00Z"), "a recompute does not move it"
    assert as_instant(consult_read["sla_due_at"]) == as_instant("2026-08-01T04:00:00Z"), (
        "re-anchored on the unchanged triaged_at with the P1 allowance of 4 hours"
    )
    assert consult_read["status"] == "ASSESSED"
    assert consult_read["version"] == 5, (
        "1 at creation, +1 triage, +1 assign, +1 assessment filing, +1 validation hop 1"
    )

    case_read = get_success_data(api.get_pressure_injury_case(case["id"], nurse_headers))
    assert case_read["classification"] == "HAPI", "hop 2, with no lag"
    assert case_read["status"] == "RCA_REQUIRED", "hop 3, with no lag"
    assert as_instant(case_read["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z")

    unit_read = get_success_data(api.get_unit(unit["id"], nurse_headers))
    assert unit_read["open_hapi_rca_count"] == 1, "hop 4, with no lag"
    assert unit_read["survey_posture"] == "OPEN", "one open analysis is below the floor of 2"
    assert unit_read["version"] == 2

    patient_read = get_success_data(api.get_patient(patient["id"], nurse_headers))
    assert patient_read["poa_skin_assessment_documented"] is False, (
        "the present-on-admission half of hop 1 did not fire on a HAPI verdict"
    )
    assert patient_read["version"] == 2, "the only bump came from filing the assessment"

    rows, meta = validate_paginated(
        api.list_skin_assessments(
            nurse_headers,
            {"patient_id": patient["id"], "validation_status": "VALIDATED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == assessment["id"]
    assert rows[0]["validation_status"] == "VALIDATED"
    assert rows[0]["confirmed_stage"] == "STAGE_3"
    assert rows[0]["poa_determination"] == "HAPI", (
        "the list projection agrees field-for-field with the trigger's own body"
    )
