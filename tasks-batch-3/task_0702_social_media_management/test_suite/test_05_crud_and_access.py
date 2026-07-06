"""CRUD, defaults, foreign-key, listing, validation-constraint, and RBAC tests.

Covers the corner entities, validations, endpoints, and rbac sections.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    is_valid_uuid, ApiErrorId, NON_EXISTENT_UUID,
    create_client, create_and_activate_package, create_live_channel,
    setup_active_client, create_content_with_target,
)
from test_helpers import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CC = TEST_USERS["content_creator_headers"]


# ===========================================================================
# corner entities section
# ===========================================================================
def test_create_client_returns_201_with_onboarding_defaults(api):
    """PRD §3.1: "The account is born in `ONBOARDING` status with a
    `current_cycle_index` of 0 and every budget figure — `retainer_fee_cents`,
    `boost_budget_limit_cents`, `boost_reserved_cents`, `boost_spent_cents`,
    `boost_available_cents`, and `monthly_post_quota` — sitting at zero."
    PRD §2.4: "`version` — an integer that starts at its initial value and
    increments by one on every mutation".

    Design: Corner/entities/corner_create_client_returns_201_with_onboarding_defaults
    """
    data = validate_success(
        api.create_client({"name": "Fresh", "account_manager_id": "am-9"}, AM),
        expected_status=201)
    assert data["status"] == "ONBOARDING", f"expected ONBOARDING, got {data['status']}"
    assert data["current_cycle_index"] == 0
    assert data["boost_available_cents"] == 0
    assert data["version"] == 1, f"version must start at 1, got {data['version']}"


def test_get_client_not_found_returns_404(api):
    """PRD §2.5: "For any request whose path names a resource, the server validates
    the path identifier and rejects a request that names a non-existent resource."
    PRD §2.5: lists `ERR_CLIENT_NOT_FOUND` ... "each returned with HTTP 404."

    Design: Corner/entities/corner_get_client_not_found_returns_404
    """
    validate_error(api.get_client(NON_EXISTENT_UUID, AM),
                   ApiErrorId.ERR_CLIENT_NOT_FOUND.value)


def test_create_channel_missing_handle_returns_400(api):
    """PRD §3.8: "Finally, generic body validation — required fields present and
    correctly typed ... — is reported as `ERR_INVALID_REQUEST` with HTTP 400 on any
    write endpoint."

    Design: Corner/entities/corner_create_channel_missing_required_handle_returns_400
    """
    client = create_client()
    validate_error(
        api.create_channel({"client_id": client["id"], "platform": "X"}, AM),
        ApiErrorId.ERR_INVALID_REQUEST.value)


def test_channel_default_min_publish_gap_applied(api):
    """PRD §3.2: "The onboarding payload may optionally set
    `min_publish_gap_minutes`, the minimum number of minutes that must separate two
    schedule slots on this channel, which is zero or greater and defaults to 30."

    Design: Corner/entities/corner_channel_default_min_publish_gap_applied
    """
    client = create_client()
    data = validate_success(
        api.create_channel(
            {"client_id": client["id"], "platform": "INSTAGRAM", "handle": "@chdef"}, AM),
        expected_status=201)
    assert data["min_publish_gap_minutes"] == 30, (
        f"default min_publish_gap_minutes must be 30, got {data['min_publish_gap_minutes']}")


def test_content_target_cross_client_returns_409(api):
    """PRD §3.3: "Because a target spans a content item and a channel, the
    channel's `client_id` must equal the content item's `client_id`; a mismatch is
    rejected with `ERR_CROSS_CLIENT_REFERENCE`."

    Design: Corner/entities/corner_create_content_target_cross_client_returns_409
    """
    client_a = create_client(name="A", account_manager_id="am-1")
    client_b = create_client(name="B", account_manager_id="am-2")
    item = get_success_data(api.create_content_item(
        {"client_id": client_a["id"], "author_id": "cc-1", "title": "X", "body": "b"}, CC))
    channel_b = get_success_data(api.create_channel(
        {"client_id": client_b["id"], "platform": "X", "handle": "@b"}, AM))
    validate_error(
        api.create_content_target(
            {"content_item_id": item["id"], "channel_id": channel_b["id"]}, AM),
        ApiErrorId.ERR_CROSS_CLIENT_REFERENCE.value)


def test_system_fields_ignored_on_create_client(api):
    """PRD §2.4: "`id` — a server-minted UUID with no type prefix, used for identity
    only."
    PRD §3.1: "The account is born in `ONBOARDING` status".

    Design: Corner/entities/corner_system_fields_ignored_on_create_client
    """
    data = validate_success(
        api.create_client({"name": "Sys", "account_manager_id": "am-1"}, AM),
        expected_status=201)
    assert is_valid_uuid(data["id"]), f"id must be a server-minted UUID, got {data['id']!r}"
    assert "_" not in data["id"], "id must have no type prefix"
    assert data["status"] == "ONBOARDING"


# ===========================================================================
# corner validations section
# ===========================================================================
def test_duplicate_channel_handle_returns_409(api):
    """PRD §3.2: "The handle must be unique within the combination of `client_id`
    and `platform`; a collision is rejected with `ERR_DUPLICATE_HANDLE`."

    Design: Corner/validations/corner_duplicate_channel_handle_returns_409
    """
    client = create_client()
    get_success_data(api.create_channel(
        {"client_id": client["id"], "platform": "INSTAGRAM", "handle": "@dup"}, AM))
    validate_error(
        api.create_channel(
            {"client_id": client["id"], "platform": "INSTAGRAM", "handle": "@dup"}, AM),
        ApiErrorId.ERR_DUPLICATE_HANDLE.value)


def test_channel_limit_exceeded_on_go_live(api):
    """PRD §3.2: "Taking a channel live advances it from `CONNECTED` to `LIVE`, but
    only when the number of the client's channels already in the live state is
    strictly fewer than the `included_channels` allowance on the client's active
    retainer package; reaching that allowance and attempting one more go-live is
    rejected with `ERR_CHANNEL_LIMIT_EXCEEDED`."

    Design: Corner/validations/corner_channel_limit_exceeded_on_go_live
    """
    client = create_client()
    create_and_activate_package(
        client["id"], tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1)
    create_live_channel(client["id"], platform="INSTAGRAM", handle="@lim1")
    ch2 = get_success_data(api.create_channel(
        {"client_id": client["id"], "platform": "FACEBOOK", "handle": "@lim2"}, AM))
    get_success_data(api.connect_channel(ch2["id"], AM))
    validate_error(api.go_live_channel(ch2["id"], AM),
                   ApiErrorId.ERR_CHANNEL_LIMIT_EXCEEDED.value)


def test_activate_client_without_package_or_live_channel_rejected(api):
    """PRD §3.1: "Activating the client itself, performed by an `AccountManager`,
    advances it from `ONBOARDING` to `ACTIVE`, but only when the client has exactly
    one retainer package in `ACTIVE` status and at least one of its channels has
    reached the live state; if neither precondition holds the transition is an
    invalid one."

    Design: Corner/validations/corner_activate_client_without_package_rejected
    """
    client = create_client(name="Bare")
    validate_error(api.activate_client(client["id"], AM),
                   ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# corner endpoints section (listing)
# ===========================================================================
def test_list_clients_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned ... Every
    list response includes `limit`, `offset`, `total_count`, and `has_more` in the
    `meta` object of the envelope."

    Design: Corner/endpoints/corner_list_clients_pagination_envelope
    """
    create_client(name="C1")
    create_client(name="C2")
    data, meta = validate_paginated(api.list_clients(AM, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more must be true, got {meta['has_more']}"
    assert len(data) == 1, f"data length must be 1, got {len(data)}"


def test_filter_channels_by_client(api):
    """PRD §2.3: "most list endpoints accept additional filter query parameters
    drawn from the resource's own fields ... other entity-specific filters (such as
    `platform`, `entry_type`, or a parent foreign key) are available where the
    endpoint table indicates them."

    Design: Corner/endpoints/corner_filter_channels_by_client
    """
    client_a = create_client(name="FA")
    client_b = create_client(name="FB")
    get_success_data(api.create_channel(
        {"client_id": client_a["id"], "platform": "X", "handle": "@fa"}, AM))
    get_success_data(api.create_channel(
        {"client_id": client_b["id"], "platform": "X", "handle": "@fb"}, AM))
    data, _meta = validate_paginated(
        api.list_channels(AM, params={"client_id": client_a["id"]}))
    assert all(ch["client_id"] == client_a["id"] for ch in data), (
        "every returned channel must belong to client A")
    assert len(data) == 1, f"data length must be 1, got {len(data)}"


# ===========================================================================
# corner rbac section
# ===========================================================================
def test_content_creator_cannot_approve(api):
    """PRD §2.1: "When a request is well-formed but the acting role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/corner_content_creator_cannot_approve
    """
    client, channel = setup_active_client(
        tier="STARTER", monthly_retainer_fee_cents=200000,
        monthly_boost_budget_cents=0, monthly_post_quota=5, included_channels=1,
        platform="X")
    item = create_content_with_target(client["id"], channel["id"])
    get_success_data(api.submit_content_item(item["id"], CC))
    # ContentCreator attempting the Approver-exclusive approve.
    validate_error(api.approve_content_item(item["id"], CC),
                   ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_user_context_returns_401(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, declaring the operational
    capacity under which the request is made. If either header is missing or
    malformed, the request is rejected with `ERR_MISSING_USER_CONTEXT`."

    Design: Corner/rbac/corner_missing_user_context_returns_401
    """
    validate_error(
        api.create_client({"name": "NoAuth", "account_manager_id": "am-1"}, {}),
        ApiErrorId.ERR_MISSING_USER_CONTEXT.value)
