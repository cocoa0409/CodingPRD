"""Clock advance endpoint with offer-timeout sweep.

Each call to /api/_clock/advance moves the logical clock forward by the
given number of seconds and then sweeps any OFFERED assignments older
than 60 seconds (per §3.6) into REJECTED, redispatching the order.
"""

from datetime import timedelta

from flask import Blueprint, request

import auth
import envelope
import state
import validators
from services import dispatch as dispatch_svc


bp = Blueprint("clock", __name__)


def _read_payload():
    try:
        return request.get_json(silent=True) or {}
    except Exception:
        return {}


def _sweep_offer_timeouts():
    """Sweep any OFFERED assignment older than 60 seconds → REJECTED."""
    threshold = state.now() - timedelta(seconds=60)
    # Snapshot the ids so we don't mutate while iterating.
    expired = [
        a for a in list(state.STORE.assignments.values())
        if a["status"] == "OFFERED" and a["offered_at"] <= threshold
    ]
    for a in expired:
        rider = state.STORE.riders.get(a["rider_id"])
        if rider is None:
            continue
        dispatch_svc.on_reject(a, rider, redispatch=True)


@bp.route("/api/_clock/advance", methods=["POST"])
def advance():
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "PlatformAdmin":
        return envelope.forbidden()
    payload = _read_payload()
    err = validators.require_body(payload)
    if err:
        return err
    if "seconds" not in payload or not validators.is_number(payload["seconds"]):
        return envelope.validation("seconds must be a number.")
    secs = float(payload["seconds"])
    if secs < 0:
        return envelope.validation("seconds must be non-negative.")
    with state.lock():
        state.advance_clock(secs)
        _sweep_offer_timeouts()
        return envelope.success({
            "offset_seconds": state.STORE.offset_seconds,
            "now": state.fmt_dt(state.now()),
        })
