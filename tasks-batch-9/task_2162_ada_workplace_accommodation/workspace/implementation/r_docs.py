"""Medical documentation rounds and essential-function analyses."""
from flask import Blueprint, g, request as flask_request

import calc
import domain
from authz import (ALL_ROLES, endpoint, need_analysis, need_doc_request, need_function,
                   need_request, require_case_owner, require_manager_scope_case,
                   require_not_sealed)
from envelope import created, listing, ok, read_pagination, touch
from errors import ApiError
from store import by_created, parse_datetime, store
from validation import F, MEDICAL_FIELDS, bad, raw_body, validate

bp = Blueprint("docs", __name__)

DOC_SPEC = [
    F("scope_fields_requested", "enum_array", required=True, non_empty=True,
      enum=tuple(MEDICAL_FIELDS)),
    F("due_date", "datetime", required=True),
    F("is_second_opinion", "boolean", default=False, has_default=True),
    F("expected_request_version", "integer", required=True),
]


@bp.post("/accommodation-requests/<case_id>/medical-doc-requests")
@endpoint(["AccommodationCoordinator"])
def issue_doc_request(case_id):
    data = validate(raw_body(), DOC_SPEC)
    issued_at = store.now()
    due = parse_datetime(data["due_date"])
    if due <= issued_at:
        bad("due_date must be strictly after the moment of issuance.")
    req = need_request(case_id)
    if req["stage"] not in ("INTAKE", "DOC_PENDING"):
        raise ApiError("ERR_INVALID_STAGE_TRANSITION",
                       "Documentation may not be issued from this stage.")
    if data["expected_request_version"] != req["version"]:
        raise ApiError("ERR_STALE_VERSION")
    require_not_sealed(req)
    scope = data["scope_fields_requested"]
    if "diagnosis" in scope or "treatment_plan" in scope:
        raise ApiError("ERR_MEDICAL_SCOPE_OVERBROAD",
                       "The employer may request functional information only.")
    if req["disability_obvious"] is True:
        raise ApiError("ERR_DOCUMENTATION_NOT_PERMITTED",
                       "The limitation is obvious; documentation may not be requested.")
    if req["documentation_budget_remaining"] < 1:
        raise ApiError("ERR_DOC_REQUEST_LIMIT_EXCEEDED",
                       "The documentation budget is exhausted.")
    for existing in calc.doc_rounds_of(req["id"]):
        if existing["status"] != "ISSUED":
            continue
        if issued_at < parse_datetime(existing["due_date"]):
            raise ApiError("ERR_DOC_WINDOW_OVERLAP",
                           "An open documentation window is still running.")

    row = store.new_row("MedicalDocumentationRequest", {
        "request_id": req["id"],
        "round_index": req["medical_doc_request_count"] + 1,
        "scope_fields_requested": scope,
        "issued_at": store.now_iso(),
        "due_date": data["due_date"],
        "responded_at": None,
        "response_summary": None,
        "is_second_opinion": data["is_second_opinion"],
        "adjudication_note": None,
        "status": "ISSUED",
    })
    store.doc_requests[row["id"]] = row
    domain.refresh_doc_budget(req)
    domain.refresh_integrity(req)
    if req["stage"] == "INTAKE":
        req["stage"] = "DOC_PENDING"
    touch(req)
    return created(row)


@bp.get("/accommodation-requests/<case_id>/medical-doc-requests")
@endpoint(["Employee", "AccommodationCoordinator", "MedicalReviewOfficer",
           "AppealOfficer", "ComplianceAuditor"])
def list_doc_requests(case_id):
    limit, offset = read_pagination()
    need_request(case_id)
    rows = [d for d in store.doc_requests.values() if d["request_id"] == case_id]
    status = flask_request.args.get("status")
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return listing(by_created(rows), limit, offset)


@bp.post("/medical-doc-requests/<doc_id>/respond")
@endpoint(["Employee"])
def respond_doc_request(doc_id):
    data = validate(raw_body(), [F("response_summary", "string", required=True)])
    row = need_doc_request(doc_id)
    req = store.requests.get(row["request_id"])
    require_case_owner(req)
    if row["status"] != "ISSUED" or store.now() >= parse_datetime(row["due_date"]):
        raise ApiError("ERR_DOC_REQUEST_NOT_OPEN",
                       "The documentation round is not open for a response.")
    require_not_sealed(req)
    row["status"] = "RESPONDED"
    row["responded_at"] = store.now_iso()
    row["response_summary"] = data["response_summary"]
    touch(row)
    if req["confidentiality_posture"] == "STANDARD":
        domain.assign(req, confidentiality_posture="RESTRICTED")
    return ok(row)


@bp.post("/medical-doc-requests/<doc_id>/adjudicate")
@endpoint(["MedicalReviewOfficer"])
def adjudicate_doc_request(doc_id):
    data = validate(raw_body(), [
        F("verdict", "enum", required=True, enum=("SUFFICIENT", "INSUFFICIENT")),
        F("adjudication_note", "string", nullable=True),
    ])
    row = need_doc_request(doc_id)
    req = store.requests.get(row["request_id"])
    if row["status"] != "RESPONDED":
        raise ApiError("ERR_DOC_REQUEST_NOT_OPEN",
                       "Only a RESPONDED round can be adjudicated.")
    require_not_sealed(req)
    row["status"] = ("ACCEPTED_SUFFICIENT" if data["verdict"] == "SUFFICIENT"
                     else "REJECTED_INSUFFICIENT")
    if "adjudication_note" in data:
        row["adjudication_note"] = data["adjudication_note"]
    touch(row)
    return ok(row)


@bp.post("/medical-doc-requests/<doc_id>/withdraw")
@endpoint(["AccommodationCoordinator"])
def withdraw_doc_request(doc_id):
    raw_body(required=False)
    row = need_doc_request(doc_id)
    req = store.requests.get(row["request_id"])
    if row["status"] not in ("ISSUED", "RESPONDED"):
        raise ApiError("ERR_DOC_REQUEST_NOT_OPEN",
                       "Only an outstanding round can be withdrawn.")
    require_not_sealed(req)
    row["status"] = "WITHDRAWN"
    touch(row)
    domain.refresh_doc_budget(req)
    domain.refresh_integrity(req)
    return ok(row)


# ======================= Function analyses ===============================
TREATMENTS = ("NOT_LIMITED", "PERFORM_WITH_AID", "RESTRUCTURE",
              "REASSIGN_MARGINAL", "CANNOT_PERFORM")

ANALYSIS_SPEC = [
    F("essential_function_id", "id", required=True),
    F("can_perform_unaided", "boolean", required=True),
    F("limitation_severity", "integer", required=True, minimum=0, maximum=5),
    F("proposed_treatment", "enum", required=True, enum=TREATMENTS),
]


@bp.post("/accommodation-requests/<case_id>/function-analyses")
@endpoint(["Manager"])
def create_analysis(case_id):
    data = validate(raw_body(), ANALYSIS_SPEC)
    req = need_request(case_id)
    function = need_function(data["essential_function_id"])
    require_manager_scope_case(req)
    require_not_sealed(req)
    if (function["status"] != "ACTIVE" or function["is_essential"] is not True
            or function["job_profile_id"] != req["job_profile_id"]):
        raise ApiError("ERR_FUNCTION_NOT_IN_PINNED_PROFILE",
                       "The duty is not a live essential duty on the pinned profile.")
    for existing in domain.analyses_of(req["id"]):
        if existing["essential_function_id"] == function["id"] and \
                existing["status"] in ("RECORDED", "DISPUTED"):
            raise ApiError("ERR_DUPLICATE_FUNCTION_ANALYSIS",
                           "This duty already carries a live analysis on the case.")
    row = store.new_row("FunctionAnalysis", {
        "request_id": req["id"],
        "essential_function_id": function["id"],
        "manager_id": g.user_id,
        "can_perform_unaided": data["can_perform_unaided"],
        "limitation_severity": data["limitation_severity"],
        "proposed_treatment": data["proposed_treatment"],
        "employee_dispute_note": None,
        "status": "RECORDED",
    })
    store.function_analyses[row["id"]] = row
    return created(row)


@bp.get("/function-analyses/<analysis_id>")
@endpoint(ALL_ROLES)
def get_analysis(analysis_id):
    return ok(need_analysis(analysis_id))


@bp.get("/function-analyses")
@endpoint(["Employee", "Manager", "AccommodationCoordinator", "AppealOfficer",
           "ComplianceAuditor"])
def list_analyses():
    limit, offset = read_pagination()
    rows = list(store.function_analyses.values())
    for key in ("request_id", "essential_function_id", "manager_id", "status"):
        value = flask_request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return listing(by_created(rows), limit, offset)


@bp.patch("/function-analyses/<analysis_id>")
@endpoint(["Manager", "Employee"])
def patch_analysis(analysis_id):
    data = validate(raw_body(), [
        F("can_perform_unaided", "boolean"),
        F("limitation_severity", "integer", minimum=0, maximum=5),
        F("proposed_treatment", "enum", enum=TREATMENTS),
        F("employee_dispute_note", "string", nullable=True),
    ])
    row = need_analysis(analysis_id)
    req = store.requests.get(row["request_id"])
    require_case_owner(req)
    require_manager_scope_case(req)
    require_not_sealed(req)
    if g.role == "Manager":
        for key in ("can_perform_unaided", "limitation_severity", "proposed_treatment"):
            if key in data:
                row[key] = data[key]
    elif g.role == "Employee" and "employee_dispute_note" in data:
        row["employee_dispute_note"] = data["employee_dispute_note"]
        if data["employee_dispute_note"] is not None and row["status"] == "RECORDED":
            row["status"] = "DISPUTED"
    touch(row)
    return ok(row)
