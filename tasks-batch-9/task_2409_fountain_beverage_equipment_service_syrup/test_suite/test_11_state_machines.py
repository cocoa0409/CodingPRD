"""Declared start states and the refusals that guard every declared hop.

Each entity is inspected the instant it is created, then every action endpoint is
pushed from a state the contract does not declare it from. The refusal is always
409 and the target row is left exactly as it stood.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    activate_agreement,
    api_client,
    ApiErrorId,
    change_outlet_status,
    complete_task,
    compliance_hold_payload,
    create_agreement,
    create_agreement_payload,
    create_call,
    create_outlet,
    create_route,
    create_route_stop_payload,
    create_task,
    create_unit,
    create_van_stock,
    dispatch_call,
    dispatch_route_payload,
    arrive_call,
    outlet_status_change_payload,
    pin_clock,
    place_compliance_hold,
    place_service_hold,
    read_agreement,
    read_call,
    read_outlet,
    read_route,
    read_stop,
    read_task,
    read_unit,
    read_van_stock,
    recall_decision_payload,
    resolve_call,
    resolve_call_payload,
    service_hold_payload,
    skip_stop,
    skip_stop_payload,
    waive_task_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PLANNER = TEST_USERS["planner_headers"]
DRIVER = TEST_USERS["driver_headers"]
TECH = TEST_USERS["technician_headers"]
TECH_ALT = TEST_USERS["technician_alt_headers"]
OFFICER = TEST_USERS["officer_headers"]
OFFICER_ALT = TEST_USERS["officer_alt_headers"]

CLOCK = "2026-08-01T00:00:00Z"


def _outlet():
    """One freshly registered R-WEST outlet with the clock pinned."""
    pin_clock(CLOCK)
    return create_outlet(
        name="Riverside Diner", account_code="OUT-1001", region_code="R-WEST"
    )


def _outlet_and_draft_agreement():
    """An outlet plus one DRAFT agreement over an 8000-gallon commitment."""
    outlet = _outlet()
    agreement = create_agreement(
        outlet["id"],
        annual_commitment_gallons=8000,
        equipment_value_cents=480000,
    )
    return outlet, agreement


def _outlet_agreement_and_unit(activate=False):
    """An outlet, one agreement and one IN_SERVICE machine placed under it."""
    outlet, agreement = _outlet_and_draft_agreement()
    unit = create_unit(
        outlet["id"], agreement["id"],
        serial_number="SN-9001", installed_at="2025-11-01T00:00:00Z",
    )
    if activate:
        activate_agreement(agreement["id"])
    return outlet, agreement, unit


def _planned_route_with_one_stop():
    """A PLANNED route out of depot R-WEST carrying a single PENDING stop."""
    outlet = _outlet()
    route = create_route(
        route_code="RT-01", depot_region_code="R-WEST",
        service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
    )
    stop = validate_success(
        api_client.create_route_stop(
            route["id"],
            create_route_stop_payload(
                outlet["id"], route["version"], 1,
                "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
            ),
            PLANNER,
        ),
        201,
    )
    return outlet, route, stop


class TestDeclaredInitialStates:
    def test_a_freshly_drafted_agreement_carries_no_assessment_outputs_yet(self, api):
        """PRD §3.2: "Creation answers with 201, the agreement's `status` is `DRAFT`
        and its `version` is 1; its assessment outputs start empty, with
        `assessed_shortfall_gallons` and `assessed_fee_cents` at 0,
        `recall_exposure_cents` at 0, `exposure_variant` recorded as `BOOK_VALUE`,
        `assessment_period_start` and `assessment_period_end` null, and both
        `shortfall_assessed_by_user_id` and `recall_decided_by_user_id` null."

        Design: Corner/state_machines/placement_agreement_initial_state_draft_on_create
        """
        outlet = _outlet()

        agreement = validate_success(
            api.create_agreement(
                create_agreement_payload(
                    outlet["id"], outlet["version"],
                    annual_commitment_gallons=8000, equipment_value_cents=480000,
                ),
                ADMIN,
            ),
            201,
        )

        assert agreement["status"] == "DRAFT"
        assert agreement["version"] == 1
        assert agreement["free_on_loan"] is True
        assert agreement["shortfall_fee_cents_per_gallon"] == 50
        assert agreement["exposure_variant"] == "BOOK_VALUE"
        assert agreement["assessed_shortfall_gallons"] == 0
        assert agreement["assessed_fee_cents"] == 0
        assert agreement["recall_exposure_cents"] == 0
        assert agreement["assessment_period_start"] is None
        assert agreement["assessment_period_end"] is None
        assert agreement["shortfall_assessed_by_user_id"] is None
        assert agreement["recall_decided_by_user_id"] is None

    def test_a_new_machine_starts_in_service_and_unverified_at_once(self, api):
        """PRD §3.3: "A newly recorded unit answers 201 with `status` `IN_SERVICE`,
        `calibration_status` `UNVERIFIED`, `lifetime_dispensed_gallons` at 0,
        `gallons_at_last_filter_change` at 0, `brix_ratio_last_measured` null and
        `version` 1."

        Design: Corner/state_machines/dispenser_unit_initial_states_on_both_dimensions
        """
        outlet, agreement = _outlet_and_draft_agreement()

        unit = validate_success(
            api.create_dispenser_unit(
                {
                    "outlet_id": outlet["id"],
                    "agreement_id": agreement["id"],
                    "serial_number": "SN-9001",
                    "model_code": "FREESTYLE_9100",
                    "installed_at": "2025-11-01T00:00:00Z",
                },
                ADMIN,
            ),
            201,
        )

        assert unit["status"] == "IN_SERVICE"
        assert unit["calibration_status"] == "UNVERIFIED"
        assert unit["brix_ratio_last_measured"] is None
        assert unit["lifetime_dispensed_gallons"] == 0
        assert unit["gallons_at_last_filter_change"] == 0
        assert unit["version"] == 1

    def test_a_new_route_is_planned_and_its_first_stop_is_pending(self, api):
        """PRD §3.7: "Planning answers 201 with `status` `PLANNED`, `committed_units`
        at 0, `delivered_units` at 0 and `version` 1."

        PRD §3.7: "A created stop answers 201 with `status` `PENDING`,
        `delivered_units` at 0, `skip_reason_code` null and `version` 1, and the
        owning route's `version` also increments by one."

        Design: Corner/state_machines/route_and_stop_initial_states_planned_and_pending
        """
        outlet = _outlet()

        route = validate_success(
            api.create_route(
                {
                    "route_code": "RT-01",
                    "depot_region_code": "R-WEST",
                    "service_date": "2026-08-03T00:00:00Z",
                    "van_code": "VAN-7",
                    "capacity_units": 60,
                },
                PLANNER,
            ),
            201,
        )
        assert route["status"] == "PLANNED"
        assert route["committed_units"] == 0
        assert route["delivered_units"] == 0
        assert route["version"] == 1

        stop = validate_success(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(
                    outlet["id"], route["version"], 1,
                    "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z",
                ),
                PLANNER,
            ),
            201,
        )
        assert stop["status"] == "PENDING"
        assert stop["delivered_units"] == 0
        assert stop["skip_reason_code"] is None
        assert stop["version"] == 1
        assert read_route(route["id"])["version"] == 2

    def test_a_reported_call_starts_open_with_nothing_dispatched(self, api):
        """PRD §3.8: "Creation answers 201 with `status` `OPEN`, `van_code`,
        `scheduled_window_start`, `scheduled_window_end`, `assigned_tech_user_id`,
        `reserved_part_stock_id` and `resolution_code` all null,
        `reserved_part_units`, `consumed_part_units` and `escalation_count` all 0,
        and `version` 1."

        Design: Corner/state_machines/service_call_initial_state_open_with_null_dispatch_fields
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit(activate=True)

        call = validate_success(
            api.create_service_call(
                {
                    "dispenser_unit_id": unit["id"],
                    "reported_at": CLOCK,
                    "symptom_code": "CO2_LOW",
                },
                ADMIN,
            ),
            201,
        )

        assert call["status"] == "OPEN"
        assert call["van_code"] is None
        assert call["scheduled_window_start"] is None
        assert call["scheduled_window_end"] is None
        assert call["assigned_tech_user_id"] is None
        assert call["reserved_part_stock_id"] is None
        assert call["resolution_code"] is None
        assert call["reserved_part_units"] == 0
        assert call["consumed_part_units"] == 0
        assert call["escalation_count"] == 0
        assert call["version"] == 1


class TestAgreementTransitionGuards:
    def test_activating_an_already_active_agreement_is_refused(self, api):
        """PRD §3.2: "It requires three things at once: the agreement must actually
        be in `DRAFT`, the owning outlet's `status` must be `ACTIVE`, and at least
        one dispenser unit must already reference this agreement."

        Design: Corner/state_machines/activate_already_active_agreement_returns_invalid_state_transition
        """
        _outlet, agreement, _unit = _outlet_agreement_and_unit(activate=True)
        activated = read_agreement(agreement["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == 2

        response = api.activate_agreement(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_agreement(agreement["id"])
        assert after["status"] == "ACTIVE"
        assert after["version"] == 2

    def test_an_agreement_with_no_equipment_cannot_be_activated(self, api):
        """PRD §3.2: "An agreement with no equipment recorded against it cannot be
        activated, and the refusal is `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/activate_agreement_without_dispenser_unit_returns_invalid_state_transition
        """
        _outlet, agreement = _outlet_and_draft_agreement()

        response = api.activate_agreement(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_agreement(agreement["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1

    def test_a_suspended_outlet_cannot_have_its_agreement_activated(self, api):
        """PRD §3.2: "Activation moves the agreement `DRAFT → ACTIVE` and is
        available to a `NetworkAdmin` with no request body."

        Design: Corner/state_machines/activate_agreement_on_suspended_outlet_returns_invalid_state_transition
        """
        outlet, agreement, _unit = _outlet_agreement_and_unit()
        change_outlet_status(outlet["id"], "SUSPEND")

        response = api.activate_agreement(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        assert read_outlet(outlet["id"])["status"] == "SUSPENDED"
        after = read_agreement(agreement["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1

    def test_closing_the_term_of_a_draft_agreement_fails_on_the_state_not_the_clock(
        self, api
    ):
        """PRD §2.6: "The target resource must currently sit in a state from which
        the requested transition is declared in §3."

        Design: Corner/state_machines/close_term_on_draft_agreement_returns_invalid_state_transition
        """
        _outlet, agreement, _unit = _outlet_agreement_and_unit()

        response = api.close_term(agreement["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_agreement(agreement["id"])
        assert after["status"] == "DRAFT"
        assert after["version"] == 1

    def test_a_recall_decision_needs_an_agreement_under_review(self, api):
        """PRD §3.9: "The **recall decision** then belongs to a `ComplianceOfficer`,
        who submits an `outcome` of either `FEE_ONLY` or `RECALL` on an agreement
        sitting in `SHORTFALL_REVIEW`."

        Design: Corner/state_machines/recall_decision_on_active_agreement_returns_invalid_state_transition
        """
        _outlet, agreement, unit = _outlet_agreement_and_unit(activate=True)

        response = api.recall_decision(
            agreement["id"], recall_decision_payload("RECALL"), OFFICER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_agreement(agreement["id"])
        assert after["status"] == "ACTIVE"
        assert after["recall_decided_by_user_id"] is None
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"


class TestRouteAndStopTransitionGuards:
    def test_a_driver_cannot_arrive_before_the_route_is_dispatched(self, api):
        """PRD §3.7: "Arriving at a stop moves it `PENDING → ARRIVED` and is legal
        only while the owning route is `DISPATCHED`."

        Design: Corner/state_machines/arrive_stop_while_route_still_planned_returns_invalid_state_transition
        """
        _outlet, route, stop = _planned_route_with_one_stop()

        response = api.arrive_stop(stop["id"], DRIVER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        assert read_stop(stop["id"])["status"] == "PENDING"
        assert read_route(route["id"])["status"] == "PLANNED"

    def test_a_second_skip_cannot_rewrite_the_recorded_reason(self, api):
        """PRD §3.7: "Both `SERVED` and `SKIPPED` are terminal; a stop never leaves
        either."

        Design: Corner/state_machines/skip_already_skipped_stop_returns_invalid_state_transition
        """
        _outlet, _route, stop = _planned_route_with_one_stop()
        skipped = skip_stop(stop["id"], "ACCESS_DENIED")
        assert skipped["status"] == "SKIPPED"

        response = api.skip_stop(
            stop["id"], skip_stop_payload("OUTLET_CLOSED"), DRIVER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_stop(stop["id"])
        assert after["status"] == "SKIPPED"
        assert after["skip_reason_code"] == "ACCESS_DENIED"
        assert after["version"] == skipped["version"]

    def test_a_route_with_no_stops_cannot_be_dispatched(self, api):
        """PRD §3.7: "It requires `expected_route_version`, and it requires that the
        route has at least one stop and that its `committed_units` do not exceed its
        `capacity_units`; the move is `PLANNED → DISPATCHED` and the route's
        `version` advances by one."

        Design: Corner/state_machines/dispatch_route_without_stops_returns_invalid_state_transition
        """
        pin_clock(CLOCK)
        route = create_route(
            route_code="RT-01", depot_region_code="R-WEST",
            service_date="2026-08-03T00:00:00Z", van_code="VAN-7", capacity_units=60,
        )
        assert route["version"] == 1

        response = api.dispatch_route(
            route["id"], dispatch_route_payload(route["version"]), PLANNER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_route(route["id"])
        assert after["status"] == "PLANNED"
        assert after["version"] == 1

    def test_a_route_still_holding_a_pending_stop_cannot_be_completed(self, api):
        """PRD §3.7: "Completion moves it `DISPATCHED → COMPLETED`, takes no request
        body and no expected-version field, and is permitted only once every stop of
        the route has reached `SERVED` or `SKIPPED`; it recomputes the route's
        `delivered_units` as the sum of `delivered_units` over its `SERVED` stops and
        advances the route's `version` by one."

        Design: Corner/state_machines/complete_route_with_pending_stop_returns_invalid_state_transition
        """
        _outlet, route, stop = _planned_route_with_one_stop()
        dispatched = validate_success(
            api.dispatch_route(
                route["id"],
                dispatch_route_payload(read_route(route["id"])["version"]),
                PLANNER,
            )
        )
        assert dispatched["status"] == "DISPATCHED"

        response = api.complete_route(route["id"], PLANNER)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_route(route["id"])
        assert after["status"] == "DISPATCHED"
        assert after["delivered_units"] == 0
        assert read_stop(stop["id"])["status"] == "PENDING"


class TestServiceCallTransitionGuards:
    def test_an_undispatched_call_cannot_be_resolved(self, api):
        """PRD §3.8: "Resolution moves the call `ON_SITE → RESOLVED`, which is
        terminal."

        PRD §2.6: "The target resource must currently sit in a state from which the
        requested transition is declared in §3."

        Design: Corner/state_machines/resolve_service_call_from_open_returns_invalid_state_transition
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit(activate=True)
        call = create_call(unit["id"], "LEAK", CLOCK)
        assert call["status"] == "OPEN"

        response = api.resolve_service_call(
            call["id"], resolve_call_payload("CLEANED"), TECH
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_call(call["id"])
        assert after["status"] == "OPEN"
        assert after["resolution_code"] is None

    def test_a_resolved_call_cannot_be_cancelled_afterwards(self, api):
        """PRD §3.8: "Cancellation is available to the `OutletManager` who owns the
        outlet or to a `NetworkAdmin`, from `OPEN` or from `DISPATCHED`, and drives
        the call to the terminal `CANCELLED`."

        Design: Corner/state_machines/cancel_resolved_service_call_returns_invalid_state_transition
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit(activate=True)
        stock = create_van_stock("VAN-7", "PUMP_ASSY_12", 5)
        call = create_call(unit["id"], "NO_POUR", CLOCK)
        dispatch_call(
            call["id"], "VAN-7", "2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z", TECH,
            part_sku="PUMP_ASSY_12", part_units=2,
        )
        arrive_call(call["id"], TECH)
        resolved = resolve_call(call["id"], "PART_REPLACED", TECH, consumed_part_units=2)

        response = api.cancel_service_call(call["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_call(call["id"])
        assert after["status"] == "RESOLVED"
        assert after["resolution_code"] == "PART_REPLACED"
        assert after["consumed_part_units"] == 2
        assert after["version"] == resolved["version"]

        van = read_van_stock(stock["id"])
        assert van["on_van_units"] == 3
        assert van["reserved_units"] == 0
        assert van["consumed_units"] == 2


class TestUnitServiceDimension:
    def test_holding_a_machine_that_is_already_held_is_refused(self, api):
        """PRD §3.3: "`PLACE` moves the unit `IN_SERVICE → SERVICE_HOLD`; `RELEASE`
        moves it `SERVICE_HOLD → IN_SERVICE`, but is blocked while any maintenance
        task of that unit whose `task_type` is `SANITATION` sits in `OVERDUE`, in
        which case the release is refused with `ERR_SANITATION_OVERDUE`."

        Design: Corner/state_machines/service_hold_place_twice_returns_invalid_state_transition
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        held = place_service_hold(unit["id"], TECH)
        assert held["status"] == "SERVICE_HOLD"

        response = api.unit_service_hold(
            unit["id"], service_hold_payload("PLACE"), TECH
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_unit(unit["id"])
        assert after["status"] == "SERVICE_HOLD"
        assert after["version"] == held["version"]

    def test_a_clean_machine_walks_out_of_the_hold_and_back_in_service(self, api):
        """PRD §3.3: "Either action increments the unit's `version` by one."

        Design: Corner/state_machines/service_hold_place_then_release_returns_unit_to_in_service
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        assert unit["version"] == 1

        held = validate_success(
            api.unit_service_hold(unit["id"], service_hold_payload("PLACE"), TECH)
        )
        assert held["status"] == "SERVICE_HOLD"
        assert held["version"] == 2
        assert held["calibration_status"] == "UNVERIFIED"

        released = validate_success(
            api.unit_service_hold(unit["id"], service_hold_payload("RELEASE"), TECH)
        )
        assert released["status"] == "IN_SERVICE"
        assert released["version"] == 3
        assert released["calibration_status"] == "UNVERIFIED"


class TestOutletStandingGuards:
    def test_releasing_a_hold_that_was_never_placed_is_refused(self, api):
        """PRD §3.1: "`RELEASE` requires `open_compliance_hold_count` to be exactly
        1, returns it to 0, **retains** `last_hold_placed_by_user_id` at its current
        value as the audit trail that powers the waiver separation of §2.12,
        recomputes `service_posture` — which will settle on `FROZEN`, `RESTRICTED` or
        `OPEN` purely according to how many overdue tasks the outlet still carries —
        and increments `version` by one."

        Design: Corner/state_machines/compliance_hold_release_without_open_hold_returns_invalid_state_transition
        """
        outlet = _outlet()
        assert outlet["open_compliance_hold_count"] == 0

        response = api.outlet_compliance_hold(
            outlet["id"], compliance_hold_payload("RELEASE", "AUDIT_CLEARED"), OFFICER
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_outlet(outlet["id"])
        assert after["open_compliance_hold_count"] == 0
        assert after["service_posture"] == "OPEN"
        assert after["version"] == outlet["version"]

    def test_a_suspended_outlet_carrying_an_open_hold_cannot_be_reinstated(self, api):
        """PRD §3.1: "`REINSTATE` drives it `SUSPENDED → ACTIVE`, and is legal only
        while no compliance hold is open — a suspended outlet that still carries an
        open hold cannot be reinstated, and the attempt is refused as an illegal
        transition with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/reinstate_suspended_outlet_with_open_hold_returns_invalid_state_transition
        """
        outlet = _outlet()
        place_compliance_hold(outlet["id"], OFFICER)
        change_outlet_status(outlet["id"], "SUSPEND")

        response = api.outlet_status_change(
            outlet["id"], outlet_status_change_payload("REINSTATE"), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_outlet(outlet["id"])
        assert after["status"] == "SUSPENDED"
        assert after["open_compliance_hold_count"] == 1
        assert after["service_posture"] == "FROZEN"
        assert after["last_hold_placed_by_user_id"] == OFFICER["X-User-ID"]

    def test_an_outlet_keeping_one_machine_cannot_be_closed(self, api):
        """PRD §3.1: "`CLOSE` drives the outlet to `CLOSED` from either `ACTIVE` or
        `SUSPENDED`, and it is permitted only once every dispenser unit at that
        outlet has reached `RETURNED`; `CLOSED` is terminal and nothing leaves it."

        Design: Corner/state_machines/close_outlet_with_unreturned_unit_returns_invalid_state_transition
        """
        outlet, _agreement, unit = _outlet_agreement_and_unit()

        response = api.outlet_status_change(
            outlet["id"],
            outlet_status_change_payload("CLOSE", reason_code="CONTRACT_ENDED"),
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        assert read_outlet(outlet["id"])["status"] == "ACTIVE"
        assert read_unit(unit["id"])["status"] == "IN_SERVICE"


class TestMaintenanceTaskTerminalStates:
    def test_a_completed_task_cannot_be_completed_a_second_time(self, api):
        """PRD §3.5: "Completion writes `completed_at` from the logical clock and
        `completed_by_user_id` from the acting `X-User-ID`, moves the task to the
        terminal `COMPLETED` state and increments its `version` by one."

        Design: Corner/state_machines/complete_maintenance_task_twice_returns_invalid_state_transition
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "SANITATION", "2026-08-15T00:00:00Z")
        completed = complete_task(task["id"], TECH)

        response = api.complete_task(task["id"], TECH_ALT)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_task(task["id"])
        assert after["status"] == "COMPLETED"
        assert after["completed_by_user_id"] == TECH["X-User-ID"]
        assert after["completed_at"].startswith("2026-08-01T00:00:00")
        assert after["version"] == completed["version"]

    def test_a_completed_task_can_no_longer_be_waived(self, api):
        """PRD §3.5: "A `ComplianceOfficer` may waive a task from `DUE` or from
        `OVERDUE` — never from `SCHEDULED`, and never once it is terminal — by
        supplying a free-text `waiver_reason`."

        Design: Corner/state_machines/waive_completed_task_returns_invalid_state_transition
        """
        _outlet, _agreement, unit = _outlet_agreement_and_unit()
        task = create_task(unit["id"], "PREVENTIVE", "2026-08-15T00:00:00Z")
        complete_task(task["id"], TECH)

        response = api.waive_task(
            task["id"], waive_task_payload("Retroactive paperwork fix"), OFFICER_ALT
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

        after = read_task(task["id"])
        assert after["status"] == "COMPLETED"
        assert after["waiver_reason"] is None
        assert after["waived_by_user_id"] is None
