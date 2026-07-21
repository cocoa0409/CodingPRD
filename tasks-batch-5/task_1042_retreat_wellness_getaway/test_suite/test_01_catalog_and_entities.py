"""Catalog creation, entity defaults, not-found handling, listing, and immediate visibility."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_guest_headers,
    create_retreat_payload, create_room_payload, create_guest_payload,
    assert_retreat, assert_guest,
    set_clock, setup_published_retreat, setup_booking,
    new_retreat,
)
from test_helpers.constants import DEFAULT_CLOCK, PARTY2_BASE150000

_OP = TEST_USERS["operator_headers"]
_ANON = TEST_USERS["anonymous_headers"]


def test_create_retreat_returns_draft_defaults(api):
    """PRD §3.1: "A freshly created retreat reports `status` of `DRAFT`, a `reserved_count` of 0, and a `schedule_ready` flag of false."
    PRD §2.4: "a `version` integer that begins at 1 and increments by one on each mutation."

    Design: Corner/entities/corner_retreat_creation_returns_draft
    """
    set_clock(api, DEFAULT_CLOCK)
    resp = api.create_retreat(create_retreat_payload(capacity=10, base_price_cents=100000), _OP)
    data = validate_success(resp, 201)
    assert_retreat(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["reserved_count"] == 0
    assert data["schedule_ready"] is False


def test_create_retreat_missing_base_price_rejected(api):
    """PRD §2.9: "Fourth is body well-formedness — required fields present, enum values legal, integer amounts non-negative, and any end instant strictly after its start instant — with `ERR_VALIDATION` (400) on failure."

    Design: Corner/entities/corner_retreat_missing_required_field_rejected
    """
    payload = {
        "name": "Bad", "theme": "YOGA", "location": "X",
        "start_date": "2026-09-01T00:00:00Z", "end_date": "2026-09-08T00:00:00Z",
        "capacity": 10,
    }
    resp = api.create_retreat(payload, _OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_guest_registration_defaults_dietary_notes_empty(api):
    """PRD §3.4: "optionally a `phone`, `dietary_notes`, and `health_notes` (each defaulting to an empty string)."

    Design: Corner/entities/corner_guest_default_dietary_notes_empty
    """
    resp = api.create_guest(create_guest_payload(email="d@example.com", full_name="D"), _ANON)
    data = validate_success(resp, 201)
    assert_guest(data)
    assert data["dietary_notes"] == ""


def test_get_unknown_retreat_returns_not_found(api):
    """PRD §2.5: "Each entity type has its own not-found error: a missing retreat yields `ERR_RETREAT_NOT_FOUND`, a missing room `ERR_ROOM_NOT_FOUND`"

    Design: Corner/entities/corner_retreat_not_found_returns_404
    """
    resp = api.get_retreat("00000000-0000-4000-8000-000000000000", _OP)
    validate_error(resp, ApiErrorId.ERR_RETREAT_NOT_FOUND.value)


def test_get_unknown_booking_returns_not_found(api):
    """PRD §2.5: "a missing facilitator `ERR_FACILITATOR_NOT_FOUND`, a missing booking `ERR_BOOKING_NOT_FOUND`, a missing waiver `ERR_WAIVER_NOT_FOUND`, a missing shuttle `ERR_SHUTTLE_NOT_FOUND`"

    Design: Corner/entities/corner_booking_not_found_returns_404
    """
    resp = api.get_booking("00000000-0000-4000-8000-000000000001", _OP)
    validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND.value)


def test_create_room_invalid_kind_rejected(api):
    """PRD §2.9: "Fourth is body well-formedness — required fields present, enum values
    legal ... with ERR_VALIDATION (400) on failure."

    Design: Corner/entities/corner_room_kind_enum_invalid_rejected
    """
    retreat = new_retreat(api, capacity=10, base_price_cents=100000)
    resp = api.create_room(
        create_room_payload(retreat["id"], kind="PALACE", bed_count=2, label="R"), _OP)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_list_bookings_filtered_by_guest(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD §4: "GET | `/v1/bookings` | List bookings by retreat, guest, or room"

    Design: Corner/endpoints/corner_list_bookings_by_guest_filter
    """
    ctx = setup_booking(api, party_size=2)
    gh = ctx["guest_headers"]
    resp = api.list_bookings(gh, params={"guest_id": ctx["guest"]["id"]})
    data, meta = validate_paginated(resp)
    ids = [b["id"] for b in data]
    assert ctx["booking"]["id"] in ids
    assert "total_count" in meta and "has_more" in meta


def test_list_retreats_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter caps how many items a response returns; when omitted it defaults to 10, and callers may request a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0."

    Design: Corner/endpoints/corner_list_retreats_pagination_defaults
    """
    new_retreat(api, capacity=10, base_price_cents=150000)
    resp = api.list_retreats(_OP)
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


def test_booking_immediately_readable_after_create(api):
    """PRD §3.2: "The `grand_total_cents` is the pre-tax total plus that tax; this is the amount the guest ultimately owes."
    PRD §2.4: "Every resource is assigned an id, a server-minted UUID that carries no type prefix."

    Design: Corner/consistency_model/corner_immediate_visibility_of_booking
    """
    ctx = setup_booking(api, party_size=2)
    gh = ctx["guest_headers"]
    resp = api.get_booking(ctx["booking"]["id"], gh)
    data = validate_success(resp, 200)
    assert data["status"] == "PENDING_DEPOSIT"
    assert data["grand_total_cents"] == PARTY2_BASE150000["grand_total_cents"]
