"""Therapy-plan creation, the revision cycle, and the phase ladder in both directions."""

from test_helpers import (
    advance_phase,
    assert_pct,
    build_battery,
    build_signed_evaluation,
    create_plan_payload,
    get_success_data,
    log_and_attest_home_sessions,
    make_optometrist_headers,
    new_patient,
    new_therapist,
    npc_measurement_payload,
    read_phase,
    read_plan,
    record_mastery,
    set_clock,
    setup_active_plan,
    symptom_measurement_payload,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as _client

WINDOW_ATTESTATIONS = [
    "2026-05-20T10:00:00Z",
    "2026-05-25T10:00:00Z",
    "2026-05-29T10:00:00Z",
]


def test_plan_snapshots_its_baselines_and_leaves_absent_metrics_null(api):
    """PRD §3.4: "Creation snapshots the plan's five baselines from the source
    battery's readings, and those baselines are what every later progress percentage
    is measured against: `baseline_npc_break_cm` from the near-point break,
    `baseline_amplitude_d` from the accommodative amplitude,
    `baseline_vergence_bo_break_pd` from the base-out vergence break,
    `baseline_acuity_logmar` from the best-corrected acuity, and `baseline_ciss_score`
    from the symptom survey."
    PRD §3.4: "Any baseline whose metric has no row on the source battery is null, and
    a null baseline is not an error — it simply makes that metric contribute nothing
    later."
    PRD §3.4: "A new plan opens in `status` `DRAFT` with `authorization_id` null,
    `current_phase_index` 1, `revision_count` 0, `consecutive_low_delta_count` 0,
    `cumulative_therapy_minutes` 0.0, `home_compliance_pct` `0.00`, `discharge_ready`
    false, `suspension_reason` null,
    `previous_prescribed_home_sessions_per_week` null and `prescription_changed_at`
    null."

    Design: Corner/entities/plan_baselines_are_computed_from_the_source_assessment
    """
    set_clock("2026-06-01T00:00:00Z")
    patient = new_patient(date_of_birth="2016-06-01")
    optometrist = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    evaluation = build_signed_evaluation(
        patient["id"],
        optometrist["id"],
        measurements=[
            npc_measurement_payload(12.0, 16.0),
            symptom_measurement_payload(34),
        ],
    )

    data = validate_success(
        api.create_therapy_plan(
            create_plan_payload(
                patient["id"],
                evaluation["id"],
                discharge_criteria_mode="GOAL",
                prescribed_home_sessions_per_week=2,
            ),
            make_optometrist_headers(optometrist["id"]),
        ),
        201,
    )

    assert data["baseline_npc_break_cm"] == 12.0
    assert data["baseline_ciss_score"] == 34
    assert data["baseline_vergence_bo_break_pd"] is None
    assert data["baseline_acuity_logmar"] is None
    assert data["status"] == "DRAFT"
    assert data["progress_state"] == "ON_TRACK"
    assert data["authorization_id"] is None
    assert data["current_phase_index"] == 1
    assert data["revision_count"] == 0
    assert data["discharge_ready"] is False
    assert data["suspension_reason"] is None
    assert data["previous_prescribed_home_sessions_per_week"] is None
    assert data["prescription_changed_at"] is None


def test_revision_supersedes_the_prescription_and_reactivation_closes_the_cycle(api):
    """PRD §3.4: "The plan moves to `UNDER_REVISION`, `revision_count` increments by
    1, and `version` is bumped."
    PRD §3.4: "When the call also supplies a new `prescribed_home_sessions_per_week`,
    the old figure is copied into `previous_prescribed_home_sessions_per_week`, the
    new figure replaces it, and `prescription_changed_at` is stamped with the clock;
    when it does not, all three of those fields are left exactly as they were."
    PRD §3.4: "Activating a plan that is in `UNDER_REVISION` instead moves it
    `UNDER_REVISION → ACTIVE`, rebinds `authorization_id` to the supplied pool, and
    additionally resets `progress_state` from `REVISION_PENDING` back to `ON_TRACK`
    when it was sitting at `REVISION_PENDING`; it does not disturb the phase ladder."

    Design: Corner/state_machines/plan_revision_cycle_active_under_revision_active
    """
    scn = setup_active_plan()

    revised = validate_success(
        api.revise_plan(
            scn["plan"],
            {
                "expected_plan_version": scn["plan_v"],
                "revision_reason": "Add anti-suppression work",
                "prescribed_home_sessions_per_week": 2,
            },
            scn["hdr_od1"],
        ),
        200,
    )
    assert revised["status"] == "UNDER_REVISION"
    assert revised["revision_count"] == 1
    assert revised["prescription_changed_at"] is not None
    assert revised["previous_prescribed_home_sessions_per_week"] == 1
    assert revised["prescribed_home_sessions_per_week"] == 2

    reactivated = validate_success(
        api.activate_plan(scn["plan"], {"authorization_id": scn["auth"]}, scn["hdr_od1"]),
        200,
    )
    assert reactivated["status"] == "ACTIVE"
    assert reactivated["progress_state"] == "ON_TRACK"
    assert reactivated["current_phase_index"] == 1
    assert reactivated["previous_prescribed_home_sessions_per_week"] == 1


def test_plan_phase_list_is_returned_in_ascending_sequence_index(api):
    """PRD §2.3: "The one exception in this service is the per-plan phase list, which
    is returned sorted by `sequence_index` ascending."
    PRD §3.4: "Every phase is created in `status` `LOCKED` with
    `activities_mastered_count` 0 and both `started_at` and `mastered_at` null."
    PRD §3.4: "Activating a plan that is in `DRAFT` requires at least one phase with
    `sequence_index` 1 to exist, moves the plan `DRAFT → ACTIVE`, binds
    `authorization_id`, sets `current_phase_index` to 1, moves that first phase
    `LOCKED → IN_PROGRESS` with `started_at` stamped from the clock, and bumps both
    the plan's and the phase's `version`."

    Design: Corner/endpoints/plan_phases_subresource_returns_children_in_sequence_order
    """
    scn = setup_active_plan()

    rows, meta = validate_paginated(
        api.list_phases(scn["plan"], scn["hdr_od1"], {"limit": 10, "offset": 0})
    )

    assert len(rows) == 2 and meta["total_count"] == 2
    assert rows[0]["sequence_index"] == 1
    assert rows[0]["id"] == scn["ph1"]
    assert rows[0]["status"] == "IN_PROGRESS"
    assert rows[1]["sequence_index"] == 2
    assert rows[1]["id"] == scn["ph2"]
    assert rows[1]["status"] == "LOCKED"


def _plan_advanced_to_phase_two():
    scn = setup_active_plan()
    log_and_attest_home_sessions(scn, WINDOW_ATTESTATIONS)
    record_mastery(scn, scn["ph1"], 2)
    advanced = advance_phase(scn)
    assert advanced["current_phase_index"] == 2, "Setup step failed: plan did not advance"
    return scn


def test_a_low_scoring_reassessment_walks_the_phase_ladder_backwards(api):
    """PRD §3.7: "When a reassessment is finalized with a `composite_progress_score`
    strictly below 40.0 points and the plan's `current_phase_index` is greater than 1,
    and the phase one step below the current index is in `status` `MASTERED`, the
    phase at the current index moves back to `LOCKED` with its `started_at` cleared to
    null, the phase one step below moves `MASTERED → IN_PROGRESS` with `mastered_at`
    cleared to null and `started_at` re-stamped from the clock, and the plan's
    `current_phase_index` decreases by 1."
    PRD §3.7: "The near-point component measures how far the break distance has closed
    toward its discharge target. It is the plan's `baseline_npc_break_cm` less the
    current `npc_break_cm`, divided by the plan's `baseline_npc_break_cm` less 5.0
    centimetres — the discharge break target — with that divisor floored at 0.1 so it
    can never be zero or negative, then multiplied by 100 and clamped between 0 and
    100."

    Design: Difficulty/non_linear_state_machine/plan_phase_regression_mastered_back_to_in_progress
    """
    scn = _plan_advanced_to_phase_two()
    reassessment = build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[npc_measurement_payload(12.0, 16.0)],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )

    finalized = validate_success(
        api.finalize_assessment(reassessment["id"], scn["hdr_od1"]), 200
    )

    assert_pct(finalized["composite_progress_score"], 0.00, "composite_progress_score")
    assert read_plan(scn["plan"])["current_phase_index"] == 1


def test_phase_regression_relocks_the_phase_it_left_and_reopens_the_one_below(api):
    """PRD §3.7: "the phase at the current index moves back to `LOCKED` with its
    `started_at` cleared to null, the phase one step below moves
    `MASTERED → IN_PROGRESS` with `mastered_at` cleared to null and `started_at`
    re-stamped from the clock, and the plan's `current_phase_index` decreases by 1."
    PRD §3.7: "Both phase rows have their `version` bumped. This is the closing edge
    of the phase cycle `IN_PROGRESS → MASTERED → IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/plan_phase_regression_mastered_back_to_in_progress
    """
    scn = _plan_advanced_to_phase_two()
    assert read_phase(scn["plan"], scn["ph1"])["status"] == "MASTERED"
    assert read_phase(scn["plan"], scn["ph2"])["status"] == "IN_PROGRESS"

    reassessment = build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[npc_measurement_payload(12.0, 16.0)],
        finalize_it=False,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )
    validate_success(api.finalize_assessment(reassessment["id"], scn["hdr_od1"]), 200)

    phase_one = read_phase(scn["plan"], scn["ph1"])
    phase_two = read_phase(scn["plan"], scn["ph2"])
    assert phase_one["status"] == "IN_PROGRESS"
    assert phase_one["mastered_at"] is None
    assert phase_one["started_at"] is not None
    assert phase_two["status"] == "LOCKED"
    assert phase_two["started_at"] is None
