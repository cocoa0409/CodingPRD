"""Battery routes — registration, lifecycle, SOH assessments."""

from flask import Blueprint, request

from db import DB, new_id
from errors import (
    ERR_BATTERY_RECALLED,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    raise_error,
)
from middleware import auth_required
from response import list_response, success_response
from services.audit import append_audit
from services.calculations import (
    cascade_stage_for_battery,
    create_soh_assessment,
)
from services.common import (
    bump_version,
    check_occ,
    get_body,
    get_or_404,
    get_pagination,
    init_common,
    optional_number,
    optional_string,
    paginate,
    require_number,
    require_string,
    sort_by_created_at_asc,
)
from services.lookups import (
    battery_model_by_code,
    charging_slot_for_battery,
    is_compatible,
)


bp = Blueprint("batteries", __name__, url_prefix="/swap-stations")


BATTERY_STATUSES = {"IDLE", "CHARGING", "IN_USE", "FAULT", "RETIRED", "RECYCLED", "IN_TRANSIT"}


# ---------------------------------------------------------------------------
# Battery lifecycle helpers — used here and from the swap-event/dispatch flows
# ---------------------------------------------------------------------------

def _new_battery_row(*, serial_number, battery_model_code, station_id,
                    warranty_expires_at, soc_pct, soh_pct) -> dict:
    row = {
        "id": new_id(),
        "serial_number": serial_number,
        "battery_model_code": battery_model_code,
        "station_id": station_id,
        "status": "IDLE",
        "soc_pct": float(soc_pct),
        "soh_pct": float(soh_pct),
        "soh_grade": "A",
        "cycle_count": 0,
        "cascade_stage": "NONE",
        "warranty_expires_at": warranty_expires_at,
        "recall_flag": False,
    }
    init_common(row)
    return row


# ---------------------------------------------------------------------------
# /batteries — register, list, get
# ---------------------------------------------------------------------------

@bp.route("/batteries", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_battery():
    body = get_body()
    serial_number = require_string(body, "serial_number", min_len=6, max_len=64)
    battery_model_code = require_string(body, "battery_model_code")
    station_id = require_string(body, "station_id")
    warranty_expires_at = require_string(body, "warranty_expires_at")

    if battery_model_by_code(battery_model_code) is None:
        raise_error(ERR_INVALID_INPUT, "battery_model_code does not exist")
    station = DB["stations"].get(station_id)
    if station is None:
        raise_error(ERR_INVALID_INPUT, "station_id does not exist")

    soc_pct = optional_number(body, "soc_pct", 0.0)
    soh_pct = optional_number(body, "soh_pct", 100.0)
    if not (0.0 <= soc_pct <= 100.0):
        raise_error(ERR_INVALID_INPUT, "soc_pct must be in [0, 100]")
    if not (0.0 <= soh_pct <= 100.0):
        raise_error(ERR_INVALID_INPUT, "soh_pct must be in [0, 100]")

    for b in DB["batteries"].values():
        if b.get("serial_number") == serial_number:
            raise_error(ERR_DUPLICATE_RESOURCE, "Battery serial_number already exists")

    row = _new_battery_row(
        serial_number=serial_number,
        battery_model_code=battery_model_code,
        station_id=station_id,
        warranty_expires_at=warranty_expires_at,
        soc_pct=soc_pct,
        soh_pct=soh_pct,
    )
    DB["batteries"][row["id"]] = row

    station["idle_battery_count"] = int(station.get("idle_battery_count", 0)) + 1
    bump_version(station)
    return success_response(row, http_status=201)


@bp.route("/batteries", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator"])
def list_batteries():
    limit, offset = get_pagination()
    station_id = request.args.get("station_id")
    status_filter = request.args.get("status")
    battery_model_code = request.args.get("battery_model_code")
    vehicle_model_compatible = request.args.get("vehicle_model_compatible")

    if status_filter is not None and status_filter not in BATTERY_STATUSES:
        raise_error(ERR_INVALID_INPUT, "Unknown battery status filter")

    items = list(DB["batteries"].values())
    if station_id is not None:
        items = [b for b in items if b.get("station_id") == station_id]
    if status_filter is not None:
        items = [b for b in items if b.get("status") == status_filter]
    if battery_model_code is not None:
        items = [b for b in items if b.get("battery_model_code") == battery_model_code]
    if vehicle_model_compatible is not None:
        items = [b for b in items
                 if is_compatible(vehicle_model_compatible, b.get("battery_model_code"))]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)


@bp.route("/batteries/<battery_id>", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator", "Member"])
def get_battery(battery_id):
    row = get_or_404("batteries", battery_id)
    return success_response(row)


# ---------------------------------------------------------------------------
# /batteries/{id}/start-charging
# ---------------------------------------------------------------------------

@bp.route("/batteries/<battery_id>/start-charging", methods=["POST"])
@auth_required(["StationOperator"])
def start_charging(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)

    charging_slot_id = require_string(body, "charging_slot_id")
    slot = DB["charging_slots"].get(charging_slot_id)
    if slot is None:
        raise_error(ERR_NOT_FOUND, "charging slot not found")

    # State precondition first (priority 4 > recall, priority 6)
    if battery.get("status") != "IDLE":
        raise_error(ERR_INVALID_STATE, "Battery is not in IDLE")
    if slot.get("status") != "EMPTY" or slot.get("battery_id") is not None:
        raise_error(ERR_INVALID_STATE, "Charging slot is not EMPTY")
    if battery.get("recall_flag"):
        raise_error(ERR_BATTERY_RECALLED, "Battery has been recalled")

    # Side effects
    from_status = battery["status"]
    battery["status"] = "CHARGING"
    bump_version(battery)

    slot["status"] = "OCCUPIED"
    slot["battery_id"] = battery_id
    bump_version(slot)

    station = DB["stations"].get(slot["station_id"])
    if station is not None:
        station["idle_battery_count"] = max(0, int(station.get("idle_battery_count", 0)) - 1)
        station["charging_battery_count"] = int(station.get("charging_battery_count", 0)) + 1
        bump_version(station)

    append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, from_status, "CHARGING")
    return success_response(battery)


# ---------------------------------------------------------------------------
# /batteries/{id}/finish-charging
# ---------------------------------------------------------------------------

@bp.route("/batteries/<battery_id>/finish-charging", methods=["POST"])
@auth_required(["StationOperator"])
def finish_charging(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)

    soc_pct = require_number(body, "soc_pct")
    capacity_test_kwh = require_number(body, "capacity_test_kwh")
    internal_resistance_mohm = require_number(body, "internal_resistance_mohm")
    avg_temperature_c = require_number(body, "avg_temperature_c")

    if not (0.0 <= soc_pct <= 100.0):
        raise_error(ERR_INVALID_INPUT, "soc_pct must be in [0, 100]")
    if battery.get("status") != "CHARGING":
        raise_error(ERR_INVALID_STATE, "Battery is not CHARGING")
    if soc_pct < 95:
        raise_error(ERR_INVALID_STATE, "soc_pct must be >= 95 to finish charging")

    bm = battery_model_by_code(battery["battery_model_code"])
    if bm is None:
        raise_error(ERR_INVALID_INPUT, "Battery model missing")

    # 1. Increment cycle_count and overwrite soc_pct.
    battery["cycle_count"] = int(battery.get("cycle_count", 0)) + 1
    battery["soc_pct"] = float(soc_pct)

    # 2. Create SOHAssessment row — uses POST-increment cycle_count.
    assessment = create_soh_assessment(
        battery,
        {
            "capacity_test_kwh": float(capacity_test_kwh),
            "internal_resistance_mohm": float(internal_resistance_mohm),
            "avg_temperature_c": float(avg_temperature_c),
        },
        rated_capacity_kwh=bm["rated_capacity_kwh"],
    )

    # 3. Mirror the assessment outputs onto the battery. Use the row we
    # just inserted — a `max(... key=(created_at, id))` lookup would
    # collide on created_at when the test-only clock is pinned (every
    # row in this finish cycle shares the same server timestamp) and
    # could return an older row whose id sorts later.
    new_soh_pct = assessment["soh_pct_out"]
    new_grade = assessment["soh_grade_out"]
    battery["soh_pct"] = float(new_soh_pct)
    battery["soh_grade"] = new_grade

    slot = charging_slot_for_battery(battery_id)
    station = DB["stations"].get(slot["station_id"]) if slot is not None else None

    if new_grade == "RETIRED_EV":
        # Auto-transition CHARGING -> RETIRED.
        from_status = "CHARGING"
        battery["status"] = "RETIRED"
        if slot is not None:
            slot["status"] = "EMPTY"
            slot["battery_id"] = None
            bump_version(slot)
        if station is not None:
            station["charging_battery_count"] = max(
                0, int(station.get("charging_battery_count", 0)) - 1
            )
            bump_version(station)
        # Run cascade grading immediately to populate cascade_stage.
        battery["cascade_stage"] = cascade_stage_for_battery(battery)
        bump_version(battery)
        append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, from_status, "RETIRED")
    else:
        # Normal return CHARGING -> IDLE.
        from_status = "CHARGING"
        battery["status"] = "IDLE"
        if slot is not None:
            slot["status"] = "EMPTY"
            slot["battery_id"] = None
            bump_version(slot)
        if station is not None:
            station["charging_battery_count"] = max(
                0, int(station.get("charging_battery_count", 0)) - 1
            )
            station["idle_battery_count"] = int(station.get("idle_battery_count", 0)) + 1
            bump_version(station)
        bump_version(battery)
        append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, from_status, "IDLE")

    return success_response(battery)


# ---------------------------------------------------------------------------
# /batteries/{id}/report-fault and /clear-fault
# ---------------------------------------------------------------------------

@bp.route("/batteries/<battery_id>/report-fault", methods=["POST"])
@auth_required(["StationOperator"])
def report_fault(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)
    _ = optional_string(body, "reason")

    if battery.get("status") not in {"IDLE", "CHARGING"}:
        raise_error(ERR_INVALID_STATE, "Battery cannot be reported as faulty in current state")

    prev_status = battery["status"]
    station = DB["stations"].get(battery.get("station_id"))
    if prev_status == "CHARGING":
        slot = charging_slot_for_battery(battery_id)
        if slot is not None:
            slot["status"] = "EMPTY"
            slot["battery_id"] = None
            bump_version(slot)
        if station is not None:
            station["charging_battery_count"] = max(
                0, int(station.get("charging_battery_count", 0)) - 1
            )
            bump_version(station)
    elif prev_status == "IDLE" and station is not None:
        station["idle_battery_count"] = max(0, int(station.get("idle_battery_count", 0)) - 1)
        bump_version(station)

    battery["status"] = "FAULT"
    bump_version(battery)
    append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, prev_status, "FAULT")
    return success_response(battery)


@bp.route("/batteries/<battery_id>/clear-fault", methods=["POST"])
@auth_required(["StationOperator"])
def clear_fault(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)

    if battery.get("status") != "FAULT":
        raise_error(ERR_INVALID_STATE, "Battery is not in FAULT")
    if battery.get("recall_flag"):
        raise_error(ERR_BATTERY_RECALLED, "Battery has been recalled")

    battery["status"] = "IDLE"
    station = DB["stations"].get(battery.get("station_id"))
    if station is not None:
        station["idle_battery_count"] = int(station.get("idle_battery_count", 0)) + 1
        bump_version(station)
    bump_version(battery)
    append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, "FAULT", "IDLE")
    return success_response(battery)


# ---------------------------------------------------------------------------
# /batteries/{id}/grade-cascade and /recycle
# ---------------------------------------------------------------------------

@bp.route("/batteries/<battery_id>/grade-cascade", methods=["POST"])
@auth_required(["PlatformAdmin"])
def grade_cascade(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)

    if battery.get("status") != "RETIRED":
        raise_error(ERR_INVALID_STATE, "Battery must be RETIRED")
    if battery.get("cascade_stage") != "NONE":
        raise_error(ERR_INVALID_STATE, "Cascade stage already assigned")

    battery["cascade_stage"] = cascade_stage_for_battery(battery)
    bump_version(battery)
    return success_response(battery)


@bp.route("/batteries/<battery_id>/recycle", methods=["POST"])
@auth_required(["PlatformAdmin"])
def recycle_battery(battery_id):
    battery = get_or_404("batteries", battery_id)
    body = get_body()
    check_occ(battery, body)

    if battery.get("status") != "RETIRED":
        raise_error(ERR_INVALID_STATE, "Battery must be RETIRED")
    if battery.get("cascade_stage") != "END_OF_LIFE":
        raise_error(ERR_INVALID_STATE, "Cascade stage must be END_OF_LIFE to recycle")

    prev = battery["status"]
    battery["status"] = "RECYCLED"
    battery["station_id"] = None
    bump_version(battery)
    append_audit("BATTERY_STATUS_CHANGE", "Battery", battery_id, prev, "RECYCLED")
    # External RECYCLE_HANDOVER event is a no-op mock.
    return success_response(battery)


# ---------------------------------------------------------------------------
# /batteries/{id}/soh-assessments
# ---------------------------------------------------------------------------

@bp.route("/batteries/<battery_id>/soh-assessments", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator"])
def list_soh_assessments(battery_id):
    get_or_404("batteries", battery_id)
    limit, offset = get_pagination()
    items = [r for r in DB["soh_assessments"].values() if r["battery_id"] == battery_id]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)
