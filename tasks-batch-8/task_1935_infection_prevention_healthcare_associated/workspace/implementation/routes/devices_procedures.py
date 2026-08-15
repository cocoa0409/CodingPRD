"""DeviceEpisodes and SurgicalProcedures."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_DEVICE_EPISODE_NOT_ACTIVE,
    ERR_DEVICE_EPISODE_NOT_FOUND,
    ERR_DEVICE_EPISODE_OVERLAP,
    ERR_INVALID_REQUEST,
    ERR_PATIENT_NOT_ADMITTED,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROCEDURE_NOT_FOUND,
    ERR_PROCEDURE_OVERLAP,
    ERR_SUMMARY_LOCKED,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import new_entity, recompute_covering_summary, summary_locked, touch
from services.serializers import device_episode_view, procedure_view
from validate import body, opt_bool, pagination_args, req_dt, req_enum, req_int, req_string

bp = Blueprint("devices_procedures", __name__)

DEVICE_TYPES = {"CENTRAL_LINE", "URINARY_CATHETER", "VENTILATOR"}
WOUND_CLASSES = {"CLEAN", "CLEAN_CONTAMINATED", "CONTAMINATED", "DIRTY"}


@bp.post("/api/device-episodes")
def create_episode():
    require_roles(["UnitNurseManager"])
    b = body()
    for f in ("patient_id", "device_type", "placed_at"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    patient_id = b.get("patient_id")
    if not isinstance(patient_id, str) or not patient_id:
        raise_err(ERR_INVALID_REQUEST, "patient_id must be a string")
    device_type = req_enum(b, "device_type", DEVICE_TYPES)
    placed_at = req_dt(b, "placed_at")

    patient = db.patients.get(patient_id)
    if patient is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    if patient["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")

    # Half-open [placed_at, removed_at) overlap, same patient + device_type.
    # New episode is open-ended ([placed_at, +inf)); back-to-back placement
    # (new placed_at == existing removed_at) is allowed because the interval is half-open.
    for e in db.device_episodes.values():
        if e["patient_id"] == patient_id and e["device_type"] == device_type:
            ex_start = e["placed_at"]
            ex_end = e["removed_at"]  # None = open
            if ex_end is None or placed_at < ex_end:
                raise_err(ERR_DEVICE_EPISODE_OVERLAP, "device episode overlaps an existing episode")

    ep = new_entity({
        "patient_id": patient_id,
        "unit_id": patient["current_unit_id"],
        "device_type": device_type,
        "placed_at": placed_at,
        "removed_at": None,
        "status": "ACTIVE",
    })
    db.device_episodes[ep["id"]] = ep
    return success_object(device_episode_view(ep), 201)


@bp.get("/api/device-episodes")
def list_episodes():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    patient_id = request.args.get("patient_id")
    unit_id = request.args.get("unit_id")
    device_type = request.args.get("device_type")

    def _match(e):
        if patient_id is not None and e["patient_id"] != patient_id:
            return False
        if unit_id is not None and e["unit_id"] != unit_id:
            return False
        if device_type is not None and e["device_type"] != device_type:
            return False
        return True

    items = [e for e in db.device_episodes.values() if _match(e)]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([device_episode_view(e) for e in page], total, limit, offset)


@bp.get("/api/device-episodes/<eid>")
def get_episode(eid):
    require_roles(ALL_ROLES)
    e = db.device_episodes.get(eid)
    if e is None:
        raise_err(ERR_DEVICE_EPISODE_NOT_FOUND, "device episode id does not exist")
    return success_object(device_episode_view(e))


@bp.post("/api/device-episodes/<eid>/remove")
def remove_episode(eid):
    require_roles(["UnitNurseManager"])
    e = db.device_episodes.get(eid)
    if e is None:
        raise_err(ERR_DEVICE_EPISODE_NOT_FOUND, "device episode id does not exist")
    b = body()
    if "removed_at" not in b or b["removed_at"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: removed_at")
    removed_at = req_dt(b, "removed_at")
    if e["status"] != "ACTIVE":
        raise_err(ERR_DEVICE_EPISODE_NOT_ACTIVE, "remove requires episode status ACTIVE")
    if removed_at < e["placed_at"]:
        raise_err(ERR_INVALID_REQUEST, "removed_at must be >= placed_at")
    e["removed_at"] = removed_at
    e["status"] = "REMOVED"
    touch(e)
    return success_object(device_episode_view(e))


# ---------------------------------------------------------------------------
# Surgical procedures
# ---------------------------------------------------------------------------
@bp.post("/api/surgical-procedures")
def create_procedure():
    require_roles(["UnitNurseManager"])
    b = body()
    for f in ("patient_id", "procedure_code", "performed_at", "duration_minutes", "asa_score", "wound_class"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    patient_id = b.get("patient_id")
    if not isinstance(patient_id, str) or not patient_id:
        raise_err(ERR_INVALID_REQUEST, "patient_id must be a string")
    procedure_code = req_string(b, "procedure_code")
    performed_at = req_dt(b, "performed_at")
    duration_minutes = req_int(b, "duration_minutes", min_v=1)
    asa_score = req_int(b, "asa_score", min_v=1, max_v=5)
    wound_class = req_enum(b, "wound_class", WOUND_CLASSES)
    implant = opt_bool(b, "implant", default=False)

    patient = db.patients.get(patient_id)
    if patient is None:
        raise_err(ERR_PATIENT_NOT_FOUND, "patient id does not exist")
    if patient["status"] != "ADMITTED":
        raise_err(ERR_PATIENT_NOT_ADMITTED, "patient must be ADMITTED")

    unit_id = patient["current_unit_id"]

    # Covering summary lock (procedure's unit + month of performed_at)
    if summary_locked(unit_id, performed_at):
        raise_err(ERR_SUMMARY_LOCKED, "covering MonthlySummary is locked for this unit-month")

    # CLOSED interval overlap [performed_at, performed_at + duration]
    new_start = performed_at
    new_end = performed_at + timedelta(minutes=duration_minutes)
    for p in db.surgical_procedures.values():
        if p["patient_id"] == patient_id:
            ex_start = p["performed_at"]
            ex_end = p["performed_at"] + timedelta(minutes=p["duration_minutes"])
            if new_start <= ex_end and ex_start <= new_end:
                raise_err(ERR_PROCEDURE_OVERLAP, "procedure overlaps an existing procedure for this patient")

    proc = new_entity({
        "patient_id": patient_id,
        "unit_id": unit_id,
        "procedure_code": procedure_code,
        "performed_at": performed_at,
        "duration_minutes": duration_minutes,
        "asa_score": asa_score,
        "wound_class": wound_class,
        "implant": implant,
    })
    db.surgical_procedures[proc["id"]] = proc

    recompute_covering_summary(unit_id, performed_at)
    return success_object(procedure_view(proc), 201)


@bp.get("/api/surgical-procedures")
def list_procedures():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    patient_id = request.args.get("patient_id")
    unit_id = request.args.get("unit_id")

    def _match(p):
        if patient_id is not None and p["patient_id"] != patient_id:
            return False
        if unit_id is not None and p["unit_id"] != unit_id:
            return False
        return True

    items = [p for p in db.surgical_procedures.values() if _match(p)]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([procedure_view(p) for p in page], total, limit, offset)


@bp.get("/api/surgical-procedures/<pid>")
def get_procedure(pid):
    require_roles(ALL_ROLES)
    p = db.surgical_procedures.get(pid)
    if p is None:
        raise_err(ERR_PROCEDURE_NOT_FOUND, "surgical procedure id does not exist")
    return success_object(procedure_view(p))
