"""State-machine corners: invalid transitions, terminal lockdown, cascades."""
import test_helpers as th


def test_pickup_from_created_returns_invalid_state(api):
    """PRD §3.4: "the order must be in `SCHEDULED`, or the request is rejected
    with `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/pickup_from_created_returns_invalid_state
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    # order is CREATED (never scheduled)
    resp = api.pickup_order(order["id"], th.dispatch_headers())
    th.validate_error(resp, "ERR_INVALID_ORDER_STATE", 409)


def test_cancel_delivered_order_returns_invalid_state(api):
    """PRD §3.7: "Cancellation is forbidden once the order is `OUT_FOR_DELIVERY`,
    `DELIVERED`, or already `CANCELLED`; an attempt in any of those states is
    rejected with `ERR_INVALID_ORDER_STATE`."

    Design: Corner/state_machines/cancel_delivered_order_returns_invalid_state
    """
    customer, pickup, delivery, order, _ = th.order_delivered(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}],
        actuals=[{"actual_weight_grams": 2000}],
    )
    ov = th.get_order(order["id"], customer["id"])["version"]
    resp = api.cancel_order(order["id"], {"expected_order_version": ov},
                            th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_INVALID_ORDER_STATE", 409)


def test_order_initial_state_is_created(api):
    """PRD §3.2: "A fresh order starts with `status` `CREATED`,
    `estimate_total_cents` 0, `final_total_cents` 0, and `risk_flag` false."

    Design: Corner/state_machines/order_initial_state_is_created
    """
    customer, pickup, delivery = th.create_zone_setup()
    resp = api.create_order(
        th.create_order_payload(customer["id"], pickup["id"], delivery["id"]),
        th.make_customer_headers(customer["id"]))
    data = th.validate_success(resp, expected_status=201)
    assert data["status"] == "CREATED", f"initial state is CREATED, got {data['status']}"


def test_start_processing_cascades_garments_to_cleaning(api):
    """PRD §3.5: "Starting processing carries every garment from `INTAKE_LOGGED`
    to `CLEANING` as a system-driven child transition."

    Design: Corner/state_machines/garment_intake_logged_cascades_to_cleaning
    """
    customer, pickup, delivery, order, garments = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    th.schedule_order(order, customer)
    th.pickup_order(order)
    th.log_intake(order, garments[0], actual_weight_grams=2000)
    th.start_processing(order)
    garment = th.validate_success(
        api.get_garment(order["id"], garments[0]["id"], th.plant_headers()))
    assert garment["status"] == "CLEANING", \
        f"garment cascades to CLEANING, got {garment['status']}"


def test_appeal_limit_reached_blocks_further_appeal(api):
    """PRD §3.10: "requires `appeal_count` to be strictly less than the maximum
    allowed appeals (otherwise `ERR_APPEAL_LIMIT_REACHED`)"
    PRD §3.10: "once that bound is reached no further appeal is permitted and
    final denial becomes available."

    Two reject/appeal rounds exhaust the appeal allowance; a third appeal after a
    further rejection returns ERR_APPEAL_LIMIT_REACHED.

    Design: Corner/state_machines/appeal_limit_reached_blocks_further_appeal
    """
    customer, pickup, delivery, order, _ = th.create_order_with_garments(
        garments=[{"service_type": "WASH_FOLD", "declared_weight_grams": 2000}])
    claim = th.file_claim(order, customer, subject_kind="ORDER", declared_value_cents=5000)
    th.investigate(claim)
    th.reject(claim)
    th.appeal(claim, customer)   # appeal_count 1
    th.reject(claim)
    th.appeal(claim, customer)   # appeal_count 2 (limit reached)
    th.reject(claim)
    resp = api.appeal_claim(claim["id"], th.make_customer_headers(customer["id"]))
    th.validate_error(resp, "ERR_APPEAL_LIMIT_REACHED", 409)
