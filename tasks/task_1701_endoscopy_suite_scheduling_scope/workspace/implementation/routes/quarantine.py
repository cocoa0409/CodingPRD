"""QuarantineCase read endpoints and the computed exposure read (PRD 3.7)."""
from flask import Blueprint, request

from db import db
from errors import ERR_QUARANTINE_CASE_NOT_FOUND
from middleware import authorized, ALL_READ_ROLES
from response import success_list
from routes.helpers import get_one, get_pagination, list_response
from services.core import public, sort_key
from validate import require_path_resource

bp = Blueprint("quarantine_cases", __name__)


@bp.get("/endoscopy/quarantine-cases")
def list_quarantine_cases():
    return list_response("quarantine_cases", {
        "scope_id": request.args.get("scope_id"),
        "status": request.args.get("status"),
        "triggering_culture_id": request.args.get("triggering_culture_id"),
        "reculture_cycle_id": request.args.get("reculture_cycle_id"),
    })


@bp.get("/endoscopy/quarantine-cases/<rid>")
def get_quarantine_case(rid):
    return get_one("quarantine_cases", rid, ERR_QUARANTINE_CASE_NOT_FOUND)


@bp.get("/endoscopy/quarantine-cases/<rid>/exposures")
def get_quarantine_exposures(rid):
    """Computed read: the ScopeUsage rows inside the case's exposure window,
    under the same left-exclusive, right-inclusive rule as the cascade."""
    authorized(ALL_READ_ROLES)
    case = require_path_resource("quarantine_cases", rid, ERR_QUARANTINE_CASE_NOT_FOUND)
    from routes.cultures import exposures_in_window
    usages = exposures_in_window(
        case["scope_id"], case["exposure_window_start"], case["exposure_window_end"])
    usages.sort(key=sort_key)
    total = len(usages)
    limit, offset = get_pagination()
    page = usages[offset:offset + limit]
    return success_list([public(u) for u in page], total, limit, offset)
