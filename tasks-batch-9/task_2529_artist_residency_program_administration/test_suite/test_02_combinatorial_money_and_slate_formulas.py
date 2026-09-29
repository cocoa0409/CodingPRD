"""Formulas whose nested clamps, rounding order and pinned divisors all matter."""

from test_helpers import (
    FINANCE_SCHEDULER_USER_ID,
    SPONSORED_SESSION_START,
    assert_money_equals,
    assert_score_equals,
    assign_and_score,
    create_applicant,
    create_chair,
    create_international_applicant,
    create_panelist,
    create_residency,
    disbursements_for,
    generate_stipend_schedule,
    lock_slate,
    pay_disbursement,
    payment_dates,
    read_cycle,
    refresh_application,
    refresh_residency,
    schedule_residency,
    setup_locked_slate,
    setup_open_cycle,
    setup_panel_review_cycle,
    setup_residency_ready_for_payment,
    tax_report,
)

# Two disciplines, each owed a minimum of one slot, so the first allocation
# bucket provably consumes two of the ten cohort slots.
TWO_DISCIPLINES = [
    {},
    {
        "code": "PRINT",
        "name": "Printmaking",
        "required_capability_tags": ["PRINT_PRESS"],
        "required_ventilation_class": "NONE",
    },
]


def _scheduled_residency(api, weeks, start="2026-11-02", international=False):
    cycle = setup_open_cycle(api)
    maker = create_international_applicant if international else create_applicant
    applicant = maker(api)
    residency = create_residency(api, cycle, applicant)
    schedule_residency(api, residency, start, weeks)
    return cycle, residency


def test_five_week_session_splits_into_three_periods(api):
    """A week count that is not a multiple of two rounds the period count up.

    PRD: "The number of periods is the residency's `session_length_weeks`
    divided by two, rounded **up**."

    Design: Difficulty/combinatorial_formula/stipend_period_split_nested_min_produces_short_final_period
    """
    _cycle, residency = _scheduled_residency(api, 5)
    assert residency.session_end_date == "2026-12-06"

    generate_stipend_schedule(api, residency)

    rows = disbursements_for(api, residency.residency_id)
    assert len(rows) == 3
    assert [r["period_index"] for r in rows] == [1, 2, 3]


def test_the_short_final_period_is_clamped_on_both_its_price_and_its_end_date(api):
    """The last period takes the remaining weeks and stops at the session end.

    PRD: "each period's `weeks_in_period` is two, except that the last period
    takes only the weeks that remain, so a five-week session splits into two,
    two and one."

    Design: Difficulty/combinatorial_formula/stipend_period_split_nested_min_produces_short_final_period
    """
    _cycle, residency = _scheduled_residency(api, 5)
    generate_stipend_schedule(api, residency)
    rows = disbursements_for(api, residency.residency_id)

    first, second, third = rows
    assert (first["period_start_date"], first["period_end_date"]) == (
        "2026-11-02",
        "2026-11-15",
    )
    assert_money_equals(first["gross_cents"], 140000, "period 1 gross")
    assert (second["period_start_date"], second["period_end_date"]) == (
        "2026-11-16",
        "2026-11-29",
    )
    assert_money_equals(second["gross_cents"], 140000, "period 2 gross")
    # Both clamps bite here: one week of pay, and an end date pulled in 7 days.
    assert (third["period_start_date"], third["period_end_date"]) == (
        "2026-11-30",
        "2026-12-06",
    )
    assert_money_equals(third["gross_cents"], 70000, "period 3 gross")
    assert third["weeks_in_period"] == 1
    assert third["period_end_date"] == residency.session_end_date


def test_the_period_split_conserves_the_whole_award(api):
    """Row grosses sum to the residency award and carry the scheduler's identity.

    PRD: "five weeks at the same rate yields 140,000, 140,000 and 70,000
    summing to 350,000."

    Design: Difficulty/combinatorial_formula/stipend_period_split_nested_min_produces_short_final_period
    """
    _cycle, residency = _scheduled_residency(api, 5)
    generate_stipend_schedule(api, residency)
    rows = disbursements_for(api, residency.residency_id)

    assert_money_equals(
        sum(r["gross_cents"] for r in rows), 350000, "sum of period grosses"
    )
    assert_money_equals(
        residency.residency["stipend_total_cents"], 350000, "residency award"
    )
    for row in rows:
        assert row["status"] == "SCHEDULED"
        assert row["scheduled_by_user_id"] == FINANCE_SCHEDULER_USER_ID
        assert row["tax_form_type"] == "W9"
        assert row["period_end_date"] <= residency.session_end_date


def test_the_cumulative_exemption_is_consumed_once_not_once_per_payment(api):
    """The first payment absorbs the exemption; later ones are fully taxable.

    PRD: "The taxable amount is then found from a **cumulative** exemption of
    60,000 cents across the residency's paid disbursements, not a per-payment
    exemption."

    Design: Difficulty/combinatorial_formula/withholding_round_per_disbursement_then_sum_versus_round_once
    """
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api, session_length_weeks=8, international=True, weekly_rate_override_cents=43751
    )
    assert len(rows) == 4
    dates = payment_dates(SPONSORED_SESSION_START, 4)

    paid = []
    for index, row in enumerate(rows):
        assert_money_equals(row["gross_cents"], 87502, f"period {index + 1} gross")
        paid.append(pay_disbursement(api, row["id"], dates[index]))

    assert [p["cumulative_taxable_cents"] for p in paid] == [27502, 87502, 87502, 87502]
    assert [p["withholding_cents"] for p in paid] == [4125, 13125, 13125, 13125]
    assert [p["net_cents"] for p in paid] == [83377, 74377, 74377, 74377]
    for payment in paid:
        assert payment["withholding_rate"] == 0.15
        assert payment["tax_form_type"] == "1042S"


def test_the_tax_report_separates_the_two_rounding_orders(api):
    """Per-payment rounding then summing differs from rounding the total once.

    PRD: "For a treaty resident paid four periods of 87,502 cents at 0.15, the
    per-payment withholdings are 4,125, 13,125, 13,125 and 13,125 cents,
    totalling 43,500, while the statutory line is the rate applied once to
    290,008 cents of taxable income, rounding to 43,501, so the delta is −1."

    Design: Difficulty/combinatorial_formula/withholding_round_per_disbursement_then_sum_versus_round_once
    """
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api, session_length_weeks=8, international=True, weekly_rate_override_cents=43751
    )
    for row, paid_on in zip(rows, payment_dates(SPONSORED_SESSION_START, 4)):
        pay_disbursement(api, row["id"], paid_on)

    report = tax_report(api, residency.residency_id)

    assert report["tax_form_type"] == "1042S"
    assert report["withholding_rate"] == 0.15
    assert report["paid_period_count"] == 4
    assert_money_equals(report["annual_gross_cents"], 350008, "annual gross")
    assert_money_equals(report["annual_taxable_cents"], 290008, "annual taxable")
    assert_money_equals(report["withheld_actual_cents"], 43500, "withheld actual")
    assert_money_equals(
        report["statutory_liability_cents"], 43501, "statutory liability"
    )
    assert report["reconciliation_delta_cents"] == -1
    assert (
        report["reconciliation_delta_cents"]
        == report["withheld_actual_cents"] - report["statutory_liability_cents"]
    )


def test_the_residency_ledger_tracks_the_actual_withholding_variant(api):
    """Money held back on the residency matches the per-payment sum.

    PRD: "`withheld_actual_cents` is the sum of `withholding_cents` over those
    same paid rows — the money actually held back, with each payment's rounding
    already baked in."

    Design: Difficulty/combinatorial_formula/withholding_round_per_disbursement_then_sum_versus_round_once
    """
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api, session_length_weeks=8, international=True, weekly_rate_override_cents=43751
    )
    for row, paid_on in zip(rows, payment_dates(SPONSORED_SESSION_START, 4)):
        pay_disbursement(api, row["id"], paid_on)

    settled = refresh_residency(api, residency)
    assert_money_equals(
        settled["withholding_to_date_cents"], 43500, "withholding to date"
    )
    assert_money_equals(
        settled["stipend_paid_gross_cents"], 350008, "paid gross to date"
    )


def test_the_alumni_reserve_is_pinned_to_the_cohort_target(api):
    """Discipline minimums consume slots without shrinking the reserve divisor.

    PRD: "The reserve is **pinned to the cohort target**, not recomputed
    against whatever slots survive the first bucket: with a cohort target of 10
    and a reserve fraction of 0.25 the reserve is 3 slots, and it stays 3 slots
    even after discipline minimums have already consumed 2 of the 10".

    Design: Difficulty/combinatorial_formula/alumni_reserve_pinned_to_cohort_target_not_post_bucket_remainder
    """
    cycle, apps, _chair = setup_locked_slate(
        api,
        applicant_count=2,
        panelist_count=2,
        discipline_specs=TWO_DISCIPLINES,
        cohort_target_size=10,
        alumni_reserve_pct=0.25,
    )
    locked = read_cycle(api, cycle.cycle_id)

    assert locked["status"] == "SLATE_LOCKED"
    # ceil(0.25 * 10) = 3, never ceil(0.25 * (10 - 2)) = 2.
    assert locked["alumni_reserved_slots"] == 3
    assert locked["cohort_target_size"] - locked["alumni_reserved_slots"] == 7
    assert len(apps) == 2


def test_the_reserve_is_only_written_when_the_slate_is_allocated(api):
    """Before allocation the cycle reports no reserved slots at all.

    PRD: "`alumni_reserved_slots` is set when the slate is allocated."

    Design: Difficulty/combinatorial_formula/alumni_reserve_pinned_to_cohort_target_not_post_bucket_remainder
    """
    cycle, apps = setup_panel_review_cycle(
        api,
        applicant_count=2,
        discipline_specs=TWO_DISCIPLINES,
        cohort_target_size=10,
        alumni_reserve_pct=0.25,
    )
    panelists = [create_panelist(api) for _ in range(2)]
    for app in apps:
        for panelist in panelists:
            assign_and_score(api, app, panelist)

    before = read_cycle(api, cycle.cycle_id)
    assert before["slate_ready_count"] == 2
    assert before["panel_review_complete"] is True
    assert before["alumni_reserved_slots"] == 0

    lock_slate(api, cycle, create_chair(api))

    after = read_cycle(api, cycle.cycle_id)
    assert after["alumni_reserved_slots"] == 3


def test_offers_do_not_touch_the_slot_ledger(api):
    """The reserve arithmetic and the filled-slot ledger stay independent.

    PRD: "`slots_filled_count` is the number of residencies of the cycle in
    those same four statuses, and `slots_open_count` is the cohort target less
    the filled count, floored at zero so it never reports a negative."

    Design: Difficulty/combinatorial_formula/alumni_reserve_pinned_to_cohort_target_not_post_bucket_remainder
    """
    cycle, apps, _chair = setup_locked_slate(
        api,
        applicant_count=2,
        panelist_count=2,
        discipline_specs=TWO_DISCIPLINES,
        cohort_target_size=10,
        alumni_reserve_pct=0.25,
    )
    locked = read_cycle(api, cycle.cycle_id)

    assert locked["slots_filled_count"] == 0
    assert locked["slots_open_count"] == 10

    for app in apps:
        record = refresh_application(api, app)
        assert record["status"] == "OFFERED"
        assert_score_equals(record["final_panel_score"], 80.00, "final score")
        assert record["rank_in_discipline"] == 1
        assert record["waitlist_rank"] is None
