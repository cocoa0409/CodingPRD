"""Composite setup helpers.

Every helper builds preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server with an empty
database). Setup calls use get_success_data so failures surface as clear
"Setup failed" errors. Ownership-gated calls always thread the real
Applicant id through make_applicant_headers (PRD section 2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PRINTS_AT
from .factories import (
    create_applicant_payload,
    create_application_payload,
    create_background_check_payload,
    create_ce_audit_payload,
    create_ce_credit_payload,
    create_disciplinary_action_payload,
    create_emergency_permit_payload,
    create_endorsement_payload,
    create_misconduct_case_payload,
    create_program_payload,
    create_reciprocity_evaluation_payload,
    create_test_score_payload,
    create_transcript_payload,
)
from .test_users import (
    TEST_USERS,
    make_applicant_headers,
    make_background_investigator_headers,
    make_legal_officer_headers,
)

ANON = TEST_USERS["anonymous_headers"]
INTAKE = TEST_USERS["intake_officer_headers"]
EVALUATOR = TEST_USERS["credential_evaluator_headers"]
INVESTIGATOR = TEST_USERS["background_investigator_headers"]
LEGAL = TEST_USERS["legal_officer_headers"]
PAO = TEST_USERS["program_approval_officer_headers"]
ADMIN = TEST_USERS["agency_admin_headers"]


def _fail(step, resp):
    raise AssertionError(
        f"Setup failed at {step}: HTTP {resp.status_code} {resp.text}"
    )


def _ok(step, resp, expected_status=None):
    if expected_status is not None and resp.status_code != expected_status:
        _fail(step, resp)
    data = get_success_data(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 1 — single-entity creation and simple transitions
# ---------------------------------------------------------------------------

def register_applicant(**overrides):
    resp = api_client.create_applicant(create_applicant_payload(**overrides), ANON)
    return _ok("register_applicant", resp, expected_status=201)


def create_approved_program(approved_subject_areas=None, **overrides):
    if approved_subject_areas is not None:
        overrides["approved_subject_areas"] = approved_subject_areas
    resp = api_client.create_program(create_program_payload(**overrides), PAO)
    program = _ok("create_program", resp, expected_status=201)
    resp = api_client.transition_program(
        program["id"], {"to_status": "UNDER_REVIEW"}, PAO)
    _ok("program UNDER_REVIEW", resp)
    resp = api_client.transition_program(
        program["id"], {"to_status": "APPROVED"}, PAO)
    return _ok("program APPROVED", resp)


def create_application(applicant_id, **overrides):
    resp = api_client.create_application(
        create_application_payload(applicant_id, **overrides),
        make_applicant_headers(applicant_id),
    )
    return _ok("create_application", resp, expected_status=201)


def pay_application_fee(application_id, applicant_id, token="tok_1"):
    resp = api_client.pay_application_fee(
        application_id, {"payment_token": token},
        make_applicant_headers(applicant_id))
    return _ok("pay_application_fee", resp)


def advance_application(application_id, to_status, headers):
    resp = api_client.transition_application(
        application_id, {"to_status": to_status}, headers)
    return _ok(f"application -> {to_status}", resp)


def withdraw_application(application_id, applicant_id):
    return advance_application(
        application_id, "WITHDRAWN", make_applicant_headers(applicant_id))


def add_transcript(application_id, applicant_id, **overrides):
    resp = api_client.create_transcript(
        application_id, create_transcript_payload(**overrides),
        make_applicant_headers(applicant_id))
    return _ok("create_transcript", resp, expected_status=201)


def verify_transcript(transcript_id, subject_relevant_hours=18):
    resp = api_client.verify_transcript(
        transcript_id,
        {"verification_status": "VERIFIED",
         "subject_relevant_hours": subject_relevant_hours},
        EVALUATOR)
    return _ok("verify_transcript", resp)


def add_and_verify_transcript(application_id, applicant_id,
                              subject_relevant_hours=18, **overrides):
    transcript = add_transcript(application_id, applicant_id, **overrides)
    return verify_transcript(transcript["id"], subject_relevant_hours)


def report_test_score(application_id, applicant_id, exam_code="PRAXIS_SUBJECT",
                      raw_score=60, tested_on="2026-07-01T00:00:00Z"):
    resp = api_client.create_test_score(
        application_id,
        create_test_score_payload(exam_code=exam_code, raw_score=raw_score,
                                  tested_on=tested_on),
        make_applicant_headers(applicant_id))
    return _ok("create_test_score", resp, expected_status=201)


def verify_test_score(test_score_id):
    resp = api_client.verify_test_score(
        test_score_id, {"verification_status": "VERIFIED"}, EVALUATOR)
    return _ok("verify_test_score", resp)


def report_and_verify_score(application_id, applicant_id, exam_code,
                            raw_score, tested_on="2026-07-01T00:00:00Z"):
    score = report_test_score(application_id, applicant_id, exam_code,
                              raw_score, tested_on)
    return verify_test_score(score["id"])


def open_background_check(application_id, adverse_findings=None):
    resp = api_client.create_background_check(
        application_id,
        create_background_check_payload(adverse_findings=adverse_findings or []),
        INVESTIGATOR)
    return _ok("create_background_check", resp, expected_status=201)


def submit_prints(check_id, fingerprint_submitted_at=PRINTS_AT):
    resp = api_client.transition_background_check(
        check_id,
        {"to_status": "PRINTS_SUBMITTED",
         "fingerprint_submitted_at": fingerprint_submitted_at},
        INVESTIGATOR)
    return _ok("submit_prints", resp)


def open_and_submit_background_check(application_id, adverse_findings=None,
                                     fingerprint_submitted_at=PRINTS_AT):
    check = open_background_check(application_id, adverse_findings)
    return submit_prints(check["id"], fingerprint_submitted_at)


def create_and_finalize_reciprocity(application_id, source_state="TX",
                                    source_license_type="STANDARD",
                                    years_teaching=5,
                                    mapping_mode="DETERMINISTIC"):
    resp = api_client.create_reciprocity_evaluation(
        application_id,
        create_reciprocity_evaluation_payload(
            source_state=source_state, source_license_type=source_license_type,
            years_teaching=years_teaching),
        EVALUATOR)
    evaluation = _ok("create_reciprocity_evaluation", resp, expected_status=201)
    resp = api_client.finalize_reciprocity_evaluation(
        evaluation["id"], {"mapping_mode": mapping_mode}, EVALUATOR)
    return _ok("finalize_reciprocity_evaluation", resp)


def create_deficiency_plan(application_id, expected_application_version):
    resp = api_client.create_deficiency_plan(
        application_id,
        {"expected_application_version": expected_application_version},
        EVALUATOR)
    return _ok("create_deficiency_plan", resp, expected_status=201)


def transition_plan(plan_id, to_status):
    resp = api_client.transition_deficiency_plan(
        plan_id, {"to_status": to_status}, EVALUATOR)
    return _ok(f"plan -> {to_status}", resp)


def post_plan_evidence(plan_id, hours):
    resp = api_client.post_plan_evidence(plan_id, {"hours": hours}, EVALUATOR)
    return _ok("post_plan_evidence", resp)


def issue_emergency_permit(application_id, district_code="D01",
                           valid_from="2026-09-01T00:00:00Z",
                           valid_until="2027-03-01T00:00:00Z"):
    resp = api_client.create_emergency_permit(
        application_id,
        create_emergency_permit_payload(district_code=district_code,
                                        valid_from=valid_from,
                                        valid_until=valid_until),
        EVALUATOR)
    return _ok("create_emergency_permit", resp, expected_status=201)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return _ok("set_clock", resp)


def get_license_for_application(application_id):
    resp = api_client.list_licenses(
        EVALUATOR, params={"application_id": application_id})
    data = _ok("list_licenses", resp)
    assert isinstance(data, list) and len(data) == 1, (
        f"Setup failed: expected exactly one license for application "
        f"{application_id}, got {data}")
    return data[0]


# ---------------------------------------------------------------------------
# Tier 2/3 — lifecycle composites
# ---------------------------------------------------------------------------

def setup_paid_application_in_intake(applicant, pathway="RECIPROCITY",
                                     subject_area="MATHEMATICS",
                                     grade_band="G7_12", **app_overrides):
    """Applicant + application, fee PAID, advanced to INTAKE_REVIEW."""
    app = create_application(applicant["id"], pathway=pathway,
                             subject_area=subject_area, grade_band=grade_band,
                             **app_overrides)
    pay_application_fee(app["id"], applicant["id"])
    app = advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
    return app


def setup_reciprocity_full_in_evaluation(applicant, subject_area="MATHEMATICS",
                                         years_teaching=5,
                                         subject_relevant_hours=18):
    """RECIPROCITY application advanced to EVALUATION with a finalized
    TX/STANDARD DETERMINISTIC evaluation (outcome FULL) and one VERIFIED
    transcript. Returns the application dict as of EVALUATION."""
    app = setup_paid_application_in_intake(applicant, pathway="RECIPROCITY",
                                           subject_area=subject_area)
    create_and_finalize_reciprocity(app["id"], years_teaching=years_teaching)
    app = advance_application(app["id"], "EVALUATION", INTAKE)
    add_and_verify_transcript(app["id"], applicant["id"],
                              subject_relevant_hours=subject_relevant_hours)
    return app


def setup_licensed_applicant(years_teaching=5, subject_area="MATHEMATICS",
                             grade_band="G7_12", **applicant_overrides):
    """Full approval chain at the default logical clock: RECIPROCITY
    TX/STANDARD DETERMINISTIC (FULL, zero deficiency), one VERIFIED
    transcript, clean background check, through to APPROVED.
    Returns {"applicant", "application", "license"}."""
    applicant = register_applicant(**applicant_overrides)
    app = setup_reciprocity_full_in_evaluation(
        applicant, subject_area=subject_area, years_teaching=years_teaching)
    open_and_submit_background_check(app["id"], adverse_findings=[])
    app = advance_application(app["id"], "BACKGROUND_REVIEW", EVALUATOR)
    app = advance_application(app["id"], "PENDING_DECISION", INVESTIGATOR)
    app = advance_application(app["id"], "APPROVED", EVALUATOR)
    license_ = get_license_for_application(app["id"])
    return {"applicant": applicant, "application": app, "license": license_}


def setup_deficiency_pending_application(plan_hours_required=30,
                                         accept_plan=False,
                                         **applicant_overrides):
    """ALTERNATIVE SCIENCE application (no transcripts, no exams) advanced to
    DEFICIENCY_PENDING with deficiency_hours_required 30.
    When accept_plan is True, also creates and ACCEPTs a deficiency plan.
    Returns {"applicant", "application", "plan" (or None)}."""
    applicant = register_applicant(**applicant_overrides)
    app = create_application(applicant["id"], pathway="ALTERNATIVE",
                             subject_area="SCIENCE", grade_band="G5_8")
    pay_application_fee(app["id"], applicant["id"])
    app = advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
    app = advance_application(app["id"], "EVALUATION", INTAKE)
    app = advance_application(app["id"], "DEFICIENCY_PENDING", EVALUATOR)
    plan = None
    if accept_plan:
        plan = create_deficiency_plan(app["id"], app["version"])
        plan = transition_plan(plan["id"], "ACCEPTED")
    return {"applicant": applicant, "application": app, "plan": plan}


def add_verified_ce_credit(license_id, applicant_id, category, hours,
                           earned_on, provider_name="CE Provider"):
    resp = api_client.create_ce_credit(
        license_id,
        create_ce_credit_payload(provider_name=provider_name,
                                 category=category, hours=hours,
                                 earned_on=earned_on),
        make_applicant_headers(applicant_id))
    credit = _ok("create_ce_credit", resp, expected_status=201)
    resp = api_client.transition_ce_credit(
        credit["id"], {"to_status": "VERIFIED"}, EVALUATOR)
    return _ok("verify ce credit", resp)


def open_ce_audit(license_id, audit_variant="STANDARD"):
    resp = api_client.create_ce_audit(
        license_id, create_ce_audit_payload(audit_variant=audit_variant),
        EVALUATOR)
    return _ok("create_ce_audit", resp, expected_status=201)


def post_determination(audit_id, expected_ce_audit_version):
    resp = api_client.post_audit_determination(
        audit_id, {"expected_ce_audit_version": expected_ce_audit_version},
        EVALUATOR)
    return _ok("post_audit_determination", resp, expected_status=201)


def transition_audit(audit_id, to_status):
    resp = api_client.transition_ce_audit(
        audit_id, {"to_status": to_status}, EVALUATOR)
    return _ok(f"audit -> {to_status}", resp)


def setup_adjudicated_case(license_id, allegation_category="INCOMPETENCE",
                           investigator_id="inv-1", adjudicator_id="legal-1",
                           finding="SUBSTANTIATED"):
    """Misconduct case walked OPENED -> INVESTIGATING -> HEARING ->
    ADJUDICATED. The investigating user id and the adjudicating user id are
    distinct (segregation of duties, PRD section 3.9)."""
    resp = api_client.create_misconduct_case(
        license_id,
        create_misconduct_case_payload(allegation_category=allegation_category),
        LEGAL)
    case = _ok("create_misconduct_case", resp, expected_status=201)
    resp = api_client.transition_misconduct_case(
        case["id"], {"to_status": "INVESTIGATING"},
        make_background_investigator_headers(investigator_id))
    case = _ok("case INVESTIGATING", resp)
    resp = api_client.transition_misconduct_case(
        case["id"], {"to_status": "HEARING"}, LEGAL)
    case = _ok("case HEARING", resp)
    resp = api_client.transition_misconduct_case(
        case["id"], {"to_status": "ADJUDICATED", "finding": finding},
        make_legal_officer_headers(adjudicator_id))
    return _ok("case ADJUDICATED", resp)


def propose_action(case_id, sanction_type="REPRIMAND", **overrides):
    resp = api_client.create_disciplinary_action(
        case_id,
        create_disciplinary_action_payload(sanction_type=sanction_type,
                                           **overrides),
        LEGAL)
    return _ok("create_disciplinary_action", resp, expected_status=201)


def issue_action(action_id):
    resp = api_client.transition_disciplinary_action(
        action_id, {"to_status": "ISSUED"}, LEGAL)
    return _ok("action ISSUED", resp)


def request_endorsement(license_id, applicant_id,
                        subject_area="SPECIAL_EDUCATION", grade_band="PK_6"):
    resp = api_client.create_endorsement(
        license_id,
        create_endorsement_payload(subject_area=subject_area,
                                   grade_band=grade_band),
        make_applicant_headers(applicant_id))
    return _ok("create_endorsement", resp, expected_status=201)


def transition_endorsement(endorsement_id, to_status, headers):
    resp = api_client.transition_endorsement(
        endorsement_id, {"to_status": to_status}, headers)
    return _ok(f"endorsement -> {to_status}", resp)
