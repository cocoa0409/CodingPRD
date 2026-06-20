"""Origination: principal-limit computation, draw-type divergence, LESA sizing,
the age floor, and PLF resolution failure.

All tests build their own entities; the server is restarted before each test.
"""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_lender_with_plf,
    create_borrower,
    create_loan,
    setup_preorigination_loan,
    setup_originated_loan_with_lesa,
)

_SO = TEST_USERS["servicer_ops_headers"]


# ---------------------------------------------------------------------------
# combinatorial_formula / principal_limit_nested_minmax_with_tiered_plf
# ---------------------------------------------------------------------------
def test_principal_limit_nested_minmax_with_tiered_plf(api):
    """PRD §3.4: "First, the `max_claim_amount_cents` is the smaller of the loan's
    `appraised_value_cents` and the lender's `hud_lending_limit_cents`."
    PRD §3.4: "The `gross_principal_limit_cents` is then the `max_claim_amount_cents`
    multiplied by the resolved `principal_limit_factor_micros`, that product
    divided by 1,000,000, with the single multiply-and-divide step rounded
    half up to whole cents."

    Design: Difficulty/combinatorial_formula/principal_limit_nested_minmax_with_tiered_plf
    """
    lender = setup_lender_with_plf()  # PLF age 75 @ 500bps = 523000, clock 2024-01-01
    borrower = create_borrower(lender["id"])  # birthdate 1948-06-01 => age 75
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=500,
                       draw_type="LINE_OF_CREDIT", initial_financed_costs_cents=1000000)

    data = validate_success(api.originate_loan(loan["id"], _SO))
    assert data["max_claim_amount_cents"] == 30000000
    assert data["principal_limit_factor_micros"] == 523000
    assert data["gross_principal_limit_cents"] == 15690000
    assert data["net_principal_limit_cents"] == 14690000


def test_principal_limit_caps_max_claim_at_hud_lending_limit(api):
    """PRD §3.4: "First, the `max_claim_amount_cents` is the smaller of the loan's
    `appraised_value_cents` and the lender's `hud_lending_limit_cents`."

    Design: Difficulty/combinatorial_formula/principal_limit_nested_minmax_with_tiered_plf
    """
    # appraised 90000000 > hud 80000000 => max_claim capped at 80000000.
    lender = setup_lender_with_plf(lender_overrides={"hud_lending_limit_cents": 80000000})
    borrower = create_borrower(lender["id"])
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=90000000, expected_rate_bps=500,
                       draw_type="LINE_OF_CREDIT", initial_financed_costs_cents=1000000)

    data = validate_success(api.originate_loan(loan["id"], _SO))
    assert data["max_claim_amount_cents"] == 80000000
    # gross = round_half_up(80000000 * 523000 / 1_000_000) = 41840000
    assert data["gross_principal_limit_cents"] == 41840000


# ---------------------------------------------------------------------------
# entities / loan_computed_fields_ignore_client_supplied_values_on_origination
# ---------------------------------------------------------------------------
def test_loan_computed_fields_resolved_by_formula_on_origination(api):
    """PRD §3.4: "The `gross_principal_limit_cents` is then the `max_claim_amount_cents`
    multiplied by the resolved `principal_limit_factor_micros`, that product
    divided by 1,000,000, with the single multiply-and-divide step rounded
    half up to whole cents."

    Design: Corner/entities/loan_computed_fields_ignore_client_supplied_values_on_origination
    """
    lender = setup_lender_with_plf()
    borrower = create_borrower(lender["id"])
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=500,
                       draw_type="LINE_OF_CREDIT")
    data = validate_success(api.originate_loan(loan["id"], _SO))
    assert data["max_claim_amount_cents"] == 30000000
    assert data["principal_limit_factor_micros"] == 523000
    assert data["gross_principal_limit_cents"] == 15690000


# ---------------------------------------------------------------------------
# dual_variant_calc / lesa_fully_funded_vs_partially_funded_sizing
# ---------------------------------------------------------------------------
def test_lesa_fully_funded_sizes_full_horizon(api):
    """PRD §3.3: "Under `FULLY_FUNDED` mode — where the servicer pays the property charges
    directly — the `initial_amount_cents` is the
    `annual_property_charge_cents` multiplied by the `life_expectancy_years`
    horizon, carving the full horizon from the principal limit."

    Design: Difficulty/dual_variant_calc/lesa_fully_funded_vs_partially_funded_sizing
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa(
        funding_mode="FULLY_FUNDED", annual_property_charge_cents=600000,
        life_expectancy_years=10)
    assert lesa["initial_amount_cents"] == 6000000
    assert loan["lesa_set_aside_cents"] == 6000000
    # net = gross(15690000) - lesa(6000000) - costs(1000000)
    assert loan["net_principal_limit_cents"] == 8690000


def test_lesa_partially_funded_sizes_half_horizon(api):
    """PRD §3.3: "Under `PARTIALLY_FUNDED` mode — a semi-annual disbursement model in which the
    borrower receives funds to pay charges — the `initial_amount_cents` is the
    `annual_property_charge_cents` multiplied by the `life_expectancy_years`
    horizon, that product then divided by 2 and rounded half up to whole
    cents."

    Design: Difficulty/dual_variant_calc/lesa_fully_funded_vs_partially_funded_sizing
    """
    lender, borrower, loan, lesa = setup_originated_loan_with_lesa(
        funding_mode="PARTIALLY_FUNDED", annual_property_charge_cents=600000,
        life_expectancy_years=10)
    assert lesa["initial_amount_cents"] == 3000000
    assert loan["lesa_set_aside_cents"] == 3000000
    # net = gross(15690000) - lesa(3000000) - costs(1000000)
    assert loan["net_principal_limit_cents"] == 11690000


# ---------------------------------------------------------------------------
# boundary_precision_check / borrower_age_exactly_62_allowed_61_rejected
# ---------------------------------------------------------------------------
def test_borrower_age_exactly_62_originates(api):
    """PRD §3.4: "the youngest borrower's age, computed as the whole number of years between the
    borrower's `birthdate` and the date portion of the lender's `clock_utc`
    (flooring to whole years), must be at least 62; if it is below 62,
    origination is rejected with `ERR_BORROWER_UNDER_AGE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/borrower_age_exactly_62_allowed_61_rejected
    """
    # clock 2024-01-01; borrower born 1962-01-01 is exactly 62.
    lender = setup_lender_with_plf(plf_overrides={"age": 62, "expected_rate_bps": 500,
                                                  "factor_micros": 400000})
    borrower = create_borrower(lender["id"], full_name="Kit Exactly62",
                               birthdate="1962-01-01")
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=500,
                       draw_type="LUMP_SUM")
    data = validate_success(api.originate_loan(loan["id"], _SO))
    assert data["disposition_status"] == "ACTIVE"
    assert data["origination_date"] is not None


def test_borrower_one_day_short_of_62_rejected(api):
    """PRD §3.4: "the youngest borrower's age, computed as the whole number of years between the
    borrower's `birthdate` and the date portion of the lender's `clock_utc`
    (flooring to whole years), must be at least 62; if it is below 62,
    origination is rejected with `ERR_BORROWER_UNDER_AGE` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/borrower_age_exactly_62_allowed_61_rejected
    """
    # clock 2024-01-01; borrower born 1962-01-02 is one day short of 62.
    lender = setup_lender_with_plf(plf_overrides={"age": 62, "expected_rate_bps": 500,
                                                  "factor_micros": 400000})
    borrower = create_borrower(lender["id"], full_name="Lou Almost62",
                               birthdate="1962-01-02")
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=500,
                       draw_type="LUMP_SUM")
    validate_error(api.originate_loan(loan["id"], _SO), ApiErrorId.ERR_BORROWER_UNDER_AGE.value)


# ---------------------------------------------------------------------------
# calculations / scheduled_payment_term_floor_correct_result
# ---------------------------------------------------------------------------
def test_scheduled_payment_term_zero_rate_floors_division(api):
    """PRD §3.4: "If the monthly rate is zero, the `monthly_payment_cents` is the available
    principal divided by the number of payment months, floored to whole cents."

    Design: Corner/calculations/scheduled_payment_term_floor_correct_result
    """
    # expected_rate_bps=0 => monthly_rate 0; TERM n=120; PLF age75@0bps=523000.
    lender = setup_lender_with_plf(plf_overrides={"age": 75, "expected_rate_bps": 0,
                                                  "factor_micros": 523000})
    borrower = create_borrower(lender["id"])
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=0,
                       draw_type="TERM", tenure_term_months=120,
                       initial_financed_costs_cents=1000000)
    data = validate_success(api.originate_loan(loan["id"], _SO))
    assert data["net_principal_limit_cents"] == 14690000
    # floor(14690000 / 120) = 122416
    assert data["monthly_payment_cents"] == 122416


# ---------------------------------------------------------------------------
# errors / originate_without_matching_plf_returns_plf_not_found
# ---------------------------------------------------------------------------
def test_originate_without_matching_plf_returns_plf_not_found(api):
    """PRD §3.4: "If no factor row matches the loan's `expected_rate_bps` and the borrower's age
    at origination, origination is rejected with `ERR_PLF_NOT_FOUND` (HTTP
    422)."

    Design: Corner/errors/originate_without_matching_plf_returns_plf_not_found
    """
    lender = validate_success(
        api.create_lender({"name": "NoPlf Servicer", "hud_lending_limit_cents": 80000000}, _SO),
        expected_status=201)
    validate_success(api.set_clock(
        {"lender_id": lender["id"], "to_iso8601": "2024-01-01T00:00:00.000Z"}, _SO))
    borrower = create_borrower(lender["id"], full_name="Pam Borrower")
    loan = create_loan(lender["id"], borrower["id"],
                       appraised_value_cents=30000000, expected_rate_bps=500,
                       draw_type="LUMP_SUM", initial_financed_costs_cents=1000000)
    validate_error(api.originate_loan(loan["id"], _SO), ApiErrorId.ERR_PLF_NOT_FOUND.value)
