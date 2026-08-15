"""ConditionCode44Request endpoints."""
from flask import Blueprint

import db
from db import now_iso
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_CC44_POST_DISCHARGE, ERR_CC44_ALREADY_OPEN, ERR_CC44_PAYER_INELIGIBLE,
    ERR_CC44_CRITERIA_STILL_MET, ERR_SOD_ROLE_CONFLICT, ERR_VALIDATION_FAILED,
)
from middleware import require_roles, check_attending_ownership
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.calculations import cc44_rebill_estimate, MEDICARE_FAMILY
from services.case_service import recompute_certified_counts
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int,
    validate_string,
)

bp = Blueprint("cc44", __name__)

CREATE_FIELDS = ["rationale", "service_lines", "expected_case_version"]
CONCURRENCE_FIELDS = ["decision", "concurrence_note"]
COMMITTEE_FIELDS = ["decision", "committee_note"]
RESCIND_FIELDS = ["rescind_reason"]


def cc44_view(req):
    out = dict(req)
    out.pop("_retagged_auth_ids", None)
    return out


def _validate_service_lines(body):
    if "service_lines" not in body or body["service_lines"] is None:
        raise ApiError(ERR_VALIDATION_FAILED, "Missing required field: service_lines", 400)
    lines = body["service_lines"]
    if not isinstance(lines, list):
        raise ApiError(ERR_VALIDATION_FAILED, "service_lines must be an array", 400)
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(ERR_VALIDATION_FAILED, "Each service line must be an object", 400)
        for k in line:
            if k not in ("description", "charge_cents", "rate_milli"):
                raise ApiError(ERR_VALIDATION_FAILED, f"Service line field not allowed: {k}", 400)
        if "description" not in line or not isinstance(line["description"], str):
            raise ApiError(ERR_VALIDATION_FAILED, "Service line description must be a string", 400)
        for f in ("charge_cents", "rate_milli"):
            if f not in line or not isinstance(line[f], int) or isinstance(line[f], bool):
                raise ApiError(ERR_VALIDATION_FAILED, f"Service line {f} must be an integer", 400)
    return lines


@bp.post("/api/utilization-cases/<cid>/condition-code-44-requests")
def create_cc44(cid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_string(body, "rationale")
    lines = _validate_service_lines(body)
    validate_int(body, "expected_case_version")

    case = lookup(db.utilization_cases, cid, "UtilizationCase")

    # Priority 8: OCC — checked before the domain-specific post-discharge gate
    # (priority 9) per the scaffold's validation ordering. Note: priority 6
    # (ERR_CASE_CLOSED) does not apply to this endpoint; the CC44 flow has its
    # own post-discharge error at priority 9.
    if body["expected_case_version"] != case["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_case_version does not match current case version", 412)
    # Priority 9: post-discharge CC44 guard
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CC44_POST_DISCHARGE, "CC44 request created after discharge", 409)
    # Priority 18: at most one open CC44 per case
    for existing in db.condition_code_44_requests.values():
        if existing["case_id"] == cid and existing["status"] in ("CONCURRENCE_PENDING", "COMMITTEE_PENDING"):
            raise ApiError(ERR_CC44_ALREADY_OPEN,
                           "A CC44 request is already open for this case", 409)
    # Priority 24: Medicare-family payer eligibility
    payer = db.payers[case["payer_id"]]
    if payer["plan_class"] not in MEDICARE_FAMILY:
        raise ApiError(ERR_CC44_PAYER_INELIGIBLE,
                       "CC44 requires payer plan_class MEDICARE or MANAGED_MEDICARE", 422)
    # Priority 25: clinical basis — latest SUBMITTED/ADVISOR_REVIEWED review is CRITERIA_NOT_MET
    submitted_reviews = [
        r for r in db.admission_reviews.values()
        if r["case_id"] == cid and r["status"] in ("SUBMITTED", "ADVISOR_REVIEWED")
    ]
    if not submitted_reviews:
        raise ApiError(ERR_CC44_CRITERIA_STILL_MET,
                       "No submitted admission review establishes the CC44 clinical basis", 422)
    # "Latest" review (PRD §3.6): the last row of the case's created_at-
    # ascending review listing. sorted() is stable, so tied timestamps —
    # common under the logical clock — resolve to the most recently created.
    latest = sorted(submitted_reviews, key=lambda r: r["created_at"])[-1]
    if latest["determination"] != "CRITERIA_NOT_MET":
        raise ApiError(ERR_CC44_CRITERIA_STILL_MET,
                       "Latest submitted admission review has determination CRITERIA_MET", 422)

    req = {
        **init_common(),
        "case_id": cid,
        "rationale": body["rationale"],
        "service_lines": lines,
        "rebill_estimate_cents": cc44_rebill_estimate(lines),
        "attending_concurrence": "PENDING",
        "committee_reviewer_id": None,
        "status": "CONCURRENCE_PENDING",
        "effective_at": None,
    }
    db.condition_code_44_requests[req["id"]] = req
    touch(case)
    append_audit(cid, "CC44_INITIATED", role, user_id,
                 f"CC44 request {req['id']} initiated; rebill estimate {req['rebill_estimate_cents']} cents")
    return success_object(cc44_view(req), 201)


@bp.get("/api/utilization-cases/<cid>/condition-code-44-requests")
def list_cc44(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (r for r in db.condition_code_44_requests.values() if r["case_id"] == cid),
        key=lambda r: r["created_at"],
    )
    return paginate([cc44_view(r) for r in items])


@bp.post("/api/condition-code-44-requests/<cid>/concurrence")
def cc44_concurrence(cid):
    user_id, role = require_roles(["AttendingPhysician"])
    body = get_json_body()
    reject_unknown_fields(body, CONCURRENCE_FIELDS)
    validate_enum(body, "decision", {"CONCUR", "DECLINE"})
    validate_string(body, "concurrence_note", required=False)

    req = lookup(db.condition_code_44_requests, cid, "ConditionCode44Request")
    case = db.utilization_cases[req["case_id"]]

    # Priority 5: attending ownership
    check_attending_ownership(case, user_id)
    # Priority 7: state legality
    if req["status"] != "CONCURRENCE_PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       f"CC44 request is {req['status']}, not CONCURRENCE_PENDING", 409)

    if body["decision"] == "CONCUR":
        req["attending_concurrence"] = "CONCURRED"
        req["status"] = "COMMITTEE_PENDING"
        touch(req)
        append_audit(case["id"], "CC44_CONCURRED", role, user_id,
                     f"Attending concurred on CC44 {cid}")
    else:
        req["attending_concurrence"] = "DECLINED"
        req["status"] = "DECLINED_CLOSED"
        touch(req)
        append_audit(case["id"], "CC44_DECLINED", role, user_id,
                     f"Attending declined CC44 {cid}")
    return success_object(cc44_view(req), 200)


@bp.post("/api/condition-code-44-requests/<cid>/committee-review")
def cc44_committee_review(cid):
    user_id, role = require_roles(["PhysicianAdvisor"])
    body = get_json_body()
    reject_unknown_fields(body, COMMITTEE_FIELDS)
    validate_enum(body, "decision", {"APPROVE", "REJECT"})
    validate_string(body, "committee_note", required=False)

    req = lookup(db.condition_code_44_requests, cid, "ConditionCode44Request")
    case = db.utilization_cases[req["case_id"]]

    if req["status"] != "COMMITTEE_PENDING":
        raise ApiError(ERR_INVALID_STATE,
                       f"CC44 request is {req['status']}, not COMMITTEE_PENDING", 409)
    # Priority 13: segregation of duties
    if user_id == case["attending_physician_id"]:
        raise ApiError(ERR_SOD_ROLE_CONFLICT,
                       "Committee reviewer must differ from the case attending physician", 422)

    req["committee_reviewer_id"] = user_id

    if body["decision"] == "REJECT":
        req["status"] = "REJECTED"
        touch(req)
        append_audit(case["id"], "CC44_REJECTED", role, user_id,
                     f"Committee rejected CC44 {cid}")
        return success_object(cc44_view(req), 200)

    # APPROVE — full status-change cascade
    req["status"] = "APPROVED"
    req["effective_at"] = now_iso()
    touch(req)

    case["current_admission_status"] = "OBSERVATION"
    # Withdraw non-terminal INPATIENT auth requests
    for ar in db.authorization_requests.values():
        if ar["case_id"] == case["id"] and ar["level_of_care"] == "INPATIENT" \
                and ar["status"] in ("SUBMITTED", "PENDED"):
            ar["status"] = "WITHDRAWN"
            touch(ar)
            append_audit(case["id"], "AUTH_WITHDRAWN", role, user_id,
                         f"INPATIENT authorization {ar['id']} withdrawn on CC44 approval")
    # Re-tag APPROVED INPATIENT certified intervals to OBSERVATION (ranges unchanged);
    # remember exactly which intervals this request re-tagged so rescind restores
    # only those (and not intervals granted later under an honest OBSERVATION tag).
    retagged = []
    for ar in db.authorization_requests.values():
        if ar["case_id"] == case["id"] and ar["status"] == "APPROVED" \
                and ar.get("_interval_level") == "INPATIENT":
            ar["_interval_level"] = "OBSERVATION"
            touch(ar)
            retagged.append(ar["id"])
    req["_retagged_auth_ids"] = retagged
    recompute_certified_counts(case)
    touch(case)
    append_audit(case["id"], "CC44_APPROVED", role, user_id,
                 f"CC44 {cid} approved; case status flipped to OBSERVATION")
    return success_object(cc44_view(req), 200)


@bp.post("/api/condition-code-44-requests/<cid>/rescind")
def cc44_rescind(cid):
    user_id, role = require_roles(["URDirector"])
    body = get_json_body()
    reject_unknown_fields(body, RESCIND_FIELDS)
    validate_string(body, "rescind_reason")

    req = lookup(db.condition_code_44_requests, cid, "ConditionCode44Request")
    case = db.utilization_cases[req["case_id"]]

    # Case-closure gate rejects rescission on a discharged case
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if req["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE,
                       f"CC44 request is {req['status']}, not APPROVED", 409)

    req["status"] = "RESCINDED"
    touch(req)

    # Compensating action: restore INPATIENT status and the exact interval tags
    # this CC44 re-tagged at approval
    case["current_admission_status"] = "INPATIENT"
    for auth_id in req.get("_retagged_auth_ids", []):
        ar = db.authorization_requests.get(auth_id)
        if ar is not None and ar["status"] == "APPROVED" and ar.get("_interval_level") == "OBSERVATION":
            ar["_interval_level"] = "INPATIENT"
            touch(ar)
    recompute_certified_counts(case)
    touch(case)
    append_audit(case["id"], "CC44_RESCINDED", role, user_id,
                 f"CC44 {cid} rescinded; case status restored to INPATIENT")
    return success_object(cc44_view(req), 200)
