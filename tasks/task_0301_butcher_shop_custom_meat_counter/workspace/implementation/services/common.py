"""Cross-cutting helpers: entity lookup with existence (404), active pricing
policy resolution, datetime parsing, and derived-field reconciliation
(PRD §2.5, §2.8).
"""
from datetime import datetime, timezone

import db
import errors


# --- Lookup with existence enforcement (PRD §2.5) ---

def get_or_404(collection, resource_id):
    record = collection.get(resource_id)
    if record is None:
        errors.fail(errors.ERR_NOT_FOUND, "Resource not found: %s" % resource_id)
    return record


def fk_or_404(collection, resource_id):
    """Same as get_or_404 but phrased as a foreign-key existence check."""
    record = collection.get(resource_id)
    if record is None:
        errors.fail(errors.ERR_NOT_FOUND, "Referenced resource not found: %s"
                    % resource_id)
    return record


# --- Active pricing policy ---

def active_policy_or_400():
    for p in db.pricing_policies.values():
        if p.get("is_active"):
            return p
    # No active policy configured. Pricing cannot proceed; treat as bad request.
    errors.fail(errors.ERR_INVALID_REQUEST, "No active pricing policy.")


# --- Datetime parsing (ISO 8601 UTC) ---

def parse_iso(value, field):
    if not isinstance(value, str):
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field %s must be an ISO 8601 string." % field)
    raw = value
    try:
        s = raw
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        errors.fail(errors.ERR_INVALID_REQUEST,
                    "Field %s is not a valid ISO 8601 timestamp." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# --- Derived-field reconciliation (PRD §2.8) ---

def reconcile_lot_remaining(lot):
    """remaining_weight_g = received - sum(COMMITTED LotDraw.weight_g)."""
    committed = sum(
        d["weight_g"] for d in db.lot_draws.values()
        if d["inventory_lot_id"] == lot["id"] and d["draw_status"] == "COMMITTED")
    lot["remaining_weight_g"] = lot["received_weight_g"] - committed


def reconcile_locker_occupied(locker):
    """occupied_g = sum(received_weight_g) over AGING lots in this locker."""
    occupied = sum(
        l["received_weight_g"] for l in db.inventory_lots.values()
        if l.get("locker_id") == locker["id"] and l["lot_status"] == "AGING")
    locker["occupied_g"] = occupied


def reconcile_share(share):
    """claimed_fraction_x4 + remaining_carcass_g from ACTIVE claims."""
    units = 0
    for c in db.share_claims.values():
        if c["animal_share_id"] == share["id"] and c["claim_status"] == "ACTIVE":
            units += 1 if c["fraction"] == "QUARTER" else 2
    share["claimed_fraction_x4"] = units
    share["remaining_carcass_g"] = (
        share["carcass_weight_g"] * (4 - units)) // 4


def order_ordered_grams(order_id):
    """Sum of ordered_weight_g over the order's lines."""
    return sum(
        l["ordered_weight_g"] for l in db.order_lines.values()
        if l["custom_order_id"] == order_id)


def reconcile_window_committed(window):
    """committed_g = sum ordered grams over live holiday orders in this window
    (PRD §3.6: PLACED, CONFIRMED, FILLED, SHORT_FILLED)."""
    live = {"PLACED", "CONFIRMED", "FILLED", "SHORT_FILLED"}
    total = 0
    for o in db.custom_orders.values():
        if o.get("holiday_window_id") == window["id"] and o["order_status"] in live:
            total += order_ordered_grams(o["id"])
    window["committed_g"] = total


def credit_customer(customer_id, cents):
    """Refund `cents` to the customer's store credit (mutation bumps version)."""
    customer = db.customers.get(customer_id)
    if customer is None or cents <= 0:
        return
    customer["store_credit_cents"] += cents
    db.touch(customer)
