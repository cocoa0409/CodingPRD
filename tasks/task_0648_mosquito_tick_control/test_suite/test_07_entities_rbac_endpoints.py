"""Entity CRUD, computed-field, RBAC, and listing/pagination tests.

Covers the corner entities, rbac, and endpoints sections.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, validate_paginated,
    is_valid_uuid, ApiErrorId,
    TEST_USERS, make_account_holder_headers, make_crew_tech_headers,
    create_active_subscription, list_recurring_visits, create_crew,
    create_route, dispatch_visit, log_application, complete_visit, set_clock,
    create_service_plan, create_account_holder, create_property, add_zone,
    create_subscription, setup_completed_per_visit_with_invoice,
)

PLATFORM = TEST_USERS["platform_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_admin_headers"]


def test_create_property_returns_201_with_zeroed_computed_fields(api):
    """
    PRD 3.1: "On creation, a property's `zone_count` and `total_treatable_sqft` both initialize to 0."

    Design: Corner/entities/create_property_returns_201_with_zeroed_computed_fields
    """
    holder = create_account_holder()
    ah = make_account_holder_headers(holder["id"])
    prop = validate_success(api.create_property(
        {"account_holder_id": holder["id"], "street_address": "1 Way", "lot_size_sqft": 6000, "service_region_code": "NE01"},
        ah), expected_status=201)
    assert is_valid_uuid(prop["id"])
    assert prop["zone_count"] == 0
    assert prop["total_treatable_sqft"] == 0
    assert prop["version"] == 1


def test_get_property_nonexistent_returns_not_found(api):
    """
    PRD 2.6: "For any request, the system validates the existence of every path identifier and every foreign-key body field in left-to-right path order, rejecting with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing resource."

    Design: Corner/entities/get_property_nonexistent_returns_not_found
    """
    validate_error(api.get_property("00000000-0000-4000-8000-000000000001", PLATFORM), ApiErrorId.ERR_NOT_FOUND.value)


def test_create_subscription_missing_billing_mode_returns_invalid_request(api):
    """
    PRD 3.2: "It is created in `DRAFT` status with the `property_id` it services, the `service_plan_id` governing cadence and pricing, a `billing_mode` of either `PER_VISIT` or `SEASONAL`, an inclusive `season_start_date` and inclusive `season_end_date` (each a `YYYY-MM-DD` calendar date), and an `auto_renew` flag that defaults to true."

    Design: Corner/entities/create_subscription_missing_required_field_returns_invalid_request
    """
    plan = create_service_plan()
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    ah = make_account_holder_headers(holder["id"])
    validate_error(api.create_subscription(
        {"property_id": prop["id"], "service_plan_id": plan["id"], "season_start_date": "2026-05-01", "season_end_date": "2026-08-31"},
        ah), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_zone_invalid_enum_zone_type_returns_invalid_request(api):
    """
    PRD 3.1: "A zone is added under its property with a `label` (a human description such as "Backyard" or "Front perimeter"), a `zone_type` — one of `TURF`, `PERIMETER`, `WATER_FEATURE`, or `WOODLINE`, which sets the per-zone application weighting used in pricing — and an `area_sqft` that must be greater than zero."

    Design: Corner/entities/create_zone_invalid_enum_zone_type_returns_invalid_request
    """
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    ah = make_account_holder_headers(holder["id"])
    validate_error(api.add_zone(prop["id"], {"label": "Bad", "zone_type": "DRIVEWAY", "area_sqft": 1000}, ah), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_zone_add_recomputes_count_and_treatable_sqft(api):
    """
    PRD 2.5: "On a `Property`, the `zone_count` is the number of `TreatmentZone` rows whose `property_id` equals that property, counted regardless of zone status, and `total_treatable_sqft` is the sum of `area_sqft` across only those zones whose `status` is `ACTIVE`."

    Design: Corner/entities/zone_count_and_total_treatable_sqft_recompute_on_zone_add
    """
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    ah = make_account_holder_headers(holder["id"])
    add_zone(prop, holder["id"], label="Turf", zone_type="TURF", area_sqft=4000)
    validate_success(api.add_zone(prop["id"], {"label": "Perim", "zone_type": "PERIMETER", "area_sqft": 2000}, ah), expected_status=201)
    after = get_success_data(api.get_property(prop["id"], ah))
    assert after["zone_count"] == 2
    assert after["total_treatable_sqft"] == 6000


def test_excluded_zone_drops_out_of_total_treatable_sqft(api):
    """
    PRD 2.5: "excluding a zone leaves `zone_count` unchanged (an excluded zone is still counted) but drops that zone's area out of `total_treatable_sqft`."

    Design: Corner/entities/excluded_zone_drops_out_of_total_treatable_sqft
    """
    holder = create_account_holder()
    prop = create_property(holder["id"], service_region_code="NE01")
    ah = make_account_holder_headers(holder["id"])
    add_zone(prop, holder["id"], label="Turf", zone_type="TURF", area_sqft=4000)
    perim = add_zone(prop, holder["id"], label="Perim", zone_type="PERIMETER", area_sqft=2000)
    excluded = validate_success(api.exclude_zone(perim["id"], ah))
    assert excluded["status"] == "EXCLUDED"
    after = get_success_data(api.get_property(prop["id"], ah))
    assert after["zone_count"] == 2
    assert after["total_treatable_sqft"] == 4000


def test_application_log_is_append_only_no_version_field(api):
    """
    PRD 3.4: "Application logs are append-only event records: each carries its own `id` and `created_at` and nothing more."

    Design: Corner/entities/application_log_immutable_no_version_field
    """
    ctx = create_active_subscription(region="NE01")
    crew = create_crew(home_region_code="NE01")
    rec = list_recurring_visits(ctx["sub"]["id"])[0]
    route = create_route(crew["id"], region="NE01", route_date=rec["scheduled_date"])
    dispatch_visit(route["id"], rec["id"], route["version"])
    log = validate_success(api.add_application_log(rec["id"],
        {"treatment_zone_id": ctx["zones"][0]["id"], "product_code": "BIFEN_IT", "gallons_applied": 2.0, "logged_by_tech_id": crew["id"]},
        make_crew_tech_headers(crew["id"])), expected_status=201)
    assert "id" in log and "created_at" in log
    assert "version" not in log, "ApplicationLog is append-only; no version"
    assert "updated_at" not in log, "ApplicationLog is append-only; no updated_at"
    _, meta = validate_paginated(api.list_application_logs(rec["id"], make_crew_tech_headers(crew["id"])))
    assert meta["total_count"] == 1


def test_dispatcher_cannot_pay_invoice_forbidden_role(api):
    """
    PRD 2.1: "When the headers are well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/dispatcher_cannot_pay_invoice_forbidden_role
    """
    ctx = setup_completed_per_visit_with_invoice(
        zones=[{"label": "Turf", "zone_type": "TURF", "area_sqft": 4000},
               {"label": "Perim", "zone_type": "PERIMETER", "area_sqft": 2000}],
        lot_size_sqft=8000)
    inv = ctx["invoice"]
    validate_error(api.pay_invoice(inv["id"], {"paid_amount_cents": inv["amount_cents"]}, DISPATCHER), ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_account_holder_cannot_act_on_other_holders_subscription(api):
    """
    PRD 2.1: "An account holder who targets a property, subscription, visit, or invoice that does not roll up to their own `X-User-ID` is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/account_holder_cannot_act_on_other_holders_property
    """
    plan = create_service_plan()
    holder_a = create_account_holder()
    holder_b = create_account_holder()
    prop = create_property(holder_a["id"], service_region_code="NE01")
    add_zone(prop, holder_a["id"], zone_type="TURF", area_sqft=4000)
    sub = create_subscription(prop["id"], plan["id"], holder_a["id"], billing_mode="PER_VISIT")
    validate_error(api.activate_subscription(sub["id"], make_account_holder_headers(holder_b["id"])), ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_unauthenticated_request_missing_headers(api):
    """
    PRD 2.1: "When either header is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_request_missing_headers
    """
    validate_error(api.create_property(
        {"account_holder_id": "00000000-0000-4000-8000-000000000099", "street_address": "X", "lot_size_sqft": 6000, "service_region_code": "NE01"},
        {}), ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_list_subscription_visits_pagination_envelope(api):
    """
    PRD 2.3: "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_subscription_visits_pagination_envelope
    """
    ctx = create_active_subscription(region="NE01", season_start="2026-05-01", season_end="2026-08-31")
    ah = make_account_holder_headers(ctx["holder"]["id"])
    data, meta = validate_paginated(api.list_subscription_visits(ctx["sub"]["id"], ah, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 6
    assert meta["has_more"] is False
    assert len(data) == 6
