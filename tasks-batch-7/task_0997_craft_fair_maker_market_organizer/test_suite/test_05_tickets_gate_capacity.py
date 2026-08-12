"""Tickets and the gate: venue capacity with VIP double-count, redeem gating by
posture/weather, and terminal-state lockdown."""
from test_helpers import (
    validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS,
    assert_ticket,
    create_event, create_ticket_payload,
    reset_clock, setup_live_ctx, setup_approved_ctx, sell_ticket, redeem_ticket,
    api_client,
)

REDEEM_GATE_ERRORS = [
    ApiErrorId.ERR_TICKET_NOT_REDEEMABLE,
    ApiErrorId.ERR_POSTURE_FORBIDS,
]


def test_capacity_boundary_last_admit_then_reject(api):
    """PRD §3.6: "Capacity is the fourth gate, with its own error: effective
    occupancy counts every Attendance row of the event whose `exited_at` is still
    null, then adds one more for each such row whose ticket is a `VIP`; admission is
    granted only while that effective occupancy is strictly below `venue_capacity`."
    PRD §3.6: "The last successful scan is therefore the one taken while effective
    occupancy equals `venue_capacity` minus one; any attempt at equality or beyond
    is rejected with `ERR_VENUE_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/venue_capacity_vip_double_count_at_boundary
    """
    ctx = setup_live_ctx(event_overrides={"venue_capacity": 5})
    event_id = ctx["event"]["id"]
    t1 = sell_ticket(event_id, kind="GA")
    t2 = sell_ticket(event_id, kind="GA")
    t3 = sell_ticket(event_id, kind="VIP", price_cents=5000)
    t4 = sell_ticket(event_id, kind="GA")
    t5 = sell_ticket(event_id, kind="GA")

    # On site: GA + GA + VIP -> effective occupancy 1 + 1 + 2 = 4.
    for t in (t1, t2, t3):
        redeemed = validate_success(redeem_ticket(event_id, t["id"]), 200)
        assert_ticket(redeemed)
        assert redeemed["state"] == "REDEEMED"

    # Effective occupancy 4 == capacity - 1: this is the last successful scan.
    redeemed4 = validate_success(redeem_ticket(event_id, t4["id"]), 200)
    assert redeemed4["state"] == "REDEEMED"

    # Effective occupancy is now 5 >= 5: any further admit rejects.
    res5 = redeem_ticket(event_id, t5["id"])
    validate_error(res5, ApiErrorId.ERR_VENUE_AT_CAPACITY, expected_status=409)
    t5_after = get_success_data(
        api_client.get_ticket(event_id, t5["id"], TEST_USERS["event_coordinator_headers"])
    )
    assert t5_after["state"] == "ISSUED", "rejected redeem must leave the ticket ISSUED"


def test_vip_counts_double_against_capacity(api):
    """PRD §3.6: "`VIP` tickets include early entry and, crucially for the gate,
    count double against the venue's occupancy projection."
    PRD §3.6: "The last successful scan is therefore the one taken while effective
    occupancy equals `venue_capacity` minus one; any attempt at equality or beyond
    is rejected with `ERR_VENUE_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/venue_capacity_vip_double_count_at_boundary
    """
    ctx = setup_live_ctx(event_overrides={"venue_capacity": 2})
    event_id = ctx["event"]["id"]
    vip = sell_ticket(event_id, kind="VIP", price_cents=5000)
    ga = sell_ticket(event_id, kind="GA")

    # One VIP on site already fills effective occupancy to 2 == capacity.
    validate_success(redeem_ticket(event_id, vip["id"]), 200)
    res = redeem_ticket(event_id, ga["id"])
    validate_error(res, ApiErrorId.ERR_VENUE_AT_CAPACITY, expected_status=409)


def test_redeem_rejected_before_event_live(api):
    """PRD §3.6: "Three conditions reject a redemption with
    `ERR_TICKET_NOT_REDEEMABLE`: the ticket is not in `ISSUED`, the `weather_flag`
    is `SEVERE`, or the posture is anything but `LIVE`."
    PRD §2.4: "When the current posture does not permit the requested child write,
    the request is rejected with `ERR_POSTURE_FORBIDS`."

    Design: Difficulty/cross_entity_state_dependency/ticket_redeem_gated_by_vendorassignment_state
    """
    # Event reaches SCHEDULING (no payment made, so go-live precondition cannot be
    # met); the ticket is ISSUED but the posture is anything but LIVE.
    ctx = setup_approved_ctx()
    event_id = ctx["event"]["id"]
    ticket = sell_ticket(event_id, kind="GA")
    assert ticket["state"] == "ISSUED"

    res = redeem_ticket(event_id, ticket["id"])
    actual = validate_error_is_one_of(res, REDEEM_GATE_ERRORS)
    assert actual in ("ERR_TICKET_NOT_REDEEMABLE", "ERR_POSTURE_FORBIDS")
    after = get_success_data(
        api_client.get_ticket(event_id, ticket["id"], ctx["coordinator_headers"])
    )
    assert after["state"] == "ISSUED", "rejected redeem must leave the ticket ISSUED"


def test_redeem_rejected_during_weather_hold(api):
    """PRD §3.6: "Three conditions reject a redemption with
    `ERR_TICKET_NOT_REDEEMABLE`: the ticket is not in `ISSUED`, the `weather_flag`
    is `SEVERE`, or the posture is anything but `LIVE`."
    PRD §2.4: "When the current posture does not permit the requested child write,
    the request is rejected with `ERR_POSTURE_FORBIDS`."

    Design: Difficulty/cross_entity_state_dependency/ticket_redeem_gated_by_vendorassignment_state
    """
    ctx = setup_live_ctx()
    event_id = ctx["event"]["id"]
    ticket = sell_ticket(event_id, kind="GA")
    # SEVERE while LIVE slams the event into WEATHER_HOLD and suspends redemption.
    validate_success(
        api_client.set_weather(event_id, "SEVERE", ctx["coordinator_headers"]), 200
    )
    res = redeem_ticket(event_id, ticket["id"])
    actual = validate_error_is_one_of(res, REDEEM_GATE_ERRORS)
    assert actual in ("ERR_TICKET_NOT_REDEEMABLE", "ERR_POSTURE_FORBIDS")
    after = get_success_data(
        api_client.get_ticket(event_id, ticket["id"], ctx["coordinator_headers"])
    )
    assert after["state"] == "ISSUED"


def test_refunded_ticket_cannot_be_redeemed(api):
    """PRD §3.6: "An `ISSUED` ticket may be refunded — moving it to `REFUNDED` —
    whenever the event's posture is one of `PLANNING`, `APPLICATION_OPEN`,
    `JURY_REVIEW`, `SCHEDULING`, or `WEATHER_HOLD`, or whenever the supplied
    `reason` is `EVENT_CANCELLED`, regardless of posture."
    PRD §3.6: "Three conditions reject a redemption with
    `ERR_TICKET_NOT_REDEEMABLE`: the ticket is not in `ISSUED`, the `weather_flag`
    is `SEVERE`, or the posture is anything but `LIVE`."

    Design: Corner/state_machines/ticket_terminal_state_lockdown
    """
    coordinator = TEST_USERS["event_coordinator_headers"]
    reset_clock()
    event = create_event(coordinator, name="T")
    ticket = validate_success(
        api_client.create_ticket(event["id"], create_ticket_payload(), coordinator),
        201,
    )
    refunded = validate_success(
        api_client.refund_ticket(event["id"], ticket["id"],
                                 {"reason": "USER_REQUEST"}, coordinator),
        200,
    )
    assert refunded["state"] == "REFUNDED"

    res = api_client.redeem_ticket(event["id"], ticket["id"],
                                   TEST_USERS["gate_agent_headers"])
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_TICKET_NOT_REDEEMABLE,
            ApiErrorId.ERR_INVALID_STATE,
            ApiErrorId.ERR_POSTURE_FORBIDS,
        ],
    )
    after = get_success_data(api_client.get_ticket(event["id"], ticket["id"],
                                                   coordinator))
    assert after["state"] == "REFUNDED"
