"""Drone registry, drone lifecycle terminal states, and charge-session
rules including aggregate bay port capacity."""
from test_helpers import (
    ApiErrorId,
    assert_drone,
    create_charge_bay,
    create_charge_session_payload,
    create_drone_payload,
    create_site,
    get_success_data,
    register_drone,
    set_clock,
    start_charge_session,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

FLEET = TEST_USERS["fleet_manager_headers"]


class TestDroneRegistry:
    def test_drone_defaults_applied_on_create(self, api):
        """PRD: "The `charge_pct` may be supplied (0 to 100 inclusive) and
        defaults to 100; `battery_cycle_count` may likewise be seeded to
        register a used airframe and defaults to 0. New drones start
        `AVAILABLE`."

        Design: Corner/entities/drone_defaults_applied_on_create
        """
        drone = validate_success(
            api.create_drone(create_drone_payload("SN-DEF-1"), FLEET), 201)
        assert_drone(drone)
        assert drone["charge_pct"] == 100
        assert drone["battery_cycle_count"] == 0
        assert drone["status"] == "AVAILABLE"

    def test_drone_duplicate_serial_rejected(self, api):
        """PRD: "Registering a **Drone** requires a `serial_number` that is
        globally unique across all drones — a duplicate is rejected with
        `ERR_DUPLICATE_SERIAL`"

        Design: Corner/entities/drone_duplicate_serial_rejected
        """
        validate_success(api.create_drone(create_drone_payload("SN-DUP-1"), FLEET),
                         201)
        resp = api.create_drone(create_drone_payload("SN-DUP-1", model="LUM-3"),
                                FLEET)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)

    def test_retired_drone_terminal_lockdown(self, api):
        """PRD: "Retirement to the terminal `RETIRED` state is a `FleetManager`
        action available only from `AVAILABLE`, `IN_MAINTENANCE`, or `GROUNDED`
        (else `ERR_INVALID_STATE`)." and "A `SafetyOfficer` may ground a drone
        from `AVAILABLE`, `RESERVED`, or `IN_MAINTENANCE` (any other from-state
        is `ERR_INVALID_STATE`)" and "Release from `IN_MAINTENANCE` or
        `GROUNDED` back to `AVAILABLE` is a `SafetyOfficer` action (else
        `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/retired_drone_terminal_lockdown
        """
        drone = register_drone(serial_number="SN-R1")
        retired = validate_success(api.retire_drone(drone["id"], FLEET))
        assert retired["status"] == "RETIRED"

        validate_error(api.ground_drone(drone["id"], make_safety_officer_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.release_drone(drone["id"], make_safety_officer_headers()),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.maintain_drone(drone["id"], FLEET),
                       ApiErrorId.ERR_INVALID_STATE)


class TestChargeSessions:
    def test_charge_full_battery_rejected(self, api):
        """PRD: "a drone whose `charge_pct` is already 100 is rejected with
        `ERR_CHARGE_NOT_NEEDED`."

        Design: Corner/validations/charge_full_battery_rejected
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-3")
        drone = register_drone(serial_number="SN-F100X")  # defaults to 100
        resp = api.create_charge_session(
            create_charge_session_payload(drone["id"], bay["id"]), FLEET)
        validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_NEEDED)

    def test_charge_session_target_bounds(self, api):
        """PRD: "Completing requires the target to be strictly above
        `charge_from_pct` and at most 100, otherwise `ERR_INVALID_CHARGE_TARGET`;
        the session becomes `COMPLETED`. Interrupting keeps a partial charge:
        the target need only be at least `charge_from_pct` and at most 100, with
        the same `ERR_INVALID_CHARGE_TARGET` on violation; the session becomes
        `INTERRUPTED`."
        PRD: "Either way `ended_at` is stamped, the drone's `charge_pct` is set
        to the session's `charge_to_pct`, and the drone returns from `CHARGING`
        to `AVAILABLE`."

        Design: Corner/validations/charge_session_target_bounds
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-4")
        drone = register_drone(serial_number="SN-T50", charge_pct=50)
        session = start_charge_session(drone["id"], bay["id"])

        # Complete requires strictly greater than charge_from_pct (50).
        resp = api.complete_charge_session(session["id"], {"charge_to_pct": 50},
                                           FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_CHARGE_TARGET)

        # Interrupt tolerates equality: the partial (zero) gain is kept.
        interrupted = validate_success(
            api.interrupt_charge_session(session["id"], {"charge_to_pct": 50},
                                         FLEET))
        assert interrupted["status"] == "INTERRUPTED"
        drone_after = validate_success(api.get_drone(drone["id"], FLEET))
        assert drone_after["charge_pct"] == 50
        assert drone_after["status"] == "AVAILABLE"

    def test_charge_session_complete_twice_returns_invalid_state(self, api):
        """PRD: "Sessions end in one of two ways, each carrying the reached
        `charge_to_pct`." — a completed session has ended, and per the
        state-admissibility rule a transition is rejected unless the entity is
        in a from-state that permits it ("else `ERR_INVALID_STATE`").
        PRD: "Either way `ended_at` is stamped, the drone's `charge_pct` is set
        to the session's `charge_to_pct`, and the drone returns from `CHARGING`
        to `AVAILABLE`."

        Design: Corner/state_machines/charge_session_complete_twice_returns_invalid_state
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-9")
        drone = register_drone(serial_number="SN-C9", charge_pct=50)
        session = start_charge_session(drone["id"], bay["id"])

        completed = validate_success(
            api.complete_charge_session(session["id"], {"charge_to_pct": 95},
                                        FLEET))
        assert completed["status"] == "COMPLETED"
        drone_after = validate_success(api.get_drone(drone["id"], FLEET))
        assert drone_after["charge_pct"] == 95
        assert drone_after["status"] == "AVAILABLE"

        validate_error(api.complete_charge_session(session["id"],
                                                   {"charge_to_pct": 100}, FLEET),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.interrupt_charge_session(session["id"],
                                                    {"charge_to_pct": 96}, FLEET),
                       ApiErrorId.ERR_INVALID_STATE)


class TestChargeSessionDroneStateGate:
    def test_grounded_drone_cannot_start_session(self, api):
        """PRD: "The drone must be `AVAILABLE`: a drone already `CHARGING` (or
        in any other non-available state) fails the state check with
        `ERR_INVALID_STATE`, which also enforces the one-active-session-per-drone
        rule."

        Design: Difficulty/cross_entity_state_dependency/charge_session_requires_available_drone
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-1", port_count=2)
        drone = register_drone(serial_number="SN-I01", charge_pct=50)
        get_success_data(api.ground_drone(drone["id"],
                                          make_safety_officer_headers("so-1")))

        resp = api.create_charge_session(
            create_charge_session_payload(drone["id"], bay["id"]), FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        get_success_data(api.release_drone(drone["id"],
                                           make_safety_officer_headers("so-1")))
        session = validate_success(api.create_charge_session(
            create_charge_session_payload(drone["id"], bay["id"]), FLEET), 201)
        assert session["status"] == "ACTIVE"
        assert session["charge_from_pct"] == 50, \
            "the session captures the drone's current charge as charge_from_pct"

    def test_busy_drone_and_second_port(self, api):
        """PRD: "The drone must be `AVAILABLE`: a drone already `CHARGING` (or
        in any other non-available state) fails the state check with
        `ERR_INVALID_STATE`, which also enforces the one-active-session-per-drone
        rule."
        PRD: "A new session captures the drone's current charge as
        `charge_from_pct`, stamps `started_at` from the logical clock, enters
        `ACTIVE` status, and moves the drone to `CHARGING`."

        Design: Difficulty/cross_entity_state_dependency/charge_session_requires_available_drone
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-1", port_count=2)
        d1 = register_drone(serial_number="SN-I01", charge_pct=50)
        d2 = register_drone(serial_number="SN-I02", charge_pct=60)
        session1 = start_charge_session(d1["id"], bay["id"])
        assert session1["status"] == "ACTIVE"

        # Same drone while CHARGING: rejected (one ACTIVE session per drone).
        resp = api.create_charge_session(
            create_charge_session_payload(d1["id"], bay["id"]), FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # A different drone takes the bay's second port.
        session2 = validate_success(api.create_charge_session(
            create_charge_session_payload(d2["id"], bay["id"]), FLEET), 201)
        assert session2["status"] == "ACTIVE"


class TestChargeBayCapacity:
    def test_third_session_beyond_port_count_rejected(self, api):
        """PRD: "A bay already hosting `port_count` `ACTIVE` sessions rejects
        the request with `ERR_BAY_CAPACITY_EXCEEDED`"

        Design: Difficulty/resource_temporal_overlap/charge_bay_aggregate_port_capacity
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-2", port_count=2)
        drones = [register_drone(charge_pct=50) for _ in range(3)]
        start_charge_session(drones[0]["id"], bay["id"])
        start_charge_session(drones[1]["id"], bay["id"])

        # Two ACTIVE sessions fill the aggregate capacity of 2.
        resp = api.create_charge_session(
            create_charge_session_payload(drones[2]["id"], bay["id"]), FLEET)
        validate_error(resp, ApiErrorId.ERR_BAY_CAPACITY_EXCEEDED)

    def test_completing_session_frees_port(self, api):
        """PRD: "A bay already hosting `port_count` `ACTIVE` sessions rejects
        the request with `ERR_BAY_CAPACITY_EXCEEDED`" and "Either way `ended_at`
        is stamped, the drone's `charge_pct` is set to the session's
        `charge_to_pct`, and the drone returns from `CHARGING` to `AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/charge_bay_aggregate_port_capacity
        """
        site = create_site()
        set_clock()
        bay = create_charge_bay(site["id"], bay_code="BAY-2", port_count=2)
        drones = [register_drone(charge_pct=50) for _ in range(3)]
        s1 = start_charge_session(drones[0]["id"], bay["id"])
        start_charge_session(drones[1]["id"], bay["id"])
        validate_error(api.create_charge_session(
            create_charge_session_payload(drones[2]["id"], bay["id"]), FLEET),
            ApiErrorId.ERR_BAY_CAPACITY_EXCEEDED)

        completed = validate_success(
            api.complete_charge_session(s1["id"], {"charge_to_pct": 90}, FLEET))
        assert completed["status"] == "COMPLETED"
        drone0 = validate_success(api.get_drone(drones[0]["id"], FLEET))
        assert drone0["charge_pct"] == 90 and drone0["status"] == "AVAILABLE"

        # The freed port admits the previously rejected third session.
        s3 = validate_success(api.create_charge_session(
            create_charge_session_payload(drones[2]["id"], bay["id"]), FLEET), 201)
        assert s3["status"] == "ACTIVE"
