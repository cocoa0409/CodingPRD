"""Fair and community event contracts: draft, send, counter, execute."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import transitions
import validators as v
from errors import fail
from middleware import (ROLE_CONTRACT_NEGOTIATOR, ROLE_GENERAL_MANAGER,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("contracts", __name__)

READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
              ROLE_TICKETING_AUDITOR, ROLE_CONTRACT_NEGOTIATOR)
EXCLUSIVITY = ("NONE", "RIDES", "FOOD", "FULL")
SETTLEMENT_BASIS = ("GREATER_OF", "SPLIT_ONLY")


@bp.post("/contracts")
def create_contract():
    require_role(ROLE_CONTRACT_NEGOTIATOR)
    body = v.get_body()
    stop = v.body_ref(body, "route_stop_id", "route_stops")
    if stop is None:
        v.req_str(body, "route_stop_id")
    counterparty_name = v.req_str(body, "counterparty_name")
    split_pct = v.req_num(body, "revenue_split_pct_operator", minimum=20,
                         maximum=70, max_decimals=2)
    sponsor_name = v.opt_str(body, "sponsor_name", None)
    guarantee_cents = v.opt_int(body, "guarantee_cents", 0, minimum=0)
    ride_minimum_count = v.opt_int(body, "ride_minimum_count", 0, minimum=0)
    exclusivity = v.opt_enum(body, "exclusivity", EXCLUSIVITY, "NONE")
    settlement_basis = v.opt_enum(body, "settlement_basis", SETTLEMENT_BASIS,
                                 "GREATER_OF")

    if calc.live_contract_of_stop(stop["id"]) is not None:
        fail(errors.ERR_DUPLICATE_ACTIVE_CONTRACT,
             "This lot already carries a live contract.")

    row = db.create(db.store.contracts, {
        "route_stop_id": stop["id"],
        "counterparty_name": counterparty_name,
        "sponsor_name": sponsor_name,
        "revenue_split_pct_operator": split_pct,
        "guarantee_cents": guarantee_cents,
        "ride_minimum_count": ride_minimum_count,
        "exclusivity": exclusivity,
        "settlement_basis": settlement_basis,
        "negotiation_round": 0,
        "status": "DRAFT",
        "last_sent_by_user_id": None,
        "executed_at": None,
    })
    return created(ser.contract(row))


@bp.get("/contracts/<contract_id>")
def get_contract(contract_id):
    require_role(*READ_ROLES)
    return ok(ser.contract(v.path_row("contracts", contract_id)))


@bp.get("/contracts")
def list_contracts():
    require_role(*READ_ROLES)
    rows = db.all_of(db.store.contracts)
    route_stop_id = request.args.get("route_stop_id")
    status = request.args.get("status")
    if route_stop_id:
        rows = [r for r in rows if r["route_stop_id"] == route_stop_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.contract)


@bp.post("/contracts/<contract_id>/send")
def send_contract(contract_id):
    caller = require_role(ROLE_CONTRACT_NEGOTIATOR)
    contract = v.path_row("contracts", contract_id)
    stop = db.store.route_stops.get(contract["route_stop_id"])
    route = calc.route_of(stop) if stop else None
    if route is None or route["status"] not in ("SEQUENCED", "COMMITTED"):
        fail(errors.ERR_ROUTE_STATE_INVALID,
             "The route must be SEQUENCED or COMMITTED to send a deal.")
    if contract["status"] not in ("DRAFT", "COUNTERED"):
        fail(errors.ERR_CONTRACT_STATE_INVALID,
             "Only a DRAFT or COUNTERED deal may be sent.")
    if int(contract["negotiation_round"]) >= calc.MAX_NEGOTIATION_ROUNDS:
        fail(errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
             "The negotiation budget for this deal is spent.")
    contract["status"] = "SENT"
    contract["last_sent_by_user_id"] = caller.user_id
    db.touch(contract)
    return ok(ser.contract(contract))


@bp.post("/contracts/<contract_id>/counter")
def counter_contract(contract_id):
    require_role(ROLE_CONTRACT_NEGOTIATOR)
    contract = v.path_row("contracts", contract_id)
    body = v.get_body()
    split_pct = v.opt_num(body, "revenue_split_pct_operator", None, minimum=20,
                         maximum=70, max_decimals=2)
    guarantee_cents = v.opt_int(body, "guarantee_cents", None, minimum=0)
    ride_minimum_count = v.opt_int(body, "ride_minimum_count", None, minimum=0)
    if contract["status"] != "SENT":
        fail(errors.ERR_CONTRACT_STATE_INVALID,
             "Only a SENT deal may be countered.")
    if int(contract["negotiation_round"]) >= calc.MAX_NEGOTIATION_ROUNDS:
        fail(errors.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
             "The negotiation budget for this deal is spent.")
    contract["status"] = "COUNTERED"
    contract["negotiation_round"] = int(contract["negotiation_round"]) + 1
    if split_pct is not None:
        contract["revenue_split_pct_operator"] = split_pct
    if guarantee_cents is not None:
        contract["guarantee_cents"] = guarantee_cents
    if ride_minimum_count is not None:
        contract["ride_minimum_count"] = ride_minimum_count
    db.touch(contract)
    return ok(ser.contract(contract))


@bp.post("/contracts/<contract_id>/execute")
def execute_contract(contract_id):
    caller = require_role(ROLE_GENERAL_MANAGER)
    contract = v.path_row("contracts", contract_id)
    stop = db.store.route_stops.get(contract["route_stop_id"])
    route = calc.route_of(stop) if stop else None
    if route is None or route["status"] != "COMMITTED":
        fail(errors.ERR_ROUTE_STATE_INVALID,
             "The route must be COMMITTED to execute a deal.")
    if stop["status"] != "PLANNED":
        fail(errors.ERR_STOP_STATE_INVALID,
             "The lot must still be PLANNED to execute its deal.")
    if contract["status"] != "SENT":
        fail(errors.ERR_CONTRACT_STATE_INVALID,
             "Only a SENT deal may be executed.")
    if caller.user_id == contract.get("last_sent_by_user_id"):
        fail(errors.ERR_SEGREGATION_OF_DUTIES,
             "The user who sent this deal may not countersign it.")
    _check_exclusivity(contract, stop)

    contract["status"] = "EXECUTED"
    contract["executed_at"] = db.now_iso()
    db.touch(contract)
    db.touch(route)          # guarantee ledger
    transitions.confirm_stop(stop)
    return ok(ser.contract(contract))


def _check_exclusivity(contract, stop):
    open_dt = calc.dt(stop, "open_date")
    close_dt = calc.dt(stop, "close_date")
    for other in db.all_of(db.store.contracts):
        if other["id"] == contract["id"] or other["status"] != "EXECUTED":
            continue
        other_stop = db.store.route_stops.get(other["route_stop_id"])
        if other_stop is None or other_stop["venue_id"] != stop["venue_id"]:
            continue
        if contract["exclusivity"] not in ("RIDES", "FULL") \
                and other["exclusivity"] not in ("RIDES", "FULL"):
            continue
        if open_dt <= calc.dt(other_stop, "close_date") \
                and calc.dt(other_stop, "open_date") <= close_dt:
            fail(errors.ERR_EXCLUSIVITY_CONFLICT,
                 "An exclusive executed deal already covers this lot's window.")
