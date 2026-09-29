"""§3.3 / §3.7 WorkOrder routes (both parallel state dimensions)."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, filt, get_body, need_fk, occ, ok,
                    ok_list, pagination, path_row, v_fk, v_int, v_str)
from errors import ApiError
from store import ordered, store

bp = Blueprint("workorders", __name__)

CANCELLABLE = ["BLANKS_RESERVED", "GRINDING", "POLISHING", "FIGURING",
               "FIGURE_ACCEPTED", "HELD"]
POST_RELEASE_SCRAPPABLE = ["FIGURE_ACCEPTED", "COATED", "RELEASED_TO_ASSEMBLY"]
SCRAP_REASONS = ["LATENT_SUBSURFACE_DEFECT", "ASSEMBLY_DAMAGE"]


@bp.post("/optics/work-orders")
def create_work_order():
    authenticate(["ProcessTechnician"])
    body = get_body()

    # priority 4 — body foreign keys, in the endpoint's declared field order
    design = v_fk(body, "design_id", store.designs, "ERR_DESIGN_NOT_FOUND")
    lot = v_fk(body, "glass_lot_id", store.lots, "ERR_GLASS_LOT_NOT_FOUND")

    # priority 5 — field validation, in the endpoint's declared field order
    wo_code = v_str(body, "wo_code", False, None, min_len=1, max_len=40)
    design = need_fk(body, "design_id", design)
    lot = need_fk(body, "glass_lot_id", lot)
    element_count = v_int(body, "element_count", True, ge=1, le=12)

    # priority 6 — optimistic concurrency control on the lot
    occ(body, "expected_glass_lot_version", lot, "ERR_STALE_GLASS_LOT_VERSION")

    # priority 13 — both parents released
    if design["design_status"] != "RELEASED":
        raise ApiError("ERR_DESIGN_NOT_RELEASED")
    if lot["lot_status"] != "RELEASED":
        raise ApiError("ERR_GLASS_LOT_NOT_RELEASED")

    # priority 21 — substrate suitability
    if (calc.INDEX_HOMOGENEITY_RANK[lot["effective_index_homogeneity_grade"]]
            > calc.INDEX_HOMOGENEITY_RANK[design["min_index_homogeneity_grade"]]):
        raise ApiError("ERR_GLASS_GRADE_UNSUITABLE")
    if (calc.STRIAE_RANK[lot["effective_striae_grade"]]
            > calc.STRIAE_RANK[design["max_striae_grade"]]):
        raise ApiError("ERR_GLASS_GRADE_UNSUITABLE")
    if (Decimal(lot["blank_center_thickness_um"])
            < Decimal(design["min_center_thickness_um"])):
        raise ApiError("ERR_GLASS_GRADE_UNSUITABLE")

    # priority 26 — the lot must have the blanks
    spare, reserved = calc.reservation_sizing(element_count)
    if int(lot["available_blank_count"]) < reserved:
        raise ApiError("ERR_INSUFFICIENT_BLANKS")

    wo = store.new_row()
    wo["wo_code"] = wo_code
    wo["design_id"] = design["id"]
    wo["glass_lot_id"] = lot["id"]
    wo["element_count"] = element_count
    wo["spare_blank_count"] = spare
    wo["reserved_blank_count"] = reserved
    wo["blank_center_thickness_um"] = lot["blank_center_thickness_um"]
    wo["pinned_design_revision"] = int(design["design_revision"])
    wo["process_status"] = "BLANKS_RESERVED"
    wo["compliance_status"] = "UNCLASSIFIED"
    wo["figuring_iteration_count"] = 0
    wo["cumulative_removal_nm"] = Decimal("0")
    wo["remaining_center_thickness_um"] = lot["blank_center_thickness_um"]
    wo["hold_reason"] = None
    wo["scrap_reason"] = None
    wo["cancel_reason"] = None
    store.work_orders[wo["id"]] = wo

    logic.lot_reserve(lot, wo)
    return ok(logic.ser_work_order(wo), 201)


@bp.get("/optics/work-orders/<row_id>")
def get_work_order(row_id):
    authenticate(ALL_ROLES)
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")
    return ok(logic.ser_work_order(wo))


@bp.get("/optics/work-orders")
def list_work_orders():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.work_orders.values()))
    for name in ("design_id", "glass_lot_id", "process_status", "compliance_status"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_work_order, limit, offset)


@bp.get("/optics/work-orders/<row_id>/assembly-components")
def list_work_order_components(row_id):
    authenticate(ALL_ROLES)
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")
    limit, offset = pagination()
    rows = ordered([c for c in store.components.values()
                    if c["work_order_id"] == wo["id"]])
    value = filt("component_status")
    if value is not None:
        rows = [r for r in rows if r["component_status"] == value]
    return ok_list(rows, logic.ser_component, limit, offset)


@bp.post("/optics/work-orders/<row_id>/compliance-screen")
def compliance_screen(row_id):
    authenticate(["ExportComplianceOfficer"])
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")

    if wo["compliance_status"] != "UNCLASSIFIED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    gov = logic.governing_classification(wo["design_id"])
    if gov is None:
        raise ApiError("ERR_EXPORT_CLASSIFICATION_MISSING")

    if gov["classification_status"] == "LICENSE_REQUIRED":
        wo["compliance_status"] = "SCREENED"
    else:
        wo["compliance_status"] = "CLEARED"
    store.touch(wo)
    return ok(logic.ser_work_order(wo))


@bp.post("/optics/work-orders/<row_id>/release-to-assembly")
def release_to_assembly(row_id):
    authenticate(["ProcessTechnician"])
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")

    if wo["process_status"] != "COATED":
        raise ApiError("ERR_WORK_ORDER_NOT_IN_PROCESS")
    if wo["compliance_status"] != "CLEARED":
        raise ApiError("ERR_EXPORT_LICENSE_NOT_APPROVED")

    wo["process_status"] = "RELEASED_TO_ASSEMBLY"
    store.touch(wo)

    lot = store.lots.get(wo["glass_lot_id"])
    if lot is not None:
        logic.lot_consume(lot, wo)
    return ok(logic.ser_work_order(wo))


@bp.post("/optics/work-orders/<row_id>/scrap")
def scrap_work_order(row_id):
    authenticate(["QualityManager"])
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")
    body = get_body()

    reason = v_str(body, "scrap_reason", True, min_len=1, max_len=200)

    if wo["process_status"] not in POST_RELEASE_SCRAPPABLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    logic.scrap_work_order(wo, reason)
    return ok(logic.ser_work_order(wo))


@bp.post("/optics/work-orders/<row_id>/cancel")
def cancel_work_order(row_id):
    authenticate(["ProcessTechnician", "QualityManager"])
    wo = path_row(store.work_orders, row_id, "ERR_WORK_ORDER_NOT_FOUND")
    body = get_body()

    reason = v_str(body, "cancel_reason", False, None, min_len=1, max_len=500)

    if wo["process_status"] not in CANCELLABLE:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    logic.cancel_work_order_cascade(wo, reason)
    return ok(logic.ser_work_order(wo))
