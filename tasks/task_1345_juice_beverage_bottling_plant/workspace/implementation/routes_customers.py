"""CustomerAccount endpoints and the credit lifecycle."""
from flask import Blueprint

from domain import (OPEN_ORDER_STATES, OPEN_RUN_STATES, ser_customer,
                    ser_order, ser_pallet_account, ser_run)
from errors import err
from store import db, stamp, touch
from util import (body, ok, paginate, req_field, require_any, require_roles)

bp = Blueprint("customers", __name__)


def get_customer_or_404(customer_id):
    customer = db.customers.get(customer_id)
    if customer is None:
        raise err("ERR_CUSTOMER_NOT_FOUND", f"CustomerAccount {customer_id} not found")
    return customer


@bp.post("/v1/customer-accounts")
def create_customer():
    require_roles("PlantManager")
    data = body()
    name = req_field(data, "name", "str")
    credit_limit = req_field(data, "credit_limit_cents", "int")
    minimum_run = req_field(data, "minimum_run_units", "int")
    pallet_deposit = req_field(data, "pallet_deposit_cents", "int")
    customer = {
        "name": name,
        "credit_limit_cents": credit_limit,
        "minimum_run_units": minimum_run,
        "pallet_deposit_cents": pallet_deposit,
        "outstanding_balance_cents": 0,
        "status": "PENDING_CREDIT",
    }
    stamp(customer)
    db.customers[customer["id"]] = customer
    account = {
        "customer_id": customer["id"],
        "pallets_out_total": 0,
        "pallets_returned_total": 0,
        "pallets_converted_total": 0,
    }
    stamp(account)
    db.pallet_accounts[account["id"]] = account
    return ok(ser_customer(customer), 201)


@bp.get("/v1/customer-accounts")
def list_customers():
    from flask import request
    require_any()
    status = request.args.get("status")
    items = list(db.customers.values())
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items, ser_customer)


@bp.get("/v1/customer-accounts/<customer_id>")
def get_customer(customer_id):
    require_any()
    return ok(ser_customer(get_customer_or_404(customer_id)))


@bp.post("/v1/customer-accounts/<customer_id>/approve-credit")
def approve_credit(customer_id):
    require_roles("FinanceClerk")
    customer = get_customer_or_404(customer_id)
    if customer["status"] != "PENDING_CREDIT":
        raise err("ERR_CUSTOMER_STATE_INVALID",
                  "approve-credit requires status PENDING_CREDIT")
    customer["status"] = "ACTIVE"
    touch(customer)
    return ok(ser_customer(customer))


@bp.post("/v1/customer-accounts/<customer_id>/suspend")
def suspend_customer(customer_id):
    require_roles("FinanceClerk")
    customer = get_customer_or_404(customer_id)
    if customer["status"] != "ACTIVE":
        raise err("ERR_CUSTOMER_STATE_INVALID",
                  "suspend requires status ACTIVE")
    customer["status"] = "SUSPENDED"
    touch(customer)
    return ok(ser_customer(customer))


@bp.post("/v1/customer-accounts/<customer_id>/reactivate")
def reactivate_customer(customer_id):
    require_roles("FinanceClerk")
    customer = get_customer_or_404(customer_id)
    if customer["status"] != "SUSPENDED":
        raise err("ERR_CUSTOMER_STATE_INVALID",
                  "reactivate requires status SUSPENDED")
    threshold = (customer["credit_limit_cents"] * 4) // 5
    if customer["outstanding_balance_cents"] > threshold:
        raise err("ERR_REACTIVATION_THRESHOLD_NOT_MET",
                  "Outstanding balance must fall to at most floor(0.8 * credit_limit)")
    customer["status"] = "ACTIVE"
    touch(customer)
    return ok(ser_customer(customer))


@bp.post("/v1/customer-accounts/<customer_id>/close")
def close_customer(customer_id):
    require_roles("FinanceClerk")
    customer = get_customer_or_404(customer_id)
    if customer["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_CUSTOMER_STATE_INVALID",
                  "close requires status ACTIVE or SUSPENDED")
    for run in db.runs.values():
        if run["customer_id"] == customer_id and run["production_status"] in OPEN_RUN_STATES:
            raise err("ERR_CUSTOMER_STATE_INVALID",
                      "Customer has production runs still open")
    for order in db.orders.values():
        if order["customer_id"] == customer_id and order["status"] in OPEN_ORDER_STATES:
            raise err("ERR_CUSTOMER_STATE_INVALID",
                      "Customer has shipment orders still open")
    account = _account_of(customer_id)
    if account is not None:
        outstanding = (account["pallets_out_total"] - account["pallets_returned_total"]
                       - account["pallets_converted_total"])
        if outstanding != 0:
            raise err("ERR_CUSTOMER_STATE_INVALID",
                      "Customer still has outstanding returnable pallets")
    customer["status"] = "CLOSED"
    touch(customer)
    return ok(ser_customer(customer))


@bp.post("/v1/customer-accounts/<customer_id>/payments")
def post_payment(customer_id):
    require_roles("FinanceClerk")
    customer = get_customer_or_404(customer_id)
    data = body()
    amount = req_field(data, "amount_cents", "int")
    if amount <= 0 or amount > customer["outstanding_balance_cents"]:
        raise err("ERR_PAYMENT_INVALID_AMOUNT",
                  "Payment must satisfy 0 < amount <= outstanding_balance_cents")
    customer["outstanding_balance_cents"] -= amount
    touch(customer)
    return ok(ser_customer(customer), 201)


@bp.get("/v1/customer-accounts/<customer_id>/production-runs")
def customer_runs(customer_id):
    require_any()
    get_customer_or_404(customer_id)
    items = [r for r in db.runs.values() if r["customer_id"] == customer_id]
    return paginate(items, ser_run)


@bp.get("/v1/customer-accounts/<customer_id>/shipment-orders")
def customer_orders(customer_id):
    require_any()
    get_customer_or_404(customer_id)
    items = [o for o in db.orders.values() if o["customer_id"] == customer_id]
    return paginate(items, ser_order)


@bp.get("/v1/customer-accounts/<customer_id>/pallet-account")
def customer_pallet_account(customer_id):
    from util import ok_list
    require_any()
    get_customer_or_404(customer_id)
    account = _account_of(customer_id)
    items = [ser_pallet_account(account)] if account is not None else []
    return ok_list(items, len(items), 0, len(items))


def _account_of(customer_id):
    for account in db.pallet_accounts.values():
        if account["customer_id"] == customer_id:
            return account
    return None
