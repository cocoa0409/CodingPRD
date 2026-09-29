"""Two calculations that expose two variants each on identical stored data.

The cycle calendar answers "how much room is left" twice — once in calendar
days and once in business days — and a post-filing correction answers "how
material is this" twice, once under the rollover method and once under the
iron-curtain method.
"""

from test_helpers.assertions import (
    assert_instant_equals,
    assert_integer,
    assert_money,
    assert_slack,
)
from test_helpers.fixtures import (
    add_milestone,
    assess_correction,
    build_committee,
    build_cycle,
    deficiencies_of,
    open_correction,
    readiness,
    refresh_cycle,
)

SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]


def _single_seat_committee(api):
    """A charter that a single voting finance member can adopt on its own."""
    return build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Q2 Disclosure Committee Charter",
        chair_key="fin",
    )


def test_close_milestone_reports_three_calendar_days_and_one_business_day(api):
    """The same close window ending 2026-08-07T00:00:00Z against a deadline of
    2026-08-10T17:30:00Z yields 3 under the calendar variant and 1 under the
    business-day variant, because the weekend of 8 and 9 August is not counted.

    PRD 3.3: "For each milestone of the cycle, `slack_calendar_days` is the number of whole days in the interval from that milestone's `planned_end_utc` to the cycle's `statutory_deadline_utc`, truncated toward zero so any partial day is dropped; a milestone planned to end after the deadline yields a negative number."

    Design: Difficulty/dual_variant_calc/milestone_slack_calendar_versus_business_day_variant_divergence
    """
    committee = _single_seat_committee(api)
    cycle = build_cycle(api, committee)
    assert_instant_equals(cycle["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(cycle["internal_target_utc"], "2026-08-05T17:30:00Z")

    milestone = add_milestone(
        api,
        committee,
        cycle["id"],
        "CLOSE",
        "2026-08-03T00:00:00Z",
        "2026-08-07T00:00:00Z",
    )
    assert milestone["status"] == "PLANNED"
    assert_integer(milestone["slack_calendar_days"])
    assert_integer(milestone["slack_business_days"])
    assert_slack(milestone, 3, 1)
    assert milestone["slack_calendar_days"] != milestone["slack_business_days"], (
        "the two variants must disagree on this window"
    )

    after = refresh_cycle(api, cycle["id"])
    assert_slack(after, 3, 1)
    assert after["status"] == "PLANNING"


def test_readiness_read_carries_both_slack_variants_for_the_one_open_window(api):
    """The dashboard re-runs the slack computation before answering, and reports
    both variants side by side: 3 calendar days and 1 business day for the only
    open milestone on the cycle.

    PRD 3.2: "It is a computed read, and unusually for a read it performs work before answering — it runs the breach sweep and re-runs the slack computation against the current logical clock, so the slack figures it reports are never stale."

    Design: Difficulty/dual_variant_calc/milestone_slack_calendar_versus_business_day_variant_divergence
    """
    committee = _single_seat_committee(api)
    cycle = build_cycle(api, committee)
    add_milestone(
        api,
        committee,
        cycle["id"],
        "CLOSE",
        "2026-08-03T00:00:00Z",
        "2026-08-07T00:00:00Z",
    )

    dashboard = readiness(api, cycle["id"])
    assert dashboard["cycle_id"] == cycle["id"]
    assert dashboard["cycle_status"] == "PLANNING"
    assert_instant_equals(dashboard["statutory_deadline_utc"], "2026-08-10T17:30:00Z")
    assert_instant_equals(dashboard["internal_target_utc"], "2026-08-05T17:30:00Z")
    assert_slack(dashboard, 3, 1)


def test_rollover_and_iron_curtain_split_the_same_correction_figures(filed_cycle):
    """Two corrections carrying byte-identical figures land on opposite sides of
    the 5.00 threshold: 4.00 and REVISION under the rollover method, 5.83 and
    RESTATEMENT under the iron-curtain method.

    PRD 3.9: "For an `error_amount` of 400000, a `current_period_pretax_income` of 10000000, a `cumulative_prior_uncorrected_amount` of 300000 and a `prior_period_pretax_income` of 12000000, the rollover method returns 4.00 and classifies the correction as a `REVISION`, while the iron-curtain method returns 5.83 and classifies the identical data as a `RESTATEMENT`."

    Design: Difficulty/dual_variant_calc/correction_materiality_rollover_versus_iron_curtain_variant_divergence
    """
    api = filed_cycle.api
    filing_id = filed_cycle.filing["id"]
    figures = dict(
        error_amount=400000,
        current_period_pretax_income=10000000,
        prior_period_pretax_income=12000000,
        cumulative_prior_uncorrected_amount=300000,
    )
    correction_a = open_correction(
        api, filing_id, description="Understated warranty accrual", **figures
    )
    correction_b = open_correction(
        api, filing_id, description="Same warranty accrual, iron-curtain view", **figures
    )
    assert correction_a["status"] == "DRAFT"
    assert correction_b["status"] == "DRAFT"

    assessed_a = assess_correction(
        api,
        correction_a["id"],
        method="ROLLOVER",
        likelihood_pct=40,
        magnitude_amount=700000,
        compensating_control_present=False,
    )
    assessed_b = assess_correction(
        api,
        correction_b["id"],
        method="IRON_CURTAIN",
        likelihood_pct=40,
        magnitude_amount=700000,
        compensating_control_present=False,
    )

    assert assessed_a["method"] == "ROLLOVER"
    assert_money(assessed_a["materiality_pct"], 4.00)
    assert assessed_a["classification"] == "REVISION"
    assert assessed_a["status"] == "ASSESSED"

    assert assessed_b["method"] == "IRON_CURTAIN"
    assert_money(assessed_b["materiality_pct"], 5.83)
    assert assessed_b["classification"] == "RESTATEMENT"
    assert assessed_b["status"] == "ASSESSED"

    assert float(assessed_a["materiality_pct"]) != float(assessed_b["materiality_pct"]), (
        "the two methods must not agree on these figures"
    )


def test_the_two_methods_cascade_into_different_deficiency_tiers(filed_cycle):
    """The classification each method reaches drives a different deficiency
    tier: 4.00 scores a significant deficiency weighted 8.00, while 5.83 scores
    a material weakness weighted 23.32, and the cycle carries the sum 31.32 on
    its remediation axis while staying FILED on its workflow axis.

    PRD 3.9: "Sixth, `deficiency_weight` is `severity_score` multiplied by a factor fixed by the selected tier — 1.0 for a `DEFICIENCY`, 2.0 for a `SIGNIFICANT_DEFICIENCY` and 4.0 for a `MATERIAL_WEAKNESS` — and rounded half up to two decimal places."

    Design: Difficulty/dual_variant_calc/correction_materiality_rollover_versus_iron_curtain_variant_divergence
    """
    api = filed_cycle.api
    filing_id = filed_cycle.filing["id"]
    figures = dict(
        error_amount=400000,
        current_period_pretax_income=10000000,
        prior_period_pretax_income=12000000,
        cumulative_prior_uncorrected_amount=300000,
    )
    correction_a = open_correction(
        api, filing_id, description="Understated warranty accrual", **figures
    )
    correction_b = open_correction(
        api, filing_id, description="Same warranty accrual, iron-curtain view", **figures
    )
    assess_correction(
        api,
        correction_a["id"],
        method="ROLLOVER",
        likelihood_pct=40,
        magnitude_amount=700000,
        compensating_control_present=False,
    )
    assess_correction(
        api,
        correction_b["id"],
        method="IRON_CURTAIN",
        likelihood_pct=40,
        magnitude_amount=700000,
        compensating_control_present=False,
    )

    rows_a = deficiencies_of(api, correction_a["id"])
    assert len(rows_a) == 1, f"the rollover correction raises exactly one deficiency: {rows_a}"
    assert rows_a[0]["severity"] == "SIGNIFICANT_DEFICIENCY"
    assert_money(rows_a[0]["severity_score"], 4.00)
    assert_money(rows_a[0]["deficiency_weight"], 8.00)
    assert rows_a[0]["status"] == "OPEN"

    rows_b = deficiencies_of(api, correction_b["id"])
    assert len(rows_b) == 1, f"the iron-curtain correction raises exactly one deficiency: {rows_b}"
    assert rows_b[0]["severity"] == "MATERIAL_WEAKNESS"
    assert_money(rows_b[0]["severity_score"], 5.83)
    assert_money(rows_b[0]["deficiency_weight"], 23.32)
    assert rows_b[0]["status"] == "OPEN"

    cycle = refresh_cycle(api, filed_cycle.cycle_id)
    assert_money(cycle["unresolved_deficiency_weight"], 31.32)
    assert cycle["restatement_stage"] == "RESTATEMENT_DECLARED"
    assert cycle["status"] == "FILED"
