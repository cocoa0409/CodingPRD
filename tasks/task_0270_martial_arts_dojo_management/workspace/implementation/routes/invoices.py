"""Invoices: get, list, pay, waive, mark-overdue (PRD §3.8)."""
from flask import Blueprint, request

from db import db
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_UNAUTHORIZED
from middleware import (
    get_identity, require_roles, ROLE_FRONTDESK, ROLE_MEMBER,
)
from response import success
from common import parse_pagination, paginate, sort_by_created, parse_iso8601
from services.serialize import view, view_list
from services import domain

bp = Blueprint("invoices", __name__)


def _member_owns(role, user_id, inv):
    if role == ROLE_MEMBER and inv["member_id"] != user_id:
        raise err(ERR_UNAUTHORIZED, "Member may only act on their own invoices.")


@bp.get("/dojo/invoices/<iid>")
def get_invoice(iid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    inv = db.invoices.get(iid)
    if inv is None:
        raise err(ERR_NOT_FOUND, "Invoice not found.")
    _member_owns(role, user_id, inv)
    return success(view(inv), 200)


@bp.get("/dojo/invoices")
def list_invoices():
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    kind = request.args.get("kind")
    items = []
    for inv in db.invoices.values():
        if role == ROLE_MEMBER and inv["member_id"] != user_id:
            continue
        if member_id is not None and inv["member_id"] != member_id:
            continue
        if contract_id is not None and inv.get("contract_id") != contract_id:
            continue
        if status is not None and inv["status"] != status:
            continue
        if kind is not None and inv["kind"] != kind:
            continue
        items.append(inv)
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(view_list(page), 200, pagination=meta)


@bp.post("/dojo/invoices/<iid>/pay")
def pay_invoice(iid):
    user_id, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK, ROLE_MEMBER])
    inv = db.invoices.get(iid)
    if inv is None:
        raise err(ERR_NOT_FOUND, "Invoice not found.")
    _member_owns(role, user_id, inv)
    if inv["status"] not in ("DUE", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "Invoice not in a payable state.")
    inv["status"] = "PAID"
    domain.touch(inv)
    domain.recompute_member_balance(inv["member_id"])
    return success(view(inv), 200)


@bp.post("/dojo/invoices/<iid>/waive")
def waive_invoice(iid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    inv = db.invoices.get(iid)
    if inv is None:
        raise err(ERR_NOT_FOUND, "Invoice not found.")
    if inv["status"] not in ("DUE", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "Invoice not in a waivable state.")
    inv["status"] = "WAIVED"
    domain.touch(inv)
    domain.recompute_member_balance(inv["member_id"])
    return success(view(inv), 200)


@bp.post("/dojo/invoices/<iid>/mark-overdue")
def mark_overdue(iid):
    _, role = get_identity()
    require_roles(role, [ROLE_FRONTDESK])
    inv = db.invoices.get(iid)
    if inv is None:
        raise err(ERR_NOT_FOUND, "Invoice not found.")
    if inv["status"] != "DUE":
        raise err(ERR_INVALID_STATE, "Invoice not in DUE state.")
    # only move to OVERDUE if the clock has passed due_at
    now = db.now()
    if now > parse_iso8601(inv["due_at"]):
        inv["status"] = "OVERDUE"
        domain.touch(inv)
        # overdue does not change amount_due; balance already counts DUE|OVERDUE,
        # but recompute to run any suspension cascade that the sweep may trigger.
        domain.recompute_member_balance(inv["member_id"])
    return success(view(inv), 200)
