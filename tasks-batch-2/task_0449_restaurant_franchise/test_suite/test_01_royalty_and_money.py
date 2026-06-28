"""Royalty, ad-fund, late-fee, and transfer-fee money calculations.

Covers the late-fee dual-variant and the marginal-royalty combinatorial-formula
difficulty instances plus the observable calculation-section corner instances.

NOTE ON REBATE SHARES: The PRD (§3.9) describes the rebate waterfall algorithm in
full but names NO observable field for a per-authorization share — VendorAuthorization
exposes only {unit_id, vendor_id, qualifying_purchase_cents, status} and the distribute
endpoint returns the NationalAccount (status only). A faithful PRD-only implementer
could compute shares purely internally and surface nothing. The per-share / pool-
conservation assertions therefore fail unique derivability and are SKIPPED here (see
the worklog summary). Only the PRD-named distribute outcome (status OPEN→DISTRIBUTED)
and the OCC behaviors are exercised; those live in test_05.
"""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    write_off_payload,
    transfer_agreement_payload,
    setup_issued_statement,
    setup_open_unit,
    create_accepted_sales_report,
    create_issued_statement,
    setup_renewal_pending_agreement,
    create_franchisee,
    approve_franchisee,
    get_brand_version,
)

CLERK = TEST_USERS["finance_clerk_headers"]
FRANCHISOR = TEST_USERS["franchisor_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: dual_variant_calc / late_fee_simple_vs_compound_on_royalty_statement
# ═══════════════════════════════════════════════════════════════════════════
def test_writeoff_applies_compound_final_late_fee():
    """PRD §3.9: "The final variant is applied when an overdue statement is written
    off: here late_fee_cents is the principal multiplied by the quantity (one plus the
    monthly rate, raised to the power of the months-late count, then minus one), rounded
    half up to whole cents — a compound accrual that diverges upward from the simple
    variant once the months-late count is 2 or more."

    Design: Difficulty/dual_variant_calc/late_fee_simple_vs_compound_on_royalty_statement
    """
    brand, _, _, unit = setup_open_unit(owner_user_id="u_lf", territory_code="LF")
    create_accepted_sales_report(unit["id"], 0, 12_000_000, discounts_cents=500_000)
    statement = create_issued_statement(unit["id"], 0)
    # basis 11500000 → royalty 610000 + ad_fund 230000 = principal 840000.
    assert statement["royalty_cents"] == 610000
    assert statement["ad_fund_cents"] == 230000
    assert statement["total_due_cents"] == 840000
    for _ in range(4):  # current_period_index → 4, months_late = 4 - 1 = 3
        get_success_data(api_client.close_period(brand["id"], FRANCHISOR))
    brand_v = get_brand_version(brand["id"])
    data = validate_success(
        api_client.write_off_royalty_statement(
            statement["id"], write_off_payload(brand_v), CLERK
        ),
        expected_status=200,
    )
    assert data["late_fee_cents"] == 38370, (
        f"compound final late fee must be 38370, got {data['late_fee_cents']}"
    )
    assert data["status"] == "WRITTEN_OFF"
    assert data["total_due_cents"] == 878370  # 840000 + 38370


def test_writeoff_compound_fee_differs_from_simple_provisional():
    """PRD §3.9: "The provisional variant is applied when a statement auto-transitions
    to OVERDUE during a period close: here late_fee_cents is the principal multiplied by
    the monthly rate multiplied by the months-late count, rounded half up to whole cents
    — a simple linear accrual with no compounding."
    PRD §3.9: "a compound accrual that diverges upward from the simple variant once the
    months-late count is 2 or more."

    Design: Difficulty/dual_variant_calc/late_fee_simple_vs_compound_on_royalty_statement
    """
    brand, _, _, unit = setup_open_unit(owner_user_id="u_lf2", territory_code="LF2")
    create_accepted_sales_report(unit["id"], 0, 12_000_000, discounts_cents=500_000)
    statement = create_issued_statement(unit["id"], 0)
    for _ in range(4):
        get_success_data(api_client.close_period(brand["id"], FRANCHISOR))
    overdue = get_success_data(api_client.get_royalty_statement(statement["id"], CLERK))
    assert overdue["status"] == "OVERDUE"
    # NOTE: the exact intermediate provisional late_fee while OVERDUE is NOT uniquely
    # derivable from the PRD. §3.11 mandates the simple-provisional recompute ONLY on
    # the "ISSUED → OVERDUE" transition cascade; it is silent on whether an already-
    # OVERDUE statement re-accrues its provisional fee on each subsequent period close.
    # A faithful PRD-only implementer may compute the provisional fee once at the
    # transition (months_late=1) and never re-accrue it. That assertion was removed
    # (BRANCH-ASYMMETRIC SIDE EFFECT silence). The compound FINAL fee below IS uniquely
    # derivable: §3.9 says the final compound variant is recomputed against the brand
    # clock at write-off (months_late = current_period_index - due_period_index = 3).
    brand_v = get_brand_version(brand["id"])
    final = validate_success(
        api_client.write_off_royalty_statement(
            statement["id"], write_off_payload(brand_v), CLERK
        ),
        expected_status=200,
    )
    # 840000 * ((1+0.015)**3 - 1) rounded half-up = 38370 (compound, months_late=3).
    assert final["late_fee_cents"] == 38370
    # §3.9: the compound variant "diverges upward from the simple variant once the
    # months-late count is 2 or more" — at months_late=3 the simple value is 37800.
    assert final["late_fee_cents"] != 37800, "compound must diverge from the simple value"


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: combinatorial_formula / tiered_royalty_marginal_three_band_nonlinear
# ═══════════════════════════════════════════════════════════════════════════
def test_marginal_three_band_royalty_nonlinear():
    """PRD §3.9: "The first $50,000 of basis — that is, the first 5,000,000 cents — is
    charged at the brand's royalty_tier_1_rate. The portion of the basis above 5,000,000
    cents and up to $100,000 (10,000,000 cents) is charged at royalty_tier_2_rate. Any
    portion of the basis above 10,000,000 cents is charged at royalty_tier_3_rate."

    Design: Difficulty/combinatorial_formula/tiered_royalty_marginal_three_band_nonlinear
    """
    # basis 11500000 → 5000000*0.06 + 5000000*0.05 + 1500000*0.04 = 300000+250000+60000
    _, _, _, _, statement = setup_issued_statement(11_500_000)
    assert statement["net_sales_basis_cents"] == 11_500_000
    assert statement["royalty_cents"] == 610000, (
        f"marginal tiers must give 610000, got {statement['royalty_cents']}"
    )
    assert statement["ad_fund_cents"] == 230000
    assert statement["total_due_cents"] == 840000


def test_marginal_royalty_not_single_blended_rate():
    """PRD §3.9: "The royalty on a statement is computed by marginal tiers on its
    net_sales_basis_cents, never as a single blended rate on the whole basis."
    PRD §3.9: "The three tier contributions are summed first, and the single summed
    total is then rounded half up to whole cents to yield royalty_cents — rounding is
    applied once to the summed marginal total, not separately per tier."

    Design: Difficulty/combinatorial_formula/tiered_royalty_marginal_three_band_nonlinear
    """
    _, _, _, _, statement = setup_issued_statement(11_500_000)
    blended = round(11_500_000 * 0.06)  # 690000 — the wrong single-rate answer
    assert statement["royalty_cents"] == 610000
    assert statement["royalty_cents"] != blended, (
        "must not apply tier-1 rate to the whole basis"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty: combinatorial_formula / royalty_aggregate_basis_then_tier_vs_per_report
# ═══════════════════════════════════════════════════════════════════════════
def test_royalty_aggregates_basis_then_tiers():
    """PRD §3.8: "The net_sales_basis_cents is the sum of net_sales_cents over the
    ACCEPTED sales reports for that unit and period_index."
    PRD §3.9: "The first $50,000 of basis — that is, the first 5,000,000 cents — is
    charged at the brand's royalty_tier_1_rate."

    Design: Difficulty/combinatorial_formula/royalty_aggregate_basis_then_tier_vs_per_report_order
    """
    brand, _, _, unit = setup_open_unit(owner_user_id="u_agg", territory_code="AG")
    create_accepted_sales_report(unit["id"], 0, 4_000_000, discounts_cents=0)
    create_accepted_sales_report(unit["id"], 0, 4_000_000, discounts_cents=0)
    statement = create_issued_statement(unit["id"], 0)
    # basis 8000000 → 5000000*0.06 + 3000000*0.05 = 300000 + 150000 = 450000
    assert statement["net_sales_basis_cents"] == 8_000_000
    assert statement["royalty_cents"] == 450000, (
        f"aggregate-then-tier must give 450000, got {statement['royalty_cents']}"
    )
    assert statement["ad_fund_cents"] == 160000


def test_royalty_not_tiered_per_report_then_summed():
    """PRD §3.8: "The net_sales_basis_cents is the sum of net_sales_cents over the
    ACCEPTED sales reports for that unit and period_index."
    PRD §3.9: "The royalty on a statement is computed by marginal tiers on its
    net_sales_basis_cents, never as a single blended rate on the whole basis."

    Design: Difficulty/combinatorial_formula/royalty_aggregate_basis_then_tier_vs_per_report_order
    """
    brand, _, _, unit = setup_open_unit(owner_user_id="u_agg2", territory_code="AG2")
    create_accepted_sales_report(unit["id"], 0, 4_000_000, discounts_cents=0)
    create_accepted_sales_report(unit["id"], 0, 4_000_000, discounts_cents=0)
    statement = create_issued_statement(unit["id"], 0)
    per_report_then_sum = round(4_000_000 * 0.06) * 2  # 480000, the wrong answer
    assert statement["royalty_cents"] == 450000
    assert statement["royalty_cents"] != per_report_then_sum, (
        "must aggregate basis before tiering, not tier each report"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Corner: calculations / ad_fund_rounding_half_up
# ═══════════════════════════════════════════════════════════════════════════
def test_ad_fund_rounds_half_up():
    """PRD §3.9: "The ad-fund contribution is simpler: ad_fund_cents is the
    net_sales_basis_cents multiplied by the brand's ad_fund_rate, rounded half up to
    whole cents."

    Design: Corner/calculations/ad_fund_rounding_half_up
    """
    _, _, _, _, statement = setup_issued_statement(1_234_567)
    assert statement["net_sales_basis_cents"] == 1_234_567
    assert statement["ad_fund_cents"] == 24691  # round_half_up(24691.34)
    assert statement["royalty_cents"] == 74074  # round_half_up(1234567*0.06=74074.02)


# ═══════════════════════════════════════════════════════════════════════════
# Corner: calculations / transfer_fee_floor_applies_for_new_operator
# ═══════════════════════════════════════════════════════════════════════════
def test_transfer_fee_floor_plus_training_for_new_operator():
    """PRD §3.9: "the base fee is the larger of that rounded percentage component and a
    flat floor of $10,000 (1,000,000 cents). The final transfer fee is the base fee
    plus a training fee of $5,000 (500,000 cents) when the buyer's is_existing_operator
    is false, or the base fee alone when the buyer is already an existing operator."

    Design: Corner/calculations/transfer_fee_floor_applies_for_new_operator
    """
    # Seller has NO issued statements → trailing_basis 0 → percentage 0 → floor 1000000;
    # buyer is a new operator (is_existing_operator false) → +500000 = 1500000.
    brand, seller, terr, agreement, _ = setup_renewal_pending_agreement(
        owner_user_id="u_seller", territory_code="TF"
    )
    buyer = create_franchisee(
        brand["id"], owner_user_id="u_buyer", is_existing_operator=False
    )
    approve_franchisee(buyer["id"])
    data = validate_success(
        api_client.transfer_agreement(
            agreement["id"], transfer_agreement_payload(buyer["id"]), FRANCHISOR
        ),
        expected_status=200,
    )
    assert data["status"] == "TRANSFERRED"
    # PRD §3.3 states the fee is "returned in the response"; the cents value is what
    # is pinned. Accept the canonical *_cents field name the response carries.
    fee = next(
        (data[k] for k in ("transfer_fee_cents", "transfer_fee", "fee_cents")
         if k in data and data[k] is not None),
        None,
    )
    assert fee == 1500000, (
        f"transfer fee must be floor 1000000 + training 500000 = 1500000, got {fee} "
        f"(response keys: {list(data)})"
    )
