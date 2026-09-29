"""Equipment assets, service history and disposition (PRD 3.1, 3.2, 3.11)."""

from decimal import Decimal

from flask import Blueprint

import lookups
import serializers
from db import db, new_child_row, new_row, ordered, touch
from errors import ApiError
from middleware import CAPITAL_PLANNER, guard
from response import created_response, object_response
from services import cascades, ruls
from validation import (body, bool_field, dec_field, dt_field, enum_field,
                        int_field, pagination, q_str, raw_ref, str_field)

bp = Blueprint("assets", __name__)

MODALITIES = ("CT", "MRI", "CATH_LAB", "ULTRASOUND", "LAB", "SURGICAL")
CATEGORIES = ("PM", "CORRECTIVE", "RECALL", "UPGRADE")
DISPOSITIONS = ("TRADED_IN", "SCRAPPED")


@bp.route("/capital/assets", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_asset():
    data = body()
    ref = raw_ref(data, "facility_id")
    if ref is not None:
        lookups.facility(ref)
    ref = raw_ref(data, "department_id")
    if ref is not None:
        lookups.department(ref)

    facility_id = str_field(data, "facility_id", 1, None)
    department_id = str_field(data, "department_id", 1, None)
    modality = enum_field(data, "modality", MODALITIES)
    model_name = str_field(data, "model_name", 1, 120)
    install_raw, install_date = dt_field(data, "install_date")
    expected_life_years = int_field(data, "expected_life_years", 1, 30)
    acquisition_cost_cents = int_field(data, "acquisition_cost_cents", 1)
    oem_raw, oem_date = dt_field(data, "oem_support_end_date")

    facility = lookups.facility(facility_id)
    department = lookups.department(department_id)

    if department["facility_id"] != facility["id"]:
        raise ApiError("ERR_ASSET_FACILITY_MISMATCH")

    row = new_row({
        "facility_id": facility["id"],
        "department_id": department["id"],
        "modality": modality,
        "model_name": model_name,
        "install_date": install_raw,
        "_install_date": install_date,
        "expected_life_years": expected_life_years,
        "acquisition_cost_cents": acquisition_cost_cents,
        "oem_support_end_date": oem_raw,
        "_oem_support_end_date": oem_date,
        "status": "IN_SERVICE",
        "disposition_status": "NONE",
        "trade_in_credit_applied_cents": 0,
        "age_years": Decimal("0.00"),
        "nominal_ruls_score": Decimal("100.00"),
        "adjusted_ruls_score": Decimal("100.00"),
        "service_penalty_points": Decimal("0.00"),
        "corrective_count_24m": 0,
        "downtime_hours_24m": Decimal("0.00"),
        "unresolved_recall": False,
        "ruls_as_of": None,
    })
    ruls.recompute(row)
    # On creation the derate gate decides the status the row is born with.
    row["status"] = ruls.post_derate_status(row)
    db.assets[row["id"]] = row

    facility["active_asset_count"] += 1
    touch(facility)
    return created_response(serializers.asset(row))


@bp.route("/capital/assets/<asset_id>", methods=["PATCH"])
@guard(CAPITAL_PLANNER)
def patch_asset(asset_id):
    asset = lookups.asset(asset_id)
    data = body()
    model_name = str_field(data, "model_name", 1, 120, required=False)
    install_raw, install_date = dt_field(data, "install_date", required=False)
    expected_life_years = int_field(data, "expected_life_years", 1, 30,
                                    required=False)
    oem_raw, oem_date = dt_field(data, "oem_support_end_date", required=False)
    acquisition_cost_cents = int_field(data, "acquisition_cost_cents", 1,
                                       required=False)

    if asset["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ASSET_INVALID_STATE")

    if model_name is not None:
        asset["model_name"] = model_name
    if install_raw is not None:
        asset["install_date"] = install_raw
        asset["_install_date"] = install_date
    if expected_life_years is not None:
        asset["expected_life_years"] = expected_life_years
    if oem_raw is not None:
        asset["oem_support_end_date"] = oem_raw
        asset["_oem_support_end_date"] = oem_date
    if acquisition_cost_cents is not None:
        asset["acquisition_cost_cents"] = acquisition_cost_cents

    ruls.recompute(asset)
    ruls.apply_derate_gate(asset)
    touch(asset)
    cascades.rescore_asset_requests(asset)
    return object_response(serializers.asset(asset))


@bp.route("/capital/assets/<asset_id>", methods=["GET"])
@guard()
def get_asset(asset_id):
    return object_response(serializers.asset(lookups.asset(asset_id)))


@bp.route("/capital/assets", methods=["GET"])
@guard()
def list_assets():
    limit, offset = pagination()
    rows = lookups.filtered(db.assets.values(), [
        ("facility_id", q_str("facility_id")),
        ("department_id", q_str("department_id")),
        ("modality", q_str("modality")),
        ("status", q_str("status")),
        ("disposition_status", q_str("disposition_status")),
    ])
    return lookups.paginate(rows, limit, offset, serializers.asset)


# -------------------------------------------------------------- ServiceEvent

@bp.route("/capital/assets/<asset_id>/service-events", methods=["POST"])
@guard(CAPITAL_PLANNER)
def create_service_event(asset_id):
    asset = lookups.asset(asset_id)
    data = body()
    event_raw, event_date = dt_field(data, "event_date")
    category = enum_field(data, "category", CATEGORIES)
    downtime_hours = dec_field(data, "downtime_hours", "0", "8760", max_dp=2,
                               required=False, default=Decimal("0.00"))
    cost_cents = int_field(data, "cost_cents", 0, required=False, default=0)
    recall_resolved = bool_field(data, "recall_resolved", required=False,
                                 default=False)
    notes = str_field(data, "notes", 0, 500, required=False)

    if asset["status"] == "DECOMMISSIONED":
        raise ApiError("ERR_ASSET_INVALID_STATE")
    if event_date > db.now():
        raise ApiError("ERR_EVENT_DATE_IN_FUTURE")

    row = new_child_row({
        "asset_id": asset["id"],
        "event_date": event_raw,
        "_event_date": event_date,
        "category": category,
        "downtime_hours": downtime_hours,
        "cost_cents": cost_cents,
        "recall_resolved": recall_resolved,
        "notes": notes,
    })
    db.service_events[row["id"]] = row

    ruls.recompute(asset)
    changed = ruls.apply_derate_gate(asset)
    touch(asset)
    if changed:
        cascades.rescore_asset_requests(asset)
    return created_response(serializers.service_event(row))


@bp.route("/capital/assets/<asset_id>/service-events", methods=["GET"])
@guard()
def list_service_events(asset_id):
    asset = lookups.asset(asset_id)
    limit, offset = pagination()
    rows = lookups.filtered(
        [e for e in db.service_events.values() if e["asset_id"] == asset["id"]],
        [("category", q_str("category"))])
    return lookups.paginate(rows, limit, offset, serializers.service_event)


# ------------------------------------------------------------- decommission

@bp.route("/capital/assets/<asset_id>/decommission", methods=["POST"])
@guard(CAPITAL_PLANNER)
def decommission_asset(asset_id):
    asset = lookups.asset(asset_id)
    data = body()
    disposition = enum_field(data, "disposition", DISPOSITIONS)

    if asset["status"] != "REPLACEMENT_PENDING":
        raise ApiError("ERR_ASSET_INVALID_STATE")

    commissioned = False
    for project in ordered(db.projects.values()):
        if project["record_status"] != "ACTIVE":
            continue
        request_row = db.requests.get(project["request_id"])
        if request_row is None or request_row["asset_id"] != asset["id"]:
            continue
        if project["equipment_status"] == "COMMISSIONED":
            commissioned = True
            break
    if not commissioned:
        raise ApiError("ERR_INSTALLATION_NOT_COMMISSIONED")

    if disposition == "TRADED_IN" and asset["disposition_status"] != "HELD_FOR_TRADE_IN":
        raise ApiError("ERR_TRADE_IN_NOT_HELD")

    asset["status"] = "DECOMMISSIONED"
    asset["disposition_status"] = disposition
    touch(asset)

    facility = db.facilities.get(asset["facility_id"])
    if facility is not None:
        facility["active_asset_count"] -= 1
        touch(facility)
    return object_response(serializers.asset(asset))
