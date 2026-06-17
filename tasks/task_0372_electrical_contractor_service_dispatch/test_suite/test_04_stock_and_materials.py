"""Truck-stock balance: debit-on-usage, restore-on-void, and the stock floor.

Queue A (Difficulty): boundary_precision (stock), compensating_invariant (stock units).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS, make_technician_headers,
    make_customer, make_technician, make_sku, stock_truck, make_job,
    quote_and_accept, dispatch_tech, depart_and_arrive, record_usage,
)

DISP = TEST_USERS["dispatcher_headers"]


def _onsite_outlet_job(zone, email, sku_overrides=None, stock_qty=10, stock_threshold=0):
    cust = make_customer(email=email, service_zip=zone + "01")
    tech = make_technician(service_zone=zone, license_class="JOURNEYMAN", hourly_rate_cents=10000)
    sku = make_sku(**(sku_overrides or {"unit_price_cents": 1000, "taxable": True}))
    stock = stock_truck(tech["id"], sku["id"], quantity_on_hand=stock_qty, reorder_threshold=stock_threshold)
    job = make_job(cust["id"], scope="OUTLET", job_class="SERVICE")
    quote_and_accept(job["id"], cust["id"], pricing_mode="FLAT_RATE", flat_rate_cents=10000)
    disp = dispatch_tech(job["id"], tech["id"], "2026-07-30T09:00:00Z", "2026-07-30T10:00:00Z")
    depart_and_arrive(disp["id"], tech["id"])
    return cust, tech, sku, stock, job


# ─── Queue A: boundary_precision (stock) ──────────────────────────────────
def test_stock_exact_quantity_succeeds_plus_one_rejected(api):
    """PRD §3.2: "The boundary is inclusive on the side of success — a usage of exactly the
    current `quantity_on_hand` succeeds and leaves the balance at zero, while a usage of one
    unit more than the on-hand amount is rejected."
    PRD §3.5: "Each line's `line_total_cents` is computed at the moment of recording as the
    `quantity` multiplied by that SKU's `unit_price_cents` at usage time."

    Design: Difficulty/boundary_precision_check/boundary_stock_exact_quantity_succeeds_plus_one_rejected
    """
    cust, tech, sku, stock, job = _onsite_outlet_job(
        "700", "bp1@x.com", sku_overrides={"unit_price_cents": 1000, "taxable": True}, stock_qty=5
    )
    th = make_technician_headers(tech["id"])
    # exactly quantity_on_hand (5) succeeds, leaves 0.
    usage = validate_success(api.create_material_usage(
        {"job_id": job["id"], "technician_id": tech["id"], "sku_id": sku["id"], "quantity": 5}, th), 201)
    assert usage["line_total_cents"] == 5000
    after = validate_success(api.get_truck_stock_item(stock["id"], DISP), 200)
    assert after["quantity_on_hand"] == 0
    # one more than remaining (0) is rejected.
    resp = api.create_material_usage(
        {"job_id": job["id"], "technician_id": tech["id"], "sku_id": sku["id"], "quantity": 1}, th)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


def test_stock_usage_one_over_initial_rejected(api):
    """PRD §3.2: "The on-hand balance may never go negative: a usage whose `quantity`
    exceeds the current `quantity_on_hand` is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/boundary_precision_check/boundary_stock_exact_quantity_succeeds_plus_one_rejected
    """
    cust, tech, sku, stock, job = _onsite_outlet_job(
        "701", "bp1b@x.com", sku_overrides={"unit_price_cents": 1000, "taxable": True}, stock_qty=5
    )
    th = make_technician_headers(tech["id"])
    resp = api.create_material_usage(
        {"job_id": job["id"], "technician_id": tech["id"], "sku_id": sku["id"], "quantity": 6}, th)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)
    # nothing was debited
    after = validate_success(api.get_truck_stock_item(stock["id"], DISP), 200)
    assert after["quantity_on_hand"] == 5


# ─── Queue A: compensating_invariant (stock units conserved) ──────────────
def test_usage_then_void_conserves_truck_stock(api):
    """PRD §3.5: "voiding a line sets `voided` to true, restores the truck stock, and
    excludes the line from any future invoice."
    PRD §3.2: "When a usage is voided, the previously consumed `quantity` is added back to
    the same truck-stock item's `quantity_on_hand` and `low_stock` is recomputed once more."

    Design: Difficulty/compensating_invariant/invariant_usage_then_void_conserves_truck_stock
    """
    cust, tech, sku, stock, job = _onsite_outlet_job(
        "900", "ci1@x.com", sku_overrides={"unit_price_cents": 1000, "taxable": True},
        stock_qty=10, stock_threshold=2,
    )
    th = make_technician_headers(tech["id"])
    usage = record_usage(job["id"], tech["id"], sku["id"], 3)
    after_use = validate_success(api.get_truck_stock_item(stock["id"], DISP), 200)
    assert after_use["quantity_on_hand"] == 7

    voided = validate_success(api.void_material_usage(usage["id"], th), 200)
    assert voided["voided"] is True
    after_void = validate_success(api.get_truck_stock_item(stock["id"], DISP), 200)
    assert after_void["quantity_on_hand"] == 10  # restored to pre-usage value
    assert after_void["low_stock"] is False       # 10 > reorder_threshold 2


def test_void_restores_stock_to_allow_full_reuse(api):
    """PRD §3.2: "When a usage is voided, the previously consumed `quantity` is added back to
    the same truck-stock item's `quantity_on_hand` and `low_stock` is recomputed once more."
    PRD §3.2: "The on-hand balance may never go negative: a usage whose `quantity` exceeds
    the current `quantity_on_hand` is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/compensating_invariant/invariant_usage_then_void_conserves_truck_stock
    """
    cust, tech, sku, stock, job = _onsite_outlet_job(
        "901", "ci1b@x.com", sku_overrides={"unit_price_cents": 1000, "taxable": True}, stock_qty=5
    )
    th = make_technician_headers(tech["id"])
    usage = record_usage(job["id"], tech["id"], sku["id"], 5)  # drains to 0
    void = validate_success(api.void_material_usage(usage["id"], th), 200)
    assert void["voided"] is True
    # after the credit, the full 5 units are available again: a fresh 5-unit usage succeeds.
    reuse = validate_success(api.create_material_usage(
        {"job_id": job["id"], "technician_id": tech["id"], "sku_id": sku["id"], "quantity": 5}, th), 201)
    assert reuse["line_total_cents"] == 5000
    final = validate_success(api.get_truck_stock_item(stock["id"], DISP), 200)
    assert final["quantity_on_hand"] == 0
