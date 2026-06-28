"""Compartment endpoints (PRD §3.2, §3.6).

Created nested under a TENDERED shipment; read flat. Adding a compartment bumps
the parent shipment's version (the OCC key for accept).
"""

from flask import Blueprint, request

from constants import IMPAIRMENTS
from db import store
from errors import err
from helpers import (
    get_compartment_or_404,
    get_shipment_or_404,
    pagination_params,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from services import (
    classify_impairment,
    compartment_view,
    provisional_degree_minutes,
    round_half_up_2dp,
)
from validators import as_int, as_string, get_body, require

bp = Blueprint("compartments", __name__)


@bp.route("/shipments/<sid>/compartments", methods=["POST"])
def create_compartment(sid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "PlatformAdmin"})
    shipment = get_shipment_or_404(sid)

    body = get_body(request)
    temp_lane_id = as_string(require(body, "temp_lane_id"), "temp_lane_id")
    ordinal = as_int(require(body, "ordinal"), "ordinal", minimum=1)

    # FK existence (priority 4)
    if temp_lane_id not in store.temp_lanes:
        raise err("ERR_FK_NOT_FOUND", "temp_lane_id does not resolve to a temp lane")

    # state: only while TENDERED (priority 5)
    if shipment["status"] != "TENDERED":
        raise err("ERR_INVALID_STATE", "Compartments may only be added while TENDERED")

    # ordinal uniqueness + range gate (priority 11).
    # Upper bound is the assigned reefer compartment_count when known, else 4.
    existing = [c for c in store.compartments.values() if c["shipment_id"] == sid]
    for c in existing:
        if c["ordinal"] == ordinal:
            raise err("ERR_DUPLICATE_ORDINAL", "ordinal already used on this shipment")

    upper = 4
    unit = store.reefer_units.get(shipment.get("reefer_unit_id"))
    if unit is not None:
        upper = unit["compartment_count"]
    if ordinal > upper:
        raise err("ERR_DUPLICATE_ORDINAL", "ordinal out of 1..compartment_count range")

    rec = {
        "shipment_id": sid,
        "temp_lane_id": temp_lane_id,
        "ordinal": ordinal,
        "door_open_events": 0,
        "degree_minutes_out": 0,
        "impairment": "NONE",
    }
    stamp_create(rec)
    store.compartments[rec["id"]] = rec

    # adding a compartment bumps the shipment version (PRD §3.2 / §2.7)
    touch(shipment)
    return object_response(compartment_view(rec), 201)


@bp.route("/compartments/<cid>", methods=["GET"])
def get_compartment(cid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_compartment_or_404(cid)
    return object_response(compartment_view(rec), 200)


@bp.route("/compartments", methods=["GET"])
def list_compartments():
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    shipment_id = request.args.get("shipment_id")
    temp_lane_id = request.args.get("temp_lane_id")
    impairment = request.args.get("impairment")
    if impairment is not None and impairment not in IMPAIRMENTS:
        raise err("ERR_INVALID_REQUEST", "Invalid impairment filter")

    records = list(store.compartments.values())
    if shipment_id is not None:
        records = [r for r in records if r["shipment_id"] == shipment_id]
    if temp_lane_id is not None:
        records = [r for r in records if r["temp_lane_id"] == temp_lane_id]

    # impairment filter compares against the live (computed) impairment
    def _live_imp(comp):
        view = compartment_view(comp)
        return view["impairment"]

    if impairment is not None:
        records = [r for r in records if _live_imp(r) == impairment]

    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return array_response([compartment_view(r) for r in page], limit, offset, total)


@bp.route("/compartments/<cid>/excursion-report", methods=["GET"])
def excursion_report(cid):
    _uid, role = authenticate()
    require_role(role, {"Shipper", "Carrier", "Driver", "ComplianceOfficer", "PlatformAdmin"})
    comp = get_compartment_or_404(cid)

    deg = provisional_degree_minutes(comp)
    flagged = sum(
        1
        for r in store.sensor_readings.values()
        if r["compartment_id"] == cid and r["kind"] == "TEMP" and r.get("excursion_flagged")
    )
    shipment = store.shipments.get(comp["shipment_id"])
    from services import _now_offset_min
    as_of = _now_offset_min(shipment)
    if as_of is None:
        as_of = 0
    return object_response(
        {
            "compartment_id": cid,
            "provisional_degree_minutes_out": round_half_up_2dp(deg),
            "excursion_flagged_count": flagged,
            "as_of_offset_min": as_of,
        },
        200,
    )
