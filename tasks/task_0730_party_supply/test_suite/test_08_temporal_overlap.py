"""Difficulty rule 8 — resource temporal-overlap conflicts across different
interval semantics.

Instance A: DeliverySlot half-open [start,end) per van_id.
Instance B: RentalContract aggregate-capacity overlap per sku_id.
"""
from test_helpers import (
    validate_success, validate_error, api_client, ApiErrorId,
    make_store_clerk_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_delivery_slot,
    setup_tableware_sku_with_stock, create_order, create_rental_contract,
)


# =====================================================================
# Instance A — delivery_slot_half_open_adjacent_permits
# =====================================================================

def test_delivery_slot_adjacent_endpoint_permitted():
    """PRD §3.3: "The system rejects a create request whose half-open
    interval [window_start, window_end) overlaps another slot's interval
    on the same van_id with ERR_DELIVERY_SLOT_CONFLICT; two slots that
    share only an endpoint (one ends exactly when the other starts) do
    not overlap."

    Design: Difficulty/resource_temporal_overlap/delivery_slot_half_open_adjacent_permits
    """
    set_clock("2026-06-15T09:00:00Z")
    slot_a = create_delivery_slot("2026-06-15T10:00:00Z",
                                    "2026-06-15T12:00:00Z", van_id="V1")
    # Adjacent slot [12:00, 14:00) starts exactly when slot A ends → allowed.
    resp = api_client.create_delivery_slot(
        {"window_start": "2026-06-15T12:00:00Z",
         "window_end": "2026-06-15T14:00:00Z",
         "van_id": "V1"},
        make_store_clerk_headers(),
    )
    slot_b = validate_success(resp, expected_status=201)
    assert slot_b["status"] == "AVAILABLE"
    assert slot_b["van_id"] == "V1"


def test_delivery_slot_true_overlap_rejects_with_conflict():
    """PRD §3.3: "The system rejects a create request whose half-open
    interval [window_start, window_end) overlaps another slot's interval
    on the same van_id with ERR_DELIVERY_SLOT_CONFLICT; two slots that
    share only an endpoint (one ends exactly when the other starts) do
    not overlap."

    Design: Difficulty/resource_temporal_overlap/delivery_slot_half_open_adjacent_permits
    """
    set_clock("2026-06-15T09:00:00Z")
    create_delivery_slot("2026-06-15T10:00:00Z",
                         "2026-06-15T12:00:00Z", van_id="V1")
    create_delivery_slot("2026-06-15T12:00:00Z",
                         "2026-06-15T14:00:00Z", van_id="V1")
    # A slot [11:30, 12:30) strictly overlaps slot A on same van.
    resp = api_client.create_delivery_slot(
        {"window_start": "2026-06-15T11:30:00Z",
         "window_end": "2026-06-15T12:30:00Z",
         "van_id": "V1"},
        make_store_clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_DELIVERY_SLOT_CONFLICT)


# =====================================================================
# Instance B — rental_contract_aggregate_capacity_overlap
# =====================================================================

def test_rental_aggregate_capacity_overlap_rejects():
    """PRD §3.6: "The contract's [rental_start, rental_end) interval is
    additionally checked against every other non-terminal contract on
    the same sku_id: if the aggregate concurrent reserved quantity — the
    sum of qty across contracts whose intervals overlap this one —
    would exceed the SKU's on_hand_qty, the create is rejected with
    ERR_RENTAL_OVERLAP_CAPACITY."

    Design: Difficulty/resource_temporal_overlap/rental_contract_aggregate_capacity_overlap
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=300, on_hand=8)
    order_a = create_order(cust["id"], channel="IN_STORE",
                            lines=[{"sku_id": plate["id"], "qty": 1}])
    create_rental_contract(
        order_a["id"], plate["id"], qty=6,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    order_b = create_order(cust["id"], channel="IN_STORE",
                            lines=[{"sku_id": plate["id"], "qty": 1}])
    # 6+3=9 > 8 → reject.
    resp = api_client.create_rental_contract(
        {"order_id": order_b["id"], "sku_id": plate["id"], "qty": 3,
         "rental_start": "2026-06-18T00:00:00Z",
         "rental_end": "2026-06-19T00:00:00Z"},
        make_store_clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_RENTAL_OVERLAP_CAPACITY)


def test_rental_non_overlapping_windows_permitted():
    """PRD §3.6: "The contract's [rental_start, rental_end) interval is
    additionally checked against every other non-terminal contract on
    the same sku_id: if the aggregate concurrent reserved quantity — the
    sum of qty across contracts whose intervals overlap this one —
    would exceed the SKU's on_hand_qty, the create is rejected with
    ERR_RENTAL_OVERLAP_CAPACITY."
    PRD §2.9: "Delivery slots and rental periods use half-open intervals
    [window_start, window_end) and [rental_start, rental_end), meaning
    that a slot or contract whose end coincides with the next slot's or
    contract's start does not overlap."

    Design: Difficulty/resource_temporal_overlap/rental_contract_aggregate_capacity_overlap
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    plate = setup_tableware_sku_with_stock(unit_price_cents=300, on_hand=8)
    order_a = create_order(cust["id"], channel="IN_STORE",
                            lines=[{"sku_id": plate["id"], "qty": 1}])
    create_rental_contract(
        order_a["id"], plate["id"], qty=8,
        rental_start="2026-06-16T00:00:00Z",
        rental_end="2026-06-20T00:00:00Z",
    )
    order_b = create_order(cust["id"], channel="IN_STORE",
                            lines=[{"sku_id": plate["id"], "qty": 1}])
    # Non-overlapping (starts exactly when A ends) → aggregate over
    # overlapping is 0 → allowed even at full capacity.
    resp = api_client.create_rental_contract(
        {"order_id": order_b["id"], "sku_id": plate["id"], "qty": 8,
         "rental_start": "2026-06-20T00:00:00Z",
         "rental_end": "2026-06-25T00:00:00Z"},
        make_store_clerk_headers(),
    )
    rc = validate_success(resp, expected_status=201)
    assert rc["qty"] == 8
    assert rc["status"] == "RESERVED"
