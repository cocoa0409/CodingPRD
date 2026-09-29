"""Departure: the exit assessment chain, rescission and the two unit-valuation variants."""

from test_helpers import (
    assert_exit_assessment,
    assert_fields_equal,
    assert_valuation,
    file_withdrawal_notice,
    make_finance_officer_headers,
    read_member,
    rescind_withdrawal_notice,
    setup_approved_bowl_appearance,
    setup_charter_roster,
    setup_operating_conference_with_reserve,
    setup_posted_fy2026_distribution,
    validate_success,
)

FY2026_GROSS_CENTS = 1_190_000_000
FY2026_AUDITED_EXPENSE_CENTS = 4_000_000


def _settlement(api, member_id):
    return validate_success(
        api.get_exit_settlement(member_id, headers=make_finance_officer_headers())
    )


def _valuation(api, member_id):
    return validate_success(
        api.get_postseason_unit_valuation(
            member_id, headers=make_finance_officer_headers()
        )
    )


def _setup_member_with_posted_annual_distribution(api):
    ctx = setup_operating_conference_with_reserve(api)
    setup_posted_fy2026_distribution(
        api,
        ctx,
        gross_revenue_cents=FY2026_GROSS_CENTS,
        audited_expense_cents=FY2026_AUDITED_EXPENSE_CENTS,
    )
    return ctx


def test_exit_assessment_walks_the_six_steps_from_the_posted_annual_distribution(api):
    """PRD §3.8: "Step two selects the `notice_multiplier_bps`: 10000 basis points when
    `notice_days` is 730 or more, 20000 when it is at least 365 but fewer than 730, and 30000
    when it is fewer than 365 — so a school that gives less than a year's notice pays three
    times its annual distribution rather than one."
    PRD §3.8: "Step three computes `base_assessment_cents` as the member's
    `last_full_annual_distribution_cents` multiplied by `notice_multiplier_bps` and divided by
    10000, rounded up; a member that has never appeared on a posted final audited media-rights
    run has a `last_full_annual_distribution_cents` of 0 and therefore a base assessment of 0."
    PRD §3.8: "Step five computes `surcharge_cents` as `base_assessment_cents` multiplied by
    `surcharge_bracket_bps` divided by 10000, rounded up."
    PRD §3.8: "Step six sets `exit_settlement_total_cents` to `base_assessment_cents` plus
    `surcharge_cents`."

    Design: Difficulty/combinatorial_formula/exit_settlement_bracket_keyed_on_base_not_total
    """
    ctx = _setup_member_with_posted_annual_distribution(api)
    member_id = ctx["member_ids"]["west"]
    assert (
        read_member(api, member_id)["last_full_annual_distribution_cents"]
        == 295_000_000
    )

    file_withdrawal_notice(api, member_id, withdrawal_effective_fiscal_year=2030)

    settlement = _settlement(api, member_id)
    assert_exit_assessment(
        settlement,
        notice_multiplier_bps=10000,
        base_assessment_cents=295_000_000,
        surcharge_bracket_bps=350,
        surcharge_cents=10_325_000,
        exit_settlement_total_cents=305_325_000,
        exit_settlement_paid_cents=0,
    )
    assert_fields_equal(
        settlement, member_id=member_id, remaining_balance_cents=305_325_000
    )


def test_surcharge_bracket_stays_on_the_base_when_the_total_crosses_the_ceiling(api):
    """PRD §3.8: "Step four selects the `surcharge_bracket_bps` from `base_assessment_cents`
    alone: 200 basis points when the base is below 100,000,000 cents, 350 when it is at least
    100,000,000 but below 300,000,000, and 500 when it is 300,000,000 or more."
    PRD §3.8: "Step four must read the step-three base and must never re-read the step-six
    total: bracketing on the total would be circular, since the total depends on the
    surcharge, the surcharge on the bracket, and the bracket on the total."
    PRD §3.8: "Fixing the base as the bracket key is what breaks that loop, and it means a
    base sitting just under a bracket ceiling stays in the lower bracket even though its total
    crosses the ceiling."

    Design: Difficulty/combinatorial_formula/exit_settlement_bracket_keyed_on_base_not_total
    """
    ctx = _setup_member_with_posted_annual_distribution(api)
    member_id = ctx["member_ids"]["south"]

    file_withdrawal_notice(api, member_id, withdrawal_effective_fiscal_year=2030)

    settlement = _settlement(api, member_id)
    # The base sits below the 300,000,000 cent ceiling, so the middle bracket holds even
    # though the resulting total lands above it; keying on the total would have selected
    # 500 basis points and a surcharge of 15,266,250 instead.
    assert settlement["base_assessment_cents"] == 295_000_000
    assert settlement["base_assessment_cents"] < 300_000_000
    assert settlement["exit_settlement_total_cents"] > 300_000_000
    assert_fields_equal(
        settlement, surcharge_bracket_bps=350, surcharge_cents=10_325_000
    )


def test_filing_a_notice_zeroes_the_voting_weight_and_assesses_the_settlement(api):
    """PRD §3.8: "Filing sets the member's `status` to `WITHDRAWAL_NOTICED`, stamps
    `withdrawal_notice_at` from the logical clock, drops its `voting_weight_bps` to 0 so it
    can no longer influence any ballot, switches its postseason-unit valuation to the
    `CURRENT_YEAR_ONLY` variant of §3.6, and advances the member's `version` by 1."

    Design: Difficulty/non_linear_state_machine/member_withdrawal_notice_rescission_restores_full_share
    """
    ctx = _setup_member_with_posted_annual_distribution(api)
    member_id = ctx["member_ids"]["west"]
    before = read_member(api, member_id)
    assert_fields_equal(before, status="FULL_SHARE", voting_weight_bps=10000)

    noticed = file_withdrawal_notice(
        api, member_id, withdrawal_effective_fiscal_year=2030
    )

    assert_fields_equal(
        noticed,
        status="WITHDRAWAL_NOTICED",
        voting_weight_bps=0,
        withdrawal_effective_fiscal_year=2030,
        version=before["version"] + 1,
    )
    assert noticed["withdrawal_notice_at"] is not None
    assert _settlement(api, member_id)["exit_settlement_total_cents"] == 305_325_000


def test_rescinding_a_notice_restores_full_share_and_clears_the_assessment(api):
    """PRD §3.8: "Rescission returns the member's `status` to `FULL_SHARE`, restores its
    `voting_weight_bps` to 10000, clears `withdrawal_notice_at`, `notice_days` and
    `withdrawal_effective_fiscal_year` back to null, zeroes `notice_multiplier_bps`,
    `base_assessment_cents`, `surcharge_bracket_bps`, `exit_settlement_total_cents` and
    `exit_settlement_paid_cents`, restores the `ROLLING_SIX_YEAR` valuation variant so the
    member's whole six-year unit history counts again, and advances the member's `version`
    by 1."
    PRD §3.8: "Because the rescission returns the member to a status it already held, the
    member machine is a cycle rather than a one-way path, and a member may file, rescind and
    re-file a notice."

    Design: Difficulty/non_linear_state_machine/member_withdrawal_notice_rescission_restores_full_share
    """
    ctx = _setup_member_with_posted_annual_distribution(api)
    member_id = ctx["member_ids"]["west"]
    noticed = file_withdrawal_notice(
        api, member_id, withdrawal_effective_fiscal_year=2030
    )

    restored = rescind_withdrawal_notice(api, member_id)

    assert_fields_equal(
        restored,
        status="FULL_SHARE",
        voting_weight_bps=10000,
        distribution_phase_bps=10000,
        withdrawal_notice_at=None,
        notice_days=None,
        withdrawal_effective_fiscal_year=None,
        exit_settlement_total_cents=0,
        exit_settlement_paid_cents=0,
        version=noticed["version"] + 1,
    )
    assert_exit_assessment(
        _settlement(api, member_id),
        notice_multiplier_bps=0,
        base_assessment_cents=0,
        surcharge_bracket_bps=0,
        surcharge_cents=0,
        exit_settlement_total_cents=0,
        exit_settlement_paid_cents=0,
    )
    # The cycle is re-enterable: the same member may file a fresh notice afterwards.
    refiled = file_withdrawal_notice(
        api, member_id, withdrawal_effective_fiscal_year=2030
    )
    assert_fields_equal(refiled, status="WITHDRAWAL_NOTICED", voting_weight_bps=0)


def test_rolling_six_year_valuation_counts_every_year_in_the_window(api):
    """PRD §3.6: "For a member in `ADMITTED_PHASING`, `FULL_SHARE` or `DEPARTED` the
    `ROLLING_SIX_YEAR` variant applies: the window covers the six fiscal years ending at the
    conference's `current_fiscal_year`, so `window_start_fiscal_year` is
    `current_fiscal_year` minus 5 and `window_end_fiscal_year` is `current_fiscal_year`."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count
    multiplied by the conference's `unit_value_cents`, an exact multiplication with no
    rounding."

    Design: Difficulty/dual_variant_calc/rolling_six_year_vs_current_year_only_unit_valuation
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    setup_approved_bowl_appearance(
        api, member_id, fiscal_year=2026, event_name="Prairie Bowl", units_claimed=2
    )
    setup_approved_bowl_appearance(
        api, member_id, fiscal_year=2027, event_name="Lakeside Bowl", units_claimed=3
    )

    valuation = _valuation(api, member_id)

    assert_valuation(
        valuation,
        variant="ROLLING_SIX_YEAR",
        window_start_fiscal_year=2022,
        window_end_fiscal_year=2027,
        validated_unit_count=5,
        valuation_cents=170_000_000,
    )


def test_notice_switches_the_valuation_to_the_current_year_only_variant(api):
    """PRD §3.6: "For a member in `WITHDRAWAL_NOTICED` the `CURRENT_YEAR_ONLY` variant
    applies: both window bounds are the `current_fiscal_year` itself, so a school under
    notice loses its historical units from the entitlement entirely."
    PRD §3.6: "Within the window, `validated_unit_count` is the number of that member's
    postseason units in status `VALIDATED` whose `fiscal_year` falls inside the window —
    provisional and voided units never count — and `valuation_cents` is that count
    multiplied by the conference's `unit_value_cents`, an exact multiplication with no
    rounding."

    Design: Difficulty/dual_variant_calc/rolling_six_year_vs_current_year_only_unit_valuation
    """
    ctx = setup_charter_roster(api)
    member_id = ctx["member_ids"]["north"]
    setup_approved_bowl_appearance(
        api, member_id, fiscal_year=2026, event_name="Prairie Bowl", units_claimed=2
    )
    setup_approved_bowl_appearance(
        api, member_id, fiscal_year=2027, event_name="Lakeside Bowl", units_claimed=3
    )

    file_withdrawal_notice(api, member_id, withdrawal_effective_fiscal_year=2028)

    valuation = _valuation(api, member_id)
    # The two FY2026 units drop out of the entitlement entirely under notice.
    assert_valuation(
        valuation,
        variant="CURRENT_YEAR_ONLY",
        window_start_fiscal_year=2027,
        window_end_fiscal_year=2027,
        validated_unit_count=3,
        valuation_cents=102_000_000,
    )
