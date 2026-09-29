"""Lots: receiving, release, aeration records and adverse-event reports."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

import clock
import response
import validation as V
from db import db
from errors import ApiError
from middleware import authenticate, customer_scope
from routes.common import fetch, paginate
from services import calc
from services.domain import (by_seq, current_qualification, governing_cycle,
                             indicators_of_cycle, new_record,
                             recompute_open_lot_count, touch)

bp = Blueprint("lots", __name__)


# =====================================================================
# Lot
# =====================================================================
@bp.post("/sterilization/lots")
def create_lot():
    authenticate("CustomerRep")
    body = V.body()
    customer_id = V.req_id(body, "customer_id")
    product_id = V.req_id(body, "product_id")
    lot_code = V.req_string(body, "lot_code", 1, 32)
    total_pallet_count = V.req_int(body, "total_pallet_count", minimum=1)

    customer = fetch("customers", customer_id)
    product = fetch("products", product_id)

    for existing in db.lots.values():
        if existing["customer_id"] == customer_id and existing["lot_code"] == lot_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "lot_code '%s' already exists for this customer." % lot_code)

    customer_scope(customer["id"])

    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED",
                       "A SUSPENDED account may not book lots into the facility.")

    lot = new_record({
        "customer_id": customer["id"],
        "product_id": product["id"],
        "parent_lot_id": None,
        "lot_code": lot_code,
        "total_pallet_count": total_pallet_count,
        "staged_pallet_count": 0,
        "available_pallet_count": total_pallet_count,
        "status": "RECEIVED",
        "residual_status": "NOT_APPLICABLE",
        "quarantine_reason": "NONE",
        "cumulative_dose_kgy": Decimal("0.00"),
        "resterilization_count": 0,
        "schedulable": True,
        "release_mode": "NONE",
        "released_at": None,
        "released_by_user_id": None,
        "release_dose_kgy": None,
    })
    db.lots[lot["id"]] = lot
    recompute_open_lot_count(customer["id"])
    return response.object_response(lot, 201)


@bp.get("/sterilization/lots/<lot_id>")
def read_lot(lot_id):
    authenticate("CustomerRep", "CycleOperator", "DosimetryAnalyst",
                 "QualityReleaseOfficer", "RegulatoryAdmin")
    lot = fetch("lots", lot_id)
    customer_scope(lot["customer_id"])
    return response.object_response(lot)


@bp.get("/sterilization/lots")
def list_lots():
    authenticate("CustomerRep", "CycleOperator", "DosimetryAnalyst",
                 "QualityReleaseOfficer", "RegulatoryAdmin")
    limit, offset = V.pagination()
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    parent_lot_id = request.args.get("parent_lot_id")
    status = request.args.get("status")
    residual_status = request.args.get("residual_status")
    rows = [
        lot for lot in db.lots.values()
        if (customer_id is None or lot["customer_id"] == customer_id)
        and (product_id is None or lot["product_id"] == product_id)
        and (parent_lot_id is None or lot["parent_lot_id"] == parent_lot_id)
        and (status is None or lot["status"] == status)
        and (residual_status is None or lot["residual_status"] == residual_status)
    ]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# =====================================================================
# Release (PRD 3.9) - the gate chain runs in section 2.7 priority order
# =====================================================================
@bp.post("/sterilization/lots/<lot_id>/release")
def release_lot(lot_id):
    user_id, _role = authenticate("QualityReleaseOfficer")
    body = V.body()
    release_mode = V.req_enum(body, "release_mode", ("PARAMETRIC", "DOSIMETRIC"))
    lot = fetch("lots", lot_id)

    # priority 45 - lot posture
    cycle = governing_cycle(lot)
    if lot["status"] != "QUARANTINE" \
            or lot["residual_status"] == "RESIDUAL_FAIL" \
            or cycle is None:
        raise ApiError("ERR_LOT_NOT_RELEASABLE")

    indicators = indicators_of_cycle(cycle["id"])
    recipe = db.recipes.get(cycle["recipe_id"])

    # priority 55 - biological indicator positivity
    for indicator in indicators:
        if indicator["indicator_type"] == "BIOLOGICAL" and indicator["bi_result"] == "POSITIVE":
            raise ApiError("ERR_BI_POSITIVE_BLOCKS_RELEASE")

    # priority 58 - cycle conformance
    if cycle["status"] != "DOSE_CONFORMING":
        raise ApiError("ERR_CYCLE_DEVIATION_BLOCKS_RELEASE")

    # priority 60 - current qualification
    if current_qualification(lot["product_id"], cycle["recipe_id"]) is None:
        raise ApiError("ERR_QUALIFICATION_NOT_CURRENT")

    # priority 70 - segregation of duties
    if user_id == cycle.get("operator_user_id") \
            or user_id == cycle.get("dosimetry_closed_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # priority 80 - residual timing
    if lot["residual_status"] in ("PENDING_AERATION", "AERATING"):
        raise ApiError("ERR_AERATION_INCOMPLETE")

    # priority 90 / 91 - release-mode eligibility
    if release_mode == "PARAMETRIC":
        if recipe is None or recipe["required_biological_indicators"] != 0:
            raise ApiError("ERR_PARAMETRIC_NOT_PERMITTED")
    else:
        for indicator in indicators:
            if indicator["indicator_type"] == "BIOLOGICAL" \
                    and indicator["reading_status"] != "READ":
                raise ApiError("ERR_BI_INCUBATION_PENDING")

    # priority 98 - customer standing
    customer = db.customers.get(lot["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED")

    lot["status"] = "RELEASED"
    lot["release_mode"] = release_mode
    lot["released_at"] = clock.now()
    lot["released_by_user_id"] = user_id
    lot["release_dose_kgy"] = cycle.get("delivered_dose_kgy")
    lot["quarantine_reason"] = "NONE"
    touch(lot)
    recompute_open_lot_count(lot["customer_id"])
    return response.object_response(lot)


# =====================================================================
# AerationRecord (PRD 3.8)
# =====================================================================
@bp.post("/sterilization/lots/<lot_id>/aeration-records")
def open_aeration_record(lot_id):
    authenticate("CycleOperator")
    lot = fetch("lots", lot_id)

    # priority 81 - aeration applicability
    if lot["residual_status"] != "PENDING_AERATION":
        raise ApiError("ERR_AERATION_NOT_APPLICABLE",
                       "The lot's residual_status is %s." % lot["residual_status"])
    cycle = governing_cycle(lot)
    if cycle is None:
        raise ApiError("ERR_AERATION_NOT_APPLICABLE", "The lot has no governing cycle.")

    recipe = db.recipes.get(cycle["recipe_id"])
    base_hours = recipe["aeration_base_hours"] if recipe else 0
    factor = calc.density_factor(cycle["load_density_g_per_cm3"])
    required_hours = calc.required_hours_standard(base_hours, factor)
    started_at = clock.now()

    record = new_record({
        "lot_id": lot["id"],
        "aeration_start_at": started_at,
        "base_hours": base_hours,
        "density_factor": factor,
        "required_hours": required_hours,
        "target_end_at": started_at + timedelta(hours=required_hours),
        "retest_count": 0,
        "last_failed_sample_at": None,
        "last_eto_ppm": None,
        "last_ech_ppm": None,
        "variant_applied": "STANDARD",
        "status": "IN_PROGRESS",
    })
    db.aeration_records[record["id"]] = record

    lot["residual_status"] = "AERATING"
    touch(lot)
    return response.object_response(record, 201)


@bp.get("/sterilization/lots/<lot_id>/aeration-records")
def list_aeration_records(lot_id):
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    limit, offset = V.pagination()
    fetch("lots", lot_id)
    rows = [r for r in db.aeration_records.values() if r["lot_id"] == lot_id]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# =====================================================================
# AdverseEvent (PRD 3.9)
# =====================================================================
EVENT_TYPES = ("STERILITY_COMPLAINT", "RESIDUAL_EXCEEDANCE",
               "FIELD_DOSE_DEVIATION", "PACKAGING_BREACH")
SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@bp.post("/sterilization/lots/<lot_id>/adverse-events")
def report_adverse_event(lot_id):
    user_id, _role = authenticate("CustomerRep", "QualityReleaseOfficer")
    body = V.body()
    event_type = V.req_enum(body, "event_type", EVENT_TYPES)
    severity = V.req_enum(body, "severity", SEVERITIES)
    description = V.req_string(body, "description", 1, 500)
    expected_lot_version = V.req_int(body, "expected_lot_version")

    lot = fetch("lots", lot_id)
    customer_scope(lot["customer_id"])

    # priority 50 - optimistic concurrency on the parent lot
    if expected_lot_version != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION")

    if lot["status"] == "QUARANTINE":
        lot["quarantine_reason"] = "ADVERSE_EVENT"
    touch(lot)

    event = new_record({
        "lot_id": lot["id"],
        "lot_version_after": lot["version"],
        "event_type": event_type,
        "severity": severity,
        "description": description,
        "reported_by_user_id": user_id,
        "disposition": None,
        "status": "REPORTED",
    })
    db.adverse_events[event["id"]] = event
    return response.object_response(event, 201)


@bp.get("/sterilization/lots/<lot_id>/adverse-events")
def list_adverse_events(lot_id):
    authenticate("CustomerRep", "QualityReleaseOfficer", "RegulatoryAdmin")
    limit, offset = V.pagination()
    fetch("lots", lot_id)
    rows = [e for e in db.adverse_events.values() if e["lot_id"] == lot_id]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)
