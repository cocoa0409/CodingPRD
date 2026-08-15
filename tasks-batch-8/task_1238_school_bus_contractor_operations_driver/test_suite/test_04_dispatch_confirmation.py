"""Dispatch confirmation: safety stack, temporal overlap, priority ordering,
and immediate consistency of coverage counters."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    build_service_day,
    confirm_assignment,
    create_active_driver,
    create_bus,
    create_district,
    create_work_order,
    get_success_data,
    make_driver_headers,
    setup_ops_scenario,
    suspend_driver,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers.fixtures import HR, OPS


class TestConfirmRequiresActiveDriver:
    def _setup_suspended_driver_day(self, api):
        ctx = setup_ops_scenario(district_name="D-XD1")
        suspend_driver(ctx["driver"]["id"], reason="Policy violation")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        return ctx, day, assignments[0]

    def test_confirm_rejected_when_driver_suspended(self, api):
        """PRD section 3.5: "Confirmation runs the full safety stack. The driver
        must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), hold an active `CDL_B`
        (`ERR_CREDENTIAL_EXPIRED`) and an active `S_ENDORSEMENT`
        (`ERR_ENDORSEMENT_MISSING`), and carry `license_class` `B`
        (`ERR_LICENSE_CLASS_INSUFFICIENT`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_driver
        """
        ctx, _day, assignment = self._setup_suspended_driver_day(api)
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE, 409)
        fetched = validate_success(api.get_assignment(assignment["id"], OPS))
        assert fetched["status"] == "PLANNED", "rejected confirm leaves PLANNED"

    def test_rejected_confirm_leaves_driver_unassigned(self, api):
        """PRD section 3.5: "A successful confirmation sets the assignment's
        driver and bus, adds the planned minutes to the driver's
        `weekly_assigned_minutes`, and recomputes the day's covered and
        uncovered counts."
        PRD section 3.5: "The driver must be `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`),
        hold an active `CDL_B` (`ERR_CREDENTIAL_EXPIRED`) and an active
        `S_ENDORSEMENT` (`ERR_ENDORSEMENT_MISSING`), and carry `license_class`
        `B` (`ERR_LICENSE_CLASS_INSUFFICIENT`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_active_driver
        """
        ctx, _day, assignment = self._setup_suspended_driver_day(api)
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ACTIVE)
        fetched = validate_success(api.get_assignment(assignment["id"], OPS))
        assert fetched["driver_id"] is None, "no driver attached on rejection"
        assert fetched["bus_id"] is None


class TestConfirmRequiresInServiceBus:
    def _setup_in_shop_bus_day(self, api):
        ctx = setup_ops_scenario(district_name="D-XD2")
        create_work_order(ctx["bus"]["id"], category="REPAIR",
                          description="Brake line")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        return ctx, day, assignments[0]

    def test_work_order_moves_bus_in_shop_and_blocks_confirm(self, api):
        """PRD section 3.4: "Creating one with a `bus_id`, a `category` of `PM`,
        `REPAIR`, or `INSPECTION_FOLLOWUP`, and a `description` opens it in
        `OPEN` and immediately moves the bus from `IN_SERVICE` or `GROUNDED` to
        `IN_SHOP`."
        PRD section 3.5: "The bus must be `IN_SERVICE` (`ERR_BUS_NOT_IN_SERVICE`)
        with its `next_inspection_due` on or after the day's `service_date`
        (`ERR_INSPECTION_OVERDUE`), must seat at least the route's
        `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must belong
        to the same district as the contract being served
        (`ERR_BUS_DISTRICT_MISMATCH`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_in_service_bus
        """
        ctx, _day, assignment = self._setup_in_shop_bus_day(api)
        bus = validate_success(api.get_bus(ctx["bus"]["id"], OPS))
        assert bus["status"] == "IN_SHOP", "work order side effect"

        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_NOT_IN_SERVICE, 409)

    def test_rejected_confirm_leaves_assignment_planned(self, api):
        """PRD section 3.5: "A successful confirmation sets the assignment's
        driver and bus, adds the planned minutes to the driver's
        `weekly_assigned_minutes`, and recomputes the day's covered and
        uncovered counts."
        PRD section 3.5: "The bus must be `IN_SERVICE` (`ERR_BUS_NOT_IN_SERVICE`)
        with its `next_inspection_due` on or after the day's `service_date`
        (`ERR_INSPECTION_OVERDUE`), must seat at least the route's
        `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must belong
        to the same district as the contract being served
        (`ERR_BUS_DISTRICT_MISMATCH`)."

        Design: Difficulty/cross_entity_state_dependency/confirm_requires_in_service_bus
        """
        ctx, _day, assignment = self._setup_in_shop_bus_day(api)
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_NOT_IN_SERVICE)
        fetched = validate_success(api.get_assignment(assignment["id"], OPS))
        assert fetched["status"] == "PLANNED"
        assert fetched["bus_id"] is None


class TestDriverOverlapHalfOpen:
    def _setup_three_route_day(self, api):
        ctx = setup_ops_scenario(
            district_name="D-OV1",
            routes=[(420, 480, 40), (480, 540, 30), (470, 540, 30)])
        bus2 = create_bus(ctx["district"]["id"], fleet_number="BO2")
        bus3 = create_bus(ctx["district"]["id"], fleet_number="BO3")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        return ctx, day, assignments, [ctx["bus"], bus2, bus3]

    def test_adjacent_runs_share_driver_allowed(self, api):
        """PRD section 3.5: "Neither driver nor bus may already hold a
        conflicting commitment on the same service date: intervals are treated
        as half-open, so one commitment ending at exactly the minute another
        begins is permissible, while any true intersection is rejected with
        `ERR_DRIVER_OVERLAP_CONFLICT` or `ERR_BUS_OVERLAP_CONFLICT`
        respectively."

        Design: Difficulty/resource_temporal_overlap/driver_overlap_half_open_adjacency
        """
        ctx, _day, assignments, buses = self._setup_three_route_day(api)
        driver_id = ctx["driver"]["id"]
        first = confirm_assignment(assignments[0]["id"], driver_id, buses[0]["id"])
        assert first["status"] == "CONFIRMED"
        second = confirm_assignment(assignments[1]["id"], driver_id, buses[1]["id"])
        assert second["status"] == "CONFIRMED", (
            "adjacent at minute 480: half-open [420,480) and [480,540) do not "
            "intersect")

    def test_overlapping_run_rejected_for_same_driver(self, api):
        """PRD section 3.5: "Neither driver nor bus may already hold a
        conflicting commitment on the same service date: intervals are treated
        as half-open, so one commitment ending at exactly the minute another
        begins is permissible, while any true intersection is rejected with
        `ERR_DRIVER_OVERLAP_CONFLICT` or `ERR_BUS_OVERLAP_CONFLICT`
        respectively."

        Design: Difficulty/resource_temporal_overlap/driver_overlap_half_open_adjacency
        """
        ctx, _day, assignments, buses = self._setup_three_route_day(api)
        driver_id = ctx["driver"]["id"]
        confirm_assignment(assignments[0]["id"], driver_id, buses[0]["id"])
        confirm_assignment(assignments[1]["id"], driver_id, buses[1]["id"])

        resp = api.confirm_assignment(
            assignments[2]["id"], {"driver_id": driver_id, "bus_id": buses[2]["id"]},
            OPS)
        validate_error(resp, ApiErrorId.ERR_DRIVER_OVERLAP_CONFLICT, 409)
        fetched = validate_success(api.get_assignment(assignments[2]["id"], OPS))
        assert fetched["status"] == "PLANNED", "[470,540) intersects [420,480)"
        assert fetched["driver_id"] is None


class TestBusOverlapOnConfirm:
    def test_error_bus_overlap_on_confirm_returns_409(self, api):
        """PRD section 3.5: "Neither driver nor bus may already hold a
        conflicting commitment on the same service date: intervals are treated
        as half-open, so one commitment ending at exactly the minute another
        begins is permissible, while any true intersection is rejected with
        `ERR_DRIVER_OVERLAP_CONFLICT` or `ERR_BUS_OVERLAP_CONFLICT`
        respectively."

        Design: Corner/errors/error_bus_overlap_on_confirm_returns_409
        """
        ctx = setup_ops_scenario(district_name="D-ERR24",
                                 routes=[(420, 480, 40), (430, 500, 30)])
        driver_b = create_active_driver(ctx["district"]["id"], full_name="D Err24b",
                                        license_number="L291")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])

        resp = api.confirm_assignment(
            assignments[1]["id"],
            {"driver_id": driver_b["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_OVERLAP_CONFLICT, 409)


class TestConfirmSafetyRejections:
    def test_error_capacity_insufficient_on_confirm_returns_422(self, api):
        """PRD section 3.5: "The bus must be `IN_SERVICE`
        (`ERR_BUS_NOT_IN_SERVICE`) with its `next_inspection_due` on or after the
        day's `service_date` (`ERR_INSPECTION_OVERDUE`), must seat at least the
        route's `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must
        belong to the same district as the contract being served
        (`ERR_BUS_DISTRICT_MISMATCH`)."

        Design: Corner/errors/error_capacity_insufficient_on_confirm_returns_422
        """
        ctx = setup_ops_scenario(district_name="D-ERR7",
                                 bus_overrides={"capacity": 30})
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        resp = api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_INSUFFICIENT, 422)

    def test_error_inspection_overdue_on_confirm_returns_409(self, api):
        """PRD section 3.5: "The bus must be `IN_SERVICE`
        (`ERR_BUS_NOT_IN_SERVICE`) with its `next_inspection_due` on or after the
        day's `service_date` (`ERR_INSPECTION_OVERDUE`), must seat at least the
        route's `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must
        belong to the same district as the contract being served
        (`ERR_BUS_DISTRICT_MISMATCH`)."

        Design: Corner/errors/error_inspection_overdue_on_confirm_returns_409
        """
        ctx = setup_ops_scenario(district_name="D-ERR14",
                                 bus_overrides={"next_inspection_due": "2026-05-31"})
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        resp = api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_OVERDUE, 409)

    def test_error_license_class_insufficient_on_confirm_returns_409(self, api):
        """PRD section 3.5: "The driver must be `ACTIVE`
        (`ERR_DRIVER_NOT_ACTIVE`), hold an active `CDL_B`
        (`ERR_CREDENTIAL_EXPIRED`) and an active `S_ENDORSEMENT`
        (`ERR_ENDORSEMENT_MISSING`), and carry `license_class` `B`
        (`ERR_LICENSE_CLASS_INSUFFICIENT`)."
        PRD section 3.3: "`license_class` (`A` or `B`; school bus dispatch
        requires `B`)"

        Design: Corner/errors/error_license_class_insufficient_on_confirm_returns_409
        """
        ctx = setup_ops_scenario(district_name="D-ERR17",
                                 driver_overrides={"license_class": "A"})
        assert ctx["driver"]["status"] == "ACTIVE"
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        resp = api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_LICENSE_CLASS_INSUFFICIENT, 409)


class TestConfirmSchemaAndReferential:
    def test_error_driver_required_on_confirm_returns_422(self, api):
        """PRD section 2.8: "Endpoint-level conditional presence is evaluated at
        this same stage, before any existence or state lookup — notably,
        confirming an assignment requires `driver_id` and `bus_id` together, and
        a payload missing either is rejected here with `ERR_DRIVER_REQUIRED`
        (HTTP 422)."

        Design: Corner/errors/error_driver_required_on_confirm_returns_422
        """
        ctx = setup_ops_scenario(district_name="D-ERR12", with_driver=False)
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        resp = api.confirm_assignment(
            assignments[0]["id"], {"driver_id": NON_EXISTENT_UUID}, OPS)
        validate_error(resp, ApiErrorId.ERR_DRIVER_REQUIRED, 422)

    def test_confirm_bus_district_mismatch_rejected(self, api):
        """PRD section 3.5: "The bus must be `IN_SERVICE`
        (`ERR_BUS_NOT_IN_SERVICE`) with its `next_inspection_due` on or after the
        day's `service_date` (`ERR_INSPECTION_OVERDUE`), must seat at least the
        route's `student_count` (`ERR_CAPACITY_INSUFFICIENT`, HTTP 422), and must
        belong to the same district as the contract being served
        (`ERR_BUS_DISTRICT_MISMATCH`)."

        Design: Corner/validations/confirm_bus_district_mismatch_rejected
        """
        ctx = setup_ops_scenario(district_name="D-VAL5A")
        other_district = create_district(name="D-VAL5B")
        foreign_bus = create_bus(other_district["id"], fleet_number="BV5")
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")

        resp = api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": foreign_bus["id"]}, OPS)
        validate_error(resp, ApiErrorId.ERR_BUS_DISTRICT_MISMATCH, 409)
        fetched = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert fetched["status"] == "PLANNED"


class TestConfirmStateRules:
    def test_idempotent_second_confirm_rejected(self, api):
        """PRD section 3.5: "While a service day stands `DISPATCH_OPEN`,
        `ContractorOps` builds coverage by confirming its `PLANNED` assignments."
        PRD section 2.8: "7. **From-state validity.** The entity must be in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/idempotent_second_confirm_rejected
        """
        ctx = setup_ops_scenario(district_name="D-SM12")
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        payload = {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])

        resp = api.confirm_assignment(assignments[0]["id"], payload, OPS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert fetched["status"] == "CONFIRMED"

    def test_invalid_transition_complete_from_planned_returns_409(self, api):
        """PRD section 3.5: "Completing the run moves `EN_ROUTE` to `COMPLETED`
        and records the actuals: `actual_start_minute`, `actual_end_minute` —
        which must be strictly later than the start, else
        `ERR_INVALID_TIME_RANGE` — and `actual_miles`, which is added to the
        bus's `odometer_miles`."
        PRD section 2.8: "7. **From-state validity.** The entity must be in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/invalid_transition_complete_from_planned_returns_409
        """
        ctx = setup_ops_scenario(district_name="D-SM2")
        _day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        confirm_assignment(assignments[0]["id"], ctx["driver"]["id"], ctx["bus"]["id"])

        resp = api.complete_assignment(
            assignments[0]["id"],
            {"actual_start_minute": 420, "actual_end_minute": 480, "actual_miles": 50},
            make_driver_headers(ctx["driver"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        fetched = validate_success(api.get_assignment(assignments[0]["id"], OPS))
        assert fetched["status"] == "CONFIRMED", "never started; stays CONFIRMED"
        assert fetched["billable"] is False


class TestConfirmImmediateConsistency:
    def test_immediate_consistency_confirm_visible_in_same_response(self, api):
        """PRD section 3.5: "A successful confirmation sets the assignment's
        driver and bus, adds the planned minutes to the driver's
        `weekly_assigned_minutes`, and recomputes the day's covered and
        uncovered counts."
        PRD section 1: "All side effects are atomic within the triggering
        request: when a credential expires, a bus fails inspection, or a contract
        is terminated, every downstream cancellation and recomputation lands in
        the same transaction."

        Design: Corner/consistency_model/immediate_consistency_confirm_visible_in_same_response
        """
        ctx = setup_ops_scenario(district_name="D-CON1")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")

        confirmed = validate_success(api.confirm_assignment(
            assignments[0]["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["driver_id"] == ctx["driver"]["id"], "same response"
        assert confirmed["bus_id"] == ctx["bus"]["id"]

        day_after = validate_success(api.get_service_day(day["id"], OPS))
        assert day_after["covered_routes"] == 1, (
            "parent aggregate already updated on the immediately following read")
        assert day_after["uncovered_routes"] == 0


class TestPriorityExistenceBeatsState:
    def _setup_cancelled_assignment(self, api):
        ctx = setup_ops_scenario(district_name="D-PC1")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        get_success_data(api.cancel_assignment(assignments[0]["id"],
                                               {"reason": "ops cleanup"}, OPS))
        return ctx, day, assignments[0]

    def test_missing_bus_reference_returns_not_found(self, api):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"
        PRD section 2.8: "4. **Existence.** Path identifiers are resolved first,
        then body foreign-key references — `contract_id`, `district_id`,
        `driver_id`, `bus_id`, `route_id`, `assignment_id`, and the
        uncovered/absorbing assignment identifiers of a doubling decision —
        validated left to right; the first missing reference yields
        `ERR_NOT_FOUND` (HTTP 404)."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_assignment_with_missing_bus_returns_not_found
        """
        ctx, _day, assignment = self._setup_cancelled_assignment(api)
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": NON_EXISTENT_UUID}, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_rejected_confirm_preserves_cancelled_state(self, api):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"
        PRD section 3.5: "Dispatch may also cancel outright: from `PLANNED` or
        `CONFIRMED`, an operator cancellation lands the assignment in terminal
        `CANCELLED` with `cancellation_reason` `OPS_CANCEL`"

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_assignment_with_missing_bus_returns_not_found
        """
        ctx, _day, assignment = self._setup_cancelled_assignment(api)
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": NON_EXISTENT_UUID}, OPS)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        fetched = validate_success(api.get_assignment(assignment["id"], OPS))
        assert fetched["status"] == "CANCELLED", "failed confirm mutates nothing"


class TestPriorityStateBeatsSafety:
    def _setup_cancelled_assignment_with_suspended_driver(self, api):
        ctx = setup_ops_scenario(district_name="D-PC2")
        suspend_driver(ctx["driver"]["id"], reason="Discipline")
        day, assignments = build_service_day(ctx["contract"]["id"], "2026-06-01")
        get_success_data(api.cancel_assignment(assignments[0]["id"], {}, OPS))
        return ctx, day, assignments[0]

    def test_state_rejection_precedes_driver_safety_check(self, api):
        """PRD section 2.8: "Every request passes through a fixed validation
        pipeline, and the order is part of the contract — when several checks
        would fail, the earliest one in this order determines the error
        returned:"
        PRD section 2.8: "7. **From-state validity.** The entity must be in a
        state from which the requested transition exists, else
        `ERR_INVALID_STATE` (HTTP 409)."
        PRD section 2.8: "9. **Driver dispatchability.** Where dispatch requires
        it: the driver's status is `ACTIVE` (`ERR_DRIVER_NOT_ACTIVE`), the driver
        holds an active CDL-B credential (`ERR_CREDENTIAL_EXPIRED`), holds an
        active S-endorsement (`ERR_ENDORSEMENT_MISSING`), and has `license_class`
        B (`ERR_LICENSE_CLASS_INSUFFICIENT`)." — the state rung precedes it.

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_assignment_with_suspended_driver_returns_409
        """
        ctx, _day, assignment = (
            self._setup_cancelled_assignment_with_suspended_driver(api))
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        # The state layer (from-state validity / terminal-state rejection) must
        # answer before the driver-dispatchability rung is ever consulted.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])
        assert resp.status_code == 409

    def test_rejected_confirm_leaves_assignment_and_driver_unchanged(self, api):
        """PRD section 3.5: "Dispatch may also cancel outright: from `PLANNED` or
        `CONFIRMED`, an operator cancellation lands the assignment in terminal
        `CANCELLED` with `cancellation_reason` `OPS_CANCEL`"
        PRD section 3.3: "An `action` of `SUSPEND` on an `ACTIVE` driver moves
        them to `SUSPENDED` with `suspension_reason` `DISCIPLINE` and fires the
        same assignment cascade: future `CONFIRMED` assignments on days dated on
        or after the clock date are cancelled with reason `DRIVER_SUSPENDED`, and
        each affected service day recomputes its `covered_routes`,
        `uncovered_routes`, and `shortage_flag`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_cancelled_assignment_with_suspended_driver_returns_409
        """
        ctx, _day, assignment = (
            self._setup_cancelled_assignment_with_suspended_driver(api))
        resp = api.confirm_assignment(
            assignment["id"],
            {"driver_id": ctx["driver"]["id"], "bus_id": ctx["bus"]["id"]}, OPS)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])

        fetched = validate_success(api.get_assignment(assignment["id"], OPS))
        assert fetched["status"] == "CANCELLED"
        driver = validate_success(api.get_driver(ctx["driver"]["id"], HR))
        assert driver["status"] == "SUSPENDED"
