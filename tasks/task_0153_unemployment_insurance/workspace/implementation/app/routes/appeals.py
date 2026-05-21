"""Appeal routes."""
from __future__ import annotations

from flask import Blueprint, jsonify

from ..auth import (
    ROLE_ADJUDICATOR,
    ROLE_APPEAL_OFFICER,
    ROLE_CLAIMANT,
    ROLE_SYSTEM_ADMIN,
    current_user_id,
    require_auth,
)
from ..envelope import success_object
from ..serializers import serialize_appeal
from ..services.entities import (
    decide_appeal,
    file_appeal,
    start_hearing,
    withdraw_appeal,
)
from ..validators import get_json_body, optional_int, require_enum, require_string
from ._helpers import lookup_appeal, lookup_claim, require_claim_owner

bp = Blueprint("appeals", __name__)


@bp.post("/appeals")
@require_auth([ROLE_CLAIMANT])
def appeals_create():
    body = get_json_body()
    claim_id = require_string(body, "claim_id")
    cl = lookup_claim(claim_id)
    require_claim_owner(cl)
    subject_type = require_enum(
        body, "subject_type",
        {"MONETARY_DETERMINATION", "WEEKLY_DENIAL", "OVERPAYMENT_ASSESSMENT"},
    )
    subject_id = require_string(body, "subject_id")
    officer_id = require_string(body, "assigned_appeal_officer_id")
    a = file_appeal(claim_id, subject_type, subject_id, officer_id, current_user_id())
    return jsonify(success_object(serialize_appeal(a))), 201


@bp.get("/appeals/<appeal_id>")
@require_auth([ROLE_CLAIMANT, ROLE_APPEAL_OFFICER, ROLE_ADJUDICATOR, ROLE_SYSTEM_ADMIN])
def appeals_read(appeal_id: str):
    a = lookup_appeal(appeal_id)
    # Claimant must own the claim.
    cl = lookup_claim(a["claim_id"])
    require_claim_owner(cl)
    return jsonify(success_object(serialize_appeal(a))), 200


@bp.post("/appeals/<appeal_id>/start-hearing")
@require_auth([ROLE_APPEAL_OFFICER])
def appeals_start_hearing(appeal_id: str):
    lookup_appeal(appeal_id)
    a = start_hearing(appeal_id, current_user_id())
    return jsonify(success_object(serialize_appeal(a))), 200


@bp.post("/appeals/<appeal_id>/decide")
@require_auth([ROLE_APPEAL_OFFICER])
def appeals_decide(appeal_id: str):
    lookup_appeal(appeal_id)
    body = get_json_body()
    decision = require_enum(body, "decision", {"SUSTAINED", "REVERSED"})
    version = optional_int(body, "version", min_val=0)
    a = decide_appeal(appeal_id, decision, current_user_id(), version)
    return jsonify(success_object(serialize_appeal(a))), 200


@bp.post("/appeals/<appeal_id>/withdraw")
@require_auth([ROLE_CLAIMANT])
def appeals_withdraw(appeal_id: str):
    lookup_appeal(appeal_id)
    a = withdraw_appeal(appeal_id, current_user_id())
    return jsonify(success_object(serialize_appeal(a))), 200
