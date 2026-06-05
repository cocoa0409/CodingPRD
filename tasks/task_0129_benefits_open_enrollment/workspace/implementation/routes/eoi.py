"""EOIRequest endpoints (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint, request

import db
import errors as E
from middleware import (
    authenticate, authorize,
    BENEFITS_ADMIN, COMPLIANCE_OFFICER,
)
import response
from services import common as C
from services import domain as D
from routes._helpers import get_or_404

bp = Blueprint("eoi", __name__)

DECISIONS = {"APPROVED", "DENIED"}


@bp.route("/eoi-requests/<eoi_id>", methods=["GET"])
def get_eoi(eoi_id):
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER})
    eoi = get_or_404(db.eoi_requests, eoi_id, "EOIRequest")
    return response.ok_object(C.serialize(eoi), 200)


@bp.route("/eoi-requests", methods=["GET"])
def list_eoi():
    role = authenticate()
    authorize(role, {BENEFITS_ADMIN, COMPLIANCE_OFFICER})
    limit, offset = C.parse_pagination()
    enrollment_id = request.args.get("enrollment_id")
    decision = request.args.get("decision")
    items = list(db.eoi_requests.values())
    if enrollment_id is not None:
        items = [e for e in items if e["enrollment_id"] == enrollment_id]
    if decision is not None:
        items = [e for e in items if e["decision"] == decision]
    items = C.order_by_created(items)
    page, total = C.paginate(items, limit, offset)
    return response.ok_array(C.serialize_list(page), limit, offset, total, 200)


@bp.route("/eoi-requests/<eoi_id>/decide", methods=["POST"])
def decide_eoi(eoi_id):
    role = authenticate()
    authorize(role, {COMPLIANCE_OFFICER})
    eoi = get_or_404(db.eoi_requests, eoi_id, "EOIRequest")
    body = C.get_body()
    C.require_fields(body, ["decision"])
    decision = C.require_enum(body, "decision", DECISIONS)

    # State (priority 5): the request must currently be PENDING and the linked
    # enrollment must currently be PENDING_EOI.
    if eoi["decision"] != "PENDING":
        raise E.invalid_state("EOIRequest must be PENDING to decide")
    enr = db.enrollments.get(eoi["enrollment_id"])
    if enr is None or enr["status"] != "PENDING_EOI":
        raise E.invalid_state("Linked enrollment must be PENDING_EOI")

    emp = db.employees[enr["employee_id"]]

    if decision == "APPROVED":
        eoi["decision"] = "APPROVED"
        C.touch(eoi)
        # Cross-entity cascade: enrollment PENDING_EOI -> ACTIVE.
        enr["status"] = "ACTIVE"
        D.recompute_enrollment_costs(enr, emp)
        C.touch(enr)
        D.emit_carrier_feed(enr, "ADD")
    else:  # DENIED
        eoi["decision"] = "DENIED"
        C.touch(eoi)
        # Compensation: enrollment PENDING_EOI -> DRAFT; no carrier feed.
        enr["status"] = "DRAFT"
        C.touch(enr)

    return response.ok_object(C.serialize(eoi), 200)
