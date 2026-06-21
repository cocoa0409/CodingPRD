"""Validation precedence, hazard-class safety, temporal overlap, OCC, RBAC, ownership,
authentication, pagination, and FK reverse-reachability listing reads.

Covers difficulty rules priority_pair_validation_conflict and resource_temporal_overlap
(diversion period), plus the validations / rbac / errors / cross-cutting / endpoints
corner instances.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_route_payload,
    create_stop_payload,
    create_pickup_payload,
    complete_pickup_payload,
    create_invoice_payload,
    create_diversion_period_payload,
    create_special_pickup_payload,
    create_account,
    create_active_cart,
    create_active_plan,
    setup_active_account,
    setup_route_in_progress,
    schedule_pickup,
    setup_scheduled_special_pickup,
    make_resident_headers,
)
import test_helpers as th

api = th.api_client
DISPATCHER = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
BILLING = TEST_USERS["billing_headers"]

MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-06-01T00:00:00Z"
# Anonymous: no auth headers at all (only the content type the client always sends).
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / priority_pair_validation_conflict
# ═══════════════════════════════════════════════════════════════════════════

def test_route_complete_from_planned_is_state_error_not_stops_pending():
    """PRD §2.5: "Only once a request is authenticated, authorized, resolved, and
    well-formed does the system evaluate state and business rules: whether the requested
    transition is defined for the resource's current state (`ERR_INVALID_STATE`)".
    PRD §3.2: "the driver completes the route, moving it from `IN_PROGRESS` to the
    terminal `COMPLETED` state" — completion is defined only from IN_PROGRESS, so a
    PLANNED route's completion has no defined transition.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_route_complete
    """
    account = create_account(address="19 Holly St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-15T00:00:00Z", stream="TRASH", assigned_driver_id="drv-7"), DISPATCHER), 201)
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    # Route is PLANNED with a PENDING stop; complete must fail state-first.
    resp = api.complete_route(route["id"], DRIVER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_route_complete_planned_state_error_is_409():
    """PRD §2.5: "Only once a request is authenticated, authorized, resolved, and
    well-formed does the system evaluate state and business rules: whether the requested
    transition is defined for the resource's current state (`ERR_INVALID_STATE`)".
    PRD §3.2: "the driver completes the route, moving it from `IN_PROGRESS` to the
    terminal `COMPLETED` state".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_route_complete
    """
    account = create_account(address="19b Holly St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-05-15T00:00:00Z", stream="TRASH", assigned_driver_id="drv-7b"), DISPATCHER), 201)
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    resp = api.complete_route(route["id"], DRIVER)
    err = validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert err["error_id"] == "ERR_INVALID_STATE"


def test_approve_nonexistent_special_is_not_found_not_hazard():
    """PRD §2.5: "the system validates the existence of each identifier from left to
    right and rejects the request with `ERR_NOT_FOUND` at the *first* path identifier
    that does not resolve to an existing resource."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_special_approve
    """
    resp = api.approve_special_pickup(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


def test_approve_nonexistent_special_status_404():
    """PRD §2.5: "the system validates the existence of each identifier from left to
    right and rejects the request with `ERR_NOT_FOUND` at the *first* path identifier
    that does not resolve to an existing resource."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_safety_on_special_approve
    """
    resp = api.approve_special_pickup("00000000-0000-0000-0000-000000000000", DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)


# ═══════════════════════════════════════════════════════════════════════════
# Difficulty / resource_temporal_overlap — diversion period half-open overlap
# ═══════════════════════════════════════════════════════════════════════════

def test_diversion_period_overlap_rejected():
    """PRD §3.8: "the new window must not overlap any existing `OPEN` or `FINALIZED`
    diversion period for that account. Overlap is judged on half-open intervals, so two
    windows that merely touch at a shared endpoint do not overlap and are allowed; a
    genuine overlap is rejected with `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/diversion_period_half_open_overlap_rejected
    """
    account = create_account(address="29 Cherry St")
    validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"), BILLING), 201)
    resp = api.create_diversion_period(
        account["id"], create_diversion_period_payload("2026-05-15T00:00:00Z", "2026-06-15T00:00:00Z"), BILLING)
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP, 409)


def test_diversion_period_touching_endpoint_allowed():
    """PRD §3.8: "Overlap is judged on half-open intervals, so two windows that merely
    touch at a shared endpoint do not overlap and are allowed".

    Design: Difficulty/resource_temporal_overlap/diversion_period_half_open_overlap_rejected
    """
    account = create_account(address="29b Cherry St")
    validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"), BILLING), 201)
    # New window starts exactly at the prior window's end -> touching, allowed.
    second = validate_success(api.create_diversion_period(
        account["id"], create_diversion_period_payload("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"), BILLING), 201)
    assert second["status"] == "OPEN", f"touching window must be created, got {second['status']}"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / validations — hazard class required, invalid period, pagination
# ═══════════════════════════════════════════════════════════════════════════

def test_hazard_class_required_on_create_hazardous_special():
    """PRD §3.5: "a `hazard_class` of `FLAMMABLE`, `CORROSIVE`, `TOXIC`, or `EWASTE`. A
    hazardous request created without a `hazard_class` is rejected with
    `ERR_HAZARD_CLASS_REQUIRED`."

    Design: Corner/validations/hazard_class_required_on_create_hazardous_special
    """
    account, _cart, _plan = setup_active_account(address="121 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    resp = api.create_special_pickup(
        account["id"],
        create_special_pickup_payload("HAZARDOUS", "2026-06-03T00:00:00Z"),
        make_resident_headers(account["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_HAZARD_CLASS_REQUIRED, 422)


def test_invoice_invalid_period_start_not_before_end():
    """PRD §3.6: "the `period_start` must be strictly before `period_end` or the request
    is rejected with `ERR_INVALID_PERIOD`."

    Design: Corner/validations/invoice_invalid_period_start_not_before_end
    """
    account, _cart, _plan = setup_active_account(address="123 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    resp = api.create_invoice(account["id"], create_invoice_payload(
        "2026-06-01T00:00:00Z", "2026-06-01T00:00:00Z", acct["version"]), BILLING)
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD, 422)


def test_list_accounts_invalid_pagination():
    """PRD §2.3: "A `limit` outside the inclusive range of 1 through 100, or an `offset`
    below 0, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/validations/list_accounts_invalid_pagination
    """
    resp = api.list_accounts(DISPATCHER, params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION, 400)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / cross_cutting — OCC on account invoice-create and pickup-complete
# ═══════════════════════════════════════════════════════════════════════════

def test_invoice_create_stale_account_version_rejected():
    """PRD §2.7: "Creating a draft invoice for an account requires the request body to
    carry `expected_account_version`, holding the `version` of the target
    `ServiceAccount` that the client last observed."
    PRD §2.7: "If that value does not match the account's current `version` — for
    instance because a prior invoice issue, void, or credit cascade has since advanced
    the account's `version` and recomputed its balance — the create is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/invoice_issue_stale_account_version_rejected
    """
    account, _cart, _plan = setup_active_account(address="132 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    v0 = validate_success(api.get_account(account["id"], BILLING), 200)["version"]
    # First create succeeds and bumps the account version.
    validate_success(api.create_invoice(account["id"], create_invoice_payload(
        MAY_START, MAY_END, v0), BILLING), 201)
    # Second create still carrying v0 is now stale.
    resp = api.create_invoice(account["id"], create_invoice_payload(
        "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", v0), BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_pickup_complete_correct_cart_version_succeeds_and_bumps():
    """PRD §3.3: "On completion the pickup's stop bubbles up from `PENDING` to
    `SERVICED`, the cart's `version` is incremented (so the next read of that cart
    reflects the empty), and the pickup's own `version` is incremented."

    Design: Corner/cross_cutting_complexity_layers/pickup_complete_correct_cart_version_succeeds_and_bumps
    """
    account = create_account(address="133 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])
    cart_v = cart["version"]
    completed = validate_success(api.complete_pickup(pickup["id"], complete_pickup_payload(cart_v), DRIVER), 200)
    assert completed["outcome"] == "COMPLETED"
    cart_after = validate_success(api.get_cart(cart["id"], DRIVER), 200)
    assert cart_after["version"] == cart_v + 1, (
        f"completion must bump cart version to {cart_v + 1}, got {cart_after['version']}"
    )


def test_pickup_complete_stale_cart_version_rejected():
    """PRD §2.7: "Recording a completed pickup requires the request body to carry
    `expected_cart_version`, holding the `version` of the pickup's `Cart` that the
    driver last observed."
    PRD §2.7: "If the cart's `version` has advanced since — because the cart was placed
    on hold or retired, or because another pickup already emptied and re-measured it —
    the completion is rejected with `ERR_STALE_VERSION` (HTTP 412), forcing the driver
    application to re-fetch the cart before recording the empty."

    Design: Corner/cross_cutting_complexity_layers/pickup_complete_stale_cart_version_rejected
    """
    account = create_account(address="134 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH")
    pickup = schedule_pickup(stops[0]["id"], cart["id"])
    # Pass a version one behind the cart's current version.
    resp = api.complete_pickup(pickup["id"], complete_pickup_payload(cart["version"] - 1), DRIVER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
    after = validate_success(api.get_pickup(pickup["id"], DRIVER), 200)
    assert after["outcome"] == "SCHEDULED", f"pickup must stay SCHEDULED, got {after['outcome']}"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / rbac — role denial, ownership, authentication
# ═══════════════════════════════════════════════════════════════════════════

def test_driver_cannot_create_invoice_forbidden():
    """PRD §2.1: "When a request is made under a role that is not authorized for the
    targeted endpoint, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: invoice creation (`POST /accounts/{id}/invoices`) is authorized for `Billing`.

    Design: Corner/rbac/driver_cannot_create_invoice_forbidden
    """
    account = create_account(address="128 Main St")
    acct_v = account["version"]
    resp = api.create_invoice(
        account["id"],
        create_invoice_payload(MAY_START, MAY_END, acct_v),
        build_user_headers("drv-99", "Driver"),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)


def test_resident_cannot_dispute_other_accounts_invoice():
    """PRD §2.1: "a resident acting on a resource whose account is not its own is
    rejected with `ERR_NOT_RESOURCE_OWNER`. This ownership check applies to the
    resident's self-service operations: disputing an invoice, requesting a special
    pickup, and cancelling a special pickup."

    Design: Corner/rbac/resident_cannot_dispute_other_accounts_invoice_not_owner
    """
    # Account A has an ISSUED invoice; account B is a different resident.
    account_a, _cart, _plan = setup_active_account(address="129 Main St", stream="TRASH",
                                                   base_monthly_fee_cents=1000)
    account_b = create_account(address="130 Main St")
    acct_a = validate_success(api.get_account(account_a["id"], BILLING), 200)
    invoice = validate_success(api.create_invoice(account_a["id"], create_invoice_payload(
        MAY_START, MAY_END, acct_a["version"]), BILLING), 201)
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    # Resident B (X-User-ID = account B) disputes account A's invoice.
    resp = api.dispute_invoice(invoice["id"], make_resident_headers(account_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request to the API must carry two mandatory HTTP headers:
    `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which
    declares the operational capacity under which the request is made. If either header
    is missing or malformed, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    account = create_account(address="131 Main St")
    resp = api.get_account(account["id"], NO_AUTH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


# ═══════════════════════════════════════════════════════════════════════════
# Corner / entities — paginated listing envelope
# ═══════════════════════════════════════════════════════════════════════════

def test_list_carts_paginated_envelope():
    """PRD §2.3: "Each list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."
    PRD §2.3: "The `limit` parameter caps the number of items returned".

    Design: Corner/entities/list_carts_paginated_envelope
    """
    account = create_account(address="102 Main St")
    validate_success(api.create_cart({"account_id": account["id"], "stream": "TRASH", "size_gallons": 65}, DISPATCHER), 201)
    validate_success(api.create_cart({"account_id": account["id"], "stream": "RECYCLE", "size_gallons": 96}, DISPATCHER), 201)
    data, meta = validate_paginated(api.list_carts(DISPATCHER, params={"account_id": account["id"], "limit": 1, "offset": 0}))
    assert len(data) == 1, f"limit=1 must cap to 1 item, got {len(data)}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"


# ═══════════════════════════════════════════════════════════════════════════
# Corner / endpoints — FK reverse-reachability filtered/sub-resource reads
# ═══════════════════════════════════════════════════════════════════════════

def test_list_stops_by_route_subresource():
    """PRD §3.2: "Each stop records the `route_id` of the route it belongs to, and the
    stop list may be filtered by `route_id`, by `account_id`, or by `status`."

    Design: Corner/endpoints/list_stops_by_route_subresource
    """
    account = create_account(address="136 Main St")
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-06-10T00:00:00Z", stream="TRASH", assigned_driver_id="drv-34"), DISPATCHER), 201)
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 2), DISPATCHER), 201)
    data, _ = validate_paginated(api.list_route_stops(route["id"], DISPATCHER))
    assert len(data) == 2, f"route must list its two stops, got {len(data)}"


def test_list_pickups_by_cart_filtered():
    """PRD §3.3: "The pickup list may be filtered by `stop_id`, by `cart_id`, or by
    `outcome`."

    Design: Corner/endpoints/list_pickups_by_cart_filtered
    """
    account = create_account(address="139 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route = validate_success(api.create_route(create_route_payload(
        service_date="2026-06-12T00:00:00Z", stream="TRASH", assigned_driver_id="drv-36"), DISPATCHER), 201)
    stop = validate_success(api.create_stop(route["id"], create_stop_payload(account["id"], 1), DISPATCHER), 201)
    pk = validate_success(api.create_pickup(stop["id"], create_pickup_payload(cart["id"]), DISPATCHER), 201)
    data, _ = validate_paginated(api.list_pickups(DISPATCHER, params={"cart_id": cart["id"]}))
    assert len(data) == 1, f"expected one pickup for the cart, got {len(data)}"
    assert data[0]["id"] == pk["id"]


def test_list_credits_by_source_pickup_filtered():
    """PRD §3.7: "Its `source_type` is `PICKUP` when it was generated by a carrier-fault
    missed pickup, or `SPECIAL_PICKUP` when it was generated by cancelling a
    carrier-committed special pickup".
    PRD §3.7: "a `PICKUP`-sourced credit is a flat goodwill amount of 1500 cents
    regardless of weight or plan".

    Design: Corner/endpoints/list_credits_by_source_pickup_filtered
    """
    account = create_account(address="140 Main St")
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH", service_date="2026-06-13T00:00:00Z")
    pk = schedule_pickup(stops[0]["id"], cart["id"])
    validate_success(api.miss_pickup(pk["id"], {"miss_reason": "MISSED_BY_CREW"}, DRIVER), 200)
    data, _ = validate_paginated(api.list_credits(BILLING, params={"source_pickup_id": pk["id"]}))
    assert len(data) == 1, f"expected one credit for the missed pickup, got {len(data)}"
    assert data[0]["amount_cents"] == 1500, f"flat pickup credit must be 1500, got {data[0]['amount_cents']}"


def test_list_credits_by_source_special_pickup_filtered():
    """PRD §3.7: "exactly one of `source_pickup_id` or `source_special_pickup_id` is
    populated to match" the credit's source.
    PRD §3.7: "a `SPECIAL_PICKUP`-sourced credit is 50 percent of the originating
    special pickup's `quoted_fee_cents`, rounded half-up to whole cents."

    Design: Corner/endpoints/list_credits_by_source_special_pickup_filtered
    """
    account, _cart, _plan = setup_active_account(address="137 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=1000)
    sp = setup_scheduled_special_pickup(account["id"], kind="BULK")  # quote 3500
    validate_success(api.cancel_special_pickup(sp["id"], make_resident_headers(account["id"])), 200)
    data, _ = validate_paginated(api.list_credits(BILLING, params={"source_special_pickup_id": sp["id"]}))
    assert len(data) == 1, f"expected one credit for the cancelled special pickup, got {len(data)}"
    assert data[0]["amount_cents"] == 1750, f"50% of 3500 = 1750 expected, got {data[0]['amount_cents']}"


def test_list_credits_by_applied_invoice_filtered():
    """PRD §3.7: "When an invoice is issued, the system absorbs each eligible `PENDING`
    credit for that invoice's account — that is, every `PENDING` credit whose
    `account_id` matches the invoice's account — moving it to `APPLIED` and setting its
    `applied_invoice_id` to the issued invoice; the credit's `version` increments."

    Design: Corner/endpoints/list_credits_by_applied_invoice_filtered
    """
    account, _cart, _plan = setup_active_account(address="138 Main St", stream="TRASH",
                                                 base_monthly_fee_cents=2000)
    # Carrier-fault miss -> PENDING credit 1500.
    cart = create_active_cart(account["id"], stream="TRASH", size_gallons=65)
    route, stops = setup_route_in_progress(account["id"], stream="TRASH", service_date="2026-05-20T00:00:00Z")
    pk = schedule_pickup(stops[0]["id"], cart["id"])
    validate_success(api.miss_pickup(pk["id"], {"miss_reason": "TRUCK_FULL"}, DRIVER), 200)
    acct = validate_success(api.get_account(account["id"], BILLING), 200)
    invoice = validate_success(api.create_invoice(account["id"], create_invoice_payload(
        MAY_START, MAY_END, acct["version"]), BILLING), 201)
    validate_success(api.issue_invoice(invoice["id"], BILLING), 200)
    data, _ = validate_paginated(api.list_credits(BILLING, params={"applied_invoice_id": invoice["id"]}))
    assert len(data) == 1, f"expected one credit applied to the invoice, got {len(data)}"
    assert data[0]["status"] == "APPLIED", f"credit must be APPLIED, got {data[0]['status']}"
    assert data[0]["amount_cents"] == 1500, f"flat pickup credit must be 1500, got {data[0]['amount_cents']}"
