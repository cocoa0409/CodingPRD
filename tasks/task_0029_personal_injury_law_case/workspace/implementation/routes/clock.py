"""System clock test-driving endpoints (PRD §2.10, §3.9)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_INVALID_REQUEST
from middleware import require_auth, get_json_body
from response import ok_object
from services.cascades import expire_pending_offers


bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    # Public — no X-User-Role required (per PRD §2.1). The validation table
    # lists PlatformAdmin but the PRD also exempts this endpoint from the
    # auth check; we accept missing role and any role for write.
    # However, the validation table priority-1 rule says applies_to:
    # "all except POST /clients/register and POST /_clock/set_current_utc".
    body = get_json_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or to_iso == "":
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing or malformed to_iso8601")
    try:
        db.parse_iso_dt(to_iso)
    except Exception:
        raise APIError(ERR_INVALID_REQUEST, 400, "to_iso8601 is not a valid ISO 8601 datetime")

    db.set_current_utc(to_iso)
    # Sweep PENDING settlement offers system-wide.
    expire_pending_offers()
    return ok_object(db.clock_state_view(), 200)


@bp.get("/_clock")
def get_clock():
    # Reader: PlatformAdmin, Paralegal, Attorney, ManagingPartner per PRD/Scaffold.
    # PRD §2.10 also says the public-reader is anonymous for "reading the system
    # clock"; the scaffold §1.7 lists PlatformAdmin+roles in shared_operations.
    # We honour the scaffold endpoint table here: require one of those four
    # roles (Anonymous not in this list).
    require_auth({"PlatformAdmin", "Paralegal", "Attorney", "ManagingPartner"})()
    return ok_object(db.clock_state_view(), 200)
