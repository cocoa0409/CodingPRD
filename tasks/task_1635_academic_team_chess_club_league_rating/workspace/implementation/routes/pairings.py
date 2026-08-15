from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso
from errors import (invalid_request, state_error, integrity_error,
                    forbidden_ownership)
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.ratings import (ALL_RESULTS, apply_confirmation_effects)
from services.serializers import pairing_json, dispute_json
from validate import Body, get_body

bp = Blueprint("pairings", __name__)

READ = ALL_ROLES


def _meet_of(pairing):
    return store.meets[pairing["meet_id"]]


def _coach_in_meet_clubs(meet):
    coach = acting_coach()
    if coach is None or coach["club_id"] not in (meet["host_club_id"],
                                                 meet["away_club_id"]):
        raise forbidden_ownership()
    return coach


@bp.route("/api/pairings", methods=["GET"])
@require_roles(*READ)
def list_pairings():
    items = list(store.pairings.values())
    for param, field in (("meet_id", "meet_id"),
                         ("white_player_id", "white_player_id"),
                         ("black_player_id", "black_player_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([pairing_json(p) for p in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/pairings/<pairingId>", methods=["GET"])
@require_roles(*READ)
def get_pairing(pairingId):
    p = get_or_404(store.pairings, pairingId, "pairing")
    return success_object(pairing_json(p), 200)


@bp.route("/api/pairings/<pairingId>/report-result", methods=["POST"])
@require_roles("ClubCoach")
def report_result(pairingId):
    data = get_body()
    p = get_or_404(store.pairings, pairingId, "pairing")
    # pairing state checked first (pinned)
    if p["status"] != "SCHEDULED":
        raise state_error("ERR_PAIRING_INVALID_STATE", "Pairing is not SCHEDULED")
    meet = _meet_of(p)
    if meet["status"] != "IN_PROGRESS":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not IN_PROGRESS")
    coach = _coach_in_meet_clubs(meet)
    body = Body(data, {"result"})
    result = body.req_enum("result", ALL_RESULTS)
    p["result"] = result
    p["reported_by_coach_id"] = coach["id"]
    p["status"] = "REPORTED"
    touch(p)
    return success_object(pairing_json(p), 200)


@bp.route("/api/pairings/<pairingId>/confirm", methods=["POST"])
@require_roles("ClubCoach")
def confirm_result(pairingId):
    get_body()
    p = get_or_404(store.pairings, pairingId, "pairing")
    if p["status"] != "REPORTED":
        raise state_error("ERR_PAIRING_INVALID_STATE", "Pairing is not REPORTED")
    meet = _meet_of(p)
    if meet["status"] != "IN_PROGRESS":
        raise state_error("ERR_MEET_INVALID_STATE", "Meet is not IN_PROGRESS")
    coach = _coach_in_meet_clubs(meet)
    reporter = store.coaches.get(p["reported_by_coach_id"])
    if reporter is not None and coach["club_id"] == reporter["club_id"]:
        raise integrity_error("ERR_SAME_CLUB_CONFIRMATION",
                              "Confirmer must not belong to the reporting club")
    p["status"] = "CONFIRMED"
    apply_confirmation_effects(p)
    return success_object(pairing_json(p), 200)


@bp.route("/api/pairings/<pairingId>/dispute", methods=["POST"])
@require_roles("ClubCoach")
def dispute_pairing(pairingId):
    data = get_body()
    p = get_or_404(store.pairings, pairingId, "pairing")
    if p["status"] not in ("REPORTED", "CONFIRMED"):
        raise state_error("ERR_PAIRING_INVALID_STATE",
                          "Pairing is not REPORTED or CONFIRMED")
    meet = _meet_of(p)
    coach = _coach_in_meet_clubs(meet)
    body = Body(data, {"reason"})
    reason = body.req_str("reason")
    if len(reason) < 10:
        raise invalid_request("reason must be at least 10 characters")
    now = now_iso()
    d = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "pairing_id": p["id"],
         "raised_by_coach_id": coach["id"], "reason": reason,
         "resolved_result": None, "resolution_notes": None, "status": "OPEN"}
    store.disputes[d["id"]] = d
    p["status"] = "DISPUTED"
    touch(p)
    return success_object(dispute_json(d), 201)
