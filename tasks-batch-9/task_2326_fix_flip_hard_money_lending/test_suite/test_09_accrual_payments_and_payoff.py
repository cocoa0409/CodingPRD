"""Interest accrual, the reserve sweep, the payment waterfall and the payoff quote."""

from test_helpers import (
    ApiErrorId,
    DayCountConvention,
    LedgerEntryType,
    LoanConstructionStatus,
    LoanExitStatus,
    LoanPaymentStatus,
    MilestoneType,
    PropertyStatus,
    api_client,
    assert_accrual_period,
    assert_exit_monitoring,
    assert_loan_axes,
    assert_loan_buckets,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
    SERVICER,
    SERVICER_2,
)

CLOSING_DATE = "2026-08-10"
DRAW_CLOCK = "2026-09-01T12:00:00Z"
FUNDING_DATE = "2026-09-01"


def _closed_loan(clock, **kwargs):
    """A three-line closed loan — funded 13,151,375, reserve 802,338, holdback 10,000,000."""
    ctx = fixtures.build_closed_loan(**kwargs)
    if clock is not None:
        fixtures.set_clock(clock)
    return ctx


def _two_line_loan(**kwargs):
    """A two-line closed loan — funded 16,439,218, reserve 1,002,923, holdback 5,000,000."""
    return fixtures.build_closed_loan(scope=tuple(fixtures.TWO_LINE_SCOPE), **kwargs)


def _sibling_two_line_loan(ctx, address_line, **application_overrides):
    """A second loan for the same sponsor on fresh collateral and the same scope."""
    collateral = fixtures.register_property(address_line=address_line)
    application = fixtures.open_application(
        ctx.borrower_id, collateral["id"], **application_overrides
    )
    lines = [
        fixtures.add_scope_line(
            application["id"], spec, ctx.contractor_id(spec.contractor)
        )
        for spec in fixtures.TWO_LINE_SCOPE
    ]
    for spec, line in zip(fixtures.TWO_LINE_SCOPE, lines):
        fixtures.approve_scope_line(line["id"], spec.cost_cents)
    validate_success(
        api_client.size_application(
            application["id"], factories.size_payload(), LOAN_OFFICER
        ),
        200,
    )
    validate_success(
        api_client.decide_application(
            application["id"], factories.decision_payload(), CREDIT_COMMITTEE
        ),
        200,
    )
    loan = validate_success(
        api_client.close_application(
            application["id"], factories.close_payload(CLOSING_DATE), SERVICER
        ),
        201,
    )
    return collateral, loan


def _exhaust_the_reserve(ctx):
    """Accrue 190 days then one more, taking the 802,338 reserve to exactly zero.

    The loan is read between the two periods so the caller can see the mid-state
    the first sweep left behind as well as the final one.
    """
    first = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2027-02-15")
    after_first = fixtures.read_loan(ctx.loan_id)
    second = fixtures.accrue(ctx.loan_id, "2027-02-16", "2027-02-16")
    return first, after_first, second


def _accrual_error(loan_id, period_start, period_end, error_id):
    return validate_error(
        api_client.create_interest_accrual(
            loan_id, factories.accrual_payload(period_start, period_end), SERVICER
        ),
        error_id,
    )


class TestAccrualPeriodTiling:
    def test_only_the_day_after_the_last_period_is_admissible(self):
        """One day earlier is an overlap, one day later is a gap; only 2026-09-10 fits.

        The stored period closed on 2026-09-09 inclusive, so a request restarting on
        that same day collides with it and a request restarting on 2026-09-11 strands
        2026-09-10. The PRD states: "Periods must be contiguous and must not overlap:
        a period that overlaps an existing accrual period of the loan on the inclusive
        interval is rejected with `ERR_ACCRUAL_PERIOD_OVERLAP`, and a `period_start`
        that is not exactly one day after the loan's `last_accrual_through` — or, for
        the very first period, not exactly the `closing_date` — leaves an un-accrued
        gap and is rejected with `ERR_ACCRUAL_PERIOD_GAP`."

        Design: Difficulty/resource_temporal_overlap/accrual_periods_are_inclusive_closed_and_gapless
        """
        ctx = _closed_loan("2026-09-20T12:00:00Z")
        first = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2026-09-09")
        assert_accrual_period(
            first,
            day_count=31,
            principal_snapshot_cents=13_151_375,
            interest_accrued_cents=130_235,
            swept_from_reserve_cents=130_235,
            unpaid_added_cents=0,
        )
        loan = ctx.refresh_loan()
        assert loan["last_accrual_through"] == "2026-09-09"
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_281_610,
            interest_reserve_balance_cents=672_103,
        )

        _accrual_error(
            ctx.loan_id, "2026-09-09", "2026-09-20",
            ApiErrorId.ACCRUAL_PERIOD_OVERLAP.value,
        )
        _accrual_error(
            ctx.loan_id, "2026-09-11", "2026-09-20",
            ApiErrorId.ACCRUAL_PERIOD_GAP.value,
        )

        second = fixtures.accrue(ctx.loan_id, "2026-09-10", "2026-09-20")
        assert_accrual_period(
            second,
            day_count=11,
            principal_snapshot_cents=13_281_610,
            interest_accrued_cents=46_670,
            swept_from_reserve_cents=46_670,
            unpaid_added_cents=0,
        )
        assert second["interest_accrued_cents"] != 46_212, (
            "the snapshot is the post-capitalisation principal, not the original 13,151,375"
        )
        loan = ctx.refresh_loan()
        assert loan["last_accrual_through"] == "2026-09-20"
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_328_280,
            interest_reserve_balance_cents=625_433,
        )
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert loan["commitment_balance_check_cents"] == 0

        _accrual_error(
            ctx.loan_id, "2026-09-21", "2026-09-30",
            ApiErrorId.ACCRUAL_BEYOND_CLOCK.value,
        )
        _, meta = validate_paginated(
            api_client.list_interest_periods(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 2, (
            f"only the two accepted periods may exist, got {meta['total_count']}"
        )

    def test_the_very_first_period_must_start_exactly_on_the_closing_date(self):
        """With no stored period the anchor is the closing date itself, to the day.

        Starting the first period a day early or a day late is the same gap refusal,
        so the opening anchor is a single admissible date rather than a range. The
        PRD states: "Both endpoints are inclusive, so `day_count` is the number of
        days from `period_start` to `period_end` plus one."

        Design: Difficulty/resource_temporal_overlap/accrual_periods_are_inclusive_closed_and_gapless
        """
        ctx = _closed_loan("2026-09-20T12:00:00Z")
        assert ctx.loan["last_accrual_through"] is None
        assert ctx.loan["closing_date"] == CLOSING_DATE

        _accrual_error(
            ctx.loan_id, "2026-08-11", "2026-09-09",
            ApiErrorId.ACCRUAL_PERIOD_GAP.value,
        )
        _accrual_error(
            ctx.loan_id, "2026-08-09", "2026-09-09",
            ApiErrorId.ACCRUAL_PERIOD_GAP.value,
        )
        _, meta = validate_paginated(
            api_client.list_interest_periods(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 0, "a refused accrual writes no period row"
        assert ctx.refresh_loan()["last_accrual_through"] is None

        period = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2026-09-09")
        assert period["period_start"] == CLOSING_DATE
        assert period["period_end"] == "2026-09-09"
        assert_accrual_period(period, day_count=31, note_rate_days=31, default_rate_days=0)
        assert period["day_count"] == 31, (
            "2026-08-10 and 2026-09-09 are both counted, giving 30 elapsed days plus one"
        )
        loan = ctx.refresh_loan()
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert loan["commitment_balance_check_cents"] == 0


class TestReserveExhaustionBoundary:
    def test_the_sweep_clamps_to_the_last_cents_left_in_the_reserve(self):
        """4,456 of interest meets 4,123 of reserve; the reserve lands on zero, not below.

        The second period's own interest proves the first sweep capitalised, because
        4,456 can only come from the grown 13,949,590 principal and not from the
        original 13,151,375, which would have produced 4,201. The PRD states:
        "`swept_from_reserve_cents` is the smaller of `interest_accrued_cents` and the
        loan's `interest_reserve_balance_cents` as it stood before the sweep, and
        `unpaid_added_cents` is `interest_accrued_cents` less `swept_from_reserve_cents`."

        Design: Difficulty/boundary_precision_check/reserve_exhausts_to_exactly_zero_and_one_cent_cure_boundary
        """
        ctx = _closed_loan("2027-02-16T12:00:00Z")
        first, after_first, second = _exhaust_the_reserve(ctx)

        assert_accrual_period(
            first,
            day_count=190,
            principal_snapshot_cents=13_151_375,
            interest_accrued_cents=798_215,
            swept_from_reserve_cents=798_215,
            unpaid_added_cents=0,
        )
        assert_loan_buckets(
            after_first,
            funded_principal_cents=13_949_590,
            interest_reserve_balance_cents=4_123,
        )
        assert after_first["payment_status"] == LoanPaymentStatus.CURRENT.value

        assert_accrual_period(
            second,
            day_count=1,
            principal_snapshot_cents=13_949_590,
            interest_accrued_cents=4_456,
            swept_from_reserve_cents=4_123,
            unpaid_added_cents=333,
        )
        assert second["interest_accrued_cents"] != 4_201, (
            "4,201 is the pre-capitalisation figure and must not be the answer"
        )
        loan = ctx.refresh_loan()
        assert loan["interest_reserve_balance_cents"] == 0, (
            "the clamp lands on exactly zero and never goes negative"
        )
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_953_713,
            interest_reserve_balance_cents=0,
        )
        assert loan["accrued_interest_unpaid_cents"] == 333
        assert loan["payment_status"] == LoanPaymentStatus.DELINQUENT.value
        assert loan["delinquent_since"] == "2027-02-16"
        assert loan["commitment_balance_check_cents"] == 0
        assert loan["interest_reserve_funded_cents"] == 802_338, (
            "the funded figure records what was seeded, not what is left"
        )

    def test_a_one_cent_shortfall_leaves_the_loan_delinquent_and_the_next_cent_cures_it(self):
        """332 of the 333 owed is not a cure; the 333rd cent is.

        Both payments run the same waterfall on the same loan, and the only thing
        separating a `DELINQUENT` outcome from a `CURRENT` one is that last cent of
        unpaid interest. The PRD states: "If the loan was `DELINQUENT` and both
        `fee_balance_cents` and `accrued_interest_unpaid_cents` have now reached zero,
        the loan moves `DELINQUENT → CURRENT` and `delinquent_since` is cleared to
        null; a shortfall of even one cent on either balance leaves the loan
        `DELINQUENT`."

        Design: Difficulty/boundary_precision_check/reserve_exhausts_to_exactly_zero_and_one_cent_cure_boundary
        """
        ctx = _closed_loan("2027-02-16T12:00:00Z")
        _exhaust_the_reserve(ctx)
        assert ctx.refresh_loan()["accrued_interest_unpaid_cents"] == 333

        loan = fixtures.pay(ctx.loan_id, 332, "2027-02-16")
        assert loan["accrued_interest_unpaid_cents"] == 1
        assert loan["payment_status"] == LoanPaymentStatus.DELINQUENT.value, (
            "one cent of unpaid interest still blocks the cure"
        )
        assert loan["delinquent_since"] == "2027-02-16"
        assert loan["funded_principal_cents"] == 13_953_713, (
            "the interest tier absorbed the whole payment, so principal is untouched"
        )
        assert loan["repaid_principal_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0

        loan = fixtures.pay(ctx.loan_id, 1, "2027-02-16")
        assert loan["accrued_interest_unpaid_cents"] == 0
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert loan["delinquent_since"] is None
        assert loan["funded_principal_cents"] == 13_953_713
        assert loan["repaid_principal_cents"] == 0
        assert loan["fee_balance_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0


class TestDefaultRateMidPeriodSwitch:
    def test_the_default_effective_date_splits_one_period_into_two_rounded_legs(self):
        """9 days at 1150 bps and 34 at 1750 bps, each rounded before they are added.

        The period straddles the 2027-02-26 declaration, and the effective date
        itself prices at the default rate, so the split is 9 against 34 rather than
        10 against 33. The PRD states: "`note_rate_days` counts the days in the
        inclusive period for which either `default_effective_date` is null or the day
        falls strictly before `default_effective_date`; `default_rate_days` is
        `day_count` less `note_rate_days`."

        Design: Corner/cross_cutting_complexity_layers/the_default_rate_switches_mid_period_on_the_effective_date
        """
        ctx = _closed_loan("2027-02-16T12:00:00Z")
        _exhaust_the_reserve(ctx)

        fixtures.set_clock("2027-02-26T09:00:00Z")
        loan = fixtures.declare_default(ctx.loan_id)
        assert loan["payment_status"] == LoanPaymentStatus.DEFAULT.value
        assert loan["default_effective_date"] == "2027-02-26"
        assert loan["note_rate_bps"] == 1150
        assert loan["default_rate_bps"] == 1750
        assert loan["last_accrual_through"] == "2027-02-16"

        fixtures.set_clock("2027-03-31T12:00:00Z")
        period = fixtures.accrue(ctx.loan_id, "2027-02-17", "2027-03-31")
        assert_accrual_period(
            period,
            day_count=43,
            note_rate_days=9,
            default_rate_days=34,
            principal_snapshot_cents=13_953_713,
            note_rate_interest_cents=40_117,
            default_rate_interest_cents=230_624,
            interest_accrued_cents=270_741,
            swept_from_reserve_cents=0,
            unpaid_added_cents=270_741,
        )
        assert period["interest_accrued_cents"] != 191_670, (
            "a single blended computation over 43 days is the wrong number"
        )
        assert (
            period["note_rate_interest_cents"] + period["default_rate_interest_cents"]
            == period["interest_accrued_cents"]
        ), "the two independently rounded legs must sum to the accrued figure"

        loan = ctx.refresh_loan()
        assert loan["accrued_interest_unpaid_cents"] == 271_074
        assert loan["funded_principal_cents"] == 13_953_713, (
            "with an empty reserve there is nothing to sweep and nothing capitalises"
        )
        assert loan["interest_reserve_balance_cents"] == 0
        assert loan["commitment_balance_check_cents"] == 0


class TestPaymentWaterfall:
    def test_a_regular_payment_fills_fees_before_interest_before_principal(self):
        """200,000 clears the 131,514 fee first and only then touches principal.

        Had the payment reached principal first the fee balance would still be
        standing, so the ordering is observable from the two balances alone; the very
        next cent above the remaining obligation is then refused outright. The PRD
        states: "Starting with the full payment amount as the remaining balance:
        first pay the smaller of the remaining balance and `fee_balance_cents`,
        reducing the remaining balance accordingly; then pay the smaller of what
        remains and `accrued_interest_unpaid_cents`, again reducing the remainder;
        then pay the smaller of what remains and `funded_principal_cents`."

        Design: Corner/calculations/a_regular_payment_fills_fees_before_interest_before_principal
        """
        ctx = _closed_loan(None)
        loan = fixtures.extend(ctx.loan_id, 1)
        assert loan["fee_balance_cents"] == 131_514
        assert loan["extension_count"] == 1
        assert loan["extension_months_total"] == 1
        assert loan["maturity_date"] == "2027-06-10"
        assert loan["note_rate_bps"] == 1200
        assert loan["default_rate_bps"] == 1800
        assert loan["committed_amount_cents"] == 23_953_713
        assert loan["commitment_balance_check_cents"] == 0, (
            "the fee is revenue and sits outside the conservation identity"
        )
        assert loan["accrued_interest_unpaid_cents"] == 0

        loan = fixtures.pay(ctx.loan_id, 200_000, CLOSING_DATE)
        assert loan["fee_balance_cents"] == 0
        assert loan["accrued_interest_unpaid_cents"] == 0
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_082_889,
            repaid_principal_cents=68_486,
            interest_reserve_balance_cents=802_338,
            undisbursed_holdback_cents=10_000_000,
        )
        assert 131_514 + 68_486 == 200_000
        assert loan["commitment_balance_check_cents"] == 0
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value, (
            "the loan was never delinquent, so the cure branch cannot fire"
        )

        validate_error(
            api_client.create_payment(
                ctx.loan_id,
                factories.payment_payload(13_082_890, CLOSING_DATE),
                SERVICER,
            ),
            ApiErrorId.PAYMENT_EXCEEDS_BALANCE.value,
        )
        unchanged = ctx.refresh_loan()
        assert unchanged["funded_principal_cents"] == 13_082_889
        assert unchanged["repaid_principal_cents"] == 68_486

        entries, meta = validate_paginated(
            api_client.list_ledger_entries(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 3, (
            f"the refused payment writes no entry, got {meta['total_count']}"
        )
        assert [(e["entry_type"], e["amount_cents"]) for e in entries] == [
            (LedgerEntryType.INITIAL_FUNDING.value, 13_151_375),
            (LedgerEntryType.EXTENSION_FEE.value, 131_514),
            (LedgerEntryType.BORROWER_PAYMENT.value, 200_000),
        ]


class TestAccrualClockBoundary:
    def test_the_identical_period_is_refused_then_accepted_when_only_the_clock_moves(self):
        """Nothing about the request changes; the clock catching up is what admits it.

        The boundary is inclusive of the clock date, so a period ending on
        2026-08-31 passes at a 2026-08-31 clock while a one-day period on 2026-09-01
        does not. The PRD states: "A `period_end` later than the logical-clock date
        is rejected with `ERR_ACCRUAL_BEYOND_CLOCK`, and a `period_end` earlier than
        `period_start` is a schema violation."

        Design: Corner/validations/an_accrual_period_may_not_reach_past_the_logical_clock
        """
        ctx = _closed_loan(None)
        _accrual_error(
            ctx.loan_id, CLOSING_DATE, "2026-08-31",
            ApiErrorId.ACCRUAL_BEYOND_CLOCK.value,
        )

        fixtures.set_clock("2026-08-31T23:00:00Z")
        period = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2026-08-31")
        assert_accrual_period(
            period,
            day_count=22,
            note_rate_days=22,
            default_rate_days=0,
            principal_snapshot_cents=13_151_375,
            interest_accrued_cents=92_425,
            swept_from_reserve_cents=92_425,
            unpaid_added_cents=0,
        )
        loan = ctx.refresh_loan()
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_243_800,
            interest_reserve_balance_cents=709_913,
        )
        assert loan["accrued_interest_unpaid_cents"] == 0
        assert loan["last_accrual_through"] == "2026-08-31"
        assert loan["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert loan["commitment_balance_check_cents"] == 0

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id, SERVICER, {"entry_type": LedgerEntryType.RESERVE_SWEEP.value}
            )
        )
        assert len(entries) == 1, f"one sweep entry expected, got {len(entries)}"
        assert entries[0]["amount_cents"] == 92_425
        assert entries[0]["effective_date"] == "2026-08-31"

        _accrual_error(
            ctx.loan_id, "2026-09-01", "2026-09-01",
            ApiErrorId.ACCRUAL_BEYOND_CLOCK.value,
        )
        _, meta = validate_paginated(
            api_client.list_interest_periods(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 1, (
            f"exactly one period survives all four attempts, got {meta['total_count']}"
        )


class TestPayoffQuoteRead:
    def test_the_payoff_quote_tracks_the_clock_and_is_never_stored(self):
        """One day of per-diem on the closing-day read, twelve days eleven days later.

        The loan's version and timestamps are identical across all three reads, so
        the growing quote is recomputed on demand rather than written down, and two
        different roles reading the same instant see the same figure. The PRD states:
        "The **payoff quote** is computed as of a quote date, which is the
        logical-clock date when a loan is merely being read and the supplied
        `payment_date` when a payoff is being applied."

        Design: Corner/endpoints/the_payoff_quote_is_a_pure_computed_read_that_tracks_the_clock
        """
        ctx = _closed_loan(None)
        assert ctx.loan["last_accrual_through"] is None
        assert ctx.loan["day_count_convention"] == DayCountConvention.PER_DIEM_360.value

        first = fixtures.read_loan(ctx.loan_id)
        assert first["payoff_quote_cents"] == 13_155_576, (
            "the 2026-08-09 anchor gives one per-diem day worth 4,201"
        )
        assert first["version"] == 1
        assert first["updated_at"] == first["created_at"]

        fixtures.set_clock("2026-08-21T09:00:00Z")
        second = fixtures.read_loan(ctx.loan_id)
        assert second["payoff_quote_cents"] == 13_201_789, (
            "twelve per-diem days from the 2026-08-09 anchor are worth 50,414"
        )
        assert second["funded_principal_cents"] == 13_151_375, (
            "reading a quote does not accrue, capitalise or otherwise move money"
        )
        assert second["accrued_interest_unpaid_cents"] == 0
        assert second["fee_balance_cents"] == 0
        assert second["version"] == 1
        assert second["updated_at"] == first["updated_at"]

        borrower_view = validate_success(
            api_client.get_loan(ctx.loan_id, ctx.borrower_headers), 200
        )
        assert borrower_view["payoff_quote_cents"] == 13_201_789, (
            "the quote is a function of loan state and clock, not of the caller"
        )
        assert borrower_view["version"] == 1

        _, meta = validate_paginated(
            api_client.list_interest_periods(ctx.loan_id, SERVICER)
        )
        assert meta["total_count"] == 0, (
            "the per-diem came from the closing-date fallback anchor, not an accrual row"
        )


class TestPayoffConventionSplit:
    def test_the_two_conventions_quote_different_figures_on_the_same_money(self):
        """23 per-diem days cost 120,783 on a 360 basis and 119,128 on a 365 basis.

        The two loans agree on funded principal, unpaid interest, fees and anchor
        date, so the 1,655 cent gap between the quotes is attributable to the
        divisor alone. The PRD states: "The divisor is 360 when
        `day_count_convention` is `PER_DIEM_360` and 365 when it is `PER_DIEM_365`."

        Design: Difficulty/dual_variant_calc/payoff_quote_per_diem_360_vs_365_short_payment
        """
        ctx = _two_line_loan()
        _, loan_365 = _sibling_two_line_loan(
            ctx, "42 Cholla Way", day_count_convention="PER_DIEM_365"
        )
        assert ctx.loan["day_count_convention"] == DayCountConvention.PER_DIEM_360.value
        assert loan_365["day_count_convention"] == DayCountConvention.PER_DIEM_365.value
        for loan in (ctx.loan, loan_365):
            assert_loan_buckets(
                loan,
                committed_amount_cents=22_442_141,
                funded_principal_cents=16_439_218,
                interest_reserve_balance_cents=1_002_923,
                undisbursed_holdback_cents=5_000_000,
            )
            assert loan["note_rate_bps"] == 1150
            assert loan["last_accrual_through"] is None
            assert loan["closing_date"] == CLOSING_DATE

        fixtures.set_clock("2026-09-01T09:00:00Z")
        quote_360 = fixtures.read_loan(ctx.loan_id)["payoff_quote_cents"]
        quote_365 = fixtures.read_loan(loan_365["id"])["payoff_quote_cents"]
        assert quote_360 == 16_560_001, f"360 basis expected 16,560,001, got {quote_360}"
        assert quote_365 == 16_558_346, f"365 basis expected 16,558,346, got {quote_365}"
        assert quote_360 - quote_365 == 1_655
        assert quote_360 > quote_365, "the 360-day convention produces the larger quote"

    def test_a_365_sized_payment_is_short_against_the_360_loan(self):
        """The same cheque pays one loan off in full and is refused by the other.

        16,558,346 is the exact quote on the 365 loan and 1,655 cents under the 360
        loan's quote, so the refusal is the convention showing up as a shortfall
        rather than as a rounding wobble. The PRD states: "The 360-day convention
        produces the larger quote and the 365-day convention the smaller; a payoff
        sized off the wrong convention is short, and a payment below
        `payoff_quote_cents` as of `payment_date` is rejected with
        `ERR_PAYOFF_SHORT`."

        Design: Difficulty/dual_variant_calc/payoff_quote_per_diem_360_vs_365_short_payment
        """
        ctx = _two_line_loan()
        collateral_365, loan_365 = _sibling_two_line_loan(
            ctx, "42 Cholla Way", day_count_convention="PER_DIEM_365"
        )
        fixtures.set_clock("2026-09-01T09:00:00Z")

        validate_error(
            api_client.create_payment(
                ctx.loan_id,
                factories.payment_payload(16_558_346, "2026-09-01", intent="PAYOFF"),
                SERVICER,
            ),
            ApiErrorId.PAYOFF_SHORT.value,
        )
        stubborn = fixtures.read_loan(ctx.loan_id)
        assert stubborn["payment_status"] == LoanPaymentStatus.CURRENT.value
        assert stubborn["funded_principal_cents"] == 16_439_218
        assert stubborn["repaid_principal_cents"] == 0

        settled = fixtures.pay(
            loan_365["id"], 16_558_346, "2026-09-01", intent="PAYOFF"
        )
        assert settled["payment_status"] == LoanPaymentStatus.PAID_OFF.value
        assert_loan_buckets(
            settled,
            committed_amount_cents=22_442_141,
            funded_principal_cents=0,
            repaid_principal_cents=16_439_218,
            interest_reserve_balance_cents=0,
            undisbursed_holdback_cents=0,
            decommitted_holdback_cents=6_002_923,
        )
        assert settled["commitment_balance_check_cents"] == 0
        assert settled["exit_status"] == LoanExitStatus.EXITED.value
        assert fixtures.read_property(collateral_365["id"])["status"] == (
            PropertyStatus.SOLD.value
        )
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.BORROWER_OWNED.value
        ), "the refused payoff leaves its collateral where it was"


class TestPayoffLockdown:
    def test_the_exact_quote_settles_the_loan_and_locks_out_every_later_write(self):
        """One cent short is short; the exact figure makes the loan accept nothing more.

        The accrual, draw request and extension that follow are all refused on the
        terminal payment status, and the draw request carries a freshly read loan
        version so the answer cannot be an optimistic-concurrency complaint. The PRD
        states: "Any write attempted against a loan whose `payment_status` has
        reached `PAID_OFF` or `CHARGED_OFF` is rejected with
        `ERR_LOAN_STATE_INVALID` — those two are terminal and accept nothing
        further."

        Design: Corner/state_machines/payoff_locks_the_loan_and_every_later_write_is_refused
        """
        ctx = _two_line_loan()
        fixtures.set_clock("2026-09-01T09:00:00Z")
        assert fixtures.read_loan(ctx.loan_id)["payoff_quote_cents"] == 16_560_001

        validate_error(
            api_client.create_payment(
                ctx.loan_id,
                factories.payment_payload(16_560_000, "2026-09-01", intent="PAYOFF"),
                SERVICER,
            ),
            ApiErrorId.PAYOFF_SHORT.value,
        )
        assert fixtures.read_loan(ctx.loan_id)["payment_status"] == (
            LoanPaymentStatus.CURRENT.value
        )

        settled = fixtures.pay(ctx.loan_id, 16_560_001, "2026-09-01", intent="PAYOFF")
        assert_loan_axes(
            settled,
            payment_status=LoanPaymentStatus.PAID_OFF.value,
            construction_status=LoanConstructionStatus.NOT_STARTED.value,
            exit_status=LoanExitStatus.EXITED.value,
        )
        assert settled["accrued_interest_unpaid_cents"] == 0
        assert settled["fee_balance_cents"] == 0
        assert_loan_buckets(
            settled,
            funded_principal_cents=0,
            repaid_principal_cents=16_439_218,
            interest_reserve_balance_cents=0,
            undisbursed_holdback_cents=0,
            decommitted_holdback_cents=6_002_923,
        )
        assert settled["commitment_balance_check_cents"] == 0
        assert fixtures.read_property(ctx.property_id)["status"] == (
            PropertyStatus.SOLD.value
        )

        fresh_version = settled["version"]
        validate_error(
            api_client.create_interest_accrual(
                ctx.loan_id,
                factories.accrual_payload(CLOSING_DATE, "2026-09-01"),
                SERVICER,
            ),
            ApiErrorId.LOAN_STATE_INVALID.value,
        )
        validate_error(
            api_client.create_draw_request(
                ctx.loan_id,
                factories.draw_request_payload(
                    [factories.line_allocation(ctx.line_id(0), 0.50)], fresh_version
                ),
                ctx.borrower_headers,
            ),
            ApiErrorId.LOAN_STATE_INVALID.value,
        )
        validate_error(
            api_client.create_extension(
                ctx.loan_id, factories.extension_payload(1), SERVICER
            ),
            ApiErrorId.LOAN_STATE_INVALID.value,
        )

        entries, _ = validate_paginated(
            api_client.list_ledger_entries(
                ctx.loan_id, SERVICER, {"entry_type": LedgerEntryType.PAYOFF.value}
            )
        )
        assert len(entries) == 1, f"one payoff entry expected, got {len(entries)}"
        assert entries[0]["amount_cents"] == 16_560_001
        assert entries[0]["effective_date"] == "2026-09-01"


class TestThreeIndependentAxes:
    def test_funding_a_listing_and_an_accrual_each_move_one_axis_only(self):
        """The loan ends up (DELINQUENT, IN_PROGRESS, LISTED) — one axis per write.

        Funding moves construction and nothing else, the listing moves exit and
        nothing else, and the accrual that outruns the reserve moves payment and
        nothing else, so the three dimensions are genuinely independent rather than a
        single status field. The PRD states: "The loan opens on three independent
        state axes: `payment_status` at `CURRENT`, `construction_status` at
        `NOT_STARTED`, and `exit_status` at `NOT_LISTED`."

        Design: Difficulty/non_linear_state_machine/loan_three_parallel_axes_advance_independently
        """
        ctx = fixtures.build_closed_loan()
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(0), 3_400_000)
        fixtures.file_waiver(ctx.loan_id, ctx.contractor_id(1), 700_000)
        fixtures.set_clock(DRAW_CLOCK)
        lines = [ctx.line_by_code(code)["id"] for code in ("ROOF", "KITCHEN", "ELECTRICAL")]
        draw, _ = fixtures.build_inspected_draw(
            ctx,
            [(lines[0], 0.60), (lines[1], 0.45), (lines[2], 0.33)],
            [(lines[0], 0.50), (lines[1], 0.45), (lines[2], 0.30)],
        )
        fixtures.review_draw(draw["id"])
        fixtures.fund_draw(draw["id"], SERVICER_2, FUNDING_DATE)

        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.CURRENT.value,
            construction_status=LoanConstructionStatus.IN_PROGRESS.value,
            exit_status=LoanExitStatus.NOT_LISTED.value,
        )
        assert_loan_buckets(
            loan,
            funded_principal_cents=17_043_875,
            reserved_release_cents=0,
            undisbursed_holdback_cents=6_107_500,
        )
        assert loan["commitment_balance_check_cents"] == 0

        fixtures.set_clock("2026-12-01T09:00:00Z")
        fixtures.file_milestone(ctx.loan_id, MilestoneType.LISTED.value, "2026-12-01")
        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.CURRENT.value,
            construction_status=LoanConstructionStatus.IN_PROGRESS.value,
            exit_status=LoanExitStatus.LISTED.value,
        )
        assert loan["funded_principal_cents"] == 17_043_875, (
            "a milestone is not a money event"
        )
        assert loan["commitment_balance_check_cents"] == 0

        fixtures.set_clock("2027-01-31T12:00:00Z")
        period = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2027-01-31")
        assert_accrual_period(
            period,
            day_count=175,
            principal_snapshot_cents=17_043_875,
            interest_accrued_cents=952_800,
            swept_from_reserve_cents=802_338,
            unpaid_added_cents=150_462,
        )
        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.DELINQUENT.value,
            construction_status=LoanConstructionStatus.IN_PROGRESS.value,
            exit_status=LoanExitStatus.LISTED.value,
        )
        assert loan["delinquent_since"] == "2027-01-31"
        assert_loan_buckets(
            loan,
            funded_principal_cents=17_846_213,
            interest_reserve_balance_cents=0,
            undisbursed_holdback_cents=6_107_500,
        )
        assert loan["accrued_interest_unpaid_cents"] == 150_462
        assert loan["commitment_balance_check_cents"] == 0
        assert_exit_monitoring(loan, days_on_market=61, exit_watch_flag=False)

    def test_the_payment_axis_moves_without_construction_or_exit_following(self):
        """An unbuilt, unlisted loan can still go delinquent, then get listed alone.

        No draw was ever funded and no milestone filed when the reserve runs dry, so
        `construction_status` stays `NOT_STARTED` while `payment_status` moves; the
        later listing then moves `exit_status` and leaves the delinquency in place.
        The PRD states: "Whenever `unpaid_added_cents` comes out greater than zero on
        a loan that is `CURRENT`, the loan moves `CURRENT → DELINQUENT` and
        `delinquent_since` is set to that period's `period_end`."

        Design: Difficulty/non_linear_state_machine/loan_three_parallel_axes_advance_independently
        """
        ctx = _closed_loan("2027-02-20T12:00:00Z")
        period = fixtures.accrue(ctx.loan_id, CLOSING_DATE, "2027-02-20")
        assert_accrual_period(
            period,
            day_count=195,
            principal_snapshot_cents=13_151_375,
            interest_accrued_cents=819_221,
            swept_from_reserve_cents=802_338,
            unpaid_added_cents=16_883,
        )
        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.DELINQUENT.value,
            construction_status=LoanConstructionStatus.NOT_STARTED.value,
            exit_status=LoanExitStatus.NOT_LISTED.value,
        )
        assert loan["delinquent_since"] == "2027-02-20"
        assert_loan_buckets(
            loan,
            funded_principal_cents=13_953_713,
            interest_reserve_balance_cents=0,
            undisbursed_holdback_cents=10_000_000,
        )
        assert loan["accrued_interest_unpaid_cents"] == 16_883
        assert loan["commitment_balance_check_cents"] == 0
        assert_exit_monitoring(loan, days_on_market=0, exit_watch_flag=False)

        fixtures.file_milestone(ctx.loan_id, MilestoneType.LISTED.value, "2027-02-20")
        loan = ctx.refresh_loan()
        assert_loan_axes(
            loan,
            payment_status=LoanPaymentStatus.DELINQUENT.value,
            construction_status=LoanConstructionStatus.NOT_STARTED.value,
            exit_status=LoanExitStatus.LISTED.value,
        )
        assert loan["delinquent_since"] == "2027-02-20", (
            "listing the property does not cure the delinquency"
        )
        assert loan["accrued_interest_unpaid_cents"] == 16_883
        assert_exit_monitoring(loan, days_on_market=0, exit_watch_flag=False)
