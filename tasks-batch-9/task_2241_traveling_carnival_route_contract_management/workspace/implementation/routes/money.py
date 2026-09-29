"""Ticket sales and settlements."""

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import transitions
import validators as v
from errors import fail, invalid
from middleware import (ROLE_CONTRACT_NEGOTIATOR, ROLE_GENERAL_MANAGER,
                        ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER,
                        ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("money", __name__)

CHANNELS = ("WRISTBAND", "SINGLE", "PRESALE", "COMP")
SALE_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
                   ROLE_TICKETING_AUDITOR)
SETTLEMENT_READ_ROLES = SALE_READ_ROLES + (ROLE_CONTRACT_NEGOTIATOR,)


# --------------------------------------------------------------------------
# ticket sales
# --------------------------------------------------------------------------
@bp.post("/route-stops/<stop_id>/ticket-sales")
def create_ticket_sale(stop_id):
    require_role(ROLE_TICKETING_AUDITOR)
    stop = v.path_row("route_stops", stop_id)
    body = v.get_body()
    channel = v.req_enum(body, "channel", CHANNELS)
    units = v.req_int(body, "units", minimum=1)
    unit_price_cents = v.req_int(body, "unit_price_cents", minimum=0)
    business_raw, business_dt = v.req_dt(body, "business_date")
    if channel == "COMP" and unit_price_cents != 0:
        invalid("unit_price_cents must be 0 for a COMP batch.")
    if channel != "COMP" and unit_price_cents <= 0:
        invalid("unit_price_cents must be greater than 0 for a paid batch.")

    if stop["status"] not in ("OPEN", "TEARDOWN"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Sales may only be booked while the lot is OPEN or TEARDOWN.")
    if not (calc.dt(stop, "open_date") <= business_dt
            <= calc.dt(stop, "close_date")):
        fail(errors.ERR_SALE_OUTSIDE_OPERATING_WINDOW,
             "business_date lies outside the lot's operating window.")

    row = db.create(db.store.ticket_sales, {
        "route_stop_id": stop["id"],
        "channel": channel,
        "units": units,
        "unit_price_cents": unit_price_cents,
        "gross_cents": units * unit_price_cents,
        "business_date": business_raw,
    }, common=False)
    return created(ser.ticket_sale(row))


@bp.get("/route-stops/<stop_id>/ticket-sales")
def list_ticket_sales(stop_id):
    require_role(*SALE_READ_ROLES)
    stop = v.path_row("route_stops", stop_id)
    rows = calc.sales_of_stop(stop["id"])
    channel = request.args.get("channel")
    if channel:
        rows = [r for r in rows if r["channel"] == channel]
    return paginate(rows, ser.ticket_sale)


# --------------------------------------------------------------------------
# settlements
# --------------------------------------------------------------------------
@bp.post("/settlements")
def create_settlement():
    require_role(ROLE_TICKETING_AUDITOR)
    body = v.get_body()
    contract = v.body_ref(body, "contract_id", "contracts")
    if contract is None:
        v.req_str(body, "contract_id")
    expected_version = v.req_int(body, "expected_contract_version")

    if expected_version != int(contract["version"]):
        fail(errors.ERR_STALE_CONTRACT_VERSION,
             "The deal has changed since it was read.")
    if calc.settlements_of_contract(contract["id"], ("FINAL",)):
        fail(errors.ERR_SETTLEMENT_ALREADY_FINAL,
             "The money for this deal is already closed.")
    stop = db.store.route_stops.get(contract["route_stop_id"])
    if contract["status"] != "EXECUTED":
        fail(errors.ERR_CONTRACT_STATE_INVALID,
             "Only an EXECUTED deal may be settled.")
    if stop is None or stop["status"] not in ("OPEN", "TEARDOWN"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "The lot must be OPEN or TEARDOWN to build a settlement.")

    for prior in calc.settlements_of_contract(contract["id"],
                                              ("PROVISIONAL", "DISPUTED")):
        prior["status"] = "SUPERSEDED"
        db.touch(prior)

    amounts = calc.stop_settlement(contract, stop, "PROVISIONAL")
    data = {
        "contract_id": contract["id"],
        "variant": "PROVISIONAL",
        "status": "PROVISIONAL",
        "dispute_reason": None,
        "finalized_at": None,
    }
    data.update(amounts)
    row = db.create(db.store.settlements, data)
    db.touch(contract)
    return created(ser.settlement(row))


@bp.get("/settlements/<settlement_id>")
def get_settlement(settlement_id):
    require_role(*SETTLEMENT_READ_ROLES)
    return ok(ser.settlement(v.path_row("settlements", settlement_id)))


@bp.get("/contracts/<contract_id>/settlements")
def list_settlements(contract_id):
    require_role(*SETTLEMENT_READ_ROLES)
    contract = v.path_row("contracts", contract_id)
    rows = calc.settlements_of_contract(contract["id"])
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.settlement)


@bp.post("/settlements/<settlement_id>/dispute")
def dispute_settlement(settlement_id):
    require_role(ROLE_CONTRACT_NEGOTIATOR)
    settlement = v.path_row("settlements", settlement_id)
    body = v.get_body()
    reason = v.req_str(body, "dispute_reason")
    if settlement["status"] != "PROVISIONAL":
        fail(errors.ERR_SETTLEMENT_STATE_INVALID,
             "Only a PROVISIONAL settlement may be disputed.")
    settlement["status"] = "DISPUTED"
    settlement["dispute_reason"] = reason
    db.touch(settlement)
    return ok(ser.settlement(settlement))


@bp.post("/settlements/<settlement_id>/reconcile")
def reconcile_settlement(settlement_id):
    require_role(ROLE_TICKETING_AUDITOR)
    settlement = v.path_row("settlements", settlement_id)
    if settlement["status"] != "DISPUTED":
        fail(errors.ERR_SETTLEMENT_STATE_INVALID,
             "Only a DISPUTED settlement may be reconciled.")
    contract = db.store.contracts.get(settlement["contract_id"])
    stop = db.store.route_stops.get(contract["route_stop_id"]) if contract else None
    if contract is None or stop is None:
        fail(errors.ERR_SETTLEMENT_STATE_INVALID,
             "The settlement's deal is no longer readable.")
    settlement.update(calc.stop_settlement(contract, stop, "PROVISIONAL"))
    settlement["status"] = "PROVISIONAL"
    settlement["variant"] = "PROVISIONAL"
    settlement["dispute_reason"] = None
    db.touch(settlement)
    return ok(ser.settlement(settlement))


@bp.post("/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    require_role(ROLE_GENERAL_MANAGER)
    settlement = v.path_row("settlements", settlement_id)
    contract = db.store.contracts.get(settlement["contract_id"])
    stop = db.store.route_stops.get(contract["route_stop_id"]) if contract else None
    if stop is None or stop["status"] != "TEARDOWN":
        fail(errors.ERR_STOP_STATE_INVALID,
             "The lot must be TEARDOWN to finalize its money.")
    if settlement["status"] != "PROVISIONAL":
        fail(errors.ERR_SETTLEMENT_STATE_INVALID,
             "Only a PROVISIONAL settlement may be finalized.")
    if calc.closures_of_stop(stop["id"], ("LOGGED",)):
        fail(errors.ERR_CLOSURE_NOT_ADJUDICATED,
             "Every weather closure of the lot must be adjudicated first.")
    if calc.make_goods_of_contract(contract["id"], ("PROPOSED",)):
        fail(errors.ERR_MAKEGOOD_PENDING,
             "Every make-good arrangement must be answered first.")

    settlement.update(calc.stop_settlement(contract, stop, "FINAL"))
    settlement["variant"] = "FINAL"
    settlement["status"] = "FINAL"
    settlement["finalized_at"] = db.now_iso()
    db.touch(settlement)
    transitions.close_stop(stop)
    return ok(ser.settlement(settlement))
