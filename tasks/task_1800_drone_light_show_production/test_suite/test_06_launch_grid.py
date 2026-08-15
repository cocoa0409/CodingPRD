"""Launch-grid assignment gates: drone flyability, cold-weather battery
derating, grid geometry and uniqueness, and the assign/void/ground
pool-partition invariant."""
from test_helpers import (
    ApiErrorId,
    assign_drone,
    create_drone_payload,
    create_launch_grid_assignment_payload,
    create_site,
    create_show,
    get_show,
    get_success_data,
    post_weather,
    register_drone,
    set_clock,
    setup_authorized_show,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

PLANNER = TEST_USERS["planner_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]


class TestGridGeometryAndUniqueness:
    def test_grid_bounds_slot_and_drone_uniqueness(self, api):
        """PRD: "The launch grid uses a 2.0-meter slot pitch over the venue's
        ground rectangle: one more than `grid_row`, multiplied by the 2.0-meter
        pitch, must not exceed the site's `ground_length_m`, and one more than
        `grid_col` times the pitch must not exceed `ground_width_m`;
        out-of-bounds coordinates are rejected with `ERR_GRID_OUT_OF_BOUNDS`. A
        coordinate pair is occupied for the show when an existing slot in
        `ASSIGNED`, `FLOWN`, or `RECONCILED` status sits on it — a `VOIDED` slot
        frees its coordinate — and reusing an occupied pair is
        `ERR_GRID_SLOT_OCCUPIED`. A drone may hold at most one `ASSIGNED` slot
        on the show (else `ERR_DRONE_ALREADY_ASSIGNED`)"

        Design: Corner/validations/grid_bounds_slot_and_drone_uniqueness
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d1 = register_drone(serial_number="SN-G1")
        d2 = register_drone(serial_number="SN-G2")

        # Row 499 fits: (499+1) * 2.0 == 1000 <= ground_length_m 1000.
        a1 = assign_drone(show_id, d1["id"], 499, 0)
        assert a1["status"] == "ASSIGNED"
        # Row 500: (500+1) * 2.0 == 1002 > 1000.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d2["id"], 500, 0), FLEET)
        validate_error(resp, ApiErrorId.ERR_GRID_OUT_OF_BOUNDS)
        # Slot (499, 0) is occupied by d1's ASSIGNED row.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d2["id"], 499, 0), FLEET)
        validate_error(resp, ApiErrorId.ERR_GRID_SLOT_OCCUPIED)
        # d1 already holds an ASSIGNED slot on this show.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d1["id"], 0, 1), FLEET)
        validate_error(resp, ApiErrorId.ERR_DRONE_ALREADY_ASSIGNED)

    def test_grid_full_returns_assignment_exceeds_design(self, api):
        """PRD: "when the show's `assigned_count` already equals the pinned
        design's `drone_count`, further assignments are rejected with
        `ERR_ASSIGNMENT_EXCEEDS_DESIGN`."

        Design: Corner/validations/grid_full_returns_assignment_exceeds_design
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 1},
            design_overrides={"drone_count": 1, "duration_sec": 300})
        show_id = ctx["show"]["id"]
        d1 = register_drone(serial_number="SN-E1")
        d2 = register_drone(serial_number="SN-E2")
        assign_drone(show_id, d1["id"], 0, 0)  # grid complete -> READY
        assert get_show(show_id)["lifecycle_status"] == "READY"

        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d2["id"], 0, 1), FLEET)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_EXCEEDS_DESIGN)


class TestAssignmentLifecycle:
    def test_assignment_void_twice_returns_invalid_state(self, api):
        """PRD: "voiding an assignment — a `FleetManager` action valid only from
        `ASSIGNED`, else `ERR_INVALID_STATE` — moves the slot to `VOIDED`,
        returns a `RESERVED` drone to `AVAILABLE`, decrements `assigned_count`"

        Design: Corner/state_machines/assignment_void_twice_returns_invalid_state
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        d1 = register_drone(serial_number="SN-V1")
        a1 = assign_drone(ctx["show"]["id"], d1["id"], 0, 0)
        validate_success(api.void_launch_grid_assignment(a1["id"], FLEET))

        resp = api.void_launch_grid_assignment(a1["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        drone = validate_success(api.get_drone(d1["id"], FLEET))
        assert drone["status"] == "AVAILABLE", "the drone is released exactly once"

    def test_immediate_consistency_after_assignment(self, api):
        """PRD: "Each accepted assignment moves the drone `AVAILABLE` →
        `RESERVED` and increments the show's `assigned_count` by one."

        Design: Corner/consistency_model/immediate_consistency_after_assignment
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        drone = register_drone(serial_number="SN-IMM")
        assignment = assign_drone(ctx["show"]["id"], drone["id"], 0, 0)
        assert assignment["status"] == "ASSIGNED"

        # The very next reads already reflect the mutation.
        show = get_show(ctx["show"]["id"])
        assert show["assigned_count"] == 1
        drone_after = validate_success(api.get_drone(drone["id"], FLEET))
        assert drone_after["status"] == "RESERVED"


class TestFlyabilityGate:
    def test_in_maintenance_drone_rejected(self, api):
        """PRD: "the drone must be `AVAILABLE` — a `GROUNDED`, `IN_MAINTENANCE`,
        `RETIRED`, or `CHARGING` drone is rejected with `ERR_DRONE_NOT_FLYABLE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_flyable_drone
        """
        ctx = setup_authorized_show()
        drone = register_drone(serial_number="SN-G01")
        get_success_data(api.maintain_drone(drone["id"], FLEET))

        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(ctx["show"]["id"], drone["id"],
                                                  0, 0), FLEET)
        validate_error(resp, ApiErrorId.ERR_DRONE_NOT_FLYABLE)

    def test_released_drone_assigns_successfully(self, api):
        """PRD: "the drone must be `AVAILABLE` — a `GROUNDED`, `IN_MAINTENANCE`,
        `RETIRED`, or `CHARGING` drone is rejected with `ERR_DRONE_NOT_FLYABLE`."
        and "Release from `IN_MAINTENANCE` or `GROUNDED` back to `AVAILABLE` is
        a `SafetyOfficer` action (else `ERR_INVALID_STATE`)."

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_flyable_drone
        """
        ctx = setup_authorized_show()
        drone = register_drone(serial_number="SN-G01")
        get_success_data(api.maintain_drone(drone["id"], FLEET))
        get_success_data(api.release_drone(drone["id"],
                                           make_safety_officer_headers("so-1")))

        assignment = assign_drone(ctx["show"]["id"], drone["id"], 0, 0)
        assert assignment["status"] == "ASSIGNED"


class TestValidationPriorityOnAssignment:
    def test_show_state_error_precedes_drone_safety_error(self, api):
        """PRD: "When several validations could reject the same request, they
        are evaluated in a fixed priority order, and the first failing check
        produces the response." — state admissibility (item 6) precedes safety
        and regulatory limits (item 8).
        PRD: "The show must be `AUTHORIZED` or `READY` (else
        `ERR_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_precedes_drone_safety
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])  # PLANNING
        drone = register_drone(serial_number="SN-D01")
        get_success_data(api.ground_drone(drone["id"],
                                          make_safety_officer_headers("so-1")))

        # Show in PLANNING AND drone GROUNDED: the state error wins.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show["id"], drone["id"], 0, 0),
            FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_show_state_error_fires_alone(self, api):
        """PRD: "The show must be `AUTHORIZED` or `READY` (else
        `ERR_INVALID_STATE`)"

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_precedes_drone_safety
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])  # PLANNING
        drone = register_drone(serial_number="SN-D02")  # AVAILABLE

        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show["id"], drone["id"], 0, 0),
            FLEET)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDoubleBookingPriority:
    def _two_authorized_shows_same_window(self):
        """Two AUTHORIZED shows at different sites with identical windows."""
        ctx_a = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        ctx_c = setup_authorized_show(
            site_overrides={"name": "Site C", "latitude": 40.0,
                            "longitude": -74.0},
            show_overrides={"name": "Show C", "drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        return ctx_a, ctx_c

    def test_double_booked_drone_error_precedes_slot_occupied(self, api):
        """PRD: "When several validations could reject the same request, they
        are evaluated in a fixed priority order, and the first failing check
        produces the response." — temporal window rules (item 9) precede
        uniqueness and capacity (item 10).
        PRD: "must not already hold an `ASSIGNED` slot on another show whose
        window overlaps this one — the same half-open semantics as airspace
        windows, so back-to-back shows touching at an endpoint do not conflict —
        else `ERR_DRONE_DOUBLE_BOOKED`."

        Design: Difficulty/priority_pair_validation_conflict/drone_double_booking_temporal_precedes_slot_constraint
        """
        ctx_a, ctx_c = self._two_authorized_shows_same_window()
        d1 = register_drone(serial_number="SN-E01")
        d2 = register_drone(serial_number="SN-E02")
        assign_drone(ctx_a["show"]["id"], d1["id"], 0, 0)
        assign_drone(ctx_c["show"]["id"], d2["id"], 0, 0)

        # d1 is booked on the window-identical Show A, and slot (0,0) on
        # Show C is also occupied: the temporal double-booking error wins.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(ctx_c["show"]["id"], d1["id"],
                                                  0, 0), FLEET)
        validate_error(resp, ApiErrorId.ERR_DRONE_DOUBLE_BOOKED)

    def test_slot_occupied_fires_alone(self, api):
        """PRD: "A coordinate pair is occupied for the show when an existing
        slot in `ASSIGNED`, `FLOWN`, or `RECONCILED` status sits on it — a
        `VOIDED` slot frees its coordinate — and reusing an occupied pair is
        `ERR_GRID_SLOT_OCCUPIED`."

        Design: Difficulty/priority_pair_validation_conflict/drone_double_booking_temporal_precedes_slot_constraint
        """
        ctx_a, ctx_c = self._two_authorized_shows_same_window()
        d2 = register_drone(serial_number="SN-E02")
        d3 = register_drone(serial_number="SN-E03")
        assign_drone(ctx_c["show"]["id"], d2["id"], 0, 0)

        # d3 holds no slot anywhere; only the occupied coordinate fails.
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(ctx_c["show"]["id"], d3["id"],
                                                  0, 0), FLEET)
        validate_error(resp, ApiErrorId.ERR_GRID_SLOT_OCCUPIED)


class TestBatteryLaunchEligibility:
    def test_nominal_charge_85_passes_84_fails(self, api):
        """PRD: "the assignment is eligible only when that effective charge
        reaches the 85 percent launch minimum, else `ERR_CHARGE_BELOW_MINIMUM`."
        and "When no such reading exists, or the latest reading's temperature is
        at least 5 degrees Celsius, the derate factor is 1.0 and eligibility is
        decided on the raw `charge_pct`."

        Design: Difficulty/boundary_precision_check/launch_charge_85_and_cold_derate_100_boundaries
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d85 = register_drone(serial_number="SN-F85", charge_pct=85)
        d84 = register_drone(serial_number="SN-F84", charge_pct=84)

        # No weather readings at the site: NOMINAL variant, raw charge decides.
        a85 = assign_drone(show_id, d85["id"], 0, 0)
        assert a85["status"] == "ASSIGNED", "85 reaches the 85 percent minimum"
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d84["id"], 0, 1), FLEET)
        validate_error(resp, ApiErrorId.ERR_CHARGE_BELOW_MINIMUM)

    def test_cold_derate_100_passes_99_fails(self, api):
        """PRD: "A latest temperature below 5 but at least −5 degrees Celsius
        derates to 0.85" and "The boundary is exact: a fully charged drone at
        the 0.85 derate posts an effective charge of exactly 85.00 and passes,
        while the same derate on a 99 percent drone yields 84.15 and fails."

        Design: Difficulty/boundary_precision_check/launch_charge_85_and_cold_derate_100_boundaries
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d100 = register_drone(serial_number="SN-F100", charge_pct=100)
        d99 = register_drone(serial_number="SN-F99", charge_pct=99)
        set_clock("2026-08-01T12:00:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-01T11:30:00Z",
                     wind_speed_kt=5, gust_kt=8, temperature_c=0)

        a100 = assign_drone(show_id, d100["id"], 0, 2)
        assert a100["status"] == "ASSIGNED", "100 * 0.85 == 85.00 exactly"
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d99["id"], 0, 3), FLEET)
        validate_error(resp, ApiErrorId.ERR_CHARGE_BELOW_MINIMUM)  # 84.15 < 85

    def test_nominal_variant_accepts_99_percent(self, api):
        """PRD: "When no such reading exists, or the latest reading's
        temperature is at least 5 degrees Celsius, the derate factor is 1.0 and
        eligibility is decided on the raw `charge_pct`."

        Design: Difficulty/dual_variant_calc/battery_launch_eligibility_nominal_vs_cold_derated
        """
        ctx = setup_authorized_show()
        d2 = register_drone(serial_number="SN-B02", charge_pct=99)
        assignment = assign_drone(ctx["show"]["id"], d2["id"], 0, 1)
        assert assignment["status"] == "ASSIGNED", \
            "NOMINAL variant: 99% raw charge is eligible (no recent reading)"

    def test_cold_derated_variant_rejects_same_99_percent(self, api):
        """PRD: "The effective charge is the drone's `charge_pct` multiplied by
        the factor, rounded half up to two decimal places, and the assignment is
        eligible only when that effective charge reaches the 85 percent launch
        minimum, else `ERR_CHARGE_BELOW_MINIMUM`. The boundary is exact: a fully
        charged drone at the 0.85 derate posts an effective charge of exactly
        85.00 and passes, while the same derate on a 99 percent drone yields
        84.15 and fails."

        Design: Difficulty/dual_variant_calc/battery_launch_eligibility_nominal_vs_cold_derated
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d2 = register_drone(serial_number="SN-B02", charge_pct=99)
        d3 = register_drone(serial_number="SN-B03", charge_pct=100)

        # NOMINAL first: the 99% drone is accepted, then voided off the grid.
        a2 = assign_drone(show_id, d2["id"], 0, 1)
        validate_success(api.void_launch_grid_assignment(a2["id"], FLEET))

        # COLD_DERATED: a 0C reading within the 120-minute recency window.
        set_clock("2026-08-01T12:00:00Z")
        post_weather(ctx["site"]["id"], recorded_at="2026-08-01T11:30:00Z",
                     wind_speed_kt=5, gust_kt=8, temperature_c=0)
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d2["id"], 0, 1), FLEET)
        validate_error(resp, ApiErrorId.ERR_CHARGE_BELOW_MINIMUM)  # 99 * 0.85 = 84.15

        a3 = assign_drone(show_id, d3["id"], 0, 2)
        assert a3["status"] == "ASSIGNED", "100% derates to exactly 85.00"

    def test_derate_recency_window_120min_boundary(self, api):
        """PRD: "The system takes the most recent weather reading at the show's
        site whose `recorded_at` lies within the trailing 120 minutes up to and
        including the current logical-clock reading (the latest by
        `recorded_at`, ties broken by `created_at`)."

        Design: Corner/calculations/derate_recency_window_120min_boundary
        """
        ctx = setup_authorized_show()
        show_id = ctx["show"]["id"]
        d99a = register_drone(serial_number="SN-T99A", charge_pct=99)
        d99b = register_drone(serial_number="SN-T99B", charge_pct=99)
        set_clock("2026-08-01T12:00:00Z")

        # 121 minutes old: outside the trailing 120 minutes, so NOMINAL applies.
        post_weather(ctx["site"]["id"], recorded_at="2026-08-01T09:59:00Z",
                     wind_speed_kt=5, gust_kt=8, temperature_c=0)
        a_ok = assign_drone(show_id, d99a["id"], 0, 0)
        assert a_ok["status"] == "ASSIGNED"

        # Exactly 120 minutes old: included ("up to and including"), so the
        # 0.85 derate applies and the same 99% charge is rejected.
        post_weather(ctx["site"]["id"], recorded_at="2026-08-01T10:00:00Z",
                     wind_speed_kt=5, gust_kt=8, temperature_c=0)
        resp = api.create_launch_grid_assignment(
            create_launch_grid_assignment_payload(show_id, d99b["id"], 0, 1), FLEET)
        validate_error(resp, ApiErrorId.ERR_CHARGE_BELOW_MINIMUM)


class TestDronePoolInvariant:
    def test_assign_void_reassign_keeps_pool_conserved(self, api):
        """PRD: "Each accepted assignment moves the drone `AVAILABLE` →
        `RESERVED` and increments the show's `assigned_count` by one. When the
        count thereby reaches the pinned design's `drone_count` while perimeter
        containment is `VALID`, the show automatically advances from
        `AUTHORIZED` to `READY`. Conversely, voiding an assignment — a
        `FleetManager` action valid only from `ASSIGNED`, else
        `ERR_INVALID_STATE` — moves the slot to `VOIDED`, returns a `RESERVED`
        drone to `AVAILABLE`, decrements `assigned_count`, and drops a `READY`
        show whose grid is no longer complete back to `AUTHORIZED`"

        Design: Difficulty/compensating_invariant/drone_pool_partition_invariant_assign_void
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        show_id = ctx["show"]["id"]
        d1 = register_drone(serial_number="SN-K01")
        d2 = register_drone(serial_number="SN-K02")
        register_drone(serial_number="SN-K03")  # stays AVAILABLE throughout

        a1 = assign_drone(show_id, d1["id"], 0, 0)
        assign_drone(show_id, d2["id"], 0, 1)
        show = get_show(show_id)
        assert show["lifecycle_status"] == "READY" and show["assigned_count"] == 2

        validate_success(api.void_launch_grid_assignment(a1["id"], FLEET))
        d1_after = validate_success(api.get_drone(d1["id"], FLEET))
        assert d1_after["status"] == "AVAILABLE", "void returns RESERVED -> AVAILABLE"
        show = get_show(show_id)
        assert show["lifecycle_status"] == "AUTHORIZED" \
            and show["assigned_count"] == 1, "incomplete grid drops READY"

        # The voided slot and the released drone are both reusable.
        re_assigned = assign_drone(show_id, d1["id"], 0, 0)
        assert re_assigned["status"] == "ASSIGNED"

    def test_grounding_reserved_drone_voids_slot_and_shrinks_pool(self, api):
        """PRD: "grounding a `RESERVED` drone additionally voids every
        `ASSIGNED` launch-grid slot it holds — each voided slot decrements its
        show's `assigned_count` and downgrades a `READY` show to `AUTHORIZED`
        with posture recomputed."
        PRD: "A `SafetyOfficer` may ground a drone from `AVAILABLE`,
        `RESERVED`, or `IN_MAINTENANCE` (any other from-state is
        `ERR_INVALID_STATE`): grounding moves it to `GROUNDED`"

        Design: Difficulty/compensating_invariant/drone_pool_partition_invariant_assign_void
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        show_id = ctx["show"]["id"]
        d1 = register_drone(serial_number="SN-K01")
        d2 = register_drone(serial_number="SN-K02")
        assign_drone(show_id, d1["id"], 0, 0)
        a2 = assign_drone(show_id, d2["id"], 0, 1)
        assert get_show(show_id)["lifecycle_status"] == "READY"

        grounded = validate_success(api.ground_drone(
            d2["id"], make_safety_officer_headers("so-1")))
        assert grounded["status"] == "GROUNDED"
        a2_after = validate_success(api.get_launch_grid_assignment(a2["id"], FLEET))
        assert a2_after["status"] == "VOIDED"
        show = get_show(show_id)
        assert show["assigned_count"] == 1, "the void decrements the count"
        assert show["lifecycle_status"] == "AUTHORIZED", \
            "grid incomplete: READY falls back to AUTHORIZED"
