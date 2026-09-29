"""Sample logistics, reconciliation, sales lift, invoicing and credits."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain as dm
import validation as v
from envelope import ok, ok_array, paginate
from errors import fail
from store import by_seq, db, iso_now, new_row, touch

bp = Blueprint("money", __name__)

INVOICE_ACTIONS = ("ISSUE", "VOID", "REDRAFT", "RECORD_PAYMENT")

INVOICE_FROM_STATES = {
    "ISSUE": ("DRAFT",),
    "VOID": ("ISSUED",),
    "REDRAFT": ("VOID",),
    "RECORD_PAYMENT": ("ISSUED",),
}

MANUFACTURER_MIRRORS = (
    "outstanding_balance_cents",
    "credit_note_balance_cents",
    "account_status",
)


def _refresh_manufacturer(man):
    """Recompute the manufacturer mirrors, bumping the row only when it moved."""
    if man is None:
        return
    before = tuple(man[field] for field in MANUFACTURER_MIRRORS)
    dm.recompute_manufacturer_rollup(man)
    if tuple(man[field] for field in MANUFACTURER_MIRRORS) != before:
        touch(man)


# ===========================================================================
# SampleShipment
# ===========================================================================
@bp.post("/demo-events/<eid>/sample-shipments")
def create_shipment(eid):
    caller = v.guard(("ProgramAdmin", "Manufacturer"))
    body = v.json_body()
    cases_shipped = v.req_int(body, "cases_shipped", minimum=1, maximum=40)
    carrier_reference = v.opt_string(body, "carrier_reference")
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    v.check_ownership(caller, manufacturer_id=event["manufacturer_id"])

    row = new_row(
        demo_event_id=event["id"],
        cases_shipped=cases_shipped,
        carrier_reference=carrier_reference,
        shipped_at=iso_now(),
        cases_received=None,
        received_at=None,
        short_cases=0,
        shipment_status="IN_TRANSIT",
    )
    db.shipments[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/demo-events/<eid>/sample-shipments")
def list_shipments(eid):
    v.guard(("ProgramAdmin", "ClubOperations", "Manufacturer"))
    limit, offset = v.pagination()
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    rows = dm.event_shipments(event["id"])
    status = v.query_enum("shipment_status", calc.SHIPMENT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["shipment_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.post("/sample-shipments/<sid>/receive")
def receive_shipment(sid):
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    cases_received = v.req_int(body, "cases_received", minimum=0)
    shipment = dm.resolve(db.shipments, sid, "ERR_RESOURCE_NOT_FOUND")
    event = db.demo_events.get(shipment["demo_event_id"])
    v.check_ownership(caller, club_id=event["club_id"] if event else None)

    if shipment["shipment_status"] != "IN_TRANSIT":
        fail("ERR_INVALID_STATE", "the shipment has already been received.")
    if event is None or event["booking_status"] not in calc.LIVE_BOOKING_STATUSES:
        fail("ERR_INVALID_STATE", "the event booking is not live.")
    if cases_received > shipment["cases_shipped"]:
        fail("ERR_RECEIVED_EXCEEDS_SHIPPED", "cases_received exceeds cases_shipped.")

    shipment["cases_received"] = cases_received
    shipment["received_at"] = iso_now()
    shipment["short_cases"] = max(0, shipment["cases_shipped"] - cases_received)
    if cases_received == shipment["cases_shipped"]:
        shipment["shipment_status"] = "DELIVERED"
    elif cases_received == 0:
        shipment["shipment_status"] = "REJECTED"
    else:
        shipment["shipment_status"] = "SHORT"
    touch(shipment)

    if shipment["shipment_status"] == "SHORT":
        event["allocated_sample_cases"] = dm.received_cases(event["id"])
        dm.sync_required_support(event)
        dm.recompute_coverage(event)
        touch(event)
        if event["event_type"] == "FOOD_SAMPLING":
            dm.create_cancellation_credit(event, "PRODUCT_SHORT")

    return ok(dm.pub(shipment))


# ===========================================================================
# SampleReconciliation
# ===========================================================================
@bp.post("/demo-events/<eid>/sample-reconciliation")
def create_reconciliation(eid):
    caller = v.guard(("ProgramAdmin", "ClubOperations"))
    body = v.json_body()
    units_sampled = v.req_int(body, "units_sampled", minimum=0)
    units_wasted = v.req_int(body, "units_wasted", minimum=0)
    units_returned = v.req_int(body, "units_returned", minimum=0)
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    v.check_ownership(caller, club_id=event["club_id"])

    if event["booking_status"] != "COMPLETED":
        fail("ERR_EVENT_NOT_COMPLETED", "the event is not COMPLETED.")
    if dm.event_reconciliation(event["id"]) is not None:
        fail("ERR_DUPLICATE_RESOURCE", "this event is already reconciled.")

    product = db.products[event["product_id"]]
    figures = dm.reconciliation_figures(
        event, product, units_sampled, units_wasted, units_returned
    )
    row = new_row(demo_event_id=event["id"], **figures)
    db.reconciliations[row["id"]] = row
    return ok(dm.pub(row), 201)


@bp.get("/demo-events/<eid>/sample-reconciliation")
def get_reconciliation(eid):
    v.guard(("ProgramAdmin", "ClubOperations", "Manufacturer"))
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    row = dm.event_reconciliation(event["id"])
    rows = [] if row is None else [dm.pub(row)]
    return ok_array(rows, 10, 0, len(rows))


@bp.post("/sample-reconciliations/<rid>/write-off")
def write_off_reconciliation(rid):
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    v.opt_string(body, "note")
    recon = dm.resolve(db.reconciliations, rid, "ERR_RESOURCE_NOT_FOUND")
    if recon["recon_status"] != "VARIANCE_FLAGGED":
        fail("ERR_INVALID_STATE", "only a VARIANCE_FLAGGED reconciliation may be written off.")

    event = db.demo_events.get(recon["demo_event_id"])
    product = db.products.get(event["product_id"]) if event is not None else None
    unit_cost = product["unit_cost_cents"] if product is not None else 0
    recon["write_off_cost_cents"] = calc.cents(
        Decimal(abs(recon["variance_units"])) * Decimal(unit_cost)
    )
    recon["recon_status"] = "WRITTEN_OFF"
    touch(recon)
    return ok(dm.pub(recon))


# ===========================================================================
# SalesLiftMeasurement
# ===========================================================================
@bp.post("/demo-events/<eid>/lift-measurements")
def create_measurement(eid):
    caller = v.guard(("ProgramAdmin", "Manufacturer"))
    body = v.json_body()
    variant = v.req_enum(body, "measurement_variant", calc.MEASUREMENT_VARIANTS)
    units_sold = v.req_int(body, "units_sold_in_window", minimum=0)
    expected = v.req_int(body, "expected_demo_event_version", minimum=1)
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    v.check_ownership(caller, manufacturer_id=event["manufacturer_id"])

    if expected != event["version"]:
        fail("ERR_STALE_EVENT_VERSION", "the demo event has moved on since it was read.")

    baseline = dm.baseline_for(event["club_id"], event["product_id"])
    if baseline is None:
        fail("ERR_BASELINE_MISSING", "no baseline exists for this club and product.")

    recon = dm.event_reconciliation(event["id"])
    if variant == "FINAL" and recon is None:
        fail("ERR_RECONCILIATION_UNRESOLVED", "a FINAL measurement needs a reconciliation.")

    for earlier in dm.event_measurements(event["id"]):
        if earlier["measurement_variant"] != variant:
            continue
        if earlier["measurement_status"] in ("POSTED", "STALE"):
            earlier["measurement_status"] = "SUPERSEDED"

    row = dm.build_measurement(event, variant, units_sold, baseline, recon)
    touch(event)
    return ok(dm.pub(row), 201)


@bp.get("/demo-events/<eid>/lift-measurements")
def list_measurements(eid):
    v.guard(("ProgramAdmin", "Manufacturer", "ClubOperations"))
    limit, offset = v.pagination()
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")
    rows = list(reversed(dm.event_measurements(event["id"])))
    variant = v.query_enum("measurement_variant", calc.MEASUREMENT_VARIANTS)
    if variant is not None:
        rows = [r for r in rows if r["measurement_variant"] == variant]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


# ===========================================================================
# EventInvoice
# ===========================================================================
@bp.post("/demo-events/<eid>/invoice")
def create_invoice(eid):
    v.guard(("ProgramAdmin",))
    body = v.json_body()
    expected = v.req_int(body, "expected_demo_event_version", minimum=1)
    event = dm.resolve(db.demo_events, eid, "ERR_DEMO_EVENT_NOT_FOUND")

    if event["booking_status"] != "COMPLETED":
        fail("ERR_EVENT_NOT_COMPLETED", "the event is not COMPLETED.")
    if dm.live_invoice(event["id"]) is not None:
        fail("ERR_INVOICE_ALREADY_EXISTS", "a live invoice already exists for this event.")
    if expected != event["version"]:
        fail("ERR_STALE_EVENT_VERSION", "the demo event has moved on since it was read.")

    man = db.manufacturers[event["manufacturer_id"]]
    row = new_row(
        demo_event_id=event["id"],
        manufacturer_id=man["id"],
        base_fee_cents=0,
        addon_fee_cents=0,
        staffing_fee_cents=0,
        sample_handling_fee_cents=0,
        line_items=[],
        subtotal_cents=0,
        monthly_completed_event_count=0,
        volume_discount_pct=0.00,
        discount_cents=0,
        credit_applied_cents=0,
        total_due_cents=0,
        credit_terms_days=man["credit_terms_days"],
        invoice_status="DRAFT",
        issued_by_user_id=None,
        issued_at=None,
        paid_at=None,
    )
    dm.apply_invoice_figures(row, event)
    db.invoices[row["id"]] = row
    touch(event)
    return ok(dm.pub(row), 201)


@bp.get("/event-invoices/<iid>")
def get_invoice(iid):
    v.guard(("ProgramAdmin", "Manufacturer"))
    row = dm.resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/event-invoices")
def list_invoices():
    v.guard(("ProgramAdmin", "Manufacturer"))
    limit, offset = v.pagination()
    rows = by_seq(list(db.invoices.values()))
    for field in ("demo_event_id", "manufacturer_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = v.query_enum("invoice_status", calc.INVOICE_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["invoice_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.post("/event-invoices/<iid>/transitions")
def transition_invoice(iid):
    caller = v.guard(("ProgramAdmin",))
    body = v.json_body()
    action = v.req_enum(body, "action", INVOICE_ACTIONS)
    amount_cents = None
    if action == "RECORD_PAYMENT":
        amount_cents = v.req_int(body, "amount_cents", minimum=0)
    else:
        v.opt_int(body, "amount_cents", minimum=0)

    invoice = dm.resolve(db.invoices, iid, "ERR_INVOICE_NOT_FOUND")
    state = invoice["invoice_status"]
    if state not in INVOICE_FROM_STATES[action]:
        fail("ERR_INVALID_STATE", "%s is not legal from invoice_status %s." % (action, state))

    event = db.demo_events.get(invoice["demo_event_id"])
    man = db.manufacturers.get(invoice["manufacturer_id"])

    if action == "ISSUE":
        if event is None or event["booking_status"] != "COMPLETED":
            fail("ERR_INVALID_STATE", "the event is not COMPLETED.")

    if man is not None and man["account_status"] == "SUSPENDED":
        fail("ERR_MANUFACTURER_SUSPENDED", "the manufacturer account is suspended.")

    if action == "ISSUE":
        recon = dm.event_reconciliation(invoice["demo_event_id"])
        if recon is None or recon["recon_status"] not in ("BALANCED", "WRITTEN_OFF"):
            fail("ERR_RECONCILIATION_UNRESOLVED", "the reconciliation is unresolved.")

    if action == "RECORD_PAYMENT":
        if amount_cents != invoice["total_due_cents"]:
            fail("ERR_PAYMENT_AMOUNT_MISMATCH", "amount_cents must equal total_due_cents.")

    if action == "ISSUE":
        invoice["invoice_status"] = "ISSUED"
        invoice["issued_by_user_id"] = caller.user_id
        invoice["issued_at"] = iso_now()
        touch(invoice)
        _refresh_manufacturer(man)
        if event is not None:
            dm.recompute_settlement(event)
            touch(event)

    elif action == "VOID":
        invoice["invoice_status"] = "VOID"
        invoice["issued_by_user_id"] = None
        invoice["issued_at"] = None
        touch(invoice)
        _refresh_manufacturer(man)
        if event is not None:
            dm.recompute_settlement(event)
            touch(event)

    elif action == "REDRAFT":
        invoice["invoice_status"] = "DRAFT"
        if event is not None:
            dm.apply_invoice_figures(invoice, event)
        touch(invoice)

    else:  # RECORD_PAYMENT
        invoice["invoice_status"] = "PAID"
        invoice["paid_at"] = iso_now()
        touch(invoice)
        _refresh_manufacturer(man)
        if event is not None:
            dm.recompute_settlement(event)
            touch(event)

    return ok(dm.pub(invoice))


# ===========================================================================
# CancellationCredit
# ===========================================================================
@bp.get("/cancellation-credits/<cid>")
def get_credit(cid):
    v.guard(("ProgramAdmin", "Manufacturer"))
    row = dm.resolve(db.credits, cid, "ERR_RESOURCE_NOT_FOUND")
    return ok(dm.pub(row))


@bp.get("/cancellation-credits")
def list_credits():
    v.guard(("ProgramAdmin", "Manufacturer", "ClubOperations"))
    limit, offset = v.pagination()
    rows = by_seq(list(db.credits.values()))
    for field in ("demo_event_id", "manufacturer_id", "applied_to_invoice_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = v.query_enum("credit_status", calc.CREDIT_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["credit_status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_array([dm.pub(r) for r in page], limit, offset, total)


@bp.post("/cancellation-credits/<cid>/decisions")
def decide_credit(cid):
    caller = v.guard(("ProgramAdmin",))
    body = v.json_body()
    decision = v.req_enum(body, "decision", ("APPROVE", "REJECT"))
    v.opt_string(body, "note")
    credit = dm.resolve(db.credits, cid, "ERR_RESOURCE_NOT_FOUND")

    if credit["credit_status"] != "PENDING_APPROVAL":
        fail("ERR_INVALID_STATE", "this credit has already been decided.")

    event = db.demo_events.get(credit["demo_event_id"])
    invoices = dm.event_invoices(credit["demo_event_id"])

    if decision == "APPROVE":
        for inv in invoices:
            if inv["invoice_status"] in ("ISSUED", "PAID"):
                if inv["issued_by_user_id"] == caller.user_id:
                    fail(
                        "ERR_SEGREGATION_OF_DUTIES",
                        "the issuer of an invoice may not approve its credit.",
                    )

    credit["approved_by_user_id"] = caller.user_id

    if decision == "REJECT":
        credit["credit_status"] = "REJECTED"
        touch(credit)
        return ok(dm.pub(credit))

    target = None
    for inv in invoices:
        if inv["invoice_status"] in ("DRAFT", "ISSUED"):
            target = inv
            break

    credit["credit_status"] = "APPLIED"
    if target is not None:
        credit["applied_to_invoice_id"] = target["id"]
        target["credit_applied_cents"] += credit["credit_amount_cents"]
        dm.recompute_total_due(target)
        touch(target)
    touch(credit)

    _refresh_manufacturer(db.manufacturers.get(credit["manufacturer_id"]))
    if event is not None:
        dm.recompute_settlement(event)
        touch(event)

    return ok(dm.pub(credit))
