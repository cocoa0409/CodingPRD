"""StoragePlacement endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    compute_storage_charge,
    mint_common_fields,
    recompute_segment_storage_ledger,
    refresh_provisional_storage_charge,
    touch,
)
from util import (
    as_iso_date,
    as_str,
    body,
    pagination_args,
    parse_ymd,
    required,
)


def _get_placement_or_404(placement_id):
    p = DB["storage_placements"].get(placement_id)
    if p is None:
        raise ApiError(
            "ERR_STORAGE_PLACEMENT_NOT_FOUND", 404, "StoragePlacement not found"
        )
    return p


def register(app):
    @app.route("/storage-placements", methods=["POST"])
    def create_placement():
        user_id, role = auth(["ShipperFacilityManager"])
        data = body()
        segment_id = as_str(required(data, "segment_id"), "segment_id")
        car_mark = as_str(required(data, "car_mark"), "car_mark")
        placed_date = as_iso_date(required(data, "placed_date"), "placed_date")

        segment = DB["segments"].get(segment_id)
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
        agreement = DB["agreements"].get(segment["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "TrackAgreement not found")
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)

        # Cross-entity state
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )
        # Segment safety gates: in-service, then suspension
        if segment["status"] != "IN_SERVICE":
            raise ApiError(
                "ERR_SEGMENT_OUT_OF_SERVICE", 409, "Segment must be IN_SERVICE"
            )
        if segment.get("safety_suspended"):
            raise ApiError(
                "ERR_SEGMENT_SAFETY_SUSPENDED", 409, "Segment is safety-suspended"
            )

        # Capacity
        stored_count = sum(
            1
            for p in DB["storage_placements"].values()
            if p.get("segment_id") == segment["id"] and p.get("status") == "STORED"
        )
        if stored_count >= int(segment["storage_capacity_cars"]):
            raise ApiError(
                "ERR_STORAGE_CAPACITY_EXCEEDED",
                409,
                "Segment storage capacity reached",
            )

        placement = {
            "segment_id": segment["id"],
            "car_mark": car_mark,
            "placed_date": placed_date,
            "released_date": None,
            "accrued_storage_charge_cents": 0,
            "days_charged": None,
            "final_storage_charge_cents": None,
            "status": "STORED",
        }
        mint_common_fields(placement)
        DB["storage_placements"][placement["id"]] = placement
        # Bump segment ledger
        segment["stored_car_count"] = segment.get("stored_car_count", 0) + 1
        touch(segment)
        refresh_provisional_storage_charge(placement)
        return ok(placement, 201)

    @app.route("/storage-placements", methods=["GET"])
    def list_placements():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        segment_id = request.args.get("segment_id")
        status = request.args.get("status")
        items = list(DB["storage_placements"].values())
        if segment_id is not None:
            items = [p for p in items if p.get("segment_id") == segment_id]
        if status is not None:
            items = [p for p in items if p.get("status") == status]
        for p in items:
            refresh_provisional_storage_charge(p)
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/storage-placements/<placementId>", methods=["GET"])
    def get_placement(placementId):
        auth(ALL_ROLES)
        p = _get_placement_or_404(placementId)
        refresh_provisional_storage_charge(p)
        return ok(p)

    @app.route("/storage-placements/<placementId>/release", methods=["POST"])
    def release_placement(placementId):
        user_id, role = auth(["ShipperFacilityManager"])
        p = _get_placement_or_404(placementId)
        segment = DB["segments"].get(p["segment_id"])
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
        agreement = DB["agreements"].get(segment["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "TrackAgreement not found")
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        data = body()
        released_date = as_iso_date(required(data, "released_date"), "released_date")

        if p["status"] != "STORED":
            raise ApiError(
                "ERR_PLACEMENT_INVALID_STATE",
                409,
                "Placement must be STORED to release",
            )
        if parse_ymd(released_date) < parse_ymd(p["placed_date"]):
            raise ApiError(
                "ERR_INVALID_REQUEST",
                400,
                "released_date must be on or after placed_date",
            )
        days_charged, charge = compute_storage_charge(
            p, agreement, parse_ymd(released_date)
        )
        p["released_date"] = released_date
        p["days_charged"] = days_charged
        p["final_storage_charge_cents"] = charge
        p["accrued_storage_charge_cents"] = charge
        p["status"] = "RELEASED"
        touch(p)
        recompute_segment_storage_ledger(segment)
        touch(segment)
        return ok(p)
