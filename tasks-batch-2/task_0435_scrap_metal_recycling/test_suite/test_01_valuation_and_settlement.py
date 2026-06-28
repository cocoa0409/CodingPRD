"""Valuation and settlement-reconciliation calculations.

Difficulty queue: dual_variant_calc + combinatorial_formula calculation instances.
"""
from test_helpers import (
    validate_success,
    fixtures,
)
from test_helpers.fixtures import (
    publish_price,
    register_seller,
    stage_container,
    open_ticket,
    add_line,
    create_released_ticket,
    dispatch_container,
    YM, WM, SA,
)
from test_helpers.api_client import api_client


# ---------------------------------------------------------------------------
# Rule 1 — dual_variant_calc / intake_spot_vs_mill_settlement_variant_diverges
# ---------------------------------------------------------------------------
def test_intake_spot_valuation_freezes_at_weighed(api):
    """PRD §3.3: "The line's `line_valuation_cents` is computed immediately as the
    line's `weight_lb` multiplied by that pinned row's `spot_price_cents_per_lb`,
    rounded half-up to whole cents."
    PRD §3.3: "The frozen gross valuation is the sum of the already-rounded
    `line_valuation_cents` across all the ticket's line items — each line rounded
    at line-creation time, then summed here."

    Two CU lines (10.1, 20.1 lb @ spot 375): 3788 + 7538 = 11326c on the buy side.

    Design: Difficulty/dual_variant_calc/intake_spot_vs_mill_settlement_variant_diverges
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="Acme Salvage", id_type="DRIVERS_LICENSE",
                             id_number="DL-1", tin="11-1111111")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 10.1)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 20.1)
    data = validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    assert data["gross_valuation_cents"] == 11326, \
        f"expected gross_valuation_cents 11326, got {data['gross_valuation_cents']}"


def test_mill_settlement_estimate_diverges_from_intake_spot(api):
    """PRD §3.7: "for each `TicketLineItem` on it, the line's `weight_lb` is
    multiplied by the `mill_price_cents_per_lb` of the line's pinned
    `commodity_price_id` row and rounded half-up to whole cents, and these rounded
    per-line amounts are accumulated into `expected_settlement_cents`."

    The SAME two CU lines (10.1, 20.1 lb) read on the sell side @ mill 410 yield
    4141 + 8241 = 12382c — a different figure on a different entity than the
    intake spot valuation (11326c).

    Design: Difficulty/dual_variant_calc/intake_spot_vs_mill_settlement_variant_diverges
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="Acme Salvage", id_type="DRIVERS_LICENSE",
                             id_number="DL-1", tin="11-1111111")
    container = stage_container("NON_FERROUS", capacity_lb=100000)
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 10.1)
    add_line(ticket["id"], "CU_BARE_BRIGHT", 20.1)
    ticket = validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    api_client.release_ticket(ticket["id"], {"container_id": container["id"]}, WM)
    dispatch_container(container["id"])
    ship = validate_success(
        api.create_mill_shipment({"container_id": container["id"]}, YM), 201
    )
    assert ship["expected_settlement_cents"] == 12382, \
        f"expected settlement 12382, got {ship['expected_settlement_cents']}"
    assert ship["expected_settlement_cents"] != ticket["gross_valuation_cents"], \
        "mill estimate must diverge from the intake spot valuation"


# ---------------------------------------------------------------------------
# Rule 1 — dual_variant_calc / cumulative_1099_ledger_vs_hedge_pnl_on_different_entities
# ---------------------------------------------------------------------------
def test_cash_ledger_accrues_on_seller(api):
    """PRD §3.5: "When `method` is `CASH`, the seller's `ytd_cash_paid_cents` — the
    cumulative cash, not check, paid to that seller across the tax year — is
    increased by the payout's `amount_cents`."

    A single 11000c CASH payout leaves the seller's ytd_cash_paid_cents at 11000.

    Design: Difficulty/dual_variant_calc/cumulative_1099_ledger_vs_hedge_pnl_on_different_entities
    """
    publish_price("SHRED_STEEL", "FERROUS", spot=11, mill=14)
    seller = register_seller(legal_name="Bolt Metals", id_type="STATE_ID",
                             id_number="SID-2", tin="22-2222222")
    built = fixtures.create_released_ticket(
        grade_code="SHRED_STEEL", category="FERROUS", spot=11, mill=14,
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        capacity_lb=5000, seller_id=seller["id"],
    )
    payout = validate_success(
        api.create_payout({"ticket_id": built["ticket"]["id"], "method": "CASH"},
                          fixtures.PC), 201
    )
    validate_success(api.settle_payout(payout["id"], fixtures.PC))
    seller_after = validate_success(api.get_seller(seller["id"], WM))
    assert seller_after["ytd_cash_paid_cents"] == 11000, \
        f"expected ytd_cash_paid_cents 11000, got {seller_after['ytd_cash_paid_cents']}"


def test_hedge_pnl_accrues_on_hedge_position(api):
    """PRD §3.7: "The leg's profit and loss is the realized pounds multiplied by the
    difference between the hedge's `locked_price_cents_per_lb` and that effective
    realized mill price, rounded half-up to whole cents — positive when the locked
    price exceeds the realized mill price."

    A 1300 lb shipment settled at 100000c (effective 77c) against a hedge locked at
    90c realizes leg P&L 1300*(90-77)=16900c on the HedgePosition — a different
    conserved metric on a different entity than the seller cash ledger.

    Design: Difficulty/dual_variant_calc/cumulative_1099_ledger_vs_hedge_pnl_on_different_entities
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 100000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    hedge_after = validate_success(api.get_hedge(built["hedge"]["id"], SA))
    assert hedge_after["realized_pnl_cents"] == 16900, \
        f"expected realized_pnl_cents 16900, got {hedge_after['realized_pnl_cents']}"
    assert hedge_after["realized_weight_lb"] == 1300, \
        f"expected realized_weight_lb 1300, got {hedge_after['realized_weight_lb']}"


# ---------------------------------------------------------------------------
# Rule 2 — combinatorial_formula / per_line_round_then_sum_order_pinned
# ---------------------------------------------------------------------------
def test_per_line_round_then_sum_order_pinned(api):
    """PRD §2.5: "where a total spans several material lines, each line's cents value
    is rounded first and the rounded line values are then summed — never the
    reverse."
    PRD §3.3: "The frozen gross valuation is the sum of the already-rounded
    `line_valuation_cents` across all the ticket's line items — each line rounded
    at line-creation time, then summed here."

    10.1*375=3787.5 -> 3788, 20.1*375=7537.5 -> 7538, sum 11326 (sum-then-round
    would give 11325).

    Design: Difficulty/combinatorial_formula/per_line_round_then_sum_order_pinned
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="Acme Salvage", id_type="DRIVERS_LICENSE",
                             id_number="DL-1")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    line1 = validate_success(
        api.add_line_item(ticket["id"], {"grade_code": "CU_BARE_BRIGHT", "weight_lb": 10.1}, WM), 201
    )
    line2 = validate_success(
        api.add_line_item(ticket["id"], {"grade_code": "CU_BARE_BRIGHT", "weight_lb": 20.1}, WM), 201
    )
    assert line1["line_valuation_cents"] == 3788, \
        f"expected line1 3788, got {line1['line_valuation_cents']}"
    assert line2["line_valuation_cents"] == 7538, \
        f"expected line2 7538, got {line2['line_valuation_cents']}"
    data = validate_success(api.weigh_out(ticket["id"], {"tare_weight_lb": 200}, WM))
    assert data["gross_valuation_cents"] == 11326, \
        f"expected gross_valuation_cents 11326, got {data['gross_valuation_cents']}"


# ---------------------------------------------------------------------------
# Rule 2 — combinatorial_formula / hedge_pnl_min_cap_and_nested_min_inputs
# ---------------------------------------------------------------------------
def test_hedge_pnl_unfavorable_nested_min_and_branch(api):
    """PRD §3.7: "The pounds realized on this leg is the smaller of the shipment's
    `shipped_weight_lb` and the hedge's remaining capacity."
    PRD §3.7: "The leg's profit and loss is the realized pounds multiplied by the
    difference between the hedge's `locked_price_cents_per_lb` and that effective
    realized mill price, rounded half-up to whole cents ... negative when the
    locked price is below it (the hedge lost while spot rose)."
    PRD §3.7: "If the realization brings `realized_weight_lb` to at least
    `hedged_weight_lb`, the hedge auto-closes, moving `OPEN → CLOSED`."

    1300 lb shipment, final 130000c -> effective 100c; leg P&L 1300*(90-100)=-13000;
    realized reaches hedged 1300 so the hedge auto-closes.

    Design: Difficulty/combinatorial_formula/hedge_pnl_min_cap_and_nested_min_inputs
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 130000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    hedge_after = validate_success(api.get_hedge(built["hedge"]["id"], SA))
    assert hedge_after["realized_pnl_cents"] == -13000, \
        f"expected realized_pnl_cents -13000, got {hedge_after['realized_pnl_cents']}"
    assert hedge_after["realized_weight_lb"] == 1300, \
        f"expected realized_weight_lb 1300, got {hedge_after['realized_weight_lb']}"
    assert hedge_after["status"] == "CLOSED", \
        f"expected hedge CLOSED, got {hedge_after['status']}"


def test_per_line_round_individual_line_value(api):
    """PRD §3.3: "The line's `line_valuation_cents` is computed immediately as the
    line's `weight_lb` multiplied by that pinned row's `spot_price_cents_per_lb`,
    rounded half-up to whole cents."
    PRD §2.5: "a value of exactly one-half cent rounds away from zero, upward."

    A single 10.1 lb line @ 375c is exactly 3787.5 -> rounds up to 3788 (the
    rounding-at-the-line half of the per-line-round-then-sum rule).

    Design: Difficulty/combinatorial_formula/per_line_round_then_sum_order_pinned
    """
    publish_price("CU_BARE_BRIGHT", "NON_FERROUS", spot=375, mill=410)
    seller = register_seller(legal_name="Acme Salvage", id_type="DRIVERS_LICENSE",
                             id_number="DL-1")
    ticket = open_ticket(seller["id"], gross_weight_lb=1500)
    line = validate_success(
        api.add_line_item(ticket["id"], {"grade_code": "CU_BARE_BRIGHT", "weight_lb": 10.1}, WM), 201
    )
    assert line["line_valuation_cents"] == 3788, \
        f"10.1*375=3787.5 must round-half-up to 3788, got {line['line_valuation_cents']}"


def test_hedge_pnl_favorable_nested_min_and_branch(api):
    """PRD §3.7: "The realization first derives the effective realized sell price per
    pound: the shipment's `final_settlement_cents` divided by its
    `shipped_weight_lb`, rounded half-up to whole cents."
    PRD §3.7: "The leg's profit and loss is the realized pounds multiplied by the
    difference between the hedge's `locked_price_cents_per_lb` and that effective
    realized mill price, rounded half-up to whole cents — positive when the locked
    price exceeds the realized mill price (the hedge gained while spot fell)."

    1300 lb, final 100000c -> effective 77c; leg 1300*(90-77)=+16900 (favorable branch),
    the opposite sign branch from the unfavorable case.

    Design: Difficulty/combinatorial_formula/hedge_pnl_min_cap_and_nested_min_inputs
    """
    built = fixtures.create_shipped_shipment_with_hedge(
        hedged_weight_lb=1300, locked_price=90, category="FERROUS",
        weight_lb=1000, gross_weight_lb=1500, tare_weight_lb=200,
        spot=11, mill=14, grade_code="SHRED_STEEL",
    )
    validate_success(
        api.settle_mill_shipment(
            built["shipment"]["id"],
            {"final_settlement_cents": 100000,
             "expected_hedge_version": built["hedge_version"]},
            SA,
        )
    )
    hedge_after = validate_success(api.get_hedge(built["hedge"]["id"], SA))
    assert hedge_after["realized_pnl_cents"] == 16900, \
        f"favorable leg P&L must be +16900, got {hedge_after['realized_pnl_cents']}"
