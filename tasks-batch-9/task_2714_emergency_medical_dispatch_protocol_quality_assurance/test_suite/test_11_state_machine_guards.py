"""Review, rebuttal, sampling-period and rollout transition guards.

Covers the reachable transitions and the refusals that protect them: the two
adjudication arms of the SELECTED -> SCORED -> DISPUTED -> SELECTED cycle, the
preconditions on scoring, what closing a period does and does not freeze, the
birth values of a fresh review, the lockdown of the terminal VOIDED state, and
the derived training dimension a certification drives on a rollout.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as err
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, assert_common_fields, assert_instant_equals
from test_helpers.test_users import (
    ADMIN,
    REVIEWER,
    SUPERVISOR,
    SUPERVISOR_USER_ID,
    make_dispatcher_headers,
)

# 18/20, 26/30, 2/3 and 5/7 give 90.00, 86.67, 66.67 and 71.43, whose mean is
# 78.6925 and therefore 78.7 at one decimal place.
SHEET_78_7 = {"case_entry": (18, 20), "key_questions": (26, 30),
              "pre_arrival": (2, 3), "final_coding": (5, 7)}
PERFECT_SHEET = {"case_entry": (20, 20), "key_questions": (30, 30),
                 "pre_arrival": (3, 3), "final_coding": (7, 7)}


def test_rejecting_a_rebuttal_returns_the_review_to_scored_with_its_number_intact(api):
    """PRD §3.7: "Rejecting takes the rebuttal `SUBMITTED → REJECTED`, records
    `decided_by_user_id`, and returns the review `DISPUTED → SCORED` with its
    `provisional_composite_score` and `scored_at` preserved intact, because the existing
    sheet stands."
    PRD §3.7: "Either decision increments the review's `version`."
    PRD §3.7: "An accepted filing creates a rebuttal in `status` `SUBMITTED`, linked by
    `review_id`, with `round_index` one greater than the review's `rebuttal_round_count` at
    the time of filing and `submitted_by_user_id` recording the filing dispatcher — always
    the same identifier as the review's `dispatcher_id`."
    PRD §3.5: "Sheets themselves are **append-only**: each submission creates a new score
    sheet whose `sheet_round` is one greater than the review's `current_sheet_round` at the
    moment of submission, and no earlier sheet is ever mutated or deleted."

    Design: Corner/state_machines/rejected_rebuttal_decision_restores_the_scored_review
    """
    env = fx.scored_review_env(
        api, sections=SHEET_78_7, reviewer_determinant_code="10-C-2"
    )
    rebuttal = fx.file_rebuttal(
        api,
        env["review_id"],
        env["dispatcher_id"],
        grounds_category="AUDIO_QUALITY",
        narrative="background noise obscured the caller's answers",
    )
    disputed = fx.get_review(api, env["review_id"])
    assert disputed["status"] == "DISPUTED"
    scored_at = disputed["scored_at"]

    data = validate_success(
        api.decide_rebuttal(
            rebuttal["id"],
            f.rebuttal_decision_payload(
                "REJECTED", decision_notes="audio was audible on the master recording"
            ),
            SUPERVISOR,
        )
    )
    assert data["status"] == "REJECTED"
    assert data["decided_by_user_id"] == SUPERVISOR_USER_ID
    assert data["round_index"] == 1

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SCORED"
    assert review["provisional_composite_score"] == approx1(78.7)
    assert_instant_equals(review["scored_at"], scored_at)
    assert review["rebuttal_round_count"] == 1
    assert review["version"] == disputed["version"] + 1

    sheets = fx.list_sheets(api, env["review_id"])
    assert len(sheets) == 1, "a rejected rebuttal creates no new round"


def test_one_section_earning_more_than_it_could_aborts_the_whole_submission(api):
    """PRD §3.5: "Every one of the eight must be at least 0, and within each pair the points
    earned must not exceed the points possible — a sheet violating either is rejected as an
    invalid request."
    PRD §2.9: "**Request shape** — the body parses, required fields are present, types
    match, enum values are declared members, and numeric fields are in range, else
    `ERR_INVALID_REQUEST`."
    PRD §3.5: "The same value is written onto the review's own
    `provisional_composite_score`, and the review's `scored_at` is stamped from the logical
    clock."

    Design: Corner/state_machines/scoring_with_points_earned_above_possible_is_rejected
    """
    env = fx.selected_review_env(api)
    inverted = dict(SHEET_78_7, pre_arrival=(4, 3))

    response = api.submit_scores(
        env["review_id"],
        f.section_score_payload(env["review"]["version"], inverted, "10-C-4"),
        REVIEWER,
    )
    validate_error(response, err.ERR_INVALID_REQUEST, 400)

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED"
    assert review["current_sheet_round"] == 0
    assert review["provisional_composite_score"] is None
    assert review["scored_at"] is None
    assert review["version"] == env["review"]["version"], "a refusal is not a mutation"
    assert fx.list_sheets(api, env["review_id"]) == [], "no partial sheet was written"

    accepted = validate_success(
        api.submit_scores(
            env["review_id"],
            f.section_score_payload(
                review["version"], dict(SHEET_78_7, pre_arrival=(3, 3)), "10-C-4"
            ),
            REVIEWER,
        ),
        201,
    )
    assert accepted["sheet_round"] == 1
    assert fx.get_review(api, env["review_id"])["status"] == "SCORED"


def test_closing_a_period_shuts_off_selection_only(api):
    """PRD §3.4: "Closing a period is a `QaSupervisor` action carrying an optional
    `closing_note`, and it moves the period `OPEN → CLOSED` with `closed_at` stamped from the
    logical clock."
    PRD §3.4: "Both routes require the period to still be `OPEN`; once it is closed or
    locked, selection is refused with `ERR_PERIOD_NOT_OPEN`."
    PRD §3.4: "Closing shuts off further selection but nothing else: reviews already
    selected inside a closed period remain fully scorable, disputable and finalizable."
    PRD §3.4: "A successful targeted selection creates one review with `selection_mode` of
    `TARGETED`, moves the call to `SELECTED`, and increments the period's
    `selected_review_count` by one."

    Design: Corner/state_machines/closing_a_period_blocks_further_selection
    """
    env = fx.selected_review_env(api)
    second_call = fx.ingest_call(
        api, env["dispatcher_id"], call_reference="C-0002", received_at="2026-08-06T09:00:00Z"
    )

    closed = validate_success(
        api.close_sampling_period(env["period_id"], {"closing_note": "quota met"}, SUPERVISOR)
    )
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], fx.WORKING_CLOCK)

    refused = api.target_review(
        env["period_id"],
        f.target_review_payload(second_call["id"], selection_reason="COMPLAINT"),
        SUPERVISOR,
    )
    validate_error(refused, err.ERR_PERIOD_NOT_OPEN, 409)

    calls, _ = validate_paginated(
        api.list_call_records(env["dispatcher_id"], ADMIN, {"limit": 100})
    )
    stored_second = next(row for row in calls if row["id"] == second_call["id"])
    assert stored_second["status"] == "INGESTED", "the refused call keeps its status"

    current = fx.get_review(api, env["review_id"])
    sheet = validate_success(
        api.submit_scores(
            env["review_id"],
            f.section_score_payload(current["version"], SHEET_78_7, "10-C-2"),
            REVIEWER,
        ),
        201,
    )
    assert sheet["sheet_round"] == 1, "a closed period does not freeze scoring"
    scored = fx.get_review(api, env["review_id"])
    assert scored["status"] == "SCORED"
    assert scored["provisional_composite_score"] == approx1(78.7)

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 1, "the refused selection consumed no slot"


def test_finalizing_a_review_that_was_never_scored_is_refused(api):
    """PRD §3.7: "The review must be in `SCORED`, and any other status is refused with
    `ERR_REVIEW_NOT_FINALIZABLE`."
    PRD §3.7: "Cascade A then runs outward from that single number."
    PRD §3.7: "The dispatcher's compliance figures are recomputed from scratch over every
    review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`, `DISPUTED` or `VOIDED`
    contribute nothing: `reviewed_case_count` is the number of such reviews,
    `compliance_points_total` is the sum of their `final_composite_score` values rounded half
    up to 1 decimal place, and `compliance_pct` is that total divided by the count, rounded
    half up to 1 decimal place."

    Design: Corner/state_machines/finalizing_a_selected_review_is_rejected
    """
    env = fx.selected_review_env(api)

    response = api.finalize_review(
        env["review_id"], {"finalization_note": "premature"}, SUPERVISOR
    )
    validate_error(response, err.ERR_REVIEW_NOT_FINALIZABLE, 409)

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED"
    for field in (
        "final_composite_score",
        "pre_penalty_composite_score",
        "penalty_points",
        "determinant_accuracy",
        "compliant",
        "finalized_at",
    ):
        assert review[field] is None, f"{field} must stay null when finalization is refused"

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["reviewed_case_count"] == 0, "no cascade fired"
    assert dispatcher["compliance_pct"] is None
    assert dispatcher["compliance_posture"] == "UNRATED"


def test_rebutting_a_review_that_was_never_scored_is_refused(api):
    """PRD §3.7: "Filing is possible only against a review in `SCORED`; a review in any other
    status is refused with `ERR_REVIEW_NOT_DISPUTABLE`."
    PRD §3.7: "The review's `rebuttal_round_count` is set to that same round index, the
    review moves `SCORED → DISPUTED`, and its `version` is incremented."

    Design: Corner/state_machines/finalizing_a_selected_review_is_rejected
    """
    env = fx.selected_review_env(api)

    response = api.create_rebuttal(
        env["review_id"],
        f.rebuttal_payload(),
        make_dispatcher_headers(env["dispatcher_id"]),
    )
    validate_error(response, err.ERR_REVIEW_NOT_DISPUTABLE, 409)

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED"
    assert review["rebuttal_round_count"] == 0
    assert review["version"] == env["review"]["version"]
    assert fx.list_rebuttals_for(api, env["review_id"]) == []


def test_a_targeted_cardiac_arrest_review_is_born_selected_and_empty(api):
    """PRD §3.4: "Whichever route created it, a new review is born in `status` `SELECTED` with
    `current_sheet_round` at 0, with `provisional_composite_score`,
    `pre_penalty_composite_score`, `determinant_accuracy`, `penalty_points`,
    `final_composite_score` and `compliant` all null, with `rebuttal_round_count` at 0, and
    with no `scored_at`, `finalized_at`, `voided_at` or `void_reason`."
    PRD §3.4: "The second is `high_risk`, which is true when any one of three conditions
    holds — the call's `call_type` is `CARDIAC_ARREST`, or the call's
    `cardiac_arrest_confirmed` flag is true, or the level letter of the call's
    `dispatched_determinant_code` is `E` — and false otherwise."
    PRD §2.4: "Most resources additionally carry `updated_at`, in the same format, refreshed
    on every mutation of the row, and `version`, an integer that starts at 1 on creation and
    is incremented by 1 on every mutation of that row — including mutations the server
    performs on its own initiative as part of a cascade, not only those a client requests
    directly on that resource."

    Design: Corner/state_machines/a_new_targeted_review_starts_selected_with_no_sheets
    """
    env = fx.enrolled_dispatcher_env(api)
    call = fx.ingest_cardiac_arrest_call(api, env["dispatcher_id"], call_reference="C-0009")
    period = fx.new_period(
        api, env["program_id"], call_type="CARDIAC_ARREST", target_sample_count=2
    )

    data = validate_success(
        api.target_review(
            period["id"],
            f.target_review_payload(call["id"], selection_reason="HIGH_RISK_OUTCOME"),
            REVIEWER,
        ),
        201,
    )
    assert_common_fields(data, expected_version=1)
    assert data["status"] == "SELECTED"
    assert data["selection_mode"] == "TARGETED"
    assert data["current_sheet_round"] == 0
    assert data["rebuttal_round_count"] == 0
    for field in (
        "provisional_composite_score",
        "pre_penalty_composite_score",
        "penalty_points",
        "final_composite_score",
        "determinant_accuracy",
        "compliant",
        "scored_at",
        "finalized_at",
        "voided_at",
        "void_reason",
    ):
        assert data[field] is None, f"a newborn review must carry a null {field}"
    assert data["high_risk"] is True, "a CARDIAC_ARREST call is high risk"

    sheets, sheet_meta = validate_paginated(
        api.list_score_sheets(data["id"], SUPERVISOR, {"limit": 100})
    )
    assert sheets == [] and sheet_meta["total_count"] == 0
    clinical, clinical_meta = validate_paginated(
        api.list_high_risk_reviews(data["id"], REVIEWER, {"limit": 100})
    )
    assert clinical == [] and clinical_meta["total_count"] == 0


def test_a_voided_review_refuses_every_further_transition(api):
    """PRD §3.7: "A review may be voided from `SELECTED`, `SCORED`, `DISPUTED` or `FINALIZED`;
    a second attempt on an already-voided review is refused with
    `ERR_REVIEW_ALREADY_VOIDED`, and voiding a finalized review inside a `LOCKED` period is
    refused with `ERR_PERIOD_LOCKED`."
    PRD §3.5: "And no rebuttal on the review may still be sitting in `SUBMITTED` — while a
    dispute is undecided the sheet is out of the reviewer's hands, and an attempt to overwrite
    it, like any attempt to score a review that is not in `SELECTED` or `SCORED`, is rejected
    with `ERR_REVIEW_NOT_SCORABLE`."
    PRD §3.7: "The review must be in `SCORED`, and any other status is refused with
    `ERR_REVIEW_NOT_FINALIZABLE`."
    PRD §3.7: "Voiding from `SCORED` additionally clears `provisional_composite_score` to
    null."

    Design: Corner/state_machines/a_voided_review_cannot_be_scored_or_voided_again
    """
    env = fx.scored_review_env(
        api, sections=SHEET_78_7, reviewer_determinant_code="10-C-2"
    )
    voided = fx.void(api, env["review_id"], reason="AUDIO_UNAVAILABLE")
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "AUDIO_UNAVAILABLE"
    assert voided["provisional_composite_score"] is None

    validate_error(
        api.void_review(env["review_id"], {"void_reason": "DUPLICATE_CASE"}, SUPERVISOR),
        err.ERR_REVIEW_ALREADY_VOIDED,
        409,
    )
    validate_error(
        api.submit_scores(
            env["review_id"],
            f.section_score_payload(voided["version"], PERFECT_SHEET, "10-C-4"),
            REVIEWER,
        ),
        err.ERR_REVIEW_NOT_SCORABLE,
        409,
    )
    validate_error(
        api.finalize_review(
            env["review_id"], {"finalization_note": "attempt on a voided review"}, SUPERVISOR
        ),
        err.ERR_REVIEW_NOT_FINALIZABLE,
        409,
    )

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "VOIDED"
    assert review["void_reason"] == "AUDIO_UNAVAILABLE", "the first reason stands"
    assert review["version"] == voided["version"], "refusals leave the row untouched"
    assert len(fx.list_sheets(api, env["review_id"])) == 1


def test_deciding_the_same_rebuttal_twice_is_refused_and_changes_nothing(api):
    """PRD §3.7: "The rebuttal must still be in `SUBMITTED` — a second decision on an
    already-adjudicated rebuttal is refused with `ERR_REBUTTAL_ALREADY_DECIDED` — and its
    parent review must be in `DISPUTED`."
    PRD §3.7: "Upholding takes the rebuttal `SUBMITTED → UPHELD`, records
    `decided_by_user_id`, and sends the review backwards: `DISPUTED → SELECTED`, with
    `provisional_composite_score` and `scored_at` both cleared to null because the case must
    be scored again from scratch."
    PRD §3.7: "The review's `current_sheet_round` is deliberately **not** rewound — the
    invalidated sheet stays in the append-only audit log, and the replacement sheet will carry
    the next round number up."

    Design: Corner/state_machines/deciding_the_same_rebuttal_twice_is_rejected
    """
    env = fx.scored_review_env(
        api, sections=SHEET_78_7, reviewer_determinant_code="10-C-2"
    )
    rebuttal = fx.file_rebuttal(
        api,
        env["review_id"],
        env["dispatcher_id"],
        grounds_category="SCORING_DISPUTE",
        narrative="key-question credit was withheld twice for one omission",
    )
    upheld = fx.decide_rebuttal(
        api, rebuttal["id"], "UPHELD", "double deduction confirmed"
    )
    assert upheld["status"] == "UPHELD"
    after_first = fx.get_review(api, env["review_id"])
    assert after_first["status"] == "SELECTED"
    assert after_first["provisional_composite_score"] is None
    assert after_first["current_sheet_round"] == 1, "the round counter is not rewound"

    validate_error(
        api.decide_rebuttal(
            rebuttal["id"],
            f.rebuttal_decision_payload("REJECTED", decision_notes="changed my mind"),
            SUPERVISOR,
        ),
        err.ERR_REBUTTAL_ALREADY_DECIDED,
        409,
    )

    rebuttals = fx.list_rebuttals_for(api, env["review_id"])
    assert len(rebuttals) == 1
    assert rebuttals[0]["status"] == "UPHELD", "the first decision stands"
    assert rebuttals[0]["decision_notes"] == "double deduction confirmed"

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED"
    assert review["provisional_composite_score"] is None
    assert review["rebuttal_round_count"] == 1, "a refused decision consumes no round"
    assert review["version"] == after_first["version"]


def test_certification_recomputes_the_rollouts_training_dimension(api):
    """PRD §3.3: "A new rollout has `golive_status` of `SCHEDULED`, no `went_live_at`, and a
    `trained_dispatcher_count` and `training_status` computed immediately from whoever is
    already certified — normally `NOT_STARTED`, but `IN_PROGRESS` or `COMPLETE` if
    certifications already exist on that version."
    PRD §3.3: "The training dimension takes the values `NOT_STARTED`, `IN_PROGRESS` and
    `COMPLETE`, is entirely derived, and may move in both directions."
    PRD §3.3: "When that count is 0 the training dimension reads `NOT_STARTED`; when it is at
    or above `target_dispatcher_count` it reads `COMPLETE`, so hitting the target exactly is
    enough; anything between reads `IN_PROGRESS`."
    PRD §3.3: "The go-live dimension takes the values `SCHEDULED` and `LIVE`, advances only by
    an explicit go-live request, and is one-way."
    PRD §3.3: "A successful certification moves `certification_status` from `PROVISIONAL →
    CERTIFIED`, or from `LAPSED → CERTIFIED` when it is a re-certification onto a newer
    version, sets `certified_protocol_version_id` and `certified_at`, and then bubbles upward:
    every rollout on the target version — and, on a re-certification, every rollout on the
    version the dispatcher is leaving — recomputes its `trained_dispatcher_count` and
    re-derives its `training_status`, which is how a rollout crosses `TRAINING_NOT_STARTED →
    TRAINING_IN_PROGRESS` on the first certification and `TRAINING_IN_PROGRESS →
    TRAINING_COMPLETE` on the one that reaches the target."
    PRD §3.8: "Otherwise it is `FULL`."

    Design: Corner/state_machines/certifying_a_dispatcher_advances_the_rollout_training_counters
    """
    program = fx.new_program(api, name="Basin EMD QA", accreditation_body="IAED")
    version = fx.new_approved_version(
        api,
        program["id"],
        version_label="MPDS-14.0",
        effective_from="2026-09-01T00:00:00Z",
    )
    rollout = fx.new_rollout(
        api,
        version["id"],
        scheduled_golive_at="2026-09-01T00:00:00Z",
        target_dispatcher_count=2,
        required_training_hours=4.0,
    )
    assert rollout["trained_dispatcher_count"] == 0
    assert rollout["training_status"] == "NOT_STARTED"
    assert rollout["golive_status"] == "SCHEDULED"
    assert rollout["went_live_at"] is None

    first = fx.new_dispatcher(api, program["id"], employee_code="EMD-001", full_name="Ada Rune")
    second = fx.new_dispatcher(
        api, program["id"], employee_code="EMD-002", full_name="Bo Wexler"
    )

    certified_first = fx.certify(api, first["id"], version["id"])
    after_one = fx.get_rollout(api, version["id"], rollout["id"])
    assert after_one["trained_dispatcher_count"] == 1
    assert after_one["training_status"] == "IN_PROGRESS"
    assert after_one["golive_status"] == "SCHEDULED", "training never touches go-live"
    assert after_one["went_live_at"] is None

    fx.certify(api, second["id"], version["id"])
    after_two = fx.get_rollout(api, version["id"], rollout["id"])
    assert after_two["trained_dispatcher_count"] == 2
    assert after_two["training_status"] == "COMPLETE", "hitting the target exactly completes"
    assert after_two["golive_status"] == "SCHEDULED"
    assert after_two["went_live_at"] is None

    assert certified_first["certification_status"] == "CERTIFIED"
    assert certified_first["certified_protocol_version_id"] == version["id"]
    assert certified_first["certified_at"] is not None
    assert certified_first["dispatch_privilege"] == "FULL"
    stored_first = fx.get_dispatcher(api, first["id"])
    assert stored_first["certification_status"] == "CERTIFIED"
    assert stored_first["certified_protocol_version_id"] == version["id"]
    assert stored_first["dispatch_privilege"] == "FULL"
