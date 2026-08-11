"""Sale-day posture and the close cascade (PRD 3.2, 3.10)."""
from flask import Blueprint

import config
import serialize
from auth import actor
from bodyval import body, enum_field, path_row
from envelope import ok
from errors import fail
from gates import run_gates
from services.close import close_sale_day
from store import insert_versioned, touch

bp = Blueprint("sale_days", __name__)
ALL = config.ALL_ROLES

ADVANCE_EDGES = {
    ("SCHEDULED", "CHECK_IN_OPEN"),
    ("CHECK_IN_OPEN", "RINGING"),
    ("RINGING", "BIDDING_CLOSED"),
    ("BIDDING_CLOSED", "RINGING"),
    ("SCHEDULED", "CANCELLED"),
    ("CHECK_IN_OPEN", "CANCELLED"),
    ("RINGING", "CANCELLED"),
    ("BIDDING_CLOSED", "CANCELLED"),
}


@bp.post("/sale-barn/sale-days")
def create_sale_day():
    actor(["BarnAdmin"])
    data = body()
    row = insert_versioned("sale_days", {
        "sale_date": _require(data, "sale_date"),
        "barn_code": _require(data, "barn_code"),
        "barn_state_code": _require(data, "barn_state_code"),
        "status": "SCHEDULED",
        "next_ring_order": config.RING_ORDER_STEP,
        "reopen_count": 0,
    })
    return ok(serialize.sale_day(row), 201)


def _require(data, name):
    from bodyval import require
    return require(data, name, "string")


@bp.get("/sale-barn/sale-days/<sale_day_id>")
def read_sale_day(sale_day_id):
    actor(ALL)
    return ok(serialize.sale_day(path_row("sale_days", sale_day_id, "SaleDay")))


@bp.post("/sale-barn/sale-days/<sale_day_id>/advance")
def advance_sale_day(sale_day_id):
    actor(["BarnAdmin"])
    sale_day = path_row("sale_days", sale_day_id, "SaleDay")
    data = body()
    to_status = enum_field(data, "to_status", config.SALE_DAY_STATUSES)
    # G1 is not exempt anywhere: a cancelled day answers ERR_SALE_DAY_CANCELLED
    # even here. G2 exempts this endpoint so the day can be advanced around a
    # quarantined lot, and G3 exempts it too.
    run_gates("sale_days.advance", sale_day=sale_day)
    if (sale_day["status"], to_status) not in ADVANCE_EDGES:
        fail("ERR_INVALID_STATE")
    if sale_day["status"] == "BIDDING_CLOSED" and to_status == "RINGING":
        sale_day["reopen_count"] = sale_day["reopen_count"] + 1
    sale_day["status"] = to_status
    touch(sale_day)
    return ok(serialize.sale_day(sale_day))


@bp.post("/sale-barn/sale-days/<sale_day_id>/close")
def close(sale_day_id):
    actor(["SettlementClerk"])
    sale_day = path_row("sale_days", sale_day_id, "SaleDay")
    run_gates("sale_days.close", sale_day=sale_day)
    if sale_day["status"] != "BIDDING_CLOSED":
        fail("ERR_INVALID_STATE")
    close_sale_day(sale_day)
    return ok(serialize.sale_day(sale_day))
