"""Inspection endpoints: record (scored, immutable; failing opens a violation),
list, read."""
import uuid
from datetime import timedelta

from flask import Blueprint, request

from db import STORE, now, next_seq
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import auth, require_roles, get_or_404, paginate, by_creation
from response import success
from services.calculations import (
    inspection_score,
    highest_severity,
    CURE_DAYS,
    SEVERITY_DEDUCTION,
)
from services.posture import touch_establishment
from services.serializers import ser_inspection
from validation import body_json, v_str

bp = Blueprint("inspections", __name__)

READERS = ["ProgramAdmin", "Inspector", "ComplianceOfficer"]
CATEGORIES = ("GREASE_TRAP_MAINTENANCE", "RECORD_KEEPING", "STRUCTURAL", "BMP_PRACTICES")
SEVERITIES = tuple(SEVERITY_DEDUCTION.keys())


def _validate_items(body):
    if "items" not in body or body["items"] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: items")
    items = body["items"]
    if not isinstance(items, list):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field 'items' must be an array")
    normalized = []
    for item in items:
        if not isinstance(item, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each inspection item must be an object")
        category = item.get("category")
        severity = item.get("severity")
        if category not in CATEGORIES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid item category")
        if severity not in SEVERITIES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid item severity")
        normalized.append({"category": category, "severity": severity})
    return normalized


@bp.post("/inspections")
def create_inspection():
    uid, role = auth()
    body = body_json()
    est_id = v_str(body, "establishment_id")
    items = _validate_items(body)
    require_roles(role, ["Inspector"])
    get_or_404("establishments", est_id)
    current = now()
    score, passed = inspection_score(items)
    insp = {
        "id": str(uuid.uuid4()),
        "establishment_id": est_id,
        "items": items,
        "inspector_user_id": uid,
        "score": score,
        "passed": passed,
        "created_at": current,
        "_seq": next_seq(),
    }
    STORE["inspections"][insp["id"]] = insp
    if not passed:
        severity = highest_severity(items)
        violation = {
            "id": str(uuid.uuid4()),
            "establishment_id": est_id,
            "inspection_id": insp["id"],
            "severity": severity,
            "status": "NOTICED",
            "cure_deadline": current + timedelta(days=CURE_DAYS[severity]),
            "fine_cents": 0,
            "recorded_by_user_id": uid,
            "escalated_at": None,
            "resolved_at": None,
            "dismissed_at": None,
            "dismissed_by_user_id": None,
            "created_at": current,
            "updated_at": current,
            "version": 1,
            "_seq": next_seq(),
        }
        STORE["violations"][violation["id"]] = violation
        touch_establishment(STORE["establishments"][est_id], current, bump=False)
    return success(ser_inspection(insp), 201)


@bp.get("/inspections")
def list_inspections():
    uid, role = auth()
    require_roles(role, READERS)
    est_filter = request.args.get("establishment_id")
    items = list(STORE["inspections"].values())
    if est_filter is not None:
        items = [i for i in items if i["establishment_id"] == est_filter]
    page, meta = paginate(by_creation(items))
    return success([ser_inspection(i) for i in page], 200, "array", meta)


@bp.get("/inspections/<iid>")
def get_inspection(iid):
    uid, role = auth()
    require_roles(role, READERS)
    insp = get_or_404("inspections", iid)
    return success(ser_inspection(insp))
