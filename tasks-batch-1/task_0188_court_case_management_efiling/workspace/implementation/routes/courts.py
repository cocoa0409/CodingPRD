"""Court configuration and the system clock."""
from flask import Blueprint, request

import db
import errors
from middleware import get_actor, require_role
from response import success
from services import domain, validate
from services.calc import parse_dt

bp = Blueprint("courts", __name__)


@bp.post("/courts")
def create_court():
    _, role = get_actor()
    require_role(role, {"SystemAdmin"})
    data = validate.body(request)
    name = validate.require_str(data, "name")
    jurisdiction_code = validate.require_str(data, "jurisdiction_code")
    filing_fee_cents = validate.non_negative_int(data, "filing_fee_cents", required=True)
    business_days_only = validate.optional_bool(data, "business_days_only", default=True)
    holidays = data.get("holidays")
    if holidays is None:
        holidays = []
    if not isinstance(holidays, list) or not all(isinstance(h, str) for h in holidays):
        raise errors.err(errors.ERR_INVALID_REQUEST, "holidays must be an array of date strings")
    appeal_window_days = validate.non_negative_int(
        data, "appeal_window_days", required=False, default=30
    )

    rec = db.base_record()
    rec.update({
        "name": name,
        "jurisdiction_code": jurisdiction_code,
        "filing_fee_cents": filing_fee_cents,
        "business_days_only": business_days_only,
        "holidays": holidays,
        "appeal_window_days": appeal_window_days,
    })
    db.courts[rec["id"]] = rec
    return success(domain._clean(rec), status=201)


@bp.get("/courts/<court_id>")
def get_court(court_id):
    get_actor()
    rec = domain.get_or_404(db.courts, court_id)
    return success(domain._clean(rec), status=200)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_actor()
    require_role(role, {"SystemAdmin"})
    data = validate.body(request)
    validate.require(data, "to_iso8601")
    dt = parse_dt(data["to_iso8601"])
    if dt is None:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    db.set_clock(dt)
    current = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return success({"current_utc": current}, status=200)
