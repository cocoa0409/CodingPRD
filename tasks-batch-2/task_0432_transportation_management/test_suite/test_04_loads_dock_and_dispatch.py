"""Load consolidation, dock appointments, dispatch, and the cross-entity /
priority guards layered over them.

Covers the capacity boundary, the half-open dock-overlap rule, optimistic
concurrency on consolidation, the state-vs-fiscal and state-vs-referential
priority conflicts, the depart-requires-dispatched cross-entity gate, and
the dispatch/close preconditions.
"""
from test_helpers import (
    TEST_USERS,
    validate_success, validate_error,
    assert_load, assert_dock_appointment,
    ApiErrorId,
    create_carrier_payload, create_load_payload, create_dock_appointment_payload,
    setup_carrier_rate, setup_consolidated_shipment, setup_dispatched_load,
    setup_in_transit_shipment, setup_tendered_shipment, setup_booked_shipment,
    setup_load_with_two_booked_shipments, setup_two_loads_one_appointment,
    create_order_payload, create_shipment_payload,
)

CARRIER = TEST_USERS["carrier_ops_headers"]
SHIPPER = TEST_USERS["shipper_ops_headers"]
DOCK = TEST_USERS["dock_ops_headers"]


class TestLoadCapacityBoundary:
    """Capacity guard fires strictly when the new total exceeds capacity."""

    def test_total_exactly_equal_to_capacity_allowed(self, api):
        """PRD §3.6: "A new total exactly equal to the planned capacity is allowed;
        the rejection fires strictly when the new total would exceed capacity."

        Design: Difficulty/boundary_precision_check/load_capacity_equal_allowed_over_rejected
        """
        ctx = setup_load_with_two_booked_shipments(
            planned_capacity_lbs=10000, ship1_weight=6000, ship2_weight=4000)
        load_v = validate_success(api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship1"]["id"], "expected_load_version": ctx["load_version"]},
            DOCK), 200)
        resp = api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship2"]["id"], "expected_load_version": load_v["version"]},
            DOCK)
        data = validate_success(resp, 200)
        assert_load(data)
        assert data["consolidated_weight_lbs"] == 10000

    def test_total_one_over_capacity_rejected(self, api):
        """PRD §3.6: "if the load's consolidated weight before the add, plus the
        incoming shipment's weight, would be greater than the load's planned
        capacity, the add is rejected with `ERR_LOAD_CAPACITY_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/load_capacity_equal_allowed_over_rejected
        """
        ctx = setup_load_with_two_booked_shipments(
            planned_capacity_lbs=10000, ship1_weight=6000, ship2_weight=4001)
        load_v = validate_success(api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship1"]["id"], "expected_load_version": ctx["load_version"]},
            DOCK), 200)
        resp = api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship2"]["id"], "expected_load_version": load_v["version"]},
            DOCK)
        validate_error(resp, ApiErrorId.ERR_LOAD_CAPACITY_EXCEEDED.value)


class TestDockHalfOpenBoundary:
    """Dock appointment windows are half-open; touching at a boundary is not overlap."""

    def test_touching_at_boundary_is_not_overlap(self, api):
        """PRD §3.7: "because the window is half-open, two appointments that merely
        touch at a boundary — one ending exactly where the next begins — do not
        overlap."

        Design: Difficulty/boundary_precision_check/dock_halfopen_touching_boundary_not_overlap
        """
        ctx = setup_two_loads_one_appointment(dock_door="D1", appt_start=0, appt_end=60)
        resp = api.create_dock_appointment(create_dock_appointment_payload(
            load_id=ctx["load2"]["id"], dock_door="D1", start_minute=60, end_minute=120), DOCK)
        data = validate_success(resp, 201)
        assert_dock_appointment(data)
        assert data["status"] == "SCHEDULED"

    def test_new_window_ending_at_existing_start_is_not_overlap(self, api):
        """PRD §3.7: "The window is half-open, written `[start_minute, end_minute)`:
        it includes the start minute but not the end minute."
        PRD §3.7: "two appointments that merely touch at a boundary — one ending
        exactly where the next begins — do not overlap."

        Design: Difficulty/boundary_precision_check/dock_halfopen_touching_boundary_not_overlap
        """
        ctx = setup_two_loads_one_appointment(dock_door="D1", appt_start=60, appt_end=120)
        resp = api.create_dock_appointment(create_dock_appointment_payload(
            load_id=ctx["load2"]["id"], dock_door="D1", start_minute=0, end_minute=60), DOCK)
        data = validate_success(resp, 201)
        assert_dock_appointment(data)
        assert data["status"] == "SCHEDULED"

    def test_overlapping_window_is_double_booked(self, api):
        """PRD §3.7: "A new appointment whose window overlaps an existing
        `SCHEDULED` or `CHECKED_IN` appointment on the same `dock_door` is rejected
        with `ERR_DOCK_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/dock_appointment_overlap_halfopen_per_door
        """
        ctx = setup_two_loads_one_appointment(dock_door="D1", appt_start=0, appt_end=60)
        resp = api.create_dock_appointment(create_dock_appointment_payload(
            load_id=ctx["load2"]["id"], dock_door="D1", start_minute=30, end_minute=90), DOCK)
        validate_error(resp, ApiErrorId.ERR_DOCK_DOUBLE_BOOKED.value)

    def test_partial_overlap_on_same_door_rejected(self, api):
        """PRD §3.7: "Appointments on the same door may not overlap"
        PRD §3.7: "A new appointment whose window overlaps an existing `SCHEDULED`
        or `CHECKED_IN` appointment on the same `dock_door` is rejected with
        `ERR_DOCK_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/dock_appointment_overlap_halfopen_per_door
        """
        ctx = setup_two_loads_one_appointment(dock_door="D1", appt_start=0, appt_end=60)
        resp = api.create_dock_appointment(create_dock_appointment_payload(
            load_id=ctx["load2"]["id"], dock_door="D1", start_minute=10, end_minute=50), DOCK)
        validate_error(resp, ApiErrorId.ERR_DOCK_DOUBLE_BOOKED.value)


class TestOptimisticConcurrency:
    """OCC on Load.version for consolidation."""

    def test_stale_expected_version_rejected(self, api):
        """PRD §2.9: "If that value does not equal the load's current `version`,
        the request is rejected with `ERR_STALE_LOAD_VERSION` and HTTP status 412."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_load_version_rejected
        """
        ctx = setup_load_with_two_booked_shipments(
            planned_capacity_lbs=20000, ship1_weight=6000, ship2_weight=4000)
        validate_success(api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship1"]["id"], "expected_load_version": ctx["load_version"]},
            DOCK), 200)
        resp = api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship2"]["id"], "expected_load_version": ctx["load_version"]},
            DOCK)
        validate_error(resp, ApiErrorId.ERR_STALE_LOAD_VERSION.value)

    def test_correct_version_succeeds_and_bumps_version(self, api):
        """PRD §3.6: "A successful add sets the shipment's `load_id` to this load,
        recomputes the consolidated weight, and increments the load's version by
        one."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_and_bumps
        """
        ctx = setup_load_with_two_booked_shipments(
            planned_capacity_lbs=10000, ship1_weight=6000, ship2_weight=4000)
        data = validate_success(api.add_shipment_to_load(
            ctx["load_id"],
            {"shipment_id": ctx["ship1"]["id"], "expected_load_version": ctx["load_version"]},
            DOCK), 200)
        assert data["version"] == 2
        assert data["consolidated_weight_lbs"] == 6000


class TestValidationPriorityConflicts:
    """A resource's state precondition is checked before quantitative/referential guards."""

    def test_load_state_beats_capacity_on_add_shipment(self, api):
        """PRD §2.8: "Within the business tier, a resource's state precondition is
        checked before the cross-entity and quantitative guards layered on top of
        it."
        PRD §3.6: "Adding a shipment to a load is permitted only while the load is
        `BUILDING`; an attempt on a non-building load is rejected with
        `ERR_LOAD_NOT_BUILDING`."

        Design: Difficulty/priority_pair_validation_conflict/load_state_beats_capacity_fiscal_on_add_shipment
        """
        # Load capacity 5000, dispatched with one 4000-lb shipment, then attempt a 6000-lb add.
        carrier, _ = setup_carrier_rate()
        order1 = validate_success(api.create_order(
            create_order_payload(customer_ref="C1", weight_lbs=4000, declared_value_cents=100000), SHIPPER), 201)
        ship1 = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order1["id"], weight_lbs=4000), SHIPPER), 201)
        tender1 = validate_success(api.create_tender(ship1["id"], {"tender_minute": 100}, SHIPPER), 201)
        validate_success(api.accept_tender(tender1["id"], CARRIER), 200)
        load = validate_success(api.create_load(
            create_load_payload(carrier_id=carrier["id"], planned_capacity_lbs=5000), DOCK), 201)
        validate_success(api.add_shipment_to_load(
            load["id"], {"shipment_id": ship1["id"], "expected_load_version": load["version"]}, DOCK), 200)
        validate_success(api.create_dock_appointment(create_dock_appointment_payload(
            load_id=load["id"], dock_door="D1", start_minute=200, end_minute=260), DOCK), 201)
        dispatched = validate_success(api.dispatch_load(load["id"], DOCK), 200)

        order2 = validate_success(api.create_order(
            create_order_payload(customer_ref="C2", weight_lbs=6000, declared_value_cents=100000), SHIPPER), 201)
        ship2 = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order2["id"], weight_lbs=6000), SHIPPER), 201)
        tender2 = validate_success(api.create_tender(ship2["id"], {"tender_minute": 100}, SHIPPER), 201)
        validate_success(api.accept_tender(tender2["id"], CARRIER), 200)

        resp = api.add_shipment_to_load(
            load["id"], {"shipment_id": ship2["id"], "expected_load_version": dispatched["version"]}, DOCK)
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_BUILDING.value)

    def test_dispatched_load_rejects_add_even_when_within_capacity(self, api):
        """PRD §3.6: "Adding a shipment to a load is permitted only while the load
        is `BUILDING`; an attempt on a non-building load is rejected with
        `ERR_LOAD_NOT_BUILDING`."
        PRD §2.8: "Within the business tier, a resource's state precondition is
        checked before the cross-entity and quantitative guards layered on top of
        it."

        Design: Difficulty/priority_pair_validation_conflict/load_state_beats_capacity_fiscal_on_add_shipment
        """
        # Load dispatched with a 4000-lb shipment; capacity 20000 leaves ample headroom,
        # so a second 4000-lb add would fit on capacity — yet the non-BUILDING state wins.
        carrier, _ = setup_carrier_rate()
        order1 = validate_success(api.create_order(
            create_order_payload(customer_ref="C1", weight_lbs=4000, declared_value_cents=100000), SHIPPER), 201)
        ship1 = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order1["id"], weight_lbs=4000), SHIPPER), 201)
        tender1 = validate_success(api.create_tender(ship1["id"], {"tender_minute": 100}, SHIPPER), 201)
        validate_success(api.accept_tender(tender1["id"], CARRIER), 200)
        load = validate_success(api.create_load(
            create_load_payload(carrier_id=carrier["id"], planned_capacity_lbs=20000), DOCK), 201)
        validate_success(api.add_shipment_to_load(
            load["id"], {"shipment_id": ship1["id"], "expected_load_version": load["version"]}, DOCK), 200)
        validate_success(api.create_dock_appointment(create_dock_appointment_payload(
            load_id=load["id"], dock_door="D1", start_minute=200, end_minute=260), DOCK), 201)
        dispatched = validate_success(api.dispatch_load(load["id"], DOCK), 200)

        order2 = validate_success(api.create_order(
            create_order_payload(customer_ref="C2", weight_lbs=4000, declared_value_cents=100000), SHIPPER), 201)
        ship2 = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order2["id"], weight_lbs=4000), SHIPPER), 201)
        tender2 = validate_success(api.create_tender(ship2["id"], {"tender_minute": 100}, SHIPPER), 201)
        validate_success(api.accept_tender(tender2["id"], CARRIER), 200)

        resp = api.add_shipment_to_load(
            load["id"], {"shipment_id": ship2["id"], "expected_load_version": dispatched["version"]}, DOCK)
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_BUILDING.value)

    def test_shipment_state_beats_load_referential_on_depart(self, api):
        """PRD §2.8: "Within the business tier, a resource's state precondition is
        checked before the cross-entity and quantitative guards layered on top of
        it."
        PRD §3.8: "the shipment must be `BOOKED` in its tender dimension (otherwise
        `ERR_SHIPMENT_NOT_BOOKED`), it must be `PENDING` in its execution dimension
        (otherwise `ERR_SHIPMENT_NOT_PENDING`), and it must be sitting on a load
        whose status is `DISPATCHED` — that is, its `load_id` is set and that load
        is dispatched, otherwise `ERR_LOAD_NOT_DISPATCHED`."

        Design: Difficulty/priority_pair_validation_conflict/shipment_state_beats_load_referential_on_depart
        """
        order = validate_success(api.create_order(create_order_payload(), SHIPPER), 201)
        ship = validate_success(api.create_shipment(
            create_shipment_payload(order_id=order["id"]), SHIPPER), 201)
        resp = api.depart_shipment(ship["id"], CARRIER)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_BOOKED.value)

    def test_tendered_not_booked_shipment_depart_reports_not_booked(self, api):
        """PRD §3.8: "the shipment must be `BOOKED` in its tender dimension
        (otherwise `ERR_SHIPMENT_NOT_BOOKED`), it must be `PENDING` in its execution
        dimension (otherwise `ERR_SHIPMENT_NOT_PENDING`), and it must be sitting on
        a load whose status is `DISPATCHED` — that is, its `load_id` is set and that
        load is dispatched, otherwise `ERR_LOAD_NOT_DISPATCHED`."
        PRD §2.8: "Within the business tier, a resource's state precondition is
        checked before the cross-entity and quantitative guards layered on top of
        it."

        Design: Difficulty/priority_pair_validation_conflict/shipment_state_beats_load_referential_on_depart
        """
        # Shipment is TENDERED (offered tender) but never booked, and has no load.
        # Both the BOOKED state check and the dispatched-load check fail; state wins.
        ctx = setup_tendered_shipment()
        resp = api.depart_shipment(ctx["shipment"]["id"], CARRIER)
        validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_BOOKED.value)


class TestDepartRequiresDispatchedLoad:
    """A booked shipment on a still-BUILDING load cannot depart."""

    def test_depart_on_building_load_rejected(self, api):
        """PRD §3.8: "it must be sitting on a load whose status is `DISPATCHED` —
        that is, its `load_id` is set and that load is dispatched, otherwise
        `ERR_LOAD_NOT_DISPATCHED`. A shipment cannot leave until the truck carrying
        it has been dispatched."

        Design: Difficulty/cross_entity_state_dependency/shipment_depart_requires_load_dispatched
        """
        ctx = setup_consolidated_shipment()  # load is BUILDING, not dispatched
        resp = api.depart_shipment(ctx["shipment"]["id"], CARRIER)
        validate_error(resp, ApiErrorId.ERR_LOAD_NOT_DISPATCHED.value)

    def test_depart_succeeds_once_load_dispatched(self, api):
        """PRD §3.8: "A `CarrierOps` operator departs a shipment, advancing its
        `execution_status` from `PENDING` to `IN_TRANSIT`."

        Design: Difficulty/cross_entity_state_dependency/shipment_depart_requires_load_dispatched
        """
        ctx = setup_dispatched_load()
        ship = validate_success(api.depart_shipment(ctx["shipment"]["id"], CARRIER), 200)
        assert ship["execution_status"] == "IN_TRANSIT"


def test_deliver_shipment_not_in_transit_returns_invalid_state(api):
    """PRD §3.8: "A `CarrierOps` operator delivers an in-transit shipment by
    supplying the `delivered_minute` at which it arrived; the shipment must be
    `IN_TRANSIT` (otherwise `ERR_SHIPMENT_NOT_IN_TRANSIT`)."

    Design: Corner/state_machines/deliver_shipment_not_in_transit_returns_invalid_state
    """
    # Booked shipment, still PENDING (never departed).
    ctx = setup_booked_shipment()
    resp = api.deliver_shipment(ctx["shipment"]["id"], {"delivered_minute": 400}, CARRIER)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_IN_TRANSIT.value)


def test_dispatch_empty_load_rejected(api):
    """PRD §3.7: "to carry a positive consolidated weight — that is, at least one
    non-cancelled shipment is consolidated, otherwise `ERR_EMPTY_LOAD`"

    Design: Corner/state_machines/dispatch_empty_load_rejected
    """
    carrier, _ = setup_carrier_rate()
    load = validate_success(api.create_load(create_load_payload(carrier_id=carrier["id"]), DOCK), 201)
    validate_success(api.create_dock_appointment(create_dock_appointment_payload(
        load_id=load["id"], dock_door="D1", start_minute=200, end_minute=260), DOCK), 201)
    resp = api.dispatch_load(load["id"], DOCK)
    validate_error(resp, ApiErrorId.ERR_EMPTY_LOAD.value)


def test_dispatch_load_without_dock_appointment_rejected(api):
    """PRD §3.7: "and to have at least one `SCHEDULED` or `CHECKED_IN` dock
    appointment, otherwise `ERR_NO_DOCK_APPOINTMENT`."

    Design: Corner/state_machines/dispatch_load_without_dock_appointment_rejected
    """
    ctx = setup_consolidated_shipment()  # consolidated but no dock appointment yet
    resp = api.dispatch_load(ctx["load_id"], DOCK)
    validate_error(resp, ApiErrorId.ERR_NO_DOCK_APPOINTMENT.value)


def test_load_close_with_undelivered_shipment_rejected(api):
    """PRD §3.7: "a `DockOps` operator closes the load, which requires it to be
    `DISPATCHED` (otherwise `ERR_LOAD_NOT_DISPATCHED`) and requires every
    non-cancelled shipment on the load to have reached `DELIVERED` (otherwise
    `ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS`)"

    Design: Corner/state_machines/load_close_with_undelivered_shipment_rejected
    """
    ctx = setup_in_transit_shipment()  # departed but not delivered
    resp = api.close_load(ctx["load_id"], DOCK)
    validate_error(resp, ApiErrorId.ERR_LOAD_HAS_UNDELIVERED_SHIPMENTS.value)


def test_release_appointment_not_checked_in_rejected(api):
    """PRD §3.7: "A checked-in appointment may be released, requiring it to be
    `CHECKED_IN` (otherwise `ERR_APPT_NOT_CHECKED_IN`)"

    Design: Corner/state_machines/release_appointment_not_checked_in_rejected
    """
    carrier, _ = setup_carrier_rate()
    load = validate_success(api.create_load(create_load_payload(carrier_id=carrier["id"]), DOCK), 201)
    appt = validate_success(api.create_dock_appointment(create_dock_appointment_payload(
        load_id=load["id"], dock_door="D1", start_minute=0, end_minute=60), DOCK), 201)
    resp = api.release_dock_appointment(appt["id"], DOCK)
    validate_error(resp, ApiErrorId.ERR_APPT_NOT_CHECKED_IN.value)


def test_list_shipments_filtered_by_load_id(api):
    """PRD §3.6: "The consolidated weight is always the sum of `weight_lbs` over
    every shipment whose `load_id` points at this load"
    PRD §4 (routing): "GET | `/tms/loads/{loadId}/shipments` | List shipments
    consolidated on a load".

    Design: Corner/endpoints/list_shipments_filtered_by_load_id
    """
    ctx = setup_consolidated_shipment()
    resp = api.list_load_shipments(ctx["load_id"], DOCK)
    data = validate_success(resp, 200)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["id"] == ctx["shipment"]["id"]
