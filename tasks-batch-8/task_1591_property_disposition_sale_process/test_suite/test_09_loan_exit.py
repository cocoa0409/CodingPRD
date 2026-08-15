"""Loan exit: payoff vs defeasance quote variants, pinned rounding orders,
step-down bands, the yield-maintenance floor, quote staleness and requote, and
eligibility gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    alpha_asset_payload,
    assert_timestamp_prefix,
    beta_asset_payload,
    create_asset,
    create_payoff_payload,
    delta_asset_payload,
    set_clock,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]
LS = TEST_USERS["ls_headers"]


def _quote(api_client, asset_id, **overrides):
    return api_client.create_payoff(create_payoff_payload(asset_id, **overrides), DM)


class TestPayoffVsDefeasance:
    def test_payoff_quote_cost_fields(self, api):
        """PRD: "`accrued_interest_cents` is the `loan_balance_cents` times the
        note rate implied by `loan_rate_bps`, times `accrued_days`, divided by
        360 — a 30/360-style accrual basis — rounded half up."
        PRD: "for `PAYOFF` it is the balance plus accrued interest plus the
        prepayment penalty; for `DEFEASANCE` it is the defeasance cost."
        PRD: "`defeasance_cost_cents` is computed only for the `DEFEASANCE`
        method and is 0 for `PAYOFF`."

        Design: Difficulty/dual_variant_calc/loan_exit_payoff_vs_defeasance
        """
        asset = create_asset(alpha_asset_payload())
        quote = validate_success(
            _quote(api, asset["id"], method="PAYOFF", reinvestment_rate_bps=400,
                   accrued_days=12), 201)
        assert quote["status"] == "QUOTED"
        # Yield maintenance: 250bps spread over a 46-month annuity at a 400bps
        # reinvestment rate; above the 1% floor of 30,000,000.
        assert quote["prepayment_penalty_cents"] == 266_132_822
        # 3,000,000,000 x 650bps x 12/360.
        assert quote["accrued_interest_cents"] == 6_500_000
        assert quote["defeasance_cost_cents"] == 0
        assert quote["total_estimated_cost_cents"] == 3_272_632_822
        assert quote["final_total_cents"] is None

    def test_defeasance_quote_cost_fields_diverge(self, api):
        """PRD: "It is the present value of the remaining debt service: each
        remaining month's `monthly_debt_service_cents` discounted at the monthly
        reinvestment rate for that many months, plus the remaining
        `loan_balance_cents` as a balloon discounted over the full remaining
        term."
        PRD: "The flat `defeasance_fee_cents` is added after that rounding."
        PRD: "`prepayment_penalty_cents` depends on `prepayment_type` and
        applies only to the `PAYOFF` method; it is 0 for `DEFEASANCE`"
        PRD: "The two routes genuinely diverge for identical loan inputs — a
        payoff pays principal and penalty, while defeasance buys a replacement
        securities portfolio"

        Design: Difficulty/dual_variant_calc/loan_exit_payoff_vs_defeasance
        """
        asset = create_asset(alpha_asset_payload())
        payoff = validate_success(
            _quote(api, asset["id"], method="PAYOFF", reinvestment_rate_bps=400,
                   accrued_days=12), 201)
        defeasance = validate_success(
            _quote(api, asset["id"], method="DEFEASANCE",
                   reinvestment_rate_bps=400, accrued_days=12), 201)
        assert defeasance["prepayment_penalty_cents"] == 0
        # PV of the debt-service stream plus balloon, rounded once, plus the
        # 50,000,000 flat fee.
        assert defeasance["defeasance_cost_cents"] == 3_433_231_264
        assert defeasance["total_estimated_cost_cents"] == 3_433_231_264
        assert payoff["total_estimated_cost_cents"] != \
            defeasance["total_estimated_cost_cents"], \
            "the two exit routes diverge for identical loan inputs"


class TestDefeasanceRoundingOrder:
    def test_defeasance_single_rounding_order(self, api):
        """PRD: "The entire present-value sum is carried in full floating-point
        precision and rounded half up exactly once at the end; rounding each
        monthly term before summing is a different algorithm and yields a
        different cent."

        Design: Difficulty/combinatorial_formula/defeasance_single_rounding_order
        """
        asset = create_asset(alpha_asset_payload())
        quote = validate_success(
            _quote(api, asset["id"], method="DEFEASANCE",
                   reinvestment_rate_bps=400, accrued_days=12), 201)
        assert quote["defeasance_cost_cents"] == 3_433_231_264, \
            "round-once-at-end order, fee added after rounding"
        assert quote["total_estimated_cost_cents"] == 3_433_231_264, \
            "the defeasance route total ignores accrued interest and penalty"

    def test_defeasance_rejects_per_month_rounding_cent(self, api):
        """PRD: "rounding each monthly term before summing is a different
        algorithm and yields a different cent."

        Design: Difficulty/combinatorial_formula/defeasance_single_rounding_order
        """
        asset = create_asset(alpha_asset_payload())
        quote = validate_success(
            _quote(api, asset["id"], method="DEFEASANCE",
                   reinvestment_rate_bps=400, accrued_days=12), 201)
        assert quote["defeasance_cost_cents"] != 3_433_231_265, \
            "the per-month-rounded alternative is off by one cent"
        assert quote["prepayment_penalty_cents"] == 0


class TestPrepaymentPenalty:
    def test_step_down_band_edges(self, api):
        """PRD: "Under `STEP_DOWN`, the penalty band is keyed on
        `remaining_term_months`: more than 48 months remaining costs five
        hundred basis points of the balance; more than 36 and at most 48 costs
        four hundred — note that exactly 48 months lands in this
        four-hundred-point band, since the upper edges are strict; more than 24
        and at most 36 costs three hundred; more than 12 and at most 24 costs
        two hundred; more than 0 and at most 12 costs one hundred; and exactly
        0 months costs nothing."

        Design: Corner/calculations/step_down_band_edges
        """
        b49 = create_asset(delta_asset_payload(
            name="B49", remaining_term_months=49,
            loan_maturity_date="2030-09-30T00:00:00Z"))
        b46 = create_asset(delta_asset_payload(
            name="B46", remaining_term_months=46,
            loan_maturity_date="2030-06-30T00:00:00Z"))
        b12 = create_asset(delta_asset_payload(
            name="B12", remaining_term_months=12,
            loan_maturity_date="2027-08-31T00:00:00Z"))

        q49 = validate_success(_quote(api, b49["id"], reinvestment_rate_bps=300,
                                      accrued_days=0), 201)
        assert q49["prepayment_penalty_cents"] == 40_000_000, "49 > 48: 5% band"
        assert q49["total_estimated_cost_cents"] == 840_000_000, \
            "balance + penalty with zero accrued days"

        q46 = validate_success(_quote(api, b46["id"], reinvestment_rate_bps=300,
                                      accrued_days=0), 201)
        assert q46["prepayment_penalty_cents"] == 32_000_000, "36 < 46 <= 48: 4%"

        q12 = validate_success(_quote(api, b12["id"], reinvestment_rate_bps=300,
                                      accrued_days=0), 201)
        assert q12["prepayment_penalty_cents"] == 8_000_000, "0 < 12 <= 12: 1%"

    def test_yield_maintenance_floor_applies(self, api):
        """PRD: "the raw figure is the balance times the excess of the note rate
        over the reinvestment rate (never below zero), expressed monthly, times
        that annuity factor, using floating-point math inside the factor; the
        penalty is then the greater of the raw figure rounded half up and one
        hundred basis points of the balance rounded half up — a one-percent
        floor applied after rounding."

        Design: Corner/calculations/yield_maintenance_floor_applies
        """
        asset = create_asset(alpha_asset_payload())
        # Reinvestment rate (700bps) meets the coupon (650bps): raw figure 0,
        # so the 1%-of-balance floor binds.
        quote = validate_success(
            _quote(api, asset["id"], method="PAYOFF", reinvestment_rate_bps=700,
                   accrued_days=12), 201)
        assert quote["prepayment_penalty_cents"] == 30_000_000
        assert quote["total_estimated_cost_cents"] == 3_036_500_000, \
            "3,000,000,000 balance + 6,500,000 accrued + 30,000,000 floor"


class TestQuoteLifecycle:
    def test_payoff_stale_sweep_and_requote_cycle(self, api):
        """PRD: "A clean quote lands in `QUOTED` status with `quoted_at` stamped
        from the clock and `quote_expires_at` set exactly ten days later."
        PRD: "The clock sweep moves a `QUOTED` payoff to `STALE` once the clock
        passes `quote_expires_at`."
        PRD: "confirming anything not `QUOTED` is `ERR_INVALID_STATE_TRANSITION`"
        PRD: "A `STALE` quote is refreshed by a `DispositionManager` requote,
        which accepts optional replacement `reinvestment_rate_bps`,
        `accrued_days`, and `anticipated_settlement_date`, restamps `quoted_at`
        from the clock, extends `quote_expires_at` to ten days out, and
        recomputes every computed field with the current inputs, returning the
        quote to `QUOTED`."

        Design: Corner/state_machines/payoff_stale_sweep_and_requote_cycle
        """
        asset = create_asset(alpha_asset_payload())
        quote = validate_success(
            _quote(api, asset["id"], method="PAYOFF", reinvestment_rate_bps=400,
                   accrued_days=12), 201)
        assert quote["status"] == "QUOTED"
        assert_timestamp_prefix(quote["quote_expires_at"], "2026-08-11T00:00:00")

        set_clock("2026-08-12T00:00:00Z")
        payoffs = validate_success(api.list_asset_payoffs(asset["id"], DM))
        assert payoffs[0]["status"] == "STALE"

        validate_error(api.confirm_payoff(quote["id"], LS),
                       ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        refreshed = validate_success(
            api.requote_payoff(quote["id"], {"reinvestment_rate_bps": 350}, DM))
        assert refreshed["status"] == "QUOTED"
        # 300bps spread annuity at 350bps reinvestment, recomputed on requote.
        assert refreshed["prepayment_penalty_cents"] == 322_418_340
        assert_timestamp_prefix(refreshed["quote_expires_at"],
                                "2026-08-22T00:00:00")


class TestEligibilityGates:
    def test_err_loan_locked_out(self, api):
        """PRD: "when the asset's `prepayment_lockout_until` is set, the
        anticipated settlement must lie strictly after it
        (`ERR_LOAN_LOCKED_OUT`)"

        Design: Corner/errors/err_loan_locked_out
        """
        asset = create_asset(beta_asset_payload())  # lockout until 2027-01-01
        validate_error(
            _quote(api, asset["id"], method="PAYOFF", reinvestment_rate_bps=400,
                   accrued_days=12,
                   anticipated_settlement_date="2026-10-30T00:00:00Z"),
            ApiErrorId.ERR_LOAN_LOCKED_OUT)
        payoffs = validate_success(api.list_asset_payoffs(asset["id"], DM))
        assert payoffs == [], "no quote row was created"

    def test_err_defeasance_not_allowed(self, api):
        """PRD: "a `DEFEASANCE` request on an asset whose `defeasance_allowed`
        is false is rejected with `ERR_DEFEASANCE_NOT_ALLOWED`."

        Design: Corner/errors/err_defeasance_not_allowed
        """
        asset = create_asset(delta_asset_payload())  # defeasance_allowed false
        validate_error(
            _quote(api, asset["id"], method="DEFEASANCE",
                   reinvestment_rate_bps=300, accrued_days=15,
                   anticipated_settlement_date="2026-10-15T00:00:00Z"),
            ApiErrorId.ERR_DEFEASANCE_NOT_ALLOWED)
