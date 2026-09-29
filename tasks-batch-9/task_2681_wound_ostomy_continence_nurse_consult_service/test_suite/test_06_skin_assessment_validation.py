"""Bedside staging: the two-person controls on validation, the present-on-admission
verdict, the dispute-and-restage loop and the protocol gate that hangs off them."""
from test_helpers import (
    as_instant,
    assign_consult,
    create_candidate_nurse,
    create_certified_nurse,
    create_consult,
    create_patient,
    create_product,
    create_unit,
    file_assessment,
    find_case_for_assessment,
    get_success_data,
    read_patient_version,
    set_clock,
    triage_consult,
    validate_assessment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_nurse_headers


DIRECTOR = make_director_headers()


def _self_staged_pending_assessment(api):
    """A pending SACRUM staging filed by the nurse it will be offered to, on a
    patient whose present-on-admission window shut eleven days earlier."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-P1",
        admitted_at="2026-07-20T00:00:00Z",
        comorbidity_count=0,
        device_related_risk=False,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound noted on rounds.",
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
        present_on_admission_claimed=True,
    )
    assert assessment["staged_by_nurse_id"] == nina["id"]
    return unit, nina, patient, consult, assessment


def test_a_nurse_confirming_her_own_staging_loses_to_no_other_rule(api):
    """Two 422s are in play at once; only the earlier rung's code may surface.

    PRD §2.7: "First, when a skin assessment is validated by a caller acting as
    `WocNurse`, `X-User-ID` must not equal that assessment's
    `staged_by_nurse_id` — a nurse may not confirm their own staging."
    PRD §2.10 rung 30: "Segregation of duties as described in §2.7 —
    `ERR_SEGREGATION_OF_DUTIES` (422), on
    `POST /skin-assessments/{assessment_id}/validate`,
    `POST /skin-assessments/{assessment_id}/restage` and
    `POST /pressure-injury-cases/{case_id}/rca-start`."
    PRD §2.10 rung 40: "`present_on_admission_confirmed` may only be accepted as
    true when the assessment's `observed_at` is at or before the patient's
    `admitted_at` plus 24 hours — `ERR_POA_WINDOW_CLOSED` (422), on
    `POST /skin-assessments/{assessment_id}/validate`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_poa_window_on_validate
    """
    _unit, nina, _patient, _consult, assessment = _self_staged_pending_assessment(api)

    response = api.validate_skin_assessment(
        assessment["id"],
        {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": True},
        make_nurse_headers(nina["id"]),
    )
    validate_error(response, "ERR_SEGREGATION_OF_DUTIES", expected_status=422)
    assert response.json()["data"]["error_id"] != "ERR_POA_WINDOW_CLOSED", (
        "observed_at 2026-08-01T00:00:00Z is eleven days past the window end of "
        "2026-07-21T00:00:00Z, yet rung 30 answers before rung 40"
    )


def test_the_refused_self_validation_fires_no_hop_of_the_cascade(api):
    """A rejection at rung 30 leaves assessment, patient, case and unit alone.

    PRD §3.5: "Validation moves the assessment `PENDING_VALIDATION →
    VALIDATED`, writes `confirmed_stage`, records `validated_by_user_id` as the
    acting `X-User-ID`, and computes `poa_determination`."
    PRD §3.5: "The first hop is the assessment's own mutation just described,
    plus, when `poa_determination` came out `POA`, setting the patient's
    `poa_skin_assessment_documented` to true and versioning the patient."
    PRD §3.5: "The fourth hop follows from the third: the case's unit has
    `open_hapi_rca_count` raised by 1 and `survey_posture` re-derived on the
    four-or-more-`FROZEN`, two-or-more-`RESTRICTED`, otherwise-`OPEN` ladder,
    and the unit is versioned."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_poa_window_on_validate
    """
    unit, nina, patient, _consult, assessment = _self_staged_pending_assessment(api)

    validate_error(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": True},
            make_nurse_headers(nina["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=422,
    )

    after = get_success_data(api.get_skin_assessment(assessment["id"], DIRECTOR))
    assert after["validation_status"] == "PENDING_VALIDATION"
    assert after["poa_determination"] is None
    assert after["confirmed_stage"] is None
    assert after["validated_by_user_id"] is None

    assert (
        get_success_data(api.get_patient(patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is False
    )
    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 0
    assert after_unit["survey_posture"] == "OPEN"
    assert after_unit["disputed_staging_count"] == 0

    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["classification"] == "UNDETERMINED"
    assert case["status"] == "OPEN"


def _pending_staging_and_a_product(api):
    """A consult sitting at `ASSESSED` over a still-pending staging, plus the
    preferred-tier product a protocol would name."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    omar = create_certified_nurse(unit, api=api, full_name="Omar Verify", ce_credits=30)
    product = create_product(
        api,
        sku="FOAM-01",
        name="Silicone foam dressing 10x10",
        category="FOAM",
        unit_cost_cents=1250,
        formulary_tier="PREFERRED",
    )
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-V1",
        admitted_at="2026-07-31T12:00:00Z",
        comorbidity_count=0,
        device_related_risk=False,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound present on arrival.",
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
        present_on_admission_claimed=True,
    )
    assert assessment["validation_status"] == "PENDING_VALIDATION"
    protocol_payload = {
        "consult_request_id": consult["id"],
        "formulary_product_id": product["id"],
        "change_frequency_hours": 48,
        "units_per_change": 2,
    }
    return {
        "unit": unit,
        "nina": nina,
        "omar": omar,
        "patient": patient,
        "consult": consult,
        "assessment": assessment,
        "protocol_payload": protocol_payload,
    }


def test_a_dressing_protocol_is_refused_while_the_staging_is_only_pending(api):
    """The protocol gate reads a different entity's `validation_status`.

    PRD §2.10 rung 34: "A dressing protocol may only be filed when its consult's
    `protocol_hold` is false and the consult's most recently created skin
    assessment has `validation_status` equal to `VALIDATED` —
    `ERR_STAGE_NOT_VALIDATED` (422), on `POST /dressing-protocols`."
    PRD §3.9: "A consult whose staging is still `PENDING_VALIDATION`, or is
    under dispute, cannot carry a protocol."

    Design: Difficulty/cross_entity_state_dependency/dressing_protocol_blocked_until_assessment_validated
    """
    scenario = _pending_staging_and_a_product(api)
    consult, nina = scenario["consult"], scenario["nina"]

    validate_error(
        api.create_dressing_protocol(
            scenario["protocol_payload"], make_nurse_headers(nina["id"])
        ),
        "ERR_STAGE_NOT_VALIDATED",
        expected_status=422,
    )

    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["status"] == "ASSESSED", "the consult did not advance"
    assert after_consult["protocol_hold"] is False, (
        "the hold was never set; it was the staging state that blocked the write"
    )
    _rows, meta = validate_paginated(
        api.list_dressing_protocols(DIRECTOR, {"consult_request_id": consult["id"]})
    )
    assert meta["total_count"] == 0, "the refused authorship inserted no protocol"


def test_the_identical_protocol_payload_lands_once_the_staging_is_validated(api):
    """Only the other entity's state moves between the two attempts.

    PRD §3.9: "Two clinical gates guard authorship, and both surface through
    `ERR_STAGE_NOT_VALIDATED`: the consult's `protocol_hold` must be false, and
    the consult's most recently created skin assessment — the one with the latest
    `created_at` — must have `validation_status` equal to `VALIDATED`."
    PRD §3.9: "`changes_per_week` is 168 hours — one week — divided by
    `change_frequency_hours`, discarding any remainder, so a 12-hour interval
    yields 14 changes and a 5-day interval yields 1."
    PRD §3.9: "On a `PREFERRED` or `RESTRICTED` product that product is the
    answer exactly, with no rounding needed."
    PRD §3.9: "And the consult advances, `ASSESSED → PLAN_ACTIVE` on a first
    protocol or holding at `PLAN_ACTIVE` on a revision, and is versioned."

    Design: Difficulty/cross_entity_state_dependency/dressing_protocol_blocked_until_assessment_validated
    """
    scenario = _pending_staging_and_a_product(api)
    consult, nina, omar = scenario["consult"], scenario["nina"], scenario["omar"]
    patient, assessment = scenario["patient"], scenario["assessment"]
    payload = scenario["protocol_payload"]

    validate_error(
        api.create_dressing_protocol(payload, make_nurse_headers(nina["id"])),
        "ERR_STAGE_NOT_VALIDATED",
        expected_status=422,
    )

    validated = validate_assessment(
        assessment,
        api=api,
        headers=make_nurse_headers(omar["id"]),
        confirmed_stage="STAGE_2",
        present_on_admission_confirmed=True,
    )
    assert validated["validation_status"] == "VALIDATED"
    assert validated["poa_determination"] == "POA"
    assert (
        get_success_data(api.get_patient(patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is True
    )

    protocol = validate_success(
        api.create_dressing_protocol(payload, make_nurse_headers(nina["id"])),
        expected_status=201,
    )
    assert protocol["changes_per_week"] == 3, "floor(168 / 48) = 3"
    assert protocol["weekly_cost_cents"] == 7500, (
        "3 changes * 1250 cents * 2 units, with no surcharge at the PREFERRED tier"
    )
    assert protocol["status"] == "ACTIVE"
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["status"]
        == "PLAN_ACTIVE"
    )


def test_a_second_validation_of_a_validated_row_is_refused_and_changes_nothing(api):
    """`VALIDATED` accepts only supersession, never a second confirmation.

    PRD §2.10 rung 11: "The skin assessment's `validation_status` is a legal
    starting state for the requested transition —
    `ERR_ASSESSMENT_INVALID_STATE` (409), on
    `POST /skin-assessments/{assessment_id}/validate`, `/dispute` and
    `/restage`."
    PRD §3.5: "The second hop reaches the case file: the pressure injury case
    whose `skin_assessment_id` is this assessment takes `classification` from the
    verdict and moves `OPEN → CLASSIFIED_POA` when the verdict was `POA`,
    `OPEN → CLASSIFIED_HAPI` when it was `HAPI`, and stays at `OPEN` with
    `classification` left `UNDETERMINED` when it was `INDETERMINATE`."

    Design: Corner/state_machines/validate_on_already_validated_assessment_rejected
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
    patient = create_patient(unit, api=api, mrn="MRN-G7", admitted_at="2026-07-31T12:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound present on arrival.",
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
        present_on_admission_claimed=True,
    )
    validate_assessment(
        assessment,
        api=api,
        headers=make_nurse_headers(omar["id"]),
        confirmed_stage="STAGE_2",
        present_on_admission_confirmed=True,
    )

    validate_error(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_4", "present_on_admission_confirmed": False},
            make_nurse_headers(omar["id"]),
        ),
        "ERR_ASSESSMENT_INVALID_STATE",
        expected_status=409,
    )

    after = get_success_data(api.get_skin_assessment(assessment["id"], DIRECTOR))
    assert after["validation_status"] == "VALIDATED"
    assert after["confirmed_stage"] == "STAGE_2", (
        "the refused call's STAGE_4 was not written over the pinned stage"
    )
    assert after["poa_determination"] == "POA", "the verdict was not recomputed"
    assert (
        get_success_data(api.get_patient(patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is True
    )

    cases, meta = validate_paginated(
        api.list_pressure_injury_cases(DIRECTOR, {"skin_assessment_id": assessment["id"]})
    )
    assert meta["total_count"] == 1
    assert cases[0]["classification"] == "POA"
    assert cases[0]["status"] == "CLASSIFIED_POA"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 0, (
        "the HAPI branch never ran despite the refused call claiming a false POA"
    )
    assert after_unit["survey_posture"] == "OPEN"

    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["status"] == "ASSESSED"
    assert after_consult["acuity_score"] == 35.0, (
        "(35 stage + 0 comorbidity + 0 device + min(15, floor(6 / 10) * 5)) * 1.00"
    )


def test_the_dispute_loop_clears_the_latch_but_never_the_lifetime_counter(api):
    """One turn of the staging dispute cycle, counter by counter.

    PRD §3.5: "What *does* happen is a hold and a counter that validation never
    touches: the consult's `protocol_hold` is set to true and the consult
    versioned, and the unit of the assessment's patient has
    `disputed_staging_count` raised by 1 and is versioned."
    PRD §3.5: "The re-staging supplies a fresh `observed_stage` and a fresh
    `measured_area_cm2`, which overwrite the originals; `restage_count` rises by
    1, `dispute_reason` is cleared to null, the assessment returns
    `DISPUTED → PENDING_VALIDATION`, and the consult's `protocol_hold` is
    released back to false with the consult versioned."
    PRD §3.5: "No pressure injury case field is touched at all: the case remains
    `classification` `UNDETERMINED` and `status` `OPEN`, no root cause analysis
    is opened, and no unit posture moves."

    Design: Corner/state_machines/dispute_then_restage_returns_assessment_to_pending_validation
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nina = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    patient = create_patient(unit, api=api, mrn="MRN-G8", admitted_at="2026-07-31T12:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound, staging uncertain.",
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

    disputed = validate_success(
        api.dispute_skin_assessment(
            assessment["id"],
            {"dispute_reason": "Photo suggests a deep tissue injury, not stage 2."},
            DIRECTOR,
        )
    )
    assert disputed["validation_status"] == "DISPUTED"
    assert disputed["dispute_reason"] == "Photo suggests a deep tissue injury, not stage 2."
    assert disputed["poa_determination"] is None
    assert disputed["confirmed_stage"] is None
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["protocol_hold"]
        is True
    )
    unit_after_dispute = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert unit_after_dispute["disputed_staging_count"] == 1
    assert unit_after_dispute["survey_posture"] == "OPEN"
    case = find_case_for_assessment(assessment["id"], api=api)
    assert case["classification"] == "UNDETERMINED", "a dispute touches no case field"
    assert case["status"] == "OPEN"

    restaged = validate_success(
        api.restage_skin_assessment(
            assessment["id"],
            {"observed_stage": "DTI", "measured_area_cm2": 22},
            make_nurse_headers(nina["id"]),
        )
    )
    assert restaged["validation_status"] == "PENDING_VALIDATION"
    assert restaged["observed_stage"] == "DTI"
    assert restaged["measured_area_cm2"] == 22
    assert restaged["restage_count"] == 1
    assert restaged["dispute_reason"] is None

    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["protocol_hold"] is False, "the latch is released"
    assert after_consult["acuity_score"] == 35.0, (
        "neither the dispute nor the restage recomputes acuity"
    )
    assert (
        get_success_data(api.get_unit(unit["id"], DIRECTOR))["disputed_staging_count"] == 1
    ), "a lifetime counter is never decremented"


def test_a_re_assessment_retires_the_prior_row_and_opens_one_successor_case(api):
    """Supersession of a validated row produces exactly one successor case.

    PRD §3.5: "The earlier row moves `VALIDATED → SUPERSEDED`; its pressure
    injury case, if that case's `status` is `OPEN`, `CLASSIFIED_POA`,
    `CLASSIFIED_HAPI` or `RCA_REQUIRED`, moves to `RECLASSIFIED`; and a
    successor case is created carrying `predecessor_case_id` pointing at the
    reclassified case, `skin_assessment_id` pointing at the *new* assessment,
    `classification` `UNDETERMINED` and `status` `OPEN`."
    PRD §3.5: "Only the single assessment row that drove the recompute
    participates: no other assessment for that patient enters the formula, so a
    row that has become `SUPERSEDED` never influences `acuity_score` again."

    Design: Corner/state_machines/superseding_assessment_marks_prior_row_superseded_and_reclassifies_case
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
    patient = create_patient(unit, api=api, mrn="MRN-H4", admitted_at="2026-07-31T12:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound noted on arrival.",
    )
    triage_consult(consult, nina, api=api)
    assign_consult(consult, nina, api=api)
    first = file_assessment(
        consult,
        patient,
        nina,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-07-31T18:00:00Z",
        present_on_admission_claimed=True,
    )
    validate_assessment(
        first,
        api=api,
        headers=make_nurse_headers(omar["id"]),
        confirmed_stage="STAGE_2",
        present_on_admission_confirmed=True,
    )
    original_case = find_case_for_assessment(first["id"], api=api)
    assert original_case["status"] == "CLASSIFIED_POA"

    second = file_assessment(
        consult,
        patient,
        nina,
        api=api,
        expected_patient_version=read_patient_version(patient["id"], api=api),
        anatomic_location="SACRUM",
        observed_stage="STAGE_3",
        measured_area_cm2=12,
        observed_at="2026-08-01T00:00:00Z",
    )
    assert second["validation_status"] == "PENDING_VALIDATION"

    retired = get_success_data(api.get_skin_assessment(first["id"], DIRECTOR))
    assert retired["validation_status"] == "SUPERSEDED", (
        "the prior VALIDATED row for the same patient and body site is retired"
    )
    reclassified = get_success_data(
        api.get_pressure_injury_case(original_case["id"], DIRECTOR)
    )
    assert reclassified["status"] == "RECLASSIFIED"
    assert reclassified["classification"] == "POA", "the historical verdict stands"

    cases, meta = validate_paginated(
        api.list_pressure_injury_cases(DIRECTOR, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2, "exactly one successor case was created, not two"
    successors = [row for row in cases if row["id"] != original_case["id"]]
    assert len(successors) == 1
    successor = successors[0]
    assert successor["predecessor_case_id"] == original_case["id"]
    assert successor["skin_assessment_id"] == second["id"]
    assert successor["classification"] == "UNDETERMINED"
    assert successor["status"] == "OPEN"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 0, (
        "a present-on-admission case never incremented the counter, so nothing is reversed"
    )
    assert after_unit["survey_posture"] == "OPEN"

    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["status"] == "ASSESSED", "a later assessment holds at ASSESSED"
    assert after_consult["acuity_score"] == 65.0, (
        "(60 stage + min(15, floor(12 / 10) * 5)) * 1.00, from the new row alone"
    )
    assert (
        get_success_data(api.get_patient(patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is True
    ), "the historical POA fact is not retracted by the re-assessment"


def test_the_poa_window_edge_is_inclusive_and_the_gate_reads_the_payload(api):
    """One observation past the window, one exactly on it, one non-POA retry.

    PRD §3.5: "When `present_on_admission_confirmed` is supplied as true, the
    assessment's `observed_at` must be at or before the patient's `admitted_at`
    plus 24 hours; a later observation cannot be confirmed as present on
    admission and the attempt is refused with `ERR_POA_WINDOW_CLOSED`."
    PRD §3.5: "The 24-hour bound is inclusive: an observation landing exactly on
    `admitted_at` plus 24 hours is inside the window."
    PRD §3.5: "The verdict is then `POA` whenever `present_on_admission_confirmed`
    was supplied as true; otherwise it is `HAPI` when
    `present_on_admission_confirmed` was false *and* that earliest documentation
    instant falls strictly later than the patient's `admitted_at` plus 24 hours;
    otherwise it is `INDETERMINATE`."
    PRD §3.6: "A case classified hospital-acquired takes `classification`
    `HAPI`, lands in `CLASSIFIED_HAPI`, and immediately advances again to
    `RCA_REQUIRED` with `rca_due_at` set to the logical clock plus 72 hours, at
    which point the unit's `open_hapi_rca_count` rises and its `survey_posture`
    is re-derived."

    Design: Corner/validations/poa_window_closed_rejects_present_on_admission_confirmation
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    # PRD §3.2: `admitted_at` "must not be later than the logical clock at the
    # moment of admission", so the clock is positioned before either admission.
    set_clock("2026-08-03T00:00:00Z", api=api)
    late_patient = create_patient(
        unit, api=api, mrn="MRN-P1", admitted_at="2026-07-31T00:00:00Z"
    )
    edge_patient = create_patient(
        unit, api=api, mrn="MRN-P2", admitted_at="2026-08-02T00:00:00Z"
    )

    late_consult = create_consult(
        unit,
        late_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound noticed on day two.",
    )
    triage_consult(late_consult, nurse, api=api)
    assign_consult(late_consult, nurse, api=api)
    late_assessment = file_assessment(
        late_consult,
        late_patient,
        nurse,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-08-02T00:00:00Z",
        present_on_admission_claimed=True,
    )
    edge_consult = create_consult(
        unit,
        edge_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound documented at the bedside on arrival.",
    )
    triage_consult(edge_consult, nurse, api=api)
    assign_consult(edge_consult, nurse, api=api)
    edge_assessment = file_assessment(
        edge_consult,
        edge_patient,
        nurse,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-08-03T00:00:00Z",
        present_on_admission_claimed=True,
    )

    validate_error(
        api.validate_skin_assessment(
            late_assessment["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": True},
            DIRECTOR,
        ),
        "ERR_POA_WINDOW_CLOSED",
        expected_status=422,
    )
    refused = get_success_data(api.get_skin_assessment(late_assessment["id"], DIRECTOR))
    assert refused["validation_status"] == "PENDING_VALIDATION"
    assert refused["poa_determination"] is None
    assert refused["confirmed_stage"] is None

    on_the_edge = validate_success(
        api.validate_skin_assessment(
            edge_assessment["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": True},
            DIRECTOR,
        )
    )
    assert on_the_edge["poa_determination"] == "POA", (
        "2026-08-03T00:00:00Z equals admitted_at plus 24 hours exactly, so it is inside"
    )
    assert (
        get_success_data(api.get_patient(edge_patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is True
    )

    as_hapi = validate_success(
        api.validate_skin_assessment(
            late_assessment["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    assert as_hapi["validation_status"] == "VALIDATED", (
        "with a false claim the window gate does not apply at all"
    )
    assert as_hapi["poa_determination"] == "HAPI"
    hapi_case = find_case_for_assessment(late_assessment["id"], api=api)
    assert hapi_case["status"] == "RCA_REQUIRED"
    assert as_instant(hapi_case["rca_due_at"]) == as_instant("2026-08-06T00:00:00Z"), "the clock plus 72 hours"
    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 1
    assert after_unit["survey_posture"] == "OPEN", "one open analysis is below the floor of two"


def test_the_poa_verdict_orders_site_history_by_observation_not_by_filing(api):
    """The candidate set is sorted chronologically, superseded rows included.

    PRD §3.5: "Its candidate set is every skin assessment for the same patient
    and the same `anatomic_location` whose `validation_status` is
    `PENDING_VALIDATION`, `VALIDATED`, `DISPUTED` or `SUPERSEDED` — that is,
    every row that has ever documented that site."
    PRD §3.5: "Those rows are ordered by `observed_at` ascending with
    `created_at` ascending as the sole tie-break; the row `id` is never
    consulted."
    PRD §3.5: "Including superseded rows in the candidate set is deliberate — a
    later re-documentation of the same site cannot retroactively convert an
    injury first seen on admission into a hospital-acquired one."

    Design: Corner/calculations/poa_determination_orders_by_observed_at_not_creation_order
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_candidate_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    patient = create_patient(unit, api=api, mrn="MRN-M1", admitted_at="2026-07-31T12:00:00Z")
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound, conflicting documentation on arrival.",
    )
    set_clock("2026-08-04T00:00:00Z", api=api)
    triage_consult(consult, nurse, api=api)
    assign_consult(consult, nurse, api=api)

    filed_first_observed_last = file_assessment(
        consult,
        patient,
        nurse,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-08-03T00:00:00Z",
    )
    filed_second_observed_first = file_assessment(
        consult,
        patient,
        nurse,
        api=api,
        expected_patient_version=read_patient_version(patient["id"], api=api),
        anatomic_location="SACRUM",
        observed_stage="STAGE_2",
        measured_area_cm2=6,
        observed_at="2026-08-01T00:00:00Z",
    )
    assert (
        get_success_data(api.get_skin_assessment(filed_first_observed_last["id"], DIRECTOR))[
            "validation_status"
        ]
        == "SUPERSEDED"
    )
    assert filed_second_observed_first["validation_status"] == "PENDING_VALIDATION"

    verdict = validate_success(
        api.validate_skin_assessment(
            filed_second_observed_first["id"],
            {"confirmed_stage": "STAGE_2", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    assert verdict["validation_status"] == "VALIDATED"
    assert verdict["poa_determination"] == "INDETERMINATE", (
        "the earliest observation 2026-08-01T00:00:00Z is not after the window end "
        "2026-08-01T12:00:00Z, so the hospital-acquired branch cannot fire"
    )
    assert verdict["poa_determination"] != "HAPI", (
        "ordering by created_at would have picked the 2026-08-03T00:00:00Z observation"
    )

    case = find_case_for_assessment(filed_second_observed_first["id"], api=api)
    assert case["classification"] == "UNDETERMINED"
    assert case["status"] == "OPEN", "the case hop only classifies on POA or HAPI"

    after_unit = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert after_unit["open_hapi_rca_count"] == 0
    assert after_unit["survey_posture"] == "OPEN"
    assert (
        get_success_data(api.get_patient(patient["id"], DIRECTOR))[
            "poa_skin_assessment_documented"
        ]
        is False
    ), "only a present-on-admission verdict sets that flag"

    cases, meta = validate_paginated(
        api.list_pressure_injury_cases(DIRECTOR, {"patient_id": patient["id"]})
    )
    assert meta["total_count"] == 2, "one case per filed assessment"
    for row in cases:
        assert row["status"] == "OPEN"
        assert row["rca_due_at"] is None


def test_restage_demands_the_stager_while_the_analysis_lead_must_not_be(api):
    """One code, two opposite directions, on two different endpoints.

    PRD §2.7: "Third, and in the opposite direction, only the nurse who staged
    an assessment may re-stage it after a dispute: on that operation
    `X-User-ID` must equal `staged_by_nurse_id`, and any other caller is refused
    with the same code."
    PRD §3.6: "The lead must be fully `CERTIFIED` — `CANDIDATE` is not
    sufficient here, unlike consult assignment — and must not be the nurse
    recorded as `staged_by_nurse_id` on the case's originating assessment."
    PRD §2.10: "This ordering is normative: a request that violates two rules
    must surface the earlier one's code."

    Design: Corner/rbac/restage_requires_the_original_stager_while_rca_lead_must_differ_from_it
    """
    unit = create_unit(api, unit_code="3E", name="Three East", bed_count=18)
    patient = create_patient(
        unit,
        api=api,
        mrn="RBACMRN07",
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=2,
        device_related_risk=False,
        ostomy_present=False,
    )
    stager = create_candidate_nurse(unit, api=api, full_name="Sara Stager", ce_credits=30)
    verifier = create_certified_nurse(unit, api=api, full_name="Vera Verifier", ce_credits=30)
    assert stager["certification_status"] == "CANDIDATE"
    assert verifier["certification_status"] == "CERTIFIED"

    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_3",
        clinical_note="Full-thickness sacral wound with slough at the margin.",
    )
    triage_consult(consult, stager, api=api)
    assign_consult(consult, stager, api=api)
    assessment = file_assessment(
        consult,
        patient,
        stager,
        api=api,
        anatomic_location="SACRUM",
        observed_stage="STAGE_3",
        measured_area_cm2=12.0,
        observed_at="2026-08-01T00:00:00Z",
        present_on_admission_claimed=False,
    )
    case = find_case_for_assessment(assessment["id"], api=api)

    disputed = validate_success(
        api.dispute_skin_assessment(
            assessment["id"],
            {
                "dispute_reason": (
                    "Photograph does not support a full-thickness call; "
                    "re-measure and re-stage."
                )
            },
            DIRECTOR,
        )
    )
    assert disputed["validation_status"] == "DISPUTED"
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["protocol_hold"]
        is True
    )
    assert get_success_data(api.get_unit(unit["id"], DIRECTOR))["disputed_staging_count"] == 1

    validate_error(
        api.restage_skin_assessment(
            assessment["id"],
            {"observed_stage": "STAGE_3", "measured_area_cm2": 14.0},
            make_nurse_headers(verifier["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=422,
    )
    untouched = get_success_data(api.get_skin_assessment(assessment["id"], DIRECTOR))
    assert untouched["measured_area_cm2"] == 12.0
    assert untouched["restage_count"] == 0
    assert untouched["validation_status"] == "DISPUTED"
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["protocol_hold"]
        is True
    )

    restaged = validate_success(
        api.restage_skin_assessment(
            assessment["id"],
            {"observed_stage": "STAGE_3", "measured_area_cm2": 14.0},
            make_nurse_headers(stager["id"]),
        )
    )
    assert restaged["validation_status"] == "PENDING_VALIDATION"
    assert restaged["measured_area_cm2"] == 14.0
    assert restaged["restage_count"] == 1
    assert restaged["dispute_reason"] is None
    assert (
        get_success_data(api.get_consult_request(consult["id"], DIRECTOR))["protocol_hold"]
        is False
    )

    validated = validate_success(
        api.validate_skin_assessment(
            assessment["id"],
            {"confirmed_stage": "STAGE_3", "present_on_admission_confirmed": False},
            DIRECTOR,
        )
    )
    assert validated["poa_determination"] == "HAPI"
    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["acuity_score"] == 75.0, (
        "(60 stage + min(25, 5 * 2) comorbidity + 0 device + min(15, floor(14 / 10) * 5))"
        " * 1.00"
    )
    assert after_consult["priority_band"] == "P1"
    escalating_case = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert escalating_case["status"] == "RCA_REQUIRED"
    assert as_instant(escalating_case["rca_due_at"]) == as_instant("2026-08-04T00:00:00Z")
    unit_after_cascade = get_success_data(api.get_unit(unit["id"], DIRECTOR))
    assert unit_after_cascade["open_hapi_rca_count"] == 1
    assert unit_after_cascade["survey_posture"] == "OPEN"

    validate_error(
        api.rca_start(
            case["id"],
            {"rca_lead_nurse_id": stager["id"]},
            make_nurse_headers(verifier["id"]),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        expected_status=422,
    )
    still_required = get_success_data(api.get_pressure_injury_case(case["id"], DIRECTOR))
    assert still_required["status"] == "RCA_REQUIRED"
    assert still_required["rca_lead_nurse_id"] is None, (
        "the stager is refused at rung 30 before the certification rung is reached"
    )

    started = validate_success(
        api.rca_start(
            case["id"],
            {"rca_lead_nurse_id": verifier["id"]},
            make_nurse_headers(verifier["id"]),
        )
    )
    assert started["status"] == "RCA_IN_PROGRESS"
    assert started["rca_lead_nurse_id"] == verifier["id"]

    assert unit_after_cascade["version"] == 3, (
        "1 at creation, 1 from the dispute counter and 1 from the hospital-acquired hop"
    )
