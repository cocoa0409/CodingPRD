"""DeviceDayCounts (+reconcile) and MonthlySummaries (NHSN submission cycle)."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ERR_DEVICE_DAY_COUNT_NOT_FOUND,
    ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS,
    ERR_DUPLICATE_DEVICE_DAY_COUNT,
    ERR_DUPLICATE_SUMMARY_MONTH,
    ERR_INVALID_REQUEST,
    ERR_MONTHLY_SUMMARY_NOT_FOUND,
    ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION,
    ERR_SEGREGATION_OF_DUTY,
    ERR_STALE_VERSION,
    ERR_SUMMARY_NOT_AMENDABLE,
    ERR_SUMMARY_NOT_REVIEWABLE,
    ERR_SUMMARY_NOT_SUBMITTABLE,
    ERR_SUMMARY_LOCKED,
    ERR_UNIT_NOT_FOUND,
    raise_err,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services.core import (
    MUTABLE_SUMMARY_STATUSES,
    find_covering_summary,
    new_entity,
    recompute_covering_summary,
    recompute_summary,
    summary_locked,
    touch,
)
from services.serializers import ddc_view, summary_view
from util import cal_date, midnight_utc, parse_dt
from validate import (
    body,
    pagination_args,
    req_int,
    req_month,
)

bp = Blueprint("denominators", __name__)


def _ddc_fields(b):
    for f in ("central_line_days", "urinary_catheter_days", "ventilator_days", "patient_days"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    cl = req_int(b, "central_line_days", min_v=0)
    uc = req_int(b, "urinary_catheter_days", min_v=0)
    vent = req_int(b, "ventilator_days", min_v=0)
    pat = req_int(b, "patient_days", min_v=0)
    return cl, uc, vent, pat


@bp.post("/api/device-day-counts")
def create_ddc():
    require_roles(["UnitNurseManager"])
    b = body()
    for f in ("unit_id", "count_date", "central_line_days", "urinary_catheter_days", "ventilator_days", "patient_days"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    raw_date = b.get("count_date")
    try:
        count_dt = parse_dt(raw_date, "count_date")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "count_date must be an ISO-8601 timestamp")
    cl, uc, vent, pat = _ddc_fields(b)

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    count_date = midnight_utc(cal_date(count_dt))

    # Covering summary lock
    if summary_locked(unit_id, count_date):
        raise_err(ERR_SUMMARY_LOCKED, "covering MonthlySummary is locked for this unit-month")

    # Uniqueness (unit_id, count_date)
    for r in db.device_day_counts.values():
        if r["unit_id"] == unit_id and r["count_date"] == count_date:
            raise_err(ERR_DUPLICATE_DEVICE_DAY_COUNT, "a DeviceDayCount row already exists for (unit_id, count_date)")

    # Intra-row: each device-day figure <= patient_days
    if cl > pat or uc > pat or vent > pat:
        raise_err(ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS, "device days exceed patient_days")

    row = new_entity({
        "unit_id": unit_id,
        "count_date": count_date,
        "central_line_days": cl,
        "urinary_catheter_days": uc,
        "ventilator_days": vent,
        "patient_days": pat,
        "status": "DRAFT",
    })
    db.device_day_counts[row["id"]] = row
    recompute_covering_summary(unit_id, count_date)
    return success_object(ddc_view(row), 201)


@bp.get("/api/device-day-counts")
def list_ddc():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    month = request.args.get("month")

    def _match(r):
        if unit_id is not None and r["unit_id"] != unit_id:
            return False
        if month is not None:
            d = cal_date(r["count_date"])
            if f"{d.year:04d}-{d.month:02d}" != month:
                return False
        return True

    items = [r for r in db.device_day_counts.values() if _match(r)]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ddc_view(r) for r in page], total, limit, offset)


# NOTE: /api/device-day-counts/reconcile must be registered BEFORE /api/device-day-counts/<did>
@bp.get("/api/device-day-counts/reconcile")
def reconcile_ddc():
    require_roles(ALL_ROLES)
    unit_id = request.args.get("unit_id")
    device_type = request.args.get("device_type")
    count_date_raw = request.args.get("count_date")
    if not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id query parameter is required")
    if device_type not in ("CENTRAL_LINE", "URINARY_CATHETER", "VENTILATOR"):
        raise_err(ERR_INVALID_REQUEST, "device_type must be CENTRAL_LINE | URINARY_CATHETER | VENTILATOR")
    if not count_date_raw:
        raise_err(ERR_INVALID_REQUEST, "count_date query parameter is required")
    try:
        count_dt = parse_dt(count_date_raw, "count_date")
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "count_date must be an ISO-8601 timestamp")

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    day_start = midnight_utc(cal_date(count_dt))
    day_end = day_start + timedelta(days=1)

    expected = 0
    for e in db.device_episodes.values():
        if e["unit_id"] == unit_id and e["device_type"] == device_type:
            if e["placed_at"] < day_end and (e["removed_at"] is None or e["removed_at"] >= day_start):
                expected += 1

    recorded = None
    delta = None
    matches = False
    for r in db.device_day_counts.values():
        if r["unit_id"] == unit_id and r["count_date"] == day_start:
            field = {
                "CENTRAL_LINE": "central_line_days",
                "URINARY_CATHETER": "urinary_catheter_days",
                "VENTILATOR": "ventilator_days",
            }[device_type]
            recorded = r[field]
            delta = recorded - expected
            matches = (recorded == expected)
            break

    return success_object({
        "expected_device_days": expected,
        "recorded_device_days": recorded,
        "delta": delta,
        "matches": matches,
    })


@bp.get("/api/device-day-counts/<did>")
def get_ddc(did):
    require_roles(ALL_ROLES)
    r = db.device_day_counts.get(did)
    if r is None:
        raise_err(ERR_DEVICE_DAY_COUNT_NOT_FOUND, "device day count id does not exist")
    return success_object(ddc_view(r))


@bp.put("/api/device-day-counts/<did>")
def update_ddc(did):
    require_roles(["UnitNurseManager"])
    b = body()
    cl, uc, vent, pat = _ddc_fields(b)
    if "expected_device_day_count_version" not in b or b["expected_device_day_count_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: expected_device_day_count_version")
    ev = b["expected_device_day_count_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise_err(ERR_INVALID_REQUEST, "expected_device_day_count_version must be an integer")

    r = db.device_day_counts.get(did)
    if r is None:
        raise_err(ERR_DEVICE_DAY_COUNT_NOT_FOUND, "device day count id does not exist")

    # Covering summary lock (a LOCKED row's covering summary is locked)
    if summary_locked(r["unit_id"], r["count_date"]):
        raise_err(ERR_SUMMARY_LOCKED, "covering MonthlySummary is locked for this unit-month")

    if ev != r["version"]:
        raise_err(ERR_STALE_VERSION, "expected_device_day_count_version does not match current version")

    if cl > pat or uc > pat or vent > pat:
        raise_err(ERR_DEVICE_DAYS_EXCEED_PATIENT_DAYS, "device days exceed patient_days")

    r["central_line_days"] = cl
    r["urinary_catheter_days"] = uc
    r["ventilator_days"] = vent
    r["patient_days"] = pat
    touch(r)
    recompute_covering_summary(r["unit_id"], r["count_date"])
    return success_object(ddc_view(r))


# ---------------------------------------------------------------------------
# Monthly summaries
# ---------------------------------------------------------------------------
@bp.post("/api/monthly-summaries")
def create_summary():
    require_roles(["InfectionPreventionist"])
    b = body()
    for f in ("unit_id", "month"):
        if f not in b or b[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")
    unit_id = b.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise_err(ERR_INVALID_REQUEST, "unit_id must be a string")
    month = req_month(b, "month")

    unit = db.units.get(unit_id)
    if unit is None:
        raise_err(ERR_UNIT_NOT_FOUND, "unit id does not exist")

    for s in db.monthly_summaries.values():
        if s["unit_id"] == unit_id and s["month"] == month:
            raise_err(ERR_DUPLICATE_SUMMARY_MONTH, "a MonthlySummary already exists for (unit_id, month)")

    summary = new_entity({
        "unit_id": unit_id,
        "month": month,
        "central_line_days": 0,
        "urinary_catheter_days": 0,
        "ventilator_days": 0,
        "patient_days_total": 0,
        "procedure_count": 0,
        "clabsi_count": 0,
        "cauti_count": 0,
        "ssi_count": 0,
        "provisional_clabsi_count": 0,
        "provisional_cauti_count": 0,
        "provisional_ssi_count": 0,
        "predicted_clabsi": None,
        "predicted_cauti": None,
        "predicted_ssi": None,
        "sir_clabsi": None,
        "sir_cauti": None,
        "sir_ssi": None,
        "provisional_sir_clabsi": None,
        "provisional_sir_cauti": None,
        "provisional_sir_ssi": None,
        "sir_flag": "NOT_CALCULATED",
        "status": "OPEN",
        "amendment_count": 0,
        "submitted_by_user_id": None,
        "accepted_by_user_id": None,
    })
    db.monthly_summaries[summary["id"]] = summary
    recompute_summary(summary)
    return success_object(summary_view(summary), 201)


@bp.get("/api/monthly-summaries")
def list_summaries():
    require_roles(ALL_ROLES)
    limit, offset = pagination_args()
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")

    def _match(s):
        if unit_id is not None and s["unit_id"] != unit_id:
            return False
        if status is not None and s["status"] != status:
            return False
        return True

    items = [s for s in db.monthly_summaries.values() if _match(s)]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([summary_view(s) for s in page], total, limit, offset)


@bp.get("/api/monthly-summaries/<sid>")
def get_summary(sid):
    require_roles(ALL_ROLES)
    s = db.monthly_summaries.get(sid)
    if s is None:
        raise_err(ERR_MONTHLY_SUMMARY_NOT_FOUND, "monthly summary id does not exist")
    return success_object(summary_view(s))


def _lock_denominators(summary):
    start_d, end_d = _summary_month_range(summary)
    for r in db.device_day_counts.values():
        if r["unit_id"] == summary["unit_id"] and start_d <= r["count_date"] < end_d:
            if r["status"] != "LOCKED":
                r["status"] = "LOCKED"
                touch(r)


def _unlock_denominators(summary):
    start_d, end_d = _summary_month_range(summary)
    for r in db.device_day_counts.values():
        if r["unit_id"] == summary["unit_id"] and start_d <= r["count_date"] < end_d:
            if r["status"] != "DRAFT":
                r["status"] = "DRAFT"
                touch(r)


def _summary_month_range(summary):
    from services.core import _month_bounds
    return _month_bounds(summary["month"])


@bp.post("/api/monthly-summaries/<sid>/submit")
def submit_summary(sid):
    user_id, _ = require_roles(["InfectionPreventionist"])
    s = db.monthly_summaries.get(sid)
    if s is None:
        raise_err(ERR_MONTHLY_SUMMARY_NOT_FOUND, "monthly summary id does not exist")
    if s["status"] not in ("OPEN", "REJECTED", "UNDER_AMENDMENT"):
        raise_err(ERR_SUMMARY_NOT_SUBMITTABLE, "submit requires status OPEN, REJECTED, or UNDER_AMENDMENT")
    unit = db.units[s["unit_id"]]
    if unit["surveillance_posture"] == "OUTBREAK":
        raise_err(ERR_OUTBREAK_POSTURE_BLOCKS_SUBMISSION, "unit surveillance_posture OUTBREAK blocks submission")
    s["status"] = "SUBMITTED"
    s["submitted_by_user_id"] = user_id
    touch(s)
    _lock_denominators(s)
    return success_object(summary_view(s))


@bp.post("/api/monthly-summaries/<sid>/accept")
def accept_summary(sid):
    user_id, _ = require_roles(["InfectionControlDirector"])
    s = db.monthly_summaries.get(sid)
    if s is None:
        raise_err(ERR_MONTHLY_SUMMARY_NOT_FOUND, "monthly summary id does not exist")
    if s["status"] != "SUBMITTED":
        raise_err(ERR_SUMMARY_NOT_REVIEWABLE, "accept requires status SUBMITTED")
    if s["submitted_by_user_id"] is not None and user_id == s["submitted_by_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTY, "acceptor must differ from submitted_by_user_id")
    s["status"] = "ACCEPTED"
    s["accepted_by_user_id"] = user_id
    touch(s)
    return success_object(summary_view(s))


@bp.post("/api/monthly-summaries/<sid>/reject")
def reject_summary(sid):
    require_roles(["InfectionControlDirector"])
    b = body()
    if "reason" not in b or b["reason"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reason")
    s = db.monthly_summaries.get(sid)
    if s is None:
        raise_err(ERR_MONTHLY_SUMMARY_NOT_FOUND, "monthly summary id does not exist")
    if s["status"] != "SUBMITTED":
        raise_err(ERR_SUMMARY_NOT_REVIEWABLE, "reject requires status SUBMITTED")
    s["status"] = "REJECTED"
    touch(s)
    _unlock_denominators(s)
    return success_object(summary_view(s))


@bp.post("/api/monthly-summaries/<sid>/amend")
def amend_summary(sid):
    require_roles(["InfectionPreventionist"])
    b = body()
    if "reason" not in b or b["reason"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: reason")
    s = db.monthly_summaries.get(sid)
    if s is None:
        raise_err(ERR_MONTHLY_SUMMARY_NOT_FOUND, "monthly summary id does not exist")
    if s["status"] != "ACCEPTED":
        raise_err(ERR_SUMMARY_NOT_AMENDABLE, "amend requires status ACCEPTED")
    s["status"] = "UNDER_AMENDMENT"
    s["amendment_count"] += 1
    s["submitted_by_user_id"] = None
    s["accepted_by_user_id"] = None
    touch(s)
    _unlock_denominators(s)
    return success_object(summary_view(s))
