"""CRUD defaults, immutability, invalid transitions, RBAC, listing, and error
corner instances.

Covers the entities, remaining state_machines, errors, endpoints, and rbac
corner-design sections.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_creator_headers,
    make_patron_headers,
    make_platform_admin_headers,
    NO_AUTH_HEADERS,
    ApiErrorId,
    BOGUS_UUID,
    set_clock,
    create_creator,
    create_published_tier,
    create_patron,
    create_active_pledge,
    setup_active_membership,
    first_pledge_charge,
    settle_charge,
    open_conversation,
    create_post_payload,
)

ADMIN = make_platform_admin_headers()


# ---------------------------------------------------------------------------
# entities section
# ---------------------------------------------------------------------------
def test_creator_create_returns_201_with_defaults(api):
    """PRD §3.1: "The `platform_plan` selects the creator's own subscription to
    the platform and defaults to `STARTER`". "The `billing_mode` is the default
    billing model the creator offers and defaults to `MONTHLY`". "The
    `charge_timing` decides when new-cycle and proration charges are collected
    and defaults to `UP_FRONT`". "On registration the creator's `status` is set
    to `ACTIVE` and `pending_payout_cents` is initialized to 0."

    Design: Corner/entities/creator_create_returns_201_with_defaults
    """
    resp = api_client.create_creator(
        {"display_name": "Solo", "email": "solo_defaults@x.com", "payout_account_ref": "acct_solo"},
        make_creator_headers("bootstrap"),
    )
    data = validate_success(resp, 201)
    assert data["platform_plan"] == "STARTER"
    assert data["billing_mode"] == "MONTHLY"
    assert data["charge_timing"] == "UP_FRONT"
    assert data["status"] == "ACTIVE"
    assert data["pending_payout_cents"] == 0
    assert data["version"] == 1


def test_creator_get_nonexistent_returns_404(api):
    """PRD §2.5: "a missing creator yields `ERR_CREATOR_NOT_FOUND`".

    Design: Corner/entities/creator_get_nonexistent_returns_404
    """
    resp = api_client.get_creator(BOGUS_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CREATOR_NOT_FOUND.value)


def test_tier_create_missing_billing_model_returns_invalid_request(api):
    """PRD §3.1: "Creating a `Tier` requires the owning `creator_id`, a `name`,
    the `billing_model` the tier uses (`MONTHLY` or `PER_CREATION`), and a
    `rank`".
    PRD §2.6: "sixth, request-body well-formedness — required fields present,
    enum members valid, and integers within their permitted ranges
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/tier_create_missing_required_returns_invalid_request
    """
    creator = create_creator()
    resp = api_client.create_tier(
        {"creator_id": creator["id"], "name": "T", "rank": 1, "monthly_fee_cents": 1500},
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_patron_wallet_credit_starts_at_zero(api):
    """PRD §3.2: "registration sets the patron's `status` to `ACTIVE` and
    initializes `wallet_credit_cents` to 0."

    Design: Corner/entities/patron_wallet_credit_is_system_computed_input_ignored
    """
    resp = api_client.create_patron(
        {"display_name": "P", "email": "pcomp_wallet@x.com"}, make_patron_headers("bootstrap"),
    )
    data = validate_success(resp, 201)
    assert data["wallet_credit_cents"] == 0
    assert data["status"] == "ACTIVE"


def test_postaccess_immutable_no_version_field(api):
    """PRD §2.4: "The first is `PostAccess`, an access-grant record minted once
    when a patron is admitted to a post."
    PRD §3.8: "Posts with a `min_tier_rank` of 0 are public and admit any
    patron."

    Design: Corner/entities/postaccess_immutable_no_version_field
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator()
    headers = make_creator_headers(creator["id"])
    post = get_success_data(api_client.create_post(
        create_post_payload(creator["id"], min_tier_rank=0), headers))
    validate_success(api_client.publish_post(post["id"], headers), 200)
    patron = create_patron()

    resp = api_client.request_post_access(
        post["id"], {"patron_id": patron["id"]}, make_patron_headers(patron["id"]),
    )
    data = validate_success(resp, 201)
    assert data["granted_tier_rank"] == 0, f"public access snapshot rank 0, got {data['granted_tier_rank']}"
    assert "version" not in data, "PostAccess must not carry a version field"
    assert "updated_at" not in data, "PostAccess must not carry an updated_at field"


def test_tier_invalid_enum_billing_model_rejected(api):
    """PRD §2.6: "sixth, request-body well-formedness — required fields present,
    enum members valid, and integers within their permitted ranges
    (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/tier_invalid_enum_billing_model_rejected
    """
    creator = create_creator()
    resp = api_client.create_tier(
        {"creator_id": creator["id"], "name": "T", "billing_model": "HOURLY", "rank": 1,
         "monthly_fee_cents": 1500},
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# state_machines section (invalid transitions / idempotency)
# ---------------------------------------------------------------------------
def test_publish_already_published_tier_rejected(api):
    """PRD §3.1: "A tier becomes pledgeable only when its creator publishes it,
    advancing its `status` from `DRAFT` to `PUBLISHED`."
    PRD §5: "`ERR_TIER_NOT_PUBLISHED` | 409 Conflict".

    Design: Corner/state_machines/tier_publish_from_published_returns_not_published
    """
    creator = create_creator()
    headers = make_creator_headers(creator["id"])
    tier = create_published_tier(creator["id"], name="T", monthly_fee_cents=1500)

    resp = api_client.publish_tier(tier["id"], headers)
    validate_error(resp, ApiErrorId.ERR_TIER_NOT_PUBLISHED.value)


def test_settle_already_succeeded_charge_rejected(api):
    """PRD §3.5: "The settle is permitted only when the charge is `PENDING`;
    otherwise it is rejected with `ERR_CHARGE_NOT_PENDING`."

    Design: Corner/state_machines/charge_settle_from_succeeded_returns_not_pending
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    charge_id = s["init_charge"]["id"]  # already SUCCEEDED in setup

    resp = api_client.settle_charge(charge_id, {"outcome": "SUCCEEDED"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_CHARGE_NOT_PENDING.value)


# ---------------------------------------------------------------------------
# errors section
# ---------------------------------------------------------------------------
def test_publish_per_creation_tier_missing_fee_fields_rejected(api):
    """PRD §3.1: "Publishing first verifies that the pricing fields appropriate
    to the tier's billing model are present — a `MONTHLY` tier must have
    `monthly_fee_cents`, and a `PER_CREATION` tier must have both
    `per_creation_fee_cents` and `per_creation_monthly_cap_cents` — failing which
    the publish is rejected with `ERR_TIER_FIELDS_INCOMPLETE`."

    Design: Corner/errors/tier_fields_incomplete_on_publish
    """
    creator = create_creator(billing_mode="PER_CREATION")
    headers = make_creator_headers(creator["id"])
    tier = get_success_data(api_client.create_tier(
        {"creator_id": creator["id"], "name": "PC", "billing_model": "PER_CREATION", "rank": 1}, headers))

    resp = api_client.publish_tier(tier["id"], headers)
    validate_error(resp, ApiErrorId.ERR_TIER_FIELDS_INCOMPLETE.value)


# ---------------------------------------------------------------------------
# endpoints section
# ---------------------------------------------------------------------------
def test_list_pledges_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_pledges_pagination_envelope
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    resp = api_client.list_pledges(ADMIN, params={"creator_id": s["creator"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected one pledge, got {meta['total_count']}"
    assert meta["has_more"] is False


def test_post_access_grant_succeeds_for_qualifying_tier(api):
    """PRD §3.8: "the gate admits the patron only when the patron holds an
    `ACTIVE` pledge to the post's creator on a tier whose `rank` is at least the
    post's `min_tier_rank`."
    PRD §3.8: "and `granted_tier_rank`, a snapshot of the patron's tier rank at
    the instant access was granted."

    Design: Corner/endpoints/post_access_grant_succeeds_for_qualifying_tier
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator()
    high = create_published_tier(creator["id"], name="HIGH", rank=3, monthly_fee_cents=2500)
    patron = create_patron()
    create_active_pledge(patron["id"], creator["id"], high["id"])
    headers = make_creator_headers(creator["id"])
    post = get_success_data(api_client.create_post(
        create_post_payload(creator["id"], min_tier_rank=2), headers))
    validate_success(api_client.publish_post(post["id"], headers), 200)

    resp = api_client.request_post_access(
        post["id"], {"patron_id": patron["id"]}, make_patron_headers(patron["id"]),
    )
    data = validate_success(resp, 201)
    assert data["granted_tier_rank"] == 3, f"snapshot must be the patron's rank 3, got {data['granted_tier_rank']}"


def test_message_send_increments_conversation_count(api):
    """PRD §3.8: "the server derives `sender_role` (`CREATOR` or `PATRON`) and
    `sender_id` from the auth context".
    PRD §3.8: "Each posted message increments the conversation's `message_count`
    by one."

    Design: Corner/endpoints/message_send_increments_conversation_count
    """
    s = setup_active_membership(clock="2026-06-16T00:00:00Z", monthly_fee_cents=1500)
    conv = open_conversation(s["creator"]["id"], s["patron"]["id"])

    msg_resp = api_client.create_message(
        {"conversation_id": conv["id"], "body": "thanks!"}, make_patron_headers(s["patron"]["id"]),
    )
    msg = validate_success(msg_resp, 201)
    assert msg["sender_role"] == "PATRON", f"sender_role must be PATRON, got {msg['sender_role']}"

    conv_now = get_success_data(api_client.get_conversation(conv["id"], make_creator_headers(s["creator"]["id"])))
    assert conv_now["message_count"] == 1, f"message_count must be 1, got {conv_now['message_count']}"


# ---------------------------------------------------------------------------
# rbac section
# ---------------------------------------------------------------------------
def test_missing_auth_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value,
    is rejected with `ERR_MISSING_AUTH_CONTEXT`."

    Design: Corner/rbac/missing_auth_header_returns_401
    """
    resp = api_client.create_creator(
        {"display_name": "C", "email": "cnoauth@x.com", "payout_account_ref": "acct_na"},
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_CONTEXT.value)


def test_patron_cannot_create_tier_returns_403(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/patron_cannot_create_tier_returns_403
    """
    creator = create_creator()
    patron = create_patron()
    resp = api_client.create_tier(
        {"creator_id": creator["id"], "name": "T", "billing_model": "MONTHLY", "rank": 1,
         "monthly_fee_cents": 1500},
        make_patron_headers(patron["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_patron_cannot_pause_other_patrons_pledge_returns_not_owner(api):
    """PRD §2.1: "When an entity-backed actor (`Creator` or `Patron`) targets a
    resource it does not own — for example a `Creator` trying to refund a charge
    belonging to another creator, or a `Patron` pausing someone else's pledge —
    the request is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/patron_cannot_pause_other_patrons_pledge_returns_not_owner
    """
    set_clock("2026-06-16T00:00:00Z")
    creator = create_creator(charge_timing="UP_FRONT")
    tier = create_published_tier(creator["id"], name="T", monthly_fee_cents=1500)
    patron_a = create_patron()
    patron_b = create_patron()
    pledge = create_active_pledge(patron_a["id"], creator["id"], tier["id"])
    v0 = pledge["version"]

    # Patron B attempts to pause Patron A's pledge.
    resp = api_client.pause_pledge(
        pledge["id"], {"expected_pledge_version": v0}, make_patron_headers(patron_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
