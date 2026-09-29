"""Lane reads and lane validation — PRD §3.3."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from services import lanes as lane_svc

bp = Blueprint("lanes", __name__)


@bp.get("/freight-procurement/lanes/<lane_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def get_lane(lane_id):
    return responses.ok(helpers.get_lane(lane_id))


@bp.get("/freight-procurement/lanes")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "ContractAdmin",
                     "CarrierRep")
def list_lanes():
    rows = store.sorted_rows(store.lanes.values())
    rows = helpers.filter_rows(rows, {
        "bid_event_id": "bid_event_id",
        "incumbent_carrier_id": "incumbent_carrier_id",
        "status": "status",
        "equipment_type": "equipment_type",
    })
    return responses.listing(rows)


@bp.post("/freight-procurement/lanes/<lane_id>/validate")
@auth.roles_required("ProcurementAnalyst")
def validate_lane(lane_id):
    lane = helpers.get_lane(lane_id)
    v.body()
    event = helpers.event_of(lane)

    if lane["status"] != "DRAFT" or event is None or event["status"] != "DRAFT":
        raise ApiError("ERR_LANE_NOT_VALIDATED")

    # Validation recomputes the flags from scratch first; a blocking flag rejects the
    # request outright and no partial write is retained.
    flags = lane_svc.data_quality_flags(lane)
    if any(flag in lane_svc.BLOCKING_FLAGS for flag in flags):
        raise ApiError("ERR_LANE_DATA_QUALITY_BLOCKED")

    lane["data_quality_flags"] = flags
    lane["unallocated_volume_loads"] = lane["annual_volume_loads"]
    lane["baseline_cost_usd"] = lane_svc.baseline_cost(lane)
    lane["validated_at"] = store.now_iso()
    lane["status"] = "VALIDATED"
    store.touch(lane)
    return responses.ok(lane)
