"""PRD 3.8 -- plant lines and the fabrication lots that occupy their windows."""

from datetime import timedelta

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import domain
from store import db, new_row, now, now_iso, ordered, touch

bp = Blueprint("production", __name__)


@bp.route("/production-lines", methods=["POST"])
@roles_required("PlatformAdmin")
def create_production_line():
    data = V.body()
    code = V.get_string(data, "code", min_len=2, max_len=16)
    name = V.get_string(data, "name", min_len=1)
    line_type = V.get_enum(data, "line_type", C.LINE_TYPES)
    buffer_minutes = V.get_int(
        data,
        "changeover_buffer_minutes",
        required=False,
        default=C.DEFAULT_CHANGEOVER_BUFFER_MINUTES,
        minimum=0,
    )

    for existing in db.production_lines.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE")

    row = new_row(
        {
            "code": code,
            "name": name,
            "line_type": line_type,
            "changeover_buffer_minutes": buffer_minutes,
        }
    )
    db.production_lines[row["id"]] = row
    return object_response(S.production_line_out(row), 201)


@bp.route("/production-lines/<line_id>", methods=["GET"])
@roles_required(ANY)
def read_production_line(line_id):
    return object_response(S.production_line_out(domain.get_production_line(line_id)))


@bp.route("/production-lots", methods=["POST"])
@roles_required("ProductionPlanner")
def create_production_lot():
    data = V.body()
    order_id = V.get_string(data, "order_id")
    line_id = V.get_string(data, "line_id")
    lot_type = V.get_enum(data, "lot_type", C.LOT_TYPES)
    paint_color = V.get_enum(data, "paint_color", C.COLORS)
    window_start, window_start_raw = V.get_datetime(data, "window_start")
    window_end, window_end_raw = V.get_datetime(data, "window_end")

    order = domain.get_order(order_id)
    line = domain.get_production_line(line_id)

    # Band 10.
    if order["production_status"] not in ("PROD_RELEASED", "PROD_IN_FABRICATION"):
        raise ApiError("ERR_ORDER_NOT_RELEASED")

    # Band 12 -- lot type against line type, then paint colour.
    if C.LINE_TYPE_FOR_LOT_TYPE[lot_type] != line["line_type"]:
        raise ApiError("ERR_LOT_TYPE_LINE_MISMATCH")
    if lot_type == "PANEL_RUN":
        config = db.configurations.get(order["configuration_id"])
        if config is None:
            raise ApiError("ERR_CONFIGURATION_NOT_FOUND")
        if paint_color != config["panel_color"]:
            raise ApiError("ERR_PAINT_COLOR_MISMATCH")

    # Band 13 -- half-open window, so the end must be strictly after the start.
    if not window_end > window_start:
        raise ApiError("ERR_INVALID_WINDOW_RANGE")
    if window_start < now():
        raise ApiError("ERR_LOT_WINDOW_IN_PAST")

    # Band 14 -- colour-dependent buffer on both sides, both comparisons strict.
    for occupant in domain.lots_of_line(line["id"]):
        if occupant["status"] not in C.ACTIVE_LOT_STATUSES:
            continue
        buffer = timedelta(
            minutes=0
            if occupant["paint_color"] == paint_color
            else line["changeover_buffer_minutes"]
        )
        if (
            window_start < occupant["_window_end_dt"] + buffer
            and occupant["_window_start_dt"] < window_end + buffer
        ):
            raise ApiError("ERR_LINE_WINDOW_CONFLICT")

    row = new_row(
        {
            "order_id": order["id"],
            "line_id": line["id"],
            "lot_type": lot_type,
            "paint_color": paint_color,
            "window_start": window_start_raw,
            "window_end": window_end_raw,
            "_window_start_dt": window_start,
            "_window_end_dt": window_end,
            "status": "SCHEDULED",
            "completed_at": None,
        }
    )
    db.production_lots[row["id"]] = row

    domain.production_status_rollup(order)
    touch(order)
    return object_response(S.production_lot_out(row), 201)


@bp.route("/production-lots/<lot_id>", methods=["GET"])
@roles_required(ANY)
def read_production_lot(lot_id):
    return object_response(S.production_lot_out(domain.get_production_lot(lot_id)))


@bp.route("/production-lots", methods=["GET"])
@roles_required(ANY)
def list_production_lots():
    order_id = request.args.get("order_id")
    line_id = request.args.get("line_id")
    status = request.args.get("status")

    def predicate(row):
        if order_id is not None and row["order_id"] != order_id:
            return False
        if line_id is not None and row["line_id"] != line_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.production_lots, predicate), S.production_lot_out)


@bp.route("/production-lots/<lot_id>/complete", methods=["POST"])
@roles_required("ProductionPlanner")
def complete_production_lot(lot_id):
    lot = domain.get_production_lot(lot_id)

    if lot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    order = db.orders.get(lot["order_id"])
    if order is None:
        raise ApiError("ERR_ORDER_NOT_FOUND")
    if order["production_status"] not in ("PROD_RELEASED", "PROD_IN_FABRICATION"):
        raise ApiError("ERR_ORDER_NOT_RELEASED")

    lot["status"] = "COMPLETE"
    lot["completed_at"] = now_iso()
    touch(lot)

    domain.production_status_rollup(order)
    touch(order)
    return object_response(S.production_lot_out(lot))


@bp.route("/production-lots/<lot_id>/cancel", methods=["POST"])
@roles_required("ProductionPlanner")
def cancel_production_lot(lot_id):
    lot = domain.get_production_lot(lot_id)

    if lot["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    lot["status"] = "CANCELLED"
    touch(lot)

    order = db.orders.get(lot["order_id"])
    if order is not None:
        domain.production_status_rollup(order)
        touch(order)
    return object_response(S.production_lot_out(lot))
