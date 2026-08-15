"""Pool contracts and loans."""
from decimal import Decimal
from flask import Blueprint, request
from middleware import require_role
from errors import (
    err_invalid_state, err_invalid_input, err_reference_not_found,
    err_duplicate_active, err_pool_unavailable,
)
from db import store, new_id
from response import success_object, success_list
from serializers import pool_contract_view, pool_loan_view
from services import calc
from services.lazy import bump, refresh_pool_loan, recompute_standing
from routes.common import (
    get_json_body, parse_int_field, get_shop_or_404, get_contract_or_404,
    get_loan_or_404, get_pagination, paginate,
)

bp = Blueprint("pool", __name__)


@bp.route("/shops/<shopId>/pool-contracts", methods=["POST"])
def create_contract(shopId):
    require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    body = get_json_body()
    customer_id = body.get("customer_id")
    if not isinstance(customer_id, str):
        raise err_invalid_input("customer_id is required")
    customer = store.customers.get(customer_id)
    if customer is None or customer["shop_id"] != shopId:
        raise err_reference_not_found("customer_id does not resolve")
    slot_count = parse_int_field(body, "slot_count", required=True, min_value=1, allow_zero=True)

    # uniqueness: only one ACTIVE contract per (customer, shop)
    for c in store.pool_contracts.values():
        if c["shop_id"] == shopId and c["customer_id"] == customer_id and c["status"] == "ACTIVE":
            raise err_duplicate_active("An ACTIVE contract already exists for this customer")

    now = store.now()
    first_month_fee = calc.compute_first_month_fee_cents(shop, slot_count, now)
    c = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "shop_id": shopId,
        "customer_id": customer_id,
        "slot_count": slot_count,
        "activated_on": now,
        "status": "ACTIVE",
        "first_month_fee_cents": first_month_fee,
    }
    store.pool_contracts[c["id"]] = c
    return success_object(pool_contract_view(c), status=201)


def _list_contracts(shop_id_filter):
    items = list(store.pool_contracts.values())
    if shop_id_filter is not None:
        items = [c for c in items if c["shop_id"] == shop_id_filter]
    if request.args.get("customer_id"):
        items = [c for c in items if c["customer_id"] == request.args["customer_id"]]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    items.sort(key=lambda c: c["created_at"])
    return items


@bp.route("/shops/<shopId>/pool-contracts", methods=["GET"])
def list_contracts(shopId):
    require_role("ShopAdmin", "Estimator", "ServiceManager")
    get_shop_or_404(shopId)
    limit, offset = get_pagination()
    items = _list_contracts(shopId)
    page, total = paginate(items, limit, offset)
    return success_list([pool_contract_view(c) for c in page], limit, offset, total)


@bp.route("/shops/<shopId>/pool-contracts/<contractId>", methods=["GET"])
def get_contract(shopId, contractId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    c = get_contract_or_404(contractId, shopId)
    return success_object(pool_contract_view(c))


@bp.route("/shops/pool-contracts-flat", methods=["GET"])
def list_contracts_flat():
    require_role("ShopAdmin", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    shop_id = request.args.get("shop_id")
    items = _list_contracts(shop_id)
    page, total = paginate(items, limit, offset)
    return success_list([pool_contract_view(c) for c in page], limit, offset, total)


@bp.route("/shops/pool-contracts-flat/<contractId>", methods=["GET"])
def get_contract_flat(contractId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    c = get_contract_or_404(contractId)
    return success_object(pool_contract_view(c))


def _has_open_loans(contract_id):
    for l in store.pool_loans.values():
        if l["contract_id"] == contract_id and l["status"] in ("OUT", "OVERDUE"):
            return True
    return False


@bp.route("/shops/<shopId>/pool-contracts/<contractId>/suspend", methods=["POST"])
def suspend_contract(shopId, contractId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    c = get_contract_or_404(contractId, shopId)
    if c["status"] != "ACTIVE":
        raise err_invalid_state("Contract must be ACTIVE to suspend")
    if _has_open_loans(contractId):
        raise err_invalid_state("Contract has open loans")
    c["status"] = "SUSPENDED"
    bump(c)
    return success_object(pool_contract_view(c))


@bp.route("/shops/<shopId>/pool-contracts/<contractId>/resume", methods=["POST"])
def resume_contract(shopId, contractId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    c = get_contract_or_404(contractId, shopId)
    if c["status"] != "SUSPENDED":
        raise err_invalid_state("Contract must be SUSPENDED to resume")
    c["status"] = "ACTIVE"
    bump(c)
    return success_object(pool_contract_view(c))


@bp.route("/shops/<shopId>/pool-contracts/<contractId>/terminate", methods=["POST"])
def terminate_contract(shopId, contractId):
    require_role("ServiceManager")
    get_shop_or_404(shopId)
    c = get_contract_or_404(contractId, shopId)
    if c["status"] == "ACTIVE":
        if _has_open_loans(contractId):
            raise err_invalid_state("Contract has open loans")
    elif c["status"] == "SUSPENDED":
        pass
    else:
        raise err_invalid_state("Contract cannot be terminated from this state")
    c["status"] = "TERMINATED"
    bump(c)
    return success_object(pool_contract_view(c))


# ---------- Loans ----------

@bp.route("/shops/<shopId>/pool-contracts/<contractId>/loans", methods=["POST"])
def checkout_loan(shopId, contractId):
    require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    contract = get_contract_or_404(contractId, shopId)
    body = get_json_body()
    work_order_id = body.get("work_order_id")
    spare_motor_id = body.get("spare_motor_id")
    if not isinstance(work_order_id, str) or not isinstance(spare_motor_id, str):
        raise err_invalid_input("work_order_id and spare_motor_id are required strings")
    wo = store.work_orders.get(work_order_id)
    if wo is None or wo["shop_id"] != shopId:
        raise err_reference_not_found("work_order_id does not resolve")
    spare = store.motors.get(spare_motor_id)
    if spare is None or spare["shop_id"] != shopId:
        raise err_reference_not_found("spare_motor_id does not resolve")

    # availability gates (all ERR_POOL_UNAVAILABLE)
    if contract["status"] != "ACTIVE":
        raise err_pool_unavailable("Contract is not ACTIVE")
    active_loans = [
        l for l in store.pool_loans.values()
        if l["contract_id"] == contractId and l["status"] in ("OUT", "OVERDUE")
    ]
    if len(active_loans) >= contract["slot_count"]:
        raise err_pool_unavailable("No available slots")
    if not spare["is_pool_spare"] or spare["custody"] != "IN_POOL":
        raise err_pool_unavailable("Spare is not IN_POOL")
    repair_motor = store.motors[wo["motor_id"]]
    spare_kw = Decimal(str(spare["rated_kw"]))
    repair_kw = Decimal(str(repair_motor["rated_kw"]))
    low = repair_kw * Decimal("0.8")
    high = repair_kw * Decimal("1.2")
    if spare_kw < low or spare_kw > high:
        raise err_pool_unavailable("Spare rated_kw outside +/-20% band")

    now = store.now()
    loan = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "contract_id": contractId,
        "work_order_id": work_order_id,
        "spare_motor_id": spare_motor_id,
        "checked_out_at": now,
        "due_at": None,
        "returned_at": None,
        "overdue_days": 0,
        "overdue_charge_cents": 0,
        "status": "OUT",
        "_shop_id": shopId,
    }
    store.pool_loans[loan["id"]] = loan
    spare["custody"] = "ON_LOAN"
    bump(spare)
    return success_object(pool_loan_view(loan), status=201)


def _list_loans(contract_id_filter):
    items = list(store.pool_loans.values())
    if contract_id_filter is not None:
        items = [l for l in items if l["contract_id"] == contract_id_filter]
    if request.args.get("work_order_id"):
        items = [l for l in items if l["work_order_id"] == request.args["work_order_id"]]
    if request.args.get("spare_motor_id"):
        items = [l for l in items if l["spare_motor_id"] == request.args["spare_motor_id"]]
    if request.args.get("status"):
        items = [l for l in items if l["status"] == request.args["status"]]
    for l in items:
        refresh_pool_loan(l)
    items.sort(key=lambda l: l["created_at"])
    return items


@bp.route("/shops/<shopId>/pool-contracts/<contractId>/loans", methods=["GET"])
def list_loans(shopId, contractId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    get_shop_or_404(shopId)
    get_contract_or_404(contractId, shopId)
    limit, offset = get_pagination()
    items = _list_loans(contractId)
    page, total = paginate(items, limit, offset)
    return success_list([pool_loan_view(l) for l in page], limit, offset, total)


@bp.route("/shops/pool-loans", methods=["GET"])
def list_loans_flat():
    require_role("ShopAdmin", "Estimator", "ServiceManager")
    limit, offset = get_pagination()
    contract_id = request.args.get("contract_id")
    items = _list_loans(contract_id)
    page, total = paginate(items, limit, offset)
    return success_list([pool_loan_view(l) for l in page], limit, offset, total)


@bp.route("/shops/pool-loans/<loanId>", methods=["GET"])
def get_loan_flat(loanId):
    require_role("ShopAdmin", "Estimator", "ServiceManager", "Customer")
    loan = get_loan_or_404(loanId)
    refresh_pool_loan(loan)
    return success_object(pool_loan_view(loan))


@bp.route("/shops/<shopId>/pool-contracts/<contractId>/loans/<loanId>/return", methods=["POST"])
def return_loan(shopId, contractId, loanId):
    require_role("ServiceManager")
    shop = get_shop_or_404(shopId)
    contract = get_contract_or_404(contractId, shopId)
    loan = get_loan_or_404(loanId, contractId)
    if loan["status"] not in ("OUT", "OVERDUE"):
        raise err_invalid_state("Loan must be OUT or OVERDUE to return")
    now = store.now()
    loan["returned_at"] = now
    od, oc = calc.compute_overdue(loan["due_at"], now, now, shop["pool_loan_daily_cents"])
    loan["overdue_days"] = od
    loan["overdue_charge_cents"] = oc
    loan["status"] = "RETURNED"
    spare = store.motors[loan["spare_motor_id"]]
    spare["custody"] = "IN_POOL"
    bump(spare)
    bump(loan)

    # surcharge invoice when charge > 0
    if oc > 0:
        inv = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "work_order_id": loan["work_order_id"],
            "customer_id": contract["customer_id"],
            "total_cents": oc,
            "amount_paid_cents": 0,
            "balance_due_cents": oc,
            "issued_at": now,
            "due_at": now,  # due immediately
            "status": "OPEN",
        }
        from datetime import timedelta
        inv["due_at"] = now + timedelta(days=30)
        store.invoices[inv["id"]] = inv

    recompute_standing(contract["customer_id"])
    return success_object(pool_loan_view(loan))
