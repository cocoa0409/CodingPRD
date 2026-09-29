"""
The two tax bases read from one installment ledger, and the program evaluation's
concentration arithmetic including its empty-pool contract.
"""

from conftest import build_application, register_artist

from test_helpers import (
    BOARD_MEMBER,
    FISCAL_OFFICER,
    PROGRAM_OFFICER,
    api_client,
    assert_cents,
    assert_rate,
    assert_score,
    add_second_application,
    cyclemain_application_submitted,
    cyclemain_cycle_draft,
    cyclemain_cycle_open,
    cyclemain_installment_one_paid,
    make_artist_headers,
    read_discipline,
    set_clock,
    validate_success,
)


def _pay_remaining_installments(ctx):
    """Pay installment 2 inside 2027 and installment 3 on 10 January 2028."""
    set_clock("2027-05-01T00:00:00Z")
    validate_success(api_client.release_installment(ctx.inst2, FISCAL_OFFICER))
    validate_success(api_client.pay_installment(ctx.inst2, FISCAL_OFFICER))
    set_clock("2028-01-10T00:00:00Z")
    validate_success(api_client.release_installment(ctx.inst3, FISCAL_OFFICER))
    validate_success(api_client.pay_installment(ctx.inst3, FISCAL_OFFICER))


def _tax_report(award_id, params):
    return validate_success(api_client.get_tax_report(award_id, FISCAL_OFFICER, params))


class TestTaxBasesReadDifferentDateColumns:
    """Accrual keys on scheduled_date; cash keys on paid_at."""

    def test_the_2027_accrual_view_reports_all_three_rows_and_cash_only_two(self):
        """
        With every installment scheduled in 2027 but only the first two paid in 2027, the
        accrual view of 2027 reports the whole 1,500,000 over three rows while the cash view
        of the same year reports 1,125,000 over two.

        PRD: "Continuing the 1,500,000-cent example with all three installments scheduled
        during 2027 and installments one and two paid during 2027 while installment three is
        paid on 10 January 2028: the accrual view of 2027 reports 1,500,000 gross, 406,051
        withholding, 1,093,949 net over 3 installments; the cash view of 2027 reports
        1,125,000, 304,538, 820,462 over 2; the cash view of 2028 reports 375,000, 101,513,
        273,487 over 1; and the accrual view of 2028 reports zeros over 0 installments."

        Design: Difficulty/dual_variant_calc/tax_report_cash_basis_vs_accrual_basis_on_one_ledger
        """
        ctx = cyclemain_installment_one_paid()
        _pay_remaining_installments(ctx)

        accrual = _tax_report(ctx.aw1, {"tax_year": 2027, "basis": "ACCRUAL"})
        assert accrual["award_id"] == ctx.aw1, "the report should echo its award"
        assert accrual["tax_year"] == 2027, f"tax_year echo, got {accrual['tax_year']}"
        assert accrual["basis"] == "ACCRUAL", f"basis echo, got {accrual['basis']}"
        assert_cents(
            accrual["reportable_gross_cents"], 1_500_000, "accrual 2027 gross"
        )
        assert_cents(
            accrual["reportable_withholding_cents"], 406_051, "accrual 2027 withholding"
        )
        assert_cents(accrual["reportable_net_cents"], 1_093_949, "accrual 2027 net")
        assert accrual["installment_count"] == 3, (
            f"all three scheduled rows fall in 2027, got {accrual['installment_count']}"
        )

        cash = _tax_report(ctx.aw1, {"tax_year": 2027, "basis": "CASH"})
        assert cash["basis"] == "CASH", f"basis echo, got {cash['basis']}"
        assert_cents(cash["reportable_gross_cents"], 1_125_000, "cash 2027 gross")
        assert_cents(
            cash["reportable_withholding_cents"], 304_538, "cash 2027 withholding"
        )
        assert_cents(cash["reportable_net_cents"], 820_462, "cash 2027 net")
        assert cash["installment_count"] == 2, (
            f"only the two rows paid in 2027 count, got {cash['installment_count']}"
        )

    def test_the_2028_views_split_the_third_row_from_the_accrual_year(self):
        """
        The installment paid on 10 January 2028 is the whole of the 2028 cash view while the
        2028 accrual view is empty, the two cash years add back to the single accrual year,
        and omitting the basis reads as accrual.

        PRD: "It takes an optional `tax_year`, defaulting to the calendar year of the logical
        clock, and an optional `basis`, defaulting to `ACCRUAL`."

        Design: Difficulty/dual_variant_calc/tax_report_cash_basis_vs_accrual_basis_on_one_ledger
        """
        ctx = cyclemain_installment_one_paid()
        _pay_remaining_installments(ctx)

        cash_2028 = _tax_report(ctx.aw1, {"tax_year": 2028, "basis": "CASH"})
        assert_cents(cash_2028["reportable_gross_cents"], 375_000, "cash 2028 gross")
        assert_cents(
            cash_2028["reportable_withholding_cents"], 101_513, "cash 2028 withholding"
        )
        assert_cents(cash_2028["reportable_net_cents"], 273_487, "cash 2028 net")
        assert cash_2028["installment_count"] == 1, (
            f"one row was paid in 2028, got {cash_2028['installment_count']}"
        )

        accrual_2028 = _tax_report(ctx.aw1, {"tax_year": 2028, "basis": "ACCRUAL"})
        assert_cents(accrual_2028["reportable_gross_cents"], 0, "accrual 2028 gross")
        assert_cents(
            accrual_2028["reportable_withholding_cents"], 0, "accrual 2028 withholding"
        )
        assert_cents(accrual_2028["reportable_net_cents"], 0, "accrual 2028 net")
        assert accrual_2028["installment_count"] == 0, (
            "no scheduled_date falls in 2028, got "
            f"{accrual_2028['installment_count']}"
        )

        cash_2027 = _tax_report(ctx.aw1, {"tax_year": 2027, "basis": "CASH"})
        assert (
            cash_2027["reportable_gross_cents"] + cash_2028["reportable_gross_cents"]
            == 1_500_000
        ), "the cash years must partition the award gross with no loss or double counting"

        defaulted = _tax_report(ctx.aw1, {"tax_year": 2027})
        assert defaulted["basis"] == "ACCRUAL", (
            f"an omitted basis resolves to ACCRUAL, got {defaulted['basis']}"
        )
        assert_cents(
            defaulted["reportable_gross_cents"], 1_500_000, "defaulted 2027 gross"
        )
        assert defaulted["installment_count"] == 3, (
            f"the defaulted read matches accrual, got {defaulted['installment_count']}"
        )


class TestEvaluationOfAnEmptyPool:
    """An undefined concentration index is null, never zero."""

    def test_a_cycle_with_no_applications_reports_nulls_rather_than_dividing(self):
        """
        Read against a registered cycle and discipline that have attracted no application at
        all, the evaluation reports a pool of zero with a null index, a null distribution
        score and a null funded rate.

        PRD: "When the pool is empty, `region_hhi`, `geographic_distribution_score` and
        `funded_rate` are all reported as `null`, with `region_breakdown` and
        `discipline_breakdown` empty — the evaluation never divides by zero."

        Design: Difficulty/boundary_precision_check/diversity_evaluation_on_an_empty_pool_returns_nulls_not_zeros
        """
        ctx = cyclemain_cycle_draft()

        evaluation = validate_success(
            api_client.get_cycle_evaluation(ctx.cyc, PROGRAM_OFFICER)
        )
        assert evaluation["eligible_pool_size"] == 0, (
            f"an empty pool has size 0, got {evaluation['eligible_pool_size']}"
        )
        assert evaluation["region_hhi"] is None, (
            f"region_hhi must be null, not {evaluation['region_hhi']}"
        )
        assert evaluation["geographic_distribution_score"] is None, (
            "geographic_distribution_score must be null, not "
            f"{evaluation['geographic_distribution_score']}"
        )
        assert evaluation["funded_rate"] is None, (
            f"funded_rate must be null, not {evaluation['funded_rate']}"
        )

    def test_a_draft_application_leaves_the_pool_empty_and_the_breakdowns_bare(self):
        """
        A registered discipline does not put a row in the discipline breakdown, and an
        application still in DRAFT is outside the eligible pool, so both breakdown arrays
        stay empty and every derived figure stays null.

        PRD: "The **eligible pool** is every application of the cycle whose `status` is
        anything other than `DRAFT`, `WITHDRAWN` or `INELIGIBLE`, and `eligible_pool_size` is
        its size."

        Design: Difficulty/boundary_precision_check/diversity_evaluation_on_an_empty_pool_returns_nulls_not_zeros
        """
        ctx = cyclemain_cycle_draft()
        bare = validate_success(
            api_client.get_cycle_evaluation(ctx.cyc, PROGRAM_OFFICER)
        )
        assert bare["region_breakdown"] == [], (
            f"no applicant means no region row, got {bare['region_breakdown']}"
        )
        assert bare["discipline_breakdown"] == [], (
            "a registered discipline alone must not populate the breakdown, got "
            f"{bare['discipline_breakdown']}"
        )

        drafted = cyclemain_cycle_open()
        artist_id = register_artist(
            "Dov Halloran",
            "dov.halloran@example.org",
            "2021-03-04",
            "NORTH",
            residency_county="Lakeshore",
        )
        build_application(
            drafted.cyc,
            drafted.disc,
            artist_id,
            make_artist_headers(artist_id),
            statement="Essays on grain elevators and the language of weighbridges.",
            narrative="Long-running regional column, one collection, two teaching residencies.",
            page_counts=(13, 6),
            submit=False,
        )

        still_empty = validate_success(
            api_client.get_cycle_evaluation(drafted.cyc, PROGRAM_OFFICER)
        )
        assert still_empty["eligible_pool_size"] == 0, (
            "a DRAFT application is outside the pool, got "
            f"{still_empty['eligible_pool_size']}"
        )
        assert still_empty["region_hhi"] is None, "region_hhi stays null for an empty pool"
        assert still_empty["region_breakdown"] == [], (
            f"region_breakdown stays empty, got {still_empty['region_breakdown']}"
        )


class TestHhiScoreConsumesTheRoundedIndex:
    """Two-step rounding: round the index, then derive the score."""

    def _three_applicant_pool(self):
        ctx = cyclemain_application_submitted()
        add_second_application(ctx)
        artist_id = register_artist(
            "Dov Halloran",
            "dov.halloran@example.org",
            "2021-03-04",
            "NORTH",
            residency_county="Lakeshore",
        )
        build_application(
            ctx.cyc,
            ctx.disc,
            artist_id,
            make_artist_headers(artist_id),
            statement="Essays on grain elevators and the language of weighbridges.",
            narrative="Long-running regional column, one collection, two teaching residencies.",
            page_counts=(13, 6),
        )
        return ctx

    def test_a_two_north_one_south_pool_scores_fifty_five_point_five_five(self):
        """
        Shares of two-thirds and one-third give a raw index of 0.5555…, and the score must
        be derived from the index after it is rounded to 0.5556, landing on 55.55 rather
        than the 55.56 that one-step evaluation would produce.

        PRD: "A pool of three applications from `NORTH`, `NORTH` and `SOUTH` gives shares of
        two-thirds and one-third, a raw index of 0.5555…, a `region_hhi` of 0.5556, and a
        `geographic_distribution_score` of 55.55; deriving the score from the unrounded index
        would give 55.56 instead, and that reading is wrong."

        Design: Difficulty/boundary_precision_check/hhi_score_consumes_the_rounded_hhi_not_the_raw_share_sum
        """
        ctx = self._three_applicant_pool()

        evaluation = validate_success(
            api_client.get_cycle_evaluation(ctx.cyc, BOARD_MEMBER)
        )
        assert evaluation["eligible_pool_size"] == 3, (
            "submitted applications count toward the pool, got "
            f"{evaluation['eligible_pool_size']}"
        )
        assert_rate(evaluation["region_hhi"], 0.5556, "evaluation.region_hhi")
        assert_score(
            evaluation["geographic_distribution_score"],
            55.55,
            "evaluation.geographic_distribution_score",
        )
        assert evaluation["geographic_distribution_score"] != 55.56, (
            "55.56 is the forbidden one-step reading"
        )
        assert_rate(evaluation["funded_rate"], 0.0, "evaluation.funded_rate")

    def test_the_region_breakdown_is_ordered_by_region_code(self):
        """
        The breakdown carries one row per region present in the pool, ordered by region code
        ascending, so the two NORTH applicants precede the single SOUTH one; the discipline
        breakdown carries the cycle's one discipline with nothing committed yet.

        PRD: "`region_breakdown` lists each region in ascending region-code order with its
        applicant count and its share, and `discipline_breakdown` lists each discipline in
        ascending `code` order with its `eligible_application_count`, its
        `funded_application_count` and its `committed_cents`."

        Design: Difficulty/boundary_precision_check/hhi_score_consumes_the_rounded_hhi_not_the_raw_share_sum
        """
        ctx = self._three_applicant_pool()

        evaluation = validate_success(
            api_client.get_cycle_evaluation(ctx.cyc, BOARD_MEMBER)
        )
        regions = evaluation["region_breakdown"]
        assert len(regions) == 2, (
            f"only regions present in the pool appear, got {len(regions)} rows"
        )
        assert [row["applicant_count"] for row in regions] == [2, 1], (
            "NORTH sorts before SOUTH and carries two applicants, got "
            f"{[row['applicant_count'] for row in regions]}"
        )

        disciplines = evaluation["discipline_breakdown"]
        assert len(disciplines) == 1, (
            f"the cycle has one discipline, got {len(disciplines)} rows"
        )
        discipline = read_discipline(ctx.disc)
        assert disciplines[0]["eligible_application_count"] == (
            discipline["eligible_application_count"]
        ), "the breakdown should mirror the discipline's own eligible count"
        assert disciplines[0]["funded_application_count"] == 0, (
            "nothing is funded yet, got "
            f"{disciplines[0]['funded_application_count']}"
        )
        assert_cents(
            disciplines[0]["committed_cents"], 0, "discipline_breakdown.committed_cents"
        )
