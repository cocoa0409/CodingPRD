"""Entity creation & system fields, RBAC (auth/authz/ownership), listing & pagination,
and cross-cutting version/OCC behavior."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    RetailerStatus, WorkOrderStatus, TEST_USERS,
    make_retailer_headers, make_pro_headers, make_customer_headers,
    setup_catalog, setup_scheduled_order, setup_completed_order,
    new_retailer, new_zone, new_customer, new_task, new_pro, new_approved_pro,
    new_draft_work_order,
    create_retailer_payload, create_install_task_payload, create_work_order_payload,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/create_retailer_returns_201_with_all_fields
# ---------------------------------------------------------------------------
def test_create_retailer_returns_201_with_all_fields(api):
    """PRD §3.1: "A retailer begins life with `status` `ACTIVE` and a `settlement_balance_cents` of
    0; an admin can later toggle `status` between `ACTIVE` and `SUSPENDED`."

    Design: Corner/entities/create_retailer_returns_201_with_all_fields
    """
    data = validate_success(
        api.create_retailer(create_retailer_payload(name="Costco", commission_rate_bps=1500), ADMIN), 201)
    assert data["status"] == RetailerStatus.ACTIVE.value
    assert data["settlement_balance_cents"] == 0
    assert data["commission_rate_bps"] == 1500


# ---------------------------------------------------------------------------
# Corner/entities/get_service_zone_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_service_zone_not_found_returns_404(api):
    """PRD §2.8: "if any referenced resource does not exist the request fails with the
    corresponding `ERR_<RESOURCE>_NOT_FOUND` code (HTTP 404) — `ERR_RETAILER_NOT_FOUND`,
    `ERR_SERVICE_ZONE_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`"

    Design: Corner/entities/get_service_zone_not_found_returns_404
    """
    validate_error(api.get_service_zone(NON_EXISTENT_UUID, ADMIN),
                   ApiErrorId.ERR_SERVICE_ZONE_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/entities/create_work_order_missing_customer_id_returns_400
# ---------------------------------------------------------------------------
def test_create_work_order_missing_customer_id_returns_400(api):
    """PRD §2.9: "then body well-formedness (`ERR_VALIDATION`: required fields present, enum values
    valid, `stars` within 1 to 5, monetary fields integral)."

    Design: Corner/entities/create_work_order_missing_customer_id_returns_400
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    payload = {
        "retailer_id": ret_id, "install_task_id": ctx["task"]["id"],
        "service_zone_id": ctx["zone"]["id"], "product_sku": "S", "product_category": "TV_MOUNT",
    }  # customer_id intentionally omitted
    validate_error(api.create_work_order(payload, make_retailer_headers(ret_id)),
                   ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Corner/entities/create_install_task_invalid_category_returns_400
# ---------------------------------------------------------------------------
def test_create_install_task_invalid_category_returns_400(api):
    """PRD §3.1: "a `category` (one of `TV_MOUNT`, `APPLIANCE`, or `SMART_DEVICE`)"
    PRD §2.9: "then body well-formedness (`ERR_VALIDATION`: required fields present, enum values
    valid, `stars` within 1 to 5, monetary fields integral)."

    Design: Corner/entities/create_install_task_invalid_category_returns_400
    """
    payload = create_install_task_payload(category="FRIDGE", required_skill="APPLIANCE")
    validate_error(api.create_install_task(payload, ADMIN), ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Corner/entities/system_fields_minted_on_pro_create
# ---------------------------------------------------------------------------
def test_system_fields_minted_on_pro_create(api):
    """PRD §2.4: "an integer `version` that starts at 1 on creation and increments by 1 on every
    mutation to that resource."
    PRD §3.1: "All of a pro's derived counters start at 0: `pending_payout_cents`,
    `reserved_slot_count`, `rating_sum`, `rating_count`, and `rating_avg`."

    Design: Corner/entities/system_fields_minted_on_pro_create
    """
    zone = new_zone(api)
    pro = new_pro(api, zone["id"], skills=["TV_MOUNT"])
    assert pro["version"] == 1
    assert pro["reserved_slot_count"] == 0
    assert pro["pending_payout_cents"] == 0
    assert pro["rating_count"] == 0


# ---------------------------------------------------------------------------
# Corner/entities/rating_entity_has_no_version_field
# ---------------------------------------------------------------------------
def test_rating_entity_has_no_version_field(api):
    """PRD §2.4: "The `Rating` resource is the sole exception: a rating is immutable once written,
    so it carries only `id` and `created_at` — it has neither an `updated_at` field nor a `version`
    field."

    Design: Corner/entities/rating_entity_has_no_version_field
    """
    ctx = setup_completed_order(api, scheduled_start="2026-03-05T09:00:00Z",
                                scheduled_end="2026-03-05T10:00:00Z", clock="2026-03-05T10:00:00Z")
    rating = validate_success(
        api.create_rating(ctx["wo"]["id"], {"stars": 5, "comment": "great"},
                          make_customer_headers(ctx["customer"]["id"])), 201)
    assert "version" not in rating, "Rating must carry no version field"
    assert "updated_at" not in rating, "Rating must carry no updated_at field"
    assert rating["pro_id"] == ctx["pro"]["id"]


# ---------------------------------------------------------------------------
# Corner/entities/create_work_order_unknown_retailer_returns_404
# ---------------------------------------------------------------------------
def test_create_work_order_unknown_retailer_returns_404(api):
    """PRD §2.8: "if any referenced resource does not exist the request fails with the
    corresponding `ERR_<RESOURCE>_NOT_FOUND` code (HTTP 404) — `ERR_RETAILER_NOT_FOUND`"

    Design: Corner/entities/create_work_order_unknown_retailer_returns_404
    """
    zone = new_zone(api)
    customer = new_customer(api)
    task = new_task(api)
    payload = create_work_order_payload(
        retailer_id=NON_EXISTENT_UUID, customer_id=customer["id"], install_task_id=task["id"],
        service_zone_id=zone["id"], product_category="TV_MOUNT")
    # Caller's own X-User-ID equals the (bogus) retailer_id, so ownership passes and existence fails.
    validate_error(api.create_work_order(payload, make_retailer_headers(NON_EXISTENT_UUID)),
                   ApiErrorId.ERR_RETAILER_NOT_FOUND)


# ---------------------------------------------------------------------------
# Corner/rbac/missing_auth_headers_returns_401
# ---------------------------------------------------------------------------
def test_missing_auth_headers_returns_401(api):
    """PRD §2.1: "If either header is missing, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) before any other processing."

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    validate_error(api.create_retailer(create_retailer_payload(), {}),
                   ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# Corner/rbac/retailer_cannot_dispatch_returns_403
# ---------------------------------------------------------------------------
def test_retailer_cannot_dispatch_returns_403(api):
    """PRD §2.1: "If both headers are present but the role is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/retailer_cannot_dispatch_returns_403
    """
    ctx = setup_scheduled_order(api)
    ret_id = ctx["retailer"]["id"]
    validate_error(
        api.dispatch_work_order(ctx["wo"]["id"], {"expected_work_order_version": ctx["version"]},
                                make_retailer_headers(ret_id)),
        ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner/rbac/pro_cannot_create_work_order_returns_403
# ---------------------------------------------------------------------------
def test_pro_cannot_create_work_order_returns_403(api):
    """PRD §2.1: "If both headers are present but the role is not permitted to perform the requested
    operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/pro_cannot_create_work_order_returns_403
    """
    ctx = setup_catalog(api)
    pro = new_pro(api, ctx["zone"]["id"], skills=["TV_MOUNT"])
    payload = create_work_order_payload(
        retailer_id=ctx["retailer"]["id"], customer_id=ctx["customer"]["id"],
        install_task_id=ctx["task"]["id"], service_zone_id=ctx["zone"]["id"],
        product_category="TV_MOUNT")
    validate_error(api.create_work_order(payload, make_pro_headers(pro["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner/rbac/retailer_cannot_schedule_other_retailers_order_returns_403
# ---------------------------------------------------------------------------
def test_retailer_cannot_schedule_other_retailers_order_returns_403(api):
    """PRD §2.1: "The same `ERR_UNAUTHORIZED` code is returned when a caller is permitted by role
    but does not own the specific resource being acted upon."

    Design: Corner/rbac/retailer_cannot_schedule_other_retailers_order_returns_403
    """
    ret_a = new_retailer(api, name="A")
    ret_b = new_retailer(api, name="B")
    zone = new_zone(api)
    customer = new_customer(api)
    task = new_task(api)
    wo = new_draft_work_order(api, ret_a["id"], customer["id"], task["id"], zone["id"])
    resp = api.schedule_work_order(
        wo["id"], {"scheduled_start": "2026-03-05T09:00:00Z", "scheduled_end": "2026-03-05T10:00:00Z"},
        make_retailer_headers(ret_b["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


# ---------------------------------------------------------------------------
# Corner/endpoints/list_work_orders_by_retailer_paginates
# ---------------------------------------------------------------------------
def test_list_work_orders_by_retailer_paginates(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count` (the total number
    of matching rows before the page window is applied), and `has_more` (a boolean that is true when
    rows remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_work_orders_by_retailer_paginates
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    for sku in ("S1", "S2"):
        new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"],
                             ctx["zone"]["id"], product_sku=sku)
    data, meta = validate_paginated(
        api.list_work_orders(ADMIN, params={"retailer_id": ret_id, "limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ---------------------------------------------------------------------------
# Corner/endpoints/list_pros_filtered_by_zone_returns_both
# ---------------------------------------------------------------------------
def test_list_pros_filtered_by_zone_returns_both(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count` (the total number
    of matching rows before the page window is applied), and `has_more` (a boolean that is true when
    rows remain beyond the current page) inside the `meta` object."

    Design: Corner/endpoints/list_pros_filtered_by_zone_returns_both
    """
    zone = new_zone(api)
    new_pro(api, zone["id"], skills=["TV_MOUNT"], full_name="P1", email="p1@x.com")
    new_pro(api, zone["id"], skills=["APPLIANCE"], full_name="P2", email="p2@x.com")
    data, meta = validate_paginated(api.list_pros(ADMIN, params={"service_zone_id": zone["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# Corner/cross_cutting/occ_stale_version_on_dispatch_returns_412
# ---------------------------------------------------------------------------
def test_occ_stale_version_on_dispatch_returns_412(api):
    """PRD §2.6: "The server compares `expected_work_order_version` against the work order's current
    `version`. If they do not match, the dispatch is rejected with `ERR_STALE_VERSION` (HTTP 412)
    and nothing is mutated."

    Design: Corner/cross_cutting/occ_stale_version_on_dispatch_returns_412
    """
    ctx = setup_scheduled_order(api)
    new_approved_pro(api, ctx["zone"]["id"])  # an eligible pro exists; only the version is stale
    stale = ctx["version"] - 1
    validate_error(
        api.dispatch_work_order(ctx["wo"]["id"], {"expected_work_order_version": stale}, ADMIN),
        ApiErrorId.ERR_STALE_VERSION)


# ---------------------------------------------------------------------------
# Corner/cross_cutting/work_order_version_increments_on_schedule
# ---------------------------------------------------------------------------
def test_work_order_version_increments_on_schedule(api):
    """PRD §2.4: "an integer `version` that starts at 1 on creation and increments by 1 on every
    mutation to that resource."

    Design: Corner/cross_cutting/work_order_version_increments_on_schedule
    """
    ctx = setup_scheduled_order(api)
    # create -> version 1, schedule -> version 2.
    assert ctx["wo"]["version"] == 2, f"expected version 2 after schedule, got {ctx['wo']['version']}"
