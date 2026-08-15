from flask import Blueprint, g, request

from db import store
from errors import invalid_request, state_error, forbidden_ownership
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.ratings import (ALL_RESULTS, apply_confirmation_effects,
                              apply_overturn_effects)
from services.serializers import dispute_json
from validate import Body, get_body

bp = Blueprint("disputes", __name__)

READ = ALL_ROLES


@bp.route("/api/disputes", methods=["GET"])
@require_roles(*READ)
def list_disputes():
    items = list(store.disputes.values())
    for param, field in (("pairing_id", "pairing_id"),
                         ("raised_by_coach_id", "raised_by_coach_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([dispute_json(d) for d in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/disputes/<disputeId>", methods=["GET"])
@require_roles(*READ)
def get_dispute(disputeId):
    d = get_or_404(store.disputes, disputeId, "dispute")
    return success_object(dispute_json(d), 200)


@bp.route("/api/disputes/<disputeId>/open-review", methods=["POST"])
@require_roles("FederationAdmin")
def open_review(disputeId):
    get_body()
    d = get_or_404(store.disputes, disputeId, "dispute")
    if d["status"] != "OPEN":
        raise state_error("ERR_DISPUTE_INVALID_STATE", "Dispute is not OPEN")
    d["status"] = "UNDER_REVIEW"
    touch(d)
    return success_object(dispute_json(d), 200)


@bp.route("/api/disputes/<disputeId>/resolve", methods=["POST"])
@require_roles("FederationAdmin")
def resolve_dispute(disputeId):
    data = get_body()
    d = get_or_404(store.disputes, disputeId, "dispute")
    # state checked first (pinned)
    if d["status"] != "UNDER_REVIEW":
        raise state_error("ERR_DISPUTE_INVALID_STATE",
                          "Dispute is not UNDER_REVIEW")
    body = Body(data, {"outcome", "resolved_result", "resolution_notes"})
    outcome = body.req_enum("outcome", ("UPHELD", "OVERTURNED"))
    notes = body.opt_str("resolution_notes")
    p = store.pairings[d["pairing_id"]]
    if outcome == "UPHELD":
        if body.present("resolved_result") and body.d["resolved_result"] is not None:
            raise invalid_request("resolved_result must be absent for UPHELD")
        d["status"] = "UPHELD"
        d["resolution_notes"] = notes
        touch(d)
        # reported result stands; apply rating side effects if never confirmed
        p["status"] = "CONFIRMED"
        if not p["was_confirmed"]:
            apply_confirmation_effects(p)
        else:
            touch(p)
    else:
        rr = body.d.get("resolved_result")
        if rr is None or rr not in ALL_RESULTS:
            raise invalid_request(
                "resolved_result is required for OVERTURNED and must be a "
                "reportable result (not UNREPORTED)")
        d["status"] = "OVERTURNED"
        d["resolved_result"] = rr
        d["resolution_notes"] = notes
        touch(d)
        p["status"] = "CONFIRMED"
        apply_overturn_effects(p, rr)
    return success_object(dispute_json(d), 200)


@bp.route("/api/disputes/<disputeId>/withdraw", methods=["POST"])
@require_roles("ClubCoach")
def withdraw_dispute(disputeId):
    get_body()
    d = get_or_404(store.disputes, disputeId, "dispute")
    # state checked first (pinned)
    if d["status"] != "OPEN":
        raise state_error("ERR_DISPUTE_INVALID_STATE", "Dispute is not OPEN")
    if d["raised_by_coach_id"] != g.user_id:
        raise forbidden_ownership()
    d["status"] = "WITHDRAWN"
    touch(d)
    p = store.pairings[d["pairing_id"]]
    # restore without touching ratings
    p["status"] = "CONFIRMED" if p["was_confirmed"] else "REPORTED"
    touch(p)
    return success_object(dispute_json(d), 200)
