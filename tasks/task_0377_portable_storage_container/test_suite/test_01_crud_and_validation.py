"""CRUD, defaults, immutability, and schema-validation tests (PRD §2.4, §2.10, §3.1, §3.2)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_rental_agreement_payload, create_container_model_payload,
    create_protection_plan_payload, create_depot_payload,
    create_depot_inventory_payload, create_delivery_job_payload,
    reserve_payload,
    assert_rental_agreement, assert_protection_plan, assert_depot_inventory,
    TEST_USERS, make_customer_headers,
)
from test_helpers import fixtures as F

PA = TEST_USERS["platform_admin_headers"]
DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]


def test_create_rental_agreement_applies_defaults(api):
    """PRD §3.2: "A new agreement begins with `lifecycle_status` of `QUOTED` and
    `billing_status` of `CURRENT`". PRD §3.2: "an optional `protection_tier_code`
    (defaulting to `NONE`), an optional `declared_value_cents` for the stored contents
    (defaulting to 0), an optional `proration_method` (one of `CALENDAR_DAY` or `FIXED_30`,
    defaulting to `CALENDAR_DAY`)".

    Design: Corner/entities/create_rental_agreement_returns_201_with_defaults
    """
    F.set_clock()
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="crt@x.com")

    payload = create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16")
    # Omit the optional fields so server defaults are exercised.
    for opt in ("protection_tier_code", "declared_value_cents", "proration_method"):
        payload.pop(opt, None)

    res = api.create_rental_agreement(payload, DO)
    ag = validate_success(res, 201)
    assert_rental_agreement(ag)
    assert ag["lifecycle_status"] == "QUOTED"
    assert ag["billing_status"] == "CURRENT"
    assert ag["protection_tier_code"] == "NONE"
    assert ag["declared_value_cents"] == 0
    assert ag["proration_method"] == "CALENDAR_DAY"


def test_get_rental_agreement_not_found(api):
    """PRD §2.10: "every resource referenced in the path and in the body's foreign keys
    is resolved left-to-right ... and the first reference that does not resolve yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_rental_agreement_not_found_returns_404
    """
    res = api.get_rental_agreement(NON_EXISTENT_UUID, BC)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_rental_agreement_missing_site_address(api):
    """PRD §2.10: "Schema validity is fourth: required fields present, enum values in
    their allowed sets, integers non-negative, window ordering correct, and supply lines
    non-empty, otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_rental_agreement_missing_site_address_returns_invalid_request
    """
    F.create_container_model(size_code="C16")
    depot = F.create_depot()
    F.create_depot_inventory(depot["id"], size_code="C16", total_units=1)
    cust = F.create_customer(email="mr@x.com")

    payload = create_rental_agreement_payload(cust["id"], depot["id"], size_code="C16")
    del payload["site_address"]
    res = api.create_rental_agreement(payload, DO)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_rental_agreement_bad_size_enum(api):
    """PRD §2.10: "Schema validity is fourth: required fields present, enum values in
    their allowed sets, integers non-negative, window ordering correct, and supply lines
    non-empty, otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_rental_agreement_bad_size_enum_returns_invalid_request
    """
    depot = F.create_depot()
    cust = F.create_customer(email="be@x.com")
    payload = create_rental_agreement_payload(cust["id"], depot["id"], size_code="C99")
    res = api.create_rental_agreement(payload, DO)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_protection_plan_immutable_no_version_field(api):
    """PRD §2.4: "The following entities are immutable after creation and therefore carry
    only `id` and `created_at`, with no `updated_at` and no `version`: the `ContainerModel`
    catalog entries and the `ProtectionPlan` tiers."

    Design: Corner/entities/protection_plan_immutable_no_version_field
    """
    res = api.create_protection_plan(create_protection_plan_payload(
        tier_code="BASIC", base_premium_cents=1000, rate_bps=50,
        min_premium_cents=1500, coverage_cap_cents=5000000), PA)
    plan = validate_success(res, 201)
    get_res = api.get_protection_plan(plan["id"], TEST_USERS["customer_headers"])
    fetched = validate_success(get_res, 200)
    assert_protection_plan(fetched)
    assert fetched["tier_code"] == "BASIC"
    assert "version" not in fetched
    assert "updated_at" not in fetched


def test_depot_inventory_computed_fields_initialized(api):
    """PRD §3.1: "on creation the row's `reserved_units` and `committed_units` both start
    at 0 and `available_units` starts equal to `total_units`."

    Design: Corner/entities/depot_inventory_computed_fields_initialized
    """
    depot = F.create_depot()
    res = api.create_depot_inventory(
        create_depot_inventory_payload(depot["id"], size_code="C12", total_units=3), PA)
    inv = validate_success(res, 201)
    assert_depot_inventory(inv)
    assert inv["available_units"] == 3
    assert inv["reserved_units"] == 0
    assert inv["committed_units"] == 0


def test_list_container_models_pagination_envelope(api):
    """PRD §2.3: "Each list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope, where `total_count` is the number of
    matching resources before pagination is applied and `has_more` is true when more items
    remain beyond the current page."

    Design: Corner/endpoints/list_container_models_pagination_envelope
    """
    api.create_container_model(create_container_model_payload(
        size_code="C8", cubic_feet=400, monthly_rate_cents=6000,
        delivery_fee_cents=0, footprint_sqft=80), PA)
    api.create_container_model(create_container_model_payload(size_code="C16"), PA)

    data, meta = validate_paginated(api.list_container_models(PA, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_create_delivery_job_window_end_before_start(api):
    """PRD §2.10: "Schema validity is fourth: required fields present, enum values in
    their allowed sets, integers non-negative, window ordering correct, and supply lines
    non-empty, otherwise `ERR_INVALID_REQUEST`." PRD §2.8: "`window_end` must be strictly
    after `window_start`."

    Design: Corner/errors/error_invalid_request_window_end_before_start_on_delivery
    """
    world = F.seed_world(size_code="C16", with_crew=True)
    ag, unit = F.create_quoted_then_reserved(world)
    res = api.create_delivery_job(
        create_delivery_job_payload(
            ag["id"], world["crew"]["id"], unit["id"],
            window_start="2026-07-16T11:00:00Z", window_end="2026-07-16T09:00:00Z"),
        DO)
    validate_error(res, "ERR_INVALID_REQUEST")
