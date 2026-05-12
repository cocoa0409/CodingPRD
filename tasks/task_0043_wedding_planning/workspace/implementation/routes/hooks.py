"""Test/integration hooks: /_events/emit, /_clock/advance, /_sweep/run."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import success
from services.sweep import run_sweep


bp = Blueprint("hooks", __name__)


@bp.post("/_events/emit")
def emit_event():
    require_roles("Planner", "Auditor", "VendorRep", "Couple")
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    envelope_id = body.get("envelope_id")
    if kind == "ESIGN_COMPLETED" and envelope_id:
        db.esign_completed_envelope_ids.add(envelope_id)
    # PAYMENT_RECEIVED, IM_DELIVERED are informational here
    return success({}, status=202)


@bp.post("/_clock/advance")
def clock_advance():
    require_roles("Planner", "Auditor", "VendorRep", "Couple")
    body = request.get_json(silent=True) or {}
    to_ts = body.get("to_timestamp")
    if to_ts is not None:
        db.set_clock(int(to_ts))
    run_sweep()
    return success({})


@bp.post("/_sweep/run")
def sweep_run():
    require_roles("Planner", "Auditor", "VendorRep", "Couple")
    run_sweep()
    return success({})
