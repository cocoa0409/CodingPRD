"""Routes: rounds, pairings, pairing-entries."""
from datetime import timedelta

from flask import Blueprint, request

from core import (
    ApiError, auth_context, db, get_body, new_id, now_ts, ok, paginate, parse_dt,
    require_role, touch, validation_error,
)
from services import (
    generate_pairings, get_or_404, pairing_member_ids, recompute_division_stats,
    resolve_elim_placements, round_pairings, serialize_pairing,
    serialize_pairing_entry, serialize_round,
)

bp = Blueprint("routes_c", __name__)

TAB = ["TabStaff"]
TURNOVER = timedelta(minutes=30)


def get_round(rid):
    return get_or_404("rounds", rid, "ERR_ROUND_NOT_FOUND")


def get_pairing(pid):
    return get_or_404("pairings", pid, "ERR_PAIRING_NOT_FOUND")


def _pairing_tournament(p):
    r = db.rounds.get(p["round_id"])
    div = db.divisions.get(r["division_id"]) if r else None
    return db.tournaments.get(div["tournament_id"]) if div else None


def _pairing_slot(p):
    r = db.rounds.get(p["round_id"])
    return (r["starts_at"], r["ends_at"]) if r else (None, None)


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


@bp.route("/rounds", methods=["POST"])
def create_round():
    _, role = auth_context()
    require_role(role, TAB)
    body = get_body()
    division_id = body.get("division_id")
    div = db.divisions.get(division_id) if division_id else None
    if div is None:
        raise ApiError("ERR_DIVISION_NOT_FOUND", 404, "division_id does not exist")
    number = body.get("round_number")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise validation_error("round_number must be an integer >= 1")
    kind = body.get("kind")
    if kind not in ("PRELIM", "ELIM"):
        raise validation_error("kind must be PRELIM or ELIM")
    try:
        starts_at = parse_dt(body.get("starts_at"))
        ends_at = parse_dt(body.get("ends_at"))
    except (ValueError, TypeError):
        raise validation_error("starts_at and ends_at are required ISO-8601 datetimes")
    if not starts_at < ends_at:
        raise ApiError("ERR_ROUND_INVALID_STATE", 409, "starts_at must be strictly earlier than ends_at")
    for r in db.rounds.values():
        if r["division_id"] == div["id"] and r["round_number"] == number:
            raise ApiError("ERR_ROUND_NUMBER_EXISTS", 409,
                           "A round with this round_number already exists in the division")
    r = {
        "id": new_id(),
        "division_id": div["id"],
        "round_number": number,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "SCHEDULED",
        "pairings_total": 0,
        "pairings_verified_count": 0,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.rounds[r["id"]] = r
    return ok(serialize_round(r), 201)


@bp.route("/rounds", methods=["GET"])
def list_rounds():
    auth_context()
    items = list(db.rounds.values())
    did = request.args.get("division_id")
    kind = request.args.get("kind")
    status = request.args.get("status")
    if did:
        items = [r for r in items if r["division_id"] == did]
    if kind:
        items = [r for r in items if r["kind"] == kind]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    data, meta = paginate(items, serialize_round)
    return ok(data, 200, meta)


@bp.route("/rounds/<rid>", methods=["GET"])
def get_round_route(rid):
    auth_context()
    return ok(serialize_round(get_round(rid)), 200)


@bp.route("/rounds/<rid>/generate-pairings", methods=["POST"])
def generate_pairings_route(rid):
    _, role = auth_context()
    require_role(role, TAB)
    r = get_round(rid)
    div = db.divisions.get(r["division_id"])
    t = db.tournaments.get(div["tournament_id"]) if div else None
    required_phase = "PRELIMS_ACTIVE" if r["kind"] == "PRELIM" else "ELIMS_ACTIVE"
    if not t or t["status"] != required_phase:
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Pairing generation requires tournament %s" % required_phase)
    body = get_body()
    expected = body.get("expected_round_version")
    if not isinstance(expected, int) or expected != r["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_round_version does not match the round's current version")
    if r["status"] != "SCHEDULED":
        raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                       "generate-pairings requires round status SCHEDULED")
    for other in db.rounds.values():
        if (other["division_id"] == r["division_id"] and other["kind"] == r["kind"]
                and other["round_number"] < r["round_number"] and other["status"] != "TABULATED"):
            raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                           "All prior-numbered %s rounds of the division must be TABULATED" % r["kind"])
    created = generate_pairings(r)
    r["pairings_total"] = len(created)
    r["pairings_verified_count"] = sum(1 for p in created if p["status"] == "VERIFIED")
    r["status"] = "PAIRED"
    touch(r)
    return ok(serialize_round(r), 200)


@bp.route("/rounds/<rid>/open-ballots", methods=["POST"])
def open_ballots(rid):
    _, role = auth_context()
    require_role(role, TAB)
    r = get_round(rid)
    if r["status"] != "PAIRED":
        raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                       "open-ballots requires round status PAIRED")
    for p in round_pairings(r["id"]):
        if not p["is_bye"] and p["status"] != "STAFFED":
            raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                           "Every non-bye pairing must be STAFFED to open ballots")
    for p in round_pairings(r["id"]):
        if not p["is_bye"] and p["status"] == "STAFFED":
            p["status"] = "BALLOT_RELEASED"
            touch(p)
    r["status"] = "BALLOTS_OPEN"
    touch(r)
    return ok(serialize_round(r), 200)


@bp.route("/rounds/<rid>/tabulate", methods=["POST"])
def tabulate_round(rid):
    _, role = auth_context()
    require_role(role, TAB)
    r = get_round(rid)
    if r["status"] != "BALLOTS_OPEN":
        raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                       "tabulate requires round status BALLOTS_OPEN")
    for p in round_pairings(r["id"]):
        if p["status"] != "VERIFIED":
            raise ApiError("ERR_ROUND_INVALID_STATE", 409,
                           "Every pairing of the round must be VERIFIED to tabulate")
    div = db.divisions.get(r["division_id"])
    if div is not None:
        recompute_division_stats(div)
        if r["kind"] == "ELIM":
            resolve_elim_placements(r, div)
    r["status"] = "TABULATED"
    touch(r)
    return ok(serialize_round(r), 200)


# ---------------------------------------------------------------------------
# Pairings
# ---------------------------------------------------------------------------


@bp.route("/pairings", methods=["GET"])
def list_pairings():
    auth_context()
    items = list(db.pairings.values())
    rid = request.args.get("round_id")
    jid = request.args.get("judge_id")
    room_id = request.args.get("room_id")
    status = request.args.get("status")
    if rid:
        items = [p for p in items if p["round_id"] == rid]
    if jid:
        items = [p for p in items if p["judge_id"] == jid]
    if room_id:
        items = [p for p in items if p["room_id"] == room_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["created_at"])
    data, meta = paginate(items, serialize_pairing)
    return ok(data, 200, meta)


@bp.route("/pairings/<pid>", methods=["GET"])
def get_pairing_route(pid):
    auth_context()
    return ok(serialize_pairing(get_pairing(pid)), 200)


@bp.route("/pairings/<pid>/assign-room", methods=["POST"])
def assign_room(pid):
    _, role = auth_context()
    require_role(role, TAB)
    p = get_pairing(pid)
    body = get_body()
    room_id = body.get("room_id")
    room = db.rooms.get(room_id) if room_id else None
    if room is None:
        raise ApiError("ERR_ROOM_NOT_FOUND", 404, "room_id does not exist")
    if p["status"] not in ("PENDING_STAFFING", "STAFFED"):
        raise ApiError("ERR_PAIRING_INVALID_STATE", 409,
                       "assign-room requires pairing status PENDING_STAFFING or STAFFED")
    new_start, new_end = _pairing_slot(p)
    for other in db.pairings.values():
        if other["id"] == p["id"] or other["room_id"] != room["id"]:
            continue
        o_start, o_end = _pairing_slot(other)
        if o_start is None or new_start is None:
            continue
        if o_start < new_end and new_start < o_end:
            raise ApiError("ERR_ROOM_DOUBLE_BOOKED", 409,
                           "Room is already occupied by an overlapping pairing slot")
    t = _pairing_tournament(p)
    if t is None or room["tournament_id"] != t["id"]:
        raise ApiError("ERR_CROSS_TOURNAMENT_REFERENCE", 409,
                       "Room and pairing belong to different tournaments")
    p["room_id"] = room["id"]
    if p["judge_id"] is not None and p["status"] == "PENDING_STAFFING":
        p["status"] = "STAFFED"
    touch(p)
    return ok(serialize_pairing(p), 200)


@bp.route("/pairings/<pid>/assign-judge", methods=["POST"])
def assign_judge(pid):
    _, role = auth_context()
    require_role(role, TAB)
    p = get_pairing(pid)
    body = get_body()
    judge_id = body.get("judge_id")
    j = db.judges.get(judge_id) if judge_id else None
    if j is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", 404, "judge_id does not exist")
    if j["status"] != "COMMITTED":
        raise ApiError("ERR_JUDGE_INVALID_STATE", 409,
                       "assign-judge requires judge status COMMITTED")
    if p["status"] != "PENDING_STAFFING" or p["judge_id"] is not None:
        raise ApiError("ERR_PAIRING_INVALID_STATE", 409,
                       "assign-judge requires pairing status PENDING_STAFFING with no judge")
    member_schools = set()
    for mid in pairing_member_ids(p["id"]):
        e = db.entries.get(mid)
        if e:
            member_schools.add(e["school_id"])
    conflicted_schools = set()
    if j["school_id"] is not None:
        conflicted_schools.add(j["school_id"])
    for c in db.judge_conflicts.values():
        if c["judge_id"] == j["id"]:
            conflicted_schools.add(c["school_id"])
    if member_schools & conflicted_schools:
        raise ApiError("ERR_JUDGE_CONFLICT_OF_INTEREST", 409,
                       "Judge may not be assigned to a pairing involving a conflicted school")
    assigned_count = sum(1 for x in db.pairings.values() if x["judge_id"] == j["id"])
    if assigned_count >= j["commitment_rounds"]:
        raise ApiError("ERR_JUDGE_OVER_COMMITTED", 409,
                       "Judge has reached their commitment_rounds ceiling")
    new_start, new_end = _pairing_slot(p)
    for other in db.pairings.values():
        if other["id"] == p["id"] or other["judge_id"] != j["id"]:
            continue
        o_start, o_end = _pairing_slot(other)
        if o_start is None or new_start is None:
            continue
        if o_start < new_end and new_start < o_end:
            raise ApiError("ERR_JUDGE_TURNOVER_CONFLICT", 409,
                           "Judge is staffed on an overlapping pairing slot")
        if o_end <= new_start and (new_start - o_end) < TURNOVER:
            raise ApiError("ERR_JUDGE_TURNOVER_CONFLICT", 409,
                           "Judge has less than 30 minutes before an adjacent pairing")
        if new_end <= o_start and (o_start - new_end) < TURNOVER:
            raise ApiError("ERR_JUDGE_TURNOVER_CONFLICT", 409,
                           "Judge has less than 30 minutes after an adjacent pairing")
    t = _pairing_tournament(p)
    if t is None or j["tournament_id"] != t["id"]:
        raise ApiError("ERR_CROSS_TOURNAMENT_REFERENCE", 409,
                       "Judge and pairing belong to different tournaments")
    p["judge_id"] = j["id"]
    if p["room_id"] is not None:
        p["status"] = "STAFFED"
    touch(p)
    touch(j)
    return ok(serialize_pairing(p), 200)


@bp.route("/pairings/<pid>/unassign-judge", methods=["POST"])
def unassign_judge(pid):
    _, role = auth_context()
    require_role(role, TAB)
    p = get_pairing(pid)
    if p["status"] not in ("PENDING_STAFFING", "STAFFED") or p["judge_id"] is None:
        raise ApiError("ERR_PAIRING_INVALID_STATE", 409,
                       "unassign-judge requires a staffed pairing in PENDING_STAFFING or STAFFED")
    j = db.judges.get(p["judge_id"])
    p["judge_id"] = None
    p["status"] = "PENDING_STAFFING"
    touch(p)
    if j is not None:
        touch(j)
    return ok(serialize_pairing(p), 200)


# ---------------------------------------------------------------------------
# Pairing entries
# ---------------------------------------------------------------------------


@bp.route("/pairing-entries", methods=["GET"])
def list_pairing_entries():
    auth_context()
    items = list(db.pairing_entries.values())
    pid = request.args.get("pairing_id")
    eid = request.args.get("entry_id")
    if pid:
        items = [pe for pe in items if pe["pairing_id"] == pid]
    if eid:
        items = [pe for pe in items if pe["entry_id"] == eid]
    items.sort(key=lambda pe: pe["created_at"])
    data, meta = paginate(items, serialize_pairing_entry)
    return ok(data, 200, meta)


@bp.route("/pairing-entries/<peid>", methods=["GET"])
def get_pairing_entry(peid):
    auth_context()
    return ok(
        serialize_pairing_entry(
            get_or_404("pairing_entries", peid, "ERR_PAIRING_ENTRY_NOT_FOUND")
        ),
        200,
    )
