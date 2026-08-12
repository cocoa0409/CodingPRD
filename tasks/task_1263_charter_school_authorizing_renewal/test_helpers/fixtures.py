"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as clear
"Setup failed" errors instead of confusing assertion failures. Every helper builds
its preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_application_payload, create_score_payload, create_interview_payload,
    create_contract_payload, create_target_payload, create_monitoring_report_payload,
    create_lottery_payload, create_lottery_entry_payload, create_intervention_payload,
    create_corrective_plan_payload, create_renewal_decision_payload,
    create_closure_plan_payload, create_student_transition_payload,
    create_fee_invoice_payload, create_appeal_payload,
)
from .constants import CLOCK, CONTRACT
from .test_users import (
    TEST_USERS, make_applicant_headers, make_staff_headers, make_reviewer_headers,
    make_board_headers, make_appeals_officer_headers, make_school_operator_headers,
    make_admin_headers,
)

RUBRIC_CRITERIA = ["ACADEMIC_PLAN", "FINANCE_PLAN", "GOVERNANCE",
                   "OPERATIONS_PLAN", "COMMUNITY_SUPPORT"]

STAFF = TEST_USERS["staff_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _setup_fail(step: str, res):
    raise AssertionError(f"Setup failed at {step}: HTTP {res.status_code} {res.text[:400]}")


def _ok(res, step: str):
    if res.status_code >= 400:
        _setup_fail(step, res)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 0: clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601: str, admin_headers=None):
    """Drive the logical clock (PRD §2.5). Returns the clock response payload."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, admin_headers or ADMIN)
    return _ok(res, f"set_clock({to_iso8601})")


# ---------------------------------------------------------------------------
# Tier 1: application state progression (PRD §3.1)
# ---------------------------------------------------------------------------
def create_application(school_name="Test Charter Academy", applicant_id="applicant_fx",
                       founding_group="FG Test", cycle_year=2027, proposed_grades="K-8"):
    """Create a SUBMITTED application. Returns the application."""
    res = api_client.create_application(
        create_application_payload(school_name=school_name, founding_group=founding_group,
                                   cycle_year=cycle_year, proposed_grades=proposed_grades),
        make_applicant_headers(applicant_id))
    return _ok(res, "create_application")


def create_application_under_review(**kwargs):
    """Create + accept intake. Returns an UNDER_REVIEW application."""
    app = create_application(**kwargs)
    res = api_client.accept_intake(app["id"], STAFF)
    return _ok(res, "accept_intake")


def post_full_rubric(application_id: str, reviewer_id: str, scores=(90, 90, 90, 90, 90)):
    """Post one score per rubric criterion from a single reviewer. Returns last response data."""
    assert len(scores) == 5, "rubric has five criteria"
    app = None
    for criterion, score in zip(RUBRIC_CRITERIA, scores):
        res = api_client.post_application_score(
            application_id, create_score_payload(criterion=criterion, score=score),
            make_reviewer_headers(reviewer_id))
        app = _ok(res, f"post_score({criterion})")
    return app


def create_scored_application(school_name="Test Charter Academy",
                              applicant_id="applicant_fx",
                              reviewer_id="rev_fx",
                              rubric_scores=(90, 90, 90, 90, 90),
                              panelist_id="rev_panel_fx",
                              panel_score=90,
                              interview_start="2026-05-10T10:00:00Z",
                              interview_end="2026-05-10T11:00:00Z"):
    """UNDER_REVIEW application with a complete rubric and a SCORED interview.
    Returns (application, interview)."""
    app = create_application_under_review(school_name=school_name, applicant_id=applicant_id)
    post_full_rubric(app["id"], reviewer_id, rubric_scores)
    interview = _ok(
        api_client.schedule_interview(
            app["id"],
            create_interview_payload(scheduled_start=interview_start,
                                     scheduled_end=interview_end,
                                     panelist_user_ids=[panelist_id]),
            STAFF),
        "schedule_interview")
    interview = _ok(
        api_client.score_interview(interview["id"], {"panel_score": panel_score},
                                   make_reviewer_headers(panelist_id)),
        "score_interview")
    app = _ok(api_client.get_application(app["id"], STAFF), "get_application")
    return app, interview


def create_board_ready_application(**kwargs):
    """Application advanced to BOARD_REVIEW (composite frozen FINAL). Returns (app, interview)."""
    app, interview = create_scored_application(**kwargs)
    app = _ok(api_client.advance_to_board(app["id"], STAFF), "advance_to_board")
    return app, interview


def create_approved_school(decider_id="board_1", **kwargs):
    """Application approved by the board. Returns (app, school PRE_OPENING)."""
    app, _interview = create_board_ready_application(**kwargs)
    app = _ok(
        api_client.decide_application(app["id"], {"outcome": "APPROVED"},
                                      make_board_headers(decider_id)),
        "decide_application(APPROVED)")
    schools = _ok(api_client.list_application_schools(app["id"], STAFF), "list schools")
    assert isinstance(schools, list) and len(schools) == 1, (
        f"Setup failed: approval cascade created {len(schools)} schools")
    return app, schools[0]


def create_denied_application(denial_reason="Application weaknesses",
                              decider_id="board_1", **kwargs):
    """Application decided DENIED from BOARD_REVIEW. Returns the DENIED application."""
    kwargs.setdefault("rubric_scores", (80, 80, 80, 80, 80))
    kwargs.setdefault("panel_score", 80)
    app, _interview = create_board_ready_application(**kwargs)
    app = _ok(
        api_client.decide_application(
            app["id"], {"outcome": "DENIED", "denial_reason": denial_reason},
            make_board_headers(decider_id)),
        "decide_application(DENIED)")
    return app


# ---------------------------------------------------------------------------
# Tier 2: contracts and the open school (PRD §3.2)
# ---------------------------------------------------------------------------
STANDARD_TARGETS = (
    {"domain": "ACADEMIC", "metric_code": "MATH_PROF", "target_value": 80,
     "floor_value": 60, "weight": 0.5},
    {"domain": "FINANCIAL", "metric_code": "AUDIT_CLEAN", "target_value": 1,
     "floor_value": 1, "weight": 0.25},
    {"domain": "OPERATIONAL", "metric_code": "ENROLL_PCT", "target_value": 95,
     "floor_value": 85, "weight": 0.25},
)


def create_draft_contract(school_id: str, expected_school_version,
                          framework_version=CONTRACT["FRAMEWORK_VERSION"],
                          term_start=CONTRACT["TERM_START"], term_end=CONTRACT["TERM_END"],
                          prior_contract_id=None):
    """Create a DRAFT contract (OCC field per PRD §2.7). Returns the contract."""
    res = api_client.create_contract(
        school_id,
        create_contract_payload(expected_school_version=expected_school_version,
                                framework_version=framework_version,
                                term_start=term_start, term_end=term_end,
                                prior_contract_id=prior_contract_id),
        STAFF)
    return _ok(res, "create_contract")


def add_standard_targets(contract_id: str):
    """Attach the three-domain performance framework summing to weight 1.0."""
    for spec in STANDARD_TARGETS:
        _ok(api_client.add_contract_target(contract_id, create_target_payload(**spec), STAFF),
            f"add_target({spec['domain']})")


def create_open_school(decider_id="board_1", **kwargs):
    """Approved application + ACTIVE contract. Returns dict with application,
    school (OPEN), and contract (ACTIVE)."""
    app, school = create_approved_school(decider_id=decider_id, **kwargs)
    school = _ok(api_client.get_school(school["id"], STAFF), "get school")
    contract = create_draft_contract(school["id"], school["version"])
    add_standard_targets(contract["id"])
    contract = _ok(api_client.activate_contract(contract["id"], STAFF), "activate_contract")
    school = _ok(api_client.get_school(school["id"], STAFF), "get school after activation")
    return {"application": app, "school": school, "contract": contract}


# ---------------------------------------------------------------------------
# Tier 3: monitoring, lotteries, interventions (PRD §3.3–§3.5)
# ---------------------------------------------------------------------------
def add_monitoring_report(school_id: str, fiscal_year=2028, academic_score=90,
                          financial_score=90, operational_score=90,
                          staff_id="staff_fx"):
    """Create a SUBMITTED monitoring report. Returns the report."""
    res = api_client.create_monitoring_report(
        school_id,
        create_monitoring_report_payload(fiscal_year=fiscal_year,
                                         academic_score=academic_score,
                                         financial_score=financial_score,
                                         operational_score=operational_score),
        make_staff_headers(staff_id))
    return _ok(res, f"create_monitoring_report({fiscal_year})")


def accept_report(report_id: str, staff_id="staff_fx"):
    """Accept a SUBMITTED report. Returns the ACCEPTED report."""
    res = api_client.accept_monitoring_report(report_id, make_staff_headers(staff_id))
    return _ok(res, "accept_monitoring_report")


def add_accepted_report(school_id: str, fiscal_year=2028, academic_score=90,
                        financial_score=90, operational_score=90, staff_id="staff_fx"):
    """Create + accept a monitoring report. Returns the ACCEPTED report."""
    report = add_monitoring_report(school_id, fiscal_year, academic_score,
                                   financial_score, operational_score, staff_id)
    return accept_report(report["id"], staff_id)


def create_lottery(school_id: str, academic_year=2028, capacity=10):
    """Create a DRAFT lottery. Returns the lottery."""
    res = api_client.create_lottery(
        school_id, create_lottery_payload(academic_year=academic_year, capacity=capacity), STAFF)
    return _ok(res, "create_lottery")


def open_lottery(lottery_id: str):
    res = api_client.open_lottery(lottery_id, STAFF)
    return _ok(res, "open_lottery")


def create_open_lottery(school_id: str, academic_year=2028, capacity=10):
    """Create + open a lottery (school must be OPEN). Returns the OPEN lottery."""
    lottery = create_lottery(school_id, academic_year, capacity)
    return open_lottery(lottery["id"])


def add_lottery_entry(lottery_id: str, school_id: str, student_ref="stu_1",
                      grade_level="K", preference_codes=None):
    """Add an entry as the owning SchoolOperator (identity threading per PRD §2.1)."""
    res = api_client.add_lottery_entry(
        lottery_id,
        create_lottery_entry_payload(student_ref=student_ref, grade_level=grade_level,
                                     preference_codes=preference_codes if preference_codes is not None else []),
        make_school_operator_headers(school_id))
    return _ok(res, f"add_lottery_entry({student_ref})")


def create_intervention(school_id: str, level="NOTICE", domain="COMPLIANCE",
                        reason="Intervention reason"):
    """Create a DRAFT intervention notice. Returns the notice."""
    res = api_client.create_intervention(
        school_id, create_intervention_payload(level=level, domain=domain, reason=reason), STAFF)
    return _ok(res, "create_intervention")


def create_issued_notice(school_id: str, level="NOTICE", domain="COMPLIANCE",
                         reason="Intervention reason", issuer_id="staff_a"):
    """Create + issue a notice. Returns the ISSUED notice (with fresh version)."""
    notice = create_intervention(school_id, level, domain, reason)
    res = api_client.issue_intervention(notice["id"], make_staff_headers(issuer_id))
    return _ok(res, "issue_intervention")


def submit_corrective_plan(notice_id: str, school_id: str, plan_text="Plan v1",
                           expected_intervention_version=None):
    """Submit a corrective plan as the owning SchoolOperator. Returns the plan."""
    if expected_intervention_version is None:
        notice = _ok(api_client.get_intervention(notice_id, STAFF), "get notice for version")
        expected_intervention_version = notice["version"]
    res = api_client.create_corrective_plan(
        notice_id,
        create_corrective_plan_payload(plan_text=plan_text,
                                       expected_intervention_version=expected_intervention_version),
        make_school_operator_headers(school_id))
    return _ok(res, "create_corrective_plan")


# ---------------------------------------------------------------------------
# Tier 4: renewal track record and decisions (PRD §3.6)
# ---------------------------------------------------------------------------
# Three ACCEPTED reports whose compliance indices average to 90.3 (top tier inputs).
RENEWAL_REPORT_SPECS = (
    {"fiscal_year": 2028, "academic_score": 92, "financial_score": 88, "operational_score": 88},
    {"fiscal_year": 2029, "academic_score": 90, "financial_score": 90, "operational_score": 90},
    {"fiscal_year": 2030, "academic_score": 94, "financial_score": 92, "operational_score": 84},
)


def build_renewal_track_record(school_id: str, report_specs=RENEWAL_REPORT_SPECS,
                               staff_id="staff_fx"):
    """Create + accept the given monitoring reports. Returns the reports."""
    reports = []
    for spec in report_specs:
        reports.append(add_accepted_report(school_id, staff_id=staff_id, **spec))
    return reports


def setup_renewal_ready_school(**kwargs):
    """Open school with ACTIVE contract plus the standard three-report track record,
    clock moved inside the renewal window. Returns the create_open_school dict."""
    ctx = create_open_school(**kwargs)
    build_renewal_track_record(ctx["school"]["id"])
    set_clock(CLOCK["RENEWAL_OPEN"])
    return ctx


def create_renewal_decision(school_id: str, contract_id: str):
    """Open a renewal decision (PENDING). Returns the decision."""
    res = api_client.create_renewal_decision(
        school_id, create_renewal_decision_payload(contract_id), STAFF)
    return _ok(res, "create_renewal_decision")


# ---------------------------------------------------------------------------
# Tier 5: fees, appeals, closure (PRD §3.7–§3.9)
# ---------------------------------------------------------------------------
def create_fee_invoice(school_id: str, fiscal_year=2026, estimated_enrollment=400,
                       base_per_pupil_cents=800000, qualifying_supplemental_pupils=100):
    """Issue an ESTIMATED fee invoice. Returns the invoice."""
    res = api_client.create_fee_invoice(
        school_id,
        create_fee_invoice_payload(fiscal_year=fiscal_year,
                                   estimated_enrollment=estimated_enrollment,
                                   base_per_pupil_cents=base_per_pupil_cents,
                                   qualifying_supplemental_pupils=qualifying_supplemental_pupils),
        STAFF)
    return _ok(res, "create_fee_invoice")


def finalize_invoice(invoice_id: str, audited_enrollment: int):
    """ESTIMATED -> FINALIZED. Returns the invoice."""
    res = api_client.finalize_fee_invoice(
        invoice_id, {"audited_enrollment": audited_enrollment}, STAFF)
    return _ok(res, "finalize_fee_invoice")


def create_finalized_invoice(school_id: str, fiscal_year=2026, estimated_enrollment=400,
                             base_per_pupil_cents=800000,
                             qualifying_supplemental_pupils=100, audited_enrollment=None):
    """ESTIMATED invoice finalized with audited enrollment (defaults to estimated)."""
    invoice = create_fee_invoice(school_id, fiscal_year, estimated_enrollment,
                                 base_per_pupil_cents, qualifying_supplemental_pupils)
    return finalize_invoice(invoice["id"],
                            audited_enrollment if audited_enrollment is not None
                            else estimated_enrollment)


def create_closure_plan(school_id: str, reason="VOLUNTARY",
                        closure_date="2027-06-30T00:00:00Z", board_id="board_2"):
    """Board initiates a closure plan (school OPEN -> CLOSING). Returns the plan."""
    res = api_client.create_closure_plan(
        school_id, create_closure_plan_payload(reason=reason, closure_date=closure_date),
        make_board_headers(board_id))
    return _ok(res, "create_closure_plan")


def add_student_transition(plan_id: str, student_ref="stu_close_1"):
    """Add a PENDING student transition to a closure plan. Returns the transition."""
    res = api_client.add_student_transition(
        plan_id, create_student_transition_payload(student_ref=student_ref), STAFF)
    return _ok(res, "add_student_transition")


def file_application_denial_appeal(application_id: str, applicant_id: str,
                                   grounds="Procedural defect"):
    """Applicant files an APPLICATION_DENIAL appeal (school_id null). Returns the appeal."""
    res = api_client.file_appeal(
        create_appeal_payload(target_type="APPLICATION_DENIAL", target_id=application_id,
                              grounds=grounds),
        make_applicant_headers(applicant_id))
    return _ok(res, "file APPLICATION_DENIAL appeal")


def file_school_appeal(school_id: str, target_type: str, target_id: str,
                       grounds="Procedural defect"):
    """SchoolOperator files an appeal for its own school. Returns the appeal."""
    res = api_client.file_appeal(
        create_appeal_payload(target_type=target_type, target_id=target_id,
                              grounds=grounds, school_id=school_id),
        make_school_operator_headers(school_id))
    return _ok(res, f"file {target_type} appeal")


def schedule_appeal_hearing(appeal_id: str, hearing_officer_user_id: str):
    """FILED -> HEARING_SCHEDULED. Returns the appeal."""
    res = api_client.schedule_hearing(
        appeal_id, {"hearing_officer_user_id": hearing_officer_user_id}, STAFF)
    return _ok(res, "schedule_hearing")


def rule_appeal(appeal_id: str, officer_id: str, ruling: str):
    """Assigned officer rules on the appeal. Returns the appeal."""
    res = api_client.rule_appeal(appeal_id, {"ruling": ruling},
                                 make_appeals_officer_headers(officer_id))
    return _ok(res, f"rule_appeal({ruling})")
