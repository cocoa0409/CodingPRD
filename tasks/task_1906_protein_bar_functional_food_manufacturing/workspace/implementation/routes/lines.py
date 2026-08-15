"""Production lines, line slots, changeover events, and day availability."""
from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch, CLOCK
from errors import (
    not_found, invalid_request, invalid_state, terminal_locked, unprocessable,
    ERR_LINE_NOT_FOUND, ERR_SLOT_NOT_FOUND, ERR_CHANGEOVER_NOT_FOUND,
    ERR_SWAB_NOT_REQUIRED, ERR_SWAB_PPM_EXCEEDS_LIMIT, ERR_SOD_VIOLATION,
)
from middleware import require_roles
from response import ok_object, list_response
from services import calc
from util import (
    get_body, require, opt, check_str, check_number, check_enum, parse_date,
    D,
)

bp = Blueprint("lines", __name__)

LINE_READ = ("PlantAdmin", "FormulationScientist", "QualityManager",
             "ProductionPlanner", "LabTechnician")
SLOT_READ = ("PlantAdmin", "ProductionPlanner", "QualityManager")
CHANGEOVER_READ = ("PlantAdmin", "ProductionPlanner", "QualityManager",
                   "LabTechnician")

LINE_TYPES = ["SLAB_FORM_CUT"]
SLOT_STATUS = ["CONFIRMED", "COMPLETED", "RELEASED"]
CHANGEOVER_STATUS = ["PENDING", "CLEANING_LOGGED", "SWAB_RECORDED",
                     "VALIDATED", "FAILED", "CANCELLED"]


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_line(lid):
    rec = STORES["lines"].get(lid)
    if rec is None:
        raise not_found(ERR_LINE_NOT_FOUND, f"Production line {lid} does not exist")
    return rec


def _get_slot(sid):
    rec = STORES["slots"].get(sid)
    if rec is None:
        raise not_found(ERR_SLOT_NOT_FOUND, f"Line slot {sid} does not exist")
    return rec


def _get_changeover(cid):
    rec = STORES["changeovers"].get(cid)
    if rec is None:
        raise not_found(ERR_CHANGEOVER_NOT_FOUND,
                        f"Changeover event {cid} does not exist")
    return rec


# ---------------- lines ----------------

@bp.post("/mfg/lines")
def create_line():
    require_roles("PlantAdmin")
    body = get_body(request)
    name = check_str(require(body, "name"), "name")
    type_raw = opt(body, "line_type", "SLAB_FORM_CUT")
    check_str(type_raw, "line_type")
    capacity = check_number(require(body, "capacity_kg_per_hour"),
                            "capacity_kg_per_hour", gt=0)
    slab_weight = check_number(require(body, "slab_weight_kg"),
                               "slab_weight_kg", gt=0)
    line_type = check_enum(type_raw, "line_type", LINE_TYPES)
    rec = base_record()
    rec.update({
        "name": name,
        "line_type": line_type,
        "capacity_kg_per_hour": capacity,
        "slab_weight_kg": slab_weight,
        "current_allergen_profile": [],
        "last_wet_clean_utc_dt": None,
    })
    STORES["lines"][rec["id"]] = rec
    return ok_object(serialize.line(rec), 201)


@bp.get("/mfg/lines")
def list_lines():
    require_roles(*LINE_READ)
    return list_response([serialize.line(l) for l in _sorted("lines")])


@bp.get("/mfg/lines/<lid>")
def get_line(lid):
    require_roles(*LINE_READ)
    return ok_object(serialize.line(_get_line(lid)))


@bp.get("/mfg/lines/<lid>/slots")
def list_line_slots(lid):
    require_roles(*SLOT_READ)
    _get_line(lid)
    items = [s for s in _sorted("slots") if s["line_id"] == lid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", SLOT_STATUS)
        items = [s for s in items if s["status"] == st]
    return list_response([serialize.slot(s) for s in items])


@bp.get("/mfg/lines/<lid>/changeovers")
def list_line_changeovers(lid):
    require_roles(*CHANGEOVER_READ)
    _get_line(lid)
    items = [c for c in _sorted("changeovers") if c["line_id"] == lid]
    st = request.args.get("status")
    if st is not None:
        check_enum(st, "status", CHANGEOVER_STATUS)
        items = [c for c in items if c["status"] == st]
    return list_response([serialize.changeover(c) for c in items])


@bp.get("/mfg/lines/<lid>/day-availability")
def line_day_availability(lid):
    require_roles("PlantAdmin", "ProductionPlanner")
    line = _get_line(lid)
    raw = request.args.get("date")
    if raw is None:
        raise invalid_request("Missing required query parameter 'date'")
    day_start = parse_date(raw, "date")
    occupied, buffered, free = calc.day_availability(line, day_start)
    return ok_object({
        "date": raw,
        "occupied_minutes": occupied,
        "buffered_minutes": buffered,
        "free_minutes": free,
    })


# ---------------- slots ----------------

@bp.get("/mfg/slots/<sid>")
def get_slot(sid):
    require_roles(*SLOT_READ)
    return ok_object(serialize.slot(_get_slot(sid)))


# ---------------- changeovers ----------------

@bp.get("/mfg/changeovers/<cid>")
def get_changeover(cid):
    require_roles(*CHANGEOVER_READ)
    return ok_object(serialize.changeover(_get_changeover(cid)))


def _changeover_action(cid):
    rec = _get_changeover(cid)
    if rec["status"] == "CANCELLED":
        raise terminal_locked("Changeover event is CANCELLED (terminal)")
    return rec


@bp.post("/mfg/changeovers/<cid>/log-cleaning")
def log_cleaning(cid):
    require_roles("ProductionPlanner")
    rec = _changeover_action(cid)
    if rec["status"] not in ("PENDING", "FAILED"):
        raise invalid_state(
            f"Changeover in status {rec['status']} cannot be cleaning-logged")
    if rec["status"] == "FAILED":
        rec["swab_allergen_ppm"] = None
        rec["swab_recorded_by"] = None
    rec["status"] = "CLEANING_LOGGED"
    touch(rec)
    return ok_object(serialize.changeover(rec))


@bp.post("/mfg/changeovers/<cid>/record-swab")
def record_swab(cid):
    uid, _role = require_roles("LabTechnician")
    rec = _changeover_action(cid)
    if rec["status"] != "CLEANING_LOGGED":
        raise invalid_state(
            f"Changeover in status {rec['status']} cannot record a swab")
    if rec["required_level"] != "SWAB_VALIDATE":
        raise unprocessable(
            ERR_SWAB_NOT_REQUIRED,
            "record-swab requires required_level == SWAB_VALIDATE")
    body = get_body(request)
    ppm = check_number(require(body, "swab_allergen_ppm"), "swab_allergen_ppm",
                       gte=0)
    rec["swab_allergen_ppm"] = ppm
    rec["swab_recorded_by"] = uid
    rec["status"] = "SWAB_RECORDED"
    touch(rec)
    return ok_object(serialize.changeover(rec))


@bp.post("/mfg/changeovers/<cid>/validate")
def validate_changeover(cid):
    uid, _role = require_roles("QualityManager")
    rec = _changeover_action(cid)
    if rec["status"] == "CLEANING_LOGGED":
        if rec["required_level"] not in ("DRY_CLEAN", "WET_CLEAN"):
            raise invalid_state(
                "SWAB_VALIDATE changeovers must pass through SWAB_RECORDED")
    elif rec["status"] == "SWAB_RECORDED":
        if D(rec["swab_allergen_ppm"]) > calc.SWAB_LIMIT_PPM:
            raise unprocessable(
                ERR_SWAB_PPM_EXCEEDS_LIMIT,
                "Swab reading exceeds the 20 ppm limit")
        if uid == rec["swab_recorded_by"]:
            raise unprocessable(
                ERR_SOD_VIOLATION,
                "Validator must differ from the swab recorder")
    else:
        raise invalid_state(
            f"Changeover in status {rec['status']} cannot be validated")
    rec["status"] = "VALIDATED"
    rec["validated_by"] = uid
    if rec["required_level"] in ("WET_CLEAN", "SWAB_VALIDATE"):
        line = STORES["lines"].get(rec["line_id"])
        if line is not None:
            line["last_wet_clean_utc_dt"] = CLOCK.current
            touch(line)
    touch(rec)
    return ok_object(serialize.changeover(rec))


@bp.post("/mfg/changeovers/<cid>/fail")
def fail_changeover(cid):
    require_roles("QualityManager")
    rec = _changeover_action(cid)
    if rec["status"] != "SWAB_RECORDED":
        raise invalid_state(
            f"Changeover in status {rec['status']} cannot be failed")
    rec["status"] = "FAILED"
    touch(rec)
    return ok_object(serialize.changeover(rec))
