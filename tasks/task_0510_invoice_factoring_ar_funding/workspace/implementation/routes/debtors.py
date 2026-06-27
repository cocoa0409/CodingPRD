"""Debtor endpoints (§3.1, §3.2). declare-insolvent triggers the depth-3
relationship-suspension cascade."""

from flask import Blueprint, request

import db
import errors
from common import public, req_str, req_enum, req_number, opt_bool, stamp_common, touch
from middleware import authenticate, authorize, ALL_ROLES
from response import success
from routes.helpers import get_body, lookup, list_response
from services.views import debtor_view

bp = Blueprint("debtors", __name__)

CREDIT_RATINGS = {"AAA", "A", "BBB", "BB", "C"}


@bp.post("/factoring/debtors")
def create_debtor():
    _, role = authenticate()
    authorize(role, ("PlatformAdmin", "UnderwritingOfficer"))
    body = get_body()
    program_id = req_str(body, "program_id")
    legal_name = req_str(body, "legal_name")
    program = db.programs.get(program_id)
    if program is None:
        raise errors.not_found("program_id does not resolve")
    credit_rating = req_enum(body, "credit_rating", CREDIT_RATINGS)

    debtor = {
        "program_id": program_id,
        "legal_name": legal_name,
        "credit_rating": credit_rating,
        "approved_credit_ceiling_cents": None,
        "verification_required": True,
        "outstanding_face_cents": 0,
        "credit_decision_user_id": None,
        "status": "PENDING",
    }
    stamp_common(debtor)
    db.debtors[debtor["id"]] = debtor
    return success(public(debtor), status=201)


@bp.get("/factoring/debtors")
def list_debtors():
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    records = []
    for d in db.debtors.values():
        if program_id is not None and d["program_id"] != program_id:
            continue
        if status is not None and d["status"] != status:
            continue
        records.append(d)
    return list_response(records, view_fn=debtor_view)


@bp.get("/factoring/debtors/<debtor_id>")
def read_debtor(debtor_id):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    debtor = lookup(db.debtors, debtor_id)
    return success(debtor_view(debtor), status=200)


@bp.post("/factoring/debtors/<debtor_id>/credit-decision")
def debtor_credit_decision(debtor_id):
    user_id, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    debtor = lookup(db.debtors, debtor_id)
    body = get_body()
    decision = req_str(body, "decision")
    if decision not in ("APPROVE", "REJECT"):
        raise errors.invalid_request("decision must be APPROVE or REJECT")

    if debtor["status"] != "PENDING":
        raise errors.invalid_state("Debtor is not PENDING")

    if decision == "APPROVE":
        if "approved_credit_ceiling_cents" not in body or body["approved_credit_ceiling_cents"] is None:
            raise errors.invalid_request("approved_credit_ceiling_cents is required on approve")
        ceiling = body["approved_credit_ceiling_cents"]
        if isinstance(ceiling, bool) or not isinstance(ceiling, int):
            raise errors.invalid_request("approved_credit_ceiling_cents must be an integer")
        verification = opt_bool(body, "verification_required", True)
        if ceiling <= 0:
            raise errors.invalid_request("approved_credit_ceiling_cents must be greater than zero")
        debtor["approved_credit_ceiling_cents"] = ceiling
        debtor["verification_required"] = verification
        debtor["credit_decision_user_id"] = user_id
        debtor["status"] = "APPROVED"
    else:
        debtor["status"] = "REJECTED"

    touch(debtor)
    return success(debtor_view(debtor), status=200)


@bp.post("/factoring/debtors/<debtor_id>/declare-insolvent")
def declare_insolvent(debtor_id):
    _, role = authenticate()
    authorize(role, ("UnderwritingOfficer",))
    debtor = lookup(db.debtors, debtor_id)
    if debtor["status"] != "APPROVED":
        raise errors.invalid_state("Debtor is not APPROVED")

    debtor["status"] = "INSOLVENT"
    # Cascade hop 1: every NOTICED relationship on this debtor -> SUSPENDED.
    for rel in db.relationships.values():
        if rel["debtor_id"] == debtor_id and rel["notice_status"] == "NOTICED":
            rel["notice_status"] = "SUSPENDED"
            touch(rel)
    touch(debtor)
    return success(debtor_view(debtor), status=200)
