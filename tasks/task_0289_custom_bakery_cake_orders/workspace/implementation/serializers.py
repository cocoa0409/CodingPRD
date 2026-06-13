"""Entity -> JSON serializers. Each returns the exact public field set.

Stored entity dicts already hold the right shapes; serializers copy them so
internal-only bookkeeping never leaks and field ordering stays stable.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(obj, fields):
    return {f: obj.get(f) for f in fields}


def product(obj):
    return _pick(obj, [
        "id", "name", "base_price_cents", "base_lead_days", "tier_levels",
        "allowed_option_codes", "declared_allergen_codes", "status",
        "created_at", "updated_at", "version",
    ])


def option(obj):
    return _pick(obj, [
        "id", "option_code", "surcharge_cents", "introduces_allergen_codes",
        "dietary_exclusion_codes", "created_at", "updated_at", "version",
    ])


def production_day(obj):
    return _pick(obj, [
        "id", "production_date", "unit_capacity", "units_committed", "is_peak",
        "order_cutoff_at", "created_at", "updated_at", "version",
    ])


def route(obj):
    return _pick(obj, [
        "id", "route_name", "service_date", "stop_minutes",
        "created_at", "updated_at", "version",
    ])


def customer(obj):
    return _pick(obj, [
        "id", "email", "full_name", "store_credit_cents", "lifetime_spend_cents",
        "loyalty_tier", "created_at", "updated_at", "version",
    ])


def order(obj):
    return _pick(obj, [
        "id", "customer_id", "product_id", "production_day_id", "placed_at",
        "production_status", "payment_status", "estimate_total_cents",
        "final_total_cents", "deposit_due_cents", "balance_due_cents",
        "applied_credit_cents", "peak_surcharge_cents", "cancel_reason",
        "created_at", "updated_at", "version",
    ])


def line(obj):
    return _pick(obj, [
        "id", "order_id", "units", "selected_option_codes",
        "requested_dietary_codes", "line_surcharge_cents",
        "effective_allergen_codes", "created_at", "updated_at", "version",
    ])


def proof(obj):
    return _pick(obj, [
        "id", "order_id", "revision_number", "image_ref", "proof_status",
        "change_note", "created_at", "updated_at", "version",
    ])


def payment(obj):
    # Payment carries only id + created_at (PRD §2.4): no updated_at, no version.
    return _pick(obj, [
        "id", "order_id", "kind", "amount_cents", "credit_applied_cents",
        "settled_at", "created_at",
    ])


def reservation(obj):
    return _pick(obj, [
        "id", "order_id", "fulfillment_mode", "route_id", "window_start_min",
        "status", "created_at", "updated_at", "version",
    ])
