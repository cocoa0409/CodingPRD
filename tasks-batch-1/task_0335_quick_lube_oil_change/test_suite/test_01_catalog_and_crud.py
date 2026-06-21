"""Catalog CRUD, computed-field defaults, type/uniqueness constraints, coupon eligibility,
listing/pagination, reverse-lookup, not-found errors, and RBAC.

Sources: corner sections entities, validations, endpoints, errors, rbac; difficulty rule
boundary_precision_check (coupon min-subtotal inclusive boundary).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    TEST_USERS,
    build_user_headers,
    make_fleet_manager_headers,
    assert_shop,
    assert_vehicle,
    assert_service_sticker,
    # fixtures
    set_clock,
    create_shop,
    create_package,
    create_bay,
    create_coupon,
    create_fleet_account,
    create_fleet_vehicle,
    create_retail_vehicle,
    create_direct_work_order,
    setup_shop_with_catalog,
    drive_to_completed,
    drive_to_paid,
    claim_start,
    mark_ready,
    authorize,
    capture,
)

SA = TEST_USERS["service_advisor_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── corner: entities ──────────────────────────────────

def test_create_shop_returns_201_with_defaults(api):
    """PRD §3.1: "A new shop opens with `status` `OPEN` and an `open_bay_count` of zero,
    since no bays exist yet."
    PRD §3.1: "The manager may also supply `max_discount_pct`, the hard ceiling on the
    combined coupon-and-fleet discount as a fraction of the subtotal; it must be greater
    than zero and at most one, and when omitted it defaults to one half."

    Design: Corner/entities/create_shop_returns_201_with_defaults
    """
    set_clock()
    res = api.create_shop(
        {"name": "Main", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, SM)
    shop = validate_success(res, 201)
    assert_shop(shop)
    assert shop["status"] == "OPEN"
    assert shop["open_bay_count"] == 0
    assert shop["max_discount_pct"] == 0.50
    assert shop["version"] == 1


def test_create_work_order_missing_package_id_rejected(api):
    """PRD §2.6: "Body-shape problems — a missing required field, a wrong type, an
    unrecognized enum value, or a negative amount where a non-negative one is required —
    are reported as `ERR_VALIDATION` (HTTP 400)."
    PRD §3.4: "Direct creation supplies `shop_id`, `vehicle_id`, `bay_id`, `package_id`,
    the `odometer_in` reading taken at check-in (at least zero), and optionally a
    `coupon_code`."

    Design: Corner/entities/create_work_order_missing_required_field_rejected
    """
    shop = create_shop()
    bay = create_bay(shop["id"])
    veh = create_retail_vehicle(shop["id"], vin="VINREQ001", plate="REQ1",
                                make="Honda", model="Fit", odometer=1000)
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"], "bay_id": bay["id"],
         "odometer_in": 1000}, SA)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_get_nonexistent_work_order_returns_not_found(api):
    """PRD §2.5: "This existence pass is the third priority check on any path-parameterized
    request, evaluated only after authentication and role authorization succeed."
    PRD §2.5: "The catalog of not-found codes is resource-specific: `ERR_SHOP_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_INSPECTION_ITEM_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`,
    `ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, and `ERR_STICKER_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/get_work_order_non_existent_returns_not_found
    """
    create_shop()
    res = api.get_work_order("00000000-0000-4000-8000-000000000000", SA)
    validate_error(res, "ERR_WORK_ORDER_NOT_FOUND", expected_status=404)


def test_fresh_vehicle_service_due_false_no_history(api):
    """PRD §3.2: "A freshly registered vehicle has no service history: `last_service_odometer`,
    `last_service_date`, `next_service_odometer`, and `next_service_date` are all null, and
    `service_due` is false."

    Design: Corner/entities/vehicle_computed_service_due_false_without_history
    """
    shop = create_shop()
    veh = create_retail_vehicle(shop["id"], vin="VINNEW001", plate="NEW1",
                                make="Honda", model="Fit", odometer=1000)
    fetched = get_success_data(api.get_vehicle(veh["id"], SA))
    assert_vehicle(fetched)
    assert fetched["service_due"] is False
    assert fetched["next_service_odometer"] is None
    assert fetched["last_service_date"] is None


def test_duplicate_vin_rejected(api):
    """PRD §3.2: "A duplicate VIN within the same shop is rejected with `ERR_DUPLICATE_VIN`
    (HTTP 409)."

    Design: Corner/entities/duplicate_vin_rejected
    """
    shop = create_shop()
    create_retail_vehicle(shop["id"], vin="VINDUP001", plate="DUP1",
                          make="Honda", model="Fit", odometer=1000)
    res = api.create_vehicle(
        {"shop_id": shop["id"], "vin": "VINDUP001", "plate": "DUP2",
         "make": "Honda", "model": "Jazz", "odometer": 2000}, SA)
    validate_error(res, "ERR_DUPLICATE_VIN", expected_status=409)


def test_service_package_invalid_oil_grade_rejected(api):
    """PRD §3.1: "an `oil_grade` of `CONVENTIONAL`, `SYNTHETIC_BLEND`, `FULL_SYNTHETIC`, or
    `HIGH_MILEAGE`".
    PRD §2.6: "Body-shape problems — a missing required field, a wrong type, an unrecognized
    enum value, or a negative amount where a non-negative one is required — are reported as
    `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/service_package_invalid_enum_oil_grade_rejected
    """
    shop = create_shop()
    res = api.create_service_package(
        {"shop_id": shop["id"], "oil_grade": "BIODIESEL", "name": "Bad",
         "base_price_cents": 5000, "included_quarts": 5, "labor_minutes": 20,
         "interval_miles": 5000, "interval_days": 180}, SM)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_service_sticker_immutable_no_version(api):
    """PRD §2.4: "A `ServiceSticker` is an immutable printed record: it carries only `id`
    and `created_at`, and has neither `updated_at` nor `version`."
    PRD §3.10: "The sticker's `next_service_odometer` is that service odometer plus the
    package's `interval_miles`."

    Design: Corner/entities/service_sticker_immutable_no_version_field
    """
    base = setup_shop_with_catalog(clock="2026-06-14T09:00:00Z")
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINSTK002", plate="STK2",
                                make="Honda", model="Fit", odometer=30000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 30000)
    drive_to_completed(wo["id"], tech["id"], payment_method="CASH")
    stickers = validate_success(api.get_sticker(wo["id"], SA))
    assert len(stickers) == 1
    sticker = stickers[0]
    assert_service_sticker(sticker)  # asserts no version / no updated_at
    assert sticker["next_service_odometer"] == 35000
    assert sticker["basis"] == "MILEAGE"


# ─── corner: validations (coupon eligibility) ──────────

def test_apply_exhausted_coupon_rejected(api):
    """PRD §3.5: "its `status` must be `ACTIVE`, or the request is rejected with
    `ERR_COUPON_EXPIRED` (which also covers an exhausted coupon)".
    PRD §3.8 (capture): "If the order carried a coupon, that coupon's `redeemed_count` is
    recomputed, and if the recomputed count reaches or exceeds the coupon's `usage_limit`
    the coupon's `status` moves to `EXHAUSTED`."

    Design: Corner/validations/coupon_usage_exceeded_rejected
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    create_coupon(shop["id"], code="ONESHOT", discount_type="FLAT", flat_cents=500,
                  min_subtotal_cents=0, usage_limit=1)
    veh_a = create_retail_vehicle(shop["id"], vin="VINCUE001", plate="CUE1",
                                  make="Honda", model="Fit", odometer=1000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINCUE002", plate="CUE2",
                                  make="Honda", model="Jazz", odometer=2000)
    # First order redeems the coupon (capture -> redeemed_count 1 -> EXHAUSTED).
    wo_a = create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 1000,
                                    coupon_code="ONESHOT")
    drive_to_paid(wo_a["id"], tech["id"], payment_method="CASH")
    # Second order tries to apply the now-exhausted coupon.
    wo_b = create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 2000)
    res = api.apply_coupon(wo_b["id"], {"coupon_code": "ONESHOT"}, SA)
    validate_error(res, "ERR_COUPON_EXPIRED", expected_status=409)


def test_apply_coupon_below_min_subtotal_rejected(api):
    """PRD §3.5: "the order's `subtotal_cents` must be at least the coupon's
    `min_subtotal_cents`, or the request is rejected with `ERR_COUPON_MIN_SUBTOTAL_NOT_MET`."

    Design: Corner/validations/coupon_min_subtotal_not_met_rejected
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    create_coupon(shop["id"], code="BIGMIN", discount_type="FLAT", flat_cents=1000,
                  min_subtotal_cents=10000, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINCMS001", plate="CMS1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    assert wo["subtotal_cents"] == 6995  # below the 10000 minimum
    res = api.apply_coupon(wo["id"], {"coupon_code": "BIGMIN"}, SA)
    validate_error(res, "ERR_COUPON_MIN_SUBTOTAL_NOT_MET", expected_status=409)


# ─── difficulty: boundary_precision_check / coupon min-subtotal inclusive ──

def test_coupon_min_subtotal_inclusive_boundary_applies(api):
    """PRD §3.1: "An optional `min_subtotal_cents` (default zero) sets the minimum
    work-order subtotal at which the coupon becomes eligible, applied as an at-least
    threshold."
    PRD §3.5: "the order's `subtotal_cents` must be at least the coupon's
    `min_subtotal_cents`, or the request is rejected with `ERR_COUPON_MIN_SUBTOTAL_NOT_MET`."

    Design: Difficulty/boundary_precision_check/coupon_min_subtotal_inclusive_boundary
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    create_coupon(shop["id"], code="BORDER", discount_type="FLAT", flat_cents=500,
                  min_subtotal_cents=6995, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINBND001", plate="BND1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    assert wo["subtotal_cents"] == 6995  # exactly equals the min -> the at-least passes
    applied = validate_success(api.apply_coupon(wo["id"], {"coupon_code": "BORDER"}, SA), 200)
    assert applied["total_discount_cents"] == 500  # FLAT applied


def test_coupon_min_subtotal_one_below_boundary_rejected(api):
    """PRD §3.1: "An optional `min_subtotal_cents` (default zero) sets the minimum
    work-order subtotal at which the coupon becomes eligible, applied as an at-least
    threshold."
    PRD §3.5: "the order's `subtotal_cents` must be at least the coupon's
    `min_subtotal_cents`, or the request is rejected with `ERR_COUPON_MIN_SUBTOTAL_NOT_MET`."

    Design: Difficulty/boundary_precision_check/coupon_min_subtotal_inclusive_boundary
    """
    base = setup_shop_with_catalog(package_overrides={"base_price_cents": 6994})
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    # min_subtotal 6995 with a 6994 package: subtotal 6994 is one below the inclusive bound.
    create_coupon(shop["id"], code="BORDER", discount_type="FLAT", flat_cents=500,
                  min_subtotal_cents=6995, usage_limit=5)
    veh = create_retail_vehicle(shop["id"], vin="VINBND002", plate="BND2",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    assert wo["subtotal_cents"] == 6994  # one below the 6995 minimum
    res = api.apply_coupon(wo["id"], {"coupon_code": "BORDER"}, SA)
    validate_error(res, "ERR_COUPON_MIN_SUBTOTAL_NOT_MET", expected_status=409)


# ─── corner: endpoints (listing + reverse lookup) ──────

def test_list_work_orders_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_work_orders_pagination_envelope
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay = base["shop"], base["package"], base["bay"]
    bay_b = get_success_data(api.create_bay({"shop_id": shop["id"], "label": "Bay 2"}, SM))
    veh_a = create_retail_vehicle(shop["id"], vin="VINPAG001", plate="PAG1",
                                  make="Honda", model="Fit", odometer=1000)
    veh_b = create_retail_vehicle(shop["id"], vin="VINPAG002", plate="PAG2",
                                  make="Honda", model="Jazz", odometer=2000)
    create_direct_work_order(shop["id"], veh_a["id"], bay["id"], pkg["id"], 1000)
    create_direct_work_order(shop["id"], veh_b["id"], bay_b["id"], pkg["id"], 2000)
    res = api.list_work_orders(SA, params={"shop_id": shop["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_fleet_account_vehicles_reverse_lookup(api):
    """PRD §3.12: "Several reverse-lookup reads walk a foreign key backward: a fleet
    account's vehicles, a vehicle's work orders, a work order's lines, a work order's
    payments, and a work order's sticker."

    Design: Corner/endpoints/filter_vehicles_by_fleet_account_reverse_reachability
    """
    shop = create_shop()
    fleet = create_fleet_account(shop["id"], company_name="Acme", discount_pct=0.10,
                                 credit_limit_cents=100000)
    create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLT001", plate="FLT1",
                         make="Ford", model="F150", odometer=1000)
    create_fleet_vehicle(shop["id"], fleet["id"], vin="VINFLT002", plate="FLT2",
                         make="Ford", model="F250", odometer=2000)
    create_retail_vehicle(shop["id"], vin="VINRTL001", plate="RTL1",
                          make="Honda", model="Fit", odometer=3000)
    fm = make_fleet_manager_headers(fleet["id"])
    data, _ = validate_paginated(api.list_fleet_account_vehicles(fleet["id"], fm))
    assert len(data) == 2
    assert all(v["fleet_account_id"] == fleet["id"] for v in data)


# ─── corner: errors (referential not-found) ────────────

def test_create_work_order_unknown_bay_returns_bay_not_found(api):
    """PRD §2.5: "The catalog of not-found codes is resource-specific: `ERR_SHOP_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_INSPECTION_ITEM_NOT_FOUND`, `ERR_COUPON_NOT_FOUND`,
    `ERR_FLEET_ACCOUNT_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_BAY_NOT_FOUND`,
    `ERR_TECHNICIAN_NOT_FOUND`, `ERR_QUEUE_TICKET_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`,
    `ERR_LINE_NOT_FOUND`, and `ERR_STICKER_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/errors/bay_not_found_on_create_work_order
    """
    shop = create_shop()
    pkg = create_package(shop["id"])
    veh = create_retail_vehicle(shop["id"], vin="VINBNF001", plate="BNF1",
                                make="Honda", model="Fit", odometer=1000)
    res = api.create_work_order(
        {"shop_id": shop["id"], "vehicle_id": veh["id"],
         "bay_id": "11111111-1111-4111-8111-111111111111",
         "package_id": pkg["id"], "odometer_in": 1000}, SA)
    validate_error(res, "ERR_BAY_NOT_FOUND", expected_status=404)


def test_add_line_unknown_inspection_item_returns_not_found(api):
    """PRD §3.7: "The referenced inspection item must exist, or the request is rejected with
    `ERR_INSPECTION_ITEM_NOT_FOUND`."

    Design: Corner/errors/inspection_item_not_found_on_add_line
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINIIF001", plate="IIF1",
                                make="Honda", model="Fit", odometer=1000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 1000)
    claim_start(wo["id"], tech["id"])
    in_insp = get_success_data(api.begin_inspection(
        wo["id"], build_user_headers(tech["id"], "Technician")))
    res = api.add_line(
        wo["id"],
        {"inspection_item_id": "22222222-2222-4222-8222-222222222222",
         "expected_work_order_version": in_insp["version"]},
        build_user_headers(tech["id"], "Technician"))
    validate_error(res, "ERR_INSPECTION_ITEM_NOT_FOUND", expected_status=404)


# ─── corner: rbac ──────────────────────────────────────

def test_technician_cannot_create_shop(api):
    """PRD §2.1: "A request whose role is not permitted to perform the requested operation
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 (endpoint table): `POST /shops` authorized role is `ShopManager`.

    Design: Corner/rbac/technician_cannot_create_shop
    """
    set_clock()
    headers = build_user_headers("00000000-0000-4000-8000-000000000abc", "Technician")
    res = api.create_shop(
        {"name": "Hijack", "tax_rate": 0.0825, "target_throughput_seconds": 1800}, headers)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_technician_cannot_authorize_payment(api):
    """PRD §2.1: "A request whose role is not permitted to perform the requested operation
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4 (endpoint table): `POST /work-orders/{id}/authorize` authorized role is
    `ServiceAdvisor`.

    Design: Corner/rbac/technician_cannot_authorize_payment
    """
    base = setup_shop_with_catalog()
    shop, pkg, bay, tech = base["shop"], base["package"], base["bay"], base["technician"]
    veh = create_retail_vehicle(shop["id"], vin="VINRBC001", plate="RBC1",
                                make="Honda", model="Fit", odometer=5000)
    wo = create_direct_work_order(shop["id"], veh["id"], bay["id"], pkg["id"], 5000)
    claim_start(wo["id"], tech["id"])
    mark_ready(wo["id"], tech["id"])
    res = api.authorize_payment(
        wo["id"], {"payment_method": "CASH"}, build_user_headers(tech["id"], "Technician"))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_missing_auth_header_rejected(api):
    """PRD §2.1: "A request missing or malformed in either header is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_rejected
    """
    res = api.list_shops({})
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
