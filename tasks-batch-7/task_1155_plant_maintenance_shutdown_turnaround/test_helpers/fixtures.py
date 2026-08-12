"""Composite setup helpers — multi-step preambles shared across tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use get_success_data() (lenient) so a setup failure
surfaces as a clear "Setup failed" error rather than a confusing assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_turnaround_payload,
    create_work_item_payload,
    create_contractor_payload,
    create_worker_payload,
    create_shift_payload,
    create_isolation_payload,
    create_permit_payload,
    create_discovery_payload,
    create_laydown_area_payload,
    create_reservation_payload,
    create_daily_report_payload,
    create_report_line,
    create_punch_item_payload,
)
from .test_users import (
    TEST_USERS,
    make_supervisor_headers,
    make_manager_headers,
    make_controller_headers,
)

MANAGER = TEST_USERS["manager_headers"]
PLANNER = TEST_USERS["planner_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
OPERATIONS = TEST_USERS["operations_headers"]


# ---------------------------------------------------------------------------
# Tier 1: Turnaround state progression
# ---------------------------------------------------------------------------

def create_turnaround(**overrides):
    """Create a turnaround in PLANNING. Returns the turnaround dict."""
    resp = api_client.create_turnaround(create_turnaround_payload(**overrides), MANAGER)
    return get_success_data(resp)


def create_turnaround_with_item(work_item_overrides=None, **ta_overrides):
    """Turnaround in PLANNING + one PROPOSED work item. Returns (turnaround, item)."""
    ta = create_turnaround(**ta_overrides)
    item = get_success_data(api_client.create_work_item(
        ta["id"], create_work_item_payload(**(work_item_overrides or {})), PLANNER))
    return ta, item


def freeze_turnaround(turnaround_id, scope_cutoff_count=1):
    """Freeze scope on a turnaround. Returns the updated turnaround."""
    return get_success_data(api_client.freeze_scope(
        turnaround_id, {"scope_cutoff_count": scope_cutoff_count}, MANAGER))


def advance_turnaround(turnaround_id):
    return get_success_data(api_client.advance_turnaround(turnaround_id, MANAGER))


def setup_scope_frozen(num_items=1, scope_cutoff_count=1, **ta_overrides):
    """Turnaround SCOPE_FROZEN with num_items work items (first scope_cutoff_count FROZEN).

    Returns (turnaround, [items]).
    """
    ta = create_turnaround(**ta_overrides)
    items = []
    for i in range(num_items):
        items.append(get_success_data(api_client.create_work_item(
            ta["id"],
            create_work_item_payload(title=f"Item {i+1}", system_area=f"AREA-{i+1}"),
            PLANNER)))
    ta = freeze_turnaround(ta["id"], scope_cutoff_count)
    return ta, items


# ---------------------------------------------------------------------------
# Tier 2: Contractor / worker hierarchy
# ---------------------------------------------------------------------------

def invite_contractor(turnaround_id, **overrides):
    """Invite a contractor. Returns the contractor dict."""
    return get_success_data(api_client.create_contractor(
        turnaround_id, create_contractor_payload(**overrides), MANAGER))


def register_worker(contractor_id, **overrides):
    """Register a worker under the contractor (ownership-gated on contractor id)."""
    return get_success_data(api_client.register_worker(
        contractor_id, create_worker_payload(**overrides),
        make_supervisor_headers(contractor_id)))


def vet_and_badge_worker(worker_id):
    """REGISTERED -> VETTED -> BADGED. Returns the BADGED worker."""
    get_success_data(api_client.vet_worker(worker_id, COORDINATOR))
    return get_success_data(api_client.badge_worker(worker_id, COORDINATOR))


def mobilize_contractor_once(contractor_id):
    """One mobilization step (INVITED->MOBILIZING or MOBILIZING->MOBILIZED)."""
    return get_success_data(api_client.mobilize_contractor(
        contractor_id, make_supervisor_headers(contractor_id)))


def setup_contractor_mobilized(turnaround_id, num_workers=1, **contractor_overrides):
    """Invite a contractor, move to MOBILIZING, register+badge workers, reach MOBILIZED.

    Requires the turnaround to already be in MOBILIZATION or EXECUTION.
    Returns (contractor, [workers]).
    """
    contractor = invite_contractor(turnaround_id, **contractor_overrides)
    mobilize_contractor_once(contractor["id"])  # INVITED -> MOBILIZING
    workers = []
    for i in range(num_workers):
        w = register_worker(contractor["id"], full_name=f"Worker {i+1}")
        workers.append(vet_and_badge_worker(w["id"]))
    contractor = mobilize_contractor_once(contractor["id"])  # MOBILIZING -> MOBILIZED
    return contractor, workers


# ---------------------------------------------------------------------------
# Tier 3: Full lifecycle shortcuts — turnaround to EXECUTION
# ---------------------------------------------------------------------------

def setup_execution_turnaround(num_items=1, scope_cutoff_count=1, num_workers=1,
                               work_item_overrides=None, **ta_overrides):
    """Turnaround advanced all the way to EXECUTION with one MOBILIZED contractor.

    Chain: create -> work items -> freeze -> contractor -> advance (MOBILIZATION)
    -> mobilize -> workers -> vet/badge -> mobilize (MOBILIZED) -> advance (EXECUTION).

    Returns dict with keys: turnaround, items, contractor, workers.
    """
    ta = create_turnaround(**ta_overrides)
    items = []
    for i in range(num_items):
        ov = dict(work_item_overrides or {})
        ov.setdefault("title", f"Item {i+1}")
        ov.setdefault("system_area", f"AREA-{i+1}")
        items.append(get_success_data(api_client.create_work_item(
            ta["id"], create_work_item_payload(**ov), PLANNER)))
    ta = freeze_turnaround(ta["id"], scope_cutoff_count)
    advance_turnaround(ta["id"])  # SCOPE_FROZEN -> MOBILIZATION
    contractor, workers = setup_contractor_mobilized(ta["id"], num_workers=num_workers)
    ta = advance_turnaround(ta["id"])  # MOBILIZATION -> EXECUTION
    return {
        "turnaround": ta,
        "items": items,
        "contractor": contractor,
        "workers": workers,
    }


def schedule_and_start_work_item(work_item_id, contractor_id):
    """FROZEN -> SCHEDULED -> IN_PROGRESS. Returns the IN_PROGRESS work item."""
    get_success_data(api_client.schedule_work_item(work_item_id, PLANNER))
    return get_success_data(api_client.start_work_item(
        work_item_id, make_supervisor_headers(contractor_id)))


def complete_work_item(work_item_id, contractor_id, actual_hours):
    return get_success_data(api_client.complete_work_item(
        work_item_id, {"actual_hours": actual_hours}, make_supervisor_headers(contractor_id)))


def verify_work_item(work_item_id, outcome="VERIFIED"):
    return get_success_data(api_client.verify_work_item(
        work_item_id, {"outcome": outcome}, OPERATIONS))


def walk_work_item_to_verified(work_item_id, contractor_id, actual_hours=9):
    """FROZEN -> SCHEDULED -> IN_PROGRESS -> COMPLETE -> VERIFIED (no permit path)."""
    schedule_and_start_work_item(work_item_id, contractor_id)
    complete_work_item(work_item_id, contractor_id, actual_hours)
    return verify_work_item(work_item_id, "VERIFIED")


# ---------------------------------------------------------------------------
# Tier 3b: Permit / isolation setups
# ---------------------------------------------------------------------------

def create_verified_isolation(turnaround_id, **overrides):
    """Create an isolation and walk PLANNED -> ISOLATED -> VERIFIED."""
    iso = get_success_data(api_client.create_isolation(
        turnaround_id, create_isolation_payload(**overrides), COORDINATOR))
    get_success_data(api_client.transition_isolation(iso["id"], {"to": "ISOLATED"}, COORDINATOR))
    return get_success_data(api_client.transition_isolation(
        iso["id"], {"to": "VERIFIED"}, COORDINATOR))


def create_permit_for_item(work_item_id, isolation_ids=None, **overrides):
    """Request a permit on a work item. Returns the REQUESTED permit."""
    payload = create_permit_payload(**overrides)
    payload["required_isolation_ids"] = list(isolation_ids or [])
    return get_success_data(api_client.create_permit(work_item_id, payload, COORDINATOR))


def issue_permit(permit_id):
    return get_success_data(api_client.transition_permit(permit_id, {"to": "ISSUED"}, COORDINATOR))


def activate_permit(permit_id):
    return get_success_data(api_client.transition_permit(permit_id, {"to": "ACTIVE"}, COORDINATOR))


def setup_active_permit_scenario(clock="2026-06-15T09:00:00Z", **ta_overrides):
    """EXECUTION turnaround with W1 (requires_permit) SCHEDULED, I1 VERIFIED,
    P1 ISSUED then ACTIVATED under the given logical clock.

    Returns dict with turnaround, items ([W1]), contractor, workers, isolation, permit.
    """
    ctx = setup_execution_turnaround(
        num_items=1,
        work_item_overrides={"estimated_hours": 100, "estimated_cost_cents": 200000,
                             "requires_permit": True},
        **ta_overrides)
    t_id = ctx["turnaround"]["id"]
    w1 = ctx["items"][0]
    get_success_data(api_client.schedule_work_item(w1["id"], PLANNER))
    iso = create_verified_isolation(t_id)
    permit = create_permit_for_item(w1["id"], isolation_ids=[iso["id"]])
    set_clock(clock)
    issue_permit(permit["id"])
    permit = activate_permit(permit["id"])
    ctx["isolation"] = iso
    ctx["permit"] = permit
    return ctx


# ---------------------------------------------------------------------------
# Tier 3c: Shifts & assignments
# ---------------------------------------------------------------------------

def create_shift(turnaround_id, **overrides):
    return get_success_data(api_client.create_shift(
        turnaround_id, create_shift_payload(**overrides), PLANNER))


def assign_worker(shift_id, worker_id, planned_hours=8, headers=None):
    return get_success_data(api_client.create_assignment(
        shift_id, {"worker_id": worker_id, "planned_hours": planned_hours},
        headers or PLANNER))


# ---------------------------------------------------------------------------
# Tier 3d: Discovery helpers
# ---------------------------------------------------------------------------

def report_discovery(turnaround_id, reporter_user_id, reporter_headers=None, **overrides):
    """Report a discovery with an explicit reporter X-User-ID (SoD anchor)."""
    headers = reporter_headers or make_manager_headers(reporter_user_id)
    return get_success_data(api_client.create_discovery(
        turnaround_id, create_discovery_payload(**overrides), headers))


def triage_discovery(discovery_id):
    return get_success_data(api_client.triage_discovery(discovery_id, MANAGER))


def setup_triaged_discovery(turnaround_id, reporter_user_id="tm-100", **overrides):
    """Discovery REPORTED then TRIAGED. Returns the TRIAGED discovery."""
    d = report_discovery(turnaround_id, reporter_user_id, **overrides)
    return triage_discovery(d["id"])


# ---------------------------------------------------------------------------
# Tier 3e: Lay-down / reservation helpers
# ---------------------------------------------------------------------------

def create_laydown_area(turnaround_id, **overrides):
    return get_success_data(api_client.create_laydown_area(
        turnaround_id, create_laydown_area_payload(**overrides), MANAGER))


def create_reservation(area_id, expected_laydown_area_version, **overrides):
    payload = create_reservation_payload(**overrides)
    payload["expected_laydown_area_version"] = expected_laydown_area_version
    return get_success_data(api_client.create_reservation(area_id, payload, PLANNER))


# ---------------------------------------------------------------------------
# Tier 3f: Daily report helpers
# ---------------------------------------------------------------------------

def create_draft_report(turnaround_id, contractor_id, report_date, lines):
    payload = create_daily_report_payload(report_date=report_date, lines=lines)
    return get_success_data(api_client.create_daily_report(
        turnaround_id, payload, make_supervisor_headers(contractor_id)))


def submit_report(report_id, contractor_id):
    return get_success_data(api_client.submit_daily_report(
        report_id, make_supervisor_headers(contractor_id)))


def approve_report(report_id, approver_user_id="cc-1"):
    return get_success_data(api_client.approve_daily_report(
        report_id, make_controller_headers(approver_user_id)))


def setup_submitted_report(report_date="2026-06-15", hours=8, hazard=False,
                           clock="2026-06-15T21:00:00Z", **ta_overrides):
    """EXECUTION turnaround with a submitted report (one DAY-shift line).

    Returns dict with turnaround, items, contractor, workers, shift, report.
    """
    ctx = setup_execution_turnaround(num_items=1, **ta_overrides)
    t_id = ctx["turnaround"]["id"]
    contractor = ctx["contractor"]
    worker = ctx["workers"][0]
    shift = create_shift(t_id, shift_date=report_date)
    set_clock(clock)
    report = create_draft_report(
        t_id, contractor["id"], report_date,
        [create_report_line(worker["id"], shift["id"], hours, hazard)])
    report = submit_report(report["id"], contractor["id"])
    ctx["shift"] = shift
    ctx["report"] = report
    return ctx


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER))


# ---------------------------------------------------------------------------
# Tier 4: Punch list / handover
# ---------------------------------------------------------------------------

def setup_startup_turnaround(**ta_overrides):
    """Turnaround walked all the way to STARTUP with W1 VERIFIED and no live
    permits or isolations. Returns the execution context."""
    ctx = setup_execution_turnaround(num_items=1, **ta_overrides)
    t_id = ctx["turnaround"]["id"]
    w1 = ctx["items"][0]
    walk_work_item_to_verified(w1["id"], ctx["contractor"]["id"])
    ta = advance_turnaround(t_id)  # EXECUTION -> STARTUP
    ctx["turnaround"] = ta
    return ctx
