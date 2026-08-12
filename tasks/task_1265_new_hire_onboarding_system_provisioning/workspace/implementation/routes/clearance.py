"""ClearanceCase action endpoints (PRD §3.4)."""

from flask import Blueprint

from auth import require_roles
from db import store
from errors import (ApiError, ERR_CLEARANCE_NOT_FOUND,
                    ERR_INVALID_CLEARANCE_STATE, ERR_CLEARANCE_NOT_ESCALATED,
                    ERR_SELF_ADJUDICATION_FORBIDDEN)
from helpers import touch, get_or_404, ser_clearance
from sweep import create_provisioning_order, revoke_case
from util import success, get_body, req_present, as_str, as_enum

bp = Blueprint("clearance", __name__)

COMPONENTS = ("BACKGROUND", "REFERENCE")
RESULTS = ("PASSED", "FAILED")
DECISIONS = ("CLEARED", "REJECTED")


@bp.post("/api/clearance-cases/<cid>/record-result")
def record_result(cid):
    require_roles("HRAdmin")
    body = get_body()
    component = as_enum(req_present(body, "component"), "component",
                        COMPONENTS)
    result = as_enum(req_present(body, "result"), "result", RESULTS)
    cc = get_or_404("clearances", cid, ERR_CLEARANCE_NOT_FOUND,
                    "ClearanceCase")
    field = "background_status" if component == "BACKGROUND" \
        else "reference_status"
    if cc["status"] != "IN_PROGRESS" or cc[field] != "PENDING":
        raise ApiError(ERR_INVALID_CLEARANCE_STATE, 409,
                       "record-result requires IN_PROGRESS with the "
                       "component still PENDING")
    cc[field] = result
    if cc["background_status"] == "PASSED" and \
            cc["reference_status"] == "PASSED":
        cc["status"] = "CLEARED"
        touch(cc)
        # Automatic hinge: owning case advances to PROVISIONING
        case = store["cases"].get(cc["case_id"])
        if case is not None and case["phase"] == "CLEARANCE_IN_PROGRESS":
            create_provisioning_order(case)
    elif result == "FAILED":
        cc["status"] = "ESCALATED"
        touch(cc)
    else:
        touch(cc)
    return success(ser_clearance(cc))


@bp.post("/api/clearance-cases/<cid>/adjudicate")
def adjudicate(cid):
    uid, _ = require_roles("BackgroundAdjudicator")
    body = get_body()
    decision = as_enum(req_present(body, "decision"), "decision", DECISIONS)
    rationale = as_str(req_present(body, "rationale"), "rationale")
    cc = get_or_404("clearances", cid, ERR_CLEARANCE_NOT_FOUND,
                    "ClearanceCase")
    # Stage 6: state gate — must be ESCALATED
    if cc["status"] != "ESCALATED":
        raise ApiError(ERR_CLEARANCE_NOT_ESCALATED, 409,
                       "adjudicate requires an ESCALATED clearance case")
    # Stage 7: segregation of duties — the initiator may never adjudicate
    if uid == cc["initiated_by_user_id"]:
        raise ApiError(ERR_SELF_ADJUDICATION_FORBIDDEN, 403,
                       "The clearance initiator may not adjudicate it")
    cc["adjudicated_by_user_id"] = uid
    cc["adjudication_rationale"] = rationale
    case = store["cases"].get(cc["case_id"])
    if decision == "CLEARED":
        cc["status"] = "CLEARED"
        cc["override_clear"] = True
        touch(cc)
        if case is not None and case["phase"] == "CLEARANCE_IN_PROGRESS":
            create_provisioning_order(case)
    else:
        cc["status"] = "REJECTED"
        touch(cc)
        if case is not None and case["phase"] == "CLEARANCE_IN_PROGRESS":
            revoke_case(case)
    return success(ser_clearance(cc))
