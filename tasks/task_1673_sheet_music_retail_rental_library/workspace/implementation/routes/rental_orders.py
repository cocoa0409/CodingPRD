"""Rental orders: the full journey from DRAFT to SETTLED (PRD 3.5, 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import calc
from db import db
from errors import (
    ApiError,
    ERR_ACCOUNT_NOT_FOUND,
    ERR_ACCOUNT_NOT_IN_GOOD_STANDING,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_FORBIDDEN_ACCOUNT,
    ERR_INSUFFICIENT_COPIES,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LICENSE_FORMAT_NOT_AVAILABLE,
    ERR_NOTHING_TO_DISPUTE,
    ERR_ORDER_NOT_CANCELLABLE,
    ERR_PO_AMOUNT_EXCEEDED,
    ERR_PO_NOT_FOUND,
    ERR_PO_NOT_USABLE,
    ERR_PREPAYMENT_REQUIRED,
    ERR_PREPAYMENT_SHORTFALL,
    ERR_RENEWAL_CAP_REACHED,
    ERR_RENEWAL_CONFLICT,
    ERR_RENTAL_ORDER_NOT_FOUND,
    ERR_RENTAL_SET_NOT_FOUND,
    ERR_RENTAL_SET_NOT_RENTABLE,
    ERR_RIGHTS_NOT_CLEARED,
    ERR_STALE_VERSION,
    ERR_UNRESOLVED_DISPUTES,
    ERR_UNSETTLED_DAMAGE_INVOICES,
    ERR_WORK_NOT_RENTABLE,
)
from middleware import require_auth
from response import success_object
from serializers import ser_order
from services import (
    compute_encumbered,
    compute_exposures,
    count_blocking_copies,
    get_or_404,
    invoices_of_order,
    lines_of_order,
    lines_of_set,
    maybe_restore_standing,
    order_of_line,
)
from util import is_int, is_str, new_record, now_date, parse_day, touch
from routes.helpers import body, coerce_version, paginate, require_fields

bp = Blueprint("rental_orders", __name__)

ALL_ROLES = ("LibraryAdmin", "LibraryClerk", "ReturnsClerk", "BillingManager", "RightsAdvisor", "Customer")
FULFILLMENT_FORMATS = ("PHYSICAL", "DIGITAL")
RENEWAL_CAP = 2
GRADES_WITH_LOST = ("A", "B", "C", "D", "LOST")


# ------------------------------------------------------------------ helpers

def _work_set_pub(order):
    rental_set = db["rental_sets"].get(order["rental_set_id"])
    work = db["works"].get(rental_set["work_id"]) if rental_set else None
    publisher = db["publishers"].get(work["publisher_id"]) if work else None
    return rental_set, work, publisher


def _po_usable(po):
    today = now_date()
    return po["status"] == "APPROVED" and po["valid_from"] <= today <= po["valid_until"]


def create_order_record(account, rental_set, data, fulfillment_format="PHYSICAL"):
    """Shared DRAFT-order construction (create endpoint + perusal conversion)."""
    copies = data.get("copies_requested")
    if not is_int(copies) or copies < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "copies_requested must be an integer >= 1")
    checkout = parse_day(data.get("checkout_date"))
    due = parse_day(data.get("due_date"))
    if checkout is None or due is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "checkout_date/due_date must be ISO dates")
    if due <= checkout:
        raise ApiError(ERR_INVALID_REQUEST, 400, "due_date must be later than checkout_date")
    rec = new_record()
    rec.update(
        {
            "account_id": account["id"],
            "rental_set_id": rental_set["id"],
            "purchase_order_id": data.get("purchase_order_id"),
            "fulfillment_format": fulfillment_format,
            "copies_requested": copies,
            "checkout_date": checkout,
            "due_date": due,
            "loan_periods": calc.loan_periods(checkout, due),
            "estimated_fee_cents": None,
            "final_fee_cents": None,
            "renewal_count": 0,
            "prepayment_cents": 0,
            "status": "DRAFT",
        }
    )
    db["rental_orders"][rec["id"]] = rec
    return rec


def do_reserve(order):
    """Full reserve chain (PRD 3.5, pipeline order of PRD 2.9). Also used by
    perusal conversion to RENTAL."""
    account = db["customer_accounts"].get(order["account_id"])
    rental_set, work, publisher = _work_set_pub(order)

    # (4) state
    if order["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DRAFT order may be reserved")
    # (7) license format
    if order["fulfillment_format"] == "DIGITAL":
        if work["license_format"] not in ("DIGITAL_ONLY", "PRINT_AND_DIGITAL") or publisher["print_only_rental"]:
            raise ApiError(ERR_LICENSE_FORMAT_NOT_AVAILABLE, 422, "Digital fulfillment not licensed")
    # (8) rentability: set, then work/publisher
    if rental_set["status"] != "IN_SERVICE" or rental_set["condition_grade"] == "D":
        raise ApiError(ERR_RENTAL_SET_NOT_RENTABLE, 409, "Rental set is not rentable")
    if work["status"] != "CATALOGED" or publisher["status"] != "ACTIVE":
        raise ApiError(ERR_WORK_NOT_RENTABLE, 409, "Work is withdrawn or publisher suspended")
    # (9) copy-window overlap (PHYSICAL orders only)
    if order["fulfillment_format"] == "PHYSICAL":
        blockers = count_blocking_copies(rental_set, order["checkout_date"], order["due_date"])
        if order["copies_requested"] > rental_set["copy_count"] - blockers:
            raise ApiError(ERR_INSUFFICIENT_COPIES, 409, "Fewer allocatable copies than requested")

    estimated = calc.estimate_fee(order, work, publisher)

    # (12) PO usability
    po = None
    if order.get("purchase_order_id"):
        po = db["purchase_orders"].get(order["purchase_order_id"])
        if po is None:
            raise ApiError(ERR_PO_NOT_FOUND, 404, "PurchaseOrder not found")
    if account["requires_purchase_order"] and po is None:
        raise ApiError(ERR_PO_NOT_USABLE, 409, "Account requires a purchase order")
    if po is not None and not _po_usable(po):
        raise ApiError(ERR_PO_NOT_USABLE, 409, "Purchase order is not usable")
    # (13) PO amount headroom
    if po is not None:
        if compute_encumbered(po) + estimated > po["authorized_amount_cents"]:
            raise ApiError(ERR_PO_AMOUNT_EXCEEDED, 402, "PO authorized amount would be exceeded")
    # (14) credit limit (PREPAY skips; limit 0 == uncapped)
    if account["credit_tier"] != "PREPAY" and account["credit_limit_cents"] > 0:
        _, settled = compute_exposures(account["id"])
        if settled + estimated > account["credit_limit_cents"]:
            raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402, "Credit limit would be exceeded")
    # (16) standing gate
    if account["standing"] != "GOOD":
        raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account is not in good standing")

    # ---- side effects: allocate lines, stamp fee, encumber PO, recompute ----
    for i in range(1, order["copies_requested"] + 1):
        ln = new_record()
        ln.update(
            {
                "rental_order_id": order["id"],
                "copy_seq": i,
                "checkout_condition": "A",
                "return_condition": None,
                "status": "RESERVED",
            }
        )
        db["rental_lines"][ln["id"]] = ln
    order["estimated_fee_cents"] = estimated
    order["status"] = "RESERVED"
    touch(order)
    touch(rental_set)  # availability recompute is a mutation (PRD 2.4)
    if po is not None:
        touch(po)  # encumbrance accrued
    touch(account)  # exposure recompute
    return order


# ------------------------------------------------------------------ CRUD + reads

@bp.post("/library/rental-orders")
def create_rental_order():
    require_auth("LibraryClerk", "Customer")
    data = body()
    require_fields(data, ["account_id", "rental_set_id", "copies_requested", "checkout_date", "due_date"])
    account = db["customer_accounts"].get(data["account_id"])
    if account is None:
        raise ApiError(ERR_ACCOUNT_NOT_FOUND, 404, "CustomerAccount not found")
    rental_set = db["rental_sets"].get(data["rental_set_id"])
    if rental_set is None:
        raise ApiError(ERR_RENTAL_SET_NOT_FOUND, 404, "RentalSet not found")
    po_id = data.get("purchase_order_id")
    if po_id is not None and po_id not in db["purchase_orders"]:
        raise ApiError(ERR_PO_NOT_FOUND, 404, "PurchaseOrder not found")
    fmt = data.get("fulfillment_format", "PHYSICAL")
    if fmt not in FULFILLMENT_FORMATS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid fulfillment_format")
    # Creation stores the request unchecked: license/overlap/standing/fiscal
    # rules are all deferred to reservation.
    rec = create_order_record(account, rental_set, data, fulfillment_format=fmt)
    return success_object(ser_order(rec), status=201)


@bp.get("/library/rental-orders")
def list_orders():
    require_auth(*ALL_ROLES)
    rows = list(db["rental_orders"].values())
    for param, field in (("account_id", "account_id"), ("rental_set_id", "rental_set_id"), ("purchase_order_id", "purchase_order_id")):
        v = request.args.get(param)
        if v is not None:
            rows = [o for o in rows if o.get(field) == v]
    return paginate(rows, ser_order)


@bp.get("/library/rental-orders/<oid>")
def get_order(oid):
    require_auth(*ALL_ROLES)
    rec = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    return success_object(ser_order(rec))


@bp.get("/library/rental-orders/<oid>/settlement-preview")
def settlement_preview(oid):
    require_auth("LibraryAdmin", "LibraryClerk", "BillingManager", "Customer")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] not in ("ON_LOAN", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409, "Settlement preview requires ON_LOAN or OVERDUE")
    _, work, publisher = _work_set_pub(order)
    today = now_date()
    effective_end = max(order["due_date"], today)
    periods = calc.loan_periods(order["checkout_date"], effective_end)
    projected = calc.estimate_fee(order, work, publisher, periods=periods)
    late_days = max(0, (today - order["due_date"]).days)
    return success_object({"projected_fee_cents": projected, "late_days": late_days})


# ------------------------------------------------------------------ transitions

@bp.post("/library/rental-orders/<oid>/reserve")
def reserve_order(oid):
    require_auth("LibraryClerk")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    do_reserve(order)
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/dispatch")
def dispatch_order(oid):
    require_auth("LibraryClerk")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    account = db["customer_accounts"].get(order["account_id"])
    _, work, _ = _work_set_pub(order)
    # (4) state
    if order["status"] != "RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RESERVED order may be dispatched")
    # (6) rights clearance
    if work["rights_class"] in ("GRAND_RIGHTS", "RESTRICTED"):
        cleared = any(
            c["account_id"] == order["account_id"]
            and c["work_id"] == work["id"]
            and c["status"] == "DECIDED"
            and c["determination"] == "CLEARED"
            for c in db["rights_cases"].values()
        )
        if not cleared:
            raise ApiError(ERR_RIGHTS_NOT_CLEARED, 409, "Rights advisory case not cleared")
    # (12) PO usability
    if order.get("purchase_order_id"):
        po = db["purchase_orders"].get(order["purchase_order_id"])
        if po is None or not _po_usable(po):
            raise ApiError(ERR_PO_NOT_USABLE, 409, "Purchase order is not usable")
    # (15) PREPAY prepayment sufficiency
    if account["credit_tier"] == "PREPAY":
        if order["prepayment_cents"] < (order["estimated_fee_cents"] or 0):
            raise ApiError(ERR_PREPAYMENT_REQUIRED, 402, "PREPAY account must prepay before dispatch")
    # (16) standing gate
    if account["standing"] != "GOOD":
        raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account is not in good standing")

    for ln in lines_of_order(order["id"]):
        if ln["status"] == "RESERVED":
            ln["status"] = "DISPATCHED"
            touch(ln)
    order["status"] = "DISPATCHED"
    touch(order)
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/confirm-receipt")
def confirm_receipt(oid):
    uid, _ = require_auth("Customer")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPATCHED order may be confirmed")
    if uid != order["account_id"]:
        raise ApiError(ERR_FORBIDDEN_ACCOUNT, 403, "Customer may act only on its own account's orders")
    for ln in lines_of_order(order["id"]):
        if ln["status"] == "DISPATCHED":
            ln["status"] = "ON_LOAN"
            touch(ln)
    order["status"] = "ON_LOAN"
    touch(order)
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/renew")
def renew_order(oid):
    require_auth("LibraryClerk")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    account = db["customer_accounts"].get(order["account_id"])
    rental_set, work, publisher = _work_set_pub(order)
    # (4) state
    if order["status"] != "ON_LOAN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an ON_LOAN order may be renewed")

    new_due = order["due_date"] + timedelta(days=calc.LOAN_PERIOD_DAYS)
    new_periods = calc.loan_periods(order["checkout_date"], new_due)
    new_est = calc.estimate_fee(order, work, publisher, periods=new_periods)

    # (10) renewal-window overlap (self-excluding)
    blockers = count_blocking_copies(rental_set, order["checkout_date"], new_due, exclude_order_id=order["id"])
    if order["copies_requested"] > rental_set["copy_count"] - blockers:
        raise ApiError(ERR_RENEWAL_CONFLICT, 409, "Renewal window collides with another order")
    # (13) PO amount headroom with the new total fee
    po = None
    if order.get("purchase_order_id"):
        po = db["purchase_orders"].get(order["purchase_order_id"])
        if po is not None:
            headroom = compute_encumbered(po) - (order["estimated_fee_cents"] or 0) + new_est
            if po["status"] != "APPROVED" or headroom > po["authorized_amount_cents"]:
                raise ApiError(ERR_PO_AMOUNT_EXCEEDED, 402, "PO authorized amount would be exceeded")
    # (16) standing gate
    if account["standing"] != "GOOD":
        raise ApiError(ERR_ACCOUNT_NOT_IN_GOOD_STANDING, 409, "Account is not in good standing")
    # (18) renewal cap
    if order["renewal_count"] >= RENEWAL_CAP:
        raise ApiError(ERR_RENEWAL_CAP_REACHED, 409, "Renewal cap reached")
    # (19) shape, then (20) OCC
    data = body()
    require_fields(data, ["expected_rental_order_version"])
    expected = coerce_version(data["expected_rental_order_version"], "expected_rental_order_version")
    if expected != order["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale rental order version")

    order["due_date"] = new_due
    order["loan_periods"] = new_periods
    order["estimated_fee_cents"] = new_est
    order["renewal_count"] += 1
    touch(order)
    if po is not None:
        touch(po)  # encumbrance delta applied
    touch(account)  # exposure recompute
    return success_object(ser_order(order))


# ------------------------------------------------------------------ check-in

def _parse_line_grades(raw, returnable_lines):
    """line_grades accepts a comma-separated grade string, a list of grade
    strings, a {line_id: grade} map, or a list of {line ref, grade} objects.
    Returns {line_id: grade}. Unmentioned lines default to their recorded
    checkout condition (no degradation)."""
    grades = {}
    if isinstance(raw, str):
        tokens = [t.strip() for t in raw.split(",") if t.strip()]
        for ln, g in zip(returnable_lines, tokens):
            grades[ln["id"]] = g
    elif isinstance(raw, list):
        if all(isinstance(x, str) for x in raw):
            for ln, g in zip(returnable_lines, raw):
                grades[ln["id"]] = g
        else:
            for item in raw:
                if not isinstance(item, dict):
                    raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed line_grades entry")
                ref = item.get("rental_line_id") or item.get("line_id")
                grade = item.get("observed_grade") or item.get("return_condition") or item.get("grade")
                if ref is None and item.get("copy_seq") is not None:
                    match = [ln for ln in returnable_lines if ln["copy_seq"] == item["copy_seq"]]
                    ref = match[0]["id"] if match else None
                if ref is None or grade is None:
                    raise ApiError(ERR_INVALID_REQUEST, 400, "Malformed line_grades entry")
                grades[ref] = grade
    elif isinstance(raw, dict):
        for k, v in raw.items():
            grades[k] = v
    else:
        raise ApiError(ERR_INVALID_REQUEST, 400, "line_grades must be a string, list, or map")
    valid = set(GRADES_WITH_LOST)
    known = {ln["id"] for ln in returnable_lines}
    for line_id, g in list(grades.items()):
        if line_id not in known:
            del grades[line_id]
            continue
        if g not in valid:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid condition grade: %s" % g)
    return grades


@bp.post("/library/rental-orders/<oid>/check-in")
def check_in_order(oid):
    uid, _ = require_auth("ReturnsClerk")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] not in ("ON_LOAN", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE, 409, "Check-in requires ON_LOAN or OVERDUE")
    data = body()
    if "line_grades" not in data:
        raise ApiError(ERR_INVALID_REQUEST, 400, "line_grades is required")
    account = db["customer_accounts"].get(order["account_id"])
    rental_set, work, publisher = _work_set_pub(order)
    all_lines = lines_of_order(order["id"])
    returnable = [ln for ln in all_lines if ln["status"] in ("ON_LOAN", "OVERDUE")]
    grades = _parse_line_grades(data["line_grades"], returnable)

    # Final fee (late days measured in whole days at the logical clock date).
    order["final_fee_cents"] = calc.final_fee(order, work, publisher, now_date())
    order["status"] = "RETURNED"
    touch(order)

    for ln in returnable:
        grade = grades.get(ln["id"], ln["checkout_condition"])
        ln["return_condition"] = grade
        if grade == "LOST":
            ln["status"] = "LOST"  # the copy never returns; pool not restored
        else:
            ln["status"] = "RETURNED"
        touch(ln)
        charge = calc.damage_charge(ln["checkout_condition"], grade, rental_set)
        if charge > 0:
            rep = new_record()
            rep.update(
                {
                    "rental_line_id": ln["id"],
                    "assessor_user_id": uid,
                    "observed_grade": grade,
                    "findings": None,
                    "assessed_charge_cents": charge,
                    "status": "FILED",
                }
            )
            db["condition_reports"][rep["id"]] = rep

    # Set condition cascade: worst grade across all RETURNED lines of the set;
    # a returned D drops an IN_SERVICE set to UNDER_REPAIR.
    returned_grades = [
        ln["return_condition"]
        for ln in lines_of_set(rental_set["id"])
        if ln["status"] == "RETURNED" and ln["return_condition"] in ("A", "B", "C", "D")
    ]
    if returned_grades:
        worst = max(returned_grades, key=lambda g: calc.GRADE_RANK[g])
        rental_set["condition_grade"] = worst
        if worst == "D" and rental_set["status"] == "IN_SERVICE":
            rental_set["status"] = "UNDER_REPAIR"
    touch(rental_set)  # availability restore + grade sync are mutations

    touch(account)  # exposure recompute
    return success_object(ser_order(order))


# ------------------------------------------------------------------ dispute loop + settle

@bp.post("/library/rental-orders/<oid>/dispute")
def dispute_order(oid):
    uid, _ = require_auth("Customer")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RETURNED order may be disputed")
    # (21) dispute integrity
    issued = [inv for inv in invoices_of_order(oid) if inv["status"] == "ISSUED"]
    if not issued:
        raise ApiError(ERR_NOTHING_TO_DISPUTE, 409, "No ISSUED damage invoice on this order")
    # (22) ownership
    if uid != order["account_id"]:
        raise ApiError(ERR_FORBIDDEN_ACCOUNT, 403, "Customer may act only on its own account's orders")
    for inv in issued:
        inv["status"] = "DISPUTED"
        touch(inv)
    order["status"] = "DISPUTED"
    touch(order)
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/resolve-dispute")
def resolve_dispute_order(oid):
    require_auth("BillingManager")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] != "DISPUTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a DISPUTED order may resolve its dispute")
    open_disputes = [inv for inv in invoices_of_order(oid) if inv["status"] == "DISPUTED"]
    if open_disputes:
        raise ApiError(ERR_UNRESOLVED_DISPUTES, 409, "Disputed invoices remain unresolved")
    order["status"] = "RETURNED"
    touch(order)
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/settle")
def settle_order(oid):
    require_auth("BillingManager")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] != "RETURNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a RETURNED order may be settled")
    account = db["customer_accounts"].get(order["account_id"])
    # (21) settle integrity: every damage invoice terminal
    non_terminal = [
        inv for inv in invoices_of_order(oid)
        if inv["status"] in ("DRAFT", "ISSUED", "DISPUTED")
    ]
    if non_terminal:
        raise ApiError(ERR_UNSETTLED_DAMAGE_INVOICES, 409, "Damage invoices are not all settled")
    # PREPAY shortfall: final fee covered by prepayment + collected damage + top-up
    data = body()
    topup = data.get("topup_cents", 0)
    if topup is None:
        topup = 0
    if not is_int(topup) or topup < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "topup_cents must be an integer >= 0")
    if account["credit_tier"] == "PREPAY":
        collected = sum(
            inv["amount_cents"]
            for inv in invoices_of_order(oid)
            if inv["status"] in ("PAID", "RESOLVED_ACCEPTED")
        )
        coverage = order["prepayment_cents"] + collected + topup
        if (order["final_fee_cents"] or 0) > coverage:
            raise ApiError(ERR_PREPAYMENT_SHORTFALL, 402, "Prepayment does not cover the final fee")
        if topup:
            order["prepayment_cents"] += topup

    po = db["purchase_orders"].get(order["purchase_order_id"]) if order.get("purchase_order_id") else None
    order["status"] = "SETTLED"
    touch(order)
    if po is not None:
        touch(po)  # encumbrance released
    touch(account)  # exposure recompute
    maybe_restore_standing(account)  # standing restoration evaluation
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/cancel")
def cancel_order(oid):
    require_auth("LibraryClerk")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    if order["status"] not in ("DRAFT", "RESERVED"):
        raise ApiError(ERR_ORDER_NOT_CANCELLABLE, 409, "Only DRAFT or RESERVED orders may be cancelled")
    account = db["customer_accounts"].get(order["account_id"])
    had_lines = False
    for ln in lines_of_order(order["id"]):
        if ln["status"] == "RESERVED":
            ln["status"] = "RELEASED"
            touch(ln)
            had_lines = True
    rental_set = db["rental_sets"].get(order["rental_set_id"])
    po = db["purchase_orders"].get(order["purchase_order_id"]) if order.get("purchase_order_id") else None
    order["status"] = "CANCELLED"
    touch(order)
    if had_lines and rental_set is not None:
        touch(rental_set)  # availability restored
    if po is not None and order["estimated_fee_cents"] is not None:
        touch(po)  # encumbrance released
    touch(account)  # exposure recompute
    return success_object(ser_order(order))


@bp.post("/library/rental-orders/<oid>/prepayments")
def record_prepayment(oid):
    require_auth("BillingManager")
    order = get_or_404("rental_orders", oid, ERR_RENTAL_ORDER_NOT_FOUND)
    data = body()
    amount = data.get("amount_cents")
    if not is_int(amount) or amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be an integer > 0")
    order["prepayment_cents"] += amount
    touch(order)
    return success_object(ser_order(order))
