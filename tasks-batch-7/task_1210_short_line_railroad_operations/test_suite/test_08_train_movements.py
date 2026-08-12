"""Train movement gates and terminal lockdown: segment-in-service readiness,
missing crew, unrated-waybill settle block, and SETTLED absorbing
(PRD §2.9, §3.4, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_call,
    api_client,
    create_customer,
    create_crew_call_for_movement,
    create_crew_member,
    create_inspection,
    create_movement,
    create_railcar,
    create_segment,
    create_waybill,
    setup_arrived_movement,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]
INSPECTOR = TEST_USERS["track_inspector_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _restricted_segment_with_movement():
    """Segment restricted by a CRITICAL defect, then a movement planned over it
    with an ACCEPTED crew call."""
    segment = create_segment(name="Main MP 70-74", milepost_start=70, milepost_end=74, fra_class="CLASS_3")
    inspection = create_inspection(segment["id"], scheduled_date="2026-05-01")
    validate_success(
        api_client.file_track_inspection(
            inspection["id"],
            {"defect_found": True, "defect_severity": "CRITICAL", "findings": "wide gauge"},
            INSPECTOR,
        )
    )
    movement = create_movement([segment["id"]], symbol="GW-701")
    member = create_crew_member(name="J. Conductor")
    call = create_crew_call_for_movement(member["id"], movement["id"])
    call = accept_call(call["id"], member["id"])
    return segment, inspection, movement, member, call


class TestReadySegmentGate:
    def test_ready_blocked_over_restricted_segment(self, api, dispatcher_headers):
        """PRD §3.4: "Readying a movement is a `Dispatcher` action with two gates:
        every segment in `route_segment_ids` must be `IN_SERVICE`, failing as
        `ERR_SEGMENT_NOT_IN_SERVICE`, and at least one crew call tied to the
        movement must be in `ACCEPTED` or `ON_DUTY`, failing as
        `ERR_MOVEMENT_NO_CREW`. Success moves the movement `PLANNED` → `READY`."

        Design: Difficulty/cross_entity_state_dependency/movement_ready_requires_segments_in_service
        """
        segment, inspection, movement, member, call = _restricted_segment_with_movement()
        assert call["status"] == "ACCEPTED"

        resp = api.ready_train_movement(movement["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_SEGMENT_NOT_IN_SERVICE)

        mov = validate_success(api.get_train_movement(movement["id"], dispatcher_headers))
        assert mov["status"] == "PLANNED", (
            f"a rejected ready must leave the movement PLANNED, got {mov['status']}"
        )

    def test_ready_succeeds_after_defect_remediated(self, api, dispatcher_headers, track_inspector_headers):
        """PRD §3.6: "Either action clears the segment's defect — `defect_open`
        false, `open_defect_severity` unset — and returns the segment from
        `RESTRICTED` to `IN_SERVICE`, provided it is not overdue, with
        `effective_speed_mph` recomputed on return."
        PRD §3.4: "Readying a movement is a `Dispatcher` action with two gates:
        every segment in `route_segment_ids` must be `IN_SERVICE`, failing as
        `ERR_SEGMENT_NOT_IN_SERVICE`, and at least one crew call tied to the
        movement must be in `ACCEPTED` or `ON_DUTY`, failing as
        `ERR_MOVEMENT_NO_CREW`. Success moves the movement `PLANNED` → `READY`."

        Design: Difficulty/cross_entity_state_dependency/movement_ready_requires_segments_in_service
        """
        segment, inspection, movement, member, call = _restricted_segment_with_movement()
        validate_success(api.remediate_track_inspection(inspection["id"], track_inspector_headers))
        seg = validate_success(api.get_track_segment(segment["id"], dispatcher_headers))
        assert seg["status"] == "IN_SERVICE", (
            f"remediating the open defect must return the segment to IN_SERVICE, got {seg['status']}"
        )

        ready = validate_success(api.ready_train_movement(movement["id"], dispatcher_headers))
        assert ready["status"] == "READY", (
            f"with the segment back IN_SERVICE and an ACCEPTED call, ready must succeed, got {ready['status']}"
        )


class TestMovementSettleGate:
    def test_movement_settled_terminal_lockdown(self, api, dispatcher_headers, settlement_clerk_headers):
        """PRD §3.5: "The movement itself stands `SETTLED`, terminal, with its
        `version` incremented."
        PRD §2.9: "Fourth, state legality: the target resource must be in a state
        from which the requested transition is defined, failing as
        `ERR_INVALID_STATE` (HTTP 409) — or the more specific state errors
        `ERR_ORDER_NOT_AMENDABLE` and `ERR_MEMBER_NOT_AVAILABLE` where §3 names
        them."

        Design: Corner/state_machines/movement_settled_terminal_lockdown
        """
        ctx = setup_arrived_movement(symbol="GW-901")
        settled = validate_success(api.settle_train_movement(ctx["movement"]["id"], settlement_clerk_headers))
        assert settled["status"] == "SETTLED", f"settle of an arrived movement must stand SETTLED, got {settled['status']}"

        resp = api.depart_train_movement(ctx["movement"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_movement_settle_blocked_by_unrated_waybill(self, api, dispatcher_headers, settlement_clerk_headers):
        """PRD §3.5: "The gate is that every waybill tied to the movement must
        already be `RATED` or `BILLED`; a waybill still in `CREATED` blocks
        settlement with `ERR_WAYBILL_NOT_RATED`."

        Design: Corner/state_machines/movement_settle_blocked_by_unrated_waybill
        """
        ctx = setup_arrived_movement(symbol="GW-903")
        customer = create_customer(name="Unrated Co", billing_email="u@x.example")
        railcar = create_railcar(reporting_mark="GNWR 8001", car_type="BOX")
        create_waybill(
            railcar["id"], customer["id"], movement_id=ctx["movement"]["id"],
            destination="Rochester", commodity="LUMBER", weight_tons=10, through_route=False,
        )

        resp = api.settle_train_movement(ctx["movement"]["id"], settlement_clerk_headers)
        validate_error(resp, ApiErrorId.ERR_WAYBILL_NOT_RATED)

        mov = validate_success(api.get_train_movement(ctx["movement"]["id"], dispatcher_headers))
        assert mov["status"] == "ARRIVED", (
            f"a blocked settle must leave the movement ARRIVED, got {mov['status']}"
        )


class TestReadyCrewGate:
    def test_movement_ready_without_crew_rejected(self, api, dispatcher_headers):
        """PRD §3.4: "Readying a movement is a `Dispatcher` action with two gates:
        every segment in `route_segment_ids` must be `IN_SERVICE`, failing as
        `ERR_SEGMENT_NOT_IN_SERVICE`, and at least one crew call tied to the
        movement must be in `ACCEPTED` or `ON_DUTY`, failing as
        `ERR_MOVEMENT_NO_CREW`. Success moves the movement `PLANNED` → `READY`."

        Design: Corner/errors/movement_ready_without_crew_rejected
        """
        segment = create_segment(name="Main MP 61-62", milepost_start=61, milepost_end=62, fra_class="CLASS_2")
        movement = create_movement([segment["id"]], symbol="GW-907")
        resp = api.ready_train_movement(movement["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_MOVEMENT_NO_CREW)
