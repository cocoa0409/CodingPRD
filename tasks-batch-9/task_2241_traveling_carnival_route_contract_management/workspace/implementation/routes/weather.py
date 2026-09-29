"""Weather closures and sponsor make-good arrangements."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import validators as v
from errors import fail, invalid
from middleware import (ROLE_CONTRACT_NEGOTIATOR, ROLE_GENERAL_MANAGER,
                        ROLE_LOT_BOSS, ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("weather", __name__)

CAUSES = ("WIND", "RAIN", "LIGHTNING", "HEAT")
KINDS = ("CASH_REFUND", "SPONSOR_CREDIT", "BONUS_DAY")
RESPONSES = ("ACCEPT", "DECLINE")
REFUND_ELIGIBLE_CAUSES = ("WIND", "LIGHTNING")
CLOSURE_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                      ROLE_GENERAL_MANAGER, ROLE_TICKETING_AUDITOR, ROLE_LOT_BOSS)
MAKEGOOD_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                       ROLE_GENERAL_MANAGER, ROLE_TICKETING_AUDITOR,
                       ROLE_CONTRACT_NEGOTIATOR)


# --------------------------------------------------------------------------
# weather closures
# --------------------------------------------------------------------------
@bp.post("/route-stops/<stop_id>/weather-closures")
def create_closure(stop_id):
    require_role(ROLE_ROUTE_MANAGER, ROLE_LOT_BOSS)
    stop = v.path_row("route_stops", stop_id)
    body = v.get_body()
    cause = v.req_enum(body, "cause", CAUSES)
    from_raw, closed_from = v.req_dt(body, "closed_from")
    to_raw, closed_to = v.req_dt(body, "closed_to")
    if closed_to <= closed_from:
        invalid("closed_to must be after closed_from.")

    if stop["status"] not in ("OPEN", "TEARDOWN"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Closures may only be logged while the lot is OPEN or TEARDOWN.")
    if not calc.closure_intersects_window(stop, closed_from, closed_to):
        fail(errors.ERR_CLOSURE_OUTSIDE_OPERATING_WINDOW,
             "The closure intersects none of the lot's operating windows.")

    row = db.create(db.store.weather_closures, {
        "route_stop_id": stop["id"],
        "cause": cause,
        "closed_from": from_raw,
        "closed_to": to_raw,
        "closure_hours_raw": float(v.rhu(calc.hours_between(closed_from,
                                                            closed_to), 2)),
        "abated_hours": 0,
        "status": "LOGGED",
    })
    return created(ser.weather_closure(row))


@bp.get("/route-stops/<stop_id>/weather-closures")
def list_stop_closures(stop_id):
    require_role(*CLOSURE_READ_ROLES)
    stop = v.path_row("route_stops", stop_id)
    rows = calc.closures_of_stop(stop["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.weather_closure)


@bp.get("/weather-closures/<closure_id>")
def get_closure(closure_id):
    require_role(*CLOSURE_READ_ROLES)
    return ok(ser.weather_closure(v.path_row("weather_closures", closure_id)))


@bp.post("/weather-closures/<closure_id>/adjudicate")
def adjudicate_closure(closure_id):
    require_role(ROLE_GENERAL_MANAGER)
    closure = v.path_row("weather_closures", closure_id)
    stop = db.store.route_stops.get(closure["route_stop_id"])
    if stop is None or stop["status"] not in ("OPEN", "TEARDOWN"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Closures may only be adjudicated while the lot is OPEN or "
             "TEARDOWN.")
    if closure["status"] != "LOGGED":
        fail(errors.ERR_CLOSURE_STATE_INVALID,
             "Only a LOGGED closure may be adjudicated.")
    closure["status"] = "ADJUDICATED"
    db.touch(closure)
    calc.weather_abatement_hours(stop)
    db.touch(stop)
    return ok(ser.weather_closure(closure))


# --------------------------------------------------------------------------
# make-goods
# --------------------------------------------------------------------------
@bp.post("/make-goods")
def create_make_good():
    require_role(ROLE_GENERAL_MANAGER)
    body = v.get_body()
    closure = v.body_ref(body, "weather_closure_id", "weather_closures")
    contract = v.body_ref(body, "contract_id", "contracts")
    if closure is None:
        v.req_str(body, "weather_closure_id")
    if contract is None:
        v.req_str(body, "contract_id")
    kind = v.req_enum(body, "kind", KINDS)

    provisional = calc.settlements_of_contract(contract["id"], ("PROVISIONAL",))
    if len(provisional) != 1:
        fail(errors.ERR_NO_PROVISIONAL_SETTLEMENT,
             "The deal must carry exactly one PROVISIONAL settlement.")
    settlement = provisional[0]
    stop = db.store.route_stops.get(contract["route_stop_id"])
    if stop is None:
        fail(errors.ERR_NO_PROVISIONAL_SETTLEMENT,
             "The deal's lot is no longer readable.")

    amount_cents = calc.makegood_amount(contract, stop, closure, settlement, kind)

    if closure["status"] != "ADJUDICATED" \
            or closure["route_stop_id"] != contract["route_stop_id"]:
        fail(errors.ERR_MAKEGOOD_STOP_MISMATCH,
             "The closure must be ADJUDICATED and belong to the deal's lot.")
    if kind == "CASH_REFUND" and closure["cause"] not in REFUND_ELIGIBLE_CAUSES:
        fail(errors.ERR_REFUND_NOT_ELIGIBLE,
             "A cash refund is admitted only for a WIND or LIGHTNING closure.")

    row = db.create(db.store.make_goods, {
        "weather_closure_id": closure["id"],
        "contract_id": contract["id"],
        "kind": kind,
        "amount_cents": amount_cents,
        "status": "PROPOSED",
        "responded_at": None,
    })
    return created(ser.make_good(row))


@bp.get("/contracts/<contract_id>/make-goods")
def list_contract_make_goods(contract_id):
    require_role(*MAKEGOOD_READ_ROLES)
    contract = v.path_row("contracts", contract_id)
    rows = calc.make_goods_of_contract(contract["id"])
    status = request.args.get("status")
    kind = request.args.get("kind")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if kind:
        rows = [r for r in rows if r["kind"] == kind]
    return paginate(rows, ser.make_good)


@bp.get("/weather-closures/<closure_id>/make-goods")
def list_closure_make_goods(closure_id):
    require_role(*MAKEGOOD_READ_ROLES)
    closure = v.path_row("weather_closures", closure_id)
    rows = [r for r in db.all_of(db.store.make_goods)
            if r["weather_closure_id"] == closure["id"]]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.make_good)


@bp.post("/make-goods/<make_good_id>/respond")
def respond_make_good(make_good_id):
    require_role(ROLE_CONTRACT_NEGOTIATOR)
    make_good = v.path_row("make_goods", make_good_id)
    body = v.get_body()
    response = v.req_enum(body, "response", RESPONSES)
    if response == "ACCEPT" and calc.settlements_of_contract(
            make_good["contract_id"], ("FINAL",)):
        fail(errors.ERR_SETTLEMENT_ALREADY_FINAL,
             "The money for this deal is already closed.")
    if make_good["status"] != "PROPOSED":
        fail(errors.ERR_MAKEGOOD_STATE_INVALID,
             "Only a PROPOSED make-good may be answered.")
    make_good["status"] = "ACCEPTED" if response == "ACCEPT" else "DECLINED"
    make_good["responded_at"] = db.now_iso()
    db.touch(make_good)
    return ok(ser.make_good(make_good))
