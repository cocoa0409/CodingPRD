"""Pad routes: create, get, list, take_out_of_service."""
from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util

bp = Blueprint("pads", __name__)

SIZE_CLASSES = {"SMALL", "MEDIUM", "LARGE"}


@bp.route("/deice-ops/pads", methods=["POST"])
def create_pad():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["station_id", "code", "max_size_class", "rated_collection_pct"])
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    code = payload["code"]
    if not isinstance(code, str) or not code:
        raise errors.invalid_request("code must be a non-empty string")
    max_size_class = util.require_enum(payload["max_size_class"], SIZE_CLASSES, "max_size_class")
    rated_collection_pct = float(util.to_decimal(payload["rated_collection_pct"], "rated_collection_pct"))
    for p in db.pads.values():
        if p["station_id"] == station["id"] and p["code"] == code:
            raise errors.invalid_request("code must be unique within station")
    now = util.iso_now()
    pad = {
        "id": util.new_id(),
        "station_id": station["id"],
        "code": code,
        "max_size_class": max_size_class,
        "rated_collection_pct": rated_collection_pct,
        "status": "AVAILABLE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    pad["_created_dt"] = db.get_clock()
    db.pads[pad["id"]] = pad
    return response.success_object(serializers.pad(pad), 201)


@bp.route("/deice-ops/pads/<pid>", methods=["GET"])
def get_pad(pid):
    middleware.require_roles("StationAdmin", "PadOperator")
    pad = db.pads.get(pid)
    if pad is None:
        raise errors.not_found("pad not found")
    return response.success_object(serializers.pad(pad), 200)


@bp.route("/deice-ops/pads", methods=["GET"])
def list_pads():
    middleware.require_roles("StationAdmin", "PadOperator")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = list(db.pads.values())
    if station_id is not None:
        items = [p for p in items if p["station_id"] == station_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.pad(p) for p in page], limit, offset, total)


@bp.route("/deice-ops/pads/<pid>/take_out_of_service", methods=["POST"])
def take_out_of_service(pid):
    middleware.require_roles("StationAdmin")
    pad = db.pads.get(pid)
    if pad is None:
        raise errors.not_found("pad not found")
    if pad["status"] != "AVAILABLE":
        raise errors.invalid_state("pad must be AVAILABLE to take out of service")
    pad["status"] = "OUT_OF_SERVICE"
    pad["version"] += 1
    pad["updated_at"] = util.iso_now()
    return response.success_object(serializers.pad(pad), 200)
