"""AcuitySnapshot endpoints: submission enters SUBMITTED directly, supersedes
the prior snapshot for the slot, and runs the shift recompute cascade."""

from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_UNIT_NOT_FOUND,
    ERR_SNAPSHOT_NOT_FOUND,
    ERR_MATRIX_RULE_MISSING,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services.core import (
    SHIFT_CODES,
    matrix_complete,
    required_nurses_from_acuity,
    supersede_cascade,
    pub,
)
from util import (
    get_json_body,
    req_iso_date,
    req_enum,
    req_int,
    parse_pagination,
    paginate,
    apply_filters,
)

bp = Blueprint("acuity_snapshots", __name__)


def _req_census(body: dict, name: str) -> int:
    v = req_int(body, name)
    if v < 0:
        raise_err(ERR_INVALID_REQUEST, f"{name} must be >= 0")
    return v


@bp.post("/acuity-snapshots")
@require_roles("ChargeNurse")
def create_acuity_snapshot(_user_id: str, _role: str):
    body = get_json_body()

    # Body FK: presence, then existence (ERR_UNIT_NOT_FOUND).
    if "unit_id" not in body or body["unit_id"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: unit_id")
    unit_id = body["unit_id"]
    if not isinstance(unit_id, str) or unit_id == "":
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "Unit not found")

    shift_date = req_iso_date(body, "shift_date").isoformat()
    shift_code = req_enum(body, "shift_code", SHIFT_CODES)
    census_low = _req_census(body, "census_low")
    census_moderate = _req_census(body, "census_moderate")
    census_high = _req_census(body, "census_high")
    census_critical = _req_census(body, "census_critical")

    # Referential prerequisite: all four matrix rules for the unit type.
    if not matrix_complete(unit["unit_type"]):
        raise_err(ERR_MATRIX_RULE_MISSING,
                  "Not all four acuity-level matrix rules exist for the unit's unit_type")

    census = {
        "census_low": census_low,
        "census_moderate": census_moderate,
        "census_high": census_high,
        "census_critical": census_critical,
    }
    total_census = census_low + census_moderate + census_high + census_critical
    required = required_nurses_from_acuity(unit["unit_type"], census)

    # Supersede the prior SUBMITTED snapshot for the slot, if any.
    prior = None
    for s in db.snapshots.values():
        if (
            s["unit_id"] == unit_id
            and s["shift_date"] == shift_date
            and s["shift_code"] == shift_code
            and s["status"] == "SUBMITTED"
        ):
            prior = s
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    snapshot = {
        "unit_id": unit_id,
        "shift_date": shift_date,
        "shift_code": shift_code,
        **census,
        "total_census": total_census,
        "required_nurses": required,
        "status": "SUBMITTED",
    }
    db.stamp_new(snapshot)
    db.snapshots[snapshot["id"]] = snapshot

    # Cascade into the matching shift (recompute, posture, auto float).
    supersede_cascade(snapshot)

    return success_object(pub(snapshot), 201)


@bp.get("/acuity-snapshots")
@require_roles(*ALL_ROLES)
def list_acuity_snapshots(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sorted(db.snapshots.values(), key=lambda s: s["created_at"])
    items = apply_filters(items, {
        "unit_id": request.args.get("unit_id"),
        "shift_date": request.args.get("shift_date"),
        "shift_code": request.args.get("shift_code"),
        "status": request.args.get("status"),
    })
    page, total = paginate(items, limit, offset)
    return success_list([pub(s) for s in page], limit, offset, total)


@bp.get("/acuity-snapshots/<snapshotId>")
@require_roles(*ALL_ROLES)
def get_acuity_snapshot(snapshotId: str, _user_id: str, _role: str):
    snapshot = db.snapshots.get(snapshotId)
    if snapshot is None:
        raise_err(ERR_SNAPSHOT_NOT_FOUND, "Acuity snapshot not found")
    return success_object(pub(snapshot))
