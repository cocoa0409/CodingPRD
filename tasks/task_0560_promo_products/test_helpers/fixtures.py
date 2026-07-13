"""Composite setup helpers.

Each helper builds its preconditions from scratch (the server DB is empty at the
start of every test) using only PRD-declared endpoints, and returns a mutable
`ctx` dict of ids and captured entities. Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion error.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import TEST_USERS, make_customer_headers
from .factories import (
    create_supplier_payload,
    create_product_payload,
    create_price_tier_payload,
    create_station_payload,
    create_customer_payload,
    create_order_payload,
    create_line_payload,
    create_art_proof_payload,
    create_purchase_order_payload,
    create_payment_payload,
    schedule_payload,
    complete_run_payload,
    qc_payload,
    receive_payload,
    clock_payload,
)
from .constants import (
    DEFAULT_IN_HANDS_ISO,
    DEFAULT_CLOCK_ISO,
    DEFAULT_INITIAL_CREDIT_CENTS,
    CANONICAL_DEPOSIT_CENTS,
)

DEFAULT_SCREENPRINT_TIERS = [
    ("SCREEN_PRINT", 48, 599),
    ("SCREEN_PRINT", 144, 499),
]


def _admin():
    return TEST_USERS["catalog_admin_headers"]


def _am():
    return TEST_USERS["account_manager_headers"]


def _pm():
    return TEST_USERS["production_manager_headers"]


def set_clock(iso=DEFAULT_CLOCK_ISO):
    """Set the deterministic logical clock."""
    get_success_data(api.set_clock(clock_payload(to_iso8601=iso), _admin()))


def seed_catalog(
    min_order_qty=48,
    tiers=None,
    blank_unit_cost_cents=150,
    concurrent_capacity_units=500,
    with_station=False,
):
    """Create supplier + product + its price tiers (+ optional station)."""
    if tiers is None:
        tiers = DEFAULT_SCREENPRINT_TIERS
    sup = get_success_data(api.create_supplier(
        create_supplier_payload(
            blank_unit_cost_cents=blank_unit_cost_cents,
            concurrent_capacity_units=concurrent_capacity_units,
        ), _admin()))
    prod = get_success_data(api.create_product(
        create_product_payload(sup["id"], min_order_qty=min_order_qty), _admin()))
    for method, min_quantity, unit_price_cents in tiers:
        get_success_data(api.create_price_tier(
            prod["id"],
            create_price_tier_payload(
                decoration_method=method,
                min_quantity=min_quantity,
                unit_price_cents=unit_price_cents,
            ),
            _admin()))
    ctx = {
        "supplier_id": sup["id"], "supplier": sup,
        "product_id": prod["id"], "product": prod,
    }
    if with_station:
        st = get_success_data(api.create_station(create_station_payload(), _admin()))
        ctx["station_id"] = st["id"]
        ctx["station"] = st
    return ctx


def setup_catalog_customer_order(
    min_order_qty=48,
    tiers=None,
    order_type="STANDARD",
    in_hands_date=DEFAULT_IN_HANDS_ISO,
    initial_credit_cents=DEFAULT_INITIAL_CREDIT_CENTS,
    with_station=False,
    set_clock_first=True,
    blank_unit_cost_cents=150,
    concurrent_capacity_units=500,
):
    """Clock + catalog + customer + a fresh DRAFT order (no lines yet)."""
    if set_clock_first:
        set_clock()
    ctx = seed_catalog(
        min_order_qty=min_order_qty, tiers=tiers,
        blank_unit_cost_cents=blank_unit_cost_cents,
        concurrent_capacity_units=concurrent_capacity_units,
        with_station=with_station,
    )
    cust = get_success_data(api.create_customer(
        create_customer_payload(initial_credit_cents=initial_credit_cents), _admin()))
    ch = make_customer_headers(cust["id"])
    order = get_success_data(api.create_order(
        create_order_payload(cust["id"], order_type=order_type, in_hands_date=in_hands_date), ch))
    ctx.update({
        "customer_id": cust["id"], "customer": cust, "cust_headers": ch,
        "order_id": order["id"], "order": order,
    })
    return ctx


def setup_draft_line(quantity=200, imprint_color_count=3, decoration_method="SCREEN_PRINT", **kw):
    """DRAFT order with one PENDING_ART line (default: SCREEN_PRINT qty 200, 3 colors)."""
    ctx = setup_catalog_customer_order(**kw)
    line = get_success_data(api.create_line(
        ctx["order_id"],
        create_line_payload(
            ctx["product_id"],
            decoration_method=decoration_method,
            quantity=quantity,
            imprint_color_count=imprint_color_count,
        ),
        ctx["cust_headers"]))
    ctx.update({"line_id": line["id"], "line": line, "line_version": line["version"]})
    return ctx


def setup_submitted_proof(**kw):
    """DRAFT order + line + one proof advanced to PENDING_APPROVAL."""
    ctx = setup_draft_line(**kw)
    proof = get_success_data(api.create_art_proof(
        ctx["line_id"],
        create_art_proof_payload(expected_order_line_version=ctx["line_version"]),
        _am()))
    get_success_data(api.submit_proof(proof["id"], _am()))
    ctx.update({"proof_id": proof["id"]})
    return ctx


def setup_approved_proof(**kw):
    """DRAFT order + line whose proof is APPROVED (line ART_READY)."""
    ctx = setup_submitted_proof(**kw)
    get_success_data(api.approve_proof(ctx["proof_id"], ctx["cust_headers"]))
    return ctx


def setup_quoted_order(**kw):
    """QUOTED order with APPROVED art. Returns ctx with refreshed order."""
    ctx = setup_approved_proof(**kw)
    get_success_data(api.quote_order(ctx["order_id"], _am()))
    ctx["order"] = get_success_data(api.get_order(ctx["order_id"], _am()))
    return ctx


def setup_quoted_order_no_art(**kw):
    """QUOTED order with a line but NO art proof (quoting does not require art)."""
    ctx = setup_draft_line(**kw)
    get_success_data(api.quote_order(ctx["order_id"], _am()))
    ctx["order"] = get_success_data(api.get_order(ctx["order_id"], _am()))
    return ctx


def setup_quoted_paid_unapproved_art(deposit_amount=CANONICAL_DEPOSIT_CENTS, **kw):
    """QUOTED order, deposit paid, but the line's proof is only PENDING_APPROVAL."""
    ctx = setup_submitted_proof(**kw)
    get_success_data(api.quote_order(ctx["order_id"], _am()))
    get_success_data(api.create_payment(
        ctx["order_id"], create_payment_payload(deposit_amount), ctx["cust_headers"]))
    ctx["order"] = get_success_data(api.get_order(ctx["order_id"], _am()))
    return ctx


def setup_deposit_paid_order(deposit_amount=CANONICAL_DEPOSIT_CENTS, **kw):
    """QUOTED order with the deposit paid (payment_status DEPOSIT_PAID), art APPROVED."""
    ctx = setup_quoted_order(**kw)
    get_success_data(api.create_payment(
        ctx["order_id"], create_payment_payload(deposit_amount), ctx["cust_headers"]))
    ctx["order"] = get_success_data(api.get_order(ctx["order_id"], _am()))
    return ctx


def setup_confirmed_order(deposit_amount=CANONICAL_DEPOSIT_CENTS, **kw):
    """CONFIRMED order (art approved, deposit paid, lead OK)."""
    ctx = setup_deposit_paid_order(deposit_amount=deposit_amount, **kw)
    get_success_data(api.confirm_order(ctx["order_id"], _am()))
    ctx["order"] = get_success_data(api.get_order(ctx["order_id"], _am()))
    return ctx


def setup_confirmed_with_po(
    ordered_blank_qty=210,
    production_start="2026-05-05T00:00:00Z",
    production_end="2026-05-08T00:00:00Z",
    deposit_amount=CANONICAL_DEPOSIT_CENTS,
    **kw,
):
    """CONFIRMED order + one DRAFT PurchaseOrder for the line."""
    ctx = setup_confirmed_order(deposit_amount=deposit_amount, **kw)
    po = get_success_data(api.create_purchase_order(
        create_purchase_order_payload(
            ctx["line_id"], ctx["supplier_id"],
            ordered_blank_qty=ordered_blank_qty,
            production_start=production_start,
            production_end=production_end,
        ),
        _am()))
    ctx.update({"po_id": po["id"], "po": po})
    return ctx


def setup_issued_po(ordered_blank_qty=210, **kw):
    """CONFIRMED order + one ISSUED PurchaseOrder (supplier reservation raised)."""
    ctx = setup_confirmed_with_po(ordered_blank_qty=ordered_blank_qty, **kw)
    get_success_data(api.issue_po(ctx["po_id"], _am()))
    return ctx


def setup_received_po(received_blank_qty=205, **kw):
    """CONFIRMED order + one RECEIVED PurchaseOrder."""
    ctx = setup_issued_po(**kw)
    get_success_data(api.receive_po(
        ctx["po_id"], receive_payload(received_blank_qty), _pm()))
    return ctx


def setup_in_production_received_po(**kw):
    """IN_PRODUCTION order (RECEIVED PO, station created), line still CONFIRMED."""
    kw.setdefault("with_station", True)
    ctx = setup_received_po(**kw)
    get_success_data(api.start_production(ctx["order_id"], _pm()))
    return ctx


def setup_in_production_issued_po(**kw):
    """IN_PRODUCTION order whose PurchaseOrder is only ISSUED (not received)."""
    kw.setdefault("with_station", True)
    ctx = setup_issued_po(**kw)
    get_success_data(api.start_production(ctx["order_id"], _pm()))
    return ctx


def setup_scheduled_line(
    scheduled_start="2026-05-10T09:00:00Z",
    scheduled_end="2026-05-10T12:00:00Z",
    **kw,
):
    """IN_PRODUCTION order with the line SCHEDULED on the station."""
    ctx = setup_in_production_received_po(**kw)
    get_success_data(api.schedule_line(
        ctx["line_id"],
        schedule_payload(ctx["station_id"], scheduled_start, scheduled_end),
        _pm()))
    return ctx


def setup_printing_line(**kw):
    """Line advanced to PRINTING."""
    ctx = setup_scheduled_line(**kw)
    get_success_data(api.start_print(ctx["line_id"], _pm()))
    return ctx


def setup_qc_hold_line(produced_qty=205, spoiled_qty=10, **kw):
    """Line advanced to QC_HOLD with the given run outcome."""
    ctx = setup_printing_line(**kw)
    get_success_data(api.complete_run(
        ctx["line_id"], complete_run_payload(produced_qty, spoiled_qty), _pm()))
    return ctx


def setup_completed_line(produced_qty=205, spoiled_qty=10, **kw):
    """Line advanced to COMPLETED via a passing QC (good qty within tolerance)."""
    ctx = setup_qc_hold_line(produced_qty=produced_qty, spoiled_qty=spoiled_qty, **kw)
    get_success_data(api.qc_line(ctx["line_id"], qc_payload("PASS"), _pm()))
    return ctx


# --------------------------------------------------------------------------
# Dedicated multi-line scenarios (station double-booking / supplier capacity)
# --------------------------------------------------------------------------

def _seed_two_line_confirmed(with_station):
    """Two-line CONFIRMED order: line1 SCREEN_PRINT qty 200 3-color, line2 qty 100 1-color.
    Deposit 91850 paid (subtotal 121300 + 62400 = 183700, non-rush; deposit ceil(50%))."""
    set_clock()
    cat = seed_catalog(with_station=with_station)
    cust = get_success_data(api.create_customer(create_customer_payload(), _admin()))
    ch = make_customer_headers(cust["id"])
    order = get_success_data(api.create_order(create_order_payload(cust["id"]), ch))
    ctx = {
        **cat,
        "customer_id": cust["id"], "cust_headers": ch,
        "order_id": order["id"],
    }
    # line 1
    l1 = get_success_data(api.create_line(
        order["id"],
        create_line_payload(cat["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=200, imprint_color_count=3),
        ch))
    p1 = get_success_data(api.create_art_proof(
        l1["id"], create_art_proof_payload(expected_order_line_version=l1["version"]), _am()))
    get_success_data(api.submit_proof(p1["id"], _am()))
    get_success_data(api.approve_proof(p1["id"], ch))
    # line 2
    l2 = get_success_data(api.create_line(
        order["id"],
        create_line_payload(cat["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=100, imprint_color_count=1),
        ch))
    p2 = get_success_data(api.create_art_proof(
        l2["id"], create_art_proof_payload(expected_order_line_version=l2["version"]), _am()))
    get_success_data(api.submit_proof(p2["id"], _am()))
    get_success_data(api.approve_proof(p2["id"], ch))
    # quote / pay / confirm
    get_success_data(api.quote_order(order["id"], _am()))
    get_success_data(api.create_payment(order["id"], create_payment_payload(91850), ch))
    get_success_data(api.confirm_order(order["id"], _am()))
    ctx.update({"line1_id": l1["id"], "line2_id": l2["id"]})
    return ctx


def setup_station_double_book():
    """IN_PRODUCTION 2-line order; both lines RECEIVED-sourced; line1 SCHEDULED on the
    station for [09:00,12:00). Returns ctx with line2_id (still CONFIRMED) for the
    overlapping-schedule trigger."""
    ctx = _seed_two_line_confirmed(with_station=True)
    sup, st = ctx["supplier_id"], ctx["station_id"]
    # PO for line1 -> received
    po1 = get_success_data(api.create_purchase_order(
        create_purchase_order_payload(ctx["line1_id"], sup, ordered_blank_qty=210), _am()))
    get_success_data(api.issue_po(po1["id"], _am()))
    get_success_data(api.receive_po(po1["id"], receive_payload(205), _pm()))
    # PO for line2 -> received
    po2 = get_success_data(api.create_purchase_order(
        create_purchase_order_payload(ctx["line2_id"], sup, ordered_blank_qty=105), _am()))
    get_success_data(api.issue_po(po2["id"], _am()))
    get_success_data(api.receive_po(po2["id"], receive_payload(100), _pm()))
    # release + schedule line1
    get_success_data(api.start_production(ctx["order_id"], _pm()))
    get_success_data(api.schedule_line(
        ctx["line1_id"],
        schedule_payload(st, "2026-05-10T09:00:00Z", "2026-05-10T12:00:00Z"),
        _pm()))
    return ctx


def setup_rush_two_line_quoted():
    """QUOTED rush order (in_hands 2026-05-09, lead 8 < 10) with two 1-color lines:
    line A SCREEN_PRINT qty 48 (subtotal 31252) and line B SCREEN_PRINT qty 148
    (subtotal 76352). No art needed for quoting. Returns ctx with the order_id."""
    set_clock()
    cat = seed_catalog()
    cust = get_success_data(api.create_customer(create_customer_payload(), _admin()))
    ch = make_customer_headers(cust["id"])
    order = get_success_data(api.create_order(
        create_order_payload(cust["id"], in_hands_date="2026-05-09T00:00:00Z"), ch))
    get_success_data(api.create_line(
        order["id"],
        create_line_payload(cat["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=48, imprint_color_count=1),
        ch))
    get_success_data(api.create_line(
        order["id"],
        create_line_payload(cat["product_id"], decoration_method="SCREEN_PRINT",
                            quantity=148, imprint_color_count=1),
        ch))
    get_success_data(api.quote_order(order["id"], _am()))
    ctx = {**cat, "customer_id": cust["id"], "cust_headers": ch, "order_id": order["id"]}
    return ctx


def setup_supplier_capacity_near_limit():
    """CONFIRMED 2-line order; PO1 (ordered 300, window [05-01,05-05)) ISSUED on a
    capacity-500 supplier; PO2 (ordered 250, window [05-03,05-07)) still DRAFT.
    Returns ctx with po2_id for the capacity-exceeding issue trigger."""
    ctx = _seed_two_line_confirmed(with_station=False)
    sup = ctx["supplier_id"]
    po1 = get_success_data(api.create_purchase_order(
        create_purchase_order_payload(
            ctx["line1_id"], sup, ordered_blank_qty=300,
            production_start="2026-05-01T00:00:00Z",
            production_end="2026-05-05T00:00:00Z"),
        _am()))
    get_success_data(api.issue_po(po1["id"], _am()))
    po2 = get_success_data(api.create_purchase_order(
        create_purchase_order_payload(
            ctx["line2_id"], sup, ordered_blank_qty=250,
            production_start="2026-05-03T00:00:00Z",
            production_end="2026-05-07T00:00:00Z"),
        _am()))
    ctx.update({"po1_id": po1["id"], "po2_id": po2["id"]})
    return ctx
