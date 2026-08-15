"""Recovery projection gross/net variants (PRD §3.3)."""
from test_helpers import (
    make_appeal,
    make_denial,
    make_queued_denial,
    setup_catalog,
    validate_success,
)

PROJECTION_RULE_CITE = (
    'PRD §3.3: "The **gross** variant multiplies `open_balance_cents` by the rate at the '
    'next level and rounds half-up to whole cents."'
)
NET_RULE_CITE = (
    'PRD §3.3: "The **net** variant starts from the same product and subtracts 5000 cents '
    'of appeal processing cost per remaining level, flooring the result at zero; gross is '
    'therefore never less than net for identical data, and net is strictly smaller whenever '
    'at least one level remains."'
)
FALLBACK_CITE = (
    'PRD §3.3: "The fallback ladder is deterministic: if no appeal has resolved at the '
    'target level, use the payer-wide rate across all levels; if the payer has no resolved '
    'appeals at all, use the default rate 0.50."'
)


def test_recovery_projection_gross_variant(api, manager_headers):
    """PRD §3.3: "The **gross** variant multiplies `open_balance_cents` by the rate at the
    next level and rounds half-up to whole cents."
    PRD §3.3: "The fallback ladder is deterministic: if no appeal has resolved at the target
    level, use the payer-wide rate across all levels; if the payer has no resolved appeals at
    all, use the default rate 0.50."
    PRD §3.3: "The next level is the denial's `current_appeal_level` plus one, and the
    remaining levels are three minus the current level."

    Design: Difficulty/dual_variant_calc/recovery_projection_gross_vs_net
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-101", billed_amount_cents=220000, denied_amount_cents=200000,
    )
    data = validate_success(
        api.get_recovery_projection(denial["id"], manager_headers, params={"variant": "gross"})
    )
    assert data["variant"] == "gross"
    assert data["expected_recovery_cents"] == 100000  # 200000 * 0.50
    assert data["rate_applied"] == 0.5
    assert data["remaining_levels"] == 3


def test_recovery_projection_net_variant_differs(api, manager_headers):
    """PRD §3.3: "The **net** variant starts from the same product and subtracts 5000 cents
    of appeal processing cost per remaining level, flooring the result at zero; gross is
    therefore never less than net for identical data, and net is strictly smaller whenever at
    least one level remains."

    Design: Difficulty/dual_variant_calc/recovery_projection_gross_vs_net
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-101", billed_amount_cents=220000, denied_amount_cents=200000,
    )
    gross = validate_success(
        api.get_recovery_projection(denial["id"], manager_headers, params={"variant": "gross"})
    )
    net = validate_success(
        api.get_recovery_projection(denial["id"], manager_headers, params={"variant": "net"})
    )
    assert net["variant"] == "net"
    assert net["expected_recovery_cents"] == 85000  # 100000 - 5000 * 3
    assert gross["expected_recovery_cents"] != net["expected_recovery_cents"]


def test_recovery_projection_after_level_one(api, specialist_headers):
    """PRD §3.3: "To inform whether a denial is worth another appeal level, every role may
    read its **recovery projection**, a computed figure with an optional `variant` query
    parameter — `gross` (the default) or `net`."
    PRD §3.3: "The **net** variant starts from the same product and subtracts 5000 cents of
    appeal processing cost per remaining level, flooring the result at zero; gross is
    therefore never less than net for identical data, and net is strictly smaller whenever at
    least one level remains."

    Design: Corner/calculations/recovery_projection_after_level_one
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2205", billed_amount_cents=220000, denied_amount_cents=200000,
    )
    make_appeal(denial["id"])  # current_appeal_level -> 1
    default = validate_success(
        api.get_recovery_projection(denial["id"], specialist_headers)
    )
    assert default["variant"] == "gross", "omitting variant defaults to gross"
    assert default["expected_recovery_cents"] == 100000  # 200000 * 0.50
    assert default["remaining_levels"] == 2
    net = validate_success(
        api.get_recovery_projection(denial["id"], specialist_headers, params={"variant": "net"})
    )
    assert net["expected_recovery_cents"] == 90000  # 100000 - 5000 * 2
