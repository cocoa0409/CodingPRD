"""Corner queue B: entity CRUD, defaults, not-found, required fields, listing,
and FK-reverse reads.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    NON_EXISTENT_UUID,
    register_fan,
    setup_held_ticket,
    make_fan_headers,
)
from test_helpers.fixtures import PROMOTER


def test_create_event_returns_201_with_defaults(api):
    """PRD §3.2: "it defaults to 110 and must be at least 100."
    PRD §3.2: "tickets_sold_count (the number of tickets issued for the event,
    starting at 0) and sales_status, the lifecycle gate, one of DRAFT, PRESALE,
    GENERAL, SOLD_OUT, or CLOSED, defaulting to DRAFT."
    PRD §2.4: "a version, an integer that begins at 1 at creation".

    Design: Corner/entities/create_event_returns_201_with_defaults
    """
    res = api.create_event(
        {"title": "E", "venue_capacity": 100, "presale_code": "S", "face_value_cents": 10000},
        PROMOTER,
    )
    event = validate_success(res, 201)
    assert event["sales_status"] == "DRAFT", event
    assert event["tickets_sold_count"] == 0, event
    assert event["resale_cap_pct"] == 110, event
    assert event["version"] == 1, event


def test_get_event_not_found(api):
    """PRD §2.8: "The first referenced resource that does not exist causes the
    request to be rejected with ERR_NOT_FOUND."

    Design: Corner/entities/get_event_not_found
    """
    res = api.get_event(NON_EXISTENT_UUID, PROMOTER)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_event_missing_required_field(api):
    """PRD §2.9: "Required-field and well-typedness checks surface as
    ERR_INVALID_REQUEST."
    PRD §3.2: "a face_value_cents base price (greater than zero)".

    Design: Corner/entities/create_event_missing_required_field
    """
    res = api.create_event(
        {"title": "E", "venue_capacity": 100, "presale_code": "S"},
        PROMOTER,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_register_then_verify_resolves_status(api):
    """PRD §3.1: "Registration always lands the new fan in the UNVERIFIED
    verification state with a freshly computed risk_score, and a
    completed_purchase_count of 0."
    PRD §3.1: "if the current risk_score is below the bot-flag threshold of 70,
    the fan transitions UNVERIFIED → VERIFIED."
    PRD §2.4: "a version, an integer that begins at 1 at creation and increments
    by exactly 1 on every mutation".

    Design: Corner/entities/register_then_verify_resolves_status
    """
    fan = register_fan("clean@x.com", device="dev-clean", full_name="Clean")
    assert fan["risk_score"] == 0, fan
    assert fan["verification_status"] == "UNVERIFIED", fan
    assert fan["version"] == 1, fan
    verified = validate_success(api.verify_fan(fan["id"], make_fan_headers(fan["id"])), 200)
    assert verified["verification_status"] == "VERIFIED", verified
    assert verified["version"] == 2, verified


def test_list_events_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned ... The
    meta object of every list response carries limit, offset, total_count, and
    has_more."

    Design: Corner/entities/list_events_pagination_envelope
    """
    api.create_event(
        {"title": "E1", "venue_capacity": 100, "presale_code": "S", "face_value_cents": 10000},
        PROMOTER,
    )
    api.create_event(
        {"title": "E2", "venue_capacity": 100, "presale_code": "S", "face_value_cents": 10000},
        PROMOTER,
    )
    data, meta = validate_paginated(api.list_events(PROMOTER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert len(data) == 1, data


def test_list_tickets_by_holder_fk_reverse(api):
    """PRD §4 (endpoint table): "GET /tickets | List tickets; filterable".
    PRD §3.5: "the holder_fan_id (the current holder, which changes when a
    transfer completes or a resale settles)".

    Filtering tickets by holder_fan_id returns that fan's tickets.

    Design: Corner/endpoints/list_tickets_by_holder_fk_reverse
    """
    event, tier, fan, order, ticket = setup_held_ticket(phase="GENERAL")
    data, _meta = validate_paginated(
        api.list_tickets(make_fan_headers(fan["id"]), params={"holder_fan_id": fan["id"]})
    )
    assert len(data) == 1, data
    assert data[0]["holder_fan_id"] == fan["id"], data
