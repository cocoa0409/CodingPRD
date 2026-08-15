"""AuthorizationRequest endpoints: create (OCC-guarded create-with-supersede),
payer-decision, resubmit, withdraw, denial listing."""
from datetime import timedelta
from flask import Blueprint

import db
from db import now_iso
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_CLINICAL_DOC_INCOMPLETE, ERR_BED_DAY_BUDGET_EXCEEDED,
    ERR_CERTIFIED_DAY_OVERLAP, ERR_VALIDATION_FAILED,
)
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import (
    certified_intervals, recompute_certified_counts, intervals_overlap,
)
from services.clock import parse_iso
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int,
    validate_string,
)

bp = Blueprint("authorization_requests", __name__)

LEVELS_OF_CARE = {"INPATIENT", "OBSERVATION"}
DECISIONS = {"APPROVE", "PEND", "DENY"}
DENIAL_REASON_CODES = {"CRITERIA_NOT_MET", "DOC_INSUFFICIENT", "LEVEL_OF_CARE"}

CREATE_FIELDS = ["level_of_care", "requested_day_count", "clinical_summary", "expected_case_version"]
DECISION_FIELDS = ["decision", "certified_day_start", "certified_day_count", "denial_reason_code", "pend_reason"]

CLINICAL_SUMMARY_MIN = 50


def auth_view(ar):
    out = dict(ar)
    out.pop("_interval_level", None)
    # denial_is_final: true when DENIED and no linked conference SCHEDULED
    if ar["status"] == "DENIED":
        from services.case_service import maybe_expire_conference
        final = True
        for conf in db.peer_to_peer_conferences.values():
            if conf["authorization_request_id"] == ar["id"]:
                maybe_expire_conference(conf)
                if conf["status"] == "SCHEDULED":
                    final = False
                    break
        out["denial_is_final"] = final
    else:
        out["denial_is_final"] = False
    return out


@bp.post("/api/utilization-cases/<cid>/authorization-requests")
def create_authorization_request(cid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_enum(body, "level_of_care", LEVELS_OF_CARE)
    validate_int(body, "requested_day_count", min_val=1)
    validate_string(body, "clinical_summary")
    validate_int(body, "expected_case_version")

    case = lookup(db.utilization_cases, cid, "UtilizationCase")

    # Priority 6: case-open gate
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # Priority 8: OCC
    if body["expected_case_version"] != case["version"]:
        raise ApiError(ERR_STALE_VERSION, "expected_case_version does not match current case version", 412)
    # Priority 12: clinical documentation completeness
    if len(body["clinical_summary"]) < CLINICAL_SUMMARY_MIN:
        raise ApiError(ERR_CLINICAL_DOC_INCOMPLETE,
                       "clinical_summary must be at least 50 characters", 422)
    # Priority 27: bed-day budget on create
    payer = db.payers[case["payer_id"]]
    if body["requested_day_count"] > payer["bed_day_budget_per_case"]:
        raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                       "requested_day_count exceeds payer bed_day_budget_per_case", 422)

    # Supersede existing SUBMITTED/PENDED requests of the case
    for existing in db.authorization_requests.values():
        if existing["case_id"] == cid and existing["status"] in ("SUBMITTED", "PENDED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)
            append_audit(cid, "AUTH_SUPERSEDED", role, user_id,
                         f"Authorization request {existing['id']} superseded by new request")

    ar = {
        **init_common(),
        "case_id": cid,
        "level_of_care": body["level_of_care"],
        "requested_day_count": body["requested_day_count"],
        "clinical_summary": body["clinical_summary"],
        "submission_round": 1,
        "status": "SUBMITTED",
        "certified_day_start": None,
        "certified_day_end": None,
        "denial_reason_code": None,
        "decided_at": None,
        "_interval_level": body["level_of_care"],  # current tag on granted interval (CC44 retag mutates)
    }
    db.authorization_requests[ar["id"]] = ar

    if case["auth_status"] == "AUTH_PENDING":
        case["auth_status"] = "AUTH_IN_PROGRESS"
    touch(case)
    append_audit(cid, "AUTH_SUBMITTED", role, user_id,
                 f"Authorization request {ar['id']} submitted ({body['level_of_care']}, {body['requested_day_count']} days)")
    return success_object(auth_view(ar), 201)


@bp.get("/api/utilization-cases/<cid>/authorization-requests")
def list_authorization_requests(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (a for a in db.authorization_requests.values() if a["case_id"] == cid),
        key=lambda a: a["created_at"],
    )
    return paginate([auth_view(a) for a in items])


@bp.get("/api/authorization-requests/<aid>")
def get_authorization_request(aid):
    any_authenticated()
    return success_object(auth_view(lookup(db.authorization_requests, aid, "AuthorizationRequest")))


@bp.post("/api/authorization-requests/<aid>/payer-decision")
def payer_decision(aid):
    user_id, role = require_roles(["PayerReviewer"])
    body = get_json_body()
    reject_unknown_fields(body, DECISION_FIELDS)
    validate_enum(body, "decision", DECISIONS)
    decision = body["decision"]
    if decision == "APPROVE":
        validate_int(body, "certified_day_start", min_val=1)
        validate_int(body, "certified_day_count", min_val=1)
    if decision == "DENY":
        validate_enum(body, "denial_reason_code", DENIAL_REASON_CODES)
    validate_string(body, "pend_reason", required=False)

    ar = lookup(db.authorization_requests, aid, "AuthorizationRequest")
    case = db.utilization_cases[ar["case_id"]]
    payer = db.payers[case["payer_id"]]

    # Case-open gate
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    # State legality: payer decision requires SUBMITTED
    if ar["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, f"Authorization request is {ar['status']}, not SUBMITTED", 409)

    if decision == "PEND":
        ar["status"] = "PENDED"
        ar["decided_at"] = now_iso()
        touch(ar)
        touch(case)
        append_audit(case["id"], "AUTH_PENDED", role, user_id,
                     f"Authorization request {aid} pended")
        return success_object(auth_view(ar), 200)

    if decision == "APPROVE":
        start = body["certified_day_start"]
        count = body["certified_day_count"]
        end = start + count
        # Certified-interval overlap (priority 21)
        if intervals_overlap(case["id"], start, end):
            raise ApiError(ERR_CERTIFIED_DAY_OVERLAP,
                           "Proposed certified interval intersects an existing certified interval", 409)
        # Budget (priority 27)
        if case["certified_day_count"] + count > payer["bed_day_budget_per_case"]:
            raise ApiError(ERR_BED_DAY_BUDGET_EXCEEDED,
                           "Approval would exceed payer bed_day_budget_per_case", 422)
        ar["status"] = "APPROVED"
        ar["certified_day_start"] = start
        ar["certified_day_end"] = end
        ar["_interval_level"] = ar["level_of_care"]
        ar["decided_at"] = now_iso()
        touch(ar)
        case["auth_status"] = "AUTHORIZED"
        if case["review_status"] == "ADMISSION_REVIEWED":
            case["review_status"] = "MONITORING"
        recompute_certified_counts(case)
        touch(case)
        append_audit(case["id"], "AUTH_APPROVED", role, user_id,
                     f"Authorization request {aid} approved [{start},{end})")
        return success_object(auth_view(ar), 200)

    # DENY
    ar["status"] = "DENIED"
    ar["denial_reason_code"] = body["denial_reason_code"]
    ar["decided_at"] = now_iso()
    touch(ar)

    denied_at = ar["decided_at"]
    appeal_deadline = (parse_iso(denied_at) + timedelta(days=payer["appeal_deadline_days"]))
    from db import new_id
    denial = {
        **init_common(),
        "case_id": case["id"],
        "authorization_request_id": ar["id"],
        "denial_type": "INITIAL_AUTH",
        "denied_at": denied_at,
        "denied_day_count": ar["requested_day_count"],
        "appeal_deadline_at": appeal_deadline.strftime("%Y-%m-%dT%H:%M:%S.") + f"{appeal_deadline.microsecond // 1000:03d}Z",
        "status": "OPEN",
    }
    db.denial_cases[denial["id"]] = denial

    case["auth_status"] = "DENIED"
    touch(case)
    append_audit(case["id"], "AUTH_DENIED", role, user_id,
                 f"Authorization request {aid} denied ({body['denial_reason_code']}); denial {denial['id']} opened")
    return success_object(auth_view(ar), 200)


@bp.post("/api/authorization-requests/<aid>/resubmit")
def resubmit_authorization_request(aid):
    user_id, role = require_roles(["URNurse"])
    body = get_json_body()
    reject_unknown_fields(body, ["clinical_summary"])
    validate_string(body, "clinical_summary")

    ar = lookup(db.authorization_requests, aid, "AuthorizationRequest")
    case = db.utilization_cases[ar["case_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if ar["status"] != "PENDED":
        raise ApiError(ERR_INVALID_STATE, f"Authorization request is {ar['status']}, not PENDED", 409)
    if len(body["clinical_summary"]) < CLINICAL_SUMMARY_MIN:
        raise ApiError(ERR_CLINICAL_DOC_INCOMPLETE,
                       "clinical_summary must be at least 50 characters", 422)

    ar["status"] = "SUBMITTED"
    ar["clinical_summary"] = body["clinical_summary"]
    ar["submission_round"] += 1
    touch(ar)
    append_audit(case["id"], "AUTH_RESUBMITTED", role, user_id,
                 f"Authorization request {aid} resubmitted (round {ar['submission_round']})")
    return success_object(auth_view(ar), 200)


@bp.post("/api/authorization-requests/<aid>/withdraw")
def withdraw_authorization_request(aid):
    user_id, role = require_roles(["URNurse"])
    get_json_body()

    ar = lookup(db.authorization_requests, aid, "AuthorizationRequest")
    case = db.utilization_cases[ar["case_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if ar["status"] not in ("SUBMITTED", "PENDED"):
        raise ApiError(ERR_INVALID_STATE,
                       f"Authorization request is {ar['status']}; only SUBMITTED or PENDED may be withdrawn",
                       409)

    ar["status"] = "WITHDRAWN"
    touch(ar)
    append_audit(case["id"], "AUTH_WITHDRAWN", role, user_id,
                 f"Authorization request {aid} withdrawn")
    return success_object(auth_view(ar), 200)


@bp.get("/api/authorization-requests/<aid>/denial-cases")
def list_auth_denial_cases(aid):
    any_authenticated()
    lookup(db.authorization_requests, aid, "AuthorizationRequest")
    items = sorted(
        (d for d in db.denial_cases.values() if d["authorization_request_id"] == aid),
        key=lambda d: d["created_at"],
    )
    from services.case_service import maybe_close_denial
    for d in items:
        maybe_close_denial(d)
    from routes.denials import denial_view
    return paginate([denial_view(d) for d in items])
