"""Dispatch selection & offer acceptance: pro-schedule buffer overlap, zone aggregate capacity,
cross-entity vetting dependency, empty candidate pool, expired vetting, appointment-not-started."""
from datetime import datetime, timedelta
from test_helpers import (
    validate_success, validate_error, ApiErrorId, AssignmentStatus,
    setup_catalog, new_approved_pro, new_pro, new_application, new_draft_work_order,
    schedule_order, dispatch_order, offered_assignment_for, accept_assignment,
    setup_scheduled_order, setup_dispatched_order, setup_in_progress_order,
    set_clock, make_pro_headers, TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _plus_one_second(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(seconds=1)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _dispatch_two_single_pro(api, w1, w2):
    """Single approved pro; two orders each dispatched (both OFFERED), then order-1 accepted.
    Returns (pro, offered_assignment_for_order_2)."""
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = setup_catalog(api, max_concurrent=5)
    ret, cust, task, zone = (ctx["retailer"]["id"], ctx["customer"]["id"],
                             ctx["task"]["id"], ctx["zone"]["id"])
    pro, _ = new_approved_pro(api, zone)
    wo1 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S1")
    wo1 = schedule_order(api, wo1["id"], ret, w1[0], w1[1])
    dispatch_order(api, wo1["id"], wo1["version"])
    asg1 = offered_assignment_for(api, wo1["id"])
    wo2 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S2")
    wo2 = schedule_order(api, wo2["id"], ret, w2[0], w2[1])
    dispatch_order(api, wo2["id"], wo2["version"])
    asg2 = offered_assignment_for(api, wo2["id"])
    accept_assignment(api, asg1["id"], pro["id"])
    return pro, asg2


def _two_pros_capacity(api, capacity, w1, w2):
    """Two approved pros in one zone (capacity `capacity`); order-1 accepted by P1;
    order-2 dispatched to P2. Returns (p2, offered_assignment_for_order_2)."""
    set_clock(api, "2026-03-01T00:00:00Z")
    ctx = setup_catalog(api, max_concurrent=capacity)
    ret, cust, task, zone = (ctx["retailer"]["id"], ctx["customer"]["id"],
                             ctx["task"]["id"], ctx["zone"]["id"])
    p1, _ = new_approved_pro(api, zone, full_name="P1", email="p1@x.com", background_check_ref="BG1")
    p2, _ = new_approved_pro(api, zone, full_name="P2", email="p2@x.com", background_check_ref="BG2")
    wo1 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S1")
    wo1 = schedule_order(api, wo1["id"], ret, w1[0], w1[1])
    dispatch_order(api, wo1["id"], wo1["version"])
    asg1 = offered_assignment_for(api, wo1["id"])
    accept_assignment(api, asg1["id"], p1["id"])
    wo2 = new_draft_work_order(api, ret, cust, task, zone, product_sku="S2")
    wo2 = schedule_order(api, wo2["id"], ret, w2[0], w2[1])
    dispatch_order(api, wo2["id"], wo2["version"])
    asg2 = offered_assignment_for(api, wo2["id"])
    return p2, asg2


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/pro_schedule_buffer_overlap_returns_409
# ---------------------------------------------------------------------------
def test_accept_conflicting_within_buffer_returns_schedule_conflict(api):
    """PRD §3.5: "The pro must have no scheduling conflict: the accepted window
    `[appointment_start, appointment_end)`, expanded by the 30-minute travel buffer on each side,
    must not overlap another `ACCEPTED` assignment of the same pro, else `ERR_PRO_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pro_schedule_buffer_overlap_returns_409
    """
    # WO1 [10:00,11:00) accepted; WO2 [11:15,12:00) is only 15 min later -> collides after +/-30 buffer.
    pro, asg2 = _dispatch_two_single_pro(
        api, ("2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        ("2026-03-05T11:15:00Z", "2026-03-05T12:00:00Z"))
    validate_error(api.accept_assignment(asg2["id"], make_pro_headers(pro["id"])),
                   ApiErrorId.ERR_PRO_SCHEDULE_CONFLICT)


def test_accept_outside_buffer_gap_succeeds(api):
    """PRD §3.5: "The pro must have no scheduling conflict: the accepted window
    `[appointment_start, appointment_end)`, expanded by the 30-minute travel buffer on each side,
    must not overlap another `ACCEPTED` assignment of the same pro, else `ERR_PRO_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pro_schedule_buffer_overlap_returns_409
    """
    # WO1 [10:00,11:00) accepted; WO2 [12:30,13:30) -> even after +/-30 buffer there is a clear gap.
    pro, asg2 = _dispatch_two_single_pro(
        api, ("2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        ("2026-03-05T12:30:00Z", "2026-03-05T13:30:00Z"))
    data = validate_success(api.accept_assignment(asg2["id"], make_pro_headers(pro["id"])), 200)
    assert data["status"] == AssignmentStatus.ACCEPTED.value


# ---------------------------------------------------------------------------
# Difficulty/resource_temporal_overlap/zone_capacity_aggregate_overlap_returns_409
# ---------------------------------------------------------------------------
def test_accept_over_zone_capacity_returns_capacity_exceeded(api):
    """PRD §3.5: "Finally, zone aggregate capacity must hold: the count of `ACCEPTED` assignments in
    the same zone whose windows overlap this one must be strictly less than the zone's
    `max_concurrent_appointments`, else `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_aggregate_overlap_returns_409
    """
    # capacity 1: one ACCEPTED overlapping assignment already present -> second accept exceeds.
    p2, asg2 = _two_pros_capacity(
        api, 1, ("2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        ("2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"))
    validate_error(api.accept_assignment(asg2["id"], make_pro_headers(p2["id"])),
                   ApiErrorId.ERR_ZONE_CAPACITY_EXCEEDED)


def test_accept_within_zone_capacity_succeeds(api):
    """PRD §3.5: "Finally, zone aggregate capacity must hold: the count of `ACCEPTED` assignments in
    the same zone whose windows overlap this one must be strictly less than the zone's
    `max_concurrent_appointments`, else `ERR_ZONE_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/zone_capacity_aggregate_overlap_returns_409
    """
    # capacity 2: one ACCEPTED overlapping assignment; count 1 < 2 -> second accept allowed.
    p2, asg2 = _two_pros_capacity(
        api, 2, ("2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"),
        ("2026-03-05T10:30:00Z", "2026-03-05T11:30:00Z"))
    data = validate_success(api.accept_assignment(asg2["id"], make_pro_headers(p2["id"])), 200)
    assert data["status"] == AssignmentStatus.ACCEPTED.value


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency/accept_requires_pro_application_approved_returns_409
# ---------------------------------------------------------------------------
def test_accept_after_application_suspended_returns_not_approved(api):
    """PRD §3.5: "The accepting pro's vetting must be `APPROVED` — not `PENDING_REVIEW`,
    `SUSPENDED`, or `REJECTED` — else `ERR_PRO_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_pro_application_approved_returns_409
    """
    ctx = setup_dispatched_order(api)
    validate_success(api.suspend_application(ctx["app"]["id"], ADMIN), 200)
    validate_error(api.accept_assignment(ctx["assignment"]["id"], make_pro_headers(ctx["pro"]["id"])),
                   ApiErrorId.ERR_PRO_NOT_APPROVED)


def test_accept_after_reinstate_succeeds(api):
    """PRD §3.2: "A `SUSPENDED` application can be reinstated back to `APPROVED`, which restores the
    pro's dispatch eligibility while leaving `approved_at` and `expires_at` unchanged."
    PRD §3.5: "The accepting pro's vetting must be `APPROVED` — not `PENDING_REVIEW`, `SUSPENDED`,
    or `REJECTED` — else `ERR_PRO_NOT_APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_pro_application_approved_returns_409
    """
    ctx = setup_dispatched_order(api)
    validate_success(api.suspend_application(ctx["app"]["id"], ADMIN), 200)
    validate_success(api.reinstate_application(ctx["app"]["id"], ADMIN), 200)
    data = validate_success(
        api.accept_assignment(ctx["assignment"]["id"], make_pro_headers(ctx["pro"]["id"])), 200)
    assert data["status"] == AssignmentStatus.ACCEPTED.value


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_returns_409
# ---------------------------------------------------------------------------
def test_dispatch_with_no_pros_returns_no_eligible_pro(api):
    """PRD §3.4: "If the candidate pool is empty, dispatch is refused with `ERR_NO_ELIGIBLE_PRO`."

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_returns_409
    """
    ctx = setup_scheduled_order(api)  # no pro exists at all
    validate_error(
        api.dispatch_work_order(ctx["wo"]["id"], {"expected_work_order_version": ctx["version"]}, ADMIN),
        ApiErrorId.ERR_NO_ELIGIBLE_PRO)


def test_dispatch_with_only_unapproved_pro_returns_no_eligible_pro(api):
    """PRD §3.4: "the pro has a vetting application that is `APPROVED` with the logical clock at or
    before its `expires_at` (a suspended, rejected, pending, or expired vetting disqualifies the pro)"

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_returns_409
    """
    ctx = setup_scheduled_order(api)
    pro = new_pro(api, ctx["zone"]["id"], skills=["TV_MOUNT"])
    new_application(api, pro["id"])  # PENDING_REVIEW, never approved -> pool stays empty
    validate_error(
        api.dispatch_work_order(ctx["wo"]["id"], {"expected_work_order_version": ctx["version"]}, ADMIN),
        ApiErrorId.ERR_NO_ELIGIBLE_PRO)


# ---------------------------------------------------------------------------
# Corner/validations/accept_with_expired_vetting_returns_409
# ---------------------------------------------------------------------------
def test_accept_with_expired_vetting_returns_vetting_expired(api):
    """PRD §3.5: "That approved vetting must not have lapsed: the clock must be at or before the
    application's `expires_at`, else `ERR_VETTING_EXPIRED`."

    Design: Corner/validations/accept_with_expired_vetting_returns_409
    """
    ctx = setup_dispatched_order(api, clock="2026-03-01T00:00:00Z")
    # Advance the logical clock to one second past the approved application's own expiry instant.
    set_clock(api, _plus_one_second(ctx["app"]["expires_at"]))
    validate_error(api.accept_assignment(ctx["assignment"]["id"], make_pro_headers(ctx["pro"]["id"])),
                   ApiErrorId.ERR_VETTING_EXPIRED)


# ---------------------------------------------------------------------------
# Corner/validations/complete_before_appointment_start_returns_422
# ---------------------------------------------------------------------------
def test_complete_before_appointment_start_returns_not_started(api):
    """PRD §3.6: "and is allowed only once the clock has reached the appointment start — that is,
    the current clock must be at or after `scheduled_start`, else the completion is refused with
    `ERR_APPOINTMENT_NOT_STARTED`."

    Design: Corner/validations/complete_before_appointment_start_returns_422
    """
    ctx = setup_in_progress_order(
        api, clock="2026-03-01T00:00:00Z",
        scheduled_start="2026-03-20T10:00:00Z", scheduled_end="2026-03-20T11:00:00Z")
    validate_error(api.complete_work_order(ctx["wo"]["id"], make_pro_headers(ctx["pro"]["id"])),
                   ApiErrorId.ERR_APPOINTMENT_NOT_STARTED)
