"""Credit application endpoints — PRD §3.2, §3.3, §4.

State machine (SCAFFOLD Table 2): DRAFT -> SUBMITTED -> {RETURNED_FOR_INFO,
APPROVED, DECLINED}; RETURNED_FOR_INFO -> DRAFT (cyclic revision loop).
"""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_string, require_int, require_positive_int,
    serialize, paginate, sort_by_created,
)
from services import domain
from services import calculations as calc

bp = Blueprint("credit_applications", __name__)


@bp.post("/lessors/<lessor_id>/credit-applications")
def create_application(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        body = get_json_body()
        applicant_legal_name = require_string(body, "applicant_legal_name")
        requested_amount_cents = require_positive_int(body, "requested_amount_cents")
        credit_score = require_int(body, "credit_score")
        rec = db.init_record({
            "lessor_id": lessor_id,
            "applicant_legal_name": applicant_legal_name,
            "requested_amount_cents": requested_amount_cents,
            "credit_score": credit_score,
            "approved_amount_cents": None,
            "pricing_tier": None,
            "submitted_by_user_id": None,
            "revision_count": 0,
            "status": "DRAFT",
        })
        db.credit_applications[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/credit-applications/<app_id>")
def get_application(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/credit-applications")
def list_applications(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        items = [a for a in db.credit_applications.values() if a["lessor_id"] == lessor_id]
        status = request.args.get("status")
        if status is not None and status != "":
            items = [a for a in items if a["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/credit-applications/<app_id>/submit")
def submit_application(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        if rec["status"] != "DRAFT":
            raise errors.invalid_state("Application is not in DRAFT")
        # Submission preconditions (PRD §3.2): requested > 0 and score in 300..850.
        if rec["requested_amount_cents"] <= 0 or not (300 <= rec["credit_score"] <= 850):
            raise errors.invalid_request("Requested amount or credit score out of range")
        rec["status"] = "SUBMITTED"
        rec["submitted_by_user_id"] = user_id
        db.touch(rec)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/credit-applications/<app_id>/return-for-info")
def return_for_info(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        if rec["status"] != "SUBMITTED":
            raise errors.invalid_state("Application is not SUBMITTED")
        rec["status"] = "RETURNED_FOR_INFO"
        db.touch(rec)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/credit-applications/<app_id>/revise")
def revise_application(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        if rec["status"] != "RETURNED_FOR_INFO":
            raise errors.invalid_state("Application is not RETURNED_FOR_INFO")
        rec["status"] = "DRAFT"
        rec["revision_count"] += 1
        rec["submitted_by_user_id"] = None
        db.touch(rec)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/credit-applications/<app_id>/approve")
def approve_application(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        body = get_json_body()
        # Body well-formedness (priority 4) before state? PRD §2.11 puts request
        # body validity (4) ahead of state (5). But approve's required field is
        # approved_amount_cents; validate it as priority 4.
        approved_amount_cents = require_positive_int(body, "approved_amount_cents")
        if rec["status"] != "SUBMITTED":
            raise errors.invalid_state("Application is not SUBMITTED")
        # Segregation of duties first among business rules (PRD §3.2).
        if user_id == rec["submitted_by_user_id"]:
            raise errors.conflict_403(errors.ERR_SEGREGATION_OF_DUTIES,
                                      "Approver must differ from submitter")
        if approved_amount_cents > rec["requested_amount_cents"]:
            raise errors.conflict(errors.ERR_APPROVED_EXCEEDS_REQUESTED,
                                  "approved_amount_cents exceeds requested_amount_cents")
        if rec["credit_score"] < calc.APPROVAL_SCORE_FLOOR:
            raise errors.conflict(errors.ERR_SCORE_BELOW_FLOOR,
                                  "credit_score below underwriting floor")
        rec["status"] = "APPROVED"
        rec["approved_amount_cents"] = approved_amount_cents
        rec["pricing_tier"] = calc.pricing_tier(rec["credit_score"])
        db.touch(rec)
        # Cross-entity side effect: mint a Lessee bound to this application.
        lessee = db.init_record({
            "lessor_id": lessor_id,
            "credit_application_id": rec["id"],
            "legal_name": rec["applicant_legal_name"],
            "approved_credit_cents": approved_amount_cents,
            "committed_credit_cents": 0,
            "available_credit_cents": approved_amount_cents,
        })
        db.lessees[lessee["id"]] = lessee
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/credit-applications/<app_id>/decline")
def decline_application(lessor_id, app_id):
    user_id, role = get_user_context()
    require_roles(role, ["CreditAnalyst"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_credit_application(lessor_id, app_id)
        if rec["status"] != "SUBMITTED":
            raise errors.invalid_state("Application is not SUBMITTED")
        if user_id == rec["submitted_by_user_id"]:
            raise errors.conflict_403(errors.ERR_SEGREGATION_OF_DUTIES,
                                      "Decliner must differ from submitter")
        rec["status"] = "DECLINED"
        db.touch(rec)
        return object_response(serialize(rec), 200)
