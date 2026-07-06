"""Read-time serializers that project computed fields onto stored entities.

We never persist computed fields; they are always re-derived on read so the
logical clock and the aggregate joins produce fresh answers.
"""
from util import iso_now, parse_iso
import db
from services import calculations as calc


# -------------------- Customer --------------------
def _customer_lifetime_cycles(customer_id):
    # Count DELIVERED shipments across subscriptions owned by this customer.
    n = 0
    for s in db.shipments.values():
        if s.get("status") != "DELIVERED":
            continue
        sub = db.subscriptions.get(s["subscription_id"])
        if sub and sub.get("customer_id") == customer_id:
            n += 1
    return n


def _customer_wallet_credit(customer_id):
    total = 0
    for w in db.wallet_entries.values():
        if w.get("customer_id") == customer_id:
            total += int(w["amount_cents"])
    return total


def customer_view(c):
    lc = _customer_lifetime_cycles(c["id"])
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "email": c["email"],
        "full_name": c["full_name"],
        "default_zip": c.get("default_zip"),
        "status": c.get("status", "ACTIVE"),
        "lifetime_cycles": lc,
        "loyalty_tier": calc.loyalty_tier(lc),
        "wallet_credit_cents": _customer_wallet_credit(c["id"]),
    }


# -------------------- Plan --------------------
def plan_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "cadence": p["cadence"],
        "base_fee_cents": p["base_fee_cents"],
        "default_style": p.get("default_style", "ROUND"),
        "is_active": p.get("is_active", True),
    }


# -------------------- Subscription --------------------
def _subscription_renewal_price(sub):
    plan = db.plans.get(sub["plan_id"])
    if plan is None:
        return sub.get("renewal_price_cents", 0)
    return calc.renewal_price_cents(
        plan=plan,
        size=sub["size"],
        vase_addon=sub.get("vase_addon", False),
        discount_pct=sub.get("discount_pct", 0),
    )


def subscription_view(sub):
    return {
        "id": sub["id"],
        "created_at": sub["created_at"],
        "updated_at": sub["updated_at"],
        "version": sub["version"],
        "customer_id": sub["customer_id"],
        "plan_id": sub["plan_id"],
        "size": sub["size"],
        "style": sub.get("style", "ROUND"),
        "vase_addon": sub.get("vase_addon", False),
        "is_gift": sub.get("is_gift", False),
        "occasion": sub.get("occasion"),
        "gift_message": sub.get("gift_message"),
        "lifecycle_status": sub.get("lifecycle_status", "ACTIVE"),
        "billing_status": sub.get("billing_status", "CURRENT"),
        "current_cycle_index": sub.get("current_cycle_index", 1),
        "next_renewal_date": sub.get("next_renewal_date"),
        "discount_pct": float(sub.get("discount_pct", 0)),
        "renewal_price_cents": _subscription_renewal_price(sub),
        "cancel_reason": sub.get("cancel_reason"),
        "paused_until": sub.get("paused_until"),
        "start_date": sub.get("start_date"),
    }


# -------------------- Shipment --------------------
def shipment_view(sh):
    return {
        "id": sh["id"],
        "created_at": sh["created_at"],
        "updated_at": sh["updated_at"],
        "version": sh["version"],
        "subscription_id": sh["subscription_id"],
        "cycle_index": sh["cycle_index"],
        "scheduled_delivery_date": sh["scheduled_delivery_date"],
        "status": sh["status"],
        "occasion": sh.get("occasion"),
        "gift_message": sh.get("gift_message"),
        "substitution_applied": sh.get("substitution_applied", False),
        "route_id": sh.get("route_id"),
        "delivery_window_start": sh.get("delivery_window_start"),
        "delivery_window_end": sh.get("delivery_window_end"),
        "stem_cost_cents": sh.get("stem_cost_cents"),
    }


# -------------------- StemLot --------------------
def _lot_quantity_available(lot_id, quantity_total):
    reserved = 0
    for a in db.allocations.values():
        if a["lot_id"] != lot_id:
            continue
        if a["status"] in ("RESERVED", "COMMITTED"):
            reserved += int(a["quantity_reserved"])
    return int(quantity_total) - reserved


def stem_lot_view(lot):
    state, usable_until = calc.cold_chain_state(lot, db.now())
    return {
        "id": lot["id"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
        "variety": lot["variety"],
        "grade": lot["grade"],
        "quantity_total": lot["quantity_total"],
        "unit_cost_cents": lot["unit_cost_cents"],
        "sourced_at": lot["sourced_at"],
        "shelf_life_hours": lot["shelf_life_hours"],
        "quantity_available": _lot_quantity_available(lot["id"], lot["quantity_total"]),
        "usable_until": iso_now(usable_until),
        "cold_chain_state": state,
    }


# -------------------- StemAllocation --------------------
def allocation_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "shipment_id": a["shipment_id"],
        "lot_id": a["lot_id"],
        "quantity_reserved": a["quantity_reserved"],
        "hold_start": a["hold_start"],
        "hold_end": a["hold_end"],
        "status": a["status"],
        "reserved_value_cents": a.get("reserved_value_cents"),
        "committed_value_cents": a.get("committed_value_cents"),
    }


# -------------------- CarrierRoute --------------------
def route_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "zone": r["zone"],
        "service_date": r["service_date"],
    }


# -------------------- Charge --------------------
def charge_view(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "subscription_id": c["subscription_id"],
        "cycle_index": c["cycle_index"],
        "kind": c.get("kind", "RENEWAL"),
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "refunded_cents": c.get("refunded_cents", 0),
    }


# -------------------- WalletEntry --------------------
def wallet_entry_view(w):
    return {
        "id": w["id"],
        "created_at": w["created_at"],
        "customer_id": w["customer_id"],
        "amount_cents": w["amount_cents"],
        "reason": w["reason"],
        "related_charge_id": w.get("related_charge_id"),
    }


# -------------------- WinBackOffer --------------------
def winback_view(o):
    # Lazy EXPIRED transition on read.
    if o.get("status") == "OFFERED":
        exp = parse_iso(o["expires_at"])
        if db.now() > exp:
            o["status"] = "EXPIRED"
            # Not touching updated_at/version: the transition is observed lazily.
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "customer_id": o["customer_id"],
        "discount_pct": float(o["discount_pct"]),
        "expires_at": o["expires_at"],
        "status": o["status"],
    }


# -------------------- SubstitutionRule --------------------
def substitution_rule_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "from_variety": r["from_variety"],
        "to_variety": r["to_variety"],
        "allowed": r.get("allowed", True),
        "max_substitution_pct": float(r.get("max_substitution_pct", 0.5)),
        "quality_floor_grade": r.get("quality_floor_grade", "B"),
    }
