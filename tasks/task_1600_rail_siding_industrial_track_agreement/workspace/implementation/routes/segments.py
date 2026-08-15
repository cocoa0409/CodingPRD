"""TrackSegment endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    apply_expiry_sweep_to_agreement,
    get_agreement_or_404,
    mint_common_fields,
    touch,
)
from util import as_non_negative_int, as_positive_int, as_str, body, pagination_args, required


def _get_segment_or_404(segment_id):
    s = DB["segments"].get(segment_id)
    if s is None:
        raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
    return s


def register(app):
    @app.route("/segments", methods=["POST"])
    def create_segment():
        auth(["RailroadEngineer"])
        data = body()
        agreement_id = as_str(required(data, "agreement_id"), "agreement_id")
        agreement = get_agreement_or_404(agreement_id)
        apply_expiry_sweep_to_agreement(agreement)

        segment_name = as_str(required(data, "segment_name"), "segment_name")
        length_feet = as_positive_int(required(data, "length_feet"), "length_feet")
        storage_capacity_cars = as_non_negative_int(
            required(data, "storage_capacity_cars"), "storage_capacity_cars"
        )

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )

        segment = {
            "agreement_id": agreement["id"],
            "segment_name": segment_name,
            "length_feet": length_feet,
            "storage_capacity_cars": storage_capacity_cars,
            "stored_car_count": 0,
            "accrued_storage_cents": 0,
            "safety_suspended": False,
            "status": "IN_SERVICE",
        }
        mint_common_fields(segment)
        DB["segments"][segment["id"]] = segment
        return ok(segment, 201)

    @app.route("/segments", methods=["GET"])
    def list_segments():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        agreement_id = request.args.get("agreement_id")
        items = list(DB["segments"].values())
        if agreement_id is not None:
            items = [s for s in items if s.get("agreement_id") == agreement_id]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/segments/<segmentId>", methods=["GET"])
    def get_segment(segmentId):
        auth(ALL_ROLES)
        return ok(_get_segment_or_404(segmentId))

    @app.route("/segments/<segmentId>/take-out-of-service", methods=["POST"])
    def take_out_of_service(segmentId):
        auth(["RailroadEngineer"])
        s = _get_segment_or_404(segmentId)
        agreement = get_agreement_or_404(s["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        if s["status"] != "IN_SERVICE":
            raise ApiError(
                "ERR_SEGMENT_INVALID_STATE",
                409,
                "Segment must be IN_SERVICE to take out of service",
            )
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )
        # Non-cascading: do not touch orders/placements
        s["status"] = "OUT_OF_SERVICE"
        touch(s)
        return ok(s)

    @app.route("/segments/<segmentId>/return-to-service", methods=["POST"])
    def return_to_service(segmentId):
        auth(["RailroadEngineer"])
        s = _get_segment_or_404(segmentId)
        agreement = get_agreement_or_404(s["agreement_id"])
        apply_expiry_sweep_to_agreement(agreement)
        if s["status"] != "OUT_OF_SERVICE":
            raise ApiError(
                "ERR_SEGMENT_INVALID_STATE",
                409,
                "Segment must be OUT_OF_SERVICE to return to service",
            )
        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )
        if s.get("safety_suspended"):
            raise ApiError(
                "ERR_SEGMENT_SAFETY_SUSPENDED",
                409,
                "Segment is safety-suspended",
            )
        s["status"] = "IN_SERVICE"
        touch(s)
        return ok(s)
