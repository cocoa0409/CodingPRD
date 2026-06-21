"""Public serialization of each entity (drops internal helper fields)."""

# Fields common to every entity, in a stable leading order.
_COMMON = ["id", "created_at", "updated_at", "version"]

# Per-entity public field order (after the common block).
_ENTITY_FIELDS = {
    "arena": [
        "name", "timezone", "current_utc",
        "marker_pool_total", "vest_pool_total",
        "marker_available_count", "vest_available_count",
        "deposit_held_cents", "deposit_refunded_cents", "deposit_forfeited_cents",
        "status",
    ],
    "field": [
        "arena_id", "name", "game_mode", "capacity_max", "turnaround_minutes",
        "reserved_headcount", "status",
    ],
    "party_package": [
        "arena_id", "name", "included_players", "extra_player_fee_cents",
        "base_fee_cents", "included_ammo_balls", "discount_pct", "active",
    ],
    "booking": [
        "arena_id", "field_id", "package_id", "booking_type", "party_size",
        "window_start", "window_end", "status", "field_fee_cents",
        "invoice_total_cents", "checked_in_count", "minors_present",
        "referee_required",
    ],
    "waiver_profile": [
        "arena_id", "booking_id", "participant_name", "date_of_birth",
        "age_years", "is_minor", "guardian_name", "status",
    ],
    "equipment_unit": [
        "arena_id", "unit_type", "asset_tag", "deposit_cents",
        "condition_grade", "status",
    ],
    "rental": [
        "arena_id", "booking_id", "equipment_unit_id", "deposit_hold_cents",
        "damage_fee_cents", "deposit_refund_cents", "deposit_forfeit_cents",
        "status",
    ],
    "add_on_order": [
        "arena_id", "booking_id", "ammo_balls", "co2_tanks", "misc_cents",
        "quote_total_cents", "settled_total_cents", "status",
    ],
    "referee": [
        "arena_id", "name", "certified_paintball", "status",
    ],
    "referee_assignment": [
        "arena_id", "booking_id", "referee_id", "status",
    ],
    "league": [
        "arena_id", "name", "total_rounds", "current_round",
        "win_points", "draw_points", "status",
    ],
    "league_match": [
        "arena_id", "league_id", "booking_id", "round_index",
        "home_team", "away_team", "home_score", "away_score",
        "outcome", "status",
    ],
}


def serialize(kind, record):
    out = {}
    for f in _COMMON:
        out[f] = record.get(f)
    for f in _ENTITY_FIELDS[kind]:
        out[f] = record.get(f)
    return out
