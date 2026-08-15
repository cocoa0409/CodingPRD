"""Dispute endpoints: open/list/get, assign-mediator, resolve, escalate."""

from decimal import Decimal

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_MEDIATOR_CONFLICT,
    ERR_MEDIATOR_INVALID,
    ERR_NOT_FOUND,
)
from middleware import body, paginate, require_roles
from response import created, ok
from serializers import dispute_view
from services.calc import (
    SCORE_DISPUTE_ESCALATED,
    adjust_reliability,
    append_ledger,
    settle_assignment,
)
from util import base_entity, to_dec, touch

bp = Blueprint("disputes", __name__)

DISPUTE_TYPES = {"SITTING_QUALITY", "CREDIT_BALANCE", "ACCESS_DAMAGE", "BEHAVIOR"}
ESCALATABLE_TYPES = {"ACCESS_DAMAGE", "BEHAVIOR"}


def get_dispute_or_404(dispute_id):
    dispute = db.store["disputes"].get(dispute_id)
    if dispute is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"Dispute {dispute_id} does not exist")
    return dispute


@bp.post("/coop/disputes")
def open_dispute():
    user_id, _ = require_roles("Member")
    data = body()
    respondent_member_id = data.get("respondent_member_id")
    if not isinstance(respondent_member_id, str) or not respondent_member_id.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "respondent_member_id is required")
    respondent = db.store["members"].get(respondent_member_id)
    if respondent is None:
        raise ApiError(
            ERR_NOT_FOUND,
            404,
            f"Respondent member {respondent_member_id} does not exist",
        )
    sitting_assignment_id = data.get("sitting_assignment_id")
    assignment = None
    if sitting_assignment_id is not None:
        assignment = db.store["assignments"].get(sitting_assignment_id)
        if assignment is None:
            raise ApiError(
                ERR_NOT_FOUND,
                404,
                f"SittingAssignment {sitting_assignment_id} does not exist",
            )
        if user_id not in (
            assignment["owner_member_id"],
            assignment["sitter_member_id"],
        ):
            raise ApiError(
                ERR_FORBIDDEN,
                403,
                "Only the assignment's owner or sitter may open a dispute on it",
            )
    dispute_type = data.get("dispute_type")
    if dispute_type not in DISPUTE_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "dispute_type must be one of SITTING_QUALITY, CREDIT_BALANCE, ACCESS_DAMAGE, BEHAVIOR",
        )
    statement = data.get("statement")
    if not isinstance(statement, str) or len(statement) < 40:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "statement must be at least 40 characters"
        )
    if dispute_type == "SITTING_QUALITY" and sitting_assignment_id is None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "sitting_assignment_id is required for SITTING_QUALITY disputes",
        )
    dispute = base_entity()
    dispute.update(
        {
            "initiator_member_id": user_id,
            "respondent_member_id": respondent_member_id,
            "sitting_assignment_id": sitting_assignment_id,
            "dispute_type": dispute_type,
            "statement": statement,
            "mediator_member_id": None,
            "status": "FILED",
            "resolution_notes": None,
        }
    )
    db.store["disputes"][dispute["id"]] = dispute
    # A dispute referencing an assignment awaiting review blocks settlement.
    if assignment is not None and assignment["status"] == "COMPLETED_PENDING_REVIEW":
        assignment["status"] = "DISPUTED"
        touch(assignment)
    return created(dispute_view(dispute))


@bp.get("/coop/disputes")
def list_disputes():
    require_roles("CoopAdmin", "Member")
    items = list(db.store["disputes"].values())
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    initiator = request.args.get("initiator_member_id")
    if initiator is not None:
        items = [d for d in items if d["initiator_member_id"] == initiator]
    respondent = request.args.get("respondent_member_id")
    if respondent is not None:
        items = [d for d in items if d["respondent_member_id"] == respondent]
    return paginate(items, dispute_view)


@bp.get("/coop/disputes/<dispute_id>")
def get_dispute(dispute_id):
    require_roles("CoopAdmin", "Member")
    return ok(dispute_view(get_dispute_or_404(dispute_id)))


@bp.post("/coop/disputes/<dispute_id>/assign-mediator")
def assign_mediator(dispute_id):
    require_roles("CoopAdmin")
    dispute = get_dispute_or_404(dispute_id)
    if dispute["status"] != "FILED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Dispute must be FILED to assign a mediator"
        )
    data = body()
    mediator_member_id = data.get("mediator_member_id")
    if not isinstance(mediator_member_id, str) or not mediator_member_id.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "mediator_member_id is required")
    mediator = db.store["members"].get(mediator_member_id)
    if (
        mediator is None
        or mediator["vetting_status"] != "VETTED"
        or mediator["mediator_flag"] is not True
    ):
        raise ApiError(
            ERR_MEDIATOR_INVALID,
            409,
            "mediator_member_id must reference a VETTED member with mediator_flag true",
        )
    if mediator_member_id in (
        dispute["initiator_member_id"],
        dispute["respondent_member_id"],
    ):
        raise ApiError(
            ERR_MEDIATOR_CONFLICT,
            409,
            "Mediator must be neither the initiator nor the respondent",
        )
    dispute["mediator_member_id"] = mediator_member_id
    dispute["status"] = "MEDIATION"
    touch(dispute)
    return ok(dispute_view(dispute))


@bp.post("/coop/disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    user_id, _ = require_roles("Member")
    dispute = get_dispute_or_404(dispute_id)
    if dispute["status"] != "MEDIATION":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Dispute must be in MEDIATION to resolve"
        )
    if user_id != dispute["mediator_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the assigned mediator may resolve the dispute"
        )
    data = body()
    outcome = data.get("outcome")
    if outcome not in ("UPHELD", "DISMISSED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "outcome must be UPHELD or DISMISSED")
    resolution_notes = data.get("resolution_notes")
    if outcome == "UPHELD" and (
        not isinstance(resolution_notes, str) or not resolution_notes.strip()
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "resolution_notes is required when outcome is UPHELD",
        )
    dispute["status"] = "RESOLVED_UPHELD" if outcome == "UPHELD" else "RESOLVED_DISMISSED"
    if isinstance(resolution_notes, str):
        dispute["resolution_notes"] = resolution_notes
    touch(dispute)
    # Credit-balance mediation adjustment: credit the initiator and debit the
    # respondent by the same amount.
    if dispute["dispute_type"] == "CREDIT_BALANCE":
        raw_adj = data.get("credit_adjustment_hours")
        if raw_adj is not None:
            try:
                adjustment = to_dec(raw_adj)
            except (TypeError, ValueError, ArithmeticError):
                raise ApiError(
                    ERR_INVALID_REQUEST,
                    400,
                    "credit_adjustment_hours must be a number",
                )
            if adjustment != 0:
                initiator = db.store["members"].get(dispute["initiator_member_id"])
                respondent = db.store["members"].get(dispute["respondent_member_id"])
                if initiator is not None:
                    append_ledger(
                        initiator,
                        "MEDIATION_ADJUSTMENT",
                        adjustment,
                        dispute_id=dispute["id"],
                        memo="Mediation adjustment in initiator's favor",
                    )
                if respondent is not None:
                    append_ledger(
                        respondent,
                        "MEDIATION_ADJUSTMENT",
                        -adjustment,
                        dispute_id=dispute["id"],
                        memo="Mediation adjustment charged to respondent",
                    )
    # A referenced DISPUTED assignment settles through the standard cascade.
    if dispute["sitting_assignment_id"] is not None:
        assignment = db.store["assignments"].get(dispute["sitting_assignment_id"])
        if assignment is not None and assignment["status"] == "DISPUTED":
            settle_assignment(assignment)
    return ok(dispute_view(dispute))


@bp.post("/coop/disputes/<dispute_id>/escalate")
def escalate_dispute(dispute_id):
    user_id, _ = require_roles("Member")
    dispute = get_dispute_or_404(dispute_id)
    if dispute["status"] != "MEDIATION":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Dispute must be in MEDIATION to escalate"
        )
    if user_id != dispute["mediator_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the assigned mediator may escalate the dispute"
        )
    data = body()
    if dispute["dispute_type"] not in ESCALATABLE_TYPES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Only ACCESS_DAMAGE and BEHAVIOR disputes may be escalated",
        )
    resolution_notes = data.get("resolution_notes")
    if not isinstance(resolution_notes, str) or not resolution_notes.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "resolution_notes is required")
    dispute["status"] = "ESCALATED_REMOVAL"
    dispute["resolution_notes"] = resolution_notes
    touch(dispute)
    respondent = db.store["members"].get(dispute["respondent_member_id"])
    if respondent is not None:
        adjust_reliability(respondent, SCORE_DISPUTE_ESCALATED)
    return ok(dispute_view(dispute))
