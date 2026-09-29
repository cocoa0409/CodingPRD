"""Parts: opening, machining, QC and the rework loop (PRD 3.5)."""

from decimal import Decimal

from flask import Blueprint

import auth
import calc
import domain
import validate as v
from constants import (COMPONENT_STATUSES, GRADE_RANK, MAX_COMPONENT_REWORKS,
                       QC_HOLD_REASONS)
from envelope import object_response, paginate
from errors import ApiError
from serialize import component_view
from store import (BILLETS, COMPONENTS, LOTS, ORDERS, RESERVATIONS, ROOMS,
                   SPECS, STATIONS, new_record, touch)

bp = Blueprint("components", __name__)


def _climate_guard(station):
    room = ROOMS.get(station["room_id"])
    if room is None:
        return
    if room["climate_status"] == "QUARANTINED":
        raise ApiError("ERR_ROOM_QUARANTINED", "the room is quarantined")
    if room["climate_status"] != "IN_SPEC":
        raise ApiError("ERR_ROOM_CLIMATE_OUT_OF_SPEC",
                       "the room housing the station is out of spec")


def _order_of(component):
    if not component.get("build_order_id"):
        return None
    return ORDERS.get(component["build_order_id"])


@bp.post("/components")
def create_component():
    auth.require(auth.MACHINIST)
    body = v.body()
    spec_id = v.get_id(body, "spec_id")
    billet_id = v.get_id(body, "billet_id")
    order_id = v.get_id(body, "build_order_id", required=False)

    spec = v.fetch(SPECS, spec_id, "ERR_COMPONENT_SPEC_NOT_FOUND")
    billet = v.fetch(BILLETS, billet_id, "ERR_BILLET_NOT_FOUND")
    if order_id is not None:
        v.fetch(ORDERS, order_id, "ERR_BUILD_ORDER_NOT_FOUND")

    if billet["status"] == "QUARANTINED":
        raise ApiError("ERR_PROTECTED_SPECIES_QUARANTINED",
                       "the billet is impounded by a lot rejection")
    if billet["status"] != "AVAILABLE":
        raise ApiError("ERR_BILLET_STATE_INVALID",
                       "only an AVAILABLE billet may be committed to a part")

    lot = LOTS.get(billet["lot_id"])
    if lot is not None and lot["species_code"] not in spec["required_species_codes"]:
        raise ApiError("ERR_SPECIES_NOT_PERMITTED",
                       "the lot species is not permitted by the spec")
    if GRADE_RANK[billet["grade"]] < GRADE_RANK[spec["min_grade"]]:
        raise ApiError("ERR_GRADE_BELOW_MINIMUM",
                       "the billet grade ranks below the spec minimum")
    if lot is not None and lot["status"] != "RELEASED":
        raise ApiError("ERR_LOT_NOT_RELEASED", "the source lot is not RELEASED")

    rec = new_record(COMPONENTS, {
        "spec_id": spec_id,
        "billet_id": billet_id,
        "build_order_id": order_id,
        "measured_thickness_mm": None,
        "qc_hold_reason": "NONE",
        "rework_count": 0,
        "status": "ROUGH_SAWN",
    })
    domain.reserve_billet(billet)
    return object_response(component_view(rec), 201)


@bp.get("/components/<component_id>")
def read_component(component_id):
    auth.require_staff()
    return object_response(component_view(
        v.fetch(COMPONENTS, component_id, "ERR_COMPONENT_NOT_FOUND")))


@bp.get("/components")
def list_components():
    auth.require_staff()
    rows = v.apply_filters(list(COMPONENTS.values()), [
        ("spec_id", v.filter_value("spec_id")),
        ("billet_id", v.filter_value("billet_id")),
        ("build_order_id", v.filter_value("build_order_id")),
        ("status", v.filter_enum("status", COMPONENT_STATUSES)),
        ("qc_hold_reason", v.filter_enum("qc_hold_reason", QC_HOLD_REASONS)),
    ])
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return paginate(rows, component_view)


def _machine(component_id, station_type, from_states, to_state,
             check_build_stage):
    body = v.body()
    reservation_id = v.get_id(body, "station_reservation_id")
    thickness = v.get_dec(body, "measured_thickness_mm", gt=0)
    comp = v.fetch(COMPONENTS, component_id, "ERR_COMPONENT_NOT_FOUND")
    res = v.fetch(RESERVATIONS, reservation_id,
                  "ERR_STATION_RESERVATION_NOT_FOUND")
    first_pass = comp["status"] == "ROUGH_SAWN"
    if comp["status"] not in from_states:
        raise ApiError("ERR_COMPONENT_STATE_INVALID",
                       "the part is not in a machinable state")
    if res["status"] != "HELD":
        raise ApiError("ERR_RESERVATION_STATE_INVALID",
                       "the cited reservation is no longer HELD")
    station = STATIONS.get(res["station_id"])
    _climate_guard(station)
    order = _order_of(comp)
    if order is not None and order["build_stage"] == "COMPLIANCE_HOLD":
        raise ApiError("ERR_COMPLIANCE_HOLD_ACTIVE",
                       "the owning order is parked on a compliance hold")
    if res["component_id"] != comp["id"]:
        raise ApiError("ERR_RESERVATION_COMPONENT_MISMATCH",
                       "the reservation does not name this part")
    if station is not None and station["station_type"] != station_type:
        raise ApiError("ERR_STATION_TYPE_MISMATCH",
                       "the reservation is not on a %s" % station_type)
    if check_build_stage and order is not None and first_pass \
            and order["build_stage"] != "COMPONENTS_RELEASED":
        raise ApiError("ERR_BUILD_STAGE_INVALID",
                       "the owning order has not been released to the shop")

    comp["measured_thickness_mm"] = thickness
    comp["status"] = to_state
    touch(comp)
    res["status"] = "CONSUMED"
    touch(res)
    if station is not None:
        domain.station_consume(station, res["duration_minutes"])
    return object_response(component_view(comp))


@bp.post("/components/<component_id>/route")
def route_component(component_id):
    auth.require(auth.MACHINIST)
    return _machine(component_id, "CNC_ROUTER", ("ROUGH_SAWN", "REWORK"),
                    "CNC_ROUTED", check_build_stage=True)


@bp.post("/components/<component_id>/hand-shape")
def hand_shape_component(component_id):
    auth.require(auth.LUTHIER)
    return _machine(component_id, "HAND_SHAPING", ("CNC_ROUTED",),
                    "HAND_SHAPED", check_build_stage=False)


@bp.post("/components/<component_id>/qc")
def qc_component(component_id):
    auth.require(auth.QUALITY_INSPECTOR)
    body = v.body()
    verdict = v.get_enum(body, "verdict", ("ACCEPT", "HOLD"))
    hold_reason = v.get_enum(body, "hold_reason", QC_HOLD_REASONS,
                             required=False)
    comp = v.fetch(COMPONENTS, component_id, "ERR_COMPONENT_NOT_FOUND")
    if comp["status"] != "HAND_SHAPED":
        raise ApiError("ERR_COMPONENT_STATE_INVALID",
                       "quality control is only accepted from HAND_SHAPED")
    spec = SPECS.get(comp["spec_id"])
    if verdict == "ACCEPT":
        measured = comp.get("measured_thickness_mm")
        target = Decimal(spec["target_thickness_mm"])
        tolerance = Decimal(spec["thickness_tolerance_mm"])
        if measured is None or abs(Decimal(measured) - target) > tolerance:
            raise ApiError("ERR_THICKNESS_OUT_OF_TOLERANCE",
                           "the measured thickness is outside tolerance")
        comp["status"] = "ACCEPTED"
        comp["qc_hold_reason"] = "NONE"
    else:
        comp["status"] = "QC_HELD"
        comp["qc_hold_reason"] = hold_reason or "DIMENSION"
    touch(comp)
    order = _order_of(comp)
    if order is not None:
        calc.refresh_protected_species(order)
        touch(order)
    return object_response(component_view(comp))


@bp.post("/components/<component_id>/disposition")
def disposition_component(component_id):
    _, role = auth.require(auth.LUTHIER, auth.QUALITY_INSPECTOR)
    body = v.body()
    disposition = v.get_enum(body, "disposition", ("REWORK", "SCRAP"))
    if disposition == "REWORK" and role != auth.LUTHIER:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "only a Luthier may send a part back for rework")
    if disposition == "SCRAP" and role != auth.QUALITY_INSPECTOR:
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "only a QualityInspector may scrap a part")
    comp = v.fetch(COMPONENTS, component_id, "ERR_COMPONENT_NOT_FOUND")
    if comp["status"] != "QC_HELD":
        raise ApiError("ERR_COMPONENT_STATE_INVALID",
                       "only a QC_HELD part may be dispositioned")
    if disposition == "REWORK":
        if comp["qc_hold_reason"] == "PROTECTED_SPECIES":
            raise ApiError("ERR_REWORK_NOT_PERMITTED",
                           "impounded wood may only be destroyed")
        if comp["rework_count"] >= MAX_COMPONENT_REWORKS:
            raise ApiError("ERR_MAX_REWORK_EXCEEDED",
                           "the per-part rework ceiling has been reached")
        comp["status"] = "REWORK"
        comp["rework_count"] += 1
        comp["qc_hold_reason"] = "NONE"
    else:
        comp["status"] = "SCRAPPED"
        comp["qc_hold_reason"] = "NONE"
        billet = BILLETS.get(comp["billet_id"])
        if billet is not None and billet["status"] != "QUARANTINED":
            domain.scrap_billet(billet)
    touch(comp)
    order = _order_of(comp)
    if order is not None:
        calc.refresh_protected_species(order)
        touch(order)
    return object_response(component_view(comp))
