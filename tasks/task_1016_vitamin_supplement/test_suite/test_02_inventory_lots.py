"""Inventory lots: the AVAILABLE<->QUARANTINED cycle, recall terminality,
sellability at placement, FEFO allocation ordering, the reserved/available
reconciliation, expiry materialization, and reverse-lookup listing.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_lot, assert_lot_invariants, TEST_USERS, make_customer_headers,
    new_customer, new_product, new_lot, new_order, add_line, place,
    set_clock, run_expiry_sweep, recall_lot,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_lot_quarantine_transition(api):
    """PRD §3.2: "A lot moves from `AVAILABLE` to `QUARANTINED` when the current
    status is `AVAILABLE`; while `QUARANTINED` the lot is excluded from the
    first-expire-first-out candidate set and cannot serve new allocations, but
    any allocations already `RESERVED` against it are left untouched."

    Design: Difficulty/non_linear_state_machine/lot_available_quarantined_cycle
    """
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=5, lot_number="CY-1")
    assert lot["status"] == "AVAILABLE"
    res = api.set_lot_state(lot["id"], {"to_status": "QUARANTINED"}, OPERATOR)
    updated = validate_success(res, 200)
    assert_lot(updated)
    assert updated["status"] == "QUARANTINED"


def test_lot_available_quarantined_available_round_trip(api):
    """PRD §3.2: "A quarantined lot returns to `AVAILABLE` (re-entering the
    candidate set) when its current status is `QUARANTINED`. This forms a cyclic
    `AVAILABLE` ↔ `QUARANTINED` loop."

    Design: Difficulty/non_linear_state_machine/lot_available_quarantined_cycle
    """
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=5, lot_number="CY-1")
    validate_success(api.set_lot_state(lot["id"], {"to_status": "QUARANTINED"}, OPERATOR), 200)
    res = api.set_lot_state(lot["id"], {"to_status": "AVAILABLE"}, OPERATOR)
    updated = validate_success(res, 200)
    assert updated["status"] == "AVAILABLE", "round trip must restore AVAILABLE"


def test_quarantine_recalled_lot_rejected(api):
    """PRD §3.2: "`RECALLED` is a terminal lot status." — and §3.2: "A transition
    requested from a status that does not admit it is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_recalled_lot_terminal_lockdown
    """
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=5, lot_number="TL-1")
    recall_lot(lot["id"], reason="audit", severity="CLASS_III")
    res = api.set_lot_state(lot["id"], {"to_status": "QUARANTINED"}, OPERATOR)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_place_with_only_quarantined_lot_not_sellable(api):
    """PRD §2.6: "When allocation is attempted and no sellable lot can serve the
    demand, the offending condition surfaces as `ERR_LOT_NOT_SELLABLE`."

    Design: Corner/validations/corner_lot_not_sellable_when_quarantined
    """
    cust = new_customer(email="v4@x.com", full_name="V Four")
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=10, lot_number="V4-1")
    validate_success(api.set_lot_state(lot["id"], {"to_status": "QUARANTINED"}, OPERATOR), 200)
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 1)
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, "ERR_LOT_NOT_SELLABLE", expected_status=409)


def test_expiry_sweep_marks_lot_expired(api):
    """PRD §3.2: "When the sweep runs, any lot in `AVAILABLE` or `QUARANTINED`
    whose `expiration_date` is at or before the current logical clock transitions
    to `EXPIRED`; an expired lot is permanently excluded from the allocation
    candidate set."

    Design: Corner/cross_cutting/corner_expiry_sweep_marks_lot_expired
    """
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=5,
                  expiration_date="2026-08-01T00:00:00Z", lot_number="EX-1")
    set_clock("2026-09-01T00:00:00Z")
    run_expiry_sweep()
    fetched = validate_success(api.get_lot(lot["id"], OPERATOR), 200)
    assert fetched["status"] == "EXPIRED"


def test_list_product_lots_reverse_lookup(api):
    """PRD §3.1: "A lot may be listed under its product or filtered by `status`."
    PRD §2.3: "Paginated list responses include `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."

    Design: Corner/endpoints/corner_list_product_lots_reverse_lookup
    """
    prod = new_product(unit_price_cents=1000)
    new_lot(prod["id"], quantity_received=5, expiration_date="2027-01-01T00:00:00Z", lot_number="LS-1")
    new_lot(prod["id"], quantity_received=5, expiration_date="2027-02-01T00:00:00Z", lot_number="LS-2")
    data, meta = validate_paginated(api.list_product_lots(prod["id"], OPERATOR))
    assert meta["total_count"] == 2, "product has exactly 2 lots"
    assert len(data) == 2


def test_fefo_allocates_earliest_expiry_first(api):
    """PRD §3.6: "the candidate lots are the lots of the line's product whose
    `status` is `AVAILABLE` and whose `expiration_date` is strictly after the
    current logical clock; they are considered in order of `expiration_date`
    ascending, breaking ties by `created_at` ascending."

    Design: Corner/calculations/corner_fefo_earliest_expiry_first
    """
    cust = new_customer(email="ca4@x.com", full_name="CA Four")
    prod = new_product(unit_price_cents=1000)
    # Later-expiring lot created FIRST, earlier-expiring lot created SECOND.
    lot_b = new_lot(prod["id"], quantity_received=10,
                    expiration_date="2027-01-01T00:00:00Z", lot_number="FEFO-B")
    lot_a = new_lot(prod["id"], quantity_received=2,
                    expiration_date="2026-09-01T00:00:00Z", lot_number="FEFO-A")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 3)
    place(order["id"], cust["id"])
    a = validate_success(api.get_lot(lot_a["id"], OPERATOR), 200)
    b = validate_success(api.get_lot(lot_b["id"], OPERATOR), 200)
    assert a["quantity_reserved"] == 2, "earlier-expiring lot exhausted first"
    assert b["quantity_reserved"] == 1, "later-expiring lot serves the remainder"


def test_lot_reserved_available_reconciled_after_place(api):
    """PRD §2.6: "`quantity_available` is always `quantity_on_hand` minus
    `quantity_reserved`, and it is the count a new allocation may draw against."
    PRD §3.6: "increases the lot's `quantity_reserved` by the same amount,
    reducing the remaining demand."

    Design: Corner/cross_cutting/corner_lot_reserved_reconciled_after_place
    """
    cust = new_customer(email="cc3@x.com", full_name="CC Three")
    prod = new_product(unit_price_cents=1000)
    lot = new_lot(prod["id"], quantity_received=10, lot_number="RE-1")
    order = new_order(cust["id"])
    add_line(order["id"], cust["id"], prod["id"], 3)
    place(order["id"], cust["id"])
    fetched = validate_success(api.get_lot(lot["id"], OPERATOR), 200)
    assert fetched["quantity_reserved"] == 3
    assert fetched["quantity_available"] == 7
    assert fetched["quantity_on_hand"] == 10
    assert_lot_invariants(fetched)
