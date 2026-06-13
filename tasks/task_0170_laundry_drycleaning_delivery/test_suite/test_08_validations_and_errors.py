"""Validation, endpoint-action, and error corners."""
import test_helpers as th


# --------------------------------------------------------------------------
# validations
# --------------------------------------------------------------------------
def test_service_type_field_mismatch_rejected(api):
    """PRD §3.2: "a `WASH_FOLD` line requires `declared_weight_grams` greater than
    zero with both the declared piece count and the alteration fee zero ... Any
    line whose measurement fields contradict its service type is rejected with
    `ERR_SERVICE_TYPE_FIELD_MISMATCH` at HTTP 422."

    WASH_FOLD with declared_piece_count>0 (and zero weight) is inconsistent.

    Design: Corner/validations/service_type_field_mismatch_rejected
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(garments=[])
    resp = api.add_garment(order["id"],
                           {"service_type": "WASH_FOLD", "declared_piece_count": 3},
                           th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_SERVICE_TYPE_FIELD_MISMATCH", 422)


def test_window_zone_mismatch_rejected(api):
    """PRD §3.3: "The chosen pickup window must have `window_kind` `PICKUP` and a
    `zone_code` equal to the customer's `zone_code`, or the request is rejected
    with `ERR_WINDOW_ZONE_MISMATCH`."

    Customer in Z1, pickup window in Z2.

    Design: Corner/validations/window_zone_mismatch_rejected
    """
    customer = th.create_customer(zone_code="Z1")
    pickup = th.create_pickup_window(zone_code="Z2", stop_capacity=5)
    delivery = th.create_delivery_window(zone_code="Z1", stop_capacity=5)
    _, _, _, order, _ = th.create_order_with_garments(
        customer=customer, pickup=pickup, delivery=delivery,
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    resp = api.schedule_order(order["id"], th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_WINDOW_ZONE_MISMATCH", 409)


def test_invalid_interval_on_route_window_rejected(api):
    """PRD §2.9: "a route window's `end_utc` must be strictly later than its
    `start_utc`" and these share "`ERR_INVALID_INTERVAL` at HTTP 400".

    Design: Corner/validations/invalid_interval_on_route_window_rejected
    """
    payload = th.create_route_window_payload(
        zone_code="Z1", window_kind="PICKUP",
        start_utc="2026-06-01T11:00:00Z", end_utc="2026-06-01T09:00:00Z", stop_capacity=5)
    resp = api.create_route_window(payload, th.dispatch_headers())
    th.validate_error(resp, "ERR_INVALID_INTERVAL", 400)


def test_claim_subject_mismatch_garment_id_missing(api):
    """PRD §3.10: "when `subject_kind` is `GARMENT` the `garment_id` must be
    present and must name a garment whose `order_id` equals the claim's
    `order_id` ... A subject inconsistency is rejected with
    `ERR_CLAIM_SUBJECT_MISMATCH` at HTTP 422."

    subject_kind=GARMENT with no garment_id.

    Design: Corner/validations/claim_subject_mismatch_garment_id_missing
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    ov = th.get_order(order["id"], customer["id"])["version"]
    payload = {
        "order_id": order["id"],
        "subject_kind": "GARMENT",
        "declared_value_cents": 5000,
        "expected_order_version": ov,
    }  # garment_id omitted
    resp = api.create_claim(payload, th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_CLAIM_SUBJECT_MISMATCH", 422)


# --------------------------------------------------------------------------
# endpoints
# --------------------------------------------------------------------------
def test_log_intake_missing_measurement_rejected(api):
    """PRD §3.4: "A wash-fold garment must be logged with `actual_weight_grams`
    greater than zero ... a missing or zero measurement inconsistent with the
    garment's service type is rejected with `ERR_INVALID_INTAKE_MEASUREMENT` at
    HTTP 422."

    WASH_FOLD garment logged with actual_piece_count only (no actual_weight_grams).

    Design: Corner/endpoints/log_intake_missing_measurement_rejected
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    th.pickup_order(order)
    resp = api.log_intake(order["id"], garments[0]["id"],
                          {"actual_piece_count": 1}, th.plant_headers())
    th.validate_error(resp, "ERR_INVALID_INTAKE_MEASUREMENT", 422)


def test_dispatch_locker_order_without_assignment_rejected(api):
    """PRD §3.6: "if the order's `handoff_method` is `LOCKER`, there must already
    exist a locker assignment for this order in either `OCCUPIED` or `RESERVED`
    status, or the request is rejected with `ERR_NO_LOCKER_ASSIGNED`."

    A LOCKER order at READY with no assignment.

    Design: Corner/endpoints/dispatch_locker_order_without_assignment_rejected
    """
    customer, pickup, delivery, order, _ = th.order_at_ready(
        garments=[{"service_type": "DRY_CLEAN", "declared_piece_count": 1}],
        order_overrides={"handoff_method": "LOCKER"},
    )
    resp = api.dispatch_delivery(order["id"], th.dispatch_headers())
    th.validate_error(resp, "ERR_NO_LOCKER_ASSIGNED", 409)


def test_locker_assignment_filtered_list_by_order(api):
    """PRD §3.11: "locker assignments by `order_id` and `locker_id`" (filterable
    list reads).

    GET /locker-assignments?order_id=<id> returns the RESERVED assignment created
    for that order.

    Design: Corner/endpoints/locker_assignment_filtered_list_by_order
    """
    customer, pickup, delivery, order, garments, locker, assignment = \
        th.ready_locker_order_with_assignment()
    resp = api.list_locker_assignments(th.dispatch_headers(), params={"order_id": order["id"]})
    data, _ = th.validate_paginated(resp)
    matching = [a for a in data if a["id"] == assignment["id"]]
    assert matching, f"assignment {assignment['id']} should be in the filtered list"
    assert matching[0]["status"] == "RESERVED", \
        f"assignment should be RESERVED, got {matching[0]['status']}"


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
def test_hold_not_expired_rejected(api):
    """PRD §3.9: "Expiring an assignment moves it from `RESERVED` or `OCCUPIED` to
    `EXPIRED` and requires ... the current server time to be at or after the
    assignment's `hold_end_utc` (otherwise `ERR_HOLD_NOT_EXPIRED`)."

    Clock at 08:00, hold_end at 18:00 -> expire is rejected.

    Design: Corner/errors/hold_not_expired_rejected
    """
    th.set_clock("2026-06-01T08:00:00Z")
    customer, pickup, delivery, order, garments, locker, assignment = \
        th.ready_locker_order_with_assignment(
            hold_start_utc="2026-06-03T09:00:00Z", hold_end_utc="2026-06-03T18:00:00Z")
    resp = api.expire_assignment(assignment["id"], th.dispatch_headers())
    th.validate_error(resp, "ERR_HOLD_NOT_EXPIRED", 409)


def test_cancel_already_cancelled_subscription_rejected(api):
    """PRD §3.1: "Cancelling a subscription is permitted only while its `status`
    is `ACTIVE` - otherwise the cancel is rejected with
    `ERR_INVALID_SUBSCRIPTION_STATE`"

    Design: Corner/errors/cancel_already_cancelled_subscription_rejected
    """
    customer, sub, version_after = th.cancelled_subscription()
    resp = api.cancel_subscription(
        sub["id"], {"expected_subscription_version": version_after},
        th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_INVALID_SUBSCRIPTION_STATE", 409)
