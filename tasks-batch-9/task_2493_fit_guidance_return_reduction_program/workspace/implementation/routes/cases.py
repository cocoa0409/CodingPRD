"""Return cases: opening, coding, closing and reversing (PRD 3.7, 3.8)."""

from flask import Blueprint

import clock
import constants as C
import validate as V
from db import db, new_row, touch
from errors import ApiError
from lookup import (ensure_not_delisted, filtered, get_customer, get_item,
                    get_order_line, get_return_case)
from middleware import authenticate, require_owner
from response import array_response, object_response
from services.derive import (effective_window_days, postings_of_case,
                             recompute_customer, recompute_item, recompute_vendor)
from services.policy import resolve_effective_policy, return_deadline_at
from services.returns import (compute_fee_and_refund, write_original_postings,
                              write_reversal_postings)

bp = Blueprint("return_cases", __name__)


def _line_and_parents(case):
    line = db.order_lines.get(case["order_line_id"])
    item = db.items.get(line["item_id"]) if line is not None else None
    customer = db.customers.get(line["customer_profile_id"]) if line else None
    return line, item, customer


@bp.post("/fit-program/return-cases")
def open_return_case():
    actor = authenticate(C.ROLE_CUSTOMER)

    # rank 4 precedes rank 5: peek at the body's order_line_id
    peeked = V.peek_str(V.raw_body(), "order_line_id")
    if peeked is not None and peeked in db.order_lines:
        require_owner(
            db.order_lines[peeked]["customer_profile_id"] == actor.user_id,
            "A Customer may only open returns on their own order lines.")

    body = V.get_body()
    order_line_id = V.req_str(body, "order_line_id", min_len=1)
    requested_reason_code = V.req_enum(body, "requested_reason_code", C.REASON_CODES)
    V.opt_str(body, "comment")

    line = get_order_line(order_line_id)
    require_owner(line["customer_profile_id"] == actor.user_id,
                  "A Customer may only open returns on their own order lines.")

    item = get_item(line["item_id"])
    ensure_not_delisted(item)

    customer = get_customer(line["customer_profile_id"])
    if customer["abuse_status"] == "BLOCKED":
        raise ApiError("ERR_CUSTOMER_RETURN_BLOCKED",
                       "This shopper is BLOCKED from opening new returns.")

    # the window check needs a resolved policy, so resolution runs first; when no
    # candidate exists there is no window to evaluate and rank 15 is what fires
    policy = resolve_effective_policy(item["category_code"], customer["id"])
    if policy is None:
        raise ApiError("ERR_NO_RETURN_POLICY",
                       "No return policy row governs this category for this shopper.")

    window_days = effective_window_days(policy["window_days"],
                                        customer["policy_class"])
    deadline = return_deadline_at(line["delivered_at"], window_days)
    now = clock.now()
    if now > deadline:
        raise ApiError("ERR_RETURN_WINDOW_CLOSED",
                       "The return window closed at %s." % clock.iso(deadline))

    for existing in db.return_cases.values():
        if existing["order_line_id"] != line["id"]:
            continue
        if existing["status"] in C.LIVE_OR_CLOSED_CASE_STATUSES:
            raise ApiError("ERR_DUPLICATE_RETURN_CASE",
                           "This order line already carries a %s return case."
                           % existing["status"])

    case = new_row({
        "order_line_id": line["id"],
        "requested_reason_code": requested_reason_code,
        "reason_code": requested_reason_code,
        "reason_family": C.REASON_FAMILY_OF[requested_reason_code],
        "status": "TRIAGE",
        "effective_policy_id": policy["id"],
        "effective_window_days": window_days,
        "return_deadline_at": deadline,
        "requested_at": now,
        "item_condition": None,
        "restocking_fee_cents": 0,
        "refund_amount_cents": 0,
        "total_cost_cents": 0,
        "classified_by_user_id": None,
        "resolved_by_user_id": None,
        "void_reason": None,
    })
    db.return_cases[case["id"]] = case

    line["status"] = "RETURN_IN_PROGRESS"
    touch(line)

    recompute_customer(customer)
    return object_response(case, 201)


@bp.get("/fit-program/return-cases/<case_id>")
def read_return_case(case_id):
    actor = authenticate(C.ROLE_RETURNS_AUDITOR, C.ROLE_MERCH_OPS_ADMIN,
                         C.ROLE_CUSTOMER)
    case = get_return_case(case_id)
    if actor.role == C.ROLE_CUSTOMER:
        line = db.order_lines.get(case["order_line_id"])
        require_owner(line is not None
                      and line["customer_profile_id"] == actor.user_id,
                      "A Customer may only read their own return cases.")
    return object_response(case)


@bp.get("/fit-program/return-cases")
def list_return_cases():
    authenticate(C.ROLE_RETURNS_AUDITOR, C.ROLE_MERCH_OPS_ADMIN)
    limit, offset = V.pagination_params()
    rows = filtered(db.return_cases.values(), {
        "order_line_id": "order_line_id",
        "effective_policy_id": "effective_policy_id",
        "status": "status",
        "reason_family": "reason_family",
    })
    page, meta = V.paginate(rows, limit, offset)
    return array_response(page, meta)


BRANCH_OF_FAMILY = {
    "FIT": "FIT_REVIEW",
    "QUALITY": "QUALITY_REVIEW",
    "EXPECTATION": "EXPECTATION_REVIEW",
    "CHANGE_OF_MIND": "COOLING_OFF",
}


@bp.post("/fit-program/return-cases/<case_id>/classify")
def classify_return_case(case_id):
    actor = authenticate(C.ROLE_RETURNS_AUDITOR)
    case = get_return_case(case_id)
    body = V.get_body()
    reason_code = V.req_enum(body, "reason_code", C.REASON_CODES)
    V.opt_str(body, "evidence_note")

    if case["status"] != "TRIAGE":
        raise ApiError("ERR_INVALID_RETURN_CASE_STATE",
                       "Only a TRIAGE case can be classified; this one is %s."
                       % case["status"])

    case["reason_code"] = reason_code
    case["reason_family"] = C.REASON_FAMILY_OF[reason_code]
    case["classified_by_user_id"] = actor.user_id
    case["status"] = BRANCH_OF_FAMILY[case["reason_family"]]
    touch(case)
    return object_response(case)


@bp.post("/fit-program/return-cases/<case_id>/resolve")
def resolve_return_case(case_id):
    actor = authenticate(C.ROLE_RETURNS_AUDITOR)
    case = get_return_case(case_id)
    body = V.get_body()
    item_condition = V.req_enum(body, "item_condition", C.ITEM_CONDITIONS)
    V.opt_str(body, "resolution_note")

    if case["status"] not in C.REVIEW_BRANCH_STATUSES:
        raise ApiError("ERR_INVALID_RETURN_CASE_STATE",
                       "Only a case in a review branch can be resolved; this one "
                       "is %s." % case["status"])

    if (case["classified_by_user_id"] is not None
            and case["classified_by_user_id"] == actor.user_id):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The operator who classified a case may not resolve it.")

    line, item, customer = _line_and_parents(case)
    policy = db.policies.get(case["effective_policy_id"])

    refunded = customer["abuse_status"] != "BLOCKED"

    # the fee and the refund are computed first, before any posting is written
    fee, refund = compute_fee_and_refund(case, line, policy, customer, refunded)
    total_cost = write_original_postings(case, line, item, item_condition,
                                         refund, refunded)

    case["item_condition"] = item_condition
    case["restocking_fee_cents"] = fee
    case["refund_amount_cents"] = refund
    case["total_cost_cents"] = total_cost
    case["resolved_by_user_id"] = actor.user_id
    case["status"] = "RESOLVED_REFUNDED" if refunded else "RESOLVED_DENIED"
    touch(case)

    line["status"] = "RETURNED" if refunded else "KEPT"
    touch(line)

    recompute_item(item, set_pdp_review=(case["reason_family"] == "EXPECTATION"))
    if case["reason_family"] == "QUALITY":
        vendor = db.vendors.get(item["vendor_id"])
        if vendor is not None:
            recompute_vendor(vendor)
    recompute_customer(customer)

    return object_response(case)


@bp.post("/fit-program/return-cases/<case_id>/void")
def void_return_case(case_id):
    authenticate(C.ROLE_RETURNS_AUDITOR)
    case = get_return_case(case_id)
    body = V.get_body()
    void_reason = V.req_enum(body, "void_reason", C.VOID_REASONS)

    if case["status"] not in C.RESOLVED_CASE_STATUSES:
        raise ApiError("ERR_INVALID_RETURN_CASE_STATE",
                       "Only a resolved case can be voided; this one is %s."
                       % case["status"])

    line, item, customer = _line_and_parents(case)

    write_reversal_postings(case)

    # refund_amount_cents and restocking_fee_cents keep their historical values
    case["void_reason"] = void_reason
    case["total_cost_cents"] = 0
    case["status"] = "VOIDED"
    touch(case)

    line["status"] = "DELIVERED"
    touch(line)

    recompute_item(item)
    if case["reason_family"] == "QUALITY":
        vendor = db.vendors.get(item["vendor_id"])
        if vendor is not None:
            recompute_vendor(vendor)
    recompute_customer(customer)

    return object_response(case)


@bp.get("/fit-program/return-cases/<case_id>/cost-postings")
def read_cost_postings(case_id):
    authenticate(C.ROLE_RETURNS_AUDITOR, C.ROLE_MERCH_OPS_ADMIN)
    case = get_return_case(case_id)
    return array_response(postings_of_case(case["id"]))
