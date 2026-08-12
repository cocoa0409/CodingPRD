"""Routes: half-open window overlap, publish gate, archival, capacity; and
pickup ticket scheduling, completion, and missed-report gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_pickup_ticket,
    complete_ticket,
    create_household,
    create_pickup_ticket_payload,
    create_published_route,
    create_route,
    create_route_payload,
    create_subscription,
    create_ticket,
    create_zone,
    get_ticket,
    make_resident_headers,
    make_supervisor_headers,
    report_missed,
    set_clock,
    setup_active_household_with_route,
    setup_households_with_active_subscriptions,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / route_window_half_open_adjacency
# ---------------------------------------------------------------------------

def test_route_window_overlap_rejected(api, admin_headers):
    """PRD section 3.4: "Two routes in the same zone on the same weekday may not
    have overlapping half-open windows while both are non-`ARCHIVED`; such a
    conflict is rejected with `ERR_ROUTE_WINDOW_OVERLAP`". [2026-07-01,
    2026-10-01) overlaps the existing [2026-05-01, 2026-08-01).

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_adjacency
    """
    zone = create_zone()
    r1 = create_route(zone["id"], effective_start_date="2026-05-01",
                      effective_end_date="2026-08-01")
    assert r1["status"] == "DRAFT"

    res = api.create_route(
        create_route_payload(zone["id"], effective_start_date="2026-07-01",
                             effective_end_date="2026-10-01"),
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_ROUTE_WINDOW_OVERLAP)


def test_route_window_adjacency_allowed(api, admin_headers):
    """PRD section 3.4: "though adjacency — one route's window ending exactly
    where the next begins — is allowed." [2026-08-01, 2026-10-31) begins exactly
    where the existing [2026-05-01, 2026-08-01) ends.

    Design: Difficulty/resource_temporal_overlap/route_window_half_open_adjacency
    """
    zone = create_zone()
    r1 = create_route(zone["id"], effective_start_date="2026-05-01",
                      effective_end_date="2026-08-01")

    r3 = validate_success(api.create_route(
        create_route_payload(zone["id"], effective_start_date="2026-08-01",
                             effective_end_date="2026-10-31"),
        admin_headers), 201)
    assert r3["status"] == "DRAFT"

    r1_after = validate_success(api.get_route(r1["id"], admin_headers), 200)
    assert r1_after["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B: routes
# ---------------------------------------------------------------------------

def test_route_draft_blocks_ticket_then_publish_allows(api, admin_headers, supervisor_headers):
    """PRD section 3.4: "A route starts `DRAFT`, is made bookable when a
    `ProgramAdmin` publishes it (`DRAFT` is required, otherwise
    `ERR_INVALID_STATE`)" and "the route must be `PUBLISHED`
    (`ERR_ROUTE_NOT_PUBLISHED`)" for ticket scheduling.

    Design: Corner/endpoints/route_draft_blocks_ticket_then_publish_allows
    """
    set_clock("2026-04-15T00:00:00Z")
    zone = create_zone(set_clock_first=False, service_model="UNIVERSAL",
                       base_seasonal_fee_cents=9000)
    household = create_household(zone["id"])
    sub = create_subscription(household, season_year=2026)
    assert sub["status"] == "ACTIVE"
    route = create_route(zone["id"])

    res = api.create_pickup_ticket(
        create_pickup_ticket_payload(sub["id"], route["id"], "2026-05-04"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_ROUTE_NOT_PUBLISHED)

    validate_success(api.publish_route(route["id"], admin_headers), 200)
    ticket = validate_success(api.create_pickup_ticket(
        create_pickup_ticket_payload(sub["id"], route["id"], "2026-05-04"),
        supervisor_headers), 201)
    assert_pickup_ticket(ticket)
    assert ticket["status"] == "SCHEDULED"


def test_route_auto_archive_by_clock(api, admin_headers):
    """PRD section 3.4: "and becomes `ARCHIVED` automatically once the clock
    date passes its `effective_end_date`, applied lazily on access."

    Design: Corner/state_machines/route_auto_archive_by_clock
    """
    zone = create_zone(clock="2026-05-05T00:00:00Z")
    route = create_route(zone["id"], effective_start_date="2026-05-01",
                         effective_end_date="2026-06-01")
    published = validate_success(api.publish_route(route["id"], admin_headers), 200)
    assert published["status"] == "PUBLISHED"

    set_clock("2026-06-05T00:00:00Z")
    route_after = validate_success(api.get_route(route["id"], admin_headers), 200)
    assert route_after["status"] == "ARCHIVED"


def test_route_stop_capacity_boundary(api, admin_headers, supervisor_headers):
    """PRD section 3.4: "if that count already equals or exceeds `max_stops`,
    the new ticket is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED` (a count one
    below the cap is allowed)." With max_stops 2 the first two tickets are
    scheduled and the third is rejected.

    Design: Corner/calculations/route_stop_capacity_boundary
    """
    zone = create_zone(service_model="UNIVERSAL", base_seasonal_fee_cents=9000)
    households = setup_households_with_active_subscriptions(zone, 3)
    route = create_published_route(zone["id"], max_stops=2, max_tonnage_lbs=100000)

    for entry in households[:2]:
        create_ticket(entry["subscription"]["id"], route["id"], "2026-05-04")

    res = api.create_pickup_ticket(
        create_pickup_ticket_payload(households[2]["subscription"]["id"], route["id"], "2026-05-04"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)


def test_route_tonnage_boundary(api, admin_headers, supervisor_headers):
    """PRD section 3.4: "Second, project the day's tonnage as the existing count
    plus the new ticket, multiplied by an average of 200 pounds per ticket; if
    that projection exceeds `max_tonnage_lbs`, the ticket is rejected with
    `ERR_ROUTE_TONNAGE_EXCEEDED` (a projection exactly equal to the cap is
    allowed)." max_tonnage 400: the 2nd ticket projects (1+1)x200 == 400 and is
    allowed; the 3rd projects 600 > 400 and is rejected.

    Design: Corner/calculations/route_tonnage_boundary
    """
    zone = create_zone(service_model="UNIVERSAL", base_seasonal_fee_cents=9000)
    households = setup_households_with_active_subscriptions(zone, 3)
    route = create_published_route(zone["id"], max_stops=10, max_tonnage_lbs=400)

    t1 = create_ticket(households[0]["subscription"]["id"], route["id"], "2026-05-04")
    t2 = create_ticket(households[1]["subscription"]["id"], route["id"], "2026-05-04")
    assert t1["status"] == "SCHEDULED"
    assert t2["status"] == "SCHEDULED"

    res = api.create_pickup_ticket(
        create_pickup_ticket_payload(households[2]["subscription"]["id"], route["id"], "2026-05-04"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_ROUTE_TONNAGE_EXCEEDED)

    assert get_ticket(t1["id"])["status"] == "SCHEDULED"
    assert get_ticket(t2["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Queue B: pickup ticket listing and scheduling shape
# ---------------------------------------------------------------------------

def test_ticket_list_pagination_envelope(api, admin_headers):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter skips that many items from the start of the result set
    and defaults to 0." and "The `meta` object of a list response carries four
    pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/ticket_list_pagination_envelope
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    for date in ("2026-05-04", "2026-05-11", "2026-05-18"):
        create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], date)

    page1, meta1 = validate_paginated(
        api.list_pickup_tickets(admin_headers, params={"route_id": ctx["route"]["id"],
                                                       "limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2
    assert meta1["offset"] == 0

    page2, meta2 = validate_paginated(
        api.list_pickup_tickets(admin_headers, params={"route_id": ctx["route"]["id"],
                                                       "limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_ticket_weekday_mismatch_returns_invalid_request(api, admin_headers, supervisor_headers):
    """PRD section 3.4: "the weekday of the `service_date` must match the
    route's `weekday` (`ERR_INVALID_REQUEST`)". 2026-05-05 is a Tuesday and does
    not match a MONDAY route.

    Design: Corner/validations/ticket_weekday_mismatch_returns_invalid_request
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    res = api.create_pickup_ticket(
        create_pickup_ticket_payload(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-05"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)


def test_ticket_date_out_of_season(api, admin_headers, supervisor_headers):
    """PRD section 3.4: "the `service_date` must fall inside the zone's season
    window inclusive on both ends (`ERR_TICKET_DATE_OUT_OF_SEASON`)".
    2026-11-30 is a Monday after the 2026-10-31 season end.

    Design: Corner/validations/ticket_date_out_of_season
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    res = api.create_pickup_ticket(
        create_pickup_ticket_payload(ctx["subscription"]["id"], ctx["route"]["id"], "2026-11-30"),
        supervisor_headers,
    )
    validate_error(res, ApiErrorId.ERR_TICKET_DATE_OUT_OF_SEASON)


def test_report_missed_before_service_date(api, admin_headers):
    """PRD section 3.6: "the report may only be filed on or after the ticket's
    `service_date` — reporting before the scheduled day is rejected with
    `ERR_TICKET_NOT_YET_DUE`".

    Design: Corner/validations/report_missed_before_service_date
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-11")
    set_clock("2026-05-04T00:00:00Z")  # before the ticket's service date

    res = api.report_missed_pickup_ticket(ticket["id"], make_resident_headers(ctx["household"]["id"]))
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_YET_DUE)
    assert get_ticket(ticket["id"])["status"] == "SCHEDULED"


def test_report_missed_on_completed_ticket_rejected(api, admin_headers):
    """PRD section 3.6: "The ticket must be `SCHEDULED`
    (`ERR_TICKET_NOT_SCHEDULED`)" for a missed-pickup report.

    Design: Corner/state_machines/report_missed_on_completed_ticket_rejected
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    complete_ticket(ticket["id"], 100)
    set_clock("2026-05-05T00:00:00Z")

    res = api.report_missed_pickup_ticket(ticket["id"], make_resident_headers(ctx["household"]["id"]))
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_SCHEDULED)
    assert get_ticket(ticket["id"])["status"] == "COMPLETED"


def test_validate_missed_on_scheduled_ticket_rejected(api, admin_headers, supervisor_headers):
    """PRD section 3.6: "The ticket must be `MISSED_REPORTED` (otherwise
    `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/validate_missed_on_scheduled_ticket_rejected
    """
    ctx = setup_active_household_with_route(service_model="UNIVERSAL")
    ticket = create_ticket(ctx["subscription"]["id"], ctx["route"]["id"], "2026-05-04")
    set_clock("2026-05-05T00:00:00Z")

    res = api.validate_missed_pickup_ticket(ticket["id"], {"validated": True}, supervisor_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert get_ticket(ticket["id"])["status"] == "SCHEDULED"
