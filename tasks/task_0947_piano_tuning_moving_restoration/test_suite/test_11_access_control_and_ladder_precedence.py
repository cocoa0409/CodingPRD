"""Authentication, role authorisation, actor scope, existence rungs and precedence."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    draft_quote,
    headers_without_role,
    instrument_version,
    make_client_headers,
    make_headers,
    new_client,
    new_location,
    new_instrument,
    quote_payload,
    read_instrument,
    setup_client_with_instrument,
    setup_voice_order_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["shop_manager_headers"]


def test_request_without_a_role_header_is_unauthenticated(api):
    """PRD 2.8: "**Authentication headers.** `X-User-Role` must be present and
    non-empty; `X-User-ID` must be present for the entity-backed roles `Technician` and
    `Client`, and for **any** role on the four segregation-of-duties operations
    `POST /milestones/{id}/release`, `POST /warranty-claims/{id}/adjudicate`,
    `POST /consignment-agreements` and `POST /consignment-agreements/{id}/record-sale`.
    Otherwise `ERR_MISSING_AUTH_HEADER` (401). Applies to every operation."

    Design: Corner/rbac/create_client_with_missing_auth_header_returns_unauthenticated
    """
    response = api.create_client(
        {
            "display_name": "No Auth",
            "email": "noauth@example.com",
            "phone": "555-0370",
            "home_zone_code": "ZONE_A",
        },
        headers_without_role(),
    )
    validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADER.value)

    rows, _ = validate_paginated(api.list_clients(MANAGER))
    assert rows == [], "the unauthenticated request created nothing"


def test_request_with_an_undeclared_role_is_rejected_before_authorisation(api):
    """PRD 2.8: "**Known role.** `X-User-Role` must name a role declared in the matrix.
    Otherwise `ERR_INVALID_ROLE` (401). Applies to every operation."
    PRD 2.1: "A role name the matrix does not declare is rejected with
    `ERR_INVALID_ROLE` (HTTP 401)."

    Design: Corner/rbac/create_client_with_invalid_role_returns_unauthenticated
    """
    response = api.create_client(
        {
            "display_name": "Bad Role",
            "email": "badrole@example.com",
            "phone": "555-0371",
            "home_zone_code": "ZONE_A",
        },
        make_headers("someone-1", "PianoOwner"),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_ROLE.value)


def test_client_role_cannot_release_a_milestone(api):
    """PRD 2.8: "**Role authorisation.** The role must be listed among the operation's
    authorised roles. Otherwise `ERR_UNAUTHORIZED_ROLE` (403). Applies to every
    operation."
    PRD 3.6: "A `ShopManager` releases a `READY` milestone for client acceptance while
    the order is `IN_PROGRESS`, which stamps `released_by_user_id` with the acting
    `X-User-ID` and `released_at` from the clock and bumps the milestone's `version` by
    1."

    Design: Corner/rbac/client_cannot_release_a_milestone
    """
    ctx = setup_voice_order_in_progress(funding=200000)
    first = min(ctx["milestones"], key=lambda m: m["sequence_index"])

    response = api.release_milestone(
        first["id"], make_client_headers(ctx["client"]["id"])
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)

    refreshed = validate_success(
        api.list_service_order_milestones(ctx["order"]["id"], MANAGER)
    )
    current = next(m for m in refreshed if m["id"] == first["id"])
    assert current["status"] == "READY"
    assert current["released_by_user_id"] is None


def test_client_cannot_read_another_clients_instrument(api):
    """PRD 2.1: "When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting
    `Client` row; ownership checks compare it to the addressed resource's `client_id`,
    and on a consignment agreement to `consignor_client_id` or `buyer_client_id`."
    PRD 2.1: "An entity-backed actor that addresses a row it does not own is rejected
    with `ERR_ACTOR_SCOPE_VIOLATION` (HTTP 403). This check runs on every operation
    whose authorised role list includes `Technician` or `Client`."

    Design: Corner/rbac/client_cannot_read_another_clients_instrument
    """
    nosy = new_client()
    private = new_client()
    address = new_location(private["id"], label="Room")
    instrument = new_instrument(private["id"], address["id"])

    response = api.get_instrument(instrument["id"], make_client_headers(nosy["id"]))
    validate_error(response, ApiErrorId.ERR_ACTOR_SCOPE_VIOLATION.value)

    allowed = validate_success(
        api.get_instrument(instrument["id"], make_client_headers(private["id"]))
    )
    assert allowed["id"] == instrument["id"]


def test_service_order_create_with_unresolvable_quote_is_not_found(api):
    """PRD 2.8: "**Quote existence.** A `quote_id` that does not resolve yields
    `ERR_QUOTE_NOT_FOUND` (404). Applies to the quote paths and to service-order
    creation."

    Design: Corner/errors/service_order_create_with_unknown_quote_returns_quote_not_found
    """
    response = api.create_service_order(
        {"quote_id": "00000000-0000-4000-8000-000000000003"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_QUOTE_NOT_FOUND.value)


def test_milestone_listing_for_an_unresolvable_order_is_not_found(api):
    """PRD 2.8: "**Service-order existence.** A `service_order_id` that does not resolve
    yields `ERR_SERVICE_ORDER_NOT_FOUND` (404)."
    PRD 2.4: "When an operation addresses a child resource beneath a parent — the
    readings of a location, the recalls of an instrument, the milestones or parts
    allocations of a service order — the parent id is resolved first and its
    non-existence is reported before the child id is even examined."

    Design: Corner/errors/milestones_listing_for_unknown_service_order_returns_service_order_not_found
    """
    response = api.list_service_order_milestones(
        "00000000-0000-4000-8000-000000000004", MANAGER
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_ORDER_NOT_FOUND.value)


def test_route_day_transition_on_an_unresolvable_id_is_a_generic_not_found(api):
    """PRD 2.8: "**Everything else.** Any other referenced id that does not resolve —
    `Technician`, `RouteDay`, `Appointment`, `TuningRecall`, `Milestone`, `MoveJob`,
    `Warranty`, `WarrantyClaim`, `ConsignmentAgreement`, `PartsLot`, `PartsAllocation`,
    `LedgerEntry` — yields `ERR_RESOURCE_NOT_FOUND` (404)."

    Design: Corner/errors/route_day_transition_on_unknown_id_returns_resource_not_found
    """
    response = api.create_route_day_status_transition(
        "00000000-0000-4000-8000-000000000005", {"to_status": "LOCKED"}, MANAGER
    )
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)


def test_client_standing_is_reported_ahead_of_the_stale_instrument_version(api):
    """PRD 2.8: "The server evaluates every request against one ordered ladder and
    returns the **first** error it reaches; later rungs are never evaluated once an
    earlier one has failed."
    PRD 2.8: "**Client standing.** The acting or owning client's `status` must be
    `ACTIVE`. Otherwise `ERR_CLIENT_NOT_ACTIVE` (409). Applies to exactly eight
    operations: `POST /quotes`, `POST /quotes/{id}/issue`, `POST /quotes/{id}/approve`,
    `POST /appointments`, `POST /service-orders`, `POST /service-orders/{id}/resume`,
    `POST /warranty-claims` and `POST /tuning-recalls/{id}/notify`."
    PRD 2.8: "**Instrument version.** `expected_instrument_version` must equal the
    instrument's current `version`. Otherwise `ERR_STALE_INSTRUMENT_VERSION` (412).
    Applies to `POST /quotes`, `POST /quotes/{id}/reissue` and
    `POST /consignment-agreements`."

    Design: Difficulty/priority_pair_validation_conflict/client_not_active_beats_stale_instrument_version
    """
    base = setup_client_with_instrument(deviation=3.0)
    client, instrument = base["client"], base["instrument"]
    stale_version = instrument_version(instrument["id"])
    first_quote = draft_quote(instrument["id"], "TUNE")
    version_after_first_quote = instrument_version(instrument["id"])

    validate_success(api.update_client(client["id"], {"status": "SUSPENDED"}, MANAGER))

    response = api.create_quote(
        quote_payload(instrument["id"], "REGULATE", stale_version), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_CLIENT_NOT_ACTIVE.value)

    rows, _ = validate_paginated(
        api.list_quotes(MANAGER, params={"instrument_id": instrument["id"]})
    )
    assert [r["id"] for r in rows] == [first_quote["id"]], "the rejected call minted nothing"
    assert read_instrument(instrument["id"])["version"] == version_after_first_quote


def test_the_stale_version_rung_fires_once_the_client_is_active_again(api):
    """PRD 2.7: "Drafting a quote requires `expected_instrument_version` carrying the
    client's last observed `version` of the instrument being quoted; if the instrument's
    current `version` differs, the request is rejected with
    `ERR_STALE_INSTRUMENT_VERSION` (HTTP 412)."
    PRD 3.1: "A `ShopManager` moves an `ACTIVE` client to `SUSPENDED` by supplying that
    `status` on the update, and moves a `SUSPENDED` client back to `ACTIVE` the same
    way; each edge bumps the client's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/client_not_active_beats_stale_instrument_version
    """
    base = setup_client_with_instrument(deviation=3.0)
    client, instrument = base["client"], base["instrument"]
    stale_version = instrument_version(instrument["id"])
    first_quote = draft_quote(instrument["id"], "TUNE")
    version_after_first_quote = instrument_version(instrument["id"])

    validate_success(api.update_client(client["id"], {"status": "SUSPENDED"}, MANAGER))
    validate_success(api.update_client(client["id"], {"status": "ACTIVE"}, MANAGER))

    response = api.create_quote(
        quote_payload(instrument["id"], "REGULATE", stale_version), MANAGER
    )
    validate_error(response, ApiErrorId.ERR_STALE_INSTRUMENT_VERSION.value)

    rows, _ = validate_paginated(
        api.list_quotes(MANAGER, params={"instrument_id": instrument["id"]})
    )
    assert [r["id"] for r in rows] == [first_quote["id"]]
    assert read_instrument(instrument["id"])["version"] == version_after_first_quote
