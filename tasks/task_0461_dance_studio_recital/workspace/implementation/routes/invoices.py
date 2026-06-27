"""Invoice routes (PRD 3.9)."""
import re

from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import lookup, paginate, require_fields, require_str, sort_by_created
from middleware import authenticate, get_json, require_owner
from response import success
from services.billing import has_other_past_due, set_family_status
from views import public, public_list

bp = Blueprint("invoices", __name__)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@bp.route("/invoices/generate", methods=["POST"])
def generate_invoice():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["family_id", "term_id", "billing_month"])
    family = lookup(db.families, body["family_id"])
    term = lookup(db.terms, body["term_id"])
    billing_month = require_str(body, "billing_month")
    if not _MONTH_RE.match(billing_month):
        raise err("ERR_INVALID_REQUEST", "billing_month must be 'YYYY-MM'.")

    # Uniqueness: at most one non-VOID invoice per (family, term, billing_month).
    for inv in db.invoices.values():
        if (inv["family_id"] == family["id"] and inv["term_id"] == term["id"]
                and inv["billing_month"] == billing_month and inv["status"] != "VOID"):
            raise err("ERR_DUPLICATE_INVOICE", "A non-void invoice already exists.")

    # tuition snapshot: sum monthly_charge_cents of BILLING_ACTIVE enrollments.
    section_ids = {s["id"] for s in db.sections.values() if s["term_id"] == term["id"]}
    tuition = sum(
        e["monthly_charge_cents"] for e in db.enrollments.values()
        if e["family_id"] == family["id"]
        and e["billing_status"] == "BILLING_ACTIVE"
        and e["section_id"] in section_ids
    )

    fees = 0
    gross = tuition + fees
    credit_applied = min(family["account_credit_cents"], gross)
    amount_due = max(0, gross - credit_applied)

    inv = {
        "id": new_id(),
        "family_id": family["id"],
        "term_id": term["id"],
        "billing_month": billing_month,
        "tuition_cents": tuition,
        "fees_cents": fees,
        "credit_applied_cents": credit_applied,
        "amount_due_cents": amount_due,
        "status": "OPEN",
        **common_fields(),
    }
    # Decrement the wallet by the applied credit at generation.
    if credit_applied > 0:
        family["account_credit_cents"] -= credit_applied
        touch(family)
    db.invoices[inv["id"]] = inv
    return success(public(inv), status=201)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    inv = lookup(db.invoices, iid)
    require_owner(role, user_id, inv["family_id"])
    return success(public(inv), status=200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    items = list(db.invoices.values())
    for key in ("family_id", "term_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    # A Parent may only list their own family's invoices.
    if role == "Parent":
        items = [i for i in items if str(i["family_id"]) == str(user_id)]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    inv = lookup(db.invoices, iid)
    require_owner(role, user_id, inv["family_id"])
    if inv["status"] not in {"OPEN", "PAST_DUE"}:
        raise err("ERR_INVALID_STATE", "Invoice cannot be paid.")
    family = db.families.get(inv["family_id"])
    if family is None or not family["payment_method_on_file"]:
        raise err("ERR_NO_PAYMENT_METHOD", "No payment method on file.")
    was_past_due = inv["status"] == "PAST_DUE"
    inv["status"] = "PAID"
    touch(inv)
    # Clear delinquency if no other PAST_DUE invoice remains.
    if family["status"] == "DELINQUENT" and not has_other_past_due(family["id"], inv["id"]):
        set_family_status(family["id"], "ACTIVE")
    return success(public(inv), status=200)


@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    authenticate({"StudioAdmin"})
    inv = lookup(db.invoices, iid)
    if inv["status"] not in {"OPEN", "PAST_DUE"}:
        raise err("ERR_INVALID_STATE", "Invoice cannot be voided.")
    was_past_due = inv["status"] == "PAST_DUE"
    inv["status"] = "VOID"
    touch(inv)
    # Return any applied credit to the family wallet.
    family = db.families.get(inv["family_id"])
    if inv["credit_applied_cents"] > 0 and family is not None:
        family["account_credit_cents"] += inv["credit_applied_cents"]
        touch(family)
    # If voiding a past-due invoice clears the last delinquency, return to ACTIVE.
    if was_past_due and family is not None and family["status"] == "DELINQUENT" \
            and not has_other_past_due(family["id"], inv["id"]):
        set_family_status(family["id"], "ACTIVE")
    return success(public(inv), status=200)
