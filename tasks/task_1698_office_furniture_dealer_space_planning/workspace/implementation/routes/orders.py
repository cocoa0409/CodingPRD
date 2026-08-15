"""ProjectOrder routes: the order lifecycle — submit gauntlet with version
pinning, manufacturer acknowledgment, cancel with restocking fee, credit
application, and close."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_CONTRACT_NOT_EFFECTIVE,
    ERR_CONTRACT_PRICING_VIOLATION,
    ERR_PLAN_NOT_APPROVED,
    ERR_PLAN_SUPERSEDED,
    ERR_TYPICAL_PLAN_MISMATCH,
    ERR_INSTALL_NOT_COMPLETE,
    ERR_ORDER_HAS_OPEN_PUNCH,
    ERR_CREDIT_CAP_EXCEEDED,
    ERR_INSUFFICIENT_CREDIT,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import (
    get_or_404, new_entity, touch,
    lines_of_order, punches_of_order,
    recompute_order_totals, recompute_promised_date, recompute_customer_balance,
    credit_cap_cents, apply_lot_consumption_fifo, rollback_lot_consumption,
)
from services.pricing import (
    MAX_DISCOUNT_PCT, price_line, resolve_discount_pct, set_provisional_lead,
    set_confirmed_lead, restocking_fee,
)
from util import CLOCK, parse_date
from validate import body_dict, req_str, req_int

bp = Blueprint("project_orders", __name__)


def _check_contract_effective(contract):
    """Contract ACTIVE and current UTC date within [effective_from, effective_to]
    inclusive."""
    if contract["status"] != "ACTIVE":
        raise_error(ERR_CONTRACT_NOT_EFFECTIVE, f"contract is {contract['status']}, not ACTIVE")
    today = CLOCK.today()
    from_d = parse_date(contract["effective_from"])
    to_d = parse_date(contract["effective_to"])
    if from_d is not None and today < from_d:
        raise_error(ERR_CONTRACT_NOT_EFFECTIVE, "current date precedes the contract effectiveness window")
    if to_d is not None and today > to_d:
        raise_error(ERR_CONTRACT_NOT_EFFECTIVE, "current date is past the contract effectiveness window")


@bp.route("/api/project-orders", methods=["POST"])
def create_order():
    authorize(["AccountExecutive"])
    body = body_dict()
    customer_id = req_str(body, "customer_id")
    contract_id = req_str(body, "contract_id")
    space_plan_id = req_str(body, "space_plan_id")
    # priority 3: FK existence
    customer = get_or_404("customers", customer_id)
    get_or_404("pricing_contracts", contract_id)
    get_or_404("space_plans", space_plan_id)
    # business safety: customer must be ACTIVE
    if customer["status"] != "ACTIVE":
        raise_error(ERR_CUSTOMER_NOT_ACTIVE, f"customer is {customer['status']}, not ACTIVE")
    order = new_entity("project_orders", {
        "customer_id": customer_id,
        "contract_id": contract_id,
        "space_plan_id": space_plan_id,
        "pinned_contract_version": None,
        "pinned_plan_version": None,
        "total_list_cents": 0,
        "total_net_cents": 0,
        "install_fee_cents": 0,
        "credit_applied_cents": 0,
        "grand_total_cents": 0,
        "promised_date": None,
        "cancel_fee_cents": 0,
        "status": "DRAFT",
        "install_posture": "NOT_SCHEDULED",
        "_lot_consumption": [],
    })
    return success_object(public(order), status=201)


@bp.route("/api/project-orders", methods=["GET"])
def list_orders():
    authorize(ALL_ROLES)
    return list_response("project_orders", ["customer_id", "contract_id", "space_plan_id", "status"])


@bp.route("/api/project-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    authorize(ALL_ROLES)
    return get_response("project_orders", order_id)


@bp.route("/api/project-orders/<order_id>/submit", methods=["POST"])
def submit_order(order_id):
    authorize(["AccountExecutive"])
    order = get_or_404("project_orders", order_id)
    # priority 4: transition exists only from DRAFT; at least one OPEN line
    if order["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot submit an order in status {order['status']}")
    lines = lines_of_order(order_id)
    if not any(l["status"] == "OPEN" for l in lines):
        raise_error(ERR_INVALID_STATE, "an order requires at least one OPEN line to submit")
    customer = get_or_404("customers", order["customer_id"])
    contract = get_or_404("pricing_contracts", order["contract_id"])
    plan = get_or_404("space_plans", order["space_plan_id"])
    # priority 5: customer standing
    if customer["status"] != "ACTIVE":
        raise_error(ERR_CUSTOMER_NOT_ACTIVE, f"customer is {customer['status']}, not ACTIVE")
    # priority 6: contract effectiveness
    _check_contract_effective(contract)
    # priority 7a: plan approval and approval-anchor freshness
    if plan["status"] == "SUPERSEDED":
        raise_error(ERR_PLAN_SUPERSEDED, "the space plan has been SUPERSEDED")
    if plan["status"] != "APPROVED":
        raise_error(ERR_PLAN_NOT_APPROVED, f"space plan is {plan['status']}, not APPROVED")
    if plan.get("approved_version") != plan["version"]:
        raise_error(ERR_PLAN_SUPERSEDED, "the plan's approval anchor is stale")
    # priority 7b: every line's typical (when set) belongs to the order's plan
    for line in lines:
        typical_id = line.get("typical_id")
        if typical_id:
            typical = db["typicals"].get(typical_id)
            if typical is None or typical["space_plan_id"] != order["space_plan_id"]:
                raise_error(ERR_TYPICAL_PLAN_MISMATCH,
                            f"line typical {typical_id} does not belong to plan {order['space_plan_id']}")
    # priority 9: pricing compliance re-checked line by line
    for line in lines:
        series = db["product_series"].get(line["series_id"])
        if series is None or line.get("is_replacement"):
            continue
        discount = resolve_discount_pct(contract, series["category"], line["quantity"])
        if discount > MAX_DISCOUNT_PCT:
            raise_error(ERR_CONTRACT_PRICING_VIOLATION,
                        f"resolved discount {discount}% exceeds the {MAX_DISCOUNT_PCT}% maximum")
    # side effects: reprice, provisional lead times, rollup, pins, transitions
    submit_date = CLOCK.today()
    for line in lines:
        series = db["product_series"].get(line["series_id"])
        if series is not None:
            price_line(line, series, contract)
            set_provisional_lead(line, series, submit_date)
        if line["status"] == "OPEN":
            line["status"] = "PLACED"
        touch(line)
    order["pinned_contract_version"] = contract["version"]
    order["pinned_plan_version"] = plan["approved_version"]
    order["status"] = "SUBMITTED"
    recompute_order_totals(order)
    recompute_promised_date(order)
    return success_object(public(order))


@bp.route("/api/project-orders/<order_id>/revise", methods=["POST"])
def revise_order(order_id):
    authorize(["AccountExecutive"])
    order = get_or_404("project_orders", order_id)
    if order["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"cannot revise an order in status {order['status']}")
    order["pinned_contract_version"] = None
    order["pinned_plan_version"] = None
    order["status"] = "DRAFT"
    for line in lines_of_order(order_id):
        if line["status"] == "PLACED":
            line["status"] = "OPEN"
            touch(line)
    touch(order)
    return success_object(public(order))


@bp.route("/api/project-orders/<order_id>/acknowledge", methods=["POST"])
def acknowledge_order(order_id):
    authorize(["ManufacturerRep"])
    order = get_or_404("project_orders", order_id)
    if order["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, f"cannot acknowledge an order in status {order['status']}")
    contract = get_or_404("pricing_contracts", order["contract_id"])
    plan = get_or_404("space_plans", order["space_plan_id"])
    # priority 6: pinned contract version still current, contract still ACTIVE
    if contract["status"] != "ACTIVE" or order.get("pinned_contract_version") != contract["version"]:
        raise_error(ERR_CONTRACT_NOT_EFFECTIVE, "the pinned contract version is no longer current")
    # priority 7a: pinned plan version still the approved anchor
    if plan["status"] != "APPROVED" or order.get("pinned_plan_version") != plan.get("approved_version"):
        raise_error(ERR_PLAN_SUPERSEDED, "the pinned plan version is no longer the approved one")
    ack_date = CLOCK.today()
    for line in lines_of_order(order_id):
        if line["status"] == "PLACED":
            series = db["product_series"].get(line["series_id"])
            if series is not None:
                set_confirmed_lead(line, series, ack_date)
            line["status"] = "ACKNOWLEDGED"
            touch(line)
    order["status"] = "ACKNOWLEDGED"
    recompute_promised_date(order)
    touch(order)
    return success_object(public(order))


@bp.route("/api/project-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    authorize(["AccountExecutive"])
    order = get_or_404("project_orders", order_id)
    if order["status"] not in ("DRAFT", "SUBMITTED", "ACKNOWLEDGED"):
        raise_error(ERR_INVALID_STATE, f"cannot cancel an order in status {order['status']}")
    prior_status = order["status"]
    all_lines = lines_of_order(order_id, include_cancelled=True)
    fee = 0
    if prior_status == "ACKNOWLEDGED":
        fee = restocking_fee(all_lines)
    # line and reservation cascades
    for line in all_lines:
        if prior_status == "SUBMITTED" and line["status"] == "PLACED":
            line["status"] = "CANCELLED"
            touch(line)
        elif prior_status == "ACKNOWLEDGED" and line["status"] == "ACKNOWLEDGED":
            line["status"] = "CANCELLED"
            touch(line)
        if prior_status == "ACKNOWLEDGED" and line["status"] == "CANCELLED":
            for r in db["staging_reservations"].values():
                if r["order_line_id"] == line["id"] and r["status"] == "RESERVED":
                    r["status"] = "CANCELLED"
                    touch(r)
    order["status"] = "CANCELLED"
    order["cancel_fee_cents"] = fee
    touch(order)
    customer = db["customers"].get(order["customer_id"])
    if customer is not None:
        # credit_applied_cents returns to the ledger: the order drops out of the
        # non-CANCELLED credit_applied term, and the lot FIFO pool is restored.
        rollback_lot_consumption(order.get("_lot_consumption") or [])
        order["_lot_consumption"] = []
        recompute_customer_balance(customer)
        if fee > 0:
            # restocking fee is debited from the credit ledger first; any
            # remainder above the balance stays recorded on the order as due.
            debit = min(fee, customer["liquidation_credit_balance_cents"])
            if debit > 0:
                customer["_fee_debits"] = customer.get("_fee_debits", 0) + debit
                recompute_customer_balance(customer)
    return success_object(public(order))


@bp.route("/api/project-orders/<order_id>/apply_credit", methods=["POST"])
def apply_credit(order_id):
    authorize(["FinanceManager"])
    order = get_or_404("project_orders", order_id)
    if order["status"] not in ("SUBMITTED", "ACKNOWLEDGED"):
        raise_error(ERR_INVALID_STATE, f"cannot apply credit to an order in status {order['status']}")
    body = body_dict()
    amount = req_int(body, "amount_cents", minv=1)
    customer = get_or_404("customers", order["customer_id"])
    # priority 9, money-last ordering: credit cap first, then balance
    new_applied = order["credit_applied_cents"] + amount
    if new_applied > credit_cap_cents(order):
        raise_error(ERR_CREDIT_CAP_EXCEEDED,
                    "credit_applied_cents would exceed the per-order credit cap")
    if amount > customer["liquidation_credit_balance_cents"]:
        raise_error(ERR_INSUFFICIENT_CREDIT, "amount exceeds the customer's available credit balance")
    order["credit_applied_cents"] = new_applied
    order["_lot_consumption"] = (order.get("_lot_consumption") or []) + \
        apply_lot_consumption_fifo(customer["id"], amount)
    recompute_order_totals(order)
    recompute_customer_balance(customer)
    return success_object(public(order))


@bp.route("/api/project-orders/<order_id>/close", methods=["POST"])
def close_order(order_id):
    authorize(["ProjectManager"])
    order = get_or_404("project_orders", order_id)
    if order["status"] not in ("DELIVERED", "INSTALLED"):
        raise_error(ERR_INVALID_STATE, f"cannot close an order in status {order['status']}")
    # priority 7f: install completion gate first, then open punch items
    if order["install_posture"] != "COMPLETE":
        raise_error(ERR_INSTALL_NOT_COMPLETE, "install_posture is not COMPLETE")
    open_punches = [p for p in punches_of_order(order_id) if p["status"] != "CLOSED"]
    if open_punches:
        raise_error(ERR_ORDER_HAS_OPEN_PUNCH, "the order has punch items that are not CLOSED")
    for line in lines_of_order(order_id):
        if line["status"] == "RECEIVED":
            line["status"] = "CLOSED"
            touch(line)
    order["status"] = "CLOSED"
    touch(order)
    return success_object(public(order))
