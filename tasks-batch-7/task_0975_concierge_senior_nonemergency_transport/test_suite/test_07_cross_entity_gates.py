"""Cross-entity state gates: ride/series creation gated on client and rate-card
state, and offer acceptance gated on the driver aggregate's live state."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_booked_ride,
    create_client,
    create_ride_payload,
    create_standing_ride_payload,
    get_success_data,
    make_client_headers,
    make_driver_headers,
    set_clock,
    setup_standard_dispatch_env,
    suspend_client,
    validate_error,
    validate_success,
    api_client,
)

COORD = TEST_USERS["coordinator_headers"]


def test_ride_booking_rejected_for_suspended_client(api):
    """PRD §3.4: "The client must be `ACTIVE` — booking for a `SUSPENDED` or
    `DEACTIVATED` client is rejected with `ERR_CLIENT_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/ride_create_blocked_when_client_suspended
    """
    client = create_client()
    suspend_client(client["id"], client["version"])
    resp = api_client.create_ride(
        create_ride_payload(client["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED)


def test_ride_booking_rejected_for_deactivated_client(api):
    """PRD §3.4: "The client must be `ACTIVE` — booking for a `SUSPENDED` or
    `DEACTIVATED` client is rejected with `ERR_CLIENT_SUSPENDED`."
    PRD §3.1: "Deactivation — permitted from either `ACTIVE` or `SUSPENDED` —
    is guarded: the client must have no rides in any open state (`SCHEDULED`,
    `DISPATCHING`, `ASSIGNED`, `EN_ROUTE`, `ARRIVED`, or `IN_SERVICE`) and no
    invoices in `DRAFT`, `ISSUED`, or `PARTIALLY_PAID`, otherwise the request
    fails with `ERR_CLIENT_HAS_OPEN_WORK`. `DEACTIVATED` is terminal."

    Design: Difficulty/cross_entity_state_dependency/ride_create_blocked_when_client_suspended
    """
    client = create_client()
    resp = api_client.patch_client(
        client["id"],
        {"status": "DEACTIVATED", "expected_client_version": client["version"]},
        COORD)
    get_success_data(resp)
    resp = api_client.create_ride(
        create_ride_payload(client["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_CLIENT_SUSPENDED)


def _setup_offer_then_suspend_driver():
    """ACTIVE driver with a live OFFERED assignment, then SUSPENDed.
    Returns (ride, driver, offer)."""
    client, driver = setup_standard_dispatch_env()
    ride = create_booked_ride(client["id"], scheduled_pickup_at="2026-06-05T10:00:00Z")
    offer = get_success_data(api_client.dispatch_ride(ride["id"], COORD))
    get_success_data(api_client.driver_status_event(
        driver["id"], {"event_type": "SUSPEND", "reason": "complaint under review"}, COORD))
    return ride, driver, offer


def test_accept_after_driver_suspension_fails_eligibility_recheck(api):
    """PRD §3.2: "Outstanding `OFFERED` assignments are deliberately not
    expired by the cascade; they simply fail if the driver attempts to accept,
    rejected with `ERR_DRIVER_NOT_ELIGIBLE`."
    PRD §3.5: "Acceptance rechecks the full eligibility rule at that moment —
    an offer accepted late can still fail: a driver no longer `ACTIVE` or whose
    documents do not cover the pickup date is rejected with
    `ERR_DRIVER_NOT_ELIGIBLE`"

    Design: Difficulty/cross_entity_state_dependency/accept_blocked_when_driver_suspended
    """
    ride, driver, offer = _setup_offer_then_suspend_driver()
    resp = api_client.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ELIGIBLE)


def test_unaccepted_offer_survives_driver_suspension(api):
    """PRD §3.2: "Outstanding `OFFERED` assignments are deliberately not
    expired by the cascade; they simply fail if the driver attempts to accept,
    rejected with `ERR_DRIVER_NOT_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/accept_blocked_when_driver_suspended
    """
    ride, driver, offer = _setup_offer_then_suspend_driver()
    resp = api_client.respond_assignment(
        offer["id"], {"decision": "ACCEPT"}, make_driver_headers(driver["id"]))
    validate_error(resp, ApiErrorId.ERR_DRIVER_NOT_ELIGIBLE)
    asg = validate_success(api_client.get_assignment(offer["id"], COORD))
    assert asg["status"] == "OFFERED", "the offer is NOT auto-expired by suspension"
    ride_after = validate_success(api_client.get_ride(ride["id"], COORD))
    assert ride_after["status"] == "DISPATCHING"
    assert ride_after["assigned_driver_id"] is None


def test_standing_ride_creation_requires_active_rate_card(api):
    """PRD §3.4: "Series creation walks the same gates as one-off booking: the
    client must be `ACTIVE` (`ERR_CLIENT_SUSPENDED`), a
    `booked_by_family_member_id` recording the portal booker must belong to the
    series' client (`ERR_FAMILY_CLIENT_MISMATCH`), and the fiscal gates apply
    unchanged — rate-card availability for the derived class
    (`ERR_RATE_CARD_NOT_ACTIVE`) and the billing-hold check (`ERR_BILLING_HOLD`)."
    PRD §3.3: "Exactly one such card must exist; its absence rejects booking
    with `ERR_RATE_CARD_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/standing_ride_blocked_without_active_rate_card
    """
    client = create_client()
    resp = api_client.create_standing_ride(
        create_standing_ride_payload(client["id"]), COORD)
    validate_error(resp, ApiErrorId.ERR_RATE_CARD_NOT_ACTIVE)


def test_standing_ride_creation_succeeds_once_card_active(api):
    """PRD §3.3: "Every ride's fare — quoted or final — evaluates the same
    pinned formula against the single `ACTIVE` card of the ride's
    `service_class` whose window contains the pickup date. Exactly one such
    card must exist; its absence rejects booking with
    `ERR_RATE_CARD_NOT_ACTIVE`."
    PRD §3.4: "Creation immediately generates occurrences: for every calendar
    date matching the series weekday that falls from the logical today through
    the earlier of `ends_on` and fourteen days out — today included — a
    `SCHEDULED` ride is created"

    Design: Difficulty/cross_entity_state_dependency/standing_ride_blocked_without_active_rate_card
    """
    from test_helpers import create_active_rate_card
    client = create_client()
    create_active_rate_card()
    set_clock("2026-05-20T09:00:00Z")
    series = get_success_data(api_client.create_standing_ride(
        create_standing_ride_payload(client["id"]), COORD))
    assert series["status"] == "ACTIVE"
    assert series["next_occurrence_date"] == "2026-06-01"
