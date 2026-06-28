from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import db, common_create_fields
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.calc import LOAD_RISK, UNINSURED_RISK, DECAY, RISK_CEILING
from services.common import (
    get_body, require_fields, as_str, as_int, as_enum,
    get_technician, get_pagination, paginate, sorted_by_creation,
)

bp = Blueprint("technicians", __name__)

INSURANCE_VALUES = {"ACTIVE", "EXPIRED"}


@bp.post("/technicians")
def create_technician():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["full_name"])
    full_name = as_str(body["full_name"], "full_name")
    ladder = 1
    if "ladder_cert_max_stories" in body and body["ladder_cert_max_stories"] is not None:
        ladder = as_int(body["ladder_cert_max_stories"], "ladder_cert_max_stories", minimum=1)
    insurance = "ACTIVE"
    if "insurance_status" in body and body["insurance_status"] is not None:
        insurance = as_enum(body["insurance_status"], "insurance_status", INSURANCE_VALUES)
    t = common_create_fields()
    t.update({
        "full_name": full_name,
        "ladder_cert_max_stories": ladder,
        "insurance_status": insurance,
        "scheduled_minutes": 0,
    })
    db.technicians[t["id"]] = t
    return success(serialize.technician_view(t), 201)


@bp.get("/technicians")
def list_technicians():
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    insurance = request.args.get("insurance_status")
    limit, offset = get_pagination()
    items = [t for t in db.technicians.values()
             if insurance is None or t["insurance_status"] == insurance]
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.technician_view(t) for t in page], limit, offset, total)


@bp.get("/technicians/<tid>")
def get_one_technician(tid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    t = get_technician(tid)
    return success(serialize.technician_view(t), 200)


@bp.get("/technicians/<tid>/risk-score")
def risk_score(tid):
    _, role = get_identity()
    require_role(role, {"Dispatcher"})
    t = get_technician(tid)
    mode = request.args.get("mode", "projected")
    if mode not in ("projected", "chronological"):
        raise ApiError("ERR_INVALID_REQUEST", "mode must be projected or chronological")

    assignments = [a for a in db.crew_assignments.values() if a["technician_id"] == tid]

    if mode == "projected":
        committed = [a for a in assignments if a["status"] in ("RESERVED", "CONFIRMED")]
        value = Decimal(len(committed)) * Decimal(LOAD_RISK)
        if t["insurance_status"] == "EXPIRED":
            value += Decimal(UNINSURED_RISK)
    else:
        # chronological: only assignments whose linked visit is COMPLETED,
        # ordered by Visit.updated_at ASC then Visit.created_at ASC (never id).
        completed = []
        for a in assignments:
            v = db.visits.get(a["visit_id"])
            if v is not None and v["status"] == "COMPLETED":
                completed.append((v["updated_at"], v["created_at"], a))
        completed.sort(key=lambda x: (x[0], x[1]))
        value = Decimal(0)
        for k, (_, _, _a) in enumerate(completed):
            value += Decimal(LOAD_RISK) * (DECAY ** k)

    clamped = min(Decimal(RISK_CEILING), max(Decimal(0), value))
    score = int(clamped.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return success({"risk_score": score, "mode": mode}, 200)
