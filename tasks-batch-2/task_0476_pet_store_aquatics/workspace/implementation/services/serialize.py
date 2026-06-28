"""Entity serialization to response JSON, including computed fields."""
from services.derive import compute_recall_state, compute_loyalty_tier

# Common system fields present on every entity (PRD §2.4).
_COMMON = ("id", "created_at", "updated_at", "version")


def _base(record, fields):
    out = {k: record[k] for k in _COMMON}
    for f in fields:
        out[f] = record.get(f)
    return out


def store_out(r):
    return _base(r, ["name", "state_code", "loyalty_point_value_cents", "status"])


def product_out(r):
    out = _base(r, [
        "sku", "name", "category", "unit_price_cents",
        "is_prescription_diet", "loyalty_points_per_unit",
    ])
    out["recall_state"] = compute_recall_state(r)
    return out


def lot_out(r):
    return _base(r, [
        "store_id", "product_id", "lot_code", "quantity_on_hand",
        "quantity_reserved", "received_at", "expiry_date", "status",
    ])


def batch_out(r):
    return _base(r, [
        "store_id", "species", "animal_class", "head_count", "unit_price_cents",
        "intake_at", "quarantine_days", "mortality_count",
        "health_state", "sale_state",
    ])


def customer_out(r):
    out = _base(r, [
        "email", "full_name", "home_store_id",
        "loyalty_points", "lifetime_spend_cents",
    ])
    out["loyalty_tier"] = compute_loyalty_tier(r["lifetime_spend_cents"])
    return out


def prescription_out(r):
    return _base(r, [
        "customer_id", "product_id", "issued_by_appointment_id",
        "max_units_per_order", "expires_at", "status",
    ])


def appointment_out(r):
    return _base(r, [
        "store_id", "customer_id", "service_type", "room",
        "start_at", "end_at", "fee_cents", "status",
    ])


def subscription_out(r):
    return _base(r, [
        "customer_id", "product_id", "store_id", "quantity_per_cycle",
        "cycle_days", "discount_pct", "next_ship_at",
        "shipments_count", "status",
    ])


def shipment_out(r):
    return _base(r, [
        "subscription_id", "lot_id", "units", "gross_cents", "net_cents", "status",
    ])


def special_order_out(r):
    return _base(r, [
        "customer_id", "product_id", "store_id", "quantity", "deposit_pct",
        "deposit_cents", "balance_cents", "status",
    ])


def recall_out(r):
    return _base(r, [
        "product_id", "lot_code", "severity", "scope_state_code",
        "affected_lot_count", "halted_subscription_count", "status",
    ])


def event_out(r):
    return _base(r, [
        "store_id", "partner_name", "event_date", "capacity",
        "placed_head", "status",
    ])


def placement_out(r):
    return _base(r, ["event_id", "batch_id", "head", "status"])
