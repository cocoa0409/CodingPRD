"""The delivery fleet: barges and road tankers (PRD 3.1, 3.6)."""

from decimal import Decimal

from flask import Blueprint

import db
import serializers
from db import store
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, cascade
from validation import (
    apply_page,
    body,
    pagination,
    q_enum,
    q_str,
    v_bool,
    v_decimal,
    v_enum,
    v_int,
    v_string,
)

bp = Blueprint("assets", __name__)

ASSET_READERS = ("OpsCoordinator", "ComplianceOfficer", "BargeMaster")
ASSET_TYPES = ("BARGE", "TRUCK")
ASSET_STATUSES = ("AVAILABLE", "QUARANTINED")


@bp.post("/delivery-assets")
@roles("OpsCoordinator")
def create_asset():
    data = body()
    port = body_ref(data, "home_port_id", store.ports, "ERR_PORT_NOT_FOUND")
    name = v_string(data, "name", min_len=1)
    asset_type = v_enum(data, "asset_type", ASSET_TYPES)
    capacity_mt = v_decimal(data, "capacity_mt", 3, positive=True)
    home_port_id = v_string(data, "home_port_id", min_len=1)
    boom_certified = v_bool(data, "boom_certified", required=False, default=False)
    segregated_tanks = v_bool(data, "segregated_tanks", required=False, default=False)
    turnaround_buffer_minutes = v_int(
        data, "turnaround_buffer_minutes", required=False, default=90, min_value=0
    )
    if port is None:
        raise ApiError("ERR_PORT_NOT_FOUND")

    asset = db.new_record()
    asset.update(
        {
            "name": name,
            "asset_type": asset_type,
            "capacity_mt": capacity_mt,
            "home_port_id": home_port_id,
            "boom_certified": boom_certified,
            "segregated_tanks": segregated_tanks,
            "turnaround_buffer_minutes": turnaround_buffer_minutes,
            "last_grade_id": None,
            "status": "AVAILABLE",
            "committed_quantity_mt": Decimal("0.000"),
            "compliance_score": Decimal("100.00"),
        }
    )
    store.delivery_assets[asset["id"]] = asset
    return success(serializers.delivery_asset(asset), 201)


@bp.get("/delivery-assets/<rec_id>")
@roles(*ASSET_READERS)
def get_asset(rec_id):
    asset = path_ref(store.delivery_assets, rec_id, "ERR_ASSET_NOT_FOUND")
    return success(serializers.delivery_asset(asset))


@bp.get("/delivery-assets")
@roles(*ASSET_READERS)
def list_assets():
    home_port_id = q_str("home_port_id")
    last_grade_id = q_str("last_grade_id")
    status = q_enum("status", ASSET_STATUSES)
    asset_type = q_enum("asset_type", ASSET_TYPES)
    limit, offset = pagination()

    def match(row):
        if home_port_id is not None and row["home_port_id"] != home_port_id:
            return False
        if last_grade_id is not None and row["last_grade_id"] != last_grade_id:
            return False
        if status is not None and row["status"] != status:
            return False
        if asset_type is not None and row["asset_type"] != asset_type:
            return False
        return True

    rows = db.sorted_rows(store.delivery_assets, match)
    page = apply_page(rows, limit, offset)
    return success_list(
        [serializers.delivery_asset(r) for r in page], limit, offset, len(rows)
    )


@bp.post("/delivery-assets/<rec_id>/return-to-service")
@roles("ComplianceOfficer")
def return_to_service(rec_id):
    asset = path_ref(store.delivery_assets, rec_id, "ERR_ASSET_NOT_FOUND")
    if asset["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_ASSET_STATE")
    if calc.open_spill_incidents(asset["id"]):
        raise ApiError("ERR_OPEN_SPILL_INCIDENT")

    asset["status"] = "AVAILABLE"
    cascade.refresh_asset(asset, score=True)
    return success(serializers.delivery_asset(asset))
