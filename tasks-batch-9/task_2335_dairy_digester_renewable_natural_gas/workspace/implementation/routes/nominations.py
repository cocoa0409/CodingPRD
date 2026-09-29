from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import db
from errors import fail
from middleware import endpoint, body
from numeric import D, q
from response import created, ok
from routes.common import get_interconnect, get_nomination, get_ops_day, paged_list, resolve_refs
from services import cascade, derive
from validation import require_strict_range

bp = Blueprint("nominations", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "PipelineScheduler",
              "ProgramAdministrator", "CreditVerifier"]

BLOCKING_STATUSES = ("NOMINATED", "CONFIRMED", "CURTAILED", "DELIVERED")


@bp.post("/injection-nominations")
@endpoint(["PipelineScheduler"])
def create_nomination():
    b = body()
    interconnect, day = resolve_refs(b, (("interconnect_id", get_interconnect),
                                         ("ops_day_id", get_ops_day)))
    start_raw, start_dt = b.datetime_utc("window_start_utc")
    end_raw, end_dt = b.datetime_utc("window_end_utc")
    nominated = b.number("nominated_mmbtu", 3, gt=0)
    require_strict_range(start_dt, end_dt)

    if day["gas_state"] != "PIPELINE_SPEC":
        fail("ERR_GAS_NOT_PIPELINE_SPEC",
             "The source operations day is not at pipeline specification.")
    if interconnect["status"] != "ACTIVE" or \
            derive.active_interconnect(day["facility_id"]) is None:
        fail("ERR_NO_ACTIVE_INTERCONNECT",
             "No ACTIVE interconnection agreement is available.")

    lead = timedelta(hours=interconnect["nomination_lead_hours"])
    if start_dt - db.now_logical() < lead:
        fail("ERR_NOMINATION_LEAD_TIME",
             "The window starts inside the pipeline's notice period.")

    buffer_delta = timedelta(minutes=interconnect["ramp_buffer_minutes"])
    new_low = start_dt - buffer_delta
    new_high = end_dt + buffer_delta
    for other in db.nominations.values():
        if other["interconnect_id"] != interconnect["id"] or \
                other["status"] not in BLOCKING_STATUSES:
            continue
        other_low = other["_window_start"] - buffer_delta
        other_high = other["_window_end"] + buffer_delta
        if new_low < other_high and other_low < new_high:
            fail("ERR_INJECTION_WINDOW_OVERLAP",
                 "The buffered injection window collides with an existing nomination.")

    if nominated > D(day["pipeline_gas_mmbtu"]):
        fail("ERR_NOMINATION_EXCEEDS_PRODUCTION",
             "The nominated energy exceeds the day's pipeline production.")

    window_minutes = int((end_dt - start_dt).total_seconds() // 60)
    if window_minutes <= 0:
        fail("ERR_HOURLY_CAPACITY_EXCEEDED",
             "The injection window is shorter than one whole minute.")
    hourly_rate = q(nominated / (D(window_minutes) / 60), 3)
    if hourly_rate > D(interconnect["max_hourly_injection_mmbtu"]):
        fail("ERR_HOURLY_CAPACITY_EXCEEDED",
             "The implied injection rate exceeds the interconnection ceiling.")

    row = db.new_row({
        "interconnect_id": interconnect["id"],
        "ops_day_id": day["id"],
        "window_start_utc": start_raw,
        "window_end_utc": end_raw,
        "_window_start": start_dt,
        "_window_end": end_dt,
        "nominated_mmbtu": nominated,
        "window_minutes": window_minutes,
        "hourly_rate_mmbtu": hourly_rate,
        "status": "NOMINATED",
        "confirmed_mmbtu": None,
        "delivered_mmbtu": None,
    })
    db.nominations[row["id"]] = row
    return created(derive.ser_nomination(row))


@bp.get("/injection-nominations")
@endpoint(READ_ROLES)
def list_nominations():
    return paged_list(db.nominations, derive.ser_nomination,
                      ("interconnect_id", "ops_day_id", "status"))


@bp.get("/injection-nominations/<nomination_id>")
@endpoint(READ_ROLES)
def read_nomination(nomination_id):
    return ok(derive.ser_nomination(get_nomination(nomination_id)))


@bp.post("/injection-nominations/<nomination_id>/schedule-decision")
@endpoint(["PipelineScheduler"])
def schedule_decision(nomination_id):
    nomination = get_nomination(nomination_id)
    b = body()
    decision = b.enum("decision", ("CONFIRM", "CURTAIL"))
    b.string("reason", required=False)
    curtailed = None
    if decision == "CURTAIL":
        curtailed = b.number("curtailed_mmbtu", 3, gt=0)
        if curtailed >= D(nomination["nominated_mmbtu"]):
            fail("ERR_INVALID_REQUEST",
                 "curtailed_mmbtu must be strictly less than nominated_mmbtu.")

    interconnect = db.interconnects[nomination["interconnect_id"]]
    day = db.ops_days[nomination["ops_day_id"]]

    if nomination["status"] != "NOMINATED":
        fail("ERR_INVALID_STATE", "Only a NOMINATED nomination may be decided.")

    if decision == "CONFIRM":
        if interconnect["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The interconnection agreement is not ACTIVE.")
        if day["gas_state"] != "PIPELINE_SPEC":
            fail("ERR_GAS_NOT_PIPELINE_SPEC",
                 "The source operations day is not at pipeline specification.")
        nomination["status"] = "CONFIRMED"
        nomination["confirmed_mmbtu"] = nomination["nominated_mmbtu"]
        db.touch(nomination)
    else:
        nomination["status"] = "CURTAILED"
        nomination["confirmed_mmbtu"] = curtailed
        db.touch(nomination)
        cascade.bump_curtailment(interconnect, 1)
        db.touch(interconnect)
    return ok(derive.ser_nomination(nomination))


@bp.post("/injection-nominations/<nomination_id>/deliver")
@endpoint(["PipelineScheduler"])
def deliver_nomination(nomination_id):
    nomination = get_nomination(nomination_id)
    b = body()
    delivered = b.number("delivered_mmbtu", 3, ge=0)
    day = db.ops_days[nomination["ops_day_id"]]

    if nomination["status"] not in ("CONFIRMED", "CURTAILED"):
        fail("ERR_INVALID_STATE",
             "Only a CONFIRMED or CURTAILED nomination may be delivered.")
    if day["gas_state"] != "PIPELINE_SPEC":
        fail("ERR_GAS_NOT_PIPELINE_SPEC",
             "The source operations day is not at pipeline specification.")
    if delivered > D(nomination["confirmed_mmbtu"] or Decimal("0")):
        fail("ERR_DELIVERY_EXCEEDS_CONFIRMED",
             "The delivered energy exceeds the confirmed energy.")

    nomination["status"] = "DELIVERED"
    nomination["delivered_mmbtu"] = delivered
    db.touch(nomination)
    day["gas_state"] = "INJECTED"
    db.touch(day)
    return ok(derive.ser_nomination(nomination))
