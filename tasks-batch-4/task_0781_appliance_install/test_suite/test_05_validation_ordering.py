"""Validation precedence & temporal boundaries: appointment-window vs invalid-state,
vetting vs zone-capacity, retailer-active gate, warranty-expiry instant, and single-rule guards."""
from datetime import datetime, timedelta
from test_helpers import (
    validate_success, validate_error, ApiErrorId, WorkOrderStatus,
    setup_catalog, setup_scheduled_order, setup_completed_order, setup_dispatched_order,
    new_draft_work_order, new_addon, new_approved_pro, schedule_order, dispatch_order,
    offered_assignment_for, accept_assignment, suspend_retailer, set_clock,
    make_retailer_headers, make_customer_headers, make_pro_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _plus_one_second(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(seconds=1)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/schedule_bad_window_beats_invalid_state_returns_422
# ---------------------------------------------------------------------------
def test_bad_window_beats_invalid_state_on_scheduled_order(api):
    """PRD §2.9: "The appointment-window ordering check (`ERR_INVALID_APPOINTMENT_WINDOW`) is
    evaluated after body well-formedness. State checks follow: first that the target is in a valid
    from-state for the requested transition (`ERR_INVALID_STATE`), then that it is not already in a
    terminal state (`ERR_ALREADY_TERMINAL`)."

    Design: Difficulty/priority_pair_validation_conflict/schedule_bad_window_beats_invalid_state_returns_422
    """
    ctx = setup_scheduled_order(api)  # already SCHEDULED (an invalid from-state to re-schedule)
    ret_id = ctx["retailer"]["id"]
    resp = api.schedule_work_order(
        ctx["wo"]["id"],
        {"scheduled_start": "2026-03-10T10:00:00Z", "scheduled_end": "2026-03-10T10:00:00Z"},
        make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)


def test_bad_window_rejected_on_draft_schedule(api):
    """PRD §3.3: "the window must be well-ordered with `scheduled_start` strictly before
    `scheduled_end`, else `ERR_INVALID_APPOINTMENT_WINDOW`"

    Design: Difficulty/priority_pair_validation_conflict/schedule_bad_window_beats_invalid_state_returns_422
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    resp = api.schedule_work_order(
        wo["id"],
        {"scheduled_start": "2026-03-10T11:00:00Z", "scheduled_end": "2026-03-10T10:00:00Z"},
        make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_APPOINTMENT_WINDOW)


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/accept_suspended_pro_beats_zone_capacity_returns_409
# ---------------------------------------------------------------------------
def test_suspended_pro_beats_zone_capacity_on_accept(api):
    """PRD §3.5: "The accepting pro's vetting must be `APPROVED` — not `PENDING_REVIEW`,
    `SUSPENDED`, or `REJECTED` — else `ERR_PRO_NOT_APPROVED`."
    PRD §3.5: "Finally, zone aggregate capacity must hold: the count of `ACCEPTED` assignments in
    the same zone whose windows overlap this one must be strictly less than the zone's
    `max_concurrent_appointments`, else `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/accept_suspended_pro_beats_zone_capacity_returns_409
    """
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = setup_catalog(api, max_concurrent=1)
    ret, cust, task, zone = (ctx["retailer"]["id"], ctx["customer"]["id"],
                             ctx["task"]["id"], ctx["zone"]["id"])
    p1, _ = new_approved_pro(api, zone, full_name="P1", email="p1@x.com", background_check_ref="BG1")
    p2, app2 = new_approved_pro(api, zone, full_name="P2", email="p2@x.com", background_check_ref="BG2")
    wo1 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S1")
    wo1 = schedule_order(api, wo1["id"], ret, "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z")
    dispatch_order(api, wo1["id"], wo1["version"])
    accept_assignment(api, offered_assignment_for(api, wo1["id"])["id"], p1["id"])
    wo2 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S2")
    wo2 = schedule_order(api, wo2["id"], ret, "2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z")
    dispatch_order(api, wo2["id"], wo2["version"])
    asg2 = offered_assignment_for(api, wo2["id"])
    validate_success(api.suspend_application(app2["id"], ADMIN), 200)
    # Both vetting (p12) and zone-capacity (p16) would reject; the earlier vetting check wins.
    validate_error(api.accept_assignment(asg2["id"], make_pro_headers(p2["id"])),
                   ApiErrorId.ERR_PRO_NOT_APPROVED)


def test_suspended_pro_rejected_on_accept_in_isolation(api):
    """PRD §3.5: "The accepting pro's vetting must be `APPROVED` — not `PENDING_REVIEW`,
    `SUSPENDED`, or `REJECTED` — else `ERR_PRO_NOT_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/accept_suspended_pro_beats_zone_capacity_returns_409
    """
    ctx = setup_dispatched_order(api)  # ample zone capacity; only vetting can fail
    validate_success(api.suspend_application(ctx["app"]["id"], ADMIN), 200)
    validate_error(api.accept_assignment(ctx["assignment"]["id"], make_pro_headers(ctx["pro"]["id"])),
                   ApiErrorId.ERR_PRO_NOT_APPROVED)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/redo_at_exact_warranty_expiry_instant_allowed
# ---------------------------------------------------------------------------
def test_redo_at_exact_warranty_expiry_instant_allowed(api):
    """PRD §3.8: "The customer who owns the order (`X-User-ID` equal to the order's `customer_id`)
    may request a redo while the order is `COMPLETED` and the clock is at or before the order's
    `warranty_expires_at`; a request after that instant is refused with `ERR_WARRANTY_EXPIRED`, and
    a request on an order not in `COMPLETED` yields `ERR_INVALID_STATE`."

    Design: Difficulty/boundary_precision_check/redo_at_exact_warranty_expiry_instant_allowed
    """
    ctx = setup_completed_order(api, warranty_days=30,
                                scheduled_start="2026-03-05T09:00:00Z",
                                scheduled_end="2026-03-05T10:00:00Z", clock="2026-03-05T10:00:00Z")
    set_clock(api, ctx["wo"]["warranty_expires_at"])  # exactly at expiry instant (inclusive)
    wo = validate_success(api.request_redo(ctx["wo"]["id"], make_customer_headers(ctx["customer"]["id"])), 200)
    assert wo["status"] == WorkOrderStatus.REDO_REQUESTED.value
    assert wo["redo_count"] == 1


def test_redo_one_second_after_warranty_rejected(api):
    """PRD §3.8: "The customer who owns the order (`X-User-ID` equal to the order's `customer_id`)
    may request a redo while the order is `COMPLETED` and the clock is at or before the order's
    `warranty_expires_at`; a request after that instant is refused with `ERR_WARRANTY_EXPIRED`, and
    a request on an order not in `COMPLETED` yields `ERR_INVALID_STATE`."

    Design: Difficulty/boundary_precision_check/redo_at_exact_warranty_expiry_instant_allowed
    """
    ctx = setup_completed_order(api, warranty_days=30,
                                scheduled_start="2026-03-05T09:00:00Z",
                                scheduled_end="2026-03-05T10:00:00Z", clock="2026-03-05T10:00:00Z")
    set_clock(api, _plus_one_second(ctx["wo"]["warranty_expires_at"]))
    validate_error(api.request_redo(ctx["wo"]["id"], make_customer_headers(ctx["customer"]["id"])),
                   ApiErrorId.ERR_WARRANTY_EXPIRED)


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/schedule_requires_retailer_active_returns_409
# ---------------------------------------------------------------------------
def test_schedule_with_suspended_retailer_rejected(api):
    """PRD §3.3: "the referring retailer must be `ACTIVE`, else the request is refused with
    `ERR_RETAILER_SUSPENDED`"

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_retailer_active_returns_409
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    suspend_retailer(api, ret_id)
    resp = api.schedule_work_order(
        wo["id"], {"scheduled_start": "2026-03-05T09:00:00Z", "scheduled_end": "2026-03-05T10:00:00Z"},
        make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_RETAILER_SUSPENDED)


def test_schedule_succeeds_after_retailer_reactivated(api):
    """PRD §3.1: "A retailer begins life with `status` `ACTIVE` and a `settlement_balance_cents` of
    0; an admin can later toggle `status` between `ACTIVE` and `SUSPENDED`. A suspended retailer
    blocks new scheduling (see §3.3)."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_retailer_active_returns_409
    """
    ctx = setup_catalog(api)
    ret_id = ctx["retailer"]["id"]
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    suspend_retailer(api, ret_id)
    validate_success(api.update_retailer_status(ret_id, {"status": "ACTIVE"}, ADMIN), 200)
    scheduled = validate_success(api.schedule_work_order(
        wo["id"], {"scheduled_start": "2026-03-05T09:00:00Z", "scheduled_end": "2026-03-05T10:00:00Z"},
        make_retailer_headers(ret_id)), 200)
    assert scheduled["status"] == WorkOrderStatus.SCHEDULED.value


# ---------------------------------------------------------------------------
# Corner/validations/schedule_addon_category_mismatch_returns_422
# ---------------------------------------------------------------------------
def test_schedule_addon_category_mismatch_returns_422(api):
    """PRD §3.3: "and every id in `selected_addon_ids` must resolve to an add-on whose `category`
    equals the order's install task `category`, else `ERR_ADDON_CATEGORY_MISMATCH`."

    Design: Corner/validations/schedule_addon_category_mismatch_returns_422
    """
    ctx = setup_catalog(api, category="TV_MOUNT", required_skill="TV_MOUNT")
    ret_id = ctx["retailer"]["id"]
    addon = new_addon(api, 4000, category="APPLIANCE", addon_code="AP", name="Appliance Haul")
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    resp = api.schedule_work_order(
        wo["id"], {"scheduled_start": "2026-03-05T09:00:00Z", "scheduled_end": "2026-03-05T10:00:00Z",
                   "selected_addon_ids": [addon["id"]]}, make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_ADDON_CATEGORY_MISMATCH)


# ---------------------------------------------------------------------------
# Corner/validations/schedule_into_inactive_zone_returns_409
# ---------------------------------------------------------------------------
def test_schedule_into_inactive_zone_returns_409(api):
    """PRD §3.3: "the target zone's `coverage_active` must be true, else `ERR_ZONE_COVERAGE_INACTIVE`"

    Design: Corner/validations/schedule_into_inactive_zone_returns_409
    """
    ctx = setup_catalog(api, coverage_active=False)
    ret_id = ctx["retailer"]["id"]
    wo = new_draft_work_order(api, ret_id, ctx["customer"]["id"], ctx["task"]["id"], ctx["zone"]["id"])
    resp = api.schedule_work_order(
        wo["id"], {"scheduled_start": "2026-03-05T09:00:00Z", "scheduled_end": "2026-03-05T10:00:00Z"},
        make_retailer_headers(ret_id))
    validate_error(resp, ApiErrorId.ERR_ZONE_COVERAGE_INACTIVE)


# ---------------------------------------------------------------------------
# Corner/validations/rate_before_completion_returns_409
# ---------------------------------------------------------------------------
def test_rate_before_completion_returns_409(api):
    """PRD §3.9: "A rating may be submitted only when the order's `status` is `COMPLETED` or
    `CLOSED`, else the request is refused with `ERR_RATING_NOT_ALLOWED`"

    Design: Corner/validations/rate_before_completion_returns_409
    """
    ctx = setup_scheduled_order(api)
    resp = api.create_rating(ctx["wo"]["id"], {"stars": 5}, make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_RATING_NOT_ALLOWED)


# ---------------------------------------------------------------------------
# Corner/validations/request_redo_after_warranty_returns_422
# ---------------------------------------------------------------------------
def test_request_redo_after_warranty_returns_422(api):
    """PRD §3.8: "The customer who owns the order (`X-User-ID` equal to the order's `customer_id`)
    may request a redo while the order is `COMPLETED` and the clock is at or before the order's
    `warranty_expires_at`; a request after that instant is refused with `ERR_WARRANTY_EXPIRED`, and
    a request on an order not in `COMPLETED` yields `ERR_INVALID_STATE`."

    Design: Corner/validations/request_redo_after_warranty_returns_422
    """
    ctx = setup_completed_order(api, warranty_days=30,
                                scheduled_start="2026-03-05T09:00:00Z",
                                scheduled_end="2026-03-05T10:00:00Z", clock="2026-03-05T10:00:00Z")
    set_clock(api, _plus_one_second(ctx["wo"]["warranty_expires_at"]))
    validate_error(api.request_redo(ctx["wo"]["id"], make_customer_headers(ctx["customer"]["id"])),
                   ApiErrorId.ERR_WARRANTY_EXPIRED)
