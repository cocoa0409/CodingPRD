"""DealMemo endpoints and negotiation lifecycle (PRD §3.5)."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_int,
    lookup,
    paginate,
)
from services.calc import MAX_ROUNDS

bp = Blueprint("deal_memos", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}


@bp.route("/deal-memos", methods=["POST"])
def create_deal_memo():
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    body = get_json_body()
    casting_call_id = require_str(body, "casting_call_id")
    talent_id = require_str(body, "talent_id")
    submission_id = require_str(body, "submission_id")
    with lock:
        lookup("CastingCall", casting_call_id)
        lookup("Talent", talent_id)
        sub = lookup("Submission", submission_id)
        record = mint_common({
            "casting_call_id": casting_call_id,
            "talent_id": talent_id,
            "submission_id": submission_id,
            "current_day_rate_cents": 0,
            "usage_term_months": 0,
            "round_count": 0,
            "status": "DRAFT",
        })
        db.deal_memos[record["id"]] = record
        # Side effect: advance submission AUDITION_SCHEDULED/CALLBACK_SCHEDULED
        # -> OFFER_EXTENDED.
        if sub["status"] in ("AUDITION_SCHEDULED", "CALLBACK_SCHEDULED"):
            sub["status"] = "OFFER_EXTENDED"
            touch(sub)
        return object_response(public(record), status=201)


@bp.route("/deal-memos", methods=["GET"])
def list_deal_memos():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.deal_memos.values())
        for field in ("casting_call_id", "talent_id", "submission_id", "status"):
            val = request.args.get(field)
            if val is not None:
                items = [d for d in items if d[field] == val]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/deal-memos/<memo_id>", methods=["GET"])
def get_deal_memo(memo_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("DealMemo", memo_id)
        return object_response(public(record), status=200)


@bp.route("/deal-memos/<memo_id>/offer", methods=["POST"])
def offer_deal_memo(memo_id):
    _, role = get_identity()
    require_role(role, {"CastingDirector"})
    body = get_json_body()
    rate = require_int(body, "offer_day_rate_cents", minimum=0)
    term = require_int(body, "offer_usage_term_months")
    with lock:
        memo = lookup("DealMemo", memo_id)
        status = memo["status"]
        if status not in ("DRAFT", "COUNTERED"):
            raise ApiError("ERR_INVALID_STATE")
        if status == "DRAFT":
            # First offer requires the submission OFFER_EXTENDED (cross-entity).
            sub = lookup("Submission", memo["submission_id"])
            if sub["status"] != "OFFER_EXTENDED":
                raise ApiError("ERR_SUBMISSION_NOT_OFFERABLE")
        else:  # re-offer out of COUNTERED, bounded by MAX_ROUNDS
            if memo["round_count"] >= MAX_ROUNDS:
                raise ApiError("ERR_MAX_NEGOTIATION_ROUNDS")
        memo["current_day_rate_cents"] = rate
        memo["usage_term_months"] = term
        memo["round_count"] += 1
        memo["status"] = "OFFERED"
        touch(memo)
        return object_response(public(memo), status=200)


@bp.route("/deal-memos/<memo_id>/counter", methods=["POST"])
def counter_deal_memo(memo_id):
    _, role = get_identity()
    require_role(role, {"Talent"})
    body = get_json_body()
    rate = require_int(body, "counter_day_rate_cents", minimum=0)
    term = require_int(body, "counter_usage_term_months")
    with lock:
        memo = lookup("DealMemo", memo_id)
        if memo["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE")
        if memo["round_count"] >= MAX_ROUNDS:
            raise ApiError("ERR_MAX_NEGOTIATION_ROUNDS")
        memo["current_day_rate_cents"] = rate
        memo["usage_term_months"] = term
        memo["round_count"] += 1
        memo["status"] = "COUNTERED"
        touch(memo)
        return object_response(public(memo), status=200)


@bp.route("/deal-memos/<memo_id>/accept", methods=["POST"])
def accept_deal_memo(memo_id):
    _, role = get_identity()
    require_role(role, {"Talent", "CastingDirector"})
    with lock:
        memo = lookup("DealMemo", memo_id)
        _resolve_party(memo, role)
        memo["status"] = "ACCEPTED"
        touch(memo)
        return object_response(public(memo), status=200)


@bp.route("/deal-memos/<memo_id>/reject", methods=["POST"])
def reject_deal_memo(memo_id):
    _, role = get_identity()
    require_role(role, {"Talent", "CastingDirector"})
    with lock:
        memo = lookup("DealMemo", memo_id)
        _resolve_party(memo, role)
        memo["status"] = "REJECTED"
        touch(memo)
        return object_response(public(memo), status=200)


def _resolve_party(memo, role):
    """The party facing the standing terms is entitled to accept/reject.

    OFFERED -> Talent faces it; COUNTERED -> CastingDirector faces it.
    """
    status = memo["status"]
    if status == "OFFERED":
        entitled = "Talent"
    elif status == "COUNTERED":
        entitled = "CastingDirector"
    else:
        raise ApiError("ERR_INVALID_STATE")
    if role != entitled:
        raise ApiError("ERR_FORBIDDEN_ROLE")
