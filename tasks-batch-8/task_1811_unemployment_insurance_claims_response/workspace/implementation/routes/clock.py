"""Test-driving endpoints: logical clock control and agency adjudication ack."""
from flask import Blueprint

from db import STORE
from errors import err, ERR_INVALID_STATE
from middleware import require_roles
from response import success
from services.core import find_or_404, now, serialize, touch
from util import as_str, body_json, parse_dt, req

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = body_json()
    raw = as_str(req(body, "to_iso8601"), "to_iso8601")
    new_clock = parse_dt(raw)
    STORE.clock = new_clock
    STORE.clock_raw = raw
    return success({"current_utc": STORE.clock_raw})


@bp.post("/_events/claim_adjudication_ack")
def claim_adjudication_ack():
    """Simulate the state agency acknowledging a submitted response:
    RESPONSE_SUBMITTED | LATE_RESPONSE -> UNDER_ADJUDICATION."""
    require_roles("PlatformAdmin")
    body = body_json()
    claim_id = as_str(req(body, "claim_id"), "claim_id")
    claim = find_or_404(STORE.claims, claim_id, "claim")
    if claim["status"] not in ("RESPONSE_SUBMITTED", "LATE_RESPONSE"):
        raise err(ERR_INVALID_STATE, 409, "claim is not awaiting adjudication acknowledgment")
    was_late = claim["status"] == "LATE_RESPONSE"
    claim["status"] = "UNDER_ADJUDICATION"
    touch(claim)
    if was_late:
        # Late response flagged on the adjudication record; the employer loses
        # the timely-protest presumption on reason coding.
        claim["late_flagged"] = True
        sep = STORE.separations.get(claim["separation_id"])
        if sep is not None and sep["reason_coding_confidence"] == "CONFIRMED":
            sep["reason_coding_confidence"] = "DISPUTED"
            touch(sep)
    return success(serialize(claim))
