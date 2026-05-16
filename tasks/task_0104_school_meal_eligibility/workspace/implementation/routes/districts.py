"""District endpoints. PRD §3.1."""

from flask import Blueprint, request

from core.auth import require_roles
from core.envelope import success_object
from core.store import STORE, stamp_common, lock
from core.validation import (
    require_body, require_field, parse_iso8601,
)

from services.relationships import get_district_or_404
from services.views import district_view


bp = Blueprint("districts", __name__)


@bp.post("/districts")
@require_roles("AuditOfficer")
def create_district():
    body = require_body(request)
    name = require_field(body, "name", kind="string")
    sys_str = require_field(body, "school_year_start", kind="string")
    sys_dt = parse_iso8601(sys_str, "school_year_start")
    # Store the timestamp in canonical ISO form (3-fractional digits) to match
    # the rest of the timestamps and the snapshot equality semantics used by
    # FrlApplication.school_year_start.
    from core.store import iso_from_dt
    sys_iso = iso_from_dt(sys_dt)
    with lock():
        d = {
            "name": name,
            "school_year_start": sys_iso,
        }
        stamp_common(d)
        STORE.districts[d["id"]] = d
        view = district_view(d)
    return success_object(view, status=201)


@bp.get("/districts/<district_id>")
@require_roles("Parent", "DistrictReviewer", "CafeteriaManager", "AuditOfficer")
def get_district(district_id):
    with lock():
        d = get_district_or_404(district_id)
        return success_object(district_view(d))
