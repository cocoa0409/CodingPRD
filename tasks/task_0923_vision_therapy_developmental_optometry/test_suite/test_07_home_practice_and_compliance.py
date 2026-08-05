"""Home practice, the trailing compliance window, and the three phase-advance gates."""

from test_helpers import (
    ApiErrorId,
    amplitude_measurement_payload,
    assert_minutes,
    assert_pct,
    attest_home_session,
    build_battery,
    check_in,
    complete_session,
    get_success_data,
    log_and_attest_home_sessions,
    log_home_session,
    npc_measurement_payload,
    read_authorization,
    read_phase,
    read_plan,
    record_mastery,
    schedule_session,
    setup_active_plan,
    symptom_measurement_payload,
    validate_error,
    validate_success,
    vergence_measurement_payload,
)

WINDOW_ATTESTATIONS = [
    "2026-05-20T10:00:00Z",
    "2026-05-25T10:00:00Z",
    "2026-05-29T10:00:00Z",
]


def _plan_ready_to_advance_with_raised_prescription(api, scn):
    """Three attested home sessions, phase 1 mastered, prescription raised 1 -> 4."""
    log_and_attest_home_sessions(scn, WINDOW_ATTESTATIONS)
    record_mastery(scn, scn["ph1"], 2)
    before = read_plan(scn["plan"])
    revised = validate_success(
        api.revise_plan(
            scn["plan"],
            {
                "expected_plan_version": before["version"],
                "revision_reason": "Increase home dosage",
                "prescribed_home_sessions_per_week": 4,
            },
            scn["hdr_od1"],
        ),
        200,
    )
    get_success_data(
        api.activate_plan(scn["plan"], {"authorization_id": scn["auth"]}, scn["hdr_od1"])
    )
    return before, revised


def test_compliance_denominator_is_the_prescription_in_force_at_the_window_start(api):
    """PRD §3.6: "The denominator is the prescribed weekly figure multiplied by
    twenty-eight and divided by seven — four weeks of prescription — held as an exact
    unrounded quantity."
    PRD §3.6: "The rule is that the denominator is always the prescription that was in
    force at the *start* of the window, never the current one."
    PRD §3.6: "So when the plan's `prescription_changed_at` is not null and is later
    than the window start, the denominator uses
    `previous_prescribed_home_sessions_per_week`; in every other case — no
    prescription change has ever happened, or the change happened at or before the
    window start — it uses the current `prescribed_home_sessions_per_week`."

    Design: Difficulty/combinatorial_formula/compliance_denominator_pinned_to_window_start_prescription_mode_c
    """
    scn = setup_active_plan()
    before, revised = _plan_ready_to_advance_with_raised_prescription(api, scn)

    assert_pct(before["home_compliance_pct"], 75.00, "home_compliance_pct before revision")
    assert revised["previous_prescribed_home_sessions_per_week"] == 1
    assert revised["prescribed_home_sessions_per_week"] == 4

    advanced = validate_success(api.advance_phase(scn["plan"], scn["hdr_od1"]), 200)

    assert_pct(advanced["home_compliance_pct"], 75.00, "home_compliance_pct at advance")
    assert advanced["home_compliance_pct"] != 18.75


def test_the_advance_succeeds_once_the_pinned_denominator_clears_the_threshold(api):
    """PRD §3.6: "**Third, home compliance.** The plan's `home_compliance_pct`,
    recomputed right then, must be at least 75.00, or the advance is refused with
    `ERR_COMPLIANCE_BELOW_THRESHOLD`; exactly 75.00 passes."
    PRD §3.6: "When all three gates pass, the phase currently `IN_PROGRESS` moves
    `IN_PROGRESS → MASTERED` with `mastered_at` stamped from the clock. If a phase
    with the next `sequence_index` exists, it moves `LOCKED → IN_PROGRESS` with
    `started_at` stamped, and the plan's `current_phase_index` is set to that phase's
    `sequence_index`; both phase rows and the plan have their `version` bumped."

    Design: Difficulty/combinatorial_formula/compliance_denominator_pinned_to_window_start_prescription_mode_c
    """
    scn = setup_active_plan()
    _plan_ready_to_advance_with_raised_prescription(api, scn)

    advanced = validate_success(api.advance_phase(scn["plan"], scn["hdr_od1"]), 200)

    assert advanced["current_phase_index"] == 2
    assert advanced["status"] == "ACTIVE"
    assert read_phase(scn["plan"], scn["ph1"])["status"] == "MASTERED"
    assert read_phase(scn["plan"], scn["ph2"])["status"] == "IN_PROGRESS"


def test_a_home_session_enters_the_axis_at_logged_and_never_draws_a_unit(api):
    """PRD §3.6: "The row is created with `modality` `HOME`, `procedure_code`
    `HOME_PRACTICE`, `schedule_status` `LOGGED` and `billing_status` `NON_BILLABLE`,
    and with `therapist_id`, `room_id`, `authorization_id`, `scheduled_start_at` and
    `scheduled_end_at` all null."
    PRD §3.6: "A home session enters the scheduling axis at `LOGGED` and never at
    `SCHEDULED`, never consumes an authorization unit, and is never billable."
    PRD §3.6: "A session's `weighted_minutes` is its `timed_minutes` outright when the
    `modality` is `IN_OFFICE`, and is its `timed_minutes` multiplied by a home
    weighting of 0.5 — half credit, rounded half-up to one decimal place — when the
    `modality` is `HOME`."
    PRD §3.6: "The plan's `cumulative_therapy_minutes` is the sum of
    `weighted_minutes` over every session on the plan whose `schedule_status` is
    `COMPLETED` or `ATTESTED`; sessions sitting at `SCHEDULED`, `CHECKED_IN`,
    `LOGGED`, `CANCELLED` or `NO_SHOW` contribute nothing, which means a home session
    that is logged but never attested adds no minutes at all."

    Design: Corner/state_machines/home_session_enters_the_axis_at_logged_and_is_never_billable
    """
    scn = setup_active_plan()

    data = validate_success(
        api.create_home_session(
            scn["plan"],
            {
                "performed_at": "2026-05-28T18:00:00Z",
                "timed_minutes": 20,
                "activity_notes": "Brock string, 4 sets",
            },
            scn["hdr_patient"],
        ),
        201,
    )

    assert data["schedule_status"] == "LOGGED"
    assert data["modality"] == "HOME"
    assert data["procedure_code"] == "HOME_PRACTICE"
    assert data["billing_status"] == "NON_BILLABLE"
    assert_minutes(data["weighted_minutes"], 10.0, "weighted_minutes")
    assert data["authorization_id"] is None

    pool = read_authorization(scn["auth"])
    assert pool["visits_consumed"] == 0 and pool["visits_remaining"] == 12
    assert_minutes(
        read_plan(scn["plan"])["cumulative_therapy_minutes"], 0.0, "cumulative_therapy_minutes"
    )


def test_cumulative_minutes_counts_only_completed_and_attested_rows(api):
    """PRD §3.6: "The plan's `cumulative_therapy_minutes` is the sum of
    `weighted_minutes` over every session on the plan whose `schedule_status` is
    `COMPLETED` or `ATTESTED`; sessions sitting at `SCHEDULED`, `CHECKED_IN`,
    `LOGGED`, `CANCELLED` or `NO_SHOW` contribute nothing, which means a home session
    that is logged but never attested adds no minutes at all."
    PRD §3.6: "Attestation is again a `PatientUser` operation, requires `X-User-ID` to
    equal the session's `patient_id`, takes a free-text `attestation_statement`, and
    moves the session `LOGGED → ATTESTED` with `attested_at` stamped from the clock
    and the session's `version` bumped."

    Design: Corner/calculations/cumulative_minutes_counts_only_completed_and_attested_rows
    """
    scn = setup_active_plan()
    in_office = schedule_session(scn, therapist_id=scn["cvt1"], room_id=scn["room_a"])
    cancelled = schedule_session(
        scn,
        therapist_id=scn["cvt1"],
        room_id=scn["room_a"],
        scheduled_start_at="2026-06-11T09:00:00Z",
        scheduled_end_at="2026-06-11T10:00:00Z",
    )
    check_in(scn, in_office["id"])
    complete_session(scn, in_office["id"], "2026-06-10T09:40:00Z", 40)
    get_success_data(
        api.cancel_session(
            cancelled["id"], {"cancel_reason": "PATIENT_REQUEST"}, scn["hdr_front"]
        )
    )
    first_home = log_home_session(scn, "2026-05-26T18:00:00Z", 30)
    second_home = log_home_session(scn, "2026-05-27T18:00:00Z", 30)

    attest_home_session(scn, first_home["id"], "Done")

    assert_minutes(
        read_plan(scn["plan"])["cumulative_therapy_minutes"],
        55.0,
        "cumulative_therapy_minutes",
    )
    assert (
        validate_success(api.get_session(second_home["id"], scn["hdr_front"]), 200)[
            "schedule_status"
        ]
        == "LOGGED"
    )
    assert (
        validate_success(api.get_session(cancelled["id"], scn["hdr_front"]), 200)[
            "schedule_status"
        ]
        == "CANCELLED"
    )


def test_the_mastery_gate_is_evaluated_before_the_compliance_gate(api):
    """PRD §3.6: "Advancing the ladder is an optometrist's or a vision therapist's
    operation on an `ACTIVE` plan, and it is gated by three checks evaluated in this
    order."
    PRD §3.6: "**Second, activity mastery.** The phase currently `IN_PROGRESS` must
    have an `activities_mastered_count` at least equal to its own
    `required_mastery_count`, or the advance is refused with `ERR_MASTERY_NOT_MET`."
    PRD §3.6: "**Third, home compliance.** The plan's `home_compliance_pct`,
    recomputed right then, must be at least 75.00, or the advance is refused with
    `ERR_COMPLIANCE_BELOW_THRESHOLD`; exactly 75.00 passes."
    PRD §3.4: "An optometrist, a vision therapist or an assistant supplies a
    non-negative `mastered_delta`, which is added to that phase's
    `activities_mastered_count` and bumps the phase's `version`"

    Design: Corner/validations/mastery_rung_pre_empts_the_compliance_rung_on_advance_phase
    """
    scn = setup_active_plan()

    both_failing = api.advance_phase(scn["plan"], scn["hdr_od1"])
    validate_error(both_failing, ApiErrorId.ERR_MASTERY_NOT_MET.value, 422)

    mastered = record_mastery(scn, scn["ph1"], 2)
    assert mastered["activities_mastered_count"] == 2

    compliance_failing = api.advance_phase(scn["plan"], scn["hdr_od1"])
    validate_error(compliance_failing, ApiErrorId.ERR_COMPLIANCE_BELOW_THRESHOLD.value, 422)

    assert read_plan(scn["plan"])["current_phase_index"] == 1
    assert read_phase(scn["plan"], scn["ph1"])["status"] == "IN_PROGRESS"


def test_entering_phase_three_requires_a_recent_signed_reassessment(api):
    """PRD §3.6: "**First, reassessment currency.** When the phase about to be entered
    has a `sequence_index` of 3 or higher, the plan must hold a `SIGNED` battery of
    `assessment_type` `REASSESSMENT` whose `signed_at` is at or after the instant
    twenty-one days before the current clock reading; if it does not, the advance is
    refused with `ERR_REASSESSMENT_REQUIRED`."
    PRD §3.6: "Advancing into phase 1 or phase 2 carries no such requirement."

    Design: Corner/validations/advancing_into_phase_three_requires_a_recent_signed_reassessment
    """
    scn = setup_active_plan(phase_count=3)
    log_and_attest_home_sessions(scn, WINDOW_ATTESTATIONS)
    record_mastery(scn, scn["ph1"], 2)
    advanced = validate_success(api.advance_phase(scn["plan"], scn["hdr_od1"]), 200)
    assert advanced["current_phase_index"] == 2
    record_mastery(scn, scn["ph2"], 2)

    refused = api.advance_phase(scn["plan"], scn["hdr_od1"])
    validate_error(refused, ApiErrorId.ERR_REASSESSMENT_REQUIRED.value, 422)

    reassessment = build_battery(
        scn["pt"],
        scn["od1"],
        measurements=[
            npc_measurement_payload(7.0, 9.0),
            amplitude_measurement_payload(11.0),
            vergence_measurement_payload(14.0),
            symptom_measurement_payload(20),
        ],
        finalize_it=True,
        assessment_type="REASSESSMENT",
        purpose="PROGRESS",
        encounter_date="2026-06-01",
        plan_id=scn["plan"],
    )
    assert_pct(reassessment["composite_progress_score"], 59.31, "composite_progress_score")
    get_success_data(api.sign_assessment(reassessment["id"], scn["hdr_od2"]))

    accepted = validate_success(api.advance_phase(scn["plan"], scn["hdr_od1"]), 200)

    assert accepted["current_phase_index"] == 3
    assert read_phase(scn["plan"], scn["ph2"])["status"] == "MASTERED"
    assert read_phase(scn["plan"], scn["ph3"])["status"] == "IN_PROGRESS"
