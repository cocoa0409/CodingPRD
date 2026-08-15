"""DerailDevice endpoints."""
from flask import request

from db import DB
from errors import ApiError
from middleware import ALL_ROLES, auth, require_shipper_party
from response import ok, ok_list
from services import apply_expiry_sweep_to_agreement, mint_common_fields, touch
from util import as_enum, as_str, body, pagination_args, required

DEVICE_TYPES = {"DERAIL", "WHEEL_STOP", "BUMPING_POST"}


def _get_device_or_404(device_id):
    d = DB["derail_devices"].get(device_id)
    if d is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND", 404, "DerailDevice not found")
    return d


def register(app):
    @app.route("/derail-devices", methods=["POST"])
    def create_device():
        user_id, role = auth(["ShipperFacilityManager"])
        data = body()
        segment_id = as_str(required(data, "segment_id"), "segment_id")
        segment = DB["segments"].get(segment_id)
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
        agreement = DB["agreements"].get(segment["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "TrackAgreement not found")
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)

        device_type = as_enum(
            required(data, "device_type"), "device_type", DEVICE_TYPES
        )
        location_description = as_str(
            required(data, "location_description"), "location_description"
        )

        if agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_AGREEMENT_NOT_ACTIVE", 409, "Parent agreement must be ACTIVE"
            )

        device = {
            "segment_id": segment["id"],
            "device_type": device_type,
            "location_description": location_description,
            "status": "PROPOSED",
        }
        mint_common_fields(device)
        DB["derail_devices"][device["id"]] = device
        return ok(device, 201)

    @app.route("/derail-devices", methods=["GET"])
    def list_devices():
        auth(ALL_ROLES)
        limit, offset = pagination_args()
        segment_id = request.args.get("segment_id")
        items = list(DB["derail_devices"].values())
        if segment_id is not None:
            items = [d for d in items if d.get("segment_id") == segment_id]
        items.sort(key=lambda x: (x["created_at"], x["id"]))
        total = len(items)
        return ok_list(items[offset : offset + limit], total, limit, offset)

    @app.route("/derail-devices/<deviceId>", methods=["GET"])
    def get_device(deviceId):
        auth(ALL_ROLES)
        return ok(_get_device_or_404(deviceId))

    @app.route("/derail-devices/<deviceId>/approve", methods=["POST"])
    def approve_device(deviceId):
        auth(["RailroadEngineer"])
        d = _get_device_or_404(deviceId)
        if d["status"] != "PROPOSED":
            raise ApiError(
                "ERR_DEVICE_INVALID_STATE", 409, "Device must be PROPOSED to approve"
            )
        d["status"] = "APPROVED"
        touch(d)
        return ok(d)

    @app.route("/derail-devices/<deviceId>/mark-installed", methods=["POST"])
    def mark_installed(deviceId):
        user_id, role = auth(["ShipperFacilityManager"])
        d = _get_device_or_404(deviceId)
        segment = DB["segments"].get(d["segment_id"])
        if segment is None:
            raise ApiError("ERR_SEGMENT_NOT_FOUND", 404, "TrackSegment not found")
        agreement = DB["agreements"].get(segment["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "TrackAgreement not found")
        apply_expiry_sweep_to_agreement(agreement)
        require_shipper_party(user_id, agreement)
        if d["status"] != "APPROVED":
            raise ApiError(
                "ERR_DEVICE_INVALID_STATE",
                409,
                "Device must be APPROVED to mark installed",
            )
        d["status"] = "INSTALLED"
        touch(d)
        return ok(d)
