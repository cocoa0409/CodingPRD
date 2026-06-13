"""Entity CRUD, input validation, RBAC, OCC, and listing/pagination tests
(PRD §2.1, §2.3, §2.8, §3.1, §3.3, §3.7, §3.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    setup_scheduled_visit_planned_route, setup_work_order_awaiting_approval,
    setup_completed_visit, setup_resolved_work_order,
    create_customer, create_pool,
    create_customer_payload, create_pool_payload, create_service_plan_payload,
    create_invoice_payload, skip_payload, visit_log_payload,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS, build_user_headers,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


# --------------------------------------------------------------------------
# Entity creation / not-found / required-field / enum
# --------------------------------------------------------------------------
def test_create_pool_returns_201_with_defaults(api):
    """PRD §3.1: "Every newly registered pool begins `CLOSED`, recorded in its
    `service_status`".
    PRD §2.4: "a `version`, an integer that begins at 1 and increments by exactly 1
    on every mutation of that resource."
    PRD §3.1: "The `balance_due_cents` is the sum of `amount_cents` over this pool's
    invoices whose status is `ISSUED`".

    Design: Corner/entities/create_pool_returns_201_with_defaults
    """
    customer = create_customer()
    resp = api.create_pool(create_pool_payload(customer["id"], water_type="CHLORINE", volume_gallons=20000), AM)
    data = validate_success(resp, 201)
    assert data["service_status"] == "CLOSED"
    assert data["version"] == 1
    assert data["balance_due_cents"] == 0
    assert data["open_work_order_count"] == 0


def test_get_pool_not_found_returns_404(api):
    """PRD §2.6: "The first identifier in the path that does not resolve to an
    existing resource produces `ERR_NOT_FOUND` immediately, before any later
    identifier or any business rule is evaluated."

    Design: Corner/entities/get_pool_not_found_returns_404
    """
    resp = api.get_pool(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_create_pool_missing_water_type_returns_invalid_request(api):
    """PRD §3.1: "Registering a pool requires the owning `customer_id`, a human
    `label` such as "Backyard pool", the sanitizer chemistry `water_type` (one of
    `CHLORINE`, `SALTWATER`, or `BROMINE_SPA`, which selects the dosing constants),
    and the water `volume_gallons`, an integer of at least 100."
    PRD §2.9: "Generic request-body schema validation — missing required fields,
    wrong types, bad enum members, out-of-range numbers — surfaces as
    `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_pool_missing_required_field_returns_invalid_request
    """
    customer = create_customer()
    payload = {"customer_id": customer["id"], "label": "Yard", "volume_gallons": 20000}
    resp = api.create_pool(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_pool_invalid_water_type_enum_returns_invalid_request(api):
    """PRD §3.1: "the sanitizer chemistry `water_type` (one of `CHLORINE`,
    `SALTWATER`, or `BROMINE_SPA`, which selects the dosing constants)".
    PRD §2.9: "Generic request-body schema validation — missing required fields,
    wrong types, bad enum members, out-of-range numbers — surfaces as
    `ERR_INVALID_REQUEST` and is the lowest-priority check of all."

    Design: Corner/entities/create_pool_invalid_enum_water_type_returns_invalid_request
    """
    customer = create_customer()
    payload = {"customer_id": customer["id"], "label": "Yard", "water_type": "GAS", "volume_gallons": 20000}
    resp = api.create_pool(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_customer_billing_terms_defaults_to_per_visit(api):
    """PRD §3.1: "The billing relationship is captured in `billing_terms`, which is
    either `PER_VISIT` or `MONTHLY_ACCRUAL` and defaults to `PER_VISIT` when omitted.
    A new customer starts life with `account_status` of `ACTIVE`."

    Design: Corner/entities/customer_billing_terms_default_applied
    """
    resp = api.create_customer(create_customer_payload(), AM)
    data = validate_success(resp, 201)
    assert data["billing_terms"] == "PER_VISIT"
    assert data["account_status"] == "ACTIVE"


# --------------------------------------------------------------------------
# Business-constraint validations
# --------------------------------------------------------------------------
def test_one_time_plan_with_frequency_rejected(api):
    """PRD §3.3: "a `ONE_TIME` plan must have `frequency` equal to `NONE`, and a
    `RECURRING` plan must have a `frequency` other than `NONE`. A plan whose type and
    cadence disagree is rejected with `ERR_FREQUENCY_PLAN_MISMATCH`."

    Design: Corner/validations/one_time_plan_with_frequency_returns_mismatch
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    payload = create_service_plan_payload(pool["id"], plan_type="ONE_TIME", frequency="WEEKLY",
                                          per_visit_rate_cents=8000)
    resp = api.create_service_plan(payload, AM)
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_PLAN_MISMATCH.value)


def test_skip_without_reason_rejected(api):
    """PRD §3.7: "The request must carry a `skip_reason` other than `NONE`; a skip
    with a missing reason or with `skip_reason` of `NONE` is rejected with
    `ERR_SKIP_REASON_REQUIRED`."

    Design: Corner/validations/skip_without_reason_returns_skip_reason_required
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    resp = api.skip_visit(ctx["visit"]["id"], skip_payload(skip_reason="NONE"), RM)
    validate_error(resp, ApiErrorId.ERR_SKIP_REASON_REQUIRED.value)


def test_invoice_with_both_references_rejected(api):
    """PRD §3.10: "An account manager creates a draft invoice against a pool by
    naming the `pool_id` and exactly one of a `visit_id` (for a completed visit) or a
    `work_order_id` (for a resolved repair). An invoice that names both, or neither,
    is rejected with `ERR_INVOICE_REFERENCE_MISMATCH`."

    Design: Corner/validations/invoice_both_references_returns_mismatch
    """
    visit_ctx = setup_completed_visit(green_pool=False, volume_gallons=20000,
                                      per_visit_rate_cents=8000, plan_type="ONE_TIME", frequency="NONE")
    wo_ctx = setup_resolved_work_order(severity="MINOR", component="FILTER",
                                       quoted_parts_cents=0, labor_minutes=30)
    payload = create_invoice_payload(visit_ctx["pool"]["id"],
                                     visit_id=visit_ctx["visit"]["id"],
                                     work_order_id=wo_ctx["work_order"]["id"])
    resp = api.create_invoice(payload, AM)
    validate_error(resp, ApiErrorId.ERR_INVOICE_REFERENCE_MISMATCH.value)


# --------------------------------------------------------------------------
# RBAC / auth
# --------------------------------------------------------------------------
def test_field_technician_cannot_create_pool(api):
    """PRD §2.1: "When a request is authenticated but the role is not permitted to
    perform the requested operation, the system responds with `ERR_UNAUTHORIZED`."
    PRD §4: pool registration is authorized for AccountManager only.

    Design: Corner/rbac/field_technician_cannot_create_pool
    """
    customer = create_customer()
    resp = api.create_pool(create_pool_payload(customer["id"]), FT)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)


def test_non_owner_customer_cannot_resolve_work_order(api):
    """PRD §2.1: "A customer acting on a work order they do not own through this
    chain is rejected with `ERR_NOT_POOL_OWNER`."
    PRD §3.9: "Both customer actions require that the acting customer own the pool
    the work order references (its pool's `customer_id` equals the customer's
    `X-User-ID`); a non-owner is rejected with `ERR_NOT_POOL_OWNER`."

    Design: Corner/rbac/non_owner_customer_cannot_resolve_work_order
    """
    # Owner A's pool with an AWAITING_APPROVAL work order; a second customer B acts.
    ctx = setup_work_order_awaiting_approval(severity="MAJOR", component="PUMP",
                                             quoted_parts_cents=5000, labor_minutes=90)
    customer_b = create_customer()
    headers_b = build_user_headers(customer_b["id"], "Customer")
    resp = api.resolve_work_order(ctx["work_order"]["id"], headers_b)
    validate_error(resp, ApiErrorId.ERR_NOT_POOL_OWNER.value, 403)


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers identifying the actor:
    `X-User-ID`, the acting operator's identifier, and `X-User-Role`, the operational
    capacity under which they act. A request missing either header is rejected with
    `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    resp = api.create_customer(create_customer_payload(), {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# --------------------------------------------------------------------------
# OCC on same-day visit logs
# --------------------------------------------------------------------------
def test_visit_log_with_correct_version_succeeds(api):
    """PRD §2.8: "the log request must carry `expected_pool_version` as a required
    field bearing the pool `version` the client last read."
    PRD §2.4: "And each carries a `version`, an integer that begins at 1 and
    increments by exactly 1 on every mutation of that resource."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_pool_version_visit_log_succeeds
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    resp = api.create_visit_log(pool["id"], visit_log_payload(expected_pool_version=pool["version"],
                                                              note="morning check"), FT)
    data = validate_success(resp, 201)
    assert data["version"] == pool["version"] + 1


def test_visit_log_with_stale_version_returns_412(api):
    """PRD §2.8: "If another writer has already advanced the pool's `version` since
    the client last read it — for instance by posting a superseding log of their own
    — then the submitted `expected_pool_version` no longer matches the pool's current
    `version`, and the request is rejected with `ERR_STALE_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_pool_version_visit_log_returns_412
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    # First log advances the version (pool now version pool.version+1).
    validate_success(api.create_visit_log(pool["id"],
                                          visit_log_payload(expected_pool_version=pool["version"], note="first"), FT), 201)
    # Second log reuses the stale (pre-supersede) expected version.
    resp = api.create_visit_log(pool["id"],
                                visit_log_payload(expected_pool_version=pool["version"], note="stale"), FT)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


# --------------------------------------------------------------------------
# Listing / pagination / filters
# --------------------------------------------------------------------------
def test_list_pools_pagination_meta(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when
    omitted it defaults to 10, and a supplied value must fall between a minimum of 1
    and a maximum of 100."
    PRD §2.3: "List responses carry the pagination accounting in the `meta` object,
    specifically `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/pagination_list_pools_has_more_total_count
    """
    customer = create_customer()
    create_pool(customer["id"], label="P1", water_type="CHLORINE", volume_gallons=20000)
    create_pool(customer["id"], label="P2", water_type="SALTWATER", volume_gallons=15000)
    resp = api.list_pools(AM, params={"customer_id": customer["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_visits_filtered_by_pool_id(api):
    """PRD §4: "List visits, optionally by pool, plan, or route".
    PRD §2.3: "List responses carry the pagination accounting in the `meta` object,
    specifically `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_visits_filtered_by_pool_id
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    resp = api.list_visits(RM, params={"pool_id": ctx["pool"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert data[0]["id"] == ctx["visit"]["id"]
