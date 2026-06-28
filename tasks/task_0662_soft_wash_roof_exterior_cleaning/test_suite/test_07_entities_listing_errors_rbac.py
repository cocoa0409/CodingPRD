"""Entity creation defaults, validation, system-minted fields, append-only immutability,
parent-FK existence, listing/pagination, not-found errors, RBAC denials, and the quote-create
OCC happy/stale paths. Translates the entities / endpoints / errors / rbac /
cross_cutting_complexity_layers corner instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, ApiErrorId,
    create_customer_payload, create_route_payload, create_property_payload,
    create_quote_payload, create_line_item_payload,
    create_customer, create_route, create_property, create_draft_quote, add_line_item,
    send_quote,
    TEST_USERS, make_customer_headers, build_user_headers,
)

DISP = TEST_USERS["dispatcher_headers"]
BILL = TEST_USERS["billing_admin_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Corner / entities
# ─────────────────────────────────────────────────────────────────────────

def test_create_customer_defaults(api):
    """PRD §3.1: "A `Customer` is created with a `full_name` and an `email` ... and an optional
    `credit_limit_cents` that defaults to 0 ... On creation the customer's `status` is `ACTIVE`
    and the derived `outstanding_balance_cents` is 0."

    Design: Corner/entities/create_customer_returns_201_with_defaults
    """
    cust = validate_success(
        api.create_customer(create_customer_payload(full_name="New Cust", email="newcust@x.com"), DISP), 201)
    assert cust["status"] == "ACTIVE", cust["status"]
    assert cust["outstanding_balance_cents"] == 0, cust["outstanding_balance_cents"]
    assert cust["credit_limit_cents"] == 0, cust["credit_limit_cents"]


def test_get_customer_nonexistent_returns_not_found(api):
    """PRD §2.7: "the first identifier that does not resolve produces the corresponding
    not-found error: `ERR_CUSTOMER_NOT_FOUND` ... Each carries HTTP 404."

    Design: Corner/entities/get_customer_nonexistent_returns_not_found
    """
    resp = api.get_customer("00000000-0000-4000-8000-000000000000", DISP)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_create_property_missing_stories_rejected(api):
    """PRD §2.8: "Any violation — a bad enum value, an out-of-range integer, a missing required
    field, or an end timestamp at or before the start timestamp — is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/create_property_missing_required_stories_returns_invalid_request
    """
    cust = create_customer()
    route = create_route()
    # Omit the required `stories` field.
    payload = {"customer_id": cust["id"], "route_id": route["id"], "address": "No Stories"}
    resp = api.create_property(payload, DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_line_item_invalid_surface_enum_rejected(api):
    """PRD §2.8: "Every enumerated field must carry one of its declared values".
    PRD §3.2: "a `surface_type` (one of `ROOF`, `SIDING`, or `CONCRETE`)".

    Design: Corner/entities/create_lineitem_invalid_enum_surface_returns_invalid_request
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1)
    quote = create_draft_quote(prop["id"], prop["version"])
    payload = {"surface_type": "WALLS", "service_type": "HOUSE_WASH", "measured_sqft": 100}
    resp = api.add_line_item(quote["id"], payload, DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_customer_id_is_server_minted_uuid(api):
    """PRD §2.4: "`id` — a unique, server-minted identifier formatted as a UUID, with no type
    prefix. It conveys identity only."
    PRD §2.4: "`version` — an integer that begins at its initial value on creation".

    Design: Corner/entities/customer_id_system_minted_input_id_ignored
    """
    cust = validate_success(
        api.create_customer(create_customer_payload(full_name="Sys", email="sysfield@x.com"), DISP), 201)
    assert is_valid_uuid(cust["id"]), cust["id"]
    assert "_" not in cust["id"], "id must have no type prefix"
    assert is_iso8601_timestamp(cust["created_at"]), cust["created_at"]
    assert cust["version"] == 1, cust["version"]


def test_quote_line_item_is_append_only_no_version(api):
    """PRD §2.4: "Two record types are append-only evidence rows and therefore carry **only**
    `id` and `created_at`: a `QuoteLineItem` (a priced line on a quote) and a `PhotoSet` (a
    before/after photo record on a visit). For these two record types, both `updated_at` and
    `version` are absent; they are never modified after creation."

    Design: Corner/entities/quote_line_item_immutable_no_version_field
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=500)
    quote = create_draft_quote(prop["id"], prop["version"])
    li = validate_success(
        api.add_line_item(quote["id"], create_line_item_payload("SIDING", "HOUSE_WASH", 500), DISP), 201)
    assert "version" not in li, "QuoteLineItem must carry no version field"
    assert "updated_at" not in li, "QuoteLineItem must carry no updated_at field"
    data, meta = validate_paginated(api.list_line_items(quote["id"], DISP))
    assert len(data) == 1 and data[0]["id"] == li["id"], data


def test_create_property_unknown_customer_rejected(api):
    """PRD §2.7: "Identifiers are validated left to right, parents before children, and the
    first identifier that does not resolve produces the corresponding not-found error:
    `ERR_CUSTOMER_NOT_FOUND` ... Each carries HTTP 404."

    Design: Corner/entities/property_requires_existing_customer_parent
    """
    route = create_route()
    payload = {"customer_id": "11111111-1111-4111-8111-111111111111",
               "route_id": route["id"], "address": "Ghost", "stories": 1}
    resp = api.create_property(payload, DISP)
    validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND.value)


def test_list_customers_pagination_envelope(api):
    """PRD §2.3: "Each list response includes the following fields in the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."
    PRD §2.3: "The `limit` parameter specifies the maximum number of items to return; if
    omitted, it defaults to 10".

    Design: Corner/entities/list_customers_pagination_envelope
    """
    create_customer(email="pgl1@x.com")
    create_customer(email="pgl2@x.com")
    data, meta = validate_paginated(api.list_customers(DISP))
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is False, meta
    assert meta["limit"] == 10, meta


# ─────────────────────────────────────────────────────────────────────────
# Corner / endpoints
# ─────────────────────────────────────────────────────────────────────────

def test_filter_visits_by_property_id(api):
    """PRD §4 (Visits): "List Visits; filter by property, quote, plan, route, reclean source,
    or status".
    PRD §2.3: "Each list response includes the following fields in the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/filtered_list_visits_by_property_id
    """
    cust = create_customer(credit_limit_cents=100000000)
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=700)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 700)
    send_quote(quote["id"])
    from test_helpers import accept_quote, create_visit
    accept_quote(quote["id"], cust["id"])
    visit = create_visit(prop["id"], quote["id"], scheduled_date="2026-05-01")
    data, meta = validate_paginated(api.list_visits(DISP, params={"property_id": prop["id"]}))
    assert meta["total_count"] == 1, meta
    assert len(data) == 1 and data[0]["id"] == visit["id"], data


def test_list_visit_photos_subresource(api):
    """PRD §4 (Visits): "List PhotoSets for a visit; filter by phase".
    PRD §3.7: "A `FieldTech` uploads a `PhotoSet` for a visit, supplying a `phase` (either
    `BEFORE` or `AFTER`) and a `photo_url`."

    Design: Corner/endpoints/list_visit_photos_subresource_after_uploads
    """
    from test_helpers import setup_crewed_scheduled_visit, upload_photo
    ctx = setup_crewed_scheduled_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        route_overrides={"travel_buffer_minutes": 0},
    )
    photo = upload_photo(ctx["visit"]["id"], "BEFORE", ctx["technician"]["id"])
    data, meta = validate_paginated(api.list_photos(ctx["visit"]["id"], DISP))
    assert meta["total_count"] == 1, meta
    assert len(data) == 1 and data[0]["id"] == photo["id"], data


# ─────────────────────────────────────────────────────────────────────────
# Corner / errors
# ─────────────────────────────────────────────────────────────────────────

def test_cancel_nonexistent_visit_not_found(api):
    """PRD §2.7: "`ERR_VISIT_NOT_FOUND` ... Each carries HTTP 404."

    Design: Corner/errors/visit_not_found_on_cancel
    """
    resp = api.cancel_visit("22222222-2222-4222-8222-222222222222", DISP)
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_FOUND.value)


def test_create_weather_window_unknown_route_not_found(api):
    """PRD §2.7: "`ERR_ROUTE_NOT_FOUND` ... Each carries HTTP 404."

    Design: Corner/errors/route_not_found_on_weather_window_create
    """
    from test_helpers import create_weather_window_payload
    resp = api.create_weather_window(
        create_weather_window_payload("33333333-3333-4333-8333-333333333333",
                                      "2026-05-01T10:00:00Z", "2026-05-01T12:00:00Z", 5), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_FOUND.value)


# ─────────────────────────────────────────────────────────────────────────
# Corner / rbac
# ─────────────────────────────────────────────────────────────────────────

def test_customer_cannot_create_quote(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/customer_cannot_create_quote_unauthorized
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1)
    resp = api.create_quote(
        create_quote_payload(prop["id"], prop["version"]), make_customer_headers(cust["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_dispatcher_cannot_accept_quote(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/dispatcher_cannot_accept_quote_unauthorized
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=500)
    quote = create_draft_quote(prop["id"], prop["version"])
    add_line_item(quote["id"], "SIDING", "HOUSE_WASH", 500)
    send_quote(quote["id"])
    # Accept is Customer-exclusive; Dispatcher is denied.
    validate_error(api.accept_quote(quote["id"], DISP), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected
    with `ERR_MISSING_AUTH_HEADER`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    resp = api.create_customer(create_customer_payload(full_name="Anon", email="anon@x.com"),
                               headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)


def test_customer_cannot_dispute_other_owners_invoice(api):
    """PRD §2.1: "Whenever an entity-backed user (a `Customer` or a `FieldTech`) attempts to
    act on a resource it does not own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`.
    For a `Customer`, ownership extends to the properties, quotes, and invoices that trace back
    to that customer".

    Design: Corner/rbac/customer_dispute_other_owner_invoice_not_resource_owner
    """
    from test_helpers import setup_completed_visit
    ctx = setup_completed_visit(
        property_overrides={"stories": 2, "roof_sqft": 2000},
        line_items=[("ROOF", "ROOF_SOFT_WASH", 2000)],
        re_measured_roof_sqft=2000,
        route_overrides={"travel_buffer_minutes": 0},
    )
    other = create_customer(email="other-owner@x.com")
    inv = ctx["invoice"]
    resp = api.dispute_invoice(inv["id"], make_customer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─────────────────────────────────────────────────────────────────────────
# Corner / cross_cutting_complexity_layers (OCC on quote create)
# ─────────────────────────────────────────────────────────────────────────

def test_quote_create_with_correct_property_version_succeeds(api):
    """PRD §2.6: "Creating a new quote requires the field `expected_property_version`,
    carrying the client's last observed `version` of the target `Property`. Creating a new
    quote legitimately supersedes whatever prior non-terminal quote already exists on that
    property, and doing so advances the property's `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_quote_create_correct_property_version_succeeds
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=600)
    quote = validate_success(
        api.create_quote(create_quote_payload(prop["id"], prop["version"]), DISP), 201)
    assert quote["status"] == "DRAFT", quote["status"]
    after = get_success_data(api.get_property(prop["id"], DISP))
    assert after["version"] == prop["version"] + 1, after["version"]


def test_quote_create_with_stale_property_version_rejected(api):
    """PRD §2.6: "if the property's `version` has already advanced since the client read it,
    the supplied `expected_property_version` will no longer equal the property's current
    `version`, and the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_quote_create_stale_property_version_rejected
    """
    cust = create_customer()
    route = create_route()
    prop = create_property(cust["id"], route["id"], stories=1, siding_sqft=600)
    stale_version = prop["version"]
    # First create advances the property version away from stale_version.
    validate_success(api.create_quote(create_quote_payload(prop["id"], stale_version), DISP), 201)
    # Second create still carrying the original (now stale) version is rejected.
    resp = api.create_quote(create_quote_payload(prop["id"], stale_version), DISP)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
