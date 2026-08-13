"""FeeSchedule endpoints."""
from flask import Blueprint

from db import DB, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from util import as_int, body, paginate, pagination, parse_dt, required, stamp_new

bp = Blueprint("fees", __name__)


def fee_schedule_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


@bp.post("/accreditation/fee-schedules")
def create_fee_schedule():
    auth(["AccreditationOfficer"])
    data = body()
    effective_from_raw = required(data, "effective_from")
    effective_dt = parse_dt(effective_from_raw, "effective_from")
    base_system_fee_cents = as_int(
        required(data, "base_system_fee_cents"), "base_system_fee_cents"
    )
    per_campus_fee_cents = as_int(
        required(data, "per_campus_fee_cents"), "per_campus_fee_cents"
    )
    large_campus_fee_cents = as_int(
        required(data, "large_campus_fee_cents"), "large_campus_fee_cents"
    )
    large_campus_threshold = as_int(
        required(data, "large_campus_threshold"), "large_campus_threshold"
    )
    visit_day_rate_cents = as_int(
        required(data, "visit_day_rate_cents"), "visit_day_rate_cents"
    )
    # Uniqueness on effective_from.
    for s in DB["fee_schedules"].values():
        if s["_effective_from_dt"] == effective_dt:
            raise ApiError(
                "ERR_DUPLICATE_RESOURCE",
                409,
                "A fee schedule with this effective_from already exists",
            )
    record = {
        "id": new_id(),
        "effective_from": fmt_iso(effective_dt),
        "base_system_fee_cents": base_system_fee_cents,
        "per_campus_fee_cents": per_campus_fee_cents,
        "large_campus_fee_cents": large_campus_fee_cents,
        "large_campus_threshold": large_campus_threshold,
        "visit_day_rate_cents": visit_day_rate_cents,
        "_effective_from_dt": effective_dt,
    }
    # FeeSchedule carries id and created_at only (PRD 2.4).
    stamp_new(record, with_version=False)
    DB["fee_schedules"][record["id"]] = record
    return ok(fee_schedule_view(record), status=201)


@bp.get("/accreditation/fee-schedules")
def list_fee_schedules():
    auth(["AccreditationOfficer", "SystemBursar"])
    limit, offset = pagination()
    rows = sorted(DB["fee_schedules"].values(), key=lambda s: s["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([fee_schedule_view(r) for r in page], total, limit, offset)
