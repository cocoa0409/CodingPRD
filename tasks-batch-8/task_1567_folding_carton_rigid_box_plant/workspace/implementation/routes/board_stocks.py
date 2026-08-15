"""BoardStock endpoints (PRD §2.7): lot registration and top-ups."""

from flask import Blueprint

import db
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    get_body,
    get_or_404,
    list_response,
    req_int,
    req_str,
    ser_board_stock,
)
from util import touch

bp = Blueprint("board_stocks", __name__)


@bp.post("/plant/board-stocks")
def create_board_stock():
    authenticate(("PlantAdmin",))
    data = get_body()
    substrate_code = req_str(data, "substrate_code")
    caliper_pts = req_int(data, "caliper_pts", 1)
    sheet_w_cin = req_int(data, "sheet_w_cin", 1)
    sheet_h_cin = req_int(data, "sheet_h_cin", 1)
    unit_cost_cents = req_int(data, "unit_cost_cents", 0)
    received_sheets = req_int(data, "received_sheets", 0)
    rec = db.new_record()
    rec.update({
        "substrate_code": substrate_code,
        "caliper_pts": caliper_pts,
        "sheet_w_cin": sheet_w_cin,
        "sheet_h_cin": sheet_h_cin,
        "unit_cost_cents": unit_cost_cents,
        "received_sheets": received_sheets,
        "reserved_sheets": 0,
        "consumed_sheets": 0,
    })
    db.board_stocks[rec["id"]] = rec
    return ok_object(ser_board_stock(rec), 201)


@bp.get("/plant/board-stocks")
def list_board_stocks():
    authenticate(ALL_ROLES)
    return list_response(
        db.board_stocks.values(),
        ser_board_stock,
        [("substrate_code", "substrate_code", "str"),
         ("caliper_pts", "caliper_pts", "int")],
    )


@bp.get("/plant/board-stocks/<stockId>")
def get_board_stock(stockId):
    authenticate(ALL_ROLES)
    return ok_object(ser_board_stock(get_or_404(db.board_stocks, stockId)))


@bp.post("/plant/board-stocks/<stockId>/receive")
def receive_board_stock(stockId):
    authenticate(("PlantAdmin",))
    rec = get_or_404(db.board_stocks, stockId)
    data = get_body()
    additional_sheets = req_int(data, "additional_sheets", 1)
    rec["received_sheets"] += additional_sheets
    touch(rec)
    return ok_object(ser_board_stock(rec))
