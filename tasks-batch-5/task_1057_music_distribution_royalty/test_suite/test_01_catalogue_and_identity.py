"""Platform catalogue: plans, stores, artist accounts, envelope and access control."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, assert_subscription_plan, assert_store, assert_artist,
    create_subscription_plan_payload, create_store_payload, create_artist_payload,
    set_clock, create_plan, create_store, create_artist, create_active_subscription,
    create_release, add_track, create_collaborator, CLOCK_BASE, upc, isrc,
    make_admin_headers, make_artist_headers, make_ops_headers,
)


def test_create_subscription_plan_returns_201_with_declared_fields(api, admin_headers):
    """PRD §4: "Operations that bring a brand-new resource into existence answer with HTTP 201;
    every other successful operation — reads, metadata amendments, state transitions and
    computed reports — answers with HTTP 200."
    PRD §3.1: "A plan's `status` is either `ACTIVE` or `RETIRED` and defaults to `ACTIVE` when omitted."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation of that
    row, and `version`, an integer that starts at 1 when the row is created and increases by
    exactly 1 on each mutation."

    Design: Corner/entities/create_subscription_plan_returns_201_with_all_declared_fields
    """
    set_clock(CLOCK_BASE)
    payload = create_subscription_plan_payload(
        code="STARTER", name="Starter", annual_fee_cents=1200,
        included_release_slots=2, commission_bps=1500, allows_content_id=False,
    )
    plan = validate_success(api.create_subscription_plan(payload, admin_headers), 201)

    assert_subscription_plan(plan)
    assert plan["code"] == "STARTER"
    assert plan["annual_fee_cents"] == 1200
    assert plan["included_release_slots"] == 2
    assert plan["commission_bps"] == 1500
    assert plan["status"] == "ACTIVE", "status defaults to ACTIVE when omitted"
    assert plan["version"] == 1, "version starts at 1 when the row is created"


def test_store_optional_fields_fall_back_to_declared_defaults(api, admin_headers):
    """PRD §3.1: "Three booleans describe what the store demands of the metadata it receives:
    `supports_pre_save` records whether the store participates in pre-save campaigns (default
    false), `requires_isrc` records whether it refuses a delivery when any track of the release
    still has no recording code (default true), and `requires_explicit_flag` records whether it
    refuses a delivery when any track has left its explicit-content declaration undeclared
    (default true)."
    PRD §3.1: "The store's own cut is `surcharge_bps`, a commission surcharge in basis points
    between 0 and 2000 inclusive that defaults to 0 and later enters the weighted surcharge of a
    statement's commission."
    PRD §3.1: "Finally, `max_concurrent_deliveries` — at least 1, defaulting to 2 — caps how many
    delivery windows may be in flight against this store at any single instant."
    PRD §3.1: "A store's `status` is either `ACTIVE` or `PAUSED` and defaults to `ACTIVE`; a
    delivery may only be dispatched to a store that is `ACTIVE`."

    Design: Corner/entities/store_optional_fields_fall_back_to_declared_defaults
    """
    set_clock(CLOCK_BASE)
    store = validate_success(
        api.create_store({"code": "DEEZER", "name": "Deezer", "delivery_lead_days": 4},
                         admin_headers),
        201,
    )

    assert_store(store)
    assert store["supports_pre_save"] is False
    assert store["requires_isrc"] is True
    assert store["requires_explicit_flag"] is True
    assert store["surcharge_bps"] == 0
    assert store["max_concurrent_deliveries"] == 2
    assert store["status"] == "ACTIVE"


def test_create_store_missing_required_field_rejected(api, admin_headers):
    """PRD §2.8: "Request shape — the body parses, all required input fields are present, enum
    members are legal, numbers fall in their declared ranges, and identifier formats match (a
    `upc` is exactly 12 digits, an `isrc` is exactly 12 alphanumeric characters, a `country_code`
    is exactly 2 uppercase letters): `ERR_VALIDATION`. This applies to every write endpoint."

    Design: Corner/entities/create_store_missing_required_field_rejected_with_validation_error
    """
    set_clock(CLOCK_BASE)
    resp = api.create_store({"code": "TIDAL", "name": "Tidal"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    listed, meta = validate_paginated(api.list_stores(admin_headers))
    assert meta["total_count"] == 0, "the rejected store must not have been persisted"


def test_create_artist_with_malformed_country_code_rejected(api, admin_headers):
    """PRD §2.8: "Request shape — the body parses, all required input fields are present, enum
    members are legal, numbers fall in their declared ranges, and identifier formats match (a
    `upc` is exactly 12 digits, an `isrc` is exactly 12 alphanumeric characters, a `country_code`
    is exactly 2 uppercase letters): `ERR_VALIDATION`. This applies to every write endpoint."

    Design: Corner/entities/create_artist_with_malformed_country_code_rejected
    """
    set_clock(CLOCK_BASE)
    payload = create_artist_payload(country_code="usa", email="bad@example.com")
    resp = api.create_artist(payload, admin_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_artist_by_id_returns_stored_representation(api, admin_headers):
    """PRD §3.1: "A freshly registered artist begins with `status` `ACTIVE` — the enumeration is
    `ACTIVE`, `SUSPENDED` or `CLOSED` — and with both of its running totals initialised to zero:
    `lifetime_gross_cents`, which accumulates the gross of every statement of this artist that has
    reached `CLOSED` and which later determines the artist's loyalty discount, and
    `live_track_count`, which counts the tracks in `ACTIVE` status across all of this artist's
    releases."

    Design: Corner/entities/get_artist_by_id_returns_stored_representation
    """
    created = create_artist(display_name="Echo", legal_name="Echo LLC",
                            country_code="US", email="echo@example.com")

    artist = validate_success(api.get_artist(created["id"], admin_headers))

    assert_artist(artist)
    assert artist["display_name"] == "Echo"
    assert artist["status"] == "ACTIVE"
    assert artist["lifetime_gross_cents"] == 0
    assert artist["live_track_count"] == 0


def test_list_stores_paginates_with_limit_offset_and_has_more(api, admin_headers):
    """PRD §2.3: "`limit` controls page size: it defaults to 10 when omitted, may be no smaller
    than 1, and may be no larger than 100."
    PRD §2.3: "The `meta` block of a list response carries `limit` and `offset` as they were
    applied, `total_count` giving the number of records matching the filters before the page
    window is applied, and `has_more`, which is true exactly when records matching the filters
    remain beyond the current page."

    Design: Corner/entities/list_stores_paginates_with_limit_offset_total_count_has_more
    """
    set_clock(CLOCK_BASE)
    create_store(code="SPOTIFY", name="Spotify", delivery_lead_days=5)
    create_store(code="APPLE", name="Apple Music", delivery_lead_days=5)
    create_store(code="YOUTUBE", name="YouTube", delivery_lead_days=3)

    resp = api.list_stores(admin_headers, params={"limit": 2, "offset": 1})
    data, meta = validate_paginated(resp)

    assert meta["total_count"] == 3
    assert len(data) == 2
    assert meta["limit"] == 2 and meta["offset"] == 1
    assert meta["has_more"] is False, "offset 1 plus a page of 2 exhausts the three stores"


def test_get_release_with_unknown_uuid_returns_not_found(api, ops_headers):
    """PRD §2.8: "Path existence — every resource named in the URL exists, checked left to right:
    `ERR_RESOURCE_NOT_FOUND`. This applies to every endpoint with path parameters."

    Design: Corner/entities/get_release_with_unknown_uuid_returns_not_found
    """
    set_clock(CLOCK_BASE)
    resp = api.get_release(NON_EXISTENT_UUID, ops_headers)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_create_track_under_nonexistent_release_returns_not_found(api):
    """PRD §2.11: "In every such case the path segments are resolved from left to right: the
    outermost identifier is looked up first, and if it does not resolve the request fails
    immediately with `ERR_RESOURCE_NOT_FOUND` without any inner identifier being consulted."

    Design: Corner/entities/create_track_under_nonexistent_release_returns_not_found
    """
    set_clock(CLOCK_BASE)
    artist = create_artist(display_name="Ghost", legal_name="Ghost LLC",
                           country_code="US", email="ghost@example.com")

    resp = api.add_track(
        NON_EXISTENT_UUID,
        {"title": "Nowhere", "duration_seconds": 100, "track_number": 1},
        make_artist_headers(artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_request_without_role_header_is_unauthenticated(api):
    """PRD §2.1: "Both headers must be present, and `X-User-Role` must name one of the six
    recognised roles, otherwise the request is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/request_without_role_header_is_unauthenticated
    """
    set_clock(CLOCK_BASE)
    plan = create_plan(code="PRO", name="Pro")
    artist = create_artist(display_name="Scutum", legal_name="Scutum LLC",
                           country_code="US", email="scutum@example.com")
    create_active_subscription(artist["id"], plan["id"])

    resp = api._request(
        "POST",
        "/api/releases",
        {"artist_id": artist["id"], "title": "Shield",
         "release_date": "2026-09-01T00:00:00Z",
         "primary_genre": "Pop", "label_name": "Scutum Rec"},
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    listed, meta = validate_paginated(
        api.list_releases(make_admin_headers(), params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 0, "an unauthenticated write must persist nothing"


def test_filtered_list_endpoints_scope_children_by_foreign_key(api, admin_headers):
    """PRD §2.3: "Filters supplied alongside pagination narrow the matched set before counting."
    PRD §2.3: "Most collections accept a `status` filter; beyond that, subscriptions may be
    narrowed by `artist_id` or `plan_id`, releases by `artist_id` and by either state dimension
    (`status` or `delivery_status`), tracks by `release_id`, collaborators by `artist_id`, split
    sheets by `track_id`, split shares by `split_sheet_id` or `collaborator_id`, deliveries by
    `release_id` or `store_id`, royalty statements by `artist_id`, royalty lines by
    `royalty_statement_id`, `track_id`, `store_id` or `source`, payouts by `collaborator_id` or
    `royalty_statement_id`, and tax forms by `collaborator_id` or `tax_year`."

    Design: Corner/endpoints/filtered_list_endpoints_scope_children_by_foreign_key
    """
    set_clock(CLOCK_BASE)
    plan = create_plan(code="PRO", name="Pro")
    artist_1 = create_artist(display_name="A One", legal_name="A One LLC",
                             country_code="US", email="aone@example.com")
    artist_2 = create_artist(display_name="A Two", legal_name="A Two LLC",
                             country_code="US", email="atwo@example.com")
    create_active_subscription(artist_1["id"], plan["id"])
    sub_2 = create_active_subscription(artist_2["id"], plan["id"])

    rel_1 = create_release(artist_1["id"], title="R1", label_name="L1", upc=upc(1))
    rel_2 = create_release(artist_2["id"], title="R2", label_name="L2", upc=upc(2))
    add_track(rel_1["id"], artist_1["id"], title="T1", track_number=1, isrc=isrc(1))
    add_track(rel_1["id"], artist_1["id"], title="T2", track_number=2, isrc=isrc(2))
    t3 = add_track(rel_2["id"], artist_2["id"], title="T3", track_number=1, isrc=isrc(3))

    releases, meta = validate_paginated(
        api.list_releases(admin_headers, params={"artist_id": artist_1["id"]})
    )
    assert meta["total_count"] == 1 and releases[0]["id"] == rel_1["id"]

    tracks_1, meta_1 = validate_paginated(
        api.list_tracks(admin_headers, params={"release_id": rel_1["id"]})
    )
    assert meta_1["total_count"] == 2

    tracks_2, meta_2 = validate_paginated(
        api.list_tracks(admin_headers, params={"release_id": rel_2["id"]})
    )
    assert meta_2["total_count"] == 1 and tracks_2[0]["id"] == t3["id"]

    subs, meta_s = validate_paginated(
        api.list_subscriptions(admin_headers, params={"artist_id": artist_2["id"]})
    )
    assert meta_s["total_count"] == 1 and subs[0]["id"] == sub_2["id"]
