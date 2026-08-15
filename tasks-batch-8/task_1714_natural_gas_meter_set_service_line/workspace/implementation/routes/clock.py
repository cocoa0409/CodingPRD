"""Logical clock endpoint: POST /_clock/set_current_utc runs all sweeps atomically."""

import datetime as _dt

from flask import Blueprint

import db
from errors import ERR_INVALID_REQUEST, raise_error
from middleware import get_body, require_fields, require_roles
from response import success_object
from services.domain import expire_application_cascade, touch

bp = Blueprint("clock", __name__)

EXPIRY_SWEEP_GRACE_DAYS = 7


def _parse_instant(value):
    if not isinstance(value, str):
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 instant")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("SystemAdmin")
    body = get_body()
    require_fields(body, "to_iso8601")
    instant = _parse_instant(body["to_iso8601"])
    db.set_current_utc(instant)
    _run_sweeps()
    return success_object({"current_utc": db.format_ts(instant)})


def _run_sweeps():
    today = db.today_date()

    # --- Quote expiry: QUOTED app whose current date > quote_valid_until + 7-day grace ---
    for app in list(db.service_applications.values()):
        if app["status"] == "QUOTED" and app.get("quote_valid_until"):
            qvu = _dt.date.fromisoformat(app["quote_valid_until"])
            if today > qvu + _dt.timedelta(days=EXPIRY_SWEEP_GRACE_DAYS):
                expire_application_cascade(app)
                app["status"] = "EXPIRED"
                touch(app)

    # --- Permit expiry: APPROVED whose expires_at has passed ---
    for permit in list(db.permits.values()):
        if permit["status"] == "APPROVED" and permit.get("expires_at"):
            expires = _dt.date.fromisoformat(permit["expires_at"])
            if today > expires:
                permit["status"] = "EXPIRED"
                touch(permit)

    # --- Inspection expiry: SCHEDULED whose inspection_date has passed ---
    for inspection in list(db.inspections.values()):
        if inspection["status"] == "SCHEDULED":
            idate = _dt.date.fromisoformat(inspection["inspection_date"])
            if today > idate:
                inspection["status"] = "EXPIRED"
                touch(inspection)

    # --- Commitment sweep: ACCEPTED/AT_RISK past committed date while app not COMPLETED ---
    for commitment in list(db.timeline_commitments.values()):
        if commitment["status"] in ("ACCEPTED", "AT_RISK"):
            committed = _dt.date.fromisoformat(commitment["committed_completion_date"])
            app = db.service_applications.get(commitment["service_application_id"])
            if today > committed and (app is None or app["status"] != "COMPLETED"):
                was_accepted = commitment["status"] == "ACCEPTED"
                commitment["status"] = "MISSED"
                if was_accepted and not commitment.get("delay_attribution"):
                    commitment["delay_attribution"] = "UTILITY"
                touch(commitment)
