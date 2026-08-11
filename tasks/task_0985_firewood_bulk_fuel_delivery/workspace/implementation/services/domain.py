"""Domain helpers: area restrictions, wallet clamping, window/day-before-cutoff,
season sweep, and serialization."""

from datetime import date, datetime, timedelta, timezone

import errors
from clock import clock
from db import db
from util import dec, now_iso


# ---------------------------------------------------------------------------
# Area restrictions (PRD §3.2)
# ---------------------------------------------------------------------------

def _window_covers(start_md, end_md, target_md):
    """MM-DD window coverage, inclusive both ends, may wrap year end."""
    def tup(s):
        return (int(s[0:2]), int(s[3:5]))
    s, e, t = tup(start_md), tup(end_md), tup(target_md)
    if s <= e:
        return s <= t <= e
    # wraps year end
    return t >= s or t <= e


def check_area_restrictions(delivery_postal_code, requested_delivery_date, product):
    """Raise ERR_AREA_RESTRICTED if any ACTIVE restriction covering the postal
    code and date bans this product's kind or species."""
    target_md = requested_delivery_date[5:10]  # MM-DD
    for r in db.area_restrictions.values():
        if not r.get("active", True):
            continue
        if delivery_postal_code not in r.get("postal_codes", []):
            continue
        if not _window_covers(r["enforcement_window_start"], r["enforcement_window_end"], target_md):
            continue
        if product["product_kind"] in r.get("restricted_kinds", []):
            raise errors.area_restricted(
                f"product_kind {product['product_kind']} restricted in {delivery_postal_code}"
            )
        if product["species"] in r.get("restricted_species", []):
            raise errors.area_restricted(
                f"species {product['species']} restricted in {delivery_postal_code}"
            )


# ---------------------------------------------------------------------------
# Wallet clamping (PRD §3.1): credit_balance_cents never negative; overflow of
# debits carries into outstanding_refund_cents; refunds absorb outstanding first.
# ---------------------------------------------------------------------------

def credit_wallet(customer, amount_cents):
    """Add amount to credit. First absorb outstanding refund owed (reduce it),
    remainder goes into credit_balance. Never makes credit negative here."""
    amount = int(amount_cents)
    outstanding = customer.get("outstanding_refund_cents", 0)
    if outstanding > 0:
        absorb = min(outstanding, amount)
        customer["outstanding_refund_cents"] = outstanding - absorb
        amount -= absorb
    customer["credit_balance_cents"] = customer.get("credit_balance_cents", 0) + amount


def debit_wallet(customer, amount_cents):
    """Debit amount from credit; clamp at 0, overflow into outstanding_refund_cents
    (a debit standing against future refunds)."""
    amount = int(amount_cents)
    credit = customer.get("credit_balance_cents", 0)
    if credit >= amount:
        customer["credit_balance_cents"] = credit - amount
    else:
        shortfall = amount - credit
        customer["credit_balance_cents"] = 0
        customer["outstanding_refund_cents"] = customer.get("outstanding_refund_cents", 0) + shortfall


# ---------------------------------------------------------------------------
# Loyalty tier (PRD §3.1)
# ---------------------------------------------------------------------------

def recompute_loyalty_tier(customer):
    ce = dec(customer.get("lifetime_cord_equivalent_delivered", 0))
    if ce >= dec("10"):
        customer["loyalty_tier"] = "GOLD"
    elif ce >= dec("4"):
        customer["loyalty_tier"] = "SILVER"
    else:
        customer["loyalty_tier"] = "STANDARD"


# ---------------------------------------------------------------------------
# Temporal helpers
# ---------------------------------------------------------------------------

def day_before_cutoff(window):
    """18:00 local (we treat logical clock as UTC) on the day before service_date."""
    d = date(
        int(window["service_date"][0:4]),
        int(window["service_date"][5:7]),
        int(window["service_date"][8:10]),
    )
    prev = d - timedelta(days=1)
    return datetime(prev.year, prev.month, prev.day, 18, 0, 0, tzinfo=timezone.utc)


def service_datetime(window):
    d = date(
        int(window["service_date"][0:4]),
        int(window["service_date"][5:7]),
        int(window["service_date"][8:10]),
    )
    return datetime(d.year, d.month, d.day, window["start_hour"], 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Season sweep (PRD §3.9)
# ---------------------------------------------------------------------------

def run_season_sweep(season_year):
    """Evaluate all ACTIVE subscriptions for the season; SHORTFALL/EXPIRED.
    Returns list of transitioned subscription ids."""
    from services import pricing  # late import to avoid cycle

    transitioned = []
    for sub in list(db.subscriptions.values()):
        if sub["season_year"] != season_year:
            continue
        if sub["status"] != "ACTIVE":
            continue
        delivered = dec(sub["delivered_cord_equivalent"])
        committed = dec(sub["commitment_cord_equivalent"])
        if delivered >= committed:
            sub["status"] = "EXPIRED"
            sub["closed_at"] = clock.now_iso()
            sub["updated_at"] = now_iso()
            sub["version"] += 1
            transitioned.append(sub["id"])
        else:
            penalty = pricing.compute_shortfall_penalty(sub)
            # Raise synthetic invoice: most recent delivered order, else standalone bound to customer
            target_order = None
            for order in db.orders.values():
                if order["customer_id"] != sub["customer_id"]:
                    continue
                if order["fulfillment_status"] != "DELIVERED":
                    continue
                if target_order is None or order["created_at"] > target_order["created_at"]:
                    target_order = order
            ts = now_iso()
            invoice = {
                "id": __import__("db").new_id(),
                "created_at": ts,
                "updated_at": ts,
                "version": 1,
                "order_id": target_order["id"] if target_order else None,
                "customer_id": sub["customer_id"],
                "invoice_number": pricing.next_invoice_number(season_year),
                "amount_cents": penalty,
                "paid_cents": 0,
                "refunded_cents": 0,
                "status": "OPEN",
                "due_date": clock.now_iso()[0:10],
                "issued_at": clock.now_iso(),
                "settled_at": None,
            }
            db.invoices[invoice["id"]] = invoice
            sub["status"] = "SHORTFALL"
            sub["closed_at"] = clock.now_iso()
            sub["updated_at"] = ts
            sub["version"] += 1
            transitioned.append(sub["id"])
    return transitioned


# ---------------------------------------------------------------------------
# Serializers — control exactly which fields appear in responses.
# ---------------------------------------------------------------------------

def serialize_customer(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "full_name": c["full_name"],
        "email": c["email"],
        "phone": c["phone"],
        "street_address": c["street_address"],
        "postal_code": c["postal_code"],
        "credit_balance_cents": c["credit_balance_cents"],
        "outstanding_refund_cents": c["outstanding_refund_cents"],
        "lifetime_cord_equivalent_delivered": c["lifetime_cord_equivalent_delivered"],
        "loyalty_tier": c["loyalty_tier"],
        "account_status": c["account_status"],
        "suspended_reason": c.get("suspended_reason"),
    }


def serialize_product(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "sku": p["sku"],
        "product_kind": p["product_kind"],
        "species": p["species"],
        "seasoned_grade": p["seasoned_grade"],
        "base_price_cents": p["base_price_cents"],
        "moisture_ceiling_pct": p["moisture_ceiling_pct"],
        "available_qty": p["available_qty"],
        "reserved_qty": p["reserved_qty"],
        "discontinued": p.get("discontinued", False),
    }


def serialize_area_restriction(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "name": r["name"],
        "postal_codes": r["postal_codes"],
        "restricted_kinds": r["restricted_kinds"],
        "restricted_species": r["restricted_species"],
        "enforcement_window_start": r["enforcement_window_start"],
        "enforcement_window_end": r["enforcement_window_end"],
        "active": r.get("active", True),
    }


def serialize_subscription(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "customer_id": s["customer_id"],
        "tier": s["tier"],
        "season_year": s["season_year"],
        "commitment_cord_equivalent": s["commitment_cord_equivalent"],
        "delivered_cord_equivalent": s["delivered_cord_equivalent"],
        "prepaid_cents": s["prepaid_cents"],
        "discount_pct": s["discount_pct"],
        "stacking_included": s["stacking_included"],
        "status": s["status"],
        "activated_at": s.get("activated_at"),
        "closed_at": s.get("closed_at"),
    }


def serialize_route(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "route_code": r["route_code"],
        "depot_name": r["depot_name"],
        "service_postal_prefixes": r["service_postal_prefixes"],
        "capacity_cord_equivalent": r["capacity_cord_equivalent"],
        "active": r.get("active", True),
    }


def serialize_window(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
        "route_id": w["route_id"],
        "service_date": w["service_date"],
        "start_hour": w["start_hour"],
        "end_hour": w["end_hour"],
        "capacity_cord_equivalent": w["capacity_cord_equivalent"],
        "committed_cord_equivalent": w["committed_cord_equivalent"],
        "status": w["status"],
    }


def serialize_order(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "customer_id": o["customer_id"],
        "subscription_id": o.get("subscription_id"),
        "delivery_window_id": o.get("delivery_window_id"),
        "delivery_street_address": o["delivery_street_address"],
        "delivery_postal_code": o["delivery_postal_code"],
        "requested_delivery_date": o["requested_delivery_date"],
        "payment_status": o["payment_status"],
        "fulfillment_status": o["fulfillment_status"],
        "stacking_addon": o.get("stacking_addon", False),
        "stacking_fee_cents": o["stacking_fee_cents"],
        "subtotal_cents": o["subtotal_cents"],
        "volume_discount_cents": o["volume_discount_cents"],
        "subscription_discount_cents": o["subscription_discount_cents"],
        "loyalty_discount_cents": o["loyalty_discount_cents"],
        "seasonal_surcharge_cents": o["seasonal_surcharge_cents"],
        "delivery_fee_cents": o["delivery_fee_cents"],
        "total_cents": o["total_cents"],
        "total_cord_equivalent": o["total_cord_equivalent"],
        "scheduled_at": o.get("scheduled_at"),
        "delivered_at": o.get("delivered_at"),
        "cancelled_reason": o.get("cancelled_reason"),
    }


def serialize_order_line(l):
    return {
        "id": l["id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
        "order_id": l["order_id"],
        "product_id": l["product_id"],
        "quantity": l["quantity"],
        "unit_price_cents": l["unit_price_cents"],
        "cord_equivalent_per_unit": l["cord_equivalent_per_unit"],
        "line_cord_equivalent": l["line_cord_equivalent"],
        "volume_tier_applied": l["volume_tier_applied"],
        "extended_price_cents": l["extended_price_cents"],
        "moisture_reading_id": l.get("moisture_reading_id"),
    }


def serialize_moisture_reading(m):
    # MoistureReading is append-only: id + created_at only (PRD §2.4)
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "order_line_id": m["order_line_id"],
        "recorded_by_user_id": m["recorded_by_user_id"],
        "moisture_pct": m["moisture_pct"],
        "reading_pass": m["reading_pass"],
        "recorded_at": m["recorded_at"],
    }


def serialize_invoice(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "order_id": i.get("order_id"),
        "invoice_number": i["invoice_number"],
        "amount_cents": i["amount_cents"],
        "paid_cents": i["paid_cents"],
        "refunded_cents": i["refunded_cents"],
        "status": i["status"],
        "due_date": i["due_date"],
        "issued_at": i["issued_at"],
        "settled_at": i.get("settled_at"),
    }


def serialize_payment_event(e):
    # PaymentEvent is append-only: id + created_at only (PRD §2.4)
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "invoice_id": e["invoice_id"],
        "event_kind": e["event_kind"],
        "amount_cents": e["amount_cents"],
        "external_ref": e["external_ref"],
    }
