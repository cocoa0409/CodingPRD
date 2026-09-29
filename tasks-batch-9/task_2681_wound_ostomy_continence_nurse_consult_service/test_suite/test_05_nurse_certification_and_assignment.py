"""The certification ladder, the eligibility score it is gated on, and the
capacity bookkeeping that assignment, closure and cancellation share."""
from test_helpers import factories as f
from test_helpers import (
    as_instant,
    assert_two_decimal_places,
    assert_woc_nurse,
    assign_consult,
    create_candidate_nurse,
    create_certified_nurse,
    create_consult,
    create_patient,
    create_product,
    create_trainee_nurse,
    create_unit,
    file_assessment,
    get_success_data,
    set_clock,
    triage_consult,
    validate_assessment,
    validate_error,
    validate_success,
)
from test_helpers.test_users import make_director_headers, make_nurse_headers


DIRECTOR = make_director_headers()


def _lapsed_nurse_and_triaged_consult(api):
    """Unit 7W, a nurse walked up to `CERTIFIED` and then lapsed, and a consult
    sitting in `TRIAGED` with nobody assigned to it."""
    unit = create_unit(
        api,
        unit_code="7W",
        name="Seven West",
        bed_count=24,
        rental_budget_cap_cents=500000,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    assert nurse["certification_status"] == "CERTIFIED"
    assert nurse["max_consult_load"] == 8
    lapsed = validate_success(
        api.lapse_woc_nurse(
            nurse["id"], {"reason": "Recertification paperwork not submitted."}, DIRECTOR
        )
    )
    assert lapsed["certification_status"] == "LAPSED"
    patient = create_patient(
        unit,
        api=api,
        mrn="MRN-L1",
        admitted_at="2026-07-30T00:00:00Z",
        comorbidity_count=1,
        device_related_risk=False,
    )
    consult = create_consult(
        unit,
        patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound, partial thickness.",
    )
    triaged = triage_consult(consult, nurse, api=api)
    assert triaged["status"] == "TRIAGED"
    assert triaged["assigned_nurse_id"] is None
    return unit, nurse, consult


def test_a_lapsed_nurse_cannot_be_handed_a_triaged_consult(api):
    """A well-formed assignment fails on the target nurse's own state.

    PRD §3.4: "The nominated nurse's `certification_status` must be `CANDIDATE`
    or `CERTIFIED` — a `TRAINEE` or `LAPSED` nurse is refused with
    `ERR_NURSE_NOT_CERTIFIED` — and their `active_consult_load` must be strictly
    below their `max_consult_load`, otherwise `ERR_NURSE_LOAD_EXCEEDED`."
    PRD §3.3: "Lapsing takes a `CERTIFIED` nurse to `LAPSED` with a recorded
    `reason` and drops `max_consult_load` to 0; crucially, `active_consult_load`
    is left exactly as it was, because a lapse does not tear a nurse away from
    patients already in their care — it only blocks new assignments."

    Design: Difficulty/cross_entity_state_dependency/assign_blocked_when_nurse_lapsed
    """
    _unit, nurse, consult = _lapsed_nurse_and_triaged_consult(api)

    validate_error(
        api.assign_consult_request(
            consult["id"], {"assigned_nurse_id": nurse["id"]}, DIRECTOR
        ),
        "ERR_NURSE_NOT_CERTIFIED",
        expected_status=422,
    )

    after_nurse = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert after_nurse["certification_status"] == "LAPSED"
    assert after_nurse["max_consult_load"] == 0
    assert after_nurse["active_consult_load"] == 0, (
        "the refused assignment performed no increment"
    )
    assert_woc_nurse(after_nurse)

    after_consult = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
    assert after_consult["status"] == "TRIAGED", "the consult stayed where it was"
    assert after_consult["assigned_nurse_id"] is None


def test_the_certification_gate_answers_before_the_load_gate(api):
    """Both gates are breached at once; the earlier rung's code must surface.

    PRD §2.10: "When more than one rule could reject a request, the rules are
    evaluated in the fixed ascending order below, the first failing rule wins,
    and no later rule is evaluated."
    PRD §2.10 rung 32: "Certification gating of nurse references: an assignment
    target's `certification_status` must be `CANDIDATE` or `CERTIFIED`, an RCA
    lead's must be exactly `CERTIFIED`, and a survey observer's must be
    `CANDIDATE` or `CERTIFIED` — `ERR_NURSE_NOT_CERTIFIED` (422), on
    `POST /consult-requests/{consult_id}/assign`,
    `POST /pressure-injury-cases/{case_id}/rca-start` and
    `POST /survey-observations`."
    PRD §2.10 rung 52: "The assignment target's `active_consult_load` is
    strictly below their `max_consult_load`, evaluated before any increment;
    re-assigning the nurse who already holds the consult skips this check
    entirely — `ERR_NURSE_LOAD_EXCEEDED` (422), on
    `POST /consult-requests/{consult_id}/assign`."

    Design: Difficulty/cross_entity_state_dependency/assign_blocked_when_nurse_lapsed
    """
    _unit, nurse, consult = _lapsed_nurse_and_triaged_consult(api)
    before = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert before["active_consult_load"] == 0
    assert before["max_consult_load"] == 0, (
        "0 < 0 is false, so the load rung would also reject this request"
    )

    response = api.assign_consult_request(
        consult["id"], {"assigned_nurse_id": nurse["id"]}, DIRECTOR
    )
    validate_error(response, "ERR_NURSE_NOT_CERTIFIED", expected_status=422)
    assert response.json()["data"]["error_id"] != "ERR_NURSE_LOAD_EXCEEDED", (
        "rung 32 is evaluated before rung 52, so the capacity code is unreachable here"
    )

    renewed = validate_success(
        api.certify_woc_nurse(
            nurse["id"], {"cert_expires_at": "2029-08-01T00:00:00Z"}, DIRECTOR
        )
    )
    assert renewed["certification_status"] == "CERTIFIED"
    assert renewed["max_consult_load"] == 8

    assigned = validate_success(
        api.assign_consult_request(
            consult["id"], {"assigned_nurse_id": nurse["id"]}, DIRECTOR
        )
    )
    assert assigned["status"] == "ASSIGNED", (
        "the identical payload succeeds once the certification dimension is repaired"
    )
    assert assigned["assigned_nurse_id"] == nurse["id"]
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["active_consult_load"] == 1


def _nina_holding_two_consults(api):
    """Nina holds two consults: one driven to `PLAN_ACTIVE` over a confirmed
    present-on-admission staging, one left at `ASSIGNED`."""
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
        sku="FOAM-02",
        name="Silicone foam dressing 15x15",
        category="FOAM",
        unit_cost_cents=1250,
        formulary_tier="PREFERRED",
    )
    first_patient = create_patient(
        unit,
        api=api,
        mrn="MRN-W1",
        admitted_at="2026-07-31T12:00:00Z",
        comorbidity_count=0,
        device_related_risk=False,
    )
    second_patient = create_patient(
        unit,
        api=api,
        mrn="MRN-W2",
        admitted_at="2026-07-31T12:00:00Z",
        comorbidity_count=0,
        device_related_risk=False,
    )
    first = create_consult(
        unit,
        first_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Sacral wound documented on admission.",
    )
    triage_consult(first, nina, api=api)
    assign_consult(first, nina, api=api)
    second = create_consult(
        unit,
        second_patient,
        api=api,
        consult_type="WOUND",
        reported_stage="STAGE_2",
        clinical_note="Heel redness documented on admission.",
    )
    triage_consult(second, nina, api=api)
    assign_consult(second, nina, api=api)

    assessment = file_assessment(
        first,
        first_patient,
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
    plan_active = validate_success(
        api.create_dressing_protocol(
            f.create_dressing_protocol_payload(
                first["id"], product["id"], change_frequency_hours=48, units_per_change=2
            ),
            make_nurse_headers(nina["id"]),
        ),
        expected_status=201,
    )
    assert plan_active["consult_request_id"] == first["id"]
    return {"nina": nina, "omar": omar, "first": first, "second": second}


def test_the_capacity_count_returns_to_zero_across_a_close_and_a_cancel(api):
    """Two assignments, one closure and one cancellation net out to zero load.

    PRD §3.3: "`active_consult_load` counts the nurse's consults whose `status`
    is `ASSIGNED`, `ASSESSED`, `PLAN_ACTIVE` or `ESCALATED` — note that an
    escalated consult still occupies load — and it is a conserved quantity:
    every operation that adds one to it somewhere must take one away somewhere
    else or be an outright assignment, and it may never exceed
    `max_consult_load` or fall below 0."
    PRD §3.4: "Closing moves the consult `PLAN_ACTIVE → CLOSED` and reaches into
    the assigned nurse's record in three ways at once: `active_consult_load`
    falls by 1, `mentored_consult_count` rises by 1, and
    `certification_eligibility_score` is recomputed from the new mentored count,
    with the nurse row versioned for all three."
    PRD §3.4: "The first hop sets the consult's `status` to `CANCELLED` and,
    when an `assigned_nurse_id` is present, reduces that nurse's
    `active_consult_load` by 1 and versions the nurse row."

    Design: Difficulty/compensating_invariant/nurse_consult_load_conserved_across_assign_and_close
    """
    scenario = _nina_holding_two_consults(api)
    nina, omar = scenario["nina"], scenario["omar"]
    first, second = scenario["first"], scenario["second"]
    nurse_headers = make_nurse_headers(nina["id"])

    checkpoint_zero = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_zero["active_consult_load"] == 2, "two outright assignments"
    assert checkpoint_zero["max_consult_load"] == 8
    assert checkpoint_zero["certification_status"] == "CERTIFIED"

    closed = validate_success(
        api.close_consult_request(
            first["id"],
            {"closing_summary": "Wound healing, unit staff educated, POA documented."},
            nurse_headers,
        )
    )
    assert closed["status"] == "CLOSED"
    checkpoint_one = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_one["active_consult_load"] == 1, "the close took one away"
    assert checkpoint_one["certification_status"] == "CERTIFIED"
    assert checkpoint_one["max_consult_load"] == 8

    cancelled = validate_success(
        api.cancel_consult_request(
            second["id"], {"reason": "Patient transferred to another facility."}, DIRECTOR
        )
    )
    assert cancelled["status"] == "CANCELLED"
    checkpoint_two = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_two["active_consult_load"] == 0, (
        "2 assignments less 1 close less 1 cancel lands on exactly 0, not on 1"
    )
    assert checkpoint_two["certification_status"] == "CERTIFIED", (
        "load bookkeeping never touches the certification dimension"
    )
    assert checkpoint_two["max_consult_load"] == 8
    assert_woc_nurse(checkpoint_two)

    validator = get_success_data(api.get_woc_nurse(omar["id"], DIRECTOR))
    assert validator["active_consult_load"] == 0, (
        "validating another nurse's staging carries no load"
    )
    assert validator["mentored_consult_count"] == 0


def test_only_the_closed_consult_counts_as_mentoring_and_lifts_the_score(api):
    """The mentored component moves on the close and ignores the cancel.

    PRD §3.3: "`mentored_consult_count` counts the nurse's consults whose
    `status` is `CLOSED`."
    PRD §3.3: "The **mentored component** is 10 points for each closed consult
    the nurse has mentored, counting at most 4 of them, so it saturates at 40
    points."
    PRD §3.3: "The score is then the recency component weighted at 0.4, plus the
    credit component weighted at 0.4, plus the mentored component weighted at
    0.2, and that weighted sum is rounded half up to two decimal places once, at
    the end."
    PRD §3.3: "It is recomputed on every competency signoff and again every time
    one of the nurse's consults is closed."

    Design: Difficulty/compensating_invariant/nurse_consult_load_conserved_across_assign_and_close
    """
    scenario = _nina_holding_two_consults(api)
    nina = scenario["nina"]
    first, second = scenario["first"], scenario["second"]

    checkpoint_zero = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_zero["mentored_consult_count"] == 0
    assert checkpoint_zero["certification_eligibility_score"] == 64.0, (
        "0.4 * 100 + 0.4 * min(60, 2 * 30) + 0.2 * 0 = 40 + 24 + 0"
    )
    assert_two_decimal_places(checkpoint_zero["certification_eligibility_score"])

    validate_success(
        api.close_consult_request(
            first["id"],
            {"closing_summary": "Wound healing, unit staff educated, POA documented."},
            make_nurse_headers(nina["id"]),
        )
    )
    checkpoint_one = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_one["mentored_consult_count"] == 1
    assert checkpoint_one["certification_eligibility_score"] == 66.0, (
        "0.4 * 100 + 0.4 * 60 + 0.2 * (10 * min(4, 1)) = 40 + 24 + 2"
    )

    validate_success(
        api.cancel_consult_request(
            second["id"], {"reason": "Patient transferred to another facility."}, DIRECTOR
        )
    )
    checkpoint_two = get_success_data(api.get_woc_nurse(nina["id"], DIRECTOR))
    assert checkpoint_two["mentored_consult_count"] == 1, (
        "a cancelled consult is not a mentored one"
    )
    assert checkpoint_two["certification_eligibility_score"] == 66.0, (
        "the cancel leaves the score exactly where the close put it"
    )


def test_a_lapse_and_a_renewal_walk_the_ladder_back_down_and_up(api):
    """`LAPSED` locks nothing: the same nurse row returns to `CERTIFIED`.

    PRD §3.3: "Nurses enter the service at the bottom of a four-rung
    certification ladder and may cycle back down and up again."
    PRD §3.3: "Renewal closes the cycle: a `LAPSED` nurse who satisfies the same
    three gates returns `LAPSED → CERTIFIED` with a fresh `cert_expires_at` and
    a `max_consult_load` of 8 once more."
    PRD §3.3: "`certification_status` takes exactly one of `TRAINEE`,
    `CANDIDATE`, `CERTIFIED` and `LAPSED`, and it is the sole determinant of
    `max_consult_load`: a `CERTIFIED` nurse may hold 8 concurrent consults, a
    `CANDIDATE` 3, and a `TRAINEE` or `LAPSED` nurse none at all."

    Design: Corner/state_machines/nurse_lapse_then_recertify_cycles_back_to_certified
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=250000,
    )
    nurse = create_certified_nurse(
        unit,
        api=api,
        full_name="Nina Stage",
        ce_credits=30,
        cert_expires_at="2028-08-01T00:00:00Z",
    )
    assert nurse["certification_status"] == "CERTIFIED"
    assert nurse["max_consult_load"] == 8
    assert nurse["competency_signoff_count"] == 2
    assert nurse["certification_eligibility_score"] == 64.0
    assert as_instant(nurse["cert_expires_at"]) == as_instant("2028-08-01T00:00:00Z")

    lapsed = validate_success(
        api.lapse_woc_nurse(
            nurse["id"],
            {"reason": "Certification renewal paperwork overdue."},
            DIRECTOR,
        )
    )
    assert lapsed["certification_status"] == "LAPSED"
    assert lapsed["max_consult_load"] == 0
    assert lapsed["active_consult_load"] == 0, "lapsing does not touch the live load"
    assert lapsed["ce_credits"] == 30, "nor the credit balance"
    assert lapsed["certification_eligibility_score"] == 64.0, (
        "the certification dimension does not feed the score"
    )

    renewed = validate_success(
        api.certify_woc_nurse(
            nurse["id"], {"cert_expires_at": "2029-08-01T00:00:00Z"}, DIRECTOR
        )
    )
    assert renewed["certification_status"] == "CERTIFIED"
    assert renewed["max_consult_load"] == 8
    assert as_instant(renewed["cert_expires_at"]) == as_instant("2029-08-01T00:00:00Z"), (
        "the fresh expiry overwrites the old one rather than being preserved"
    )
    assert renewed["certification_eligibility_score"] == 64.0
    assert renewed["competency_signoff_count"] == 2
    assert_woc_nurse(renewed)


def test_the_recency_component_decays_with_the_clock_not_the_signoff_instant(api):
    """Two months of clock cost 10 recency points even on a back-dated signoff.

    PRD §3.3: "The **recency component** starts from a base of 100 and loses 5
    points for each whole 30-day month elapsed since the last signoff: the
    elapsed time from `last_competency_signoff_at` to the logical clock is
    measured in whole hours and divided by 720, discarding any remainder, to
    give a month count; the component is 100 less 5 times that month count,
    floored at 0 so it never goes negative; and when
    `last_competency_signoff_at` is null the month count is treated as 0, which
    leaves the recency component at its full 100."
    PRD §3.3: "Each accepted signoff adds 1 to `competency_signoff_count`,
    overwrites `last_competency_signoff_at` with the supplied `signed_off_at`,
    and recomputes `certification_eligibility_score`."
    PRD §3.3: "Advancement from `TRAINEE → CANDIDATE` requires at least 1
    recorded competency signoff and sets `max_consult_load` to 3."
    PRD §3.3: "Certification is reachable from either `CANDIDATE` or `LAPSED`,
    moving the nurse to `CERTIFIED`, stamping the supplied `cert_expires_at`
    onto the record and setting `max_consult_load` to 8; it demands all three
    gates simultaneously — a `certification_eligibility_score` of at least
    55.00, `ce_credits` of at least 30, and `competency_signoff_count` of at
    least 2."

    Design: Corner/calculations/certification_eligibility_score_applies_monthly_recency_decay
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_trainee_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    for domain in ("WOUND_STAGING", "TRIAGE"):
        validate_success(
            api.create_competency_signoff(
                nurse["id"],
                {"signed_off_at": "2026-08-01T00:00:00Z", "competency_domain": domain},
                DIRECTOR,
            )
        )
    fresh = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert fresh["certification_eligibility_score"] == 64.0, (
        "0.4 * (100 - 5 * 0 months) + 0.4 * min(60, 2 * 30) + 0.2 * 0"
    )

    set_clock("2026-10-01T00:00:00Z", api=api)

    validate_success(
        api.create_competency_signoff(
            nurse["id"],
            {"signed_off_at": "2026-08-01T00:00:00Z", "competency_domain": "RCA"},
            DIRECTOR,
        )
    )
    decayed = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert decayed["competency_signoff_count"] == 3
    assert as_instant(decayed["last_competency_signoff_at"]) == as_instant("2026-08-01T00:00:00Z"), (
        "the field tracks the supplied instant, not the clock the signoff was taken at"
    )
    assert decayed["certification_eligibility_score"] == 60.0, (
        "floor(1464 / 720) = 2 months, so 0.4 * (100 - 5 * 2) + 0.4 * 60 = 36 + 24"
    )
    assert decayed["certification_eligibility_score"] != 64.0, (
        "the clock moved even though the signoff instant did not"
    )
    assert_two_decimal_places(decayed["certification_eligibility_score"])

    advanced = validate_success(api.advance_woc_nurse(nurse["id"], {}, DIRECTOR))
    assert advanced["certification_status"] == "CANDIDATE"
    assert advanced["max_consult_load"] == 3

    certified = validate_success(
        api.certify_woc_nurse(
            nurse["id"], {"cert_expires_at": "2028-10-01T00:00:00Z"}, DIRECTOR
        )
    )
    assert certified["certification_status"] == "CERTIFIED", (
        "60.00 still clears the 55.00 floor with 30 credits and 3 signoffs"
    )
    assert certified["max_consult_load"] == 8


def test_thirty_credits_and_two_hundred_credits_score_identically(api):
    """The credit term flattens at the cap, and the credit floor is separate.

    PRD §3.3: "The **credit component** is 2 points for each unit of
    `ce_credits`, capped at 60 points, so credits beyond 30 add nothing to this
    component."
    PRD §3.3: "The three components are themselves never individually rounded."
    PRD §2.10 rung 62: "The certification pipeline gate: certifying requires a
    `certification_eligibility_score` of at least 55.00, `ce_credits` of at
    least 30 and `competency_signoff_count` of at least 2, while advancing to
    candidate requires `competency_signoff_count` of at least 1 —
    `ERR_CERTIFICATION_NOT_ELIGIBLE` (422), on
    `POST /woc-nurses/{nurse_id}/certify` and
    `POST /woc-nurses/{nurse_id}/advance`."

    Design: Corner/calculations/certification_credit_component_capped_at_sixty_points
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    at_the_cap = create_trainee_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    far_past_it = create_trainee_nurse(unit, api=api, full_name="Otto Credit", ce_credits=200)
    one_short = create_trainee_nurse(unit, api=api, full_name="Pia Short", ce_credits=29)
    for nurse in (at_the_cap, far_past_it, one_short):
        for domain in ("WOUND_STAGING", "TRIAGE"):
            validate_success(
                api.create_competency_signoff(
                    nurse["id"],
                    {"signed_off_at": "2026-08-01T00:00:00Z", "competency_domain": domain},
                    DIRECTOR,
                )
            )

    capped = get_success_data(api.get_woc_nurse(at_the_cap["id"], DIRECTOR))
    saturated = get_success_data(api.get_woc_nurse(far_past_it["id"], DIRECTOR))
    below = get_success_data(api.get_woc_nurse(one_short["id"], DIRECTOR))
    assert capped["certification_eligibility_score"] == 64.0, (
        "0.4 * 100 + 0.4 * min(60, 2 * 30) + 0.2 * 0"
    )
    assert saturated["certification_eligibility_score"] == 64.0, (
        "2 * 200 = 400 raw credit points still contribute only the capped 60"
    )
    assert saturated["certification_eligibility_score"] <= 100.0, (
        "an uncapped credit term would score 200.00, outside the 0.00-to-100.00 scale"
    )
    assert below["certification_eligibility_score"] == 63.2, (
        "0.4 * 100 + 0.4 * (2 * 29) = 40.00 + 23.20, so one credit below the cap shows"
    )
    assert_two_decimal_places(below["certification_eligibility_score"])

    advanced = validate_success(api.advance_woc_nurse(one_short["id"], {}, DIRECTOR))
    assert advanced["certification_status"] == "CANDIDATE", (
        "two signoffs clear the single-signoff advancement gate"
    )

    validate_error(
        api.certify_woc_nurse(
            one_short["id"], {"cert_expires_at": "2028-08-01T00:00:00Z"}, DIRECTOR
        ),
        "ERR_CERTIFICATION_NOT_ELIGIBLE",
        expected_status=422,
    )
    refused = get_success_data(api.get_woc_nurse(one_short["id"], DIRECTOR))
    assert refused["certification_status"] == "CANDIDATE", (
        "29 credits fail the standalone credit gate even though 63.20 clears 55.00"
    )
    assert refused["cert_expires_at"] is None
    assert refused["max_consult_load"] == 3


def test_the_fourth_assignment_is_refused_but_re_routing_the_incumbent_is_not(api):
    """The ceiling bites before the increment, and the incumbent is exempt.

    PRD §2.10 rung 52: "The assignment target's `active_consult_load` is
    strictly below their `max_consult_load`, evaluated before any increment;
    re-assigning the nurse who already holds the consult skips this check
    entirely — `ERR_NURSE_LOAD_EXCEEDED` (422), on
    `POST /consult-requests/{consult_id}/assign`."
    PRD §3.3: "`certification_status` takes exactly one of `TRAINEE`,
    `CANDIDATE`, `CERTIFIED` and `LAPSED`, and it is the sole determinant of
    `max_consult_load`: a `CERTIFIED` nurse may hold 8 concurrent consults, a
    `CANDIDATE` 3, and a `TRAINEE` or `LAPSED` nurse none at all."
    PRD §3.4: "When the clock runs out on an assigned consult, a `WocNurse` or a
    `WocProgramDirector` escalates it with a `reason`, moving it
    `ASSIGNED → ESCALATED` and adding 1 to `escalation_count`."

    Design: Corner/validations/nurse_load_aggregate_rejected_at_ceiling_but_reassignment_exempt
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_candidate_nurse(
        unit, api=api, full_name="Nina Stage", ce_credits=30
    )
    assert nurse["certification_status"] == "CANDIDATE"
    assert nurse["max_consult_load"] == 3

    notes = [
        "Redness over the sacrum.",
        "Redness over the left heel.",
        "Redness over the right heel.",
        "Redness over the ischium.",
    ]
    consults = []
    for index, note in enumerate(notes, start=1):
        patient = create_patient(
            unit, api=api, mrn=f"MRN-S{index}", admitted_at="2026-07-31T00:00:00Z"
        )
        consult = create_consult(
            unit,
            patient,
            api=api,
            consult_type="WOUND",
            reported_stage="STAGE_1",
            clinical_note=note,
        )
        triaged = triage_consult(consult, nurse, api=api)
        assert triaged["priority_band"] == "P3"
        assert as_instant(triaged["sla_due_at"]) == as_instant("2026-08-04T00:00:00Z")
        consults.append(consult)
    for consult in consults[:3]:
        assign_consult(consult, nurse, api=api)

    at_ceiling = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert at_ceiling["active_consult_load"] == 3
    assert at_ceiling["max_consult_load"] == 3

    validate_error(
        api.assign_consult_request(
            consults[3]["id"], {"assigned_nurse_id": nurse["id"]}, DIRECTOR
        ),
        "ERR_NURSE_LOAD_EXCEEDED",
        expected_status=422,
    )
    fourth = get_success_data(api.get_consult_request(consults[3]["id"], DIRECTOR))
    assert fourth["status"] == "TRIAGED"
    assert fourth["assigned_nurse_id"] is None
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["active_consult_load"] == 3, (
        "no partial increment leaked out of the refused assignment"
    )

    set_clock("2026-08-05T00:00:00Z", api=api)
    escalated = validate_success(
        api.escalate_consult_request(
            consults[0]["id"],
            {"reason": "SLA breached overnight with no bedside assessment."},
            make_nurse_headers(nurse["id"]),
        )
    )
    assert escalated["status"] == "ESCALATED"
    assert escalated["escalation_count"] == 1
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["active_consult_load"] == 3, (
        "escalation does not release the nurse"
    )

    re_routed = validate_success(
        api.assign_consult_request(
            consults[0]["id"], {"assigned_nurse_id": nurse["id"]}, DIRECTOR
        )
    )
    assert re_routed["status"] == "ASSIGNED", (
        "the load check is skipped entirely when the nurse does not change"
    )
    assert re_routed["assigned_nurse_id"] == nurse["id"]
    assert get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))["active_consult_load"] == 3, (
        "a re-assignment to the incumbent must not double-count"
    )


def test_lapsing_leaves_the_nurse_deliberately_over_committed(api):
    """The lapse action zeroes the ceiling and leaves the live load standing.

    PRD §3.3: "Lapsing takes a `CERTIFIED` nurse to `LAPSED` with a recorded
    `reason` and drops `max_consult_load` to 0; crucially, `active_consult_load`
    is left exactly as it was, because a lapse does not tear a nurse away from
    patients already in their care — it only blocks new assignments."
    PRD §3.3: "It is recomputed on every competency signoff and again every time
    one of the nurse's consults is closed."

    Design: Corner/endpoints/nurse_lapse_action_zeroes_max_load_without_touching_active_load
    """
    unit = create_unit(
        api,
        unit_code="3E",
        name="Three East",
        bed_count=18,
        rental_budget_cap_cents=0,
    )
    nurse = create_certified_nurse(unit, api=api, full_name="Nina Stage", ce_credits=30)
    consults = []
    for index, note in ((1, "Sacral redness."), (2, "Heel redness.")):
        patient = create_patient(
            unit, api=api, mrn=f"MRN-AC{index}", admitted_at="2026-07-31T00:00:00Z"
        )
        consult = create_consult(
            unit,
            patient,
            api=api,
            consult_type="WOUND",
            reported_stage="STAGE_1",
            clinical_note=note,
        )
        triage_consult(consult, nurse, api=api)
        assign_consult(consult, nurse, api=api)
        consults.append(consult)

    before = get_success_data(api.get_woc_nurse(nurse["id"], DIRECTOR))
    assert before["certification_status"] == "CERTIFIED"
    assert before["max_consult_load"] == 8
    assert before["active_consult_load"] == 2
    version_before = before["version"]
    score_before = before["certification_eligibility_score"]

    lapsed = validate_success(
        api.lapse_woc_nurse(
            nurse["id"],
            {"reason": "Certification renewal paperwork not filed by the deadline."},
            DIRECTOR,
        )
    )
    assert lapsed["certification_status"] == "LAPSED"
    assert lapsed["max_consult_load"] == 0
    assert lapsed["active_consult_load"] == 2, (
        "the action must not silently unassign work to restore load below the ceiling"
    )
    assert lapsed["version"] == version_before + 1
    assert lapsed["certification_eligibility_score"] == score_before, (
        "the score is recomputed only on a signoff or a consult close"
    )

    for consult in consults:
        still_assigned = get_success_data(api.get_consult_request(consult["id"], DIRECTOR))
        assert still_assigned["status"] == "ASSIGNED"
        assert still_assigned["assigned_nurse_id"] == nurse["id"]
        assert still_assigned["version"] == 3, (
            "one create, one triage and one assign — the lapse moved no consult row"
        )
