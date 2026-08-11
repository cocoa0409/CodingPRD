"""Invoice endpoints: drafting (with the full billing computation), issuing,
disputes, voiding, and the payment sub-collection."""
from flask import Blueprint, request

import errors
import services
from db import db
from middleware import (body_json, check_transition, f_date, f_enum, f_str,
                        require_owner, require_roles)
from response import list_response, ok_object
from services import (base_record, bump, ser_invoice, ser_payment)

bp = Blueprint("invoices", __name__)

INVOICE_TERMINAL = ("PAID", "VOID")
BILLING_READ_ROLES = ("OpsAdmin", "BillingAdmin", "CustomerSelf")


def _get_invoice(iid):
    inv = db.invoices.get(iid)
    if inv is None:
        raise errors.not_found("invoice not found")
    return inv


def compute_invoice_totals(customer, period_start, period_end):
    """Run the billing engine for [period_start, period_end)."""
    cid = customer["id"]
    subtotal_water = 0
    shortage_charge = 0
    for s in db.stops.values():
        if (s["customer_id"] != cid
                or s["stop_status"] not in ("DELIVERED", "PARTIAL")):
            continue
        route = db.routes.get(s["route_id"])
        if route is None:
            continue
        try:
            sd = services.parse_date(route["service_date"])
        except ValueError:
            continue
        if not (period_start <= sd < period_end):
            continue
        cfg = services.config_at(sd)
        rate = services.rate_for_tier(cfg, customer["pricing_tier"])
        subtotal_water += rate * s["actual_bottles_delivered"]
        if s["stop_status"] == "PARTIAL" and s["shortage_count"] > 0 and cfg:
            shortage_charge += (s["shortage_count"]
                                * cfg["bottle_shortage_fee_cents"])

    subtotal_addon = 0
    for a in db.addons.values():
        if a["customer_id"] != cid:
            continue
        if a["cadence"] == "RECURRING":
            if a["addon_status"] == "ACTIVE":
                subtotal_addon += a["quantity"] * a["unit_price_cents"]
        else:  # ONE_TIME: charged only in the period of its purchase
            if (a["addon_status"] != "CANCELLED"
                    and period_start <= a["created_at"].date() < period_end):
                subtotal_addon += a["quantity"] * a["unit_price_cents"]

    subtotal_rent = 0
    for r in db.rentals.values():
        if r["customer_id"] != cid:
            continue
        subtotal_rent += services.prorated_rent(r, period_start, period_end)
        services.refresh_accrued_rent(r)

    deposit_credit = services.deposit_refund_cents(cid, period_start,
                                                   period_end)
    # Returned cooler deposits become refundable on the next invoice.
    for r in db.rentals.values():
        if (r["customer_id"] == cid and r.get("returned_at") is not None
                and not r.get("deposit_consumed")):
            deposit_credit += r["deposit_cents"]
            r["deposit_consumed"] = True

    # Skip credits already APPLIED but not yet absorbed by an invoice.
    applied_credit = 0
    for sc in db.skip_credits.values():
        if (sc["customer_id"] == cid and sc["credit_status"] == "APPLIED"
                and sc.get("pending_consumption")):
            applied_credit += sc["credit_cents"]
            sc["pending_consumption"] = False

    total = (subtotal_water + subtotal_addon + subtotal_rent
             + shortage_charge - deposit_credit - applied_credit)
    return {
        "subtotal_water_cents": subtotal_water,
        "subtotal_addon_cents": subtotal_addon,
        "subtotal_rent_cents": subtotal_rent,
        "shortage_charge_cents": shortage_charge,
        "deposit_credit_cents": deposit_credit,
        "total_due_cents": total,
    }


@bp.post("/invoices")
@require_roles("BillingAdmin")
def create_invoice():
    d = body_json()
    customer_id = f_str(d, "customer_id")
    period_start = f_date(d, "billing_period_start")
    period_end = f_date(d, "billing_period_end")
    due_date = f_date(d, "due_date")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise errors.invalid_reference("customer_id does not resolve")
    if period_end <= period_start:
        raise errors.invalid_date_range(
            "billing_period_end must be strictly after billing_period_start")
    with db.lock:
        totals = compute_invoice_totals(customer, period_start, period_end)
        rec = base_record()
        rec.update({
            "customer_id": customer_id,
            "billing_period_start": d["billing_period_start"],
            "billing_period_end": d["billing_period_end"],
            "due_date": d["due_date"],
            "invoice_status": "DRAFT",
            "issued_at": None,
            "balance_due_cents": totals["total_due_cents"],
        })
        rec.update(totals)
        db.invoices[rec["id"]] = rec
    return ok_object(ser_invoice(rec), 201)


@bp.get("/invoices")
@require_roles("OpsAdmin", "BillingAdmin")
def list_invoices():
    items = list(db.invoices.values())
    customer_id = request.args.get("customer_id")
    if customer_id is not None:
        items = [i for i in items if i["customer_id"] == customer_id]
    status = request.args.get("invoice_status")
    if status is not None:
        items = [i for i in items if i["invoice_status"] == status]
    return list_response(items, ser_invoice)


@bp.get("/invoices/<iid>")
@require_roles(*BILLING_READ_ROLES)
def get_invoice(iid):
    inv = _get_invoice(iid)
    require_owner(inv["customer_id"])
    return ok_object(ser_invoice(inv))


@bp.post("/invoices/<iid>/issue")
@require_roles("BillingAdmin")
def issue_invoice(iid):
    inv = _get_invoice(iid)
    check_transition(inv, "invoice_status", ("DRAFT",), INVOICE_TERMINAL,
                     "Invoice")
    if inv["total_due_cents"] <= 0:
        raise errors.invalid_state("invoice total_due_cents must be positive")
    with db.lock:
        inv["invoice_status"] = "OPEN"
        inv["issued_at"] = services.now()
        bump(inv)
        # Automatic tier upgrade for the NEXT period, thresholds inclusive.
        customer = db.customers.get(inv["customer_id"])
        if customer is not None:
            ps = services.parse_date(inv["billing_period_start"])
            pe = services.parse_date(inv["billing_period_end"])
            bottles = 0
            for s in db.stops.values():
                if (s["customer_id"] != customer["id"]
                        or s["stop_status"] not in ("DELIVERED", "PARTIAL")):
                    continue
                route = db.routes.get(s["route_id"])
                if route is None:
                    continue
                sd = services.parse_date(route["service_date"])
                if ps <= sd < pe:
                    bottles += s["actual_bottles_delivered"]
            cfg = services.config_at(pe)
            if cfg is not None:
                if bottles >= cfg["gold_volume_threshold"]:
                    new_tier = "GOLD"
                elif bottles >= cfg["silver_volume_threshold"]:
                    new_tier = "SILVER"
                else:
                    new_tier = "STANDARD"
                if new_tier != customer["pricing_tier"]:
                    customer["pricing_tier"] = new_tier
                    bump(customer)
    return ok_object(ser_invoice(inv))


@bp.post("/invoices/<iid>/dispute")
@require_roles("CustomerSelf")
def dispute_invoice(iid):
    inv = _get_invoice(iid)
    check_transition(inv, "invoice_status", ("OPEN", "PARTIALLY_PAID"),
                     INVOICE_TERMINAL, "Invoice")
    require_owner(inv["customer_id"])
    with db.lock:
        inv["invoice_status"] = "DISPUTED"
        bump(inv)
    return ok_object(ser_invoice(inv))


@bp.post("/invoices/<iid>/resolve-dispute")
@require_roles("BillingAdmin")
def resolve_dispute(iid):
    inv = _get_invoice(iid)
    check_transition(inv, "invoice_status", ("DISPUTED",), INVOICE_TERMINAL,
                     "Invoice")
    d = body_json()
    outcome = f_enum(d, "outcome", {"RESTORE", "VOID"})
    with db.lock:
        if outcome == "RESTORE":
            inv["invoice_status"] = "OPEN"
        else:
            inv["invoice_status"] = "VOID"
            inv["balance_due_cents"] = 0
        bump(inv)
    return ok_object(ser_invoice(inv))


@bp.post("/invoices/<iid>/void")
@require_roles("BillingAdmin")
def void_invoice(iid):
    inv = _get_invoice(iid)
    check_transition(inv, "invoice_status", ("DRAFT",), INVOICE_TERMINAL,
                     "Invoice")
    with db.lock:
        inv["invoice_status"] = "VOID"
        inv["balance_due_cents"] = 0
        bump(inv)
    return ok_object(ser_invoice(inv))


@bp.get("/invoices/<iid>/payments")
@require_roles(*BILLING_READ_ROLES)
def list_invoice_payments(iid):
    inv = _get_invoice(iid)
    require_owner(inv["customer_id"])
    items = [p for p in db.payments.values() if p["invoice_id"] == iid]
    return list_response(items, ser_payment)
