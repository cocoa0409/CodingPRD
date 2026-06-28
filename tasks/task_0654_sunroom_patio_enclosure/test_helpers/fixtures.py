"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear "Setup failed"
errors, not confusing assertion failures.

Identity threading: after creating a Homeowner (entity_backed), every ownership-gated call
(accept/reject quote, submit financing, resubmit permit, cancel project) uses
make_homeowner_headers(homeowner_id) — never the shared TEST_USERS["homeowner_headers"].

The pipeline reaches a testable state through this canonical chain:
  homeowner -> project -> measurement -> accept -> finalize-design -> quote ->
  accept(OCC) -> permit -> begin-review -> [engineering] -> decide(APPROVED) ->
  manufacture-order -> start -> ready -> crew -> install-job -> start -> complete ->
  inspection -> pass
Helpers stop at whatever stage a caller needs.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_homeowner_payload, create_project_payload, create_measurement_payload,
    create_quote_payload, create_quote_accept_payload, create_financing_payload,
    create_permit_payload, create_permit_decide_payload, create_hoa_decision_payload,
    create_engineering_review_payload, create_manufacture_order_payload, create_crew_payload,
    create_install_job_payload, create_inspection_payload, create_clock_payload,
)
from .test_users import TEST_USERS, make_homeowner_headers

SD = TEST_USERS["sales_designer_headers"]
PO = TEST_USERS["permit_officer_headers"]
MF = TEST_USERS["manufacturer_headers"]
IM = TEST_USERS["install_manager_headers"]
INS = TEST_USERS["inspector_headers"]


# ─── clock control ─────────────────────────────────────────────────────────

def set_clock(iso: str):
    """Set the logical clock to a fixed instant for deterministic time-gated rules."""
    return get_success_data(api_client.set_clock(create_clock_payload(iso), MF))


# ─── Tier 1: primitive creators ─────────────────────────────────────────────

def create_homeowner(**overrides):
    """Register a homeowner. Returns the homeowner entity."""
    return get_success_data(api_client.create_homeowner(create_homeowner_payload(**overrides), SD))


def create_project(homeowner_id, **overrides):
    """Create a DRAFT project. Returns the project entity."""
    return get_success_data(
        api_client.create_project(create_project_payload(homeowner_id, **overrides), SD))


def create_pending_measurement(project_id, **overrides):
    """Record a PENDING measurement. Returns the measurement entity."""
    return get_success_data(
        api_client.create_measurement(create_measurement_payload(project_id, **overrides), SD))


def create_crew(**overrides):
    """Register an install crew. Returns the crew entity."""
    return get_success_data(api_client.create_crew(create_crew_payload(**overrides), IM))


# ─── Tier 2: state-progression building blocks ──────────────────────────────

def setup_measured_project(homeowner_overrides=None, project_overrides=None,
                           measurement_overrides=None):
    """homeowner -> project -> measurement -> accept. Project is MEASURED.
    Returns (homeowner, project, measurement)."""
    ho = create_homeowner(**(homeowner_overrides or {}))
    pj = create_project(ho["id"], **(project_overrides or {}))
    m = create_pending_measurement(pj["id"], **(measurement_overrides or {}))
    get_success_data(api_client.accept_measurement(m["id"], SD))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, m


def setup_designed_project(homeowner_overrides=None, project_overrides=None,
                           measurement_overrides=None):
    """...-> finalize-design. Project is DESIGNED.
    Returns (homeowner, project, measurement)."""
    ho, pj, m = setup_measured_project(homeowner_overrides, project_overrides,
                                       measurement_overrides)
    get_success_data(api_client.finalize_design(pj["id"], SD))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, m


def setup_quoted_project(homeowner_overrides=None, project_overrides=None,
                         measurement_overrides=None):
    """...-> issue ESTIMATE quote. Project is QUOTED, quote ISSUED.
    Returns (homeowner, project, measurement, quote)."""
    ho, pj, m = setup_designed_project(homeowner_overrides, project_overrides,
                                       measurement_overrides)
    q = get_success_data(api_client.create_quote(create_quote_payload(pj["id"]), SD))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, m, q


def setup_permitting_project(homeowner_overrides=None, project_overrides=None,
                             measurement_overrides=None):
    """...-> accept quote (OCC). Project is PERMITTING, quote ACCEPTED.
    Returns (homeowner, project, measurement, quote)."""
    ho, pj, m, q = setup_quoted_project(homeowner_overrides, project_overrides,
                                        measurement_overrides)
    pv = get_success_data(api_client.get_project(pj["id"], SD))["version"]
    get_success_data(api_client.accept_quote(
        q["id"], create_quote_accept_payload(pv), make_homeowner_headers(ho["id"])))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    q = get_success_data(api_client.get_quote(q["id"], SD))
    return ho, pj, m, q


def setup_permit_in_review(homeowner_overrides=None, project_overrides=None,
                           measurement_overrides=None, permit_overrides=None):
    """...-> submit permit -> begin-review. Permit is IN_REVIEW.
    Returns (homeowner, project, quote, permit)."""
    ho, pj, m, q = setup_permitting_project(homeowner_overrides, project_overrides,
                                            measurement_overrides)
    pa = get_success_data(
        api_client.create_permit_application(create_permit_payload(pj["id"],
                                             **(permit_overrides or {})), SD))
    get_success_data(api_client.begin_permit_review(pa["id"], PO))
    pa = get_success_data(api_client.get_permit_application(pa["id"], PO))
    return ho, pj, q, pa


def setup_approved_to_build(homeowner_overrides=None, project_overrides=None,
                            measurement_overrides=None, with_engineering=False,
                            engineering_overrides=None):
    """...-> [engineering pass if requires_engineering] -> decide(APPROVED).
    Project is APPROVED_TO_BUILD. Returns (homeowner, project, quote, permit).

    Set with_engineering=True for FOUR_SEASON / high-load sites so an EngineeringReview
    is submitted and ruled PASSED before the permit is approved.
    """
    ho, pj, q, pa = setup_permit_in_review(homeowner_overrides, project_overrides,
                                           measurement_overrides)
    if with_engineering:
        er = get_success_data(api_client.create_engineering_review(
            create_engineering_review_payload(pa["id"], pj["id"],
                                              **(engineering_overrides or {})), SD))
        get_success_data(api_client.rule_engineering_review(er["id"], PO))
    get_success_data(api_client.decide_permit(pa["id"],
                     create_permit_decide_payload("APPROVED"), PO))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    pa = get_success_data(api_client.get_permit_application(pa["id"], PO))
    return ho, pj, q, pa


def setup_in_manufacture(homeowner_overrides=None, project_overrides=None,
                         measurement_overrides=None, with_engineering=False,
                         engineering_overrides=None):
    """...-> create manufacture order. Project IN_MANUFACTURE, order QUEUED.
    Returns (homeowner, project, quote, manufacture_order)."""
    ho, pj, q, pa = setup_approved_to_build(homeowner_overrides, project_overrides,
                                            measurement_overrides, with_engineering,
                                            engineering_overrides)
    mo = get_success_data(api_client.create_manufacture_order(
        create_manufacture_order_payload(pj["id"], q["id"]), MF))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, q, mo


def setup_manufacture_ready(homeowner_overrides=None, project_overrides=None,
                            measurement_overrides=None, with_engineering=False,
                            engineering_overrides=None):
    """...-> start -> ready. Project IN_MANUFACTURE, order READY.
    Returns (homeowner, project, manufacture_order)."""
    ho, pj, q, mo = setup_in_manufacture(homeowner_overrides, project_overrides,
                                         measurement_overrides, with_engineering,
                                         engineering_overrides)
    get_success_data(api_client.start_manufacture_order(mo["id"], MF))
    ready_resp = api_client.ready_manufacture_order(mo["id"], MF)
    mo = get_success_data(ready_resp)
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, mo


def setup_installing_project(homeowner_overrides=None, project_overrides=None,
                             measurement_overrides=None, with_engineering=False,
                             engineering_overrides=None, crew_overrides=None,
                             scheduled_start="2026-05-02T08:00:00Z",
                             scheduled_end="2026-05-02T17:00:00Z",
                             install_job_overrides=None):
    """...-> create crew -> schedule install job. Project INSTALLING, job SCHEDULED/CLEAR.
    Returns (homeowner, project, crew, install_job)."""
    ho, pj, mo = setup_manufacture_ready(homeowner_overrides, project_overrides,
                                         measurement_overrides, with_engineering,
                                         engineering_overrides)
    crew = create_crew(**(crew_overrides or {}))
    ij = get_success_data(api_client.create_install_job(
        create_install_job_payload(pj["id"], crew["id"], scheduled_start, scheduled_end,
                                   **(install_job_overrides or {})), IM))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    return ho, pj, crew, ij


def setup_inspecting_project(homeowner_overrides=None, project_overrides=None,
                             measurement_overrides=None, with_engineering=False,
                             engineering_overrides=None, crew_overrides=None,
                             scheduled_start="2026-05-02T08:00:00Z",
                             scheduled_end="2026-05-02T17:00:00Z"):
    """...-> start install -> complete install -> schedule inspection.
    Project INSPECTING, inspection SCHEDULED (attempt_no 1).
    Returns (homeowner, project, install_job, inspection)."""
    ho, pj, crew, ij = setup_installing_project(
        homeowner_overrides, project_overrides, measurement_overrides, with_engineering,
        engineering_overrides, crew_overrides, scheduled_start, scheduled_end)
    get_success_data(api_client.start_install_job(ij["id"], IM))
    get_success_data(api_client.complete_install_job(ij["id"], IM))
    ins = get_success_data(api_client.create_inspection(
        create_inspection_payload(pj["id"], ij["id"]), IM))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    ij = _find_install_job(pj["id"], ij["id"])
    return ho, pj, ij, ins


def setup_completed_project(homeowner_overrides=None, project_overrides=None,
                            measurement_overrides=None, with_engineering=False,
                            engineering_overrides=None,
                            scheduled_start="2026-05-02T08:00:00Z",
                            scheduled_end="2026-05-02T17:00:00Z"):
    """...-> pass inspection. Project COMPLETED, warranty issued.
    Returns (homeowner, project, inspection)."""
    ho, pj, ij, ins = setup_inspecting_project(
        homeowner_overrides, project_overrides, measurement_overrides, with_engineering,
        engineering_overrides, None, scheduled_start, scheduled_end)
    get_success_data(api_client.pass_inspection(ins["id"], INS))
    pj = get_success_data(api_client.get_project(pj["id"], SD))
    ins = _find_inspection(pj["id"], ins["id"])
    return ho, pj, ins


# ─── helpers to re-read list-discovered children ────────────────────────────

def _list(response):
    """Return (data_list, meta) from a list response, lenient about envelope."""
    body = response.json()
    data = body.get("data", [])
    meta = body.get("meta", {})
    return data, meta


def _find_install_job(project_id, job_id):
    jobs, _ = _list(api_client.list_project_install_jobs(project_id, IM))
    for j in jobs:
        if j["id"] == job_id:
            return j
    return jobs[-1]


def _find_inspection(project_id, inspection_id):
    items, _ = _list(api_client.list_project_inspections(project_id, IM))
    for it in items:
        if it["id"] == inspection_id:
            return it
    return items[-1]
