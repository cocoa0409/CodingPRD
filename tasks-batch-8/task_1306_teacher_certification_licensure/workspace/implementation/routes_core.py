"""Routes: applicants, educator-prep programs, applications, transcripts,
test scores, background checks, reciprocity evaluations, deficiency plans,
emergency permits, and the admin clock."""
from flask import Blueprint, request

import errors
import services as svc
import util
from db import db
from middleware import require_roles, check_applicant_ownership, STAFF_ROLES
from response import success_object, success_list

bp = Blueprint("core", __name__)

ALL_READ = ("Applicant", "IntakeOfficer", "CredentialEvaluator", "BackgroundInvestigator",
            "LegalOfficer", "ProgramApprovalOfficer", "AgencyAdmin")

PATHWAYS = svc.PATHWAYS
SUBJECT_AREAS = svc.SUBJECT_AREAS
GRADE_BANDS = svc.GRADE_BANDS


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------

def applicant_view(a):
    return dict(a)


@bp.route("/licensure/applicants", methods=["POST"])
@require_roles("Anonymous")
def create_applicant(actor):
    body = util.get_body()
    util.require_fields(body, ["full_name", "email", "date_of_birth", "ssn_last4",
                               "moral_character_attestation"])
    full_name = util.require_string(body["full_name"], "full_name")
    email = util.require_string(body["email"], "email")
    dob = util.parse_iso(body["date_of_birth"], "date_of_birth")
    ssn = body["ssn_last4"]
    if not isinstance(ssn, str) or len(ssn) != 4 or not ssn.isdigit():
        raise errors.err_validation("ssn_last4 must be exactly 4 digits")
    mca = util.require_bool(body["moral_character_attestation"], "moral_character_attestation")
    if any(a["email"] == email for a in db.applicants.values()):
        raise errors.err_validation("email must be unique across applicants")
    applicant = util.stamp_new({
        "id": util.new_id(),
        "full_name": full_name,
        "email": email,
        "date_of_birth": util.to_iso(dob),
        "ssn_last4": ssn,
        "moral_character_attestation": mca,
        "status": "REGISTERED",
    })
    db.applicants[applicant["id"]] = applicant
    return success_object(applicant_view(applicant), 201)


@bp.route("/licensure/applicants/<applicantId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_applicant(actor, applicantId):
    applicant = db.applicants.get(applicantId)
    if applicant is None:
        raise errors.err_not_found("Applicant not found")
    check_applicant_ownership(actor, "applicant", applicant)
    return success_object(applicant_view(applicant))


@bp.route("/licensure/applicants", methods=["GET"])
@require_roles("IntakeOfficer", "CredentialEvaluator", "BackgroundInvestigator",
               "LegalOfficer", "ProgramApprovalOfficer", "AgencyAdmin")
def list_applicants(actor):
    status = request.args.get("status")
    items = list(db.applicants.values())
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = util.sorted_by_created(items)
    page, limit, offset, total = util.paginate(items)
    return success_list([applicant_view(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Educator Prep Programs
# ---------------------------------------------------------------------------

def program_view(p):
    return dict(p)


@bp.route("/licensure/educator-prep-programs", methods=["POST"])
@require_roles("ProgramApprovalOfficer")
def create_program(actor):
    body = util.get_body()
    util.require_fields(body, ["institution_name", "program_code", "approved_subject_areas"])
    name = util.require_string(body["institution_name"], "institution_name")
    code = util.require_string(body["program_code"], "program_code")
    areas = body["approved_subject_areas"]
    if not isinstance(areas, list):
        raise errors.err_validation("approved_subject_areas must be an array")
    for a in areas:
        util.require_enum(a, SUBJECT_AREAS, "approved_subject_areas")
    program = util.stamp_new({
        "id": util.new_id(),
        "institution_name": name,
        "program_code": code,
        "approved_subject_areas": list(areas),
        "approval_status": "CANDIDATE",
    })
    db.programs[program["id"]] = program
    return success_object(program_view(program), 201)


@bp.route("/licensure/educator-prep-programs/<programId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_program(actor, programId):
    program = db.programs.get(programId)
    if program is None:
        raise errors.err_not_found("Program not found")
    return success_object(program_view(program))


PROGRAM_TRANSITIONS = {
    "CANDIDATE": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"APPROVED", "APPROVAL_WITHDRAWN"},
    "APPROVED": {"PROBATION"},
    "PROBATION": {"APPROVED", "APPROVAL_WITHDRAWN"},
    "APPROVAL_WITHDRAWN": set(),
}


@bp.route("/licensure/educator-prep-programs/<programId>/state", methods=["POST"])
@require_roles("ProgramApprovalOfficer")
def program_state(actor, programId):
    program = db.programs.get(programId)
    if program is None:
        raise errors.err_not_found("Program not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, {"CANDIDATE", "UNDER_REVIEW", "APPROVED", "PROBATION",
                                  "APPROVAL_WITHDRAWN"}, "to_status")
    if to_status not in PROGRAM_TRANSITIONS[program["approval_status"]]:
        raise errors.err_invalid_state()
    old = program["approval_status"]
    program["approval_status"] = to_status
    util.touch(program)
    if old == "PROBATION" and to_status == "APPROVAL_WITHDRAWN":
        svc.cascade_program_withdrawn(program)
    return success_object(program_view(program))


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

def application_view(a):
    return dict(a)


@bp.route("/licensure/applications", methods=["POST"])
@require_roles("Applicant")
def create_application(actor):
    body = util.get_body()
    util.require_fields(body, ["applicant_id", "pathway", "subject_area", "grade_band"])
    applicant_id = body["applicant_id"]
    pathway = util.require_enum(body["pathway"], PATHWAYS, "pathway")
    subject_area = util.require_enum(body["subject_area"], SUBJECT_AREAS, "subject_area")
    grade_band = util.require_enum(body["grade_band"], GRADE_BANDS, "grade_band")
    program_id = body.get("program_id")
    expedite = body.get("expedite_requested", False)
    if not isinstance(expedite, bool):
        raise errors.err_validation("expedite_requested must be a boolean")
    applicant = db.applicants.get(applicant_id)
    if applicant is None:
        raise errors.err_not_found("Applicant not found")
    # ownership: Applicant may only act for itself
    if actor.user_id != applicant_id:
        raise errors.err_forbidden()
    # safety: barred
    if applicant["status"] == "BARRED":
        raise errors.err_applicant_barred()
    # pathway/program referential integrity at creation
    if pathway == "TRADITIONAL":
        if not program_id:
            raise errors.err_pathway_program_required()
        if program_id not in db.programs:
            raise errors.err_not_found("Program not found")
    else:
        if program_id:
            raise errors.err_pathway_program_required()
    # uniqueness: one non-terminal application per (applicant, subject_area)
    for a in db.applications.values():
        if (a["applicant_id"] == applicant_id and a["subject_area"] == subject_area
                and a["status"] not in svc.APP_TERMINAL):
            raise errors.err_duplicate_open_application()
    application = util.stamp_new({
        "id": util.new_id(),
        "applicant_id": applicant_id,
        "pathway": pathway,
        "subject_area": subject_area,
        "grade_band": grade_band,
        "program_id": program_id if pathway == "TRADITIONAL" else None,
        "expedite_requested": expedite,
        "fee_cents": 0,
        "fee_status": "UNPAID",
        "status": "SUBMITTED",
        "deficiency_hours_required": 0,
    })
    db.applications[application["id"]] = application
    application["fee_cents"] = svc.compute_application_fee(application)
    if applicant["status"] == "REGISTERED":
        applicant["status"] = "APPLICATION_IN_PROGRESS"
        util.touch(applicant)
    return success_object(application_view(application), 201)


@bp.route("/licensure/applications/<applicationId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_application(actor, applicationId):
    application = db.applications.get(applicationId)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    return success_object(application_view(application))


@bp.route("/licensure/applications", methods=["GET"])
@require_roles(*ALL_READ)
def list_applications(actor):
    applicant_id = request.args.get("applicant_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.applications.values())
    if actor.role == "Applicant":
        items = [a for a in items if a["applicant_id"] == actor.user_id]
    if applicant_id is not None:
        items = [a for a in items if a["applicant_id"] == applicant_id]
    if program_id is not None:
        items = [a for a in items if a.get("program_id") == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = util.sorted_by_created(items)
    page, limit, offset, total = util.paginate(items)
    return success_list([application_view(a) for a in page], limit, offset, total)


@bp.route("/licensure/applications/<applicationId>/fee-payment", methods=["POST"])
@require_roles("Applicant")
def pay_fee(actor, applicationId):
    application = db.applications.get(applicationId)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    body = util.get_body()
    util.require_fields(body, ["payment_token"])
    if application["fee_status"] == "PAID":
        raise errors.err_fee_already_paid()
    application["fee_status"] = "PAID"
    util.touch(application)
    return success_object(application_view(application))


# --- Application state machine ---

APP_TRANSITIONS = {
    "SUBMITTED": {"INTAKE_REVIEW", "WITHDRAWN"},
    "INTAKE_REVIEW": {"EVALUATION", "WITHDRAWN"},
    "EVALUATION": {"DEFICIENCY_PENDING", "BACKGROUND_REVIEW", "WITHDRAWN"},
    "DEFICIENCY_PENDING": {"EVALUATION", "WITHDRAWN"},
    "BACKGROUND_REVIEW": {"PENDING_DECISION"},
    "PENDING_DECISION": {"APPROVED", "DENIED"},
    "APPROVED": set(),
    "DENIED": set(),
    "WITHDRAWN": set(),
}

# Which roles may drive which targets on the application state endpoint
APP_STATE_ROLE_TARGETS = {
    "Applicant": {"WITHDRAWN"},
    "IntakeOfficer": {"INTAKE_REVIEW", "EVALUATION"},
    "CredentialEvaluator": {"DEFICIENCY_PENDING", "BACKGROUND_REVIEW", "APPROVED", "DENIED",
                            "EVALUATION"},
    "BackgroundInvestigator": {"PENDING_DECISION"},
}


@bp.route("/licensure/applications/<applicationId>/state", methods=["POST"])
@require_roles("Applicant", "IntakeOfficer", "CredentialEvaluator", "BackgroundInvestigator")
def application_state(actor, applicationId):
    application = db.applications.get(applicationId)
    if application is None:
        raise errors.err_not_found("Application not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(APP_TRANSITIONS.keys()), "to_status")

    # Role-target authorization
    allowed_targets = APP_STATE_ROLE_TARGETS.get(actor.role, set())
    if to_status not in allowed_targets:
        raise errors.err_forbidden()
    # CredentialEvaluator may only take EVALUATION from DEFICIENCY_PENDING
    if actor.role == "CredentialEvaluator" and to_status == "EVALUATION":
        if application["status"] != "DEFICIENCY_PENDING":
            raise errors.err_forbidden()
    # Applicant ownership for withdrawal
    if actor.role == "Applicant":
        check_applicant_ownership(actor, "application", application)

    current = application["status"]
    if to_status not in APP_TRANSITIONS[current]:
        raise errors.err_invalid_state()

    applicant = db.applicants.get(application["applicant_id"])

    # Precondition evaluation per transition
    if current == "SUBMITTED" and to_status == "INTAKE_REVIEW":
        if application["fee_status"] != "PAID":
            raise errors.err_fee_unpaid()
        if not (applicant and applicant.get("moral_character_attestation") is True):
            raise errors.err_moral_attestation()
        if applicant and applicant["status"] == "BARRED":
            raise errors.err_applicant_barred()
    elif current == "INTAKE_REVIEW" and to_status == "EVALUATION":
        if application["pathway"] == "TRADITIONAL":
            pid = application.get("program_id")
            if not pid:
                raise errors.err_pathway_program_required()
            program = db.programs.get(pid)
            if (program is None or program["approval_status"] != "APPROVED"
                    or application["subject_area"] not in program["approved_subject_areas"]):
                raise errors.err_program_not_approved()
        elif application["pathway"] == "RECIPROCITY":
            ev = svc.final_reciprocity_eval(application["id"])
            if ev is None or ev.get("outcome") == "DENIED":
                raise errors.err_reciprocity_not_finalized()
    elif current == "EVALUATION" and to_status == "DEFICIENCY_PENDING":
        if not (application.get("deficiency_hours_required") or 0) > 0:
            raise errors.err_deficiency_not_present()
    elif current == "DEFICIENCY_PENDING" and to_status == "EVALUATION":
        if not any(p["status"] == "COMPLETED" for p in svc.deficiency_plans_of(application["id"])):
            raise errors.err_deficiency_outstanding()
    elif current == "EVALUATION" and to_status == "BACKGROUND_REVIEW":
        # fixed inner order: transcripts, exams, deficiency, background
        transcripts = svc.transcripts_of(application["id"])
        if not transcripts or any(t["verification_status"] != "VERIFIED" for t in transcripts):
            raise errors.err_transcripts_unverified()
        verified_passing = {t["exam_code"] for t in svc.test_scores_of(application["id"])
                            if t["verification_status"] == "VERIFIED" and t.get("passing")}
        if any(e not in verified_passing for e in svc.required_exams(application)):
            raise errors.err_exam_requirement_unmet()
        if (application.get("deficiency_hours_required") or 0) > 0:
            raise errors.err_deficiency_outstanding()
        checks = svc.background_checks_of(application["id"])
        if not checks or all(c["status"] == "DENIED" for c in checks):
            raise errors.err_background_not_cleared()
    elif current == "BACKGROUND_REVIEW" and to_status == "PENDING_DECISION":
        checks = svc.background_checks_of(application["id"])
        if not any(c["status"] == "CLEARED" for c in checks):
            raise errors.err_background_not_cleared()

    # Execute transition + side effects
    application["status"] = to_status
    if current in ("SUBMITTED", "INTAKE_REVIEW", "EVALUATION", "DEFICIENCY_PENDING") \
            and to_status == "WITHDRAWN":
        if application["fee_status"] == "PAID":
            application["fee_status"] = "REFUNDED"
        if current in ("EVALUATION", "DEFICIENCY_PENDING"):
            svc.cascade_application_withdrawn(application)
    if current == "INTAKE_REVIEW" and to_status == "EVALUATION":
        svc.recompute_deficiency(application)
    if current == "DEFICIENCY_PENDING" and to_status == "EVALUATION":
        application["deficiency_hours_required"] = 0
    if current == "PENDING_DECISION" and to_status == "APPROVED":
        svc.cascade_application_approved(application)
    if current == "PENDING_DECISION" and to_status == "DENIED":
        svc.cascade_application_denied(application)
    util.touch(application)
    return success_object(application_view(application))


# ---------------------------------------------------------------------------
# Transcripts
# ---------------------------------------------------------------------------

def transcript_view(t):
    return dict(t)


DEGREE_LEVELS = {"BACHELORS", "MASTERS", "DOCTORATE"}
LETTER_GRADES = {"A", "A_MINUS", "B", "C", "D", "F"}


@bp.route("/licensure/applications/<id>/transcripts", methods=["POST"])
@require_roles("Applicant")
def create_transcript(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    body = util.get_body()
    util.require_fields(body, ["institution_name", "degree_level", "total_semester_hours", "courses"])
    inst = util.require_string(body["institution_name"], "institution_name")
    degree = util.require_enum(body["degree_level"], DEGREE_LEVELS, "degree_level")
    tsh = util.require_number(body["total_semester_hours"], "total_semester_hours")
    courses = body["courses"]
    if not isinstance(courses, list):
        raise errors.err_validation("courses must be an array")
    for c in courses:
        if not isinstance(c, dict):
            raise errors.err_validation("course entries must be objects")
        util.require_fields(c, ["course_code", "credit_hours", "letter_grade"])
        util.require_string(c["course_code"], "course_code")
        util.require_number(c["credit_hours"], "credit_hours")
        util.require_enum(c["letter_grade"], LETTER_GRADES, "letter_grade")
    transcript = util.stamp_new({
        "id": util.new_id(),
        "application_id": id,
        "institution_name": inst,
        "degree_level": degree,
        "total_semester_hours": tsh,
        "courses": [dict(c) for c in courses],
        "scaled_gpa": None,
        "subject_relevant_hours": None,
        "verification_status": "UNVERIFIED",
    })
    db.transcripts[transcript["id"]] = transcript
    # adding a transcript recomputes the fee
    application["fee_cents"] = svc.compute_application_fee(application)
    util.touch(application)
    return success_object(transcript_view(transcript), 201)


@bp.route("/licensure/applications/<id>/transcripts", methods=["GET"])
@require_roles(*ALL_READ)
def list_transcripts(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    items = util.sorted_by_created(svc.transcripts_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([transcript_view(t) for t in page], limit, offset, total)


@bp.route("/licensure/transcripts/<transcriptId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_transcript(actor, transcriptId):
    transcript = db.transcripts.get(transcriptId)
    if transcript is None:
        raise errors.err_not_found("Transcript not found")
    check_applicant_ownership(actor, "transcript", transcript)
    return success_object(transcript_view(transcript))


@bp.route("/licensure/transcripts/<transcriptId>/verify", methods=["POST"])
@require_roles("CredentialEvaluator")
def verify_transcript(actor, transcriptId):
    transcript = db.transcripts.get(transcriptId)
    if transcript is None:
        raise errors.err_not_found("Transcript not found")
    body = util.get_body()
    util.require_fields(body, ["verification_status"])
    target = util.require_enum(body["verification_status"], {"VERIFIED", "REJECTED"},
                               "verification_status")
    if transcript["verification_status"] != "UNVERIFIED":
        raise errors.err_invalid_state()
    if target == "VERIFIED":
        if "subject_relevant_hours" not in body or body["subject_relevant_hours"] is None:
            raise errors.err_validation("subject_relevant_hours is required when verifying")
        srh = util.require_number(body["subject_relevant_hours"], "subject_relevant_hours")
        transcript["scaled_gpa"] = svc.compute_scaled_gpa(transcript["courses"])
        transcript["subject_relevant_hours"] = srh
        transcript["verification_status"] = "VERIFIED"
        util.touch(transcript)
        application = db.applications.get(transcript["application_id"])
        if application is not None:
            svc.recompute_deficiency(application)
            util.touch(application)
    else:
        transcript["verification_status"] = "REJECTED"
        util.touch(transcript)
    return success_object(transcript_view(transcript))


# ---------------------------------------------------------------------------
# Test scores
# ---------------------------------------------------------------------------

def test_score_view(t):
    return dict(t)


EXAM_CODES = {"PRAXIS_CORE", "PRAXIS_SUBJECT", "PEDAGOGY"}


@bp.route("/licensure/applications/<id>/test-scores", methods=["POST"])
@require_roles("Applicant")
def create_test_score(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    body = util.get_body()
    util.require_fields(body, ["exam_code", "raw_score", "tested_on"])
    exam_code = util.require_enum(body["exam_code"], EXAM_CODES, "exam_code")
    raw_score = util.require_int(body["raw_score"], "raw_score", 0, 100)
    tested_on = util.parse_iso(body["tested_on"], "tested_on")
    ts = util.stamp_new({
        "id": util.new_id(),
        "application_id": id,
        "exam_code": exam_code,
        "raw_score": raw_score,
        "scaled_score": None,
        "passing": None,
        "tested_on": util.to_iso(tested_on),
        "verification_status": "REPORTED",
    })
    db.test_scores[ts["id"]] = ts
    return success_object(test_score_view(ts), 201)


@bp.route("/licensure/applications/<id>/test-scores", methods=["GET"])
@require_roles(*ALL_READ)
def list_test_scores(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    items = util.sorted_by_created(svc.test_scores_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([test_score_view(t) for t in page], limit, offset, total)


@bp.route("/licensure/test-scores/<testScoreId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_test_score(actor, testScoreId):
    ts = db.test_scores.get(testScoreId)
    if ts is None:
        raise errors.err_not_found("TestScore not found")
    check_applicant_ownership(actor, "test_score", ts)
    return success_object(test_score_view(ts))


@bp.route("/licensure/test-scores/<testScoreId>/verify", methods=["POST"])
@require_roles("CredentialEvaluator")
def verify_test_score(actor, testScoreId):
    ts = db.test_scores.get(testScoreId)
    if ts is None:
        raise errors.err_not_found("TestScore not found")
    body = util.get_body()
    util.require_fields(body, ["verification_status"])
    target = util.require_enum(body["verification_status"], {"VERIFIED", "REJECTED"},
                               "verification_status")
    if ts["verification_status"] != "REPORTED":
        raise errors.err_invalid_state()
    if target == "VERIFIED":
        scaled, passing = svc.compute_test_scaling(ts["exam_code"], ts["raw_score"])
        ts["scaled_score"] = scaled
        ts["passing"] = passing
        ts["verification_status"] = "VERIFIED"
        util.touch(ts)
        application = db.applications.get(ts["application_id"])
        if application is not None:
            svc.recompute_deficiency(application)
            util.touch(application)
    else:
        ts["verification_status"] = "REJECTED"
        util.touch(ts)
    return success_object(test_score_view(ts))


# ---------------------------------------------------------------------------
# Background checks
# ---------------------------------------------------------------------------

def bg_view(b):
    return dict(b)


OFFENSE_CATEGORIES = {"FELONY_VIOLENT", "FELONY_OTHER", "MISDEMEANOR_DRUG",
                      "MISDEMEANOR_OTHER", "INFRACTION"}
DISPOSITIONS = {"CONVICTION", "DISMISSED", "PENDING"}


def _validate_findings(findings):
    if not isinstance(findings, list):
        raise errors.err_validation("adverse_findings must be an array")
    for f in findings:
        if not isinstance(f, dict):
            raise errors.err_validation("finding entries must be objects")
        util.require_fields(f, ["offense_category", "offense_date", "disposition"])
        util.require_enum(f["offense_category"], OFFENSE_CATEGORIES, "offense_category")
        util.require_enum(f["disposition"], DISPOSITIONS, "disposition")
        util.parse_iso(f["offense_date"], "offense_date")


@bp.route("/licensure/applications/<id>/background-checks", methods=["POST"])
@require_roles("BackgroundInvestigator")
def create_background_check(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    body = util.get_body()
    util.require_fields(body, ["adverse_findings"])
    _validate_findings(body["adverse_findings"])
    # one non-terminal check per application
    for c in svc.background_checks_of(id):
        if c["status"] not in svc.BG_TERMINAL:
            raise errors.err_background_check_open()
    check = util.stamp_new({
        "id": util.new_id(),
        "application_id": id,
        "adverse_findings": [dict(f) for f in body["adverse_findings"]],
        "fingerprint_submitted_at": None,
        "risk_score": None,
        "status": "INITIATED",
    })
    db.background_checks[check["id"]] = check
    return success_object(bg_view(check), 201)


@bp.route("/licensure/applications/<id>/background-checks", methods=["GET"])
@require_roles(*ALL_READ)
def list_background_checks(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    items = util.sorted_by_created(svc.background_checks_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([bg_view(b) for b in page], limit, offset, total)


@bp.route("/licensure/background-checks/<checkId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_background_check(actor, checkId):
    check = db.background_checks.get(checkId)
    if check is None:
        raise errors.err_not_found("BackgroundCheck not found")
    check_applicant_ownership(actor, "background_check", check)
    return success_object(bg_view(check))


BG_TRANSITIONS = {
    "INITIATED": {"PRINTS_SUBMITTED"},
    "PRINTS_SUBMITTED": set(),
    "CLEARED": set(),
    "FLAGGED": {"ADJUDICATION"},
    "ADJUDICATION": {"CLEARED", "DENIED"},
    "DENIED": set(),
}

BG_ROLE_TARGETS = {
    "BackgroundInvestigator": {"PRINTS_SUBMITTED"},
    "LegalOfficer": {"ADJUDICATION", "CLEARED", "DENIED"},
}


@bp.route("/licensure/background-checks/<checkId>/state", methods=["POST"])
@require_roles("BackgroundInvestigator", "LegalOfficer")
def background_check_state(actor, checkId):
    check = db.background_checks.get(checkId)
    if check is None:
        raise errors.err_not_found("BackgroundCheck not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, set(BG_TRANSITIONS.keys()), "to_status")
    if to_status not in BG_ROLE_TARGETS.get(actor.role, set()):
        raise errors.err_forbidden()
    current = check["status"]
    if to_status not in BG_TRANSITIONS[current]:
        raise errors.err_invalid_state()
    if current == "INITIATED" and to_status == "PRINTS_SUBMITTED":
        if "fingerprint_submitted_at" not in body or body["fingerprint_submitted_at"] is None:
            raise errors.err_validation("fingerprint_submitted_at is required")
        fps = util.parse_iso(body["fingerprint_submitted_at"], "fingerprint_submitted_at")
        check["fingerprint_submitted_at"] = util.to_iso(fps)
        risk, forced = svc.compute_risk_score(check["adverse_findings"], fps)
        check["risk_score"] = risk
        if risk < svc.CLEAR_THRESHOLD_EXCLUSIVE and not forced:
            check["status"] = "CLEARED"
        else:
            check["status"] = "FLAGGED"
        util.touch(check)
        return success_object(bg_view(check))
    # FLAGGED -> ADJUDICATION, ADJUDICATION -> CLEARED / DENIED
    check["status"] = to_status
    util.touch(check)
    if current == "ADJUDICATION" and to_status == "DENIED":
        application = db.applications.get(check["application_id"])
        if application is not None and application["status"] == "BACKGROUND_REVIEW":
            application["status"] = "DENIED"
            util.touch(application)
            svc.cascade_application_denied(application)
    return success_object(bg_view(check))


# ---------------------------------------------------------------------------
# Reciprocity evaluations
# ---------------------------------------------------------------------------

def recip_view(r):
    return dict(r)


SOURCE_LICENSE_TYPES = {"STANDARD", "PROFESSIONAL", "PROVISIONAL"}
MAPPING_MODES = {"DETERMINISTIC", "COMMITTEE"}


@bp.route("/licensure/applications/<id>/reciprocity-evaluations", methods=["POST"])
@require_roles("CredentialEvaluator")
def create_reciprocity_evaluation(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    body = util.get_body()
    util.require_fields(body, ["source_state", "source_license_type", "years_teaching"])
    if application["pathway"] != "RECIPROCITY":
        raise errors.err_validation("reciprocity evaluations are only for pathway=RECIPROCITY")
    source_state = util.require_string(body["source_state"], "source_state")
    slt = util.require_enum(body["source_license_type"], SOURCE_LICENSE_TYPES, "source_license_type")
    years = util.require_int(body["years_teaching"], "years_teaching", 0)
    evaluation = util.stamp_new({
        "id": util.new_id(),
        "application_id": id,
        "source_state": source_state,
        "source_license_type": slt,
        "years_teaching": years,
        "mapping_mode": None,
        "outcome": None,
        "deficiency_subject_hours": None,
        "finalized": False,
    })
    db.reciprocity_evaluations[evaluation["id"]] = evaluation
    return success_object(recip_view(evaluation), 201)


@bp.route("/licensure/applications/<id>/reciprocity-evaluations", methods=["GET"])
@require_roles(*ALL_READ)
def list_reciprocity_evaluations(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    items = util.sorted_by_created(svc.reciprocity_evals_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([recip_view(r) for r in page], limit, offset, total)


@bp.route("/licensure/reciprocity-evaluations/<evaluationId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_reciprocity_evaluation(actor, evaluationId):
    evaluation = db.reciprocity_evaluations.get(evaluationId)
    if evaluation is None:
        raise errors.err_not_found("ReciprocityEvaluation not found")
    check_applicant_ownership(actor, "reciprocity_evaluation", evaluation)
    return success_object(recip_view(evaluation))


@bp.route("/licensure/reciprocity-evaluations/<evaluationId>/finalize", methods=["POST"])
@require_roles("CredentialEvaluator")
def finalize_reciprocity_evaluation(actor, evaluationId):
    evaluation = db.reciprocity_evaluations.get(evaluationId)
    if evaluation is None:
        raise errors.err_not_found("ReciprocityEvaluation not found")
    body = util.get_body()
    util.require_fields(body, ["mapping_mode"])
    mode = util.require_enum(body["mapping_mode"], MAPPING_MODES, "mapping_mode")
    if evaluation.get("finalized"):
        raise errors.err_invalid_state("ReciprocityEvaluation already finalized")
    outcome, hours = svc.compute_reciprocity_outcome(
        evaluation["source_state"], evaluation["source_license_type"],
        evaluation["years_teaching"], mode)
    evaluation["mapping_mode"] = mode
    evaluation["outcome"] = outcome
    evaluation["deficiency_subject_hours"] = hours
    evaluation["finalized"] = True
    util.touch(evaluation)
    return success_object(recip_view(evaluation))


# ---------------------------------------------------------------------------
# Deficiency plans
# ---------------------------------------------------------------------------

def plan_view(p):
    return dict(p)


@bp.route("/licensure/applications/<id>/deficiency-plans", methods=["POST"])
@require_roles("CredentialEvaluator")
def create_deficiency_plan(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    body = util.get_body()
    util.require_fields(body, ["expected_application_version"])
    expected = util.require_int(body["expected_application_version"], "expected_application_version")
    if expected != application["version"]:
        raise errors.err_stale_version()
    # supersede existing PROPOSED plan
    for plan in svc.deficiency_plans_of(id):
        if plan["status"] == "PROPOSED":
            plan["status"] = "SUPERSEDED"
            util.touch(plan)
    now = db.now()
    plan = util.stamp_new({
        "id": util.new_id(),
        "application_id": id,
        "required_hours": application.get("deficiency_hours_required") or 0,
        "completed_hours": 0,
        "deadline": util.to_iso(now.replace() + __import__("datetime").timedelta(days=730)),
        "extension_used": False,
        "status": "PROPOSED",
    })
    db.deficiency_plans[plan["id"]] = plan
    util.touch(application)
    return success_object(plan_view(plan), 201)


@bp.route("/licensure/applications/<id>/deficiency-plans", methods=["GET"])
@require_roles(*ALL_READ)
def list_deficiency_plans(actor, id):
    application = db.applications.get(id)
    if application is None:
        raise errors.err_not_found("Application not found")
    check_applicant_ownership(actor, "application", application)
    items = util.sorted_by_created(svc.deficiency_plans_of(id))
    page, limit, offset, total = util.paginate(items)
    return success_list([plan_view(p) for p in page], limit, offset, total)


@bp.route("/licensure/deficiency-plans/<planId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_deficiency_plan(actor, planId):
    plan = db.deficiency_plans.get(planId)
    if plan is None:
        raise errors.err_not_found("DeficiencyPlan not found")
    check_applicant_ownership(actor, "deficiency_plan", plan)
    return success_object(plan_view(plan))


@bp.route("/licensure/deficiency-plans/<planId>/state", methods=["POST"])
@require_roles("CredentialEvaluator")
def deficiency_plan_state(actor, planId):
    plan = db.deficiency_plans.get(planId)
    if plan is None:
        raise errors.err_not_found("DeficiencyPlan not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, {"PROPOSED", "ACCEPTED", "IN_PROGRESS", "COMPLETED",
                                  "DEFAULTED", "EXTENDED", "SUPERSEDED"}, "to_status")
    current = plan["status"]
    allowed = {}
    if current == "PROPOSED":
        allowed = {"ACCEPTED"}
    elif current == "DEFAULTED":
        allowed = {"EXTENDED"}
    if to_status not in allowed:
        raise errors.err_invalid_state()
    if current == "DEFAULTED" and to_status == "EXTENDED":
        if plan.get("extension_used"):
            raise errors.err_plan_deadline_passed()
        plan["extension_used"] = True
        deadline = util.parse_iso(plan["deadline"])
        from datetime import timedelta
        plan["deadline"] = util.to_iso(deadline + timedelta(days=365))
    plan["status"] = to_status
    util.touch(plan)
    return success_object(plan_view(plan))


@bp.route("/licensure/deficiency-plans/<planId>/evidence", methods=["POST"])
@require_roles("CredentialEvaluator")
def post_deficiency_evidence(actor, planId):
    plan = db.deficiency_plans.get(planId)
    if plan is None:
        raise errors.err_not_found("DeficiencyPlan not found")
    body = util.get_body()
    util.require_fields(body, ["hours"])
    hours = util.require_number(body["hours"], "hours", gt=0)
    if plan["status"] not in ("ACCEPTED", "IN_PROGRESS", "EXTENDED"):
        raise errors.err_invalid_state()
    plan["completed_hours"] = (plan.get("completed_hours") or 0) + hours
    plan["status"] = "IN_PROGRESS"
    if plan["completed_hours"] >= plan["required_hours"]:
        plan["status"] = "COMPLETED"
    util.touch(plan)
    return success_object(plan_view(plan))


# ---------------------------------------------------------------------------
# Emergency permits
# ---------------------------------------------------------------------------

def permit_view(p):
    return dict(p)


@bp.route("/licensure/applications/<applicationId>/emergency-permits", methods=["POST"])
@require_roles("CredentialEvaluator")
def create_emergency_permit(actor, applicationId):
    application = db.applications.get(applicationId)
    if application is None:
        raise errors.err_not_found("Application not found")
    body = util.get_body()
    util.require_fields(body, ["district_code", "valid_from", "valid_until"])
    district_code = util.require_string(body["district_code"], "district_code")
    valid_from = util.parse_iso(body["valid_from"], "valid_from")
    valid_until = util.parse_iso(body["valid_until"], "valid_until")
    if valid_until < valid_from:
        raise errors.err_validation("valid_until must not be earlier than valid_from")
    # state precondition
    if application["status"] != "DEFICIENCY_PENDING":
        raise errors.err_invalid_state()
    if not any(p["status"] in ("ACCEPTED", "IN_PROGRESS")
               for p in svc.deficiency_plans_of(applicationId)):
        raise errors.err_invalid_state()
    # safety: background hold on any of the applicant's checks
    applicant_id = application["applicant_id"]
    for app in db.applications.values():
        if app["applicant_id"] != applicant_id:
            continue
        for check in svc.background_checks_of(app["id"]):
            if check["status"] in ("FLAGGED", "ADJUDICATION"):
                raise errors.err_background_hold()
    # temporal: duration <= 365 days
    if (valid_until - valid_from).total_seconds() > 365 * 86400:
        raise errors.err_permit_duration_exceeded()
    # overlap: half-open [valid_from, valid_until) per (applicant, district)
    for p in svc.permits_of_applicant(applicant_id):
        if p["district_code"] != district_code or p["status"] not in ("ISSUED", "ACTIVE"):
            continue
        p_from = util.parse_iso(p["valid_from"])
        p_until = util.parse_iso(p["valid_until"])
        if valid_from < p_until and p_from < valid_until:
            raise errors.err_permit_interval_overlap()
    permit = util.stamp_new({
        "id": util.new_id(),
        "application_id": applicationId,
        "applicant_id": applicant_id,
        "district_code": district_code,
        "valid_from": util.to_iso(valid_from),
        "valid_until": util.to_iso(valid_until),
        "status": "ISSUED",
    })
    db.emergency_permits[permit["id"]] = permit
    return success_object(permit_view(permit), 201)


@bp.route("/licensure/emergency-permits/<permitId>", methods=["GET"])
@require_roles(*ALL_READ)
def get_emergency_permit(actor, permitId):
    permit = db.emergency_permits.get(permitId)
    if permit is None:
        raise errors.err_not_found("EmergencyPermit not found")
    check_applicant_ownership(actor, "emergency_permit", permit)
    return success_object(permit_view(permit))


@bp.route("/licensure/emergency-permits", methods=["GET"])
@require_roles(*ALL_READ)
def list_emergency_permits(actor):
    application_id = request.args.get("application_id")
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    items = list(db.emergency_permits.values())
    if actor.role == "Applicant":
        items = [p for p in items if p["applicant_id"] == actor.user_id]
    if application_id is not None:
        items = [p for p in items if p["application_id"] == application_id]
    if applicant_id is not None:
        items = [p for p in items if p["applicant_id"] == applicant_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = util.sorted_by_created(items)
    page, limit, offset, total = util.paginate(items)
    return success_list([permit_view(p) for p in page], limit, offset, total)


@bp.route("/licensure/emergency-permits/<permitId>/state", methods=["POST"])
@require_roles("LegalOfficer", "CredentialEvaluator")
def emergency_permit_state(actor, permitId):
    permit = db.emergency_permits.get(permitId)
    if permit is None:
        raise errors.err_not_found("EmergencyPermit not found")
    body = util.get_body()
    util.require_fields(body, ["to_status"])
    to_status = body["to_status"]
    util.require_enum(to_status, {"ISSUED", "ACTIVE", "EXPIRED", "CONVERTED", "REVOKED"},
                      "to_status")
    # Manual revocation only: ISSUED/ACTIVE -> REVOKED
    if to_status != "REVOKED" or permit["status"] not in ("ISSUED", "ACTIVE"):
        raise errors.err_invalid_state()
    permit["status"] = "REVOKED"
    util.touch(permit)
    return success_object(permit_view(permit))


# ---------------------------------------------------------------------------
# Admin clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("AgencyAdmin")
def set_clock(actor):
    body = util.get_body()
    util.require_fields(body, ["to_iso8601"])
    target = util.parse_iso(body["to_iso8601"], "to_iso8601")
    db.set_clock(target)
    svc.sweep_clock()
    return success_object({"current_utc": util.to_iso(db.now())})
