"""Expense claim endpoints (pre-approval then settlement)."""

from flask import request

from . import calc
from .auth import require, require_owner
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_expense_claim
from .store import STORE, new_entity, touch
from .util import body, is_int, opt_bool, paged, pagination_params, req_enum, sort_created

CATEGORIES = ("TRAVEL", "MEALS", "EQUIPMENT", "OTHER")
READ_ROLES = ["DeskAdmin", "Editor", "FinanceUser", "Contributor"]


def _get_claim_or_404(eid):
    c = STORE.expense_claims.get(eid)
    if c is None:
        not_found("ExpenseClaim")
    return c


@bp.post("/freelance-desk/assignments/<aid>/expense-claims")
def create_expense_claim(aid):
    uid, role = require(["Contributor"])
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    require_owner(uid, a["contributor_id"])
    b = body()
    # Priority 13 (amount sanity) precedes priority 15 (generic field shape)
    requested = b.get("requested_cents")
    if requested is not None:
        if not is_int(requested):
            bad_request("requested_cents must be an integer")
        if requested < 1:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "requested_cents must be >= 1")
    category = req_enum(b, "category", CATEGORIES)
    if requested is None:
        bad_request("requested_cents is required")

    e = new_entity()
    e.update({
        "assignment_id": aid,
        "category": category,
        "requested_cents": requested,
        "approved_cents": None,
        "claimed_cents": None,
        "receipt_attached": False,
        "status": "PRE_APPROVAL_REQUESTED",
        "reimbursable_cents": None,
    })
    STORE.expense_claims[e["id"]] = e
    return ok_obj(ser_expense_claim(e), 201)


@bp.get("/freelance-desk/assignments/<aid>/expense-claims")
def list_expense_claims(aid):
    uid, role = require(READ_ROLES)
    a = STORE.assignments.get(aid)
    if a is None:
        not_found("Assignment")
    if role == "Contributor":
        require_owner(uid, a["contributor_id"])
    items = [c for c in STORE.expense_claims.values() if c["assignment_id"] == aid]
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_expense_claim(c) for c in page], limit, offset, total)


@bp.get("/freelance-desk/expense-claims/<eid>")
def get_expense_claim(eid):
    uid, role = require(READ_ROLES)
    c = _get_claim_or_404(eid)
    if role == "Contributor":
        a = STORE.assignments.get(c["assignment_id"])
        require_owner(uid, a["contributor_id"] if a else None)
    return ok_obj(ser_expense_claim(c))


@bp.post("/freelance-desk/expense-claims/<eid>/decide")
def decide_expense_claim(eid):
    require(["Editor"])
    c = _get_claim_or_404(eid)
    if c["status"] != "PRE_APPROVAL_REQUESTED":
        invalid_state("Only a PRE_APPROVAL_REQUESTED claim can be decided")
    b = body()
    decision = req_enum(b, "decision", ("APPROVE", "REJECT"))
    if decision == "APPROVE":
        a = STORE.assignments.get(c["assignment_id"])
        if a is None or a["editorial_status"] not in ("OFFERED", "ACCEPTED", "IN_PROGRESS"):
            invalid_state(
                "Pre-approval requires the assignment to be OFFERED, ACCEPTED, or IN_PROGRESS"
            )
        c["approved_cents"] = min(c["requested_cents"], calc.category_cap(c["category"]))
        c["status"] = "APPROVED"
    else:
        c["status"] = "REJECTED"
    touch(c)
    return ok_obj(ser_expense_claim(c))


@bp.post("/freelance-desk/expense-claims/<eid>/submit")
def submit_expense_claim(eid):
    uid, role = require(["Contributor"])
    c = _get_claim_or_404(eid)
    if c["status"] != "APPROVED":
        invalid_state("Only an APPROVED claim can be submitted")
    a = STORE.assignments.get(c["assignment_id"])
    require_owner(uid, a["contributor_id"] if a else None)
    b = body()
    claimed = b.get("claimed_cents")
    if claimed is not None and not is_int(claimed):
        bad_request("claimed_cents must be an integer")
    receipt = opt_bool(b, "receipt_attached", False)
    # Priority 12: receipt gate; priority 13: amount sanity
    if claimed is not None:
        if claimed >= calc.cfg("receipt_required_cents") and not receipt:
            raise ApiError(
                "ERR_RECEIPT_REQUIRED",
                422,
                "Claims at or above receipt_required_cents require receipt_attached",
            )
        if claimed < 1:
            raise ApiError("ERR_INVALID_AMOUNT", 422, "claimed_cents must be >= 1")
    if claimed is None:
        bad_request("claimed_cents is required")

    c["claimed_cents"] = claimed
    c["receipt_attached"] = receipt
    c["status"] = "SUBMITTED"
    touch(c)
    return ok_obj(ser_expense_claim(c))


@bp.post("/freelance-desk/expense-claims/<eid>/settle-decision")
def settle_expense_claim(eid):
    require(["Editor"])
    c = _get_claim_or_404(eid)
    if c["status"] != "SUBMITTED":
        invalid_state("Only a SUBMITTED claim can be settled")
    b = body()
    decision = req_enum(b, "decision", ("REIMBURSE", "DENY"))
    if decision == "REIMBURSE":
        a = STORE.assignments.get(c["assignment_id"])
        if a is None or a["editorial_status"] not in (
            "UNDER_VERIFICATION",
            "ACCEPTED_FOR_PUBLICATION",
            "KILLED",
        ):
            invalid_state(
                "Reimbursement requires the assignment to be UNDER_VERIFICATION, "
                "ACCEPTED_FOR_PUBLICATION, or KILLED"
            )
        # expense_reimbursement: min(claimed, approved); excess silently forfeited
        c["reimbursable_cents"] = min(c["claimed_cents"], c["approved_cents"])
        c["status"] = "REIMBURSABLE"
    else:
        c["reimbursable_cents"] = 0
        c["status"] = "DENIED"
    touch(c)
    return ok_obj(ser_expense_claim(c))
