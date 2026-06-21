"""Meter and MeterRead routes (PRD §3.2)."""
from flask import Blueprint

import db
import errors
import middleware
from response import object_response, array_response
from services import lookup
from services.common import (
    get_json_body, require_str, require_int, require_enum, require_datetime,
    public, public_list, parse_pagination, paginate, parse_datetime,
)

bp = Blueprint("meters", __name__)


def _meter_public(rec):
    """Meter with derived last_reading_gallons (most recent imported read,
    0 if none) (PRD §3.2)."""
    out = public(rec)
    out["last_reading_gallons"] = _last_reading_gallons(rec["id"])
    return out


def _last_reading_gallons(meter_id):
    reads = [r for r in db.meter_reads.values() if r["meter_id"] == meter_id]
    if not reads:
        return 0
    reads.sort(key=lambda r: (parse_datetime(r["read_date"]), r["_seq"]))
    return reads[-1]["reading_gallons"]


def _prior_read(meter_id, read_dt, exclude_id=None):
    """Most recent read for the meter strictly before read_dt (chronological)."""
    candidates = []
    for r in db.meter_reads.values():
        if r["meter_id"] != meter_id:
            continue
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        rd = parse_datetime(r["read_date"])
        if rd is not None and rd < read_dt:
            candidates.append((rd, r))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]["_seq"]))
    return candidates[-1][1]


# ---- Meters ----------------------------------------------------------------
@bp.post("/accounts/<account_id>/meters")
def create_meter(account_id):
    middleware.require_role({"BillingClerk"})
    lookup.account(account_id)
    body = get_json_body()

    meter_type = require_enum(body, "meter_type", {"POTABLE", "IRRIGATION"})
    serial = require_str(body, "serial")

    rec = db.make_record({
        "account_id": account_id,
        "meter_type": meter_type,
        "serial": serial,
        "status": "ACTIVE",
    })
    db.meters[rec["id"]] = rec
    return object_response(_meter_public(rec), 201)


@bp.get("/accounts/<account_id>/meters")
def list_account_meters(account_id):
    middleware.require_role({"BillingClerk", "FieldOps", "Customer"})
    lookup.account(account_id)
    middleware.require_owner(account_id)
    limit, offset = parse_pagination()

    records = [m for m in db.meters.values() if m["account_id"] == account_id]
    window, total = paginate(records, limit, offset)
    return array_response([_meter_public(m) for m in window], limit, offset, total, 200)


@bp.get("/meters/<rid>")
def get_meter(rid):
    middleware.require_role({"BillingClerk", "FieldOps", "Customer"})
    rec = lookup.meter(rid)
    middleware.require_owner(rec["account_id"])
    return object_response(_meter_public(rec), 200)


# ---- Meter reads -----------------------------------------------------------
@bp.post("/meters/<meter_id>/reads")
def create_read(meter_id):
    middleware.require_role({"BillingClerk"})
    meter = lookup.meter(meter_id)
    body = get_json_body()

    reading_gallons = require_int(body, "reading_gallons", minimum=0)
    read_dt = require_datetime(body, "read_date")
    source = require_enum(body, "source", {"AMI", "MANUAL"}, default="AMI")

    prior = _prior_read(meter_id, read_dt)

    # ERR_READ_REGRESSION: reading below prior chronological read, unless this is
    # a MANUAL rollover correction (PRD §3.2).
    if prior is not None and reading_gallons < prior["reading_gallons"]:
        if source != "MANUAL":
            raise errors.err(
                errors.ERR_READ_REGRESSION,
                "reading_gallons is below the prior chronological read.",
            )

    # consumption = reading - prior read; first read -> 0; clamp at >= 0.
    if prior is None:
        consumption = 0
    else:
        consumption = max(0, reading_gallons - prior["reading_gallons"])

    rec = db.make_record({
        "meter_id": meter_id,
        "reading_gallons": reading_gallons,
        "read_date": body["read_date"],
        "source": source,
        "consumption_gallons": consumption,
    }, append_only=True)
    db.meter_reads[rec["id"]] = rec

    # Importing a read refreshes the meter's derived last_reading; mark meter
    # mutated so its updated_at/version advance (last_reading_gallons is derived
    # at read time but the import is a meter-touching event).
    db.touch(meter)
    return object_response(public(rec), 201)


@bp.get("/meters/<meter_id>/reads")
def list_reads(meter_id):
    middleware.require_role({"BillingClerk", "FieldOps", "Customer"})
    meter = lookup.meter(meter_id)
    middleware.require_owner(meter["account_id"])
    limit, offset = parse_pagination()

    records = [r for r in db.meter_reads.values() if r["meter_id"] == meter_id]
    # Reads listed in chronological order (PRD §3.2): by read_date ASC.
    records.sort(key=lambda r: (parse_datetime(r["read_date"]), r["_seq"]))
    total = len(records)
    window = records[offset:offset + limit]
    return array_response(public_list(window), limit, offset, total, 200)
