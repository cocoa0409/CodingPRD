"""Routes: tournaments lifecycle, logical clock, schools, divisions."""
from flask import Blueprint

from core import (
    ApiError, auth_context, clock, db, fmt_dt, get_body, new_id, now_ts, ok,
    paginate, parse_dt, require_role, touch, validation_error,
)
from services import (
    DEBATE_CODES, SPEECH_CODES, COMPETITION_STATUS_SET, award_qualification_points,
    determine_breaks_service, division_entries, get_or_404, resolve_champions,
    school_derived, serialize_division, serialize_entry, serialize_school,
    serialize_tournament, standings_order, tournament_divisions, tournament_schools,
)

bp = Blueprint("routes_a", __name__)

ALL_ROLES = ["TournamentDirector", "TabStaff", "SchoolCoach", "Judge"]
TD = ["TournamentDirector"]


def get_tournament(tid):
    return get_or_404("tournaments", tid, "ERR_TOURNAMENT_NOT_FOUND")


def get_school(sid):
    return get_or_404("schools", sid, "ERR_SCHOOL_NOT_FOUND")


def get_division(did):
    return get_or_404("divisions", did, "ERR_DIVISION_NOT_FOUND")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth_context()
    require_role(role, TD)
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not to_iso:
        raise validation_error("to_iso8601 is required")
    try:
        dt = parse_dt(to_iso)
    except (ValueError, TypeError):
        raise validation_error("to_iso8601 must be a valid ISO-8601 datetime")
    clock.current = dt
    return ok({"current_utc": fmt_dt(clock.current)}, 200)


# ---------------------------------------------------------------------------
# Tournaments
# ---------------------------------------------------------------------------


@bp.route("/tournaments", methods=["POST"])
def create_tournament():
    _, role = auth_context()
    require_role(role, TD)
    body = get_body()
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise validation_error("name is required")
    try:
        opens_at = parse_dt(body.get("registration_opens_at"))
        locks_at = parse_dt(body.get("registration_locks_at"))
    except (ValueError, TypeError):
        raise validation_error("registration_opens_at and registration_locks_at are required ISO-8601 datetimes")

    prc = body.get("prelim_round_count", 4)
    if not isinstance(prc, int) or isinstance(prc, bool) or prc < 2 or prc > 6:
        raise validation_error("prelim_round_count must be an integer in [2,6]")
    fee = body.get("entry_fee_cents", 2500)
    if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
        raise validation_error("entry_fee_cents must be an integer >= 0")
    staff = body.get("tournament_staff_count", 10)
    if not isinstance(staff, int) or isinstance(staff, bool) or staff < 0:
        raise validation_error("tournament_staff_count must be an integer >= 0")
    late_starts = body.get("late_fee_starts_at")
    if late_starts is not None:
        try:
            late_starts = parse_dt(late_starts)
        except (ValueError, TypeError):
            raise validation_error("late_fee_starts_at must be an ISO-8601 datetime")
    pct = body.get("late_fee_surcharge_pct", 0.15)
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        raise validation_error("late_fee_surcharge_pct must be a number")

    t = {
        "id": new_id(),
        "name": name,
        "status": "DRAFT",
        "results_visibility": "HIDDEN",
        "registration_opens_at": opens_at,
        "registration_locks_at": locks_at,
        "prelim_round_count": prc,
        "entry_fee_cents": fee,
        "tournament_staff_count": staff,
        "late_fee_starts_at": late_starts,
        "late_fee_surcharge_pct": pct,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.tournaments[t["id"]] = t
    return ok(serialize_tournament(t), 201)


@bp.route("/tournaments", methods=["GET"])
def list_tournaments():
    auth_context()
    items = sorted(db.tournaments.values(), key=lambda t: t["created_at"])
    data, meta = paginate(items, serialize_tournament)
    return ok(data, 200, meta)


@bp.route("/tournaments/<tid>", methods=["GET"])
def get_tournament_route(tid):
    auth_context()
    return ok(serialize_tournament(get_tournament(tid)), 200)


@bp.route("/tournaments/<tid>/open-registration", methods=["POST"])
def open_registration(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "DRAFT":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "open-registration requires status DRAFT")
    if clock.current < t["registration_opens_at"]:
        raise ApiError("ERR_REGISTRATION_WINDOW_NOT_OPEN", 409,
                       "current logical UTC is before registration_opens_at")
    t["status"] = "REGISTRATION_OPEN"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/lock-registration", methods=["POST"])
def lock_registration(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "lock-registration requires status REGISTRATION_OPEN")
    body = get_body()
    expected = body.get("expected_tournament_version")
    if not isinstance(expected, int) or expected != t["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_tournament_version does not match the tournament's current version")
    for s in tournament_schools(t["id"]):
        d = school_derived(s)
        if s["status"] != "CONFIRMED" or d["obligation_status"] != "SATISFIED":
            raise ApiError("ERR_SCHOOLS_NOT_LOCK_READY", 409,
                           "Every school must be CONFIRMED and SATISFIED to lock registration")
    if clock.current < t["registration_locks_at"]:
        raise ApiError("ERR_REGISTRATION_WINDOW_CLOSED", 409,
                       "current logical UTC is before registration_locks_at")
    t["status"] = "REGISTRATION_LOCKED"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/start-prelims", methods=["POST"])
def start_prelims(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "REGISTRATION_LOCKED":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "start-prelims requires status REGISTRATION_LOCKED")
    for div in tournament_divisions(t["id"]):
        confirmed = division_entries(div["id"], {"CONFIRMED"})
        if len(confirmed) >= 2:
            has_scheduled_prelim = any(
                r for r in db.rounds.values()
                if r["division_id"] == div["id"] and r["kind"] == "PRELIM" and r["status"] == "SCHEDULED"
            )
            if not has_scheduled_prelim:
                raise ApiError("ERR_ROUNDS_NOT_SCHEDULED", 409,
                               "Division %s lacks a SCHEDULED PRELIM round" % div["id"])
    for div in tournament_divisions(t["id"]):
        for e in division_entries(div["id"], {"CONFIRMED"}):
            e["status"] = "COMPETING"
            touch(e)
    t["status"] = "PRELIMS_ACTIVE"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/start-elims", methods=["POST"])
def start_elims(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "PRELIMS_ACTIVE":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "start-elims requires status PRELIMS_ACTIVE")
    for r in db.rounds.values():
        div = db.divisions.get(r["division_id"])
        if not div or div["tournament_id"] != t["id"]:
            continue
        if r["kind"] == "PRELIM" and r["status"] != "TABULATED":
            raise ApiError("ERR_ROUNDS_NOT_TABULATED", 409,
                           "Every PRELIM round must be TABULATED to start elims")
    for div in tournament_divisions(t["id"]):
        competing = len(division_entries(div["id"], COMPETITION_STATUS_SET))
        if competing >= 2 and not div["bracket_size"]:
            raise ApiError("ERR_BREAKS_NOT_DETERMINED", 409,
                           "Division %s has no bracket_size set" % div["id"])
    t["status"] = "ELIMS_ACTIVE"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/complete", methods=["POST"])
def complete_tournament(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "ELIMS_ACTIVE":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "complete requires status ELIMS_ACTIVE")
    for r in db.rounds.values():
        div = db.divisions.get(r["division_id"])
        if not div or div["tournament_id"] != t["id"]:
            continue
        if r["kind"] == "ELIM" and r["status"] != "TABULATED":
            raise ApiError("ERR_ROUNDS_NOT_TABULATED", 409,
                           "Every ELIM round must be TABULATED to complete the tournament")
    resolve_champions(t)
    t["status"] = "COMPLETED"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/publish-results", methods=["POST"])
def publish_results(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["status"] != "COMPLETED" or t["results_visibility"] != "HIDDEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "publish-results requires status COMPLETED and results_visibility HIDDEN")
    award_qualification_points(t)
    t["results_visibility"] = "PUBLISHED"
    touch(t)
    return ok(serialize_tournament(t), 200)


@bp.route("/tournaments/<tid>/certify-qualifications", methods=["POST"])
def certify_qualifications(tid):
    _, role = auth_context()
    require_role(role, TD)
    t = get_tournament(tid)
    if t["results_visibility"] != "PUBLISHED":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "certify-qualifications requires results_visibility PUBLISHED")
    for s in tournament_schools(t["id"]):
        for c in db.contracts.values():
            if c["school_id"] == s["id"] and c["status"] not in ("PAID", "CANCELLED"):
                raise ApiError("ERR_UNPAID_CONTRACTS_REMAIN", 409,
                               "Hired-judge contracts remain outside {PAID, CANCELLED}")
    t["results_visibility"] = "CERTIFIED"
    touch(t)
    return ok(serialize_tournament(t), 200)


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------


@bp.route("/schools", methods=["POST"])
def create_school():
    _, role = auth_context()
    require_role(role, TD)
    body = get_body()
    tid = body.get("tournament_id")
    t = get_or_404("tournaments", tid, "ERR_TOURNAMENT_NOT_FOUND") if tid else None
    if t is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND", 404, "tournament_id does not exist")
    name = body.get("name")
    if not isinstance(name, str) or not name:
        raise validation_error("name is required")
    credit = body.get("credit_limit_cents")
    if credit is not None and (not isinstance(credit, int) or isinstance(credit, bool)):
        raise validation_error("credit_limit_cents must be an integer")
    s = {
        "id": new_id(),
        "tournament_id": t["id"],
        "name": name,
        "status": "REGISTERED",
        "credit_limit_cents": credit,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.schools[s["id"]] = s
    return ok(serialize_school(s), 201)


@bp.route("/schools", methods=["GET"])
def list_schools():
    auth_context()
    items = list(db.schools.values())
    tid = None
    from flask import request
    tid = request.args.get("tournament_id")
    status = request.args.get("status")
    if tid:
        items = [s for s in items if s["tournament_id"] == tid]
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["created_at"])
    data, meta = paginate(items, serialize_school)
    return ok(data, 200, meta)


@bp.route("/schools/<sid>", methods=["GET"])
def get_school_route(sid):
    auth_context()
    return ok(serialize_school(get_school(sid)), 200)


@bp.route("/schools/<sid>/confirm", methods=["POST"])
def confirm_school(sid):
    uid, role = auth_context()
    require_role(role, ["SchoolCoach"])
    if uid != sid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A SchoolCoach may only confirm their own school")
    s = get_school(sid)
    t = db.tournaments.get(s["tournament_id"])
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "School confirmation requires tournament REGISTRATION_OPEN")
    if s["status"] != "REGISTERED":
        raise ApiError("ERR_SCHOOL_INVALID_STATE", 409,
                       "School confirm requires status REGISTERED")
    d = school_derived(s)
    if d["shortfall_rounds"] != 0:
        raise ApiError("ERR_SCHOOL_OBLIGATION_DEFICIENT", 409,
                       "School judging obligation is not fully covered")
    s["status"] = "CONFIRMED"
    touch(s)
    touch(t)
    return ok(serialize_school(s), 200)


@bp.route("/schools/<sid>/unconfirm", methods=["POST"])
def unconfirm_school(sid):
    uid, role = auth_context()
    require_role(role, ["SchoolCoach"])
    if uid != sid:
        raise ApiError("ERR_RESOURCE_OWNERSHIP_MISMATCH", 403,
                       "A SchoolCoach may only unconfirm their own school")
    s = get_school(sid)
    t = db.tournaments.get(s["tournament_id"])
    if not t or t["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "School unconfirm requires tournament REGISTRATION_OPEN")
    if s["status"] != "CONFIRMED":
        raise ApiError("ERR_SCHOOL_INVALID_STATE", 409,
                       "School unconfirm requires status CONFIRMED")
    s["status"] = "REGISTERED"
    touch(s)
    touch(t)
    return ok(serialize_school(s), 200)


# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------


@bp.route("/divisions", methods=["POST"])
def create_division():
    _, role = auth_context()
    require_role(role, TD)
    body = get_body()
    tid = body.get("tournament_id")
    t = db.tournaments.get(tid) if tid else None
    if t is None:
        raise ApiError("ERR_TOURNAMENT_NOT_FOUND", 404, "tournament_id does not exist")
    event_type = body.get("event_type")
    if event_type not in ("DEBATE", "SPEECH"):
        raise validation_error("event_type must be DEBATE or SPEECH")
    event_code = body.get("event_code")
    family = DEBATE_CODES if event_type == "DEBATE" else SPEECH_CODES
    if event_code not in family:
        raise ApiError("ERR_EVENT_CODE_TYPE_MISMATCH", 422,
                       "event_code does not belong to the event_type family")
    division = body.get("division")
    if division not in ("VARSITY", "JV", "NOVICE"):
        raise validation_error("division must be VARSITY, JV, or NOVICE")
    per_cap = body.get("per_school_entry_cap", 4)
    if not isinstance(per_cap, int) or isinstance(per_cap, bool) or per_cap < 1:
        raise validation_error("per_school_entry_cap must be an integer >= 1")
    global_cap = body.get("global_entry_cap", 32)
    if not isinstance(global_cap, int) or isinstance(global_cap, bool) or global_cap < 1:
        raise validation_error("global_entry_cap must be an integer >= 1")
    d = {
        "id": new_id(),
        "tournament_id": t["id"],
        "event_type": event_type,
        "event_code": event_code,
        "division": division,
        "per_school_entry_cap": per_cap,
        "global_entry_cap": global_cap,
        "bracket_size": None,
        "created_at": now_ts(),
        "updated_at": now_ts(),
        "version": 1,
    }
    db.divisions[d["id"]] = d
    return ok(serialize_division(d), 201)


@bp.route("/divisions", methods=["GET"])
def list_divisions():
    auth_context()
    from flask import request
    items = list(db.divisions.values())
    tid = request.args.get("tournament_id")
    etype = request.args.get("event_type")
    if tid:
        items = [d for d in items if d["tournament_id"] == tid]
    if etype:
        items = [d for d in items if d["event_type"] == etype]
    items.sort(key=lambda d: d["created_at"])
    data, meta = paginate(items, serialize_division)
    return ok(data, 200, meta)


@bp.route("/divisions/<did>", methods=["GET"])
def get_division_route(did):
    auth_context()
    return ok(serialize_division(get_division(did)), 200)


@bp.route("/divisions/<did>/determine-breaks", methods=["POST"])
def determine_breaks(did):
    _, role = auth_context()
    require_role(role, ["TabStaff"])
    d = get_division(did)
    t = db.tournaments.get(d["tournament_id"])
    if not t or t["status"] != "PRELIMS_ACTIVE":
        raise ApiError("ERR_TOURNAMENT_PHASE_FORBIDDEN", 409,
                       "determine-breaks requires tournament PRELIMS_ACTIVE")
    for r in db.rounds.values():
        if r["division_id"] == d["id"] and r["kind"] == "PRELIM" and r["status"] != "TABULATED":
            raise ApiError("ERR_ROUNDS_NOT_TABULATED", 409,
                           "Every PRELIM round of the division must be TABULATED")
    determine_breaks_service(d, t)
    return ok(serialize_division(d), 200)


@bp.route("/divisions/<did>/standings", methods=["GET"])
def division_standings(did):
    auth_context()
    d = get_division(did)
    entries = division_entries(d["id"], COMPETITION_STATUS_SET)
    entries.sort(key=lambda e: (e["prelim_rank"] is None,
                                e["prelim_rank"] if e["prelim_rank"] is not None else 0,
                                e["created_at"]))
    data, meta = paginate(entries, serialize_entry)
    return ok(data, 200, meta)
