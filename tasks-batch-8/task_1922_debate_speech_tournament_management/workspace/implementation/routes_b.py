"""Routes: entries, judges, judge-conflicts, rooms."""
from decimal import Decimal

from flask import Blueprint, request

from core import (
    ApiError, auth_context, clock, db, get_body, new_id, now_ts, ok, paginate,
    require_role, round_half_up_cents, touch, validation_error,
)
from services import (
    INVOICE_STATUS_SET, auto_release_contracts, get_or_404,
    projected_invoice_after_confirm, school_derived, serialize_entry,
    serialize_judge, serialize_judge_conflict, serialize_room,
)

bp = Blueprint("routes_b", __name__)

COACH = ["SchoolCoach"]


def _ownership_school(uid, school_id):
    if uid != school_id:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A SchoolCoach may only act on their own school's resources")


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------


@bp.route("/entries", methods=["POST"])
def create_entry():
    uid, role = auth_context()
    require_role(role, COACH)
    body = get_body()
    school_id = body.get("school_id")
    division_id = body.get("division_id")
    _ownership_school(uid, school_id)
    school = db.schools.get(school_id) if school_id else None
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND", 404, "school_id does not exist")
    div = db.divisions.get(division_id) if division_id else None
    if div is None:
        raise ApiError("ERR_DIVISION_NOT_FOUND", 404, "division_id does not exist")
    competitor_name = body.get("competitor_name")
    if not isinstance(competitor_name, str) or not competitor_name:
        raise validation_error("competitor_name is required")
    t = db.tournaments.get(div["tournament_id"])
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Entry creation requires tournament REGISTRATION_OPEN")
    school_count = sum(
        1 for e in db.entries.values()
        if e["school_id"] == school["id"] and e["division_id"] == div["id"]
        and e["status"] != "WITHDRAWN"
    )
    if school_count >= div["per_school_entry_cap"]:
        raise ApiError("ERR_SCHOOL_ENTRY_CAP_EXCEEDED", 409,
                       "School's non-WITHDRAWN entry count in the division reached its cap")
    global_count = sum(
        1 for e in db.entries.values()
        if e["division_id"] == div["id"] and e["status"] != "WITHDRAWN"
    )
    if global_count >= div["global_entry_cap"]:
        raise ApiError("ERR_DIVISION_GLOBAL_CAP_REACHED", 409,
                       "Division-wide non-WITHDRAWN entry count reached the global cap")
    if school["tournament_id"] != div["tournament_id"]:
        raise ApiError("ERR_CROSS_TOURNAMENT_REFERENCE", 409,
                       "School and division belong to different tournaments")
    e = {
        "id": new_id(),
        "school_id": school["id"],
        "division_id": div["id"],
        "competitor_name": competitor_name,
        "status": "REGISTERED",
        "wins": 0,
        "losses": 0,
        "speaker_points_raw": 0,
        "speaker_points_adjusted": 0,
        "rank_points_raw": 0,
        "rank_points_adjusted": 0,
        "opponent_strength": 0,
        "prelim_rank": None,
        "has_received_bye": False,
        "seed": None,
        "final_placement": None,
        "qualification_points": None,
        "fee_charged_cents": 0,
        "_first_places": 0,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.entries[e["id"]] = e
    return ok(serialize_entry(e), 201)


@bp.route("/entries", methods=["GET"])
def list_entries():
    auth_context()
    items = list(db.entries.values())
    sid = request.args.get("school_id")
    did = request.args.get("division_id")
    status = request.args.get("status")
    if sid:
        items = [e for e in items if e["school_id"] == sid]
    if did:
        items = [e for e in items if e["division_id"] == did]
    if status:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: e["created_at"])
    data, meta = paginate(items, serialize_entry)
    return ok(data, 200, meta)


@bp.route("/entries/<eid>", methods=["GET"])
def get_entry(eid):
    auth_context()
    return ok(serialize_entry(get_or_404("entries", eid, "ERR_ENTRY_NOT_FOUND")), 200)


def _confirm_fee(t):
    base = t["entry_fee_cents"]
    if t["late_fee_starts_at"] is not None and clock.current >= t["late_fee_starts_at"]:
        pct = Decimal(str(t["late_fee_surcharge_pct"]))
        return round_half_up_cents(Decimal(base) * (Decimal(1) + pct))
    return base


@bp.route("/entries/<eid>/confirm", methods=["POST"])
def confirm_entry(eid):
    uid, role = auth_context()
    require_role(role, COACH)
    entry = db.entries.get(eid)
    if entry is not None:
        _ownership_school(uid, entry["school_id"])
    if entry is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND", 404, "Entry id does not exist")
    school = db.schools.get(entry["school_id"])
    div = db.divisions.get(entry["division_id"])
    t = db.tournaments.get(div["tournament_id"]) if div else None
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Entry confirm requires tournament REGISTRATION_OPEN")
    if entry["status"] not in ("REGISTERED", "WITHDRAWN"):
        raise ApiError("ERR_ENTRY_INVALID_STATE", 409,
                       "Entry confirm requires status REGISTERED or WITHDRAWN")
    fee = _confirm_fee(t)
    if school and school["credit_limit_cents"] is not None:
        projected = projected_invoice_after_confirm(school, fee)
        if projected > school["credit_limit_cents"]:
            raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402,
                           "Projected invoice balance would exceed the school's credit limit")
    entry["status"] = "CONFIRMED"
    entry["fee_charged_cents"] = fee
    touch(entry)
    if school:
        touch(school)
    touch(t)
    return ok(serialize_entry(entry), 200)


@bp.route("/entries/<eid>/withdraw", methods=["POST"])
def withdraw_entry(eid):
    uid, role = auth_context()
    require_role(role, COACH)
    entry = db.entries.get(eid)
    if entry is not None:
        _ownership_school(uid, entry["school_id"])
    if entry is None:
        raise ApiError("ERR_ENTRY_NOT_FOUND", 404, "Entry id does not exist")
    school = db.schools.get(entry["school_id"])
    div = db.divisions.get(entry["division_id"])
    t = db.tournaments.get(div["tournament_id"]) if div else None
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Entry withdrawal requires tournament REGISTRATION_OPEN")
    if entry["status"] != "CONFIRMED":
        raise ApiError("ERR_ENTRY_INVALID_STATE", 409,
                       "Entry withdrawal requires status CONFIRMED")
    entry["status"] = "WITHDRAWN"
    touch(entry)
    # Cascade link 1: school counts/obligation recompute (live) + version bump.
    if school:
        touch(school)
        # Cascade link 2: surplus hired coverage auto-release (most recent first).
        auto_release_contracts(school)
        # Cascade link 3: contract fee changes feed invoice recomputation.
        touch(school)
    touch(t)
    return ok(serialize_entry(entry), 200)


# ---------------------------------------------------------------------------
# Judges
# ---------------------------------------------------------------------------


@bp.route("/judges", methods=["POST"])
def create_judge():
    uid, role = auth_context()
    require_role(role, ["SchoolCoach", "TournamentDirector"])
    body = get_body()
    tournament_id = body.get("tournament_id")
    school_id = body.get("school_id")
    if role == "SchoolCoach":
        _ownership_school(uid, school_id)
    t = db.tournaments.get(tournament_id) if tournament_id else None
    if t is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND", 404, "tournament_id does not exist")
    school = db.schools.get(school_id) if school_id else None
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND", 404, "school_id does not exist")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise validation_error("name is required")
    if school["tournament_id"] != t["id"]:
        raise ApiError("ERR_CROSS_TOURNAMENT_REFERENCE", 409,
                       "School and tournament references cross tournaments")
    j = {
        "id": new_id(),
        "tournament_id": t["id"],
        "school_id": school["id"],
        "name": name,
        "judge_type": "SCHOOL_PROVIDED",
        "status": "REGISTERED",
        "commitment_rounds": 0,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.judges[j["id"]] = j
    return ok(serialize_judge(j), 201)


@bp.route("/judges", methods=["GET"])
def list_judges():
    auth_context()
    items = list(db.judges.values())
    tid = request.args.get("tournament_id")
    sid = request.args.get("school_id")
    jtype = request.args.get("judge_type")
    status = request.args.get("status")
    if tid:
        items = [j for j in items if j["tournament_id"] == tid]
    if sid:
        items = [j for j in items if j["school_id"] == sid]
    if jtype:
        items = [j for j in items if j["judge_type"] == jtype]
    if status:
        items = [j for j in items if j["status"] == status]
    items.sort(key=lambda j: j["created_at"])
    data, meta = paginate(items, serialize_judge)
    return ok(data, 200, meta)


@bp.route("/judges/<jid>", methods=["GET"])
def get_judge(jid):
    auth_context()
    return ok(serialize_judge(get_or_404("judges", jid, "ERR_JUDGE_NOT_FOUND")), 200)


@bp.route("/judges/<jid>/commit", methods=["POST"])
def commit_judge(jid):
    uid, role = auth_context()
    require_role(role, COACH)
    j = db.judges.get(jid)
    if j is not None:
        _ownership_school(uid, j["school_id"])
    if j is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", 404, "Judge id does not exist")
    t = db.tournaments.get(j["tournament_id"])
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Judge commit requires tournament REGISTRATION_OPEN")
    if j["status"] != "REGISTERED":
        raise ApiError("ERR_JUDGE_INVALID_STATE", 409,
                       "Judge commit requires status REGISTERED")
    body = get_body()
    rounds = body.get("commitment_rounds")
    if (not isinstance(rounds, int) or isinstance(rounds, bool)
            or rounds < 1 or rounds > t["prelim_round_count"]):
        raise ApiError("ERR_COMMITMENT_ROUNDS_INVALID", 422,
                       "commitment_rounds must be in [1, prelim_round_count]")
    j["status"] = "COMMITTED"
    j["commitment_rounds"] = rounds
    touch(j)
    school = db.schools.get(j["school_id"])
    if school:
        touch(school)
    touch(t)
    return ok(serialize_judge(j), 200)


@bp.route("/judges/<jid>/withdraw", methods=["POST"])
def withdraw_judge(jid):
    uid, role = auth_context()
    require_role(role, COACH)
    j = db.judges.get(jid)
    if j is not None:
        _ownership_school(uid, j["school_id"])
    if j is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", 404, "Judge id does not exist")
    t = db.tournaments.get(j["tournament_id"])
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "Judge withdrawal requires tournament REGISTRATION_OPEN")
    if j["status"] not in ("REGISTERED", "COMMITTED"):
        raise ApiError("ERR_JUDGE_INVALID_STATE", 409,
                       "Judge withdrawal requires status REGISTERED or COMMITTED")
    j["status"] = "WITHDRAWN"
    touch(j)
    school = db.schools.get(j["school_id"])
    if school:
        touch(school)
    touch(t)
    return ok(serialize_judge(j), 200)


# ---------------------------------------------------------------------------
# Judge conflicts
# ---------------------------------------------------------------------------


@bp.route("/judge-conflicts", methods=["POST"])
def create_judge_conflict():
    uid, role = auth_context()
    require_role(role, ["SchoolCoach", "TabStaff"])
    body = get_body()
    judge_id = body.get("judge_id")
    school_id = body.get("school_id")
    if role == "SchoolCoach":
        _ownership_school(uid, school_id)
    j = db.judges.get(judge_id) if judge_id else None
    if j is None:
        raise ApiError("ERR_JUDGE_NOT_FOUND", 404, "judge_id does not exist")
    school = db.schools.get(school_id) if school_id else None
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND", 404, "school_id does not exist")
    if j["tournament_id"] != school["tournament_id"]:
        raise ApiError("ERR_CROSS_TOURNAMENT_REFERENCE", 409,
                       "Judge and school belong to different tournaments")
    reason = body.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise validation_error("reason must be a string")
    jc = {
        "id": new_id(),
        "judge_id": j["id"],
        "school_id": school["id"],
        "reason": reason,
        "created_at": now_ts(),
    }
    db.judge_conflicts[jc["id"]] = jc
    return ok(serialize_judge_conflict(jc), 201)


@bp.route("/judge-conflicts", methods=["GET"])
def list_judge_conflicts():
    auth_context()
    items = list(db.judge_conflicts.values())
    jid = request.args.get("judge_id")
    sid = request.args.get("school_id")
    if jid:
        items = [c for c in items if c["judge_id"] == jid]
    if sid:
        items = [c for c in items if c["school_id"] == sid]
    items.sort(key=lambda c: c["created_at"])
    data, meta = paginate(items, serialize_judge_conflict)
    return ok(data, 200, meta)


@bp.route("/judge-conflicts/<cid>", methods=["GET"])
def get_judge_conflict(cid):
    auth_context()
    return ok(
        serialize_judge_conflict(
            get_or_404("judge_conflicts", cid, "ERR_JUDGE_CONFLICT_NOT_FOUND")
        ),
        200,
    )


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


@bp.route("/rooms", methods=["POST"])
def create_room():
    _, role = auth_context()
    require_role(role, ["TournamentDirector"])
    body = get_body()
    tournament_id = body.get("tournament_id")
    t = db.tournaments.get(tournament_id) if tournament_id else None
    if t is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND", 404, "tournament_id does not exist")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise validation_error("name is required")
    capacity = body.get("capacity", 30)
    if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
        raise validation_error("capacity must be an integer >= 1")
    r = {
        "id": new_id(),
        "tournament_id": t["id"],
        "name": name,
        "capacity": capacity,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.rooms[r["id"]] = r
    return ok(serialize_room(r), 201)


@bp.route("/rooms", methods=["GET"])
def list_rooms():
    auth_context()
    items = list(db.rooms.values())
    tid = request.args.get("tournament_id")
    if tid:
        items = [r for r in items if r["tournament_id"] == tid]
    items.sort(key=lambda r: r["created_at"])
    data, meta = paginate(items, serialize_room)
    return ok(data, 200, meta)


@bp.route("/rooms/<rid>", methods=["GET"])
def get_room(rid):
    auth_context()
    return ok(serialize_room(get_or_404("rooms", rid, "ERR_ROOM_NOT_FOUND")), 200)
