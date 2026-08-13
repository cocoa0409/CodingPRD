"""Division and Team endpoints (PRD §3.4, §3.5)."""

from flask import Blueprint, request

import services as svc
from db import STORE, base_entity, touch
from errors import (ERR_DIVISION_BELOW_MIN_TEAMS, ERR_DIVISION_NOT_OPEN,
                    ERR_ROSTER_TOO_SMALL, already_terminal, invalid_state,
                    posture_forbids, raise_err)
from listing import list_response
from middleware import (forbid, get_body, opt_str, req_int, req_str,
                        require_any_authenticated, require_roles)
from response import ok

bp = Blueprint("divisions", __name__, url_prefix="/api/v1")


# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------

@bp.post("/events/<id>/divisions")
def create_division(id):
    require_roles("CommissionAdmin")
    e = svc.get_or_404(STORE.events, id, "event")
    data = get_body()
    name = req_str(data, "name")
    team_cap = req_int(data, "team_cap", lo=2)
    min_teams = req_int(data, "min_teams", lo=2)
    registration_fee_cents = req_int(data, "registration_fee_cents", lo=0)
    if min_teams > team_cap:
        from errors import ApiError, ERR_VALIDATION
        raise ApiError(*ERR_VALIDATION, "min_teams must be <= team_cap.")
    d = base_entity()
    d.update({
        "event_id": e["id"],
        "name": name,
        "team_cap": team_cap,
        "min_teams": min_teams,
        "registration_fee_cents": registration_fee_cents,
        "status": "OPEN",
        "bracket_size": None,
        "total_rounds": None,
    })
    STORE.divisions[d["id"]] = d
    return ok(svc.ser_division(d), status=201)


@bp.get("/events/<id>/divisions")
def list_divisions(id):
    require_any_authenticated()
    e = svc.get_or_404(STORE.events, id, "event")
    items = svc.divisions_of_event(e["id"])
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["name"], d["_seq"]))
    return list_response(items, svc.ser_division)


@bp.get("/divisions/<id>")
def get_division(id):
    require_any_authenticated()
    d = svc.get_or_404(STORE.divisions, id, "division")
    return ok(svc.ser_division(d))


@bp.post("/divisions/<id>/lock-seeding")
def lock_seeding(id):
    require_roles("CommissionAdmin")
    d = svc.get_or_404(STORE.divisions, id, "division")
    e = svc.get_or_404(STORE.events, d["event_id"], "event")
    if e["posture"] != "REGISTRATION_OPEN":
        posture_forbids("Seeding may be locked only while registration is open.")
    if d["status"] in svc.DIVISION_TERMINAL:
        already_terminal("division")
    if d["status"] != "OPEN":
        raise_err(ERR_DIVISION_NOT_OPEN, "Only an OPEN division can lock seeding.")
    if svc.division_eligible_count(d) < d["min_teams"]:
        raise_err(ERR_DIVISION_BELOW_MIN_TEAMS,
                  "eligible_team_count is below the division's min_teams.")
    svc.assign_seeds(d)  # strength_rating DESC, created_at ASC -> seed 1..N
    for t in svc.teams_of_division(d["id"]):
        if t["status"] in ("ENTERED", "WAITLISTED", "ROSTER_SUBMITTED"):
            t["status"] = "WITHDRAWN"
            touch(t)
    d["status"] = "SEEDING_LOCKED"
    touch(d)
    return ok(svc.ser_division(d))


@bp.post("/divisions/<id>/publish-bracket")
def publish_bracket(id):
    require_roles("CommissionAdmin")
    d = svc.get_or_404(STORE.divisions, id, "division")
    e = svc.get_or_404(STORE.events, d["event_id"], "event")
    if e["posture"] not in ("REGISTRATION_OPEN", "COMPETITION_SETUP"):
        posture_forbids("Bracket publication requires REGISTRATION_OPEN or COMPETITION_SETUP posture.")
    if d["status"] in svc.DIVISION_TERMINAL:
        already_terminal("division")
    if d["status"] != "SEEDING_LOCKED":
        raise_err(ERR_DIVISION_NOT_OPEN, "Only a SEEDING_LOCKED division can publish its bracket.")
    svc.publish_bracket(d)
    d["status"] = "BRACKET_PUBLISHED"
    touch(d)
    return ok(svc.ser_division(d))


@bp.get("/divisions/<id>/teams")
def list_division_teams(id):
    require_any_authenticated()
    d = svc.get_or_404(STORE.divisions, id, "division")
    items = svc.teams_of_division(d["id"])
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    # seed_number ASC nulls last, strength_rating DESC, created_at ASC
    items.sort(key=lambda t: (t["seed_number"] is None,
                              t["seed_number"] if t["seed_number"] is not None else 0,
                              -t["strength_rating"],
                              t["created_at"], t["_seq"]))
    return list_response(items, svc.ser_team)


@bp.get("/divisions/<id>/matches")
def list_division_matches(id):
    require_any_authenticated()
    d = svc.get_or_404(STORE.divisions, id, "division")
    items = svc.matches_of_division(d["id"])
    status = request.args.get("status")
    if status is not None:
        items = [m for m in items if m["status"] == status]
    round_number = request.args.get("round_number")
    if round_number is not None:
        try:
            rn = int(round_number)
        except (TypeError, ValueError):
            from errors import ApiError, ERR_VALIDATION
            raise ApiError(*ERR_VALIDATION, "round_number must be an integer.")
        items = [m for m in items if m["round_number"] == rn]
    items.sort(key=lambda m: (m["round_number"], m["bracket_slot"]))
    return list_response(items, svc.ser_match)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

@bp.post("/divisions/<id>/teams")
def create_team(id):
    require_roles("CommissionAdmin")
    d = svc.get_or_404(STORE.divisions, id, "division")
    e = svc.get_or_404(STORE.events, d["event_id"], "event")
    data = get_body()
    name = req_str(data, "name")
    contact_email = req_str(data, "contact_email")
    strength_rating = req_int(data, "strength_rating", lo=1, hi=100)
    if e["posture"] != "REGISTRATION_OPEN":
        posture_forbids("Team registration requires REGISTRATION_OPEN posture.")
    if d["status"] in svc.DIVISION_TERMINAL:
        already_terminal("division")
    if d["status"] != "OPEN":
        raise_err(ERR_DIVISION_NOT_OPEN, "Teams may register only while the division is OPEN.")
    entered = svc.division_entered_count(d)
    status = "ENTERED" if entered < d["team_cap"] else "WAITLISTED"
    t = base_entity()
    t.update({
        "division_id": d["id"],
        "name": name,
        "contact_email": contact_email,
        "strength_rating": strength_rating,
        "roster_player_count": None,
        "status": status,
        "seed_number": None,
    })
    STORE.teams[t["id"]] = t
    return ok(svc.ser_team(t), status=201)


@bp.get("/teams/<id>")
def get_team(id):
    require_any_authenticated()
    t = svc.get_or_404(STORE.teams, id, "team")
    return ok(svc.ser_team(t))


def _get_team_scoped(id, uid, role):
    """TeamRep ownership: X-User-ID must equal the team id (checked pre-load)."""
    if role == "TeamRep":
        forbid(uid != id, "TeamRep may act only on their own team.")
    return svc.get_or_404(STORE.teams, id, "team")


@bp.post("/teams/<id>/roster")
def submit_roster(id):
    uid, role = require_roles("TeamRep")
    t = _get_team_scoped(id, uid, role)
    data = get_body()
    count = data.get("roster_player_count")
    if not isinstance(count, int) or isinstance(count, bool):
        from errors import ApiError, ERR_VALIDATION
        raise ApiError(*ERR_VALIDATION, "roster_player_count is required and must be an integer.")
    d = svc.get_or_404(STORE.divisions, t["division_id"], "division")
    if t["status"] in svc.TEAM_TERMINAL:
        already_terminal("team")
    if d["status"] != "OPEN":
        raise_err(ERR_DIVISION_NOT_OPEN, "The division is not OPEN for roster submission.")
    if t["status"] != "ENTERED":
        invalid_state("Only an ENTERED team can submit its roster.")
    if count < 7:
        raise_err(ERR_ROSTER_TOO_SMALL, "The roster must field at least 7 players.")
    t["roster_player_count"] = count
    t["status"] = "ROSTER_SUBMITTED"
    touch(t)
    return ok(svc.ser_team(t))


@bp.post("/teams/<id>/verify-eligibility")
def verify_eligibility(id):
    require_roles("CommissionAdmin")
    t = svc.get_or_404(STORE.teams, id, "team")
    d = svc.get_or_404(STORE.divisions, t["division_id"], "division")
    if t["status"] in svc.TEAM_TERMINAL:
        already_terminal("team")
    if d["status"] != "OPEN":
        raise_err(ERR_DIVISION_NOT_OPEN, "The division is not OPEN for eligibility verification.")
    if t["status"] != "ROSTER_SUBMITTED":
        invalid_state("Only a ROSTER_SUBMITTED team can be marked eligible.")
    t["status"] = "ELIGIBLE"
    touch(t)
    return ok(svc.ser_team(t))


@bp.post("/teams/<id>/check-in")
def check_in_team(id):
    uid, role = require_roles("CommissionAdmin", "TeamRep")
    t = _get_team_scoped(id, uid, role)
    e = svc.event_of_team(t)
    if e is not None and e["posture"] != "LIVE":
        posture_forbids("Team check-in requires LIVE posture.")
    if t["status"] in svc.TEAM_TERMINAL:
        already_terminal("team")
    if t["status"] != "ELIGIBLE":
        invalid_state("Only an ELIGIBLE team can check in.")
    t["status"] = "CHECKED_IN"
    touch(t)
    return ok(svc.ser_team(t))


@bp.post("/teams/<id>/withdraw")
def withdraw_team(id):
    uid, role = require_roles("CommissionAdmin", "TeamRep")
    t = _get_team_scoped(id, uid, role)
    if t["status"] in svc.TEAM_TERMINAL:
        already_terminal("team")
    d = svc.get_or_404(STORE.divisions, t["division_id"], "division")
    if t["status"] not in ("ENTERED", "WAITLISTED", "ROSTER_SUBMITTED", "ELIGIBLE"):
        invalid_state("This team cannot be withdrawn from its current status.")
    if t["status"] == "ELIGIBLE" and d["status"] != "OPEN":
        raise_err(ERR_DIVISION_NOT_OPEN,
                  "An eligible team may withdraw manually only while the division is OPEN.")
    was = t["status"]
    t["status"] = "WITHDRAWN"
    touch(t)
    # Waitlist promotion: oldest WAITLISTED team (created_at ASC) is promoted
    # when an ENTERED or ELIGIBLE team withdraws while the division is OPEN.
    if was in ("ENTERED", "ELIGIBLE") and d["status"] == "OPEN":
        waiting = [w for w in svc.teams_of_division(d["id"]) if w["status"] == "WAITLISTED"]
        waiting.sort(key=lambda w: (w["created_at"], w["_seq"]))
        if waiting:
            waiting[0]["status"] = "ENTERED"
            touch(waiting[0])
    return ok(svc.ser_team(t))


@bp.post("/teams/<id>/disqualify")
def disqualify_team(id):
    require_roles("CommissionAdmin")
    t = svc.get_or_404(STORE.teams, id, "team")
    data = get_body()
    req_str(data, "reason")
    if t["status"] in svc.TEAM_TERMINAL:
        already_terminal("team")
    if t["status"] not in ("ELIGIBLE", "CHECKED_IN"):
        invalid_state("Only an ELIGIBLE or CHECKED_IN team can be disqualified.")
    was_checked_in = t["status"] == "CHECKED_IN"
    t["status"] = "DISQUALIFIED"
    touch(t)
    for m in svc.matches_of_division(t["division_id"]):
        involved = m["home_team_id"] == t["id"] or m["away_team_id"] == t["id"]
        if not involved:
            continue
        if m["status"] == "PENDING_TEAMS":
            if m["home_team_id"] == t["id"]:
                m["home_team_id"] = None
            else:
                m["away_team_id"] = None
            touch(m)
        elif was_checked_in and m["status"] in ("SCHEDULED", "IN_PROGRESS"):
            opponent = (m["away_team_id"] if m["home_team_id"] == t["id"]
                        else m["home_team_id"])
            svc.release_match_assignments(m, "MATCH_CANCELLED")
            m["status"] = "FORFEITED"
            touch(m)
            svc.apply_match_result(m, opponent)
    return ok(svc.ser_team(t))
