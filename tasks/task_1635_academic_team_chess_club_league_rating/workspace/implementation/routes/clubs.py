from flask import Blueprint, request

from db import store, new_id, next_seq, now_iso
from errors import invalid_request, state_error
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate, num_out
from services.common import get_or_404, touch
from services.serializers import club_json
from validate import Body, get_body

bp = Blueprint("clubs", __name__)

READ = ALL_ROLES

TIER1_CENTS = 40000
TIER2_CENTS = 80000
TIER1_PCT = 0.05
TIER2_PCT = 0.10


@bp.route("/api/clubs", methods=["POST"])
@require_roles("FederationAdmin")
def create_club():
    data = get_body()
    # body FK first (rung 4)
    season_id = data.get("season_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season")
    body = Body(data, {"season_id", "name", "school_name", "region_code",
                       "travel_tier"})
    sid = body.req_str("season_id")
    get_or_404(store.seasons, sid, "season")
    name = body.req_str("name")
    school = body.req_str("school_name")
    region = body.req_str("region_code")
    tier = body.req_int("travel_tier")
    if tier not in (1, 2, 3):
        raise invalid_request("travel_tier must be 1, 2 or 3")
    now = now_iso()
    c = {"id": new_id(), "_seq": next_seq(), "created_at": now, "updated_at": now,
         "version": 1, "season_id": sid, "name": name, "school_name": school,
         "region_code": region, "travel_tier": tier,
         "account_balance_cents": 0, "status": "GOOD_STANDING"}
    store.clubs[c["id"]] = c
    return success_object(club_json(c), 201)


@bp.route("/api/clubs", methods=["GET"])
@require_roles(*READ)
def list_clubs():
    items = list(store.clubs.values())
    sid = request.args.get("season_id")
    if sid is not None:
        items = [c for c in items if c["season_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    region = request.args.get("region_code")
    if region is not None:
        items = [c for c in items if c["region_code"] == region]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([club_json(c) for c in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/clubs/<clubId>", methods=["GET"])
@require_roles(*READ)
def get_club(clubId):
    c = get_or_404(store.clubs, clubId, "club")
    return success_object(club_json(c), 200)


@bp.route("/api/clubs/<clubId>/suspend", methods=["POST"])
@require_roles("FederationAdmin")
def suspend_club(clubId):
    get_body()
    c = get_or_404(store.clubs, clubId, "club")
    if c["status"] not in ("GOOD_STANDING", "DELINQUENT"):
        raise state_error("ERR_CLUB_INVALID_STATE",
                          "Club cannot be suspended from %s" % c["status"])
    c["status"] = "SUSPENDED"
    touch(c)
    return success_object(club_json(c), 200)


@bp.route("/api/clubs/<clubId>/reinstate", methods=["POST"])
@require_roles("FederationAdmin")
def reinstate_club(clubId):
    get_body()
    c = get_or_404(store.clubs, clubId, "club")
    if c["status"] != "SUSPENDED":
        raise state_error("ERR_CLUB_INVALID_STATE", "Club is not SUSPENDED")
    from services.common import club_balance
    bal = club_balance(c["id"])
    c["account_balance_cents"] = bal
    c["status"] = "DELINQUENT" if bal < 0 else "GOOD_STANDING"
    touch(c)
    return success_object(club_json(c), 200)


@bp.route("/api/clubs/<clubId>/season-invoice", methods=["GET"])
@require_roles("FederationAdmin", "ClubCoach", "Treasurer", "Auditor")
def season_invoice(clubId):
    from decimal import Decimal
    from services.ratings import round_half_up
    c = get_or_404(store.clubs, clubId, "club")
    season_id = request.args.get("season_id")
    if season_id is None:
        raise invalid_request("season_id query parameter is required")
    get_or_404(store.seasons, season_id, "season")
    player_ids = {p["id"] for p in store.players.values()
                  if p["club_id"] == c["id"]}
    dues = sum(m["fee_cents"] for m in store.memberships.values()
               if m["player_id"] in player_ids and m["season_id"] == season_id
               and m["status"] == "PAID")
    season_tournament_ids = {t["id"] for t in store.tournaments.values()
                             if t["season_id"] == season_id}
    season_section_ids = {s["id"] for s in store.sections.values()
                          if s["tournament_id"] in season_tournament_ids}
    entries = sum(e["fee_cents"] - e["refund_cents"]
                  for e in store.entries.values()
                  if e["player_id"] in player_ids
                  and e["section_id"] in season_section_ids)
    subtotal = dues + entries
    if subtotal >= TIER2_CENTS:
        pct = TIER2_PCT
    elif subtotal >= TIER1_CENTS:
        pct = TIER1_PCT
    else:
        pct = 0.0
    credit = round_half_up(Decimal(subtotal) * Decimal(str(pct)))
    total = subtotal - credit
    return success_object({
        "dues_subtotal_cents": dues,
        "entries_subtotal_cents": entries,
        "volume_credit_cents": credit,
        "total_cents": total,
        "credit_tier_pct": num_out(pct),
    }, 200)
