"""Per-unit retain valuation: pinned per-delivery rounding order
(PRD §3.2)."""
from test_helpers import get_member, setup_year_with_deliveries


def test_per_delivery_rounding_member_total_288(api):
    """PRD §3.2: "The delivery's retain is its `net_bushels` multiplied by
    the commodity's rate, rounded half-up to whole cents — and the rounding
    order is pinned: each delivery's retain is rounded individually at settle
    time, and only then accumulated into the member's
    `per_unit_retains_cents`."

    Three deliveries of 13 bu CORN at dockage 0.05: net = floor(13*0.95) = 12
    per delivery, retain = round_half_up(12*8) = 96 each, member total 288.
    An aggregate-then-round report variant would yield 296; the member ledger
    must hold the per-delivery figure.

    Design: Difficulty/dual_variant_calc/per_unit_retain_per_delivery_vs_aggregate_on_member_ledger
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
        ],
    )
    member = get_member(ctx["members"]["patron"]["id"])
    assert member["per_unit_retains_cents"] == 288, (
        "Per-delivery rounding pinned: 3 * round_half_up(12 * 8) = 288; got "
        f"{member['per_unit_retains_cents']}"
    )


def test_per_delivery_net_and_retain_values(api):
    """PRD §3.2: "At settle time the system computes the delivery's
    `net_bushels` — the `gross_bushels` multiplied by one minus the
    `dockage_pct`, rounded down to a whole bushel — and then the delivery's
    `per_unit_retain_cents`, the per-unit retain withheld into member
    capital."
    PRD §3.2: "The retain rate is fixed per commodity: 8 cents per bushel
    for `CORN`, 10 for `SOYBEAN`, 6 for `WHEAT`, 7 for `SORGHUM`, and 9 for
    `SUNFLOWER`."

    Design: Difficulty/dual_variant_calc/per_unit_retain_per_delivery_vs_aggregate_on_member_ledger
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
            {"member_key": "patron", "commodity": "CORN", "gross_bushels": 13,
             "dockage_pct": 0.05},
        ],
    )
    assert len(ctx["deliveries"]) == 3
    for delivery in ctx["deliveries"]:
        # floor(13 * 0.95) = floor(12.35) = 12; round_half_up(12 * 8) = 96
        assert delivery["net_bushels"] == 12, (
            f"Expected net_bushels 12, got {delivery['net_bushels']}"
        )
        assert delivery["per_unit_retain_cents"] == 96, (
            f"Expected per_unit_retain_cents 96, got "
            f"{delivery['per_unit_retain_cents']}"
        )


def test_rounding_order_pinned_member_total_300(api):
    """PRD §3.2: "The delivery's retain is its `net_bushels` multiplied by
    the commodity's rate, rounded half-up to whole cents — and the rounding
    order is pinned: each delivery's retain is rounded individually at settle
    time, and only then accumulated into the member's
    `per_unit_retains_cents`."

    Five deliveries of 7 bu SOYBEAN at dockage 0.10: net = floor(7*0.9) = 6
    per delivery, retain = round_half_up(6*10) = 60 each, member total 300.
    Aggregate-then-round would yield round_half_up(35*0.9*10) = 315.

    Design: Difficulty/combinatorial_formula/per_unit_retain_rounding_order_pinned
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "patron", "commodity": "SOYBEAN",
             "gross_bushels": 7, "dockage_pct": 0.10}
            for _ in range(5)
        ],
    )
    member = get_member(ctx["members"]["patron"]["id"])
    assert member["per_unit_retains_cents"] == 300, (
        "Per-delivery rounding pinned: 5 * round_half_up(6 * 10) = 300; got "
        f"{member['per_unit_retains_cents']}"
    )


def test_rounding_order_pinned_delivery_fields(api):
    """PRD §3.2: "At settle time the system computes the delivery's
    `net_bushels` — the `gross_bushels` multiplied by one minus the
    `dockage_pct`, rounded down to a whole bushel — and then the delivery's
    `per_unit_retain_cents`, the per-unit retain withheld into member
    capital."

    Design: Difficulty/combinatorial_formula/per_unit_retain_rounding_order_pinned
    """
    ctx = setup_year_with_deliveries(
        [
            {"member_key": "patron", "commodity": "SOYBEAN",
             "gross_bushels": 7, "dockage_pct": 0.10}
            for _ in range(5)
        ],
    )
    assert len(ctx["deliveries"]) == 5
    for delivery in ctx["deliveries"]:
        # floor(7 * 0.9) = floor(6.3) = 6; round_half_up(6 * 10) = 60
        assert delivery["net_bushels"] == 6
        assert delivery["per_unit_retain_cents"] == 60
