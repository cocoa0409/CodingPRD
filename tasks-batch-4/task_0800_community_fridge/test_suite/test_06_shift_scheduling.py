"""Shift scheduling: coverage overlap, steward travel buffer, window validity, listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    setup_fridge_and_steward, new_fridge, new_steward, new_shift, reset_clock,
    make_admin_headers, create_shift_payload,
)


def test_overlapping_coverage_shift_same_fridge_rejected(api):
    """PRD §3.3: "A new `COVERAGE` shift must not overlap an existing `SCHEDULED` or
    `COMPLETED` `COVERAGE` shift on the **same fridge**; the windows are treated as
    half-open intervals `[start, end)` ... while any true overlap is rejected with
    `ERR_SHIFT_OVERLAP_FRIDGE`."

    Design: Difficulty/resource_temporal_overlap/coverage_overlap_same_fridge_halfopen
    """
    fridge, steward_a = setup_fridge_and_steward(api, capacity_slots=5)
    steward_b = new_steward(api, name="B", email="b@x.org")
    new_shift(api, fridge["id"], steward_a["id"], kind="COVERAGE",
              start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    resp = api.create_shift(
        fridge["id"],
        create_shift_payload(steward_b["id"], kind="COVERAGE",
                             start_at="2026-03-01T09:30:00Z", end_at="2026-03-01T10:30:00Z"),
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP_FRIDGE.value)


def test_adjacent_coverage_shift_same_fridge_allowed(api):
    """PRD §3.3: "so a shift that begins exactly when another ends is adjacent and
    permitted, while any true overlap is rejected with `ERR_SHIFT_OVERLAP_FRIDGE`."

    Design: Difficulty/resource_temporal_overlap/coverage_overlap_same_fridge_halfopen
    """
    fridge, steward_a = setup_fridge_and_steward(api, capacity_slots=5)
    steward_b = new_steward(api, name="B", email="b@x.org")
    new_shift(api, fridge["id"], steward_a["id"], kind="COVERAGE",
              start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    resp = api.create_shift(
        fridge["id"],
        create_shift_payload(steward_b["id"], kind="COVERAGE",
                             start_at="2026-03-01T10:00:00Z", end_at="2026-03-01T11:00:00Z"),
        make_admin_headers(),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_same_steward_shifts_within_travel_buffer_rejected(api):
    """PRD §3.3: "a new shift for a given steward must not fall within a 30-minute
    travel buffer of any other shift for that **same steward** on any fridge; the
    buffer expands each existing shift by 30 minutes on both ends into a closed
    interval, and a collision is rejected with `ERR_STEWARD_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/steward_buffer_double_booking_cross_fridge
    """
    reset_clock(api)
    fridge1 = new_fridge(api, name="F1", location_label="L1", capacity_slots=5)
    fridge2 = new_fridge(api, name="F2", location_label="L2", capacity_slots=5)
    steward = new_steward(api, name="Kai", email="kai@x.org")
    new_shift(api, fridge1["id"], steward["id"], kind="COVERAGE",
              start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    resp = api.create_shift(
        fridge2["id"],
        create_shift_payload(steward["id"], kind="COVERAGE",
                             start_at="2026-03-01T10:15:00Z", end_at="2026-03-01T11:00:00Z"),
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STEWARD_DOUBLE_BOOKED.value)


def test_same_steward_shifts_outside_travel_buffer_allowed(api):
    """PRD §3.3: "a new shift for a given steward must not fall within a 30-minute
    travel buffer of any other shift for that **same steward** on any fridge; the
    buffer expands each existing shift by 30 minutes on both ends into a closed
    interval, and a collision is rejected with `ERR_STEWARD_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/steward_buffer_double_booking_cross_fridge
    """
    reset_clock(api)
    fridge1 = new_fridge(api, name="F1", location_label="L1", capacity_slots=5)
    fridge2 = new_fridge(api, name="F2", location_label="L2", capacity_slots=5)
    steward = new_steward(api, name="Kai", email="kai@x.org")
    new_shift(api, fridge1["id"], steward["id"], kind="COVERAGE",
              start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    # Starts 4 hours after the prior shift's end — well outside the 30-minute buffer.
    resp = api.create_shift(
        fridge2["id"],
        create_shift_payload(steward["id"], kind="COVERAGE",
                             start_at="2026-03-01T14:00:00Z", end_at="2026-03-01T15:00:00Z"),
        make_admin_headers(),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_shift_start_at_or_after_end_rejected(api):
    """PRD §3.3: "The window itself must be well-formed: `start_at` must be strictly
    before `end_at`, or the request is rejected with `ERR_PICKUP_WINDOW_INVALID`."

    Design: Corner/validations/shift_start_after_end_returns_pickup_window_invalid
    """
    fridge, steward = setup_fridge_and_steward(api, capacity_slots=5)
    resp = api.create_shift(
        fridge["id"],
        create_shift_payload(steward["id"], kind="COVERAGE",
                             start_at="2026-03-01T10:00:00Z", end_at="2026-03-01T09:00:00Z"),
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_WINDOW_INVALID.value)


def test_list_shifts_filtered_by_steward(api):
    """PRD §4: "GET /shifts — List shifts, filterable by fridge and/or steward."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/shifts_filtered_by_steward_returns_only_that_steward
    """
    fridge, steward_a = setup_fridge_and_steward(api, capacity_slots=5)
    steward_b = new_steward(api, name="B", email="b@x.org")
    shift_a = new_shift(api, fridge["id"], steward_a["id"], kind="COVERAGE",
                        start_at="2026-03-01T09:00:00Z", end_at="2026-03-01T10:00:00Z")
    new_shift(api, fridge["id"], steward_b["id"], kind="COVERAGE",
              start_at="2026-03-01T11:00:00Z", end_at="2026-03-01T12:00:00Z")
    resp = api.list_shifts(make_admin_headers(), params={"steward_id": steward_a["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == shift_a["id"]
