"""
State-machine behaviour of the Concussion Protocol & Return-to-Play API.

Every test here exercises one lifecycle edge of one resource type: the game
lifecycle, the sideline evaluation's eight statuses, the return step, the
consultant clearance, the protocol audit, the baseline test, and the three
independent dimensions carried on a concussion case (`case_status`,
`monitoring_status`, `roster_exemption_status`).  Initial states, permitted
transitions, refused transitions, terminal lockdown, second-write idempotency
and the declared side-effect sets are all asserted against the PRD.

The API server is restarted before every test, so each test builds the whole
protocol chain it needs and moves the logical clock explicitly.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED,
    ERR_AUDIT_STATE_INVALID,
    ERR_CASE_STATE_INVALID,
    ERR_CLEARANCE_STATE_INVALID,
    ERR_EVALUATION_STATE_INVALID,
    ERR_LOCKER_ROOM_EXAM_TOO_SHORT,
    ERR_MANDATORY_REMOVAL_ENFORCED,
    ERR_NO_GO_SIGNS_PRESENT,
    ERR_RESOURCE_STATE_INVALID,
    ERR_SAME_GAME_RETURN_PROHIBITED,
    ERR_STEP_STATE_INVALID,
)
from test_helpers.test_users import ADMIN, make_compliance_officer_headers


# ─── Game lifecycle ──────────────────────────────────────────────────────────

def test_game_advances_scheduled_to_in_progress_to_final(api):
    """A game walks SCHEDULED to IN_PROGRESS to FINAL, one advance at a time.

    PRD: "A `LeagueAdmin` walks it forward one step at a time by supplying a `to_status`: `SCHEDULED` becomes `IN_PROGRESS`, and `IN_PROGRESS` becomes `FINAL`, each advance incrementing the game's `version` by 1."

    Design: Corner/state_machines/game_advances_scheduled_to_in_progress_to_final
    """
    # Arrange: two clubs and a week-1 game scheduled for 2026-09-13T17:00:00Z.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    game = fx.create_game(api, club_h["id"], club_r["id"])
    assert game["status"] == "SCHEDULED"
    assert game["version"] == 1

    # Act 1: kickoff reached, the first advance takes the game live.
    fx.set_clock(api, fx.KICKOFF_AT)
    live = validate_success(
        api.advance_game_status(game["id"], f.advance_status_payload("IN_PROGRESS"), ADMIN)
    )

    # Assert: status and the clock-stamped updated_at, version advanced once.
    assert live["status"] == "IN_PROGRESS"
    a.assert_instant(live["updated_at"], "2026-09-13T17:00:00.000Z")
    assert live["version"] == 2

    # Act 2: three hours later the second advance closes the game out.
    fx.set_clock(api, "2026-09-13T20:00:00Z")
    final = validate_success(
        api.advance_game_status(game["id"], f.advance_status_payload("FINAL"), ADMIN)
    )

    # Assert: FINAL, freshly stamped updated_at and a third version.
    assert final["status"] == "FINAL"
    a.assert_instant(final["updated_at"], "2026-09-13T20:00:00.000Z")
    assert final["version"] == 3

    reread = fx.read_game(api, game["id"])
    assert reread["status"] == "FINAL"
    assert reread["version"] == 3


def test_game_advance_from_final_is_rejected(api):
    """FINAL is terminal, so a further advance is refused and the game stays FINAL.

    PRD: "Skipping straight from `SCHEDULED` to `FINAL` is rejected with `ERR_RESOURCE_STATE_INVALID`, as is any advance whose declared from-state does not match reality."

    Design: Corner/state_machines/game_advance_from_final_rejected
    """
    # Arrange: a game already walked all the way to FINAL.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club_h = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    club_r = fx.create_club(api, "Ridgeway Sentinels", "RWS", 3)
    game = fx.create_game(api, club_h["id"], club_r["id"])
    fx.set_clock(api, fx.KICKOFF_AT)
    fx.advance_game(api, game["id"], "IN_PROGRESS")
    fx.set_clock(api, "2026-09-13T20:00:00Z")
    fx.advance_game(api, game["id"], "FINAL")

    # Act: try to walk the finished game back to IN_PROGRESS.
    response = api.advance_game_status(
        game["id"], f.advance_status_payload("IN_PROGRESS"), ADMIN
    )

    # Assert: refused on the resource from-state rung, and nothing moved.
    validate_error(response, ERR_RESOURCE_STATE_INVALID, expected_status=409)
    reread = fx.read_game(api, game["id"])
    assert reread["status"] == "FINAL"
    assert reread["version"] == 3


# ─── Sideline evaluation lifecycle ───────────────────────────────────────────

def test_evaluation_opens_in_initiated_with_stamped_protocol_deadline(api):
    """An observer-initiated evaluation opens INITIATED with a 15-minute deadline.

    PRD: "That single boolean sets the protocol clock: `protocol_deadline_at` falls 15 minutes after `initiated_at` when `mandatory_removal` is true, and 45 minutes after it otherwise."

    Design: Corner/state_machines/evaluation_initial_state_is_initiated_with_stamped_deadline
    """
    # Arrange: live week-1 game, baselined player, clock at 2026-09-13T18:05:00Z.
    ctx = fx.setup_live_game(api)
    fx.set_clock(api, fx.EVALUATION_INITIATED_AT)

    # Act: the unaffiliated observer exercises removal authority.
    response = api.create_sideline_evaluation(
        f.evaluation_payload(
            ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
        ),
        ctx["obs_headers"],
    )

    # Assert: the declared initial state and the derived removal clock.
    created = validate_success(response, expected_status=201)
    a.assert_common_fields(created, expected_version=1)
    assert created["status"] == "INITIATED"
    assert created["mandatory_removal"] is True
    assert created["diagnosis_outcome"] == "PENDING"
    assert created["no_go_signs"] == []
    a.assert_instant(created["initiated_at"], "2026-09-13T18:05:00.000Z")
    a.assert_instant(created["protocol_deadline_at"], "2026-09-13T18:20:00.000Z")
    assert created["initiating_clinician_id"] == ctx["obs_id"]
    a.assert_null(created, "evaluating_clinician_id", "screened_at", "screen_symptom_score")

    reread = fx.read_evaluation(api, created["id"])
    assert reread["status"] == "INITIATED"
    a.assert_instant(reread["protocol_deadline_at"], "2026-09-13T18:20:00.000Z")

    # The player is untouched: only a diagnosis or prolonged watch restricts a
    # player, and the PRD's player initial state is AVAILABLE with NONE.
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "AVAILABLE"
    assert player["public_injury_designation"] == "NONE"


def test_diagnose_without_locker_room_exam_is_rejected(api):
    """Diagnosis is reachable only from LOCKER_ROOM_EXAM, never from INITIATED.

    PRD: "`ERR_EVALUATION_STATE_INVALID` (409) for the five evaluation actions."

    Design: Corner/state_machines/diagnose_without_locker_room_exam_rejected
    """
    # Arrange: an observer-initiated evaluation that was never screened.
    ctx = fx.setup_live_game(api)
    fx.set_clock(api, fx.EVALUATION_INITIATED_AT)
    evaluation = get_success_data(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="UNAFFILIATED_OBSERVER"
            ),
            ctx["obs_headers"],
        )
    )

    # Act: try to document a diagnosis straight out of INITIATED.
    response = api.diagnose_concussion(
        evaluation["id"],
        f.diagnose_payload(symptom_score=9, composite_score=70),
        ctx["doc_h_headers"],
    )

    # Assert: refused, evaluation unmoved and no case brought into existence.
    validate_error(response, ERR_EVALUATION_STATE_INVALID, expected_status=409)
    assert fx.read_evaluation(api, evaluation["id"])["status"] == "INITIATED"
    cases, meta = validate_paginated(api.list_concussion_cases(ADMIN))
    assert cases == []
    a.assert_page_meta(meta, total_count=0)
    assert fx.read_player(api, ctx["player_id"])["diagnosed_case_count"] == 0


def test_diagnose_before_eight_exam_minutes_is_rejected_then_accepted_at_eight(api):
    """Seven whole exam minutes is too short; the eighth minute exactly is enough.

    PRD: "The server computes `exam_duration_minutes` as the whole number of minutes between `exam_started_at` and `exam_completed_at`, discarding any part-minute remainder, and no conclusion of any kind may be recorded until that figure is at least 8."

    Design: Corner/state_machines/diagnose_before_eight_exam_minutes_rejected
    """
    # Arrange: the examination under way since 2026-09-13T18:10:00Z.
    ctx = fx.setup_locker_room_exam(api)

    # Act 1: a diagnosis one second short of the eighth whole minute.
    fx.set_clock(api, "2026-09-13T18:17:59Z")
    too_soon = api.diagnose_concussion(
        ctx["eval_id"],
        f.diagnose_payload(symptom_score=9, composite_score=70),
        ctx["doc_h_headers"],
    )

    # Assert: refused, and the examination is still open.
    validate_error(too_soon, ERR_LOCKER_ROOM_EXAM_TOO_SHORT, expected_status=409)
    assert fx.read_evaluation(api, ctx["eval_id"])["status"] == "LOCKER_ROOM_EXAM"

    # Act 2: one second later the eighth whole minute has elapsed.
    fx.set_clock(api, "2026-09-13T18:18:00Z")
    accepted = api.diagnose_concussion(
        ctx["eval_id"],
        f.diagnose_payload(symptom_score=9, composite_score=70),
        ctx["doc_h_headers"],
    )

    # Assert: the case opens, stamped from the logical clock.
    case = validate_success(accepted, expected_status=201)
    a.assert_instant(case["diagnosis_at"], "2026-09-13T18:18:00.000Z")
    a.assert_case_progress(case, severity_index=82)
    a.assert_instant(case["projected_return_at"], "2026-09-23T18:18:00.000Z")
    evaluation = fx.read_evaluation(api, ctx["eval_id"])
    assert evaluation["status"] == "DIAGNOSED"
    assert evaluation["exam_duration_minutes"] == 8
    a.assert_instant(evaluation["exam_completed_at"], "2026-09-13T18:18:00.000Z")


def test_conclude_no_concussion_with_no_go_sign_is_rejected_but_inconclusive_succeeds(api):
    """A recorded no-go sign forecloses NO_CONCUSSION but not INCONCLUSIVE.

    PRD: "That branch additionally requires the `no_go_signs` list recorded at the screen to be empty: a screen that saw any no-go sign forbids a no-concussion conclusion outright, refused with `ERR_NO_GO_SIGNS_PRESENT`, and the examination must instead end in a diagnosis or as inconclusive."

    Design: Corner/state_machines/conclude_no_concussion_with_no_go_sign_rejected
    """
    # Arrange: screened with an ATAXIA no-go sign, examination running since 18:10.
    ctx = fx.setup_locker_room_exam(api)
    fx.set_clock(api, fx.DIAGNOSIS_AT)

    # Act 1: try to clear the player as having no concussion.
    refused = api.conclude_no_concussion(
        ctx["eval_id"],
        f.conclude_payload(outcome="NO_CONCUSSION", documentation_note="exam unremarkable"),
        ctx["doc_h_headers"],
    )

    # Assert: refused on the no-go sign, examination still open.
    validate_error(refused, ERR_NO_GO_SIGNS_PRESENT, expected_status=409)
    assert fx.read_evaluation(api, ctx["eval_id"])["status"] == "LOCKER_ROOM_EXAM"

    # Act 2: the inconclusive branch is permitted regardless of the screen.
    accepted = api.conclude_no_concussion(
        ctx["eval_id"],
        f.conclude_payload(
            outcome="INCONCLUSIVE", documentation_note="held out for observation"
        ),
        ctx["doc_h_headers"],
    )

    # Assert: held out inconclusive, and still no case opened.
    concluded = validate_success(accepted, expected_status=200)
    assert concluded["status"] == "HELD_OUT_INCONCLUSIVE"
    assert concluded["diagnosis_outcome"] == "INCONCLUSIVE"
    a.assert_instant(concluded["exam_completed_at"], "2026-09-13T18:19:00.000Z")
    assert concluded["exam_duration_minutes"] == 9
    assert fx.read_evaluation(api, ctx["eval_id"])["status"] == "HELD_OUT_INCONCLUSIVE"
    _, meta = validate_paginated(api.list_concussion_cases(ADMIN))
    a.assert_page_meta(meta, total_count=0)


def test_on_field_clearance_blocked_by_mandatory_removal(api):
    """Mandatory removal forbids the SCREENED to CLEARED_ON_FIELD edge outright.

    PRD: "All of the following must hold: `mandatory_removal` is false, the `no_go_signs` list is empty, `screen_symptom_score` is 0, and the game is still `IN_PROGRESS`. Any of the first three failing yields `ERR_MANDATORY_REMOVAL_ENFORCED`."

    Design: Corner/state_machines/on_field_clearance_blocked_by_mandatory_removal
    """
    # Arrange: observer-initiated (mandatory removal) evaluation, screened 9/ATAXIA.
    ctx = fx.setup_screened_evaluation(api)
    screened = fx.read_evaluation(api, ctx["eval_id"])
    assert screened["status"] == "SCREENED"
    assert screened["mandatory_removal"] is True

    # Act: the club physician tries to put the player back on the field.
    response = api.clear_to_return(
        ctx["eval_id"],
        f.clear_to_return_payload("player insists he is fine"),
        ctx["doc_h_headers"],
    )

    # Assert: refused, and the evaluation is left in SCREENED.
    validate_error(response, ERR_MANDATORY_REMOVAL_ENFORCED, expected_status=409)
    reread = fx.read_evaluation(api, ctx["eval_id"])
    assert reread["status"] == "SCREENED"
    assert reread["diagnosis_outcome"] == "PENDING"
    # A refused clearance writes nothing to the player either; only a diagnosis
    # drives the player to PROTOCOL_RESTRICTED and OUT.
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "AVAILABLE"
    assert player["public_injury_designation"] == "NONE"


def test_same_game_on_field_clearance_after_diagnosis_prohibited(api):
    """A diagnosed evaluation in the game bars on-field clearance on any other one.

    PRD: "Additionally, no other evaluation for the same player in the same game may be `DIAGNOSED` or `HELD_OUT_INCONCLUSIVE`; if one is, the on-field clearance is refused with `ERR_SAME_GAME_RETURN_PROHIBITED`."

    Design: Corner/state_machines/same_game_clearance_after_diagnosis_prohibited
    """
    # Arrange: the diagnosed case, then a second evaluation in the same game with
    # a perfectly clean screen (no no-go signs, symptom score 0).
    ctx = fx.setup_diagnosed_case(api)
    fx.set_clock(api, "2026-09-13T18:45:00Z")
    second = get_success_data(
        api.create_sideline_evaluation(
            f.evaluation_payload(
                ctx["player_id"], ctx["game_id"], trigger_source="CLUB_MEDICAL_STAFF"
            ),
            ctx["doc_h_headers"],
        )
    )
    get_success_data(
        api.screen_evaluation(
            second["id"],
            f.screen_payload(no_go_signs=[], symptom_score=0),
            ctx["doc_h_headers"],
        )
    )

    # Act: try to return the player on the strength of the clean re-check.
    response = api.clear_to_return(
        second["id"],
        f.clear_to_return_payload("asymptomatic on re-check"),
        ctx["doc_h_headers"],
    )

    # Assert: refused for the game, second evaluation stuck in SCREENED.
    validate_error(response, ERR_SAME_GAME_RETURN_PROHIBITED, expected_status=409)
    assert fx.read_evaluation(api, second["id"])["status"] == "SCREENED"
    a.assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]), case_status="MANDATORY_REMOVAL"
    )
    player = fx.read_player(api, ctx["player_id"])
    assert player["public_injury_designation"] == "OUT"
    assert player["availability_status"] == "PROTOCOL_RESTRICTED"


def test_diagnosis_side_effects_stamp_case_player_and_baseline(api):
    """One diagnosis opens the case and cascades into the player and the baseline.

    PRD: "The player's `availability_status` becomes `PROTOCOL_RESTRICTED`, `public_injury_designation` becomes `OUT`, and `diagnosed_case_count` increases by 1."

    Design: Corner/state_machines/diagnosis_side_effects_stamp_case_player_and_baseline
    """
    # Arrange: the examination running since 18:10, clock at 18:19.
    ctx = fx.setup_locker_room_exam(api)
    fx.set_clock(api, fx.DIAGNOSIS_AT)

    # Act: document the concussion.
    response = api.diagnose_concussion(
        ctx["eval_id"],
        f.diagnose_payload(
            symptom_score=9,
            composite_score=70,
            documentation_note="no-go sign ataxia, removed from play",
        ),
        ctx["doc_h_headers"],
    )

    # Assert: the case opens in MANDATORY_REMOVAL with its derived figures.
    case = validate_success(response, expected_status=201)
    a.assert_common_fields(case, expected_version=1)
    assert fx.read_evaluation(api, ctx["eval_id"])["status"] == "DIAGNOSED"
    a.assert_case_dimensions(
        case,
        case_status="MANDATORY_REMOVAL",
        monitoring_status="ACTIVE_SYMPTOM_WATCH",
        roster_exemption_status="NONE",
    )
    a.assert_case_progress(
        case,
        rtp_stage=0,
        recurrence_count=0,
        severity_index=82,
        earliest_return_at=None,
    )
    a.assert_null(case, "prior_case_id", "last_symptom_check_score", "cleared_for_contact_at")
    a.assert_instant(case["diagnosis_at"], fx.DIAGNOSIS_AT_MS)
    a.assert_instant(case["projected_return_at"], fx.CANONICAL_PROJECTED_RETURN_AT)
    a.assert_instant(case["last_symptomatic_at"], fx.DIAGNOSIS_AT_MS)
    assert case["diagnosing_clinician_id"] == ctx["doc_h_id"]
    assert case["club_id"] == ctx["club_h_id"]
    assert case["sideline_evaluation_id"] == ctx["eval_id"]
    assert case["initial_symptom_score"] == 9
    assert case["diagnosis_composite_score"] == 70
    assert case["baseline_deviation_points"] == fx.CANONICAL_BASELINE_DEVIATION_POINTS

    # Assert: the player is restricted and the baseline now owes a retest.
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "PROTOCOL_RESTRICTED"
    assert player["public_injury_designation"] == "OUT"
    assert player["diagnosed_case_count"] == 1
    assert player["baseline_status"] == "RETEST_REQUIRED"
    baseline = fx.read_baseline(api, ctx["baseline_id"])
    assert baseline["status"] == "VALID"
    assert baseline["retest_required_reason"] == "NEW_DIAGNOSIS"


# ─── Return step lifecycle ───────────────────────────────────────────────────

def test_second_evaluate_on_passed_step_is_rejected(api):
    """A passed rung cannot be signed off twice, so rtp_stage advances only once.

    PRD: "Either outcome requires the step to be `IN_PROGRESS` (otherwise `ERR_STEP_STATE_INVALID`, which doubles as the guard against a second sign-off on the same step) and the case not to be `STAGE_FROZEN` (otherwise `ERR_CASE_STAGE_FROZEN`)."

    Design: Corner/state_machines/second_evaluate_on_passed_step_rejected
    """
    # Arrange: stage 1 started 2026-09-15T12:00:00Z and passed 2026-09-16T12:00:00Z.
    ctx = fx.setup_case_through_stage(api, 1)
    step_id = ctx["step_ids"][1]

    # Act: sign the same rung off a second time.
    response = api.evaluate_return_step(
        step_id,
        f.evaluate_step_payload(outcome="PASS", symptom_score=0),
        ctx["doc_h_headers"],
    )

    # Assert: refused, the first sign-off intact and rtp_stage still 1.
    validate_error(response, ERR_STEP_STATE_INVALID, expected_status=409)
    step = fx.read_step(api, step_id)
    a.assert_return_step(step, stage_index=1, status="PASSED", attempt_index=1)
    a.assert_instant(step["evaluated_at"], "2026-09-16T12:00:00.000Z")
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_progress(case, rtp_stage=1)
    a.assert_case_dimensions(case, case_status="RTP_IN_PROGRESS")


def test_symptom_recurrence_outcome_fails_the_stage(api):
    """The recurrence branch escapes the dwell gate and regresses the case.

    PRD: "One asymmetry is deliberate and load-bearing: the dwell requirement is **not** enforced on the recurrence branch, because a player who becomes symptomatic must be reportable immediately, at any point inside the rung."

    Design: Corner/state_machines/symptom_recurrence_outcome_fails_the_stage
    """
    # Arrange: a stage-1 step open since 2026-09-15T12:00:00Z (24-hour dwell).
    ctx = fx.setup_case_with_stage_open(api, 1)
    step_id = ctx["step_ids"][1]
    assert fx.read_case(api, ctx["case_id"])["case_status"] == "RTP_IN_PROGRESS"

    # Act: report symptoms six hours into the rung, well inside the dwell.
    fx.set_clock(api, "2026-09-15T18:00:00Z")
    response = api.evaluate_return_step(
        step_id,
        f.evaluate_step_payload(outcome="SYMPTOM_RECURRENCE", symptom_score=6),
        ctx["doc_h_headers"],
    )

    # Assert: accepted despite the unfinished dwell, and the step failed.
    validate_success(response, expected_status=200)
    step = fx.read_step(api, step_id)
    a.assert_return_step(step, stage_index=1, status="FAILED_SYMPTOM_RECURRENCE")
    a.assert_instant(step["evaluated_at"], "2026-09-15T18:00:00.000Z")
    assert step["evaluation_symptom_score"] == 6
    assert step["cleared_by_clinician_id"] == ctx["doc_h_id"]

    # Assert: the case loses ground — recurrence term lifts severity 82 to 94.
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_progress(
        case, rtp_stage=0, recurrence_count=1, severity_index=94, earliest_return_at=None
    )
    a.assert_instant(case["last_symptomatic_at"], "2026-09-15T18:00:00.000Z")
    # One recurrence is below the two the prolonged watch needs.
    a.assert_case_dimensions(
        case, case_status="RTP_IN_PROGRESS", monitoring_status="ACTIVE_SYMPTOM_WATCH"
    )
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "PROTOCOL_RESTRICTED"
    assert player["public_injury_designation"] == "OUT"


# ─── Consultant clearance lifecycle ──────────────────────────────────────────

def test_decide_clearance_twice_is_rejected(api):
    """A decided clearance is closed to further decisions and is not re-stamped.

    PRD: "The decision carries a `decision` value and `decision_notes` recording the consultant's rationale, and requires the clearance to be `PENDING` (otherwise `ERR_CLEARANCE_STATE_INVALID`, which also guards against a second decision on the same clearance)."

    Design: Corner/state_machines/decide_clearance_twice_rejected
    """
    # Arrange: five stages passed, retest filed, clearance approved at 09-27T12:00.
    ctx = fx.setup_case_pending_clearance(api)
    fx.decide_clearance(api, ctx, "APPROVED")

    # Act: the same consultant decides the same clearance again.
    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(decision="APPROVED", decision_notes="re-confirming"),
        ctx["inc_headers"],
    )

    # Assert: refused, with the original decision and expiry untouched.
    validate_error(response, ERR_CLEARANCE_STATE_INVALID, expected_status=409)
    clearance = fx.read_clearance(api, ctx["clearance_id"])
    assert clearance["status"] == "APPROVED"
    a.assert_instant(clearance["decided_at"], "2026-09-27T12:00:00.000Z")
    a.assert_instant(clearance["expires_at"], "2026-10-04T12:00:00.000Z")
    assert clearance["version"] == 2
    # Approval does not advance the case; only return-to-contact does.
    a.assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]), case_status="PENDING_INC_CLEARANCE"
    )


def test_clearance_denied_for_insufficient_documentation(api):
    """The documentation denial revokes nothing and keeps the accrued return date.

    PRD: "**`DENIED_INSUFFICIENT_DOCUMENTATION`** moves the clearance `PENDING → DENIED_INSUFFICIENT_DOCUMENTATION` with `decided_at` stamped, and diverges from the more-rest denial in precisely the way that matters: **no return step is revoked, `rtp_stage` is unchanged, and `earliest_return_at` is retained.**"

    Design: Corner/state_machines/clearance_denied_for_insufficient_documentation
    """
    # Arrange: all five stages passed and a PENDING clearance with the consultant.
    ctx = fx.setup_case_pending_clearance(api)

    # Act: the consultant denies for paperwork rather than for more rest.
    response = api.decide_inc_clearance(
        ctx["clearance_id"],
        f.clearance_decision_payload(
            decision="DENIED_INSUFFICIENT_DOCUMENTATION",
            decision_notes="stage 3 and stage 4 exertion logs are missing",
        ),
        ctx["inc_headers"],
    )

    # Assert: the clearance carries the denial with no expiry.
    decided = validate_success(response, expected_status=200)
    assert decided["status"] == "DENIED_INSUFFICIENT_DOCUMENTATION"
    a.assert_instant(decided["decided_at"], "2026-09-27T12:00:00.000Z")
    a.assert_null(decided, "expires_at")

    # Assert: the ladder is intact — nothing revoked, nothing regressed.
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_dimensions(
        case, case_status="RTP_IN_PROGRESS", monitoring_status="ACTIVE_SYMPTOM_WATCH"
    )
    a.assert_case_progress(
        case,
        rtp_stage=5,
        recurrence_count=0,
        severity_index=82,
        earliest_return_at=fx.CANONICAL_EARLIEST_RETURN_AT,
    )
    assert fx.read_step(api, ctx["step_ids"][5])["status"] == "PASSED"
    _, meta = validate_paginated(
        api.list_return_steps(ADMIN, case_id=ctx["case_id"], status="REVOKED")
    )
    a.assert_page_meta(meta, total_count=0)


# ─── Concussion case terminal state ──────────────────────────────────────────

def test_cleared_case_rejects_further_stage_creation(api):
    """CLEARED_FOR_CONTACT is terminal for the case dimension: no new rung opens.

    PRD: "`ERR_CASE_STATE_INVALID` (409) for the five case actions, where the permitted from-states are: stage creation — `MANDATORY_REMOVAL` or `RTP_IN_PROGRESS`; final-clearance request — `MANDATORY_REMOVAL` or `RTP_IN_PROGRESS`; return to contact — `PENDING_INC_CLEARANCE` only; roster exemption — `MANDATORY_REMOVAL`, `RTP_IN_PROGRESS`, `PENDING_INC_CLEARANCE` or `STAGE_FROZEN`; symptom check — any status at all, `CLEARED_FOR_CONTACT` included, because post-clearance and off-season monitoring writes are deliberately permitted on a cleared case."

    Design: Corner/state_machines/cleared_case_rejects_further_stage_writes
    """
    # Arrange: the whole protocol walked to CLEARED_FOR_CONTACT at 09-28T12:00.
    ctx = fx.setup_case_with_approved_clearance(api)
    get_success_data(
        api.return_to_contact(
            ctx["case_id"], f.return_to_contact_payload("full clearance"), ctx["doc_h_headers"]
        )
    )

    # Act: try to open another graduated-return rung on the cleared case.
    response = api.create_return_step(
        ctx["case_id"], f.return_step_payload(1), ctx["doc_h_headers"]
    )

    # Assert: refused on the case from-state, and no sixth step exists.
    validate_error(response, ERR_CASE_STATE_INVALID, expected_status=409)
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_dimensions(case, case_status="CLEARED_FOR_CONTACT")
    a.assert_instant(case["cleared_for_contact_at"], "2026-09-28T12:00:00.000Z")
    assert case["heightened_review_required"] is False
    _, meta = validate_paginated(api.list_return_steps(ADMIN, case_id=ctx["case_id"]))
    a.assert_page_meta(meta, total_count=5)
    player = fx.read_player(api, ctx["player_id"])
    assert player["availability_status"] == "AVAILABLE"
    assert player["public_injury_designation"] == "QUESTIONABLE"


# ─── The monitoring dimension ────────────────────────────────────────────────

def test_monitoring_dimension_advances_independently_of_case_status(api):
    """The 21-day line moves monitoring_status alone; case_status does not budge.

    PRD: "During a sweep, a case whose `days_since_diagnosis` has reached 21 and whose `case_status` is not `CLEARED_FOR_CONTACT` moves `ACTIVE_SYMPTOM_WATCH → PROLONGED_SYMPTOM_WATCH`; the twenty-first day exactly qualifies."

    Design: Corner/state_machines/monitoring_dimension_advances_independently_of_case_status
    """
    # Arrange: the case diagnosed 2026-09-13T18:19:00Z with no return steps.
    ctx = fx.setup_diagnosed_case(api)

    # Act 1: sweep one second short of the twenty-first complete day.
    fx.set_clock(api, "2026-10-04T18:18:59Z")
    day_twenty = validate_success(api.run_protocol_sweep(ADMIN), expected_status=200)

    # Assert: twenty complete days is not twenty-one, so nothing moves.
    assert day_twenty["prolonged_watch_case_ids"] == []
    assert day_twenty["breached_evaluation_ids"] == []
    a.assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]), monitoring_status="ACTIVE_SYMPTOM_WATCH"
    )

    # Act 2: sweep at exactly twenty-one elapsed days.
    fx.set_clock(api, "2026-10-04T18:19:00Z")
    day_twentyone = validate_success(api.run_protocol_sweep(ADMIN), expected_status=200)

    # Assert: only the monitoring dimension advanced.
    assert day_twentyone["prolonged_watch_case_ids"] == [ctx["case_id"]]
    assert day_twentyone["breached_evaluation_ids"] == []
    case = fx.read_case(api, ctx["case_id"])
    a.assert_case_dimensions(
        case,
        case_status="MANDATORY_REMOVAL",
        monitoring_status="PROLONGED_SYMPTOM_WATCH",
        roster_exemption_status="NONE",
    )
    a.assert_case_progress(case, rtp_stage=0)
    assert fx.read_player(api, ctx["player_id"])["public_injury_designation"] == "OUT"


def test_offseason_monitoring_takes_precedence_over_prolonged_rule(api):
    """At the off-season boundary the sweep chooses OFFSEASON_MONITORING.

    PRD: "At or after that instant a sweep moves the case to `OFFSEASON_MONITORING` from either `ACTIVE_SYMPTOM_WATCH` or `PROLONGED_SYMPTOM_WATCH`, incrementing the case's `version` by 1 — and where both the off-season boundary and the 21-day line would fire in the same sweep, the off-season transition takes precedence, so the prolonged flag is simply superseded by the off-season programme."

    Design: Corner/state_machines/offseason_monitoring_takes_precedence_over_prolonged_rule
    """
    # Arrange: the 2026-season case diagnosed 2026-09-13, never swept, with the
    # clock moved to the 2026 season's off-season start (15 February 2027).
    ctx = fx.setup_diagnosed_case(api)
    fx.set_clock(api, "2027-02-15T00:00:00Z")

    # Act: run the sweep, where both calendar lines are long past.
    response = api.run_protocol_sweep(ADMIN)

    # Assert: the off-season programme wins and the prolonged line reports nothing.
    summary = validate_success(response, expected_status=200)
    assert summary["offseason_monitoring_case_ids"] == [ctx["case_id"]]
    assert summary["prolonged_watch_case_ids"] == []
    a.assert_case_dimensions(
        fx.read_case(api, ctx["case_id"]),
        case_status="MANDATORY_REMOVAL",
        monitoring_status="OFFSEASON_MONITORING",
    )
    assert fx.read_player(api, ctx["player_id"])["public_injury_designation"] == "OUT"


# ─── Protocol audit lifecycle ────────────────────────────────────────────────

def test_respond_to_open_audit_is_rejected(api):
    """A club cannot answer an audit that has never had findings issued.

    PRD: "A response supplies a `response_note`, requires the audit to be `FINDINGS_ISSUED` (otherwise `ERR_AUDIT_STATE_INVALID`), and takes it `FINDINGS_ISSUED → CLUB_RESPONDED` while recording the note as `club_response_note` and increasing `response_round_count` by 1."

    Design: Corner/state_machines/respond_to_open_audit_rejected
    """
    # Arrange: an audit opened against the club and still OPEN.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"])
    assert audit["status"] == "OPEN"

    # Act: the club's compliance officer files a response anyway.
    response = api.respond_to_audit(
        audit["id"],
        f.audit_response_payload("we dispute the premise"),
        make_compliance_officer_headers(club["id"]),
    )

    # Assert: refused, and no round was consumed.
    validate_error(response, ERR_AUDIT_STATE_INVALID, expected_status=409)
    reread = fx.read_audit(api, audit["id"])
    assert reread["status"] == "OPEN"
    assert reread["response_round_count"] == 0
    a.assert_null(reread, "club_response_note", "findings_issued_at")
    # An OPEN audit sits in neither compliance set, so the club is untouched.
    a.assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=100,
        outstanding_fine_cents=0,
        open_violation_count=1,
    )


def test_third_club_response_exhausts_audit_rounds(api):
    """Two response rounds are the ceiling; the third response is refused.

    PRD: "A club may respond at most twice to one audit; a third attempt is refused with `ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED`."

    Design: Corner/state_machines/third_club_response_exhausts_audit_rounds
    """
    # Arrange: two full response / re-findings cycles, audit FINDINGS_ISSUED again.
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    club = fx.create_club(api, "Harbor City Kraken", "HCK", 3)
    audit = fx.open_audit(api, club["id"])
    fx.issue_findings(api, audit["id"], ["LATE_INJURY_REPORT"], exposure_days=0)
    fx.respond_to_audit(api, audit["id"], club["id"], "round one response")
    fx.issue_findings(api, audit["id"], ["LATE_INJURY_REPORT"], exposure_days=0)
    fx.respond_to_audit(api, audit["id"], club["id"], "round two response")
    fx.issue_findings(api, audit["id"], ["LATE_INJURY_REPORT"], exposure_days=0)

    # Act: a third response on the same audit.
    response = api.respond_to_audit(
        audit["id"],
        f.audit_response_payload("round three response"),
        make_compliance_officer_headers(club["id"]),
    )

    # Assert: refused with the round count frozen at the ceiling.
    validate_error(response, ERR_AUDIT_RESPONSE_ROUNDS_EXHAUSTED, expected_status=409)
    reread = fx.read_audit(api, audit["id"])
    assert reread["status"] == "FINDINGS_ISSUED"
    assert reread["response_round_count"] == 2
    # TIER_0 pricing of one LATE_INJURY_REPORT line at exposure_days 0.
    assert reread["assessed_fine_cents"] == 1500000
    assert reread["escalation_tier_at_issuance"] == "TIER_0"
    a.assert_club_posture(
        fx.read_club(api, club["id"]),
        compliance_score=94,
        escalation_tier="TIER_0",
        status="ACTIVE",
        outstanding_fine_cents=1500000,
    )


# ─── Baseline test lifecycle ─────────────────────────────────────────────────

def test_invalidating_baseline_test_twice_is_rejected(api):
    """Invalidation is one-way, and it re-resolves the player's baseline posture.

    PRD: "Invalidating a row that is not `VALID` is refused with `ERR_RESOURCE_STATE_INVALID`."

    Design: Corner/state_machines/invalidating_baseline_test_twice_rejected
    """
    # Arrange: the player's single VALID pre-season baseline, filed 2026-08-01.
    ctx = fx.setup_reference_data(api)
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "VALID"

    # Act 1: the league invalidates the row administratively.
    first = api.invalidate_baseline_test(
        ctx["baseline_id"],
        f.invalidate_payload("administered on uncalibrated hardware"),
        ADMIN,
    )

    # Assert: the row is INVALIDATED and no VALID row survives for the player.
    invalidated = validate_success(first, expected_status=200)
    assert invalidated["status"] == "INVALIDATED"
    assert invalidated["retest_required_reason"] == "ADMIN_INVALIDATION"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "NONE"

    # Act 2: invalidate the same row again.
    second = api.invalidate_baseline_test(
        ctx["baseline_id"], f.invalidate_payload("duplicate request"), ADMIN
    )

    # Assert: refused, because the row is no longer VALID.
    validate_error(second, ERR_RESOURCE_STATE_INVALID, expected_status=409)
    assert fx.read_baseline(api, ctx["baseline_id"])["status"] == "INVALIDATED"
    assert fx.read_player(api, ctx["player_id"])["baseline_status"] == "NONE"
