"""Quote ESTIMATE calculation: tiered margins, per-op rounding, boundary tier.

Translates queue A combinatorial_formula (estimate mode_b) and
boundary_precision_check (margin tier @ 50000), the ESTIMATE side of
dual_variant_calc, plus queue B calculations tier instances and the
price/approve precondition state_machine instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_priced_quote, create_draft_quote, add_routing_op,
    create_submitted_rfq_with_part_line,
    create_rfq_payload, create_part_line_payload, create_quote_payload,
    create_routing_op_payload,
    assert_quote,
    TEST_USERS,
)

EST = TEST_USERS["estimator_headers"]
ADMIN = TEST_USERS["shop_admin_headers"]


def test_estimate_labor_round_per_op_then_sum(api):
    """PRD §3.2: "for each operation, multiply its estimated cycle minutes by the
    per-minute rate of its machine class and round that product half up to whole
    cents, then multiply the rounded per-part labor by the part-line quantity,
    then add the operation's setup fee. The total labor cost is the sum of these
    per-op labor amounts across all routing operations of the quote."

    Two LATHE ops each 0.75*150 = 112.5 -> 113 cents per op; 113+113 = 226 (not a
    single round of 225.0). Design pins round-per-op-then-sum.

    Design: Difficulty/combinatorial_formula/estimate_labor_round_per_op_then_sum_mode_b
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "LATHE", "estimated_cycle_min": 0.75, "setup_fee_cents": 0},
            {"seq": 2, "machine_class": "LATHE", "estimated_cycle_min": 0.75, "setup_fee_cents": 0},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 1, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 0, "scrap_allowance_pct": 0},
        customer_id="CUST-3",
    )
    assert priced["extended_cost_cents"] == 226


def test_estimate_mode_b_margin_and_quoted_price(api):
    """PRD §3.2: "when extended_cost_cents is below 50000 cents the margin_pct is
    35".
    PRD §3.2: "The quoted price, recorded in quoted_price_cents, is the extended
    cost multiplied by one plus the margin percent divided by 100, rounded half
    up to whole cents."

    extended 226 -> 35% -> round(226*1.35)=305.

    Design: Difficulty/combinatorial_formula/estimate_labor_round_per_op_then_sum_mode_b
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "LATHE", "estimated_cycle_min": 0.75, "setup_fee_cents": 0},
            {"seq": 2, "machine_class": "LATHE", "estimated_cycle_min": 0.75, "setup_fee_cents": 0},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 1, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 0, "scrap_allowance_pct": 0},
        customer_id="CUST-3b",
    )
    assert priced["margin_pct"] == 35
    assert priced["quoted_price_cents"] == 305


def test_margin_tier_boundary_exactly_50000_uses_25pct(api):
    """PRD §3.2: "when it is at least 50000 cents but below 200000 cents the
    margin_pct is 25".

    extended lands exactly on 50000 (labor 32000 + material 18000) -> 25% tier
    (the >= boundary), not 35%.

    Design: Difficulty/boundary_precision_check/margin_tier_boundary_exactly_50000_uses_25pct
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_5AX", "estimated_cycle_min": 10.0, "setup_fee_cents": 0},
        ],
        part_line_overrides={"material_spec": "SS_304", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1800, "scrap_allowance_pct": 0},
        customer_id="CUST-11",
    )
    assert priced["extended_cost_cents"] == 50000
    assert priced["margin_pct"] == 25


def test_margin_tier_boundary_50000_quoted_price(api):
    """PRD §3.2: "The quoted price, recorded in quoted_price_cents, is the
    extended cost multiplied by one plus the margin percent divided by 100,
    rounded half up to whole cents."

    extended 50000 at 25% -> round(50000*1.25)=62500.

    Design: Difficulty/boundary_precision_check/margin_tier_boundary_exactly_50000_uses_25pct
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_5AX", "estimated_cycle_min": 10.0, "setup_fee_cents": 0},
        ],
        part_line_overrides={"material_spec": "SS_304", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1800, "scrap_allowance_pct": 0},
        customer_id="CUST-11b",
    )
    assert priced["quoted_price_cents"] == 62500


def test_estimate_low_tier_35pct(api):
    """PRD §3.2: "when extended_cost_cents is below 50000 cents the margin_pct is
    35".
    PRD §3.2: "Finally the per-part quoted price, recorded in
    quoted_unit_price_cents, is the quoted price divided by the part-line
    quantity, rounded half up to whole cents."

    Design: Corner/calculations/estimate_low_tier_35pct
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 5.0, "setup_fee_cents": 2000},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="C-19",
    )
    assert_quote(priced)
    assert priced["extended_cost_cents"] == 5800
    assert priced["margin_pct"] == 35
    assert priced["quoted_price_cents"] == 7830
    assert priced["quoted_unit_price_cents"] == 3915


def test_estimate_high_tier_18pct(api):
    """PRD §3.2: "when it is 200000 cents or more the margin_pct is 18".

    Design: Corner/calculations/estimate_high_tier_18pct
    """
    rfq, pl, priced, ops = create_priced_quote(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_5AX", "estimated_cycle_min": 30.0, "setup_fee_cents": 5000},
        ],
        part_line_overrides={"material_spec": "SS_304", "quantity": 20, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 600, "scrap_allowance_pct": 0},
        customer_id="C-20",
    )
    assert priced["extended_cost_cents"] == 209000
    assert priced["margin_pct"] == 18
    assert priced["quoted_price_cents"] == 246620


def test_price_quote_without_routing_rejected(api):
    """PRD §3.2: "Pricing is refused with ERR_QUOTE_NO_ROUTING if the quote has
    no routing operations".

    Design: Corner/state_machines/price_quote_without_routing_rejected
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-9",
    )
    res = api.price_quote(quote["id"], EST)
    validate_error(res, "ERR_QUOTE_NO_ROUTING")


def test_approve_quote_from_draft_invalid_state(api):
    """PRD §2.9: "State legality — the target resource must currently be in a
    state from which the requested transition is defined; otherwise
    ERR_INVALID_STATE (409). This applies to all state-changing endpoints."
    PRD §3.2: "Approval drives the quote PRICED -> APPROVED".

    A DRAFT (un-priced) quote cannot be approved; state check precedes OCC.

    Design: Corner/state_machines/approve_quote_from_draft_invalid_state
    """
    rfq, pl, quote = create_draft_quote(
        part_line_overrides={"material_spec": "AL_6061", "quantity": 3},
        quote_overrides={"material_unit_cost_cents": 800, "scrap_allowance_pct": 0},
        customer_id="C-10",
    )
    add_routing_op(quote["id"], seq=1, machine_class="MILL_3AX",
                   estimated_cycle_min=4.0, setup_fee_cents=1000)
    res = api.approve_quote(quote["id"], {"expected_quote_version": quote["version"]}, EST)
    validate_error(res, "ERR_INVALID_STATE")
