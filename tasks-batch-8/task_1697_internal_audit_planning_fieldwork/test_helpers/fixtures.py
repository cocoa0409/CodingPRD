"""Composite setup helpers for the internal-audit test suite.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (the harness restarts the server before each test, so each test
starts against an empty database). Setup calls use get_success_data() so a
broken precondition surfaces as a clear "Setup step failed" error.

Header conventions (PRD §2.1):
- Opaque roles (AuditAdmin, ChiefAuditExecutive, AuditCommittee,
  ManagementOwner) use the shared TEST_USERS constants.
- Entity-backed roles (AuditManager, FieldAuditor, QualityAssessor) use
  make_*_headers(auditor["id"]) so ownership checks resolve correctly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CRITICAL_MIN,
    DEFAULT_HIGH_MIN,
    DEFAULT_MODERATE_MIN,
    FIXTURE_CLOCK,
)
from .factories import (
    create_action_plan_payload,
    create_audit_plan_payload,
    create_auditable_entity_payload,
    create_audit_report_payload,
    create_auditor_payload,
    create_committee_pack_payload,
    create_engagement_assignment_payload,
    create_engagement_payload,
    create_extension_request_payload,
    create_finding_payload,
    create_management_response_payload,
    create_qa_review_payload,
    create_rating_criteria_config_payload,
    create_risk_assessment_payload,
    create_workpaper_payload,
)
from .test_users import (
    TEST_USERS,
    make_field_auditor_headers,
    make_manager_headers,
    make_qa_headers,
)

ADMIN = TEST_USERS["admin_headers"]
CAE = TEST_USERS["cae_headers"]
COMMITTEE = TEST_USERS["committee_headers"]
OWNER = TEST_USERS["owner_headers"]

WINDOW_START = "2026-02-01T00:00:00Z"
WINDOW_END = "2026-02-28T00:00:00Z"
ASSIGN_END = "2026-03-01T00:00:00Z"
DEFAULT_DUE_DATE = "2026-06-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and clock control
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = FIXTURE_CLOCK) -> None:
    """Drive the logical clock (PRD §2.5). Default pins the fixture clock."""
    get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_entity(name="Core Payments", regulatory_scrutiny=False,
                  last_audit_completed_at=None, **overrides):
    """Create an AuditableEntity. Returns the created entity dict."""
    payload = create_auditable_entity_payload(
        name=name, regulatory_scrutiny=regulatory_scrutiny, **overrides
    )
    if last_audit_completed_at is not None:
        payload["last_audit_completed_at"] = last_audit_completed_at
    return get_success_data(api_client.create_auditable_entity(payload, ADMIN))


def create_auditor(full_name="Mary Manager", grade="MANAGER", **overrides):
    """Create an Auditor. Returns the created auditor dict."""
    payload = create_auditor_payload(full_name=full_name, grade=grade, **overrides)
    return get_success_data(api_client.create_auditor(payload, ADMIN))


def create_active_rating_config(critical_min=DEFAULT_CRITICAL_MIN,
                                high_min=DEFAULT_HIGH_MIN,
                                moderate_min=DEFAULT_MODERATE_MIN,
                                name="standard-bands"):
    """Create a RatingCriteriaConfig and activate it. Returns ACTIVE config."""
    cfg = get_success_data(api_client.create_rating_criteria_config(
        create_rating_criteria_config_payload(
            name=name, critical_min=critical_min,
            high_min=high_min, moderate_min=moderate_min,
        ),
        ADMIN,
    ))
    return get_success_data(api_client.activate_rating_criteria_config(cfg["id"], ADMIN))


def create_plan(fiscal_year=2026, title="FY2026 Audit Plan"):
    """Create an AuditPlan (DRAFT). Returns the plan dict."""
    return get_success_data(api_client.create_audit_plan(
        create_audit_plan_payload(fiscal_year=fiscal_year, title=title), CAE
    ))


def get_plan(plan_id):
    return get_success_data(api_client.get_audit_plan(plan_id, CAE))


def create_engagement_for_plan(plan, entity, mgr, title="Engagement",
                               budget_hours=100, start_date=WINDOW_START,
                               end_date=WINDOW_END, **overrides):
    """Create an Engagement under `plan` (re-reads the plan version for OCC).
    Returns the created engagement dict."""
    fresh_plan = get_plan(plan["id"])
    payload = create_engagement_payload(
        plan["id"], entity["id"], fresh_plan["version"],
        title=title, budget_hours=budget_hours,
        start_date=start_date, end_date=end_date, **overrides,
    )
    return get_success_data(api_client.create_engagement(payload, make_manager_headers(mgr["id"])))


def assign_auditor(engagement_id, auditor, role_in_engagement="STAFF",
                   allocated_hours=40, start_date=WINDOW_START,
                   end_date=ASSIGN_END, actor=None):
    """Create an EngagementAssignment (ACTIVE). `actor` is the AuditManager
    auditor dict authorizing the call (defaults to the assigned auditor when
    the role is self-managed is NOT assumed; pass a manager)."""
    mgr_headers = make_manager_headers(actor["id"]) if actor else make_manager_headers(auditor["id"])
    payload = create_engagement_assignment_payload(
        engagement_id, auditor["id"],
        role_in_engagement=role_in_engagement, allocated_hours=allocated_hours,
        start_date=start_date, end_date=end_date,
    )
    return get_success_data(api_client.create_engagement_assignment(payload, mgr_headers))


# ---------------------------------------------------------------------------
# Tier 2: plan/engagement progressions
# ---------------------------------------------------------------------------

def submit_and_approve_plan(plan, submitter_headers=None, approver_headers=None):
    """Submit the plan as CAE and approve it as AuditCommittee (SoD-safe)."""
    submitter_headers = submitter_headers or CAE
    approver_headers = approver_headers or COMMITTEE
    get_success_data(api_client.submit_audit_plan(plan["id"], submitter_headers))
    return get_success_data(api_client.approve_audit_plan(plan["id"], approver_headers))


def setup_approved_plan_with_engagement(entity_name="Entity", budget_hours=100,
                                        regulatory_scrutiny=False,
                                        mgr_grade="MANAGER", staff_grade="STAFF"):
    """Approved plan + one PLANNED engagement + manager/staff auditors.

    Returns dict(plan, engagement, entity, mgr, staff)."""
    set_clock()
    ent = create_entity(name=entity_name, regulatory_scrutiny=regulatory_scrutiny)
    mgr = create_auditor(full_name="Mary Mgr", grade=mgr_grade)
    staff = create_auditor(full_name="Sam Staff", grade=staff_grade)
    plan = create_plan()
    eng = create_engagement_for_plan(plan, ent, mgr, budget_hours=budget_hours)
    approved = submit_and_approve_plan(plan)
    return {"plan": approved, "engagement": eng, "entity": ent, "mgr": mgr, "staff": staff}


def setup_engagement_in_fieldwork(entity_name="Entity", budget_hours=100,
                                  lead_hours=40, staff_hours=40,
                                  regulatory_scrutiny=False):
    """Full progression: plan APPROVED, engagement FIELDWORK with an ACTIVE
    LEAD assignment (mgr) and an ACTIVE STAFF assignment (staff).

    Returns dict(plan, engagement, entity, mgr, staff, lead_asg, staff_asg)."""
    ctx = setup_approved_plan_with_engagement(
        entity_name=entity_name, budget_hours=budget_hours,
        regulatory_scrutiny=regulatory_scrutiny,
    )
    mgr, staff, eng = ctx["mgr"], ctx["staff"], ctx["engagement"]
    mgr_h = make_manager_headers(mgr["id"])
    get_success_data(api_client.scope_engagement(eng["id"], mgr_h))
    lead_asg = assign_auditor(eng["id"], mgr, role_in_engagement="LEAD",
                              allocated_hours=lead_hours, actor=mgr)
    staff_asg = assign_auditor(eng["id"], staff, role_in_engagement="STAFF",
                               allocated_hours=staff_hours, actor=mgr)
    fieldwork = get_success_data(api_client.begin_fieldwork(eng["id"], mgr_h))
    ctx.update({
        "engagement": fieldwork, "lead_asg": lead_asg, "staff_asg": staff_asg,
    })
    return ctx


def create_signed_off_workpaper(ctx, hours_worked=10, reference="A-1",
                                title="WP", preparer=None, reviewer=None):
    """Create a workpaper and walk it DRAFT -> SUBMITTED -> SIGNED_OFF.
    `ctx` is the dict from setup_engagement_in_fieldwork. Returns the
    SIGNED_OFF workpaper dict."""
    preparer = preparer or ctx["staff"]
    reviewer = reviewer or ctx["mgr"]
    prep_h = make_field_auditor_headers(preparer["id"])
    wp = get_success_data(api_client.create_workpaper(
        create_workpaper_payload(ctx["engagement"]["id"], reference=reference,
                                 title=title, hours_worked=hours_worked),
        prep_h,
    ))
    get_success_data(api_client.submit_workpaper(wp["id"], prep_h))
    return get_success_data(
        api_client.sign_off_workpaper(wp["id"], make_manager_headers(reviewer["id"]))
    )


def setup_engagement_in_reporting(entity_name="Entity", budget_hours=100,
                                  workpaper_hours=10, num_workpapers=1):
    """Engagement walked to REPORTING with `num_workpapers` SIGNED_OFF
    workpapers and none pending. Returns the ctx dict plus 'workpapers'."""
    ctx = setup_engagement_in_fieldwork(entity_name=entity_name, budget_hours=budget_hours)
    wps = []
    for i in range(num_workpapers):
        wps.append(create_signed_off_workpaper(
            ctx, hours_worked=workpaper_hours, reference=f"A-{i + 1}", title=f"WP {i + 1}",
        ))
    reporting = get_success_data(
        api_client.begin_reporting(ctx["engagement"]["id"], make_manager_headers(ctx["mgr"]["id"]))
    )
    ctx["engagement"] = reporting
    ctx["workpapers"] = wps
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: finding negotiation and action-plan lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_issued_finding(ctx, title="Finding", likelihood=3, impact=4,
                          creator=None, issuer=None, workpaper_id=None):
    """Create a finding (as FieldAuditor `creator`) and issue it (as a
    different AuditManager `issuer`). Returns the PENDING_RESPONSE finding."""
    creator = creator or ctx["staff"]
    issuer = issuer or ctx.get("mgr2") or create_auditor(full_name="Mike Mgr2", grade="MANAGER")
    ctx.setdefault("mgr2", issuer)
    payload = create_finding_payload(
        ctx["engagement"]["id"], title=title, likelihood=likelihood, impact=impact,
    )
    if workpaper_id is not None:
        payload["workpaper_id"] = workpaper_id
    finding = get_success_data(
        api_client.create_finding(payload, make_field_auditor_headers(creator["id"]))
    )
    return get_success_data(
        api_client.issue_finding(finding["id"], make_manager_headers(issuer["id"]))
    )


def respond_to_finding(finding_id, response_text="Agree; will remediate",
                       proposed_due_date=DEFAULT_DUE_DATE):
    """ManagementOwner creates a ManagementResponse; finding -> UNDER_REVIEW.
    Returns the SUBMITTED response dict."""
    return get_success_data(api_client.create_management_response(
        create_management_response_payload(
            finding_id, response_text=response_text, proposed_due_date=proposed_due_date,
        ),
        OWNER,
    ))


def accept_response(response_id, reviewer):
    """AuditManager accepts a SUBMITTED response; finding -> AGREED."""
    return get_success_data(
        api_client.accept_management_response(response_id, make_manager_headers(reviewer["id"]))
    )


def setup_agreed_finding(entity_name="Entity", budget_hours=100,
                         likelihood=3, impact=4, title="Finding"):
    """Engagement FIELDWORK + ACTIVE config + finding in AGREED status.
    Returns ctx dict with 'finding' and 'response' added."""
    ctx = setup_engagement_in_fieldwork(entity_name=entity_name, budget_hours=budget_hours)
    ctx["config"] = create_active_rating_config()
    mgr2 = create_auditor(full_name="Mike Mgr2", grade="MANAGER")
    ctx["mgr2"] = mgr2
    finding = create_issued_finding(ctx, title=title, likelihood=likelihood,
                                    impact=impact, issuer=mgr2)
    resp = respond_to_finding(finding["id"])
    accept_response(resp["id"], mgr2)
    agreed = get_success_data(api_client.get_finding(finding["id"], make_manager_headers(ctx["mgr"]["id"])))
    ctx["finding"] = agreed
    ctx["response"] = resp
    return ctx


def setup_action_plan(due_date=DEFAULT_DUE_DATE, start=False, entity_name="Entity",
                      likelihood=3, impact=4):
    """Finding AGREED + an OPEN action plan due `due_date`.
    When start=True the plan is moved to IN_PROGRESS.
    Returns ctx dict with 'action_plan' added."""
    ctx = setup_agreed_finding(entity_name=entity_name, likelihood=likelihood,
                               impact=impact)
    ap = get_success_data(api_client.create_action_plan(
        create_action_plan_payload(ctx["finding"]["id"], due_date=due_date), OWNER,
    ))
    if start:
        ap = get_success_data(api_client.start_action_plan(ap["id"], OWNER))
    ctx["action_plan"] = ap
    return ctx


def create_and_approve_extension(action_plan_id, requested_due_date, reason="extension"):
    """Create an ExtensionRequest and approve it as CAE. Returns APPROVED request."""
    ext = get_success_data(api_client.create_extension_request(
        create_extension_request_payload(
            action_plan_id, requested_due_date=requested_due_date, reason=reason,
        ),
        OWNER,
    ))
    return get_success_data(api_client.approve_extension_request(ext["id"], CAE))


# ---------------------------------------------------------------------------
# Tier 4: report lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_approved_report(ctx, title="Report", overall_conclusion=None):
    """Draft -> PENDING_APPROVAL -> APPROVED report for an engagement in
    REPORTING. Returns the APPROVED report dict."""
    payload = create_audit_report_payload(ctx["engagement"]["id"], title=title)
    if overall_conclusion is not None:
        payload["overall_conclusion"] = overall_conclusion
    rep = get_success_data(api_client.create_audit_report(
        payload, make_manager_headers(ctx["mgr"]["id"]),
    ))
    get_success_data(api_client.submit_audit_report(rep["id"], make_manager_headers(ctx["mgr"]["id"])))
    return get_success_data(api_client.approve_audit_report(rep["id"], CAE))


def setup_qa_review(ctx, scope="INTERNAL", assessor_name="Quinn QA", assessor_grade="MANAGER"):
    """Schedule a QAReview for ctx's engagement and register an unassigned
    assessor auditor. Returns (qa_review dict, qa auditor dict)."""
    qa_auditor = create_auditor(full_name=assessor_name, grade=assessor_grade)
    review = get_success_data(api_client.create_qa_review(
        create_qa_review_payload(ctx["engagement"]["id"], scope=scope), CAE,
    ))
    return review, qa_auditor


def complete_qa_review(review_id, qa_auditor, doc=4, fieldwork=4, reporting=4,
                       independence=4):
    """Complete an IN_PROGRESS review as its assigned assessor."""
    return get_success_data(api_client.complete_qa_review(
        review_id,
        {
            "doc_quality_score": doc,
            "fieldwork_quality_score": fieldwork,
            "reporting_quality_score": reporting,
            "independence_score": independence,
        },
        make_qa_headers(qa_auditor["id"]),
    ))
