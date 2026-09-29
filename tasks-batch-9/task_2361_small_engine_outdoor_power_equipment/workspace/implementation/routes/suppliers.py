"""Supplier quality, incoming inspection and deviation acceptance."""

from collections import OrderedDict

from flask import Blueprint

import calc
import store
import svc
import validation as v
from auth import endpoint, READ_ROLES, user_id
from errors import ApiError
from response import list_response, object_response
from store import db, set_fields

bp = Blueprint("suppliers", __name__)

COMPONENT_CATEGORIES = ("CARBURETOR", "IGNITION", "CASTING")
LOT_STATUSES = ("RECEIVED", "ACCEPTED", "REJECTED", "DEVIATION_ACCEPTED", "QUARANTINED")


@bp.route("/suppliers", methods=["POST"])
@endpoint(["PlantAdmin"])
def create_supplier():
    payload = v.body()
    supplier_code = v.string_field(payload, "supplier_code", 1, 30)
    name = v.string_field(payload, "name", 1, 120)
    component_category = v.enum_field(payload, "component_category", COMPONENT_CATEGORIES)

    svc.require_unique(db.suppliers, "supplier_code", supplier_code)

    supplier = store.new_record(OrderedDict([
        ("supplier_code", supplier_code),
        ("name", name),
        ("component_category", component_category),
        ("criticality", "CRITICAL" if component_category == "CASTING" else "MAJOR"),
        ("approval_status", "APPROVED"),
        ("incoming_inspection_level", "NORMAL"),
        ("rolling_defect_ppm", 0),
        ("inspected_lot_count", 0),
        ("consecutive_accepted_lots", 0),
    ]))
    db.suppliers[supplier["id"]] = supplier
    return object_response(store.public(supplier), 201)


@bp.route("/suppliers/<supplier_id>/scorecard", methods=["GET"])
@endpoint(READ_ROLES)
def supplier_scorecard(supplier_id):
    supplier = svc.get_supplier(supplier_id)
    lots = svc.inspected_lots(supplier["id"])
    return object_response({
        "supplier_id": supplier["id"],
        "rolling_defect_ppm": supplier["rolling_defect_ppm"],
        "scorecard_average_ppm": calc.per_lot_average_ppm(lots),
        "inspected_lot_count": supplier["inspected_lot_count"],
        "consecutive_accepted_lots": supplier["consecutive_accepted_lots"],
        "approval_status": supplier["approval_status"],
        "incoming_inspection_level": supplier["incoming_inspection_level"],
        "criticality": supplier["criticality"],
    }, 200)


@bp.route("/component-lots", methods=["POST"])
@endpoint(["QualityEngineer"])
def receive_lot():
    payload = v.body()
    supplier_id = v.id_field(payload, "supplier_id")
    lot_code = v.string_field(payload, "lot_code", 1, 30)
    lot_quantity = v.int_field(payload, "lot_quantity", 1, 100000)

    supplier = svc.get_supplier(supplier_id)
    svc.require_unique(db.component_lots, "lot_code", lot_code,
                       "supplier_id", supplier["id"])
    if supplier["approval_status"] == "SUSPENDED":
        raise ApiError(
            "ERR_SUPPLIER_SUSPENDED",
            "No lot may be received from a SUSPENDED supplier.",
        )

    level = supplier["incoming_inspection_level"]
    sample_size, acceptance_number = calc.lot_sample_plan(
        lot_quantity, level, supplier["criticality"]
    )

    lot = store.new_record(OrderedDict([
        ("supplier_id", supplier["id"]),
        ("lot_code", lot_code),
        ("lot_quantity", lot_quantity),
        ("component_category", supplier["component_category"]),
        ("inspection_level_at_receipt", level),
        ("sample_size", sample_size),
        ("acceptance_number", acceptance_number),
        ("defects_found", None),
        ("status", "RECEIVED"),
        ("accepted_qty", 0),
        ("consumed_qty", 0),
        ("remaining_qty", 0),
        ("defect_ppm", None),
        ("inspected_by_user_id", None),
        ("deviation_approved_by_user_id", None),
        ("deviation_flag", False),
    ]))
    db.component_lots[lot["id"]] = lot
    return object_response(store.public(lot), 201)


@bp.route("/component-lots/<lot_id>", methods=["GET"])
@endpoint(READ_ROLES)
def read_lot(lot_id):
    lot = svc.get_lot(lot_id)
    return object_response(store.public(lot), 200)


@bp.route("/component-lots", methods=["GET"])
@endpoint(READ_ROLES)
def list_lots():
    limit, offset = v.pagination()
    supplier_id = v.query_string("supplier_id")
    status = v.query_enum("status", LOT_STATUSES)
    category = v.query_enum("component_category", COMPONENT_CATEGORIES)
    rows = store.sort_created_asc(list(db.component_lots.values()))
    if supplier_id is not None:
        rows = [r for r in rows if r["supplier_id"] == supplier_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if category is not None:
        rows = [r for r in rows if r["component_category"] == category]
    page, total = v.paginate(rows, limit, offset)
    return list_response([store.public(r) for r in page], limit, offset, total)


@bp.route("/component-lots/<lot_id>/inspect", methods=["POST"])
@endpoint(["QualityEngineer"])
def inspect_lot(lot_id):
    payload = v.body()
    defects_found = v.int_field(payload, "defects_found", 0)

    lot = svc.get_lot(lot_id)
    if defects_found > (lot["sample_size"] or 0):
        v.bad("defects_found may not exceed the lot's sample_size.")
    if lot["status"] != "RECEIVED":
        raise ApiError(
            "ERR_LOT_STATE_INVALID",
            "Only a RECEIVED lot may be inspected.",
        )

    supplier = svc.get_supplier(lot["supplier_id"])
    accepted = defects_found <= lot["acceptance_number"]
    defect_ppm = calc.lot_defect_ppm(defects_found, lot["sample_size"])

    if accepted:
        accepted_qty = lot["lot_quantity"] - defects_found
        set_fields(
            lot,
            defects_found=defects_found,
            status="ACCEPTED",
            accepted_qty=accepted_qty,
            remaining_qty=accepted_qty,
            defect_ppm=defect_ppm,
            inspected_by_user_id=user_id(),
        )
    else:
        set_fields(
            lot,
            defects_found=defects_found,
            status="REJECTED",
            accepted_qty=0,
            remaining_qty=0,
            defect_ppm=defect_ppm,
            inspected_by_user_id=user_id(),
        )

    previous_status = supplier["approval_status"]
    streak = (supplier["consecutive_accepted_lots"] or 0) + 1 if accepted else 0
    rolling = calc.pooled_ppm(svc.inspected_lots(supplier["id"]))
    counted = (supplier["inspected_lot_count"] or 0) + 1

    if previous_status == "SUSPENDED":
        # SUSPENDED is terminal; the ladder never runs on such a supplier.
        set_fields(
            supplier,
            inspected_lot_count=counted,
            consecutive_accepted_lots=streak,
            rolling_defect_ppm=rolling,
        )
    else:
        approval_status, level = calc.inspection_ladder(rolling, streak)
        set_fields(
            supplier,
            approval_status=approval_status,
            incoming_inspection_level=level,
            rolling_defect_ppm=rolling,
            inspected_lot_count=counted,
            consecutive_accepted_lots=streak,
        )
        if approval_status != previous_status and approval_status in ("PROBATION", "SUSPENDED"):
            svc.quarantine_cascade(supplier, lot["id"])

    return object_response(store.public(lot), 200)


@bp.route("/component-lots/<lot_id>/deviation-accept", methods=["POST"])
@endpoint(["ComplianceOfficer"])
def deviation_accept_lot(lot_id):
    v.body()
    lot = svc.get_lot(lot_id)
    if lot["status"] not in ("REJECTED", "QUARANTINED"):
        raise ApiError(
            "ERR_LOT_STATE_INVALID",
            "Only a REJECTED or QUARANTINED lot may be deviation-accepted.",
        )
    if lot["inspected_by_user_id"] is not None and lot["inspected_by_user_id"] == user_id():
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The approving operator may not be the inspecting operator.",
        )
    if lot["component_category"] == "CASTING":
        raise ApiError(
            "ERR_SAFETY_CONTROL_REQUIRED",
            "A critical CASTING lot may never be deviation-accepted.",
        )

    accepted_qty = lot["lot_quantity"] - (lot["defects_found"] or 0)
    set_fields(
        lot,
        status="DEVIATION_ACCEPTED",
        accepted_qty=accepted_qty,
        remaining_qty=accepted_qty,
        deviation_approved_by_user_id=user_id(),
        deviation_flag=True,
    )
    return object_response(store.public(lot), 200)
