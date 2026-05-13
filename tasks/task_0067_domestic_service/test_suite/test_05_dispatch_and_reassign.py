"""Dispatch selection, accept/reject loop, deadline expiry, and manual
reassignment (PRD §3.5).
"""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    SYSTEM_HEADERS,
    advance_clock,
    create_active_personnel,
    create_customer,
    create_service_item,
    dispatch_order,
    drive_order_to,
    get_order,
    get_personnel,
    iso_in,
    make_customer_headers,
    make_personnel_headers,
    reassign_payload,
    setup_basic_scenario,
    submit_new_order,
    validate_error,
    validate_success,
)


# =============================================================================
# Successful dispatch
# =============================================================================


def test_dispatch_increments_round_and_workload(api):
    """PRD §3.5: "the order's assigned_personnel_id is set to the chosen
    personnel; dispatch_round is incremented by one (it starts at zero on
    submission, so the first dispatch reads 1) ... dispatch_deadline_at is
    set to the current time plus 15 minutes; the chosen personnel's
    workload_active_orders is incremented by one."

    Claim: first dispatch makes dispatch_round=1 and increments the chosen
    personnel's workload_active_orders by 1.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    before_p = get_personnel(ctx["personnel"]["id"])
    dispatched = dispatch_order(ctx, order["id"])
    after_p = get_personnel(ctx["personnel"]["id"])
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["dispatch_round"] == 1
    assert dispatched["assigned_personnel_id"] == ctx["personnel"]["id"]
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] + 1


def test_dispatch_with_no_eligible_personnel_rejected(api):
    """PRD §3.5: "When the eligibility filter empties, the dispatch is
    rejected with ERR_NO_ELIGIBLE_PERSONNEL."

    Claim: dispatching an order whose required_skill_tag is held by zero
    personnel returns ERR_NO_ELIGIBLE_PERSONNEL 422.
    """
    customer = create_customer()
    # A skill_tag (CHILDCARE) for which we never create a certified personnel.
    item = create_service_item(required_skill_tag="CHILDCARE")
    ctx = {
        "customer": customer,
        "service_item": item,
        "personnel": None,
        "certification": None,
    }
    # Build order via customer headers (entity-backed).
    res = api.create_order(
        {
            "customer_id": customer["id"],
            "service_item_id": item["id"],
            "mode": "SINGLE",
            "scheduled_start_at": iso_in(hours=48),
            "duration_hours": 2.0,
        },
        make_customer_headers(customer["id"]),
    )
    order = res.json()["data"]
    api.submit_order(order["id"], make_customer_headers(customer["id"]))
    res = api.dispatch_order(order["id"], OPERATOR_HEADERS)
    validate_error(res, "ERR_NO_ELIGIBLE_PERSONNEL", expected_status=422)


# =============================================================================
# Accept / reject
# =============================================================================


def test_accept_by_wrong_personnel_not_assigned(api):
    """PRD §3.5: "Accepting drives the order from DISPATCHED to ACCEPTED and
    requires both that X-User-ID equal Order.assigned_personnel_id (otherwise
    ERR_NOT_ASSIGNED)."

    Claim: accept by a personnel whose id != assigned_personnel_id →
    ERR_NOT_ASSIGNED 403.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    other_headers = make_personnel_headers("not-the-assignee-id")
    res = api.accept_order(order["id"], other_headers)
    validate_error(res, "ERR_NOT_ASSIGNED", expected_status=403)


def test_accept_after_deadline_rejected(api):
    """PRD §3.5: "An accept attempt past the deadline is rejected with
    ERR_DISPATCH_DEADLINE_PASSED."

    Claim: advancing the clock past dispatch_deadline_at then accepting →
    ERR_DISPATCH_DEADLINE_PASSED 422.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    # PRD §3.5: dispatch_deadline_at = current_time + 15 minutes.
    advance_clock(16 * 60)
    assignee_id = order["assigned_personnel_id"]
    res = api.accept_order(order["id"], make_personnel_headers(assignee_id))
    validate_error(res, "ERR_DISPATCH_DEADLINE_PASSED", expected_status=422)


def test_reject_clears_assignment_and_decrements_workload(api):
    """PRD §3.5: "on rejection, the order reverts from DISPATCHED to
    PENDING_DISPATCH, the assignee's workload_active_orders is decremented by
    one, assigned_personnel_id is cleared, the previous personnel is added to
    the order's in-memory exclusion set so the next dispatch will not pick
    them, and an AuditLogEntry with action_type of DISPATCH_EXPIRED is
    appended."

    Claim: rejection reverts to PENDING_DISPATCH, clears assigned_personnel_id,
    and decrements workload_active_orders.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    assignee_id = order["assigned_personnel_id"]
    before_p = get_personnel(assignee_id)
    res = api.reject_order(order["id"], make_personnel_headers(assignee_id))
    body = validate_success(res)
    assert body["status"] == "PENDING_DISPATCH"
    assert body.get("assigned_personnel_id") is None
    after_p = get_personnel(assignee_id)
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] - 1


# =============================================================================
# Dispatch deadline expiry via clock advance
# =============================================================================


def test_clock_advance_expires_dispatch(api):
    """PRD §3.5: "If the deadline passes with no response and the test-driving
    clock advance fires, the same transition occurs system-driven: the order
    returns to PENDING_DISPATCH, workload_active_orders is decremented for the
    previous assignee, assigned_personnel_id is cleared, and a DISPATCH_EXPIRED
    audit row is appended."

    Claim: advancing the clock past dispatch_deadline_at reverts the order to
    PENDING_DISPATCH and decrements the previous assignee's workload.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "DISPATCHED")
    assignee_id = order["assigned_personnel_id"]
    before_p = get_personnel(assignee_id)
    advance_clock(16 * 60)
    refreshed_order = get_order(order["id"])
    assert refreshed_order["status"] == "PENDING_DISPATCH"
    assert refreshed_order.get("assigned_personnel_id") is None
    after_p = get_personnel(assignee_id)
    assert after_p["workload_active_orders"] == before_p["workload_active_orders"] - 1


# =============================================================================
# Reassign (PRD §3.5)
# =============================================================================


def test_reassign_with_ineligible_target_rejected(api):
    """PRD §3.5: "the reassignment endpoint accepts a personnel_id in its
    body and re-runs the eligibility predicate against just that candidate;
    if the candidate fails the filter, the request is rejected with
    ERR_PERSONNEL_NOT_ELIGIBLE."

    Claim: reassign to a SUSPENDED personnel → ERR_PERSONNEL_NOT_ELIGIBLE 422.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    # Build a SUSPENDED candidate.
    other_p, _ = create_active_personnel(skill_tag="CLEANING")
    api.suspend_personnel(other_p["id"], OPERATOR_HEADERS)
    res = api.reassign_order(
        order["id"], reassign_payload(other_p["id"]), OPERATOR_HEADERS
    )
    validate_error(res, "ERR_PERSONNEL_NOT_ELIGIBLE", expected_status=422)


def test_reassign_success_increments_round_and_audit(api):
    """PRD §3.5: "On success, assigned_personnel_id is set to the body's
    personnel_id, dispatch_round is incremented by one, dispatch_deadline_at
    is set to the current time plus 15 minutes, the chosen personnel's
    workload_active_orders is incremented, and an AuditLogEntry with
    action_type of REASSIGN is appended."

    Claim: reassign sets assigned_personnel_id, increments dispatch_round,
    and writes a REASSIGN audit row.
    """
    ctx = setup_basic_scenario()
    order = drive_order_to(ctx, "PENDING_DISPATCH")
    # Use the same personnel as candidate (already eligible).
    res = api.reassign_order(
        order["id"], reassign_payload(ctx["personnel"]["id"]), OPERATOR_HEADERS
    )
    body = validate_success(res)
    assert body["assigned_personnel_id"] == ctx["personnel"]["id"]
    assert body["dispatch_round"] == 1
    # Audit row check
    log_res = api.list_audit_logs(
        OPERATOR_HEADERS,
        params={
            "subject_type": "Order",
            "subject_id": order["id"],
            "action_type": "REASSIGN",
            "limit": 50,
        },
    )
    rows = log_res.json()["data"]
    rows = rows if isinstance(rows, list) else rows.get("entries", [])
    assert any(r["action_type"] == "REASSIGN" for r in rows)
