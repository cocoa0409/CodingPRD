"""Credit claims: creation, four-eyes resolution and settlement (PRD §3.8)."""

from flask import Blueprint

import calc
from envelope import list_response, object_response
from errors import ApiError
from helpers import auth, f_enum, f_int, f_string, get_body, pagination, q_enum, q_str
from routes.common import paginate, require
from store import base_row, db, public, touch

bp = Blueprint("claims", __name__)

CLAIM_TYPES = ("MISSING_ITEM", "QUALITY_ISSUE", "NEVER_DELIVERED")
CLAIM_STATUSES = ("SUBMITTED", "ROUTED_EMPLOYEE_FIRST", "ROUTED_PROPORTIONAL",
                  "SETTLED", "DENIED")
DECISIONS = ("APPROVE", "DENY")
ROUTING_BASES = ("EMPLOYEE_FIRST", "PROPORTIONAL")
DIRECTIONS = ("EMPLOYER_CREDIT", "EMPLOYEE_CARD_REFUND")
REASONS = ("CLAIM_SETTLEMENT", "ORDER_VOID")


def remaining_refundable(order):
    return (order["gross_total_cents"]
            - order["employer_refunded_cents"]
            - order["employee_refunded_cents"])


def line_cap(order, line_index):
    line = order["lines"][line_index]
    return calc.line_base(line) + calc.line_tax(line)


def bucket_status(order):
    record = calc.find_imputed_record(order["employee_id"], order["tax_month"])
    return record["status"] if record is not None else None


@bp.post("/credit-claims")
def create_claim():
    user_id, _role = auth("Employee")
    body = get_body()

    raw_order_id = body.get("order_id")
    order = db.orders.get(raw_order_id) if isinstance(raw_order_id, str) else None
    # rank 3 — ownership, before request-shape validation of the remaining fields
    if order is not None and order["employee_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE",
                       "An employee may only claim against their own orders.")

    order_id = f_string(body, "order_id")
    claim_type = f_enum(body, "claim_type", CLAIM_TYPES)
    claimed_cents = f_int(body, "claimed_cents", minimum=1)
    line_index = f_int(body, "line_index", required=False, minimum=0)

    # rank 7
    order = require(db.orders, order_id, "ERR_ORDER_NOT_FOUND")

    # rank 8 — a claim only addresses a delivered order
    if order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE",
                       "A claim may only be raised against a DELIVERED order.")

    # rank 35 — conditional line addressing
    lines = order["lines"]
    if claim_type == "MISSING_ITEM":
        if line_index is None or line_index >= len(lines):
            raise ApiError("ERR_LINE_INDEX_INVALID",
                           "A MISSING_ITEM claim must address an existing line.")
    elif claim_type == "NEVER_DELIVERED":
        if line_index is not None:
            raise ApiError("ERR_LINE_INDEX_INVALID",
                           "A NEVER_DELIVERED claim must not carry a line_index.")

    # rank 36
    if claimed_cents > remaining_refundable(order):
        raise ApiError("ERR_CLAIM_EXCEEDS_ORDER",
                       "The claimed amount exceeds the order's remaining refundable amount.")
    if claim_type == "MISSING_ITEM" and claimed_cents > line_cap(order, line_index):
        raise ApiError("ERR_CLAIM_EXCEEDS_ORDER",
                       "The claimed amount exceeds the addressed line's base plus its tax.")

    row = base_row()
    row.update({
        "order_id": order["id"],
        "claim_type": claim_type,
        "line_index": line_index,
        "claimed_cents": claimed_cents,
        "approved_cents": 0,
        "routing_basis": None,
        "employer_credit_cents": 0,
        "employee_refund_cents": 0,
        "resolved_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.credit_claims[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/credit-claims/<claim_id>")
def read_claim(claim_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    claim = require(db.credit_claims, claim_id, "ERR_CREDIT_CLAIM_NOT_FOUND")
    return object_response(public(claim))


@bp.get("/credit-claims")
def list_claims():
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    order_id = q_str("order_id")
    status = q_enum("status", CLAIM_STATUSES)
    claim_type = q_enum("claim_type", CLAIM_TYPES)
    rows = list(db.credit_claims.values())
    if order_id is not None:
        rows = [c for c in rows if c["order_id"] == order_id]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if claim_type is not None:
        rows = [c for c in rows if c["claim_type"] == claim_type]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)


@bp.post("/credit-claims/<claim_id>/resolve")
def resolve_claim(claim_id):
    user_id, _role = auth("BenefitsController")
    body = get_body()
    decision = f_enum(body, "decision", DECISIONS)
    expected_order_version = f_int(body, "expected_order_version")
    approved_cents = f_int(body, "approved_cents", required=False, minimum=1)
    routing_basis = f_enum(body, "routing_basis", ROUTING_BASES, required=False)
    if decision == "APPROVE":
        if approved_cents is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Missing required field 'approved_cents' for an APPROVE decision.")
        if routing_basis is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "Missing required field 'routing_basis' for an APPROVE decision.")

    claim = require(db.credit_claims, claim_id, "ERR_CREDIT_CLAIM_NOT_FOUND")
    order = require(db.orders, claim["order_id"], "ERR_ORDER_NOT_FOUND")

    if decision == "APPROVE" and approved_cents > claim["claimed_cents"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'approved_cents' must be <= claimed_cents.")

    # rank 8
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE",
                       "A claim in status %s cannot be resolved." % claim["status"])
    if decision == "APPROVE" and order["fulfillment_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only a DELIVERED order may have a claim approved against it.")

    # rank 13
    if expected_order_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION",
                       "The order has been modified since it was read.")

    # rank 14
    if bucket_status(order) in ("LOCKED", "EXPORTED"):
        raise ApiError("ERR_TAX_MONTH_LOCKED",
                       "The imputed-income bucket for %s is closed." % order["tax_month"])

    if decision == "DENY":
        claim["approved_cents"] = 0
        claim["employer_credit_cents"] = 0
        claim["employee_refund_cents"] = 0
        claim["resolved_by_user_id"] = user_id
        claim["status"] = "DENIED"
        touch(claim)
        return object_response(public(claim))

    # rank 36 — the approved amount may not outrun the order
    if approved_cents > remaining_refundable(order):
        raise ApiError("ERR_CLAIM_EXCEEDS_ORDER",
                       "The approved amount exceeds the order's remaining refundable amount.")
    if claim["claim_type"] == "MISSING_ITEM":
        index = claim["line_index"]
        if index is not None and index < len(order["lines"]):
            if approved_cents > line_cap(order, index):
                raise ApiError("ERR_CLAIM_EXCEEDS_ORDER",
                               "The approved amount exceeds the addressed line's base plus tax.")

    employee_refund, employer_credit = calc.route_refund(order, approved_cents, routing_basis)
    claim["approved_cents"] = approved_cents
    claim["routing_basis"] = routing_basis
    claim["employee_refund_cents"] = employee_refund
    claim["employer_credit_cents"] = employer_credit
    claim["resolved_by_user_id"] = user_id
    claim["status"] = ("ROUTED_EMPLOYEE_FIRST" if routing_basis == "EMPLOYEE_FIRST"
                       else "ROUTED_PROPORTIONAL")
    touch(claim)
    touch(order)
    return object_response(public(claim))


@bp.post("/credit-claims/<claim_id>/settle")
def settle_claim(claim_id):
    user_id, _role = auth("BenefitsController")

    claim = db.credit_claims.get(claim_id)
    # rank 4 — segregation of duties, before request-shape validation
    if claim is not None and claim.get("resolved_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The settling user must differ from the resolving user.")
    get_body()

    if claim is None:
        raise ApiError("ERR_CREDIT_CLAIM_NOT_FOUND")

    if claim["status"] not in ("ROUTED_EMPLOYEE_FIRST", "ROUTED_PROPORTIONAL"):
        raise ApiError("ERR_INVALID_STATE",
                       "A claim in status %s cannot be settled." % claim["status"])

    order = require(db.orders, claim["order_id"], "ERR_ORDER_NOT_FOUND")

    # rank 14
    if bucket_status(order) in ("LOCKED", "EXPORTED"):
        raise ApiError("ERR_TAX_MONTH_LOCKED",
                       "The imputed-income bucket for %s is closed." % order["tax_month"])

    employer_credit = claim["employer_credit_cents"]
    employee_refund = claim["employee_refund_cents"]

    if employer_credit > 0:
        calc.write_ledger_entry(order["id"], "EMPLOYER_CREDIT", employer_credit,
                                "CLAIM_SETTLEMENT", credit_claim_id=claim["id"])
    if employee_refund > 0:
        calc.write_ledger_entry(order["id"], "EMPLOYEE_CARD_REFUND", employee_refund,
                                "CLAIM_SETTLEMENT", credit_claim_id=claim["id"])

    entries = calc.order_ledger_entries(order["id"])
    order["employer_refunded_cents"] = sum(e["amount_cents"] for e in entries
                                           if e["direction"] == "EMPLOYER_CREDIT")
    order["employee_refunded_cents"] = sum(e["amount_cents"] for e in entries
                                           if e["direction"] == "EMPLOYEE_CARD_REFUND")
    cumulative = order["employer_refunded_cents"] + order["employee_refunded_cents"]
    order["net_charged_cents"] = order["gross_total_cents"] - cumulative
    order["employer_net_cents"] = (order["employer_covered_cents"]
                                   - order["employer_refunded_cents"])
    if cumulative >= order["gross_total_cents"]:
        order["settlement_status"] = "REFUNDED"
        order["net_charged_cents"] = 0
    else:
        order["settlement_status"] = "PARTIALLY_REFUNDED"

    period = db.benefit_periods.get(order["benefit_period_id"])
    if period is not None and employer_credit > 0:
        period["spent_cents"] -= employer_credit
        period["available_cents"] += employer_credit
        touch(period)

    claim["status"] = "SETTLED"
    touch(claim)
    touch(order)

    calc.reconcile_imputed(order["employee_id"], order["tax_month"])
    employee = db.employees.get(order["employee_id"])
    if employee:
        calc.recompute_program_rollups(employee["program_id"])

    return object_response(public(claim))


@bp.get("/credit-claims/<claim_id>/refund-entries")
def list_claim_entries(claim_id):
    auth("ProgramAdmin", "BenefitsController", "Employee")
    limit, offset = pagination()
    direction = q_enum("direction", DIRECTIONS)
    reason = q_enum("reason", REASONS)
    claim = require(db.credit_claims, claim_id, "ERR_CREDIT_CLAIM_NOT_FOUND")
    rows = [e for e in db.refund_entries.values()
            if e.get("credit_claim_id") == claim["id"]]
    if direction is not None:
        rows = [e for e in rows if e["direction"] == direction]
    if reason is not None:
        rows = [e for e in rows if e["reason"] == reason]
    items, total = paginate(rows, limit, offset)
    return list_response(items, limit, offset, total)
