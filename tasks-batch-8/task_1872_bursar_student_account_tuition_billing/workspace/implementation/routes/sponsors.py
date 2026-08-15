from datetime import timedelta
from flask import Blueprint, request

from db import store, base_fields, touch, clock_date
from dates import req_date, parse_date
from errors import (err, ERR_INVALID_REQUEST, ERR_STUDENT_NOT_FOUND,
                    ERR_TERM_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_SPONSOR_WINDOW_OVERLAP, ERR_AMOUNT_INVALID,
                    ERR_AGREEMENT_NOT_ACTIVE, ERR_NO_ACCOUNT_FOR_AGREEMENT,
                    ERR_BILLING_WINDOW_CLOSED, ERR_DRAFT_INVOICE_EXISTS,
                    ERR_INVOICE_STATE_INVALID, ERR_OVERPAYMENT)
from middleware import auth_context, require_roles
from response import success, json_body, req_str, req_int, req_bool, req_enum, list_response
from serialize import ser_agreement, ser_invoice
from services.core import post_entry, recompute_account
from services.domain import build_invoice_lines, agreement_account

bp = Blueprint("sponsors", __name__)


@bp.post("/bursar/sponsor-agreements")
def create_agreement():
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    body = json_body()
    sponsor_name = req_str(body, "sponsor_name")
    student_id = req_str(body, "student_id")
    term_id = req_str(body, "term_id")
    cap = req_int(body, "cap_cents")
    covers_tuition = req_bool(body, "covers_tuition")
    covers_fees = req_bool(body, "covers_fees")
    basis = req_enum(body, "billing_basis", ("NET_OF_WAIVER", "GROSS"))
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")

    if student_id not in store.students:
        raise err(ERR_STUDENT_NOT_FOUND, "Student not found")
    if term_id not in store.terms:
        raise err(ERR_TERM_NOT_FOUND, "Term not found")
    # HALF-OPEN window: start inclusive, end exclusive; end must follow start.
    if not (end > start):
        raise err(ERR_INVALID_REQUEST, "end_date must follow start_date")

    # Overlap policed per student only when covered kinds intersect;
    # half-open windows: strict adjacency (end == start) is NOT overlap.
    for o in store.agreements.values():
        if o["student_id"] != student_id:
            continue
        kinds_intersect = (covers_tuition and o["covers_tuition"]) or \
                          (covers_fees and o["covers_fees"])
        if not kinds_intersect:
            continue
        o_start = parse_date(o["start_date"])
        o_end = parse_date(o["end_date"])
        if start < o_end and o_start < end:
            raise err(ERR_SPONSOR_WINDOW_OVERLAP,
                      "Coverage window overlaps another agreement of this student")

    if cap <= 0:
        raise err(ERR_AMOUNT_INVALID, "cap_cents must be positive")

    a = base_fields()
    a.update({
        "sponsor_name": sponsor_name, "student_id": student_id,
        "term_id": term_id, "cap_cents": cap, "covers_tuition": covers_tuition,
        "covers_fees": covers_fees, "billing_basis": basis,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "billed_cents": 0, "status": "ACTIVE",
    })
    store.agreements[a["id"]] = a
    return success(ser_agreement(a), status=201)


@bp.get("/bursar/sponsor-agreements/<aid>")
def get_agreement(aid):
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.agreements.get(aid)
    if a is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor agreement not found")
    return success(ser_agreement(a))


@bp.get("/bursar/sponsor-agreements")
def list_agreements():
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    rows = list(store.agreements.values())
    for key in ("student_id", "term_id", "status"):
        v = request.args.get(key)
        if v is not None:
            rows = [a for a in rows if a[key] == v]
    rows.sort(key=lambda a: a["_seq"])
    return list_response(rows, ser_agreement)


@bp.post("/bursar/sponsor-agreements/<aid>/terminate")
def terminate_agreement(aid):
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    a = store.agreements.get(aid)
    if a is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor agreement not found")
    if a["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is already terminated")
    a["status"] = "TERMINATED"
    touch(a)
    # DRAFT invoices void (they never posted SPONSOR_CHARGE, so no reversal);
    # receivable invoices (ISSUED/PARTIALLY_PAID/DISPUTED) remain collectible.
    for inv in store.invoices.values():
        if inv["agreement_id"] == a["id"] and inv["status"] == "DRAFT":
            inv["status"] = "VOID"
            touch(inv)
    return success(ser_agreement(a))


@bp.post("/bursar/sponsor-invoices")
def create_invoice():
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    body = json_body()
    agreement_id = req_str(body, "agreement_id")
    agreement = store.agreements.get(agreement_id)
    if agreement is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor agreement not found")
    # State gate: the agreement must be ACTIVE.
    if agreement["status"] != "ACTIVE":
        raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
    # Referential: an account must exist for the agreement's (student, term).
    account = agreement_account(agreement)
    if account is None:
        raise err(ERR_NO_ACCOUNT_FOR_AGREEMENT,
                  "No student account exists for the agreement's student and term")
    # Temporal: billing cutoff closes 30 days after the term end date.
    term = store.terms[agreement["term_id"]]
    if clock_date() > parse_date(term["end_date"]) + timedelta(days=30):
        raise err(ERR_BILLING_WINDOW_CLOSED, "The sponsor billing window has closed")
    # At most one DRAFT invoice per agreement.
    for inv in store.invoices.values():
        if inv["agreement_id"] == agreement["id"] and inv["status"] == "DRAFT":
            raise err(ERR_DRAFT_INVOICE_EXISTS,
                      "A DRAFT invoice already exists for this agreement")
    lines, total = build_invoice_lines(agreement, account)
    inv = base_fields()
    inv.update({
        "agreement_id": agreement["id"],
        "invoice_date": clock_date().isoformat(),
        "lines": lines, "total_cents": total, "paid_cents": 0,
        "status": "DRAFT", "dispute_reason": None,
    })
    store.invoices[inv["id"]] = inv
    return success(ser_invoice(inv), status=201)


@bp.get("/bursar/sponsor-invoices/<iid>")
def get_invoice(iid):
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    inv = store.invoices.get(iid)
    if inv is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor invoice not found")
    return success(ser_invoice(inv))


@bp.get("/bursar/sponsor-agreements/<aid>/invoices")
def list_invoices(aid):
    _, role = auth_context()
    require_roles(role, "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.agreements.get(aid)
    if a is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor agreement not found")
    rows = [i for i in store.invoices.values() if i["agreement_id"] == aid]
    rows.sort(key=lambda i: i["_seq"])
    return list_response(rows, ser_invoice)


@bp.post("/bursar/sponsor-invoices/<iid>/transition")
def invoice_transition(iid):
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    inv = store.invoices.get(iid)
    if inv is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor invoice not found")
    body = json_body()
    action = req_enum(body, "action", ("ISSUE", "DISPUTE", "REINSTATE", "VOID"))
    agreement = store.agreements[inv["agreement_id"]]

    if action == "ISSUE":
        if inv["status"] != "DRAFT":
            raise err(ERR_INVOICE_STATE_INVALID, "ISSUE requires the invoice to be DRAFT")
        if agreement["status"] != "ACTIVE":
            raise err(ERR_AGREEMENT_NOT_ACTIVE, "Agreement is not ACTIVE")
        account = agreement_account(agreement)
        post_entry(account["id"], "SPONSOR_CHARGE", inv["total_cents"],
                   source_ref=inv["id"], memo="Sponsor billing")
        agreement["billed_cents"] += inv["total_cents"]
        if agreement["billed_cents"] == agreement["cap_cents"]:
            agreement["status"] = "EXHAUSTED"
        touch(agreement)
        inv["status"] = "ISSUED"
        touch(inv)
        recompute_account(account, force_bump=True)
        return success(ser_invoice(inv))

    if action == "DISPUTE":
        if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
            raise err(ERR_INVOICE_STATE_INVALID,
                      "DISPUTE requires the invoice to be ISSUED or PARTIALLY_PAID")
        inv["dispute_reason"] = body.get("dispute_reason")
        inv["status"] = "DISPUTED"
        touch(inv)
        return success(ser_invoice(inv))

    if action == "REINSTATE":
        if inv["status"] != "DISPUTED":
            raise err(ERR_INVOICE_STATE_INVALID, "REINSTATE requires the invoice to be DISPUTED")
        inv["dispute_reason"] = None
        inv["status"] = "PARTIALLY_PAID" if inv["paid_cents"] > 0 else "ISSUED"
        touch(inv)
        return success(ser_invoice(inv))

    # VOID
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise err(ERR_INVOICE_STATE_INVALID, "VOID requires the invoice to be DRAFT or ISSUED")
    if inv["status"] == "ISSUED":
        account = agreement_account(agreement)
        post_entry(account["id"], "SPONSOR_REVERSAL", inv["total_cents"],
                   source_ref=inv["id"], memo="Sponsor invoice voided")
        # Utilization decreases; an EXHAUSTED agreement stays EXHAUSTED.
        agreement["billed_cents"] -= inv["total_cents"]
        touch(agreement)
        recompute_account(account, force_bump=True)
    inv["status"] = "VOID"
    touch(inv)
    return success(ser_invoice(inv))


@bp.post("/bursar/sponsor-invoices/<iid>/payments")
def invoice_payment(iid):
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    inv = store.invoices.get(iid)
    if inv is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Sponsor invoice not found")
    body = json_body()
    amount = req_int(body, "amount_cents")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise err(ERR_INVOICE_STATE_INVALID,
                  "Remittances require the invoice to be ISSUED or PARTIALLY_PAID")
    if amount <= 0:
        raise err(ERR_AMOUNT_INVALID, "amount_cents must be positive")
    if inv["paid_cents"] + amount > inv["total_cents"]:
        raise err(ERR_OVERPAYMENT, "Remittance exceeds the unpaid remainder")
    inv["paid_cents"] += amount
    inv["status"] = "PAID" if inv["paid_cents"] == inv["total_cents"] else "PARTIALLY_PAID"
    touch(inv)
    return success(ser_invoice(inv))
