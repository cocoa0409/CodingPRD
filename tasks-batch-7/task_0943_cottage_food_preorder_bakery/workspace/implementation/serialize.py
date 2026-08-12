"""Entity serialisers.  Every instant leaves through tsutil.render -- the one
render function -- so a field's wire form is decided at mint time, not here."""

from tsutil import TS

COMMON = ("created_at", "updated_at", "version")

FIELDS = {
    "bakers": (
        "id", "display_name", "jurisdiction_code", "permit_status",
        "shared_kitchen", "annual_cap_cents", "cap_year",
        "annual_gross_sales_cents", "permitted_radius_km",
        "payout_period_start", "payout_net_cents",
    ),
    "customers": (
        "id", "baker_id", "display_name", "email", "delivery_distance_km",
        "allergen_avoidances", "unattended_consent", "cooler_provided",
        "credit_balance_cents",
    ),
    "recipes": (
        "id", "baker_id", "name", "recipe_status", "published_version",
        "allergen_union", "tree_depth", "cross_contact_advisory",
    ),
    "recipe_components": (
        "id", "recipe_id", "sub_recipe_id", "ingredient_lot_id",
        "component_name", "declared_allergens", "quantity_grams",
        "recalled_component",
    ),
    "ingredient_lots": (
        "id", "baker_id", "lot_code", "allergens", "cross_contact_allergens",
        "lot_status", "received_at", "expires_at",
    ),
    "menu_items": (
        "id", "baker_id", "recipe_id", "name", "product_class",
        "pricing_basis", "unit_price_cents", "dozen_price_cents",
        "temp_sensitive", "oven_profile", "oven_hours_per_batch",
        "yield_units_per_slot", "listing_status", "rating_avg",
        "rating_count", "allergen_summary",
    ),
    "offer_windows": (
        "id", "baker_id", "label", "opens_at", "order_cutoff_at",
        "production_date", "handoff_date", "handoff_window_end_at",
        "window_status", "plan_status", "capacity_posture", "capacity_units",
        "capacity_batch_slots", "capacity_oven_hours", "confirmed_units",
        "held_units", "reserved_units", "cutoff_extension_count",
    ),
    "orders": (
        "id", "customer_id", "offer_window_id", "subscription_cycle_id",
        "delivery_route_id", "channel", "handoff_mode", "source", "prepaid",
        "order_status", "payment_status", "handoff_status", "placed_at",
        "hold_expires_at", "allergen_ack", "unattended_consent",
        "cooler_provided", "delivery_distance_km", "stop_sequence",
        "subtotal_cents", "tax_total_cents", "delivery_fee_cents", "tip_cents",
        "credit_applied_cents", "grand_total_cents", "shortfall_flag",
        "rebook_count", "pickup_forfeit_at", "forfeit_latched", "fulfilled_at",
        "review_window_closes_at", "review_window_closed_latch",
    ),
    "order_lines": (
        "id", "order_id", "menu_item_id", "batch_id", "quantity",
        "disposition", "line_status", "pricing_basis_applied", "taxable",
        "line_total_cents", "line_tax_cents", "allocated_units",
        "shorted_units", "allergen_union", "hold_expires_at",
    ),
    "batches": (
        "id", "offer_window_id", "menu_item_id", "recipe_id", "batch_status",
        "slot_count", "planned_yield_units", "actual_yield_units",
        "surplus_units", "oven_hours", "recipe_version_pinned",
    ),
    "labels": (
        "id", "order_line_id", "recipe_id", "recipe_version_pinned",
        "label_status", "net_weight_grams", "allergen_union",
        "cross_contact_advisory", "statement_text",
    ),
    "subscriptions": (
        "id", "customer_id", "menu_item_id", "cadence", "units_per_cycle",
        "billing_mode", "handoff_mode", "sub_status", "pause_count",
        "past_due_since", "prepaid_balance_cents",
    ),
    "subscription_cycles": (
        "id", "subscription_id", "offer_window_id", "sequence_number",
        "cycle_status", "reserved_units", "skip_deadline_at",
        "cycle_price_cents",
    ),
    "payments": (
        "id", "order_id", "payment_state", "outcome", "tip_mode", "tip_pct",
        "tip_fixed_cents", "tip_cents", "authorized_cents", "captured_cents",
        "refunded_cents",
    ),
    "money_movements": (
        "id", "customer_id", "order_id", "payment_id", "subscription_id",
        "ledger_scope", "movement_kind", "reason", "amount_cents",
        "leg_tip_cents", "leg_delivery_fee_cents", "leg_subtotal_cents",
        "leg_credit_cents", "expires_at", "created_at",
    ),
    "delivery_routes": (
        "id", "baker_id", "offer_window_id", "route_status", "stop_count",
        "total_distance_km", "dispatched_at",
    ),
    "reviews": (
        "id", "order_id", "menu_item_id", "customer_id", "rating", "body",
        "review_status", "baker_response", "responded_at",
        "shortfall_affected", "counts_toward_rollup",
    ),
}

# MoneyMovement is an immutable ledger entry: id and created_at only.
NO_COMMON = ("money_movements",)


def _val(x):
    return x.s if isinstance(x, TS) else x


def dump(collection, record):
    fields = FIELDS[collection]
    if collection not in NO_COMMON:
        fields = fields + COMMON
    out = {f: _val(record.get(f)) for f in fields}
    if collection == "order_lines":
        # PRD 3.5: hold_expires_at is MIRRORED onto the line for as long as the
        # line is PENDING and its order is PENDING_HOLD.  Deriving the mirror on
        # read keeps it from ever going stale and keeps a mirror refresh from
        # masquerading as an independent mutation of the line.
        from db import DB
        order = DB.get("orders", record.get("order_id"))
        mirror = None
        if (order is not None
                and record.get("line_status") == "PENDING"
                and order.get("order_status") == "PENDING_HOLD"):
            mirror = order.get("hold_expires_at")
        out["hold_expires_at"] = _val(mirror)
    return out


def dump_all(collection, records):
    return [dump(collection, r) for r in records]
