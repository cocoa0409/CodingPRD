"""AvoidableDay endpoints."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_CASE_CLOSED, ERR_INVALID_STATE, ERR_AVOIDABLE_DAY_DUPLICATE,
    ERR_VALIDATION_FAILED,
)
from middleware import require_roles
from response import success_object
from routes.helpers import paginate, lookup, any_authenticated
from services.case_service import (
    recompute_attribution, recompute_open_counts_and_escalation,
    refresh_escalation_effective,
)
from services.common import init_common, touch, append_audit
from services.validation import (
    get_json_body, reject_unknown_fields, validate_enum, validate_int,
    validate_string, validate_day_date,
)

bp = Blueprint("avoidable_days", __name__)

BARRIER_CODES = {"PLACEMENT_DELAY", "PAYER_AUTH_DELAY", "TRANSPORT_DELAY", "FAMILY_DECISION", "PHYSICIAN_DELAY"}
CREATE_FIELDS = ["day_date", "barrier_code", "barrier_weight"]


@bp.post("/api/utilization-cases/<cid>/avoidable-days")
def create_avoidable_day(cid):
    user_id, role = require_roles(["URNurse", "CaseManager"])
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    validate_day_date(body, "day_date")
    validate_enum(body, "barrier_code", BARRIER_CODES)
    validate_int(body, "barrier_weight", min_val=1, max_val=5)

    case = lookup(db.utilization_cases, cid, "UtilizationCase")
    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)

    # Priority 19: uniqueness of (case_id, day_date, barrier_code)
    for a in db.avoidable_days.values():
        if a["case_id"] == cid and a["day_date"] == body["day_date"] \
                and a["barrier_code"] == body["barrier_code"]:
            raise ApiError(ERR_AVOIDABLE_DAY_DUPLICATE,
                           "An AvoidableDay with the same (case_id, day_date, barrier_code) already exists",
                           409)

    rec = {
        **init_common(),
        "case_id": cid,
        "day_date": body["day_date"],
        "barrier_code": body["barrier_code"],
        "barrier_weight": body["barrier_weight"],
        "is_attributed": False,
        "status": "OPEN",
        "mitigation_note": None,
    }
    db.avoidable_days[rec["id"]] = rec

    recompute_attribution(case, rec["day_date"])
    recompute_open_counts_and_escalation(case)
    touch(case)
    append_audit(cid, "AVOIDABLE_DAY_RECORDED", role, user_id,
                 f"Avoidable day {rec['id']} recorded ({rec['day_date']}, {rec['barrier_code']})")
    return success_object(rec, 201)


@bp.get("/api/utilization-cases/<cid>/avoidable-days")
def list_avoidable_days(cid):
    any_authenticated()
    lookup(db.utilization_cases, cid, "UtilizationCase")
    items = sorted(
        (a for a in db.avoidable_days.values() if a["case_id"] == cid),
        key=lambda a: (a["day_date"], a["created_at"]),
    )
    if "status" in request.args:
        v = request.args["status"]
        if v not in ("OPEN", "MITIGATED", "OVERTURNED"):
            raise ApiError(ERR_VALIDATION_FAILED, f"Invalid status: {v}", 400)
        items = [a for a in items if a["status"] == v]
    return paginate(items)


@bp.post("/api/avoidable-days/<aid>/mitigate")
def mitigate_avoidable_day(aid):
    user_id, role = require_roles(["CaseManager"])
    body = get_json_body()
    reject_unknown_fields(body, ["mitigation_note"])
    validate_string(body, "mitigation_note")

    rec = lookup(db.avoidable_days, aid, "AvoidableDay")
    case = db.utilization_cases[rec["case_id"]]

    if case["review_status"] == "CLOSED":
        raise ApiError(ERR_CASE_CLOSED, "Case is CLOSED", 409)
    if rec["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, f"AvoidableDay is {rec['status']}, not OPEN", 409)

    rec["status"] = "MITIGATED"
    rec["mitigation_note"] = body["mitigation_note"]
    touch(rec)

    # Attribution re-runs for the group (MITIGATED records still participate)
    recompute_attribution(case, rec["day_date"])
    recompute_open_counts_and_escalation(case)
    refresh_escalation_effective(case)
    touch(case)
    append_audit(case["id"], "AVOIDABLE_DAY_MITIGATED", role, user_id,
                 f"Avoidable day {aid} mitigated")
    return success_object(rec, 200)
