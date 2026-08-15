"""Routes: clock, events, divisions, teams, music, athletes, roster, judges."""
from datetime import timedelta

from flask import g

import calc
import errors
from bidding import (division_complete, initial_allocation, reevaluate,
                     revoke_team_bids)
from bp import bp
from envelope import ok, ok_list
from helpers import (body, get_or_404, opt_int, opt_num, own_team, req_enum,
                     req_int, req_list, req_str, require_roles, req_date_field,
                     req_datetime_field)
from store import (by_created, db, full_years, iso, now, parse_datetime,
                   set_fields, stamp, touch)

ALL_ROLES = ("EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge",
             "MusicCompliance", "EligibilityOfficer", "Spectator")


# ---------------------------------------------------------------------------
# Logical clock (test-driving)
# ---------------------------------------------------------------------------

@bp.post("/api/_clock/set_current_utc")
@require_roles("EventDirector")
def set_clock():
    b = body()
    dt = req_datetime_field(b, "to_iso8601")
    db.clock = dt
    return ok({"current_utc": iso(db.clock)})


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bp.post("/api/events")
@require_roles("EventDirector")
def create_event():
    b = body()
    name = req_str(b, "name")
    venue_name = req_str(b, "venue_name")
    start_date = req_date_field(b, "start_date")
    end_date = req_date_field(b, "end_date")
    age_reference_date = req_date_field(b, "age_reference_date")
    if end_date < start_date:
        raise errors.invalid_input("end_date must be >= start_date")
    rec = stamp({
        "name": name,
        "venue_name": venue_name,
        "start_date": start_date,
        "end_date": end_date,
        "age_reference_date": age_reference_date,
        "status": "DRAFT",
    })
    db.events[rec["id"]] = rec
    return ok(rec, 201)


def _event_or_404(event_id):
    return get_or_404(db.events, event_id, "Event")


def _event_transition(event_id, source, target):
    event = _event_or_404(event_id)
    if event["status"] != source:
        raise errors.conflict(
            "ERR_EVENT_INVALID_STATE",
            f"Event status {event['status']} does not permit this operation")
    set_fields(event, status=target)
    return ok(event)


@bp.get("/api/events/<event_id>")
@require_roles(*ALL_ROLES)
def get_event(event_id):
    return ok(_event_or_404(event_id))


@bp.post("/api/events/<event_id>/open-registration")
@require_roles("EventDirector")
def open_registration(event_id):
    return _event_transition(event_id, "DRAFT", "REGISTRATION_OPEN")


@bp.post("/api/events/<event_id>/close-registration")
@require_roles("EventDirector")
def close_registration(event_id):
    return _event_transition(event_id, "REGISTRATION_OPEN", "REGISTRATION_CLOSED")


@bp.post("/api/events/<event_id>/go-live")
@require_roles("EventDirector")
def go_live(event_id):
    return _event_transition(event_id, "SCHEDULED", "LIVE")


@bp.post("/api/events/<event_id>/finalize")
@require_roles("EventDirector")
def finalize_event(event_id):
    event = _event_or_404(event_id)
    if event["status"] != "LIVE":
        raise errors.conflict("ERR_FINALIZE_BLOCKED",
                              "Event must be LIVE to finalize")
    # Every performance of the event in a terminal state.
    for p in db.performances.values():
        div = db.divisions.get(p["division_id"])
        if div and div["event_id"] == event_id and \
                p["status"] not in ("OFFICIAL", "EXCLUDED", "CANCELLED"):
            raise errors.conflict("ERR_FINALIZE_BLOCKED",
                                  "Non-terminal performances outstanding")
    # No SUBMITTED appeal on any deduction of the event.
    for a in db.appeals.values():
        if a["status"] != "SUBMITTED":
            continue
        ded = db.deductions.get(a["deduction_id"])
        perf = db.performances.get(ded["performance_id"]) if ded else None
        div = db.divisions.get(perf["division_id"]) if perf else None
        if div and div["event_id"] == event_id:
            raise errors.conflict("ERR_FINALIZE_BLOCKED",
                                  "Appeals still SUBMITTED for this event")
    # No OFFERED bid in any division of the event.
    for bid in db.bids.values():
        if bid["status"] != "OFFERED":
            continue
        div = db.divisions.get(bid["division_id"])
        if div and div["event_id"] == event_id:
            raise errors.conflict("ERR_FINALIZE_BLOCKED",
                                  "Bids still OFFERED for this event")
    set_fields(event, status="FINALIZED")
    return ok(event)


@bp.post("/api/events/<event_id>/checkpoint")
@require_roles("EventDirector")
def checkpoint(event_id):
    event = _event_or_404(event_id)
    expired_bids = 0
    expired_orders = 0
    # Expire OFFERED bids whose deadline has passed (strictly before now).
    due_bids = [b for b in db.bids.values()
                if b["status"] == "OFFERED" and b["acceptance_deadline"] < now()
                and (db.divisions.get(b["division_id"]) or {}).get("event_id")
                == event_id]
    for bid in by_created(due_bids):
        set_fields(bid, status="EXPIRED")
        division = db.divisions.get(bid["division_id"])
        if division is not None:
            division["bid_pool_available"] += 1
            touch(division)
            from bidding import reoffer_slot
            reoffer_slot(division, bid["kind"], freed_team_id=bid["team_id"])
        expired_bids += 1
    # Expire HELD ticket orders whose hold has passed.
    due_orders = [o for o in db.ticket_orders.values()
                  if o["status"] == "HELD" and o["hold_expires_at"] < now()
                  and (db.sessions.get(o["session_id"]) or {}).get("event_id")
                  == event_id]
    for order in by_created(due_orders):
        set_fields(order, status="EXPIRED")
        session = db.sessions.get(order["session_id"])
        if session is not None:
            session["seats_held"] -= order["quantity"]
            session["seats_available"] = (session["capacity"]
                                          - session["seats_held"]
                                          - session["seats_sold"])
            touch(session)
        expired_orders += 1
    return ok({"expired_bid_count": expired_bids,
               "expired_order_count": expired_orders})


@bp.post("/api/events/<event_id>/allocate-bids")
@require_roles("EventDirector")
def allocate_bids(event_id):
    event = _event_or_404(event_id)
    b = body()
    expected = req_int(b, "expected_event_version")
    if expected != event["version"]:
        raise errors.stale_version(
            "expected_event_version does not match the event's current version")
    divisions = [d for d in db.divisions.values() if d["event_id"] == event_id]
    for division in divisions:
        if not division_complete(division):
            raise errors.conflict(
                "ERR_FINALIZE_BLOCKED",
                "Every division must be complete before re-running allocation")
    offered_ids = []
    for division in by_created(divisions):
        # Revoke standing OFFERED bids into the pool; ACCEPTED untouched.
        standing = [bd for bd in db.bids.values()
                    if bd["division_id"] == division["id"]
                    and bd["status"] == "OFFERED"]
        for bid in by_created(standing):
            set_fields(bid, status="REVOKED")
            division["bid_pool_available"] += 1
            touch(division)
        initial_allocation(division, offered_ids)
    touch(event)
    return ok({"offered_bid_ids": offered_ids})


# ---------------------------------------------------------------------------
# Divisions
# ---------------------------------------------------------------------------

@bp.post("/api/divisions")
@require_roles("EventDirector")
def create_division():
    b = body()
    event_id = req_str(b, "event_id")
    name = req_str(b, "name")
    category = req_enum(b, "category", ("CHEER", "DANCE"))
    level = req_int(b, "level", lo=1, hi=6)
    min_age = req_int(b, "min_age", lo=0)
    max_age = req_int(b, "max_age", lo=0)
    if max_age < min_age:
        raise errors.invalid_input("max_age must be >= min_age")
    min_athletes = req_int(b, "min_athletes", lo=0)
    max_athletes = req_int(b, "max_athletes", lo=0)
    if max_athletes < min_athletes:
        raise errors.invalid_input("max_athletes must be >= min_athletes")
    routine_time_limit = req_int(b, "routine_time_limit_seconds", lo=1)
    warmup_duration = opt_int(b, "warmup_duration_seconds", 900, lo=1)
    warmup_mats = req_list(b, "warmup_mats")
    for m in warmup_mats:
        if not isinstance(m, str) or not m:
            raise errors.invalid_input("warmup_mats entries must be strings")
    schedule_start_at = req_datetime_field(b, "schedule_start_at")
    judge_ids = req_list(b, "judge_ids")
    if not 3 <= len(judge_ids) <= 9:
        raise errors.invalid_input("judge_ids must contain 3..9 elements")
    for j in judge_ids:
        if not isinstance(j, str):
            raise errors.invalid_input("judge_ids entries must be strings")
    time_rate = opt_num(b, "time_deduction_per_second", 0.5, lo=0)
    safety_points = opt_num(b, "safety_deduction_points", 2.0, lo=0)
    boundary_points = opt_num(b, "boundary_deduction_points", 0.25, lo=0)
    paid_bid_count = opt_int(b, "paid_bid_count", 0, lo=0)
    at_large_bid_count = opt_int(b, "at_large_bid_count", 0, lo=0)
    # Body FK resolution (priority 4)
    get_or_404(db.events, event_id, "Event")
    for j in judge_ids:
        get_or_404(db.judges, j, "Judge")
    rec = stamp({
        "event_id": event_id,
        "name": name,
        "category": category,
        "level": level,
        "min_age": min_age,
        "max_age": max_age,
        "min_athletes": min_athletes,
        "max_athletes": max_athletes,
        "routine_time_limit_seconds": routine_time_limit,
        "warmup_duration_seconds": warmup_duration,
        "warmup_mats": list(warmup_mats),
        "schedule_start_at": schedule_start_at,
        "judge_ids": list(judge_ids),
        "time_deduction_per_second": time_rate,
        "safety_deduction_points": safety_points,
        "boundary_deduction_points": boundary_points,
        "paid_bid_count": paid_bid_count,
        "at_large_bid_count": at_large_bid_count,
        "bid_pool_available": paid_bid_count + at_large_bid_count,
        "scheduled": False,
    })
    db.divisions[rec["id"]] = rec
    return ok(rec, 201)


def _division_or_404(division_id):
    return get_or_404(db.divisions, division_id, "Division")


@bp.get("/api/divisions/<division_id>")
@require_roles(*ALL_ROLES)
def get_division(division_id):
    return ok(_division_or_404(division_id))


@bp.get("/api/divisions/<division_id>/standings")
@require_roles(*ALL_ROLES)
def division_standings(division_id):
    division = _division_or_404(division_id)
    ranked = [p for p in db.performances.values()
              if p["division_id"] == division["id"] and p["status"] == "OFFICIAL"]
    ranked.sort(key=lambda p: (p["rank_in_division"] is None,
                               p["rank_in_division"] or 0))
    return ok_list(ranked)


@bp.post("/api/divisions/<division_id>/generate-schedule")
@require_roles("EventDirector")
def generate_schedule(division_id):
    division = _division_or_404(division_id)
    b = body()
    expected = req_int(b, "expected_division_version")
    if expected != division["version"]:
        raise errors.stale_version(
            "expected_division_version does not match the division's current version")
    # Forbidden once any performance of the division reached PERFORMED+.
    for p in db.performances.values():
        if p["division_id"] == division["id"] and p["status"] not in (
                "SCHEDULED", "CANCELLED"):
            raise errors.conflict(
                "ERR_INVALID_STATE",
                "Schedule regeneration is forbidden once performances have started")
    # Eligible teams in registration order.
    teams = [t for t in db.teams.values()
             if t["division_id"] == division["id"]
             and t["reg_status"] in ("REGISTERED", "ROSTER_LOCKED", "CHECKED_IN")]
    teams = by_created(teams)
    if not teams:
        raise errors.unprocessable("ERR_DIVISION_HAS_NO_TEAMS",
                                   "Division has no eligible teams to schedule")
    if len(division["warmup_mats"]) < calc.mats_required(division):
        raise errors.unprocessable(
            "ERR_INSUFFICIENT_WARM_UP_MATS",
            "warmup_mats shorter than ceil(warmup_duration / pitch)")
    # Supersede prior schedule: cancel SCHEDULED performances, release the
    # SYSTEM warm-up assignments of this division's teams.
    team_ids = {t["id"] for t in db.teams.values()
                if t["division_id"] == division["id"]}
    for p in db.performances.values():
        if p["division_id"] == division["id"] and p["status"] == "SCHEDULED":
            set_fields(p, status="CANCELLED", rank_in_division=None)
    for w in db.warmup_assignments.values():
        if (w["event_id"] == division["event_id"] and w["team_id"] in team_ids
                and w["source"] == "SYSTEM" and w["status"] == "BOOKED"):
            set_fields(w, status="RELEASED")
    pitch = calc.performance_pitch(division)
    mats = division["warmup_mats"]
    for idx, team in enumerate(teams):
        order = idx + 1
        sched_start = division["schedule_start_at"] + timedelta(
            seconds=(order - 1) * pitch)
        perf = stamp({
            "team_id": team["id"],
            "division_id": division["id"],
            "performance_order": order,
            "scheduled_start": sched_start,
            "actual_duration_seconds": None,
            "boundary_violations": 0,
            "status": "SCHEDULED",
            "provisional_score": None,
            "official_score": None,
            "rank_in_division": None,
        })
        db.performances[perf["id"]] = perf
        warm_end = sched_start - timedelta(seconds=calc.REST_S)
        warm_start = warm_end - timedelta(
            seconds=division["warmup_duration_seconds"])
        warm = stamp({
            "event_id": division["event_id"],
            "team_id": team["id"],
            "mat": mats[idx % len(mats)],
            "starts_at": warm_start,
            "ends_at": warm_end,
            "source": "SYSTEM",
            "status": "BOOKED",
        })
        db.warmup_assignments[warm["id"]] = warm
    division["scheduled"] = True
    touch(division)
    # Auto-advance the event when every division is scheduled.
    event = db.events.get(division["event_id"])
    if event is not None and event["status"] == "REGISTRATION_CLOSED":
        siblings = [d for d in db.divisions.values()
                    if d["event_id"] == event["id"]]
        if all(d["scheduled"] for d in siblings):
            set_fields(event, status="SCHEDULED")
    return ok(division)


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

@bp.post("/api/teams")
@require_roles("TeamCoach")
def create_team():
    b = body()
    event_id = req_str(b, "event_id")
    division_id = req_str(b, "division_id")
    name = req_str(b, "name")
    organization = req_str(b, "organization")
    category = req_enum(b, "category", ("CHEER", "DANCE"))
    level = req_int(b, "level", lo=1, hi=6)
    coach_user_id = req_str(b, "coach_user_id")
    # Ownership: coach_user_id must equal the acting X-User-ID.
    if coach_user_id != g.user_id:
        raise errors.forbidden("coach_user_id must equal the acting X-User-ID")
    event = get_or_404(db.events, event_id, "Event")
    division = get_or_404(db.divisions, division_id, "Division")
    if event["status"] != "REGISTRATION_OPEN":
        raise errors.conflict("ERR_EVENT_INVALID_STATE",
                              "Team registration requires REGISTRATION_OPEN")
    if not (level == division["level"] and category == division["category"]
            and division["event_id"] == event_id):
        raise errors.unprocessable(
            "ERR_DIVISION_MISMATCH",
            "Team level/category/event does not match the division")
    rec = stamp({
        "event_id": event_id,
        "division_id": division_id,
        "name": name,
        "organization": organization,
        "category": category,
        "level": level,
        "coach_user_id": coach_user_id,
        "reg_status": "REGISTERED",
        "music_status": "PENDING",
    })
    db.teams[rec["id"]] = rec
    return ok(rec, 201)


def _team_or_404(team_id):
    return get_or_404(db.teams, team_id, "Team")


@bp.get("/api/teams/<team_id>")
@require_roles(*ALL_ROLES)
def get_team(team_id):
    return ok(_team_or_404(team_id))


def _team_division_event(team):
    division = db.divisions.get(team["division_id"])
    event = db.events.get(team["event_id"])
    return division, event


def _active_roster_count(team_id):
    return sum(1 for e in db.roster_entries.values()
               if e["team_id"] == team_id and not e["removed"]
               and e["eligibility_status"] == "ACTIVE")


@bp.post("/api/teams/<team_id>/lock-roster")
@require_roles("TeamCoach")
def lock_roster(team_id):
    team = _team_or_404(team_id)
    own_team(team)
    division, event = _team_division_event(team)
    if event is not None and event["status"] != "REGISTRATION_OPEN":
        raise errors.conflict("ERR_EVENT_INVALID_STATE",
                              "Roster lock requires REGISTRATION_OPEN")
    if team["reg_status"] != "REGISTERED":
        raise errors.conflict("ERR_INVALID_STATE",
                              "lock-roster requires reg_status REGISTERED")
    count = _active_roster_count(team_id)
    if division is not None:
        if count < division["min_athletes"]:
            raise errors.unprocessable(
                "ERR_ROSTER_TOO_SMALL",
                "Active roster below division min_athletes")
        if count > division["max_athletes"]:
            raise errors.unprocessable(
                "ERR_ROSTER_TOO_LARGE",
                "Active roster above division max_athletes")
    set_fields(team, reg_status="ROSTER_LOCKED")
    return ok(team)


@bp.post("/api/teams/<team_id>/check-in")
@require_roles("TeamCoach")
def check_in(team_id):
    team = _team_or_404(team_id)
    own_team(team)
    b = body()
    athlete_ids = req_list(b, "athlete_ids")
    for a in athlete_ids:
        if not isinstance(a, str):
            raise errors.invalid_input("athlete_ids entries must be strings")
    # Every listed athlete must map to a non-removed roster entry of this team.
    listed_entries = []
    for aid in athlete_ids:
        entry = next((e for e in db.roster_entries.values()
                      if e["team_id"] == team_id and e["athlete_id"] == aid
                      and not e["removed"]), None)
        if entry is None:
            raise errors.not_found(
                f"Athlete {aid} has no non-removed roster entry on this team")
        if entry not in listed_entries:
            listed_entries.append(entry)
    division, event = _team_division_event(team)
    if event is not None and event["status"] != "LIVE":
        raise errors.conflict("ERR_EVENT_NOT_LIVE",
                              "Check-in requires the event to be LIVE")
    if team["reg_status"] != "ROSTER_LOCKED":
        raise errors.conflict("ERR_INVALID_STATE",
                              "check-in requires reg_status ROSTER_LOCKED")
    if team["music_status"] != "VERIFIED":
        raise errors.conflict("ERR_MUSIC_NOT_VERIFIED",
                              "check-in requires music_status VERIFIED")
    active_listed = sum(1 for e in listed_entries
                        if e["eligibility_status"] == "ACTIVE")
    if division is not None and active_listed < division["min_athletes"]:
        raise errors.unprocessable(
            "ERR_ROSTER_TOO_SMALL",
            "Checked-in ACTIVE count below division min_athletes")
    for entry in listed_entries:
        set_fields(entry, checked_in=True)
    set_fields(team, reg_status="CHECKED_IN")
    return ok(team)


@bp.post("/api/teams/<team_id>/withdraw")
@require_roles("TeamCoach")
def withdraw_team(team_id):
    team = _team_or_404(team_id)
    own_team(team)
    if team["reg_status"] not in ("REGISTERED", "ROSTER_LOCKED", "CHECKED_IN",
                                  "COMPETED"):
        raise errors.conflict(
            "ERR_INVALID_STATE",
            f"Cannot withdraw from reg_status {team['reg_status']}")
    for p in db.performances.values():
        if p["team_id"] == team_id and p["status"] == "SCHEDULED":
            set_fields(p, status="CANCELLED")
    revoke_team_bids(team)
    set_fields(team, reg_status="WITHDRAWN")
    return ok(team)


@bp.post("/api/teams/<team_id>/disqualify")
@require_roles("EventDirector")
def disqualify_team(team_id):
    team = _team_or_404(team_id)
    if team["reg_status"] not in ("REGISTERED", "ROSTER_LOCKED", "CHECKED_IN",
                                  "COMPETED"):
        raise errors.conflict(
            "ERR_INVALID_STATE",
            f"Cannot disqualify from reg_status {team['reg_status']}")
    division, _ = _team_division_event(team)
    affected = False
    for p in db.performances.values():
        if p["team_id"] == team_id and p["status"] != "CANCELLED":
            set_fields(p, status="EXCLUDED", rank_in_division=None)
            affected = True
    if affected and division is not None:
        calc.recompute_ranking(division["id"])
    revoke_team_bids(team)
    set_fields(team, reg_status="DISQUALIFIED")
    return ok(team)


# ---------------------------------------------------------------------------
# Music submissions
# ---------------------------------------------------------------------------

def _latest_submission(team_id):
    subs = [s for s in db.music_submissions.values() if s["team_id"] == team_id]
    if not subs:
        return None
    return by_created(subs)[-1]


@bp.post("/api/teams/<team_id>/music-submissions")
@require_roles("TeamCoach")
def create_music_submission(team_id):
    team = _team_or_404(team_id)
    own_team(team)
    b = body()
    track_count = req_int(b, "track_count", lo=1)
    license_provider = req_str(b, "license_provider")
    license_reference = req_str(b, "license_reference")
    if team["reg_status"] not in ("REGISTERED", "ROSTER_LOCKED"):
        raise errors.conflict(
            "ERR_INVALID_STATE",
            "Music submission requires reg_status REGISTERED or ROSTER_LOCKED")
    latest = _latest_submission(team_id)
    if latest is not None and latest["status"] in ("SUBMITTED", "VERIFIED"):
        raise errors.conflict(
            "ERR_MUSIC_STATE_CONFLICT",
            "Latest submission is SUBMITTED (pending) or VERIFIED")
    if latest is not None and latest["status"] == "FLAGGED":
        set_fields(latest, status="SUPERSEDED")
    rec = stamp({
        "team_id": team_id,
        "track_count": track_count,
        "license_provider": license_provider,
        "license_reference": license_reference,
        "status": "SUBMITTED",
        "flag_reason": None,
    })
    db.music_submissions[rec["id"]] = rec
    set_fields(team, music_status="SUBMITTED")
    return ok(rec, 201)


@bp.get("/api/teams/<team_id>/music-submissions")
@require_roles("EventDirector", "TeamCoach", "MusicCompliance")
def list_music_submissions(team_id):
    _team_or_404(team_id)
    subs = by_created([s for s in db.music_submissions.values()
                       if s["team_id"] == team_id])
    return ok_list(subs)


@bp.post("/api/music-submissions/<submission_id>/review")
@require_roles("MusicCompliance")
def review_music_submission(submission_id):
    sub = get_or_404(db.music_submissions, submission_id, "MusicSubmission")
    b = body()
    decision = req_enum(b, "decision", ("VERIFIED", "FLAGGED"))
    reason = None
    if decision == "FLAGGED":
        reason = b.get("reason")
        if not isinstance(reason, str) or not reason:
            raise errors.invalid_input("reason is required when decision is FLAGGED")
    if sub["status"] != "SUBMITTED":
        raise errors.conflict("ERR_MUSIC_STATE_CONFLICT",
                              "Review requires a SUBMITTED submission")
    team = db.teams.get(sub["team_id"])
    if decision == "VERIFIED":
        set_fields(sub, status="VERIFIED")
        if team is not None:
            set_fields(team, music_status="VERIFIED")
    else:
        set_fields(sub, status="FLAGGED", flag_reason=reason)
        if team is not None:
            set_fields(team, music_status="FLAGGED")
    return ok(sub)


# ---------------------------------------------------------------------------
# Athletes
# ---------------------------------------------------------------------------

@bp.post("/api/athletes")
@require_roles("TeamCoach", "EligibilityOfficer")
def create_athlete():
    b = body()
    full_name = req_str(b, "full_name")
    dob = req_date_field(b, "date_of_birth")
    rec = stamp({"full_name": full_name, "date_of_birth": dob})
    db.athletes[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/api/athletes/<athlete_id>")
@require_roles("EventDirector", "TeamCoach", "EligibilityOfficer")
def get_athlete(athlete_id):
    return ok(get_or_404(db.athletes, athlete_id, "Athlete"))


# ---------------------------------------------------------------------------
# Roster entries
# ---------------------------------------------------------------------------

@bp.post("/api/roster-entries")
@require_roles("TeamCoach")
def create_roster_entry():
    b = body()
    team_id = req_str(b, "team_id")
    athlete_id = req_str(b, "athlete_id")
    bib_number = req_int(b, "bib_number")
    team = get_or_404(db.teams, team_id, "Team")
    athlete = get_or_404(db.athletes, athlete_id, "Athlete")
    own_team(team)
    if team["reg_status"] != "REGISTERED":
        raise errors.conflict(
            "ERR_ROSTER_LOCKED",
            "Roster create/delete requires reg_status REGISTERED")
    division, event = _team_division_event(team)
    # Age grid (inclusive) at the event's age_reference_date.
    if division is not None and event is not None:
        age = full_years(athlete["date_of_birth"], event["age_reference_date"])
        if not (division["min_age"] <= age <= division["max_age"]):
            raise errors.unprocessable(
                "ERR_ATHLETE_AGE_INELIGIBLE",
                f"Athlete age {age} outside "
                f"[{division['min_age']}, {division['max_age']}]")
    # Crossover cap: at most 2 teams per event (non-removed entries).
    event_team_ids = {e["team_id"] for e in db.roster_entries.values()
                      if e["athlete_id"] == athlete_id and not e["removed"]
                      and (db.teams.get(e["team_id"]) or {}).get("event_id")
                      == team["event_id"]}
    if team_id not in event_team_ids and len(event_team_ids) >= 2:
        raise errors.unprocessable(
            "ERR_CROSSOVER_LIMIT_EXCEEDED",
            "Athlete would exceed 2 teams in the same event")
    # Same-division ban: already rostered on another team in this division.
    for e in db.roster_entries.values():
        if e["athlete_id"] != athlete_id or e["removed"] \
                or e["team_id"] == team_id:
            continue
        other = db.teams.get(e["team_id"])
        if other is not None and other["division_id"] == team["division_id"]:
            raise errors.unprocessable(
                "ERR_SAME_DIVISION_CROSSOVER",
                "Athlete already rostered on another team in this division")
    # Roster ceiling on the resulting non-removed count.
    count = sum(1 for e in db.roster_entries.values()
                if e["team_id"] == team_id and not e["removed"])
    if division is not None and count + 1 > division["max_athletes"]:
        raise errors.unprocessable("ERR_ROSTER_TOO_LARGE",
                                   "Roster would exceed division max_athletes")
    rec = stamp({
        "team_id": team_id,
        "athlete_id": athlete_id,
        "bib_number": bib_number,
        "eligibility_status": "ACTIVE",
        "checked_in": False,
        "removed": False,
    })
    db.roster_entries[rec["id"]] = rec
    return ok(rec, 201)


def _entry_or_404(entry_id):
    return get_or_404(db.roster_entries, entry_id, "RosterEntry")


@bp.get("/api/roster-entries/<entry_id>")
@require_roles("EventDirector", "TeamCoach", "EligibilityOfficer")
def get_roster_entry(entry_id):
    return ok(_entry_or_404(entry_id))


@bp.delete("/api/roster-entries/<entry_id>")
@require_roles("TeamCoach")
def delete_roster_entry(entry_id):
    entry = _entry_or_404(entry_id)
    team = db.teams.get(entry["team_id"])
    if team is not None:
        own_team(team)
        if team["reg_status"] != "REGISTERED":
            raise errors.conflict(
                "ERR_ROSTER_LOCKED",
                "Roster removal requires reg_status REGISTERED")
    set_fields(entry, removed=True)
    return "", 204


@bp.post("/api/roster-entries/<entry_id>/set-eligibility")
@require_roles("EligibilityOfficer")
def set_eligibility(entry_id):
    entry = _entry_or_404(entry_id)
    b = body()
    target = req_enum(b, "eligibility_status", ("ACTIVE", "INELIGIBLE"))
    team = db.teams.get(entry["team_id"])
    division = db.divisions.get(team["division_id"]) if team else None
    if team is not None and team["reg_status"] not in ("REGISTERED",
                                                       "ROSTER_LOCKED"):
        raise errors.conflict(
            "ERR_ROSTER_LOCKED",
            "Eligibility changes allowed only in REGISTERED/ROSTER_LOCKED")
    if team is not None and division is not None:
        active_count = _active_roster_count(team["id"])
        if target == "INELIGIBLE" and entry["eligibility_status"] == "ACTIVE" \
                and not entry["removed"]:
            if team["reg_status"] == "ROSTER_LOCKED" \
                    and active_count - 1 < division["min_athletes"]:
                raise errors.unprocessable(
                    "ERR_ROSTER_TOO_SMALL",
                    "Resulting ACTIVE roster below division min_athletes")
        if target == "ACTIVE" and entry["eligibility_status"] == "INELIGIBLE" \
                and not entry["removed"]:
            if active_count + 1 > division["max_athletes"]:
                raise errors.unprocessable(
                    "ERR_ROSTER_TOO_LARGE",
                    "Resulting ACTIVE roster above division max_athletes")
    set_fields(entry, eligibility_status=target)
    return ok(entry)


# ---------------------------------------------------------------------------
# Judges
# ---------------------------------------------------------------------------

@bp.post("/api/judges")
@require_roles("EventDirector")
def create_judge():
    b = body()
    full_name = req_str(b, "full_name")
    levels = req_list(b, "certified_levels")
    for lv in levels:
        if isinstance(lv, bool) or not isinstance(lv, int) or not (1 <= lv <= 6):
            raise errors.invalid_input(
                "certified_levels entries must be integers within 1..6")
    rec = stamp({"full_name": full_name, "certified_levels": list(levels)})
    db.judges[rec["id"]] = rec
    return ok(rec, 201)


@bp.get("/api/judges/<judge_id>")
@require_roles("EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge")
def get_judge(judge_id):
    return ok(get_or_404(db.judges, judge_id, "Judge"))


# ---------------------------------------------------------------------------
# FK reverse-reachability list reads (core entities)
# ---------------------------------------------------------------------------

@bp.get("/api/events/<event_id>/divisions")
@require_roles(*ALL_ROLES)
def list_event_divisions(event_id):
    _event_or_404(event_id)
    return ok_list(by_created([d for d in db.divisions.values()
                               if d["event_id"] == event_id]))


@bp.get("/api/events/<event_id>/teams")
@require_roles(*ALL_ROLES)
def list_event_teams(event_id):
    _event_or_404(event_id)
    return ok_list(by_created([t for t in db.teams.values()
                               if t["event_id"] == event_id]))


@bp.get("/api/events/<event_id>/sessions")
@require_roles("EventDirector", "TeamCoach", "Spectator")
def list_event_sessions(event_id):
    _event_or_404(event_id)
    return ok_list(by_created([s for s in db.sessions.values()
                               if s["event_id"] == event_id]))


@bp.get("/api/events/<event_id>/warm-up-assignments")
@require_roles("EventDirector", "TeamCoach")
def list_event_warmups(event_id):
    _event_or_404(event_id)
    return ok_list(by_created([w for w in db.warmup_assignments.values()
                               if w["event_id"] == event_id]))


@bp.get("/api/divisions/<division_id>/teams")
@require_roles(*ALL_ROLES)
def list_division_teams(division_id):
    _division_or_404(division_id)
    return ok_list(by_created([t for t in db.teams.values()
                               if t["division_id"] == division_id]))


@bp.get("/api/divisions/<division_id>/performances")
@require_roles("EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge")
def list_division_performances(division_id):
    _division_or_404(division_id)
    return ok_list(by_created([p for p in db.performances.values()
                               if p["division_id"] == division_id]))


@bp.get("/api/divisions/<division_id>/bids")
@require_roles("EventDirector", "TeamCoach")
def list_division_bids(division_id):
    _division_or_404(division_id)
    return ok_list(by_created([b for b in db.bids.values()
                               if b["division_id"] == division_id]))


@bp.get("/api/teams/<team_id>/roster-entries")
@require_roles("EventDirector", "TeamCoach", "EligibilityOfficer")
def list_team_roster_entries(team_id):
    _team_or_404(team_id)
    from flask import request
    include_removed = request.args.get("include_removed", "").lower() in (
        "true", "1", "yes")
    entries = [e for e in db.roster_entries.values()
               if e["team_id"] == team_id and (include_removed or not e["removed"])]
    return ok_list(by_created(entries))


@bp.get("/api/athletes/<athlete_id>/roster-entries")
@require_roles("EventDirector", "TeamCoach", "EligibilityOfficer")
def list_athlete_roster_entries(athlete_id):
    get_or_404(db.athletes, athlete_id, "Athlete")
    return ok_list(by_created([e for e in db.roster_entries.values()
                               if e["athlete_id"] == athlete_id]))


@bp.get("/api/teams/<team_id>/performances")
@require_roles("EventDirector", "TeamCoach", "Judge", "HeadJudge", "SafetyJudge")
def list_team_performances(team_id):
    _team_or_404(team_id)
    return ok_list(by_created([p for p in db.performances.values()
                               if p["team_id"] == team_id]))


@bp.get("/api/teams/<team_id>/bids")
@require_roles("EventDirector", "TeamCoach")
def list_team_bids(team_id):
    _team_or_404(team_id)
    return ok_list(by_created([b for b in db.bids.values()
                               if b["team_id"] == team_id]))


@bp.get("/api/teams/<team_id>/warm-up-assignments")
@require_roles("EventDirector", "TeamCoach")
def list_team_warmups(team_id):
    _team_or_404(team_id)
    return ok_list(by_created([w for w in db.warmup_assignments.values()
                               if w["team_id"] == team_id]))


@bp.get("/api/judges/<judge_id>/score-sheets")
@require_roles("EventDirector", "Judge", "HeadJudge")
def list_judge_score_sheets(judge_id):
    get_or_404(db.judges, judge_id, "Judge")
    return ok_list(by_created([s for s in db.score_sheets.values()
                               if s["judge_id"] == judge_id]))
