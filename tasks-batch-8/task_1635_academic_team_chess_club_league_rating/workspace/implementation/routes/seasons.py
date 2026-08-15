from flask import Blueprint, request

from db import store, new_id, next_seq, now_iso
from errors import invalid_request, state_error, conflict_error, stale_version
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.serializers import season_json, snapshot_json, standing_row_json, bid_json
from services.standings import live_standings
from services.bids import generate_bids
from validate import Body, get_body

bp = Blueprint("seasons", __name__)

READ = ALL_ROLES


@bp.route("/api/seasons", methods=["POST"])
@require_roles("FederationAdmin")
def create_season():
    body = Body(get_body(), {"name", "start_date", "end_date", "dues_deadline",
                             "regular_due_cents", "late_due_cents",
                             "provisional_game_threshold", "base_rating",
                             "state_bid_slots_per_region", "travel_base_cents"})
    name = body.req_str("name")
    start_date = body.req_date("start_date")
    end_date = body.req_date("end_date")
    if end_date <= start_date:
        raise invalid_request("end_date must be strictly after start_date")
    body.req_datetime("dues_deadline")
    dues_deadline = body.d["dues_deadline"]
    regular = body.req_int("regular_due_cents")
    if regular <= 0:
        raise invalid_request("regular_due_cents must be > 0")
    late = body.req_int("late_due_cents")
    if late < regular:
        raise invalid_request("late_due_cents must be >= regular_due_cents")
    pgt = body.opt_int("provisional_game_threshold")
    if pgt is None:
        pgt = 20
    if pgt < 1:
        raise invalid_request("provisional_game_threshold must be >= 1")
    base_rating = body.opt_int("base_rating")
    if base_rating is None:
        base_rating = 800
    slots = body.opt_int("state_bid_slots_per_region")
    if slots is None:
        slots = 2
    if slots < 1:
        raise invalid_request("state_bid_slots_per_region must be >= 1")
    travel_base = body.req_int("travel_base_cents")
    if travel_base < 0:
        raise invalid_request("travel_base_cents must be >= 0")
    # normalize dues_deadline to canonical UTC form
    from db import parse_dt, iso
    dues_deadline = iso(parse_dt(dues_deadline))
    now = now_iso()
    s = {"id": new_id(), "_seq": next_seq(), "created_at": now, "updated_at": now,
         "version": 1, "name": name, "start_date": start_date, "end_date": end_date,
         "dues_deadline": dues_deadline, "regular_due_cents": regular,
         "late_due_cents": late, "provisional_game_threshold": pgt,
         "base_rating": base_rating, "state_bid_slots_per_region": slots,
         "travel_base_cents": travel_base, "status": "REGISTRATION"}
    store.seasons[s["id"]] = s
    return success_object(season_json(s), 201)


@bp.route("/api/seasons", methods=["GET"])
@require_roles(*READ)
def list_seasons():
    items = list(store.seasons.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([season_json(s) for s in page], 200,
                         paginated=True, limit=limit, offset=offset,
                         total_count=total)


@bp.route("/api/seasons/<seasonId>", methods=["GET"])
@require_roles(*READ)
def get_season(seasonId):
    s = get_or_404(store.seasons, seasonId, "season")
    return success_object(season_json(s), 200)


def _season_transition(seasonId, from_state, to_state):
    s = get_or_404(store.seasons, seasonId, "season")
    if s["status"] != from_state:
        raise state_error("ERR_SEASON_INVALID_STATE",
                          "Season is not in %s" % from_state)
    s["status"] = to_state
    touch(s)
    return s


@bp.route("/api/seasons/<seasonId>/activate", methods=["POST"])
@require_roles("FederationAdmin")
def activate_season(seasonId):
    s = _season_transition(seasonId, "REGISTRATION", "ACTIVE")
    return success_object(season_json(s), 200)


@bp.route("/api/seasons/<seasonId>/finalize", methods=["POST"])
@require_roles("FederationAdmin")
def finalize_season(seasonId):
    s = _season_transition(seasonId, "ACTIVE", "FINALIZING")
    return success_object(season_json(s), 200)


@bp.route("/api/seasons/<seasonId>/reopen", methods=["POST"])
@require_roles("FederationAdmin")
def reopen_season(seasonId):
    s = _season_transition(seasonId, "FINALIZING", "ACTIVE")
    return success_object(season_json(s), 200)


@bp.route("/api/seasons/<seasonId>/complete", methods=["POST"])
@require_roles("FederationAdmin")
def complete_season(seasonId):
    get_body()  # tolerate an empty/JSON body
    s = get_or_404(store.seasons, seasonId, "season")
    if s["status"] != "FINALIZING":
        raise state_error("ERR_SEASON_INVALID_STATE", "Season is not FINALIZING")
    if not any(x["season_id"] == s["id"] for x in store.snapshots.values()):
        raise conflict_error("ERR_STANDINGS_NOT_FINAL",
                             "No standing snapshot set exists for the season")
    open_pairing_ids = set()
    for d in store.disputes.values():
        if d["status"] in ("OPEN", "UNDER_REVIEW"):
            open_pairing_ids.add(d["pairing_id"])
    if open_pairing_ids:
        season_meet_ids = {m["id"] for m in store.meets.values()
                           if m["season_id"] == s["id"]}
        for p in store.pairings.values():
            if p["id"] in open_pairing_ids and p["meet_id"] in season_meet_ids:
                raise conflict_error("ERR_OPEN_DISPUTES_EXIST",
                                     "Open disputes remain on the season's meets")
    s["status"] = "COMPLETED"
    touch(s)
    # side effect: grade-12 ACTIVE players of this season's clubs graduate
    season_club_ids = {c["id"] for c in store.clubs.values()
                       if c["season_id"] == s["id"]}
    for p in store.players.values():
        if (p["club_id"] in season_club_ids and p["status"] == "ACTIVE"
                and p["grade_level"] == 12):
            p["status"] = "GRADUATED"
            touch(p)
    return success_object(season_json(s), 200)


@bp.route("/api/seasons/<seasonId>/standings", methods=["GET"])
@require_roles(*READ)
def get_standings(seasonId):
    s = get_or_404(store.seasons, seasonId, "season")
    rows = live_standings(s["id"])
    return success_object({"standings": [standing_row_json(r) for r in rows]}, 200)


@bp.route("/api/seasons/<seasonId>/standings/finalize", methods=["POST"])
@require_roles("FederationAdmin")
def finalize_standings(seasonId):
    data = get_body()
    s = get_or_404(store.seasons, seasonId, "season")
    # OCC (rung 6) when the field is present; absence is a shape error (rung 7)
    if "expected_season_version" in data and data["expected_season_version"] is not None:
        ev = data["expected_season_version"]
        if not isinstance(ev, int) or isinstance(ev, bool):
            raise invalid_request("expected_season_version must be an integer")
        if ev != s["version"]:
            raise stale_version()
    body = Body(data, {"expected_season_version"})
    body.req_int("expected_season_version")
    if s["status"] != "FINALIZING":
        raise state_error("ERR_SEASON_INVALID_STATE", "Season is not FINALIZING")
    # replace prior snapshot set
    for sid in [x["id"] for x in store.snapshots.values()
                if x["season_id"] == s["id"]]:
        del store.snapshots[sid]
    rows = live_standings(s["id"])
    now = now_iso()
    created = []
    for r in rows:
        snap = {"id": new_id(), "_seq": next_seq(), "created_at": now,
                "updated_at": now, "version": 1,
                "season_id": s["id"], "club_id": r["club_id"],
                "match_points": r["match_points"], "game_points": r["game_points"],
                "sonneborn_berger": r["sonneborn_berger"],
                "forfeit_losses": r["forfeit_losses"], "rank": r["rank"],
                "is_final": True}
        store.snapshots[snap["id"]] = snap
        created.append(snap)
    touch(s)  # finalize increments the season's version by 1
    return success_array([snapshot_json(x) for x in created], 201)


@bp.route("/api/seasons/<seasonId>/bids/generate", methods=["POST"])
@require_roles("FederationAdmin")
def generate(seasonId):
    get_body()
    s = get_or_404(store.seasons, seasonId, "season")
    if s["status"] != "FINALIZING":
        raise state_error("ERR_SEASON_INVALID_STATE", "Season is not FINALIZING")
    created = generate_bids(s)
    return success_array([bid_json(b) for b in created], 201)
