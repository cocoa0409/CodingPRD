"""Routes: applications, documents, verifications, duplication checks,
case notes."""

from flask import Blueprint, request

import db
import services as svc
from errors import (
    raise_err,
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_APPLICATION_STATE,
    ERR_STALE_VERSION, ERR_VENDOR_CATEGORY_MISMATCH,
    ERR_SERVICE_MONTH_CONFLICT, ERR_DOCUMENTS_INCOMPLETE,
    ERR_VENDOR_SUSPENDED, ERR_SEGREGATION_OF_DUTIES,
    ERR_DUPLICATION_CHECK_REQUIRED, ERR_DUPLICATION_UNRESOLVED,
    ERR_INVALID_VERIFICATION_STATE, ERR_INVALID_DUPLICATION_CHECK_STATE,
    ERR_APPEAL_WINDOW_CLOSED, ERR_FOLLOW_UP_REQUIRED,
    ERR_NO_ACTIVE_POLICY,
)
from middleware import require_role, ALL_ROLES
from response import success_object, success_list, paginate
from validation import (
    body, require_fields, reject_unknown_fields, req_string,
    req_positive_cents, req_int, req_enum, req_service_month, req_datetime,
    opt_string, opt_enum,
)

bp = Blueprint("cases", __name__)

READ_ROLES = ALL_ROLES

TERMINAL_APPLICATION_STATES = {"DENIED", "WITHDRAWN", "CLOSED"}
DENIAL_REASONS = {"INELIGIBLE_INCOME", "CAP_EXHAUSTED", "DUPLICATE_BENEFIT",
                  "VERIFICATION_FAILED", "ELIGIBILITY_LAPSED",
                  "PROGRAM_DIRECTED"}
DOC_TYPES = {"EVICTION_NOTICE", "LEASE_LEDGER", "UTILITY_BILL",
             "ID_VERIFICATION"}
NOTE_TYPES = {"GENERAL", "FOLLOW_UP", "DUPLICATION_CHECK", "COMMUNICATION"}
NOTE_OUTCOMES = {"CRISIS_RESOLVED", "PARTIAL_RELIEF", "NO_CHANGE",
                 "LOST_CONTACT"}


def get_application_or_404(aid):
    app = db.applications.get(aid)
    if app is None:
        raise_err(ERR_NOT_FOUND, "AssistanceApplication not found")
    return app


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

@bp.post("/assistance/applications")
def create_application():
    user_id = require_role(["Caseworker"])
    data = body()
    fields = ["household_id", "vendor_id", "category",
              "requested_amount_cents", "service_month"]
    require_fields(data, fields)
    reject_unknown_fields(data, fields)
    household_id = req_string(data, "household_id")
    vendor_id = req_string(data, "vendor_id")
    category = req_enum(data, "category", {"RENT", "UTILITY"})
    requested = req_positive_cents(data, "requested_amount_cents")
    service_month = req_service_month(data)

    # Existence (left-to-right: household, then vendor).
    household = db.households.get(household_id)
    if household is None:
        raise_err(ERR_NOT_FOUND, "Household not found")
    vendor = db.vendors.get(vendor_id)
    if vendor is None:
        raise_err(ERR_NOT_FOUND, "Vendor not found")

    # Cross-reference compatibility: category vs vendor_type.
    expected_vendor_type = "LANDLORD" if category == "RENT" else "UTILITY"
    if vendor["vendor_type"] != expected_vendor_type:
        raise_err(ERR_VENDOR_CATEGORY_MISMATCH,
                  "Application category requires a matching vendor type")

    # Structural: (household, category, service_month) unique among
    # non-terminal applications.
    for a in db.applications.values():
        if a["household_id"] == household_id \
                and a["category"] == category \
                and a["service_month"] == service_month \
                and a["status"] not in TERMINAL_APPLICATION_STATES:
            raise_err(ERR_SERVICE_MONTH_CONFLICT,
                      "Another live application exists for this household, "
                      "category, and service_month")

    rec = svc.stamp_new({
        "household_id": household_id,
        "vendor_id": vendor_id,
        "policy_id": "",
        "category": category,
        "requested_amount_cents": requested,
        "service_month": service_month,
        "intake_caseworker_id": user_id,
        "status": "INTAKE",
        "active_award_id": "",
        "submitted_at": "",
        "waitlisted_at": "",
        "denied_at": "",
        "denial_reason": "",
        "closed_at": "",
    })
    db.applications[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/applications/<aid>")
def get_application(aid):
    require_role(READ_ROLES)
    return success_object(get_application_or_404(aid))


@bp.get("/assistance/applications")
def list_applications():
    require_role(READ_ROLES)
    records = list(db.applications.values())
    for param in ("household_id", "vendor_id", "policy_id", "status",
                  "category"):
        v = request.args.get(param)
        if v is not None:
            records = [a for a in records if a[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@bp.post("/assistance/applications/<aid>/documents")
def attach_document(aid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["doc_type", "file_reference"])
    reject_unknown_fields(data, ["doc_type", "file_reference"])
    doc_type = req_enum(data, "doc_type", DOC_TYPES)
    file_reference = req_string(data, "file_reference")
    app = get_application_or_404(aid)
    if app["status"] != "INTAKE":
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Documents may only be attached while the application is "
                  "in INTAKE")
    rec = svc.stamp_new({
        "application_id": aid,
        "doc_type": doc_type,
        "file_reference": file_reference,
        "uploaded_by": user_id,
    }, with_version=False)
    db.documents[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/documents/<did>")
def get_document(did):
    require_role(READ_ROLES)
    rec = db.documents.get(did)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "ApplicationDocument not found")
    return success_object(rec)


@bp.get("/assistance/documents")
def list_documents():
    require_role(READ_ROLES)
    records = list(db.documents.values())
    v = request.args.get("application_id")
    if v is not None:
        records = [d for d in records if d["application_id"] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# Application actions: submit
# ---------------------------------------------------------------------------

def _required_doc_types(policy, category):
    if category == "RENT":
        required = set()
        if policy["require_eviction_notice"]:
            required.add("EVICTION_NOTICE")
        if policy["require_lease_ledger"]:
            required.add("LEASE_LEDGER")
        return required
    if policy["require_utility_bill"]:
        return {"UTILITY_BILL"}
    return set()


@bp.post("/assistance/applications/<aid>/submit")
def submit_application(aid):
    user_id = require_role(["Caseworker"])
    app = get_application_or_404(aid)
    if app["status"] != "INTAKE":
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Submit requires the application to be in INTAKE")
    # State-family preconditions in declaration order:
    # ERR_NO_ACTIVE_POLICY, ERR_VENDOR_SUSPENDED are state errors too;
    # ERR_DOCUMENTS_INCOMPLETE is structural (priority 10) and comes after
    # the state family. The scaffold lists the policy check first.
    policy = svc.active_policy()
    if policy is None:
        raise_err(ERR_NO_ACTIVE_POLICY, "No EligibilityPolicy is ACTIVE")
    vendor = db.vendors[app["vendor_id"]]
    if vendor["status"] != "ACTIVE":
        raise_err(ERR_VENDOR_SUSPENDED,
                  "Submit attempted while the application's vendor is "
                  "SUSPENDED")
    required = _required_doc_types(policy, app["category"])
    present = {d["doc_type"] for d in db.documents.values()
               if d["application_id"] == aid}
    if not required.issubset(present):
        raise_err(ERR_DOCUMENTS_INCOMPLETE,
                  "Required documents for the application's category are "
                  "missing")
    app["policy_id"] = policy["id"]
    app["submitted_at"] = db.now_iso()
    app["status"] = "SUBMITTED"
    svc.touch(app)
    return success_object(app)


# ---------------------------------------------------------------------------
# Vendor verifications
# ---------------------------------------------------------------------------

@bp.post("/assistance/applications/<aid>/verifications")
def create_verification(aid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["expected_application_version"])
    reject_unknown_fields(data, ["expected_application_version"])
    expected = req_int(data, "expected_application_version")
    app = get_application_or_404(aid)
    # OCC (priority 5) precedes state legality (priority 6) per scaffold's
    # concurrency rule and validations table.
    if expected != app["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_application_version does not match the "
                  "application's current version")
    if app["status"] not in ("SUBMITTED", "VERIFICATION_FAILED"):
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Verification may only open from SUBMITTED or "
                  "VERIFICATION_FAILED")
    if user_id == app["intake_caseworker_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The verifying caseworker must differ from the intake "
                  "caseworker")
    # Supersede any still-PENDING verification of this application.
    for v in db.verifications.values():
        if v["application_id"] == aid and v["status"] == "PENDING":
            v["status"] = "SUPERSEDED"
            svc.touch(v)
    rec = svc.stamp_new({
        "application_id": aid,
        "vendor_id": app["vendor_id"],
        "verifier_id": user_id,
        "status": "PENDING",
        "confirmed_amount_cents": 0,
        "outcome_notes": "",
        "completed_at": "",
    })
    db.verifications[rec["id"]] = rec
    app["status"] = "UNDER_VERIFICATION"
    svc.touch(app)
    return success_object(rec, 201)


@bp.get("/assistance/verifications/<vid>")
def get_verification(vid):
    require_role(READ_ROLES)
    rec = db.verifications.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "VendorVerification not found")
    return success_object(rec)


@bp.get("/assistance/verifications")
def list_verifications():
    require_role(READ_ROLES)
    records = list(db.verifications.values())
    for param in ("application_id", "vendor_id"):
        v = request.args.get(param)
        if v is not None:
            records = [r for r in records if r[param] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/assistance/verifications/<vid>/complete")
def complete_verification(vid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["outcome"])
    reject_unknown_fields(data, ["outcome", "confirmed_amount_cents",
                                 "outcome_notes"])
    outcome = req_enum(data, "outcome", {"PASSED", "FAILED"})
    confirmed = None
    if outcome == "PASSED":
        # Outcome-conditional field: must be present and > 0.
        confirmed = req_positive_cents(data, "confirmed_amount_cents")
    elif "confirmed_amount_cents" in data and data["confirmed_amount_cents"] is not None:
        # Allowed but not required for FAILED; validate shape if supplied.
        confirmed = req_int(data, "confirmed_amount_cents", required=False,
                            minimum=0)
    outcome_notes = opt_string(data, "outcome_notes", "")

    rec = db.verifications.get(vid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "VendorVerification not found")
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_VERIFICATION_STATE,
                  "Only a PENDING verification may be completed")
    app = db.applications[rec["application_id"]]
    if user_id == app["intake_caseworker_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The completing caseworker must differ from the intake "
                  "caseworker")
    rec["completed_at"] = db.now_iso()
    rec["outcome_notes"] = outcome_notes
    if outcome == "PASSED":
        rec["status"] = "PASSED"
        rec["confirmed_amount_cents"] = confirmed
        app["status"] = "PENDING_DECISION"
    else:
        rec["status"] = "FAILED"
        app["status"] = "VERIFICATION_FAILED"
    svc.touch(rec)
    svc.touch(app)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Duplication checks
# ---------------------------------------------------------------------------

@bp.post("/assistance/applications/<aid>/duplication-checks")
def create_duplication_check(aid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["agency_name", "expected_application_version"])
    reject_unknown_fields(data, ["agency_name",
                                 "expected_application_version"])
    agency_name = req_string(data, "agency_name")
    expected = req_int(data, "expected_application_version")
    app = get_application_or_404(aid)
    if expected != app["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_application_version does not match the "
                  "application's current version")
    # Supersede any still-PENDING check of this application.
    for c in db.duplication_checks.values():
        if c["application_id"] == aid and c["status"] == "PENDING":
            c["status"] = "SUPERSEDED"
            svc.touch(c)
    rec = svc.stamp_new({
        "application_id": aid,
        "agency_name": agency_name,
        "recorded_by": user_id,
        "status": "PENDING",
        "resolution_notes": "",
        "override_justification": "",
    })
    db.duplication_checks[rec["id"]] = rec
    svc.touch(app)
    return success_object(rec, 201)


@bp.get("/assistance/duplication-checks/<cid>")
def get_duplication_check(cid):
    require_role(READ_ROLES)
    rec = db.duplication_checks.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "DuplicationCheck not found")
    return success_object(rec)


@bp.get("/assistance/duplication-checks")
def list_duplication_checks():
    require_role(READ_ROLES)
    records = list(db.duplication_checks.values())
    v = request.args.get("application_id")
    if v is not None:
        records = [c for c in records if c["application_id"] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)


@bp.post("/assistance/duplication-checks/<cid>/resolve")
def resolve_duplication_check(cid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["result"])
    reject_unknown_fields(data, ["result", "resolution_notes"])
    result = req_enum(data, "result", {"CLEARED", "FLAGGED"})
    notes = opt_string(data, "resolution_notes", "")
    rec = db.duplication_checks.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "DuplicationCheck not found")
    if rec["status"] != "PENDING":
        raise_err(ERR_INVALID_DUPLICATION_CHECK_STATE,
                  "Resolve attempted on a non-PENDING check")
    rec["status"] = result
    rec["resolution_notes"] = notes
    svc.touch(rec)
    return success_object(rec)


@bp.post("/assistance/duplication-checks/<cid>/override")
def override_duplication_check(cid):
    user_id = require_role(["ProgramManager"])
    data = body()
    require_fields(data, ["override_justification"])
    reject_unknown_fields(data, ["override_justification"])
    justification = req_string(data, "override_justification")
    rec = db.duplication_checks.get(cid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "DuplicationCheck not found")
    if rec["status"] != "FLAGGED":
        raise_err(ERR_INVALID_DUPLICATION_CHECK_STATE,
                  "Override attempted on a non-FLAGGED check")
    rec["status"] = "CLEARED"
    rec["override_justification"] = justification
    svc.touch(rec)
    return success_object(rec)


# ---------------------------------------------------------------------------
# Decision actions: approve / waitlist / deny / appeal / withdraw / close
# ---------------------------------------------------------------------------

def _decision_gates_approve(app, user_id):
    """Segregation + duplication gates shared by approve and waitlist
    (priority 7), evaluated in the PRD's fixed order."""
    # Segregation of duties (approve flavor): actor != intake caseworker and
    # != verifier of the latest PASSED verification.
    if user_id == app["intake_caseworker_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The approver must differ from the intake caseworker")
    verification = svc.latest_passed_verification(app["id"])
    if verification is not None and user_id == verification["verifier_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The approver must differ from the verifying caseworker")
    # Duplication gates: missing-check surfaces first.
    checks = [c for c in db.duplication_checks.values()
              if c["application_id"] == app["id"]]
    if len(checks) == 0:
        raise_err(ERR_DUPLICATION_CHECK_REQUIRED,
                  "No DuplicationCheck recorded for the application")
    if any(c["status"] in ("PENDING", "FLAGGED") for c in checks):
        raise_err(ERR_DUPLICATION_UNRESOLVED,
                  "A DuplicationCheck of the application is PENDING or "
                  "FLAGGED")


@bp.post("/assistance/applications/<aid>/approve")
def approve_application(aid):
    user_id = require_role(["ProgramManager"])
    app = get_application_or_404(aid)
    if app["status"] != "PENDING_DECISION":
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Approve requires the application to be in "
                  "PENDING_DECISION")
    _decision_gates_approve(app, user_id)
    # Fiscal ceilings last (income, annual cap, category cap, funds).
    policy = db.policies.get(app["policy_id"])
    if policy is None:
        # A pinned policy always exists, but guard defensively.
        policy = svc.require_active_policy()
    award = svc.execute_approval(app, policy)
    app["status"] = "APPROVED"
    svc.touch(app)
    return success_object(app)


@bp.post("/assistance/applications/<aid>/waitlist")
def waitlist_application(aid):
    user_id = require_role(["ProgramManager"])
    app = get_application_or_404(aid)
    if app["status"] != "PENDING_DECISION":
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Waitlist requires the application to be in "
                  "PENDING_DECISION")
    _decision_gates_approve(app, user_id)
    # Same income + cap preconditions as approve; funds NOT checked.
    policy = db.policies.get(app["policy_id"])
    if policy is None:
        policy = svc.require_active_policy()
    svc.check_fiscal_eligibility(app, policy)
    app["status"] = "WAITLISTED"
    app["waitlisted_at"] = db.now_iso()
    svc.touch(app)
    return success_object(app)


@bp.post("/assistance/applications/<aid>/deny")
def deny_application(aid):
    user_id = require_role(["ProgramManager"])
    data = body()
    require_fields(data, ["reason_code"])
    reject_unknown_fields(data, ["reason_code"])
    reason = req_enum(data, "reason_code", DENIAL_REASONS)
    app = get_application_or_404(aid)
    if app["status"] not in ("PENDING_DECISION", "WAITLISTED"):
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Deny requires the application to be in PENDING_DECISION "
                  "or WAITLISTED")
    if user_id == app["intake_caseworker_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES,
                  "The denying manager must differ from the intake "
                  "caseworker")
    app["status"] = "DENIED"
    app["denied_at"] = db.now_iso()
    app["denial_reason"] = reason
    svc.touch(app)
    return success_object(app)


@bp.post("/assistance/applications/<aid>/appeal")
def appeal_application(aid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["appeal_reason"])
    reject_unknown_fields(data, ["appeal_reason"])
    req_string(data, "appeal_reason")
    app = get_application_or_404(aid)
    if app["status"] != "DENIED":
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Appeal requires the application to be DENIED")
    deadline = svc.appeal_deadline(app)
    if db.clock.now() > deadline:
        raise_err(ERR_APPEAL_WINDOW_CLOSED,
                  "Appeal attempted after the pinned policy's appeal window")
    app["status"] = "PENDING_DECISION"
    svc.touch(app)
    return success_object(app)


@bp.post("/assistance/applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id = require_role(["Caseworker"])
    app = get_application_or_404(aid)
    withdrawable = ("INTAKE", "SUBMITTED", "UNDER_VERIFICATION",
                    "VERIFICATION_FAILED", "PENDING_DECISION", "WAITLISTED")
    if app["status"] not in withdrawable:
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Withdrawal is not available from the application's "
                  "current state")
    if app["status"] == "UNDER_VERIFICATION":
        for v in db.verifications.values():
            if v["application_id"] == aid and v["status"] == "PENDING":
                v["status"] = "SUPERSEDED"
                svc.touch(v)
    app["status"] = "WITHDRAWN"
    svc.touch(app)
    return success_object(app)


@bp.post("/assistance/applications/<aid>/close")
def close_application(aid):
    user_id = require_role(["Caseworker"])
    app = get_application_or_404(aid)
    if app["status"] not in ("PAID", "DENIED"):
        raise_err(ERR_INVALID_APPLICATION_STATE,
                  "Close requires the application to be PAID or DENIED")
    has_follow_up = any(
        n["application_id"] == aid and n["note_type"] == "FOLLOW_UP"
        for n in db.case_notes.values())
    if not has_follow_up:
        raise_err(ERR_FOLLOW_UP_REQUIRED,
                  "At least one FOLLOW_UP case note must exist before "
                  "closure")
    app["status"] = "CLOSED"
    app["closed_at"] = db.now_iso()
    svc.touch(app)
    return success_object(app)


# ---------------------------------------------------------------------------
# Case notes
# ---------------------------------------------------------------------------

@bp.post("/assistance/applications/<aid>/case-notes")
def create_case_note(aid):
    user_id = require_role(["Caseworker"])
    data = body()
    require_fields(data, ["note_type", "body"])
    reject_unknown_fields(data, ["note_type", "body", "outcome",
                                 "occurred_at"])
    note_type = req_enum(data, "note_type", NOTE_TYPES)
    note_body = req_string(data, "body")
    outcome = opt_enum(data, "outcome", NOTE_OUTCOMES, "")
    if note_type == "FOLLOW_UP" and outcome == "":
        raise_err(ERR_INVALID_REQUEST,
                  "A FOLLOW_UP note must carry an outcome")
    occurred_at = req_datetime(data, "occurred_at", required=False)
    app = get_application_or_404(aid)
    rec = svc.stamp_new({
        "application_id": aid,
        "author_id": user_id,
        "note_type": note_type,
        "body": note_body,
        "outcome": outcome,
        "occurred_at": occurred_at if occurred_at is not None else db.now_iso(),
    }, with_version=False)
    db.case_notes[rec["id"]] = rec
    return success_object(rec, 201)


@bp.get("/assistance/case-notes/<nid>")
def get_case_note(nid):
    require_role(READ_ROLES)
    rec = db.case_notes.get(nid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "CaseNote not found")
    return success_object(rec)


@bp.get("/assistance/case-notes")
def list_case_notes():
    require_role(READ_ROLES)
    records = list(db.case_notes.values())
    v = request.args.get("application_id")
    if v is not None:
        records = [n for n in records if n["application_id"] == v]
    v = request.args.get("note_type")
    if v is not None:
        records = [n for n in records if n["note_type"] == v]
    page, total, limit, offset = paginate(records)
    return success_list(page, total, limit, offset)
