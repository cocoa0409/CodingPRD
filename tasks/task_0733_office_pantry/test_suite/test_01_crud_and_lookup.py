"""CRUD, retrieval, defaults, RBAC, pagination — Corner-index basics.

Skipped (silence pattern default-value):
  Corner/entities/product_dietary_flags_default_empty_array — PRD §3.1 does not name
  the server-side default for optional dietary_flags. Two faithful readers could
  ship different defaults (null vs []); asserting either would leak scaffold.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_client, assert_product, assert_subscription,
    is_valid_uuid, is_iso8601_timestamp,
    NON_EXISTENT_UUID,
    create_client_payload, create_product_payload,
    create_plan_payload, create_subscription_payload,
    make_client_admin_headers, make_platform_admin_headers,
    TEST_USERS,
    set_clock, create_plan, create_client, create_product,
    setup_active_subscription,
)


# ─────────────────────────────────────────────────────────────
# Corner/entities
# ─────────────────────────────────────────────────────────────

class TestClientCreation:
    def test_create_client_stamps_defaults(self, api):
        """PRD §3.1: "A newly created client has credit_balance_cents set to 0 and
        active_subscription_id set to null."
        PRD §2.4: "version: a monotonically increasing counter that begins at 1 on creation
        and increments by one on every mutation of the resource's fields."

        Design: Corner/entities/create_client_success_with_required_fields
        """
        set_clock("2026-06-01T00:00:00Z")
        res = api.create_client(create_client_payload(name="NewCo", headcount=25), TEST_USERS["platform_admin_headers"])
        client = validate_success(res, expected_status=201)
        assert_client(client)
        assert client["name"] == "NewCo"
        assert client["headcount"] == 25
        assert client["version"] == 1, f"expected version=1 on create, got {client['version']}"
        assert client["credit_balance_cents"] == 0, \
            f"expected credit_balance_cents=0, got {client['credit_balance_cents']}"
        assert client["active_subscription_id"] is None, \
            f"expected active_subscription_id=null, got {client['active_subscription_id']!r}"

    def test_get_client_returns_stored_fields(self, api):
        """PRD §3.1: "a platform admin registers each Client office with a name and an
        initial headcount."

        Design: Corner/entities/get_client_by_id_returns_stored_data
        """
        created = create_client(name="GetCo", headcount=7)
        res = api.get_client(created["id"], TEST_USERS["platform_admin_headers"])
        got = validate_success(res, expected_status=200)
        assert got["id"] == created["id"]
        assert got["name"] == "GetCo"
        assert got["headcount"] == 7


def test_get_client_nonexistent_returns_404(api):
    """PRD §2.5: "The first identifier that does not resolve produces the most-specific
    'not found' error for that resource type — ERR_CLIENT_NOT_FOUND ... and the request
    short-circuits (all HTTP 404)."

    Design: Corner/entities/client_not_found_returns_404
    """
    res = api.get_client(NON_EXISTENT_UUID, TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_CLIENT_NOT_FOUND", expected_status=404)


def test_subscription_defaults_status_draft_on_create(api):
    """PRD §3.3: "a new Subscription is created with status DRAFT, client_id bound to
    the target client, plan_id bound to the named plan."

    Design: Corner/entities/subscription_defaults_status_draft_on_create
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(tier="T-DEF", billing_type="FLAT", flat_fee_cents=1000, volume_discount_threshold_headcount=10)
    client = create_client(name="DefCo", headcount=5)
    res = api.create_subscription(
        client["id"],
        create_subscription_payload(plan["id"], client["version"]),
        make_client_admin_headers(client["id"]),
    )
    sub = validate_success(res, expected_status=201)
    assert sub["status"] == "DRAFT", f"expected DRAFT, got {sub['status']!r}"


def test_system_fields_id_and_created_at_stamped(api):
    """PRD §2.4: "id (string): a server-minted UUID, with no type prefix."
    PRD §2.4: "created_at (string): an ISO 8601 UTC timestamp with three fractional digits,
    stamped at creation."

    Design: Corner/entities/system_fields_id_and_created_at_stamped
    """
    set_clock("2026-05-10T09:30:00Z")
    res = api.create_client(create_client_payload(name="SysFields", headcount=3), TEST_USERS["platform_admin_headers"])
    client = validate_success(res, expected_status=201)
    assert is_valid_uuid(client["id"]), f"id must be UUID without prefix, got {client['id']!r}"
    assert is_iso8601_timestamp(client["created_at"]), \
        f"created_at must be ISO 8601, got {client['created_at']!r}"
    # PRD §2.4: three fractional digits. Server clock at 09:30:00 -> stamp reflects clock.
    assert client["created_at"] == "2026-05-10T09:30:00.000Z", \
        f"expected 2026-05-10T09:30:00.000Z, got {client['created_at']!r}"


# ─────────────────────────────────────────────────────────────
# Corner/rbac
# ─────────────────────────────────────────────────────────────

def test_location_manager_cannot_close_rotation(api):
    """PRD §2.1: "A request whose X-User-Role is not permitted for the target endpoint
    is rejected with ERR_UNAUTHORIZED (HTTP 403)."
    PRD §4 endpoint table: POST /rotation-cycles/{id}/close is authorized for PlatformAdmin only.

    Design: Corner/rbac/location_manager_cannot_close_rotation
    """
    state = setup_active_subscription()
    from test_helpers import make_location_manager_headers
    res = api.close_rotation_cycle(
        state["rotation_cycle"]["id"],
        make_location_manager_headers(state["location"]["id"]),
    )
    validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)


def test_client_admin_of_other_client_cannot_pause(api):
    """PRD §2.1: "an operation that requires role-scoped ownership but is invoked by an
    entity-backed principal whose X-User-ID does not match the target resource's
    owning-entity id is rejected with ERR_FORBIDDEN_OWNERSHIP (HTTP 403)."

    Design: Corner/rbac/client_admin_of_other_client_cannot_pause
    """
    state = setup_active_subscription()
    other = create_client(name="OtherClient", headcount=5)
    res = api.pause_subscription(
        state["subscription"]["id"],
        make_client_admin_headers(other["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_OWNERSHIP", expected_status=403)


def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "A request missing either header is rejected with
    ERR_MISSING_AUTH_HEADERS (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    res = api.create_client(create_client_payload(name="NoAuth", headcount=5), headers={})
    validate_error(res, "ERR_MISSING_AUTH_HEADERS", expected_status=401)


# ─────────────────────────────────────────────────────────────
# Corner/endpoints
# ─────────────────────────────────────────────────────────────

def test_list_products_pagination_limit_returns_two(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; it defaults to 10,
    with a minimum of 1 and a maximum of 100."

    Design: Corner/endpoints/list_products_pagination_limit_and_offset
    """
    for i, sku in enumerate(("PG-A", "PG-B", "PG-C")):
        create_product(sku=sku, name=f"Prod-{i}", category="SNACK", unit_cost_cents=(i + 1) * 10)
    res = api.list_products(TEST_USERS["platform_admin_headers"], params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 2, f"expected 2 products with limit=2, got {len(data)}"


def test_satisfaction_returns_neutral_when_no_feedback(api):
    """PRD §3.8: "If the filtered set for a variant is empty (no rows at all in
    provisional, or no rows referencing currently-stocked products in authoritative),
    the score is the neutral default of 3.00."

    Design: Corner/endpoints/satisfaction_read_returns_neutral_for_no_feedback
    """
    client = create_client(name="Silent", headcount=5)
    res = api.get_client_satisfaction(
        client["id"],
        TEST_USERS["platform_admin_headers"],
        params={"variant": "authoritative"},
    )
    body = validate_success(res, expected_status=200)
    assert body["score"] == 3.00, f"expected neutral score 3.00, got {body['score']!r}"
    assert body["feedback_considered"] == 0, \
        f"expected feedback_considered=0, got {body['feedback_considered']}"
