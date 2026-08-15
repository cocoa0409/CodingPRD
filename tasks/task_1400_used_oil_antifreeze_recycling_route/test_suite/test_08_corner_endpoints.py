"""Corner queue B — Section 5: endpoints (skip-below-minimum, pickup errors, idempotency)."""

from test_helpers import (
    api_client,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_driver_headers,
    create_pickup_ticket_payload,
    setup_ready_to_pump_stop,
    setup_completed_pickup,
)


def test_skip_below_minimum_zero_volume_ticket(api):
    """PRD §3.4: "Skipping moves the stop to `SKIPPED_BELOW_MINIMUM` and creates a zero-volume `PickupTicket` — a metered volume of exactly zero is permitted only through this path — with `density_fee_cents` posted for audit."

    Design: Corner/endpoints/skip_below_minimum_zero_volume_ticket
    """
    ctx = setup_ready_to_pump_stop(
        density_zone="URBAN", credit_terms="CHARGE_ONLY", route_eligibility_override=False,
        intake_gallons=30, route_code="SKIP",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    ticket = get_success_data(api_client.skip_below_minimum_route_stop(
        ctx["stop"]["id"], {"client_request_id": "SKIP-1"}, drv,
    ))
    stop_after = get_success_data(api_client.get_route_stop(ctx["stop"]["id"], TEST_USERS["route_planner_headers"]))
    assert stop_after["status"] == "SKIPPED_BELOW_MINIMUM"
    assert ticket["metered_volume_gallons"] == 0
    assert ticket["density_fee_cents"] == 1000  # (50-0)*20 URBAN
    assert ticket["net_amount_cents"] == -1000


def test_skip_above_minimum_returns_error(api):
    """PRD §3.4: "A driver may skip a `READY_TO_PUMP` stop only when the tank's `current_volume_gallons` is below the site zone's minimum (otherwise `ERR_VOLUME_ABOVE_MINIMUM`, signalling the pickup path must be used)".

    Design: Corner/endpoints/skip_above_minimum_returns_error
    """
    ctx = setup_ready_to_pump_stop(
        density_zone="URBAN", route_eligibility_override=False,
        intake_gallons=100, route_code="SKIP2",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    resp = api_client.skip_below_minimum_route_stop(ctx["stop"]["id"], {"client_request_id": "SKIP-2"}, drv)
    validate_error(resp, ApiErrorId.ERR_VOLUME_ABOVE_MINIMUM)


def test_pickup_zero_volume_returns_error(api):
    """PRD §3.4: "a zero metered volume yields `ERR_ZERO_VOLUME_PICKUP` (HTTP 400) — the driver must use the skip path instead".

    Design: Corner/endpoints/pickup_zero_volume_returns_error
    """
    ctx = setup_ready_to_pump_stop(
        route_eligibility_override=True, intake_gallons=100, route_code="ZERO",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    resp = api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id="ZERO-PT", metered_volume_gallons=0),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_ZERO_VOLUME_PICKUP)


def test_pickup_exceeds_tank_level_returns_error(api):
    """PRD §3.4: "volume above the tank level yields `ERR_VOLUME_EXCEEDS_TANK_LEVEL` (HTTP 422)".

    Design: Corner/endpoints/pickup_exceeds_tank_level_returns_error
    """
    ctx = setup_ready_to_pump_stop(
        route_eligibility_override=True, intake_gallons=50, route_code="OVT",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    resp = api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id="OVT-PT", metered_volume_gallons=100),
        drv,
    )
    validate_error(resp, ApiErrorId.ERR_VOLUME_EXCEEDS_TANK_LEVEL)


def test_pickup_idempotency_same_client_request_id(api):
    """PRD §3.4: "a repeated `client_request_id` on the same stop yields `ERR_DUPLICATE_CLIENT_REQUEST` (HTTP 409)";
    PRD §2.6 pins the pickup check order: "the stop's readiness state, then ... and only then the idempotency
    key (`ERR_DUPLICATE_CLIENT_REQUEST`)" — after a successful pickup the stop is COMPLETED, so the readiness
    check may legitimately fire first.

    Design: Corner/endpoints/pickup_idempotency_same_client_request_id
    """
    ctx = setup_completed_pickup(
        route_eligibility_override=True, intake_gallons=200,
        metered_volume_gallons=100, client_request_id="IDEM-1", route_code="IDEM",
    )
    drv = make_driver_headers(ctx["driver"]["id"])
    resp = api_client.create_pickup_ticket(
        ctx["stop"]["id"],
        create_pickup_ticket_payload(client_request_id="IDEM-1", metered_volume_gallons=100),
        drv,
    )
    validate_error_is_one_of(resp, [
        ApiErrorId.ERR_DUPLICATE_CLIENT_REQUEST,
        ApiErrorId.ERR_STOP_NOT_READY_TO_PUMP,
    ])
