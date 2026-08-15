"""Routes: postings, applications, credentials, faculty."""

from flask import Blueprint, request

import errors
import helpers
import services
from helpers import (
    MAX_REVISIONS,
    TIER_RANK,
    find_or_404,
    list_response,
    new_record,
    opt_enum,
    parse_date,
    req_date,
    req_enum,
    req_str,
    success_obj,
    term_by_code,
    today,
    touch,
)
from store import STORE

bp = Blueprint("hiring", __name__)

READ_ROLES = ["HRAdmin", "HRReviewer", "DepartmentChair", "Dean"]
TIER_ORDER = ["BACHELORS", "MASTERS", "DOCTORATE"]
CRED_KINDS = ["TRANSCRIPT", "DEGREE", "LICENSE", "BACKGROUND_CHECK", "TRAINING"]


def _out(rec):
    out = dict(rec)
    out.pop("_seq", None)
    return out


# ---------------------------------------------------------------------------
# Postings
# ---------------------------------------------------------------------------

@bp.post("/postings")
def create_posting():
    helpers.require_roles(["DepartmentChair"])
    data = helpers.body()
    department_id = data.get("department_id")
    if not isinstance(department_id, str) or not department_id:
        raise errors.invalid_request("Field 'department_id' is required")
    dept = find_or_404("departments", department_id, "Department")
    term_code = req_str(data, "term_code")
    title = req_str(data, "title")
    min_tier = req_enum(data, "min_education_tier", TIER_ORDER)
    open_date = req_date(data, "open_date")
    close_date = req_date(data, "close_date")
    if parse_date(close_date) < parse_date(open_date):
        raise errors.invalid_date_range("close_date must be on or after open_date")
    rec = new_record()
    rec.update(
        {
            "department_id": dept["id"],
            "term_code": term_code,
            "title": title,
            "min_education_tier": min_tier,
            "open_date": open_date,
            "close_date": close_date,
            "posting_status": "DRAFT",
        }
    )
    STORE["postings"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/postings/<rid>")
def get_posting(rid):
    helpers.require_roles(READ_ROLES)
    return success_obj(_out(find_or_404("postings", rid, "Posting")))


@bp.get("/postings")
def list_postings():
    helpers.require_roles(READ_ROLES)
    return list_response(
        STORE["postings"].values(),
        {
            "department_id": request.args.get("department_id"),
            "posting_status": request.args.get("posting_status"),
        },
    )


@bp.post("/postings/<rid>/publish")
def publish_posting(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("postings", rid, "Posting")
    if rec["posting_status"] != "DRAFT":
        raise errors.invalid_state("Posting is not DRAFT")
    dept = STORE["departments"].get(rec["department_id"])
    if dept is None or not dept["active"]:
        raise errors.invalid_state("Department is not active")
    term = term_by_code(rec["term_code"])
    if term is None or term["rollover_status"] == "ROLLED_OVER":
        raise errors.invalid_state("Term is not publishable")
    if today() > parse_date(rec["close_date"]):
        raise errors.invalid_state("Posting close_date has passed")
    rec["posting_status"] = "OPEN"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/postings/<rid>/suspend")
def suspend_posting(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("postings", rid, "Posting")
    if rec["posting_status"] != "OPEN":
        raise errors.invalid_state("Posting is not OPEN")
    rec["posting_status"] = "SUSPENDED"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/postings/<rid>/resume")
def resume_posting(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("postings", rid, "Posting")
    if rec["posting_status"] != "SUSPENDED":
        raise errors.invalid_state("Posting is not SUSPENDED")
    if today() > parse_date(rec["close_date"]):
        raise errors.invalid_state("Posting close_date has passed")
    rec["posting_status"] = "OPEN"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/postings/<rid>/close")
def close_posting(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("postings", rid, "Posting")
    if rec["posting_status"] not in ("OPEN", "SUSPENDED"):
        raise errors.invalid_state("Posting is not OPEN or SUSPENDED")
    rec["posting_status"] = "CLOSED"
    touch(rec)
    services.close_posting_cascade(rec)
    return success_obj(_out(rec))


@bp.post("/postings/<rid>/archive")
def archive_posting(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("postings", rid, "Posting")
    if rec["posting_status"] != "CLOSED":
        raise errors.invalid_state("Posting is not CLOSED")
    for app in STORE["applications"].values():
        if app["posting_id"] == rec["id"] and app["application_status"] in (
            "UNDER_REVIEW",
            "RETURNED_FOR_REVISION",
        ):
            raise errors.reference_in_use(
                "Posting has in-flight applications blocking archival"
            )
    rec["posting_status"] = "ARCHIVED"
    touch(rec)
    return success_obj(_out(rec))


@bp.get("/postings/<rid>/applications")
def list_posting_applications(rid):
    helpers.require_roles(READ_ROLES)
    find_or_404("postings", rid, "Posting")
    apps = [a for a in STORE["applications"].values() if a["posting_id"] == rid]
    return list_response(
        apps, {"application_status": request.args.get("application_status")}
    )


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.post("/applications")
def create_application():
    helpers.require_roles(["HRReviewer"])
    data = helpers.body()
    posting_id = data.get("posting_id")
    if not isinstance(posting_id, str) or not posting_id:
        raise errors.invalid_request("Field 'posting_id' is required")
    posting = find_or_404("postings", posting_id, "Posting")
    name = req_str(data, "applicant_name")
    email = req_str(data, "applicant_email")
    claimed = req_enum(data, "claimed_education_tier", TIER_ORDER)
    # posting window (priority 5)
    today_d = today()
    if posting["posting_status"] != "OPEN" or not (
        parse_date(posting["open_date"]) <= today_d <= parse_date(posting["close_date"])
    ):
        raise errors.posting_not_open()
    # duplicate email among live applications of this posting (priority 9)
    for app in STORE["applications"].values():
        if (
            app["posting_id"] == posting["id"]
            and app["applicant_email"] == email
            and app["application_status"] in ("SUBMITTED", "UNDER_REVIEW", "APPROVED")
        ):
            raise errors.duplicate(
                "applicant_email already filed against this posting"
            )
    rec = new_record()
    rec.update(
        {
            "posting_id": posting["id"],
            "applicant_name": name,
            "applicant_email": email,
            "claimed_education_tier": claimed,
            "application_status": "SUBMITTED",
            "revision_count": 0,
            "hired_faculty_id": None,
        }
    )
    STORE["applications"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/applications/<rid>")
def get_application(rid):
    helpers.require_roles(READ_ROLES)
    return success_obj(_out(find_or_404("applications", rid, "Application")))


@bp.get("/applications")
def list_applications():
    helpers.require_roles(READ_ROLES)
    return list_response(
        STORE["applications"].values(),
        {
            "posting_id": request.args.get("posting_id"),
            "application_status": request.args.get("application_status"),
            "applicant_email": request.args.get("applicant_email"),
            "hired_faculty_id": request.args.get("hired_faculty_id"),
        },
    )


@bp.post("/applications/<rid>/start-review")
def start_review(rid):
    helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] != "SUBMITTED":
        raise errors.invalid_state("Application is not SUBMITTED")
    posting = STORE["postings"].get(rec["posting_id"])
    if posting is None or posting["posting_status"] != "OPEN":
        raise errors.invalid_state("Posting is not OPEN")
    rec["application_status"] = "UNDER_REVIEW"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/applications/<rid>/return-for-revision")
def return_for_revision(rid):
    helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Application is not UNDER_REVIEW")
    if rec["revision_count"] >= MAX_REVISIONS:
        raise errors.revision_limit()
    rec["revision_count"] += 1
    rec["application_status"] = "RETURNED_FOR_REVISION"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/applications/<rid>/resubmit")
def resubmit(rid):
    helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] != "RETURNED_FOR_REVISION":
        raise errors.invalid_state("Application is not RETURNED_FOR_REVISION")
    posting = STORE["postings"].get(rec["posting_id"])
    if posting is None or posting["posting_status"] not in ("OPEN", "SUSPENDED"):
        raise errors.invalid_state("Posting is not OPEN or SUSPENDED")
    rec["application_status"] = "UNDER_REVIEW"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/applications/<rid>/approve")
def approve(rid):
    user_id, _ = helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Application is not UNDER_REVIEW")
    creds = [c for c in STORE["credentials"].values() if c["application_id"] == rec["id"]]
    # priority 6: segregation of duties
    for c in creds:
        if c["verification_status"] == "VERIFIED" and c.get("verified_by_hr_id") == user_id:
            raise errors.segregation_of_duties()
    # priority 8: credential completeness
    posting = STORE["postings"].get(rec["posting_id"])
    min_tier = posting["min_education_tier"] if posting else "BACHELORS"
    for c in creds:
        if c["kind"] in ("TRANSCRIPT", "DEGREE") and c["verification_status"] != "VERIFIED":
            raise errors.credentials_incomplete(
                "All TRANSCRIPT/DEGREE credentials must be VERIFIED"
            )
    verified_tiers = [
        c.get("verified_education_tier")
        for c in creds
        if c["verification_status"] == "VERIFIED" and c.get("verified_education_tier")
    ]
    if not any(TIER_RANK[t] >= TIER_RANK[min_tier] for t in verified_tiers):
        raise errors.credentials_incomplete(
            "No VERIFIED credential evidences the posting's minimum education tier"
        )
    for c in creds:
        if c["verification_status"] == "PENDING":
            raise errors.credentials_incomplete("PENDING credentials remain")
    # create faculty record
    highest = max(verified_tiers, key=lambda t: TIER_RANK[t])
    from store import now_iso

    fac = new_record()
    fac.update(
        {
            "application_id": rec["id"],
            "department_id": posting["department_id"] if posting else None,
            "legal_name": rec["applicant_name"],
            "education_tier": highest,
            "hire_date": today().isoformat(),
            "compliance_status": "ONBOARDING",
            "retention_status": "PROVISIONAL",
            "completed_terms": 0,
            "current_term_load_units": 0,
            "benefits_eligible": False,
        }
    )
    STORE["faculty"][fac["id"]] = fac
    # immediate ONBOARDING -> COMPLIANT evaluation on already-verified pair
    services.try_auto_compliance(fac)
    rec["hired_faculty_id"] = fac["id"]
    rec["application_status"] = "APPROVED"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/applications/<rid>/reject")
def reject_application(rid):
    helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] != "UNDER_REVIEW":
        raise errors.invalid_state("Application is not UNDER_REVIEW")
    rec["application_status"] = "REJECTED"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/applications/<rid>/withdraw")
def withdraw_application(rid):
    helpers.require_roles(["HRReviewer"])
    rec = find_or_404("applications", rid, "Application")
    if rec["application_status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise errors.invalid_state("Application is not SUBMITTED or UNDER_REVIEW")
    rec["application_status"] = "WITHDRAWN"
    touch(rec)
    return success_obj(_out(rec))


@bp.get("/applications/<rid>/credentials")
def list_application_credentials(rid):
    helpers.require_roles(READ_ROLES)
    find_or_404("applications", rid, "Application")
    creds = [c for c in STORE["credentials"].values() if c["application_id"] == rid]
    return list_response(
        creds, {"verification_status": request.args.get("verification_status")}
    )


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

@bp.post("/credentials")
def create_credential():
    helpers.require_roles(["HRReviewer"])
    data = helpers.body()
    application_id = data.get("application_id")
    if not isinstance(application_id, str) or not application_id:
        raise errors.invalid_request("Field 'application_id' is required")
    app = find_or_404("applications", application_id, "Application")
    kind = req_enum(data, "kind", CRED_KINDS)
    evidence_ref = req_str(data, "evidence_ref")
    tier = opt_enum(data, "verified_education_tier", TIER_ORDER)
    if app["application_status"] not in (
        "SUBMITTED",
        "UNDER_REVIEW",
        "RETURNED_FOR_REVISION",
        "APPROVED",
    ):
        raise errors.invalid_state(
            "Credentials may only be registered while the application is SUBMITTED, "
            "UNDER_REVIEW, RETURNED_FOR_REVISION, or APPROVED"
        )
    rec = new_record()
    rec.update(
        {
            "application_id": app["id"],
            "kind": kind,
            "evidence_ref": evidence_ref,
            "verified_education_tier": tier,
            "verification_status": "PENDING",
            "verified_by_hr_id": None,
            "decided_at": None,
        }
    )
    STORE["credentials"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/credentials/<rid>")
def get_credential(rid):
    helpers.require_roles(READ_ROLES)
    return success_obj(_out(find_or_404("credentials", rid, "Credential")))


@bp.get("/credentials")
def list_credentials():
    helpers.require_roles(READ_ROLES)
    return list_response(
        STORE["credentials"].values(),
        {
            "application_id": request.args.get("application_id"),
            "kind": request.args.get("kind"),
            "verification_status": request.args.get("verification_status"),
        },
    )


def _decide_credential(rid, decision):
    user_id, _ = helpers.require_roles(["HRReviewer"])
    rec = find_or_404("credentials", rid, "Credential")
    if rec["verification_status"] != "PENDING":
        raise errors.invalid_state("Credential is not PENDING")
    app = STORE["applications"].get(rec["application_id"])
    if app is None or app["application_status"] not in ("UNDER_REVIEW", "APPROVED"):
        raise errors.invalid_state(
            "Application is not UNDER_REVIEW or APPROVED"
        )
    rec["verification_status"] = decision
    rec["verified_by_hr_id"] = user_id
    from store import now_iso

    rec["decided_at"] = now_iso()
    touch(rec)
    if decision == "VERIFIED" and app["application_status"] == "APPROVED":
        fac = STORE["faculty"].get(app.get("hired_faculty_id") or "")
        if fac is not None:
            services.try_auto_compliance(fac)
    return rec


@bp.post("/credentials/<rid>/verify")
def verify_credential(rid):
    return success_obj(_out(_decide_credential(rid, "VERIFIED")))


@bp.post("/credentials/<rid>/reject")
def reject_credential(rid):
    return success_obj(_out(_decide_credential(rid, "REJECTED")))


# ---------------------------------------------------------------------------
# Faculty
# ---------------------------------------------------------------------------

FACULTY_READ_ROLES = ["HRAdmin", "HRReviewer", "DepartmentChair", "Dean", "PayrollOfficer"]


@bp.get("/faculty/<rid>")
def get_faculty(rid):
    helpers.require_roles(FACULTY_READ_ROLES)
    return success_obj(_out(find_or_404("faculty", rid, "Faculty")))


@bp.get("/faculty")
def list_faculty():
    helpers.require_roles(FACULTY_READ_ROLES)
    return list_response(
        STORE["faculty"].values(),
        {
            "department_id": request.args.get("department_id"),
            "application_id": request.args.get("application_id"),
            "compliance_status": request.args.get("compliance_status"),
            "retention_status": request.args.get("retention_status"),
            "benefits_eligible": request.args.get("benefits_eligible"),
        },
    )


@bp.get("/faculty/<rid>/load")
def faculty_load(rid):
    helpers.require_roles(FACULTY_READ_ROLES)
    fac = find_or_404("faculty", rid, "Faculty")
    variant = request.args.get("variant")
    if variant is None:
        variant = "actual"
    if variant not in ("actual", "scheduled"):
        raise errors.invalid_request(
            "Query parameter 'variant' must be 'actual' or 'scheduled'"
        )
    term = helpers.current_term()
    if term is None:
        return success_obj(
            {
                "load_units": 0,
                "variant": variant,
                "term_code": None,
                "load_cap_units": None,
                "benefits_eligible": False,
            }
        )
    load, eligible = services.compute_load(fac["id"], term, variant)
    return success_obj(
        {
            "load_units": load,
            "variant": variant,
            "term_code": term["code"],
            "load_cap_units": term["load_cap_units"],
            "benefits_eligible": eligible,
        }
    )


@bp.post("/faculty/<rid>/reinstate-compliance")
def reinstate_compliance(rid):
    helpers.require_roles(["HRReviewer"])
    fac = find_or_404("faculty", rid, "Faculty")
    if fac["compliance_status"] != "LAPSED":
        raise errors.invalid_state("Faculty is not LAPSED")
    has_bg = any(
        c["application_id"] == fac["application_id"]
        and c["kind"] == "BACKGROUND_CHECK"
        and c["verification_status"] == "VERIFIED"
        for c in STORE["credentials"].values()
    )
    if not has_bg:
        raise errors.compliance_incomplete(
            "Reinstatement requires a VERIFIED BACKGROUND_CHECK credential"
        )
    fac["compliance_status"] = "COMPLIANT"
    touch(fac)
    return success_obj(_out(fac))


@bp.get("/faculty/<rid>/contracts")
def faculty_contracts(rid):
    helpers.require_roles(FACULTY_READ_ROLES)
    find_or_404("faculty", rid, "Faculty")
    contracts = [c for c in STORE["contracts"].values() if c["faculty_id"] == rid]
    return list_response(
        contracts, {"contract_status": request.args.get("contract_status")}
    )


@bp.get("/faculty/<rid>/evaluations")
def faculty_evaluations(rid):
    helpers.require_roles(READ_ROLES)
    find_or_404("faculty", rid, "Faculty")
    evals = [e for e in STORE["evaluations"].values() if e["faculty_id"] == rid]
    return list_response(evals, {"term_code": request.args.get("term_code")})
