"""Invoice endpoints: submission, verification, approval."""

from datetime import timedelta

from flask import request

from . import calc
from .auth import require, require_owner
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_invoice
from .store import STORE, new_entity, now, touch
from .util import body, is_int, paged, pagination_params, req_enum, sort_created


def _get_invoice_or_404(iid):
    inv = STORE.invoices.get(iid)
    if inv is None:
        not_found("Invoice")
    return inv


def _invoice_owner_id(inv):
    a = STORE.assignments.get(inv["assignment_id"])
    return a["contributor_id"] if a else None


@bp.post("/freelance-desk/assignments/<aid>/invoices")
def create_invoice(aid):
    uid, role = require(["Contributor"])
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    # Priority 4: state preconditions
    if a["editorial_status"] not in ("ACCEPTED_FOR_PUBLICATION", "KILLED"):
        invalid_state(
            "Invoices require the assignment to be ACCEPTED_FOR_PUBLICATION or KILLED"
        )
    if a["payment_status"] != "UNINVOICED":
        invalid_state("Assignment already has an in-flight or settled invoice")
    # Priority 5: ownership
    require_owner(uid, a["contributor_id"])
    # Priority 6: verification gate
    if not calc.verification_gate_open(a):
        raise ApiError(
            "ERR_VERIFICATION_NOT_CLEARED",
            409,
            "A PENDING or FLAGGED verification report blocks invoice submission",
        )
    b = body()
    for name in ("fee_claim_cents", "expense_claim_cents"):
        if name not in b or b[name] is None:
            bad_request(f"{name} is required")
        if not is_int(b[name]) or b[name] < 0:
            bad_request(f"{name} must be a non-negative integer")

    e = new_entity()
    e.update({
        "assignment_id": aid,
        "submitted_by_contributor_id": uid,
        "fee_claim_cents": b["fee_claim_cents"],
        "expense_claim_cents": b["expense_claim_cents"],
        "gross_cents": 0,
        "withholding_cents": 0,
        "net_payable_cents": 0,
        "payment_terms_days": calc.cfg("net_terms_days"),
        "due_date_utc": None,
        "status": "SUBMITTED",
        "late_fee_cents": 0,
        "payment_batch_id": None,
        "_verified_by": None,
    })
    STORE.invoices[e["id"]] = e
    a["payment_status"] = "INVOICED"
    touch(a)
    return ok_obj(ser_invoice(e), 201)


@bp.get("/freelance-desk/assignments/<aid>/invoices")
def list_assignment_invoices(aid):
    uid, role = require(["DeskAdmin", "Editor", "FinanceUser", "Contributor"])
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    if role == "Contributor":
        require_owner(uid, a["contributor_id"])
    items = [i for i in STORE.invoices.values() if i["assignment_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.get("/freelance-desk/invoices")
def list_invoices():
    require(["DeskAdmin", "FinanceUser"])
    items = list(STORE.invoices.values())
    status = request.args.get("status")
    if status:
        items = [i for i in items if i["status"] == status]
    pbid = request.args.get("payment_batch_id")
    if pbid:
        items = [i for i in items if i["payment_batch_id"] == pbid]
    submitter = request.args.get("submitted_by_contributor_id")
    if submitter:
        items = [i for i in items if i["submitted_by_contributor_id"] == submitter]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_invoice(i) for i in page], limit, offset, total)


@bp.get("/freelance-desk/invoices/<iid>")
def get_invoice(iid):
    uid, role = require(["DeskAdmin", "FinanceUser", "Contributor"])
    inv = _get_invoice_or_404(iid)
    if role == "Contributor":
        require_owner(uid, _invoice_owner_id(inv))
    return ok_obj(ser_invoice(inv))


@bp.post("/freelance-desk/invoices/<iid>/verify")
def verify_invoice(iid):
    uid, role = require(["FinanceUser"])
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED invoice can be verified or rejected")
    a = STORE.assignments.get(inv["assignment_id"])
    if a is None or a["editorial_status"] not in ("ACCEPTED_FOR_PUBLICATION", "KILLED"):
        invalid_state("Covering assignment is not in a billable editorial state")
    # Priority 6: verification gate
    if not calc.verification_gate_open(a):
        raise ApiError(
            "ERR_VERIFICATION_NOT_CLEARED",
            409,
            "A PENDING or FLAGGED verification report blocks invoice verification",
        )
    b = body()
    decision = req_enum(b, "decision", ("VERIFY", "REJECT"))
    if decision == "REJECT":
        inv["status"] = "REJECTED"
        touch(inv)
        if a["payment_status"] == "INVOICED":
            a["payment_status"] = "UNINVOICED"
            touch(a)
        return ok_obj(ser_invoice(inv))

    # Priority 11: claim reconciliation
    expected_fee = a["final_fee_cents"] or 0
    for rp in STORE.rights_purchases.values():
        if rp["assignment_id"] == a["id"] and rp["rights_kind"] == "ALL":
            expected_fee += rp["buyout_uplift_cents"]
            break
    expected_expense = sum(
        c["reimbursable_cents"]
        for c in STORE.expense_claims.values()
        if c["assignment_id"] == a["id"] and c["status"] == "REIMBURSABLE"
    )
    if inv["fee_claim_cents"] != expected_fee or inv["expense_claim_cents"] != expected_expense:
        raise ApiError(
            "ERR_CLAIM_MISMATCH",
            422,
            "Claimed amounts do not reconcile with the assignment final fee and reimbursable expenses",
        )

    # Pinned order: gross first, withholding from fee alone second, net third.
    contributor = STORE.contributors.get(a["contributor_id"])
    inv["gross_cents"] = inv["fee_claim_cents"] + inv["expense_claim_cents"]
    inv["withholding_cents"] = calc.withholding_cents(inv["fee_claim_cents"], contributor)
    inv["net_payable_cents"] = inv["gross_cents"] - inv["withholding_cents"]
    inv["due_date_utc"] = now() + timedelta(days=inv["payment_terms_days"])
    inv["_verified_by"] = uid
    inv["status"] = "VERIFIED"
    touch(inv)
    return ok_obj(ser_invoice(inv))


@bp.post("/freelance-desk/invoices/<iid>/approve")
def approve_invoice(iid):
    uid, role = require(["FinanceUser"])
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "VERIFIED":
        invalid_state("Only a VERIFIED invoice can be approved")
    # Priority 7: segregation of duties
    if inv.get("_verified_by") is not None and uid == inv["_verified_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "The FinanceUser who verified the invoice may not approve it",
        )
    # Priority 10: contributor must hold a VERIFIED, unexpired tax document
    a = STORE.assignments.get(inv["assignment_id"])
    contributor_id = a["contributor_id"] if a else None
    if contributor_id is None or not calc.has_valid_tax_doc(contributor_id):
        raise ApiError(
            "ERR_TAX_DOC_MISSING",
            422,
            "Contributor holds no VERIFIED, unexpired tax document",
        )
    inv["status"] = "APPROVED"
    touch(inv)
    if a is not None and a["payment_status"] == "INVOICED":
        a["payment_status"] = "PAYABLE"
        touch(a)
    return ok_obj(ser_invoice(inv))
