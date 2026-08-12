"""Weighbridge: weigh window bounds, weight sanity, the reweigh loop, ticket
creation gating on booking state, terminal lockdown, and ticket listing."""
from test_helpers import (
    ApiErrorId,
    SLOT_AM_END,
    SLOT_AM_START,
    SLOT_PM_END,
    SLOT_PM_START,
    WEIGH_CLOCK_AM,
    create_confirmed_booking,
    create_requested_booking,
    create_ticket_payload,
    create_weighed_ticket,
    get_success_data,
    make_sampled_ticket,
    set_logical_clock,
    setup_world,
    validate_error,
    validate_paginated,
    validate_success,
    weigh_payload,
)


def _confirmed_world(api, pile=False):
    world = setup_world(with_pile=pile)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    world["booking"] = booking
    return world


def test_weigh_outside_slot_window_rejected(api, station_operator_headers):
    """PRD §3.3: "the logical clock must fall within the booking's weigh window,
    which opens thirty minutes (1800 seconds) before `slot_start` and closes one
    hour (3600 seconds) after `slot_end`; a weigh attempted outside that window
    is rejected with `ERR_WEIGH_WINDOW_CLOSED`."

    Design: Corner/validations/weigh_outside_slot_window_then_at_window_edge
    """
    world = _confirmed_world(api)
    set_logical_clock("2026-10-01T06:00:00Z")  # before slot_start - 1800s
    ticket = get_success_data(api.create_ticket(
        create_ticket_payload(world["booking"]["id"]), station_operator_headers))
    res = api.weigh_ticket(ticket["id"], weigh_payload(60000, 32000),
                           station_operator_headers)
    validate_error(res, ApiErrorId.ERR_WEIGH_WINDOW_CLOSED.value)


def test_weigh_at_window_opening_bound_succeeds(api, station_operator_headers):
    """PRD §3.3: "the logical clock must fall within the booking's weigh window,
    which opens thirty minutes (1800 seconds) before `slot_start` and closes one
    hour (3600 seconds) after `slot_end`".

    Design: Corner/validations/weigh_outside_slot_window_then_at_window_edge
    """
    world = _confirmed_world(api)
    set_logical_clock("2026-10-01T07:30:00Z")  # exactly slot_start - 1800s
    ticket = get_success_data(api.create_ticket(
        create_ticket_payload(world["booking"]["id"]), station_operator_headers))
    weighed = validate_success(api.weigh_ticket(
        ticket["id"], weigh_payload(60000, 32000), station_operator_headers), 200)
    assert weighed["status"] == "WEIGHED"
    assert weighed["net_weight_lbs"] == 28000


def test_weigh_invalid_weights_return_error(api, station_operator_headers):
    """PRD §3.3: "`tare_weight_lbs` must be greater than 0 and `gross_weight_lbs`
    must be strictly greater than `tare_weight_lbs`, otherwise the reading is
    rejected with `ERR_INVALID_WEIGHTS` (422)."

    Design: Corner/validations/weigh_invalid_weights_return_error
    """
    world = _confirmed_world(api)
    set_logical_clock(WEIGH_CLOCK_AM)
    ticket = get_success_data(api.create_ticket(
        create_ticket_payload(world["booking"]["id"]), station_operator_headers))
    res1 = api.weigh_ticket(ticket["id"], weigh_payload(32000, 32000),
                            station_operator_headers)
    validate_error(res1, ApiErrorId.ERR_INVALID_WEIGHTS.value)
    res2 = api.weigh_ticket(ticket["id"], weigh_payload(60000, 0),
                            station_operator_headers)
    validate_error(res2, ApiErrorId.ERR_INVALID_WEIGHTS.value)
    ticket_after = validate_success(
        api.get_ticket(ticket["id"], station_operator_headers), 200)
    assert ticket_after["status"] == "CREATED"


def test_reweigh_clears_weights_to_null(api, station_operator_headers):
    """PRD §3.3: "Flagging a reweigh — permitted only while the logical clock is
    still within the same weigh window, else `ERR_WEIGH_WINDOW_CLOSED` — moves
    the ticket from `WEIGHED` to `REWEIGHING` and clears `gross_weight_lbs`,
    `tare_weight_lbs`, and `net_weight_lbs` back to null."

    Design: Difficulty/non_linear_state_machine/ticket_reweigh_cycle_recomputes_net
    """
    world = _confirmed_world(api)
    ticket = create_weighed_ticket(world["booking"]["id"], 80000, 32000,
                                   WEIGH_CLOCK_AM)
    assert ticket["status"] == "WEIGHED"
    assert ticket["net_weight_lbs"] == 48000
    mid = validate_success(api.reweigh_ticket(ticket["id"], station_operator_headers), 200)
    assert mid["status"] == "REWEIGHING"
    assert mid["net_weight_lbs"] is None
    assert mid["gross_weight_lbs"] is None
    assert mid["tare_weight_lbs"] is None


def test_reweigh_cycle_recomputes_net_weight(api, station_operator_headers):
    """PRD §3.3: "Weighing again from `REWEIGHING` re-applies the same
    weight-sanity and window checks and recomputes `net_weight_lbs` from the new
    readings, returning the ticket to `WEIGHED`; each step increments the
    ticket's `version` by 1."

    Design: Difficulty/non_linear_state_machine/ticket_reweigh_cycle_recomputes_net
    """
    world = _confirmed_world(api)
    ticket = create_weighed_ticket(world["booking"]["id"], 80000, 32000,
                                   WEIGH_CLOCK_AM)
    get_success_data(api.reweigh_ticket(ticket["id"], station_operator_headers))
    second = validate_success(api.weigh_ticket(
        ticket["id"], weigh_payload(79800, 31700), station_operator_headers), 200)
    assert second["status"] == "WEIGHED"
    assert second["net_weight_lbs"] == 48100  # 79800 - 31700


def test_ticket_create_on_requested_booking_rejected(api, station_operator_headers):
    """PRD §3.3: "The booking must be in `CONFIRMED` or `IN_USE` status — any
    other state is rejected with `ERR_BOOKING_NOT_CONFIRMED`".

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_booking_confirmed_or_in_use
    """
    world = setup_world(with_pile=False)
    booking = create_requested_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 20)
    res = api.create_ticket(create_ticket_payload(booking["id"]),
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value)


def test_ticket_create_on_cancelled_booking_rejected(api, station_operator_headers,
                                                     scheduler_headers):
    """PRD §3.3: "The booking must be in `CONFIRMED` or `IN_USE` status — any
    other state is rejected with `ERR_BOOKING_NOT_CONFIRMED`".

    Design: Difficulty/cross_entity_state_dependency/ticket_create_requires_booking_confirmed_or_in_use
    """
    world = setup_world(with_pile=False)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_PM_START, SLOT_PM_END, 20)
    validate_success(api.cancel_booking(booking["id"], scheduler_headers), 200)
    res = api.create_ticket(create_ticket_payload(booking["id"]),
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_BOOKING_NOT_CONFIRMED.value)


def test_ticket_accept_from_created_returns_invalid_state(api, station_operator_headers):
    """PRD §3.6: "a `STATION_OPERATOR` performs it against a ticket in `SAMPLED`
    status by naming the target pile via `pile_id`."

    Design: Corner/state_machines/ticket_accept_from_created_returns_invalid_state
    """
    world = _confirmed_world(api, pile=True)
    ticket = get_success_data(api.create_ticket(
        create_ticket_payload(world["booking"]["id"]), station_operator_headers))
    res = api.accept_ticket(ticket["id"], {"pile_id": world["pile"]["id"]},
                            station_operator_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_rejected_ticket_terminal_lockdown(api, station_operator_headers):
    """PRD §3.6: "A ticket in `SAMPLED` status may be rejected — the action takes
    an optional `reason` — but only when its `provisional_trash_pct` exceeds
    20.00 percent; rejecting a load that is actually within the trash limit is a
    state error, `ERR_INVALID_STATE`. Rejection moves the ticket to the terminal
    `REJECTED` state while leaving the booking in `IN_USE`".

    Design: Corner/state_machines/rejected_ticket_terminal_lockdown
    """
    world = _confirmed_world(api, pile=True)
    ticket, _sample = make_sampled_ticket(world["booking"]["id"],
                                          gross_weight_lbs=72000,
                                          tare_weight_lbs=32000,
                                          clock=WEIGH_CLOCK_AM,
                                          sugar_pct=15.00, trash_pct=21.00)
    rejected = validate_success(api.reject_ticket(
        ticket["id"], {"reason": "trash over limit"}, station_operator_headers), 200)
    assert rejected["status"] == "REJECTED"
    res1 = api.weigh_ticket(ticket["id"], weigh_payload(72000, 32000),
                            station_operator_headers)
    validate_error(res1, ApiErrorId.ERR_INVALID_STATE.value)
    res2 = api.void_ticket(ticket["id"], {"reason": "operator error"},
                           station_operator_headers)
    validate_error(res2, ApiErrorId.ERR_INVALID_STATE.value)


def test_tickets_list_pagination_limit_and_has_more(api, station_operator_headers,
                                                    pool_accountant_headers):
    """PRD §2.3: "The `limit` parameter sets the maximum number of items returned
    in one page; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter sets the number of items skipped before the page begins
    and defaults to 0." and "The `meta` object of every list response carries
    four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/tickets_list_pagination_limit_and_has_more
    """
    world = setup_world(with_pile=False)
    booking = create_confirmed_booking(
        world["campaign"]["id"], world["station"]["id"], world["member"]["id"],
        SLOT_AM_START, SLOT_AM_END, 40)
    create_weighed_ticket(booking["id"], 60000, 32000, WEIGH_CLOCK_AM)  # t1: WEIGHED
    t2 = get_success_data(api.create_ticket(
        create_ticket_payload(booking["id"]), station_operator_headers))  # t2: CREATED

    data, meta = validate_paginated(api.list_tickets(
        pool_accountant_headers, params={"limit": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    data, meta = validate_paginated(api.list_tickets(
        pool_accountant_headers, params={"limit": 1, "offset": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2

    data, meta = validate_paginated(api.list_tickets(
        pool_accountant_headers, params={"status": "CREATED"}))
    assert len(data) == 1
    assert data[0]["id"] == t2["id"]  # t1 is WEIGHED and excluded
