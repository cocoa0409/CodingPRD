from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso, clock_now, parse_dt
from errors import (invalid_request, state_error, conflict_error,
                    forbidden_ownership, insufficient_funds)
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import get_or_404, touch, membership_for, club_balance
from services.ledger import post_ledger
from services.serializers import membership_json
from validate import Body, get_body

bp = Blueprint("memberships", __name__)

READ = ALL_ROLES


@bp.route("/api/memberships", methods=["POST"])
@require_roles("ClubCoach", "FederationAdmin")
def create_membership():
    data = get_body()
    player_id = data.get("player_id")
    season_id = data.get("season_id")
    if isinstance(player_id, str):
        get_or_404(store.players, player_id, "player")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season")
    if g.user_role == "ClubCoach":
        coach = acting_coach()
        if not isinstance(player_id, str):
            raise invalid_request("player_id is required")
        player = get_or_404(store.players, player_id, "player")
        if coach is None or coach["club_id"] != player["club_id"]:
            raise forbidden_ownership()
    body = Body(data, {"player_id", "season_id"})
    pid = body.req_str("player_id")
    sid = body.req_str("season_id")
    player = get_or_404(store.players, pid, "player")
    season = get_or_404(store.seasons, sid, "season")
    if membership_for(pid, sid) is not None:
        raise conflict_error("ERR_DUPLICATE_MEMBERSHIP",
                             "Membership already exists for this player and season")
    # membership_fee: created_at <= dues_deadline (inclusive) -> regular
    fee = (season["regular_due_cents"]
           if clock_now() <= parse_dt(season["dues_deadline"])
           else season["late_due_cents"])
    now = now_iso()
    m = {"id": new_id(), "_seq": next_seq(), "created_at": now, "updated_at": now,
         "version": 1, "player_id": pid, "season_id": sid, "fee_cents": fee,
         "paid_at": None, "status": "INVOICED"}
    store.memberships[m["id"]] = m
    return success_object(membership_json(m), 201)


@bp.route("/api/memberships", methods=["GET"])
@require_roles(*READ)
def list_memberships():
    items = list(store.memberships.values())
    pid = request.args.get("player_id")
    if pid is not None:
        items = [m for m in items if m["player_id"] == pid]
    sid = request.args.get("season_id")
    if sid is not None:
        items = [m for m in items if m["season_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([membership_json(m) for m in page], 200,
                         paginated=True, limit=limit, offset=offset,
                         total_count=total)


@bp.route("/api/memberships/<membershipId>", methods=["GET"])
@require_roles(*READ)
def get_membership(membershipId):
    m = get_or_404(store.memberships, membershipId, "membership")
    return success_object(membership_json(m), 200)


@bp.route("/api/memberships/<membershipId>/pay", methods=["POST"])
@require_roles("ClubCoach", "Treasurer", "FederationAdmin")
def pay_membership(membershipId):
    get_body()
    m = get_or_404(store.memberships, membershipId, "membership")
    player = store.players[m["player_id"]]
    if g.user_role == "ClubCoach":
        coach = acting_coach()
        if coach is None or coach["club_id"] != player["club_id"]:
            raise forbidden_ownership()
    if m["status"] != "INVOICED":
        raise state_error("ERR_MEMBERSHIP_NOT_PAYABLE",
                          "Membership is not INVOICED")
    club_id = player["club_id"]
    if club_balance(club_id) - m["fee_cents"] < 0:
        raise insufficient_funds()
    post_ledger(club_id, "MEMBERSHIP_DUE", -m["fee_cents"], g.user_id,
                membership_id=m["id"])
    m["paid_at"] = now_iso()
    m["status"] = "PAID"
    touch(m)
    return success_object(membership_json(m), 200)


@bp.route("/api/memberships/<membershipId>/waive", methods=["POST"])
@require_roles("FederationAdmin")
def waive_membership(membershipId):
    get_body()
    m = get_or_404(store.memberships, membershipId, "membership")
    if m["status"] != "INVOICED":
        raise state_error("ERR_MEMBERSHIP_NOT_PAYABLE",
                          "Membership is not INVOICED")
    m["status"] = "WAIVED"
    touch(m)
    return success_object(membership_json(m), 200)


@bp.route("/api/memberships/<membershipId>/refund", methods=["POST"])
@require_roles("Treasurer")
def refund_membership(membershipId):
    get_body()
    m = get_or_404(store.memberships, membershipId, "membership")
    if m["status"] != "PAID":
        raise state_error("ERR_MEMBERSHIP_NOT_REFUNDABLE",
                          "Membership is not PAID")
    player = store.players[m["player_id"]]
    post_ledger(player["club_id"], "MEMBERSHIP_DUE", m["fee_cents"], g.user_id,
                membership_id=m["id"])
    m["status"] = "REFUNDED"
    touch(m)
    return success_object(membership_json(m), 200)
