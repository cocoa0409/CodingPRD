"""SAR reports: draft creation, narrative edits, QA, approval, filing."""
from datetime import timedelta

from flask import Blueprint, request

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import create_continuing_review, recompute_customer_risk
from util import (QA_OUTCOMES, base_entity, opt_bool, opt_date, opt_str,
                  req_date, req_enum, req_int, serialize, sort_created, touch)

bp = Blueprint("sars", __name__)

INITIAL_WINDOW_DAYS = 30
SUBJECT_UNIDENTIFIED_EXTENSION_DAYS = 30


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


def initial_deadline(case, subject_unidentified):
    base = case["initial_detection_at"] or case["created_at"]
    days = INITIAL_WINDOW_DAYS
    if subject_unidentified:
        days += SUBJECT_UNIDENTIFIED_EXTENSION_DAYS
    return base + timedelta(days=days)


@bp.route("/cases/<rid>/sar-reports", methods=["POST"])
def create_sar(rid):
    body = get_body()
    start = req_date(body, "activity_start_date")
    end = req_date(body, "activity_end_date")
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "activity_end_date must be >= activity_start_date", 400)
    subject_unidentified = opt_bool(body, "subject_unidentified", default=False)
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    case = _get(db.cases, rid, "Case")
    if case["assigned_analyst_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the assigned analyst may create the case SAR", 403)
    if case["status"] != "SAR_IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE",
                       f"Case in status {case['status']} cannot accept a SAR draft", 409)
    sar = base_entity()
    sar.update({
        "case_id": case["id"],
        "customer_id": case["customer_id"],
        "prior_sar_id": None,
        "is_continuing": False,
        "subject_unidentified": subject_unidentified,
        "narrative": "",
        "narrative_length": 0,
        "activity_start_date": start,
        "activity_end_date": end,
        "deadline_at": initial_deadline(case, subject_unidentified),
        "status": "DRAFT",
        "drafted_by_analyst_id": user_id,
        "qa_reviewer_id": None,
        "approved_by_analyst_id": None,
        "filed_at": None,
        "filing_reference": None,
    })
    db.sars[sar["id"]] = sar
    return response.success(serialize(sar), status=201)


@bp.route("/sar-reports", methods=["GET"])
def list_sars():
    _, role = authn()
    authz(role, ALL_ROLES)
    limit, offset = pagination_params()
    items = list(db.sars.values())
    for field in ("case_id", "customer_id", "prior_sar_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [s for s in items if s.get(field) == value]
    items = sort_created(items)
    return response.paginated([serialize(s) for s in items], limit, offset)


@bp.route("/sar-reports/<rid>", methods=["GET"])
def get_sar(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    sar = _get(db.sars, rid, "SARReport")
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/narrative", methods=["PUT"])
def edit_narrative(rid):
    body = get_body()
    expected_version = req_int(body, "expected_sar_version")
    narrative = opt_str(body, "narrative", default=None)
    if "narrative" in body and body["narrative"] is not None and not isinstance(body["narrative"], str):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'narrative' must be a string", 400)
    new_start = opt_date(body, "activity_start_date", default=None)
    new_end = opt_date(body, "activity_end_date", default=None)
    if new_start is not None and new_end is not None and new_end < new_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "activity_end_date must be >= activity_start_date", 400)
    new_unidentified = opt_bool(body, "subject_unidentified", default=None)
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    sar = _get(db.sars, rid, "SARReport")
    if sar["drafted_by_analyst_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the drafting analyst may edit the narrative", 403)
    if sar["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       f"SAR in status {sar['status']} cannot be edited", 409)
    if expected_version != sar["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_sar_version does not match the SAR's current "
                       "version", 412)
    start = new_start if new_start is not None else sar["activity_start_date"]
    end = new_end if new_end is not None else sar["activity_end_date"]
    if end < start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "activity_end_date must be >= activity_start_date", 400)
    if narrative is not None:
        sar["narrative"] = narrative
    sar["activity_start_date"] = start
    sar["activity_end_date"] = end
    if new_unidentified is not None:
        sar["subject_unidentified"] = new_unidentified
    sar["narrative_length"] = len(sar["narrative"])
    touch(sar)
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/submit-qa", methods=["POST"])
def submit_qa(rid):
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    sar = _get(db.sars, rid, "SARReport")
    if sar["drafted_by_analyst_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE",
                       "Only the drafting analyst may submit the SAR for QA", 403)
    if sar["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE",
                       f"SAR in status {sar['status']} cannot be submitted for QA", 409)
    if sar["narrative_length"] < 500:
        raise ApiError("ERR_NARRATIVE_INSUFFICIENT",
                       "SAR narrative must be at least 500 characters", 422)
    sar["status"] = "IN_QA"
    touch(sar)
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/qa-review", methods=["POST"])
def sar_qa_review(rid):
    body = get_body()
    outcome = req_enum(body, "outcome", QA_OUTCOMES)
    opt_str(body, "notes")
    user_id, role = authn()
    authz(role, ["QAReviewer"])
    sar = _get(db.sars, rid, "SARReport")
    if user_id == sar["drafted_by_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "SAR QA reviewer must differ from the drafting analyst", 403)
    if sar["status"] != "IN_QA":
        raise ApiError("ERR_INVALID_STATE",
                       f"SAR in status {sar['status']} is not in QA", 409)
    if outcome == "PASS":
        sar["status"] = "QA_PASSED"
        sar["qa_reviewer_id"] = user_id
    else:
        sar["status"] = "DRAFT"
    touch(sar)
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/approve", methods=["POST"])
def approve_sar(rid):
    user_id, role = authn()
    authz(role, ["BSAManager"])
    sar = _get(db.sars, rid, "SARReport")
    if user_id == sar["drafted_by_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from the drafting analyst", 403)
    if sar["status"] != "QA_PASSED":
        raise ApiError("ERR_INVALID_STATE",
                       f"SAR in status {sar['status']} cannot be approved", 409)
    sar["status"] = "APPROVED"
    sar["approved_by_analyst_id"] = user_id
    touch(sar)
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/file", methods=["POST"])
def file_sar(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    sar = _get(db.sars, rid, "SARReport")
    if sar["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"SAR in status {sar['status']} cannot be filed", 409)
    # Priority 11 (activity-window overlap) outranks priority 17 (deadline).
    for other in db.sars.values():
        if (other["id"] != sar["id"] and other["customer_id"] == sar["customer_id"]
                and other["status"] == "FILED"
                and sar["activity_start_date"] <= other["activity_end_date"]
                and other["activity_start_date"] <= sar["activity_end_date"]):
            raise ApiError("ERR_ACTIVITY_WINDOW_OVERLAP",
                           "Activity window shares a calendar day with another "
                           "FILED SAR for this customer", 409)
    now = db.now()
    if now > sar["deadline_at"]:
        raise ApiError("ERR_FILING_DEADLINE_PASSED",
                       "The SAR filing deadline has passed", 422)
    sar["status"] = "FILED"
    sar["filed_at"] = now
    year = now.year
    seq = 1 + sum(1 for s in db.sars.values()
                  if s["id"] != sar["id"] and s["status"] == "FILED"
                  and s["filed_at"] is not None
                  and s["filed_at"].year == year)
    sar["filing_reference"] = f"SAR-{year}-{seq:06d}"
    touch(sar)

    case = db.cases.get(sar["case_id"])
    if case is not None and case["status"] == "SAR_IN_PROGRESS":
        case["status"] = "PENDING_QA"
        touch(case)

    customer = db.customers.get(sar["customer_id"])
    if customer is not None:
        recompute_customer_risk(customer)

    create_continuing_review(sar)
    return response.success(serialize(sar), status=200)


@bp.route("/sar-reports/<rid>/continuing-reviews", methods=["GET"])
def list_sar_reviews(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    sar = _get(db.sars, rid, "SARReport")
    limit, offset = pagination_params()
    items = sort_created([r for r in db.reviews.values()
                          if r["sar_report_id"] == sar["id"]])
    return response.paginated([serialize(r) for r in items], limit, offset)
