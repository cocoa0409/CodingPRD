"""SensorReading endpoints (PRD §3.5).

Append-only telemetry: TEMP / DOOR_OPEN / PRECOOL. Created nested under a
compartment, read flat. Strict shape rule + monotonic per-kind offset series.
"""

from flask import Blueprint, request

from constants import READING_KINDS
from db import store
from errors import err
from helpers import (
    get_compartment_or_404,
    get_sensor_reading_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create_event, touch
from response import array_response, object_response
from services import out_of_band_magnitude, recompute_posture_and_touch
from validators import as_enum, as_int, as_number, get_body, require

bp = Blueprint("readings", __name__)


@bp.route("/compartments/<cid>/readings", methods=["POST"])
def create_reading(cid):
    _uid, role = authenticate()
    require_role(role, {"Driver", "Carrier"})
    comp = get_compartment_or_404(cid)

    body = get_body(request)
    kind = as_enum(require(body, "kind"), "kind", READING_KINDS)
    offset_min = as_int(require(body, "offset_min"), "offset_min")
    has_temp = body.get("temp_c") is not None
    temp_c = None
    if has_temp:
        temp_c = as_number(body["temp_c"], "temp_c")

    # interval validity: non-negative offset (priority 13, ERR_INVALID_INTERVAL)
    if offset_min < 0:
        raise err("ERR_INVALID_INTERVAL", "offset_min must be >= 0")

    # window/uniqueness gates (priority 14/15) come before shape (priority 17)
    # per the validation priority ordering.
    same_kind_offsets = [
        r["offset_min"]
        for r in store.sensor_readings.values()
        if r["compartment_id"] == cid and r["kind"] == kind
    ]
    if same_kind_offsets and offset_min <= max(same_kind_offsets):
        raise err(
            "ERR_READING_OFFSET_DUPLICATE",
            "offset_min must be strictly greater than the latest same-kind offset",
        )

    # shape rule (priority 17, ERR_READING_SHAPE)
    if kind in ("TEMP", "PRECOOL"):
        if not has_temp:
            raise err("ERR_READING_SHAPE", "TEMP/PRECOOL reading requires temp_c")
    else:  # DOOR_OPEN
        if has_temp:
            raise err("ERR_READING_SHAPE", "DOOR_OPEN reading must omit temp_c")

    lane = store.temp_lanes.get(comp["temp_lane_id"])

    rec = {
        "compartment_id": cid,
        "kind": kind,
        "temp_c": temp_c,
        "offset_min": offset_min,
        "excursion_flagged": False,
    }

    # side effects
    if kind == "TEMP":
        out_of_band = lane is not None and out_of_band_magnitude(temp_c, lane) > 0
        rec["excursion_flagged"] = bool(out_of_band)

    stamp_create_event(rec)
    store.sensor_readings[rec["id"]] = rec

    if kind == "DOOR_OPEN":
        comp["door_open_events"] += 1
        touch(comp)

    # posture recompute side effect (TEMP and DOOR_OPEN). PRECOOL only enables
    # precool-verify; it does not alter posture but recomputing is harmless and
    # the spec ties posture recompute to TEMP/door events specifically.
    if kind in ("TEMP", "DOOR_OPEN"):
        shipment = store.shipments.get(comp["shipment_id"])
        if shipment is not None:
            recompute_posture_and_touch(shipment)

    return object_response(serialize(rec), 201)


@bp.route("/sensor-readings/<rid>", methods=["GET"])
def get_reading(rid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_sensor_reading_or_404(rid)
    return object_response(serialize(rec), 200)


@bp.route("/sensor-readings", methods=["GET"])
def list_readings():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    compartment_id = request.args.get("compartment_id")
    kind = request.args.get("kind")
    if kind is not None and kind not in READING_KINDS:
        raise err("ERR_INVALID_REQUEST", "Invalid kind filter")

    records = list(store.sensor_readings.values())
    if compartment_id is not None:
        records = [r for r in records if r["compartment_id"] == compartment_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
