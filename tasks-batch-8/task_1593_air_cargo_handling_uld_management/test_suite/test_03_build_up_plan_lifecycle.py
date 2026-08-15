"""Build-up plan creation, OCC guards, assignment, sealing, and cancellation."""
from test_helpers import (
    ApiErrorId,
    assign_booking,
    cancel_plan,
    create_build_up_plan,
    create_plan_payload,
    get_booking,
    get_flight,
    get_plan,
    get_uld,
    list_serviceable_ulds,
    make_accepted_booking,
    make_flight,
    make_open_flight,
    make_uld,
    make_uld_type_and_unit,
    open_flight,
    seal_plan,
    setup_departed_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanCreationOCC:
    def test_occ_stale_flight_version_rejected(self, api, ramp_operator_headers):
        """PRD §2.8: "requires the request to carry
        `expected_flight_version`, holding the client's last-observed `version`
        of the target Flight. If the flight's current `version` no longer
        matches — because allocations, restrictions, or reservations have moved
        it on since the client last read it — the create is rejected with
        `ERR_STALE_FLIGHT_VERSION` (HTTP 412)"

        Design: Corner/validations/occ_stale_flight_version_rejected
        """
        flight = make_flight(flight_number="CA325")
        stale_version = flight["version"]  # observed before open
        open_flight(flight["id"])
        _uld_type, uld = make_uld_type_and_unit()
        res = api.create_build_up_plan(
            create_plan_payload(flight["id"], uld["id"], stale_version),
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_FLIGHT_VERSION)
        current = get_flight(flight["id"], ramp_operator_headers)
        retry = validate_success(
            api.create_build_up_plan(
                create_plan_payload(flight["id"], uld["id"], current["version"]),
                ramp_operator_headers,
            ),
            201,
        )
        assert retry["status"] == "DRAFT"


class TestBuildWindowBuffer:
    def test_build_window_twenty_minute_gap_rejected(self, api, ramp_operator_headers):
        """PRD §3.4: "on the same flight, the new window must end at least 30
        minutes before, or begin at least 30 minutes after, the window of every
        other plan in `DRAFT` or `SEALED` — a separation of exactly 30 minutes
        is permitted, anything tighter is rejected with
        `ERR_BUILD_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/flight_build_window_buffer
        """
        flight = make_open_flight(flight_number="CA217", uld_position_count=3)
        _uld_type, uld1 = make_uld_type_and_unit(uld_code="AKE00013CA")
        uld2 = make_uld(_uld_type["id"], uld_code="AKE00014CA")
        create_build_up_plan(
            flight["id"], uld1["id"], "2026-08-09T10:00:00Z", "2026-08-09T12:00:00Z"
        )
        current = get_flight(flight["id"], ramp_operator_headers)
        res = api.create_build_up_plan(
            create_plan_payload(
                flight["id"], uld2["id"], current["version"],
                build_start="2026-08-09T12:20:00Z", build_end="2026-08-09T13:00:00Z",
            ),
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_BUILD_WINDOW_CONFLICT)
        assert get_uld(uld2["id"])["status"] == "SERVICEABLE", (
            "A rejected plan creation must not consume the ULD"
        )
        plans, meta = validate_paginated(
            api.list_flight_build_up_plans(flight["id"], ramp_operator_headers)
        )
        assert len(plans) == 1 and meta["total_count"] == 1, (
            "A rejected plan creation must not persist a plan"
        )

    def test_build_window_thirty_minute_gap_accepted(self, api, ramp_operator_headers):
        """PRD §3.4: "on the same flight, the new window must end at least 30
        minutes before, or begin at least 30 minutes after, the window of every
        other plan in `DRAFT` or `SEALED` — a separation of exactly 30 minutes
        is permitted, anything tighter is rejected with
        `ERR_BUILD_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/flight_build_window_buffer
        """
        flight = make_open_flight(flight_number="CA217", uld_position_count=3)
        _uld_type, uld1 = make_uld_type_and_unit(uld_code="AKE00013CA")
        uld2 = make_uld(_uld_type["id"], uld_code="AKE00014CA")
        create_build_up_plan(
            flight["id"], uld1["id"], "2026-08-09T10:00:00Z", "2026-08-09T12:00:00Z"
        )
        plan2 = create_build_up_plan(
            flight["id"], uld2["id"], "2026-08-09T12:30:00Z", "2026-08-09T13:30:00Z"
        )
        assert plan2["status"] == "DRAFT", (
            "Exactly 30 minutes of separation is permitted (boundary inclusive)"
        )


class TestPlanCreationGates:
    def test_uld_position_limit_exhausted(self, api, ramp_operator_headers):
        """PRD §2.6: "a new build-up plan may only be created while
        `reserved_positions` is strictly less than the flight's
        `uld_position_count`; a flight with every position spoken for rejects
        the plan with `ERR_ULD_POSITION_UNAVAILABLE` (HTTP 422)."

        Design: Corner/validations/uld_position_limit_exhausted
        """
        flight = make_open_flight(flight_number="CA323", uld_position_count=1)
        uld_type, uld1 = make_uld_type_and_unit(uld_code="AKE00110CA")
        uld2 = make_uld(uld_type["id"], uld_code="AKE00111CA")
        create_build_up_plan(
            flight["id"], uld1["id"], "2026-08-09T10:00:00Z", "2026-08-09T11:00:00Z"
        )
        current = get_flight(flight["id"], ramp_operator_headers)
        res = api.create_build_up_plan(
            create_plan_payload(
                flight["id"], uld2["id"], current["version"],
                build_start="2026-08-09T12:00:00Z", build_end="2026-08-09T13:00:00Z",
            ),
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_ULD_POSITION_UNAVAILABLE)

    def test_plan_create_with_assigned_uld_rejected(self, api, ramp_operator_headers):
        """PRD §3.4: "the flight must be `OPEN_FOR_BOOKING` and the unit
        `SERVICEABLE` — a unit already committed elsewhere draws
        `ERR_ULD_NOT_SERVICEABLE`, while a flight outside its booking window
        draws `ERR_FLIGHT_NOT_OPEN`"

        Design: Corner/errors/plan_create_with_assigned_uld_rejected
        """
        flight1 = make_open_flight(flight_number="CA333")
        flight2 = make_open_flight(flight_number="CA334")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00118CA")
        create_build_up_plan(flight1["id"], uld["id"])
        current = get_flight(flight2["id"], ramp_operator_headers)
        res = api.create_build_up_plan(
            create_plan_payload(flight2["id"], uld["id"], current["version"]),
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_ULD_NOT_SERVICEABLE)


class TestSealAndAssign:
    def test_seal_empty_plan_rejected(self, api, ramp_operator_headers):
        """PRD §3.4: "sealing requires the plan to be `DRAFT`
        (`ERR_PLAN_NOT_DRAFT`) and to contain at least one `BUILT_UP` booking,
        since an empty plan must never reach the aircraft (`ERR_PLAN_EMPTY`)."

        Design: Corner/state_machines/seal_empty_plan_rejected
        """
        flight = make_open_flight(flight_number="CA309")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00105CA")
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.seal_plan(plan["id"], ramp_operator_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_EMPTY)
        assert get_plan(plan["id"])["status"] == "DRAFT"

    def test_assign_booking_on_wrong_flight_mismatch(self, api, ramp_operator_headers):
        """PRD §3.4: "the booking's `flight_id` must equal the plan's
        `flight_id`, since cargo is never cross-loaded between flights, with a
        mismatch rejected as `ERR_BOOKING_FLIGHT_MISMATCH` (HTTP 422)"

        Design: Corner/validations/assign_booking_on_wrong_flight_mismatch
        """
        flight1 = make_open_flight(flight_number="CA321")
        flight2 = make_open_flight(flight_number="CA322")
        booking = make_accepted_booking(flight1["id"], shipper_ref="SHP-M2")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00109CA")
        plan = create_build_up_plan(flight2["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_BOOKING_FLIGHT_MISMATCH)

    def test_uld_payload_boundary_equality(self, api, ramp_operator_headers):
        """PRD §3.4: "the assignment is allowed when the projection is less
        than or equal to the maximum, equality included, and only a
        strictly-greater projection is rejected with
        `ERR_ULD_PAYLOAD_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/uld_payload_boundary_equality
        """
        flight = make_open_flight(flight_number="CA324", max_payload_kg=5000)
        uld_type, uld = make_uld_type_and_unit(
            {"tare_weight_kg": 100, "max_gross_weight_kg": 500},
            uld_code="AKE00112CA",
        )
        b1 = make_accepted_booking(
            flight["id"], shipper_ref="SHP-U2", gross_weight_kg=400, volume_m3=1
        )
        b2 = make_accepted_booking(
            flight["id"], shipper_ref="SHP-U3", gross_weight_kg=0.1, volume_m3=0.1
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        updated = validate_success(
            api.assign_booking_to_plan(
                plan["id"],
                {
                    "booking_id": b1["id"],
                    "expected_build_up_plan_version": plan["version"],
                },
                ramp_operator_headers,
            )
        )
        assert updated["total_weight_kg"] == 400, (
            "tare 100 + gross 400 == max_gross 500: equality must be allowed"
        )
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": b2["id"],
                "expected_build_up_plan_version": updated["version"],
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_ULD_PAYLOAD_EXCEEDED)

    def test_occ_stale_plan_version_rejected(self, api, ramp_operator_headers):
        """PRD §2.8: "requires the request to carry
        `expected_build_up_plan_version`, holding the client's
        last-observed `version` of the target BuildUpPlan. If the plan's
        current `version` has advanced since that observation — meaning its
        composition, and therefore its `total_weight_kg`, has changed — the
        assignment is rejected with `ERR_STALE_PLAN_VERSION` (HTTP 412)"

        Design: Corner/validations/occ_stale_plan_version_rejected
        """
        flight = make_open_flight(flight_number="CA326")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00114CA")
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-O4", gross_weight_kg=100, volume_m3=1
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        res = api.assign_booking_to_plan(
            plan["id"],
            {
                "booking_id": booking["id"],
                "expected_build_up_plan_version": plan["version"] - 1,
            },
            ramp_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_STALE_PLAN_VERSION)
        updated = validate_success(
            api.assign_booking_to_plan(
                plan["id"],
                {
                    "booking_id": booking["id"],
                    "expected_build_up_plan_version": plan["version"],
                },
                ramp_operator_headers,
            )
        )
        assert updated["total_weight_kg"] == 100


class TestPlanCancellation:
    def test_plan_cancel_returns_bookings_to_accepted(self, api, ramp_operator_headers):
        """PRD §3.4: "Cancellation unwinds everything the plan held: every
        booking built into it returns from `BUILT_UP` to `ACCEPTED` with its
        `build_up_plan_id` cleared and its weight subtracted from the plan's
        `total_weight_kg`, the unit is released `ASSIGNED → SERVICEABLE`, and
        the flight's `reserved_positions` is decremented by one."

        Design: Corner/state_machines/plan_cancel_returns_bookings_to_accepted
        """
        flight = make_open_flight(flight_number="CA313", max_payload_kg=5000)
        uld_type, uld = make_uld_type_and_unit(uld_code="AKE00107CA")
        booking = make_accepted_booking(
            flight["id"], shipper_ref="SHP-PC", gross_weight_kg=100, volume_m3=1
        )
        plan = create_build_up_plan(flight["id"], uld["id"])
        assign_booking(plan["id"], booking["id"])
        seal_plan(plan["id"])
        cancelled = cancel_plan(plan["id"])
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["total_weight_kg"] == 0
        observed_booking = get_booking(booking["id"], ramp_operator_headers)
        assert observed_booking["status"] == "ACCEPTED", (
            "Plan cancellation is compensation, not booking cancellation"
        )
        assert observed_booking.get("build_up_plan_id") is None
        assert get_uld(uld["id"])["status"] == "SERVICEABLE"
        assert get_flight(flight["id"], ramp_operator_headers)["reserved_positions"] == 0

    def test_plan_creation_removes_uld_from_serviceable_pool(
        self, api, ramp_operator_headers
    ):
        """PRD §3.4: "Creating the plan leaves it in `DRAFT` with
        `total_weight_kg` at zero, moves the unit `SERVICEABLE → ASSIGNED`,
        increments the flight's `reserved_positions` by one, and increments the
        flight's `version`."

        Design: Difficulty/compensating_invariant/uld_fleet_assign_cancel_conservation
        """
        flight = make_open_flight(flight_number="CA220")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00015CA")
        assert len(list_serviceable_ulds()) == 1
        create_build_up_plan(flight["id"], uld["id"])
        assert get_uld(uld["id"])["status"] == "ASSIGNED"
        serviceable, meta = validate_paginated(
            api.list_ulds(ramp_operator_headers, params={"status": "SERVICEABLE"})
        )
        assert serviceable == [] and meta["total_count"] == 0, (
            "The only unit must leave the SERVICEABLE pool while assigned"
        )

    def test_plan_cancel_restores_serviceable_pool(self, api, ramp_operator_headers):
        """PRD §3.4: "Cancellation unwinds everything the plan held: every
        booking built into it returns from `BUILT_UP` to `ACCEPTED` with its
        `build_up_plan_id` cleared and its weight subtracted from the plan's
        `total_weight_kg`, the unit is released `ASSIGNED → SERVICEABLE`, and
        the flight's `reserved_positions` is decremented by one."

        Design: Difficulty/compensating_invariant/uld_fleet_assign_cancel_conservation
        """
        flight = make_open_flight(flight_number="CA220")
        _uld_type, uld = make_uld_type_and_unit(uld_code="AKE00015CA")
        plan = create_build_up_plan(flight["id"], uld["id"])
        assert len(list_serviceable_ulds()) == 0
        cancel_plan(plan["id"])
        assert get_uld(uld["id"])["status"] == "SERVICEABLE", (
            "The compensating cancel must restore the unit to SERVICEABLE"
        )
        assert len(list_serviceable_ulds()) == 1

    def test_cancel_departed_plan_rejected(self, api, ramp_operator_headers):
        """PRD §3.4: "A plan that is no longer wanted can instead be cancelled
        from either `DRAFT` or `SEALED` — a plan in any later state is past the
        point of no return and draws `ERR_PLAN_NOT_CANCELLABLE`."

        Design: Corner/errors/cancel_departed_plan_rejected
        """
        scenario = setup_departed_scenario(
            flight_overrides={"flight_number": "CA337", "max_payload_kg": 5000},
            booking_overrides={"shipper_ref": "SHP-DP"},
            uld_code="AKE00120CA",
        )
        res = api.cancel_plan(scenario["plan"]["id"], ramp_operator_headers)
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_CANCELLABLE)
        assert get_plan(scenario["plan"]["id"])["status"] == "DEPARTED"
