"""Authentication, the endpoint role lists and the party-scope rungs."""

from test_helpers import (
    ADMIN,
    CLERK,
    COORD,
    UNKNOWN_UUIDS,
    WAREHOUSE,
    ApiErrorId,
    assert_same_instant,
    headers_role_only,
    headers_with_unknown_role,
    headers_without_role,
    make_brokerage_admin_headers,
    make_listing_agent_headers,
    make_seller_headers,
    make_vendor_rep_headers,
    new_brokerage,
    new_listing_agent,
    new_seller,
    new_vendor,
    setup_clock_only,
    setup_listing_active,
    setup_vacant_project_draft,
    setup_vacant_pull_draft,
    setup_vacant_pull_submitted,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_request_without_a_role_header_is_unauthenticated(api):
    """PRD §2.7: "Rung 1: `X-User-Role` is present on the request; otherwise
    `ERR_UNAUTHENTICATED`, HTTP 401."
    PRD §2.1: "A request that omits `X-User-Role` entirely is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401), and so is a request whose `X-User-Role` names a string
    that is not one of the eight declared roles — the two cases share one error code
    deliberately, because the server does not tell an anonymous caller which role names
    exist."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    setup_clock_only()

    resp = api.get_project(UNKNOWN_UUIDS["project"], headers_without_role())

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_an_undeclared_role_name_is_also_unauthenticated(api):
    """PRD §2.7: "Rung 2: `X-User-Role` names one of the eight declared roles; otherwise
    `ERR_UNAUTHENTICATED`, HTTP 401."
    PRD §2.1: "A request that omits `X-User-Role` entirely is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401), and so is a request whose `X-User-Role` names a string
    that is not one of the eight declared roles — the two cases share one error code
    deliberately, because the server does not tell an anonymous caller which role names
    exist."

    Design: Corner/errors/unknown_role_value_is_refused_as_unauthenticated
    """
    ctx = setup_vacant_project_draft()

    resp = api.open_pull(ctx["proj_id"], headers_with_unknown_role("WarehouseSupervisor"))

    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    _, meta = validate_paginated(api.list_pulls(WAREHOUSE, params={"project_id": ctx["proj_id"]}))
    assert meta["total_count"] == 0, "no pull row may be created by a refused request"


def test_an_entity_backed_role_must_supply_an_identity(api):
    """PRD §2.7: "Rung 3: `X-User-ID` is present whenever the role is one of the four
    entity-backed roles `ListingAgent`, `Seller`, `BrokerageAdmin` or `VendorRep`; otherwise
    `ERR_IDENTITY_REQUIRED`, HTTP 401."
    PRD §2.1: "If any of these four roles is presented without an `X-User-ID` header, the
    request is rejected with `ERR_IDENTITY_REQUIRED` (HTTP 401); the four opaque operator
    roles are not required to supply one."

    Design: Corner/rbac/entity_backed_role_missing_x_user_id_returns_identity_required
    """
    ctx = setup_listing_active()

    resp = api.listing_under_contract(ctx["listing_id"], headers_role_only("ListingAgent"))

    validate_error(resp, ApiErrorId.ERR_IDENTITY_REQUIRED.value, 401)
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "ACTIVE"


def test_a_foreign_listing_agent_cannot_drive_someone_elses_listing(api):
    """PRD §2.7: "Rung 10: when the acting role is `ListingAgent`, `X-User-ID` equals the
    `listing_agent_client_id` of the listing being touched, whether reached directly or
    through the project's `listing_id`; otherwise `ERR_NOT_LISTING_AGENT`, HTTP 403."
    PRD §2.1: "Being permitted by role is not the same as being a party to the record, and
    the two are separate rungs — a `ListingAgent` who is authorized to record a listing going
    under contract, but who is not that listing's own agent, gets `ERR_NOT_LISTING_AGENT`
    (HTTP 403) rather than `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/foreign_listing_agent_cannot_drive_another_agents_listing
    """
    ctx = setup_listing_active()
    other_agent = new_listing_agent(email="vi@ex.com", full_name="Vi Chen")

    resp = api.listing_under_contract(
        ctx["listing_id"], make_listing_agent_headers(other_agent["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_LISTING_AGENT.value, 403)
    listing = validate_success(api.get_listing(ctx["listing_id"], COORD))
    assert listing["listing_state"] == "ACTIVE"


def test_a_seller_cannot_record_consent_on_another_sellers_record(api):
    """PRD §2.7: "Rung 11: when the acting role is `Seller`, `X-User-ID` equals the
    `owner_client_id` of the property being touched; otherwise `ERR_NOT_PROPERTY_OWNER`, HTTP
    403."
    PRD §3.1: "A seller — and only the seller in question, acting on their own record, or an
    operator superuser — may set that flag true; it is the standing permission that lets
    their listing agent authorize a project above the agent's own ceiling."

    Design: Corner/rbac/foreign_seller_cannot_record_consent_for_another_seller
    """
    ctx = setup_listing_active()
    other_seller = new_seller(email="sam@ex.com", full_name="Sam Okoye")

    resp = api.record_seller_consent(
        ctx["seller_id"], make_seller_headers(other_seller["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_PROPERTY_OWNER.value, 403)
    owner = validate_success(api.get_client(ctx["seller_id"], COORD))
    assert owner["consent_on_file"] is False


def test_a_brokerage_admin_of_another_firm_cannot_authorize_the_project(api):
    """PRD §2.7: "Rung 12: when the acting role is `BrokerageAdmin`, `X-User-ID` equals the
    project's `brokerage_id`; otherwise `ERR_NOT_PROJECT_PARTY`, HTTP 403."
    PRD §2.1: "When `X-User-Role` is `BrokerageAdmin`, `X-User-ID` is the `id` of the acting
    `Brokerage` row, and ownership checks compare it against the `brokerage_id` of the
    project being touched."

    Design: Corner/rbac/foreign_brokerage_admin_cannot_authorize_another_firms_project
    """
    ctx = setup_vacant_project_draft()
    other = new_brokerage(name="Alder Group", license_code="BR-7788",
                          authorization_cap=15000.00)

    resp = api.authorize_project(
        ctx["proj_id"], make_brokerage_admin_headers(other["id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_PROJECT_PARTY.value, 403)
    project = validate_success(api.get_project(ctx["proj_id"], COORD))
    assert project["workflow_state"] == "DRAFT"


def test_a_vendor_rep_cannot_confirm_another_vendors_order(api):
    """PRD §2.7: "Rung 13: when the acting role is `VendorRep`, `X-User-ID` equals the
    `vendor_id` of the rental order being touched; otherwise `ERR_NOT_ORDER_VENDOR`, HTTP
    403."
    PRD §3.4: "The vendor's own representative — and only that representative, matched by
    identity against the order's `vendor_id` — confirms the order, moving `PLACED →
    CONFIRMED`."

    Design: Corner/rbac/foreign_vendor_rep_cannot_confirm_another_vendors_order
    """
    ctx = setup_vacant_pull_draft()
    other_vendor = new_vendor(name="Cascade Staging Supply", lead_time_days=5,
                              min_lease_cycles=3, cancel_cutoff_days=2,
                              rate_multiplier=1.20)
    order = validate_success(api.create_rental_order(
        {"project_id": ctx["proj_id"], "vendor_id": other_vendor["id"],
         "unit_count": 2}, WAREHOUSE), 201)
    validate_success(api.place_rental_order(order["id"], WAREHOUSE))

    resp = api.confirm_rental_order(order["id"], make_vendor_rep_headers(ctx["vendor_id"]))

    validate_error(resp, ApiErrorId.ERR_NOT_ORDER_VENDOR.value, 403)
    stored = validate_success(api.get_rental_order(order["id"], WAREHOUSE))
    assert stored["state"] == "PLACED"


def test_a_warehouse_manager_may_not_issue_an_invoice(api):
    """PRD §2.7: "Rung 4: the acting role appears in the endpoint's permitted-role list as
    published in §4; otherwise `ERR_UNAUTHORIZED`, HTTP 403."
    PRD §2.1: "`WarehouseManager` owns stock: inventory items, pulls, pull lines, rental
    orders, damage assessment and extension adjudication; under this service's
    segregation-of-duties model a `WarehouseManager` may never authorize a project, issue an
    invoice or take a payment."

    Design: Corner/rbac/warehouse_manager_cannot_issue_an_invoice
    """
    setup_clock_only()

    resp = api.issue_invoice(UNKNOWN_UUIDS["invoice"], WAREHOUSE)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_billing_clerk_may_not_adjudicate_a_damage_appeal(api):
    """PRD §2.7: "Rung 4: the acting role appears in the endpoint's permitted-role list as
    published in §4; otherwise `ERR_UNAUTHORIZED`, HTTP 403."
    PRD §2.1: "`BillingClerk` owns money movement — deposits, invoices and holdover accrual —
    and correspondingly may never adjudicate damage, run an allocation pass or authorize a
    project."

    Design: Corner/rbac/billing_clerk_cannot_adjudicate_a_damage_appeal
    """
    setup_clock_only()

    resp = api.adjudicate_damage(
        UNKNOWN_UUIDS["assessment"], {"decision": "UPHOLD"}, CLERK)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_a_staging_coordinator_may_not_commit_the_pull(api):
    """PRD §2.7: "Rung 4: the acting role appears in the endpoint's permitted-role list as
    published in §4; otherwise `ERR_UNAUTHORIZED`, HTTP 403."
    PRD §2.1: "`WarehouseManager` owns stock: inventory items, pulls, pull lines, rental
    orders, damage assessment and extension adjudication; under this service's
    segregation-of-duties model a `WarehouseManager` may never authorize a project, issue an
    invoice or take a payment."

    Design: Corner/rbac/staging_coordinator_cannot_run_the_allocation_pass
    """
    ctx = setup_vacant_pull_submitted()

    resp = api.commit_pull(ctx["pull_id"], ctx["proj_v"], COORD)

    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    pull = validate_success(api.get_pull(ctx["pull_id"], WAREHOUSE))
    assert pull["state"] == "SUBMITTED"


def test_the_clock_endpoint_reports_the_instant_it_was_set_to(api):
    """PRD §2.5: "A `PlatformAdmin` may reposition the clock by supplying a `to_iso8601`
    instant; the response reports the new setting as `current_utc`."
    PRD §2.5: "Repositioning the clock mutates no entity: nothing is created, no state
    advances, no version is bumped."

    Design: Corner/endpoints/clock_endpoint_reports_the_instant_it_was_set_to
    """
    validate_success(api.set_clock("2026-05-01T00:00:00Z", ADMIN))

    resp = api.set_clock("2026-06-01T00:00:00Z", ADMIN)

    data = validate_success(resp, 200)
    assert_same_instant(data["current_utc"], "2026-06-01T00:00:00Z", "clock.current_utc")
