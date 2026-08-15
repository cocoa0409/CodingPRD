"""Escort registration, listing, suspension, reinstatement."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_ESCORT_NOT_FOUND,
    ERR_ESCORT_INVALID_STATE,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_escort
from services import calc, cascade
from util import body_json, req_string, require_field, is_int, new_id

bp = Blueprint("escorts", __name__)


def _get_escort_or_404(escort_id):
    escort = db.escorts.get(escort_id)
    if escort is None:
        raise_err(ERR_ESCORT_NOT_FOUND, f"Escort {escort_id} not found")
    return escort


@bp.post("/escorts")
def create_escort():
    require_roles("Dispatcher")
    data = body_json(request)
    name = req_string(data, "operator_name")
    codes = require_field(data, "certified_state_codes")
    if not isinstance(codes, list) or len(codes) < 1:
        raise_err(ERR_INVALID_REQUEST, "certified_state_codes must be a non-empty array")
    for c in codes:
        if not isinstance(c, str) or c not in calc.VALID_STATE_CODES:
            raise_err(ERR_INVALID_REQUEST,
                      "certified_state_codes entries must be one of TX, OK, KS, LA")
    has_pole = data.get("has_height_pole", False)
    if not isinstance(has_pole, bool):
        raise_err(ERR_INVALID_REQUEST, "has_height_pole must be a boolean")
    pole_max = data.get("height_pole_max_inches", 0)
    if not is_int(pole_max) or pole_max < 0:
        raise_err(ERR_INVALID_REQUEST, "height_pole_max_inches must be an integer >= 0")
    if has_pole and pole_max <= 0:
        raise_err(ERR_INVALID_REQUEST,
                  "height_pole_max_inches must be > 0 when has_height_pole is true")
    n = db.now()
    escort = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "operator_name": name,
        "certified_state_codes": list(codes),
        "has_height_pole": has_pole,
        "height_pole_max_inches": pole_max,
        "reliability_score": calc.RELIABILITY_INITIAL,
        "escort_status": "ACTIVE",
    }
    db.escorts[escort["id"]] = escort
    return success_object(ser_escort(escort), status=201)


@bp.get("/escorts")
def list_escorts():
    require_roles(*ALL_ROLES)
    state_code = request.args.get("state_code")
    escort_status = request.args.get("escort_status")
    rows = list(db.escorts.values())
    if state_code is not None:
        rows = [e for e in rows if state_code in e["certified_state_codes"]]
    if escort_status is not None:
        rows = [e for e in rows if e["escort_status"] == escort_status]
    rows.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return paginate(request, [ser_escort(e) for e in rows])


@bp.post("/escorts/<id>/suspend")
def suspend_escort(id):
    require_roles("SafetyManager")
    body_json(request)
    escort = _get_escort_or_404(id)
    if escort["escort_status"] != "ACTIVE":
        raise_err(ERR_ESCORT_INVALID_STATE, "Suspension requires the escort to be ACTIVE")
    cascade.suspend_escort_cascade(escort)
    return success_object(ser_escort(escort))


@bp.post("/escorts/<id>/reinstate")
def reinstate_escort(id):
    require_roles("SafetyManager")
    body_json(request)
    escort = _get_escort_or_404(id)
    if escort["escort_status"] != "SUSPENDED":
        raise_err(ERR_ESCORT_INVALID_STATE, "Reinstatement requires the escort to be SUSPENDED")
    escort["escort_status"] = "ACTIVE"
    mark(escort)
    return success_object(ser_escort(escort))
