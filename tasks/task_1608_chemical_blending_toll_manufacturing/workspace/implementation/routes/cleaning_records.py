"""Cleaning record endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_cleaning_record,
    to_int,
    parse_iso,
)
from services.calculations import RESIDUE_LIMIT_PPM

bp = Blueprint("cleaning_records", __name__)

METHODS = {"SOLVENT_FLUSH", "CAUSTIC_CIP", "STEAM", "DRY_PURGE"}


def _tank_or_404(tid):
    t = db.tanks.get(tid)
    if t is None:
        raise errors.not_found("tank not found")
    return t


def _record_or_404(tank_id, record_id):
    r = db.cleaning_records.get(record_id)
    if r is None or r["tank_id"] != tank_id:
        raise errors.not_found("cleaning record not found")
    return r


@bp.route("/toll-operations/tanks/<id>/cleaning-records", methods=["POST"])
def create_cleaning_record(id):
    user_id, _role = require_role({"TankOperator"})
    tank = _tank_or_404(id)
    if tank["operational_state"] != "AVAILABLE":
        raise errors.invalid_state("tank not AVAILABLE")
    if tank["cleaning_state"] != "DIRTY":
        raise errors.invalid_state("tank not DIRTY")

    body = request.get_json(silent=True) or {}
    method = body.get("method")
    if method not in METHODS:
        raise errors.invalid_request("method invalid")
    started_at = body.get("started_at")
    completed_at = body.get("completed_at")
    if not started_at or not completed_at:
        raise errors.invalid_request("started_at and completed_at required")
    s_dt = parse_iso(started_at)
    c_dt = parse_iso(completed_at)
    if not (c_dt > s_dt):
        raise errors.invalid_request("completed_at must be > started_at")
    residue_ppm = to_int(body.get("residue_ppm"), "residue_ppm")
    if residue_ppm < 0:
        raise errors.invalid_request("residue_ppm must be >= 0")

    now = now_iso()
    rid = new_id()
    record = {
        "id": rid,
        "tank_id": id,
        "method": method,
        "started_at": started_at,
        "completed_at": completed_at,
        "residue_ppm": residue_ppm,
        "validated_by": None,
        "validation_outcome": "PENDING",
        "created_by": user_id,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.cleaning_records[rid] = record
    tank["cleaning_state"] = "CLEANING_IN_PROGRESS"
    tank["version"] += 1
    tank["updated_at"] = now
    return success_object(serialize_cleaning_record(record), status=201)


@bp.route("/toll-operations/tanks/<id>/cleaning-records", methods=["GET"])
def list_cleaning_records(id):
    require_role({"Any"})
    _tank_or_404(id)
    limit, offset = pagination_params()
    rows = [r for r in db.cleaning_records.values() if r["tank_id"] == id]
    rows = sort_by_created_at(rows)
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_cleaning_record(r) for r in slice_], limit, offset, total)


@bp.route("/toll-operations/tanks/<id>/cleaning-records/<recordId>", methods=["GET"])
def get_cleaning_record(id, recordId):
    require_role({"Any"})
    _tank_or_404(id)
    r = _record_or_404(id, recordId)
    return success_object(serialize_cleaning_record(r))


@bp.route("/toll-operations/tanks/<id>/cleaning-records/<recordId>/submit", methods=["POST"])
def submit_cleaning_record(id, recordId):
    require_role({"TankOperator"})
    tank = _tank_or_404(id)
    r = _record_or_404(id, recordId)
    if r["validation_outcome"] != "PENDING":
        raise errors.invalid_state("cleaning record not PENDING")
    if tank["cleaning_state"] != "CLEANING_IN_PROGRESS":
        raise errors.invalid_state("tank not CLEANING_IN_PROGRESS")
    now = now_iso()
    tank["cleaning_state"] = "CLEAN_PENDING_VALIDATION"
    tank["version"] += 1
    tank["updated_at"] = now
    return success_object(serialize_cleaning_record(r))


@bp.route("/toll-operations/tanks/<id>/cleaning-records/<recordId>/validate", methods=["POST"])
def validate_cleaning_record(id, recordId):
    user_id, _role = require_role({"QAValidator"})
    tank = _tank_or_404(id)
    r = _record_or_404(id, recordId)

    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in {"PASS", "FAIL"}:
        raise errors.invalid_request("decision must be PASS or FAIL")

    if r["validation_outcome"] != "PENDING":
        raise errors.invalid_state("cleaning record not PENDING")
    if tank["cleaning_state"] != "CLEAN_PENDING_VALIDATION":
        raise errors.invalid_state("tank not CLEAN_PENDING_VALIDATION")

    # Segregation of duties
    if user_id == r.get("created_by"):
        raise errors.ApiError(
            errors.ERR_SEGREGATION_OF_DUTIES,
            403,
            "validator must differ from record creator",
        )

    now = now_iso()
    if decision == "PASS":
        # Residue test only applies when last_product_ghs is non-null
        if tank.get("last_product_ghs") is not None:
            if r["residue_ppm"] > RESIDUE_LIMIT_PPM:
                # Per scaffold: PASS precondition includes residue limit.
                # If exceeded, we cannot PASS — treat as invalid request? PRD
                # says "a cleaning record reporting residue_ppm at or below that
                # limit may pass validation, while anything above it may not."
                # Surface as 422 invalid request.
                raise errors.invalid_request("residue_ppm exceeds limit; cannot PASS")
        r["validation_outcome"] = "PASSED"
        r["validated_by"] = user_id
        r["version"] += 1
        r["updated_at"] = now
        tank["cleaning_state"] = "CLEAN_VALIDATED"
        tank["last_product_ghs"] = None
        tank["version"] += 1
        tank["updated_at"] = now
    else:  # FAIL
        r["validation_outcome"] = "FAILED"
        r["version"] += 1
        r["updated_at"] = now
        tank["cleaning_state"] = "DIRTY"
        tank["version"] += 1
        tank["updated_at"] = now
    return success_object(serialize_cleaning_record(r))
