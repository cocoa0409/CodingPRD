"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch against an empty database
using only PRD-declared endpoints, threading entity-backed identities through
the per-instance header builders. Setup calls use get_success_data() so a
failed precondition surfaces as a clear setup error, not an assertion maze.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allowance_line_payload,
    create_change_order_payload,
    create_contractor_payload,
    create_design_package_payload,
    create_homeowner_payload,
    create_inspection_payload,
    create_moisture_assessment_payload,
    create_permit_payload,
    create_project_payload,
    create_site_log_payload,
    create_subcontractor_payload,
    create_work_phase_payload,
    reopen_moisture_assessment_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_contractor_headers,
    make_homeowner_headers,
    make_subcontractor_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Tier 0: identity anchors
# ---------------------------------------------------------------------------

def register_contractor(**overrides):
    """PlatformAdmin registers a contracting firm. Returns the Contractor."""
    res = api_client.create_contractor(create_contractor_payload(**overrides), ADMIN)
    return get_success_data(res)


def register_subcontractor(trade="GENERAL", **overrides):
    """PlatformAdmin registers a trade crew. Returns the Subcontractor."""
    res = api_client.create_subcontractor(
        create_subcontractor_payload(trade=trade, **overrides), ADMIN
    )
    return get_success_data(res)


def onboard_homeowner(ctr_headers, **overrides):
    """Contractor onboards a client. Returns the Homeowner."""
    res = api_client.create_homeowner(create_homeowner_payload(**overrides), ctr_headers)
    return get_success_data(res)


def set_logical_clock(to_iso8601: str):
    """PlatformAdmin sets the logical clock, triggering the expiry sweep."""
    res = api_client.set_clock(set_clock_payload(to_iso8601), ADMIN)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 1/2: project corridor (INTAKE -> ASSESSMENT -> DESIGN -> PERMITTING
#           -> SCHEDULING -> IN_PROGRESS)
# ---------------------------------------------------------------------------

def setup_intake_project(base_contract_cents=4_000_000, **project_overrides):
    """Contractor + homeowner + fresh INTAKE project.

    Returns dict(contractor, homeowner, project).
    """
    ctr = register_contractor()
    ctr_h = make_contractor_headers(ctr["id"])
    ho = onboard_homeowner(ctr_h)
    proj = get_success_data(
        api_client.create_project(
            create_project_payload(
                ho["id"], base_contract_cents=base_contract_cents, **project_overrides
            ),
            ctr_h,
        )
    )
    return {"contractor": ctr, "homeowner": ho, "project": proj}


def create_accepted_assessment(project_id, ctr_headers, **assessment_overrides):
    """Create + submit a benign assessment; returns the ACCEPTED assessment."""
    ma = get_success_data(
        api_client.create_moisture_assessment(
            project_id, create_moisture_assessment_payload(**assessment_overrides),
            ctr_headers,
        )
    )
    res = api_client.submit_moisture_assessment(ma["id"], ctr_headers)
    return get_success_data(res)


def setup_design_project(**kw):
    """Project walked to DESIGN via an accepted screening assessment."""
    ctx = setup_intake_project(**kw)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ctx["assessment"] = create_accepted_assessment(ctx["project"]["id"], ctr_h)
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], ctr_h)
    )
    return ctx


def create_approved_design(project_id, ctr_headers, ho_headers, **design_overrides):
    """Create + submit + homeowner-approve a design package. Returns APPROVED package."""
    dp = get_success_data(
        api_client.create_design_package(
            project_id, create_design_package_payload(**design_overrides), ctr_headers
        )
    )
    get_success_data(api_client.submit_design_package(dp["id"], ctr_headers))
    res = api_client.approve_design_package(dp["id"], ho_headers)
    return get_success_data(res)


def setup_permitting_project(**kw):
    """Project walked to PERMITTING (approved design package pinned on project)."""
    ctx = setup_design_project(**kw)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ho_h = make_homeowner_headers(ctx["homeowner"]["id"])
    ctx["design"] = create_approved_design(ctx["project"]["id"], ctr_h, ho_h)
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], ctr_h)
    )
    return ctx


def create_issued_permit(project_id, ctr_headers, **permit_overrides):
    """Create + submit + inspector-ISSUED permit. Returns the ISSUED permit."""
    pm = get_success_data(
        api_client.create_permit(
            project_id, create_permit_payload(**permit_overrides), ctr_headers
        )
    )
    get_success_data(api_client.submit_permit(pm["id"], ctr_headers))
    res = api_client.record_permit_decision(pm["id"], {"outcome": "ISSUED"}, INSPECTOR)
    return get_success_data(res)


def setup_scheduling_project(permit_overrides=None, **kw):
    """Project walked to SCHEDULING via an issued permit."""
    ctx = setup_permitting_project(**kw)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    ctx["permit"] = create_issued_permit(
        ctx["project"]["id"], ctr_h, **(permit_overrides or {})
    )
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], ctr_h)
    )
    return ctx


def create_started_phase(project_id, ctr_headers, subcontractor, **phase_overrides):
    """Create a phase and have the assigned subcontractor start it.

    Returns the IN_PROGRESS phase. Also moves a SCHEDULING project to
    IN_PROGRESS on first start.
    """
    wp = get_success_data(
        api_client.create_work_phase(
            project_id,
            create_work_phase_payload(subcontractor["id"], **phase_overrides),
            ctr_headers,
        )
    )
    res = api_client.start_work_phase(
        wp["id"], make_subcontractor_headers(subcontractor["id"])
    )
    return get_success_data(res)


def setup_in_progress_project(trade="PAINT", zone="REC", clock_iso=None,
                              phase_overrides=None, **kw):
    """Project walked to IN_PROGRESS with one started phase.

    Returns ctx with added subcontractor + phase. If clock_iso is given, the
    logical clock is set afterwards (site-log dating needs clock >= work_date).
    """
    ctx = setup_scheduling_project(**kw)
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    sub = register_subcontractor(trade=trade)
    ctx["subcontractor"] = sub
    ctx["phase"] = create_started_phase(
        ctx["project"]["id"], ctr_h, sub,
        trade=trade, zone=zone, **(phase_overrides or {}),
    )
    ctx["project"] = get_success_data(
        api_client.get_project(ctx["project"]["id"], ctr_h)
    )
    if clock_iso:
        set_logical_clock(clock_iso)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3/4: suspension and completion
# ---------------------------------------------------------------------------

def file_site_log(project_id, subcontractor_id, work_date, **overrides):
    """Subcontractor files a daily log. Returns the created DailySiteLog."""
    res = api_client.create_site_log(
        project_id,
        create_site_log_payload(work_date=work_date, **overrides),
        make_subcontractor_headers(subcontractor_id),
    )
    return get_success_data(res)


def file_violation_log(project_id, subcontractor_id, work_date):
    """File a violation log (containment breached). Returns the DailySiteLog."""
    return file_site_log(
        project_id, subcontractor_id, work_date, containment_intact=False
    )


def setup_suspended_project(clock_iso="2026-06-05T00:00:00Z",
                            violation_dates=("2026-06-03", "2026-06-04", "2026-06-05"),
                            **kw):
    """IN_PROGRESS project suspended by three in-window violation logs."""
    ctx = setup_in_progress_project(clock_iso=clock_iso, **kw)
    proj_id = ctx["project"]["id"]
    sub_id = ctx["subcontractor"]["id"]
    ctx["logs"] = [
        file_violation_log(proj_id, sub_id, d) for d in violation_dates
    ]
    ctx["project"] = get_success_data(
        api_client.get_project(proj_id, make_contractor_headers(ctx["contractor"]["id"]))
    )
    return ctx


def setup_completed_project(clock_iso="2026-06-10T00:00:00Z", **kw):
    """Full lifecycle through COMPLETED with the certificate issued.

    Uses a GENERAL phase (no rough-in gate) started and completed, then a
    FINAL inspection passed by the inspector at clock_iso.
    Returns ctx with added inspection + certificate.
    """
    kw.setdefault("trade", "GENERAL")
    kw.setdefault("phase_overrides", {"start_date": "2026-06-01", "end_date": "2026-06-08"})
    ctx = setup_in_progress_project(**kw)
    proj_id = ctx["project"]["id"]
    ctr_h = make_contractor_headers(ctx["contractor"]["id"])
    sub_h = make_subcontractor_headers(ctx["subcontractor"]["id"])
    get_success_data(api_client.complete_work_phase(ctx["phase"]["id"], sub_h))
    set_logical_clock(clock_iso)
    insp = get_success_data(
        api_client.create_inspection(
            proj_id, create_inspection_payload(type="FINAL"), ctr_h
        )
    )
    ctx["inspection"] = get_success_data(
        api_client.record_inspection_result(insp["id"], {"outcome": "PASSED"}, INSPECTOR)
    )
    certs, _meta = _list_certificates(proj_id, ctr_h)
    ctx["certificate"] = certs[0]
    ctx["project"] = get_success_data(api_client.get_project(proj_id, ctr_h))
    return ctx


def _list_certificates(project_id, headers):
    res = api_client.list_certificates(project_id, headers)
    body = res.json()
    return body["data"], body.get("meta", {})


# ---------------------------------------------------------------------------
# Tier 5: fiscal helpers (change orders under optimistic concurrency)
# ---------------------------------------------------------------------------

def get_project_version(project_id, headers):
    """Read the project's current version for the OCC checkpoint (PRD §2.8)."""
    return get_success_data(api_client.get_project(project_id, headers))["version"]


def create_change_order_fresh(project_id, ctr_headers, **overrides):
    """Create a change order carrying the project's freshly read version."""
    version = get_project_version(project_id, ctr_headers)
    res = api_client.create_change_order(
        project_id,
        create_change_order_payload(version, **overrides),
        ctr_headers,
    )
    return get_success_data(res)


def get_only_allowance_line(project_id, headers):
    """Read back the project's single allowance line."""
    res = api_client.list_allowance_lines(project_id, headers)
    data = res.json()["data"]
    assert len(data) == 1, f"expected exactly one allowance line, got {len(data)}"
    return data[0]
