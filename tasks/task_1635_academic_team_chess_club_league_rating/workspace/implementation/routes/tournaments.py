from flask import Blueprint, g, request

from db import store, new_id, next_seq, now_iso, parse_dt, iso
from errors import invalid_request, state_error, conflict_error
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404, touch
from services.ledger import post_ledger
from services.serializers import tournament_json, section_json
from validate import Body, get_body

bp = Blueprint("tournaments", __name__)

READ = ALL_ROLES


def _close_sections(t):
    for s in store.sections.values():
        if s["tournament_id"] == t["id"] and s["status"] in ("OPEN", "LOCKED"):
            s["status"] = "CLOSED"
            touch(s)


def _release_proctors(t):
    for a in store.proctor_assignments.values():
        if a.get("tournament_id") == t["id"] and a["status"] in ("ASSIGNED", "CONFIRMED"):
            a["status"] = "RELEASED"
            touch(a)


def _withdraw_entry_cascade(e, refund_cents, posted_by):
    e["status"] = "WITHDRAWN"
    e["refund_cents"] = refund_cents
    touch(e)
    if refund_cents > 0:
        player = store.players[e["player_id"]]
        post_ledger(player["club_id"], "ENTRY_REFUND", refund_cents,
                    posted_by, entry_id=e["id"])


@bp.route("/api/tournaments", methods=["POST"])
@require_roles("FederationAdmin")
def create_tournament():
    data = get_body()
    for field, table, what in (("season_id", store.seasons, "season"),
                               ("host_club_id", store.clubs, "club")):
        v = data.get(field)
        if isinstance(v, str):
            get_or_404(table, v, what)
    body = Body(data, {"season_id", "host_club_id", "name", "start_date",
                       "end_date", "entry_fee_cents", "early_bird_deadline",
                       "early_bird_discount_pct", "capacity"})
    sid = body.req_str("season_id")
    get_or_404(store.seasons, sid, "season")
    host = body.opt_str("host_club_id")
    if host is not None:
        get_or_404(store.clubs, host, "club")
    name = body.req_str("name")
    start = body.req_date("start_date")
    end = body.req_date("end_date")
    if end < start:
        raise invalid_request("end_date must be >= start_date")
    fee = body.req_int("entry_fee_cents")
    if fee < 0:
        raise invalid_request("entry_fee_cents must be >= 0")
    capacity = body.req_int("capacity")
    if capacity < 1:
        raise invalid_request("capacity must be >= 1")
    has_deadline = body.has("early_bird_deadline")
    has_pct = body.has("early_bird_discount_pct")
    deadline = None
    pct = None
    if has_deadline:
        deadline = iso(parse_dt(body.req_datetime("early_bird_deadline")))
        if not has_pct:
            raise invalid_request(
                "early_bird_discount_pct is required when early_bird_deadline is set")
        pct = body.req_number("early_bird_discount_pct")
        if pct < 0 or pct > 1:
            raise invalid_request("early_bird_discount_pct must be within 0..1")
    else:
        if has_pct or body.present("early_bird_discount_pct"):
            raise invalid_request(
                "early_bird_discount_pct must be absent when early_bird_deadline is not set")
    now = now_iso()
    t = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "season_id": sid,
         "host_club_id": host, "name": name, "start_date": start,
         "end_date": end, "entry_fee_cents": fee,
         "early_bird_deadline": deadline, "early_bird_discount_pct": pct,
         "capacity": capacity, "status": "DRAFT"}
    store.tournaments[t["id"]] = t
    return success_object(tournament_json(t), 201)


@bp.route("/api/tournaments", methods=["GET"])
@require_roles(*READ)
def list_tournaments():
    items = list(store.tournaments.values())
    for param, field in (("season_id", "season_id"),
                         ("host_club_id", "host_club_id"),
                         ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([tournament_json(t) for t in page], 200,
                         paginated=True, limit=limit, offset=offset,
                         total_count=total)


@bp.route("/api/tournaments/<tournamentId>", methods=["GET"])
@require_roles(*READ)
def get_tournament(tournamentId):
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    return success_object(tournament_json(t), 200)


def _t_transition(tournamentId, from_state, to_state):
    get_body()
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    if t["status"] != from_state:
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament is not in %s" % from_state)
    t["status"] = to_state
    touch(t)
    return t


@bp.route("/api/tournaments/<tournamentId>/open-registration", methods=["POST"])
@require_roles("FederationAdmin")
def open_registration(tournamentId):
    t = _t_transition(tournamentId, "DRAFT", "REGISTRATION_OPEN")
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/close-registration", methods=["POST"])
@require_roles("FederationAdmin")
def close_registration(tournamentId):
    t = _t_transition(tournamentId, "REGISTRATION_OPEN", "REGISTRATION_CLOSED")
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/reopen-registration", methods=["POST"])
@require_roles("FederationAdmin")
def reopen_registration(tournamentId):
    t = _t_transition(tournamentId, "REGISTRATION_CLOSED", "REGISTRATION_OPEN")
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/start", methods=["POST"])
@require_roles("FederationAdmin")
def start_tournament(tournamentId):
    get_body()
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    if t["status"] != "REGISTRATION_CLOSED":
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament is not REGISTRATION_CLOSED")
    if not any(a.get("tournament_id") == t["id"] and a["status"] == "CONFIRMED"
               for a in store.proctor_assignments.values()):
        raise conflict_error("ERR_NO_CONFIRMED_PROCTOR",
                             "No CONFIRMED proctor assignment for the tournament")
    t["status"] = "RUNNING"
    touch(t)
    _close_sections(t)
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/complete", methods=["POST"])
@require_roles("FederationAdmin")
def complete_tournament(tournamentId):
    get_body()
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    if t["status"] != "RUNNING":
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament is not RUNNING")
    t["status"] = "COMPLETED"
    touch(t)
    for e in store.entries.values():
        sec = store.sections[e["section_id"]]
        if sec["tournament_id"] == t["id"] and e["status"] in ("REGISTERED", "CHECKED_IN"):
            e["status"] = "FINISHED"
            touch(e)
    for a in store.proctor_assignments.values():
        if a.get("tournament_id") == t["id"] and a["status"] == "CONFIRMED":
            a["status"] = "COMPLETED"
            touch(a)
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/cancel", methods=["POST"])
@require_roles("FederationAdmin")
def cancel_tournament(tournamentId):
    get_body()
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    if t["status"] not in ("DRAFT", "REGISTRATION_OPEN", "REGISTRATION_CLOSED",
                           "RUNNING"):
        raise state_error("ERR_TOURNAMENT_INVALID_STATE",
                          "Tournament cannot be cancelled from %s" % t["status"])
    t["status"] = "CANCELLED"
    touch(t)
    # four-link cascade: withdraw with full refund -> ENTRY_REFUND post ->
    # club balance recompute -> standing auto-transition (inside post_ledger)
    for e in sorted(store.entries.values(), key=lambda x: x.get("_seq", 0)):
        sec = store.sections[e["section_id"]]
        if sec["tournament_id"] == t["id"] and e["status"] in ("REGISTERED", "CHECKED_IN"):
            _withdraw_entry_cascade(e, e["fee_cents"], g.user_id)
    _close_sections(t)
    _release_proctors(t)
    return success_object(tournament_json(t), 200)


@bp.route("/api/tournaments/<tournamentId>/sections", methods=["POST"])
@require_roles("FederationAdmin")
def create_section(tournamentId):
    data = get_body()
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    body = Body(data, {"name", "min_rating", "max_rating", "allow_provisional",
                       "max_entries"})
    name = body.req_str("name")
    min_r = body.req_int("min_rating")
    max_r = body.req_int("max_rating")
    if max_r < min_r:
        raise invalid_request("max_rating must be >= min_rating")
    allow_prov = body.opt_bool("allow_provisional")
    if allow_prov is None:
        allow_prov = False
    max_entries = body.req_int("max_entries")
    if max_entries < 1:
        raise invalid_request("max_entries must be >= 1")
    now = now_iso()
    s = {"id": new_id(), "_seq": next_seq(), "created_at": now,
         "updated_at": now, "version": 1, "tournament_id": t["id"],
         "name": name, "min_rating": min_r, "max_rating": max_r,
         "allow_provisional": allow_prov, "max_entries": max_entries,
         "status": "OPEN"}
    store.sections[s["id"]] = s
    return success_object(section_json(s), 201)


@bp.route("/api/tournaments/<tournamentId>/sections", methods=["GET"])
@require_roles(*READ)
def list_tournament_sections(tournamentId):
    t = get_or_404(store.tournaments, tournamentId, "tournament")
    items = [s for s in store.sections.values() if s["tournament_id"] == t["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([section_json(s) for s in page], 200, paginated=True,
                         limit=limit, offset=offset, total_count=total)
