"""ReleaseDetectionRecord monthly records (PRD 3.6)."""
from flask import Blueprint

from authz import FACILITY_OWNER, READ_ROLES, check_facility_ownership, require_roles
from db import store
from errors import (
    duplicate_record, future_period, invalid_request, record_not_found,
    tank_not_in_service,
)
from respond import success
from routes.facilities import get_facility_or_404
from routes.tanks import get_tank_or_404
from serialize import ser_record
from store_ops import (
    check_closed, get_or_404, json_body, new_common_fields, new_id, paginate,
    qparam, req_field, req_period, req_str, sorted_by_creation,
)
from timeutil import current_period, parse_period

bp = Blueprint("release_detection_records", __name__)


@bp.route("/release-detection-records", methods=["POST"])
def create_record():
    uid, _ = require_roles([FACILITY_OWNER])
    data = json_body()
    check_closed(data, {"tank_system_id", "period_month", "readings_summary"})
    tank_system_id = req_str(data, "tank_system_id")
    period = req_period(data, "period_month")
    readings_summary = req_field(data, "readings_summary")
    if not isinstance(readings_summary, dict):
        raise invalid_request("Field readings_summary must be an object")

    tank = get_tank_or_404(tank_system_id)
    fac = get_facility_or_404(tank["facility_id"])
    check_facility_ownership(uid, fac)
    # Priority 10: uniqueness on (tank_system_id, period_month).
    if any(r["tank_system_id"] == tank_system_id and r["period_month"] == period
           for r in store.release_detection_records.values()):
        raise duplicate_record()
    # Priority 15: period must not be after the clock's current month; the tank
    # must be IN_SERVICE or TEMPORARILY_CLOSED.
    py, pm = parse_period(period)
    cy, cm = parse_period(current_period(store.clock))
    if (py, pm) > (cy, cm):
        raise future_period()
    if tank["status"] not in ("IN_SERVICE", "TEMPORARILY_CLOSED"):
        raise tank_not_in_service("Record creation requires tank status IN_SERVICE or TEMPORARILY_CLOSED")

    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "tank_system_id": tank_system_id,
        "period_month": period,
        "method": tank["release_detection_mode"],
        "readings_summary": readings_summary,
        "status": "RECORDED",
    }
    r.update(new_common_fields())
    store.release_detection_records[r["id"]] = r
    return success(ser_record(r), status=201)


@bp.route("/release-detection-records", methods=["GET"])
def list_records():
    require_roles(READ_ROLES)
    items = store.release_detection_records.values()
    for f in ("tank_system_id", "period_month", "status"):
        v = qparam(f)
        if v is not None:
            items = [r for r in items if r[f] == v]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_record(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/release-detection-records/<rec_id>", methods=["GET"])
def get_record(rec_id):
    require_roles(READ_ROLES)
    return success(ser_record(get_or_404(store.release_detection_records, rec_id,
                                         record_not_found)))
