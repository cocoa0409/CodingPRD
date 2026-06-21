"""Validation precedence, cross-entity state gates, and temporal/capacity overlap."""
import test_helpers as th


def test_blocked_customer_beats_window_full(api):
    """PRD §2.9: "they are evaluated in a fixed priority order so that the most
    fundamental failure is reported first."
    PRD §3.3: "The owning customer's `status` must be `ACTIVE`, or the request is
    rejected with `ERR_CUSTOMER_BLOCKED`"

    A BLOCKED customer scheduling into a FULL pickup window: the safety gate
    (priority 9, ERR_CUSTOMER_BLOCKED) precedes the capacity gate (priority 14,
    ERR_WINDOW_FULL).

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_beats_window_full_state_vs_safety
    """
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=1)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    filler = th.create_customer(zone_code="Z1")
    _, _, _, filler_order, _ = th.create_order_with_garments(
        customer=filler, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.schedule_order(filler_order, filler)  # window now FULL

    blocked = th.create_customer(zone_code="Z1")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=blocked, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.validate_success(api.block_customer(blocked["id"], th.admin_headers()))

    resp = api.schedule_order(order["id"], th.make_customer_headers(blocked["id"]))
    th.validate_error(resp, "ERR_CUSTOMER_BLOCKED", 403)


def test_blocked_customer_full_window_status_code_is_403(api):
    """PRD §2.1: "a `PlatformAdmin` may administratively move a customer to
    `BLOCKED`, after which that customer cannot create orders."
    PRD §3.3: "The owning customer's `status` must be `ACTIVE`, or the request is
    rejected with `ERR_CUSTOMER_BLOCKED`"

    The blocked-vs-full conflict resolves to the 403 safety error (not the 409
    capacity error): a second test of the same precedence pinning the HTTP status.

    Design: Difficulty/priority_pair_validation_conflict/blocked_customer_beats_window_full_state_vs_safety
    """
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=1)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    filler = th.create_customer(zone_code="Z1")
    _, _, _, filler_order, _ = th.create_order_with_garments(
        customer=filler, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.schedule_order(filler_order, filler)

    blocked = th.create_customer(zone_code="Z1")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=blocked, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.validate_success(api.block_customer(blocked["id"], th.admin_headers()))
    resp = api.schedule_order(order["id"], th.make_customer_headers(blocked["id"]))
    assert resp.status_code == 403, f"safety error returns 403, got {resp.status_code}"
    th.validate_error(resp, "ERR_CUSTOMER_BLOCKED", 403)


def test_invalid_state_beats_delivery_before_ready(api):
    """PRD §2.9: "they are evaluated in a fixed priority order so that the most
    fundamental failure is reported first."
    PRD §3.6: "Dispatch requires the order to be in `READY` (otherwise
    `ERR_INVALID_ORDER_STATE`)."

    dispatch-delivery on a PICKED_UP (not READY) order whose delivery window also
    starts before ready_by: the state gate (priority 7, ERR_INVALID_ORDER_STATE)
    precedes the temporal gate (priority 12, ERR_DELIVERY_BEFORE_READY).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_delivery_before_ready_state_vs_temporal
    """
    customer = th.create_customer(zone_code="Z1")
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=5)
    delivery = th.create_delivery_window(
        zone_code="Z1", stop_capacity=5,
        start_utc="2026-06-01T09:30:00Z", end_utc="2026-06-01T10:30:00Z")
    _, _, _, order, garments = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    th.pickup_order(order)  # now PICKED_UP, not READY

    resp = api.dispatch_delivery(order["id"], th.dispatch_headers())
    th.validate_error(resp, "ERR_INVALID_ORDER_STATE", 409)


def test_invalid_state_beats_delivery_before_ready_from_created(api):
    """PRD §3.6: "Dispatch requires the order to be in `READY` (otherwise
    `ERR_INVALID_ORDER_STATE`)."
    PRD §3.6: "The delivery window's `start_utc` must be at or after the order's
    `ready_by_utc`, or the request is rejected with `ERR_DELIVERY_BEFORE_READY`."

    A CREATED order (even further from READY, with no ready_by_utc yet) dispatched
    against an early-starting delivery window still fails on the state gate first.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_delivery_before_ready_state_vs_temporal
    """
    customer = th.create_customer(zone_code="Z1")
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=5)
    delivery = th.create_delivery_window(
        zone_code="Z1", stop_capacity=5,
        start_utc="2026-06-01T09:30:00Z", end_utc="2026-06-01T10:30:00Z")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    # order is CREATED; dispatch must report the state failure, not the temporal one
    resp = api.dispatch_delivery(order["id"], th.dispatch_headers())
    th.validate_error(resp, "ERR_INVALID_ORDER_STATE", 409)


def test_schedule_empty_garment_set_rejected(api):
    """PRD §3.3: "The order must carry at least one garment, or the request is
    rejected with `ERR_NO_GARMENTS`."

    Design: Difficulty/boundary_precision_check/schedule_empty_garment_set_rejected
    """
    customer, pickup, delivery = th.create_zone_setup()
    order = th.create_order(customer, pickup, delivery)  # no garments added
    resp = api.schedule_order(order["id"], th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_NO_GARMENTS", 409)


def test_schedule_succeeds_once_one_garment_added(api):
    """PRD §3.3: "The order must carry at least one garment, or the request is
    rejected with `ERR_NO_GARMENTS`."

    The lower boundary of the at-least-one rule: exactly one garment is enough to
    schedule successfully (no ERR_NO_GARMENTS), confirming the empty-set boundary
    is at zero, not one.

    Design: Difficulty/boundary_precision_check/schedule_empty_garment_set_rejected
    """
    customer, pickup, delivery = th.create_zone_setup()
    order = th.create_order(customer, pickup, delivery)
    th.add_garment(order["id"], customer["id"],
                   service_type="WASH_FOLD", declared_weight_grams=2000)
    resp = api.schedule_order(order["id"], th.make_customer_headers(customer["id"]))
    data = th.validate_success(resp)
    assert data["status"] == "SCHEDULED", \
        f"one garment is enough to schedule, got {data['status']}"


def test_start_processing_requires_all_garments_logged(api):
    """PRD §3.5: "This requires the order to be in `PICKED_UP` (otherwise
    `ERR_INVALID_ORDER_STATE`) and every garment on the order to be in
    `INTAKE_LOGGED`; if any garment has not been logged, the request is rejected
    with `ERR_GARMENTS_NOT_LOGGED`."

    Design: Difficulty/cross_entity_state_dependency/start_processing_requires_all_garments_logged
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 2000},
            {"service_type": "DRY_CLEAN", "declared_piece_count": 2},
        ])
    th.schedule_order(order, customer)
    th.pickup_order(order)
    th.log_intake(order, garments[0], actual_weight_grams=2000)  # only first logged
    resp = api.start_processing(order["id"], th.plant_headers())
    th.validate_error(resp, "ERR_GARMENTS_NOT_LOGGED", 409)


def test_start_processing_succeeds_when_every_garment_logged(api):
    """PRD §3.5: "every garment on the order to be in `INTAKE_LOGGED`; if any
    garment has not been logged, the request is rejected with
    `ERR_GARMENTS_NOT_LOGGED`."

    The satisfied side of the cross-entity gate: once BOTH garments are logged,
    start-processing succeeds and moves the order to IN_PROCESSING.

    Design: Difficulty/cross_entity_state_dependency/start_processing_requires_all_garments_logged
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[
            {"service_type": "WASH_FOLD", "declared_weight_grams": 2000},
            {"service_type": "DRY_CLEAN", "declared_piece_count": 2},
        ])
    th.schedule_order(order, customer)
    th.pickup_order(order)
    th.log_intake(order, garments[0], actual_weight_grams=2000)
    th.log_intake(order, garments[1], actual_piece_count=2)
    data = th.validate_success(api.start_processing(order["id"], th.plant_headers()))
    assert data["status"] == "IN_PROCESSING", \
        f"all-logged order starts processing, got {data['status']}"


def test_claim_approve_requires_garment_lost(api):
    """PRD §3.10: "for a garment-subject claim the referenced garment must be in
    `LOST`, or the approval is rejected with `ERR_CLAIM_GARMENT_NOT_LOST`."

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_garment_lost
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        actuals=[{"actual_piece_count": 1}],
    )  # garment is CLEANING, not LOST
    claim = th.file_claim(order, customer, subject_kind="GARMENT",
                          declared_value_cents=5000, garment=garments[0])
    th.investigate(claim)
    resp = api.approve_claim(claim["id"], th.adjuster_headers())
    th.validate_error(resp, "ERR_CLAIM_GARMENT_NOT_LOST", 409)


def test_claim_approve_succeeds_when_garment_lost(api):
    """PRD §3.10: "for a garment-subject claim the referenced garment must be in
    `LOST`, or the approval is rejected with `ERR_CLAIM_GARMENT_NOT_LOST`."
    PRD §3.10: "Approving moves the claim from `INVESTIGATING` to `APPROVED`"

    The satisfied side: once the subject garment IS LOST, approval succeeds and
    the claim becomes APPROVED.

    Design: Difficulty/cross_entity_state_dependency/claim_approve_requires_garment_lost
    """
    customer, pickup, delivery, order, garments = th.order_in_processing(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        actuals=[{"actual_piece_count": 1}],
    )
    th.mark_lost(order, garments[0])
    claim = th.file_claim(order, customer, subject_kind="GARMENT",
                          declared_value_cents=5000, garment=garments[0])
    th.investigate(claim)
    data = th.validate_success(api.approve_claim(claim["id"], th.adjuster_headers()))
    assert data["status"] == "APPROVED", \
        f"claim on a LOST garment approves, got {data['status']}"


def test_locker_compartment_buffered_overlap_rejected(api):
    """PRD §3.9: "The system rejects a new assignment whose occupation interval
    overlaps that of any existing non-terminal assignment in the same compartment
    of the same locker, where the comparison extends each existing occupation by
    the locker's `hold_buffer_minutes` turnaround buffer so that two bags in one
    compartment are separated by at least that cleaning buffer; a collision is
    reported as `ERR_LOCKER_COMPARTMENT_CONFLICT`."

    Compartment 1 held 09:00-10:00; a second assignment at 10:15-11:00 (gap 15 <
    buffer 30) is rejected even though raw intervals do not overlap.

    Design: Difficulty/resource_temporal_overlap/locker_compartment_buffered_overlap_rejected
    """
    locker = th.create_locker(zone_code="Z1", compartment_count=2, hold_buffer_minutes=30)
    customer, pickup, delivery = th.create_zone_setup()

    _, _, _, order_a, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    th.create_locker_assignment(order_a, locker, compartment_index=1,
                                hold_start_utc="2026-06-03T09:00:00Z",
                                hold_end_utc="2026-06-03T10:00:00Z")

    _, _, _, order_b, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    payload = th.create_locker_assignment_payload(
        order_b["id"], locker["id"], compartment_index=1,
        hold_start_utc="2026-06-03T10:15:00Z", hold_end_utc="2026-06-03T11:00:00Z")
    resp = api.create_locker_assignment(payload, th.dispatch_headers())
    th.validate_error(resp, "ERR_LOCKER_COMPARTMENT_CONFLICT", 409)


def test_locker_conflict_does_not_apply_to_other_compartment(api):
    """PRD §3.9: "The system rejects a new assignment whose occupation interval
    overlaps that of any existing non-terminal assignment in the same compartment
    of the same locker"

    The conflict is per-compartment: a buffer-violating interval in a DIFFERENT
    compartment of the same locker is accepted, proving the overlap check is
    scoped to the same compartment.

    Design: Difficulty/resource_temporal_overlap/locker_compartment_buffered_overlap_rejected
    """
    locker = th.create_locker(zone_code="Z1", compartment_count=2, hold_buffer_minutes=30)
    customer, pickup, delivery = th.create_zone_setup()

    _, _, _, order_a, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    th.create_locker_assignment(order_a, locker, compartment_index=1,
                                hold_start_utc="2026-06-03T09:00:00Z",
                                hold_end_utc="2026-06-03T10:00:00Z")

    _, _, _, order_b, _ = th.order_at_ready(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    payload = th.create_locker_assignment_payload(
        order_b["id"], locker["id"], compartment_index=2,
        hold_start_utc="2026-06-03T10:15:00Z", hold_end_utc="2026-06-03T11:00:00Z")
    resp = api.create_locker_assignment(payload, th.dispatch_headers())
    data = th.validate_success(resp, expected_status=201)
    assert data["compartment_index"] == 2, "assignment lands in compartment 2"
    assert data["status"] == "RESERVED"


def test_route_window_capacity_overlap_rejected(api):
    """PRD §3.3: "the pickup window must have spare capacity - its `booked_stops`
    must be strictly less than its `stop_capacity` - or the booking is rejected
    with `ERR_WINDOW_FULL`."

    A second booking into a stop_capacity=1 pickup window is rejected by aggregate
    capacity (booked_stops vs stop_capacity), not interval geometry.

    Design: Difficulty/resource_temporal_overlap/route_window_capacity_overlap_rejected
    """
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=1)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    filler = th.create_customer(zone_code="Z1")
    _, _, _, filler_order, _ = th.create_order_with_garments(
        customer=filler, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.schedule_order(filler_order, filler)  # window now full

    customer = th.create_customer(zone_code="Z1")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    resp = api.schedule_order(order["id"], th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_WINDOW_FULL", 409)


def test_route_window_capacity_boundary_last_slot_succeeds(api):
    """PRD §3.3: "the pickup window must have spare capacity - its `booked_stops`
    must be strictly less than its `stop_capacity` - or the booking is rejected
    with `ERR_WINDOW_FULL`."

    The X-1 boundary: into a stop_capacity=2 window already holding one stop, a
    second booking still has spare capacity (booked_stops 1 < 2) and succeeds,
    bringing booked_stops to 2.

    Design: Difficulty/resource_temporal_overlap/route_window_capacity_overlap_rejected
    """
    pickup = th.create_pickup_window(zone_code="Z1", stop_capacity=2)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    filler = th.create_customer(zone_code="Z1")
    _, _, _, filler_order, _ = th.create_order_with_garments(
        customer=filler, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    th.schedule_order(filler_order, filler)  # booked_stops 1 of 2

    customer = th.create_customer(zone_code="Z1")
    _, _, _, order, _ = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 1000}])
    data = th.validate_success(
        api.schedule_order(order["id"], th.make_customer_headers(customer["id"])))
    assert data["status"] == "SCHEDULED", \
        f"the last spare slot accepts the booking, got {data['status']}"
    window = th.validate_success(api.get_route_window(pickup["id"], th.dispatch_headers()))
    assert window["booked_stops"] == 2, f"booked_stops reaches capacity 2, got {window['booked_stops']}"
