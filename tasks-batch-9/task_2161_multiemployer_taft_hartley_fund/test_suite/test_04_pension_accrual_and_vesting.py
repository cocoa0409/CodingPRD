"""Pension credit accrual, the two accrual variants, and the vesting threshold."""

from test_helpers import (
    TEST_USERS,
    accrual_for,
    assert_pension_accrual,
    coverage_month_keys,
    granted_coverage_months,
    post_report,
    read_participant,
    setup_two_funds_differing_accrual_method,
    setup_vesting_boundary_report,
    validate_paginated,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_hours_based_denies_credit_to_a_one_hundred_fifty_one_hour_year(api):
    """PRD §3.5: "Under `HOURS_BASED`, the year's `pension_credit` is the
    countable hours divided by 250 and rounded down to a whole number of
    quarter-credits — each quarter-credit worth 0.25 — with the result capped at
    a full credit of 1.00; and the year counts as a year of vesting service,
    setting `vesting_year_earned` to true, when the countable hours are **at
    least** 870, an inclusive threshold rather than a strict one."
    PRD §3.5: "Independently of the accrual variant, the row's
    `break_in_service` flag asks whether the participant worked enough in the
    plan year to avoid losing ground. It is true when the sum of
    `hours_credited` and the hours of **every** reciprocity transfer of any
    `transfer_type` accepted for this participant in this plan year comes to
    less than 375 hours."
    PRD §3.5: "The fund keeps one accrual row per participant per plan year, and
    a row springs into existence the first time a posted contribution line or an
    accepted reciprocity transfer lands in that plan year."

    Design: Difficulty/dual_variant_calc/pension_credit_hours_based_vs_elapsed_time_diverge
    """
    base = setup_two_funds_differing_accrual_method()
    participant_id = base["participant_hours"]["id"]

    post_report(base["report_hours"]["id"])
    post_report(base["report_elapsed"]["id"])

    rows, meta = validate_paginated(api.list_pension_accruals(participant_id, ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["plan_year"] == 2026
    assert_pension_accrual(rows[0])

    accrual = accrual_for(participant_id, 2026)
    assert accrual["hours_credited"] == 151.30
    assert accrual["pension_credit"] == 0.00, "151.30 hours buys no whole quarter-credit"
    assert accrual["vesting_year_earned"] is False
    assert accrual["break_in_service"] is True, "151.30 hours falls short of 375"

    participant = read_participant(participant_id)
    assert participant["vesting_service_years"] == 0
    assert participant["total_pension_credits"] == 0.00


def test_elapsed_time_grants_a_whole_credit_for_the_same_hours(api):
    """PRD §3.5: "Under `ELAPSED_TIME`, the year earns a full `pension_credit` of
    1.00 when the countable hours are greater than zero **and** the participant
    holds at least one `GRANTED` coverage month whose month falls inside this
    plan year, and 0.00 otherwise; and `vesting_year_earned` is true whenever the
    countable hours are greater than zero at all, regardless of coverage."
    PRD §3.5: "The gap between the variants is wide by design: a participant with
    151.30 countable hours earns 0.00 credit and no vesting year under
    `HOURS_BASED`, but a full 1.00 credit and a vesting year under
    `ELAPSED_TIME`."
    PRD §3.5: "`vesting_service_years` is the count of the participant's accrual
    rows whose `vesting_year_earned` is true. `total_pension_credits` is the sum
    of `pension_credit` across those rows, rounded half up to two decimals.
    `vested` is true exactly when `vesting_service_years` has reached five years,
    an inclusive threshold."

    Design: Difficulty/dual_variant_calc/pension_credit_hours_based_vs_elapsed_time_diverge
    """
    base = setup_two_funds_differing_accrual_method()
    participant_id = base["participant_elapsed"]["id"]

    post_report(base["report_hours"]["id"])
    post_report(base["report_elapsed"]["id"])

    accrual = accrual_for(participant_id, 2026)
    assert accrual["hours_credited"] == 151.30
    assert accrual["pension_credit"] == 1.00
    assert accrual["vesting_year_earned"] is True

    participant = read_participant(participant_id)
    assert participant["vesting_service_years"] == 1
    assert participant["total_pension_credits"] == 1.00
    assert participant["vested"] is False, "one year of service is not five"

    # The 2026 coverage month the replay granted is what makes the year covered.
    assert "2026-05" in coverage_month_keys(granted_coverage_months(participant_id))


def test_eight_hundred_seventy_hours_earns_the_vesting_year_and_eight_hundred_sixty_nine_does_not(api):
    """PRD §3.5: "Under `HOURS_BASED`, the year's `pension_credit` is the
    countable hours divided by 250 and rounded down to a whole number of
    quarter-credits — each quarter-credit worth 0.25 — with the result capped at
    a full credit of 1.00; and the year counts as a year of vesting service,
    setting `vesting_year_earned` to true, when the countable hours are **at
    least** 870, an inclusive threshold rather than a strict one."
    PRD §3.5: "`vesting_service_years` is the count of the participant's accrual
    rows whose `vesting_year_earned` is true."
    PRD §3.5: "Within a row, `hours_credited` is the sum of the `hours` on
    contribution lines for this participant that sit on reports whose filing
    state is `POSTED` and whose work period falls in this plan year, rounded half
    up to two decimals."

    Design: Difficulty/boundary_precision_check/vesting_year_earned_at_exactly_870_hours
    """
    base = setup_vesting_boundary_report()

    post_report(base["report"]["id"])

    at_threshold = accrual_for(base["at_threshold"]["id"], 2026)
    assert at_threshold["hours_credited"] == 870.00
    assert at_threshold["vesting_year_earned"] is True
    assert at_threshold["pension_credit"] == 0.75

    under_threshold = accrual_for(base["under_threshold"]["id"], 2026)
    assert under_threshold["hours_credited"] == 869.99
    assert under_threshold["vesting_year_earned"] is False
    assert under_threshold["pension_credit"] == 0.75, (
        "both years buy three quarter-credits, so only the vesting test separates them"
    )

    assert read_participant(base["at_threshold"]["id"])["vesting_service_years"] == 1
    assert read_participant(base["under_threshold"]["id"])["vesting_service_years"] == 0


def test_the_hundredth_of_an_hour_shows_up_in_pricing_and_in_the_hour_bank(api):
    """PRD §3.3: "Round that per-line result half up to a whole number of cents
    and store it as the line's `contribution_cents`. **Only then** sum the
    rounded line amounts to obtain the report's
    `total_contributions_due_cents`."
    PRD §3.4: "Multiply the months bought by `hours_per_coverage_month` to get
    the hours consumed, and subtract that from the available hours to get the
    leftover."
    PRD §3.4: "Starting at that month, mint as many consecutive coverage months
    as the event bought, each with `status` `GRANTED`, each with `hours_applied`
    equal to the fund's `hours_per_coverage_month`, and each with
    `granting_report_id` set to the event's report identifier — which is null for
    a reciprocal event, since no report granted it."

    Design: Difficulty/boundary_precision_check/vesting_year_earned_at_exactly_870_hours
    """
    base = setup_vesting_boundary_report()

    posted = post_report(base["report"]["id"])

    assert posted["total_contributions_due_cents"] == 1436362, (
        "718185 for the 870.00-hour line plus 718177 for the 869.99-hour line"
    )

    at_threshold = read_participant(base["at_threshold"]["id"])
    under_threshold = read_participant(base["under_threshold"]["id"])
    assert at_threshold["hour_bank_hours"] == 30.00
    assert under_threshold["hour_bank_hours"] == 29.99

    granted = granted_coverage_months(base["at_threshold"]["id"])
    assert len(granted) == 7, "870.00 hours buys seven whole 120-hour months"
    assert coverage_month_keys(granted) == [
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
    ]
