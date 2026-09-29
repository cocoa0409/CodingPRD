"""Post-construction facilities and their maintenance agreements."""

from flask import Blueprint

import enums
import middleware as mw
from db import DB, fmt_instant, new_row, touch
from errors import ApiError
from middleware import body, get_datetime, get_enum, get_int, get_number, get_str, require
from routes.common import find, one, settle
from services import calc, derive

bp = Blueprint("facilities", __name__)


@bp.post("/post-construction-facilities")
def create_facility():
    require([mw.INSPECTOR, mw.MANAGER])
    payload = body()
    site_id = get_str(payload, "construction_site_id")
    facility_type = get_enum(payload, "facility_type", enums.FACILITY_TYPE)
    ownership = get_enum(payload, "ownership", enums.OWNERSHIP)
    capacity = get_number(payload, "design_capacity_cf", exclusive_minimum=0)
    service_area = get_number(payload, "service_area_acres", exclusive_minimum=0)

    site = find("sites", site_id)
    row = new_row(
        {
            "construction_site_id": site["id"],
            "facility_type": facility_type,
            "ownership": ownership,
            "design_capacity_cf": calc.num(capacity, 2),
            "service_area_acres": calc.num(service_area, 2),
            "agreement_status": "NOT_REQUIRED" if ownership == "MUNICIPAL" else "PENDING",
            "agreement_reference": None,
            "agreement_recorded_at": None,
            "inspection_interval_months": None,
            "last_inspection_finalized_at": None,
            "months_since_last_inspection": 0,
            "inspection_overdue": False,
            "credit_eligible": False,
        }
    )
    DB.facilities[row["id"]] = row
    return one(row, 201)


@bp.get("/post-construction-facilities/<facility_id>")
def read_facility(facility_id):
    require(mw.ALL_ROLES)
    facility = find("facilities", facility_id)
    derive.refresh_facility(facility)
    return one(facility)


@bp.post("/post-construction-facilities/<facility_id>/record-agreement")
def record_agreement(facility_id):
    require([mw.INSPECTOR, mw.MANAGER])
    payload = body()
    reference = get_str(payload, "agreement_reference")
    recorded_at, _text = get_datetime(payload, "recorded_at")
    interval = get_int(payload, "inspection_interval_months", minimum=1, maximum=60)

    facility = find("facilities", facility_id)
    if facility.get("agreement_status") != "PENDING":
        raise ApiError("ERR_AGREEMENT_ALREADY_RECORDED")

    facility["agreement_status"] = "RECORDED"
    facility["agreement_reference"] = reference
    facility["agreement_recorded_at"] = fmt_instant(recorded_at)
    facility["inspection_interval_months"] = interval
    derive.refresh_facility(facility)
    touch(facility)
    settle(derive.term_of_facility(facility))
    return one(facility)
