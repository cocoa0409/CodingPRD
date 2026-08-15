"""Driver availability windows: lifecycle gating and half-open overlap
(PRD §3.1)."""
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
    create_driver, add_window, make_volunteer_driver_headers,
)
from test_helpers.factories import create_availability_window_payload

ADMIN = TEST_USERS["admin_headers"]


class TestWindowGatedByDriverStatus:
    def test_onboarding_driver_cannot_declare_availability(self, api):
        """PRD §3.1: "An `ONBOARDING` or `SUSPENDED` driver attempting this is
        rejected with `ERR_DRIVER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/availability_window_gated_by_driver_status
        """
        driver = create_driver(full_name="V New", email="vn@example.com",
                               vehicle_capacity_lbs=300, cooler_slot_count=1,
                               cold_chain_certified=True, activate=False)
        assert driver["status"] == "ONBOARDING"
        resp = api.create_availability_window(
            driver["id"],
            create_availability_window_payload(
                window_start="2026-08-02T09:00:00Z",
                window_end="2026-08-02T12:00:00Z"),
            make_volunteer_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)

    def test_same_window_request_succeeds_after_activation(self, api):
        """PRD §3.1: "Once `ACTIVE`, a driver declares when the vehicle is free
        by creating availability windows on their own record, supplying
        `window_start` (inclusive) and `window_end` (exclusive, and required to
        be after `window_start`). An `ONBOARDING` or `SUSPENDED` driver
        attempting this is rejected with `ERR_DRIVER_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/availability_window_gated_by_driver_status
        """
        driver = create_driver(full_name="V New", email="vn@example.com",
                               vehicle_capacity_lbs=300, cooler_slot_count=1,
                               cold_chain_certified=True, activate=False)
        resp = api.patch_volunteer_driver_status(driver["id"], "ACTIVE", ADMIN)
        validate_success(resp)
        # The identical request now succeeds: only the driver's state changed.
        resp = api.create_availability_window(
            driver["id"],
            create_availability_window_payload(
                window_start="2026-08-02T09:00:00Z",
                window_end="2026-08-02T12:00:00Z"),
            make_volunteer_driver_headers(driver["id"]))
        window = validate_success(resp, 201)
        assert window["status"] == "OPEN"
        assert window["driver_id"] == driver["id"]


class TestHalfOpenOverlapSemantics:
    def test_adjacent_windows_on_both_edges_allowed(self, api):
        """PRD §3.1: "A new window must not overlap any of the same driver's
        existing windows in `OPEN` or `BOOKED` status: two intervals conflict
        when the new start falls before the existing end and the existing start
        falls before the new end, with half-open semantics so a new window
        starting exactly when an existing one ends is allowed — no buffer is
        appended, in deliberate contrast to the cooler intervals of §3.3."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        driver = create_driver(full_name="V Adj", email="va@example.com",
                               vehicle_capacity_lbs=300, cooler_slot_count=1)
        w1 = add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
        assert w1["status"] == "OPEN"
        # Trailing-edge adjacency: 12:00 == 12:00 is allowed.
        w2 = add_window(driver["id"], "2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z")
        assert w2["status"] == "OPEN"
        # Leading-edge adjacency: ending exactly at an existing start is allowed.
        w4 = add_window(driver["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z")
        assert w4["status"] == "OPEN"

    def test_one_minute_overlap_rejected(self, api):
        """PRD §3.1: "An overlap is rejected with
        `ERR_AVAILABILITY_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/availability_window_half_open_adjacency
        """
        driver = create_driver(full_name="V Adj", email="va@example.com",
                               vehicle_capacity_lbs=300, cooler_slot_count=1)
        add_window(driver["id"], "2026-08-02T09:00:00Z", "2026-08-02T12:00:00Z")
        add_window(driver["id"], "2026-08-02T12:00:00Z", "2026-08-02T15:00:00Z")
        # 11:59 starts one minute before the first window's end: a true overlap.
        resp = api.create_availability_window(
            driver["id"],
            create_availability_window_payload(
                window_start="2026-08-02T11:59:00Z",
                window_end="2026-08-02T13:00:00Z"),
            make_volunteer_driver_headers(driver["id"]))
        validate_error(resp, ApiErrorId.ERR_AVAILABILITY_WINDOW_OVERLAP)
