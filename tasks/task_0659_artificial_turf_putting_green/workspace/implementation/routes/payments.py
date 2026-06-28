"""Payments (PRD 3.7, 3.12). Recorded against a project in PENDING; settled or
failed through ops drivers. Only SETTLED rows count in the ledger."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_enum,
    require_fields,
    require_int_gt,
    require_string,
    stamp_new_minimal,
)
from db import db
from errors import err
from lookups import get_payment_or_404, get_project_or_404
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success
from services.payment_service import settle_payment

bp = Blueprint("payments", __name__)

PAYMENT_KINDS = {"DEPOSIT", "BALANCE", "REFUND"}


@bp.route("/projects/<project_id>/payments", methods=["POST"])
def create_payment(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    body = get_json_body()
    require_fields(body, ["kind", "amount_cents"])
    kind = require_enum(body, "kind", PAYMENT_KINDS)
    amount = require_int_gt(body, "amount_cents", 0)

    # A BALANCE payment cannot be recorded before finance_status == BALANCE_DUE
    # (priority 19).
    if kind == "BALANCE" and project["finance_status"] != "BALANCE_DUE":
        raise err("ERR_BALANCE_NOT_DUE", "Balance is not due yet.")

    rec = {
        "project_id": project_id,
        "kind": kind,
        "amount_cents": amount,
        "status": "PENDING",
    }
    stamp_new_minimal(rec)
    db.payments[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/payments", methods=["GET"])
def list_payments(project_id):
    uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    items = [p for p in db.payments.values() if p["project_id"] == project_id]
    for field in ("kind", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/payments/<payment_id>", methods=["GET"])
def get_payment(payment_id):
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin", "SalesRep", "Customer"})
    rec = get_payment_or_404(payment_id)
    return success(public(rec), status=200)


@bp.route("/_payments/settle", methods=["POST"])
def settle():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["payment_id"])
    payment_id = require_string(body, "payment_id")
    payment = db.payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")

    if payment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Payment is not in PENDING status.")

    project = db.projects.get(payment["project_id"])
    settle_payment(payment, project)
    return success(public(payment), status=200)


@bp.route("/_payments/fail", methods=["POST"])
def fail():
    _uid, role = get_auth()
    require_role(role, {"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["payment_id"])
    payment_id = require_string(body, "payment_id")
    payment = db.payments.get(payment_id)
    if payment is None:
        raise err("ERR_NOT_FOUND", "Payment not found.")

    if payment["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Payment is not in PENDING status.")

    payment["status"] = "FAILED"
    return success(public(payment), status=200)
