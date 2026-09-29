"""Exchange file endpoints (PRD 3.5)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain

bp = Blueprint("exchange_files", __name__)


@bp.post("/exchange-files")
def create_exchange_file():
    middleware.actor([C.QI])
    payload = middleware.body_or_400()
    investor_id = middleware.req_str(payload, "investor_id")
    qi_reference = middleware.req_str(payload, "qi_reference")
    relinquished_closed_on = middleware.req_dt(payload, "relinquished_closed_on")
    relinquished_sale_price_cents = middleware.req_int(
        payload, "relinquished_sale_price_cents", 1)
    net_proceeds_cents = middleware.req_int(payload, "net_proceeds_cents", 0)
    debt_retired_cents = middleware.req_int(payload, "debt_retired_cents", 0)
    identification_rule = middleware.req_enum(
        payload, "identification_rule", C.IDENTIFICATION_RULES)
    boot_tolerance_cents = middleware.opt_int(
        payload, "boot_tolerance_cents", default=0, minimum=0)

    investor = domain.require("investor", investor_id)

    identification_deadline, exchange_deadline = calc.exchange_deadlines(
        relinquished_closed_on)
    row = db.new_row(db.exchange_files, {
        "investor_id": investor["id"],
        "source_exit_event_id": None,
        "qi_reference": qi_reference,
        "relinquished_closed_on": relinquished_closed_on,
        "relinquished_sale_price_cents": relinquished_sale_price_cents,
        "net_proceeds_cents": net_proceeds_cents,
        "debt_retired_cents": debt_retired_cents,
        "identification_rule": identification_rule,
        "boot_tolerance_cents": boot_tolerance_cents,
        "identification_deadline": identification_deadline,
        "exchange_deadline": exchange_deadline,
        "status": "OPEN",
    })
    return created_response(db.serialize(row))


@bp.get("/exchange-files/<exchange_file_id>")
def get_exchange_file(exchange_file_id):
    return read_one("exchange_file", C.READ_EXCHANGE_SIDE, exchange_file_id)


@bp.get("/exchange-files")
def list_exchange_files():
    return listing(db.exchange_files, C.READ_EXCHANGE_SIDE,
                   str_filters=("investor_id", "source_exit_event_id", "status",
                                "identification_rule"))


@bp.post("/exchange-files/<exchange_file_id>/mark-expired")
def mark_expired(exchange_file_id):
    middleware.actor([C.QI])
    exchange_file = domain.require("exchange_file", exchange_file_id)

    if exchange_file["status"] not in ("OPEN", "IDENTIFIED"):
        raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")
    now = clock.now()
    if exchange_file["status"] == "OPEN":
        if now <= exchange_file["identification_deadline"]:
            raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")
    else:
        if now <= exchange_file["exchange_deadline"]:
            raise ApiError("ERR_EXCHANGE_FILE_INVALID_STATE")

    exchange_file["status"] = "EXPIRED"
    db.touch(exchange_file)
    subs = [s for s in db.sorted_rows(db.subscriptions)
            if s["exchange_file_id"] == exchange_file["id"]]
    domain.reject_outstanding_subscriptions(subs)
    return object_response(db.serialize(exchange_file))
