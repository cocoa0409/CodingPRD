"""Public serialization of entities (PRD §1.1 fields + §2.4 system fields).

Each serializer returns the wire representation. Internal-only keys (those
prefixed with `_`) are never emitted. TempReading omits version/updated_at
(PRD §2.4: append-only logs carry only id and created_at).
"""


def _public(record, keys):
    out = {}
    for k in keys:
        out[k] = record.get(k)
    return out


SYS_FULL = ["id", "created_at", "updated_at", "version"]
SYS_LOG = ["id", "created_at"]


def customer(r):
    return _public(r, SYS_FULL + [
        "full_name", "phone", "loyalty_tier", "store_credit_cents"])


def cut_type(r):
    return _public(r, SYS_FULL + [
        "code", "species", "base_price_cents_per_kg",
        "is_grind", "requires_dry_age"])


def pricing_policy(r):
    return _public(r, SYS_FULL + [
        "shrink_pct_whole_cut", "shrink_pct_grind",
        "preferred_discount_pct", "wholesale_discount_pct",
        "bulk_threshold_g", "bulk_extra_discount_pct", "is_active"])


def inventory_lot(r):
    return _public(r, SYS_FULL + [
        "cut_type_id", "source_share_id", "received_weight_g",
        "remaining_weight_g", "lot_status", "locker_id",
        "aging_started_at", "aging_target_days"])


def dry_age_locker(r):
    return _public(r, SYS_FULL + [
        "name", "capacity_g", "occupied_g", "min_temp_c", "max_temp_c",
        "locker_status", "last_excursion_at"])


def temp_reading(r):
    return _public(r, SYS_LOG + [
        "locker_id", "temp_c", "reading_at", "in_band", "triggered_quarantine"])


def animal_share(r):
    return _public(r, SYS_FULL + [
        "species", "carcass_weight_g", "deposit_cents",
        "claimed_fraction_x4", "remaining_carcass_g", "share_status"])


def share_claim(r):
    return _public(r, SYS_FULL + [
        "animal_share_id", "customer_id", "fraction",
        "deposit_paid_cents", "claim_status"])


def custom_order(r):
    return _public(r, SYS_FULL + [
        "customer_id", "order_kind", "pickup_date", "holiday_window_id",
        "deposit_cents", "estimated_total_cents", "final_total_cents",
        "order_status"])


def order_line(r):
    return _public(r, SYS_FULL + [
        "custom_order_id", "cut_type_id", "ordered_weight_g",
        "catch_weight_g", "est_line_cents", "final_line_cents",
        "drawn_lot_id", "line_status"])


def lot_draw(r):
    return _public(r, SYS_FULL + [
        "inventory_lot_id", "order_line_id", "batch_input_id",
        "weight_g", "draw_status"])


def sausage_batch(r):
    return _public(r, SYS_FULL + [
        "recipe_name", "output_cut_type_id", "planned_output_g",
        "actual_yield_g", "batch_status"])


def batch_input(r):
    return _public(r, SYS_FULL + [
        "sausage_batch_id", "inventory_lot_id", "weight_g"])


def holiday_window(r):
    return _public(r, SYS_FULL + [
        "name", "pickup_date", "capacity_g", "committed_g", "cutoff_at"])
