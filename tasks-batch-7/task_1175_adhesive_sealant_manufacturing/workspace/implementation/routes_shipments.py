"""Shipment endpoints: build, lines, plan, confirm, dispatch, cancel, replan."""
from flask import Blueprint, request

from db import store
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_SHIPMENT_INVALID_STATE,
    ERR_SHIPMENT_BLOCKED_LINES, ERR_DUPLICATE_LOT_LINE, ERR_LOT_NOT_SHIPPABLE,
    ERR_LOT_ON_HOLD, ERR_FIFO_VIOLATION, ERR_INSUFFICIENT_LOT_STOCK,
    ERR_MIN_SHELF_LIFE_VIOLATION, ERR_HAZMAT_MODE_FORBIDDEN,
    ERR_AGREEMENT_NOT_ACTIVE, not_found,
)
from helpers import (
    ALL_ROLES, require_roles, body_json, ok, ok_list, pagination_params,
    f_str, f_int, f_enum, f_date,
)
from services import (
    new_entity, touch, get_shipment, get_lot, ser_shipment, sorted_rows,
    units_available, older_eligible_lot_with_stock, worst_hazmat_class,
    classify_line, LQ_MAX_UNIT_ML,
)

bp = Blueprint("shipments", __name__)

SHIPMENT_KINDS = ["SALE", "CONSIGNMENT", "CONSIGNMENT_REPLENISHMENT"]
TRANSPORT_MODES = ["ROAD", "AIR", "SEA"]
CONSIGNMENT_KINDS = ("CONSIGNMENT", "CONSIGNMENT_REPLENISHMENT")
CANCELLABLE = ("DRAFT", "PLANNED", "CONFIRMED", "EXCEPTION")


@bp.post("/api/shipments")
@require_roles("LogisticsCoordinator")
def create_shipment():
    b = body_json()
    kind = f_enum(b, "shipment_kind", SHIPMENT_KINDS)
    distributor_id = f_str(b, "distributor_id")
    mode = f_enum(b, "transport_mode", TRANSPORT_MODES)
    ship_date = f_date(b, "ship_date")
    agreement_id = b.get("agreement_id")
    if kind in CONSIGNMENT_KINDS:
        if agreement_id is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "agreement_id is required for consignment shipment kinds",
                400,
            )
        if not isinstance(agreement_id, str) or agreement_id == "":
            raise ApiError(ERR_INVALID_REQUEST, "Field agreement_id must be a non-empty string", 400)
    else:  # SALE
        if agreement_id is not None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "agreement_id must be absent for SALE shipments",
                400,
            )
    if distributor_id not in store.distributors:
        raise not_found("Distributor")
    if agreement_id is not None and agreement_id not in store.agreements:
        raise not_found("ConsignmentAgreement")
    s = new_entity()
    s.update({
        "shipment_kind": kind,
        "distributor_id": distributor_id,
        "agreement_id": agreement_id,
        "transport_mode": mode,
        "ship_date": ship_date,
        "lines": [],
        "hazmat_class": None,
        "auto_replenishment": False,
        "proposed_units": None,
        "status": "DRAFT",
    })
    store.shipments[s["id"]] = s
    return ok(ser_shipment(s), 201)


@bp.get("/api/shipments")
@require_roles(*ALL_ROLES)
def list_shipments():
    limit, offset = pagination_params()
    rows = list(store.shipments.values())
    did = request.args.get("distributor_id")
    aid = request.args.get("agreement_id")
    kind = request.args.get("shipment_kind")
    status = request.args.get("status")
    if did is not None:
        rows = [s for s in rows if s["distributor_id"] == did]
    if aid is not None:
        rows = [s for s in rows if s["agreement_id"] == aid]
    if kind is not None:
        rows = [s for s in rows if s["shipment_kind"] == kind]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return ok_list([ser_shipment(s) for s in sorted_rows(rows)], limit, offset)


@bp.get("/api/shipments/<sid>")
@require_roles(*ALL_ROLES)
def get_one_shipment(sid):
    return ok(ser_shipment(get_shipment(sid)), 200)


@bp.post("/api/shipments/<sid>/lines")
@require_roles("LogisticsCoordinator")
def add_line(sid):
    b = body_json()
    lot_id = f_str(b, "lot_id")
    units = f_int(b, "units", lo=1)
    s = get_shipment(sid)
    lot = get_lot(lot_id)
    # state: shipment accepts lines only in DRAFT or EXCEPTION
    if s["status"] not in ("DRAFT", "EXCEPTION"):
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE,
            "Lines may be added only in DRAFT or EXCEPTION",
            409,
        )
    # state: lot shippability (released + strictly-unexpired), then hold
    if (lot["qa_status"] != "RELEASED" or lot["expiry_date"] is None
            or not (lot["expiry_date"] > s["ship_date"])):
        raise ApiError(
            ERR_LOT_NOT_SHIPPABLE,
            "Lot is not RELEASED or its expiry_date is not strictly after ship_date",
            409,
        )
    if lot["hold_status"] != "CLEAR":
        raise ApiError(ERR_LOT_ON_HOLD, "Lot hold_status must be CLEAR", 409)
    # constraint: at most one line per lot per shipment
    if any(ln["lot_id"] == lot_id for ln in s["lines"]):
        raise ApiError(ERR_DUPLICATE_LOT_LINE, "The lot already has a line on this shipment", 409)
    # constraint: strict FIFO — an older eligible lot with stock blocks a newer one
    if older_eligible_lot_with_stock(lot, s["ship_date"]) is not None:
        raise ApiError(
            ERR_FIFO_VIOLATION,
            "An older eligible lot of the same formulation still has available units",
            409,
        )
    # referential: stock sufficiency
    if units > units_available(lot):
        raise ApiError(ERR_INSUFFICIENT_LOT_STOCK, "units exceed the lot's units_available", 409)
    s["lines"].append({"lot_id": lot_id, "units": units})
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/lines/<lid>/remove")
@require_roles("LogisticsCoordinator")
def remove_line(sid, lid):
    body_json()
    s = get_shipment(sid)
    lot = get_lot(lid)
    if s["status"] not in ("DRAFT", "EXCEPTION"):
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE,
            "Lines may be removed only in DRAFT or EXCEPTION",
            409,
        )
    if not any(ln["lot_id"] == lid for ln in s["lines"]):
        raise not_found("Shipment line")
    s["lines"] = [ln for ln in s["lines"] if ln["lot_id"] != lid]
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/plan")
@require_roles("LogisticsCoordinator")
def plan_shipment(sid):
    body_json()
    s = get_shipment(sid)
    if s["status"] != "DRAFT":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, "plan requires DRAFT", 409)
    if not s["lines"]:
        raise ApiError(ERR_INVALID_REQUEST, "Shipment must have at least one line", 400)
    s["hazmat_class"] = worst_hazmat_class(s)
    s["status"] = "PLANNED"
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/confirm")
@require_roles("LogisticsCoordinator")
def confirm_shipment(sid):
    body_json()
    s = get_shipment(sid)
    if s["status"] != "PLANNED":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, "confirm requires PLANNED", 409)
    if not s["lines"]:
        raise ApiError(ERR_INVALID_REQUEST, "Shipment must have at least one line", 400)
    # state gate: consignment kinds require an ACTIVE agreement
    if s["shipment_kind"] in CONSIGNMENT_KINDS:
        agreement = store.agreements.get(s["agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement must be ACTIVE", 409)
    # safety gate (before temporal): hazmat mode gate, AIR only
    if s["transport_mode"] == "AIR":
        for ln in s["lines"]:
            lot = store.lots[ln["lot_id"]]
            cls = classify_line(lot)
            if cls == "UN1133_CLASS3_PG_II" and (lot["unit_volume_ml"] or 0) > LQ_MAX_UNIT_ML:
                raise ApiError(
                    ERR_HAZMAT_MODE_FORBIDDEN,
                    "AIR shipment contains a PG_II line over 5000 ml",
                    422,
                )
            if cls == "UN1133_CLASS3_PG_III" and lot["pack_format"] == "DRUM":
                raise ApiError(
                    ERR_HAZMAT_MODE_FORBIDDEN,
                    "AIR shipment contains a PG_III DRUM line",
                    422,
                )
    # temporal gate: minimum remaining shelf life per line at ship_date
    for ln in s["lines"]:
        lot = store.lots[ln["lot_id"]]
        formulation = store.formulations[lot["formulation_id"]]
        min_days = formulation["min_remaining_shelf_life_days"]
        if s["shipment_kind"] in CONSIGNMENT_KINDS:
            agreement = store.agreements.get(s["agreement_id"])
            if agreement is not None and agreement["min_remaining_shelf_life_days"] is not None:
                min_days = agreement["min_remaining_shelf_life_days"]
        remaining = (lot["expiry_date"] - s["ship_date"]).days
        if remaining < min_days:
            raise ApiError(
                ERR_MIN_SHELF_LIFE_VIOLATION,
                "Remaining shelf life is below the applicable minimum",
                422,
            )
    s["status"] = "CONFIRMED"
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/dispatch")
@require_roles("LogisticsCoordinator")
def dispatch_shipment(sid):
    body_json()
    s = get_shipment(sid)
    if s["status"] != "CONFIRMED":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, "dispatch requires CONFIRMED", 409)
    if s["shipment_kind"] in CONSIGNMENT_KINDS:
        agreement = store.agreements.get(s["agreement_id"])
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, "Agreement must be ACTIVE", 409)
    for ln in s["lines"]:
        lot = store.lots[ln["lot_id"]]
        lot["units_shipped"] += ln["units"]
        touch(lot)
        if s["shipment_kind"] in CONSIGNMENT_KINDS:
            row_key = f"{s['agreement_id']}|{ln['lot_id']}"
            row = next(
                (r for r in store.stock.values() if r["row_key"] == row_key), None
            )
            if row is None:
                row = new_entity()
                row.update({
                    "agreement_id": s["agreement_id"],
                    "lot_id": ln["lot_id"],
                    "qty_shipped": 0,
                    "qty_consumed": 0,
                    "qty_returned": 0,
                    "qty_on_hand": 0,
                    "row_key": row_key,
                })
                store.stock[row["id"]] = row
            row["qty_shipped"] += ln["units"]
            row["qty_on_hand"] += ln["units"]
            touch(row)
    s["status"] = "DISPATCHED"
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/cancel")
@require_roles("LogisticsCoordinator")
def cancel_shipment(sid):
    body_json()  # optional reason accepted and not persisted
    s = get_shipment(sid)
    if s["status"] not in CANCELLABLE:
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE,
            "cancel requires DRAFT, PLANNED, CONFIRMED, or EXCEPTION",
            409,
        )
    s["status"] = "CANCELLED"
    touch(s)
    return ok(ser_shipment(s), 200)


@bp.post("/api/shipments/<sid>/replan")
@require_roles("LogisticsCoordinator")
def replan_shipment(sid):
    body_json()
    s = get_shipment(sid)
    if s["status"] != "EXCEPTION":
        raise ApiError(ERR_SHIPMENT_INVALID_STATE, "replan requires EXCEPTION", 409)
    for ln in s["lines"]:
        lot = store.lots[ln["lot_id"]]
        if lot["hold_status"] != "CLEAR":
            raise ApiError(
                ERR_SHIPMENT_BLOCKED_LINES,
                "A line still references a lot whose hold_status is not CLEAR",
                409,
            )
    s["hazmat_class"] = worst_hazmat_class(s)
    s["status"] = "PLANNED"
    touch(s)
    return ok(ser_shipment(s), 200)
