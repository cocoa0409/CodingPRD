"""Composite setup helpers.

Each helper builds a slice of domain state from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so nothing is
carried over). Setup calls use get_success_data() so a setup failure surfaces
as a clear "Setup step failed" error naming the offending step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_certification_payload,
    create_complaint_payload,
    create_contractor_payload,
    create_customer_payload,
    create_inspection_payload,
    create_inspector_payload,
    create_lead_payload,
    create_program_payload,
    create_project_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_inspector_headers,
)

PM = TEST_USERS["program_manager_headers"]


def _ok(resp, step: str):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at step [{step}]: {exc}")


def set_clock(to_iso8601: str = "2026-08-01T00:00:00Z"):
    """Advance the logical clock (PRD 2.5). Returns the clock response data."""
    return _ok(api_client.set_clock(to_iso8601, PM), f"set_clock({to_iso8601})")


def create_active_program(**overrides) -> dict:
    """Create a program and activate it. Returns the ACTIVE program."""
    prog = _ok(api_client.create_program(create_program_payload(**overrides), PM),
               "create_program")
    activated = _ok(api_client.activate_program(prog["id"], PM), "activate_program")
    return activated


def get_program(program_id: str) -> dict:
    return _ok(api_client.get_program(program_id, PM), "get_program")


def create_contractor_with_cert(measure_type: str = "HVAC", approve: bool = True,
                                cert_overrides: dict = None,
                                contractor_overrides: dict = None) -> dict:
    """Create a contractor, issue one certification, optionally approve.

    Returns dict with keys: contractor, certification.
    """
    ctr = _ok(
        api_client.create_contractor(
            create_contractor_payload(**(contractor_overrides or {})), PM),
        "create_contractor",
    )
    cert_payload = create_certification_payload(
        ctr["id"], measure_type=measure_type, **(cert_overrides or {}))
    cert = _ok(api_client.create_certification(cert_payload, PM), "create_certification")
    if approve:
        ctr = _ok(api_client.approve_contractor(ctr["id"], PM), "approve_contractor")
    return {"contractor": ctr, "certification": cert}


def create_customer(**overrides) -> dict:
    return _ok(api_client.create_customer(create_customer_payload(**overrides), PM),
               "create_customer")


def create_lead(customer_id: str, program_id: str, **overrides) -> dict:
    """Create a lead (program must be ACTIVE — PRD 3.3)."""
    return _ok(
        api_client.create_lead(create_lead_payload(customer_id, program_id, **overrides), PM),
        "create_lead",
    )


def distribute_lead(lead_id: str, expected_lead_version: int) -> dict:
    """Run the selector. Returns the OFFERED lead."""
    return _ok(api_client.distribute_lead(lead_id, expected_lead_version, PM),
               "distribute_lead")


def accept_lead(lead_id: str, contractor_id: str) -> dict:
    """Assigned contractor accepts (entity-backed identity). Returns ACCEPTED lead."""
    return _ok(
        api_client.accept_lead(lead_id, make_contractor_headers(contractor_id)),
        "accept_lead",
    )


def create_accepted_lead(customer_id: str, program_id: str, contractor_id: str = None,
                         **lead_overrides) -> dict:
    """Create a lead, distribute it, and have the assigned contractor accept it.

    Acceptance is always performed by the contractor the platform named in
    `assigned_contractor_id` (PRD 3.3: "Acceptance belongs to the assigned
    firm ... only when the caller is the contractor named in
    `assigned_contractor_id`"). The selector's PRD tie chain (qa_score_bps
    DESC, complaint_count_90d ASC, created_at ASC) can exhaust on identical
    values when several contractors qualify (frozen logical clock), so which
    candidate wins is then platform-chosen — never assume a particular winner.
    Returns the ACCEPTED lead.
    """
    lead = create_lead(customer_id, program_id, **lead_overrides)
    offered = distribute_lead(lead["id"], lead["version"])
    return accept_lead(lead["id"], offered["assigned_contractor_id"])


def create_project(lead_id: str, customer_id: str, contractor_id: str,
                   program_id: str, **overrides) -> dict:
    """Create a project (born PROPOSED — PRD 3.4)."""
    return _ok(
        api_client.create_project(
            create_project_payload(lead_id, customer_id, contractor_id, program_id, **overrides),
            PM),
        "create_project",
    )


def approve_project(project_id: str, program_id: str) -> dict:
    """Approve a project, reading the program's current version for the OCC
    expected_program_version field (PRD 2.7). Returns the APPROVED project."""
    version = get_program(program_id)["version"]
    return _ok(api_client.approve_project(project_id, version, PM), "approve_project")


def create_proposed_project(program_id: str = None, contractor_id: str = None,
                            customer_id: str = None, program_overrides: dict = None,
                            project_overrides: dict = None,
                            lead_overrides: dict = None) -> dict:
    """Tier-2 hierarchy: ACTIVE program + APPROVED contractor (HVAC cert) +
    customer + ACCEPTED lead + PROPOSED project.

    Returns dict: program, contractor, certification, customer, lead, project.
    Any of program/contractor/customer may be supplied by id to reuse existing
    entities.
    """
    program = get_program(program_id) if program_id else create_active_program(
        **(program_overrides or {}))
    if contractor_id:
        contractor = _ok(api_client.get_contractor(contractor_id, PM), "get_contractor")
        certification = None
    else:
        bundle = create_contractor_with_cert()
        contractor, certification = bundle["contractor"], bundle["certification"]
    customer = _ok(api_client.get_customer(customer_id, PM), "get_customer") \
        if customer_id else create_customer()
    lead = create_accepted_lead(customer["id"], program["id"], contractor["id"],
                                **(lead_overrides or {}))
    project = create_project(lead["id"], customer["id"], contractor["id"],
                             program["id"], **(project_overrides or {}))
    return {
        "program": program,
        "contractor": contractor,
        "certification": certification,
        "customer": customer,
        "lead": lead,
        "project": project,
    }


def create_approved_project(project_overrides: dict = None, **kwargs) -> dict:
    """create_proposed_project + approve. Adds 'payment' key (the DRAFT shell
    created atomically at approval — PRD 3.4)."""
    ctx = create_proposed_project(project_overrides=project_overrides, **kwargs)
    ctx["project"] = approve_project(ctx["project"]["id"], ctx["program"]["id"])
    ctx["program"] = get_program(ctx["program"]["id"])
    payments, _meta = _list_payments_for_project(ctx["project"]["id"])
    ctx["payment"] = payments[0] if payments else None
    return ctx


def _list_payments_for_project(project_id: str):
    resp = api_client.list_incentive_payments(PM, params={"project_id": project_id})
    data = get_success_data(resp)
    meta = resp.json().get("meta", {})
    return data, meta


def create_inspector(**overrides) -> dict:
    return _ok(api_client.create_inspector(create_inspector_payload(**overrides), PM),
               "create_inspector")


def create_work_order(project_id: str, contractor_id: str, **overrides) -> dict:
    """Contractor raises a work order for an APPROVED project (PRD 3.5)."""
    return _ok(
        api_client.create_work_order(
            project_id, create_work_order_payload(contractor_id, **overrides),
            make_contractor_headers(contractor_id)),
        "create_work_order",
    )


def complete_work_order(work_order_id: str, contractor_id: str,
                        clock_before_start: str = None) -> dict:
    """Start + complete a SCHEDULED work order as its owning contractor.

    Reads the order's scheduled_on and advances the logical clock to that date
    (start requires the clock date to equal the scheduled date — PRD 3.5).
    Returns the COMPLETED work order (with assigned_inspector_id populated).
    """
    wo = _ok(api_client.get_work_order(work_order_id, PM), "get_work_order")
    sched_date = wo["scheduled_on"][:10]
    set_clock(clock_before_start or f"{sched_date}T09:00:00Z")
    hdrs = make_contractor_headers(contractor_id)
    _ok(api_client.start_work_order(work_order_id, hdrs), "start_work_order")
    return _ok(api_client.complete_work_order(work_order_id, hdrs), "complete_work_order")


def create_installed_project(install_date: str = None,
                             inspection_date: str = None, **kwargs) -> dict:
    """Full lifecycle through INSTALLED: approved project + work order +
    inspector registered + work order completed (project auto-advances
    SCHEDULED -> INSTALLED and the platform assigns the inspector).

    Adds keys: work_order, inspector.
    """
    ctx = create_approved_project(**kwargs)
    ctr_id = ctx["contractor"]["id"]
    wo = create_work_order(
        ctx["project"]["id"], ctr_id,
        **({"scheduled_on": install_date} if install_date else {}))
    inspector = create_inspector()
    wo = complete_work_order(wo["id"], ctr_id)
    ctx["work_order"] = wo
    ctx["inspector"] = inspector
    ctx["project"] = _ok(api_client.get_project(ctx["project"]["id"], PM), "get_project")
    return ctx


def schedule_inspection(work_order_id: str, project_id: str, inspector_id: str,
                        scheduled_on: str = None) -> dict:
    """Assigned inspector schedules an inspection (project INSTALLED|REMEDIATION
    -> INSPECTING — PRD 3.6)."""
    payload = create_inspection_payload(
        work_order_id, project_id, inspector_id,
        **({"scheduled_on": scheduled_on} if scheduled_on else {}))
    return _ok(
        api_client.create_inspection(payload, make_inspector_headers(inspector_id)),
        "create_inspection",
    )


def record_inspection(inspection_id: str, inspector_id: str, outcome: str = "PASS",
                      score_bps: int = 9000, failure_reasons=None) -> dict:
    """Assigned inspector records the outcome (PRD 3.6)."""
    payload = {"outcome": outcome, "score_bps": score_bps}
    if failure_reasons is not None:
        payload["failure_reasons"] = failure_reasons
    return _ok(
        api_client.record_inspection(inspection_id, payload,
                                     make_inspector_headers(inspector_id)),
        "record_inspection",
    )


def create_inspecting_project(**kwargs) -> dict:
    """Through INSPECTING: installed project + one SCHEDULED inspection.

    The inspection is scheduled by the inspector the platform assigned at
    work-order completion (PRD 3.5-3.6: the acting inspector must match the
    order's assigned_inspector_id), which may be an earlier-registered
    inspector when several exist.

    Adds key: inspection; refreshes 'inspector' to the assigned inspector.
    """
    ctx = create_installed_project(**kwargs)
    assigned = ctx["work_order"].get("assigned_inspector_id") or ctx["inspector"]["id"]
    inspection = schedule_inspection(
        ctx["work_order"]["id"], ctx["project"]["id"], assigned)
    ctx["inspection"] = inspection
    ctx["inspector"] = _ok(api_client.get_inspector(assigned, PM), "get_inspector")
    ctx["project"] = _ok(api_client.get_project(ctx["project"]["id"], PM), "get_project")
    return ctx


def create_completed_project(pass_score_bps: int = 9000, **kwargs) -> dict:
    """Full lifecycle through COMPLETED via a PASS inspection. The payment is
    finalized (DRAFT -> AUTHORIZED) in the same step (PRD 3.6, 3.7).

    Refreshes: project, contractor, payment.
    """
    ctx = create_inspecting_project(**kwargs)
    record_inspection(ctx["inspection"]["id"], ctx["inspector"]["id"],
                      outcome="PASS", score_bps=pass_score_bps)
    ctx["project"] = _ok(api_client.get_project(ctx["project"]["id"], PM), "get_project")
    ctx["contractor"] = _ok(
        api_client.get_contractor(ctx["contractor"]["id"], PM), "get_contractor")
    payments, _ = _list_payments_for_project(ctx["project"]["id"])
    ctx["payment"] = payments[0] if payments else None
    return ctx


def create_failed_inspection_project(fail_score_bps: int = 8000,
                                     failure_reasons=None, **kwargs) -> dict:
    """Through REMEDIATION: inspecting project + FAIL recorded.

    Adds keys after refresh: project (REMEDIATION), inspection (RECORDED),
    contractor.
    """
    ctx = create_inspecting_project(**kwargs)
    record_inspection(
        ctx["inspection"]["id"], ctx["inspector"]["id"],
        outcome="FAIL", score_bps=fail_score_bps,
        failure_reasons=failure_reasons or ["BAD_SEAL"])
    ctx["project"] = _ok(api_client.get_project(ctx["project"]["id"], PM), "get_project")
    ctx["inspection"] = _ok(
        api_client.get_inspection(ctx["inspection"]["id"], PM), "get_inspection")
    ctx["contractor"] = _ok(
        api_client.get_contractor(ctx["contractor"]["id"], PM), "get_contractor")
    return ctx


def create_complaint(customer_id: str, contractor_id: str, **overrides) -> dict:
    return _ok(
        api_client.create_complaint(
            create_complaint_payload(customer_id, contractor_id, **overrides), PM),
        "create_complaint",
    )
