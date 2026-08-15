"""Shelf-life studies, texture pulls, projection, and the logical clock."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
from db import STORES, base_record, touch, CLOCK, fmt_dt
from errors import (
    not_found, invalid_request, invalid_state, terminal_locked, unprocessable,
    ERR_STUDY_NOT_FOUND, ERR_REVISION_NOT_FOUND,
    ERR_REVISION_NOT_APPROVED, ERR_FORMULA_ARCHIVED,
    ERR_CHAMBER_POSITION_OCCUPIED, ERR_PULL_WINDOW_MISSED,
)
from middleware import require_roles
from response import ok_object, list_response
from services import calc
from services import inventory as inv
from util import D, get_body, require, opt, check_str, check_int, check_number, parse_dt

bp = Blueprint("studies", __name__)

STUDY_READ = ("PlantAdmin", "FormulationScientist", "QualityManager",
              "LabTechnician")
PULL_READ = ("PlantAdmin", "QualityManager", "LabTechnician")


def _sorted(name):
    return sorted(STORES[name].values(), key=lambda r: r["_seq"])


def _get_study(sid):
    rec = STORES["studies"].get(sid)
    if rec is None:
        raise not_found(ERR_STUDY_NOT_FOUND, f"Shelf-life study {sid} does not exist")
    return rec


@bp.post("/mfg/shelf-life-studies")
def create_study():
    require_roles("LabTechnician")
    body = get_body(request)
    # Stage 5 body FK
    revision = None
    rid = body.get("revision_id")
    if isinstance(rid, str):
        revision = STORES["revisions"].get(rid)
        if revision is None:
            raise not_found(ERR_REVISION_NOT_FOUND,
                            f"Revision {rid} does not exist")
    # Stage 6 shape
    if revision is None:
        raise invalid_request("Missing required field 'revision_id'")
    chamber_id = check_str(require(body, "chamber_id"), "chamber_id")
    shelf_position = check_str(require(body, "shelf_position"), "shelf_position")
    start_dt = parse_dt(require(body, "start_utc"), "start_utc")
    expiry_dt = parse_dt(require(body, "expiry_utc"), "expiry_utc")
    if not expiry_dt > start_dt:
        raise invalid_request("Field 'expiry_utc' must be later than 'start_utc'")
    limit = check_number(require(body, "hardness_limit_n"), "hardness_limit_n", gt=0)
    interval = check_int(opt(body, "pull_interval_days", 7), "pull_interval_days",
                         min_v=1)
    # Business rules in PRD order: APPROVED revision, ACTIVE formula, capacity
    if revision["status"] != "APPROVED":
        raise unprocessable(ERR_REVISION_NOT_APPROVED,
                            "Shelf-life studies require an APPROVED revision")
    formula = STORES["formulas"].get(revision["formula_id"])
    if formula is None or formula["status"] != "ACTIVE":
        raise unprocessable(ERR_FORMULA_ARCHIVED,
                            "Revision's formula is ARCHIVED")
    for other in STORES["studies"].values():
        if other["status"] != "ACTIVE":
            continue
        if other["chamber_id"] != chamber_id \
                or other["shelf_position"] != shelf_position:
            continue
        # CLOSED intervals: start == other's expiry counts as overlap
        if start_dt <= other["expiry_utc_dt"] and other["start_utc_dt"] <= expiry_dt:
            raise unprocessable(
                ERR_CHAMBER_POSITION_OCCUPIED,
                "Another ACTIVE study occupies this chamber position", 409)
    rec = base_record()
    rec.update({
        "revision_id": revision["id"],
        "chamber_id": chamber_id,
        "shelf_position": shelf_position,
        "start_utc_dt": start_dt,
        "expiry_utc_dt": expiry_dt,
        "hardness_limit_n": limit,
        "pull_interval_days": interval,
        "projected_hardness_at_expiry_n": None,
        "status": "ACTIVE",
    })
    STORES["studies"][rec["id"]] = rec
    return ok_object(serialize.study(rec), 201)


@bp.get("/mfg/shelf-life-studies/<sid>")
def get_study(sid):
    require_roles(*STUDY_READ)
    return ok_object(serialize.study(_get_study(sid)))


@bp.post("/mfg/shelf-life-studies/<sid>/terminate")
def terminate_study(sid):
    require_roles("LabTechnician")
    rec = _get_study(sid)
    if rec["status"] in ("COMPLETED", "FAILED", "TERMINATED"):
        raise terminal_locked(f"Study is {rec['status']} (terminal)")
    rec["status"] = "TERMINATED"
    touch(rec)
    return ok_object(serialize.study(rec))


@bp.post("/mfg/shelf-life-studies/<sid>/pulls")
def record_pull(sid):
    require_roles("LabTechnician")
    study = _get_study(sid)
    body = get_body(request)
    hardness = check_number(require(body, "hardness_n"), "hardness_n", gt=0)
    recorded_dt = parse_dt(require(body, "recorded_utc"), "recorded_utc")
    if study["status"] in ("COMPLETED", "FAILED", "TERMINATED"):
        raise terminal_locked(f"Study is {study['status']} (terminal)")
    # Elapsed grace windows materialize MISSED pulls at each record attempt
    inv.materialize_missed_pulls(study)
    index = inv.next_pull_index(study)
    due_dt = inv.pull_due_utc(study, index)
    if recorded_dt > CLOCK.current or recorded_dt > due_dt + timedelta(days=2):
        raise unprocessable(
            ERR_PULL_WINDOW_MISSED,
            "recorded_utc lies outside the pull window (future or past grace)")
    rec = base_record()
    rec.update({
        "study_id": study["id"],
        "pull_index": index,
        "due_utc_dt": due_dt,
        "recorded_utc_dt": recorded_dt,
        "hardness_n": hardness,
        "status": "RECORDED",
    })
    STORES["pulls"][rec["id"]] = rec
    # Recompute the projection; STRICT failure boundary (> limit fails)
    projected, _used = calc.hardness_projection(study)
    study["projected_hardness_at_expiry_n"] = projected
    if projected is not None and projected > D(study["hardness_limit_n"]):
        study["status"] = "FAILED"
    touch(study)
    return ok_object(serialize.pull(rec), 201)


@bp.get("/mfg/shelf-life-studies/<sid>/pulls")
def list_pulls(sid):
    require_roles(*PULL_READ)
    _get_study(sid)
    items = [p for p in _sorted("pulls") if p["study_id"] == sid]
    return list_response([serialize.pull(p) for p in items])


@bp.get("/mfg/shelf-life-studies/<sid>/projection")
def get_projection(sid):
    require_roles(*PULL_READ)
    study = _get_study(sid)
    projected, used = calc.hardness_projection(study)
    will_fail = projected is not None and projected > D(study["hardness_limit_n"])
    return ok_object({
        "projected_hardness_at_expiry_n":
            float(projected) if projected is not None else None,
        "pulls_used": used,
        "will_fail": will_fail,
    })


@bp.post("/mfg/_clock/set_current_utc")
def set_clock():
    require_roles("PlantAdmin")
    body = get_body(request)
    target = parse_dt(require(body, "to_iso8601"), "to_iso8601")
    CLOCK.set(target)
    inv.evaluate_clock_transitions()
    return ok_object({"current_utc": fmt_dt(CLOCK.current)})
