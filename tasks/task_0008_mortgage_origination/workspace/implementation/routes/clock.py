"""POST /_clock/set_current_utc — test-only clock advancement."""
from __future__ import annotations

from flask import Blueprint

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_auth
from services.common import get_json_body, require_str

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_auth(
    roles=[
        "LoanOfficer",
        "Underwriter",
        "Closer",
        "ComplianceOfficer",
        "Appraiser",
        "TitleAgent",
        "Applicant",
    ]
)
def set_current_utc():
    body = get_json_body()
    raw = require_str(body, "to_iso8601")
    try:
        dt = db.parse_ts(raw)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 UTC timestamp.")
    db.set_clock(dt)
    return response.ok({"current_utc": db.fmt_ts(dt)})
