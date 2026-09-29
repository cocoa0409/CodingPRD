"""FacilityRoom and FacilityAsset endpoints (PRD 3.3)."""
from flask import Blueprint

import calc
import cascades
from core import (ApiError, ROLE_COMPLIANCE_AUDITOR, ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER,
                 bad_request, body, created, days_between, find, get_or_404, new_record, now,
                 ok, opt_date, opt_int, opt_str, req_date, req_enum, req_int, req_str,
                 require, today, to_date, upd, view, where)

bp = Blueprint("facility", __name__)

ROOM_TYPES = ("STUDIO", "WEIGHT_FLOOR", "CARDIO_FLOOR", "WELLNESS_SUITE")
ASSET_TYPES = ("AED", "CARDIO", "STRENGTH")
EVENT_TYPES = ("AED_INSPECTION", "PREVENTIVE_SERVICE", "TAKE_OUT_OF_SERVICE", "REPAIR_COMPLETE")
PASS_SCORE = 85


@bp.post("/facility-rooms")
def create_room():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    data = body()
    contract_id = req_str(data, "contract_id")
    room_name = req_str(data, "room_name", 1, 120)
    room_type = req_enum(data, "room_type", ROOM_TYPES)
    max_occupancy = req_int(data, "max_occupancy", minimum=1)
    get_or_404("contract", contract_id)
    room = new_record("room", {
        "contract_id": contract_id,
        "room_name": room_name,
        "room_type": room_type,
        "max_occupancy": max_occupancy,
        "room_state": "OPEN",
        "last_inspection_on": None,
        "last_cleanliness_score": None,
        "open_deficiency_count": 0,
    })
    return created(view(room))


@bp.post("/facility-rooms/<rid>/inspections")
def record_inspection(rid):
    require(ROLE_SITE_MANAGER, ROLE_COMPLIANCE_AUDITOR)
    room = get_or_404("room", rid)
    data = body()
    inspection_on = req_date(data, "inspection_on")
    cleanliness_score = req_int(data, "cleanliness_score", 0, 100)
    deficiency_count = req_int(data, "deficiency_count", minimum=0)
    opt_str(data, "notes", 1, 2000)
    passed = cleanliness_score >= PASS_SCORE and deficiency_count == 0
    reopening = passed and room["room_state"] == "RESTRICTED"
    if reopening:
        contract = find("contract", room["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE", 409)
    upd(room, last_inspection_on=inspection_on, last_cleanliness_score=cleanliness_score,
        open_deficiency_count=deficiency_count)
    if reopening:
        upd(room, room_state="OPEN", open_deficiency_count=0)
    elif not passed and room["room_state"] == "OPEN":
        upd(room, room_state="RESTRICTED")
        cascades.cancel_room_lock_window_sessions(room, "FACILITY")
    # PRD 4: an inspection brings no new record into existence -- it moves the
    # room through its lifecycle, so the updated room is returned with 200.
    return ok(view(room))


@bp.post("/facility-assets")
def create_asset():
    require(ROLE_OPERATOR_ADMIN, ROLE_SITE_MANAGER)
    data = body()
    contract_id = req_str(data, "contract_id")
    room_id = req_str(data, "room_id")
    asset_type = req_enum(data, "asset_type", ASSET_TYPES)
    asset_tag = req_str(data, "asset_tag", 1, 80)
    service_interval_days = opt_int(data, "service_interval_days", 1, 365, default=90)
    pad_expiry_on = opt_date(data, "pad_expiry_on")
    battery_expiry_on = opt_date(data, "battery_expiry_on")
    last_inspection_on = opt_date(data, "last_inspection_on")
    last_service_on = opt_date(data, "last_service_on")
    if asset_type == "AED":
        if pad_expiry_on is None or battery_expiry_on is None:
            raise bad_request("a defibrillator requires pad_expiry_on and battery_expiry_on")
    else:
        if pad_expiry_on is not None or battery_expiry_on is not None:
            raise bad_request("only a defibrillator carries consumable expiry dates")
    get_or_404("contract", contract_id)
    room = get_or_404("room", room_id)
    if room["contract_id"] != contract_id:
        raise ApiError("ERR_CROSS_CONTRACT_REFERENCE", 422)
    for existing in where("asset", contract_id=contract_id):
        if existing["asset_tag"] == asset_tag:
            raise ApiError("ERR_ASSET_TAG_CONFLICT", 409)
    asset = new_record("asset", {
        "contract_id": contract_id,
        "room_id": room_id,
        "asset_type": asset_type,
        "asset_tag": asset_tag,
        "status": "IN_SERVICE",
        "readiness_status": "NOT_APPLICABLE",
        "pad_expiry_on": pad_expiry_on,
        "battery_expiry_on": battery_expiry_on,
        "service_interval_days": service_interval_days,
        "last_inspection_on": last_inspection_on,
        "last_service_on": last_service_on,
        "out_of_service_since": None,
        "out_of_service_days_current_period": 0,
    })
    asset["readiness_status"] = calc.aed_readiness_status(asset)
    return created(view(asset))


@bp.post("/facility-assets/<aid>/service-events")
def record_service_event(aid):
    require(ROLE_SITE_MANAGER, ROLE_OPERATOR_ADMIN)
    asset = get_or_404("asset", aid)
    data = body()
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    pad_expiry_on = opt_date(data, "pad_expiry_on")
    battery_expiry_on = opt_date(data, "battery_expiry_on")
    opt_str(data, "note", 1, 2000)
    status = asset["status"]
    if event_type == "AED_INSPECTION":
        fields = {"last_inspection_on": today().isoformat()}
        if pad_expiry_on is not None:
            fields["pad_expiry_on"] = pad_expiry_on
        if battery_expiry_on is not None:
            fields["battery_expiry_on"] = battery_expiry_on
        upd(asset, **fields)
    elif event_type == "PREVENTIVE_SERVICE":
        if status != "MAINTENANCE_DUE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
        upd(asset, status="IN_SERVICE", last_service_on=today().isoformat())
    elif event_type == "TAKE_OUT_OF_SERVICE":
        if status not in ("IN_SERVICE", "MAINTENANCE_DUE"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
        upd(asset, status="OUT_OF_SERVICE", out_of_service_since=now())
    else:
        if status != "OUT_OF_SERVICE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409)
        since = asset.get("out_of_service_since")
        accrued = 0
        if since is not None:
            accrued = max(0, days_between(today(), since.astimezone(now().tzinfo).date()))
        upd(asset, status="IN_SERVICE", last_service_on=today().isoformat(),
            out_of_service_since=None,
            out_of_service_days_current_period=(
                asset.get("out_of_service_days_current_period") or 0) + accrued)
    cascades.refresh_asset_readiness(asset)
    # PRD 4: a service event brings no new record into existence -- it moves the
    # asset through its lifecycle, so the updated asset is returned with 200.
    return ok(view(asset))
