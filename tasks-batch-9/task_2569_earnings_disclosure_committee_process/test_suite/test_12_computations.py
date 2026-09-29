"""Formulas driven with known inputs and read back one intermediate at a time.

Bridges that must add up exactly, a deadline table whose day counts differ by
form and filer category, a percentage rounded once at the end, an aggregate that
reads a shrinking input set, and a severity floor probed on both sides.
"""

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money,
    assert_two_decimal_places,
)
from test_helpers.factories import action_payload
from test_helpers.fixtures import (
    add_adjusted_measure,
    add_matching_tie_out,
    add_milestone,
    approve_document,
    assess_correction,
    assess_event,
    assign_subcert,
    build_committee,
    build_cycle,
    complete_milestone,
    create_document,
    deficiencies_of,
    log_material_event,
    open_close,
    reconcile_measure,
    refresh_cycle,
    refresh_document,
    scenario_close_open,
    start_milestone,
    submit_filing,
    submit_for_review,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

CALC_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]
SOLE_LEGAL_SEAT = [("legal", "Owen Legal", "LEGAL", False, True)]
COVERAGE_SEATS = CALC_SEATS + [("ops", "Pia Ops", "OPERATIONS", False, False)]


def _measure_document(api):
    """A draft earnings release carrying one freshly attached measure whose
    bridge is exact and whose presentation order is already correct."""
    committee = build_committee(
        api,
        seats=CALC_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Bridge Charter",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "EARNINGS_RELEASE", author_key="fin",
        title="Q2 FY2026 Earnings Release",
        safe_harbor_present=True,
    )
    measure = add_adjusted_measure(api, committee, document["id"])
    return committee, document, measure


def test_the_bridge_sum_the_gap_and_the_prominence_verdict_are_each_exact(api):
    """Two bridging items of 150.25 and 50.25 sum to 200.50, which closes the gap
    between the adjusted 1200.50 and the reported 1000.00 to exactly 0.00; the
    reported figure is presented ahead of the adjusted one, so the presentation
    test passes and the row lands on RECONCILED rather than on either failure
    state — and the document gate is read on both sides of the call, blocked on
    reconciliation while the measure was a draft and cleared afterwards.

    PRD 3.7: "`reconciliation_sum` becomes the sum of the `amount` of every bridging item, rounded half up to two decimal places."

    PRD 3.7: "`reconciliation_gap` becomes the `adjusted_value` less the total of `comparable_gaap_value` and `reconciliation_sum`, again rounded half up to two decimal places — a gap of zero means the bridge is exact."

    PRD 3.7: "It reads `NO_MEASURES` when the document has no measures at all; `BLOCKED_RECONCILIATION` when at least one measure is in `DRAFT` or `REJECTED`; `BLOCKED_PROMINENCE` when no measure is in `DRAFT` or `REJECTED` but at least one is in `PROMINENCE_FAILED`; and `CLEARED` when every measure is `RECONCILED`."

    Design: Corner/calculations/adjusted_measure_reconciliation_produces_the_exact_sum_gap_and_prominence_verdict
    """
    committee, document, measure = _measure_document(api)

    assert measure["status"] == "DRAFT"
    assert measure["reconciliation_sum"] is None
    assert measure["reconciliation_gap"] is None
    assert measure["prominence_ok"] is None
    before = refresh_document(api, committee, document["id"])
    assert before["measure_gate_status"] == "BLOCKED_RECONCILIATION"

    reconciled = reconcile_measure(api, committee, measure["id"])
    assert_money(reconciled["reconciliation_sum"], 200.50)
    assert_money(reconciled["reconciliation_gap"], 0.00)
    assert_two_decimal_places(reconciled["reconciliation_sum"])
    assert reconciled["prominence_ok"] is True
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["version"] == 2

    after = refresh_document(api, committee, document["id"])
    assert after["measure_gate_status"] == "CLEARED"


def test_the_deadline_table_rolls_for_weekends_and_holidays_but_the_target_never_does(api):
    """Four cycles on one charter pin every branch that matters: a quarterly
    large-accelerated report takes 40 days onto a Sunday and rolls one day, an
    annual one takes 60 days onto a Saturday and rolls two, a quarterly
    non-accelerated report takes 45 days onto a Friday that needs no roll at all
    yet leaves an internal target on a Sunday, and a period ending on 29 July
    lands on a recognised holiday and rolls past it — a holiday roll rather than
    a weekend one.

    PRD 3.2: "First a statutory day count is selected from the combination of form and filer category: a quarterly report allows 40 calendar days for a large accelerated filer, 40 for an accelerated filer and 45 for a non-accelerated filer, while an annual report allows 60 calendar days for a large accelerated filer, 75 for an accelerated filer and 90 for a non-accelerated filer."

    PRD 3.2: "Then, and this asymmetry is deliberate, the cycle's `internal_target_utc` is obtained by subtracting `internal_buffer_days` **calendar** days from `statutory_deadline_utc` with no business-day roll of any kind, so an internal target can legitimately fall on a Saturday or a holiday."

    PRD 2.6: "A calendar date is a business day when it falls neither on a Saturday nor on a Sunday and is not one of the following nine recognised holidays: 2026-01-01, 2026-01-19, 2026-02-16, 2026-05-25, 2026-07-03, 2026-09-07, 2026-11-26, 2026-12-25 and 2027-01-01."

    Design: Corner/calculations/filing_deadline_table_holiday_roll_and_unrolled_internal_target_across_four_cycles
    """
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Standing Disclosure Committee Charter",
        chair_key="fin",
    )

    quarterly = build_cycle(api, committee)
    assert_instant_equals(quarterly["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(quarterly["internal_target_utc"], "2026-08-05T17:30:00Z")

    annual = build_cycle(
        api, committee, fiscal_period_label="FY2026-FY", form_type="FORM_10K"
    )
    assert_instant_equals(annual["statutory_deadline_utc"], "2026-08-31T17:30:00Z")
    assert_instant_equals(annual["internal_target_utc"], "2026-08-26T17:30:00Z")

    unhurried = build_cycle(
        api, committee, fiscal_period_label="FY2026-Q2-NA",
        filer_status="NON_ACCELERATED",
    )
    assert_instant_equals(unhurried["statutory_deadline_utc"], "2026-08-14T17:30:00Z")
    assert_instant_equals(unhurried["internal_target_utc"], "2026-08-09T17:30:00Z")

    over_a_holiday = build_cycle(
        api, committee, fiscal_period_label="FY2027-Q1", period_end_date="2026-07-29"
    )
    assert_instant_equals(over_a_holiday["statutory_deadline_utc"], "2026-09-08T17:30:00Z")
    assert_instant_equals(over_a_holiday["internal_target_utc"], "2026-09-03T17:30:00Z")


def _open_cycle(api, committee, label):
    """A CLOSE_OPEN cycle whose only milestone is the canonical close window."""
    cycle = build_cycle(api, committee, fiscal_period_label=label)
    add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    return cycle


def test_coverage_rounds_the_final_quotient_once_in_both_directions(api):
    """The same code path produces both rounding directions: 55.00 over 75.00 is
    73.3333..., which half-up leaves at 73.33, while 30.00 over 45.00 is
    66.6666..., which half-up lifts to 66.67. Both readings are stored to exactly
    two places, and the first is unreachable if a per-scope percentage is rounded
    before the figures are combined.

    PRD 3.4: "Otherwise the raw `scope_weight` values of the numerator set are summed, the raw `scope_weight` values of the denominator set are summed, the first sum is divided by the second, the quotient is multiplied by 100, and the result is rounded half up to two decimal places exactly once."

    PRD 2.5: "Half-up rounding is applied exactly once per derived value, at the point the specification for that value says so — never repeatedly at intermediate steps, because rounding a sum of already-rounded terms produces a different answer than rounding the sum of the raw terms, and this system pins the latter wherever the two diverge."

    Design: Corner/calculations/coverage_percentage_rounds_half_up_to_two_places_once_on_the_final_quotient
    """
    committee = build_committee(
        api,
        seats=COVERAGE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Rounding Charter",
    )
    heavier = _open_cycle(api, committee, "FY2026-Q2")
    lighter = _open_cycle(api, committee, "FY2026-Q2-ALT")

    revenue = assign_subcert(api, committee, heavier["id"], "fin", "REVENUE")
    contingency = assign_subcert(
        api, committee, heavier["id"], "legal", "LEGAL_CONTINGENCY"
    )
    operations = assign_subcert(api, committee, heavier["id"], "ops", "OPERATIONS")
    assert_money(revenue["scope_weight"], 30.00)
    assert_money(contingency["scope_weight"], 25.00)
    assert_money(operations["scope_weight"], 20.00)

    submit_subcert(api, committee, revenue["id"], "fin")
    delivered = submit_subcert(api, committee, contingency["id"], "legal")
    assert delivered["status"] == "SUBMITTED"

    rounded_down = refresh_cycle(api, heavier["id"])
    assert_money(rounded_down["total_assigned_scope_weight"], 75.00)
    assert_money(rounded_down["certification_coverage_pct"], 73.33)
    assert_two_decimal_places(rounded_down["certification_coverage_pct"])

    second_revenue = assign_subcert(api, committee, lighter["id"], "fin", "REVENUE")
    communications = assign_subcert(
        api, committee, lighter["id"], "ops", "IR_COMMUNICATIONS"
    )
    assert_money(communications["scope_weight"], 15.00)
    submit_subcert(api, committee, second_revenue["id"], "fin")

    rounded_up = refresh_cycle(api, lighter["id"])
    assert_money(rounded_up["total_assigned_scope_weight"], 45.00)
    assert_money(rounded_up["certification_coverage_pct"], 66.67)

    assert validate_success(api.get_subcert(operations["id"], admin_headers()))[
        "status"
    ] == "PENDING"
    assert validate_success(api.get_subcert(communications["id"], admin_headers()))[
        "status"
    ] == "PENDING"


def _milestone_of(api, cycle_id, kind):
    rows = validate_success(api.list_cycle_milestones(cycle_id, admin_headers()))
    matches = [row for row in rows if row["kind"] == kind]
    assert len(matches) == 1
    return matches[0]


def _two_open_windows(api):
    """A CLOSE_OPEN cycle carrying a close window with a week of room and a
    filing window with a single day of it."""
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Slack Set Charter",
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    close = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    filing = add_milestone(
        api, committee, cycle["id"], "FILING",
        "2026-08-09T00:00:00Z", "2026-08-09T06:00:00Z",
    )
    open_close(api, committee, cycle["id"])
    return committee, cycle, close, filing


def test_the_slack_aggregate_reads_only_the_open_rows_and_then_the_sentinel(api):
    """The aggregate is re-read three times as its input set shrinks: with both
    windows open it reports the tighter of the two, completing the window that
    held the minimum moves it back to the looser one, and completing the last
    open window empties the set so the reading becomes the sentinel rather than
    zero or null — while each completed row keeps its own figures frozen.

    PRD 3.3: "At cycle level, `min_slack_days_calendar` and `min_slack_days_business` are the minimum of the corresponding per-milestone value taken over the **open** milestones only — those whose `status` is `PLANNED` or `IN_PROGRESS`."

    PRD 3.3: "Milestones in `COMPLETE` or `BREACHED` are excluded from the aggregate while keeping their own per-row slack figures frozen at their last computation."

    PRD 3.3: "When no open milestone remains, both cycle-level figures are set to 9999."

    Design: Corner/calculations/slack_aggregate_reads_only_open_milestones_and_falls_back_to_the_empty_set_sentinel
    """
    committee, cycle, close, filing = _two_open_windows(api)
    assert close["slack_calendar_days"] == 7
    assert close["slack_business_days"] == 5
    assert filing["slack_calendar_days"] == 1
    assert filing["slack_business_days"] == 1

    both_open = refresh_cycle(api, cycle["id"])
    assert both_open["min_slack_days_calendar"] == 1
    assert both_open["min_slack_days_business"] == 1

    start_milestone(api, committee, filing["id"])
    complete_milestone(api, committee, filing["id"])
    one_open = refresh_cycle(api, cycle["id"])
    assert one_open["min_slack_days_calendar"] == 7
    assert one_open["min_slack_days_business"] == 5

    start_milestone(api, committee, close["id"])
    complete_milestone(api, committee, close["id"])
    none_open = refresh_cycle(api, cycle["id"])
    assert none_open["min_slack_days_calendar"] == 9999
    assert none_open["min_slack_days_business"] == 9999

    frozen_filing = _milestone_of(api, cycle["id"], "FILING")
    assert frozen_filing["status"] == "COMPLETE"
    assert frozen_filing["slack_calendar_days"] == 1
    assert frozen_filing["slack_business_days"] == 1

    frozen_close = _milestone_of(api, cycle["id"], "CLOSE")
    assert frozen_close["status"] == "COMPLETE"
    assert frozen_close["slack_calendar_days"] == 7
    assert frozen_close["slack_business_days"] == 5


EVENT_NOTES = {
    "below": "Below the reportable materiality floor; monitored in the routine calendar.",
    "attempt": "Attempted to treat the boundary case as non-reportable.",
    "on": "At the reportable floor; current report required.",
    "above": "Above the reportable floor; current report required.",
}


def _three_events(api):
    """One PLANNING cycle carrying three UNASSESSED events whose magnitudes
    straddle five percent of the ten-million materiality base."""
    committee = build_committee(
        api,
        seats=SOLE_LEGAL_SEAT,
        min_quorum_count=1,
        required_functions=["LEGAL"],
        name="Materiality Floor Charter",
        chair_key="legal",
    )
    cycle = build_cycle(api, committee)
    assert cycle["status"] == "PLANNING"
    below = log_material_event(
        api, committee, cycle["id"],
        category="LITIGATION_JUDGMENT",
        occurred_utc="2026-07-30T12:00:00Z",
        discovered_utc="2026-08-03T09:00:00Z",
        magnitude_amount=499000,
        description="Adverse trial court judgment, appeal filed.",
    )
    boundary = log_material_event(
        api, committee, cycle["id"],
        category="IMPAIRMENT",
        occurred_utc="2026-07-30T12:00:00Z",
        discovered_utc="2026-08-03T09:00:00Z",
        magnitude_amount=500000,
        description="Retail segment goodwill impairment indicator.",
    )
    above = log_material_event(
        api, committee, cycle["id"],
        category="DEBT_COVENANT_BREACH",
        occurred_utc="2026-07-30T12:00:00Z",
        discovered_utc="2026-08-03T09:00:00Z",
        magnitude_amount=501000,
        description="Leverage covenant breached at quarter end.",
    )
    return committee, cycle, below, boundary, above


def test_the_reportable_floor_is_probed_below_on_and_above_five_percent(api):
    """Three events against a ten-million base score 4.99, 5.00 and 5.01. The
    first may be waved off with a null deadline; the second sits exactly on the
    floor and its identical not-reportable determination is refused, then accepted
    as reportable with a deadline four business days after the Monday discovery;
    the third behaves like the second, and the open count falls only by the one
    event that left the set.

    PRD 3.8: "Its `severity_score` is the absolute value of `magnitude_amount` divided by the cycle's `materiality_base_amount`, expressed as a percentage, capped at 100.00 and rounded half up to two decimal places."

    PRD 3.8: "A materiality floor constrains which branch legal may choose: an event whose `severity_score` is greater than or equal to 5.00 percent cannot be determined `NOT_REPORTABLE`, and the attempt is rejected with `ERR_EVENT_DETERMINATION_CONFLICT`."

    PRD 3.8: "On the `REPORTABLE` branch the `current_report_deadline_utc` is set to the instant four business days after the calendar date of `discovered_utc`, at 17:30:00 UTC on that resulting date."

    Design: Corner/calculations/reportable_severity_boundary_probed_below_on_and_above_five_percent
    """
    committee, cycle, below, boundary, above = _three_events(api)

    assert_money(below["severity_score"], 4.99)
    assert_money(boundary["severity_score"], 5.00)
    assert_money(above["severity_score"], 5.01)
    for row in (below, boundary, above):
        assert row["assessment_status"] == "UNASSESSED"
        assert row["current_report_deadline_utc"] is None
    assert refresh_cycle(api, cycle["id"])["open_material_event_count"] == 3

    waved_off = assess_event(
        api, committee, below["id"], "NOT_REPORTABLE",
        determination_note=EVENT_NOTES["below"],
    )
    assert waved_off["assessment_status"] == "NOT_REPORTABLE"
    assert waved_off["current_report_deadline_utc"] is None

    validate_error(
        api.transition_material_event(
            boundary["id"],
            action_payload(
                "ASSESS",
                determination="NOT_REPORTABLE",
                determination_note=EVENT_NOTES["attempt"],
            ),
            committee.counsel("legal"),
        ),
        "ERR_EVENT_DETERMINATION_CONFLICT",
        409,
    )

    on_floor = assess_event(
        api, committee, boundary["id"], "REPORTABLE",
        determination_note=EVENT_NOTES["on"],
    )
    assert on_floor["assessment_status"] == "REPORTABLE"
    assert_instant_equals(
        on_floor["current_report_deadline_utc"], "2026-08-07T17:30:00Z"
    )

    over_floor = assess_event(
        api, committee, above["id"], "REPORTABLE",
        determination_note=EVENT_NOTES["above"],
    )
    assert over_floor["assessment_status"] == "REPORTABLE"
    assert_instant_equals(
        over_floor["current_report_deadline_utc"], "2026-08-07T17:30:00Z"
    )

    assert refresh_cycle(api, cycle["id"])["open_material_event_count"] == 2


def test_a_newly_planned_window_re_evaluates_the_minimum_with_no_transition_at_all(api):
    """The aggregate is forward-looking, so creating work moves it with no
    transition call: a cycle whose only open window is the close reads seven and
    five, adding a filing window that ends the day before the deadline drops the
    pair to one and one, and adding a review window that computes its own four and
    two leaves the pair where it was, because the aggregate is a minimum rather
    than the most recent write. All three rows stay PLANNED.

    PRD 3.3: "Slack is recomputed on milestone creation, on every milestone transition, and at the start of every cycle workflow transition."

    PRD 3.3: "For each milestone of the cycle, `slack_calendar_days` is the number of whole days in the interval from that milestone's `planned_end_utc` to the cycle's `statutory_deadline_utc`, truncated toward zero so any partial day is dropped; a milestone planned to end after the deadline yields a negative number."

    PRD 3.3: "The comparison is inclusive, so a gap of exactly the required number of hours is accepted; a shorter gap is rejected with `ERR_MILESTONE_BUFFER_VIOLATION`."

    Design: Corner/calculations/adding_a_pending_milestone_immediately_re_evaluates_the_forward_looking_minimum
    """
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Forward Looking Charter",
        chair_key="fin",
    )
    cycle = build_cycle(api, committee)
    close = add_milestone(
        api, committee, cycle["id"], "CLOSE",
        "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z",
    )
    opened = open_close(api, committee, cycle["id"])
    assert opened["min_slack_days_calendar"] == 7
    assert opened["min_slack_days_business"] == 5

    filing = add_milestone(
        api, committee, cycle["id"], "FILING",
        "2026-08-09T00:00:00Z", "2026-08-09T06:00:00Z",
    )
    after_filing = refresh_cycle(api, cycle["id"])
    assert after_filing["min_slack_days_calendar"] == 1
    assert after_filing["min_slack_days_business"] == 1

    review = add_milestone(
        api, committee, cycle["id"], "REVIEW",
        "2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z",
    )
    assert review["slack_calendar_days"] == 4
    assert review["slack_business_days"] == 2

    after_review = refresh_cycle(api, cycle["id"])
    assert after_review["min_slack_days_calendar"] == 1
    assert after_review["min_slack_days_business"] == 1

    for kind, row in (("CLOSE", close), ("FILING", filing), ("REVIEW", review)):
        assert _milestone_of(api, cycle["id"], kind)["id"] == row["id"]
        assert _milestone_of(api, cycle["id"], kind)["status"] == "PLANNED"


def test_omitting_the_method_selects_the_rollover_variant_and_the_revision_tier(
    draft_correction_cycle,
):
    """The variant is chosen by context rather than by data: with the same stored
    figures, an assess request that omits the method must fall back to the
    rollover reading, which ignores the carried-forward amount and gives 4.00
    percent — a revision, not a restatement. The knock-on chain is variant
    dependent too, so the deficiency scores 2.40 into the middle tier, the cycle's
    weight rises to 4.80, and the remediation axis stays where opening the
    correction left it.

    PRD 3.9: "The `method` supplied on the assess request may be `ROLLOVER` or `IRON_CURTAIN`, and defaults to `ROLLOVER` when omitted."

    PRD 3.9: "Under the rollover method, `materiality_pct` is the absolute value of `error_amount` divided by the absolute value of `current_period_pretax_income`, expressed as a percentage and rounded half up to two decimal places; `cumulative_prior_uncorrected_amount` is ignored entirely."

    PRD 3.9: "The `classification` then follows from that single percentage: `RESTATEMENT` when `materiality_pct` is greater than or equal to 5.00, otherwise `REVISION` when it is greater than or equal to 1.00, otherwise `IMMATERIAL`."

    PRD 3.9: "A `REVISION` classification therefore raises a deficiency and a weight but does **not** declare a restatement."

    Design: Corner/calculations/omitting_the_method_selects_the_rollover_variant_and_changes_the_classification
    """
    scenario = draft_correction_cycle
    api = scenario.api
    correction = scenario.correction
    assert correction["status"] == "DRAFT"
    assert correction["method"] is None
    assert correction["materiality_pct"] is None
    assert correction["classification"] is None

    before = refresh_cycle(api, scenario.cycle_id)
    assert before["restatement_stage"] == "UNDER_EVALUATION"
    assert_money(before["unresolved_deficiency_weight"], 0.00)

    assessed = assess_correction(
        api, correction["id"],
        likelihood_pct=40,
        magnitude_amount=500000,
        compensating_control_present=True,
    )
    assert assessed["method"] == "ROLLOVER"
    assert_money(assessed["materiality_pct"], 4.00)
    assert assessed["classification"] == "REVISION"
    assert assessed["status"] == "ASSESSED"

    rows = deficiencies_of(api, correction["id"])
    assert len(rows) == 1
    deficiency = rows[0]
    assert_money(deficiency["severity_score"], 2.40)
    assert deficiency["severity"] == "SIGNIFICANT_DEFICIENCY"
    assert_money(deficiency["deficiency_weight"], 4.80)
    assert deficiency["status"] == "OPEN"

    after = refresh_cycle(api, scenario.cycle_id)
    assert_money(after["unresolved_deficiency_weight"], 4.80)
    assert after["restatement_stage"] == "UNDER_EVALUATION"
    assert after["status"] == "FILED"


def test_the_amending_filing_takes_sequence_two_and_supersedes_the_first(filed_cycle):
    """The accession suffix counts prior filing rows in creation order, so a second
    filing built from the very same cycle fields reads two while the original keeps
    one. The whole amendment path is walked to get there: a second periodic filing
    document is drafted, reviewed and approved on a cycle that is already filed,
    the amended filing goes terminal, the workflow axis moves to AMENDED while the
    remediation axis stays untouched, and the original document keeps its filed
    status.

    PRD 3.9: "Its sequence number is one greater than the number of filings already on the cycle, counting **every** filing row regardless of status and ordering those rows by `created_at` ascending, never by `id`."

    PRD 3.9: "An amendment from `FILED` moves the cycle to `AMENDED`; an amendment from `AMENDED` leaves the cycle in `AMENDED` but still increments its `version`, so successive amendments are legal without limit."

    PRD 3.9: "In every amending case the superseded filing moves from `SUBMITTED` to the terminal `AMENDED_SUPERSEDED`."

    Design: Corner/calculations/second_filing_on_a_cycle_takes_sequence_two_and_supersedes_the_first_in_creation_order
    """
    scenario = filed_cycle
    api, committee = scenario.api, scenario.committee
    original_document = scenario.documents["PERIODIC_FILING"]
    original_filing = scenario.filing

    assert original_filing["accession_label"] == "FORM_10Q-FY2026-Q2-1"
    assert original_filing["late_flag"] is False
    assert_instant_equals(original_filing["filed_utc"], "2026-08-01T00:00:00Z")
    assert original_filing["status"] == "SUBMITTED"

    amendment = create_document(
        api, committee, scenario.cycle_id, "PERIODIC_FILING", "fin",
        title="Form 10-Q/A FY2026-Q2 Amendment No. 1",
        safe_harbor_present=True,
    )
    assert amendment["id"] != original_document["id"]
    add_matching_tie_out(
        api, committee, amendment["id"], line_label="Total revenue as amended"
    )
    submit_for_review(api, committee, amendment["id"], "fin")
    approved = approve_document(api, committee, amendment["id"], "legal")
    assert approved["status"] == "APPROVED"

    second = submit_filing(
        api, scenario.cycle_id, amendment["id"],
        amends_filing_id=original_filing["id"],
    )
    assert second["accession_label"] == "FORM_10Q-FY2026-Q2-2"
    assert second["late_flag"] is False
    assert second["status"] == "SUBMITTED"
    assert second["amends_filing_id"] == original_filing["id"]

    superseded = validate_success(
        api.get_filing(original_filing["id"], admin_headers())
    )
    assert superseded["status"] == "AMENDED_SUPERSEDED"
    assert superseded["accession_label"] == "FORM_10Q-FY2026-Q2-1"

    assert refresh_document(api, committee, original_document["id"])["status"] == "FILED"
    assert refresh_document(api, committee, amendment["id"])["status"] == "FILED"

    cycle = refresh_cycle(api, scenario.cycle_id)
    assert cycle["status"] == "AMENDED"
    assert cycle["restatement_stage"] == "NONE"
