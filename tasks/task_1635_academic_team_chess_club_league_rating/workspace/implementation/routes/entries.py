from decimal import Decimal

from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso, clock_now, parse_dt
from errors import (invalid_request, state_error, conflict_error,
                    integrity_error, forbidden_ownership, insufficient_funds)
from middleware import require_roles, ALL_ROLES, acting_coach
from response import success_object, success_array, paginate
from services.common import (get_or_404, touch, membership_for, club_balance,
                             section_current_entries)
from services.ledger import post_ledger
from services.ratings import round_half_up
from services.serializers import entry_json
from validate import Body, get_body

bp = Blueprint("entries", __name__)

READ = ALL_ROLES


def _entry_fee(tournament):
    """entry_fee calc: inclusive early-bird boundary; round_half_up per entry."""
    if tournament.get("early_bird_deadline") is not None and \
            clock_now() <= parse_dt(tournament["early_bird_deadline"]):
        pct = Decimal(str(tournament["early_bird_discount_pct"]))
        return round_half_up(Decimal(tournament["entry_fee_cents"]) * (1 - pct))
    return tournament["entry_fee_cents"]


@bp.route("/api/sections/<sectionId>/entries", methods=["POST"])
@require_roles("ClubCoach")
def create_entry(sectionId):
    data = get_body()
    section = get_or_404(store.sections, sectionId, "section")
    player_id = data.get("player_id")
    if isinstance(player_id, str):
        get_or_404(store.players, player_id, "player")
    # ownership (rung 5): coach registers one of their own players
    if not isinstance(player_id, str):
        raise invalid_request("player_id is required")
    player = store.players[player_id]
    coach = acting_coach()
    if coach is None or coach["club_id"] != player["club_id"]:
        raise forbidden_ownership()
    # shape (rung 7)
    Body(data, {"player_id"})
    tournament = store.tournaments[section["tournament_id"]]
    # state rung (8), pinned order: tournament first, then section
    if tournament["status"] != "REGISTRATION_OPEN":
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament is not REGISTRATION_OPEN")
    if section["status"] != "OPEN":
        raise state_error("ERR_SECTION_INVALID_STATE", "Section is not OPEN")
    # business integrity (rung 9)
    club = store.clubs[player["club_id"]]
    if club["status"] == "SUSPENDED":
        raise integrity_error("ERR_CLUB_SUSPENDED", "Club is SUSPENDED")
    if player["status"] == "SUSPENDED":
        raise integrity_error("ERR_PLAYER_SUSPENDED", "Player is SUSPENDED")
    # business referential (rung 10)
    mem = membership_for(player["id"], tournament["season_id"])
    if mem is None or mem["status"] not in ("PAID", "WAIVED"):
        raise conflict_error("ERR_MEMBERSHIP_REQUIRED",
                             "Player lacks a PAID or WAIVED membership")
    # business constraints (rung 11), pinned internal order
    if not (section["min_rating"] <= player["rating"] <= section["max_rating"]):
        raise conflict_error("ERR_RATING_OUT_OF_BAND",
                             "Player rating outside the section band")
    if player["is_provisional"] and not section["allow_provisional"]:
        raise conflict_error("ERR_PROVISIONAL_NOT_ALLOWED",
                             "Section does not allow provisional players")
    if section_current_entries(section["id"]) >= section["max_entries"]:
        raise conflict_error("ERR_SECTION_FULL", "Section is full")
    tournament_entry_count = 0
    for e in store.entries.values():
        if e["status"] == "WITHDRAWN":
            continue
        sec = store.sections[e["section_id"]]
        if sec["tournament_id"] == tournament["id"]:
            tournament_entry_count += 1
    if tournament_entry_count + 1 > tournament["capacity"]:
        raise conflict_error("ERR_TOURNAMENT_CAPACITY_EXCEEDED",
                             "Tournament capacity exceeded")
    for e in store.entries.values():
        if (e["section_id"] == section["id"] and e["player_id"] == player["id"]
                and e["status"] != "WITHDRAWN"):
            raise conflict_error("ERR_DUPLICATE_ENTRY",
                                 "Player already entered in this section")
    # fiscal guard (rung 13)
    fee = _entry_fee(tournament)
    if club_balance(club["id"]) - fee < 0:
        raise insufficient_funds()
    now = now_iso()
    e = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "section_id": section["id"],
         "player_id": player["id"], "fee_cents": fee, "refund_cents": 0,
         "status": "REGISTERED"}
    store.entries[e["id"]] = e
    if fee > 0:
        post_ledger(club["id"], "ENTRY_FEE", -fee, g.user_id, entry_id=e["id"])
    touch(section)  # current_entries grew
    return success_object(entry_json(e), 201)


@bp.route("/api/sections/<sectionId>/entries", methods=["GET"])
@require_roles(*READ)
def list_section_entries(sectionId):
    section = get_or_404(store.sections, sectionId, "section")
    items = [e for e in store.entries.values()
             if e["section_id"] == section["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([entry_json(e) for e in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/entries", methods=["GET"])
@require_roles(*READ)
def list_entries():
    items = list(store.entries.values())
    for param, field in (("section_id", "section_id"),
                         ("player_id", "player_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([entry_json(e) for e in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/entries/<entryId>", methods=["GET"])
@require_roles(*READ)
def get_entry(entryId):
    e = get_or_404(store.entries, entryId, "entry")
    return success_object(entry_json(e), 200)


@bp.route("/api/entries/<entryId>/withdraw", methods=["POST"])
@require_roles("ClubCoach")
def withdraw_entry(entryId):
    get_body()
    e = get_or_404(store.entries, entryId, "entry")
    player = store.players[e["player_id"]]
    coach = acting_coach()
    if coach is None or coach["club_id"] != player["club_id"]:
        raise forbidden_ownership()
    if e["status"] not in ("REGISTERED", "CHECKED_IN"):
        raise state_error("ERR_ENTRY_INVALID_STATE",
                          "Entry is not REGISTERED or CHECKED_IN")
    section = store.sections[e["section_id"]]
    tournament = store.tournaments[section["tournament_id"]]
    # withdrawal_refund: manual path, keyed on tournament status;
    # CHECKED_IN manual withdrawal always refunds zero.
    if e["status"] == "CHECKED_IN":
        refund = 0
    elif tournament["status"] == "REGISTRATION_OPEN":
        refund = e["fee_cents"]
    elif tournament["status"] == "REGISTRATION_CLOSED":
        refund = round_half_up(Decimal(e["fee_cents"]) * Decimal("0.5"))
    else:
        refund = 0
    e["status"] = "WITHDRAWN"
    e["refund_cents"] = refund
    touch(e)
    if refund > 0:
        post_ledger(player["club_id"], "ENTRY_REFUND", refund, g.user_id,
                    entry_id=e["id"])
    touch(section)  # current_entries shrank
    return success_object(entry_json(e), 200)


@bp.route("/api/entries/<entryId>/check-in", methods=["POST"])
@require_roles("Proctor", "FederationAdmin")
def check_in_entry(entryId):
    get_body()
    e = get_or_404(store.entries, entryId, "entry")
    # entry state checked first (pinned)
    if e["status"] != "REGISTERED":
        raise state_error("ERR_ENTRY_INVALID_STATE", "Entry is not REGISTERED")
    section = store.sections[e["section_id"]]
    tournament = store.tournaments[section["tournament_id"]]
    if tournament["status"] != "RUNNING":
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament is not RUNNING")
    e["status"] = "CHECKED_IN"
    touch(e)
    # +2 performance points: performance_points recomputes live from sources
    return success_object(entry_json(e), 200)
