"""Technical rider review and additional equipment (PRD section 3.3)."""

from flask import Blueprint

import calc
import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import auth, body, page, query_filter, req_bool, req_enum, req_int
from lookup import find_engagement, find_equipment, find_rider
from store import public, stamp, store, touch

bp = Blueprint("riders", __name__)

COVERS_GAP_VALUES = ("RIGGING_NEAR_LIMIT", "POWER_SHORTFALL", "DMX_SHORTFALL", "NONE")


@bp.post("/engagements/<engagement_id>/tech-riders")
def submit_rider(engagement_id):
    user_id, role = auth("ArtistRepresentative", "RentalClientContact")
    engagement = find_engagement(engagement_id)
    if role == "ArtistRepresentative":
        if user_id != engagement["artist_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")
    else:
        if user_id != engagement["rental_client_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER")

    data = body()
    record = {
        "engagement_id": engagement["id"],
        "submitted_rigging_kg": req_int(data, "submitted_rigging_kg", minimum=0),
        "requested_power_amps": req_int(data, "requested_power_amps", minimum=0),
        "requested_dmx_universes": req_int(data, "requested_dmx_universes", minimum=0),
        "requires_orchestra_pit": req_bool(data, "requires_orchestra_pit"),
        "review_status": "SUBMITTED",
        "capability_gaps": [],
        "additional_equipment_cost_cents": 0,
        "reviewed_by_user_id": None,
    }
    if derive.engagement_riders(engagement["id"]):
        raise ApiError("ERR_DUPLICATE_TECH_RIDER")
    stamp(record)
    store.riders[record["id"]] = record
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/tech-riders")
def list_riders(engagement_id):
    auth(
        "ProgrammingDirector",
        "RentalManager",
        "TechnicalDirector",
        "ArtistRepresentative",
        "RentalClientContact",
    )
    engagement = find_engagement(engagement_id)
    window, meta = page(derive.engagement_riders(engagement["id"]))
    return array_response([public(r) for r in window], meta)


@bp.get("/tech-riders/<rider_id>")
def read_rider(rider_id):
    auth(
        "ProgrammingDirector",
        "RentalManager",
        "TechnicalDirector",
        "ArtistRepresentative",
        "RentalClientContact",
    )
    return object_response(public(find_rider(rider_id)))


@bp.post("/tech-riders/<rider_id>/review")
def review_rider(rider_id):
    user_id, _role = auth("TechnicalDirector")
    rider = find_rider(rider_id)
    if rider["review_status"] != "SUBMITTED":
        raise ApiError("ERR_RIDER_INVALID_STATE")
    engagement = store.engagements.get(rider["engagement_id"])
    space = store.spaces.get(engagement["space_id"]) if engagement else None
    if space is None:
        raise ApiError("ERR_SPACE_NOT_FOUND")
    status, gaps = calc.capability_assessment(rider, space)
    rider["review_status"] = status
    rider["capability_gaps"] = gaps
    rider["reviewed_by_user_id"] = user_id
    touch(rider)
    return object_response(public(rider))


@bp.post("/tech-riders/<rider_id>/equipment-lines")
def create_equipment_line(rider_id):
    auth("TechnicalDirector")
    rider = find_rider(rider_id)
    data = body()
    item = None
    if data.get("equipment_item_id") is not None:
        item = find_equipment(data["equipment_item_id"])
    covers_gap = req_enum(data, "covers_gap", COVERS_GAP_VALUES)
    qty = req_int(data, "qty", minimum=1)
    rental_days = req_int(data, "rental_days", minimum=1)
    if item is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'equipment_item_id' is required.")
    if rider["review_status"] != "GAP_IDENTIFIED":
        raise ApiError("ERR_RIDER_INVALID_STATE")
    if qty > item["on_hand_qty"] - item["reserved_qty"]:
        raise ApiError("ERR_EQUIPMENT_STOCK_UNAVAILABLE")

    record = {
        "tech_rider_id": rider["id"],
        "equipment_item_id": item["id"],
        "covers_gap": covers_gap,
        "qty": qty,
        "rental_days": rental_days,
        "line_cost_cents": item["daily_rate_cents"] * qty * rental_days,
        "status": "RESERVED",
    }
    stamp(record)
    store.lines[record["id"]] = record
    derive.recompute_item_reserved(item)
    return object_response(public(record), 201)


@bp.get("/tech-riders/<rider_id>/equipment-lines")
def list_equipment_lines(rider_id):
    auth("TechnicalDirector", "ProgrammingDirector", "RentalManager", "CenterAdmin")
    rider = find_rider(rider_id)
    items = derive.rider_lines(rider["id"])
    status = query_filter("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    window, meta = page(items)
    return array_response([public(l) for l in window], meta)


@bp.post("/tech-riders/<rider_id>/clear")
def clear_rider(rider_id):
    auth("TechnicalDirector")
    rider = find_rider(rider_id)
    if rider["review_status"] not in ("CAPABLE", "GAP_IDENTIFIED"):
        raise ApiError("ERR_RIDER_INVALID_STATE")
    engagement = store.engagements.get(rider["engagement_id"])
    from_gap = rider["review_status"] == "GAP_IDENTIFIED"

    if from_gap:
        reserved = [l for l in derive.rider_lines(rider["id"]) if l["status"] == "RESERVED"]
        covered = set(l["covers_gap"] for l in reserved)
        for gap in rider["capability_gaps"]:
            if gap == "RIGGING_NEAR_LIMIT":
                continue
            if gap not in covered:
                raise ApiError("ERR_GAP_NOT_COVERED")
        rider["additional_equipment_cost_cents"] = sum(
            l["line_cost_cents"] for l in reserved
        )
        rider["review_status"] = "CLEARED"
        touch(rider)
        if engagement is not None:
            derive.recompute_engagement_equipment(engagement)
            derive.recompute_deposit(engagement)
    else:
        rider["additional_equipment_cost_cents"] = 0
        rider["review_status"] = "CLEARED"
        touch(rider)
        if engagement is not None:
            derive.recompute_engagement_equipment(engagement)
    return object_response(public(rider))
