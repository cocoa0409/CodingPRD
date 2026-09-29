"""The logical clock and the consent-lapse it drives (PRD §2.6)."""

from flask import Blueprint

from auth import authenticate
from db import store
from errors import ApiError
from response import object_response
from services.consent import expire_due_consent_records
from util import parse_dt
from validation import field, validate_body

bp = Blueprint("clock", __name__)

CLOCK_SPEC = {
    "to_iso8601": field("datetime"),
}


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate("LeagueDataOps")
    body = validate_body(CLOCK_SPEC)

    new_clock = parse_dt(body["to_iso8601"])
    if new_clock is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "to_iso8601 must be an ISO 8601 instant.")

    store.clock = new_clock
    store.clock_raw = body["to_iso8601"]

    # Advancing the clock is not inert: it is the mechanism by which consent
    # lapses, and each lapse runs the withdrawal cascade with CONSENT_EXPIRED.
    expired_count, suspended_count = expire_due_consent_records(
        new_clock, store.clock_raw)

    return object_response({
        "current_utc": store.clock_raw,
        "expired_consent_record_count": expired_count,
        "suspended_feed_session_count": suspended_count,
    })
