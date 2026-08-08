"""Courier slot overlap (half-open), maintenance window overlap (closed + buffer), delivery gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    setup_active_member_with_locker, store_bottle, withdraw_bottles,
    schedule_delivery, schedule_maintenance, create_locker,
    create_delivery_order_payload,
)

MGR = TEST_USERS["cellar_manager_headers"]


def _member_with_two_withdrawn_bottles(api):
    member, locker = setup_active_member_with_locker(
        api, size_tier="MEDIUM", climate_zone="WHITE", capacity=3, tier="PREMIUM"
    )
    b1 = store_bottle(api, locker["id"], member["id"], wine_name="Sancerre", varietal="Sauvignon Blanc")
    b2 = store_bottle(api, locker["id"], member["id"], wine_name="Vouvray", varietal="Chenin Blanc")
    withdraw_bottles(api, member["id"], locker["id"], [b1["id"], b2["id"]])
    return member, locker, b1, b2


# --------------------------------------------------------------------------- #
# Queue A — resource_temporal_overlap / courier_slot_half_open_overlap
# --------------------------------------------------------------------------- #
def test_overlapping_courier_slots_rejected(api):
    """PRD §3.8: "A new order conflicts with any existing non-cancelled delivery order on
    the same `courier_ref` when the new window's start falls before the existing window's
    end and the existing window's start falls before the new window's end."

    Design: Difficulty/resource_temporal_overlap/courier_slot_half_open_overlap
    """
    member, locker, b1, b2 = _member_with_two_withdrawn_bottles(api)
    schedule_delivery(api, member["id"], [b1["id"]], "CX-1",
                      "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
    payload = create_delivery_order_payload(
        member_id=member["id"], bottle_ids=[b2["id"]], courier_ref="CX-1",
        slot_start="2026-06-01T11:00:00Z", slot_end="2026-06-01T13:00:00Z",
    )
    validate_error(api.create_delivery_order(payload, MGR), ApiErrorId.ERR_COURIER_SLOT_CONFLICT.value)


def test_adjacent_courier_slot_allowed(api):
    """PRD §3.8: "Because the intervals are half-open, exact adjacency is permitted — a new
    window that starts exactly when another ends, or ends exactly when another starts, does
    not conflict."

    Design: Difficulty/resource_temporal_overlap/courier_slot_half_open_overlap
    """
    member, locker, b1, b2 = _member_with_two_withdrawn_bottles(api)
    schedule_delivery(api, member["id"], [b1["id"]], "CX-1",
                      "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
    payload = create_delivery_order_payload(
        member_id=member["id"], bottle_ids=[b2["id"]], courier_ref="CX-1",
        slot_start="2026-06-01T12:00:00Z", slot_end="2026-06-01T14:00:00Z",
    )
    data = validate_success(api.create_delivery_order(payload, MGR), expected_status=201)
    assert data["status"] == "SCHEDULED", (
        f"adjacent (non-overlapping) slot should be accepted, got {data['status']}"
    )


# --------------------------------------------------------------------------- #
# Queue A — resource_temporal_overlap / maintenance_window_closed_buffer_overlap
# --------------------------------------------------------------------------- #
def test_maintenance_window_within_buffer_rejected(api):
    """PRD §3.9: "a new window conflicts with any existing non-cancelled window on the
    locker when the new window's start is at or before the existing window's end plus 120
    minutes and the existing window's start is at or before the new window's end plus 120
    minutes. Unlike courier slots, adjacency and near-adjacency within the buffer are
    rejected here."

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_buffer_overlap
    """
    locker = create_locker(api, size_tier="LARGE", climate_zone="RED", capacity=5)
    schedule_maintenance(api, locker["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
                         reason="coil service")
    from test_helpers import create_maintenance_window_payload
    payload = create_maintenance_window_payload(
        locker_id=locker["id"], window_start="2026-06-01T13:00:00Z",
        window_end="2026-06-01T14:00:00Z", reason="sensor swap",
    )
    # second window starts 60 min after first's end -> inside the 120-min buffer
    validate_error(
        api.create_maintenance_window(payload, MGR),
        ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT.value,
    )


def test_maintenance_window_beyond_buffer_allowed(api):
    """PRD §3.9: "Maintenance windows on the same locker must be separated by a buffer of
    120 minutes".

    Design: Difficulty/resource_temporal_overlap/maintenance_window_closed_buffer_overlap
    """
    locker = create_locker(api, size_tier="LARGE", climate_zone="RED", capacity=5)
    schedule_maintenance(api, locker["id"], "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z",
                         reason="coil service")
    from test_helpers import create_maintenance_window_payload
    # start 14:01 is > first end (12:00) + 120 min (14:00) -> outside the buffer
    payload = create_maintenance_window_payload(
        locker_id=locker["id"], window_start="2026-06-01T14:01:00Z",
        window_end="2026-06-01T15:00:00Z", reason="later service",
    )
    data = validate_success(api.create_maintenance_window(payload, MGR), expected_status=201)
    assert data["status"] == "SCHEDULED", (
        f"window beyond the 120-min buffer should be accepted, got {data['status']}"
    )


# --------------------------------------------------------------------------- #
# Queue B — errors / delivery_of_stored_bottle_returns_not_withdrawn
# --------------------------------------------------------------------------- #
def test_delivery_of_stored_bottle_returns_not_withdrawn(api):
    """PRD §3.8: "Every bottle listed must belong to the member and must currently be
    `WITHDRAWN`; a bottle that is not withdrawn is refused with
    `ERR_DELIVERY_BOTTLE_NOT_WITHDRAWN`".

    Design: Corner/errors/delivery_of_stored_bottle_returns_not_withdrawn
    """
    member, locker = setup_active_member_with_locker(
        api, size_tier="MEDIUM", climate_zone="WHITE", capacity=3, tier="PREMIUM"
    )
    bottle = store_bottle(api, locker["id"], member["id"], wine_name="Chablis",
                          varietal="Chardonnay")  # STORED, never withdrawn
    payload = create_delivery_order_payload(
        member_id=member["id"], bottle_ids=[bottle["id"]], courier_ref="CX-9",
        slot_start="2026-06-02T09:00:00Z", slot_end="2026-06-02T10:00:00Z",
    )
    validate_error(
        api.create_delivery_order(payload, MGR), ApiErrorId.ERR_DELIVERY_BOTTLE_NOT_WITHDRAWN.value
    )
