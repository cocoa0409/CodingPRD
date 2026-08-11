"""No-access case endpoints (PRD 3.4): four-stage escalation ladder."""
import db
from db import base_resource, clock_now, touch
from errors import raise_err
from middleware import ALL_ROLES, require_roles
from response import ok_object
from services.core import get_or_404, list_page, ser_case, wo_cancel_cascade
from flask import Blueprint, request
from validate import body, req_enum

bp = Blueprint("cases", __name__)

RESOLUTIONS = ("ACCESS_GAINED", "ACCOUNT_EXEMPTED", "FORCED_ENTRY")

# Current stage -> channel whose DELIVERED notification gates the advance,
# and next stage (+ channel auto-sent on arrival, if any).
STAGE_FLOW = {
    "STAGE_1_DOOR_HANGER": ("DOOR_HANGER", "STAGE_2_CERTIFIED_MAIL", "CERTIFIED_MAIL"),
    "STAGE_2_CERTIFIED_MAIL": ("CERTIFIED_MAIL", "STAGE_3_PHONE_CAMPAIGN", "PHONE"),
    "STAGE_3_PHONE_CAMPAIGN": ("PHONE", "STAGE_4_FIELD_VISIT", None),
}


@bp.get("/api/no-access-cases")
@require_roles(*ALL_ROLES)
def list_cases():
    filters = {}
    for k in ("work_order_id", "stage", "status"):
        if request.args.get(k) is not None:
            filters[k] = request.args[k]
    return list_page(db.no_access_cases.values(), filters, ser_case)


@bp.get("/api/no-access-cases/<caseId>")
@require_roles(*ALL_ROLES)
def get_case(caseId):
    return ok_object(ser_case(get_or_404(db.no_access_cases, caseId, "NoAccessCase")))


@bp.post("/api/no-access-cases/<caseId>/advance")
@require_roles("Scheduler")
def advance_case(caseId):
    case = get_or_404(db.no_access_cases, caseId, "NoAccessCase")
    if case["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "No-access case is not OPEN")
    flow = STAGE_FLOW.get(case["stage"])
    if flow is None:
        raise_err("ERR_INVALID_STATE", "Case is at the final stage")
    required_channel, next_stage, next_channel = flow
    delivered = any(
        n["no_access_case_id"] == case["id"]
        and n["channel"] == required_channel
        and n["status"] == "DELIVERED"
        for n in db.notifications.values()
    )
    if not delivered:
        raise_err("ERR_ESCALATION_STEP_REQUIRED",
                  "Current stage notification must be DELIVERED before advancing")
    case["stage"] = next_stage
    touch(case)
    if next_channel is not None:
        n = base_resource()
        n.update({
            "work_order_id": case["work_order_id"],
            "no_access_case_id": case["id"],
            "channel": next_channel,
            "sent_at": clock_now(),
            "delivered_at": None,
            "status": "SENT",
        })
        db.notifications[n["id"]] = n
    return ok_object(ser_case(case))


@bp.post("/api/no-access-cases/<caseId>/resolve")
@require_roles("Scheduler")
def resolve_case(caseId):
    case = get_or_404(db.no_access_cases, caseId, "NoAccessCase")
    b = body()
    resolution = req_enum(b, "resolution", RESOLUTIONS)
    if case["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "No-access case is not OPEN")
    # Safety (stage 9): FORCED_ENTRY only from STAGE_4_FIELD_VISIT.
    if resolution == "FORCED_ENTRY" and case["stage"] != "STAGE_4_FIELD_VISIT":
        raise_err("ERR_FORCED_ENTRY_NOT_AUTHORIZED",
                  "FORCED_ENTRY requires stage STAGE_4_FIELD_VISIT")
    case["status"] = "RESOLVED"
    case["resolution"] = resolution
    touch(case)
    if resolution == "ACCOUNT_EXEMPTED":
        wo = db.work_orders.get(case["work_order_id"])
        if wo is not None and wo["lifecycle_status"] not in ("CLOSED", "CANCELLED"):
            wo_cancel_cascade(wo)
            account = db.accounts.get(wo["service_account_id"])
            if account is not None and account["status"] == "IN_PROGRAM":
                account["status"] = "EXEMPTED"
                touch(account)
    return ok_object(ser_case(case))
