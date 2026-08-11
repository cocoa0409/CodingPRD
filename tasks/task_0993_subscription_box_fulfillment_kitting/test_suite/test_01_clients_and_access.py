"""Client onboarding, wallet defaults, retrieval, auth, and role-based access.

Covers PRD §2.1 (roles and ownership), §2.9 tier-3 existence, §3.1 (wallet),
§3.2 (plan creation and SKU uniqueness).
"""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_box_plan,
    assert_client,
    create_box_plan_payload,
    create_client,
    create_client_payload,
    create_plan,
    get_plan,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_client_ops_headers,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_ops_headers"]
BILLING = TEST_USERS["billing_admin_headers"]
SUPPORT = TEST_USERS["customer_service_headers"]


class TestClientOnboarding:
    def test_client_create_applies_zero_wallet_default(self):
        """PRD §3.1: "The new client's `credit_balance_cents` is zero, and no
        creation payload may set it directly."

        Design: Corner/entities/client_create_applies_zero_wallet_default
        """
        set_clock()
        resp = api_client.create_client(
            create_client_payload(name="Corner Client",
                                  billing_email="corner@acme.test"), ADMIN)
        client = validate_success(resp, expected_status=201)
        assert_client(client)
        assert client["credit_balance_cents"] == 0, (
            f"fresh client wallet must be 0, got {client['credit_balance_cents']}"
        )
        assert is_valid_uuid(client["id"]), "id must be server-minted UUID"
        assert is_iso8601_timestamp(client["created_at"]), \
            "created_at must be server-minted ISO 8601"
        assert isinstance(client["version"], int), "version must be server-minted"


class TestBoxPlanRetrievalAndSku:
    def test_box_plan_get_returns_stored_fields(self):
        """PRD §3.2: "New plans are born in `DRAFT` status with no
        `active_revision_id`."

        Design: Corner/entities/box_plan_get_returns_stored_fields
        """
        set_clock()
        client = create_client(name="RT Client", billing_email="rt@acme.test")
        plan = create_plan(client["id"], "PL-RT", price_per_box_cents=2500,
                           shipping_weight_grams=750, name="RT Box")
        fetched = validate_success(api_client.get_box_plan(plan["id"], WAREHOUSE))
        assert_box_plan(fetched)
        assert fetched["name"] == "RT Box"
        assert fetched["price_per_box_cents"] == 2500
        assert fetched["shipping_weight_grams"] == 750
        assert fetched["status"] == "DRAFT", \
            f"new plan must be DRAFT, got {fetched['status']}"
        assert fetched["active_revision_id"] is None, \
            "new plan must have no active_revision_id"

    def test_box_plan_duplicate_sku_rejected(self):
        """PRD §3.2: "A `sku` already in use by any box plan is rejected with
        `ERR_DUPLICATE_SKU`."

        Design: Corner/validations/box_plan_duplicate_sku_rejected
        """
        set_clock()
        client_a = create_client(name="V9A Client", billing_email="v9a@acme.test")
        client_b = create_client(name="V9B Client", billing_email="v9b@acme.test")
        create_plan(client_a["id"], "PL-V9", name="V9 Box")
        resp = api_client.create_box_plan(
            create_box_plan_payload(client_b["id"], name="V9 Clone", sku="PL-V9"),
            make_client_ops_headers(client_b["id"]))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SKU)


class TestExistenceAndAuth:
    def test_subscriber_get_not_found_returns_404(self):
        """PRD §2.9: "every identifier in the path template and every foreign key
        in the body — `client_id`, `plan_id`, `shipment_id`, each entry of
        `shipment_ids`, and each `component_id` inside `lines` — resolves to an
        existing resource; failures yield `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/subscriber_get_not_found_returns_404
        """
        set_clock()
        resp = api_client.get_subscriber(NON_EXISTENT_UUID, WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_auth_headers_returns_unauthenticated(self):
        """PRD §2.1: "A request missing either header, or presenting a role
        string the system does not declare, is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        set_clock()
        client = create_client(name="ER1 Client", billing_email="er1@acme.test")
        resp = api_client.get_client(client["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRoleBasedAccess:
    def test_warehouse_ops_cannot_create_box_plan(self):
        """PRD §4: POST /box-plans is authorized for "ClientOps, PlatformAdmin"
        only. PRD §2.1: "an authenticated caller whose role is not admitted, or
        who violates the ownership rule below, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/rbac/warehouse_ops_cannot_create_box_plan
        """
        set_clock()
        client = create_client(name="RB1 Client", billing_email="rb1@acme.test")
        resp = api_client.create_box_plan(
            create_box_plan_payload(client["id"], name="RB1 Box", sku="PL-RB1"),
            WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_client_ops_cannot_touch_other_clients_plan(self):
        """PRD §2.1: "a `ClientOps` caller may act only on resources belonging
        to the client whose `id` they present — including reading a client
        record, which for `ClientOps` is restricted to their own `id`."

        Design: Corner/rbac/client_ops_cannot_touch_other_clients_plan
        """
        set_clock()
        client_a = create_client(name="RB3A Client", billing_email="rb3a@acme.test")
        client_b = create_client(name="RB3B Client", billing_email="rb3b@acme.test")
        plan = create_plan(client_b["id"], "PL-RB3", name="RB3 Box")
        resp = api_client.get_box_plan(plan["id"], make_client_ops_headers(client_a["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
