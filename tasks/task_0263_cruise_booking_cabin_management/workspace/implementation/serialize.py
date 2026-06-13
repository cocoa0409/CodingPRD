"""Public serialization of entities — strips internal fields (e.g. _seq)."""

_COMMON = ("id", "created_at", "updated_at", "version")

_FIELDS = {
    "sailing": _COMMON + (
        "ship_name", "itinerary_code", "embark_date", "disembark_date", "nights",
        "status", "total_cabins", "available_cabins",
    ),
    "cabin_category": _COMMON + (
        "sailing_id", "code", "deck_low", "deck_high", "base_fare_per_guest_cents",
        "max_occupancy", "total_cabins", "available_cabins", "held_cabins",
        "assigned_cabins", "blocked_cabins",
    ),
    "cabin": _COMMON + (
        "cabin_category_id", "sailing_id", "cabin_number", "deck", "status",
        "group_block_id", "booking_id",
    ),
    "group_block": _COMMON + (
        "sailing_id", "group_name", "cabin_category_id", "block_size",
        "group_discount_pct", "release_cutoff_date", "status", "blocked_count",
        "materialized_count",
    ),
    "booking": _COMMON + (
        "sailing_id", "cabin_category_id", "group_block_id", "cabin_id",
        "owner_user_id", "expected_sailing_version", "status", "guest_count",
        "fare_total_cents", "tax_port_total_cents", "booking_total_cents",
        "deposit_due_cents", "final_due_cents", "amount_paid_cents",
        "fcc_credit_cents", "cancel_refund_cents", "cancellation_mode",
    ),
    "guest": _COMMON + (
        "booking_id", "full_name", "age", "occupancy_index", "base_fare_cents",
        "final_fare_cents", "tax_port_cents",
    ),
    "add_on": _COMMON + (
        "booking_id", "guest_id", "kind", "title", "price_cents", "window_start",
        "window_end", "status",
    ),
    "dining_reservation": _COMMON + (
        "booking_id", "venue_code", "seating_start", "party_size", "status",
    ),
    "payment": _COMMON + (
        "booking_id", "kind", "amount_cents", "status",
    ),
    "folio": _COMMON + (
        "booking_id", "status", "gratuity_mode", "charges_total_cents",
        "gratuity_total_cents", "balance_due_cents",
    ),
    "folio_charge": _COMMON + (
        "folio_id", "guest_id", "description", "amount_cents", "status",
    ),
}


def view(kind, entity):
    fields = _FIELDS[kind]
    return {k: entity.get(k) for k in fields}
