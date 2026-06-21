"""State-machine transitions: invalid transitions, guarded transitions, immutability,
non-linear (revert) and cyclic (permit reopen) flows.

Translates queue B `state_machines` instances and queue A `non_linear_state_machine`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS,
    create_work_order_payload,
    create_account, create_site, create_technician, create_route,
    setup_account_site_tech_route, create_completed_inspection_wo,
    create_inspection_report, finalize_inspection_report, create_permit_filing,
    create_started_work_order, set_clock, get_work_order,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Corner: state_machines ────────────────────────────

def test_dispatch_from_draft_returns_invalid_state(api):
    """PRD §3.3: "Attempting any transition from a status that does not define it is
    rejected with ERR_INVALID_STATE".

    Design: Corner/state_machines/dispatch_from_draft_returns_invalid_state
    """
    account = create_account()
    site = create_site(account["id"])
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-03", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    res = api.dispatch_work_order(wo["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_dispatch_suspended_technician_returns_tech_suspended(api):
    """PRD §3.11: "Dispatching a work order requires that the work order's technician_id
    reference the route's technician_id and that that technician's status be ACTIVE;
    dispatching to a suspended technician is rejected with ERR_TECH_SUSPENDED."

    Design: Corner/state_machines/dispatch_suspended_technician_returns_tech_suspended
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-04")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-07-04", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    get_success_data(api.suspend_technician(tech["id"], DISPATCHER))
    res = api.dispatch_work_order(wo["id"], DISPATCHER)
    validate_error(res, "ERR_TECH_SUSPENDED", expected_status=409)


def test_finalize_report_on_incomplete_work_order_returns_invalid_state(api):
    """PRD §3.8: "Finalizing a report advances its status from DRAFT to FINALIZED and
    requires that a result be supplied and that the linked work order be COMPLETED with a
    work_type of INSPECTION."

    Design: Corner/state_machines/finalize_report_on_incomplete_work_order_returns_invalid_state
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-07-05")
    # WO only started (IN_PROGRESS), never completed.
    wo = create_started_work_order(
        site["id"], route["id"], tech["id"], "2026-07-05", 540, work_type="INSPECTION"
    )
    report = create_inspection_report(wo["id"], defect_count=0)
    res = api.finalize_inspection_report(report["id"], {"result": "PASS"}, COMPLIANCE)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_edit_finalized_report_returns_immutable(api):
    """PRD §3.8: "Editing a report that is no longer DRAFT is rejected with ERR_IMMUTABLE."
    PRD §3.8: "A FINALIZED report is immutable and is what unlocks permit filing."

    Design: Corner/state_machines/edit_finalized_report_returns_immutable
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    report = finalize_inspection_report(report["id"], "PASS")
    res = api.patch_inspection_report(report["id"], {"defect_count": 9}, COMPLIANCE)
    validate_error(res, "ERR_IMMUTABLE", expected_status=409)


# ─── Difficulty: non_linear_state_machine (>=2 tests each) ─

def test_work_order_dispatched_revert_to_scheduled(api):
    """PRD §3.3: "A Dispatcher may revert DISPATCHED -> SCHEDULED, which clears
    technician_id and returns the order to the schedule".

    Design: Difficulty/non_linear_state_machine/work_order_dispatched_revert_to_scheduled
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-13")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-13", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    get_success_data(api.dispatch_work_order(wo["id"], DISPATCHER))
    res = api.revert_work_order(wo["id"], DISPATCHER)
    reverted = validate_success(res, 200)
    assert reverted["status"] == "SCHEDULED"
    assert reverted["technician_id"] is None


def test_work_order_revert_clears_then_redispatch_possible(api):
    """PRD §3.3: "A Dispatcher may revert DISPATCHED -> SCHEDULED, which clears
    technician_id and returns the order to the schedule".
    PRD §3.3: "Dispatching advances SCHEDULED -> DISPATCHED: a Dispatcher performs it, the
    work order's technician_id is set from the route's technician_id".

    Design: Difficulty/non_linear_state_machine/work_order_dispatched_revert_to_scheduled
    """
    account = create_account()
    site = create_site(account["id"])
    tech = create_technician()
    route = create_route(tech["id"], "2026-06-13")
    wo = get_success_data(api.create_work_order(
        create_work_order_payload(site["id"], "PUMPING", "2026-06-13", 540, estimated_gallons=500),
        DISPATCHER,
    ))
    get_success_data(api.schedule_work_order(wo["id"], {"route_id": route["id"]}, DISPATCHER))
    get_success_data(api.dispatch_work_order(wo["id"], DISPATCHER))
    get_success_data(api.revert_work_order(wo["id"], DISPATCHER))
    # The backward edge re-enables re-dispatch.
    res = api.dispatch_work_order(wo["id"], DISPATCHER)
    redispatched = validate_success(res, 200)
    assert redispatched["status"] == "DISPATCHED"
    assert redispatched["technician_id"] == tech["id"]


def test_permit_filing_rejected_reopen_resubmit_cycle(api):
    """PRD §3.9: "A ComplianceOfficer may reopen a REJECTED filing, advancing
    REJECTED -> DRAFT so it can be resubmitted — the resubmission loop that lets a filing
    pass through REJECTED -> DRAFT -> SUBMITTED again."
    PRD §3.9: "On a successful submit the submission_count increments by one".

    Design: Difficulty/non_linear_state_machine/permit_filing_rejected_reopen_resubmit_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    report = finalize_inspection_report(report["id"], "PASS")
    filing = create_permit_filing(report["id"], base["site"]["id"])
    set_clock("2026-06-05T00:00:00Z")
    get_success_data(api.submit_permit_filing(filing["id"], COMPLIANCE))
    get_success_data(api.decide_permit_filing(
        filing["id"], {"decision": "REJECT", "decision_reason": "missing sketch"}, COMPLIANCE
    ))
    get_success_data(api.reopen_permit_filing(filing["id"], COMPLIANCE))
    res = api.submit_permit_filing(filing["id"], COMPLIANCE)
    resubmitted = validate_success(res, 200)
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["submission_count"] == 2


def test_permit_filing_reject_returns_to_draft_on_reopen(api):
    """PRD §3.9: "A reject decision advances SUBMITTED -> REJECTED, stores the
    decision_reason".
    PRD §3.9: "A ComplianceOfficer may reopen a REJECTED filing, advancing REJECTED ->
    DRAFT so it can be resubmitted".

    Design: Difficulty/non_linear_state_machine/permit_filing_rejected_reopen_resubmit_cycle
    """
    set_clock("2026-06-01T00:00:00Z")
    base = setup_account_site_tech_route("2026-06-02")
    wo = create_completed_inspection_wo(base, "2026-06-02", 540)
    report = create_inspection_report(wo["id"], defect_count=0)
    report = finalize_inspection_report(report["id"], "PASS")
    filing = create_permit_filing(report["id"], base["site"]["id"])
    set_clock("2026-06-05T00:00:00Z")
    get_success_data(api.submit_permit_filing(filing["id"], COMPLIANCE))
    rejected = validate_success(
        api.decide_permit_filing(filing["id"], {"decision": "REJECT", "decision_reason": "missing sketch"}, COMPLIANCE),
        200,
    )
    assert rejected["status"] == "REJECTED"
    reopened = validate_success(api.reopen_permit_filing(filing["id"], COMPLIANCE), 200)
    assert reopened["status"] == "DRAFT"
