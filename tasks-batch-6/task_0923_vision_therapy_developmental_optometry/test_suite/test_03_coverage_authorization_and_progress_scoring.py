"""Coverages, the prior-authorization visit pool, and reassessment progress scoring."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    acuity_measurement_payload,
    amplitude_measurement_payload,
    assert_money,
    assert_pct,
    assert_visit_unit_identity,
    assert_vision_allowance_identity,
    build_battery,
    build_signed_evaluation,
    build_signed_reassessment,
    create_plan_payload,
    get_success_data,
    make_billing_specialist_headers,
    make_front_desk_headers,
    make_optometrist_headers,
    new_medical_payer,
    new_patient,
    new_therapist,
    new_vision_payer,
    npc_measurement_payload,
    read_authorization,
    read_plan,
    schedule_session,
    set_clock,
    setup_active_plan,
    setup_clinic_configuration,
    symptom_measurement_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vergence_measurement_payload,
)
from test_helpers import api_client as _client


# --------------------------------------------------------------------------
# Coverages
# --------------------------------------------------------------------------


def test_coverage_list_filters_by_patient_and_reports_the_page_window(api):
    """PRD §2.3: "When `limit` is omitted it defaults to 10; the smallest accepted
    value is 1 and the largest is 100."
    PRD §2.3: "`total_count` reports how many rows matched the filters before the page
    window was applied, and `has_more` is true exactly when rows remain beyond the
    current window."
    PRD §3.3: "Coverages are readable individually and as a list narrowed by
    `patient_id`, `payer_id` and `status`."

    Design: Corner/entities/coverage_listing_paginates_and_filters_by_patient
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient()
    medical = new_medical_payer()
    vision = new_vision_payer()
    get_success_data(
        api.create_coverage(
            {
                "patient_id": patient["id"],
                "payer_id": medical["id"],
                "member_number": "M-1",
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
                "deductible_total": 200.00,
                "deductible_met": 0.00,
            },
            make_billing_specialist_headers(),
        )
    )
    get_success_data(
        api.create_coverage(
            {
                "patient_id": patient["id"],
                "payer_id": vision["id"],
                "member_number": "V-1",
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
                "vision_allowance_total": 250.00,
            },
            make_billing_specialist_headers(),
        )
    )

    response = api.list_coverages(
        make_billing_specialist_headers(),
        {"patient_id": patient["id"], "limit": 1, "offset": 0},
    )
    rows, meta = validate_paginated(response)

    assert response.json()["response_type"] == "array"
    assert len(rows) == 1, f"Expected a page of 1 row, got {len(rows)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_coverage_accumulators_take_their_declared_defaults(api):
    """PRD §3.3: "Four accumulators may be seeded at creation and are otherwise
    defaulted: `deductible_total` and `deductible_met`, both `0.00` by default and
    both meaningful only under a medical payer; `vision_allowance_total`, `0.00` by
    default; and the two last-paid service dates,
    `last_paid_service_date_therapy` and `last_paid_service_date_evaluation`, both
    null by default, which record the service date of the most recent paid claim in
    each frequency bucket."
    PRD §3.3: "Two further accumulators are computed rather than supplied:
    `vision_allowance_used` starts at `0.00` and `vision_allowance_remaining` starts
    equal to `vision_allowance_total`, which is how the vision-allowance identity
    holds from the very first instant."

    Design: Corner/entities/coverage_defaults_applied_when_accumulators_omitted
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient()
    vision = new_vision_payer()

    data = validate_success(
        api.create_coverage(
            {
                "patient_id": patient["id"],
                "payer_id": vision["id"],
                "member_number": "V-1",
                "effective_start_date": "2026-01-01",
                "effective_end_date": "2026-12-31",
            },
            make_billing_specialist_headers(),
        ),
        201,
    )

    assert_money(data["deductible_total"], 0.00, "deductible_total")
    assert_money(data["deductible_met"], 0.00, "deductible_met")
    assert_money(data["vision_allowance_total"], 0.00, "vision_allowance_total")
    assert_money(data["vision_allowance_used"], 0.00, "vision_allowance_used")
    assert_money(data["vision_allowance_remaining"], 0.00, "vision_allowance_remaining")
    assert data["last_paid_service_date_therapy"] is None
    assert data["last_paid_service_date_evaluation"] is None
    assert_vision_allowance_identity(data)


# --------------------------------------------------------------------------
# The prior-authorization visit pool
# --------------------------------------------------------------------------


def test_granting_a_pool_against_an_unknown_coverage_is_refused(api):
    """PRD §2.7 rung 6: "**Coverage existence.** The `Coverage` named in the path or
    in `coverage_id` exists. Otherwise `ERR_COVERAGE_NOT_FOUND`, HTTP 404. Applies to
    reading one coverage, creating an authorization, and creating a claim."

    Design: Corner/entities/authorization_requires_an_existing_coverage_parent
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient()

    response = api.create_authorization(
        {
            "patient_id": patient["id"],
            "coverage_id": NON_EXISTENT_UUID,
            "auth_number": "A-1",
            "visits_authorized": 6,
            "window_start_date": "2026-06-01",
            "window_end_date": "2026-12-01",
        },
        make_billing_specialist_headers(),
    )

    validate_error(response, ApiErrorId.ERR_COVERAGE_NOT_FOUND.value, 404)
    rows, meta = validate_paginated(
        api.list_authorizations(
            make_billing_specialist_headers(),
            {"patient_id": patient["id"], "limit": 10, "offset": 0},
        )
    )
    assert meta["total_count"] == 0 and rows == []


def test_scheduling_draws_exactly_one_unit_and_preserves_the_visit_identity(api):
    """PRD §3.5: "On success the pool gives up exactly one unit: `visits_consumed`
    rises by 1, `visits_remaining` falls by 1, the pool's `version` is bumped, and if
    `visits_remaining` reaches 0 the pool moves `ACTIVE → EXHAUSTED` in the same call."
    PRD §2.10: "On every `Authorization` row, `visits_authorized` plus
    `visits_released` equals `visits_consumed` plus `visits_remaining`."

    Design: Difficulty/compensating_invariant/authorization_units_conserved_across_schedule_then_cancel
    """
    scn = setup_active_plan()
    schedule_session(scn)

    pool = read_authorization(scn["auth"])

    assert pool["visits_authorized"] == 12
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 0
    assert pool["visits_remaining"] == 11
    assert pool["status"] == "ACTIVE"
    assert_visit_unit_identity(pool)


def test_cancelling_records_an_opposite_movement_rather_than_undoing_the_consume(api):
    """PRD §3.5: "Cancellation sets `schedule_status` `CANCELLED`, forces
    `billing_status` to `NON_BILLABLE`, and, when the session's `modality` is
    `IN_OFFICE`, returns its unit to the pool: `visits_released` rises by 1,
    `visits_remaining` rises by 1, the pool's `version` is bumped, and an `EXHAUSTED`
    pool becomes `ACTIVE` again."
    PRD §3.3: "`visits_consumed` and `visits_released` are cumulative tallies and are
    never decremented — a release does not undo a consume, it records a second,
    opposite movement — which is exactly why the visit-unit identity of §2.10 is
    stable rather than merely arithmetically convenient."

    Design: Difficulty/compensating_invariant/authorization_units_conserved_across_schedule_then_cancel
    """
    scn = setup_active_plan()
    session = schedule_session(scn)

    cancelled = validate_success(
        api.cancel_session(session["id"], {"cancel_reason": "PATIENT_REQUEST"}, scn["hdr_front"]),
        200,
    )
    assert cancelled["schedule_status"] == "CANCELLED"

    pool = read_authorization(scn["auth"])
    assert pool["visits_authorized"] == 12
    assert pool["visits_consumed"] == 1
    assert pool["visits_released"] == 1
    assert pool["visits_remaining"] == 12
    assert pool["status"] == "ACTIVE"
    assert_visit_unit_identity(pool)


def test_closing_a_pool_freezes_its_counters_and_blocks_further_scheduling(api):
    """PRD §3.3: "Closing writes `status` `CLOSED` and the reason, bumps `version`,
    and touches none of the four counters, so the identity continues to hold on a
    closed pool."
    PRD §3.3: "A billing specialist closes an `ACTIVE`, `EXHAUSTED` or `EXPIRED` pool
    with a `close_reason` of `PAYER_TERMINATED` or `EPISODE_COMPLETE`, and the
    discharge cascade closes pools with the third value, `PATIENT_DISCHARGED`."
    PRD §2.7 rung 14: "the authorization named at plan activation, or carried by a
    session, has `status` `ACTIVE` or `EXHAUSTED`"

    Design: Corner/endpoints/authorization_close_is_outside_the_write_gate_and_freezes_the_pool
    """
    scn = setup_active_plan()
    schedule_session(scn)

    closed = validate_success(
        api.close_authorization(
            scn["auth"], {"close_reason": "EPISODE_COMPLETE"}, scn["hdr_biller"]
        ),
        200,
    )
    assert closed["status"] == "CLOSED"
    assert closed["close_reason"] == "EPISODE_COMPLETE"
    assert closed["visits_authorized"] == 12
    assert closed["visits_consumed"] == 1
    assert closed["visits_released"] == 0
    assert closed["visits_remaining"] == 11
    assert_visit_unit_identity(closed)

    blocked = api.create_session(
        scn["plan"],
        {
            "therapist_id": scn["od2"],
            "room_id": scn["room_b"],
            "scheduled_start_at": "2026-06-11T09:00:00Z",
            "scheduled_end_at": "2026-06-11T10:00:00Z",
            "procedure_code": "TIMED_THERAPEUTIC_ACTIVITY",
            "expected_authorization_version": closed["version"],
        },
        scn["hdr_front"],
    )
    validate_error(blocked, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_reauthorization_refuses_a_reassessment_older_than_the_look_back(api):
    """PRD §3.3: "It takes `additional_visits`, a `new_window_end_date`, and a
    `reassessment_id` that must name a `SIGNED` battery of `assessment_type`
    `REASSESSMENT` belonging to the same patient, signed no earlier than thirty days
    before the current clock reading; a citation older than that, or one that names
    anything other than a signed reassessment for that patient, is refused with
    `ERR_REAUTH_REASSESSMENT_STALE`."
    PRD §3.3: "On success, `visits_authorized` and `visits_remaining` each rise by
    `additional_visits`, so the identity survives the refill untouched;
    `window_end_date` is rewritten to `new_window_end_date`; `reauthorization_count`
    increments by 1; `last_reauthorized_at` is stamped with the clock; the pool's
    `status` becomes `ACTIVE`; and the pool's `version` is bumped."

    Design: Corner/validations/reauthorization_look_back_rejects_a_stale_reassessment
    """
    scn = setup_active_plan()
    stale = build_signed_reassessment(
        scn["pt"], scn["plan"], scn["od1"], scn["od2"], encounter_date="2026-06-01"
    )
    set_clock("2026-07-15T00:00:00Z")
    fresh = build_signed_reassessment(
        scn["pt"], scn["plan"], scn["od1"], scn["od2"], encounter_date="2026-07-15"
    )

    refused = api.reauthorize(
        scn["auth"],
        {
            "additional_visits": 6,
            "new_window_end_date": "2027-03-01",
            "reassessment_id": stale["id"],
        },
        scn["hdr_biller"],
    )
    validate_error(refused, ApiErrorId.ERR_REAUTH_REASSESSMENT_STALE.value, 422)

    refilled = validate_success(
        api.reauthorize(
            scn["auth"],
            {
                "additional_visits": 6,
                "new_window_end_date": "2027-03-01",
                "reassessment_id": fresh["id"],
            },
            scn["hdr_biller"],
        ),
        200,
    )
    assert refilled["visits_authorized"] == 18
    assert refilled["visits_remaining"] == 18
    assert refilled["reauthorization_count"] == 1
    assert refilled["status"] == "ACTIVE"
    assert_visit_unit_identity(refilled)


# --------------------------------------------------------------------------
# Progress scoring
# --------------------------------------------------------------------------


def _reference_progress_scenario(diagnosis="CONVERGENCE_INSUFFICIENCY"):
    """A signed EVALUATION with the reference baselines plus a DRAFT reassessment."""
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01", diagnosis_category=diagnosis)
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    evaluation = build_signed_evaluation(
        patient["id"],
        optometrist["id"],
        measurements=[
            npc_measurement_payload(12.0, 16.0),
            amplitude_measurement_payload(8.0),
            vergence_measurement_payload(8.0),
            symptom_measurement_payload(34),
        ],
    )
    plan = get_success_data(
        _client.create_therapy_plan(
            create_plan_payload(patient["id"], evaluation["id"]),
            make_optometrist_headers(optometrist["id"]),
        )
    )
    reassessment = build_battery(
        patient["id"],
        optometrist["id"],
        measurements=[
            npc_measurement_payload(7.0, 9.0),
            amplitude_measurement_payload(11.0),
            vergence_measurement_payload(14.0),
            symptom_measurement_payload(20),
        ],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=plan["id"],
    )
    return patient, optometrist, plan, reassessment


def test_composite_score_weights_four_components_for_convergence_insufficiency(api):
    """PRD §3.7: "`CONVERGENCE_INSUFFICIENCY` weights them 0.40, 0.15, 0.25 and 0.20
    respectively"
    PRD §3.7: "The weighted terms are summed without any intermediate rounding, and
    the sum is rounded half-up to two decimal places once, producing
    `composite_progress_score` on a scale of `0.00` to `100.00`."
    PRD §3.7: "The same battery genuinely scores differently under different diagnoses
    — a reference set of readings scoring 59.31 under `CONVERGENCE_INSUFFICIENCY`
    scores 60.02 under `ACCOMMODATIVE_DYSFUNCTION`, and 59.09 under `AMBLYOPIA` when
    acuity is included in place of amplitude and vergence."
    PRD §3.7: "Otherwise it is the baseline less the current `ciss_score`, divided by
    the baseline, multiplied by 100, clamped to lie between 0 and 100, and rounded
    half-up to two decimal places."

    Design: Difficulty/combinatorial_formula/composite_score_nonlinear_weighted_normalisation_mode_a
    """
    patient, optometrist, plan, reassessment = _reference_progress_scenario()

    assert plan["baseline_npc_break_cm"] == 12.0
    assert plan["baseline_amplitude_d"] == 8.0
    assert plan["baseline_vergence_bo_break_pd"] == 8.0
    assert plan["baseline_ciss_score"] == 34

    finalized = validate_success(
        api.finalize_assessment(
            reassessment["id"], make_optometrist_headers(optometrist["id"])
        ),
        200,
    )

    assert_pct(finalized["symptom_improvement_pct"], 41.18, "symptom_improvement_pct")
    assert_pct(finalized["composite_progress_score"], 59.31, "composite_progress_score")


def test_the_first_reassessment_has_a_null_delta_and_leaves_the_plan_on_track(api):
    """PRD §3.7: "When there is no such prior battery, `improvement_delta_points` is
    null."
    PRD §3.7: "When `improvement_delta_points` is not null and is strictly below 5.0
    points, the plan's `consecutive_low_delta_count` increments by 1; in every other
    case — including the case where there is no prior and the delta is null — it is
    reset to 0."
    PRD §3.7: "`plateau_flag` on the reassessment is true exactly when
    `consecutive_low_delta_count` has reached 2 or more, meaning two consecutive
    reassessments have each failed to gain five points."

    Design: Difficulty/combinatorial_formula/composite_score_nonlinear_weighted_normalisation_mode_a
    """
    patient, optometrist, plan, reassessment = _reference_progress_scenario()

    finalized = validate_success(
        api.finalize_assessment(
            reassessment["id"], make_optometrist_headers(optometrist["id"])
        ),
        200,
    )

    assert finalized["improvement_delta_points"] is None
    assert finalized["plateau_flag"] is False

    stored_plan = read_plan(plan["id"])
    assert stored_plan["consecutive_low_delta_count"] == 0
    assert stored_plan["progress_state"] == "ON_TRACK"


def test_the_amblyopia_arm_scores_acuity_in_place_of_amplitude_and_vergence(api):
    """PRD §3.7: "For a patient whose `diagnosis_category` is `AMBLYOPIA`, the score
    is three terms — 0.55 times the acuity component, plus 0.25 times the near-point
    component, plus 0.20 times the symptom component — and the amplitude and vergence
    components are not used at all."
    PRD §3.7: "The acuity component measures reduction toward a fixed goal of 0.10
    logMAR. It is the plan's `baseline_acuity_logmar` less the current
    `acuity_logmar`, divided by that baseline less 0.10, with the divisor floored at
    0.01 — a tighter floor than the others, because logMAR moves in much smaller
    numbers — then multiplied by 100 and clamped between 0 and 100."
    PRD §3.7: "Under `GOAL` the service looks only at goal evidence: it finds the
    battery on this plan whose `assessment_type` is `REASSESSMENT` and whose `status`
    is `SIGNED`, again by greatest `signed_at` with `created_at` as tie-break, and
    `discharge_ready` is true when such a battery exists, its
    `composite_progress_score` is at least 80.0, and its `symptom_improvement_pct` is
    at least 50.0."

    Design: Corner/calculations/composite_score_uses_the_acuity_variant_for_amblyopia
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01", diagnosis_category="AMBLYOPIA")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    evaluation = build_signed_evaluation(
        patient["id"],
        optometrist["id"],
        measurements=[
            npc_measurement_payload(12.0, 16.0),
            acuity_measurement_payload(0.30),
            symptom_measurement_payload(34),
        ],
    )
    plan = get_success_data(
        _client.create_therapy_plan(
            create_plan_payload(
                patient["id"], evaluation["id"], discharge_criteria_mode="GOAL"
            ),
            make_optometrist_headers(optometrist["id"]),
        )
    )
    reassessment = build_battery(
        patient["id"],
        optometrist["id"],
        measurements=[
            npc_measurement_payload(7.0, 9.0),
            acuity_measurement_payload(0.18),
            symptom_measurement_payload(20),
        ],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=plan["id"],
    )

    finalized = validate_success(
        api.finalize_assessment(
            reassessment["id"], make_optometrist_headers(optometrist["id"])
        ),
        200,
    )

    assert_pct(finalized["symptom_improvement_pct"], 41.18, "symptom_improvement_pct")
    assert_pct(finalized["composite_progress_score"], 59.09, "composite_progress_score")
    assert read_plan(plan["id"])["discharge_ready"] is False


def test_two_consecutive_low_delta_reassessments_move_the_plan_to_plateau(api):
    """PRD §3.7: "Otherwise it is this reassessment's `composite_progress_score` less
    the prior one's, rounded half-up to two decimal places."
    PRD §3.7: "When `improvement_delta_points` is not null and is strictly below 5.0
    points, the plan's `consecutive_low_delta_count` increments by 1; in every other
    case — including the case where there is no prior and the delta is null — it is
    reset to 0."
    PRD §3.7: "From `ON_TRACK`, a reassessment whose `plateau_flag` is true moves the
    plan `ON_TRACK → PLATEAU`."
    PRD §3.7: "When a reassessment is finalized with a `composite_progress_score`
    strictly below 40.0 points and the plan's `current_phase_index` is greater than 1,
    and the phase one step below the current index is in `status` `MASTERED`, the
    phase at the current index moves back to `LOCKED` with its `started_at` cleared to
    null, the phase one step below moves `MASTERED → IN_PROGRESS` with `mastered_at`
    cleared to null and `started_at` re-stamped from the clock, and the plan's
    `current_phase_index` decreases by 1."

    Design: Corner/calculations/plateau_after_two_consecutive_low_delta_reassessments
    """
    scn = setup_active_plan()

    scores = []
    for _ in range(2):
        battery = build_battery(
            scn["pt"],
            scn["od1"],
            measurements=[npc_measurement_payload(7.0, 9.0)],
            finalize_it=True,
            assessment_type="REASSESSMENT",
            purpose="PROGRESS",
            encounter_date="2026-06-01",
            plan_id=scn["plan"],
        )
        scores.append(battery)
        get_success_data(api.sign_assessment(battery["id"], scn["hdr_od2"]))

    assert_pct(scores[0]["composite_progress_score"], 28.57, "first score")
    assert scores[0]["improvement_delta_points"] is None
    assert scores[0]["plateau_flag"] is False
    assert_pct(scores[1]["composite_progress_score"], 28.57, "second score")
    assert_pct(scores[1]["improvement_delta_points"], 0.00, "second delta")
    assert scores[1]["plateau_flag"] is False

    third = build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[npc_measurement_payload(7.0, 9.0)],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )
    finalized = validate_success(
        api.finalize_assessment(third["id"], scn["hdr_od1"]), 200
    )

    assert_pct(finalized["composite_progress_score"], 28.57, "third score")
    assert_pct(finalized["improvement_delta_points"], 0.00, "third delta")
    assert finalized["plateau_flag"] is True

    plan = read_plan(scn["plan"])
    assert plan["consecutive_low_delta_count"] == 2
    assert plan["progress_state"] == "PLATEAU"
    assert plan["current_phase_index"] == 1
