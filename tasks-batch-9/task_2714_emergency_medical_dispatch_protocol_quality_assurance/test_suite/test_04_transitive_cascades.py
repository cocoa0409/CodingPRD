"""Multi-link cascades: finalization out to the dispatch privilege, protocol
go-live back through certifications and coaching plans, and the filing of an
accreditation report forward into period locking.

Every test here triggers exactly one write and then walks the chain of rows the
PRD says that single write must reach.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import fixtures as fx
from test_helpers.assertions import approx1, approx2, assert_instant_equals
from test_helpers.test_users import ADMIN, OFFICER

CLOCK = "2026-08-20T00:00:00Z"


# ---------------------------------------------------------------------------
# Finalizing one under-triaged review reaches the dispatcher's privilege
# ---------------------------------------------------------------------------
def test_under_triaged_finalization_penalises_the_sheet_at_the_high_tier(api):
    """PRD §3.7: "Second, a tier multiplier is selected **from the pre-penalty score,
    never from the post-penalty result**: a pre-penalty score at or above 90.0 selects
    the high tier and multiplies the base by 1.5, a pre-penalty score at or above 75.0
    but below 90.0 selects the mid tier and multiplies by 1.0, and anything below 75.0
    selects the low tier and multiplies by 0.5."
    PRD §3.7: "`final_composite_score` is the pre-penalty score less the penalty points,
    floored at 0.0 so it can never go negative, rounded half up to 1 decimal place."
    PRD §3.7: "`compliant` is true when `final_composite_score` is at or above the
    programme's `target_compliance_pct` and false otherwise."

    Design: Difficulty/transitive_cascade/finalizing_one_under_triaged_review_restricts_the_dispatcher_five_links_later
    """
    env = fx.under_triage_finalized_env(api)

    review = fx.get_review(api, env["review_id"])
    assert review["status"] == "FINALIZED", f"expected FINALIZED, got {review['status']}"
    assert review["pre_penalty_composite_score"] == approx1(90.0)
    assert review["determinant_accuracy"] == "UNDER_TRIAGE"
    # base 10.0 for under-triage, high tier multiplier 1.5 on a 90.0 pre-penalty sheet
    assert review["penalty_points"] == approx1(15.0)
    assert review["final_composite_score"] == approx1(75.0)
    assert review["compliant"] is False, "75.0 is below the 90.0 target, so compliant is false"
    assert_instant_equals(review["finalized_at"], CLOCK)


def test_under_triage_is_classified_from_the_deviation_direction(api):
    """PRD §3.5: "Two deviation flags then compare the two decodings:
    `response_mode_deviation` is true when the reviewer's response mode differs from the
    call's `response_mode_assigned`, and `resource_deviation` is true when the reviewer's
    resource tier differs from the call's `resource_assigned`."
    PRD §3.5: "Otherwise there is a real deviation, and its direction decides: when the
    reviewer's priority rank is greater than the dispatched rank, the correct code was
    more acute than the one sent and the call was **under-triaged**, so the accuracy is
    `UNDER_TRIAGE`; when the reviewer's rank is lower, the call was sent hotter or heavier
    than it needed and the accuracy is `OVER_TRIAGE`."

    Design: Difficulty/transitive_cascade/finalizing_one_under_triaged_review_restricts_the_dispatcher_five_links_later
    """
    env = fx.under_triage_finalized_env(api)

    sheet = env["sheet"]
    # dispatched 10-C-4 is COLD/ALS at rank 4; the reviewer's 10-E-1 is HOT/ALS at rank 6
    assert sheet["reviewer_priority_rank"] == 6
    assert sheet["reviewer_response_mode"] == "HOT"
    assert sheet["reviewer_resource"] == "ALS"
    assert sheet["response_mode_deviation"] is True
    assert sheet["resource_deviation"] is False
    assert sheet["determinant_accuracy"] == "UNDER_TRIAGE"


def test_finalization_recomputes_the_dispatcher_ledger_and_drops_the_posture_to_probation(api):
    """PRD §3.7: "The dispatcher's compliance figures are recomputed from scratch over
    every review of theirs in `FINALIZED` — reviews in `SELECTED`, `SCORED`, `DISPUTED`
    or `VOIDED` contribute nothing: `reviewed_case_count` is the number of such reviews,
    `compliance_points_total` is the sum of their `final_composite_score` values rounded
    half up to 1 decimal place, and `compliance_pct` is that total divided by the count,
    rounded half up to 1 decimal place."
    PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at or
    above the programme's `target_compliance_pct`, `WATCH` when it is below that but at or
    above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a dispatcher
    with no finalized reviews is `UNRATED`."
    PRD §3.7: "The sampling period's `finalized_review_count` is recomputed as the count
    of finalized reviews in the period."

    Design: Difficulty/transitive_cascade/finalizing_one_under_triaged_review_restricts_the_dispatcher_five_links_later
    """
    env = fx.under_triage_finalized_env(api)

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["reviewed_case_count"] == 1
    assert dispatcher["compliance_points_total"] == approx1(75.0)
    assert dispatcher["compliance_pct"] == approx1(75.0)
    # 75.0 sits below the 80.0 watch floor, so the posture is PROBATION rather than WATCH
    assert dispatcher["compliance_posture"] == "PROBATION"

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["finalized_review_count"] == 1
    assert period["selected_review_count"] == 1


def test_finalization_creates_a_critical_plan_that_restricts_the_dispatch_privilege(api):
    """PRD §3.8: "When the finalized review's `determinant_accuracy` is `UNDER_TRIAGE`, or
    the clinical record's `classification` is `SENTINEL_EVENT`, the plan is `CRITICAL`, with
    a `focus_area` of `DETERMINANT_CODING` in the under-triage case and `DACPR` in the
    sentinel case."
    PRD §3.8: "Severity is not decorative: it fixes both `severity_rank` — 1 for `ADVISORY`,
    2 for `STANDARD`, 3 for `CRITICAL` — and `required_hours`, which is 2.0 hours for
    `ADVISORY`, 4.0 hours for `STANDARD`, and 8.0 hours for `CRITICAL`."
    PRD §3.8: "For each open plan the shortfall is the plan's `required_hours` less its
    `credited_hours`, floored at 0.00 so that over-delivery on one plan can never offset
    another plan's shortfall; `remediation_hours_owed` is the sum of those per-plan
    shortfalls, rounded half up to 2 decimal places."
    PRD §3.8: "Otherwise, when `remediation_hours_owed` is **strictly greater** than the
    programme's `hours_owed_restriction_threshold`, the privilege is `RESTRICTED` — owing
    exactly the threshold leaves a dispatcher at `FULL`."

    Design: Difficulty/transitive_cascade/finalizing_one_under_triaged_review_restricts_the_dispatcher_five_links_later
    """
    env = fx.under_triage_finalized_env(api)

    plans = fx.list_plans_for(api, env["dispatcher_id"])
    assert len(plans) == 1, f"expected exactly one automatic plan, got {len(plans)}"
    plan = plans[0]
    assert plan["origin"] == "AUTO"
    assert plan["severity"] == "CRITICAL"
    assert plan["severity_rank"] == 3
    assert plan["focus_area"] == "DETERMINANT_CODING"
    assert plan["required_hours"] == approx1(8.0)
    assert plan["credited_hours"] == approx2(0.00)
    assert plan["status"] == "ASSIGNED"
    assert plan["closure_reason"] is None
    assert plan["source_review_id"] == env["review_id"]

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["remediation_hours_owed"] == approx2(8.00)
    # 8.00 owed is strictly greater than the 6.0 threshold, so the privilege is curtailed
    assert dispatcher["dispatch_privilege"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# Go-live of the successor version reaches back to coaching plans
# ---------------------------------------------------------------------------
def _two_version_env_with_open_plan(api):
    """Two touching approved versions, the first live, and one open manual plan.

    The dispatcher certified on the first version carries a STANDARD manual plan
    owing 4.00 hours, which keeps their privilege at FULL while the plan is open.
    """
    env = fx.two_version_golive_env(api)
    plan = fx.new_coaching_plan(
        api, env["d1_id"], severity="STANDARD", focus_area="KEY_QUESTIONS"
    )
    env["plan1"] = plan
    env["plan1_id"] = plan["id"]
    return env


def test_golive_activates_the_new_version_and_supersedes_the_previous_active_one(api):
    """PRD §3.3: "When all four hold, the rollout crosses `GOLIVE_SCHEDULED → GOLIVE_LIVE`,
    `went_live_at` is stamped from the logical clock, and Cascade B runs in five links."
    PRD §3.3: "The first link takes the rollout's own version `APPROVED → ACTIVE` and
    stamps its `activated_at`."
    PRD §3.3: "The second link finds the version that was previously `ACTIVE` in the same
    programme and protocol family and takes it `ACTIVE → SUPERSEDED`, stamping
    `superseded_at` while leaving its declared `effective_to` untouched."

    Design: Difficulty/transitive_cascade/golive_of_the_successor_version_suspends_coaching_plans_five_links_upstream
    """
    env = _two_version_env_with_open_plan(api)

    validate_success(api.go_live(env["ro2_id"], {"golive_note": "v13.1 coordinated"}, ADMIN))

    rollout = fx.get_rollout(api, env["v2_id"], env["ro2_id"])
    assert rollout["golive_status"] == "LIVE"
    assert_instant_equals(rollout["went_live_at"], CLOCK)

    successor = fx.get_version(api, env["v2_id"])
    assert successor["status"] == "ACTIVE"
    assert_instant_equals(successor["activated_at"], CLOCK)

    predecessor = fx.get_version(api, env["v1_id"])
    assert predecessor["status"] == "SUPERSEDED"
    assert_instant_equals(predecessor["superseded_at"], CLOCK)
    # the declared interval is left exactly as registered
    assert_instant_equals(predecessor["effective_to"], "2026-09-01T00:00:00Z")


def test_golive_lapses_the_certification_and_suspends_the_open_coaching_plan(api):
    """PRD §3.3: "The third link sweeps every dispatcher whose
    `certified_protocol_version_id` is that superseded version and whose
    `certification_status` is `CERTIFIED`, taking each `CERTIFIED → LAPSED` while retaining
    the old `certified_protocol_version_id` for audit."
    PRD §3.3: "The fourth link, because those dispatchers are no longer certified, moves
    every one of their coaching plans in `ASSIGNED` or `IN_PROGRESS` to `SUSPENDED` — the
    unmet hours on a suspended plan stay in the owed ledger, and no session may be
    scheduled or completed while a plan is suspended — and re-derives each affected
    dispatcher's `dispatch_privilege`, which lands on `RESTRICTED` on the strength of the
    lapsed certification alone."
    PRD §3.8: "The owed-hours ledger itself is a full recomputation over the dispatcher's
    **open** plans — those in `ASSIGNED`, `IN_PROGRESS` or `SUSPENDED`, with `VERIFIED` and
    `CANCELLED` plans contributing nothing."

    Design: Difficulty/transitive_cascade/golive_of_the_successor_version_suspends_coaching_plans_five_links_upstream
    """
    env = _two_version_env_with_open_plan(api)

    before = fx.get_dispatcher(api, env["d1_id"])
    assert before["certification_status"] == "CERTIFIED"
    assert before["remediation_hours_owed"] == approx2(4.00)
    assert before["dispatch_privilege"] == "FULL", (
        "4.00 owed hours is below the 6.0 threshold and the certification still holds"
    )

    validate_success(api.go_live(env["ro2_id"], {"golive_note": "v13.1 coordinated"}, ADMIN))

    after = fx.get_dispatcher(api, env["d1_id"])
    assert after["certification_status"] == "LAPSED"
    assert after["certified_protocol_version_id"] == env["v1_id"], (
        "the old pointer is retained for audit"
    )

    plan = fx.get_plan(api, env["plan1_id"])
    assert plan["status"] == "SUSPENDED"
    assert plan["closure_reason"] is None

    # a SUSPENDED plan is still in the open set, so the ledger does not move
    assert after["remediation_hours_owed"] == approx2(4.00)
    # the hours are still under the threshold; the lapsed certification alone restricts
    assert after["dispatch_privilege"] == "RESTRICTED"


def test_golive_regresses_the_superseded_rollouts_training_but_not_its_golive_status(api):
    """PRD §3.3: "The fifth link recomputes `trained_dispatcher_count` and
    `training_status` on every rollout of the superseded version, so a rollout that read
    `TRAINING_COMPLETE` regresses to `TRAINING_NOT_STARTED` once its count reaches zero,
    even though its own `golive_status` remains `LIVE`."
    PRD §3.3: "Its input is `trained_dispatcher_count`, the number of dispatchers whose
    `certified_protocol_version_id` is this rollout's version and whose
    `certification_status` is exactly `CERTIFIED` — dispatchers who are `PROVISIONAL` or
    `LAPSED` do not count, no matter what version they were last certified on."

    Design: Difficulty/transitive_cascade/golive_of_the_successor_version_suspends_coaching_plans_five_links_upstream
    """
    env = _two_version_env_with_open_plan(api)

    old_rollout_before = fx.get_rollout(api, env["v1_id"], env["ro1_id"])
    assert old_rollout_before["trained_dispatcher_count"] == 1
    assert old_rollout_before["training_status"] == "COMPLETE"
    assert old_rollout_before["golive_status"] == "LIVE"

    validate_success(api.go_live(env["ro2_id"], {"golive_note": "v13.1 coordinated"}, ADMIN))

    old_rollout = fx.get_rollout(api, env["v1_id"], env["ro1_id"])
    assert old_rollout["trained_dispatcher_count"] == 0, (
        "the only certified dispatcher on that version has lapsed"
    )
    assert old_rollout["training_status"] == "NOT_STARTED"
    assert old_rollout["golive_status"] == "LIVE", "the go-live dimension is one-way"

    # the dispatcher certified on the newly activated version is untouched
    other = fx.get_dispatcher(api, env["d2_id"])
    assert other["certification_status"] == "CERTIFIED"
    assert other["dispatch_privilege"] == "FULL"


# ---------------------------------------------------------------------------
# Filing an accreditation report locks the periods it drew on
# ---------------------------------------------------------------------------
def test_filing_the_report_sets_the_programme_standing_and_locks_the_closed_period(api):
    """PRD §3.9: "Filing takes the report `DRAFT → SUBMITTED`, records the recipient and
    stamps `submitted_at` from the logical clock, and then Cascade C runs."
    PRD §3.9: "`submitted_report_count` is recomputed as the number of the programme's
    reports in `SUBMITTED`; draft reports never count."
    PRD §3.9: "`latest_compliance_pct` is copied verbatim from the winning report, and
    `accreditation_status` becomes `ACCREDITED` when that report's `threshold_met` is true
    and `AT_RISK` when it is false."
    PRD §3.9: "Every sampling period of the programme that is in `CLOSED` and whose
    half-open window overlaps the report's half-open window transitions `CLOSED → LOCKED`,
    stamping `locked_at` from the logical clock."

    Design: Difficulty/transitive_cascade/submitting_a_report_locks_the_period_and_voids_its_unscored_reviews
    """
    env = fx.locked_period_env(api)

    filed = validate_success(
        api.submit_accreditation_report(
            env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
        )
    )
    assert filed["status"] == "SUBMITTED"
    assert filed["submitted_to"] == "OVERSIGHT_COMMITTEE"
    assert_instant_equals(filed["submitted_at"], CLOCK)

    program = fx.get_program(api, env["program_id"])
    assert program["submitted_report_count"] == 1
    assert program["latest_compliance_pct"] == approx1(100.0)
    assert program["accreditation_status"] == "ACCREDITED"

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["status"] == "LOCKED"
    assert_instant_equals(period["locked_at"], CLOCK)


def test_the_filed_figure_is_case_weighted_over_the_single_finalized_review(api):
    """PRD §3.9: "Under the case-weighted variant every reviewed case counts once: the
    figure is one hundred multiplied by `compliant_review_count`, divided by `review_count`,
    rounded half up to 1 decimal place — so a dispatcher whose calls were sampled heavily
    dominates the programme number."
    PRD §3.9: "`high_risk_compliance_pct` is one hundred multiplied by the pass count,
    divided by the high-risk count, rounded half up to 1 decimal place; when the high-risk
    count is 0 the field is null rather than 0.0, because a window containing no
    cardiac-arrest cases is not a window in which the centre failed them."
    PRD §3.9: "Finally `threshold_met` is true when `compliance_pct` is at or above the
    programme's `target_compliance_pct` **and** either `high_risk_compliance_pct` is null or
    it is at or above the programme's `high_risk_target_pct`."

    Design: Difficulty/transitive_cascade/submitting_a_report_locks_the_period_and_voids_its_unscored_reviews
    """
    env = fx.locked_period_env(api)

    filed = validate_success(
        api.submit_accreditation_report(
            env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
        )
    )
    assert filed["review_count"] == 1, "only the finalized review is in the pool"
    assert filed["compliant_review_count"] == 1
    assert filed["dispatcher_count"] == 1
    assert filed["compliance_pct"] == approx1(100.0)
    assert filed["high_risk_review_count"] == 0
    assert filed["high_risk_compliance_pct"] is None
    assert filed["threshold_met"] is True


def test_locking_voids_the_unworked_review_and_returns_its_call_to_ingested(api):
    """PRD §3.9: "A review still sitting in exactly `SELECTED` was never worked and is
    voided, with `void_reason` stamped as `PERIOD_LOCKED`; its underlying call record returns
    to `INGESTED` and the period's `selected_review_count` is recomputed."
    PRD §3.7: "Every void sets `status` to `VOIDED`, stamps `voided_at` from the logical
    clock, records the `void_reason`, returns the underlying call record from `SELECTED` to
    `INGESTED`, and recomputes the period's `selected_review_count` — which is what returns
    a consumed sample slot to the quota, since that counter counts only reviews in
    `SELECTED`, `SCORED`, `DISPUTED` or `FINALIZED`."

    Design: Difficulty/transitive_cascade/submitting_a_report_locks_the_period_and_voids_its_unscored_reviews
    """
    env = fx.locked_period_env(api)

    validate_success(
        api.submit_accreditation_report(
            env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
        )
    )

    unworked = fx.get_review(api, env["r2_id"])
    assert unworked["status"] == "VOIDED"
    assert unworked["void_reason"] == "PERIOD_LOCKED"
    assert_instant_equals(unworked["voided_at"], CLOCK)

    rows, _meta = validate_paginated(
        api.list_call_records(
            env["dispatcher_id"], ADMIN, {"status": "INGESTED", "limit": 100}
        )
    )
    assert len(rows) == 1, f"expected one released call, got {len(rows)}"
    assert rows[0]["id"] == env["c2_id"]
    assert rows[0]["status"] == "INGESTED"

    period = fx.get_period(api, env["program_id"], env["period_id"])
    assert period["selected_review_count"] == 1
    assert period["finalized_review_count"] == 1


def test_locking_leaves_the_finalized_review_and_its_ledger_untouched(api):
    """PRD §3.9: "Reviews already `FINALIZED` are of course untouched: they are the very
    rows the filed figure was computed from."
    PRD §3.7: "From the percentage, `compliance_posture` follows: `GOOD` when it is at or
    above the programme's `target_compliance_pct`, `WATCH` when it is below that but at or
    above `watch_floor_pct`, and `PROBATION` when it is below the watch floor; a dispatcher
    with no finalized reviews is `UNRATED`."

    Design: Difficulty/transitive_cascade/submitting_a_report_locks_the_period_and_voids_its_unscored_reviews
    """
    env = fx.locked_period_env(api)

    validate_success(
        api.submit_accreditation_report(
            env["report_id"], {"submitted_to": "OVERSIGHT_COMMITTEE"}, OFFICER
        )
    )

    finalized = fx.get_review(api, env["r1_id"])
    assert finalized["status"] == "FINALIZED"
    assert finalized["final_composite_score"] == approx1(92.0)
    assert finalized["voided_at"] is None
    assert finalized["void_reason"] is None

    dispatcher = fx.get_dispatcher(api, env["dispatcher_id"])
    assert dispatcher["reviewed_case_count"] == 1
    assert dispatcher["compliance_pct"] == approx1(92.0)
    assert dispatcher["compliance_posture"] == "GOOD"
    assert dispatcher["remediation_hours_owed"] == approx2(0.00)
    assert dispatcher["dispatch_privilege"] == "FULL"
