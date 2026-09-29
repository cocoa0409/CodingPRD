"""§3.2 GlassLot routes."""

from decimal import Decimal

from flask import Blueprint

import calc
import logic
from common import (ALL_ROLES, authenticate, filt, get_body, ok, ok_list,
                    pagination, path_row, v_enum, v_int, v_num, v_str)
from errors import ApiError
from store import ordered, store

bp = Blueprint("glass", __name__)


def _effective(lot):
    lot["effective_index_homogeneity_grade"] = (
        lot["measured_index_homogeneity_grade"]
        or lot["declared_index_homogeneity_grade"])
    lot["effective_striae_grade"] = (
        lot["measured_striae_grade"] or lot["declared_striae_grade"])


@bp.post("/optics/glass-lots")
def create_lot():
    authenticate(["ProcurementOfficer"])
    body = get_body()

    lot_code = v_str(body, "lot_code", True, min_len=1, max_len=40)
    glass_type = v_str(body, "glass_type", True, min_len=1, max_len=30)
    melt_index = v_num(body, "melt_index_nd", False, Decimal("1.516800"),
                       ge="1.300000", le="2.200000")
    total_blanks = v_int(body, "total_blank_count", True, ge=1)
    declared_index = v_enum(body, "declared_index_homogeneity_grade",
                            calc.INDEX_HOMOGENEITY_GRADES, False, "H2")
    declared_striae = v_enum(body, "declared_striae_grade", calc.STRIAE_GRADES,
                             False, "A")
    thickness = v_num(body, "blank_center_thickness_um", False, Decimal("6200.0"), gt=0)

    for row in store.lots.values():
        if row["lot_code"] == lot_code:
            raise ApiError("ERR_DUPLICATE_LOT_CODE")

    lot = store.new_row()
    lot["lot_code"] = lot_code
    lot["glass_type"] = glass_type
    lot["melt_index_nd"] = melt_index
    lot["declared_index_homogeneity_grade"] = declared_index
    lot["declared_striae_grade"] = declared_striae
    lot["measured_index_homogeneity_grade"] = None
    lot["measured_striae_grade"] = None
    lot["effective_index_homogeneity_grade"] = declared_index
    lot["effective_striae_grade"] = declared_striae
    lot["certificate_reference"] = None
    lot["total_blank_count"] = total_blanks
    lot["reserved_blank_count"] = 0
    lot["consumed_blank_count"] = 0
    lot["scrapped_blank_count"] = 0
    lot["available_blank_count"] = total_blanks
    lot["blank_center_thickness_um"] = thickness
    lot["lot_status"] = "QUARANTINED"
    lot["block_reason"] = None
    store.lots[lot["id"]] = lot
    return ok(logic.ser_lot(lot), 201)


@bp.post("/optics/glass-lots/<row_id>/certification")
def certify_lot(row_id):
    authenticate(["ProcurementOfficer"])
    lot = path_row(store.lots, row_id, "ERR_GLASS_LOT_NOT_FOUND")
    body = get_body()

    measured_index = v_enum(body, "measured_index_homogeneity_grade",
                            calc.INDEX_HOMOGENEITY_GRADES, True)
    measured_striae = v_enum(body, "measured_striae_grade", calc.STRIAE_GRADES, True)
    certificate = v_str(body, "certificate_reference", True, min_len=1, max_len=200)

    if lot["lot_status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    lot["measured_index_homogeneity_grade"] = measured_index
    lot["measured_striae_grade"] = measured_striae
    lot["certificate_reference"] = certificate
    _effective(lot)
    lot["lot_status"] = "RELEASED"
    store.touch(lot)
    return ok(logic.ser_lot(lot))


@bp.post("/optics/glass-lots/<row_id>/block")
def block_lot(row_id):
    authenticate(["ProcurementOfficer", "QualityManager"])
    lot = path_row(store.lots, row_id, "ERR_GLASS_LOT_NOT_FOUND")
    body = get_body()

    reason = v_str(body, "block_reason", True, min_len=1, max_len=500)

    if lot["lot_status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    logic.block_lot_cascade(lot, reason)
    return ok(logic.ser_lot(lot))


@bp.get("/optics/glass-lots/<row_id>")
def get_lot(row_id):
    authenticate(ALL_ROLES)
    lot = path_row(store.lots, row_id, "ERR_GLASS_LOT_NOT_FOUND")
    return ok(logic.ser_lot(lot))


@bp.get("/optics/glass-lots")
def list_lots():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = ordered(list(store.lots.values()))
    for name in ("lot_status", "glass_type"):
        value = filt(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    return ok_list(rows, logic.ser_lot, limit, offset)
