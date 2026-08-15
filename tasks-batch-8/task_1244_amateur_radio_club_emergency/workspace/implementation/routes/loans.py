"""Equipment loan endpoints (PRD §3.8): checkout window, outstanding-loan
uniqueness, late-fee settlement, and the DAMAGED/LOST privilege cascade."""
from datetime import timedelta

from flask import Blueprint, request

import db
import services as svc
from errors import (
    ERR_EQUIPMENT_PRIVILEGE_SUSPENDED, ERR_FORBIDDEN, ERR_ITEM_ON_LOAN,
    ERR_LOAN_NOT_OUTSTANDING, ERR_LOAN_WINDOW_INVALID,
    ERR_MEMBERSHIP_NOT_ACTIVE, ApiError,
)
from middleware import auth_context, require_role
from response import paginate, success
from util import (
    RETURN_CONDITIONS, as_dt, as_enum, as_int, as_str, bad_request, body_json,
    need, opt, reject_unknown_fields,
)

bp = Blueprint("loans", __name__)

RW_ROLES = {"Member", "ClubAdmin"}


def _auth(allowed):
    user_id, role = auth_context()
    require_role(role, allowed)
    return user_id, role


@bp.post("/equipment-loans")
def create_loan():
    user_id, role = _auth(RW_ROLES)
    body = body_json(request)
    reject_unknown_fields(body, {"item_tag", "due_at", "estimated_value_cents",
                                 "member_id"})
    item_tag = as_str(need(body, "item_tag"), "item_tag")
    due_at = as_dt(need(body, "due_at"), "due_at")
    estimated_value_cents = as_int(need(body, "estimated_value_cents"),
                                   "estimated_value_cents")
    if estimated_value_cents <= 0:
        bad_request("estimated_value_cents must be > 0")
    if role == "Member":
        # Member borrowers always create their own loan.
        borrower_id = user_id
    else:
        borrower_id = opt(body, "member_id")
        if borrower_id is None:
            bad_request("member_id is required when ClubAdmin creates a loan")
        borrower_id = as_str(borrower_id, "member_id")
    borrower = svc.get_member(borrower_id)  # body FK existence
    now = db.now()
    # One outstanding (ACTIVE/OVERDUE) loan per item_tag.
    for l in db.STORE["equipment_loans"].values():
        if l["item_tag"] == item_tag and l["status"] in ("ACTIVE", "OVERDUE"):
            raise ApiError(ERR_ITEM_ON_LOAN, 409,
                           "an outstanding loan exists for item_tag %s" % item_tag)
    if not (due_at > now and due_at <= now + timedelta(days=svc.LOAN_MAX_DAYS)):
        raise ApiError(ERR_LOAN_WINDOW_INVALID, 422,
                       "due_at must be > now and <= now + 90 days")
    if borrower["membership_status"] != "ACTIVE":
        raise ApiError(ERR_MEMBERSHIP_NOT_ACTIVE, 409,
                       "borrower membership_status is not ACTIVE")
    if borrower["equipment_privilege"] != "GOOD_STANDING":
        raise ApiError(ERR_EQUIPMENT_PRIVILEGE_SUSPENDED, 409,
                       "borrower equipment_privilege is SUSPENDED")
    loan = {
        "item_tag": item_tag,
        "member_id": borrower["id"],
        "estimated_value_cents": estimated_value_cents,
        "checked_out_at": now,
        "due_at": due_at,
        "returned_at": None,
        "return_condition": None,
        "status": "ACTIVE",
        "late_fee_cents": 0,
    }
    svc.stamp_new(loan)
    db.STORE["equipment_loans"][loan["id"]] = loan
    return success(svc.ser_loan(loan), "object", 201)


@bp.get("/equipment-loans")
def list_loans():
    _auth(RW_ROLES)
    member_id = request.args.get("member_id")
    item_tag = request.args.get("item_tag")
    status = request.args.get("status")
    items = []
    for l in svc.sorted_records("equipment_loans"):
        if member_id is not None and l["member_id"] != member_id:
            continue
        if item_tag is not None and l["item_tag"] != item_tag:
            continue
        if status is not None and l["status"] != status:
            continue
        items.append(svc.ser_loan(l))
    page, meta = paginate(items, request.args)
    return success(page, "array", 200, meta)


@bp.get("/equipment-loans/<lid>")
def get_loan(lid):
    _auth(RW_ROLES)
    return success(svc.ser_loan(svc.get_loan(lid)), "object", 200)


@bp.post("/equipment-loans/<lid>/return")
def return_loan(lid):
    user_id, role = _auth(RW_ROLES)
    loan = svc.get_loan(lid)
    # Ownership: the borrower or a ClubAdmin.
    if role != "ClubAdmin" and loan["member_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "only the borrower or a ClubAdmin may return a loan")
    body = body_json(request)
    reject_unknown_fields(body, {"return_condition"})
    return_condition = as_enum(need(body, "return_condition"),
                               "return_condition", RETURN_CONDITIONS)
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError(ERR_LOAN_NOT_OUTSTANDING, 409,
                       "loan is not outstanding")
    loan["returned_at"] = db.now()
    loan["return_condition"] = return_condition
    loan["late_fee_cents"] = svc.compute_late_fee(
        loan, loan["returned_at"], return_condition)
    loan["status"] = "RETURNED"
    svc.touch(loan)
    if return_condition == "DAMAGED":
        member = svc.get_member(loan["member_id"])
        svc.privilege_suspension_cascade(member)
    return success(svc.ser_loan(loan), "object", 200)


@bp.post("/equipment-loans/<lid>/mark-lost")
def mark_lost(lid):
    _auth({"ClubAdmin"})
    loan = svc.get_loan(lid)
    body = body_json(request)
    reject_unknown_fields(body, set())
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise ApiError(ERR_LOAN_NOT_OUTSTANDING, 409,
                       "loan is not outstanding")
    # Mark-lost prices the loan at its full declared value.
    loan["late_fee_cents"] = loan["estimated_value_cents"]
    loan["status"] = "LOST"
    svc.touch(loan)
    member = svc.get_member(loan["member_id"])
    svc.privilege_suspension_cascade(member)
    return success(svc.ser_loan(loan), "object", 200)
