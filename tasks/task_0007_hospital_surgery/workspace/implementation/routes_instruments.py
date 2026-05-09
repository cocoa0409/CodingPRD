from flask import Blueprint, request

from audit import write_audit  # noqa: F401  used by apply_lazy_expiry indirectly
from calc import STERILIZATION_EXPIRY_MINUTES
from db import db
from errors import (
    raise_error,
    ERR_INSTRUMENT_SET_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from middleware import auth_required
from response import success, paginate
from serialize import serialize_instrument
from utils import get_json_body, require_str, get_pagination, check_version

SPECIALTIES = {"GENERAL", "CARDIAC", "NEURO", "OBSTETRIC"}

bp = Blueprint("instruments", __name__)


def apply_lazy_expiry(s: dict) -> bool:
    """Returns True if state was changed."""
    if s["sterilization_status"] != "CLEAN_STERILIZED":
        return False
    last = s.get("last_sterilized_at_minute")
    if last is None:
        return False
    if (db.current_minute - last) >= STERILIZATION_EXPIRY_MINUTES:
        s["sterilization_status"] = "EXPIRED"
        db.stamp_update(s)
        write_audit("InstrumentSet", s["id"], "STERILIZATION_EXPIRED",
                    {"elapsed_minutes": db.current_minute - last})
        return True
    return False


@bp.route("/instrument-sets", methods=["POST"])
@auth_required("Scheduler")
def create_instrument_set():
    body = get_json_body()
    set_name = require_str(body, "set_name")
    specialty = require_str(body, "specialty")
    if specialty not in SPECIALTIES:
        raise_error(ERR_INVALID_REQUEST, f"specialty must be one of {sorted(SPECIALTIES)}")
    with db.lock:
        s = {
            "set_name": set_name,
            "specialty": specialty,
            "sterilization_status": "SOILED",
            "last_sterilized_at_minute": None,
            "current_case_id": None,
            "cycle_count": 0,
        }
        db.stamp_create(s)
        db.instrument_sets[s["id"]] = s
    return success(serialize_instrument(s), status_code=201)


@bp.route("/instrument-sets", methods=["GET"])
@auth_required("Any")
def list_instrument_sets():
    limit, offset = get_pagination()
    status_filter = request.args.get("sterilization_status")
    with db.lock:
        for s in db.instrument_sets.values():
            apply_lazy_expiry(s)
        items = sorted(db.instrument_sets.values(), key=lambda r: (r["created_at"], r["_seq"]))
        if status_filter:
            items = [r for r in items if r["sterilization_status"] == status_filter]
        sliced, pagination = paginate(items, limit, offset)
        data = [serialize_instrument(r) for r in sliced]
    return success(data, response_type="array", pagination=pagination)


@bp.route("/instrument-sets/<set_id>", methods=["GET"])
@auth_required("Any")
def get_instrument_set(set_id):
    with db.lock:
        s = db.instrument_sets.get(set_id)
        if s is None:
            raise_error(ERR_INSTRUMENT_SET_NOT_FOUND, f"InstrumentSet {set_id} not found")
        apply_lazy_expiry(s)
        return success(serialize_instrument(s))


@bp.route("/instrument-sets/<set_id>/start-sterilization", methods=["POST"])
@auth_required("Scheduler")
def start_sterilization(set_id):
    body = get_json_body()
    with db.lock:
        s = db.instrument_sets.get(set_id)
        if s is None:
            raise_error(ERR_INSTRUMENT_SET_NOT_FOUND, f"InstrumentSet {set_id} not found")
        apply_lazy_expiry(s)
        if s["sterilization_status"] not in {"SOILED", "EXPIRED"}:
            raise_error(ERR_INVALID_STATE,
                        f"start-sterilization requires SOILED or EXPIRED, got {s['sterilization_status']}")
        check_version(body, s)

        s["sterilization_status"] = "IN_STERILIZATION"
        db.stamp_update(s)
        write_audit("InstrumentSet", s["id"], "STERILIZATION_STARTED",
                    {"new_status": "IN_STERILIZATION"})
        return success(serialize_instrument(s))


@bp.route("/instrument-sets/<set_id>/complete-sterilization", methods=["POST"])
@auth_required("Scheduler")
def complete_sterilization(set_id):
    body = get_json_body()
    with db.lock:
        s = db.instrument_sets.get(set_id)
        if s is None:
            raise_error(ERR_INSTRUMENT_SET_NOT_FOUND, f"InstrumentSet {set_id} not found")
        if s["sterilization_status"] != "IN_STERILIZATION":
            raise_error(ERR_INVALID_STATE,
                        f"complete-sterilization requires IN_STERILIZATION, got {s['sterilization_status']}")
        check_version(body, s)

        s["sterilization_status"] = "CLEAN_STERILIZED"
        s["last_sterilized_at_minute"] = db.current_minute
        s["cycle_count"] = s.get("cycle_count", 0) + 1
        db.stamp_update(s)
        write_audit("InstrumentSet", s["id"], "STERILIZATION_COMPLETED",
                    {"new_status": "CLEAN_STERILIZED",
                     "last_sterilized_at_minute": s["last_sterilized_at_minute"],
                     "cycle_count": s["cycle_count"]})
        return success(serialize_instrument(s))
