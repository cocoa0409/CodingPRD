"""Cost-basis realization (FIFO), the SELL-fill cascade, and 1099-B term.

Covers difficulty instances on the Position/Lot/Disposal domain and the
related corner-design probes.
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    make_account_holder_headers,
    make_clearing_system_headers,
    create_security, funded_cash_account, buy_and_fill, sell_and_fill,
    get_first_position, get_account_version, place_order, fill_order, advance_clock,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def test_fifo_disposal_realized_pl_and_lot_order(api):
    """PRD §3.5: "Under the FIFO variant — applied when the position's `cost_basis_method`
    is `FIFO` — the system consumes open lots oldest-first, ordered by ascending `acquired_at`
    then `created_at`, considering only `OPEN` and `PARTIALLY_CLOSED` lots and excluding
    `CLOSED` ones; for each consumed slice of quantity taken from a lot, the slice basis is
    that slice quantity multiplied by the lot's `cost_per_share_cents` rounded half up, and
    the disposal's `cost_basis_cents` is the sum of those per-slice bases, with the specific
    consumed `lot_id` recorded."
    PRD §3.5: "Proceeds are the disposed quantity multiplied by the SELL fill price per share,
    rounded half up to whole cents."
    PRD §3.5: "In both variants the realized profit or loss is the proceeds minus the cost basis."

    Design: Difficulty/dual_variant_calc/cost_basis_fifo_vs_average_divergence
    """
    sec = create_security(symbol="ACMEF", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=5_000_000)
    # Two lots in FIFO order: 2sh @ 5000c, then 3sh @ 6000c.
    buy_and_fill(account_id, sec["id"], 2, 5000, order_type="MARKET")
    buy_and_fill(account_id, sec["id"], 3, 6000, order_type="MARKET")
    position = get_first_position(account_id)
    assert position["cost_basis_method"] == "FIFO"

    # SELL 4 sh @ 7000c (closing).
    order, fill = sell_and_fill(account_id, sec["id"], 4, 7000, order_type="MARKET", is_closing=True)

    pos_after = validate_success(api.get_position(position["id"], _holder(account_id)))
    # FIFO: consume 2@5000 (basis 10000) + 2 of the 3@6000 (basis 12000) -> 22000.
    # proceeds 4*7000 = 28000; realized 28000 - 22000 = 6000.
    assert pos_after["realized_pl_cents"] == 6000, pos_after["realized_pl_cents"]

    disposals = get_success_data(api.list_disposals(position["id"], _holder(account_id)))
    total_proceeds = sum(d["proceeds_cents"] for d in disposals)
    total_basis = sum(d["cost_basis_cents"] for d in disposals)
    assert total_proceeds == 28000, total_proceeds
    assert total_basis == 22000, total_basis


def test_fifo_disposal_consumes_oldest_lot_first(api):
    """PRD §3.5: "Under the FIFO variant ... the system consumes open lots oldest-first,
    ordered by ascending `acquired_at` then `created_at` ... with the specific consumed
    `lot_id` recorded."
    PRD §3.5: "A disposal that consumes part of a lot — disposing fewer shares than the lot's
    `remaining_quantity` — moves it to `PARTIALLY_CLOSED` and reduces `remaining_quantity`; a
    disposal that consumes exactly the whole remaining quantity moves the lot to `CLOSED` with
    `remaining_quantity` driven to zero, whether that happens from `OPEN` or from
    `PARTIALLY_CLOSED`."

    Design: Difficulty/dual_variant_calc/cost_basis_fifo_vs_average_divergence
    """
    sec = create_security(symbol="ACMEG", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=5_000_000)
    buy_and_fill(account_id, sec["id"], 2, 5000, order_type="MARKET")  # lot A
    buy_and_fill(account_id, sec["id"], 3, 6000, order_type="MARKET")  # lot B
    position = get_first_position(account_id)

    lots_before = get_success_data(api.list_lots(position["id"], _holder(account_id)))
    # Oldest lot is the 2sh @ 5000c lot.
    oldest = min(lots_before, key=lambda lt: (lt["acquired_at"], lt["created_at"]))
    assert oldest["original_quantity"] == 2
    assert oldest["cost_per_share_cents"] == 5000

    sell_and_fill(account_id, sec["id"], 4, 7000, order_type="MARKET", is_closing=True)

    lots_after = get_success_data(api.list_lots(position["id"], _holder(account_id)))
    lot_a = next(lt for lt in lots_after if lt["id"] == oldest["id"])
    lot_b = next(lt for lt in lots_after if lt["id"] != oldest["id"])
    # Oldest lot (2sh) fully consumed; newer lot (3sh) reduced to 1 remaining.
    assert lot_a["status"] == "CLOSED" and lot_a["remaining_quantity"] == 0, lot_a
    assert lot_b["status"] == "PARTIALLY_CLOSED" and lot_b["remaining_quantity"] == 1, lot_b


def test_sell_fill_cascades_to_disposal_lot_and_position(api):
    """PRD §3.5: "For a SELL, the fill creates one or more `Disposal` records consuming open
    lots, cascading into a recompute of `Position.quantity` and `realized_pl_cents`."
    PRD §3.5: "A disposal that consumes part of a lot — disposing fewer shares than the lot's
    `remaining_quantity` — moves it to `PARTIALLY_CLOSED` and reduces `remaining_quantity`."
    PRD §3.5: "a computed `quantity` (the sum of `remaining_quantity` over its open lots)."

    Design: Difficulty/transitive_cascade/sell_fill_cascades_disposal_lot_position_depth3
    """
    sec = create_security(symbol="SELLCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    buy_and_fill(account_id, sec["id"], 5, 5000, order_type="MARKET")  # one lot 5sh @ 5000c
    position = get_first_position(account_id)

    sell_and_fill(account_id, sec["id"], 2, 10000, order_type="MARKET", is_closing=True)

    # Link 1: the Disposal.
    disposals = get_success_data(api.list_disposals(position["id"], _holder(account_id)))
    assert len(disposals) == 1, disposals
    d = disposals[0]
    assert d["quantity"] == 2, d
    assert d["proceeds_cents"] == 20000, d
    assert d["cost_basis_cents"] == 10000, d
    assert d["realized_pl_cents"] == 10000, d

    # Link 2: the consumed Lot.
    lots = get_success_data(api.list_lots(position["id"], _holder(account_id)))
    consumed = lots[0]
    assert consumed["status"] == "PARTIALLY_CLOSED", consumed
    assert consumed["remaining_quantity"] == 3, consumed

    # Link 3: the Position recompute.
    pos_after = validate_success(api.get_position(position["id"], _holder(account_id)))
    assert pos_after["quantity"] == 3, pos_after
    assert pos_after["realized_pl_cents"] == 10000, pos_after


def test_disposal_short_term_classification(api):
    """PRD §3.5: "The `term` is `SHORT` when the holding period from acquisition to the current
    clock instant is at most 365 days and `LONG` when it exceeds 365 days; under FIFO the
    holding period is measured from the consumed lot's `acquired_at`."

    Design: Difficulty/transitive_cascade/sell_fill_cascades_disposal_lot_position_depth3
    """
    sec = create_security(symbol="SHRTCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    buy_and_fill(account_id, sec["id"], 5, 5000, order_type="MARKET")
    position = get_first_position(account_id)
    # SELL same clock day -> held 0 days -> SHORT.
    sell_and_fill(account_id, sec["id"], 2, 10000, order_type="MARKET", is_closing=True)

    disposals = get_success_data(api.list_disposals(position["id"], _holder(account_id)))
    assert disposals[0]["term"] == "SHORT", disposals[0]


def test_disposal_long_term_classification(api):
    """PRD §3.5: "The `term` is `SHORT` when the holding period from acquisition to the current
    clock instant is at most 365 days and `LONG` when it exceeds 365 days; under FIFO the
    holding period is measured from the consumed lot's `acquired_at`."

    Design: Corner/calculations/disposal_long_term_classification
    """
    sec = create_security(symbol="LTCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    buy_and_fill(account_id, sec["id"], 2, 5000, order_type="MARKET")
    # Advance the clock past 365 days from 2026-01-01.
    advance_clock("2027-02-02T00:00:00Z")
    position = get_first_position(account_id)
    sell_and_fill(account_id, sec["id"], 1, 10000, order_type="MARKET", is_closing=True)

    disposals = get_success_data(api.list_disposals(position["id"], _holder(account_id)))
    d = disposals[0]
    assert d["term"] == "LONG", d
    assert d["proceeds_cents"] == 10000, d
    assert d["cost_basis_cents"] == 5000, d
    assert d["realized_pl_cents"] == 5000, d
