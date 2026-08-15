"""GarnishmentOrder intake, lifecycle, and corrections (PRD §3.3, §3.4, §3.8).

Two parallel dimensions: processing_status walks the legal pipeline while
remit_posture (REMITTING | HELD | CLOSED) independently gates withholding.
Terminal processing states always carry a CLOSED posture.
"""

import re
from datetime import timedelta

from flask import Blueprint

from db import logical_now, next_seq, store
from errors import (
    ERR_AUTHORITY_MISMATCH,
    ERR_CASE_NUMBER_PATTERN,
    ERR_DUPLICATE_ACTIVE_ORDER,
    ERR_EMPLOYEE_TERMINATED_INELIGIBLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_REFUND_EXCEEDS_WITHHELD,
    ERR_STALE_VERSION,
    ERR_STATE_RULE_MISSING,
    ERR_SUSPEND_LIMIT_EXCEEDED,
    fail,
)
from middleware import (
    ALL_ROLES,
    ROLE_MANAGER,
    ROLE_SPECIALIST,
    authorize,
    get_body,
    pagination,
    public,
    req_date,
    req_enum,
    req_int,
    req_str,
    sort_created,
)
from response import list_response, object_response
from routes.employees import get_employee_or_404
from services import audit
from util import (
    ANSWER_SLA_DAYS,
    MAX_SUSPENSIONS,
    NOTIFICATION_SLA_DAYS,
    add_business_days,
    new_uuid,
    parse_date,
    render_date,
    render_instant,
)

bp = Blueprint("orders", __name__)

ORDER_TYPES = ("CHILD_SUPPORT", "FEDERAL_TAX_LEVY", "STUDENT_LOAN", "CREDITOR")
AMOUNT_MODELS = ("PERCENT_OF_DISPOSABLE", "FIXED_AMOUNT_PER_PERIOD", "LUMP_SUM_BALANCE")
HOLD_REASONS = ("DISPUTED", "REFUND_PENDING")

TERMINAL_STATES = ("SATISFIED", "TERMINATED", "REJECTED")

# order_type -> acceptable issuing-authority types (exact compatibility).
AUTHORITY_COMPATIBILITY = {
    "CHILD_SUPPORT": {"CHILD_SUPPORT_AGENCY"},
    "FEDERAL_TAX_LEVY": {"FEDERAL_AGENCY"},
    "STUDENT_LOAN": {"FEDERAL_AGENCY", "STATE_AGENCY"},
    "CREDITOR": {"COURT"},
}


def get_order_or_404(order_id):
    order = store.orders.get(order_id)
    if order is None:
        fail(ERR_NOT_FOUND, 404, "GarnishmentOrder '%s' does not exist." % order_id)
    return order


def _touch(order):
    order["updated_at"] = render_instant(logical_now())
    order["version"] += 1


def _duplicate_exists(employee_id, order_type, case_number, exclude_id=None,
                      later_than_seq=None):
    for other in store.orders.values():
        if other["employee_id"] != employee_id:
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if other["order_type"] != order_type or other["case_number"] != case_number:
            continue
        if other["processing_status"] in TERMINAL_STATES:
            continue
        if later_than_seq is not None and other["_seq"] <= later_than_seq:
            continue
        return True
    return False


def _check_duplicate(employee_id, order_type, case_number, exclude_id=None,
                     later_than_seq=None):
    if _duplicate_exists(employee_id, order_type, case_number, exclude_id,
                         later_than_seq):
        fail(ERR_DUPLICATE_ACTIVE_ORDER, 409,
             "Another non-terminal order on this employee already carries "
             "(order_type, case_number) = (%s, %s)." % (order_type, case_number))


# --------------------------------------------------------------------------
# Intake
# --------------------------------------------------------------------------

@bp.post("/employees/<employeeId>/orders")
def receive_order(employeeId):
    authorize(ROLE_SPECIALIST)
    employee = get_employee_or_404(employeeId)
    body = get_body()
    issuing_authority_id = req_str(body, "issuing_authority_id")
    case_number = req_str(body, "case_number")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    amount_model = req_enum(body, "amount_model", AMOUNT_MODELS)
    amount_value = req_int(body, "amount_value")
    total_balance_cents = req_int(body, "total_balance_cents")
    effective_date = req_date(body, "effective_date")
    expected_employee_version = req_int(body, "expected_employee_version")
    if amount_value < 0:
        fail(ERR_INVALID_REQUEST, 400, "amount_value must be >= 0.")
    if total_balance_cents <= 0:
        fail(ERR_INVALID_REQUEST, 400, "total_balance_cents must be a positive integer.")

    # Business-referential intake checks (authority, pattern, state rule).
    authority = store.authorities.get(issuing_authority_id)
    if authority is None:
        fail(ERR_NOT_FOUND, 404,
             "IssuingAuthority '%s' does not exist." % issuing_authority_id)
    if re.match(authority["accepted_case_number_pattern"], case_number) is None:
        fail(ERR_CASE_NUMBER_PATTERN, 422,
             "case_number '%s' does not match the authority's "
             "accepted_case_number_pattern." % case_number)
    if employee["work_state_code"] not in store.state_rules:
        fail(ERR_STATE_RULE_MISSING, 422,
             "No StateRule row for work_state_code '%s'."
             % employee["work_state_code"])

    # Duplicate-order safety.
    _check_duplicate(employee["id"], order_type, case_number)

    # OCC (§2.7): expected_employee_version must match.
    if expected_employee_version != employee["version"]:
        fail(ERR_STALE_VERSION, 412,
             "expected_employee_version %s does not match current employee "
             "version %s." % (expected_employee_version, employee["version"]))

    # Terminated-employee ineligibility.
    if employee["termination_date"] is not None:
        fail(ERR_EMPLOYEE_TERMINATED_INELIGIBLE, 409,
             "Employee '%s' is terminated and cannot receive orders."
             % employee["id"])

    received = logical_now()
    received_at = render_instant(received)
    now = received_at
    order = {
        "id": new_uuid(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "employee_id": employee["id"],
        "employer_id": employee["employer_id"],
        "issuing_authority_id": issuing_authority_id,
        "case_number": case_number,
        "order_type": order_type,
        "amount_model": amount_model,
        "amount_value": amount_value,
        "total_balance_cents": total_balance_cents,
        "remaining_balance_cents": total_balance_cents,
        "withheld_cents": 0,
        "refunded_cents": 0,
        "effective_date": effective_date,
        "received_at": received_at,
        # answer_deadline calc: 10 business days after the receipt date.
        "answer_due_date": render_date(add_business_days(received.date(), ANSWER_SLA_DAYS)),
        # 7 calendar days after received_at (datetime granularity).
        "notification_due_at": render_instant(received + timedelta(days=NOTIFICATION_SLA_DAYS)),
        "notification_sent_at": None,
        "notification_late": None,
        "processing_status": "RECEIVED",
        "remit_posture": "REMITTING",
        "hold_reason": None,
        "suspension_count": 0,
        "answer_type": None,
        "answer_date": None,
        "answer_timeliness": None,
        "_seq": next_seq(),
    }
    store.orders[order["id"]] = order

    # Cascade: Employee.version += 1.
    employee["version"] += 1
    employee["updated_at"] = now
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.receive",
                       details={"employee_id": employee["id"],
                                "case_number": case_number,
                                "order_type": order_type})
    return object_response(public(order), 201)


@bp.get("/orders/<orderId>")
def get_order(orderId):
    authorize(*ALL_ROLES)
    return object_response(public(get_order_or_404(orderId)))


# --------------------------------------------------------------------------
# Intake decisions
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/validate")
def validate_order(orderId):
    authorize(ROLE_SPECIALIST)
    order = get_order_or_404(orderId)
    if order["processing_status"] != "RECEIVED":
        fail(ERR_INVALID_STATE, 409,
             "Order must be RECEIVED to validate; current state is %s."
             % order["processing_status"])

    # Re-checked at validation: authority-type compatibility, state rule.
    authority = store.authorities.get(order["issuing_authority_id"])
    if authority is None:
        fail(ERR_NOT_FOUND, 404,
             "IssuingAuthority '%s' does not exist." % order["issuing_authority_id"])
    if authority["authority_type"] not in AUTHORITY_COMPATIBILITY[order["order_type"]]:
        fail(ERR_AUTHORITY_MISMATCH, 422,
             "authority_type %s is incompatible with order_type %s."
             % (authority["authority_type"], order["order_type"]))
    employee = store.employees[order["employee_id"]]
    if employee["work_state_code"] not in store.state_rules:
        fail(ERR_STATE_RULE_MISSING, 422,
             "No StateRule row for work_state_code '%s'." % employee["work_state_code"])
    _check_duplicate(employee["id"], order["order_type"], order["case_number"],
                     exclude_id=order["id"])
    if employee["termination_date"] is not None:
        fail(ERR_EMPLOYEE_TERMINATED_INELIGIBLE, 409,
             "Employee '%s' is terminated; order cannot be validated."
             % employee["id"])

    order["processing_status"] = "VALIDATED"
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.validate")
    return object_response(public(order))


@bp.post("/orders/<orderId>/reject")
def reject_order(orderId):
    authorize(ROLE_SPECIALIST)
    order = get_order_or_404(orderId)
    body = get_body()
    reason = req_str(body, "reason")
    if order["processing_status"] != "RECEIVED":
        fail(ERR_INVALID_STATE, 409,
             "Order must be RECEIVED to reject; current state is %s."
             % order["processing_status"])

    order["processing_status"] = "REJECTED"
    order["remit_posture"] = "CLOSED"
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.reject", details={"reason": reason})
    return object_response(public(order))


# --------------------------------------------------------------------------
# Notification & activation
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/notify")
def notify_order(orderId):
    authorize(ROLE_SPECIALIST)
    order = get_order_or_404(orderId)
    if order["processing_status"] != "VALIDATED":
        fail(ERR_INVALID_STATE, 409,
             "Order must be VALIDATED to notify; current state is %s."
             % order["processing_status"])

    sent_at = logical_now()
    order["notification_sent_at"] = render_instant(sent_at)
    # Late notification is legal but flagged in the computation trace.
    order["notification_late"] = render_instant(sent_at) > order["notification_due_at"]
    order["processing_status"] = "EMPLOYEE_NOTIFIED"
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.notify",
                       details={"notification_sent_at": order["notification_sent_at"],
                                "notification_late": order["notification_late"]})
    return object_response(public(order))


@bp.post("/orders/<orderId>/activate")
def activate_order(orderId):
    authorize(ROLE_SPECIALIST)
    order = get_order_or_404(orderId)
    if order["processing_status"] != "EMPLOYEE_NOTIFIED":
        fail(ERR_INVALID_STATE, 409,
             "Order must be EMPLOYEE_NOTIFIED to activate; current state is %s."
             % order["processing_status"])
    if order["notification_sent_at"] is None:
        fail(ERR_INVALID_STATE, 409, "Order has no recorded notification.")
    employee = store.employees[order["employee_id"]]
    if employee["termination_date"] is not None:
        fail(ERR_EMPLOYEE_TERMINATED_INELIGIBLE, 409,
             "Employee '%s' is terminated; order cannot be activated."
             % employee["id"])

    order["processing_status"] = "ACTIVE"
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.activate")
    return object_response(public(order))


# --------------------------------------------------------------------------
# Suspend / resume (cyclic, MAX_SUSPENSIONS times)
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/suspend")
def suspend_order(orderId):
    authorize(ROLE_MANAGER)
    order = get_order_or_404(orderId)
    body = get_body()
    hold_reason = req_enum(body, "hold_reason", HOLD_REASONS)
    # An ANSWER_FILED order is treated as ACTIVE for this check.
    if order["processing_status"] not in ("ACTIVE", "ANSWER_FILED"):
        fail(ERR_INVALID_STATE, 409,
             "Order must be ACTIVE to suspend; current state is %s."
             % order["processing_status"])
    if order["suspension_count"] >= MAX_SUSPENSIONS:
        fail(ERR_SUSPEND_LIMIT_EXCEEDED, 409,
             "Order has already been suspended %d times." % MAX_SUSPENSIONS)

    order["processing_status"] = "SUSPENDED"
    order["remit_posture"] = "HELD"
    order["hold_reason"] = hold_reason
    order["suspension_count"] += 1
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.suspend", details={"hold_reason": hold_reason})
    return object_response(public(order))


@bp.post("/orders/<orderId>/resume")
def resume_order(orderId):
    authorize(ROLE_MANAGER)
    order = get_order_or_404(orderId)
    if order["processing_status"] != "SUSPENDED":
        fail(ERR_INVALID_STATE, 409,
             "Order must be SUSPENDED to resume; current state is %s."
             % order["processing_status"])
    employee = store.employees[order["employee_id"]]
    if employee["termination_date"] is not None:
        fail(ERR_EMPLOYEE_TERMINATED_INELIGIBLE, 409,
             "Employee '%s' is terminated; order cannot be resumed."
             % employee["id"])

    # Suspension count is untouched: only /suspend increments it.
    order["processing_status"] = "ACTIVE"
    order["remit_posture"] = "REMITTING"
    order["hold_reason"] = None
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.resume")
    return object_response(public(order))


# --------------------------------------------------------------------------
# Answer to court
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/answer")
def answer_order(orderId):
    authorize(ROLE_MANAGER)
    order = get_order_or_404(orderId)
    body = get_body()
    answer_type = req_str(body, "answer_type")
    answer_date = req_date(body, "answer_date")
    if answer_type != "ACCEPTED":
        fail(ERR_INVALID_REQUEST, 400,
             "answer_type must be ACCEPTED; got '%s'." % answer_type)
    if order["processing_status"] != "ACTIVE":
        fail(ERR_INVALID_STATE, 409,
             "Order must be ACTIVE to answer; current state is %s."
             % order["processing_status"])

    # On or before answer_due_date is ON_TIME; later is LATE (legal, flagged).
    timeliness = "ON_TIME" if answer_date <= order["answer_due_date"] else "LATE"
    order["processing_status"] = "ANSWER_FILED"
    order["answer_type"] = answer_type
    order["answer_date"] = answer_date
    order["answer_timeliness"] = timeliness
    _touch(order)
    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.answer",
                       details={"answer_type": answer_type,
                                "answer_date": answer_date,
                                "answer_timeliness": timeliness})
    return object_response(public(order))


# --------------------------------------------------------------------------
# Termination
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/terminate")
def terminate_order(orderId):
    authorize(ROLE_MANAGER)
    order = get_order_or_404(orderId)
    body = get_body()
    reason = req_str(body, "termination_reason")
    if order["processing_status"] not in ("ACTIVE", "ANSWER_FILED", "SUSPENDED", "SATISFIED"):
        fail(ERR_INVALID_STATE, 409,
             "Order cannot be terminated from state %s." % order["processing_status"])
    # A later non-terminal order sharing (order_type, case_number) now carries
    # the obligation; terminating the older one is refused.
    _check_duplicate(order["employee_id"], order["order_type"], order["case_number"],
                     exclude_id=order["id"], later_than_seq=order["_seq"])

    order["processing_status"] = "TERMINATED"
    order["remit_posture"] = "CLOSED"
    order["hold_reason"] = None
    _touch(order)

    # §2.7: order termination mutates the employee record through a cascade.
    employee = store.employees[order["employee_id"]]
    employee["version"] += 1
    employee["updated_at"] = render_instant(logical_now())

    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.terminate", details={"termination_reason": reason})
    return object_response(public(order))


# --------------------------------------------------------------------------
# Corrections: refund over-withheld amounts (append-only REFUND event)
# --------------------------------------------------------------------------

@bp.post("/orders/<orderId>/refund")
def refund_order(orderId):
    authorize(ROLE_MANAGER)
    order = get_order_or_404(orderId)
    body = get_body()
    refund_amount_cents = req_int(body, "refund_amount_cents")
    reason = req_str(body, "reason")
    payroll_run_id = req_str(body, "payroll_run_id")

    run = store.runs.get(payroll_run_id)
    if run is None or run["employer_id"] != order["employer_id"]:
        fail(ERR_NOT_FOUND, 404,
             "PayrollRun '%s' does not exist within the employer scope."
             % payroll_run_id)

    net_withheld = order["withheld_cents"] - order["refunded_cents"]
    if refund_amount_cents <= 0 or order["withheld_cents"] <= 0 \
            or refund_amount_cents > net_withheld:
        fail(ERR_REFUND_EXCEEDS_WITHHELD, 422,
             "refund_amount_cents must be > 0 and <= the order's net withheld "
             "(%s)." % net_withheld)

    now = render_instant(logical_now())
    event = {
        "id": new_uuid(),
        "created_at": now,
        "garnishment_order_id": order["id"],
        "employer_id": order["employer_id"],
        "payroll_run_id": payroll_run_id,
        "pay_statement_id": None,
        "event_type": "REFUND",
        "amount_cents": -refund_amount_cents,
        "computation_proof": None,
        "created_logical_at": now,
        "_seq": next_seq(),
        "_remittance_id": None,
    }
    store.events[event["id"]] = event

    order["refunded_cents"] += refund_amount_cents
    order["remaining_balance_cents"] = (
        order["total_balance_cents"] - order["withheld_cents"] + order["refunded_cents"]
    )
    # A SATISFIED order does NOT reopen; the refund only restores the ledger.
    _touch(order)

    # Posture-driven remittance consequence: recompute any PENDING remittance
    # for this (authority, run) holding this order's events; auto-cancel at 0.
    for remittance in store.remittances.values():
        if remittance["status"] != "PENDING":
            continue
        if remittance["payroll_run_id"] != payroll_run_id:
            continue
        if remittance["authority_id"] != order["issuing_authority_id"]:
            continue
        member_orders = {
            store.events[eid]["garnishment_order_id"]
            for eid in remittance["member_event_ids"]
            if eid in store.events
        }
        if order["id"] not in member_orders:
            continue
        base = sum(
            store.events[eid]["amount_cents"]
            for eid in remittance["member_event_ids"]
            if eid in store.events
        )
        refunds = sum(
            -e["amount_cents"]
            for e in store.events.values()
            if e["event_type"] == "REFUND"
            and e["payroll_run_id"] == remittance["payroll_run_id"]
            and e["garnishment_order_id"] in member_orders
        )
        effective = max(0, base - refunds)
        remittance["amount_due_cents"] = effective
        remittance["version"] += 1
        remittance["updated_at"] = render_instant(logical_now())
        if effective == 0:
            remittance["status"] = "CANCELLED"
            audit.append_audit(remittance["employer_id"], "Remittance",
                               remittance["id"], "remittance.cancel",
                               details={"reason": "refund drained effective total to zero"},
                               actor_role="SYSTEM", actor_id="system")

    audit.append_audit(order["employer_id"], "GarnishmentOrder", order["id"],
                       "order.refund",
                       details={"refund_amount_cents": refund_amount_cents,
                                "reason": reason,
                                "payroll_run_id": payroll_run_id,
                                "withholding_event_id": event["id"]})
    return object_response(public(event))


@bp.get("/orders/<orderId>/events")
def list_order_events(orderId):
    authorize(*ALL_ROLES)
    get_order_or_404(orderId)
    limit, offset = pagination()
    items = sort_created(
        [e for e in store.events.values() if e["garnishment_order_id"] == orderId]
    )
    page = items[offset:offset + limit]
    return list_response([public(e) for e in page], len(items), limit, offset)
