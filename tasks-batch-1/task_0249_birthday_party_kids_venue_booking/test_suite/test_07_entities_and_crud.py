"""Entity creation, retrieval, listing, defaults, and request-shape validation
for venues, bookings, add-ons, and guest-party roster events.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    setup_config, create_venue_payload, create_booking_payload, create_quote_draft_booking,
    record_roster, NON_EXISTENT_UUID, assert_instant_eq,
)

VM = "venue_manager_headers"
COORD = "coordinator_headers"


# ─── Corner: entities / create_venue_returns_201_with_defaults ─────────────────

def test_create_venue_applies_defaults(api, venue_manager_headers):
    """PRD 3.1: "a `weather_dependent` flag (defaulting to false, marking whether
    outdoor bookings here may be weather-held), and a `reschedule_lead_hours` value
    (defaulting to 48, the lead time a guardian self-reschedule would require)."
    PRD 3.1: "A venue begins life — and remains — in `ACTIVE`".

    Design: Corner/entities/create_venue_returns_201_with_defaults
    """
    res = api.create_venue({"name": "Acme"}, venue_manager_headers)
    venue = validate_success(res, 201)
    assert venue["status"] == "ACTIVE"
    assert venue["timezone"] == "UTC"
    assert venue["weather_dependent"] is False
    assert venue["reschedule_lead_hours"] == 48


# ─── Corner: entities / get_booking_returns_stored_and_computed ────────────────

def test_get_booking_returns_computed_fields(api, coordinator_headers, guardian_headers):
    """PRD 3.2: "At creation the server sets `effective_duration_minutes` to the
    package's `base_duration_minutes`, computes `event_end_utc` from the start plus
    that duration, sets `waivers_required` equal to `children_count`, initializes
    `payment_status` to `UNPAID`".

    Design: Corner/entities/get_booking_returns_stored_and_computed
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=8,
                                        base_duration_minutes=120)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    # All roles may call read endpoints; ownership is not checked on GET.
    fetched = validate_success(api.get_booking(bid, guardian_headers), 200)
    assert_instant_eq(fetched["event_end_utc"], "2026-07-01T12:00:00Z")
    assert fetched["quote_total_cents"] == 30000
    assert fetched["waivers_required"] == 8
    assert fetched["payment_status"] == "UNPAID"
    assert fetched["status"] == "QUOTE_DRAFT"


# ─── Corner: entities / list_bookings_paginated_envelope ───────────────────────

def test_list_bookings_pagination_envelope(api, coordinator_headers, venue_manager_headers):
    """PRD 2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_bookings_paginated_envelope
    """
    venue, room, package = setup_config()
    create_quote_draft_booking(room["id"], package["id"], children_count=8,
                               event_start_utc="2026-07-01T10:00:00Z")
    create_quote_draft_booking(room["id"], package["id"], children_count=8,
                               event_start_utc="2026-07-02T10:00:00Z")
    data, meta = validate_paginated(api.list_bookings(venue_manager_headers,
                                                      params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


# ─── Corner: entities / get_booking_not_found ──────────────────────────────────

def test_get_nonexistent_booking_not_found(api, venue_manager_headers):
    """PRD 2.7: "a missing booking yields `ERR_BOOKING_NOT_FOUND` before the child is
    ever consulted".

    Design: Corner/entities/get_booking_not_found
    """
    res = api.get_booking("00000000-0000-4000-8000-000000000000", venue_manager_headers)
    validate_error(res, "ERR_BOOKING_NOT_FOUND", expected_status=404)


# ─── Corner: entities / create_booking_missing_required_field ──────────────────

def test_create_booking_missing_children_count_rejected(api, coordinator_headers):
    """PRD 2.8: "(5) field-level request shape and bounds (`ERR_INVALID_REQUEST`)".
    PRD 3.2: "who supplies a `room_id`, a `package_id`, an `event_start_utc`, a
    `children_count` (at least 1), and optionally an `adults_count` (defaulting to 0)."

    Design: Corner/entities/create_booking_missing_required_field
    """
    venue, room, package = setup_config()
    res = api.create_booking(
        {"room_id": room["id"], "package_id": package["id"],
         "event_start_utc": "2026-07-01T10:00:00Z"}, coordinator_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities / create_booking_adults_count_default_zero ───────────────

def test_create_booking_adults_count_defaults_zero(api, coordinator_headers):
    """PRD 3.2: "and optionally an `adults_count` (defaulting to 0)."
    PRD 3.2: "The `headcount_committed` field is reconciled as the sum of
    `children_count` and `adults_count`."

    Design: Corner/entities/create_booking_adults_count_default_zero
    """
    venue, room, package = setup_config()
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=5)
    assert booking["adults_count"] == 0
    assert booking["headcount_committed"] == 5


# ─── Corner: entities / booking_system_fields_ignored_on_input ─────────────────

def test_booking_system_fields_are_server_controlled(api, coordinator_headers):
    """PRD 3.2: "The new booking lands in `QUOTE_DRAFT`."
    PRD 3.2: "The **quote estimate** is computed immediately and stored as
    `quote_total_cents`."

    Design: Corner/entities/booking_system_fields_ignored_on_input
    """
    venue, room, package = setup_config(base_price_cents=30000, included_children=8)
    # Inject server-controlled fields in the body; they must be ignored.
    res = api.create_booking(
        {"room_id": room["id"], "package_id": package["id"],
         "event_start_utc": "2026-07-01T10:00:00Z", "children_count": 8,
         "status": "CONFIRMED", "quote_total_cents": 999999}, coordinator_headers)
    booking = validate_success(res, 201)
    assert booking["status"] == "QUOTE_DRAFT"
    assert booking["quote_total_cents"] == 30000


# ─── Corner: entities / addon_invalid_enum_kind_rejected ───────────────────────

def test_addon_invalid_kind_rejected(api, coordinator_headers):
    """PRD 3.3: "Each **AddOn** carries a `kind` of `CAKE`, `CHARACTER`, or
    `EXTRA_TIME`".
    PRD 2.8: "(5) field-level request shape and bounds (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/addon_invalid_enum_kind_rejected
    """
    venue, room, package = setup_config()
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    res = api.create_add_on(booking["id"],
                            {"kind": "BALLOON", "unit_price_cents": 1000, "quantity": 1},
                            coordinator_headers)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# ─── Corner: entities / guestparty_immutable_entity_no_version ─────────────────

def test_guest_party_roster_event_recorded(api, coordinator_headers):
    """PRD 3.4: "These roster events are the historical spine the settlement
    calculation later replays, and because they have no `version` they are never
    mutated after creation."

    Design: Corner/entities/guestparty_immutable_entity_no_version
    """
    venue, room, package = setup_config(included_children=8, max_capacity=20)
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    bid = booking["id"]
    gp = record_roster(bid, children_delta=2, reason="rsvp")
    assert gp["children_delta"] == 2
    assert "version" not in gp

    data, _ = validate_paginated(api.list_guest_parties(bid, coordinator_headers))
    assert len(data) == 1
    booking = validate_success(api.get_booking(bid, coordinator_headers), 200)
    assert booking["children_count"] == 10


# ─── Corner: entities / booking_cross_aggregate_venue_resolution ───────────────

def test_booking_venue_resolved_from_room_and_package(api, coordinator_headers):
    """PRD 3.2: "the room and the package must belong to the same venue ... The
    booking's `venue_id` is then resolved from that agreement."

    Design: Corner/entities/booking_cross_aggregate_venue_resolution
    """
    venue, room, package = setup_config()
    booking = create_quote_draft_booking(room["id"], package["id"], children_count=8)
    assert booking["venue_id"] == venue["id"]


# ─── Corner: calculations / quote_overage_is_immediate (consistency) ───────────
# (Covered under consistency_model in test_09.)
