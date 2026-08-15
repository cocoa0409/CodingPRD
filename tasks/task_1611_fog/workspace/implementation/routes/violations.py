"""Violation endpoints: list, read, escalate, resolve, dismiss."""
from flask import Blueprint, request

from db import STORE, now
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_ESCALATION_NOT_DUE,
    ERR_SOD_VIOLATION,
)
from middleware import (
    auth,
    require_roles,
    forbid_unless,
    get_or_404,
    paginate,
    by_creation,
    filter_enum,
)
from response import success
from services.calculations import CITATION_FINE
from services.posture import touch_establishment
from services.serializers import ser_violation

bp = Blueprint("violations", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer", "FseContact"]
STATUSES = ("NOTICED", "CITATION", "RESOLVED", "DISMISSED")


@bp.get("/violations")
def list_violations():
    uid, role = auth()
    require_roles(role, READERS)
    est_filter = request.args.get("establishment_id")
    insp_filter = request.args.get("inspection_id")
    status_filter = filter_enum(request.args, "status", STATUSES)
    items = list(STORE["violations"].values())
    if role == "FseContact":
        items = [v for v in items if v["establishment_id"] == uid]
    if est_filter is not None:
        items = [v for v in items if v["establishment_id"] == est_filter]
    if insp_filter is not None:
        items = [v for v in items if v["inspection_id"] == insp_filter]
    if status_filter is not None:
        items = [v for v in items if v["status"] == status_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_violation(v) for v in page], 200, "array", meta)


@bp.get("/violations/<vid>")
def get_violation(vid):
    uid, role = auth()
    require_roles(role, READERS)
    v = get_or_404("violations", vid)
    if role == "FseContact":
        forbid_unless(v["establishment_id"] == uid)
    return success(ser_violation(v))


@bp.post("/violations/<vid>/escalate")
def escalate_violation(vid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    v = get_or_404("violations", vid)
    if v["status"] != "NOTICED":
        raise ApiError(ERR_INVALID_STATE, 409, "Violation is not in NOTICED status")
    current = now()
    if current < v["cure_deadline"]:
        raise ApiError(ERR_ESCALATION_NOT_DUE, 409, "cure_deadline has not been reached")
    v["status"] = "CITATION"
    v["fine_cents"] = CITATION_FINE[v["severity"]]
    v["escalated_at"] = current
    v["updated_at"] = current
    v["version"] += 1
    touch_establishment(STORE["establishments"][v["establishment_id"]], current, bump=False)
    return success(ser_violation(v))


@bp.post("/violations/<vid>/resolve")
def resolve_violation(vid):
    uid, role = auth()
    require_roles(role, ["Inspector"])
    v = get_or_404("violations", vid)
    if v["status"] not in ("NOTICED", "CITATION"):
        raise ApiError(ERR_INVALID_STATE, 409, "Violation is already closed")
    current = now()
    v["status"] = "RESOLVED"
    v["resolved_at"] = current
    v["updated_at"] = current
    v["version"] += 1
    touch_establishment(STORE["establishments"][v["establishment_id"]], current, bump=False)
    return success(ser_violation(v))


@bp.post("/violations/<vid>/dismiss")
def dismiss_violation(vid):
    uid, role = auth()
    require_roles(role, ["ComplianceOfficer"])
    v = get_or_404("violations", vid)
    if v["status"] not in ("NOTICED", "CITATION"):
        raise ApiError(ERR_INVALID_STATE, 409, "Violation is already closed")
    if uid == v["recorded_by_user_id"]:
        raise ApiError(ERR_SOD_VIOLATION, 403, "Dismissing officer must differ from the recording inspector")
    current = now()
    v["status"] = "DISMISSED"
    v["dismissed_at"] = current
    v["dismissed_by_user_id"] = uid
    v["updated_at"] = current
    v["version"] += 1
    touch_establishment(STORE["establishments"][v["establishment_id"]], current, bump=False)
    return success(ser_violation(v))
