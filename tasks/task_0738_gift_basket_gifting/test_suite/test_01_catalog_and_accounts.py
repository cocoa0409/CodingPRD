"""Catalog and account basics: FK-existence 404s across path/body references,
success-envelope shape, pagination defaults, and FK reverse-reachability.

All Corner-queue translations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, factories, fixtures,
)
from test_helpers.test_users import (
    TEST_USERS, make_account_manager_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
FIN = TEST_USERS["finance_approver_headers"]

_MISSING_ID = "00000000-0000-4000-8000-000000000000"


def test_get_account_not_found_returns_404(api):
    """PRD §2.9: "Any endpoint mounted under an account (/corporate-accounts/{id}/...)
    or referencing a corporate_account_id in its body first confirms the named
    CorporateAccount exists, failing with ERR_ACCOUNT_NOT_FOUND (404) otherwise."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account(_MISSING_ID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


def test_order_path_id_not_found_returns_404(api):
    """PRD §2.9: "Any endpoint mounted under an order (/orders/{id}/...) first
    confirms the named CorporateOrder exists, failing with ERR_ORDER_NOT_FOUND
    (404) otherwise."

    Design: Corner/entities/order_path_id_not_found_returns_404
    """
    resp = api.get_order("00000000-0000-4000-8000-000000000001", ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_recipient_path_id_not_found_returns_404(api):
    """PRD §2.9: "Any endpoint mounted under a recipient (/recipients/{id}/...)
    first confirms the named Recipient exists, failing with ERR_RECIPIENT_NOT_FOUND
    (404) otherwise."

    Design: Corner/entities/recipient_path_id_not_found_returns_404
    """
    hdrs = make_account_manager_headers("acct-doesnt-matter")
    resp = api.submit_message_proof(
        "00000000-0000-4000-8000-000000000002",
        factories.message_proof_payload(message_text="Hi",
                                        submitted_by_user_id="emp-x"),
        hdrs)
    validate_error(resp, ApiErrorId.ERR_RECIPIENT_NOT_FOUND.value)


def test_template_id_not_found_on_order_create_returns_404(api):
    """PRD §3.4: "Creation fails with ERR_TEMPLATE_NOT_FOUND (404) if the named
    template does not exist or is not active, and with ERR_BRANDING_PROFILE_NOT_FOUND
    (404) if a branding_profile_id is supplied that either does not exist or belongs
    to a different account."

    Design: Corner/entities/template_id_not_found_on_order_create_returns_404
    """
    account = fixtures.create_account(api)
    hdrs = make_account_manager_headers(account["id"])
    payload = factories.create_order_payload(
        template_id="00000000-0000-4000-8000-000000000003",
        occasion="CUSTOM",
        expected_corporate_account_version=account["version"])
    resp = api.create_order(account["id"], payload, hdrs)
    validate_error(resp, ApiErrorId.ERR_TEMPLATE_NOT_FOUND.value)


def test_branding_profile_id_not_found_on_order_create_returns_404(api):
    """PRD §3.4: "Creation fails with ERR_TEMPLATE_NOT_FOUND (404) if the named
    template does not exist or is not active, and with ERR_BRANDING_PROFILE_NOT_FOUND
    (404) if a branding_profile_id is supplied that either does not exist or belongs
    to a different account."

    Design: Corner/entities/branding_profile_id_not_found_on_order_create_returns_404
    """
    base = fixtures.setup_catalog(api)
    hdrs = make_account_manager_headers(base["account"]["id"])
    payload = factories.create_order_payload(
        template_id=base["template"]["id"],
        occasion="CUSTOM",
        branding_profile_id="00000000-0000-4000-8000-000000000004",
        expected_corporate_account_version=base["account"]["version"])
    resp = api.create_order(base["account"]["id"], payload, hdrs)
    validate_error(resp, ApiErrorId.ERR_BRANDING_PROFILE_NOT_FOUND.value)


def test_sku_id_not_found_on_template_create_returns_404(api):
    """PRD §3.1: "every sku_id referenced this way is validated against an
    existing ComponentSKU.id at write time, and a reference to a SKU that does
    not exist is rejected with ERR_SKU_NOT_FOUND (404)."

    Design: Corner/entities/sku_id_not_found_on_template_create_returns_404
    """
    payload = factories.create_template_payload(
        name="Bad Basket", category="CUSTOM", base_price_cents=1000,
        is_perishable=False,
        components=[{"sku_id": "00000000-0000-4000-8000-000000000005",
                     "quantity": 1}])
    resp = api.create_template(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SKU_NOT_FOUND.value)


def test_station_id_not_found_on_budget_decision_returns_404(api):
    """PRD §3.4: "the named station_id must resolve to an existing AssemblyStation
    (ERR_FULFILLMENT_REF_NOT_FOUND, 404)."

    Design: Corner/entities/station_id_not_found_on_budget_decision_returns_404
    """
    base = fixtures.setup_catalog(
        api, approval_threshold_cents=1000)
    p = fixtures.setup_pending_approval_order(api, base=base)
    resp = api.budget_decision(
        p["order"]["id"],
        factories.budget_decision_payload(
            decision="APPROVE", approver_user_id="fin-appr-18",
            station_id="00000000-0000-4000-8000-000000000006",
            scheduled_date="2026-03-04T00:00:00Z"),
        FIN)
    validate_error(resp, ApiErrorId.ERR_FULFILLMENT_REF_NOT_FOUND.value)


def test_assembly_task_path_id_not_found_returns_404(api, warehouse_headers):
    """PRD §2.9: "Deeper sub-resource path ids — on the assembly-task advance,
    shipment advance, message-proof fetch, message-proof decision, and
    recurring-series update operations — are checked for existence against
    ERR_SUBRESOURCE_NOT_FOUND (404)."

    Design: Corner/entities/assembly_task_path_id_not_found_returns_404
    """
    resp = api.advance_assembly_task(
        "00000000-0000-4000-8000-000000000007",
        {"target_status": "IN_PROGRESS"}, warehouse_headers)
    validate_error(resp, ApiErrorId.ERR_SUBRESOURCE_NOT_FOUND.value)


def test_success_envelope_shape_on_object_response(api):
    """PRD §2.2: "The api_request_id is a server-generated unique identifier for
    the request that starts with req_."
    PRD §2.2: "The response_type is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/success_envelope_shape_on_object_response
    """
    resp = api.create_account(
        factories.create_account_payload(
            name="Envelope Corp", billing_email="ap@envelope.example",
            monthly_budget_cents=1_000_000, approval_threshold_cents=1_000_000),
        ADMIN)
    # Raw check on the outer envelope, since validate_success only returns data.
    body = resp.json()
    assert isinstance(body.get("meta", {}).get("api_request_id"), str) \
        and len(body["meta"]["api_request_id"]) > 0, \
        "meta.api_request_id must be a non-empty string"
    assert isinstance(body["meta"].get("api_request_timestamp"), str)
    assert body["response_type"] == "object"
    assert body["data"]["name"] == "Envelope Corp"


def test_pagination_defaults_on_orders_list(api):
    """PRD §2.3: "limit defaults to 10 when omitted, and must be no smaller than
    1 and no larger than 100. offset defaults to 0 when omitted and has no
    declared upper bound."
    PRD §2.3: "The response meta object for a list endpoint carries limit, offset,
    total_count (the number of matching rows across all pages), and has_more
    (whether a subsequent page exists beyond the returned slice)."

    Design: Corner/endpoints/pagination_defaults_on_orders_list
    """
    base = fixtures.setup_catalog(api,
                                  monthly_budget_cents=100_000_000,
                                  approval_threshold_cents=100_000_000)
    fixtures.create_order(api, account=base["account"],
                          template_id=base["template"]["id"],
                          occasion="CUSTOM")
    resp = api.list_orders(ADMIN, params={"corporate_account_id": base["account"]["id"]})
    data, meta = validate_paginated(resp)
    assert isinstance(data, list)
    assert meta["limit"] == 10, "default limit must be 10"
    assert meta["offset"] == 0, "default offset must be 0"
    assert meta["total_count"] >= 1
    assert isinstance(meta["has_more"], bool)


def test_branding_profile_reverse_reachability_from_account(api):
    """PRD §3.3: "A companion listing call lets an AccountManager or PlatformAdmin
    enumerate every BrandingProfile created under a given account."

    Design: Corner/endpoints/branding_profile_reverse_reachability_from_account
    """
    account = fixtures.create_account(api)
    profile = fixtures.create_branding_profile(api, account=account, name="Reverse Kit")
    hdrs = make_account_manager_headers(account["id"])
    data, _ = validate_paginated(api.list_branding_profiles(account["id"], hdrs))
    assert len(data) == 1, "exactly one profile was created for this account"
    assert data[0]["id"] == profile["id"]


def test_inventory_reservations_reverse_reachability_by_sku_id(api, warehouse_headers):
    """PRD §3.6: "The reservation-list and assembly-task-list endpoints support
    optional filtering by recipient_id and sku_id/station_id respectively, plus
    status on both."

    Design: Corner/endpoints/inventory_reservations_reverse_reachability_by_sku_id
    """
    base = fixtures.setup_catalog(api,
                                  monthly_budget_cents=1_000_000,
                                  approval_threshold_cents=1_000_000)
    order, _ = fixtures.setup_order_with_recipients(
        api, account=base["account"], template_id=base["template"]["id"],
        rows=[factories.recipient_row(quantity=1)],
        occasion="CUSTOM")
    data, _ = validate_paginated(
        api.list_inventory_reservations(warehouse_headers,
                                        params={"sku_id": base["sku"]["id"]}))
    assert len(data) == 1
    assert data[0]["sku_id"] == base["sku"]["id"]
    assert data[0]["status"] == "RESERVED"
