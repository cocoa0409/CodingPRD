"""Requests that violate two declared rules at once.

Each scenario below is built so that two different rejection rules are genuinely
violated by one call, and the PRD's rejection ladder decides which error_id comes
back. Every scenario carries a control proving the lower-ranked violation was
present all along and was merely outranked.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx2
from test_helpers.test_users import SUPERVISOR, make_dispatcher_headers

CLOCK = "2026-08-20T00:00:00Z"
LATE_CLOCK = "2027-01-15T00:00:00Z"

ROUND_ONE_SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}
ROUND_TWO_SECTIONS = {
    "case_entry": (19, 20),
    "key_questions": (27, 30),
    "pre_arrival": (3, 3),
    "final_coding": (6, 7),
}
PERFECT_SECTIONS = {
    "case_entry": (20, 20),
    "key_questions": (30, 30),
    "pre_arrival": (10, 10),
    "final_coding": (10, 10),
}


# ---------------------------------------------------------------------------
# A review sent back to SELECTED that has also used up its rebuttal rounds
# ---------------------------------------------------------------------------
def _review_back_in_selected_with_rounds_used_up(api):
    """Two scored rounds, both disputed and both upheld, on a two-round programme.

    The review therefore sits outside `SCORED` and its `rebuttal_round_count` has
    reached the programme's cap, so a third dispute violates both rules at once.
    """
    env = fx.selected_review_env(
        api,
        program_overrides={"rebuttal_window_days": 14, "max_rebuttal_rounds": 2},
        period_overrides={"sampling_mode": "MIXED"},
    )
    fx.score(
        api, env["review_id"], sections=ROUND_ONE_SECTIONS,
        reviewer_determinant_code="10-C-2",
    )
    first = fx.file_rebuttal(
        api, env["review_id"], env["dispatcher_id"],
        grounds_category="PROTOCOL_AMBIGUITY", narrative="Round 1 dispute.",
    )
    fx.decide_rebuttal(api, first["id"], "UPHELD", "Re-score.")
    fx.score(
        api, env["review_id"], sections=ROUND_TWO_SECTIONS,
        reviewer_determinant_code="10-C-2",
    )
    second = fx.file_rebuttal(
        api, env["review_id"], env["dispatcher_id"],
        grounds_category="SCORING_DISPUTE", narrative="Round 2 dispute.",
    )
    fx.decide_rebuttal(api, second["id"], "UPHELD", "Re-score again.")
    return env


def _third_dispute(api, env):
    return api.create_rebuttal(
        env["review_id"],
        f.rebuttal_payload(
            grounds_category="AUDIO_QUALITY",
            narrative="Third attempt after two upheld rounds.",
        ),
        make_dispatcher_headers(env["dispatcher_id"]),
    )


def test_third_dispute_on_a_rewound_review_reports_the_undisputable_status(api):
    """PRD §2.9: "When a request violates more than one rule, exactly one error is
    returned, and which one is fully determined by the ladder below. Checks are evaluated in
    this order and the first violated rule wins:"
    PRD §2.9: "The practical consequence worth internalising: a state violation always
    outranks a scope, safety, overlap, temporal, uniqueness or quota violation, and an
    authorization failure outranks everything except a missing header."
    PRD §3.7: "Filing is possible only against a review in `SCORED`; a review in any other
    status is refused with `ERR_REVIEW_NOT_DISPUTABLE`."
    PRD §3.7: "The review's `rebuttal_round_count` must still be below the programme's
    `max_rebuttal_rounds`, and a case that has exhausted its rounds is refused with
    `ERR_REBUTTAL_ROUNDS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/state_check_40_beats_rounds_exhausted_70_on_a_third_rebuttal
    """
    env = _review_back_in_selected_with_rounds_used_up(api)

    before = fx.get_review(api, env["review_id"])
    assert before["status"] == "SELECTED", (
        "two upheld disputes send the review back for re-scoring"
    )
    assert before["rebuttal_round_count"] == 2, "the two-round cap has been reached"
    assert before["current_sheet_round"] == 2, "the append-only sheet log is never rewound"
    assert before["scored_at"] is None

    # Both rules are violated; the status rule outranks the round-cap rule.
    validate_error(_third_dispute(api, env), err.ERR_REVIEW_NOT_DISPUTABLE)

    after = fx.get_review(api, env["review_id"])
    assert after["rebuttal_round_count"] == 2, "the refused dispute consumed no round"
    rebuttals = fx.list_rebuttals_for(api, env["review_id"])
    assert len(rebuttals) == 2, f"expected exactly two rebuttals, got {len(rebuttals)}"


def test_once_the_review_is_scored_again_the_exhausted_round_cap_is_reported(api):
    """PRD §3.7: "The review's `rebuttal_round_count` must still be below the programme's
    `max_rebuttal_rounds`, and a case that has exhausted its rounds is refused with
    `ERR_REBUTTAL_ROUNDS_EXHAUSTED`."
    PRD §3.5: "Submitting a score against a review in `SELECTED` takes it
    `SELECTED → SCORED`; submitting a further score against a review already in `SCORED` is
    also permitted and keeps it in `SCORED`, a self-loop that supersedes the previous sheet."

    Design: Difficulty/priority_pair_validation_conflict/state_check_40_beats_rounds_exhausted_70_on_a_third_rebuttal
    """
    env = _review_back_in_selected_with_rounds_used_up(api)

    # Re-scoring clears the status objection, leaving only the round-cap violation.
    fx.score(
        api, env["review_id"], sections=ROUND_TWO_SECTIONS,
        reviewer_determinant_code="10-C-2",
    )
    rescored = fx.get_review(api, env["review_id"])
    assert rescored["status"] == "SCORED"
    assert rescored["current_sheet_round"] == 3
    assert rescored["rebuttal_round_count"] == 2

    validate_error(_third_dispute(api, env), err.ERR_REBUTTAL_ROUNDS_EXHAUSTED)

    rebuttals = fx.list_rebuttals_for(api, env["review_id"])
    assert len(rebuttals) == 2, f"expected exactly two rebuttals, got {len(rebuttals)}"


# ---------------------------------------------------------------------------
# An unsigned cardiac-arrest case that is also past its finalization deadline
# ---------------------------------------------------------------------------
def _unsigned_high_risk_review_left_too_long(api):
    """A scored cardiac-arrest review whose clinical record is graded but not signed off,
    with the logical clock moved well beyond the finalization deadline."""
    env = fx.high_risk_scored_env(
        api,
        program_overrides={"review_deadline_days": 30},
        outcome_category="ROSC_HOSPITAL",
    )
    fx.score(
        api, env["review_id"], sections=PERFECT_SECTIONS,
        reviewer_determinant_code="9-E-1",
    )
    fx.set_clock(api, LATE_CLOCK)
    return env


def test_unsigned_cardiac_arrest_case_is_never_reported_as_merely_late(api):
    """PRD §2.9: "Checks are evaluated in this order and the first violated rule wins:"
    PRD §2.9: "**Clinical safety gates** — `ERR_HIGH_RISK_SIGN_OFF_REQUIRED`,
    `ERR_SENTINEL_CLASSIFICATION_REQUIRED`."
    PRD §2.9: "**Temporal envelopes** — `ERR_CALL_RECEIVED_IN_FUTURE`,
    `ERR_CALL_OUTSIDE_PERIOD`, `ERR_REBUTTAL_WINDOW_CLOSED`, `ERR_REVIEW_DEADLINE_PASSED`,
    `ERR_INVALID_TIME_WINDOW`, `ERR_REPORT_WINDOW_INVALID`."
    PRD §3.7: "If the review is `high_risk`, a clinical record must exist on it in
    `SENTINEL_EVENT` or `COACHING_ONLY` — a record still sitting in `PENDING` or
    `DACPR_SCORED`, or no record at all, is refused with `ERR_HIGH_RISK_SIGN_OFF_REQUIRED`."
    PRD §3.7: "And the logical clock must be no later than the review's `created_at` plus
    the programme's `review_deadline_days`, with the boundary instant still inside; a review
    left too long is refused with `ERR_REVIEW_DEADLINE_PASSED`."

    Design: Difficulty/priority_pair_validation_conflict/high_risk_signoff_gate_55_beats_review_deadline_65_on_finalization
    """
    env = _unsigned_high_risk_review_left_too_long(api)

    review = fx.get_review(api, env["review_id"])
    assert review["high_risk"] is True, "a CARDIAC_ARREST call is always high risk"
    assert review["status"] == "SCORED"

    record = fx.get_high_risk_review(api, env["review_id"], env["high_risk_review_id"])
    assert record["status"] == "DACPR_SCORED"
    assert record["signed_off_at"] is None
    assert record["classification"] is None

    # Both rules answer with HTTP 422, so only the error_id distinguishes them.
    validate_error(
        api.finalize_review(
            env["review_id"], {"finalization_note": "Closing the August batch."}, SUPERVISOR
        ),
        err.ERR_HIGH_RISK_SIGN_OFF_REQUIRED,
    )

    unchanged = fx.get_review(api, env["review_id"])
    assert unchanged["status"] == "SCORED"
    assert unchanged["finalized_at"] is None


def test_after_sign_off_the_same_late_finalization_reports_the_passed_deadline(api):
    """PRD §3.7: "And the logical clock must be no later than the review's `created_at` plus
    the programme's `review_deadline_days`, with the boundary instant still inside; a review
    left too long is refused with `ERR_REVIEW_DEADLINE_PASSED`."
    PRD §3.6: "Classifying a case as coaching-only takes the record
    `DACPR_SCORED → COACHING_ONLY`, and it is gated: a record whose `dacpr_index` is below
    50.0 is too poor a performance to close as a coaching matter, and an attempt to do so is
    refused with `ERR_SENTINEL_CLASSIFICATION_REQUIRED` — below that floor the classification
    must be `SENTINEL_EVENT`."

    Design: Difficulty/priority_pair_validation_conflict/high_risk_signoff_gate_55_beats_review_deadline_65_on_finalization
    """
    env = _unsigned_high_risk_review_left_too_long(api)

    # Clearing the clinical gate leaves the temporal violation as the only objection.
    signed = fx.sign_off(api, env["high_risk_review_id"], "COACHING_ONLY")
    assert signed["status"] == "COACHING_ONLY"
    assert signed["classification"] == "COACHING_ONLY"

    validate_error(
        api.finalize_review(
            env["review_id"], {"finalization_note": "Closing the August batch."}, SUPERVISOR
        ),
        err.ERR_REVIEW_DEADLINE_PASSED,
    )

    unchanged = fx.get_review(api, env["review_id"])
    assert unchanged["status"] == "SCORED"
    assert unchanged["finalized_at"] is None


# ---------------------------------------------------------------------------
# A draft curriculum booked into a slot the dispatcher's buffer already occupies
# ---------------------------------------------------------------------------
def _dispatcher_with_an_occupied_calendar(api):
    """One approved curriculum and one still-draft curriculum in the same programme,
    a dispatcher holding a SCHEDULED 10:00-11:00 session, and a fresh open plan."""
    env = fx.program_with_version(api)
    draft = fx.new_version(
        api,
        env["program_id"],
        protocol_family="LOCAL_CARDSET",
        version_label="LOCAL-2.0-draft",
    )
    dispatcher = fx.new_dispatcher(api, env["program_id"])
    first_plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="ADVISORY", focus_area="CASE_ENTRY"
    )
    session = fx.new_session(
        api,
        first_plan["id"],
        env["version_id"],
        starts_at="2026-08-15T10:00:00Z",
        ends_at="2026-08-15T11:00:00Z",
        modality="CLASSROOM",
    )
    second_plan = fx.new_coaching_plan(
        api, dispatcher["id"], severity="STANDARD", focus_area="KEY_QUESTIONS"
    )
    env.update(
        {
            "draft_version": draft,
            "draft_version_id": draft["id"],
            "dispatcher": dispatcher,
            "dispatcher_id": dispatcher["id"],
            "first_plan_id": first_plan["id"],
            "session": session,
            "session_id": session["id"],
            "second_plan_id": second_plan["id"],
        }
    )
    return env


def _schedule_on_second_plan(api, env, version_id, starts_at, ends_at):
    return api.create_retraining_session(
        env["second_plan_id"],
        f.retraining_session_payload(
            version_id, starts_at=starts_at, ends_at=ends_at, modality="SIMULATION"
        ),
        SUPERVISOR,
    )


def test_draft_curriculum_outranks_the_buffer_collision_on_the_same_request(api):
    """PRD §2.9: "Checks are evaluated in this order and the first violated rule wins:"
    PRD §2.9: "**Referenced protocol version is usable for the purpose** —
    `ERR_VERSION_NOT_CERTIFIABLE`, `ERR_CURRICULUM_VERSION_NOT_TRAINABLE`,
    `ERR_NO_PROTOCOL_VERSION_IN_FORCE`."
    PRD §2.9: "**Window exclusivity** — `ERR_PROTOCOL_WINDOW_OVERLAP`,
    `ERR_SESSION_WINDOW_OVERLAP`."
    PRD §3.8: "The curriculum version must be in `APPROVED` or `ACTIVE` — a draft or
    superseded curriculum is refused with `ERR_CURRICULUM_VERSION_NOT_TRAINABLE` — and must
    belong to the coached dispatcher's programme, or the request is refused for programme
    scope."

    Design: Difficulty/priority_pair_validation_conflict/curriculum_usability_50_beats_session_buffer_overlap_60
    """
    env = _dispatcher_with_an_occupied_calendar(api)

    assert fx.get_version(api, env["draft_version_id"])["status"] == "DRAFT"
    occupying = fx.get_session(api, env["first_plan_id"], env["session_id"])
    assert occupying["status"] == "SCHEDULED"
    assert occupying["duration_hours"] == approx2(1.00)

    # 11:45 widened back by 45 minutes touches the 11:00 end of the existing session,
    # so the exclusivity rule is violated too; the referential rule is reported.
    validate_error(
        _schedule_on_second_plan(
            api, env, env["draft_version_id"],
            "2026-08-15T11:45:00Z", "2026-08-15T12:45:00Z",
        ),
        err.ERR_CURRICULUM_VERSION_NOT_TRAINABLE,
    )

    rows, _meta = validate_paginated(
        api.list_retraining_sessions(env["second_plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert rows == [], f"the refused request must book nothing, got {rows}"
    assert fx.get_plan(api, env["second_plan_id"])["status"] == "ASSIGNED"


def test_approved_curriculum_at_the_same_start_reports_the_buffer_collision(api):
    """PRD §3.8: "The new session's window is widened by **45 minutes on each side** and
    compared, inclusive of the endpoints, against every other `SCHEDULED` or `COMPLETED`
    session of the same dispatcher; any touching or overlap is refused with
    `ERR_SESSION_WINDOW_OVERLAP`."
    PRD §3.8: "Because the comparison is closed rather than half-open, two genuinely
    back-to-back sessions do collide — the buffer is a hard rest requirement, not a
    formality."

    Design: Difficulty/priority_pair_validation_conflict/curriculum_usability_50_beats_session_buffer_overlap_60
    """
    env = _dispatcher_with_an_occupied_calendar(api)

    # Same slot, but now on the approved curriculum: only the buffer rule is violated.
    validate_error(
        _schedule_on_second_plan(
            api, env, env["version_id"],
            "2026-08-15T11:45:00Z", "2026-08-15T12:45:00Z",
        ),
        err.ERR_SESSION_WINDOW_OVERLAP,
    )

    rows, _meta = validate_paginated(
        api.list_retraining_sessions(env["second_plan_id"], SUPERVISOR, {"limit": 100})
    )
    assert rows == [], f"the refused request must book nothing, got {rows}"
    assert fx.get_plan(api, env["second_plan_id"])["status"] == "ASSIGNED"


def test_one_minute_later_clears_the_closed_buffer_and_the_booking_succeeds(api):
    """PRD §3.8: "The new session's window is widened by **45 minutes on each side** and
    compared, inclusive of the endpoints, against every other `SCHEDULED` or `COMPLETED`
    session of the same dispatcher; any touching or overlap is refused with
    `ERR_SESSION_WINDOW_OVERLAP`."
    PRD §3.8: "A successful scheduling writes the session against its plan through
    `coaching_plan_id`, with `status` `SCHEDULED`, no `attendance_confirmed`, no
    `cancel_reason` and no `completed_at`, and computes `duration_hours` as the elapsed time
    from `starts_at` to `ends_at` expressed in hours — the elapsed seconds divided by 3600 —
    rounded half up to 2 decimal places."
    PRD §3.8: "If the plan was in `ASSIGNED`, scheduling moves it `ASSIGNED → IN_PROGRESS`."

    Design: Difficulty/priority_pair_validation_conflict/curriculum_usability_50_beats_session_buffer_overlap_60
    """
    env = _dispatcher_with_an_occupied_calendar(api)

    # A start one minute later puts the buffered edge at 11:01, clear of the 11:00 end.
    booked = validate_success(
        _schedule_on_second_plan(
            api, env, env["version_id"],
            "2026-08-15T11:46:00Z", "2026-08-15T12:46:00Z",
        ),
        201,
    )
    assert booked["coaching_plan_id"] == env["second_plan_id"]
    assert booked["status"] == "SCHEDULED"
    assert booked["duration_hours"] == approx2(1.00)
    assert booked["completed_at"] is None
    assert booked["cancel_reason"] is None

    assert fx.get_plan(api, env["second_plan_id"])["status"] == "IN_PROGRESS"
