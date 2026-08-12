"""AvailabilitySnapshot list/read routes and logical clock endpoint."""
from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid_temporal
from middleware import require_roles
from response import ok_object, ok_list, parse_pagination
from services import sweeps
from services.serializers import snapshot_out

bp = Blueprint("availability", __name__)


@bp.get("/licensing/availability-snapshots")
def list_snapshots():
    require_roles("RightsAdmin", "LicensingOfficer")
    limit, offset = parse_pagination(request.args)
    title_id = request.args.get("title_id")
    territory_code = request.args.get("territory_code")
    available_raw = request.args.get("available")
    items = list(db.availability_snapshots.values())
    if title_id is not None:
        items = [s for s in items if s["title_id"] == title_id]
    if territory_code is not None:
        items = [s for s in items if s["territory_code"] == territory_code]
    if available_raw is not None:
        if available_raw.lower() == "true":
            av = True
        elif available_raw.lower() == "false":
            av = False
        else:
            from errors import err_invalid_request
            raise err_invalid_request("available must be true or false")
        items = [s for s in items if s["available"] == av]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([snapshot_out(s) for s in page], limit, offset, total)


@bp.get("/licensing/availability-snapshots/<snapshot_id>")
def get_snapshot(snapshot_id):
    require_roles("RightsAdmin", "LicensingOfficer", "Applicant")
    s = db.availability_snapshots.get(snapshot_id)
    if not s:
        raise err_not_found("AvailabilitySnapshot not found")
    return ok_object(snapshot_out(s))


@bp.post("/licensing/_clock/set_current_utc")
def set_clock():
    require_roles("RightsAdmin")
    body = request.get_json(silent=True) or {}
    raw = body.get("to_iso8601")
    ts = db.parse_ts(raw) if raw is not None else None
    if ts is None:
        raise err_invalid_temporal("to_iso8601 must be a valid ISO8601 UTC datetime")
    db.set_clock(ts)
    sweeps.run_sweeps()
    return ok_object({"current_utc": db.fmt_ts(db.clock_now())})
