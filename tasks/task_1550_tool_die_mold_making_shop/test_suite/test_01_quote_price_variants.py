"""Quote-kind price divergence: BUDGETARY vs FIRM contingency (PRD §3.3)."""
import pytest

from test_helpers import (
    assert_quote,
    create_customer,
    create_quote,
    create_released_design,
)


def _setup_two_quotes():
    """RELEASED CLASS_103 design (4 cavities, complexity 10) with one
    BUDGETARY and one FIRM quote, both at the uncompressed 12-week lead."""
    customer = create_customer(company_name="Acme Plastics")
    design = create_released_design(customer["id"], part_number="PN-1001")
    q_budgetary = create_quote(
        customer["id"], design["id"], quote_kind="BUDGETARY", requested_lead_weeks=12
    )
    q_firm = create_quote(
        customer["id"], design["id"], quote_kind="FIRM", requested_lead_weeks=12
    )
    return customer, design, q_budgetary, q_firm


def test_budgetary_quote_carries_fifteen_percent_contingency(api):
    """PRD §3.3: "`base_price_cents` is the class base plus cavitation plus
    complexity: a class base of 12,000,000 cents for `CLASS_101`, 9,000,000
    for `CLASS_102`, 6,500,000 for `CLASS_103`, 4,000,000 for `CLASS_104`, or
    1,800,000 for `CLASS_105`; plus `cavity_count` multiplied by the
    per-cavity rate of 800,000, 650,000, 500,000, 350,000, or 200,000 cents
    for classes 101 through 105 respectively; plus `design_complexity_score`
    multiplied by 150,000 cents per point."
    PRD §3.3: "`contingency_pct` is 0.15 for a `BUDGETARY` quote and 0.05 for
    a `FIRM` quote."
    PRD §3.3: "`total_price_cents` is `subtotal_cents` multiplied by one plus
    `contingency_pct`, rounded half-up to integer cents — the second and final
    rounding step."

    Design: Difficulty/dual_variant_calc/quote_budgetary_vs_firm_contingency_divergence
    """
    _, _, q_budgetary, _ = _setup_two_quotes()

    assert_quote(q_budgetary)
    # 6,500,000 + 4 * 500,000 + 10 * 150,000 = 10,000,000.
    assert q_budgetary["base_price_cents"] == 10_000_000, (
        f"base_price_cents mismatch: {q_budgetary['base_price_cents']}"
    )
    # 12 weeks requested against the 12-week CLASS_103 standard: no compression.
    assert q_budgetary["surcharge_pct"] == pytest.approx(0.0)
    assert q_budgetary["subtotal_cents"] == 10_000_000
    assert q_budgetary["contingency_pct"] == pytest.approx(0.15)
    assert q_budgetary["total_price_cents"] == 11_500_000, (
        f"BUDGETARY total mismatch: {q_budgetary['total_price_cents']}"
    )


def test_firm_quote_carries_five_percent_contingency_and_diverges(api):
    """PRD §3.3: "`contingency_pct` is 0.15 for a `BUDGETARY` quote and 0.05
    for a `FIRM` quote."
    PRD §3.3: "`total_price_cents` is `subtotal_cents` multiplied by one plus
    `contingency_pct`, rounded half-up to integer cents — the second and final
    rounding step."

    Design: Difficulty/dual_variant_calc/quote_budgetary_vs_firm_contingency_divergence
    """
    _, _, q_budgetary, q_firm = _setup_two_quotes()

    assert_quote(q_firm)
    assert q_firm["base_price_cents"] == 10_000_000
    assert q_firm["surcharge_pct"] == pytest.approx(0.0)
    assert q_firm["subtotal_cents"] == 10_000_000
    assert q_firm["contingency_pct"] == pytest.approx(0.05)
    assert q_firm["total_price_cents"] == 10_500_000, (
        f"FIRM total mismatch: {q_firm['total_price_cents']}"
    )
    # Identical design inputs; the kind alone drives the two totals apart.
    divergence = q_budgetary["total_price_cents"] - q_firm["total_price_cents"]
    assert divergence == 1_000_000, (
        f"BUDGETARY - FIRM divergence mismatch: {divergence}"
    )
