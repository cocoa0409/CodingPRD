from decimal import Decimal

from flask import Blueprint

from db import db
from errors import fail
from middleware import endpoint, body
from numeric import D
from response import created, ok
from routes.common import get_agreement, get_delivery, get_ops_day, paged_list, resolve_refs
from services import calc, derive
from validation import date_of

bp = Blueprint("deliveries", __name__)

READ_ROLES = ["PlatformAdmin", "ProjectOperator", "DairyPartner",
              "CreditVerifier", "FinanceController"]


@bp.post("/feedstock-deliveries")
@endpoint(["ProjectOperator"])
def create_delivery():
    b = body()
    agreement, day = resolve_refs(b, (("agreement_id", get_agreement),
                                      ("ops_day_id", get_ops_day)))
    gross = b.number("gross_tonnes", 3, gt=0)
    tare = b.number("tare_tonnes", 3, required=False, default=Decimal("0.000"), ge=0)
    if tare >= gross:
        fail("ERR_INVALID_REQUEST", "tare_tonnes must be strictly less than gross_tonnes.")
    ts_pct = b.number("total_solids_pct", 1, gt=0, lt=100)
    vs_pct = b.number("volatile_solids_pct_of_ts", 1, gt=0, le=100)

    facility = db.facilities[day["facility_id"]]

    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE", "The supplying agreement is not ACTIVE.")
    if facility["ops_posture"] == "UPSET":
        fail("ERR_FACILITY_UPSET", "The facility is in biological upset.")
    ops_date = date_of(day["ops_date"])
    if not (date_of(agreement["term_start_date"]) <= ops_date
            <= date_of(agreement["term_end_date"])):
        fail("ERR_OUTSIDE_AGREEMENT_TERM",
             "The operations date falls outside the agreement term.")
    if D(ts_pct) < D(agreement["minimum_total_solids_pct"]):
        fail("ERR_SOLIDS_BELOW_MINIMUM",
             "The measured total solids are below the contracted minimum.")

    dairy = db.dairies[agreement["dairy_id"]]
    net, vs, haul = calc.delivery_derived(gross, tare, ts_pct, vs_pct,
                                          dairy["haul_distance_km"])
    booked = sum((d["net_tonnes"] for d in derive.deliveries_of_day(day["id"])),
                 Decimal("0"))
    if booked + net > D(facility["hydraulic_capacity_tonnes_per_day"]):
        fail("ERR_HYDRAULIC_CAPACITY_EXCEEDED",
             "The load would exceed the facility's hydraulic capacity for the day.")

    row = db.new_row({
        "agreement_id": agreement["id"],
        "ops_day_id": day["id"],
        "gross_tonnes": gross,
        "tare_tonnes": tare,
        "total_solids_pct": ts_pct,
        "volatile_solids_pct_of_ts": vs_pct,
        "net_tonnes": net,
        "vs_tonnes": vs,
        "haul_tonne_km": haul,
        "status": "ACCEPTED",
        "rejection_reason": None,
    })
    db.deliveries[row["id"]] = row

    derive.recompute_day_olr(day)
    db.touch(day)
    db.touch(facility)
    return created(derive.ser_delivery(row))


@bp.get("/feedstock-deliveries")
@endpoint(READ_ROLES)
def list_deliveries():
    return paged_list(db.deliveries, derive.ser_delivery,
                      ("agreement_id", "ops_day_id", "status"))


@bp.get("/feedstock-deliveries/<delivery_id>")
@endpoint(READ_ROLES)
def read_delivery(delivery_id):
    return ok(derive.ser_delivery(get_delivery(delivery_id)))


@bp.post("/feedstock-deliveries/<delivery_id>/reject")
@endpoint(["ProjectOperator"])
def reject_delivery(delivery_id):
    delivery = get_delivery(delivery_id)
    b = body()
    reason = b.enum("rejection_reason",
                    ("OFF_SPEC_SOLIDS", "CONTAMINATION", "SCALE_ERROR"))
    day = db.ops_days[delivery["ops_day_id"]]
    if delivery["status"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", "Only an ACCEPTED delivery may be rejected.")
    if day["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "The operations day is no longer OPEN.")

    delivery["status"] = "REJECTED"
    delivery["rejection_reason"] = reason
    db.touch(delivery)
    derive.recompute_day_olr(day)
    db.touch(day)
    db.touch(db.facilities[day["facility_id"]])
    return ok(derive.ser_delivery(delivery))
