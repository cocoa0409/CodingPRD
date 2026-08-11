"""Ride and assignment state machines: initial states, invalid transitions,
precondition enforcement, and dispatch side effects."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ride,
    create_booked_ride,
    create_client,
    create_completed_ride,
    create_driver,
    create_ride_payload,
    dispatch_and_accept,
    get_success_data,
    make_client_headers,
    make_driver_headers,
    set_clock,
    setup_standard_dispatch_env,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


def test_ride_created_in_scheduled_initial_state(api):
    """PRD §3.4: "the ride starts `SCHEDULED` with `dispatch_round` zero and an
    empty `excluded_driver_ids`, and the log opens with a `CREATED` event."

    Design: Corner/state_machines/ride_created_in_scheduled_initial_state
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    assert_ride(ride)
    assert ride["status"] == "SCHEDULED"
    assert ride["dispatch_round"] == 0
    assert ride["assigned_driver_id"] is None
    assert ride["excluded_driver_ids"] == []


def test_driver_created_in_applicant_initial_state(api):
    """PRD §3.2: "Drivers enter the platform as applicants. A `Coordinator`
    onboards a driver with `full_name`, `vehicle_class` (`SEDAN` or `WAV`, the
    wheelchair-accessible class), an `assist_certification` of `NONE`,
    `DOOR_TO_DOOR`, or `DOOR_THROUGH_DOOR`, a `home_zone`, and
    `max_daily_service_minutes`, the daily cap on forward-looking scheduled
    work. The record starts in `APPLICANT`."

    Design: Corner/state_machines/driver_created_in_applicant_initial_state
    """
    driver = create_driver()
    assert driver["status"] == "APPLICANT"


def test_cancel_completed_ride_returns_not_cancellable(api):
    """PRD §3.7: "A ride may be cancelled by the client themselves, by a family
    member of that client holding `BOOK_FOR_CLIENT` or `BILLING_PAYER`, or by a
    coordinator, from any of `SCHEDULED`, `DISPATCHING`, `ASSIGNED`,
    `EN_ROUTE`, or `ARRIVED`; attempts from `IN_SERVICE`, `COMPLETED`,
    `CANCELLED`, or `NO_SHOW` are rejected with `ERR_RIDE_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_completed_ride_returns_not_cancellable
    """
    client, driver = setup_standard_dispatch_env(clock="2026-05-20T09:00:00Z")
    ride = create_completed_ride(
        client["id"], driver["id"], "2026-06-01T10:00:00Z",
        estimated_duration_minutes=60, estimated_distance_miles=10,
        actual_distance_miles=10, service_minutes=60)
    assert ride["final_fare_cents"] == 4500
    resp = api_client.cancel_ride(
        ride["id"], {"cancel_note": "too late"}, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_RIDE_NOT_CANCELLABLE)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["final_fare_cents"] == 4500, "final fare is untouched"


def test_cancel_already_cancelled_returns_not_cancellable(api):
    """PRD §3.7: "attempts from `IN_SERVICE`, `COMPLETED`, `CANCELLED`, or
    `NO_SHOW` are rejected with `ERR_RIDE_NOT_CANCELLABLE`."
    PRD §3.7: "Notice of at least four hours — 240 minutes — but less than a
    full day bills half of `minimum_charge_cents`, rounded half-up to whole
    cents; exactly 240 lands in this half-fee tier."

    Design: Corner/state_machines/cancel_already_cancelled_returns_not_cancellable
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-06-08T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-10T16:00:00Z")
    set_clock("2026-06-10T12:00:00Z")
    first = validate_success(api_client.cancel_ride(
        ride["id"], {"cancel_note": "first"}, make_client_headers(client["id"])))
    assert first["cancellation_fee_cents"] == 1251
    resp = api_client.cancel_ride(
        ride["id"], {"cancel_note": "second"}, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_RIDE_NOT_CANCELLABLE)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["cancellation_fee_cents"] == 1251, "fee is not recomputed or doubled"


def test_dispatch_cancelled_ride_returns_not_dispatchable(api):
    """PRD §3.5: "Dispatching is a coordinator-driven match attempt against a
    ride in `SCHEDULED` or `DISPATCHING`; from any other status the attempt is
    rejected with `ERR_RIDE_NOT_DISPATCHABLE`"

    Design: Corner/state_machines/dispatch_cancelled_ride_returns_not_dispatchable
    """
    client, _ = setup_standard_dispatch_env(with_driver=False, clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    get_success_data(api_client.cancel_ride(
        ride["id"], {"cancel_note": "changed mind"}, make_client_headers(client["id"])))
    resp = api_client.dispatch_ride(ride["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_RIDE_NOT_DISPATCHABLE)


def test_dispatch_with_live_offer_returns_duplicate_offer(api):
    """PRD §3.5: "dispatching while an `OFFERED` assignment is still live for
    the ride is rejected with `ERR_DUPLICATE_OFFER`. Each attempt increments
    the ride's `dispatch_round` and runs the selector policy."

    Design: Corner/state_machines/dispatch_with_live_offer_returns_duplicate_offer
    """
    client, _ = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    resp = api_client.dispatch_ride(ride["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_OFFER)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["dispatch_round"] == 1, "rejected dispatch must not advance the round"


def test_respond_on_accepted_assignment_returns_not_actionable(api):
    """PRD §3.5: "The offered driver responds with a `decision` of `ACCEPT` or
    `DECLINE` and an optional `decline_reason`; responding to an assignment no
    longer `OFFERED` is `ERR_ASSIGNMENT_NOT_ACTIONABLE`"

    Design: Corner/state_machines/respond_on_accepted_assignment_returns_not_actionable
    """
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    _, assignment = dispatch_and_accept(ride["id"], driver["id"])
    resp = api_client.respond_assignment(
        assignment["id"], {"decision": "DECLINE", "decline_reason": "late"},
        make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIONABLE)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "ASSIGNED"


def test_release_offered_assignment_returns_release_invalid(api):
    """PRD §3.5: "releasing an `ACCEPTED` assignment (any other status is
    `ERR_ASSIGNMENT_RELEASE_INVALID`, with an optional `reason` recorded)"

    Design: Corner/state_machines/release_offered_assignment_returns_release_invalid
    """
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    resp = api_client.release_assignment(
        offer["id"], {"reason": "too early"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_RELEASE_INVALID)
    asg = validate_success(api_client.get_assignment(offer["id"], COORD))
    assert asg["status"] == "OFFERED"
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "DISPATCHING"


def test_service_started_from_assigned_returns_execution_event_invalid(api):
    """PRD §3.6: "An event not permitted from the ride's current status —
    including any attempt to begin service or complete while a wait segment is
    still open — is rejected with `ERR_EXECUTION_EVENT_INVALID`."
    PRD §3.6: "The happy path advances `ASSIGNED` → `EN_ROUTE` → `ARRIVED` →
    `IN_SERVICE` → `COMPLETED`."

    Design: Corner/state_machines/service_started_from_assigned_returns_execution_event_invalid
    """
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    dispatch_and_accept(ride["id"], driver["id"])
    resp = api_client.ride_execution_event(
        ride["id"], {"event_type": "SERVICE_STARTED"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_EXECUTION_EVENT_INVALID)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "ASSIGNED"


def _setup_arrived_ride_for_no_show():
    """Ride ARRIVED at 2026-06-01T09:55:00Z (pickup 10:00). Returns (client, driver, ride)."""
    from test_helpers import exec_event
    client, driver = setup_standard_dispatch_env(clock="2026-05-20T09:00:00Z")
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-01T10:00:00Z")
    dispatch_and_accept(ride["id"], driver["id"])
    exec_event(ride["id"], driver["id"], "EN_ROUTE", at_clock="2026-06-01T09:40:00Z")
    exec_event(ride["id"], driver["id"], "ARRIVED", at_clock="2026-06-01T09:55:00Z")
    return client, driver, ride


def test_no_show_before_fifteen_minutes_is_too_early(api):
    """PRD §3.6: "the assigned driver records `NO_SHOW` — but only once the
    logical now has reached fifteen minutes past `arrived_at`; an earlier
    attempt is `ERR_NO_SHOW_TOO_EARLY`."

    Design: Corner/state_machines/no_show_grace_enforced_at_fifteen_minutes
    """
    _, driver, ride = _setup_arrived_ride_for_no_show()
    set_clock("2026-06-01T10:05:00Z")
    resp = api_client.ride_execution_event(
        ride["id"], {"event_type": "NO_SHOW"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)
    after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert after["status"] == "ARRIVED"


def test_no_show_at_exactly_fifteen_minutes_succeeds(api):
    """PRD §3.6: "A recorded no-show sets `no_show_fee_cents` (zero until that
    moment) to the rate card's `minimum_charge_cents`, increments the client's
    `no_show_count`, and logs `NO_SHOW_RECORDED`."

    Design: Corner/state_machines/no_show_grace_enforced_at_fifteen_minutes
    """
    client, driver, ride = _setup_arrived_ride_for_no_show()
    set_clock("2026-06-01T10:05:00Z")
    validate_error(
        api_client.ride_execution_event(
            ride["id"], {"event_type": "NO_SHOW"}, make_driver_headers(driver["id"])),
        ApiErrorId.ERR_NO_SHOW_TOO_EARLY)
    set_clock("2026-06-01T10:10:00Z")
    no_show = validate_success(api_client.ride_execution_event(
        ride["id"], {"event_type": "NO_SHOW"}, make_driver_headers(driver["id"])))
    assert no_show["status"] == "NO_SHOW"
    assert no_show["no_show_fee_cents"] == 2501, (
        f"no-show fee equals the card minimum 2501; got {no_show['no_show_fee_cents']}")
    client_after = validate_success(api_client.get_client(client["id"], COORD))
    assert client_after["no_show_count"] == 1


def test_dispatch_creates_offer_with_expiry_and_audit_fields(api):
    """PRD §3.5: "A non-empty pool yields one `OFFERED` assignment stamped with
    `offered_at`, an `offer_expires_at` thirty minutes later, the `round` at
    which it was made, `matched_by` of `COORDINATOR`, and the dispatcher's
    identifier in `matched_by_user_id`; the ride log gains `DISPATCHED` and
    `OFFERED` events."

    Design: Corner/state_machines/dispatch_creates_offer_with_expiry_and_audit_fields
    """
    from test_helpers import make_coordinator_headers
    client, _ = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(
        ride["id"], make_coordinator_headers("coord-1")))
    assert offer["status"] == "OFFERED"
    assert offer["round"] == 1
    assert offer["matched_by"] == "COORDINATOR"
    assert offer["matched_by_user_id"] == "coord-1"
    from datetime import datetime, timedelta
    # PRD fixes the 30-minute gap but not the serialization format of these
    # fields, so parse tolerantly (with or without fractional digits).
    def _parse(ts):
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    offered_at = _parse(offer["offered_at"])
    expires_at = _parse(offer["offer_expires_at"])
    assert expires_at - offered_at == timedelta(minutes=30), (
        f"offer_expires_at must be offered_at + 30 minutes; got "
        f"{offer['offered_at']} -> {offer['offer_expires_at']}")
