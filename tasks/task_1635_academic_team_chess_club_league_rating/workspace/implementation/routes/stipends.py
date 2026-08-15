from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso
from errors import state_error, conflict_error
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, actual_stipend_meets
from services.ledger import post_ledger
from services.serializers import stipend_json
from validate import Body, get_body

bp = Blueprint("stipends", __name__)

READ = ALL_ROLES


@bp.route("/api/travel-stipends", methods=["POST"])
@require_roles("Treasurer")
def create_stipend():
    data = get_body()
    season_id = data.get("season_id")
    club_id = data.get("club_id")
    if isinstance(season_id, str):
        get_or_404(store.seasons, season_id, "season")
    if isinstance(club_id, str):
        get_or_404(store.clubs, club_id, "club")
    body = Body(data, {"season_id", "club_id"})
    sid = body.req_str("season_id")
    cid = body.req_str("club_id")
    season = get_or_404(store.seasons, sid, "season")
    club = get_or_404(store.clubs, cid, "club")
    if season["status"] != "FINALIZING":
        raise state_error("ERR_SEASON_INVALID_STATE", "Season is not FINALIZING")
    for s in store.stipends.values():
        if s["season_id"] == sid and s["club_id"] == cid:
            raise conflict_error("ERR_DUPLICATE_STIPEND",
                                 "Stipend already posted for this season and club")
    meets_counted = actual_stipend_meets(club)
    amount = club["travel_tier"] * season["travel_base_cents"] * meets_counted
    now = now_iso()
    s = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "season_id": sid, "club_id": cid,
         "meets_counted": meets_counted, "amount_cents": amount,
         "ledger_entry_id": None}
    store.stipends[s["id"]] = s
    if amount > 0:
        le = post_ledger(cid, "TRAVEL_STIPEND", amount, g.user_id)
        s["ledger_entry_id"] = le["id"]
    return success_object(stipend_json(s), 201)


@bp.route("/api/travel-stipends", methods=["GET"])
@require_roles(*READ)
def list_stipends():
    items = list(store.stipends.values())
    for param, field in (("season_id", "season_id"), ("club_id", "club_id"),
                         ("ledger_entry_id", "ledger_entry_id")):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s.get(field) == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([stipend_json(s) for s in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)


@bp.route("/api/travel-stipends/<stipendId>", methods=["GET"])
@require_roles(*READ)
def get_stipend(stipendId):
    s = get_or_404(store.stipends, stipendId, "travel stipend")
    return success_object(stipend_json(s), 200)
