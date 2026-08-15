"""Artists, shows, pagination, computed fields, and version bookkeeping."""
from test_helpers import (
    NON_EXISTENT_UUID,
    VM,
    ApiErrorId,
    assert_artist,
    assert_show,
    create_agent,
    create_artist,
    create_artist_payload,
    create_show,
    get_show,
    is_iso8601_timestamp,
    is_valid_uuid,
    place_hold,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_artist_creation_returns_201_with_system_fields(api):
    """PRD §3.1: "A `VenueManager` onboards each artist with the artist or band
    `legal_name`, the `agency` that represents them, a `guarantee_floor_cents`
    expressing the minimum guarantee the artist will accept in cents, and a
    `deposit_pct` — the fraction of the guarantee required up front as a
    deposit, carried as a value between 0.0 and 0.5 inclusive."
    PRD §2.4: "Every persisted resource carries an `id` minted by the server
    as a UUID, with no type prefix of any kind. Every resource also carries
    `created_at`, an ISO 8601 UTC timestamp with three fractional digits.
    Most resources additionally carry `updated_at`, refreshed on every
    mutation, and `version`, an integer that increments by one on every
    mutation of that resource."

    Design: Corner/entities/artist_creation_returns_201_with_system_fields
    """
    set_clock()
    resp = api.create_artist(
        create_artist_payload(
            legal_name="Alpha", agency="A",
            guarantee_floor_cents=10000, deposit_pct=0.25,
        ),
        VM,
    )
    data = validate_success(resp, 201)
    assert_artist(data)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert data["version"] == 1
    assert data["status"] == "ACTIVE"
    assert data["total_settled_shows"] == 0


def test_artist_missing_required_field_returns_400(api):
    """PRD §2.8: "a request whose required fields are missing, malformed, or
    ill-typed is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/artist_missing_required_field_returns_400
    """
    set_clock()
    resp = api.create_artist(
        {"legal_name": "Beta", "agency": "B", "deposit_pct": 0.25},
        VM,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_artist_get_nonexistent_returns_404(api):
    """PRD §2.8: "Existence of every path-template resource — show, hold,
    offer, deal, tier, sale, advance item, support act, receipt, ancillary
    row, settlement, wire — evaluated left to right along the path; the
    first miss yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/artist_get_nonexistent_returns_404
    """
    set_clock()
    resp = api.get_artist(NON_EXISTENT_UUID, VM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_show_list_pagination_defaults(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, accepts a minimum of
    1, and is capped at a maximum of 100; the `offset` parameter defaults to
    0. Every list response carries the four pagination fields `limit`,
    `offset`, `total_count`, and `has_more` inside `meta`."

    Design: Corner/entities/show_list_pagination_defaults
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    create_show(artist["id"], agent=agent)

    data, meta = validate_paginated(api.list_shows(VM))
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert isinstance(meta["has_more"], bool)
    assert len(data) == 1


def test_show_computed_tickets_sold_defaults_zero(api):
    """PRD §3.2: "A new show is born in `HOLD_PENDING` with `hold_priority`
    set to `NONE`, `cancellation_reason` set to `NONE`,
    `weather_or_emergency_flag` false, `deal_id` unset, and `tickets_sold`
    and `gross_ticket_revenue_cents` at zero; the platform also creates the
    show's advance checklist with all six items false (§3.5)."

    Design: Corner/entities/show_computed_tickets_sold_defaults_zero
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    resp = api.create_show(
        {
            "artist_id": artist["id"],
            "room": "MAIN_ROOM",
            "show_date": "2026-12-25",
            "doors_at_utc": "2026-12-25T19:00:00Z",
            "curfew_at_utc": "2026-12-25T23:00:00Z",
            "total_capacity": 100,
            "on_sale_at_utc": "2026-09-01T10:00:00Z",
        },
        VM,
    )
    data = validate_success(resp, 201)
    assert_show(data)
    assert data["tickets_sold"] == 0
    assert data["gross_ticket_revenue_cents"] == 0
    assert data["status"] == "HOLD_PENDING"
    assert data["hold_priority"] == "NONE"


def test_get_show_by_id_returns_fresh_data(api):
    """PRD §3.2: "A new show is born in `HOLD_PENDING` with `hold_priority`
    set to `NONE`, `cancellation_reason` set to `NONE`,
    `weather_or_emergency_flag` false, `deal_id` unset, and `tickets_sold`
    and `gross_ticket_revenue_cents` at zero; the platform also creates the
    show's advance checklist with all six items false (§3.5)."

    Design: Corner/endpoints/get_show_by_id_returns_fresh_data
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(artist["id"], agent=agent)

    fetched = validate_success(api.get_show(show["id"], VM), 200)
    assert fetched["id"] == show["id"]
    assert fetched["status"] == "HOLD_PENDING"
    assert fetched["hold_priority"] == "NONE"


def test_show_version_increments_on_mutation(api):
    """PRD §2.4: "Most resources additionally carry `updated_at`, refreshed
    on every mutation, and `version`, an integer that increments by one on
    every mutation of that resource."
    PRD §3.2: "A successful confirmation does four things as one cascade: the
    hold becomes `CONFIRMED`; the show moves from `HOLD_PENDING` to
    `CONFIRMED` and its `hold_priority` is copied from the confirmed hold's
    `priority`; every other date hold on the same room and date that is
    `ACTIVE` or `CHALLENGED` is released to `RELEASED`; and the show's
    `version` increments by one."

    Design: Corner/consistency_model/show_version_increments_on_mutation
    """
    set_clock()
    artist = create_artist()
    agent = create_agent()
    show = create_show(artist["id"], agent=agent)
    assert show["version"] == 1
    initial_updated_at = show["updated_at"]

    # Place a hold (does not bump show version by itself, then confirm does).
    hold = place_hold(show["id"], agent, priority="P1")
    v_before_confirm = get_show(show["id"])["version"]

    confirm_resp = api.confirm_date_hold(
        show["id"], hold["id"],
        {"expected_show_version": v_before_confirm},
        {"X-User-ID": agent["id"], "X-User-Role": "BookingAgent",
         "Content-Type": "application/json"},
    )
    validate_success(confirm_resp, 200)
    after = get_show(show["id"])
    assert after["version"] == v_before_confirm + 1
    assert after["updated_at"] != initial_updated_at
