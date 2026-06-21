"""Optimistic concurrency (OCC), reserved-seat collision, the connection buffer,
version monotonicity, derived-counter reconciliation, validation-priority
adjudication, the cancel-blocked-by-scanned-ticket dependency, the delay/restore
cycle, the baggage free-allowance boundary, and the pass-expired error.

Traces queue-A `resource_temporal_overlap`, `priority_pair_validation_conflict`,
`cross_entity_state_dependency` (booking_cancel_blocked_by_scanned_ticket),
`non_linear_state_machine` (service_date_delay_restore_cycle),
`boundary_precision_check` (baggage_free_allowance_boundary_at_23kg), plus queue-B
`cross_cutting_complexity_layers` and `errors` (pass_expired).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_passenger_headers,
    TEST_USERS,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx


# ─── resource_temporal_overlap: reserved seat exact collision ──
def test_reserved_seat_exact_collision_rejected(api):
    """PRD §3.3: "For a `RESERVED` leg, the requested `seat_number` must not already be
    occupied by another `ACTIVE` leg on the same service date, or the hold is rejected
    with `ERR_SEAT_TAKEN`."

    Design: Difficulty/resource_temporal_overlap/reserved_seat_exact_collision
    """
    cat = fx.setup_catalog(
        operator_overrides={"mode": "RAIL"},
        fare_overrides={"code": "BUSINESS", "seating_mode": "RESERVED", "surcharge_cents": 1500},
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000},
    )
    passenger_a = fx.create_passenger(full_name="A", email="a@x.com")
    fx.hold_booking(passenger_a["id"], cat["service_date"]["id"], cat["fare_class"]["id"], seat_number="12A")
    passenger_b = fx.create_passenger(full_name="B", email="b@x.com")
    resp = api.create_booking(
        f.create_booking_payload(
            passenger_b["id"],
            [f.leg_payload(cat["service_date"]["id"], cat["fare_class"]["id"], 1, seat_number="12A")],
        ),
        make_passenger_headers(passenger_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEAT_TAKEN.value, 409)
    sd = get_success_data(api.get_service_date(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd["seats_held"] == 1, "only passenger A's hold should persist"


def test_distinct_reserved_seats_both_held(api):
    """PRD §3.3: "For a `RESERVED` leg, the requested `seat_number` must not already be
    occupied by another `ACTIVE` leg on the same service date, or the hold is rejected
    with `ERR_SEAT_TAKEN`."

    Distinct seat numbers (12A and 12B) do NOT collide, so both holds succeed and the
    service date carries two held seats.

    Design: Difficulty/resource_temporal_overlap/reserved_seat_exact_collision
    """
    cat = fx.setup_catalog(
        operator_overrides={"mode": "RAIL"},
        fare_overrides={"code": "BUSINESS", "seating_mode": "RESERVED", "surcharge_cents": 1500},
        service_date_overrides={"seats_total": 10, "base_fare_cents": 4000},
    )
    passenger_a = fx.create_passenger(full_name="A", email="a@x.com")
    fx.hold_booking(passenger_a["id"], cat["service_date"]["id"], cat["fare_class"]["id"], seat_number="12A")
    passenger_b = fx.create_passenger(full_name="B", email="b@x.com")
    resp = api.create_booking(
        f.create_booking_payload(
            passenger_b["id"],
            [f.leg_payload(cat["service_date"]["id"], cat["fare_class"]["id"], 1, seat_number="12B")],
        ),
        make_passenger_headers(passenger_b["id"]),
    )
    validate_success(resp, 201)
    sd = get_success_data(api.get_service_date(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd["seats_held"] == 2


# ─── resource_temporal_overlap: connection buffer too tight ──
def test_connection_buffer_too_tight_rejected(api):
    """PRD §3.7: "the next leg's scheduled departure minute minus the inbound leg's
    scheduled arrival minute must be at least the owning operator's
    `default_connection_buffer_min` ... If any adjacent pair leaves too little time, the
    booking create or confirm is rejected with `ERR_CONNECTION_TOO_TIGHT`."

    Leg1 arrives at minute 600, leg2 departs at minute 610: gap 10 < buffer 30.

    Design: Difficulty/resource_temporal_overlap/connection_buffer_gap_too_tight
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL", default_connection_buffer_min=30)
    fare_class = fx.create_fare_class(operator["id"])
    route1 = fx.create_published_route(
        operator["id"], origin_code="NYP", destination_code="PHL",
        depart_minute_of_day=540, arrive_minute_of_day=600,
    )
    route2 = fx.create_published_route(
        operator["id"], origin_code="PHL", destination_code="WAS",
        depart_minute_of_day=610, arrive_minute_of_day=800,
    )
    sd1 = fx.create_service_date(route1["id"], seats_total=10, base_fare_cents=4000)
    sd2 = fx.create_service_date(route2["id"], seats_total=10, base_fare_cents=4000)
    passenger = fx.create_passenger()
    resp = api.create_booking(
        f.create_booking_payload(
            passenger["id"],
            [
                f.leg_payload(sd1["id"], fare_class["id"], 1),
                f.leg_payload(sd2["id"], fare_class["id"], 2),
            ],
        ),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_CONNECTION_TOO_TIGHT.value, 409)
    after1 = get_success_data(api.get_service_date(sd1["id"], TEST_USERS["schedule_manager_headers"]))
    after2 = get_success_data(api.get_service_date(sd2["id"], TEST_USERS["schedule_manager_headers"]))
    assert after1["seats_held"] == 0 and after2["seats_held"] == 0, "no leg created on a rejected booking"


def test_connection_buffer_satisfied_allows_hold(api):
    """PRD §3.7: "the next leg's scheduled departure minute minus the inbound leg's
    scheduled arrival minute must be at least the owning operator's
    `default_connection_buffer_min`".

    Leg1 arrives at minute 600, leg2 departs at minute 700: gap 100 >= buffer 30, so
    the 2-leg hold is accepted.

    Design: Difficulty/resource_temporal_overlap/connection_buffer_gap_too_tight
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL", default_connection_buffer_min=30)
    fare_class = fx.create_fare_class(operator["id"])
    route1 = fx.create_published_route(
        operator["id"], origin_code="NYP", destination_code="PHL",
        depart_minute_of_day=540, arrive_minute_of_day=600,
    )
    route2 = fx.create_published_route(
        operator["id"], origin_code="PHL", destination_code="WAS",
        depart_minute_of_day=700, arrive_minute_of_day=820,
    )
    sd1 = fx.create_service_date(route1["id"], seats_total=10, base_fare_cents=4000)
    sd2 = fx.create_service_date(route2["id"], seats_total=10, base_fare_cents=4000)
    passenger = fx.create_passenger()
    resp = api.create_booking(
        f.create_booking_payload(
            passenger["id"],
            [
                f.leg_payload(sd1["id"], fare_class["id"], 1),
                f.leg_payload(sd2["id"], fare_class["id"], 2),
            ],
        ),
        make_passenger_headers(passenger["id"]),
    )
    booking = validate_success(resp, 201)
    assert booking["booking_status"] == "HELD"


# ─── cross_entity_state_dependency: cancel blocked by scanned ticket ──
def test_confirmed_booking_cancel_blocked_by_scanned_ticket(api):
    """PRD §3.6: "Cancelling a `CONFIRMED` booking is admissible only when no ticket on
    the booking is in state `SCANNED`; a scanned ticket blocks the cancel with
    `ERR_PRECONDITION_NOT_MET`."

    Design: Difficulty/cross_entity_state_dependency/booking_cancel_blocked_by_scanned_ticket
    """
    cat = fx.setup_scanned_ticket_booking(refundable=True)
    passenger = cat["passenger"]
    booking = cat["booking"]
    ticket = cat["ticket"]
    assert ticket["state"] == "SCANNED"

    resp = api.cancel_booking(
        booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PRECONDITION_NOT_MET.value, 409)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "CONFIRMED"
    ticket_after = get_success_data(api.get_ticket(ticket["id"], TEST_USERS["gate_agent_headers"]))
    assert ticket_after["state"] == "SCANNED"


def test_confirmed_booking_cancel_allowed_without_scanned_ticket(api):
    """PRD §3.6: "Cancelling a `CONFIRMED` booking is admissible only when no ticket on
    the booking is in state `SCANNED` ... On a successful confirmed-booking cancel,
    every `ACTIVE` leg is set to `RELEASED` ... and every `ISSUED` ticket is moved to
    `VOID`."

    With no ticket scanned, the cancel succeeds and the booking becomes CANCELLED.

    Design: Difficulty/cross_entity_state_dependency/booking_cancel_blocked_by_scanned_ticket
    """
    cat = fx.setup_paid_booking(refundable=True)
    passenger = cat["passenger"]
    booking = cat["booking"]
    resp = api.cancel_booking(
        booking["id"], f.cancel_payload("CASH"), make_passenger_headers(passenger["id"])
    )
    after = validate_success(resp, 200)
    assert after["booking_status"] == "CANCELLED"


# ─── non_linear_state_machine: delay/restore cycle ──
def test_service_date_delay_restore_returns_to_scheduled(api):
    """PRD §3.2: "Marking a `SCHEDULED` trip as delayed advances `lifecycle` from
    `SCHEDULED` to `DELAYED` and bumps the version; this is reversible, and restoring a
    delayed trip moves it from `DELAYED` back to `SCHEDULED`, again bumping the version."

    Design: Difficulty/non_linear_state_machine/service_date_delay_restore_cycle
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL")
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    post_create_version = sd["version"]

    get_success_data(api.delay_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    restored = get_success_data(api.restore_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert restored["lifecycle"] == "SCHEDULED"
    assert restored["version"] == post_create_version + 2, (
        f"two transitions must bump version by 2, got {restored['version']} from {post_create_version}"
    )


def test_service_date_delay_sets_delayed(api):
    """PRD §3.2: "Marking a `SCHEDULED` trip as delayed advances `lifecycle` from
    `SCHEDULED` to `DELAYED` and bumps the version".

    Design: Difficulty/non_linear_state_machine/service_date_delay_restore_cycle
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL")
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    delayed = get_success_data(api.delay_service_date(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert delayed["lifecycle"] == "DELAYED"
    assert delayed["version"] == sd["version"] + 1


# ─── priority_pair_validation_conflict ────────────────
def test_state_check_beats_sold_out_on_reconfirm(api):
    """PRD §2.11: validation order is "... (6) the target resource is in a valid state
    for the requested transition, else `ERR_INVALID_STATE` ... (13) aggregate seat
    capacity holds, else `ERR_SOLD_OUT`".
    PRD §3.4: "Confirmation is admissible only when the booking is currently `HELD`;
    otherwise it is rejected with `ERR_INVALID_STATE`."

    Re-confirming an already-CONFIRMED booking on a sold-out (seats_total=1) service
    date fails the lower-numbered state check first => ERR_INVALID_STATE, not
    ERR_SOLD_OUT.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 1, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    fx.confirm_booking(booking["id"], passenger["id"], cat["service_date"]["id"])
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_existence_check_beats_referential_on_baggage(api):
    """PRD §2.11: validation order is "... (3) every referenced resource exists,
    validated left-to-right, else `ERR_NOT_FOUND` ... (7) cross-entity state
    preconditions hold, else `ERR_PRECONDITION_NOT_MET`".
    PRD §2.5: "rejects the request with `ERR_NOT_FOUND` at the first identifier that
    does not resolve to an existing resource."

    Adding baggage to a non-existent booking id fails the existence check (P3) first
    => ERR_NOT_FOUND, never reaching any cross-entity precondition.

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_on_baggage
    """
    fx.create_operator()
    passenger = fx.create_passenger()
    resp = api.add_baggage(
        NON_EXISTENT_UUID, f.baggage_payload(10.0), make_passenger_headers(passenger["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_state_check_beats_capacity_when_seats_available(api):
    """PRD §2.11: validation order is "... (6) the target resource is in a valid state
    for the requested transition, else `ERR_INVALID_STATE` ... (13) aggregate seat
    capacity holds, else `ERR_SOLD_OUT`".
    PRD §3.4: "Confirmation is admissible only when the booking is currently `HELD`;
    otherwise it is rejected with `ERR_INVALID_STATE`."

    Even on a roomy (seats_total=10) trip where capacity would pass, re-confirming an
    already-CONFIRMED booking fails the lower-numbered state check => ERR_INVALID_STATE,
    confirming the state layer (P6) pre-empts the fiscal layer (P13).

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_confirm
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    fx.confirm_booking(booking["id"], passenger["id"], cat["service_date"]["id"])
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_existence_check_beats_referential_on_confirm(api):
    """PRD §2.11: validation order is "... (3) every referenced resource exists,
    validated left-to-right, else `ERR_NOT_FOUND` ... (7) cross-entity state
    preconditions hold, else `ERR_PRECONDITION_NOT_MET`".
    PRD §2.5: "rejects the request with `ERR_NOT_FOUND` at the first identifier that
    does not resolve to an existing resource."

    Confirming a non-existent booking id fails the existence check (P3) first =>
    ERR_NOT_FOUND, never reaching the cross-entity confirm preconditions (P7).

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_referential_on_baggage
    """
    fx.create_operator()
    passenger = fx.create_passenger()
    resp = api.confirm_booking(
        NON_EXISTENT_UUID, f.confirm_payload(1), make_passenger_headers(passenger["id"])
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ─── boundary_precision_check: baggage free allowance at 23.0 kg ──
def test_baggage_fee_zero_at_exactly_23kg(api):
    """PRD §3.11: "if the weight is at most the free allowance of 23.0 kilograms the
    fee is 0 ... A bag at exactly 23.0 kilograms incurs a fee of 0."

    Design: Difficulty/boundary_precision_check/baggage_free_allowance_boundary_at_23kg
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    resp = api.add_baggage(booking["id"], f.baggage_payload(23.0), make_passenger_headers(passenger["id"]))
    bag = validate_success(resp, 201)
    assert bag["fee_cents"] == 0, f"23.0 kg is at the inclusive free allowance, fee must be 0, got {bag['fee_cents']}"


def test_baggage_fee_one_cent_just_over_allowance(api):
    """PRD §3.11: "otherwise the fee is the weight minus 23.0 kilograms, multiplied by
    an overweight rate of 500 cents per kilogram, rounded half up to whole cents."

    23.001 kg => (0.001 * 500) = 0.5 cents => round half up => 1 cent.

    Design: Difficulty/boundary_precision_check/baggage_free_allowance_boundary_at_23kg
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    booking = fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    resp = api.add_baggage(booking["id"], f.baggage_payload(23.001), make_passenger_headers(passenger["id"]))
    bag = validate_success(resp, 201)
    assert bag["fee_cents"] == 1, f"23.001 kg => round_half_up(0.5)=1, got {bag['fee_cents']}"


# ─── cross_cutting_complexity_layers (corner) ─────────
def test_occ_stale_service_date_version_on_confirm(api):
    """PRD §2.8: "If, at confirm time, that value does not match the service date's
    current `version` — for instance because another writer already confirmed a booking
    that consumed the last seat and legitimately advanced the service date — the confirm
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_service_date_version_on_confirm
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger_a = fx.create_passenger(full_name="A", email="a@x.com")
    passenger_b = fx.create_passenger(full_name="B", email="b@x.com")
    booking_b = fx.hold_booking(passenger_b["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    stale_version = fx.current_sd_version(cat["service_date"]["id"])

    booking_a = fx.hold_booking(passenger_a["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    # A confirms, legitimately advancing the service date version.
    fx.confirm_booking(booking_a["id"], passenger_a["id"], cat["service_date"]["id"])

    resp = api.confirm_booking(
        booking_b["id"], f.confirm_payload(stale_version), make_passenger_headers(passenger_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    after = get_success_data(api.get_booking(booking_b["id"], make_passenger_headers(passenger_b["id"])))
    assert after["booking_status"] == "HELD"


def test_occ_stale_booking_version_on_exchange(api):
    """PRD §2.8: "Exchanging a leg requires the body field `expected_booking_version` ...
    If that value does not match the booking's current `version` ... the exchange is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_booking_version_on_exchange
    """
    s = fx.setup_exchange_ready(
        base_fare_cents=4000, exchange_fee_cents=1000,
        origin_departure="2026-06-15", target_departure="2026-06-16",
    )
    passenger = s["passenger"]
    booking = s["booking"]
    b_v = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))["version"]
    resp = api.exchange_booking(
        booking["id"],
        f.exchange_payload(s["target_service_date"]["id"], s["fare_class"]["id"], b_v - 1),
        make_passenger_headers(passenger["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "CONFIRMED"


def test_service_date_version_increments_per_mutation(api):
    """PRD §2.4: "`version`, an integer that starts at 1 and increments by 1 on every
    mutation of the resource."
    PRD §3.2: "A `ScheduleManager` may suspend sales, moving `sales` from `OPEN` to
    `SUSPENDED`, or resume them ... each bumps the version."

    create => 1, suspend => 2, resume => 3.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    fx.set_clock()
    operator = fx.create_operator(mode="RAIL")
    route = fx.create_published_route(operator["id"])
    sd = fx.create_service_date(route["id"], seats_total=10, base_fare_cents=4000)
    assert sd["version"] == 1
    suspended = get_success_data(api.suspend_sales(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert suspended["version"] == 2
    resumed = get_success_data(api.resume_sales(sd["id"], TEST_USERS["schedule_manager_headers"]))
    assert resumed["version"] == 3


def test_derived_seat_counters_reconciled_after_hold(api):
    """PRD §2.6: "The held count, `seats_held`, is the number of `ACTIVE` booking legs
    on the service date whose owning booking is in `HELD` status ... The available
    count, `seats_available`, is the physical capacity `seats_total` minus `seats_held`
    minus `seats_sold`".

    After a single-leg hold on a seats_total=10 trip: held 1, sold 0, available 9.

    Design: Corner/cross_cutting_complexity_layers/derived_seat_counters_reconciled_after_hold
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000})
    passenger = fx.create_passenger()
    fx.hold_booking(passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"])
    sd = get_success_data(api.get_service_date(cat["service_date"]["id"], TEST_USERS["schedule_manager_headers"]))
    assert sd["seats_held"] == 1
    assert sd["seats_sold"] == 0
    assert sd["seats_available"] == 9


# ─── errors (corner): pass expired blocks confirm ──
def test_pass_expired_blocks_confirm(api):
    """PRD §3.10: "advancing the clock past the pass's `expires_on` drives the pass to
    the terminal `EXPIRED` state when observed on the next redemption attempt; an
    expired pass cannot fund new legs, and a redemption against it is rejected with
    `ERR_PASS_EXPIRED`."
    PRD §3.3: "a held pass booking that is later found expired at confirm raises the
    same temporal family handled under `ERR_HOLD_EXPIRED` for the hold itself."

    Pass expires 2026-06-05; clock advanced to 2026-06-10 before confirm. The PRD
    names BOTH outcomes for a confirm-time expired-pass redemption — §3.10 calls it
    `ERR_PASS_EXPIRED`, while §3.3 explicitly routes the confirm-time pass-expiry into
    the `ERR_HOLD_EXPIRED` temporal family — so a PRD-faithful implementation may
    raise either. Accept both members.

    Design: Corner/errors/pass_expired_blocks_confirm
    """
    cat = fx.setup_catalog(service_date_overrides={"seats_total": 10, "base_fare_cents": 4000, "departure_date": "2026-06-25"})
    passenger = fx.create_passenger()
    travel_pass = fx.create_pass(passenger["id"], cat["operator"]["id"], rides_total=5, expires_on="2026-06-05")
    booking = fx.hold_booking(
        passenger["id"], cat["service_date"]["id"], cat["fare_class"]["id"],
        funding_kind="PASS", pass_id=travel_pass["id"],
    )
    sd_v = fx.current_sd_version(cat["service_date"]["id"])
    fx.set_clock("2026-06-10T00:00:00Z")
    resp = api.confirm_booking(booking["id"], f.confirm_payload(sd_v), make_passenger_headers(passenger["id"]))
    assert resp.status_code == 409, f"expected HTTP 409, got {resp.status_code}"
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_PASS_EXPIRED.value, ApiErrorId.ERR_HOLD_EXPIRED.value]
    )
    after = get_success_data(api.get_booking(booking["id"], make_passenger_headers(passenger["id"])))
    assert after["booking_status"] == "HELD"
