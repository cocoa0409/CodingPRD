"""The test-driving surface for the logical clock (PRD 2.5)."""
from flask import Blueprint

import clock
import response
import validate as V
from auth import require
from db import store
from services import compute as K

bp = Blueprint("clock_routes", __name__)


@bp.post("/_clock/set_current_utc")
@require("NetworkAdmin")
def set_current_utc():
    data = V.body()
    instant = V.req_datetime(data, "to_iso8601")
    clock.set_now(instant)
    # Posture is recomputed on every instrument; no version counter moves,
    # because the clock advance is not a write against any row.
    for monitor in store.monitors.values():
        K.refresh_qc_posture(monitor)
    return response.object_response({})
