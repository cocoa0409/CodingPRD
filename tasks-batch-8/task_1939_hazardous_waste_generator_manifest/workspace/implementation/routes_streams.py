"""WasteStream endpoints."""

from __future__ import annotations

from flask import Blueprint, request

from core import base_entity, bump, now_iso
from db import store
from errors import (
    ApiError,
    ERR_ALREADY_TERMINAL,
    ERR_STALE_VERSION,
    ERR_STREAM_HAS_OPEN_CONTAINERS,
    ERR_STREAM_NOT_HAZARDOUS,
    already_terminal,
    invalid_request,
    invalid_state,
    not_found,
)
from middleware import require_roles
from response import success_list, success_object
from validators import (
    opt_str,
    reject_unknown_fields,
    req_bool,
    req_enum,
    req_int,
    req_num,
    req_str,
    req_str_list,
    require_fields,
    require_object,
)

bp = Blueprint("streams", __name__)

ALL_ROLES = ("EHSManager", "WasteCoordinator", "ComplianceAuditor", "TransporterAgent", "TSDFAgent")

_PHYSICAL_STATES = {"LIQUID", "SOLID", "SLUDGE", "GAS"}


def _parse_pagination():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def stream_view(s: dict) -> dict:
    return dict(s)


@bp.route("/hazwaste/waste-streams", methods=["POST"])
def create_stream():
    user_id, _ = require_roles("WasteCoordinator")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {"site_id", "name", "waste_codes", "physical_state"}
    reject_unknown_fields(body, allowed)
    require_fields(body, ["site_id", "name", "waste_codes", "physical_state"])
    site_id = req_str(body, "site_id")
    name = req_str(body, "name")
    waste_codes = req_str_list(body, "waste_codes")
    physical_state = req_enum(body, "physical_state", _PHYSICAL_STATES)

    if site_id not in store.sites:
        raise not_found("site not found")

    s = base_entity()
    s.update(
        {
            "site_id": site_id,
            "name": name,
            "waste_codes": list(waste_codes),
            "physical_state": physical_state,
            "status": "DRAFT",
            "is_hazardous": None,
            "flash_point_c": None,
            "ph": None,
            "ldr_treatment_standard": None,
            "characterization_version": 0,
            "total_generated_kg": 0,
        }
    )
    store.streams[s["id"]] = s
    return success_object(stream_view(s), status=201)


@bp.route("/hazwaste/waste-streams", methods=["GET"])
def list_streams():
    require_roles(*ALL_ROLES)
    limit, offset = _parse_pagination()
    site_id = request.args.get("site_id")
    items = list(store.streams.values())
    if site_id is not None:
        items = [s for s in items if s["site_id"] == site_id]
    items.sort(key=lambda s: s["created_at"])
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([stream_view(s) for s in page], limit, offset, total)


@bp.route("/hazwaste/waste-streams/<streamId>", methods=["GET"])
def get_stream(streamId: str):
    require_roles(*ALL_ROLES)
    s = store.streams.get(streamId)
    if s is None:
        raise not_found("stream not found")
    return success_object(stream_view(s))


@bp.route("/hazwaste/waste-streams/<streamId>/characterize", methods=["POST"])
def characterize(streamId: str):
    user_id, _ = require_roles("WasteCoordinator")
    s = store.streams.get(streamId)
    if s is None:
        raise not_found("stream not found")
    body = require_object(request.get_json(silent=True) or {})
    allowed = {
        "is_hazardous",
        "waste_codes",
        "ldr_treatment_standard",
        "expected_waste_stream_version",
        "flash_point_c",
        "ph",
    }
    reject_unknown_fields(body, allowed)
    require_fields(body, ["is_hazardous", "waste_codes", "ldr_treatment_standard", "expected_waste_stream_version"])
    is_hazardous = req_bool(body, "is_hazardous")
    waste_codes = req_str_list(body, "waste_codes")
    ldr_treatment_standard = req_str(body, "ldr_treatment_standard")
    expected_version = req_int(body, "expected_waste_stream_version")
    flash_point_c = None
    ph = None
    if "flash_point_c" in body and body["flash_point_c"] is not None:
        flash_point_c = req_num(body, "flash_point_c")
    if "ph" in body and body["ph"] is not None:
        ph = req_num(body, "ph")
    if is_hazardous and flash_point_c is None:
        raise invalid_request("flash_point_c is required when is_hazardous is true")

    # OCC before state
    if s["version"] != expected_version:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_waste_stream_version does not match current version")

    # State: DRAFT or ACTIVE allowed
    if s["status"] == "RETIRED":
        raise already_terminal("stream is retired")
    if s["status"] not in ("DRAFT", "ACTIVE"):
        raise invalid_state(f"cannot characterize from status {s['status']}")

    s["is_hazardous"] = is_hazardous
    s["flash_point_c"] = flash_point_c
    s["ph"] = ph
    s["ldr_treatment_standard"] = ldr_treatment_standard
    s["waste_codes"] = list(waste_codes)
    s["characterization_version"] = s.get("characterization_version", 0) + 1
    s["status"] = "CHARACTERIZED"
    bump(s)
    return success_object(stream_view(s))


@bp.route("/hazwaste/waste-streams/<streamId>/activate", methods=["POST"])
def activate(streamId: str):
    user_id, _ = require_roles("EHSManager")
    s = store.streams.get(streamId)
    if s is None:
        raise not_found("stream not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if s["status"] == "RETIRED":
        raise already_terminal("stream is retired")
    if s["status"] != "CHARACTERIZED":
        raise invalid_state(f"cannot activate from status {s['status']}")
    if not s.get("is_hazardous"):
        raise ApiError(ERR_STREAM_NOT_HAZARDOUS, 409, "stream is not hazardous")

    s["status"] = "ACTIVE"
    bump(s)
    return success_object(stream_view(s))


@bp.route("/hazwaste/waste-streams/<streamId>/retire", methods=["POST"])
def retire(streamId: str):
    user_id, _ = require_roles("EHSManager")
    s = store.streams.get(streamId)
    if s is None:
        raise not_found("stream not found")
    body = request.get_json(silent=True) or {}
    if body:
        require_object(body)
        reject_unknown_fields(body, set())

    if s["status"] == "RETIRED":
        raise already_terminal("stream is retired")
    # Check open containers
    open_statuses = {"ACCUMULATING_AT_SATELLITE", "SATELLITE_LIMIT_EXCEEDED", "IN_CENTRAL_ACCUMULATION", "STAGED_FOR_SHIPMENT"}
    for c in store.containers.values():
        if c["waste_stream_id"] == s["id"] and c["status"] in open_statuses:
            raise ApiError(ERR_STREAM_HAS_OPEN_CONTAINERS, 409, "stream has open containers")

    s["status"] = "RETIRED"
    bump(s)
    return success_object(stream_view(s))
