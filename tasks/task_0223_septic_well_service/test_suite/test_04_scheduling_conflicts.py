"""Scheduling conflict checks, cross-entity scheduling preconditions, and route
optimization ordering / empty-set boundary.

Translates queue A `resource_temporal_overlap`, `cross_entity_state_dependency`,
`boundary_precision_check` (empty route instance), and queue B `calculations`
(route_optimize ordering) instance.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_account, create_site, create_technician, create_route,
    create_work_order_payload, get_work_order, get_route,
    setup_account_site_tech_route,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Difficulty: resource_temporal_overlap ─────────────

def test_technician_window_half_open_overlap_rejected(api):
    """PRD §3.4: "The work order's half-open window [window_start_minute,
    window_end_minute) must not overlap any other SCHEDULED or DISPATCHED work order on the
    same technician and the same date; an overlap is rejected with
    ERR_TECH_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap_rejected
    """
    account = create_account()
    site1 = create_site(account["id"], address="14a Lake")
    site2 = create_site(account["id"], address="14b Lake")
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-20")
    wo1 = get_success_data(api.create_work_order(
        create_work_order_payload(site1["id"], "PUMPING", "2026-06-20", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo1["id"], {"route_id": route["id"]}, DISPATCHER))
    wo2 = get_success_data(api.create_work_order(
        create_work_order_payload(site2["id"], "PUMPING", "2026-06-20", 570, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(wo2["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_TECH_WINDOW_CONFLICT", expected_status=409)
    assert get_work_order(wo2["id"])["status"] == "DRAFT"


def test_technician_back_to_back_window_is_allowed(api):
    """PRD §3.4: "The work order's half-open window [window_start_minute,
    window_end_minute) must not overlap any other SCHEDULED or DISPATCHED work order on the
    same technician and the same date".

    Design: Difficulty/resource_temporal_overlap/technician_window_half_open_overlap_rejected
    """
    # WO1 occupies [540,600); a back-to-back WO at [600,660) does not overlap because the
    # end minute is excluded. Two distant sites avoid the site day-buffer rule.
    account = create_account()
    site1 = create_site(account["id"], address="14a Lake")
    site2 = create_site(account["id"], address="14b Lake")
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-20")
    wo1 = get_success_data(api.create_work_order(
        create_work_order_payload(site1["id"], "PUMPING", "2026-06-20", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo1["id"], {"route_id": route["id"]}, DISPATCHER))
    wo2 = get_success_data(api.create_work_order(
        create_work_order_payload(site2["id"], "PUMPING", "2026-06-20", 600, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(wo2["id"], {"route_id": route["id"]}, DISPATCHER)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_site_day_buffer_adjacency_rejected(api):
    """PRD §3.4: "between any two SCHEDULED or DISPATCHED work orders on the same site and
    date, the gap — measured as the later order's window_start_minute minus the earlier
    order's window_end_minute, with the windows treated as closed intervals — must be at
    least the site day-buffer; a gap smaller than the buffer (including windows that touch
    or sit adjacent within the buffer) is rejected with ERR_SITE_BUFFER_CONFLICT."
    PRD §3.4: "The site day-buffer is two hours."

    Design: Difficulty/resource_temporal_overlap/site_day_buffer_adjacency_rejected
    """
    account = create_account()
    site = create_site(account["id"], address="15 Mead")
    tech1 = create_technician(name="Tina")
    tech2 = create_technician(name="Ted")
    route1 = create_route(tech1["id"], "2026-06-21")
    route2 = create_route(tech2["id"], "2026-06-21")
    woA = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-21", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(woA["id"], {"route_id": route1["id"]}, DISPATCHER))
    # Second WO same site, window 630 -> gap = 630 - 600 = 30 < 120 buffer; different tech.
    woB = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-21", 630, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(woB["id"], {"route_id": route2["id"]}, DISPATCHER)
    validate_error(res, "ERR_SITE_BUFFER_CONFLICT", expected_status=409)
    assert get_work_order(woB["id"])["status"] == "DRAFT"


def test_site_day_buffer_met_when_gap_exceeds_two_hours(api):
    """PRD §3.4: "the gap — measured as the later order's window_start_minute minus the
    earlier order's window_end_minute, with the windows treated as closed intervals — must
    be at least the site day-buffer".
    PRD §3.4: "The site day-buffer is two hours."

    Design: Difficulty/resource_temporal_overlap/site_day_buffer_adjacency_rejected
    """
    # WO_A occupies [540,600); a second WO on the same site at window 720 has gap
    # 720 - 600 = 120 == SITE_BUFFER_MINUTES, which satisfies the "at least" rule.
    account = create_account()
    site = create_site(account["id"], address="15 Mead")
    tech1 = create_technician(name="Tina")
    tech2 = create_technician(name="Ted")
    route1 = create_route(tech1["id"], "2026-06-21")
    route2 = create_route(tech2["id"], "2026-06-21")
    woA = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-21", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(woA["id"], {"route_id": route1["id"]}, DISPATCHER))
    woB = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-21", 720, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.schedule_work_order(woB["id"], {"route_id": route2["id"]}, DISPATCHER)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


# ─── Difficulty: cross_entity_state_dependency ─────────

def test_schedule_blocked_when_account_on_hold(api):
    """PRD §3.4: "First, the owning site's account must be in GOOD standing; scheduling
    against an account whose standing is HOLD is rejected with ERR_ACCOUNT_ON_HOLD."

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_account_on_hold
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-19")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-19", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.hold_account(account["id"], DISPATCHER))
    res = api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_ACCOUNT_ON_HOLD", expected_status=409)
    assert get_work_order(wo["id"])["status"] == "DRAFT"


def test_schedule_succeeds_after_hold_released(api):
    """PRD §3.4: "First, the owning site's account must be in GOOD standing".
    PRD §3.10: "Releasing a hold advances standing from HOLD back to GOOD".

    Design: Difficulty/cross_entity_state_dependency/schedule_blocked_when_account_on_hold
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-19")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-19", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.hold_account(account["id"], DISPATCHER))
    get_success_data(api.release_account_hold(account["id"], DISPATCHER))
    res = api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER)
    scheduled = validate_success(res, 200)
    assert scheduled["status"] == "SCHEDULED"


def test_permit_submit_blocked_until_report_finalized(api):
    """PRD §3.9: "The linked inspection report must be FINALIZED, or the submit is rejected
    with ERR_REPORT_NOT_FINALIZED."

    Design: Difficulty/cross_entity_state_dependency/permit_submit_blocked_until_report_finalized
    """
    from test_helpers import (
        set_clock, create_completed_inspection_wo, create_inspection_report,
        create_permit_filing,
    )
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=0)  # DRAFT, not finalized
    filing = create_permit_filing(report["id"], base["site"]["id"])
    res = api.submit_permit_filing(filing["id"], TEST_USERS["compliance_officer_headers"])
    validate_error(res, "ERR_REPORT_NOT_FINALIZED", expected_status=409)
    rep_now = validate_success(
        api.get_inspection_report(report["id"], TEST_USERS["compliance_officer_headers"]), 200
    )
    assert rep_now["status"] == "DRAFT"


def test_permit_submit_succeeds_once_report_finalized(api):
    """PRD §3.9: "The linked inspection report must be FINALIZED, or the submit is rejected
    with ERR_REPORT_NOT_FINALIZED."
    PRD §3.8: "Finalizing a report advances its status from DRAFT to FINALIZED".

    Design: Difficulty/cross_entity_state_dependency/permit_submit_blocked_until_report_finalized
    """
    from test_helpers import (
        set_clock, create_completed_inspection_wo, create_inspection_report,
        finalize_inspection_report, create_permit_filing,
    )
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    finalize_inspection_report(report["id"], "PASS")
    filing = create_permit_filing(report["id"], base["site"]["id"])
    set_clock("2026-06-05T00:00:00Z")  # past cooling-off
    res = api.submit_permit_filing(filing["id"], TEST_USERS["compliance_officer_headers"])
    submitted = validate_success(res, 200)
    assert submitted["status"] == "SUBMITTED"


# ─── Difficulty: boundary_precision_check (empty route) ─

def test_route_optimize_empty_stop_set(api):
    """PRD §3.4: "When the route has no such work orders, the optimized_sequence is the
    empty list."
    PRD §3.4: "it opens with status OPEN, an assigned_stop_count of 0".

    Design: Difficulty/boundary_precision_check/route_optimize_empty_stop_set
    """
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-18")
    res = api.optimize_route(route["id"], DISPATCHER)
    optimized = validate_success(res, 200)
    assert optimized["optimized_sequence"] == []
    assert optimized["assigned_stop_count"] == 0


def test_route_optimize_no_work_orders_returns_ok(api):
    """PRD §3.4: "Optimizing a route computes its stop order."
    PRD §3.4: "When the route has no such work orders, the optimized_sequence is the empty
    list."

    Design: Difficulty/boundary_precision_check/route_optimize_empty_stop_set
    """
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-18")
    res = api.optimize_route(route["id"], DISPATCHER)
    assert res.status_code == 200
    optimized = validate_success(res, 200)
    assert optimized["optimized_sequence"] == []


# ─── Corner: route_optimize ordering ───────────────────

def test_route_optimize_orders_by_window_then_created_at(api):
    """PRD §3.4: "The optimized_sequence is the list of work_order_id values for the route's
    SCHEDULED and DISPATCHED work orders, ordered by window_start_minute ascending and
    breaking ties by created_at ascending; no other ordering key is used".

    Design: Corner/calculations/route_optimize_orders_by_window_then_created_at
    """
    account = create_account()
    site1 = create_site(account["id"], address="21a Pine")
    site2 = create_site(account["id"], address="21b Pine")
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-07")
    # WO_late created/scheduled first at window 600; WO_early scheduled second at window 540.
    wo_late = get_success_data(api.create_work_order(
        create_work_order_payload(site1["id"], "PUMPING", "2026-07-07", 600, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo_late["id"], {"route_id": route["id"]}, DISPATCHER))
    wo_early = get_success_data(api.create_work_order(
        create_work_order_payload(site2["id"], "PUMPING", "2026-07-07", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo_early["id"], {"route_id": route["id"]}, DISPATCHER))
    optimized = validate_success(api.optimize_route(route["id"], DISPATCHER), 200)
    assert optimized["optimized_sequence"] == [wo_early["id"], wo_late["id"]]
    assert optimized["assigned_stop_count"] == 2
