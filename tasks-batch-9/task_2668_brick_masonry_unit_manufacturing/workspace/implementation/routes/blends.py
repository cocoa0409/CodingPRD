"""Shipped blends: opening, hand-picking, composing, certifying and rejecting."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, actor, endpoint
from errors import ApiError
from routes import apply_filters
from store import clock, clock_str, db, new_row, parse_dt, touch
from validation import bad, body, v_bool, v_id, v_int, v_num, v_str

from flask import Blueprint

bp = Blueprint("blends", __name__)

D = Decimal


def _profile_of(pairs):
    """Colour profile over [(lot, units)] — accumulate at full precision."""
    allocated = sum(int(u) for _lot, u in pairs)
    if allocated <= 0:
        return {
            "allocated_units": allocated,
            "weighted_color_index": None,
            "color_range_span": None,
            "dye_lot_count": 0,
        }
    acc = D("0")
    indices = []
    codes = set()
    for lot, units in pairs:
        index = D(lot["color_index"])
        acc += index * D(int(units))
        indices.append(index)
        codes.add(lot.get("dye_lot_code"))
    return {
        "allocated_units": allocated,
        "weighted_color_index": calc.rh(acc / D(allocated), 2),
        "color_range_span": calc.rh(max(indices) - min(indices), 2),
        "dye_lot_count": len(codes),
    }


def _allocated_pairs(blend):
    pairs = []
    for comp in svc.allocated_components(blend["id"]):
        lot = db.fired_lots.get(comp["fired_lot_id"])
        if lot is not None:
            pairs.append((lot, int(comp["units"])))
    return pairs


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
@bp.get("/blends/<bid>")
@endpoint(ALL_ROLES)
def get_blend(bid):
    return response.entity(svc.blend_or_404(bid))


@bp.get("/blends")
@endpoint(ALL_ROLES)
def list_blends():
    rows = apply_filters(db.blends.values(), {"order_id": "order_id", "status": "status"})
    return response.collection(rows)


@bp.get("/blends/<bid>/components")
@endpoint(ALL_ROLES)
def list_blend_components(bid):
    svc.blend_or_404(bid)
    rows = svc.components_of_blend(bid)
    return response.collection(apply_filters(rows, {"status": "status", "source": "source"}))


# --------------------------------------------------------------------------
# POST /orders/{id}/blends
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/blends")
@endpoint(["BlendTechnician"])
def open_blend(oid):
    order = svc.order_or_404(oid)
    payload = body()
    blend_code = v_str(payload, "blend_code")
    low = v_num(payload, "target_color_index_min", 2, minv="0.00", maxv="100.00")
    high = v_num(payload, "target_color_index_max", 2, minv="0.00", maxv="100.00")
    requested = v_int(payload, "requested_units", minv=1)
    if low >= high:
        raise bad("target_color_index_min must be strictly less than target_color_index_max.")
    if requested > int(order["requested_units"]):
        raise bad("requested_units may not exceed the order's requested_units.")

    if order["fulfillment_status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ORDER_STATE_INVALID", "The order's fulfillment_status is not ASSIGNED."
        )
    svc.require_unique(db.blends, "blend_code", blend_code)

    row = new_row(
        order_id=oid,
        blend_code=blend_code,
        target_color_index_min=low,
        target_color_index_max=high,
        target_color_index_midpoint=calc.rh((low + high) / D("2"), 2),
        requested_units=requested,
        allocated_units=0,
        weighted_color_index=None,
        color_range_span=None,
        dye_lot_count=0,
        panel_delta_e=None,
        composed_by_user_id=None,
        certified_by_user_id=None,
        certified_at=None,
        rejection_reason=None,
        rejection_count=0,
        status="DRAFT",
    )
    db.blends[row["id"]] = row

    order["fulfillment_status"] = "IN_BLENDING"
    touch(order)
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /blends/{id}/components
# --------------------------------------------------------------------------
@bp.post("/blends/<bid>/components")
@endpoint(["BlendTechnician"])
def allocate_component(bid):
    blend = svc.blend_or_404(bid)
    payload = body()
    fired_lot_id = v_id(payload, "fired_lot_id")
    units = v_int(payload, "units", minv=1)
    expected = v_int(payload, "expected_blend_version")

    lot = svc.lot_or_404(fired_lot_id)

    if expected != int(blend["version"]):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_blend_version does not match the blend's current version.",
        )

    order = db.orders.get(blend["order_id"])

    # PRD 3.7 carves QUARANTINED out of the ERR_FIRED_LOT_UNAVAILABLE trigger list.
    if lot["status"] == "QUARANTINED":
        raise ApiError("ERR_LOT_QUARANTINED", "The fired lot is QUARANTINED.")
    if (
        lot["status"] not in ("AVAILABLE", "RESERVED")
        or lot["grade"] != "ON_COLOR"
        or int(lot["available_units"]) < units
    ):
        raise ApiError("ERR_FIRED_LOT_UNAVAILABLE", "The fired lot is not allocatable.")
    if blend["status"] != "DRAFT":
        raise ApiError("ERR_BLEND_NOT_DRAFT", "The shipped blend is not DRAFT.")
    if calc.rank(lot["durability_grade"]) < calc.rank(order["durability_grade"]):
        raise ApiError(
            "ERR_DURABILITY_GRADE_NOT_MET",
            "The lot's durability grade ranks below the order's requirement.",
        )
    if (
        lot["color_family"] != order["color_family"]
        or lot["texture"] != order["texture"]
        or svc.plant_of_lot(lot) != order.get("plant_id")
    ):
        raise ApiError(
            "ERR_LOT_ATTRIBUTE_MISMATCH",
            "The lot does not match the order's colour family, texture or assigned plant.",
        )
    if int(blend["allocated_units"]) + units > int(blend["requested_units"]):
        raise ApiError(
            "ERR_BLEND_OVER_ALLOCATION",
            "The append would allocate more than the blend's requested units.",
        )

    svc.new_component(blend, lot, units, "MANUAL")
    svc.recompute_allocated_units(blend)
    touch(blend)
    return response.entity(blend)


# --------------------------------------------------------------------------
# POST /blends/{id}/compose
# --------------------------------------------------------------------------
@bp.post("/blends/<bid>/compose")
@endpoint(["BlendTechnician"])
def compose_blend(bid):
    blend = svc.blend_or_404(bid)
    payload = body()
    auto_fill = v_bool(payload, "auto_fill", default=False)

    pairs = _allocated_pairs(blend)
    for lot, _units in pairs:
        if lot["status"] == "QUARANTINED":
            raise ApiError("ERR_LOT_QUARANTINED", "A lot behind an allocation is QUARANTINED.")
    if blend["status"] != "DRAFT":
        raise ApiError("ERR_BLEND_NOT_DRAFT", "The shipped blend is not DRAFT.")
    for lot, _units in pairs:
        if lot["status"] != "RESERVED" or lot["grade"] != "ON_COLOR":
            raise ApiError(
                "ERR_FIRED_LOT_UNAVAILABLE",
                "Every allocated component's lot must be RESERVED and graded ON_COLOR.",
            )

    order = db.orders.get(blend["order_id"])
    plan = []
    shortfall = int(blend["requested_units"]) - int(blend["allocated_units"])
    if auto_fill and shortfall > 0:
        plan, shortfall = svc.autofill_plan(blend, order)

    projected = pairs + [(lot, units) for lot, units in plan]
    profile = _profile_of(projected)

    if (
        profile["color_range_span"] is not None
        and profile["color_range_span"] > calc.BLEND_SPAN_CEILING
    ):
        raise ApiError(
            "ERR_COLOR_RANGE_SPAN_EXCEEDED",
            "The blend's colour spread exceeds the shipped-blend span ceiling.",
        )
    if profile["allocated_units"] != int(blend["requested_units"]):
        raise ApiError(
            "ERR_INSUFFICIENT_BLEND_INVENTORY",
            "The composed blend is not exactly filled.",
        )

    svc.apply_autofill(blend, plan)
    blend["allocated_units"] = profile["allocated_units"]
    blend["weighted_color_index"] = profile["weighted_color_index"]
    blend["color_range_span"] = profile["color_range_span"]
    blend["dye_lot_count"] = profile["dye_lot_count"]
    blend["status"] = "COMPOSED"
    blend["composed_by_user_id"] = actor()
    touch(blend)
    return response.entity(blend)


# --------------------------------------------------------------------------
# POST /blends/{id}/certify
# --------------------------------------------------------------------------
@bp.post("/blends/<bid>/certify")
@endpoint(["QualityManager"])
def certify_blend(bid):
    blend = svc.blend_or_404(bid)

    if blend.get("composed_by_user_id") is not None and blend["composed_by_user_id"] == actor():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The certifier may not be the operator who composed the blend.",
        )

    pairs = _allocated_pairs(blend)
    for lot, _units in pairs:
        if lot["status"] == "QUARANTINED":
            raise ApiError("ERR_LOT_QUARANTINED", "A lot behind an allocation is QUARANTINED.")
    if blend["status"] != "COMPOSED":
        raise ApiError("ERR_BLEND_NOT_COMPOSED", "The shipped blend is not COMPOSED.")

    order = db.orders.get(blend["order_id"])
    profile = _profile_of(pairs)
    panel_delta_e = None

    if order.get("requires_panel_approval"):
        panels = [p for p in svc.panels_of_order(order["id"]) if p["status"] == "APPROVED"]
        if not panels:
            raise ApiError("ERR_PANEL_NOT_APPROVED", "The order has no APPROVED sample panel.")
        valid = []
        expired_any = False
        for panel in panels:
            expires_at = parse_dt(panel.get("expires_at"))
            if expires_at is not None and clock() >= expires_at:
                panel["status"] = "EXPIRED"
                touch(panel)
                expired_any = True
            else:
                valid.append(panel)
        if not valid:
            raise ApiError(
                "ERR_PANEL_APPROVAL_EXPIRED" if expired_any else "ERR_PANEL_NOT_APPROVED",
                "The approved sample panel has expired.",
            )
        panel = valid[0]

        klass = svc.equivalence_class(panel["formulation_id"])
        for lot, _units in pairs:
            if lot.get("source_formulation_id") not in klass:
                raise ApiError(
                    "ERR_DYE_LOT_MISMATCH",
                    "An allocated lot was fired outside the panel's equivalence class.",
                )
        panel_delta_e = calc.rh(
            abs(D(profile["weighted_color_index"]) - D(panel["approved_color_index"])), 2
        )
        if panel_delta_e > D(panel["tolerance_delta_e"]):
            raise ApiError(
                "ERR_PANEL_TOLERANCE_EXCEEDED",
                "The blend deviates from the approved panel by more than its tolerance.",
            )

    if (
        profile["color_range_span"] is not None
        and profile["color_range_span"] > calc.BLEND_SPAN_CEILING
    ):
        raise ApiError(
            "ERR_COLOR_RANGE_SPAN_EXCEEDED",
            "The blend's colour spread exceeds the shipped-blend span ceiling.",
        )

    blend["allocated_units"] = profile["allocated_units"]
    blend["weighted_color_index"] = profile["weighted_color_index"]
    blend["color_range_span"] = profile["color_range_span"]
    blend["dye_lot_count"] = profile["dye_lot_count"]
    blend["panel_delta_e"] = panel_delta_e
    blend["certified_by_user_id"] = actor()
    blend["certified_at"] = clock_str()
    blend["status"] = "CERTIFIED"
    touch(blend)
    return response.entity(blend)


# --------------------------------------------------------------------------
# POST /blends/{id}/reject
# --------------------------------------------------------------------------
@bp.post("/blends/<bid>/reject")
@endpoint(["QualityManager"])
def reject_blend(bid):
    blend = svc.blend_or_404(bid)
    payload = body()
    reason = v_str(payload, "rejection_reason")

    if blend["status"] != "COMPOSED":
        raise ApiError("ERR_BLEND_NOT_COMPOSED", "The shipped blend is not COMPOSED.")

    svc.reject_cascade(blend, reason)
    return response.entity(blend)
