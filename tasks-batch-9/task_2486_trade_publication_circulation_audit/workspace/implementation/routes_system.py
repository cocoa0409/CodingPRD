"""The logical circulation clock (PRD 2.5)."""
from flask import Blueprint

import validation as V
from auth import OPERATOR_ROLES, endpoint
from envelope import ok
from errors import ApiError
from store import parse_dt, set_clock

system_bp = Blueprint("system", __name__)


@system_bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(*OPERATOR_ROLES)
def set_current_utc():
    payload = V.body()
    fields = V.parse(payload, [V.f_str("to_iso8601", max_len=64)])
    parsed = parse_dt(fields["to_iso8601"])
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "to_iso8601 must be an ISO 8601 UTC instant.")
    # Moving the clock is inert with respect to stored state: nothing is
    # mutated and no sweep is triggered.
    set_clock(parsed)
    return ok({})
