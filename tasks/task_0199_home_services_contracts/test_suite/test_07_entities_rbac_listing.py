"""Entity creation/validation, RBAC denials, and FK reverse-reachability list endpoints.

Covers corner queue sections: entities, rbac, endpoints.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    api_client,
    TEST_USERS,
    NON_EXISTENT_UUID,
    NO_AUTH_HEADERS,
    make_technician_headers,
    make_customer_headers,
    create_service_plan_payload,
    create_membership_payload,
    create_equipment_payload,
    create_warranty_claim_payload,
    create_part_usage_payload,
    ApiErrorId,
    create_plan,
    create_customer,
    create_site,
    create_equipment,
    create_membership,
    create_technician,
    create_and_activate_membership,
    setup_membership_in_renewal_pending,
    setup_completed_warranty_visit,
    setup_visit_on_site,
    book_visit,
    dispatch_visit,
    file_warranty_claim,
)

ADMIN = TEST_USERS["contract_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Corner / entities
# ===========================================================================
def test_create_service_plan_returns_201_with_all_fields(api):
    """PRD §3.1: "A plan declares its `tier` — one of `BASIC`, `PLUS`, or `PREMIUM` — and
    the `trade` it covers, either `HVAC` or `PEST`."
    PRD §3.1: "Every plan carries an `active` flag, a system-managed boolean that starts
    true."
    PRD §2.4: "a `version` integer that starts at 1 and increments by exactly one on every
    mutation that changes the resource."

    Design: Corner/entities/create_service_plan_returns_201_with_all_fields
    """
    plan = validate_success(
        api.create_service_plan(
            create_service_plan_payload(tier="BASIC", trade="PEST", annual_fee_cents=12000,
                                        included_visits_per_year=4, extra_visit_fee_cents=5000,
                                        sla_response_hours=24, parts_discount_pct=0.0), ADMIN), 201
    )
    assert plan["tier"] == "BASIC", f"tier echoed, got {plan['tier']}"
    assert plan["active"] is True, f"active starts true, got {plan['active']}"
    assert plan["version"] == 1, f"version starts at 1, got {plan['version']}"


def test_create_membership_missing_plan_id_rejected(api):
    """PRD §3.2: "A **membership** ties a customer, a site, and a plan together for a term.
    It is created with the member's `customer_id`, the covered `site_id`, and the enrolled
    `plan_id`."
    PRD §2.9: "the request body itself checked for being present, JSON-parseable, and
    complete with required fields of the correct types and valid enum values
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_membership_missing_plan_id_returns_invalid_request
    """
    customer = create_customer()
    site = create_site(customer["id"])
    payload = {"customer_id": customer["id"], "site_id": site["id"]}  # plan_id omitted
    validate_error(api.create_membership(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_service_plan_invalid_tier_enum_rejected(api):
    """PRD §3.1: "A plan declares its `tier` — one of `BASIC`, `PLUS`, or `PREMIUM` — and
    the `trade` it covers, either `HVAC` or `PEST`."
    PRD §2.9: "the request body itself checked for being present, JSON-parseable, and
    complete with required fields of the correct types and valid enum values
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/create_service_plan_invalid_tier_enum_returns_invalid_request
    """
    payload = create_service_plan_payload(tier="GOLD", trade="HVAC", annual_fee_cents=1,
                                          included_visits_per_year=1, extra_visit_fee_cents=1,
                                          sla_response_hours=1, parts_discount_pct=0.0)
    validate_error(api.create_service_plan(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_membership_returns_not_found(api):
    """PRD §2.5: "the server validates each identifier left to right and rejects the
    request with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve
    to an existing resource, before evaluating any deeper segment or applying business
    rules."

    Design: Corner/entities/get_membership_nonexistent_returns_not_found
    """
    validate_error(api.get_membership(NON_EXISTENT_UUID, ADMIN), ApiErrorId.ERR_NOT_FOUND.value)


def test_membership_auto_renew_defaults_from_plan_default(api):
    """PRD §3.2: "At creation the membership's `auto_renew` flag is taken from the plan's
    `auto_renew_default` unless the request supplies its own `auto_renew` value, and the
    membership opens in `PENDING_ACTIVATION` status."
    PRD §3.1: "A plan also stamps a default onto memberships through `auto_renew_default`,
    a boolean that defaults to true when omitted at creation."

    Design: Corner/entities/membership_auto_renew_defaults_from_plan_default
    """
    plan = create_plan()  # auto_renew_default omitted -> true
    customer = create_customer()
    site = create_site(customer["id"])
    membership = create_membership(customer["id"], site["id"], plan["id"])  # auto_renew omitted
    assert membership["auto_renew"] is True, f"auto_renew copied from plan default true, got {membership['auto_renew']}"
    assert membership["status"] == "PENDING_ACTIVATION", f"opens PENDING_ACTIVATION, got {membership['status']}"


# ===========================================================================
# Corner / rbac
# ===========================================================================
def test_dispatcher_cannot_activate_membership(api):
    """PRD §2.1: "A request whose role is recognized but is not permitted to perform the
    requested operation (per the endpoint catalogue in Section 4 and the workflow
    narratives in Section 3) is rejected with `ERR_UNAUTHORIZED`."
    PRD §4: the activate endpoint is authorized for ContractAdmin only.

    Design: Corner/rbac/dispatcher_cannot_activate_membership_unauthorized
    """
    plan = create_plan()
    customer = create_customer()
    site = create_site(customer["id"])
    membership = create_membership(customer["id"], site["id"], plan["id"])
    validate_error(api.activate_membership(membership["id"], DISPATCHER), ApiErrorId.ERR_UNAUTHORIZED.value)


def test_technician_cannot_act_on_unassigned_visit(api):
    """PRD §2.1: "a technician may only depart, arrive at, complete, or post refrigerant
    and parts against a `ServiceVisit` whose `technician_id` equals their own `X-User-ID`."
    PRD §2.1: "when a `Customer` acts on a resource it does not own, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/technician_cannot_act_on_unassigned_visit_not_resource_owner
    """
    ctx = create_and_activate_membership()
    tech_a = create_technician(full_name="Tech A", region_code="NORTH", trade="HVAC")
    tech_b = create_technician(full_name="Tech B", region_code="NORTH", trade="HVAC")
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    dispatch_visit(visit["id"], tech_a["id"])
    # Tech B (not the assigned tech) tries to depart.
    validate_error(
        api.depart_service_visit(visit["id"], make_technician_headers(tech_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )


def test_customer_cannot_cancel_another_customers_membership(api):
    """PRD §2.1: "A customer reading or cancelling a membership, reading a site or visit,
    or accepting/declining a renewal offer must own the underlying customer record; when a
    `Customer` acts on a resource it does not own, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_membership_not_owner
    """
    ctx = create_and_activate_membership()
    other_customer = create_customer(email="other-customer@example.com")
    validate_error(
        api.cancel_membership(ctx["membership"]["id"], make_customer_headers(other_customer["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits either header, or that carries an `X-User-Role`
    value outside this set, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    resp = api._request("GET", "/home-services/service-plans", headers=NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# Corner / endpoints — FK reverse-reachability lists
# ===========================================================================
def test_list_equipment_by_site_subresource(api):
    """PRD §3.7: "Equipment installed at a site is listable through the site's equipment
    sub-collection."

    Design: Corner/endpoints/list_equipment_by_site_subresource
    """
    customer = create_customer()
    site = create_site(customer["id"])
    create_equipment(site["id"], model="AC-1", refrigerant_type="R410A", nameplate_charge_grams=4000)
    create_equipment(site["id"], model="AC-2", refrigerant_type="R32", nameplate_charge_grams=2500)
    data, meta = validate_paginated(api.list_site_equipment(site["id"], ADMIN))
    assert meta["total_count"] == 2, f"two units installed at the site, got total_count={meta['total_count']}"


def test_list_service_visits_by_membership_subresource(api):
    """PRD §3.5: "Visits are listable globally and as a sub-collection of a membership,
    filterable by `membership_id`, `technician_id`, `site_id`, `status`, and
    `visit_kind`."

    Design: Corner/endpoints/list_service_visits_by_membership_subresource
    """
    ctx = create_and_activate_membership()
    book_visit(ctx["membership"], visit_kind="SEASONAL")
    data, meta = validate_paginated(api.list_membership_service_visits(ctx["membership"]["id"], DISPATCHER))
    assert meta["total_count"] == 1, f"one visit on the membership, got total_count={meta['total_count']}"


def test_list_refrigerant_logs_filtered_by_equipment(api):
    """PRD §3.7: "Refrigerant logs are listable both as a visit's sub-collection and
    globally, where they can be filtered by `equipment_id`, `posted_by_tech_id`, and the
    originating `visit_id`."

    Design: Corner/endpoints/list_refrigerant_logs_by_equipment_filtered
    """
    from test_helpers import create_refrigerant_log_payload
    ctx = setup_visit_on_site(equipment_overrides={"refrigerant_type": "R410A"})
    validate_success(
        api.post_refrigerant_log(ctx["visit"]["id"],
                                 create_refrigerant_log_payload(ctx["equipment"]["id"], "RECOVER", 100),
                                 make_technician_headers(ctx["technician"]["id"])), 201
    )
    data, meta = validate_paginated(api.list_refrigerant_logs(ADMIN, params={"equipment_id": ctx["equipment"]["id"]}))
    assert meta["total_count"] == 1, f"one log for the equipment, got total_count={meta['total_count']}"


def test_list_warranty_claims_filtered_by_equipment(api):
    """PRD §3.10: "Claims are listable and filterable by `equipment_id`,
    `origin_visit_id`, and `status`."

    Design: Corner/endpoints/list_warranty_claims_by_equipment_filtered
    """
    ctx = setup_completed_warranty_visit(equipment_overrides={"refrigerant_type": "R410A"})
    file_warranty_claim(ctx["equipment"]["id"], ctx["warranty_visit"]["id"], 10000)
    data, meta = validate_paginated(api.list_warranty_claims(ADMIN, params={"equipment_id": ctx["equipment"]["id"]}))
    assert meta["total_count"] == 1, f"one claim for the equipment, got total_count={meta['total_count']}"


def test_list_renewal_offers_filtered_by_offered_plan(api):
    """PRD §3.4: "Renewal offers are listable both as a sub-collection of a membership and
    globally, filterable by `membership_id`, `offered_plan_id`, and `status`."

    Design: Corner/endpoints/list_renewal_offers_by_offered_plan_filtered
    """
    ctx = setup_membership_in_renewal_pending()
    data, meta = validate_paginated(api.list_renewal_offers(ADMIN, params={"offered_plan_id": ctx["plan"]["id"]}))
    assert meta["total_count"] == 1, f"one offer on the plan, got total_count={meta['total_count']}"


def test_list_sites_filtered_by_customer(api):
    """PRD §3.2: "Sites can be listed and filtered by `customer_id` and `region_code`."

    Design: Corner/endpoints/list_sites_by_customer_filtered
    """
    customer = create_customer()
    create_site(customer["id"])
    data, meta = validate_paginated(api.list_sites(ADMIN, params={"customer_id": customer["id"]}))
    assert meta["total_count"] == 1, f"one site for the customer, got total_count={meta['total_count']}"


def test_list_service_visits_filtered_by_technician(api):
    """PRD §3.5: "Visits are listable globally and as a sub-collection of a membership,
    filterable by `membership_id`, `technician_id`, `site_id`, `status`, and
    `visit_kind`."

    Design: Corner/endpoints/list_service_visits_by_technician_filtered
    """
    ctx = create_and_activate_membership()
    tech = create_technician()
    visit = book_visit(ctx["membership"], visit_kind="SEASONAL")
    dispatch_visit(visit["id"], tech["id"])
    data, meta = validate_paginated(api.list_service_visits(DISPATCHER, params={"technician_id": tech["id"]}))
    assert meta["total_count"] == 1, f"one visit assigned to the tech, got total_count={meta['total_count']}"


def test_list_part_usages_by_visit_subresource(api):
    """PRD §3.7: a part usage names the `part_name`, the `quantity` consumed, and the
    per-unit `list_price_cents`. PRD §4: the part-usages sub-collection lists parts
    consumed on a visit.

    Design: Corner/endpoints/list_part_usages_by_visit_subresource
    """
    ctx = setup_visit_on_site(with_equipment=False)
    tech_headers = make_technician_headers(ctx["technician"]["id"])
    validate_success(
        api.post_part_usage(ctx["visit"]["id"], create_part_usage_payload("Belt", 1, 1000), tech_headers), 201
    )
    data, meta = validate_paginated(api.list_visit_part_usages(ctx["visit"]["id"], tech_headers))
    assert meta["total_count"] == 1, f"one part on the visit, got total_count={meta['total_count']}"
