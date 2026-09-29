"""The wage-differential ledger, its two variants, the compensating reversal and
the program outcome metrics."""
from test_helpers import (
    ApiErrorId,
    assert_wage_entry,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

WORK_WEEK = ("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07")


def test_a_provisional_entry_rounds_once_after_summing_the_weekdays(api):
    """PRD §3.10: "A **`PROVISIONAL`** entry is forward-looking and rounds exactly once, at the very end of the summation. Its `counted_day_count` is the number of calendar days in the period from `period_start` through `period_end` whose weekday falls Monday through Friday; the placement's `logged_hours` is ignored entirely. The pre-cap gross is that day count, multiplied by the statutory replacement rate of 0.6667, multiplied by the day gap evaluated at the placement's `scheduled_hours_per_day`, the whole product rounded half up to whole cents in that single operation. Its `tier_multiplier` is pinned at 1.00 because the cumulative duration is not yet known, and its `offset_cents` is zero."
    PRD §3.10: "The worker's pre-injury daily wage is `pre_injury_weekly_wage_cents` divided by the five workdays in a week, held as an exact rational value and never rounded at this step. For a given number of hours, the day's gap is that pre-injury daily wage minus the job's `hourly_rate_cents` multiplied by those hours, floored at zero."

    Design: Difficulty/dual_variant_calc/wage_provisional_vs_final_diverge_on_same_five_days
    """
    ctx = fixtures.setup_placement_with_logged_week(work_dates=WORK_WEEK)

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "PROVISIONAL", "period_start": "2026-08-03",
             "period_end": "2026-08-07"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert_wage_entry(data)
    assert data["counted_day_count"] == 5
    assert data["gross_differential_cents"] == 55003, (
        f"round(5 * 0.6667 * 16500) in one operation is 55003, got "
        f"{data['gross_differential_cents']}"
    )
    assert data["net_amount_cents"] == 55003
    assert data["offset_cents"] == 0
    assert data["tier_multiplier"] == 1.00


def test_a_final_entry_over_the_same_days_rounds_per_day_and_withholds_the_offset(api):
    """PRD §3.10: "A **`FINAL`** entry is a reconciliation against what was actually worked, and it rounds once per day *before* summing. Its `counted_day_count` is the number of entries in the placement's `logged_hours` whose `work_date` falls inside the period, walked in `work_date` ascending order. For each such entry, the statutory replacement rate of 0.6667 is multiplied by the day gap evaluated at that entry's `hours_worked` and the product is rounded half up to whole cents; those per-day amounts are then added together."
    PRD §3.10: "A final entry also withholds a benefit offset: when the placement's `benefit_continuation_status` is `EMPLOYER_SUBSIDIZED`, `offset_cents` is `gross_differential_cents` multiplied by the benefit offset rate of 0.05, rounded half up to whole cents; in every other benefit state the offset is zero."

    Design: Difficulty/dual_variant_calc/wage_provisional_vs_final_diverge_on_same_five_days
    """
    ctx = fixtures.setup_placement_with_logged_week(work_dates=WORK_WEEK)
    provisional = fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "FINAL", "period_start": "2026-08-03", "period_end": "2026-08-07"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert data["gross_differential_cents"] == 55005, (
        f"five days of round(0.6667 * 16500) = 11001 sum to 55005, got "
        f"{data['gross_differential_cents']}"
    )
    assert data["offset_cents"] == 2750
    assert data["net_amount_cents"] == 52255
    assert data["tier_multiplier"] == 1.00
    assert data["net_amount_cents"] != provisional["net_amount_cents"], (
        "the two variants read the same five days and still post different cents"
    )


def test_the_claim_paid_total_sums_both_variant_entries(api):
    """PRD §3.10: "Posting recomputes the claim's `wage_differential_paid_cents` and raises the claim's `version` by 1."
    PRD §3.10: "At priority 28, no other entry of the same placement **and the same variant** may already cover any day inside the requested period, treating both periods as closed intervals; an overlap answers `ERR_WAGE_PERIOD_OVERLAP` with HTTP 409. A provisional accrual and a final reconciliation covering the very same days are therefore both permitted, which is the point of running two variants."

    Design: Difficulty/dual_variant_calc/wage_provisional_vs_final_diverge_on_same_five_days
    """
    ctx = fixtures.setup_placement_with_logged_week(work_dates=WORK_WEEK)
    fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )
    fixtures.post_wage_entry(
        ctx, variant="FINAL", period_start="2026-08-03", period_end="2026-08-07"
    )

    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))

    assert claim["wage_differential_paid_cents"] == 107258, (
        f"55003 provisional plus 52255 final, got {claim['wage_differential_paid_cents']}"
    )


def test_a_final_four_day_period_rounds_each_day_before_summing(api):
    """PRD §3.10: "For each such entry, the statutory replacement rate of 0.6667 is multiplied by the day gap evaluated at that entry's `hours_worked` and the product is rounded half up to whole cents; those per-day amounts are then added together."
    PRD §3.10: "The summed per-day total multiplied by that `tier_multiplier` is rounded half up to whole cents to give the pre-cap gross."

    Design: Difficulty/combinatorial_formula/wage_final_rounds_each_day_before_summing_four_day_period
    """
    ctx = fixtures.setup_placement_with_logged_week(
        work_dates=("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")
    )

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "FINAL", "period_start": "2026-08-03", "period_end": "2026-08-06"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert data["counted_day_count"] == 4
    assert data["gross_differential_cents"] == 44004, (
        f"four days of 11001 sum to 44004, got {data['gross_differential_cents']}"
    )
    assert data["gross_differential_cents"] != 44002, (
        "summing before rounding would give 44002 instead"
    )


def test_the_four_day_offset_is_taken_against_the_capped_gross(api):
    """PRD §3.10: "Both variants then run the same tail, in this exact order. The period's week count is `counted_day_count` divided by the five workdays in a week and rounded **up** to a whole number. `gross_differential_cents` is the lesser of the pre-cap gross and the weekly cap of 90000 cents multiplied by that week count. `net_amount_cents` is `gross_differential_cents` minus `offset_cents`. Note that the offset is computed against the capped `gross_differential_cents`, not against the pre-cap figure."
    PRD §3.10: "A placement in its first eight elapsed weeks takes the tier-one multiplier of 1.00; through the sixteenth elapsed week it takes the tier-two multiplier of 0.90; beyond that it takes the tier-three multiplier of 0.80."

    Design: Difficulty/combinatorial_formula/wage_final_rounds_each_day_before_summing_four_day_period
    """
    ctx = fixtures.setup_placement_with_logged_week(
        work_dates=("2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06")
    )

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "FINAL", "period_start": "2026-08-03", "period_end": "2026-08-06"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert data["tier_multiplier"] == 1.00
    assert data["offset_cents"] == 2200, (
        f"5 percent of the capped 44004 gross, got {data['offset_cents']}"
    )
    assert data["net_amount_cents"] == 41804


def test_a_final_period_in_the_ninth_elapsed_week_takes_the_tier_two_multiplier(api):
    """PRD §3.10: "The duration tier is then applied: the elapsed week count is the number of days from the placement's `start_date` to `period_start` divided by seven and rounded down, plus one. A placement in its first eight elapsed weeks takes the tier-one multiplier of 1.00; through the sixteenth elapsed week it takes the tier-two multiplier of 0.90; beyond that it takes the tier-three multiplier of 0.80. The summed per-day total multiplied by that `tier_multiplier` is rounded half up to whole cents to give the pre-cap gross."

    Design: Corner/calculations/wage_final_applies_tier2_multiplier_from_week_nine
    """
    ctx = fixtures.setup_placement_with_logged_week(
        placement_overrides={"end_date": "2026-11-30"},
        work_dates=("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"),
    )

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "FINAL", "period_start": "2026-09-28", "period_end": "2026-10-02"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert data["counted_day_count"] == 5
    assert data["tier_multiplier"] == 0.90, (
        "56 days after the 2026-08-03 start is elapsed week 9, past the eight-week tier one"
    )
    assert data["gross_differential_cents"] == 49505
    assert data["offset_cents"] == 2475
    assert data["net_amount_cents"] == 47030


def test_the_weekly_cap_truncates_a_large_gross(api):
    """PRD §3.10: "`gross_differential_cents` is the lesser of the pre-cap gross and the weekly cap of 90000 cents multiplied by that week count."
    PRD §2.8: "Wherever a monetary computation produces a fraction, the result is rounded half up to whole cents, and the specification in §3 always states exactly where in the sequence that rounding occurs, because a program that rounds at a different step produces a different cent."

    Design: Corner/calculations/wage_weekly_cap_truncates_gross_at_ninety_thousand_cents
    """
    ctx = fixtures.setup_placement_with_logged_week(
        work_dates=WORK_WEEK,
        employee_overrides={"pre_injury_weekly_wage_cents": 200_000},
        job_overrides={"hourly_rate_cents": 500},
        directive_overrides={"authorized_weekly_cost_cents": 150_000},
    )

    data = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "FINAL", "period_start": "2026-08-03", "period_end": "2026-08-07"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert data["gross_differential_cents"] == 90000
    assert data["gross_differential_cents"] != 126675, (
        "the uncapped five-day sum would have been 126675"
    )
    assert data["offset_cents"] == 4500
    assert data["net_amount_cents"] == 85500


def test_a_second_entry_of_the_same_variant_overlapping_the_period_is_refused(api):
    """PRD §3.10: "At priority 28, no other entry of the same placement **and the same variant** may already cover any day inside the requested period, treating both periods as closed intervals; an overlap answers `ERR_WAGE_PERIOD_OVERLAP` with HTTP 409."

    Design: Corner/validations/second_wage_entry_overlapping_same_variant_period_is_rejected
    """
    ctx = fixtures.setup_active_placement()
    fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )

    resp = api.create_wage_entry(
        ctx["placement_id"],
        {"variant": "PROVISIONAL", "period_start": "2026-08-05", "period_end": "2026-08-11"},
        fixtures.ADMIN,
    )

    validate_error(resp, ApiErrorId.ERR_WAGE_PERIOD_OVERLAP, 409)
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))
    assert claim["wage_differential_paid_cents"] == 55003, "only the first posting counts"


def test_posting_a_provisional_entry_raises_the_claim_paid_total(api):
    """PRD §3.10: "Posting recomputes the claim's `wage_differential_paid_cents` and raises the claim's `version` by 1."
    PRD §2.8: "Because the claim's `wage_differential_paid_cents` sums `net_amount_cents` over every entry regardless of `entry_status`, an original and its reversal cancel exactly, returning the claim total to its pre-posting value."

    Design: Difficulty/compensating_invariant/wage_ledger_total_conserved_across_post_and_reverse
    """
    ctx = fixtures.setup_active_placement()
    before = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))
    assert before["wage_differential_paid_cents"] == 0

    entry = validate_success(
        api.create_wage_entry(
            ctx["placement_id"],
            {"variant": "PROVISIONAL", "period_start": "2026-08-03",
             "period_end": "2026-08-07"},
            fixtures.ADMIN,
        ),
        201,
    )

    assert entry["net_amount_cents"] == 55003
    assert entry["entry_status"] == "POSTED"
    after = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))
    assert after["wage_differential_paid_cents"] == 55003


def test_a_reversal_mints_a_negating_row_and_restores_the_claim_total(api):
    """PRD §3.10: "The caller supplies a `reason`; the original row's `entry_status` flips to `REVERSED`, and a new row is minted with `entry_status` `REVERSAL`, `reverses_entry_id` pointing at the original, the same `placement_id` and `claim_id`, and `net_amount_cents` equal to the negation of the original's. The claim's `wage_differential_paid_cents` — which sums `net_amount_cents` over every entry of the claim regardless of `entry_status` — is recomputed and returns to its pre-posting value, and the claim's `version` rises by 1."

    Design: Difficulty/compensating_invariant/wage_ledger_total_conserved_across_post_and_reverse
    """
    ctx = fixtures.setup_active_placement()
    entry = fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )

    reversal = validate_success(
        api.reverse_wage_entry(
            entry["id"], {"reason": "Period reopened by the adjuster"}, fixtures.ADMIN
        ),
        201,
    )

    assert_wage_entry(reversal)
    assert reversal["entry_status"] == "REVERSAL"
    assert reversal["reverses_entry_id"] == entry["id"]
    assert reversal["net_amount_cents"] == -55003
    original = validate_success(api.get_wage_entry(entry["id"], fixtures.ADMIN))
    assert original["entry_status"] == "REVERSED"
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))
    assert claim["wage_differential_paid_cents"] == 0, (
        "the original and its reversal cancel exactly"
    )


def test_reversing_an_already_reversed_entry_is_refused(api):
    """PRD §3.10: "Reversing an entry requires that entry still to be `POSTED`, or the request answers `ERR_WAGE_ENTRY_ALREADY_REVERSED` at priority 14."

    Design: Corner/errors/reversing_an_already_reversed_entry_is_refused
    """
    ctx = fixtures.setup_active_placement()
    entry = fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )
    fixtures.reverse_wage_entry(entry["id"], reason="Period reopened")

    resp = api.reverse_wage_entry(entry["id"], {"reason": "Second attempt"}, fixtures.ADMIN)

    validate_error(resp, ApiErrorId.ERR_WAGE_ENTRY_ALREADY_REVERSED, 409)
    claim = validate_success(api.get_claim(ctx["claim_id"], fixtures.ADMIN))
    assert claim["wage_differential_paid_cents"] == 0, "the total does not go negative"


def test_the_ledger_listing_narrows_by_claim_and_entry_status(api):
    """PRD §3.10: "The ledger may be read one row at a time or listed with optional `placement_id`, `claim_id`, `reverses_entry_id`, `variant` and `entry_status` filters."

    Design: Corner/endpoints/wage_entries_filtered_by_claim_id
    """
    ctx = fixtures.setup_active_placement()
    entry = fixtures.post_wage_entry(
        ctx, variant="PROVISIONAL", period_start="2026-08-03", period_end="2026-08-07"
    )

    resp = api.list_wage_entries(
        fixtures.ADMIN, params={"claim_id": ctx["claim_id"], "entry_status": "POSTED"}
    )

    data, _ = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == entry["id"]
    assert data[0]["net_amount_cents"] == 55003


def test_an_empty_cohort_reports_zero_counts(api, program_admin_headers):
    """PRD §3.10: "The cohort consists of every placement whose `placement_status` is `ACTIVE`, `PROGRESSION_HOLD`, `SUSPENDED`, `COMPLETED` or `TERMINATED_EARLY`, whose `activated_on` is not null, whose `activated_on` falls inside the window with both endpoints inclusive, and — when a department was named — whose transitional job's `department_code` matches it."
    PRD §3.10: "From that cohort, `total_placements` is the cohort size; `active_placements` counts those in `ACTIVE` or `PROGRESSION_HOLD`; `completed_count` counts those in `COMPLETED`"

    Design: Difficulty/boundary_precision_check/program_metrics_empty_cohort_returns_zero_rates_not_division_error
    """
    fixtures.reset_clock()

    data = validate_success(api.get_program_metrics(program_admin_headers))

    assert data["total_placements"] == 0
    assert data["active_placements"] == 0
    assert data["completed_count"] == 0
    assert data["total_wage_differential_cents"] == 0


def test_an_empty_cohort_reports_zero_rates_rather_than_dividing(api, program_admin_headers):
    """PRD §3.10: "When the cohort is empty, `successful_return_rate`, `average_duration_days`, `reinjury_rate` and `compliance_rate` are all reported as 0.0."

    Design: Difficulty/boundary_precision_check/program_metrics_empty_cohort_returns_zero_rates_not_division_error
    """
    fixtures.reset_clock()

    resp = api.get_program_metrics(program_admin_headers)

    assert resp.status_code == 200, (
        f"a zero denominator must not become an error, got {resp.status_code}"
    )
    data = validate_success(resp)
    assert data["successful_return_rate"] == 0.0
    assert data["average_duration_days"] == 0.0
    assert data["reinjury_rate"] == 0.0
    assert data["compliance_rate"] == 0.0


def test_metrics_over_a_single_completed_placement(api, program_admin_headers):
    """PRD §3.10: "Otherwise `successful_return_rate` is `completed_count` divided by `total_placements`, `reinjury_rate` is `reinjury_count` divided by `total_placements`, and `compliance_rate` is the compliant count divided by `total_placements`, each rounded half up to four decimal places; `average_duration_days` is the sum of `cumulative_days` across the cohort divided by `total_placements`, rounded half up to two decimal places."
    PRD §3.10: "and a compliant count tallies those whose `compliance_status` is `COMPLIANT` or `REMEDIATED`."

    Design: Corner/calculations/program_metrics_over_a_single_completed_placement
    """
    ctx = fixtures.setup_active_placement()
    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.get_success_data(api.complete_placement(ctx["placement_id"], fixtures.COORD))

    data = validate_success(
        api.get_program_metrics(
            program_admin_headers,
            params={"window_start": "2026-01-01", "window_end": "2026-12-31"},
        )
    )

    assert data["total_placements"] == 1
    assert data["active_placements"] == 0
    assert data["completed_count"] == 1
    assert data["successful_return_rate"] == 1.0
    assert data["average_duration_days"] == 8.00, (
        f"2026-08-03 through 2026-08-10 inclusive is 8 days, got "
        f"{data['average_duration_days']}"
    )
    assert data["reinjury_rate"] == 0.0
    assert data["compliance_rate"] == 1.0
    assert data["total_wage_differential_cents"] == 0
