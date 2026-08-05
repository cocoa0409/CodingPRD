"""Transitive cascades (order cancel; timesheet verify) and the RBAC / role-scope
/ authentication guards.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_verifier_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------- #
# Corner: RBAC
# --------------------------------------------------------------------------- #
def test_clinician_cannot_verify_own_timesheet(api):
    """PRD 2.1: "When a request is authenticated but the acting role is not among the
    roles permitted on the target endpoint, it is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/clinician_cannot_verify_own_timesheet
    """
    bundle = fx.setup_submitted_timesheet(facility_overrides={"name": "Fallow Field"})
    fac_id, cl_id, asg, ts = (
        bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"], bundle["timesheet"])
    resp = api.verify_timesheet(ts["id"], {}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
    got = validate_success(api.get_timesheet(ts["id"], ADMIN), 200)
    assert got["status"] == "SUBMITTED"
    asg_after = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert asg_after["pay_status"] == "TIMESHEET_PENDING"


def test_scheduler_cannot_act_on_other_facilitys_order(api):
    """PRD 2.1: "A facility principal acting on a resource belonging to a different
    facility is rejected with `ERR_ROLE_SCOPE_VIOLATION` (HTTP 403); a clinician acting
    on a resource belonging to a different clinician is rejected with `ERR_NOT_OWNER`
    (HTTP 403)."

    Design: Corner/rbac/scheduler_cannot_act_on_other_facilitys_order
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac_a = fx.new_facility(name="Gorse")
    fac_b = fx.new_facility(name="Heather")
    order = fx.new_order(fac_a["id"])
    resp = api.cancel_order(order["id"], {"reason": "poaching a rival's order"}, make_scheduler_headers(fac_b["id"]))
    validate_error(resp, ApiErrorId.ERR_ROLE_SCOPE_VIOLATION.value, 403)
    got = validate_success(api.get_order(order["id"], make_scheduler_headers(fac_a["id"])), 200)
    assert got["status"] == "OPEN"


def test_missing_auth_headers_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of the six
    roles defined by this system, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Foxglove")
    resp = api.get_facility(fac["id"], {})  # no X-User-ID / X-User-Role headers
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


# --------------------------------------------------------------------------- #
# Difficulty: four-link order-cancel cascade reaching the reliability score
# --------------------------------------------------------------------------- #
def _setup_order_cancel_cascade():
    """Clinician carries one PENDING no-show (provisional 70) and is CONFIRMED on a
    second order's shift; returns (fac_id, cl_id, order2_id, s2_id, asg2_id)."""
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Grand Mesa", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Gita Shah", email="gita.shah@example.com")
    fx.add_verified_credential(cl["id"])
    fac_id, cl_id = fac["id"], cl["id"]

    order1 = fx.new_order(fac_id)
    s1 = fx.add_shift(order1["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    c1 = fx.place_claim(s1["id"], cl_id)
    a1 = fx.award(s1["id"], fac_id, claim_id=c1["id"])
    fx.confirm(a1["id"], cl_id)
    fx.set_clock("2026-06-08T08:00:00Z")
    fx.no_show(a1["id"], fac_id, note="never badged in")

    order2 = fx.new_order(fac_id, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    s2 = fx.add_shift(order2["id"], fac_id, scheduled_start="2026-06-16T07:00:00Z", scheduled_end="2026-06-16T19:00:00Z")
    c2 = fx.place_claim(s2["id"], cl_id)
    a2 = fx.award(s2["id"], fac_id, claim_id=c2["id"])
    fx.confirm(a2["id"], cl_id)
    return fac_id, cl_id, order2["id"], s2["id"], a2["id"]


def test_order_cancel_cascades_to_shift_and_assignment(api):
    """PRD 3.7: "the first link sets every shift under the order whose `status` is
    `OPEN` or `ASSIGNED` to `CANCELLED`. The second link, because those shifts became
    cancelled, moves every assignment on them whose `work_status` is
    `PENDING_CONFIRMATION` or `CONFIRMED` to `CANCELLED_BY_FACILITY` and its pay axis to
    `WAIVED`."

    Design: Difficulty/transitive_cascade/order_cancel_four_link_cascade_to_reliability_score
    """
    fac_id, cl_id, order2_id, s2_id, asg2_id = _setup_order_cancel_cascade()
    cancelled = validate_success(
        api.cancel_order(order2_id, {"reason": "census dropped, unit closed for the week"},
                         make_scheduler_headers(fac_id)), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["shift_count"] == 1 and cancelled["cancelled_count"] == 1
    assert cancelled["filled_count"] == 0 and cancelled["open_count"] == 0
    shift = validate_success(api.get_shift(s2_id, make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "CANCELLED"
    asg = validate_success(api.get_assignment(asg2_id, make_scheduler_headers(fac_id)), 200)
    assert asg["work_status"] == "CANCELLED_BY_FACILITY"
    assert asg["pay_status"] == "WAIVED"


def test_order_cancel_cascades_to_reliability_credit_and_score(api):
    """PRD 3.7: "The third link, because those assignments were facility-cancelled,
    appends one `FACILITY_CANCELLATION_CREDIT` event worth 2 credit points already
    `CONFIRMED` per cancelled assignment. The fourth link, because those events were
    appended, runs the reliability recompute for each affected clinician, rewriting both
    score variants".

    Design: Difficulty/transitive_cascade/order_cancel_four_link_cascade_to_reliability_score
    """
    fac_id, cl_id, order2_id, s2_id, asg2_id = _setup_order_cancel_cascade()
    before = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert before["provisional_reliability_score"] == 70
    fx.api_client.cancel_order(order2_id, {"reason": "census dropped, unit closed for the week"},
                               make_scheduler_headers(fac_id))
    events = validate_success(api.list_assignment_reliability_events(asg2_id, OFFICER), 200)
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "FACILITY_CANCELLATION_CREDIT"
    assert ev["credit_points"] == 2 and ev["penalty_points"] == 0
    assert ev["adjudication_status"] == "CONFIRMED"
    after = validate_success(api.get_clinician(cl_id, OFFICER), 200)
    assert after["provisional_reliability_score"] == 72
    assert after["reliability_score"] == 100
    assert after["status"] == "ACTIVE"


# --------------------------------------------------------------------------- #
# Difficulty: three-link verify cascade closing the order
# --------------------------------------------------------------------------- #
def _setup_verify_cascade():
    """FILLED order holding one CONFIRMED shift with a SUBMITTED timesheet. Returns
    (fac_id, cl_id, order_id, shift_id, asg_id, ts_id)."""
    bundle = fx.setup_submitted_timesheet(facility_overrides={"name": "Ridgeway"})
    return (
        bundle["facility"]["id"], bundle["clinician"]["id"], bundle["order"]["id"],
        bundle["shift"]["id"], bundle["assignment"]["id"], bundle["timesheet"]["id"],
    )


def test_verify_cascade_advances_timesheet_assignment_and_shift(api):
    """PRD 3.6: "Because the timesheet became verified, the assignment's pay axis moves
    `TIMESHEET_PENDING → PAYABLE`, the assignment's `final_pay_cents` is set to the
    timesheet's `gross_pay_cents`, and the facility's `pending_pay_cents` grows by
    `gross_pay_cents` while the facility's `version` bumps. Because the assignment
    reached `PAYABLE`, its shift moves `ASSIGNED → COMPLETED`, which triggers the parent
    order's fill-posture recompute and can move the order to `CLOSED` once every sibling
    shift is terminal."

    Design: Difficulty/transitive_cascade/timesheet_verify_three_link_cascade_to_order_closed
    """
    fac_id, cl_id, order_id, shift_id, asg_id, ts_id = _setup_verify_cascade()
    order_before = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order_before["status"] == "FILLED"

    verified = validate_success(api.verify_timesheet(ts_id, {}, make_verifier_headers(fac_id)), 200)
    assert verified["status"] == "VERIFIED" and verified["gross_pay_cents"] == 86250
    asg = validate_success(api.get_assignment(asg_id, make_scheduler_headers(fac_id)), 200)
    assert asg["pay_status"] == "PAYABLE" and asg["final_pay_cents"] == 86250 and asg["work_status"] == "WORKED"
    shift = validate_success(api.get_shift(shift_id, make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "COMPLETED"
    order = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order["status"] == "CLOSED"


def test_verify_cascade_updates_counters_and_pending_pay(api):
    """PRD 3.6: "the facility's `pending_pay_cents` grows by `gross_pay_cents` while the
    facility's `version` bumps."
    PRD 3.3: "otherwise `CLOSED` when it has at least one shift, no open shifts remain,
    every filled shift is completed, and completed plus cancelled shifts account for all
    of them".

    Design: Difficulty/transitive_cascade/timesheet_verify_three_link_cascade_to_order_closed
    """
    fac_id, cl_id, order_id, shift_id, asg_id, ts_id = _setup_verify_cascade()
    fx.verify_timesheet(ts_id, fac_id)
    order = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order["completed_count"] == 1 and order["open_count"] == 0 and order["filled_count"] == 1
    facility = validate_success(api.get_facility(fac_id, ADMIN), 200)
    assert facility["pending_pay_cents"] == 86250
