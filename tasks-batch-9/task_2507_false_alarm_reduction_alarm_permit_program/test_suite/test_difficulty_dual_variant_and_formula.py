"""Dual-variant calculations and the combinatorial assessment formulas.

Covers the two occurrence-counting variants, the two company scoring variants,
and the pinned rounding, clamping and evaluation orders of the fee, invoice and
delinquency arithmetic.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers import test_users as U


def _renewal_boundary_world(api, counting_window_mode):
    """Four permits renewed on 2025-12-15 with four occurrences straddling that renewal.

    Two chargeable incidents fall in the old permit term (2025-03-01, 2025-06-01)
    and two in the new one (2026-01-10, 2026-02-10); the fourth is left in the
    reported state so the caller can fire the determination itself.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2025-01-01T00:00:00Z",
        installed_at="2025-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2025-01-01T00:00:00Z",
            "counting_window_mode": counting_window_mode,
        },
        site_overrides={"occupancy_class": "RESIDENTIAL"},
        company_overrides={"score_mode": "VOLUME_WEIGHTED"},
        system_count=4,
    )

    X.set_clock(api, "2025-03-01T00:00:00Z")
    first = X.create_counted_incident(
        api, bundle, bundle.system_ids[0], "2025-03-01T02:00:00Z", cause_code="OPERATOR_ERROR"
    )
    X.set_clock(api, "2025-06-01T00:00:00Z")
    second = X.create_counted_incident(
        api, bundle, bundle.system_ids[1], "2025-06-01T03:00:00Z", cause_code="EQUIPMENT_MALFUNCTION"
    )

    X.set_clock(api, "2025-12-15T00:00:00Z")
    X.run_nightly(api)
    for permit_id in list(bundle.permit_ids):
        validate_success(
            api.renew_permit(
                permit_id,
                {"expected_alarm_permit_version": X.permit_version(api, permit_id)},
                U.PERMIT_CLERK,
            ),
            200,
        )

    X.set_clock(api, "2026-01-10T00:00:00Z")
    third = X.create_counted_incident(
        api, bundle, bundle.system_ids[2], "2026-01-10T04:00:00Z", cause_code="UNKNOWN"
    )
    X.set_clock(api, "2026-02-10T00:00:00Z")
    fourth = X.create_reported_incident(
        api, bundle, bundle.system_ids[3], "2026-02-10T05:00:00Z", cause_code="OPEN_DOOR_WINDOW"
    )
    return bundle, first, second, third, fourth


def test_rolling_365_numbers_the_fourth_occurrence_across_the_renewal_boundary(api):
    """A ROLLING_365 premises numbers its 2026-02-10 occurrence 4 and prices it at the 25000-cent tier even though a renewal fell inside the window.

    PRD §3.5: "Under `ROLLING_365`, the window is anchored on the incident being numbered: it includes every chargeable incident at the same premises whose occurrence instant is at or after 365 days before this incident's own occurrence instant and at or before that instant, both bounds inclusive."
    PRD §3.5: "In either case the incident's `occurrence_index` is the size of the set it belongs to — the incident is already counted at that point, so it counts itself — and `counted_window_mode` records which variant produced the number."
    PRD §3.5: "Under `ROLLING_365` the window slides with each incident, so occurrences from a previous permit term still count and a renewal has no effect on the index."
    PRD §3.5: "Third — and this is the only rounding in the whole computation — the tier base is multiplied by all three factors together and that single product is rounded half up to a whole cent."

    The trailing 365 days before 2026-02-10 open on 2025-02-10, so the window holds
    all four occurrences (2025-03-01, 2025-06-01, 2026-01-10, 2026-02-10) and the
    index is 4. The marginal tier for index 4 is 25000 cents; RESIDENTIAL occupancy
    multiplies by 1.00, the TWO_CALL_ECV method adds no surcharge and the system was
    permitted, so 25000 * 1.00 = 25000 cents.

    Design: Difficulty/dual_variant_calc/occurrence_index_rolling_365_counts_across_the_renewal_boundary
    """
    _bundle, _first, _second, third, fourth = _renewal_boundary_world(api, "ROLLING_365")

    ruled = X.determine_counted(
        api, fourth.incident_id, review_notes="Fourth chargeable occurrence in the rolling window."
    )
    assert ruled["occurrence_index"] == 4, (
        f"the fourth rolling-window occurrence must be numbered 4, got {ruled['occurrence_index']}"
    )
    assert ruled["counted_window_mode"] == "ROLLING_365", (
        f"counted_window_mode must record the governing variant, got {ruled['counted_window_mode']!r}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 25000, "assessed_fee_cents")
    A.assert_fee_basis(
        ruled["fee_basis"],
        tier_base_cents=25000,
        occupancy_multiplier=1.00,
        non_ecv_surcharge_applied=False,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )

    earlier = X.get_incident(api, third.incident_id)
    assert earlier["occurrence_index"] == 3, (
        f"the 2026-01-10 occurrence must still be numbered 3, got {earlier['occurrence_index']}"
    )
    A.assert_money_cents(earlier["assessed_fee_cents"], 10000, "third occurrence assessed_fee_cents")

    invoice = A.single(
        api.list_penalty_invoices(
            U.BILLING_CLERK,
            {"false_alarm_incident_id": fourth.incident_id, "kind": "FALSE_ALARM_FEE"},
        )
    )
    A.assert_invoice_totals(invoice, subtotal_cents=25000, admin_fee_cents=1250, assessed_cents=26250)
    A.assert_outstanding_identity(invoice)
    assert invoice["issued_on"] == "2026-02-10T00:00:00Z", (
        f"issued_on must be the logical clock, got {invoice['issued_on']!r}"
    )
    assert X.same_instant(invoice["due_on"], "2026-03-12T00:00:00Z"), (
        f"due_on must be 30 whole days after issuance, got {invoice['due_on']!r}"
    )


def test_rolling_365_premises_counters_diverge_from_the_permit_year_counter(api):
    """The same premises reads chargeable_count_rolling_365 4 against chargeable_count_permit_year 2, with the rolling count driving the authoritative window count and the probation posture.

    PRD §3.2: "`chargeable_count_window` is the authoritative window count under the governing counting variant, while `chargeable_count_rolling_365` and `chargeable_count_permit_year` are both maintained at all times so the two variants can be compared side by side."
    PRD §3.5: "The premises' own counters use the same two definitions but evaluated at the logical clock rather than at any one incident's instant: `chargeable_count_rolling_365` counts chargeable incidents in the 365 days up to now, `chargeable_count_permit_year` counts them from the current term start up to now, and `chargeable_count_window` is whichever of the two the governing `counting_window_mode` selects."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`."
    PRD §3.5: "And when `chargeable_count_window` reaches or exceeds `suspension_threshold_count`, an enforcement order is auto-proposed for the premises: a suspension order in `PROPOSED` with `basis` of `EXCESSIVE_FALSE_ALARMS`, its `triggering_incident_id` set to this incident, `effective_from` at the logical clock plus 10 days and `effective_through` at 30 days after that."

    At the 2026-02-10 clock the trailing 365 days hold all four occurrences while the
    permit year, restarted by the 2025-12-15 renewal, holds only the last two. The
    governing ROLLING_365 mode therefore publishes 4 as the window count, which is at
    the probation threshold of 4 but below the suspension threshold of 6, so the
    premises is on probation with no order proposed.

    Design: Difficulty/dual_variant_calc/occurrence_index_rolling_365_counts_across_the_renewal_boundary
    """
    bundle, _first, _second, _third, fourth = _renewal_boundary_world(api, "ROLLING_365")

    X.determine_counted(
        api, fourth.incident_id, review_notes="Fourth chargeable occurrence in the rolling window."
    )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_rolling_365"] == 4, (
        f"chargeable_count_rolling_365 must be 4, got {site['chargeable_count_rolling_365']}"
    )
    assert site["chargeable_count_permit_year"] == 2, (
        f"chargeable_count_permit_year must be 2 after the renewal reset, "
        f"got {site['chargeable_count_permit_year']}"
    )
    assert site["chargeable_count_window"] == 4, (
        f"the governing ROLLING_365 mode must publish 4, got {site['chargeable_count_window']}"
    )
    A.assert_status(site, "RESPONSE_PROBATION", field="response_status")

    summary = X.get_summary(api, bundle.site_id)
    assert summary["chargeable_count_rolling_365"] == 4, (
        f"the summary must recompute the rolling count as 4, got {summary['chargeable_count_rolling_365']}"
    )
    assert summary["chargeable_count_permit_year"] == 2, (
        f"the summary must recompute the permit-year count as 2, "
        f"got {summary['chargeable_count_permit_year']}"
    )

    A.assert_total_count(
        api.list_suspension_orders(U.PROGRAM_ADMIN, {"alarm_site_id": bundle.site_id}), 0
    )


def test_permit_year_resets_at_renewal_and_suppresses_the_fee_entirely(api):
    """Flipping only counting_window_mode to PERMIT_YEAR renumbers the 2026-02-10 occurrence to 2, which falls inside the free allowance and is assessed 0 cents with no invoice at all.

    PRD §3.5: "Under `PERMIT_YEAR`, the window is anchored on the permit term that contains the incident: the term start is taken from the premises permit whose closed interval from `term_start_at` through `grace_through_at` contains the incident's occurrence instant, taking the greatest such `term_start_at` when several permits qualify and breaking any remaining tie by earliest `created_at`; the window then includes every chargeable incident at the premises whose occurrence instant is at or after that term start and at or before this incident's occurrence instant, again both bounds inclusive."
    PRD §3.5: "Under `PERMIT_YEAR` the window restarts at every renewal, so four incidents that would produce an index of 4 — and its 25000-cent tier — under the rolling variant instead produce an index of 1, which is free under the allowance, if a renewal falls between them."
    PRD §3.5: "First, the marginal tier: the tier base is the `base_fee_cents` of the single `fee_tiers` entry whose `from_index` is at or below the index and whose `to_index` is either null or at or above the index — this is a marginal lookup, never a cumulative sum of lower tiers — and the tier base is then forced to zero whenever the index is at or below `free_alarm_allowance`."
    PRD §3.8: "The one case that produces no row at all is a false alarm inside the free allowance with no aggravation: a zero subtotal means no invoice and therefore no administrative fee either."

    The 2025-12-15 renewal set every permit's term_start_at to that instant, so the
    window for the 2026-02-10 occurrence opens there and holds only the 2026-01-10 and
    2026-02-10 rows. Index 2 is at or below the free_alarm_allowance of 2, so the tier
    base is forced to zero and the assessed fee is 0 cents.

    Design: Difficulty/dual_variant_calc/occurrence_index_permit_year_resets_at_renewal_and_suppresses_the_same_fee
    """
    bundle, _first, _second, third, fourth = _renewal_boundary_world(api, "PERMIT_YEAR")

    ruled = X.determine_counted(
        api, fourth.incident_id, review_notes="Second occurrence of the new permit year."
    )
    assert ruled["occurrence_index"] == 2, (
        f"the permit-year window must renumber this occurrence 2, got {ruled['occurrence_index']}"
    )
    assert ruled["counted_window_mode"] == "PERMIT_YEAR", (
        f"counted_window_mode must record the governing variant, got {ruled['counted_window_mode']!r}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 0, "assessed_fee_cents")
    A.assert_fee_basis(ruled["fee_basis"], tier_base_cents=0, aggravation_cents=0, cap_applied=False)

    earlier = X.get_incident(api, third.incident_id)
    assert earlier["occurrence_index"] == 1, (
        f"the first occurrence of the new permit year must be numbered 1, "
        f"got {earlier['occurrence_index']}"
    )
    A.assert_money_cents(earlier["assessed_fee_cents"], 0, "third occurrence assessed_fee_cents")

    A.assert_total_count(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "kind": "FALSE_ALARM_FEE"}
        ),
        0,
    )


def test_permit_year_premises_still_publishes_the_rolling_count_side_by_side(api):
    """Under PERMIT_YEAR the premises publishes 2 as its authoritative window count and stays at RESPONSE_ACTIVE, while chargeable_count_rolling_365 still reads 4 on the very same row.

    PRD §3.2: "`chargeable_count_window` is the authoritative window count under the governing counting variant, while `chargeable_count_rolling_365` and `chargeable_count_permit_year` are both maintained at all times so the two variants can be compared side by side."
    PRD §3.5: "Otherwise, if `chargeable_count_window` is at or above `probation_threshold_count`, the posture is `RESPONSE_PROBATION`. Otherwise it is `RESPONSE_ACTIVE`."
    PRD §3.2: "`outstanding_balance_cents` totals what is still owed on invoices that are unpaid or partially paid and not written off; `credit_balance_cents` holds unallocated payment remainder and is never negative."

    The window count of 2 sits below the probation threshold of 4, so identical
    occurrence data leaves this premises at RESPONSE_ACTIVE. The balance is the four
    permit-issue invoices at 5000 plus the 500-cent administrative floor, each carrying
    the single 550-cent late penalty added by the 2025-12-15 nightly run, that is 6050
    apiece, plus the four renewal invoices at 3000 plus the 500-cent floor, that is
    3500 apiece: 24200 + 14000 = 38200 cents, with no false alarm fee among them.

    Design: Difficulty/dual_variant_calc/occurrence_index_permit_year_resets_at_renewal_and_suppresses_the_same_fee
    """
    bundle, _first, _second, _third, fourth = _renewal_boundary_world(api, "PERMIT_YEAR")

    X.determine_counted(
        api, fourth.incident_id, review_notes="Second occurrence of the new permit year."
    )

    site = X.get_site(api, bundle.site_id)
    assert site["chargeable_count_permit_year"] == 2, (
        f"chargeable_count_permit_year must be 2, got {site['chargeable_count_permit_year']}"
    )
    assert site["chargeable_count_rolling_365"] == 4, (
        f"chargeable_count_rolling_365 must still be 4, got {site['chargeable_count_rolling_365']}"
    )
    assert site["chargeable_count_window"] == 2, (
        f"the governing PERMIT_YEAR mode must publish 2, got {site['chargeable_count_window']}"
    )
    A.assert_status(site, "RESPONSE_ACTIVE", field="response_status")
    A.assert_money_cents(site["outstanding_balance_cents"], 38200, "outstanding_balance_cents")


def _two_period_report_world(api, score_mode):
    """One company with a busy bad March period and a quiet perfect April period.

    Three refused dispatch requests sit inside March and one inside April, so the
    city's own records show 3 and 1. The April report is filed and accepted first,
    leaving the flagging of the March report as the single trigger.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
        site_overrides={"occupancy_class": "COMMERCIAL"},
        company_overrides={"score_mode": score_mode},
        system_count=1,
    )

    for occurred_at in (
        "2026-03-05T01:00:00Z",
        "2026-03-12T01:00:00Z",
        "2026-03-20T01:00:00Z",
        "2026-04-10T01:00:00Z",
    ):
        X.set_clock(api, X.day_start(occurred_at))
        request_id = X.submit_dispatch_request(
            api,
            bundle,
            bundle.system_id,
            occurred_at,
            call_attempts=[
                F.call_attempt(bundle.contact_ids[0], X.plus_minutes(occurred_at, 1), "NO_ANSWER")
            ],
            verification_method="SINGLE_CALL",
        )
        validate_success(
            api.refuse_dispatch_request(
                request_id, {"refusal_reason": "ECV_DEFICIENT"}, U.DISPATCH_SUPERVISOR
            ),
            200,
        )

    X.set_clock(api, "2026-05-01T00:00:00Z")
    march = X.submit_compliance_report(
        api,
        bundle,
        "2026-03-01T00:00:00Z",
        "2026-03-31T23:59:59Z",
        reported_dispatch_count=6,
        reported_cancellation_count=0,
        ecv_attempt_count=3,
    )
    april = X.submit_compliance_report(
        api,
        bundle,
        "2026-04-01T00:00:00Z",
        "2026-04-30T23:59:59Z",
        reported_dispatch_count=1,
        reported_cancellation_count=0,
        ecv_attempt_count=1,
    )
    X.review_compliance_report(api, april, "ACCEPT")
    return bundle, march, april


def test_volume_weighted_scoring_lets_the_busy_bad_period_dominate_the_company_score(api):
    """A VOLUME_WEIGHTED company whose 0.20-scoring March carried three dispatches and whose 1.00-scoring April carried one is scored 0.40 and suspended.

    PRD §3.10: "`system_dispatch_count` is the number of dispatch requests attributed to that company whose `occurred_at` falls inside the closed period interval and whose status is not `CANCELLED` — a `REFUSED` request still counts, because the company did ask for dispatch even though the city declined, and only a cancellation removes the ask."
    PRD §3.10: "`period_score` is 0.6 times `period_accuracy` plus 0.4 times `period_ecv_rate`, rounded half up to two decimal places."
    PRD §3.10: "Under `VOLUME_WEIGHTED`, the weight total is the sum of `system_dispatch_count` across the set, and the score is the sum of each `period_score` times its own `system_dispatch_count` divided by that total — falling back to the plain mean of the period scores when the weight total is zero."
    PRD §3.10: "From `PROBATION`, a score below `company_suspension_score_threshold`, or a `consecutive_flagged_report_count` of 3 or more, moves the company to `SUSPENDED`."

    March reports 6 against a recorded 3, so variance_count is 3, variance_pct is
    3/3 = 1.0000, period_accuracy is 1 - 1 = 0.0000, period_ecv_rate is 3/6 = 0.5000
    and period_score is 0.6*0 + 0.4*0.5 = 0.20. April reports 1 against 1 for an
    accuracy of 1.0000, a rate of 1.0000 and a score of 1.00. Weighting by dispatch
    volume gives (0.20*3 + 1.00*1) / 4 = 0.40, which is below the 0.50 suspension
    threshold.

    Design: Difficulty/dual_variant_calc/company_score_volume_weighted_lets_one_busy_bad_period_suspend_the_company
    """
    bundle, march, april = _two_period_report_world(api, "VOLUME_WEIGHTED")

    X.review_compliance_report(
        api,
        march,
        "FLAG_VARIANCE",
        variance_notes="Reported 6 dispatches against 3 recorded; ECV attempts cover only half the reported volume.",
    )

    march_row = X.get_report(api, march)
    assert march_row["system_dispatch_count"] == 3, (
        f"three refused March requests must be counted, got {march_row['system_dispatch_count']}"
    )
    assert march_row["variance_count"] == 3, (
        f"variance_count must be |6 - 3| = 3, got {march_row['variance_count']}"
    )
    A.assert_ratio_4dp(march_row["variance_pct"], 1.0000, "variance_pct")
    A.assert_ratio_4dp(march_row["period_accuracy"], 0.0000, "period_accuracy")
    A.assert_ratio_4dp(march_row["period_ecv_rate"], 0.5000, "period_ecv_rate")
    A.assert_score_2dp(march_row["period_score"], 0.20, "March period_score")
    A.assert_status(march_row, "VARIANCE_FLAGGED")

    april_row = X.get_report(api, april)
    assert april_row["system_dispatch_count"] == 1, (
        f"one refused April request must be counted, got {april_row['system_dispatch_count']}"
    )
    A.assert_score_2dp(april_row["period_score"], 1.00, "April period_score")
    A.assert_status(april_row, "ACCEPTED")

    company = X.get_company(api, bundle.company_id)
    A.assert_score_2dp(company["reporting_compliance_score"], 0.40, "reporting_compliance_score")
    A.assert_status(company, "SUSPENDED")
    assert company["consecutive_flagged_report_count"] == 1, (
        f"one unbroken flagged run must be recorded, got {company['consecutive_flagged_report_count']}"
    )


def test_volume_weighted_score_carries_the_company_straight_past_probation(api):
    """The VOLUME_WEIGHTED company reads ACTIVE with a 1.00 score while only April is in the score set, and the March flag drops it to SUSPENDED without ever passing through PROBATION.

    PRD §3.10: "A flagged period still enters the score set: being caught does not erase the period, it prices it."
    PRD §3.10: "A score that low can also skip probation entirely and carry an `ACTIVE` company straight to `SUSPENDED`, in which case `probation_started_at` is set to the logical clock so that reinstatement eligibility still has an anchor to measure from."
    PRD §3.10: "Every status action stamps `last_status_action_at` at the logical clock and records the `status_reason`."

    With April accepted and March still merely submitted, the score set holds one
    entry of 1.00 and the company remains ACTIVE. Flagging March admits its 0.20 at
    weight 3 alongside April's 1.00 at weight 1 for 0.40, below the 0.50 suspension
    threshold, so the single review moves ACTIVE straight to SUSPENDED and anchors
    probation_started_at at the 2026-05-01 clock.

    Design: Difficulty/dual_variant_calc/company_score_volume_weighted_lets_one_busy_bad_period_suspend_the_company
    """
    bundle, march, _april = _two_period_report_world(api, "VOLUME_WEIGHTED")

    before = X.get_company(api, bundle.company_id)
    A.assert_status(before, "ACTIVE")
    A.assert_score_2dp(before["reporting_compliance_score"], 1.00, "score before the flag")

    X.review_compliance_report(
        api, march, "FLAG_VARIANCE", variance_notes="Reported 6 dispatches against 3 recorded."
    )

    after = X.get_company(api, bundle.company_id)
    A.assert_status(after, "SUSPENDED")
    assert after["status"] != "PROBATION", "a score below the suspension threshold must not stop at the probation rung"
    assert after["probation_started_at"] == "2026-05-01T00:00:00Z", (
        f"a straight-to-suspended company must anchor probation_started_at at the logical clock, "
        f"got {after['probation_started_at']!r}"
    )
    assert after["last_status_action_at"] == "2026-05-01T00:00:00Z", (
        f"last_status_action_at must be stamped at the logical clock, "
        f"got {after['last_status_action_at']!r}"
    )


def test_period_equal_scoring_leaves_the_same_two_reports_at_probation(api):
    """The identical two-period report set under PERIOD_EQUAL averages to 0.60 and lands the company in PROBATION rather than suspension.

    PRD §3.10: "Under `PERIOD_EQUAL`, the score is simply the sum of the period scores divided by the number of entries."
    PRD §3.10: "From `ACTIVE`, a recomputed score below `company_probation_score_threshold` but at or above `company_suspension_score_threshold` moves the company to `PROBATION`, stamping `probation_started_at`, `status_reason` and `last_status_action_at`; dispatch requests are still accepted on probation."
    PRD §3.10: "The two modes are not a cosmetic preference; they can invert the regulatory outcome on identical data."

    The stored period scores are unchanged at 0.20 and 1.00; the plain mean is
    (0.20 + 1.00) / 2 = 0.60, which is at or above the 0.50 suspension threshold and
    below the 0.70 probation threshold.

    Design: Difficulty/dual_variant_calc/company_score_period_equal_leaves_the_same_reports_at_probation
    """
    bundle, march, april = _two_period_report_world(api, "PERIOD_EQUAL")

    X.review_compliance_report(
        api, march, "FLAG_VARIANCE", variance_notes="Reported 6 dispatches against 3 recorded."
    )

    A.assert_score_2dp(X.get_report(api, march)["period_score"], 0.20, "March period_score")
    A.assert_score_2dp(X.get_report(api, april)["period_score"], 1.00, "April period_score")

    company = X.get_company(api, bundle.company_id)
    A.assert_score_2dp(company["reporting_compliance_score"], 0.60, "reporting_compliance_score")
    A.assert_status(company, "PROBATION")
    assert company["probation_started_at"] == "2026-05-01T00:00:00Z", (
        f"probation_started_at must be stamped at the logical clock, "
        f"got {company['probation_started_at']!r}"
    )
    assert company["consecutive_flagged_report_count"] == 1, (
        f"one unbroken flagged run must be recorded, got {company['consecutive_flagged_report_count']}"
    )


def test_period_equal_probation_keeps_the_company_dispatch_privilege(api):
    """A company dropped to PROBATION by the PERIOD_EQUAL average may still lodge a fresh dispatch request, which a suspension would have refused.

    PRD §3.10: "From `ACTIVE`, a recomputed score below `company_probation_score_threshold` but at or above `company_suspension_score_threshold` moves the company to `PROBATION`, stamping `probation_started_at`, `status_reason` and `last_status_action_at`; dispatch requests are still accepted on probation."
    PRD §2.10: "The reporting monitoring company must be `ACTIVE` or `PROBATION`; a `SUSPENDED` or `REVOKED` company may neither lodge dispatch requests nor open incident reports, and both operations fail with `ERR_COMPANY_DISPATCH_PRIVILEGE_SUSPENDED`."

    The 0.60 average sits above the suspension threshold, so the company keeps the
    privilege and its next submission is created rather than refused.

    Design: Difficulty/dual_variant_calc/company_score_period_equal_leaves_the_same_reports_at_probation
    """
    bundle, march, _april = _two_period_report_world(api, "PERIOD_EQUAL")

    X.review_compliance_report(
        api, march, "FLAG_VARIANCE", variance_notes="Reported 6 dispatches against 3 recorded."
    )
    A.assert_status(X.get_company(api, bundle.company_id), "PROBATION")

    occurred_at = "2026-05-01T01:00:00Z"
    response = api.create_dispatch_request(
        F.dispatch_request_payload(
            bundle.system_id,
            occurred_at,
            X.two_call_attempts(bundle, occurred_at),
        ),
        bundle.operator_headers,
    )
    validate_success(response, 201)
    A.assert_status(A.data_of(response, 201), "SUBMITTED")


def _school_duress_world(api):
    """A SCHOOL premises on a 3333-cent third tier with two free occurrences already spent.

    Every request is a DURESS signal verified by no method at all, which is exactly
    the pairing that survives validation while still attracting the non-ECV
    surcharge. The third incident is left reported for the caller to rule on.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "fee_tiers": [
                {"from_index": 1, "to_index": 2, "base_fee_cents": 0},
                {"from_index": 3, "to_index": 3, "base_fee_cents": 3333},
                {"from_index": 4, "to_index": 4, "base_fee_cents": 25000},
                {"from_index": 5, "to_index": 5, "base_fee_cents": 40000},
                {"from_index": 6, "to_index": None, "base_fee_cents": 75000},
            ],
        },
        site_overrides={"occupancy_class": "SCHOOL"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=3,
    )

    unverified_duress = {"alarm_type": "DURESS", "verification_method": "NONE", "call_attempts": []}

    X.set_clock(api, "2026-02-05T00:00:00Z")
    X.create_counted_incident(
        api, bundle, bundle.system_ids[0], "2026-02-05T09:00:00Z", **unverified_duress
    )
    X.set_clock(api, "2026-02-12T00:00:00Z")
    X.create_counted_incident(
        api, bundle, bundle.system_ids[1], "2026-02-12T09:00:00Z", **unverified_duress
    )
    X.set_clock(api, "2026-02-20T00:00:00Z")
    third = X.create_reported_incident(
        api, bundle, bundle.system_ids[2], "2026-02-20T09:00:00Z", **unverified_duress
    )
    return bundle, third


def test_fee_rounds_the_full_factor_product_once_to_five_thousand_cents(api):
    """A SCHOOL occurrence on a 3333-cent tier verified by no method is assessed 5000 cents, the single rounding of 3333 * 1.25 * 1.20, rather than the 4999 that rounding factor by factor produces.

    PRD §2.7: "**One rounding on a product.** Where a base amount is multiplied by several factors — the false alarm fee is the canonical case — the factors are multiplied together into a single product and that product is rounded once. Rounding each factor's contribution separately is wrong and will produce different money."
    PRD §3.5: "Second, the three multiplicative factors: the occupancy multiplier is the schedule's `occupancy_multipliers` entry for the premises' `occupancy_class`; the surcharge factor is 1 plus `non_ecv_surcharge_pct` when the originating request's `verification_method` was `NONE` or `SINGLE_CALL`, and 1 otherwise; the unpermitted factor is `unpermitted_multiplier` when the request's frozen `system_permitted_at_occurrence` is false, and 1 otherwise."
    PRD §3.5: "Third — and this is the only rounding in the whole computation — the tier base is multiplied by all three factors together and that single product is rounded half up to a whole cent."
    PRD §3.4: "From that count, `ecv_sufficient` is decided as follows: it is true whenever the `alarm_type` is `DURESS`, because a duress signal bypasses call verification entirely; otherwise it is true when the `verification_method` is `TWO_CALL_ECV` and `distinct_ecv_contact_count` is at least 2; otherwise it is true when the method is `AUDIO_VIDEO` and `audio_video_evidence` is true; otherwise it is true when the method is `GUARD_RESPONSE` and `guard_on_scene` is true; and in every remaining case it is false."

    3333 * 1.25 * 1.20 = 4999.5, which rounds half up to 5000. Rounding after the
    occupancy factor alone would give 4166, and 4166 * 1.20 = 4999.2 rounds to 4999 —
    one cent short. The 100000-cent cap is untouched and no suspension order covers
    the occurrence, so nothing is clipped and nothing is added.

    Design: Difficulty/combinatorial_formula/fee_single_rounding_of_the_full_factor_product_beats_per_factor_rounding
    """
    _bundle, third = _school_duress_world(api)

    request = A.data_of(api.get_dispatch_request(third.dispatch_request_id, U.DISPATCH_SUPERVISOR))
    assert request["ecv_sufficient"] is True, (
        "a DURESS signal bypasses call verification, so ecv_sufficient must be true"
    )
    assert request["distinct_ecv_contact_count"] == 0, (
        f"an empty call log must leave distinct_ecv_contact_count at 0, "
        f"got {request['distinct_ecv_contact_count']}"
    )

    ruled = X.determine_counted(
        api, third.incident_id, review_notes="Third chargeable occurrence, non-ECV verified."
    )
    assert ruled["occurrence_index"] == 3, (
        f"the third chargeable occurrence must be numbered 3, got {ruled['occurrence_index']}"
    )
    A.assert_money_cents(ruled["assessed_fee_cents"], 5000, "assessed_fee_cents")
    A.assert_fee_basis(
        ruled["fee_basis"],
        tier_base_cents=3333,
        occupancy_multiplier=1.25,
        non_ecv_surcharge_applied=True,
        unpermitted_multiplier_applied=False,
        cap_applied=False,
        aggravation_cents=0,
    )


def test_fee_invoice_line_carries_the_combined_multiplier_and_the_admin_floor(api):
    """The fee invoice carries one base line whose multiplier is the combined 1.50 rather than two successive roundings, and its 250-cent administrative fee is lifted to the 500-cent floor.

    PRD §3.8: "A `FALSE_ALARM_FEE` invoice carries a first line coded FALSE_ALARM_BASE whose `unit_amount_cents` is the incident's tier base, `quantity` 1, and `multiplier` the product of the occupancy multiplier, the surcharge factor and the unpermitted factor — and when the incident's `fee_basis` records `cap_applied`, that line's `extended_cents` is overridden to `per_incident_fee_cap_cents`; it carries a second line coded SUSPENSION_PERIOD_AGGRAVATION at the aggravation amount with `multiplier` 1.00, present only when the aggravation is above zero."
    PRD §3.8: "The rounding order is pinned and is not a matter of taste: each line's `extended_cents` is `unit_amount_cents` times `quantity` times `multiplier`, rounded half up to a whole cent, and only then are the lines summed into `subtotal_cents`."
    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.2: "`lifetime_assessed_cents` totals what has ever been assessed against the address across invoices that are not voided; `outstanding_balance_cents` totals what is still owed on invoices that are unpaid or partially paid and not written off; `credit_balance_cents` holds unallocated payment remainder and is never negative."

    The one line multiplies 3333 by the combined 1.25 * 1.20 = 1.50 and rounds once to
    5000, which is the whole subtotal. Five percent of 5000 is 250, below the 500-cent
    minimum, so the administrative fee is 500 and the assessment is 5500. Lifetime
    assessment is the three permit-issue invoices at 5500 apiece plus this 5500, that
    is 22000 cents.

    Design: Difficulty/combinatorial_formula/fee_single_rounding_of_the_full_factor_product_beats_per_factor_rounding
    """
    bundle, third = _school_duress_world(api)

    X.determine_counted(
        api, third.incident_id, review_notes="Third chargeable occurrence, non-ECV verified."
    )

    invoice = A.single(
        api.list_penalty_invoices(U.BILLING_CLERK, {"false_alarm_incident_id": third.incident_id})
    )
    lines = invoice["line_items"]
    assert len(lines) == 1, f"a fee with no aggravation carries exactly one line, got {len(lines)}"
    assert lines[0]["code"] == "FALSE_ALARM_BASE", (
        f"the single line must be coded FALSE_ALARM_BASE, got {lines[0]['code']!r}"
    )
    A.assert_money_cents(lines[0]["unit_amount_cents"], 3333, "line unit_amount_cents")
    assert lines[0]["quantity"] == 1, f"the base line carries quantity 1, got {lines[0]['quantity']}"
    assert float(lines[0]["multiplier"]) == 1.50, (
        f"the line multiplier must be the combined 1.25 * 1.20 = 1.50, got {lines[0]['multiplier']}"
    )
    A.assert_money_cents(lines[0]["extended_cents"], 5000, "line extended_cents")

    A.assert_invoice_totals(
        invoice, subtotal_cents=5000, admin_fee_cents=500, assessed_cents=5500
    )
    A.assert_outstanding_identity(invoice)

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["lifetime_assessed_cents"], 22000, "lifetime_assessed_cents")


def _clamp_world(api):
    """A GOVERNMENT premises with a zero balance and one registration still submitted."""
    return X.setup_program_baseline(
        api,
        clock="2026-06-01T00:00:00Z",
        installed_at="2026-06-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-06-01T00:00:00Z",
            "permit_issue_fee_cents": 200000,
        },
        site_overrides={"occupancy_class": "GOVERNMENT"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=1,
        approve=False,
    )


def test_admin_fee_ceiling_clamps_before_it_joins_assessed_cents(api):
    """A 200000-cent permit-issue subtotal carries a 5000-cent administrative fee, not the raw 10000, so the assessment is 205000 rather than 210000.

    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.8: "A `PERMIT_ISSUE_FEE` invoice carries one PERMIT_ISSUE line at `permit_issue_fee_cents`."
    PRD §3.8: "`late_penalty_cents` is 0 at issuance. `assessed_cents` is `subtotal_cents` plus `admin_fee_cents` plus `late_penalty_cents`; `paid_cents` and `adjusted_cents` start at 0; `outstanding_cents` is `assessed_cents` minus `paid_cents` minus `adjusted_cents`, floored at zero and never negative."

    Five percent of the 200000-cent subtotal is 10000, which exceeds the 5000-cent
    ceiling, so the fee is clamped to 5000 before summation: 200000 + 5000 + 0 = 205000
    cents assessed and the same amount outstanding.

    Design: Difficulty/combinatorial_formula/admin_fee_ceiling_clamps_before_it_joins_assessed_cents
    """
    bundle = _clamp_world(api)

    X.approve_system(api, bundle.system_ids[0])

    invoice = A.single(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "kind": "PERMIT_ISSUE_FEE"}
        )
    )
    lines = invoice["line_items"]
    assert len(lines) == 1, f"a permit issue invoice carries exactly one line, got {len(lines)}"
    assert lines[0]["code"] == "PERMIT_ISSUE", (
        f"the single line must be coded PERMIT_ISSUE, got {lines[0]['code']!r}"
    )
    A.assert_money_cents(lines[0]["unit_amount_cents"], 200000, "line unit_amount_cents")
    assert float(lines[0]["multiplier"]) == 1.00, (
        f"a permit issue line carries no multiplier above 1.00, got {lines[0]['multiplier']}"
    )
    A.assert_money_cents(lines[0]["extended_cents"], 200000, "line extended_cents")

    A.assert_invoice_totals(
        invoice,
        subtotal_cents=200000,
        admin_fee_cents=5000,
        assessed_cents=205000,
        paid_cents=0,
        adjusted_cents=0,
        outstanding_cents=205000,
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 0, "late_penalty_cents")
    A.assert_outstanding_identity(invoice)


def test_permit_issuance_survives_the_balance_block_it_then_creates(api):
    """The registration is approved because the pre-issuance balance is zero, and only the invoice it produces pushes the premises over the blocking threshold.

    PRD §3.3: "Six preconditions guard it, and all must hold: the premises is `ACTIVE`; the premises has at least 2 live callable contacts, else `ERR_INSUFFICIENT_ECV_CONTACTS`; the premises' outstanding balance is strictly below the schedule's blocking threshold, else `ERR_SITE_BALANCE_DELINQUENT`; the premises has no suspension order in `EFFECTIVE` or `REINSTATEMENT_PENDING`, else `ERR_POLICE_RESPONSE_SUSPENDED`; this system holds no permit in `ACTIVE`, `RENEWAL_DUE`, `RENEWAL_BLOCKED` or `GRACE`, else `ERR_ACTIVE_PERMIT_EXISTS`; and exactly one fee schedule is `ACTIVE`, else `ERR_NO_ACTIVE_FEE_SCHEDULE`."
    PRD §3.2: "`renewal_block_active` is true exactly when `outstanding_balance_cents` is at or above the schedule's `delinquent_balance_block_cents`."
    PRD §2.9: "A premises is **pinned** to a schedule the first time any of its systems is permitted: at that moment `governing_fee_schedule_id` on the `AlarmSite` is set to the currently `ACTIVE` schedule and becomes immutable, and it stays null until then."

    The premises owed nothing before approval, so the strict comparison passes. The
    205000-cent invoice then lifts the balance far above the 50000-cent block, and the
    same operation pins the governing schedule.

    Design: Difficulty/combinatorial_formula/admin_fee_ceiling_clamps_before_it_joins_assessed_cents
    """
    bundle = _clamp_world(api)

    before = X.get_site(api, bundle.site_id)
    A.assert_money_cents(before["outstanding_balance_cents"], 0, "balance before issuance")
    assert before["renewal_block_active"] is False, "an unbilled premises is not renewal blocked"
    assert before["governing_fee_schedule_id"] is None, (
        f"the governing schedule stays null until the first issuance, "
        f"got {before['governing_fee_schedule_id']!r}"
    )

    permit_id = X.approve_system(api, bundle.system_ids[0])

    A.assert_status(X.get_system(api, bundle.system_ids[0]), "PERMITTED")
    A.assert_status(X.get_permit(api, permit_id), "ACTIVE")

    after = X.get_site(api, bundle.site_id)
    A.assert_money_cents(after["outstanding_balance_cents"], 205000, "outstanding_balance_cents")
    assert after["renewal_block_active"] is True, (
        "a 205000-cent balance is at or above the 50000-cent block, so renewal_block_active is true"
    )
    assert after["governing_fee_schedule_id"] == bundle.schedule_id, (
        f"the premises must be pinned to the active schedule, "
        f"got {after['governing_fee_schedule_id']!r}"
    )


def _delinquent_invoice_world(api):
    """A 22857-cent permit-issue invoice driven to FINAL_NOTICE with its late penalty on.

    The nightly run on 2026-02-01 sits one day past the 2026-01-31 due date, and the
    run on 2026-05-01 sits exactly 90 whole days past it.
    """
    bundle = X.setup_program_baseline(
        api,
        clock="2026-01-01T00:00:00Z",
        installed_at="2026-01-01T00:00:00Z",
        schedule_overrides={
            "effective_from": "2026-01-01T00:00:00Z",
            "permit_issue_fee_cents": 22857,
        },
        site_overrides={"occupancy_class": "COMMERCIAL"},
        company_overrides={"score_mode": "PERIOD_EQUAL"},
        system_count=1,
    )
    invoice_id = A.single(
        api.list_penalty_invoices(
            U.BILLING_CLERK, {"alarm_site_id": bundle.site_id, "kind": "PERMIT_ISSUE_FEE"}
        )
    )["id"]

    X.set_clock(api, "2026-02-01T00:00:00Z")
    X.run_nightly(api)
    X.set_clock(api, "2026-05-01T00:00:00Z")
    X.run_nightly(api)
    return bundle, invoice_id


def test_late_penalty_is_folded_in_before_the_dunning_ladder_reaches_final_notice(api):
    """A 22857-cent principal assembles to 24000 assessed and the first nightly step folds in exactly one 2400-cent late penalty, carrying the invoice to 26400 at FINAL_NOTICE ninety days past due.

    PRD §3.8: "`admin_fee_cents` is then the subtotal times `admin_fee_pct`, rounded half up once on the already-rounded subtotal, and clamped upward to `admin_fee_min_cents` and downward to `admin_fee_max_cents`; the clamp binds before the fee joins the assessment, so a 200-cent subtotal still carries the 500-cent floor and a 200000-cent subtotal carries the 5000-cent ceiling."
    PRD §3.8: "Step two: `late_penalty_cents` is that principal times `late_penalty_pct`, rounded half up, and is added into `assessed_cents` — once per invoice, never twice."
    PRD §3.8: "The nightly run advances `CURRENT → NOTICE` once `days_delinquent` is at least 1, and `NOTICE → FINAL_NOTICE` once it is at least 30; both steps require `outstanding_cents` above zero and require that the linked incident, when there is one, is not in `APPEALED`. The first step is where the late penalty is added, exactly once per invoice; the second adds no further penalty and merely makes the invoice referral-eligible once `days_delinquent` reaches `delinquency_days`."
    PRD §3.8: "`days_delinquent` is the whole days between `due_on` and the logical clock, floored at zero."

    Five percent of 22857 is 1142.85, which rounds half up to 1143 and sits inside the
    500-to-5000 clamp, so the invoice is assessed 22857 + 1143 = 24000 and falls due on
    2026-01-31. Ten percent of that principal is 2400, added once, giving 26400. From
    2026-01-31 to 2026-05-01 is 28 + 31 + 30 + 1 = 90 whole days.

    Design: Difficulty/combinatorial_formula/delinquency_late_penalty_precedes_the_collections_tier_lookup
    """
    _bundle, invoice_id = _delinquent_invoice_world(api)

    invoice = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        invoice,
        subtotal_cents=22857,
        admin_fee_cents=1143,
        assessed_cents=26400,
        paid_cents=0,
        adjusted_cents=0,
        outstanding_cents=26400,
        payment_status="UNPAID",
        collections_stage="FINAL_NOTICE",
    )
    A.assert_money_cents(invoice["late_penalty_cents"], 2400, "late_penalty_cents")
    assert invoice["days_delinquent"] == 90, (
        f"days_delinquent must be 90 whole days past 2026-01-31, got {invoice['days_delinquent']}"
    )
    A.assert_outstanding_identity(invoice)


def test_collections_tier_is_keyed_on_the_post_penalty_interim_total(api):
    """The referral total is 28512 cents, because the collections tier is chosen on the 26400 interim total that already contains the late penalty rather than on the pre-penalty 24000.

    PRD §3.8: "Step three: an interim total is recomputed as `assessed_cents` minus `paid_cents` minus `adjusted_cents`, **after** step two."
    PRD §3.8: "Step four: the collections administrative charge is a flat 2000 cents when the interim total is at or below 25000 cents, the interim total times 0.08 rounded half up when it is above 25000 and at or below 100000, and a flat 10000 cents when it is above 100000."
    PRD §3.8: "The order matters concretely — a 24000-cent principal becomes 26400 at step three, which lands in the middle tier for a 2112-cent charge and a 28512-cent referral total, whereas pricing the tier off the pre-penalty 24000 would have yielded the 2000-cent flat charge and 26400."
    PRD §3.8: "And `referral_total_cents` is what the agency is handed, not what the premises owes the city: it does not feed `outstanding_cents`, so the premises' `outstanding_balance_cents` is untouched by the collections charge."
    PRD §3.8: "On success the stage moves `FINAL_NOTICE → REFERRED`, `referred_on` is stamped, `referral_total_cents` and `referral_agency` are stored, the invoice's `version` rises by 1, and — because referred invoices carry the top dunning rank — the invoice moves to the head of the automatic allocation order."

    The interim total of 26400 is above 25000 and at or below 100000, so the charge is
    26400 * 0.08 = 2112 and the referral total is 26400 + 2112 = 28512. The premises
    still owes only 26400, which is below the 50000-cent blocking threshold.

    Design: Difficulty/combinatorial_formula/delinquency_late_penalty_precedes_the_collections_tier_lookup
    """
    bundle, invoice_id = _delinquent_invoice_world(api)

    validate_success(
        api.refer_invoice_to_collections(
            invoice_id, {"referral_agency": "Statewide Municipal Recovery LLC"}, U.BILLING_CLERK
        ),
        200,
    )

    invoice = X.get_invoice(api, invoice_id)
    A.assert_invoice_totals(
        invoice, outstanding_cents=26400, payment_status="UNPAID", collections_stage="REFERRED"
    )
    A.assert_money_cents(invoice["referral_total_cents"], 28512, "referral_total_cents")
    assert invoice["referral_agency"] == "Statewide Municipal Recovery LLC", (
        f"the referral agency must be stored, got {invoice['referral_agency']!r}"
    )
    assert invoice["referred_on"] == "2026-05-01T00:00:00Z", (
        f"referred_on must be stamped at the logical clock, got {invoice['referred_on']!r}"
    )

    site = X.get_site(api, bundle.site_id)
    A.assert_money_cents(site["outstanding_balance_cents"], 26400, "outstanding_balance_cents")
    assert site["renewal_block_active"] is False, (
        "26400 cents is below the 50000-cent block, so renewal_block_active stays false"
    )
