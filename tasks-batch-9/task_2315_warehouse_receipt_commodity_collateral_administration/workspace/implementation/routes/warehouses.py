"""Warehouses: application, restatement, the licensing dimension, the
insolvency dimension and the computed position summary (§3.1, §3.7, §3.9).
"""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, fail, new_row, now, now_iso, opt_date,
                  opt_int, opt_str, req_enum, req_int, req_bool, req_str,
                  respond_object, store, touch)
from listing import list_response

bp = Blueprint("warehouses", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "RegistryAdministrator",
              "Depositor", "Lender")
PROGRAMS = ("STATE", "FEDERAL")
DECISIONS = ("ISSUE", "DENY", "SUSPEND", "REINSTATE", "REVOKE")
ACTIONS = ("DECLARE", "OPEN_CLAIMS", "ALLOCATE", "CLOSE")


@bp.post("/warehouses")
def create_warehouse():
    authenticate(("StateRegulator",))
    data = body()
    name = req_str(data, "name")
    operator_name = req_str(data, "operator_name")
    state_code = req_str(data, "state_code")
    program = req_enum(data, "license_program", PROGRAMS)
    capacity = req_int(data, "licensed_capacity_bushels", minimum=1)
    bond = req_int(data, "bond_amount_cents", minimum=0)
    net_worth = req_int(data, "net_worth_cents", minimum=0)
    lanes = req_int(data, "loadout_lane_count", minimum=1)
    participant = req_bool(data, "registry_participant")

    row = new_row()
    row.update({
        "name": name,
        "operator_name": operator_name,
        "state_code": state_code,
        "license_program": program,
        "licensed_capacity_bushels": capacity,
        "bond_amount_cents": bond,
        "net_worth_cents": net_worth,
        "loadout_lane_count": lanes,
        "registry_participant": participant,
        "license_state": "APPLIED",
        "insolvency_state": "SOLVENT",
        "licensed_by_user_id": None,
        "license_effective_date": None,
        "license_expiry_date": None,
        "insolvency_declared_at": None,
        "insolvency_price_cents_per_bushel": None,
    })
    store.warehouses[row["id"]] = row
    return respond_object(model.warehouse_out(row), 201)


@bp.get("/warehouses")
def list_warehouses():
    authenticate(READ_ROLES)
    return list_response(
        list(store.warehouses.values()),
        ("state_code", "license_program", "license_state", "insolvency_state"),
        model.warehouse_out)


@bp.get("/warehouses/<warehouse_id>")
def read_warehouse(warehouse_id):
    caller = authenticate(READ_ROLES)
    warehouse = model.get_warehouse(warehouse_id)
    model.require_operator_warehouse(caller, warehouse_id)
    return respond_object(model.warehouse_out(warehouse))


@bp.patch("/warehouses/<warehouse_id>/financials")
def restate_financials(warehouse_id):
    caller = authenticate(("StateRegulator", "WarehouseOperator"))
    warehouse = model.get_warehouse(warehouse_id)
    model.require_operator_warehouse(caller, warehouse_id)
    data = body()
    capacity = opt_int(data, "licensed_capacity_bushels", minimum=1)
    bond = opt_int(data, "bond_amount_cents", minimum=0)
    net_worth = opt_int(data, "net_worth_cents", minimum=0)
    if capacity is not None:
        warehouse["licensed_capacity_bushels"] = capacity
    if bond is not None:
        warehouse["bond_amount_cents"] = bond
    if net_worth is not None:
        warehouse["net_worth_cents"] = net_worth
    touch(warehouse)
    return respond_object(model.warehouse_out(warehouse))


def _financial_gates(warehouse):
    figures = calc.license_financials(
        warehouse["license_program"], warehouse["licensed_capacity_bushels"],
        warehouse["bond_amount_cents"], warehouse["net_worth_cents"])
    if figures["net_worth_shortfall_cents"] > figures["net_worth_tolerance_cents"]:
        fail("ERR_NET_WORTH_INSUFFICIENT", 422)
    if figures["bond_deficiency_cents"] > 0:
        fail("ERR_BOND_INSUFFICIENT", 422)


@bp.post("/warehouses/<warehouse_id>/license-decision")
def license_decision(warehouse_id):
    caller = authenticate(("StateRegulator",))
    warehouse = model.get_warehouse(warehouse_id)
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    effective = opt_date(data, "license_effective_date")
    expiry = opt_date(data, "license_expiry_date")
    opt_str(data, "note")
    state = warehouse["license_state"]

    if decision == "ISSUE":
        if state != "APPLIED":
            fail("ERR_INVALID_STATE", 409)
        _financial_gates(warehouse)
        warehouse["license_state"] = "LICENSED"
        warehouse["licensed_by_user_id"] = caller.user_id
        warehouse["license_effective_date"] = (
            effective.isoformat() if effective else None)
        warehouse["license_expiry_date"] = expiry.isoformat() if expiry else None
    elif decision == "DENY":
        if state != "APPLIED":
            fail("ERR_INVALID_STATE", 409)
        warehouse["license_state"] = "DENIED"
        warehouse["licensed_by_user_id"] = caller.user_id
    elif decision == "SUSPEND":
        if state != "LICENSED":
            fail("ERR_INVALID_STATE", 409)
        warehouse["license_state"] = "SUSPENDED"
        model.reject_weighed_tickets(warehouse_id, "LICENSE_SUSPENDED")
    elif decision == "REINSTATE":
        if state != "SUSPENDED":
            fail("ERR_INVALID_STATE", 409)
        for report in model.warehouse_reports(warehouse_id):
            if report["report_state"] == "UNDER_EXAMINATION":
                fail("ERR_INVALID_STATE", 409)
        _financial_gates(warehouse)
        warehouse["license_state"] = "LICENSED"
    else:  # REVOKE
        if state not in ("LICENSED", "SUSPENDED"):
            fail("ERR_INVALID_STATE", 409)
        warehouse["license_state"] = "REVOKED"
        model.reject_weighed_tickets(warehouse_id, "LICENSE_SUSPENDED")

    touch(warehouse)
    return respond_object(model.warehouse_out(warehouse))


@bp.post("/warehouses/<warehouse_id>/insolvency")
def insolvency(warehouse_id):
    authenticate(("StateRegulator",))
    warehouse = model.get_warehouse(warehouse_id)
    data = body()
    action = req_enum(data, "action", ACTIONS)
    price = opt_int(data, "insolvency_price_cents_per_bushel", minimum=0)
    opt_str(data, "note")
    state = warehouse["insolvency_state"]

    if action == "DECLARE":
        if state != "SOLVENT" or warehouse["license_state"] == "DENIED":
            fail("ERR_INVALID_STATE", 409)
        warehouse["insolvency_state"] = "DECLARED"
        warehouse["insolvency_declared_at"] = now_iso()
        warehouse["_insolvency_declared_dt"] = now()
        if price is not None:
            warehouse["insolvency_price_cents_per_bushel"] = price
        model.cancel_requested_orders(warehouse_id, "INSOLVENCY_DECLARED")
        model.reject_weighed_tickets(warehouse_id, "INSOLVENCY_DECLARED")
    elif action == "OPEN_CLAIMS":
        if state != "DECLARED":
            fail("ERR_INVALID_STATE", 409)
        warehouse["insolvency_state"] = "CLAIMS_OPEN"
    elif action == "ALLOCATE":
        if state != "CLAIMS_OPEN":
            fail("ERR_INVALID_STATE", 409)
        claims = model.warehouse_claims(warehouse_id)
        for claim in claims:
            if claim["claim_state"] == "FILED":
                fail("ERR_INVALID_STATE", 409)
        allowed = [c for c in claims if c["claim_state"] == "ALLOWED"]
        calc.waterfall(allowed, warehouse["bond_amount_cents"])
        for claim in allowed:
            claim["claim_state"] = "SETTLED"
            touch(claim)
        warehouse["insolvency_state"] = "ALLOCATED"
    else:  # CLOSE
        if state != "ALLOCATED":
            fail("ERR_INVALID_STATE", 409)
        warehouse["insolvency_state"] = "CLOSED"

    touch(warehouse)
    return respond_object(model.warehouse_out(warehouse))


@bp.get("/warehouses/<warehouse_id>/position-summary")
def position_summary(warehouse_id):
    caller = authenticate(("StateRegulator", "WarehouseOperator"))
    warehouse = model.get_warehouse(warehouse_id)
    model.require_operator_warehouse(caller, warehouse_id)
    data = model.warehouse_out(warehouse)
    data["warehouse_id"] = warehouse["id"]
    data["unreceipted_obligation_bushels"] = (
        model.unreceipted_obligation_bushels(warehouse_id))
    return respond_object(data)
