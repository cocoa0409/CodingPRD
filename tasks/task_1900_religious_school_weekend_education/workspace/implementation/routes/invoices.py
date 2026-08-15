"""TuitionInvoice and Payment endpoints."""

from flask import Blueprint, request
from decimal import Decimal

from db import store
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from errors import (
    ApiError, invalid_request, invalid_state, not_found, ownership_mismatch, stale_version,
    ERR_SCHOOL_YEAR_NOT_OPEN, ERR_NO_BILLABLE_ENROLLMENTS, ERR_INVOICE_HAS_PAYMENTS,
    ERR_CREDIT_ALREADY_APPLIED,
)
from services.core import (
    base_record, touch, public, get_family, get_invoice, get_payment,
    compute_net_tuition, family_year_enrollments, recompute_family_outstanding,
    round_half_up_cents,
)

bp = Blueprint("invoices", __name__)


@bp.route("/school/families/<family_id>/invoices", methods=["POST"])
def issue_invoice(family_id):
    require_roles(["SchoolAdmin"])
    family = get_family(family_id)
    body = request.get_json(silent=True) or {}
    school_year_id = body.get("school_year_id")
    if not isinstance(school_year_id, str):
        raise invalid_request("school_year_id is required")
    if "expected_family_version" not in body:
        raise invalid_request("expected_family_version is required")
    expected = body.get("expected_family_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise invalid_request("expected_family_version must be an integer")

    year = store.school_years.get(school_year_id)
    if year is None:
        raise not_found("SchoolYear not found")

    # OCC
    if expected != family["version"]:
        raise stale_version("Family version mismatch")

    if year["status"] != "OPEN":
        raise ApiError(ERR_SCHOOL_YEAR_NOT_OPEN, 409, "School year is not OPEN")

    # billable enrollments
    billable = family_year_enrollments(family["id"], school_year_id)
    if len(billable) == 0:
        raise ApiError(ERR_NO_BILLABLE_ENROLLMENTS, 409, "No billable enrollments")

    # supersede prior open TUITION invoice
    prior_open = None
    for inv in store.invoices.values():
        if (
            inv["family_id"] == family["id"]
            and inv["school_year_id"] == school_year_id
            and inv.get("kind") == "TUITION"
            and inv["status"] in ("ISSUED", "PARTIALLY_PAID")
        ):
            prior_open = inv
            break
    if prior_open is not None:
        if prior_open.get("paid_cents", 0) > 0:
            raise ApiError(ERR_INVOICE_HAS_PAYMENTS, 409, "Open invoice has payments")
        prior_open["status"] = "VOID"
        touch(prior_open)

    # line items
    line_items = []
    for e in billable:
        line, _rank = compute_net_tuition(year, family, e)
        line_items.append({
            "enrollment_id": e["id"],
            "student_id": e["student_id"],
            "line_cents": line,
        })
    gross = sum(li["line_cents"] for li in line_items)

    # award
    award = 0
    applied_app_id = None
    for app in store.applications.values():
        if (
            app["family_id"] == family["id"]
            and app["school_year_id"] == school_year_id
            and app["status"] == "APPROVED"
        ):
            if app["award_method"] == "PERCENT_OF_NET":
                award = round_half_up_cents(Decimal(str(app["award_percent"])) * Decimal(gross))
            elif app["award_method"] == "FLAT_CAP":
                award = min(app["award_amount_cents"], gross)
            applied_app_id = app["id"]
            break

    activity_fee = year["activity_fee_cents"]
    total_due = gross + activity_fee - award
    credit_applied = min(family["credit_balance_cents"], total_due)
    family["credit_balance_cents"] -= credit_applied

    now_str = store.now_str()
    rec = base_record()
    rec.update({
        "family_id": family["id"],
        "school_year_id": school_year_id,
        "status": "ISSUED",
        "kind": "TUITION",
        "line_items": line_items,
        "gross_cents": gross,
        "activity_fee_cents": activity_fee,
        "award_cents": award,
        "assistance_application_id": applied_app_id,
        "credit_applied_cents": credit_applied,
        "total_due_cents": total_due,
        "paid_cents": 0,
        "late_fees_cents": 0,
        "balance_cents": total_due - credit_applied,
        "issued_at": now_str,
        "due_date": year["tuition_due_date"],
    })
    store.invoices[rec["id"]] = rec

    recompute_family_outstanding(family)
    touch(family)

    return success_object(public(rec), status=201)


@bp.route("/school/invoices/<invoice_id>", methods=["GET"])
def get_invoice_endpoint(invoice_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    rec = get_invoice(invoice_id)
    if role == "Parent" and rec["family_id"] != user_id:
        raise ownership_mismatch()
    return success_object(public(rec))


@bp.route("/school/invoices", methods=["GET"])
def list_invoices():
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    limit, offset = parse_pagination(request.args)
    family_id = request.args.get("family_id")
    school_year_id = request.args.get("school_year_id")
    status = request.args.get("status")
    assistance_application_id = request.args.get("assistance_application_id")

    items = list(store.invoices.values())
    if role == "Parent":
        if family_id is not None and family_id != user_id:
            raise ownership_mismatch()
        items = [i for i in items if i["family_id"] == user_id]
    if family_id is not None:
        items = [i for i in items if i["family_id"] == family_id]
    if school_year_id is not None:
        items = [i for i in items if i["school_year_id"] == school_year_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if assistance_application_id is not None:
        items = [i for i in items if i.get("assistance_application_id") == assistance_application_id]
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

@bp.route("/school/families/<family_id>/payments", methods=["POST"])
def post_payment(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    method = body.get("method")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise invalid_request("amount_cents must be an integer > 0")
    if method not in ("CARD", "CHECK", "ACH"):
        raise invalid_request("method must be CARD, CHECK, or ACH")

    # waterfall: open invoices sorted by issued_at ASC, ties by created_at ASC
    open_invs = [
        i for i in store.invoices.values()
        if i["family_id"] == family["id"] and i["status"] in ("ISSUED", "PARTIALLY_PAID")
    ]
    open_invs.sort(key=lambda i: (i["issued_at"], i["created_at"], i["_seq"]))

    remaining = amount
    applications = []
    for inv in open_invs:
        if remaining <= 0:
            break
        applied = min(remaining, inv["balance_cents"])
        if applied <= 0:
            continue
        inv["paid_cents"] += applied
        inv["balance_cents"] -= applied
        remaining -= applied
        applications.append({"invoice_id": inv["id"], "applied_cents": applied})
        # status transitions
        if inv["balance_cents"] == 0:
            inv["status"] = "PAID"
        elif inv["paid_cents"] > 0:
            inv["status"] = "PARTIALLY_PAID"
        touch(inv)

    rec = base_record()
    rec.update({
        "family_id": family["id"],
        "amount_cents": amount,
        "method": method,
        "status": "POSTED",
        "applications": applications,
        "remainder_cents": remaining,
    })
    store.payments[rec["id"]] = rec

    if remaining > 0:
        family["credit_balance_cents"] += remaining
    recompute_family_outstanding(family)
    touch(family)

    return success_object(public(rec), status=201)


@bp.route("/school/families/<family_id>/payments", methods=["GET"])
def list_payments(family_id):
    role, user_id = require_roles(["SchoolAdmin", "Parent"])
    if role == "Parent" and user_id != family_id:
        raise ownership_mismatch()
    family = get_family(family_id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in store.payments.values() if p["family_id"] == family["id"]]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset: offset + limit]
    return success_list([public(p) for p in page], limit, offset, total)


@bp.route("/school/payments/<payment_id>/void", methods=["POST"])
def void_payment(payment_id):
    require_roles(["SchoolAdmin"])
    payment = get_payment(payment_id)
    if payment["status"] != "POSTED":
        raise invalid_state("Payment is not POSTED")
    family = store.families.get(payment["family_id"])
    if family is None:
        raise not_found("Family not found")
    if family["credit_balance_cents"] < payment["remainder_cents"]:
        raise ApiError(ERR_CREDIT_ALREADY_APPLIED, 409, "Payment remainder already consumed")

    # reverse applications
    for app_entry in payment["applications"]:
        inv = store.invoices.get(app_entry["invoice_id"])
        if inv is None:
            continue
        applied = app_entry["applied_cents"]
        inv["paid_cents"] -= applied
        inv["balance_cents"] += applied
        if inv["status"] == "PAID":
            inv["status"] = "PARTIALLY_PAID"
        if inv["status"] == "PARTIALLY_PAID" and inv["paid_cents"] == 0:
            inv["status"] = "ISSUED"
        touch(inv)

    family["credit_balance_cents"] -= payment["remainder_cents"]
    recompute_family_outstanding(family)
    touch(family)

    payment["status"] = "VOIDED"
    touch(payment)
    return success_object(public(payment))
