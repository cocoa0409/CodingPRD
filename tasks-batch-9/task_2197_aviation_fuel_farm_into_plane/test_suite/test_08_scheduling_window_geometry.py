"""Two scarce resources booked with opposite interval conventions: a hydrant pit on a half-open
window that tolerates touching endpoints, and a truck on a closed window inflated by its buffer."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures as fx


def _hydrant_farm_with_three_orders():
    env = fx.setup_farm_with_released_tank(
        opening_volume_liters=1_000_000.0,
        hydrant_system_available=True,
        permit_overrides={"max_daily_throughput_liters": 400000.0,
                          "max_reportable_spill_liters": 20.0})
    farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]
    env["pit"] = fx.register_pit(farm_id, tank_id, stand_code="A12")
    env["carts"] = [fx.register_cart(farm_id, turnaround_buffer_minutes=0,
                                     differential_pressure_kpa=10.0) for _ in range(3)]
    env["account"] = fx.open_account(base_price_cents_per_liter=62.00,
                                     credit_limit_cents=100_000_000, tax_exempt=False)
    account_id = env["account"]["id"]

    windows = [("2026-08-10T06:00:00Z", "2026-08-10T06:30:00Z"),
               ("2026-08-10T06:30:00Z", "2026-08-10T07:00:00Z"),
               ("2026-08-10T06:15:00Z", "2026-08-10T06:45:00Z")]
    departures = ["2026-08-10T08:00:00Z", "2026-08-10T08:30:00Z", "2026-08-10T09:00:00Z"]
    env["orders"] = []
    for (start, end), departure in zip(windows, departures):
        flight = fx.register_flight(account_id, stand_code="A12",
                                    scheduled_departure_utc=departure)
        auth = fx.issue_authorization(account_id, flight["id"], max_authorized_liters=10_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="HYDRANT",
                                requested_uplift_liters=10_000.0,
                                window_start_utc=start, window_end_utc=end)
        fx.authorize_order(order["id"])
        env["orders"].append(order)
    return env


class TestHydrantPitHalfOpenBooking:
    def test_windows_that_only_touch_at_an_endpoint_share_the_pit(self, api):
        """PRD §3.6: "**A hydrant pit is booked on a half-open interval**: the order's window from
        `window_start_utc` inclusive to `window_end_utc` exclusive must not intersect the window of
        any other order on the same pit whose `status` is `ASSIGNED` or `FUELING`."
        PRD §3.6: "Back-to-back windows that merely touch at an endpoint — one ending at exactly the
        instant the next begins — do **not** intersect and are both permitted; a real overlap is
        `ERR_PIT_WINDOW_CONFLICT`."
        PRD §2.5: "Time windows in this domain are consistently **half-open** — start inclusive, end
        exclusive — with exactly one deliberate exception."

        Design: Difficulty/resource_temporal_overlap/hydrant_pit_half_open_windows_allow_adjacency_but_reject_intersection
        """
        env = _hydrant_farm_with_three_orders()
        pit_id = env["pit"]["id"]

        first = validate_success(api.assign_order(
            env["orders"][0]["id"],
            {"fueling_asset_id": env["carts"][0]["id"], "hydrant_pit_id": pit_id}, fx.AGENT))
        assert first["status"] == "ASSIGNED"
        assert first["hydrant_pit_id"] == pit_id

        second = validate_success(api.assign_order(
            env["orders"][1]["id"],
            {"fueling_asset_id": env["carts"][1]["id"], "hydrant_pit_id": pit_id}, fx.AGENT))
        assert second["status"] == "ASSIGNED", \
            "06:30Z is excluded from the first window, so the two only touch"
        assert second["hydrant_pit_id"] == pit_id

    def test_a_genuinely_intersecting_third_window_is_refused(self, api):
        """PRD §3.6: "Back-to-back windows that merely touch at an endpoint — one ending at exactly
        the instant the next begins — do **not** intersect and are both permitted; a real overlap is
        `ERR_PIT_WINDOW_CONFLICT`."
        PRD §3.1: "A pit's `status` starts `AVAILABLE`; the only other value, `LOCKED_OUT`, is
        reserved for administrative lockout when the pit's source tank is taken out of service, and
        is never used to represent momentary occupancy by an order."
        PRD §3.6: "Assignment stores the `fueling_asset_id` and, for hydrant work, the
        `hydrant_pit_id`, and records the order's pit occupancy for its window — note that the pit's
        own `status` is *not* changed to `LOCKED_OUT` by an assignment, because lockout means
        administrative unavailability, not momentary use."

        Design: Difficulty/resource_temporal_overlap/hydrant_pit_half_open_windows_allow_adjacency_but_reject_intersection
        """
        env = _hydrant_farm_with_three_orders()
        pit_id = env["pit"]["id"]
        for index in (0, 1):
            validate_success(api.assign_order(
                env["orders"][index]["id"],
                {"fueling_asset_id": env["carts"][index]["id"], "hydrant_pit_id": pit_id},
                fx.AGENT))

        validate_error(api.assign_order(
            env["orders"][2]["id"],
            {"fueling_asset_id": env["carts"][2]["id"], "hydrant_pit_id": pit_id}, fx.AGENT),
            ApiErrorId.ERR_PIT_WINDOW_CONFLICT, 409)

        third = fx.read_order(env["orders"][2]["id"])
        assert third["status"] == "AUTHORIZED"
        assert third["hydrant_pit_id"] is None
        assert third["fueling_asset_id"] is None

        assert fx.read_pit(pit_id)["status"] == "AVAILABLE", \
            "occupancy is never expressed through the pit's own status"
        assert fx.read_asset(env["carts"][2]["id"])["status"] == "IN_SERVICE"

        tank = fx.read_tank(env["tank"]["id"])
        assert tank["reserved_volume_liters"] == pytest.approx(30000.00, abs=0.005), \
            "all three orders are AUTHORIZED or later and hold their reservations"
        assert tank["available_volume_liters"] == pytest.approx(969500.00, abs=0.005)


def _truck_farm_with_three_orders():
    env = fx.setup_farm_with_released_tank(
        opening_volume_liters=1_000_000.0,
        permit_overrides={"max_daily_throughput_liters": 400000.0,
                          "max_reportable_spill_liters": 20.0})
    farm_id, tank_id = env["farm"]["id"], env["tank"]["id"]
    env["truck"] = fx.register_truck(farm_id, tank_capacity_liters=40_000.0,
                                     turnaround_buffer_minutes=15,
                                     differential_pressure_kpa=10.0)
    env["account"] = fx.open_account(base_price_cents_per_liter=62.00,
                                     credit_limit_cents=100_000_000, tax_exempt=False)
    account_id = env["account"]["id"]

    windows = [("2026-08-10T06:00:00Z", "2026-08-10T06:30:00Z"),
               ("2026-08-10T06:45:00Z", "2026-08-10T07:15:00Z"),
               ("2026-08-10T06:46:00Z", "2026-08-10T07:16:00Z")]
    departures = ["2026-08-10T08:00:00Z", "2026-08-10T09:00:00Z", "2026-08-10T09:30:00Z"]
    stands = ["B01", "B02", "B03"]
    env["orders"] = []
    for (start, end), departure, stand in zip(windows, departures, stands):
        flight = fx.register_flight(account_id, stand_code=stand,
                                    scheduled_departure_utc=departure)
        auth = fx.issue_authorization(account_id, flight["id"], max_authorized_liters=10_000.0)
        order = fx.create_order(flight["id"], auth["id"], tank_id,
                                auth["authorization_code"], delivery_mode="TRUCK",
                                requested_uplift_liters=10_000.0,
                                window_start_utc=start, window_end_utc=end)
        fx.authorize_order(order["id"])
        env["orders"].append(order)
    return env


class TestTruckClosedBookingWithBuffer:
    def test_the_buffer_endpoint_itself_is_occupied_and_rejects_exact_adjacency(self, api):
        """PRD §3.6: "**A fuelling asset is booked on a closed interval extended by its turnaround
        buffer**: the occupied interval runs from `window_start_utc` through `window_end_utc` plus
        the asset's `turnaround_buffer_minutes`, with both endpoints included, and it must not
        intersect the correspondingly extended interval of any other order on the same asset whose
        `status` is `ASSIGNED` or `FUELING`."
        PRD §3.6: "Here touching endpoints **do** intersect, and the buffer is part of the occupied
        interval, so a default 15-minute buffer means a quarter of an hour of dead time after every
        job. A conflict is `ERR_ASSET_WINDOW_CONFLICT`."
        PRD §2.5: "The exception is asset scheduling: an asset's occupied interval is treated as
        **closed** at both ends and extended by its turnaround buffer, which is described in §3."

        Design: Difficulty/resource_temporal_overlap/truck_closed_window_plus_turnaround_buffer_rejects_exact_adjacency
        """
        env = _truck_farm_with_three_orders()
        truck_id = env["truck"]["id"]

        first = validate_success(api.assign_order(
            env["orders"][0]["id"], {"fueling_asset_id": truck_id}, fx.AGENT))
        assert first["status"] == "ASSIGNED"

        validate_error(api.assign_order(
            env["orders"][1]["id"], {"fueling_asset_id": truck_id}, fx.AGENT),
            ApiErrorId.ERR_ASSET_WINDOW_CONFLICT, 409)

        refused = fx.read_order(env["orders"][1]["id"])
        assert refused["status"] == "AUTHORIZED"
        assert refused["fueling_asset_id"] is None
        assert refused["unassign_count"] == 0, \
            "a refused assignment is not an unassignment"

    def test_one_minute_past_the_buffer_is_accepted_on_the_same_truck(self, api):
        """PRD §3.1: "`turnaround_buffer_minutes` is the mandatory gap after a booked fuelling window
        before the asset may take its next order; it defaults to 15 minutes and must be zero or
        greater."
        PRD §3.6: "The order's and asset's `version` each rise by one, and for hydrant work the pit's
        `version` also rises."
        PRD §3.4: "The `reserved_volume_liters` is the sum of `requested_uplift_liters` over every
        order on this tank whose `status` is `AUTHORIZED`, `ASSIGNED` or `FUELING`, rounded half up
        to two decimals."

        Design: Difficulty/resource_temporal_overlap/truck_closed_window_plus_turnaround_buffer_rejects_exact_adjacency
        """
        env = _truck_farm_with_three_orders()
        truck_id = env["truck"]["id"]
        validate_success(api.assign_order(
            env["orders"][0]["id"], {"fueling_asset_id": truck_id}, fx.AGENT))
        validate_error(api.assign_order(
            env["orders"][1]["id"], {"fueling_asset_id": truck_id}, fx.AGENT),
            ApiErrorId.ERR_ASSET_WINDOW_CONFLICT, 409)

        third = validate_success(api.assign_order(
            env["orders"][2]["id"], {"fueling_asset_id": truck_id}, fx.AGENT))
        assert third["status"] == "ASSIGNED", \
            "06:46Z clears the closed [06:00Z, 06:45Z] occupancy by a minute"
        assert third["fueling_asset_id"] == truck_id

        assert fx.read_asset(truck_id)["status"] == "IN_SERVICE"
        assert fx.read_tank(env["tank"]["id"])["reserved_volume_liters"] == \
            pytest.approx(30000.00, abs=0.005)
