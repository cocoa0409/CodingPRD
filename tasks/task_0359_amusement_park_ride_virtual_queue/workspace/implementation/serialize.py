"""Public field projection for each entity type.

Returns only the PRD-declared fields plus the common server-managed fields
(id, created_at, updated_at, version). Internal bookkeeping keys (prefixed with
_) are never exposed.
"""

_COMMON = ["id", "created_at", "updated_at", "version"]

_FIELDS = {
    "park": ["name", "gate_capacity", "admitted_count", "peak_threshold_pct",
             "day_phase", "operating_date", "current_utc"],
    "ride": ["park_id", "name", "hourly_throughput", "min_height_cm",
             "wheelchair_transfer_required", "single_rider_enabled",
             "operational_status", "booked_slot_count", "posted_wait_minutes"],
    "return_window": ["ride_id", "window_start_utc", "window_end_utc",
                      "slot_capacity", "reserved_count", "window_status"],
    "guest": ["park_id", "full_name", "height_cm", "uses_wheelchair", "party_id"],
    "party": ["park_id", "leader_guest_id", "member_count", "party_status"],
    "party_membership": ["party_id", "guest_id", "membership_status"],
    "entitlement_plan": ["park_id", "tier", "price_cents", "max_concurrent_holds",
                         "surge_multiplier"],
    "guest_day_ticket": ["park_id", "guest_id", "ticket_date", "admission_status"],
    "reservation": ["ride_id", "guest_id", "return_window_id", "party_id",
                    "queue_type", "reservation_status", "redistributed_from_window_id"],
    "lightning_lane_purchase": ["park_id", "guest_id", "ride_id", "plan_id",
                                "charged_cents", "hold_status"],
}


def view(kind, record):
    out = {}
    for f in _COMMON:
        out[f] = record.get(f)
    for f in _FIELDS[kind]:
        out[f] = record.get(f)
    return out
