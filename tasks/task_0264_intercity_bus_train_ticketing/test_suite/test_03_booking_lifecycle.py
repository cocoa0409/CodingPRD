"""Booking confirm/pay lifecycle, parallel status axes, the depth-2 confirm cascade,
cross-entity confirm preconditions, the service-date lifecycle machine, and the
booking-creation validation family.

Traces queue-A `non_linear_state_machine` (booking_parallel_status_axes_independent),
`transitive_cascade` (booking_confirm_depth2_ledger_and_ticket),
`cross_entity_state_dependency` (confirm_requires_service_date_sales_open),
plus queue-B `state_machines` and `validations`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    make_passenger_headers,
    TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ─── non_linear_state_machine: parallel booking axes ──
def test_confirm_then_pay_advances_axes_independently(api):
    """PRD §3.4: "A `Passenger` confirms a held booking to lock in fares ... advancing
    `booking_status` from `HELD` to `CONFIRMED`."
    PRD §3.5: "A `Passenger` pays a confirmed cash booking, moving `payment_status`
    from `UNPAID` to `PAID`."

    After confirm: booking_status CONFIRMED while payment_status stays UNPAID. After
    pay: payment_status PAID while booking_status stays CONFIRMED.

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes_independent
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    confirmed = fx.confirm_booking(booking["id"], passenger["id"], cat["service_date"]["id"])
    assert confirmed["booking_status"] == "CONFIRMED"
    assert confirmed["payment_status"] == "UNPAID", "payment axis must remain UNPAID after confirm"

    paid = fx.pay_booking(booking["id"], passenger["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["booking_status"] == "CONFIRMED", "fulfillment axis must remain CONFIRMED after pay"


def test_new_booking_starts_held_and_unpaid(api):
    """PRD §3.3: "A booking carries two parallel state axes: a fulfillment axis,
    `booking_status` ... and a settlement axis, `payment_status` ... A new booking
    begins `HELD` and `UNPAID`."

    Design: Difficulty/non_linear_state_machine/booking_parallel_status_axes_independent
    """
    cat = fx.setup_catalog()
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    assert booking["booking_status"] == "HELD"
    assert booking["payment_status"] == "UNPAID"


# ─── transitive_cascade: depth-2 confirm ledger + ticket ──
def test_confirm_moves_seat_held_to_sold_and_issues_ticket(api):
    """PRD §3.4: "each leg's service date moves one seat from held to sold —
    `seats_held` decreases by 1 and `seats_sold` increases by 1 — and the counters and
    `load_factor` are recomputed ... One **Ticket** per leg is issued in state
    `ISSUED`".

    seats_total=10, one confirmed leg => seats_held 0, seats_sold 1, load_factor 0.1.

    Design: Difficulty/transitive_cascade/booking_confirm_depth2_ledger_and_ticket
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    fx.confirm_booking(booking["id"], passenger["id"], cat["service_date"]["id"])

    sd = get_success_data(api.get_service_date(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd["seats_held"] == 0
    assert sd["seats_sold"] == 1
    assert abs(sd["load_factor"] - 0.1) < 1e-9, f"load_factor must be 1/10, got {sd['load_factor']}"

    tickets = fx.tickets_for_booking(booking["id"])
    assert len(tickets) == 1, f"expected exactly one ticket, got {len(tickets)}"
    assert tickets[0]["state"] == "ISSUED"


def test_confirm_finalizes_total_fare_from_legs(api):
    """PRD §3.4: "The booking's `total_fare_cents` is finalized: for a cash booking it
    is the sum of the per-leg fares".

    A single ECONOMY leg at load_factor 0, 14 days out prices to 3600, so the
    confirmed booking's total_fare_cents == 3600.

    Design: Difficulty/transitive_cascade/booking_confirm_depth2_ledger_and_ticket
    """
    cat = fx.setup_catalog(
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-15"}
    )
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    confirmed = fx.confirm_booking(booking["id"], passenger["id"], cat["service_date"]["id"])
    assert confirmed["total_fare_cents"] == 3600


# ─── cross_entity_state_dependency: confirm needs sales OPEN ──
def test_confirm_blocked_when_sales_suspended(api):
    """PRD §3.4: "For every leg, the referenced service date's `sales` gate must be
    `OPEN` and its `lifecycle` must be `SCHEDULED` or `DELAYED`, or the confirm is
    rejected with `ERR_PRECONDITION_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_service_date_sales_open
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    get_success_data(api.suspend_sales(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger["id"]))
    validate_error(resp, ApiErrorId.ERR_PRECONDITION_NOT_MET.value, 409)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "HELD"


def test_confirm_succeeds_after_sales_resumed(api):
    """PRD §3.4: "For every leg, the referenced service date's `sales` gate must be
    `OPEN` and its `lifecycle` must be `SCHEDULED` or `DELAYED`, or the confirm is
    rejected with `ERR_PRECONDITION_NOT_MET`."
    PRD §3.2: "A `ScheduleManager` may suspend sales, moving `sales` from `OPEN` to
    `SUSPENDED`, or resume them, moving from `SUSPENDED` back to `OPEN`".

    With sales resumed back to OPEN, the same confirm succeeds (CONFIRMED).

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_service_date_sales_open
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    get_success_data(api.suspend_sales(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    get_success_data(api.resume_sales(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger["id"]))
    confirmed = validate_success(resp, 200)
    assert confirmed["booking_status"] == "CONFIRMED"


# ─── state_machines (corner) ──────────────────────────
def test_scan_already_scanned_ticket_rejected(api):
    """PRD §3.9: "Scanning is admissible only when the ticket is currently `ISSUED` —
    a non-issued ticket is rejected with `ERR_INVALID_STATE`".

    Design: Corner/state_machines/scan_already_scanned_ticket_returns_invalid_state
    """
    cat = fx.setup_paid_booking(refundable=True)
    booking = cat["booking"]
    ticket = fx.tickets_for_booking(booking["id"])[0]
    get_success_data(api.scan_ticket(ticket["id"], TEST_USERS["gate_agent_headers"]))
    resp = api.scan_ticket(ticket["id"], TEST_USERS["gate_agent_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = get_success_data(api.get_ticket(ticket["id"], TEST_USERS["gate_agent_headers"]))
    assert after["state"] == "SCANNED"


def test_cancel_departed_service_date_rejected(api):
    """PRD §3.2: "`DEPARTED` and `CANCELLED` are terminal lifecycle states." and
    "both depart and cancel require it to be one of `SCHEDULED` or `DELAYED` — and a
    request that finds the trip in the wrong state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/depart_then_cancel_rejected_terminal_lockdown
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL")
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    get_success_data(api.depart_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    resp = api.cancel_service_date(sd["id"], TEST_USERS["schedule_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = get_success_data(api.get_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert after["lifecycle"] == "DEPARTED"


def test_restore_non_delayed_service_date_rejected(api):
    """PRD §3.2: "restoring a delayed trip moves it from `DELAYED` back to `SCHEDULED`
    ... restore requires it to be `DELAYED` ... a request that finds the trip in the
    wrong state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/restore_non_delayed_service_date_rejected
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL")
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    resp = api.restore_service_date(sd["id"], TEST_USERS["schedule_manager_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = get_success_data(api.get_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert after["lifecycle"] == "SCHEDULED"


def test_pay_pass_funded_booking_rejected(api):
    """PRD §3.5: "Paying requires the booking to be `CONFIRMED`, its `funding_kind` to
    be `CASH`, and its `payment_status` to currently be `UNPAID`; a violation is
    rejected with `ERR_INVALID_STATE` (or `ERR_PRECONDITION_NOT_MET` where the funding
    kind disqualifies it)."

    The trigger asserts that a PASS-funded booking cannot be paid; PRD allows either
    ERR_INVALID_STATE or ERR_PRECONDITION_NOT_MET for the funding-kind disqualification.

    Design: Corner/state_machines/pay_pass_funded_booking_rejected
    """
    cat = fx.setup_pass_booking_confirmed(rides_total=10)
    passenger = cat["passenger"]
    booking = cat["booking"]
    resp = api.pay_booking(booking["id"], make_passenger_headers(passenger["id"]))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_PRECONDITION_NOT_MET.value]
    )
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["payment_status"] == "UNPAID"


# ─── validations (corner — booking creation family) ──
def test_sold_out_blocks_hold(api):
    """PRD §3.3: "Holding seats requires that, for each leg, the service date's gate be
    `OPEN` and there be at least one available seat (`seats_available` of at least 1
    for the requested legs); a sold-out trip is rejected with `ERR_SOLD_OUT`."

    seats_total=1 with one HELD booking => seats_available 0 => second hold ERR_SOLD_OUT.

    Design: Corner/validations/sold_out_blocks_hold
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 1, "base_fare_cents": 4000})
    passenger_a = fx.create_passenger(full_name="A", email="a@x.com")
    fx.hold_booking(passenger_a["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    passenger_b = fx.create_passenger(full_name="B", email="b@x.com")
    resp = api.create_booking(
        f.create_booking_payload(
            passenger_b["id"], [f.leg_payload(cat["service_date"]["id"], cat["fare_class"]["id"], 1)]
        ),
        make_passenger_headers(passenger_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SOLD_OUT.value, 409)


def test_reserved_leg_missing_seat_number_rejected(api):
    """PRD §3.3: "when the chosen fare class is `RESERVED`, a `seat_number` such as
    "12A"; for an `OPEN` fare class the seat number must be omitted, and a presence
    mismatch between `seat_number` and the seating mode is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/reserved_seat_missing_number_rejected
    """
    cat = fx.setup_catalog(
        operator_overrides={"mode": "RAIL"},
        fare_overrides={"code": "BUSINESS", "seating_mode": "RESERVED", "surcharge_cents": 1500},
    )
    passenger = fx.create_passenger()
    resp = api.create_booking(
        f.create_booking_payload(
            passenger["id"], [f.leg_payload(cat["service_date"]["id"], cat["fare_class"]["id"], 1)]
        ),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_retired_fare_class_blocks_new_leg(api):
    """PRD §3.1: "A `RETIRED` fare class can still be read and still applies to
    existing legs, but a new booking leg that references a `RETIRED` class is rejected
    with `ERR_FARE_CLASS_RETIRED`."

    Design: Corner/validations/fare_class_retired_blocks_new_leg
    """
    fx.set_clock()
    operator = fx.create_operator()
    fare_class = fx.create_fare_class(operator["id"])
    get_success_data(api.retire_fare_class(fare_class["id"], TEST_USERS["fare_analyst_headers"]))
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    passenger = fx.create_passenger()
    resp = api.create_booking(
        f.create_booking_payload(passenger["id"], [f.leg_payload(sd["id"], fare_class["id"], 1)]),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FARE_CLASS_RETIRED.value, 409)


def test_service_date_on_unpublished_route_rejected(api):
    """PRD §3.1: "Only a route that has been advanced to `PUBLISHED` ... may have
    service dates scheduled against it; attempting to schedule a trip on a
    non-`PUBLISHED` route is rejected with `ERR_ROUTE_NOT_PUBLISHED`."

    Design: Corner/validations/service_date_on_unpublished_route_rejected
    """
    operator = fx.create_operator()
    route = get_success_data(
        api.create_route(f.create_route_payload(operator["id"]), TEST_USERS["schedule_manager_headers"])
    )
    resp = api.create_service_date(
        f.create_service_date_payload(route["id"], seats_total=10, base_fare_cents=4000),
        TEST_USERS["schedule_manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PUBLISHED.value, 409)


def test_pass_depleted_blocks_confirm(api):
    """PRD §3.10: "Confirming a pass-funded booking requires `rides_remaining` to be at
    least the leg count; an under-funded pass is rejected with `ERR_PASS_DEPLETED`."

    A rides_total=1 pass already consumed by a first confirm; a second PASS booking on
    another service date fails confirm with ERR_PASS_DEPLETED.

    Design: Corner/validations/pass_depleted_blocks_confirm
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10})
    sd2 = fx.create_service_date(cat["route"]["id"], seats_total=10, base_fare_cents=4000, departure_date="2026-06-16")
    passenger = fx.create_passenger()
    travel_pass = fx.create_pass(passenger["id"], cat["operator"]["id"], rides_total=1)
    fx.hold_and_confirm(
        passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    booking2 = fx.hold_booking(
        passenger["id"], sd2["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    sd2_v = fx.current_sd_version(sd2["id"])
    resp = api.confirm_booking(booking2["id"], f.confirm_payload(sd2_v), make_passenger_headers(passenger["id"]))
    validate_error(resp, ApiErrorId.ERR_PASS_DEPLETED.value, 409)
    after = get_success_data(api.get_booking(booking2["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "HELD"
