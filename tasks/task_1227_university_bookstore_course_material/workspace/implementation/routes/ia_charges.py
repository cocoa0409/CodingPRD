"""Inclusive-access charges: opt-out / revoke / refund (PRD §3.8)."""

from flask import Blueprint, request

from db import store, now, touch, pub
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_NOT_OWNER, ERR_CHARGE_ALREADY_BILLED,
    ERR_OPT_OUT_WINDOW_CLOSED,
)
from middleware import require_roles, get_or_404
from response import success, list_response

bp = Blueprint("ia_charges", __name__)

READ_ROLES = ("BookstoreManager", "Student")


@bp.get("/bookstore/inclusive-access-charges")
def list_charges():
    require_roles(*READ_ROLES)
    student_id = request.args.get("student_id")
    section_id = request.args.get("section_id")
    enrollment_id = request.args.get("enrollment_id")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    items = [
        c for c in store.ia_charges.values()
        if (student_id is None or c["student_id"] == student_id)
        and (section_id is None or c["section_id"] == section_id)
        and (enrollment_id is None or c["enrollment_id"] == enrollment_id)
        and (term_id is None or c["term_id"] == term_id)
        and (status is None or c["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/inclusive-access-charges/<cid>")
def get_charge(cid):
    require_roles(*READ_ROLES)
    return success(pub(get_or_404(store.ia_charges, cid, "charge")))


def _opt_flow_common(cid):
    uid, _ = require_roles("Student")
    ch = get_or_404(store.ia_charges, cid, "charge")
    if ch["student_id"] != uid:
        raise ApiError(ERR_NOT_OWNER, 403, "not the charge owner")
    # specific state case first: billed -> ERR_CHARGE_ALREADY_BILLED
    if ch["status"] == "BILLED":
        raise ApiError(ERR_CHARGE_ALREADY_BILLED, 409,
                       "charge already billed")
    return ch


def _check_opt_out_deadline(ch):
    term = store.terms[ch["term_id"]]
    if now() > term["ia_opt_out_deadline_at"]:
        raise ApiError(ERR_OPT_OUT_WINDOW_CLOSED, 422,
                       "opt-out deadline has passed")


@bp.post("/bookstore/inclusive-access-charges/<cid>/opt-out")
def opt_out(cid):
    ch = _opt_flow_common(cid)
    if ch["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "charge not in PENDING")
    _check_opt_out_deadline(ch)
    ch["status"] = "OPTED_OUT"
    ch["opted_out_at"] = now()
    touch(ch)
    return success(pub(ch))


@bp.post("/bookstore/inclusive-access-charges/<cid>/revoke-opt-out")
def revoke_opt_out(cid):
    ch = _opt_flow_common(cid)
    if ch["status"] != "OPTED_OUT":
        raise ApiError(ERR_INVALID_STATE, 409, "charge not in OPTED_OUT")
    _check_opt_out_deadline(ch)
    ch["status"] = "PENDING"
    ch["opted_out_at"] = None
    touch(ch)
    return success(pub(ch))


@bp.post("/bookstore/inclusive-access-charges/<cid>/refund")
def refund_charge(cid):
    require_roles("BookstoreManager")
    ch = get_or_404(store.ia_charges, cid, "charge")
    if ch["status"] != "BILLED":
        raise ApiError(ERR_INVALID_STATE, 409, "charge not in BILLED")
    student = store.students[ch["student_id"]]
    student["aid_balance_cents"] += ch["aid_applied_cents"]
    touch(student)
    ch["aid_applied_cents"] = 0
    ch["balance_due_cents"] = 0
    ch["status"] = "REFUNDED"
    touch(ch)
    return success(pub(ch))
