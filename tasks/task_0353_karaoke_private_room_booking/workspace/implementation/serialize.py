"""Output serialization for each entity (PRD §1.1 fields).

Stored records are already plain dicts; serialize returns a copy exposing the
exact field set per entity. Song and Payment are lean (id + created_at only,
no updated_at / version per PRD §2.4).
"""

VENUE_FIELDS = [
    "id", "name", "timezone", "peak_start_minute", "peak_end_minute",
    "peak_multiplier", "deposit_pct", "cancellation_cutoff_hours",
    "grace_minutes", "overage_grace_minutes",
    "created_at", "updated_at", "version",
]

ROOM_TYPE_FIELDS = [
    "id", "venue_id", "name", "capacity", "base_hourly_rate_cents",
    "fb_minimum_cents", "active", "created_at", "updated_at", "version",
]

ROOM_FIELDS = [
    "id", "venue_id", "room_type_id", "label", "status",
    "created_at", "updated_at", "version",
]

GROUP_PACKAGE_FIELDS = [
    "id", "venue_id", "name", "flat_price_cents", "included_hours",
    "included_room_type_id", "included_fb_credit_cents", "active",
    "created_at", "updated_at", "version",
]

CUSTOMER_FIELDS = [
    "id", "full_name", "email", "phone", "no_show_strikes",
    "created_at", "updated_at", "version",
]

RESERVATION_FIELDS = [
    "id", "venue_id", "room_id", "room_type_id", "customer_id",
    "group_package_id", "party_size", "slot_start_utc", "slot_end_utc",
    "status", "checked_in_at", "actual_end_utc",
    "quoted_room_subtotal_cents", "deposit_cents", "settled_room_subtotal_cents",
    "fb_consumed_cents", "fb_shortfall_cents", "final_total_cents",
    "created_at", "updated_at", "version",
]

EXTENSION_FIELDS = [
    "id", "reservation_id", "new_slot_end_utc", "added_minutes", "status",
    "created_at", "updated_at", "version",
]

SONG_FIELDS = [
    "id", "venue_id", "title", "artist", "duration_seconds", "language",
    "created_at",
]

QUEUE_ENTRY_FIELDS = [
    "id", "reservation_id", "song_id", "priority", "play_order", "status",
    "created_at", "updated_at", "version",
]

FB_ORDER_FIELDS = [
    "id", "reservation_id", "description", "unit_price_cents", "quantity",
    "line_total_cents", "status", "created_at", "updated_at", "version",
]

PAYMENT_FIELDS = [
    "id", "reservation_id", "kind", "amount_cents", "created_at",
]


def _pick(record, fields):
    return {f: record.get(f) for f in fields}


def venue(r):
    return _pick(r, VENUE_FIELDS)


def room_type(r):
    return _pick(r, ROOM_TYPE_FIELDS)


def room(r):
    return _pick(r, ROOM_FIELDS)


def group_package(r):
    return _pick(r, GROUP_PACKAGE_FIELDS)


def customer(r):
    return _pick(r, CUSTOMER_FIELDS)


def reservation(r):
    return _pick(r, RESERVATION_FIELDS)


def extension(r):
    return _pick(r, EXTENSION_FIELDS)


def song(r):
    return _pick(r, SONG_FIELDS)


def queue_entry(r):
    return _pick(r, QUEUE_ENTRY_FIELDS)


def fb_order(r):
    return _pick(r, FB_ORDER_FIELDS)


def payment(r):
    return _pick(r, PAYMENT_FIELDS)
