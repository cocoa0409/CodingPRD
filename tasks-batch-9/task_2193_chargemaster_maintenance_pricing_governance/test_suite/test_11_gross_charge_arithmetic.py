"""Gross-charge arithmetic: tier selection, Medicare floor, market cap, rounding last."""
from test_helpers import (
    api_client, validate_success,
    setup_gross_charge_nesting_scenario,
    read_item, read_facility, reprice_item, patch_facility,
)


def test_nested_tier_floor_and_cap_resolve_before_nearest_cent_rounding():
    """PRD §3.2: "Under `COST_PLUS_MARKUP`, the applicable tier is the last tier in the
    ascending `markup_tiers` array whose `min_cost_basis_cents` is at or below the item's
    `cost_basis_cents` — the boundary is inclusive, so a cost basis exactly equal to a
    tier's threshold selects *that* tier rather than the one below it — and the base is the
    item's `cost_basis_cents` multiplied by the selected tier's `markup_bp`, divided by
    10000, rounded half up."
    PRD §3.2: "The order is pinned and it matters: when the floor exceeds the cap, the cap
    wins, and the item's `price_conflict` flag is set to true (it is false by default and
    whenever the floor is at or below the cap)."
    PRD §3.2: "Under `MEDICARE_MULTIPLE`, the base is the item's `medicare_rate_cents`
    multiplied by the rule's `min_medicare_multiple_bp`, divided by 10000, rounded half up."
    PRD §3.2: "Under `NEAREST_CENT` the constrained amount stands unchanged."
    PRD §3.4: "Because the two dimensions are independent, a `DRAFT` item and an `ACTIVE`
    item are both repriceable, and the lifecycle actions of §3.3 never write `price_status`
    except where explicitly stated."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_a_tier_floor_cap_nesting_with_rounding_mode_applied_last
    """
    s = setup_gross_charge_nesting_scenario()

    x = reprice_item(s["item_x"]["id"])
    assert x["gross_charge_cents"] == 450000, (
        "cost 250000 sits exactly on the 250000 tier boundary, so 18000bp applies: "
        f"expected 450000, got {x['gross_charge_cents']}"
    )
    assert x["price_conflict"] is False
    assert x["applied_price_rule_id"] == s["rule_cost_plus"]["id"]

    y = reprice_item(s["item_y"]["id"])
    assert y["gross_charge_cents"] == 110000, (
        "the Medicare floor 120000 exceeds the market cap 110000, so the cap wins: "
        f"expected 110000, got {y['gross_charge_cents']}"
    )
    assert y["price_conflict"] is True, "floor above cap must raise price_conflict"

    w = reprice_item(s["item_w"]["id"])
    assert w["gross_charge_cents"] == 96071, (
        "85396 * 11250 / 10000 is the exact half 96070.5 and rounds half up: "
        f"expected 96071, got {w['gross_charge_cents']}"
    )
    assert w["applied_price_rule_id"] == s["rule_medicare"]["id"]

    x_after = read_item(s["item_x"]["id"])
    assert x_after["price_status"] == "PRICED_CURRENT"
    assert x_after["lifecycle_status"] == "DRAFT", (
        "repricing must not touch the lifecycle dimension"
    )

    facility = read_facility(s["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 0, (
        "no item reached ACTIVE, so no reprice touched the facility aggregates"
    )
    assert facility["stale_price_item_count"] == 0
    assert facility["chargemaster_posture"] == "OPEN"


def test_rounding_mode_is_applied_once_last_across_nearest_dollar_and_psychological_99():
    """PRD §3.2: "Under `NEAREST_DOLLAR` the amount is divided by 100, rounded half up to a
    whole number of dollars, and multiplied back by 100. Under `PSYCHOLOGICAL_99` the amount
    is divided by 100, rounded *up* to the next whole dollar, multiplied by 100, and then
    reduced by one cent — so every price ends in 99 cents."
    PRD §3.2: "*Step three — the facility's rounding mode is applied exactly once, last.*"
    PRD §3.4: "On success, in order: `prior_gross_charge_cents` takes the item's outgoing
    `gross_charge_cents` before it is overwritten; `gross_charge_cents` takes the computed
    output; `applied_price_rule_id` records the selected rule; `price_conflict` is set
    according to whether the Medicare floor exceeded the market cap; `price_status` becomes
    `PRICED_CURRENT`; and the item's `version` advances by 1."

    Design: Difficulty/combinatorial_formula/combinatorial_formula__mode_a_tier_floor_cap_nesting_with_rounding_mode_applied_last
    """
    s = setup_gross_charge_nesting_scenario()
    reprice_item(s["item_x"]["id"])
    reprice_item(s["item_y"]["id"])
    reprice_item(s["item_w"]["id"])

    patch_facility(s["facility"]["id"], rounding_mode="NEAREST_DOLLAR")
    w = reprice_item(s["item_w"]["id"])
    assert w["gross_charge_cents"] == 96100, (
        "96071 cents rounds half up to 961 dollars under NEAREST_DOLLAR: "
        f"expected 96100, got {w['gross_charge_cents']}"
    )
    assert w["prior_gross_charge_cents"] == 96071

    patch_facility(s["facility"]["id"], rounding_mode="PSYCHOLOGICAL_99")

    x = reprice_item(s["item_x"]["id"])
    assert x["gross_charge_cents"] == 449999, (
        f"PSYCHOLOGICAL_99 on 450000 must end in 99 cents, got {x['gross_charge_cents']}"
    )
    assert x["prior_gross_charge_cents"] == 450000

    y = reprice_item(s["item_y"]["id"])
    assert y["gross_charge_cents"] == 109999
    assert y["price_conflict"] is True, (
        "the rounding step does not disturb the floor-above-cap conflict flag"
    )
    assert y["prior_gross_charge_cents"] == 110000

    w2 = reprice_item(s["item_w"]["id"])
    assert w2["gross_charge_cents"] == 96099, (
        "the constrained 96071 rounds up to 96100 then loses one cent: "
        f"expected 96099, got {w2['gross_charge_cents']}"
    )
    assert w2["prior_gross_charge_cents"] == 96100
