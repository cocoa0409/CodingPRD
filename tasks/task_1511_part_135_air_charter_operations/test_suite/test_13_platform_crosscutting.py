"""Cross-cutting platform behavior: validation-priority ordering, OCC stale
version rejection, the fixed default logical clock, pagination, filters, and
the response envelope."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    is_iso8601_timestamp, ApiErrorId, NON_EXISTENT_UUID,
    create_trip, add_leg, create_owner, create_aircraft, setup_booked_trip,
    create_assignment,
    make_ops_admin_headers, make_sales_agent_headers,
    make_dispatch_manager_headers,
)

OPS_ADMIN = make_ops_admin_headers()
SALES_AGENT = make_sales_agent_headers()
DISPATCH_MANAGER = make_dispatch_manager_headers()


def _parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC instant regardless of rendering (Z vs +00:00,
    with or without fractional digits)."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Queue B: validations / existence_beats_state_on_leg_create
# ---------------------------------------------------------------------------

def test_leg_create_on_missing_trip_returns_404_not_state_error(api):
    """PRD §2.11: "Every request is evaluated against an ordered validation
    cascade, and the first failing check determines the error returned."
    PRD §2.11: "5. Existence — path identifiers and body foreign keys,
    validated left to right per §2.10; the resource-specific 404 applies."
    PRD §2.10: "The same existence rule covers foreign keys supplied in
    request bodies — a payload naming a nonexistent `trip_request_id`,
    `aircraft_id`, `crew_member_id`, `owner_id`, or `quote_leg_id` fails with
    the corresponding 404"

    Design: Corner/validations/existence_beats_state_on_leg_create
    """
    resp = api_client.create_quote_leg(
        {"trip_request_id": NON_EXISTENT_UUID, "seq_no": 1, "leg_type": "REVENUE",
         "origin_icao": "KLAX", "destination_icao": "KTEB",
         "block_minutes": 60, "fuel_stop": False},
        SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_TRIP_REQUEST_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / occ_requote_stale_version_412
# ---------------------------------------------------------------------------

def test_requote_with_stale_version_rejected(api):
    """PRD §2.7: "Two write endpoints guard against stale snapshots of a trip
    request by optimistic concurrency control: requoting a quoted trip, and
    creating an aircraft assignment. Both require the request body to carry
    `expected_trip_request_version`, holding the `version` of the
    `TripRequest` the client last observed. If the supplied value does not
    equal the trip's current `version` — because another writer has quoted,
    booked, requoted, or otherwise advanced the trip since the client read it
    — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/complexity_layers/occ_requote_stale_version_412
    """
    trip = create_trip(customer_name="Cust OC")
    add_leg(trip["id"], block_minutes=60)
    quoted = validate_success(api_client.quote_trip(trip["id"], SALES_AGENT), 200)
    v1 = quoted["version"]
    first = validate_success(api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": v1}, SALES_AGENT), 200)
    assert first["status"] == "QUOTE_DRAFT"
    assert first["version"] == v1 + 1
    # Replaying the same observed version is now stale.
    resp = api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": v1}, SALES_AGENT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_requote_stale_version_surfaces_before_state_error(api):
    """PRD §2.7: "This check is evaluated before the state preconditions of
    the endpoint, so a stale version surfaces as `ERR_STALE_VERSION` rather
    than being masked by a state error."
    (After the first requote the trip is QUOTE_DRAFT, so the state
    precondition would also fail; the OCC tier fires first.)

    Design: Corner/complexity_layers/occ_requote_stale_version_412
    """
    trip = create_trip(customer_name="Cust OC2")
    add_leg(trip["id"], block_minutes=60)
    quoted = validate_success(api_client.quote_trip(trip["id"], SALES_AGENT), 200)
    v1 = quoted["version"]
    validate_success(api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": v1}, SALES_AGENT), 200)
    resp = api_client.requote_trip(
        trip["id"], {"expected_trip_request_version": v1}, SALES_AGENT)
    assert resp.status_code == 412, (
        f"OCC tier must fire before the state tier; got {resp.status_code}")
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / occ_assignment_create_stale_version_412
# ---------------------------------------------------------------------------

def test_assignment_create_with_stale_version_rejected(api):
    """PRD §3.5: "The create carries the second optimistic-concurrency guard
    of §2.7 — `expected_trip_request_version` must equal the trip's current
    `version`, or the request is rejected with `ERR_STALE_VERSION` — because
    creating an assignment legitimately supersedes whatever tentative
    assignment the trip already has, and a writer acting on an old snapshot
    of the trip must be turned away."

    Design: Corner/complexity_layers/occ_assignment_create_stale_version_412
    """
    owner = create_owner(name="Owner OA", contact_email="oa@x.com")
    aircraft1 = create_aircraft(owner["id"], tail_number="N505OA")
    aircraft2 = create_aircraft(owner["id"], tail_number="N506OA")
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust OA")
    v_stale = trip["version"]
    asg1 = create_assignment(trip["id"], aircraft1["id"])  # bumps the trip version
    assert asg1["status"] == "TENTATIVE"
    resp = api_client.create_aircraft_assignment(
        {"trip_request_id": trip["id"], "aircraft_id": aircraft2["id"],
         "expected_trip_request_version": v_stale},
        DISPATCH_MANAGER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


def test_assignment_create_version_guard_distinct_from_state_family(api):
    """PRD §2.11: "6. Optimistic concurrency — on the two endpoints that
    declare `expected_trip_request_version`, the supplied version must equal
    the trip's current `version`; this tier is evaluated before the state
    preconditions below, and a mismatch yields `ERR_STALE_VERSION`."
    The stale create is answered 412, not a 409 state error.

    Design: Corner/complexity_layers/occ_assignment_create_stale_version_412
    """
    owner = create_owner(name="Owner OA2", contact_email="oa2@x.com")
    aircraft1 = create_aircraft(owner["id"], tail_number="N507OA")
    aircraft2 = create_aircraft(owner["id"], tail_number="N508OA")
    trip, _legs = setup_booked_trip(legs=((60, "REVENUE", False),), pay_in_full=False,
                                    customer_name="Cust OA2")
    v_stale = trip["version"]
    create_assignment(trip["id"], aircraft1["id"])
    resp = api_client.create_aircraft_assignment(
        {"trip_request_id": trip["id"], "aircraft_id": aircraft2["id"],
         "expected_trip_request_version": v_stale},
        DISPATCH_MANAGER)
    assert resp.status_code == 412
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Queue B: complexity_layers / clock_default_is_fixed_2026_08_01
# ---------------------------------------------------------------------------

def test_default_logical_clock_is_fixed(api):
    """PRD §2.4: "All time-dependent behavior in the system is evaluated
    against a logical clock, never wall-clock time. Before any clock-setting
    call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z."
    PRD §3.3: "The `quote_valid_until` is stamped at the current clock plus
    48 hours..."
    (The clock is deliberately never set in this test.)

    Design: Corner/complexity_layers/clock_default_is_fixed_2026_08_01
    """
    trip = create_trip(customer_name="Cust CK0", departure_at="2026-08-20T10:00:00Z")
    add_leg(trip["id"], block_minutes=60)
    quoted = validate_success(api_client.quote_trip(trip["id"], SALES_AGENT), 200)
    expected = datetime(2026, 8, 1, tzinfo=timezone.utc) + timedelta(hours=48)
    assert _parse_instant(quoted["quote_valid_until"]) == expected, (
        "quote_valid_until proves the fixed default clock, not wall-clock time")


# ---------------------------------------------------------------------------
# Queue B: endpoints / pagination_limit_offset_has_more
# ---------------------------------------------------------------------------

def test_list_pagination_limit_offset_has_more(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items from the start of the result set and
    defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries four pagination
    fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/pagination_limit_offset_has_more
    """
    create_trip(customer_name="Cust P1", requested_category="TURBOPROP",
                destination_icao="KLAS")
    create_trip(customer_name="Cust P2", requested_category="TURBOPROP",
                destination_icao="KLAS", departure_at="2026-08-11T10:00:00Z")
    page0, meta0 = validate_paginated(
        api_client.list_trip_requests(OPS_ADMIN, params={"limit": 1, "offset": 0}))
    assert len(page0) == 1
    assert meta0["total_count"] == 2
    assert meta0["has_more"] is True
    page1, meta1 = validate_paginated(
        api_client.list_trip_requests(OPS_ADMIN, params={"limit": 1, "offset": 1}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is False


# ---------------------------------------------------------------------------
# Queue B: endpoints / filter_aircraft_by_category
# ---------------------------------------------------------------------------

def test_list_aircraft_filter_by_category(api):
    """PRD §4: the endpoint table lists "List aircraft, optionally filtered
    by owner, category, or status".

    Design: Corner/endpoints/filter_aircraft_by_category
    """
    owner = create_owner(name="Owner FL", contact_email="fl@x.com")
    create_aircraft(owner["id"], tail_number="N100TP", category="TURBOPROP",
                    seats=6, hourly_rate_cents=140000)
    jet = create_aircraft(owner["id"], tail_number="N200LJ", category="LIGHT_JET")
    rows, meta = validate_paginated(
        api_client.list_aircraft(OPS_ADMIN, params={"category": "LIGHT_JET"}))
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == jet["id"]
    assert rows[0]["category"] == "LIGHT_JET"


# ---------------------------------------------------------------------------
# Queue B: endpoints / response_envelope_object_shape
# ---------------------------------------------------------------------------

def test_single_object_response_envelope_shape(api):
    """PRD §2.2: "The `api_request_id` is a server-generated unique
    identifier for the request that starts with `req_`."
    PRD §2.2: "The `response_type` is either "object" for a single resource
    or "array" for a list of resources."
    PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC
    timestamp with three fractional digits."

    Design: Corner/endpoints/response_envelope_object_shape
    """
    trip = create_trip(customer_name="Cust EV", requested_category="TURBOPROP",
                       destination_icao="KLAS")
    resp = api_client.get_trip_request(trip["id"], OPS_ADMIN)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == "object"
    assert body["data"]["id"] == trip["id"]
