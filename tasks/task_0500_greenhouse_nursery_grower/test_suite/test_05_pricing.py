"""Order pricing: line extension, volume rebate (sum-then-round), and the freight
band / rack / floor-cap interaction.

Queue A (difficulty) — combinatorial_formula.
Queue B (corner) — calculations (freight, rebate tier-2), endpoints (line CRUD).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_multi_line_order, setup_published_lot, create_broker, create_draft_order, add_line,
)

SC = TEST_USERS["sales_coordinator_headers"]


# ─── A3: volume rebate is sum-then-round, not round-per-line ──────────────
def test_order_total_uses_sum_then_round_rebate(api):
    """PRD 3.10: "The rebate's rounding is applied once to the summed subtotal — sum
    first, then round — not per line."

    Design: Difficulty/combinatorial_formula/rebate_sum_then_round_not_round_per_line
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 1015, "started": 1015, "unit_price_cents": 425},
                    {"quantity": 1015, "started": 1015, "unit_price_cents": 425}],
        ship_to_state="WA", confirm=True, cultivar_code="GERC1")
    order = s["order"]
    assert order["order_total_cents"] == 861495, \
        f"sum-then-round total must be 861495, got {order['order_total_cents']}"
    assert order["order_total_cents"] != 861494, "861494 would be the round-per-line rebate"


def test_order_subtotal_and_freight_cap_components(api):
    """PRD 3.10: "the `order_total_cents` is the `order_subtotal_cents` minus the
    volume rebate plus the `freight_cents`."

    Design: Difficulty/combinatorial_formula/rebate_sum_then_round_not_round_per_line
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 1015, "started": 1015, "unit_price_cents": 425},
                    {"quantity": 1015, "started": 1015, "unit_price_cents": 425}],
        ship_to_state="WA", confirm=True, cultivar_code="GERC2")
    order = s["order"]
    assert order["order_subtotal_cents"] == 862750, f"2*1015*425, got {order['order_subtotal_cents']}"
    assert order["freight_cents"] == 16000, f"NEIGHBOR cap 16000, got {order['freight_cents']}"


# ─── A4: freight FAR band with rack ceil and floor/cap clamp ─────────────
def test_freight_far_band_rack_and_clamp(api):
    """PRD 3.10: "The raw freight is the band's base plus the rack count multiplied
    by the band's per-rack charge."

    Design: Difficulty/combinatorial_formula/freight_tier_band_rack_min_max_interaction
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 100, "unit_price_cents": 500}],
        ship_to_state="NY", confirm=True, cultivar_code="MUMD1")
    assert s["order"]["freight_cents"] == 10800, \
        f"FAR: 7000 + ceil(100/50)*1900 = 10800, got {s['order']['freight_cents']}"


def test_freight_far_band_total_has_no_rebate(api):
    """PRD 3.10: "otherwise the rebate is 0. The rebate's rounding is applied once to
    the summed subtotal — sum first, then round — not per line."

    Design: Difficulty/combinatorial_formula/freight_tier_band_rack_min_max_interaction
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 100, "unit_price_cents": 500}],
        ship_to_state="NY", confirm=True, cultivar_code="MUMD2")
    order = s["order"]
    assert order["order_subtotal_cents"] == 50000
    assert order["order_total_cents"] == 60800, \
        f"50000 + 10800 freight, no rebate (100<2000), got {order['order_total_cents']}"


# ─── B23: IN_STATE freight within floor/cap ──────────────────────────────
def test_freight_in_state_band(api):
    """PRD 3.10: "The `IN_STATE` band has a base of 2500, a per-rack of 600, a floor
    of 2500, and a cap of 9000."

    Design: Corner/calculations/freight_in_state_floor_applied
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 250}],
        ship_to_state="OR", confirm=True, cultivar_code="FRR1")
    order = s["order"]
    assert order["freight_cents"] == 4900, f"2500 + ceil(200/50)*600 = 4900, got {order['freight_cents']}"
    assert order["order_subtotal_cents"] == 50000
    assert order["order_total_cents"] == 54900


# ─── B24: rebate tier-2 (5%) at exactly 5000 units ───────────────────────
def test_rebate_tier2_five_percent_at_5000_units(api):
    """PRD 3.10: "if the total units are at least 5000, the rebate is the
    `order_subtotal_cents` multiplied by five hundredths, rounded half up".

    Design: Corner/calculations/rebate_tier2_5pct_at_5000_units
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 5000, "started": 5000, "unit_price_cents": 200}],
        ship_to_state="WA", confirm=True, capacity=6000, cultivar_code="RBR1")
    order = s["order"]
    assert order["order_subtotal_cents"] == 1000000
    # subtotal 1000000 - rebate 50000 + NEIGHBOR cap 16000
    assert order["order_total_cents"] == 966000, f"got {order['order_total_cents']}"


# ─── B33 / B34: line add snapshots price; delete recomputes totals ───────
def test_add_line_snapshots_unit_price_and_recomputes_totals(api):
    """PRD 3.10: "the line snapshots its `unit_price_cents` from the named
    availability entry, computes its `extended_cents` as `quantity` multiplied by
    `unit_price_cents`, and opens in `PENDING` status".

    Design: Corner/endpoints/add_line_snapshots_unit_price_and_recomputes_totals
    """
    lot = setup_published_lot(api, unit_price_cents=375, sourced=100, started=100, cultivar_code="LNR1")
    broker = create_broker(api, ship_to_state="OR")
    order = create_draft_order(api, broker["id"])
    line = add_line(api, order["id"], lot["entry"]["id"], 40)
    assert line["unit_price_cents"] == 375
    assert line["extended_cents"] == 15000, f"40*375, got {line['extended_cents']}"
    refreshed = validate_success(api.get_order(order["id"], SC))
    assert refreshed["order_subtotal_cents"] == 15000


def test_delete_pending_line_recomputes_totals(api):
    """PRD 3.10: "Removing a `PENDING` line from a `DRAFT` order moves it to
    `RELEASED`, recomputes the order totals, and again increments the order's
    `version` by one."

    Design: Corner/endpoints/delete_pending_line_recomputes_totals
    """
    lot = setup_published_lot(api, unit_price_cents=375, sourced=100, started=100, cultivar_code="DLR1")
    broker = create_broker(api, ship_to_state="OR")
    order = create_draft_order(api, broker["id"])
    line = add_line(api, order["id"], lot["entry"]["id"], 40)
    removed = validate_success(api.delete_order_line(line["id"], SC))
    assert removed["status"] == "RELEASED"
    refreshed = validate_success(api.get_order(order["id"], SC))
    assert refreshed["order_subtotal_cents"] == 0
