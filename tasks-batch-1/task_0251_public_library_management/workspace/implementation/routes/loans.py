"""Loan endpoints (PRD §3.3, §3.4, §3.5)."""

from flask import Blueprint, request

import clock
import db
import errors
import response
from constants import MAX_RENEWALS
from middleware import (
    authenticate, require_roles, require_owner_if_patron,
    ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER,
)
from services import serialize, derive, calc, loans as loan_svc, cascade
from routes import helpers
from timeutil import add_days, parse

bp = Blueprint("loans", __name__)

LOAN_STATUSES = {"ACTIVE", "OVERDUE", "RETURNED", "LOST"}


def _branch_for_patron(patron):
    return db.branches.get(patron["branch_id"])


def _title_has_open_hold(title_id):
    """True if any WAITING or READY hold exists on the title."""
    return any(
        h["title_id"] == title_id and h["status"] in ("WAITING", "READY")
        for h in db.holds.values()
    )


@bp.post("/library/loans")
def checkout():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["copy_id", "patron_id"])
    copy_id = helpers.require_string(body, "copy_id")
    patron_id = helpers.require_string(body, "patron_id")

    # existence (priority 3), left-to-right: copy then patron
    copy = helpers.find_or_404(db.copies, copy_id)
    patron = helpers.find_or_404(db.patrons, patron_id)
    branch = _branch_for_patron(patron)

    # priority 6: copy must be AVAILABLE
    if copy["status"] != "AVAILABLE":
        raise errors.ApiError(errors.ERR_RESOURCE_NOT_AVAILABLE, 409, "Copy is not AVAILABLE.")

    # priority 7: card must be ACTIVE
    if patron["card_status"] != "ACTIVE":
        raise errors.ApiError(errors.ERR_CARD_NOT_ACTIVE, 409, "Patron card is not ACTIVE.")

    # priority 8: patron must be CLEAR (recompute first)
    derive.reconcile_patron(patron)
    if patron["borrowing_status"] == "BLOCKED":
        raise errors.ApiError(errors.ERR_PATRON_BLOCKED, 409, "Patron is BLOCKED.")

    # priority 10: checkout_limit not exceeded by this new loan
    open_loans = sum(
        1 for ln in db.loans.values()
        if ln["patron_id"] == patron_id and ln["status"] in ("ACTIVE", "OVERDUE")
    )
    if open_loans >= patron["checkout_limit"]:
        raise errors.ApiError(errors.ERR_LIMIT_EXCEEDED, 409, "checkout_limit exceeded.")

    loan = loan_svc.create_loan(copy, patron, branch)
    return response.object_response(serialize.loan(loan), status=201)


@bp.get("/library/loans/<lid>")
def get_loan(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.loans, lid)
    return response.object_response(serialize.loan(record))


@bp.get("/library/loans")
def list_loans():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    copy_id = request.args.get("copy_id")
    patron_id = request.args.get("patron_id")
    status = helpers.enum_filter("status", LOAN_STATUSES)
    records = [
        ln for ln in db.loans.values()
        if (copy_id is None or ln["copy_id"] == copy_id)
        and (patron_id is None or ln["patron_id"] == patron_id)
        and (status is None or ln["status"] == status)
    ]
    return helpers.list_response(records, serialize.loan)


@bp.get("/library/loans/<lid>/fine-estimate")
def fine_estimate(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    loan = helpers.find_or_404(db.loans, lid)
    patron = db.patrons.get(loan["patron_id"])
    branch = _branch_for_patron(patron) if patron else None

    projected_raw = request.args.get("projected_return")
    if projected_raw is not None:
        try:
            projected = parse(projected_raw)
        except (ValueError, TypeError):
            raise errors.validation_param("projected_return must be an ISO 8601 datetime.")
    else:
        projected = clock.now()

    amount, overdue_days, chargeable_days = calc.overdue_fine(
        branch, loan["due_date"], projected
    )
    return response.object_response({
        "estimate_cents": amount,
        "overdue_days": overdue_days,
        "chargeable_days": chargeable_days,
    })


@bp.post("/library/loans/<lid>/renew")
def renew(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN})
    loan = helpers.find_or_404(db.loans, lid)

    # ownership (priority 2): patron may only renew own loan
    require_owner_if_patron(caller, loan["patron_id"])

    # state (priority 5): renewal defined only from ACTIVE
    if loan["status"] != "ACTIVE":
        raise errors.invalid_state("Loan is not ACTIVE.")

    # priority 10 specific codes
    if loan["renewal_count"] >= MAX_RENEWALS:
        raise errors.ApiError(errors.ERR_RENEWAL_LIMIT, 409, "Renewal limit reached.")

    copy = db.copies.get(loan["copy_id"])
    title_id = copy["title_id"] if copy else None
    if title_id is not None and _title_has_open_hold(title_id):
        raise errors.ApiError(
            errors.ERR_RENEWAL_BLOCKED_BY_HOLD, 409,
            "Renewal blocked by an outstanding hold on the title.",
        )

    patron = db.patrons.get(loan["patron_id"])
    branch = _branch_for_patron(patron) if patron else None

    loan["renewal_count"] += 1
    loan["due_date"] = add_days(loan["due_date"], branch["loan_period_days"])
    db.touch(loan)
    return response.object_response(serialize.loan(loan))


@bp.post("/library/loans/<lid>/refresh-overdue")
def refresh_overdue(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    loan = helpers.find_or_404(db.loans, lid)

    # state (priority 5): only ACTIVE loans can flip to OVERDUE
    if loan["status"] != "ACTIVE":
        raise errors.invalid_state("Loan is not ACTIVE.")

    now = clock.now()
    if not (now > loan["due_date"]):
        raise errors.ApiError(errors.ERR_NOT_YET_DUE, 409, "Loan is not yet past due.")

    loan["status"] = "OVERDUE"
    db.touch(loan)
    derive.reconcile_patron_by_id(loan["patron_id"])
    return response.object_response(serialize.loan(loan))


@bp.post("/library/loans/<lid>/checkin")
def checkin(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    loan = helpers.find_or_404(db.loans, lid)

    # state (priority 5)
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise errors.invalid_state("Loan is not ACTIVE or OVERDUE.")

    now = clock.now()
    patron = db.patrons.get(loan["patron_id"])
    branch = _branch_for_patron(patron) if patron else None
    copy = db.copies.get(loan["copy_id"])

    # Final overdue fine assessment
    amount, _, _ = calc.overdue_fine(branch, loan["due_date"], now)

    loan["status"] = "RETURNED"
    loan["returned_at"] = now
    loan["accrued_fine_cents"] = amount
    db.touch(loan)

    # Fine cascade: Loan -> Fine -> total_owed_cents -> borrowing_status
    if amount > 0:
        fine = {
            "patron_id": loan["patron_id"],
            "loan_id": loan["id"],
            "fine_type": "OVERDUE",
            "amount_cents": amount,
            "settlement_status": "UNPAID",
            "settled_at": None,
        }
        db.stamp_create(fine)
        db.fines[fine["id"]] = fine

    # Copy ON_LOAN -> AVAILABLE
    if copy is not None and copy["status"] == "ON_LOAN":
        copy["status"] = "AVAILABLE"
        db.touch(copy)

    # Hold promotion: head WAITING hold on the title (if any) consumes this copy
    if copy is not None:
        cascade.promote_head_hold_for_title(copy["title_id"], copy)
        derive.reconcile_title_by_id(copy["title_id"])

    derive.reconcile_patron_by_id(loan["patron_id"])
    return response.object_response(serialize.loan(loan))


@bp.post("/library/loans/<lid>/declare-lost")
def declare_lost(lid):
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN})
    loan = helpers.find_or_404(db.loans, lid)

    # state (priority 5)
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise errors.invalid_state("Loan is not ACTIVE or OVERDUE.")

    body = helpers.get_json_body()
    flat_replacement = helpers.optional_bool(body, "flat_replacement", False)

    now = clock.now()
    copy = db.copies.get(loan["copy_id"])
    title = db.titles.get(copy["title_id"]) if copy else None
    patron = db.patrons.get(loan["patron_id"])

    amount = calc.replacement_charge(
        _branch_for_patron(patron) if patron else None,
        title, copy, now, flat_replacement=flat_replacement,
    )

    loan["status"] = "LOST"
    db.touch(loan)

    if copy is not None:
        copy["status"] = "LOST"
        db.touch(copy)

    fine = {
        "patron_id": loan["patron_id"],
        "loan_id": loan["id"],
        "fine_type": "LOST",
        "amount_cents": amount,
        "settlement_status": "UNPAID",
        "settled_at": None,
    }
    db.stamp_create(fine)
    db.fines[fine["id"]] = fine

    if title is not None:
        derive.reconcile_title(title)
    derive.reconcile_patron_by_id(loan["patron_id"])
    return response.object_response(serialize.loan(loan))
