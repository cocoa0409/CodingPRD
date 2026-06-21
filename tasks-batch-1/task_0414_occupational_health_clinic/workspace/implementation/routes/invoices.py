"""Invoice endpoints (PRD §3.13)."""

from datetime import timedelta

from flask import Blueprint, request

import errors
from db import LOCK, db
from errors import err
from middleware import authenticate, require_role
from response import object_response
from routes._helpers import get_json_body, paginated, sort_by_created
from services import lookup
from services.calculations import invoice_totals
from services.common import (
    base_entity, parse_date, date_of, touch,
    recompute_employer_balance, compute_outstanding_balance,
)
from services.serialize import public

bp = Blueprint("invoices", __name__)

READ_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}


def _select_line_items(employer_id, period_start, period_end):
    """Encounters for the employer: COMPLETED, not billed, billable>0, completion
    date within [period_start, period_end] inclusive. Ordered by created_at ASC."""
    selected = []
    for enc in db.encounters.values():
        if enc["employer_id"] != employer_id:
            continue
        if enc["status"] != "COMPLETED":
            continue
        if enc.get("is_billed"):
            continue
        if enc.get("billable_amount_cents", 0) <= 0:
            continue
        completed_on = date_of(enc.get("updated_at"))
        if completed_on is None:
            continue
        if completed_on < period_start or completed_on > period_end:
            continue
        selected.append(enc)
    selected = sort_by_created(selected)
    return selected


@bp.route("/clinic/invoices", methods=["POST"])
def create_invoice():
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()

    with LOCK:
        # Priority 4: body FK existence (missing OR not-found -> cross-employer).
        employer_id = body.get("employer_id")
        if employer_id is None or employer_id not in db.employers:
            raise err(errors.ERR_CROSS_EMPLOYER_REFERENCE,
                      "employer_id missing or not found")

        # Priority 5: body well-formedness.
        ps_raw = body.get("period_start")
        pe_raw = body.get("period_end")
        ps = parse_date(ps_raw) if ps_raw is not None else None
        pe = parse_date(pe_raw) if pe_raw is not None else None
        if ps is None:
            raise err(errors.ERR_INVALID_REQUEST, "period_start must be a valid date")
        if pe is None:
            raise err(errors.ERR_INVALID_REQUEST, "period_end must be a valid date")
        if pe < ps:
            raise err(errors.ERR_INVALID_REQUEST, "period_end must be on or after period_start")

        selected = _select_line_items(employer_id, ps, pe)
        line_ids = [e["id"] for e in selected]
        subtotal = sum(e["billable_amount_cents"] for e in selected)
        discount, total = invoice_totals(subtotal, len(selected))

        inv = base_entity()
        inv.update({
            "employer_id": employer_id,
            "period_start": ps_raw,
            "period_end": pe_raw,
            "issue_date": None,
            "due_date": None,
            "line_item_encounter_ids": line_ids,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "total_cents": total,
            "paid_cents": 0,
            "status": "DRAFT",
        })
        db.invoices[inv["id"]] = inv
        return object_response(public(inv), 201)


@bp.route("/clinic/invoices", methods=["GET"])
def list_invoices():
    caller = authenticate()
    require_role(caller, READ_ROLES)
    args = request.args
    items = list(db.invoices.values())
    for key in ("employer_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    return paginated(sort_by_created(items))


@bp.route("/clinic/invoices/<inv_id>", methods=["GET"])
def get_invoice(inv_id):
    caller = authenticate()
    require_role(caller, READ_ROLES)
    inv = lookup.get_invoice(inv_id)
    return object_response(public(inv), 200)


@bp.route("/clinic/invoices/<inv_id>/issue", methods=["POST"])
def issue(inv_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()
    with LOCK:
        inv = lookup.get_invoice(inv_id)
        employer = lookup.get_employer(inv["employer_id"])

        # Priority 5: body well-formedness for OCC field.
        if "expected_employer_version" not in body or body["expected_employer_version"] is None:
            raise err(errors.ERR_INVALID_REQUEST, "expected_employer_version is required")
        expected = body["expected_employer_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err(errors.ERR_INVALID_REQUEST, "expected_employer_version must be an integer")

        # Priority 6: OCC.
        if expected != employer["version"]:
            raise err(errors.ERR_STALE_EMPLOYER_VERSION,
                      "expected_employer_version does not match employer version")

        # Priority 7: state precondition.
        if inv["status"] != "DRAFT":
            raise err(errors.ERR_INVOICE_NOT_DRAFT, "Invoice must be DRAFT to issue")

        # Business rule: non-empty line items.
        if not inv.get("line_item_encounter_ids"):
            raise err(errors.ERR_INVOICE_NO_LINE_ITEMS, "Invoice has no line items")

        inv["status"] = "ISSUED"
        issue_date = employer["current_date"]
        inv["issue_date"] = issue_date
        issue_d = parse_date(issue_date)
        due_d = issue_d + timedelta(days=employer.get("net_terms_days", 30))
        inv["due_date"] = due_d.isoformat()
        touch(inv)

        # Cascade: mark line-item encounters billed.
        for enc_id in inv["line_item_encounter_ids"]:
            enc = db.encounters.get(enc_id)
            if enc is not None:
                enc["is_billed"] = True
                touch(enc)

        # Recompute outstanding balance and bump the employer version exactly once
        # (§2.8 mandates issuance advances Employer.version).
        employer["outstanding_balance_cents"] = compute_outstanding_balance(employer)
        touch(employer)

        return object_response(public(inv), 200)


@bp.route("/clinic/invoices/<inv_id>/payments", methods=["POST"])
def payments(inv_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    body = get_json_body()
    with LOCK:
        inv = lookup.get_invoice(inv_id)

        amount = body.get("amount_cents")
        if amount is None:
            raise err(errors.ERR_INVALID_REQUEST, "amount_cents is required")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise err(errors.ERR_INVALID_REQUEST, "amount_cents must be an integer")

        # Priority 7: payable state.
        if inv["status"] not in ("ISSUED", "OVERDUE", "PARTIALLY_PAID"):
            raise err(errors.ERR_INVOICE_NOT_PAYABLE, "Invoice is not in a payable state")

        # Priority 15: payment limit.
        if amount <= 0 or (inv["paid_cents"] + amount) > inv["total_cents"]:
            raise err(errors.ERR_PAYMENT_EXCEEDS_BALANCE,
                      "Payment is non-positive or exceeds the remaining balance")

        inv["paid_cents"] += amount
        if inv["paid_cents"] == inv["total_cents"]:
            inv["status"] = "PAID"
        else:
            inv["status"] = "PARTIALLY_PAID"
        touch(inv)

        employer = db.employers.get(inv["employer_id"])
        if employer is not None:
            recompute_employer_balance(employer)

        return object_response(public(inv), 200)


@bp.route("/clinic/invoices/<inv_id>/void", methods=["POST"])
def void(inv_id):
    caller = authenticate()
    require_role(caller, {"ClinicAdmin"})
    with LOCK:
        inv = lookup.get_invoice(inv_id)
        if inv["status"] != "DRAFT":
            raise err(errors.ERR_INVOICE_NOT_VOIDABLE, "Invoice must be DRAFT to void")
        inv["status"] = "VOIDED"
        touch(inv)
        # DRAFT contributed 0 to balance; recompute is harmless but the employer
        # version would bump. The spec says balance recomputes on void, so do it.
        employer = db.employers.get(inv["employer_id"])
        if employer is not None:
            recompute_employer_balance(employer)
        return object_response(public(inv), 200)
