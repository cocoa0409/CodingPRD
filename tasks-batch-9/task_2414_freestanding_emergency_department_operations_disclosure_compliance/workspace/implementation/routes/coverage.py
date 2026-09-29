"""Physician coverage blocks and volume forecasts."""

from decimal import Decimal

from flask import Blueprint

import constants as C
from db import base_row, db, touch
from domain import (
    compute_required_coverage,
    forecast_view,
    get_facility,
    get_forecast,
    get_shift,
    refresh_coverage_flag,
    rows_of,
    shift_view,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    req_bool,
    req_date,
    req_datetime,
    req_enum,
    req_int,
    req_int_array,
    req_str,
    rh2,
)

bp = Blueprint("coverage", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@bp.post("/facilities/<fid>/physician-shifts")
def create_shift(fid):
    auth("FacilityAdministrator")
    data = body()
    clinician_user_id = req_str(data, "clinician_user_id", 1, 64)
    role_type = req_enum(data, "role_type", C.ROLE_TYPES)
    board_certified = req_bool(data, "board_certified")
    start_utc = req_datetime(data, "start_utc")
    end_utc = req_datetime(data, "end_utc")
    if end_utc <= start_utc:
        raise ApiError("ERR_INVALID_REQUEST", "end_utc must be strictly later than start_utc")

    facility = get_facility(fid)

    facility_shifts = [s for s in db.shifts.values() if s["facility_id"] == facility["id"]]

    for existing in facility_shifts:
        if existing["clinician_user_id"] != clinician_user_id:
            continue
        if _overlaps(start_utc, end_utc, existing["start_utc"], existing["end_utc"]):
            raise ApiError("ERR_CLINICIAN_DOUBLE_BOOKED")

    if role_type == "PHYSICIAN":
        physician_shifts = [
            s
            for s in facility_shifts
            if s["role_type"] == "PHYSICIAN"
            and _overlaps(start_utc, end_utc, s["start_utc"], s["end_utc"])
        ]
        instants = {start_utc}
        for existing in physician_shifts:
            if start_utc < existing["start_utc"] < end_utc:
                instants.add(existing["start_utc"])
        for instant in instants:
            concurrent = 1 + sum(
                1
                for s in physician_shifts
                if s["start_utc"] <= instant < s["end_utc"]
            )
            if concurrent > facility["max_concurrent_physicians"]:
                raise ApiError("ERR_COVERAGE_CAPACITY_EXCEEDED")

    seconds = int((end_utc - start_utc).total_seconds())
    shift = base_row()
    shift.update(
        {
            "facility_id": facility["id"],
            "clinician_user_id": clinician_user_id,
            "role_type": role_type,
            "board_certified": board_certified,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "duration_hours": rh2(Decimal(seconds) / Decimal(3600)),
        }
    )
    db.shifts[shift["id"]] = shift

    refresh_coverage_flag(facility)
    touch(facility)
    return created(shift_view(shift))


@bp.get("/facilities/<fid>/physician-shifts")
def list_shifts(fid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    role_type = query_enum("role_type", C.ROLE_TYPES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.shifts, facility_id=facility["id"])
    if role_type is not None:
        rows = [r for r in rows if r["role_type"] == role_type]
    page = paginate(rows, limit, offset)
    return ok_list([shift_view(r) for r in page], limit, offset, len(rows))


@bp.get("/physician-shifts/<sid>")
def read_shift(sid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    return ok(shift_view(get_shift(sid)))


@bp.post("/facilities/<fid>/volume-forecasts")
def create_forecast(fid):
    auth("FacilityAdministrator")
    data = body()
    period_start_date = req_date(data, "period_start_date")
    period_days = req_int(data, "period_days", minimum=1, maximum=90)
    volumes = req_int_array(data, "historical_daily_volumes", minimum=0, max_items=60)
    method = req_enum(data, "method", C.FORECAST_METHODS)

    facility = get_facility(fid)

    forecast = base_row()
    forecast.update(
        {
            "facility_id": facility["id"],
            "period_start_date": period_start_date,
            "period_days": period_days,
            "historical_daily_volumes": list(volumes),
            "method": method,
            "forecast_basis": "HISTORY",
            "forecast_daily_volume": None,
            "required_physician_hours_per_day": None,
            "required_physician_hours_total": None,
            "required_board_certified_hours_total": None,
            "escalated_by_posture": False,
            "status": "ACTIVE",
        }
    )
    compute_required_coverage(forecast)

    for other in list(db.forecasts.values()):
        if other["facility_id"] == facility["id"] and other["status"] == "ACTIVE":
            other["status"] = "SUPERSEDED"
            touch(other)

    db.forecasts[forecast["id"]] = forecast

    refresh_coverage_flag(facility)
    touch(facility)
    return created(forecast_view(forecast))


@bp.get("/facilities/<fid>/volume-forecasts")
def list_forecasts(fid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    status = query_enum("status", C.FORECAST_STATUSES)
    limit, offset = pagination()
    facility = get_facility(fid)
    rows = rows_of(db.forecasts, facility_id=facility["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return ok_list([forecast_view(r) for r in page], limit, offset, len(rows))


@bp.get("/volume-forecasts/<vid>")
def read_forecast(vid):
    auth("FacilityAdministrator", "ComplianceOfficer")
    return ok(forecast_view(get_forecast(vid)))
