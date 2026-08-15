"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors.

Fixture chain overview (each tier extends the previous one):

  create_client / create_project          — intake
  create_approved_plan                    — plan revision drafted + approved
  setup_scoped_project                    — + subcontractor, boring, ticket, rig
  setup_fieldwork_project                 — + project driven to FIELDWORK
  setup_boring_cleared                    — + rig MOBILIZED, boring CLEARED
  setup_drilled_boring                    — + boring DRILLED (plan LOCKED)
  setup_lab_received_sample               — + sample shipped and received
  setup_accepted_uc_order                 — + UNCONFINED_COMPRESSION ACCEPTED
  setup_verified_analysis                 — + FoundationAnalysis VERIFIED
  setup_project_in_lab_analysis           — + boring CLOSED, project LAB_ANALYSIS
  setup_project_in_report_review          — + project REPORT_REVIEW
  setup_pe_review_report                  — + report advanced to PE_REVIEW
  setup_issued_project                    — + report ISSUED, project ISSUED
  setup_construction_support_project      — + project CONSTRUCTION_SUPPORT
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_AVG_N60,
    DEFAULT_PLANNED_DEPTH_FT,
    DEFAULT_QU_PSF,
    TICKET_ISSUED_ON,
    WINDOW_END,
    WINDOW_START,
)
from .factories import (
    create_boring_payload,
    create_boring_plan_payload,
    create_claim_payload,
    create_clearance_payload,
    create_client_payload,
    create_exploration_authorization_payload,
    create_foundation_analysis_payload,
    create_lab_test_order_payload,
    create_observation_visit_payload,
    create_project_payload,
    create_rig_assignment_payload,
    create_sample_payload,
    create_subcontractor_payload,
    drill_boring_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS,
    make_client_rep_headers,
    make_drilling_sub_headers,
    make_principal_engineer_headers,
    make_senior_engineer_headers,
)

FA = TEST_USERS["firm_admin_headers"]
PM = TEST_USERS["project_manager_headers"]
SE = TEST_USERS["staff_engineer_headers"]
FG = TEST_USERS["field_geologist_headers"]
LM = TEST_USERS["lab_manager_headers"]
LT = TEST_USERS["lab_technician_headers"]
SEN = TEST_USERS["senior_engineer_headers"]
PE = TEST_USERS["principal_engineer_headers"]

REPORT_PREPARER_ID = "se-1"
REPORT_ISSUER_ID = "pe-9"


def _ok(step, resp):
    try:
        return get_success_data(resp)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at {step}: {exc}")


# ---------------------------------------------------------------------------
# Tier 1 — intake, plan revisions, subcontractors
# ---------------------------------------------------------------------------

def create_client(**overrides):
    return _ok("create_client",
               api_client.create_client(create_client_payload(**overrides), FA))


def create_project(client_id, **overrides):
    return _ok("create_project",
               api_client.create_project(
                   create_project_payload(client_id, **overrides), FA))


def create_client_and_project(**project_overrides):
    client = create_client()
    project = create_project(client["id"], **project_overrides)
    return client, project


def transition_project(project_id, to, headers=PM):
    return _ok(f"project->{to}",
               api_client.transition_project(project_id, {"to": to}, headers))


def get_project(project_id, headers=PM):
    return _ok("get_project", api_client.get_project(project_id, headers))


def create_approved_plan(project, planned_boring_count=1,
                         planned_total_footage_ft=30, supersedes_plan_id=None):
    """Create a plan revision (OCC-guarded on the project's version) and walk
    it DRAFT -> SUBMITTED -> APPROVED. Returns the APPROVED plan."""
    payload = create_boring_plan_payload(
        project["version"],
        planned_boring_count=planned_boring_count,
        planned_total_footage_ft=planned_total_footage_ft,
    )
    if supersedes_plan_id is not None:
        payload["supersedes_plan_id"] = supersedes_plan_id
    plan = _ok("create_boring_plan",
               api_client.create_boring_plan(project["id"], payload, SE))
    plan = _ok("plan->SUBMITTED",
               api_client.transition_boring_plan(plan["id"], {"to": "SUBMITTED"}, SE))
    plan = _ok("plan->APPROVED",
               api_client.transition_boring_plan(plan["id"], {"to": "APPROVED"}, PM))
    return plan


def create_subcontractor(**overrides):
    return _ok("create_subcontractor",
               api_client.create_subcontractor(
                   create_subcontractor_payload(**overrides), FA))


def transition_subcontractor(subcontractor_id, to):
    return _ok(f"subcontractor->{to}",
               api_client.transition_subcontractor(
                   subcontractor_id, {"to": to}, FA))


# ---------------------------------------------------------------------------
# Tier 2 — borings, tickets, rig windows
# ---------------------------------------------------------------------------

def add_boring(plan_id, boring_no="B-1", planned_depth_ft=DEFAULT_PLANNED_DEPTH_FT,
               access_difficult=False):
    return _ok("add_boring",
               api_client.create_boring(
                   plan_id,
                   create_boring_payload(boring_no=boring_no,
                                         planned_depth_ft=planned_depth_ft,
                                         access_difficult=access_difficult),
                   SE))


def file_clearance(boring_id, ticket_number="T-1", issued_on=TICKET_ISSUED_ON,
                   valid_days=14, clear=True):
    """File a one-call ticket; optionally advance it FILED -> CLEARED."""
    payload = create_clearance_payload(ticket_number=ticket_number,
                                       issued_on=issued_on)
    if valid_days is not None:
        payload["valid_days"] = valid_days
    clearance = _ok("file_clearance",
                    api_client.create_clearance(boring_id, payload, SE))
    if clear:
        clearance = transition_clearance(clearance["id"], "CLEARED")
    return clearance


def transition_clearance(clearance_id, to, headers=SE):
    return _ok(f"clearance->{to}",
               api_client.transition_clearance(clearance_id, {"to": to}, headers))


def schedule_rig(boring_id, subcontractor_id, window_start=WINDOW_START,
                 window_end=WINDOW_END):
    return _ok("schedule_rig",
               api_client.create_rig_assignment(
                   boring_id,
                   create_rig_assignment_payload(
                       subcontractor_id, window_start=window_start,
                       window_end=window_end),
                   PM))


def transition_rig_assignment(assignment_id, to, headers):
    return _ok(f"rig_assignment->{to}",
               api_client.transition_rig_assignment(
                   assignment_id, {"to": to}, headers))


def mobilize_assignment(assignment_id, subcontractor_id):
    return transition_rig_assignment(
        assignment_id, "MOBILIZED", make_drilling_sub_headers(subcontractor_id))


def transition_boring(boring_id, to, headers, **extra):
    payload = {"to": to}
    payload.update(extra)
    return _ok(f"boring->{to}",
               api_client.transition_boring(boring_id, payload, headers))


def clear_boring(boring_id):
    return transition_boring(boring_id, "CLEARED", SE)


def drill_boring(boring_id, subcontractor_id, **overrides):
    return _ok("boring->DRILLED",
               api_client.transition_boring(
                   boring_id, drill_boring_payload(**overrides),
                   make_drilling_sub_headers(subcontractor_id)))


def set_logical_clock(to_iso8601):
    return _ok("set_clock",
               api_client.set_clock(set_clock_payload(to_iso8601), FA))


# ---------------------------------------------------------------------------
# Tier 3 — scoped / fieldwork composite
# ---------------------------------------------------------------------------

def setup_scoped_project(boring_count=1,
                         planned_depth_ft=DEFAULT_PLANNED_DEPTH_FT,
                         access_difficult=False, clear_tickets=True,
                         schedule_first_rig=True, **project_overrides):
    """Client + project + APPROVED plan + subcontractor + borings, each boring
    holding a ticket, plus (optionally) a rig window on the first boring.

    The project is left in DRAFT; callers drive it onward as needed."""
    client, project = create_client_and_project(**project_overrides)
    plan = create_approved_plan(
        project,
        planned_boring_count=boring_count,
        planned_total_footage_ft=planned_depth_ft * boring_count,
    )
    subcontractor = create_subcontractor()
    borings = [
        add_boring(plan["id"], boring_no=f"B-{i + 1}",
                   planned_depth_ft=planned_depth_ft,
                   access_difficult=access_difficult)
        for i in range(boring_count)
    ]
    clearances = [
        file_clearance(b["id"], ticket_number=f"T-{i + 1}", clear=clear_tickets)
        for i, b in enumerate(borings)
    ]
    assignment = None
    if schedule_first_rig:
        assignment = schedule_rig(borings[0]["id"], subcontractor["id"])
    return {
        "client": client,
        "project": project,
        "plan": plan,
        "subcontractor": subcontractor,
        "borings": borings,
        "boring": borings[0],
        "clearances": clearances,
        "clearance": clearances[0],
        "assignment": assignment,
    }


def setup_fieldwork_project(**kwargs):
    """setup_scoped_project + project driven DRAFT -> SCOPED ->
    FIELD_AUTHORIZED -> FIELDWORK."""
    ctx = setup_scoped_project(**kwargs)
    project_id = ctx["project"]["id"]
    transition_project(project_id, "SCOPED")
    transition_project(project_id, "FIELD_AUTHORIZED")
    ctx["project"] = transition_project(project_id, "FIELDWORK")
    return ctx


def setup_boring_cleared(**kwargs):
    """Project in FIELDWORK with the rig MOBILIZED and the first boring
    CLEARED (ready to drill)."""
    ctx = setup_fieldwork_project(**kwargs)
    ctx["assignment"] = mobilize_assignment(
        ctx["assignment"]["id"], ctx["subcontractor"]["id"])
    ctx["boring"] = clear_boring(ctx["boring"]["id"])
    return ctx


def setup_drilled_boring(actual_depth_ft=30, rock_depth_ft=0,
                         groundwater_depth_ft=12, avg_n60=DEFAULT_AVG_N60,
                         **kwargs):
    """Project in FIELDWORK with the first boring DRILLED (plan now LOCKED)."""
    ctx = setup_boring_cleared(**kwargs)
    ctx["boring"] = drill_boring(
        ctx["boring"]["id"], ctx["subcontractor"]["id"],
        actual_depth_ft=actual_depth_ft, rock_depth_ft=rock_depth_ft,
        groundwater_depth_ft=groundwater_depth_ft, avg_n60=avg_n60)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — samples, laboratory orders, results
# ---------------------------------------------------------------------------

def create_sample(boring_id, **overrides):
    return _ok("create_sample",
               api_client.create_sample(
                   boring_id, create_sample_payload(**overrides), FG))


def transition_sample(sample_id, to, headers):
    return _ok(f"sample->{to}",
               api_client.transition_sample(sample_id, {"to": to}, headers))


def ship_sample_to_lab(sample_id):
    transition_sample(sample_id, "IN_TRANSIT", FG)
    return transition_sample(sample_id, "LAB_RECEIVED", LT)


def setup_lab_received_sample(sampler_type="SPT", recovery_pct=80, **kwargs):
    """Drilled boring + one sample driven COLLECTED -> IN_TRANSIT ->
    LAB_RECEIVED."""
    ctx = setup_drilled_boring(**kwargs)
    sample = create_sample(ctx["boring"]["id"], sampler_type=sampler_type,
                           recovery_pct=recovery_pct)
    ctx["sample"] = ship_sample_to_lab(sample["id"])
    return ctx


def create_lab_order(project_id, sample_id, test_type="MOISTURE_CONTENT",
                     priority="STANDARD"):
    return _ok("create_lab_order",
               api_client.create_lab_test_order(
                   project_id,
                   create_lab_test_order_payload(
                       sample_id, test_type=test_type, priority=priority),
                   LM))


def transition_lab_order(order_id, to, headers):
    return _ok(f"lab_order->{to}",
               api_client.transition_lab_test_order(order_id, {"to": to}, headers))


def authorize_lab_order(order_id):
    return transition_lab_order(order_id, "AUTHORIZED", LM)


def start_lab_order(order_id):
    return transition_lab_order(order_id, "IN_TEST", LT)


def submit_lab_result(order_id, **fields):
    return _ok("submit_lab_result",
               api_client.submit_lab_result(order_id, dict(fields), LT))


def accept_lab_order(order_id):
    return transition_lab_order(order_id, "ACCEPTED", LM)


def reject_lab_order(order_id):
    return transition_lab_order(order_id, "REJECTED", LM)


def run_order_to_accepted(project_id, sample_id, test_type, result_fields,
                          priority="STANDARD"):
    """Order -> AUTHORIZED -> IN_TEST -> result submitted -> ACCEPTED."""
    order = create_lab_order(project_id, sample_id, test_type=test_type,
                             priority=priority)
    authorize_lab_order(order["id"])
    start_lab_order(order["id"])
    submit_lab_result(order["id"], **result_fields)
    return accept_lab_order(order["id"])


def setup_accepted_uc_order(qu_psf=DEFAULT_QU_PSF, sampler_type="SHELBY",
                            recovery_pct=95, **kwargs):
    """Drilled boring + LAB_RECEIVED sample + UNCONFINED_COMPRESSION order
    ACCEPTED with the given qu_psf."""
    ctx = setup_lab_received_sample(sampler_type=sampler_type,
                                    recovery_pct=recovery_pct, **kwargs)
    ctx["uc_order"] = run_order_to_accepted(
        ctx["project"]["id"], ctx["sample"]["id"], "UNCONFINED_COMPRESSION",
        {"qu_psf": qu_psf})
    return ctx


# ---------------------------------------------------------------------------
# Tier 5 — analysis, report, issuance, construction support
# ---------------------------------------------------------------------------

def create_analysis(project_id, **overrides):
    return _ok("create_analysis",
               api_client.create_foundation_analysis(
                   project_id, create_foundation_analysis_payload(**overrides),
                   SEN))


def transition_analysis(analysis_id, to):
    return _ok(f"analysis->{to}",
               api_client.transition_foundation_analysis(
                   analysis_id, {"to": to}, SEN))


def setup_verified_analysis(applied_bearing_psf=3000, footing_width_ft=6,
                            fs_required=3.0, **kwargs):
    """Accepted UC order + FoundationAnalysis created PRELIMINARY then
    VERIFIED."""
    ctx = setup_accepted_uc_order(**kwargs)
    analysis = create_analysis(
        ctx["project"]["id"], applied_bearing_psf=applied_bearing_psf,
        footing_width_ft=footing_width_ft, fs_required=fs_required)
    ctx["analysis"] = transition_analysis(analysis["id"], "VERIFIED")
    return ctx


def setup_project_in_lab_analysis(**kwargs):
    """Verified analysis + boring LOGGED/CLOSED + project LAB_ANALYSIS."""
    ctx = setup_verified_analysis(**kwargs)
    transition_boring(ctx["boring"]["id"], "LOGGED", FG)
    transition_boring(ctx["boring"]["id"], "CLOSED", SE)
    ctx["project"] = transition_project(ctx["project"]["id"], "LAB_ANALYSIS")
    return ctx


def setup_project_in_report_review(**kwargs):
    """Project advanced LAB_ANALYSIS -> REPORT_REVIEW by a SeniorEngineer."""
    ctx = setup_project_in_lab_analysis(**kwargs)
    ctx["project"] = transition_project(
        ctx["project"]["id"], "REPORT_REVIEW", headers=SEN)
    return ctx


def setup_pe_review_report(**kwargs):
    """Project REPORT_REVIEW + a report revision created by the preparer and
    advanced DRAFT -> TECH_REVIEW -> PE_REVIEW."""
    ctx = setup_project_in_report_review(**kwargs)
    report = _ok("create_report",
                 api_client.create_report(
                     ctx["project"]["id"], {},
                     make_senior_engineer_headers(REPORT_PREPARER_ID)))
    report = _ok("report->TECH_REVIEW",
                 api_client.transition_report(report["id"], {"to": "TECH_REVIEW"}, SEN))
    report = _ok("report->PE_REVIEW",
                 api_client.transition_report(report["id"], {"to": "PE_REVIEW"}, PM))
    ctx["report"] = report
    return ctx


def issue_report(report_id, issuer_id=REPORT_ISSUER_ID):
    """Issue a PE_REVIEW report with the OCC version read fresh."""
    report = _ok("get_report",
                 api_client.get_report(report_id, make_principal_engineer_headers(issuer_id)))
    return _ok("issue_report",
               api_client.issue_report(
                   report_id, {"expected_report_version": report["version"]},
                   make_principal_engineer_headers(issuer_id)))


def setup_issued_project(**kwargs):
    """Report ISSUED by a PrincipalEngineer other than the preparer, then the
    project REPORT_REVIEW -> ISSUED."""
    ctx = setup_pe_review_report(**kwargs)
    ctx["report"] = issue_report(ctx["report"]["id"])
    ctx["project"] = transition_project(ctx["project"]["id"], "ISSUED")
    return ctx


def setup_construction_support_project(**kwargs):
    """Full engagement lifecycle through project CONSTRUCTION_SUPPORT."""
    ctx = setup_issued_project(**kwargs)
    ctx["project"] = transition_project(
        ctx["project"]["id"], "CONSTRUCTION_SUPPORT",
        headers=make_client_rep_headers(ctx["client"]["id"]))
    return ctx


# ---------------------------------------------------------------------------
# Tier 6 — visits, claims, exploration authorizations, offsets
# ---------------------------------------------------------------------------

def create_visit(project_id, visit_date="2026-08-10T00:00:00Z"):
    return _ok("create_visit",
               api_client.create_observation_visit(
                   project_id,
                   create_observation_visit_payload(visit_date=visit_date),
                   PM))


def transition_visit(visit_id, to, headers=SE, **extra):
    payload = {"to": to}
    payload.update(extra)
    return _ok(f"visit->{to}",
               api_client.transition_observation_visit(visit_id, payload, headers))


def create_claim(project_id, headers=PM, **overrides):
    return _ok("create_claim",
               api_client.create_claim(
                   project_id, create_claim_payload(**overrides), headers))


def transition_claim(claim_id, to, headers=SEN, **extra):
    payload = {"to": to}
    payload.update(extra)
    return _ok(f"claim->{to}",
               api_client.transition_claim(claim_id, payload, headers))


def create_authorization(project_id, authorized_amount_cents=100000,
                         extra_boring_count=1):
    return _ok("create_authorization",
               api_client.create_exploration_authorization(
                   project_id,
                   create_exploration_authorization_payload(
                       authorized_amount_cents=authorized_amount_cents,
                       extra_boring_count=extra_boring_count),
                   PM))


def transition_authorization(authorization_id, to, client_id,
                             expected_project_version):
    return _ok(f"authorization->{to}",
               api_client.transition_exploration_authorization(
                   authorization_id,
                   {"to": to,
                    "expected_project_version": expected_project_version},
                   make_client_rep_headers(client_id)))


def approve_authorization(authorization_id, client_id, project_id):
    """Approve with the OCC version read fresh from the project."""
    project = get_project(project_id)
    return transition_authorization(
        authorization_id, "APPROVED", client_id, project["version"])


def refuse_boring(boring_id, subcontractor_id, refusal_depth_ft):
    return _ok("boring->REFUSED",
               api_client.transition_boring(
                   boring_id,
                   {"to": "REFUSED", "refusal_depth_ft": refusal_depth_ft},
                   make_drilling_sub_headers(subcontractor_id)))


def setup_refused_boring(refusal_depth_ft=18, actual_depth_ft=18, **kwargs):
    """Drilled boring then reported REFUSED at a depth below planned."""
    ctx = setup_drilled_boring(actual_depth_ft=actual_depth_ft, **kwargs)
    ctx["boring"] = refuse_boring(
        ctx["boring"]["id"], ctx["subcontractor"]["id"], refusal_depth_ft)
    return ctx
