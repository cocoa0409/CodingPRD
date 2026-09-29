"""Warranty claims: filing, adjudication and settlement."""
from flask import Blueprint

import calc
from common import (
    ApiError, DB, authenticate, f_date, f_enum, f_str, get_body, must, new_row,
    now_date, ok, page, parse_date, public, qp, scope, touch,
)

bp = Blueprint("warranty", __name__, url_prefix="/distribution")

CLAIM_READERS = ["PlatformAdmin", "SalesRep", "ComplianceOfficer", "Customer"]


@bp.post("/warranty-claims")
def create_claim():
    user_id, role = authenticate(["SalesRep", "Customer"])
    body = get_body()
    account_id = f_str(body, "account_id")
    model_id = f_str(body, "battery_model_id")
    serial_number = f_str(body, "serial_number")
    installed_on = f_date(body, "installed_on")
    failed_on = f_date(body, "failed_on")
    if parse_date(failed_on) < parse_date(installed_on):
        raise ApiError("ERR_INVALID_REQUEST", "failed_on may not precede installed_on")
    must("accounts", account_id)
    must("battery_models", model_id)
    scope(role, user_id, account_id)
    for existing in DB.warranty_claims.values():
        if existing["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_SERIAL_NUMBER", "serial number already claimed")

    row = new_row({
        "account_id": account_id,
        "battery_model_id": model_id,
        "serial_number": serial_number,
        "installed_on": installed_on,
        "failed_on": failed_on,
        "months_in_service": 0,
        "coverage_band": None,
        "credit_cents": 0,
        "settlement_mode": None,
        "replacement_order_id": None,
        "status": "SUBMITTED",
    })
    DB.warranty_claims[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/warranty-claims/<claim_id>")
def read_claim(claim_id):
    user_id, role = authenticate(CLAIM_READERS)
    row = must("warranty_claims", claim_id)
    scope(role, user_id, row["account_id"])
    return ok(public(row))


@bp.get("/warranty-claims")
def list_claims():
    user_id, role = authenticate(CLAIM_READERS)
    rows = list(DB.warranty_claims.values())
    if role == "Customer":
        requested = qp("account_id")
        if requested is not None and requested != user_id:
            raise ApiError("ERR_ACCOUNT_SCOPE_VIOLATION", "customer may only list its own account")
        rows = [r for r in rows if r["account_id"] == user_id]
    for name in ("account_id", "battery_model_id", "replacement_order_id", "status"):
        value = qp(name)
        if value is not None:
            rows = [r for r in rows if r.get(name) == value]
    return page(rows, public)


@bp.post("/warranty-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    authenticate(["SalesRep", "PlatformAdmin"])
    row = must("warranty_claims", claim_id)
    get_body()
    if row["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "claim is not SUBMITTED")
    model = DB.battery_models[row["battery_model_id"]]
    months = calc.months_in_service(row["installed_on"], row["failed_on"])
    band, credit = calc.warranty_credit(model, months)
    row["months_in_service"] = months
    row["coverage_band"] = band
    row["credit_cents"] = credit
    row["status"] = {"FREE": "APPROVED_FREE", "PRORATA": "APPROVED_PRORATA", "EXPIRED": "DENIED"}[band]
    touch(row)
    return ok(public(row))


@bp.post("/warranty-claims/<claim_id>/settle")
def settle_claim(claim_id):
    authenticate(["SalesRep", "PlatformAdmin"])
    row = must("warranty_claims", claim_id)
    body = get_body()
    mode = f_enum(body, "settlement_mode", ("ACCOUNT_CREDIT", "REPLACEMENT_ORDER"))
    warehouse_id = f_str(body, "replacement_warehouse_id", required=False, default=None)
    if mode == "REPLACEMENT_ORDER" and warehouse_id is None:
        raise ApiError("ERR_INVALID_REQUEST", "replacement_warehouse_id is required for REPLACEMENT_ORDER")
    if warehouse_id is not None:
        must("warehouses", warehouse_id)
    if row["status"] not in ("APPROVED_FREE", "APPROVED_PRORATA"):
        raise ApiError("ERR_INVALID_STATE", "claim is not approved")

    account = DB.accounts[row["account_id"]]
    if mode == "ACCOUNT_CREDIT":
        account["warranty_credit_cents"] = int(account["warranty_credit_cents"]) + int(row["credit_cents"])
        touch(account)
    else:
        model = DB.battery_models[row["battery_model_id"]]
        line_model_id = model["id"]
        if model["status"] != "ACTIVE" and model.get("replacement_model_id"):
            line_model_id = model["replacement_model_id"]
        order = new_row({
            "account_id": row["account_id"],
            "warehouse_id": warehouse_id,
            "storm_event_id": None,
            "requested_ship_date": DB.clock.date().isoformat(),
            "fulfillment_status": "DRAFT",
            "credit_status": "PENDING",
            "hazmat_hold": False,
            "rejected_carrier_ids": [],
            "line_count": 1,
            "subtotal_cents": 0,
            "core_deposit_charge_cents": 0,
            "hazmat_fee_waived": False,
            "hazmat_fee_cents": 0,
            "service_contract_fee_cents": 0,
            "total_cents": 0,
            "allocation_priority_score": 0,
            "cancellation_reason": None,
        })
        DB.orders[order["id"]] = order
        line = new_row({
            "order_id": order["id"],
            "battery_model_id": line_model_id,
            "quantity": 1,
            "core_expected_count": 1,
            "unit_price_cents": 0,
            "discount_pct": 0.0,
            "line_total_cents": 0,
            "allocated_quantity": 0,
            "allocated_lot_id": None,
            "core_due_by": None,
        })
        DB.order_lines[line["id"]] = line
        row["replacement_order_id"] = order["id"]

    row["settlement_mode"] = mode
    row["status"] = "SETTLED"
    touch(row)
    return ok(public(row))
