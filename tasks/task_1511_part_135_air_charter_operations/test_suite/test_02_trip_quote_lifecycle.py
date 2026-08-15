"""Trip request booking-axis lifecycle: quote/requote cycle, quote expiry,
itinerary edit gating, and the requote re-vet loop."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_version_incremented, ApiErrorId,
    create_trip, add_leg, quote_trip, book_trip, get_trip, set_clock,
    setup_quoted_trip, setup_booked_trip,
    make_ops_admin_headers, make_sales_agent_headers,
)

OPS_ADMIN = make_ops_admin_headers()
SALES_AGENT = make_sales_agent_headers()


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine / trip_request_requote_cycle
# ---------------------------------------------------------------------------

def test_requote_clears_pricing_and_returns_to_quote_draft(api):
    """PRD §3.3: "Requoting clears `quoted_total_cents`,
    `deposit_required_cents`, and `quote_valid_until` to null, returns the
    trip to `QUOTE_DRAFT`, increments its `version`, and forces the same
    re-vet loop as an itinerary change — `VETTED` and `FLAGGED_ILLEGAL` crew
    assignments fall back to `PROPOSED` with their computed fields cleared."

    Design: Difficulty/non_linear_state_machine/trip_request_requote_cycle
    """
    # Leg REV 60 on LIGHT_JET: legs 250000, surcharge 20000 -> quote 270000.
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),),
                                    departure_at="2026-08-20T10:00:00Z",
                                    customer_name="Cust Q")
    assert trip["quoted_total_cents"] == 270000
    v1 = trip["version"]

    resp = api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": v1}, SALES_AGENT)
    draft = validate_success(resp, expected_status=200)
    assert draft["status"] == "QUOTE_DRAFT"
    assert draft["quoted_total_cents"] is None
    assert draft["deposit_required_cents"] is None
    assert draft["quote_valid_until"] is None
    assert_version_incremented(draft["version"], v1)


def test_requote_cycle_reprices_new_itinerary_posture_stays_unpaid(api):
    """PRD §3.3: "The `quoted_total_cents` is the legs total minus the volume
    discount plus the fuel surcharge, the stop fees, and the international
    fee."
    PRD §3.2: "Two status axes now run in parallel: the booking axis
    (`QUOTE_DRAFT`, `QUOTED`, `BOOKED`, `DISPATCHED`, and the terminals
    `COMPLETED`, `CANCELLED`, `EXPIRED`) is driven by explicit actions, while
    the payment axis (`UNPAID`, `DEPOSIT_PAID`, `PAID_IN_FULL`, and the
    post-cancellation `REFUNDED_PARTIAL` and `REFUNDED_FULL`) is derived
    solely from posted payment rows and is never set directly."

    Design: Difficulty/non_linear_state_machine/trip_request_requote_cycle
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),),
                                    departure_at="2026-08-20T10:00:00Z",
                                    customer_name="Cust Q")
    draft = validate_success(api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": trip["version"]}, SALES_AGENT), 200)
    assert draft["payment_posture"] == "UNPAID"

    # Extend the itinerary with a 30-minute positioning leg, then re-quote:
    # legs = 250000 + 75000 = 325000; surcharge 8% = 26000; total 351000.
    add_leg(trip["id"], seq_no=2, block_minutes=30, leg_type="POSITIONING",
            origin_icao="KTEB", destination_icao="KLAX")
    requoted = quote_trip(trip["id"])
    assert requoted["status"] == "QUOTED"
    assert requoted["quoted_total_cents"] == 351000
    assert requoted["payment_posture"] == "UNPAID", (
        "payment axis untouched by the QUOTED -> QUOTE_DRAFT -> QUOTED cycle")


# ---------------------------------------------------------------------------
# Queue B: state_machines / quote_from_quoted_rejected
# ---------------------------------------------------------------------------

def test_quote_from_quoted_rejected(api):
    """PRD §3.3: "With at least one leg in place — pricing a legless trip
    fails with `ERR_INVALID_REQUEST` — a `SalesAgent` prices a `QUOTE_DRAFT`
    trip (any other status yields `ERR_TRIP_NOT_QUOTE_DRAFT`)."

    Design: Corner/state_machines/quote_from_quoted_rejected
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust QQ")
    resp = api_client.quote_trip(trip["id"], SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTE_DRAFT)


# ---------------------------------------------------------------------------
# Queue B: state_machines / book_from_quote_draft_rejected
# ---------------------------------------------------------------------------

def test_book_from_quote_draft_rejected(api):
    """PRD §3.4: "A `SalesAgent` books a trip in `QUOTED` status (otherwise
    `ERR_TRIP_NOT_QUOTED`) by supplying `deposit_cents`."

    Design: Corner/state_machines/book_from_quote_draft_rejected
    """
    trip = create_trip(customer_name="Cust BK")
    add_leg(trip["id"], block_minutes=60)
    resp = api_client.book_trip(trip["id"], {"deposit_cents": 67500}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTED)


# ---------------------------------------------------------------------------
# Queue B: state_machines / requote_from_booked_rejected
# ---------------------------------------------------------------------------

def test_requote_from_booked_rejected(api):
    """PRD §3.3: "Requoting requires the trip to be `QUOTED` (otherwise
    `ERR_TRIP_NOT_QUOTED`) and carries the optimistic-concurrency guard of
    §2.7: the request must present `expected_trip_request_version` equal to
    the trip's current `version`, or it is rejected with `ERR_STALE_VERSION`."

    Design: Corner/state_machines/requote_from_booked_rejected
    """
    trip, _legs = setup_booked_trip(pay_in_full=False, customer_name="Cust RQ")
    assert trip["status"] == "BOOKED"
    resp = api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": trip["version"]}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTED)


# ---------------------------------------------------------------------------
# Queue B: state_machines / quote_expiry_via_clock_terminal_lockdown
# ---------------------------------------------------------------------------

def test_quote_expiry_via_clock_locks_booking(api):
    """PRD §3.3: "Left alone, a quoted trip does not last: when a clock
    advance carries the logical clock past `quote_valid_until`, the sweep of
    §2.4 moves the trip from `QUOTED` to `EXPIRED` and increments its
    `version`."
    PRD §3.4: "A `SalesAgent` books a trip in `QUOTED` status (otherwise
    `ERR_TRIP_NOT_QUOTED`) by supplying `deposit_cents`."

    Design: Corner/state_machines/quote_expiry_via_clock_terminal_lockdown
    """
    # Quoted against the default clock 2026-08-01T00:00:00Z -> valid until
    # 2026-08-03T00:00:00Z; advancing one second past expires the quote.
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust EX")
    set_clock("2026-08-03T00:00:01Z")
    expired = get_trip(trip["id"])
    assert expired["status"] == "EXPIRED"
    resp = api_client.book_trip(trip["id"], {"deposit_cents": 67500}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTED)


# ---------------------------------------------------------------------------
# Queue B: state_machines / leg_add_on_quoted_trip_rejected
# ---------------------------------------------------------------------------

def test_leg_add_on_quoted_trip_rejected(api):
    """PRD §3.2: "Legs may be added or removed only while the trip is in
    `QUOTE_DRAFT`; either operation against a trip in any other status is
    rejected with `ERR_TRIP_NOT_QUOTE_DRAFT`."

    Design: Corner/state_machines/leg_add_on_quoted_trip_rejected
    """
    trip, _legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust LA")
    resp = api_client.create_quote_leg(
        {"trip_request_id": trip["id"], "seq_no": 2, "leg_type": "POSITIONING",
         "origin_icao": "KTEB", "destination_icao": "KLAX",
         "block_minutes": 30, "fuel_stop": False},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTE_DRAFT)


# ---------------------------------------------------------------------------
# Queue B: state_machines / delete_leg_quote_draft_ok
# ---------------------------------------------------------------------------

def test_delete_leg_on_quote_draft_succeeds(api):
    """PRD §3.2: "Legs may be added or removed only while the trip is in
    `QUOTE_DRAFT`; either operation against a trip in any other status is
    rejected with `ERR_TRIP_NOT_QUOTE_DRAFT`."
    PRD §4: "The single deletion operation, removing a quote leg, returns
    `204 No Content` with an empty body."

    Design: Corner/state_machines/delete_leg_quote_draft_ok
    """
    trip = create_trip(customer_name="Cust DL")
    leg = add_leg(trip["id"], block_minutes=60)
    resp = api_client.delete_quote_leg(leg["id"], SALES_AGENT)
    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    rows, meta = validate_paginated(api_client.list_quote_legs(trip["id"], SALES_AGENT))
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# Queue B: endpoints / quote_leg_delete_non_draft_rejected
# ---------------------------------------------------------------------------

def test_delete_leg_on_quoted_trip_rejected(api):
    """PRD §3.2: "Legs may be added or removed only while the trip is in
    `QUOTE_DRAFT`; either operation against a trip in any other status is
    rejected with `ERR_TRIP_NOT_QUOTE_DRAFT`."

    Design: Corner/endpoints/quote_leg_delete_non_draft_rejected
    """
    trip, legs = setup_quoted_trip(legs=((60, "REVENUE", False),), customer_name="Cust QD")
    resp = api_client.delete_quote_leg(legs[0]["id"], SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_NOT_QUOTE_DRAFT)
