"""Equipment and irrigation scheduling: half-open vs closed+buffer overlap
geometry, window validity, the irrigation due-time gate, and derived hour totals.

Difficulty queue A: resource_temporal_overlap (equipment half-open overlap rejected,
adjacent allowed; irrigation closed+buffer overlap rejected within buffer).
Corner queue B: validations (window_end not after start), state_machines (irrigation
complete before window), cross_cutting_complexity_layers (total_logged_hours).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    set_clock, create_parcel, create_equipment_asset,
    setup_growing_plan, setup_asset_with_usage, book_usage, schedule_irrigation,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


# ===========================================================================
# Difficulty: resource_temporal_overlap — equipment_half_open_overlap
# ===========================================================================
def test_equipment_overlapping_window_rejected(api):
    """PRD §3.8: "a new window for an asset conflicts with an existing `RECORDED` usage of
    that asset when the new start is before the existing end and the existing start is
    before the new end; back-to-back bookings where the new start equals the existing end
    do not conflict and are permitted."
    PRD §3.8: "An overlapping booking is rejected with `ERR_EQUIPMENT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_overlap_rejected_adjacent_allowed
    """
    ctx = setup_asset_with_usage(
        window_start="2026-06-15T08:00:00Z", window_end="2026-06-15T10:00:00Z")
    # 09:00-11:00 overlaps the existing 08:00-10:00.
    resp = api.create_equipment_usage({
        "equipment_asset_id": ctx["asset"]["id"], "crop_plan_id": ctx["plan"]["id"],
        "window_start": "2026-06-15T09:00:00Z", "window_end": "2026-06-15T11:00:00Z"}, AG)
    validate_error(resp, ApiErrorId.ERR_EQUIPMENT_WINDOW_CONFLICT.value)


def test_equipment_adjacent_window_allowed(api):
    """PRD §3.8: "back-to-back bookings where the new start equals the existing end do not
    conflict and are permitted."

    Design: Difficulty/resource_temporal_overlap/equipment_half_open_overlap_rejected_adjacent_allowed
    """
    ctx = setup_asset_with_usage(
        window_start="2026-06-15T08:00:00Z", window_end="2026-06-15T10:00:00Z")
    # 10:00-12:00 touches the existing end at 10:00 -> allowed (half-open).
    data = validate_success(api.create_equipment_usage({
        "equipment_asset_id": ctx["asset"]["id"], "crop_plan_id": ctx["plan"]["id"],
        "window_start": "2026-06-15T10:00:00Z", "window_end": "2026-06-15T12:00:00Z"}, AG), 201)
    assert data["status"] == "RECORDED", f"adjacent booking must be RECORDED, got {data['status']}"


# ===========================================================================
# Difficulty: resource_temporal_overlap — irrigation_closed_buffer_overlap
# ===========================================================================
def test_irrigation_within_buffer_rejected(api):
    """PRD §3.8: "A new irrigation event on a parcel conflicts with any `SCHEDULED` or
    `COMPLETED` event on the same parcel when the new start is at or before the existing
    end plus six hours, and the existing start is at or before the new end plus six hours.
    Because the interval is closed and buffered, touching endpoints do conflict, and
    bookings within six hours of one another also conflict; such an attempt is rejected
    with `ERR_IRRIGATION_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/irrigation_closed_buffer_overlap_rejected_within_buffer
    """
    parcel = create_parcel(name="IRF", acreage=100.0, soil_type="SAND")
    schedule_irrigation(parcel["id"], "2026-06-15T08:00:00Z", "2026-06-15T10:00:00Z")
    # New event starts only 3h after prior end (10:00) -> inside the 6h buffer.
    resp = api.create_irrigation_event({
        "parcel_id": parcel["id"], "window_start": "2026-06-15T13:00:00Z",
        "window_end": "2026-06-15T15:00:00Z", "inches_applied": 1.0}, AG)
    validate_error(resp, ApiErrorId.ERR_IRRIGATION_WINDOW_CONFLICT.value)


def test_irrigation_outside_buffer_allowed(api):
    """PRD §3.8: "Its overlap geometry is deliberately *stricter* than equipment's:
    irrigation uses closed intervals with a six-hour buffer on each side, a
    soil-saturation guard."

    Design: Difficulty/resource_temporal_overlap/irrigation_closed_buffer_overlap_rejected_within_buffer
    """
    parcel = create_parcel(name="IRF2", acreage=100.0, soil_type="SAND")
    schedule_irrigation(parcel["id"], "2026-06-15T08:00:00Z", "2026-06-15T10:00:00Z")
    # New event starts 7h after prior end (10:00 -> 17:00): beyond the 6h buffer.
    data = validate_success(api.create_irrigation_event({
        "parcel_id": parcel["id"], "window_start": "2026-06-15T17:00:00Z",
        "window_end": "2026-06-15T19:00:00Z", "inches_applied": 1.0}, AG), 201)
    assert data["status"] == "SCHEDULED", f"non-overlapping event must be SCHEDULED, got {data['status']}"


# ===========================================================================
# Corner: window validity, irrigation due-time, derived total_logged_hours
# ===========================================================================
def test_equipment_window_end_not_after_start_rejected(api):
    """PRD §3.8: "a `window_start` (inclusive) and `window_end` (exclusive) where
    `window_end` must be strictly after `window_start`; a window where `window_end` is not
    after `window_start` is rejected with `ERR_VALIDATION_WINDOW_INVALID`."

    Design: Corner/validations/window_end_not_after_start_rejected
    """
    ctx = setup_growing_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    asset = create_equipment_asset(name="T", kind="TRACTOR", hourly_cost=50.0)
    resp = api.create_equipment_usage({
        "equipment_asset_id": asset["id"], "crop_plan_id": ctx["plan"]["id"],
        "window_start": "2026-06-15T10:00:00Z", "window_end": "2026-06-15T09:00:00Z"}, AG)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_WINDOW_INVALID.value)


def test_irrigation_complete_before_window_rejected(api):
    """PRD §3.8: "An `Agronomist` completes a scheduled event, moving it from `SCHEDULED`
    to `COMPLETED`, but only once the current clock is at or after its `window_start`; an
    early attempt is rejected with `ERR_IRRIGATION_NOT_DUE`."

    Design: Corner/state_machines/irrigation_complete_before_window_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    parcel = create_parcel(name="IC", acreage=50.0, soil_type="SAND")
    ir = schedule_irrigation(parcel["id"], "2026-06-10T08:00:00Z", "2026-06-10T10:00:00Z")
    # Clock (2026-06-01) is before window_start (2026-06-10).
    resp = api.complete_irrigation(ir["id"], AG)
    validate_error(resp, ApiErrorId.ERR_IRRIGATION_NOT_DUE.value)


def test_total_logged_hours_reconciled_across_usages(api):
    """PRD §3.8: "An asset also reports `total_logged_hours`, the sum of `hours` across
    its `RECORDED` usages on all plans."
    PRD §3.8: "A successful booking recomputes the asset's `total_logged_hours`".

    Design: Corner/cross_cutting_complexity_layers/derived_total_logged_hours_reconciliation
    """
    ctx = setup_growing_plan(crop="CORN", planned_acres=40.0, acreage=50.0)
    asset = create_equipment_asset(name="Tractor X", kind="TRACTOR", hourly_cost=50.0)
    # 5h + 3h = 8h.
    book_usage(asset["id"], ctx["plan"]["id"], "2026-06-15T08:00:00Z", "2026-06-15T13:00:00Z")
    book_usage(asset["id"], ctx["plan"]["id"], "2026-06-16T08:00:00Z", "2026-06-16T11:00:00Z")
    data = validate_success(api.get_equipment_asset(asset["id"], FM))
    assert data["total_logged_hours"] == 8.00, (
        f"total_logged_hours must be 8.00, got {data['total_logged_hours']}")
