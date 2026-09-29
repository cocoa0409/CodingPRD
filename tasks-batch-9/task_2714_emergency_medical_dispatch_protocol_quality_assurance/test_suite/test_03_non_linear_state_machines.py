"""State machines that move sideways and backwards.

A dispute that sends a scored review back to the beginning without rewinding its
audit log, a rollout whose training dimension regresses while its go-live
dimension stays put, and a clinical sign-off whose two classifications reach into
disjoint sets of downstream rows.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2, assert_instant_equals
from test_helpers.test_users import ADMIN

DISPUTED_SHEET = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}
PERFECT_SHEET = {
    "case_entry": (20, 20),
    "key_questions": (30, 30),
    "pre_arrival": (10, 10),
    "final_coding": (10, 10),
}
DISPUTE_PROGRAM = {
    "target_compliance_pct": 90.0,
    "watch_floor_pct": 80.0,
    "rebuttal_window_days": 14,
    "max_rebuttal_rounds": 2,
}


def _disputed_review_env(api):
    """One scored review at 78.7 with a dispute from its own dispatcher pending."""
    env = fx.scored_review_env(
        api,
        sections=DISPUTED_SHEET,
        reviewer_determinant_code="10-C-4",
        program_overrides=dict(DISPUTE_PROGRAM),
    )
    env["rebuttal"] = fx.file_rebuttal(
        api,
        env["review_id"],
        env["dispatcher_id"],
        grounds_category="PROTOCOL_AMBIGUITY",
        narrative="The card set does not say which pre-arrival panel applies here.",
    )
    env["rebuttal_id"] = env["rebuttal"]["id"]
    return env


def test_upholding_a_dispute_sends_the_review_back_and_clears_its_score(api):
    """PRD 3.7: "Upholding takes the rebuttal `SUBMITTED → UPHELD`, records
    `decided_by_user_id`, and sends the review backwards: `DISPUTED → SELECTED`, with
    `provisional_composite_score` and `scored_at` both cleared to null because the
    case must be scored again from scratch."
    PRD 3.7: "The review's `current_sheet_round` is deliberately **not** rewound —
    the invalidated sheet stays in the append-only audit log, and the replacement
    sheet will carry the next round number up."

    Design: Difficulty/non_linear_state_machine/upheld_rebuttal_returns_review_to_selected_and_clears_the_score
    """
    env = _disputed_review_env(api)

    before = fx.get_review(api, env["review_id"])
    assert before["status"] == "DISPUTED"
    assert before["provisional_composite_score"] == approx1(78.7)
    assert before["rebuttal_round_count"] == 1

    decided = fx.decide_rebuttal(api, env["rebuttal_id"], "UPHELD", "Card set is genuinely unclear.")
    assert decided["status"] == "UPHELD"
    assert decided["decided_by_user_id"] is not None

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SELECTED", "an upheld dispute sends the review backwards"
    assert review["provisional_composite_score"] is None
    assert review["scored_at"] is None
    assert review["current_sheet_round"] == 1, (
        "the sheet round is not rewound, so the replacement sheet takes round 2"
    )
    assert review["rebuttal_round_count"] == 1, "the consumed dispute round is not returned"


def test_the_replacement_sheet_takes_the_next_round_and_leaves_the_old_one_intact(api):
    """PRD 3.5: "Sheets themselves are **append-only**: each submission creates a new
    score sheet whose `sheet_round` is one greater than the review's
    `current_sheet_round` at the moment of submission, and no earlier sheet is ever
    mutated or deleted."
    PRD 3.7: "The review's `current_sheet_round` is deliberately **not** rewound —
    the invalidated sheet stays in the append-only audit log, and the replacement
    sheet will carry the next round number up."

    Design: Difficulty/non_linear_state_machine/upheld_rebuttal_returns_review_to_selected_and_clears_the_score
    """
    env = _disputed_review_env(api)
    fx.decide_rebuttal(api, env["rebuttal_id"], "UPHELD", "Rescore the case.")

    replacement = fx.score(api, env["review_id"], sections=PERFECT_SHEET)
    assert replacement["sheet_round"] == 2
    assert replacement["provisional_composite_score"] == approx1(100.0)

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SCORED"
    assert review["current_sheet_round"] == 2
    assert review["provisional_composite_score"] == approx1(100.0)
    assert review["rebuttal_round_count"] == 1

    sheets = fx.list_sheets(api, env["review_id"])
    assert len(sheets) == 2, "the invalidated sheet is still in the audit log"
    by_round = {sheet["sheet_round"]: sheet for sheet in sheets}
    assert sorted(by_round) == [1, 2]
    assert by_round[1]["provisional_composite_score"] == approx1(78.7), (
        "the superseded round 1 sheet keeps the score that was disputed"
    )
    assert by_round[1]["pre_arrival_pct"] == approx2(66.67)


def test_rejecting_the_same_dispute_leaves_the_score_standing(api):
    """PRD 3.7: "Rejecting takes the rebuttal `SUBMITTED → REJECTED`, records
    `decided_by_user_id`, and returns the review `DISPUTED → SCORED` with its
    `provisional_composite_score` and `scored_at` preserved intact, because the
    existing sheet stands."

    Design: Difficulty/non_linear_state_machine/upheld_rebuttal_returns_review_to_selected_and_clears_the_score
    """
    env = _disputed_review_env(api)
    scored_at_before = fx.get_review(api, env["review_id"])["scored_at"]
    assert scored_at_before is not None

    decided = fx.decide_rebuttal(api, env["rebuttal_id"], "REJECTED", "Audio confirms the marks.")
    assert decided["status"] == "REJECTED"

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "SCORED", "a rejected dispute returns the review to SCORED"
    assert review["provisional_composite_score"] == approx1(78.7)
    assert_instant_equals(review["scored_at"], scored_at_before)
    assert review["current_sheet_round"] == 1
    assert len(fx.list_sheets(api, env["review_id"])) == 1, "no new sheet is written"


def test_a_successor_go_live_regresses_the_predecessor_rollout_training_only(api):
    """PRD 3.3: "The go-live guard reads the training dimension, but the training
    dimension never reads go-live: a rollout that has already gone live will still see
    its `training_status` regress to `NOT_STARTED` if every certification on its
    version subsequently lapses."
    PRD 3.3: "The fifth link recomputes `trained_dispatcher_count` and
    `training_status` on every rollout of the superseded version, so a rollout that
    read `TRAINING_COMPLETE` regresses to `TRAINING_NOT_STARTED` once its count
    reaches zero, even though its own `golive_status` remains `LIVE`."

    Design: Difficulty/non_linear_state_machine/rollout_training_dimension_regresses_while_golive_dimension_stays_live
    """
    env = fx.two_version_golive_env(api)

    before = fx.get_rollout(api, env["v1_id"], env["ro1_id"])
    assert before["golive_status"] == "LIVE"
    assert before["training_status"] == "COMPLETE"
    assert before["trained_dispatcher_count"] == 1

    validate_success(
        api.go_live(env["ro2_id"], {"golive_note": "card set 13.1 in force"}, ADMIN),
        expected_status=200,
    )

    assert fx.get_version(api, env["v2_id"])["status"] == "ACTIVE"
    assert fx.get_version(api, env["v1_id"])["status"] == "SUPERSEDED"
    assert fx.get_dispatcher(api, env["d1_id"])["certification_status"] == "LAPSED"

    after = fx.get_rollout(api, env["v1_id"], env["ro1_id"])
    assert after["trained_dispatcher_count"] == 0, "the only certified dispatcher lapsed"
    assert after["training_status"] == "NOT_STARTED", (
        "a count of 0 puts the training dimension back at its starting value"
    )
    assert after["golive_status"] == "LIVE", (
        "the go-live dimension is one-way and does not follow the training dimension back"
    )
    assert after["went_live_at"] is not None


def test_the_successor_rollout_carries_both_dimensions_forward(api):
    """PRD 3.3: "When all four hold, the rollout crosses `GOLIVE_SCHEDULED →
    GOLIVE_LIVE`, `went_live_at` is stamped from the logical clock, and Cascade B runs
    in five links."
    PRD 3.3: "When that count is 0 the training dimension reads `NOT_STARTED`; when it
    is at or above `target_dispatcher_count` it reads `COMPLETE`, so hitting the target
    exactly is enough; anything between reads `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/rollout_training_dimension_regresses_while_golive_dimension_stays_live
    """
    env = fx.two_version_golive_env(api)

    validate_success(
        api.go_live(env["ro2_id"], {"golive_note": "card set 13.1 in force"}, ADMIN),
        expected_status=200,
    )

    rollout = fx.get_rollout(api, env["v2_id"], env["ro2_id"])
    assert rollout["golive_status"] == "LIVE"
    assert_instant_equals(rollout["went_live_at"], fx.WORKING_CLOCK)
    assert rollout["trained_dispatcher_count"] == 1
    assert rollout["training_status"] == "COMPLETE", (
        "the dispatcher certified on the successor version is untouched by the cascade"
    )
    assert fx.get_dispatcher(api, env["d2_id"])["certification_status"] == "CERTIFIED"


def test_a_lapsed_dispatcher_keeps_the_old_version_pointer_but_stops_counting(api):
    """PRD 3.3: "The third link sweeps every dispatcher whose
    `certified_protocol_version_id` is that superseded version and whose
    `certification_status` is `CERTIFIED`, taking each `CERTIFIED → LAPSED` while
    retaining the old `certified_protocol_version_id` for audit."
    PRD 3.3: "Its input is `trained_dispatcher_count`, the number of dispatchers whose
    `certified_protocol_version_id` is this rollout's version and whose
    `certification_status` is exactly `CERTIFIED` — dispatchers who are `PROVISIONAL`
    or `LAPSED` do not count, no matter what version they were last certified on."
    PRD 3.3: "The fourth link, because those dispatchers are no longer certified, moves
    every one of their coaching plans in `ASSIGNED` or `IN_PROGRESS` to `SUSPENDED` —
    the unmet hours on a suspended plan stay in the owed ledger, and no session may be
    scheduled or completed while a plan is suspended — and re-derives each affected
    dispatcher's `dispatch_privilege`, which lands on `RESTRICTED` on the strength of
    the lapsed certification alone."

    Design: Difficulty/non_linear_state_machine/rollout_training_dimension_regresses_while_golive_dimension_stays_live
    """
    env = fx.two_version_golive_env(api)

    validate_success(
        api.go_live(env["ro2_id"], {"golive_note": "card set 13.1 in force"}, ADMIN),
        expected_status=200,
    )

    lapsed = fx.get_dispatcher(api, env["d1_id"])
    assert lapsed["certification_status"] == "LAPSED"
    assert lapsed["certified_protocol_version_id"] == env["v1_id"], (
        "the pointer to the superseded version is retained for audit"
    )
    assert lapsed["dispatch_privilege"] == "RESTRICTED"

    rollout = fx.get_rollout(api, env["v1_id"], env["ro1_id"])
    assert rollout["target_dispatcher_count"] == 1
    assert rollout["trained_dispatcher_count"] == 0, (
        "the retained pointer does not keep a lapsed dispatcher in the trained count"
    )
    assert rollout["training_status"] == "NOT_STARTED"


SIGN_OFF_PROGRAM = {
    "target_compliance_pct": 90.0,
    "watch_floor_pct": 80.0,
    "high_risk_target_pct": 85.0,
    "hours_owed_restriction_threshold": 6.0,
}
FAILED_RECOGNITION = {
    "cardiac_arrest_recognized": False,
    "recognition_time_sec": 0,
    "time_to_first_compression_sec": 0,
    "dacpr_instructions_delivered": False,
    "compressions_coached": False,
}
STRONG_RESUSCITATION = {
    "cardiac_arrest_recognized": True,
    "recognition_time_sec": 15,
    "time_to_first_compression_sec": 45,
    "dacpr_instructions_delivered": True,
    "compressions_coached": True,
}


def _two_branch_high_risk_env(api):
    """Two cardiac-arrest cases on two dispatchers, both DA-CPR scored and unsigned.

    Dispatcher X missed the arrest entirely, so their index is gated to 0.0; dispatcher
    Y ran a strong resuscitation and passes on the index.
    """
    env = fx.program_with_version(api, program_overrides=dict(SIGN_OFF_PROGRAM))
    dx = fx.new_dispatcher(api, env["program_id"])
    dy = fx.new_dispatcher(api, env["program_id"])
    call_x = fx.ingest_cardiac_arrest_call(api, dx["id"], received_at="2026-08-05T09:00:00Z")
    call_y = fx.ingest_cardiac_arrest_call(api, dy["id"], received_at="2026-08-06T09:00:00Z")
    period = fx.new_period(
        api, env["program_id"], call_type="CARDIAC_ARREST", target_sample_count=2
    )
    review_x = fx.target(api, period["id"], call_x["id"], "SENTINEL_FLAG")
    review_y = fx.target(api, period["id"], call_y["id"], "HIGH_RISK_OUTCOME")
    hr_x = fx.new_high_risk_review(api, review_x["id"], "NO_ROSC")
    hr_y = fx.new_high_risk_review(api, review_y["id"], "ROSC_FIELD")
    fx.score_dacpr(api, hr_x["id"], **FAILED_RECOGNITION)
    fx.score_dacpr(api, hr_y["id"], **STRONG_RESUSCITATION)
    env.update(
        {
            "dx_id": dx["id"],
            "dy_id": dy["id"],
            "review_x_id": review_x["id"],
            "review_y_id": review_y["id"],
            "hr_x_id": hr_x["id"],
            "hr_y_id": hr_y["id"],
        }
    )
    return env


def test_sentinel_signoff_creates_the_critical_plan_and_restricts_the_dispatcher(api):
    """PRD 3.6: "Classifying a case as a sentinel event takes the record `DACPR_SCORED
    → SENTINEL_EVENT`. Exclusively on this branch, an automatic coaching plan of
    `CRITICAL` severity carrying 8.0 required hours and a `focus_area` of `DACPR` is
    created or upgraded for the dispatcher against this review, and the sentinel
    counters are recomputed — both the dispatcher's own `sentinel_event_count` and the
    programme's `sentinel_event_count`."
    PRD 3.6: "Because the hours ledger and the sentinel count have both moved, the
    dispatcher's `remediation_hours_owed` is recomputed and their `dispatch_privilege`
    re-derived, and a first sentinel event alone is sufficient to pull that privilege
    down to `RESTRICTED`."
    PRD 3.6: "When `cardiac_arrest_recognized` is false, `compression_compliant` is set
    to false, `dacpr_index` is set to 0.0, `dacpr_pass` is set to false, and no further
    arithmetic is performed."

    Design: Difficulty/non_linear_state_machine/high_risk_signoff_branches_into_disjoint_sentinel_and_coaching_only_effects
    """
    env = _two_branch_high_risk_env(api)

    signed = fx.sign_off(api, env["hr_x_id"], "SENTINEL_EVENT", "Arrest never recognised.")
    assert signed["status"] == "SENTINEL_EVENT"
    assert signed["classification"] == "SENTINEL_EVENT"
    assert signed["dacpr_index"] == approx1(0.0)
    assert signed["dacpr_pass"] is False
    assert signed["signed_off_at"] is not None

    dispatcher = fx.get_dispatcher(api, env["dx_id"])
    assert dispatcher["sentinel_event_count"] == 1
    assert dispatcher["remediation_hours_owed"] == approx2(8.00)
    assert dispatcher["dispatch_privilege"] == "RESTRICTED"

    plans = fx.list_plans_for(api, env["dx_id"])
    assert len(plans) == 1, f"expected exactly one automatic plan, got {len(plans)}"
    plan = plans[0]
    assert plan["origin"] == "AUTO"
    assert plan["severity"] == "CRITICAL"
    assert plan["severity_rank"] == 3
    assert plan["focus_area"] == "DACPR"
    assert plan["required_hours"] == approx1(8.0)
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["status"] == "ASSIGNED"
    assert plan["source_review_id"] == env["review_x_id"]


def test_coaching_only_signoff_on_a_passing_case_touches_nothing(api):
    """PRD 3.6: "Classifying a case as coaching-only takes the record `DACPR_SCORED →
    COACHING_ONLY`, and it is gated: a record whose `dacpr_index` is below 50.0 is too
    poor a performance to close as a coaching matter, and an attempt to do so is refused
    with `ERR_SENTINEL_CLASSIFICATION_REQUIRED` — below that floor the classification
    must be `SENTINEL_EVENT`."
    PRD 3.6: "Exclusively on this branch, an `ADVISORY` automatic coaching plan
    carrying 2.0 required hours and a `focus_area` of `DACPR` is created or upgraded
    **only when `dacpr_pass` is false**; when the case passed on the index, no plan is
    created at all."
    PRD 3.6: "Also exclusively on this branch, the sentinel counters are not touched and
    `dispatch_privilege` is unaffected by the classification itself."

    Design: Difficulty/non_linear_state_machine/high_risk_signoff_branches_into_disjoint_sentinel_and_coaching_only_effects
    """
    env = _two_branch_high_risk_env(api)

    signed = fx.sign_off(api, env["hr_y_id"], "COACHING_ONLY", "Strong case, minor notes.")
    assert signed["status"] == "COACHING_ONLY"
    assert signed["classification"] == "COACHING_ONLY"
    assert signed["dacpr_index"] == approx1(85.8)
    assert signed["dacpr_pass"] is True

    dispatcher = fx.get_dispatcher(api, env["dy_id"])
    assert dispatcher["sentinel_event_count"] == 0, "the coaching branch never counts a sentinel"
    assert dispatcher["remediation_hours_owed"] == approx2(0.00)
    assert dispatcher["dispatch_privilege"] == "FULL"

    assert fx.list_plans_for(api, env["dy_id"]) == [], (
        "a case that passed on the index earns no automatic plan"
    )


def test_the_two_branches_reach_disjoint_rows_within_one_programme(api):
    """PRD 3.6: "The two branches then diverge sharply, and the difference is the whole
    point of the clinical review."
    PRD 3.6: "Also exclusively on this branch, the sentinel counters are not touched and
    `dispatch_privilege` is unaffected by the classification itself."
    PRD 3.6: "Sentinel counting deliberately does not wait for the parent review to be
    finalized: a signed-off sentinel event restricts the dispatcher from the moment of
    sign-off, and only voiding the underlying review removes it."

    Design: Difficulty/non_linear_state_machine/high_risk_signoff_branches_into_disjoint_sentinel_and_coaching_only_effects
    """
    env = _two_branch_high_risk_env(api)

    fx.sign_off(api, env["hr_x_id"], "SENTINEL_EVENT", "Arrest never recognised.")
    fx.sign_off(api, env["hr_y_id"], "COACHING_ONLY", "Strong case, minor notes.")

    program = fx.get_program(api, env["program_id"])
    assert program["sentinel_event_count"] == 1, (
        "only the sentinel branch moved the programme counter"
    )

    dx = fx.get_dispatcher(api, env["dx_id"])
    dy = fx.get_dispatcher(api, env["dy_id"])
    assert (dx["sentinel_event_count"], dx["dispatch_privilege"]) == (1, "RESTRICTED")
    assert (dy["sentinel_event_count"], dy["dispatch_privilege"]) == (0, "FULL")
    assert len(fx.list_plans_for(api, env["dx_id"])) == 1
    assert fx.list_plans_for(api, env["dy_id"]) == []

    assert fx.get_review(api, env["review_x_id"])["status"] == "SELECTED", (
        "neither sign-off finalizes the parent review"
    )
    assert fx.get_review(api, env["review_y_id"])["status"] == "SELECTED"
