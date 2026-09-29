"""Immediate visibility of the finalization cascade.

Every derived value the finalize cascade touches — the review's own scoring
fields, the dispatcher's compliance ledger and posture, the automatic coaching
plan, the owed-hours ledger, the dispatch privilege and the sampling period's
counters — must already be reconciled in the very response that triggered the
cascade and in the reads taken straight after it, with no second write and no
settling delay.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.assertions import approx1, approx2, assert_instant_equals, plus_days

CLOCK = "2026-08-20T00:00:00Z"

# 18/20, 26/30, 2/3 and 5/7 give section percentages of 90.00, 86.67, 66.67 and
# 71.43, whose weighted sum under the pinned 0.20/0.35/0.30/0.15 weights is
# 79.05 and rounds half up to a pre-penalty composite of 79.1.
SECTIONS = {
    "case_entry": (18, 20),
    "key_questions": (26, 30),
    "pre_arrival": (2, 3),
    "final_coding": (5, 7),
}


def test_every_cascade_effect_is_visible_inside_the_same_response(api):
    """PRD §2.8: "A large fraction of the fields in this system are derived rather
    than supplied, and the governing rule for all of them is **full recomputation
    from source rows, never incremental adjustment**."
    PRD §2.8: "Cascade A fires on finalization and runs from the review's own
    scoring fields out through the dispatcher's ledgers, posture, automatic
    coaching plan, owed hours and dispatch privilege."
    PRD §3.7: "The four already-rounded section percentages of the **current**
    sheet — the one whose `sheet_round` equals the review's `current_sheet_round`,
    superseded sheets being excluded entirely — are each multiplied by the
    corresponding weight on the review's pinned protocol version, the four
    products are summed, and the total is rounded half up to 1 decimal place to
    give `pre_penalty_composite_score`."
    PRD §3.7: "Second, a tier multiplier is selected **from the pre-penalty score,
    never from the post-penalty result**: a pre-penalty score at or above 90.0
    selects the high tier and multiplies the base by 1.5, a pre-penalty score at
    or above 75.0 but below 90.0 selects the mid tier and multiplies by 1.0, and
    anything below 75.0 selects the low tier and multiplies by 0.5."
    PRD §3.7: "`compliant` is true when `final_composite_score` is at or above the
    programme's `target_compliance_pct` and false otherwise."
    PRD §3.7: "The sampling period's `finalized_review_count` is recomputed as the
    count of finalized reviews in the period."
    PRD §3.7: "The automatic coaching plan described in §3.8 is then created or
    upgraded, `remediation_hours_owed` is recomputed, and `dispatch_privilege` is
    re-derived — landing on `RESTRICTED` as soon as the owed hours exceed the
    programme's `hours_owed_restriction_threshold`."
    PRD §3.8: "Otherwise, when the dispatcher's freshly recomputed
    `compliance_posture` is `PROBATION`, the plan is `STANDARD` and targets the
    weakest section."
    PRD §3.8: "When the upsert finds no existing automatic plan on the key —
    considering only plans in `ASSIGNED`, `IN_PROGRESS`, `SUSPENDED` or `VERIFIED`
    — it creates one with `origin` `AUTO`, the chosen severity and focus, the
    matching `severity_rank` and `required_hours`, `credited_hours` at 0.00,
    `status` `ASSIGNED`, no `closure_reason`, no `verified_at`, and a `due_at` set
    30 days after the logical clock."
    PRD §3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater**
    than the programme's `hours_owed_restriction_threshold`, the privilege is
    `RESTRICTED` — owing exactly the threshold leaves a dispatcher at `FULL`."

    Design: Corner/consistency_model/every_cascade_effect_is_visible_inside_the_same_response
    """
    env = fx.scored_review_env(
        api,
        sections=SECTIONS,
        reviewer_determinant_code="10-C-2",
        clock=CLOCK,
    )
    sheet = env["sheet"]
    assert sheet["case_entry_pct"] == approx2(90.00)
    assert sheet["key_questions_pct"] == approx2(86.67)
    assert sheet["pre_arrival_pct"] == approx2(66.67)
    assert sheet["final_coding_pct"] == approx2(71.43)
    assert sheet["determinant_accuracy"] == "MINOR_MISCODE", (
        "10-C-2 against a dispatched 10-C-4 keeps both the response mode and the "
        "resource tier, so the miscode had no operational consequence"
    )
    assert sheet["provisional_composite_score"] == approx1(78.7), (
        "the unweighted view is the mean of the four rounded percentages"
    )

    finalized = validate_success(
        api.finalize_review(
            env["review_id"], {"finalization_note": "cascade in one shot"}, u.SUPERVISOR
        ),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["pre_penalty_composite_score"] == approx1(79.1)
    assert finalized["penalty_points"] == approx1(2.0), (
        "the mid tier multiplier of 1.0 is chosen from the 79.1 pre-penalty score"
    )
    assert finalized["final_composite_score"] == approx1(77.1)
    assert finalized["compliant"] is False
    assert finalized["determinant_accuracy"] == "MINOR_MISCODE"
    assert_instant_equals(finalized["finalized_at"], CLOCK)

    ledger = validate_success(api.get_dispatcher(env["dispatcher_id"], u.SUPERVISOR), 200)
    assert ledger["reviewed_case_count"] == 1
    assert ledger["compliance_points_total"] == approx1(77.1)
    assert ledger["compliance_pct"] == approx1(77.1)
    assert ledger["compliance_posture"] == "PROBATION", (
        "77.1 is below the 80.0 watch floor"
    )
    assert ledger["remediation_hours_owed"] == approx2(4.00), (
        "the automatic plan is already open and owing its full 4.0 hours"
    )
    assert ledger["dispatch_privilege"] == "FULL", (
        "4.00 owed hours does not exceed the 6.0-hour restriction threshold"
    )

    plans, plan_meta = validate_paginated(
        api.list_coaching_plans(
            u.SUPERVISOR,
            {"dispatcher_id": env["dispatcher_id"], "origin": "AUTO", "limit": 10, "offset": 0},
        )
    )
    assert plan_meta["total_count"] == 1, (
        "the plan exists before any further request is made"
    )
    plan = plans[0]
    assert plan["status"] == "ASSIGNED"
    assert plan["origin"] == "AUTO"
    assert plan["severity"] == "STANDARD"
    assert plan["severity_rank"] == 2
    assert plan["required_hours"] == approx1(4.0)
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["focus_area"] == "PRE_ARRIVAL_INSTRUCTIONS", (
        "pre-arrival at 66.67 is the weakest of the four sections"
    )
    assert plan["source_review_id"] == env["review_id"]
    assert plan["closure_reason"] is None
    assert plan["verified_at"] is None
    assert_instant_equals(plan["due_at"], plus_days(CLOCK, 30))

    periods, period_meta = validate_paginated(
        api.list_sampling_periods(
            env["program_id"], u.SUPERVISOR, {"status": "OPEN", "limit": 10, "offset": 0}
        )
    )
    assert period_meta["total_count"] == 1
    assert periods[0]["id"] == env["period_id"]
    assert periods[0]["finalized_review_count"] == 1
    assert periods[0]["selected_review_count"] == 1

    repeated = validate_success(api.get_dispatcher(env["dispatcher_id"], u.SUPERVISOR), 200)
    assert repeated == ledger, (
        "a settled cascade does not shift between two identical reads"
    )
