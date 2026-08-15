"""MoveIn endpoints (day-bucket scheduling, utility gating, proration)."""
from flask import Blueprint

from db import DB, new_id
from errors import ApiError
from middleware import AGENT, PM, auth
from response import ok, ok_list
from services import (
    get_lease,
    get_movein,
    prorated_first_month_rent,
    ser_movein,
    sorted_created,
    stamp,
    touch,
)
from util import apply_filters, as_dt, as_str, body, pagination, required

bp = Blueprint("moveins", __name__)

STAFF = [PM, AGENT]
ACTIVE_MOVEIN_STATES = ("SCHEDULED", "READY")


def _movein_property(movein):
    lease = DB["leases"].get(movein["lease_id"])
    if lease is None:
        return None
    fp = DB["floorplans"].get(lease["floorplan_id"])
    if fp is None:
        return None
    return DB["properties"].get(fp["property_id"])


@bp.post("/leasing/move-ins")
def create_movein():
    auth(STAFF)
    data = body()
    lease_id = as_str(required(data, "lease_id"), "lease_id")
    scheduled_date = as_dt(required(data, "scheduled_date"), "scheduled_date")

    lease = get_lease(lease_id)
    if lease["status"] != "EXECUTED":
        raise ApiError(
            "ERR_LEASE_NOT_EXECUTED",
            409,
            "Move-in scheduling requires an EXECUTED lease",
        )
    # One active move-in per lease (priority 6).
    for m in DB["moveins"].values():
        if m["lease_id"] == lease_id and m["status"] in ACTIVE_MOVEIN_STATES:
            raise ApiError(
                "ERR_MOVEIN_ALREADY_ACTIVE",
                409,
                "Lease already has a SCHEDULED or READY move-in",
            )
    fp = DB["floorplans"][lease["floorplan_id"]]
    prop = DB["properties"][fp["property_id"]]
    # UTC day-bucket capacity (priority 7).
    day = scheduled_date.date()
    day_count = 0
    for m in DB["moveins"].values():
        if m["status"] not in ACTIVE_MOVEIN_STATES:
            continue
        if m["scheduled_date"].date() != day:
            continue
        other = _movein_property(m)
        if other is not None and other["id"] == prop["id"]:
            day_count += 1
    if day_count >= prop["max_moveins_per_day"]:
        raise ApiError(
            "ERR_MOVEIN_DAY_FULL",
            409,
            "Move-in day bucket is at the property's max_moveins_per_day capacity",
        )

    rec = {
        "id": new_id(),
        "lease_id": lease_id,
        "scheduled_date": scheduled_date,
        "utility_confirmed": False,
        "prorated_rent_cents": prorated_first_month_rent(
            lease["monthly_rent_cents"], scheduled_date, prop["prorate_method"]
        ),
        "status": "SCHEDULED",
    }
    stamp(rec)
    DB["moveins"][rec["id"]] = rec
    return ok(ser_movein(rec), status=201)


@bp.get("/leasing/move-ins")
def list_moveins():
    auth(STAFF)
    limit, offset = pagination()
    items = apply_filters(
        DB["moveins"].values(),
        [("lease_id", "lease_id"), ("status", "status")],
    )
    items = sorted_created(items)
    total = len(items)
    return ok_list(
        [ser_movein(m) for m in items[offset : offset + limit]], total, limit, offset
    )


@bp.get("/leasing/move-ins/<mid>")
def get_one_movein(mid):
    auth(STAFF)
    return ok(ser_movein(get_movein(mid)))


@bp.post("/leasing/move-ins/<mid>/confirm-utilities")
def confirm_utilities(mid):
    auth(STAFF)
    movein = get_movein(mid)
    if movein["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_MOVEIN_INVALID_STATE",
            409,
            "Only a SCHEDULED move-in can confirm utilities",
        )
    movein["utility_confirmed"] = True
    movein["status"] = "READY"
    touch(movein)
    return ok(ser_movein(movein))


@bp.post("/leasing/move-ins/<mid>/complete")
def complete_movein(mid):
    auth(STAFF)
    movein = get_movein(mid)
    if movein["status"] == "READY":
        pass
    elif movein["status"] == "SCHEDULED":
        prop = _movein_property(movein)
        if prop is not None and prop["utility_transfer_required"]:
            raise ApiError(
                "ERR_UTILITY_CONFIRMATION_REQUIRED",
                409,
                "Property requires utility transfer confirmation before completion",
            )
    else:
        raise ApiError(
            "ERR_MOVEIN_INVALID_STATE",
            409,
            "Only a READY (or eligible SCHEDULED) move-in can be completed",
        )
    movein["status"] = "COMPLETED"
    touch(movein)
    return ok(ser_movein(movein))


@bp.post("/leasing/move-ins/<mid>/cancel")
def cancel_movein(mid):
    auth(STAFF)
    movein = get_movein(mid)
    if movein["status"] not in ACTIVE_MOVEIN_STATES:
        raise ApiError(
            "ERR_MOVEIN_INVALID_STATE",
            409,
            "Only a SCHEDULED or READY move-in can be cancelled",
        )
    movein["status"] = "CANCELLED"
    touch(movein)
    return ok(ser_movein(movein))
