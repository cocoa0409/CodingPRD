"""Rate derivation: methodology variants, signatory markup, terminal rate."""
from test_helpers import (
    TEST_USERS,
    assert_rates_setting,
    create_and_open_fiscal_year,
    create_rates_setting,
    validate_success,
)

FINANCE = TEST_USERS["finance_headers"]

# Shared pool geometry for the methodology-divergence tests: the only
# difference between the two years is the methodology.
POOL = dict(
    airfield_opex_cents=1000000000,
    terminal_opex_cents=100000000,
    nonairline_airfield_revenue_cents=200000000,
    nonairline_terminal_revenue_cents=10000000,
    terminal_total_space_sqft=100000,
    forecast_landed_weight_kg=8000000,
    prior_year_surplus_cents=50000000,
)

# Per the PRD derivation: requirement * 1000 / forecast_landed_weight_kg,
# rounded half up to a whole cent.
RESIDUAL_REQUIREMENT = 1000000000 - 200000000 + 50000000   # 850_000_000
RESIDUAL_RATE = 106250          # 850_000_000 * 1000 / 8_000_000
COMPENSATORY_REQUIREMENT = 1000000000 - 200000000          # 800_000_000
COMPENSATORY_RATE = 100000      # 800_000_000 * 1000 / 8_000_000


class TestMethodologyDivergence:
    def test_residual_rate_includes_prior_year_surplus(self, api):
        """PRD §3.2: "Under a `RESIDUAL` year, `airfield_requirement_cents` is
        the airfield cost pool minus the non-airline airfield revenue offset
        plus the full `prior_year_surplus_cents`; because the carry-forward may
        be negative, a prior-year deficit raises the requirement just as a
        surplus lowers it."
        PRD §3.2: "The `signatory_landing_fee_per_1000kg_cents` is then the
        airfield requirement in cents multiplied by one thousand and divided by
        the forecast landed weight in kilograms, rounded half up to a whole
        cent."

        Design: Difficulty/dual_variant_calc/landing_fee_residual_vs_compensatory_divergence
        """
        fy_res = create_and_open_fiscal_year("FY_RES", "RESIDUAL", **POOL)
        rs_res = create_rates_setting(fy_res["id"])

        fetched = validate_success(api.get_rates_setting(rs_res["id"], FINANCE))
        assert_rates_setting(fetched)
        assert fetched["airfield_requirement_cents"] == RESIDUAL_REQUIREMENT, (
            "RESIDUAL requirement includes the full carry-forward")
        assert fetched["signatory_landing_fee_per_1000kg_cents"] == RESIDUAL_RATE

    def test_compensatory_rate_excludes_prior_year_surplus(self, api):
        """PRD §3.2: "Under a `COMPENSATORY` year, the requirement is simply
        the airfield pool minus the non-airline offset, and the carry-forward
        is excluded in full."
        PRD §3.2: "In all three methodologies the denominator is the year's
        `forecast_landed_weight_kg`."

        Design: Difficulty/dual_variant_calc/landing_fee_residual_vs_compensatory_divergence
        """
        fy_res = create_and_open_fiscal_year("FY_RES", "RESIDUAL", **POOL)
        fy_comp = create_and_open_fiscal_year("FY_COMP", "COMPENSATORY", **POOL)
        rs_res = create_rates_setting(fy_res["id"])
        rs_comp = create_rates_setting(fy_comp["id"])

        comp = validate_success(api.get_rates_setting(rs_comp["id"], FINANCE))
        res = validate_success(api.get_rates_setting(rs_res["id"], FINANCE))
        assert comp["airfield_requirement_cents"] == COMPENSATORY_REQUIREMENT, (
            "COMPENSATORY requirement excludes the carry-forward")
        assert comp["signatory_landing_fee_per_1000kg_cents"] == COMPENSATORY_RATE
        assert res["signatory_landing_fee_per_1000kg_cents"] != (
            comp["signatory_landing_fee_per_1000kg_cents"]), (
            "Identical pools must diverge across methodologies")


class TestNonSignatoryMarkup:
    def test_non_signatory_rate_is_125_percent_ceiling(self, api):
        """PRD §3.2: "The `non_signatory_landing_fee_per_1000kg_cents` follows
        from it: the signatory fee scaled by 125 percent, rounded up to the
        next whole cent whenever the scaled value is not already exact."
        PRD §2.7: "carriers that do not are charged at a non-signatory fee
        built from the signatory fee with a 125 percent markup."

        Design: Corner/calculations/non_signatory_markup_125pct_applied
        """
        fy = create_and_open_fiscal_year(
            "FY_MK", "RESIDUAL", airfield_opex_cents=100000000,
            terminal_opex_cents=0, nonairline_airfield_revenue_cents=0,
            nonairline_terminal_revenue_cents=0, terminal_total_space_sqft=100000,
            forecast_landed_weight_kg=100000, prior_year_surplus_cents=0)
        rs = create_rates_setting(fy["id"])

        fetched = validate_success(api.get_rates_setting(rs["id"], FINANCE))
        # requirement 100_000_000 * 1000 / 100_000 -> 1_000_000 per unit
        assert fetched["signatory_landing_fee_per_1000kg_cents"] == 1000000
        assert fetched["non_signatory_landing_fee_per_1000kg_cents"] == 1250000, (
            "Non-signatory fee is the signatory fee with a 125 percent markup")


class TestTerminalRentalRate:
    def test_terminal_rate_is_requirement_over_space(self, api):
        """PRD §3.2: "The terminal requirement is `terminal_opex_cents` minus
        `nonairline_terminal_revenue_cents`, and the
        `terminal_rental_rate_per_sqft_year_cents` is that requirement divided
        by the year's `terminal_total_space_sqft`, rounded half up to a whole
        cent."

        Design: Corner/calculations/terminal_rate_computation
        """
        fy = create_and_open_fiscal_year(
            "FY_TR", "RESIDUAL", airfield_opex_cents=0,
            terminal_opex_cents=5000000, nonairline_airfield_revenue_cents=0,
            nonairline_terminal_revenue_cents=1000000,
            terminal_total_space_sqft=1000, forecast_landed_weight_kg=1000,
            prior_year_surplus_cents=0)
        rs = create_rates_setting(fy["id"])

        fetched = validate_success(api.get_rates_setting(rs["id"], FINANCE))
        # (5_000_000 - 1_000_000) / 1000 = 4000 exactly
        assert fetched["terminal_rental_rate_per_sqft_year_cents"] == 4000
