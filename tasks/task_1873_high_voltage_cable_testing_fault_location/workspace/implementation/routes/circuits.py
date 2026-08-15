import uuid
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_CIRCUIT_REF
from helpers import (
    body_dict, req_str, req_int, req_enum, get_or_404, serialize, serialize_list,
    paginate,
)
from middleware import authenticate, ALL_ROLES
from response import success
from services import calc
from util import dec as dec_num

bp = Blueprint("circuits", __name__)


@bp.post("/cable-diagnostics/circuits")
def create_circuit():
    authenticate(["SystemAdmin"])
    body = body_dict()
    circuit_ref = req_str(body, "circuit_ref")
    voltage_class = req_enum(body, "voltage_class", calc.VOLTAGE_CLASSES)
    length_m = req_int(body, "length_m")
    if length_m <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "length_m must be > 0")
    installation_year = req_int(body, "installation_year")
    if not 1950 <= installation_year <= 2026:
        raise ApiError(ERR_INVALID_REQUEST, 400, "installation_year must be in 1950..2026")
    cvf = body.get("calibrated_velocity_factor")
    if cvf is not None:
        d = dec_num(cvf)
        if d is None or d < Decimal("0.45") or d > Decimal("0.60"):
            raise ApiError(
                ERR_INVALID_REQUEST, 400,
                "calibrated_velocity_factor must be null or between 0.45 and 0.60",
            )
    if any(c["circuit_ref"] == circuit_ref for c in db.circuits.values()):
        raise ApiError(ERR_DUPLICATE_CIRCUIT_REF, 409, "circuit_ref already registered")
    now = db.now()
    rec = {
        "id": str(uuid.uuid4()),
        "_seq": db.next_seq(),
        "circuit_ref": circuit_ref,
        "voltage_class": voltage_class,
        "length_m": length_m,
        "installation_year": installation_year,
        "calibrated_velocity_factor": cvf,
        "status": "IN_SERVICE",
        "unresolved_fault_count": 0,
        "resolved_fault_count_24m": 0,
        "current_health_index": None,
        "current_health_band": None,
        "replacement_recommended": False,
        "approved_outage_minutes_total": 0,
        "splice_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.circuits[rec["id"]] = rec
    return success(serialize(rec), code=201)


@bp.get("/cable-diagnostics/circuits/<cid>")
def get_circuit(cid):
    authenticate(ALL_ROLES)
    rec = get_or_404(db.circuits, cid, "CableCircuit")
    return success(serialize(rec))


@bp.get("/cable-diagnostics/circuits")
def list_circuits():
    authenticate(ALL_ROLES)
    recs = list(db.circuits.values())
    status = request.args.get("status")
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    vc = request.args.get("voltage_class")
    if vc is not None:
        recs = [r for r in recs if r["voltage_class"] == vc]
    rr = request.args.get("replacement_recommended")
    if rr is not None and rr.lower() in ("true", "false"):
        want = rr.lower() == "true"
        recs = [r for r in recs if r["replacement_recommended"] == want]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/circuits/<cid>/outage-windows")
def circuit_windows(cid):
    authenticate(ALL_ROLES)
    get_or_404(db.circuits, cid, "CableCircuit")
    recs = [w for w in db.windows.values() if w["circuit_id"] == cid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/circuits/<cid>/test-jobs")
def circuit_jobs(cid):
    authenticate(ALL_ROLES)
    get_or_404(db.circuits, cid, "CableCircuit")
    recs = [j for j in db.jobs.values() if j["circuit_id"] == cid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/circuits/<cid>/health-assessments")
def circuit_assessments(cid):
    authenticate(ALL_ROLES)
    get_or_404(db.circuits, cid, "CableCircuit")
    recs = [a for a in db.assessments.values() if a["circuit_id"] == cid]
    page, meta = paginate(recs)
    return success(serialize_list(page), response_type="array", pagination=meta)


@bp.get("/cable-diagnostics/circuits/<cid>/trend")
def circuit_trend(cid):
    authenticate(["NetworkPlanner", "AssetEngineer"])
    circuit = get_or_404(db.circuits, cid, "CableCircuit")
    adopted = [
        a for a in db.assessments.values()
        if a["circuit_id"] == cid and a["status"] == "ADOPTED"
    ]
    adopted.sort(key=lambda r: (r["created_at"], r["_seq"]))
    data = {
        "circuit_id": cid,
        "points": serialize_list(adopted),
        "replacement_recommended": circuit["replacement_recommended"],
    }
    return success(data)
