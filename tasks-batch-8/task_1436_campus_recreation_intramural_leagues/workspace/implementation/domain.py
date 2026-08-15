"""Domain layer: serializers, calculations, state-machine cascades.

All formulas follow SCAFFOLD.yaml calculations table and PRD section 3 with
pinned rounding orders (round_half_up; weekly rate rounded BEFORE multiply;
instructor pay rounded PER SESSION).
"""

import math
from datetime import date, timedelta
from decimal import Decimal

import errors as E
from store import DB
from util import now, today, fmt_dt, touch, stamp_new, rhu_cents, rhu2

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TERM_WINDOWS = {
    "FALL_2026": (date(2026, 8, 24), date(2026, 12, 11)),
    "SPRING_2027": (date(2027, 1, 12), date(2027, 5, 7)),
    "SUMMER_2027": (date(2027, 5, 24), date(2027, 8, 6)),
}
TERM_FEE_CENTS = {"STUDENT": 6000, "FACULTY": 20000, "COMMUNITY": 32000}
FULL_WINDOW_DAYS = 7

CERT_MULTIPLIER = {1: Decimal("1.0"), 2: Decimal("1.25"), 3: Decimal("1.5")}
FORFEIT_FLAT_HOURS = 1
TRAVEL_BUFFER_MINUTES = 30
FORFEIT_SUSPENSION_THRESHOLD = 3

LOCKER_FEE_CENTS = {"STUDENT": 1500, "FACULTY": 1500, "COMMUNITY": 3000}

CLASS_TYPES = {"YOGA", "SPIN", "PILATES", "HIIT", "ZUMBA"}
SPORTS = {"BASKETBALL", "SOCCER", "VOLLEYBALL", "FLAG_FOOTBALL", "DODGEBALL"}
FACILITY_KINDS = {"COURT", "FIELD", "ROOM", "POOL"}
ITEM_TYPES = {"BASKETBALL", "VOLLEYBALL", "SOCCER_BALL", "TENNIS_RACKET", "BADMINTON_SET", "YOGA_MAT"}
LOCKER_SIZES = {"S", "M", "L"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE"}
HOLD_SEVERITIES = {"MODERATE", "SEVERE"}

PLAYOFF_MIN_RATING = Decimal("3.00")
PLAYOFF_MAX_FORFEITS = 1

WIN_POINTS = 3
TIE_POINTS = 1
LOSS_POINTS = 0


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def member_out(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "affiliation": m["affiliation"],
        "status": m["status"],
        "waiver_signed_date": m["waiver_signed_date"].isoformat() if m["waiver_signed_date"] else None,
        "outstanding_fines_cents": m["outstanding_fines_cents"],
        "no_show_count": m["no_show_count"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def membership_out(ms):
    return {
        "id": ms["id"],
        "member_id": ms["member_id"],
        "term": ms["term"],
        "pricing_variant": ms["pricing_variant"],
        "fee_cents": ms["fee_cents"],
        "status": ms["status"],
        "supersedes_membership_id": ms["supersedes_membership_id"],
        "created_at": fmt_dt(ms["created_at"]),
        "updated_at": fmt_dt(ms["updated_at"]),
        "version": ms["version"],
    }


def league_out(lg):
    pool = []
    for entry in lg["free_agent_pool"]:
        pool.append({
            "member_id": entry["member_id"],
            "preferred_division_name": entry["preferred_division_name"],
            "registered_at": fmt_dt(entry["registered_at"]),
            "status": entry["status"],
        })
    divisions = []
    for d in lg["divisions"]:
        divisions.append({
            "name": d["name"],
            "capacity": d["capacity"],
            "skill_min": d["skill_min"],
            "skill_max": d["skill_max"],
        })
    return {
        "id": lg["id"],
        "name": lg["name"],
        "sport": lg["sport"],
        "divisions": divisions,
        "registration_open_at": fmt_dt(lg["registration_open_at"]),
        "registration_close_at": fmt_dt(lg["registration_close_at"]),
        "season_start_at": fmt_dt(lg["season_start_at"]),
        "season_end_at": fmt_dt(lg["season_end_at"]),
        "team_capacity": lg["team_capacity"],
        "min_teams": lg["min_teams"],
        "roster_min": lg["roster_min"],
        "roster_max": lg["roster_max"],
        "status": lg["status"],
        "free_agent_pool": pool,
        "created_at": fmt_dt(lg["created_at"]),
        "updated_at": fmt_dt(lg["updated_at"]),
        "version": lg["version"],
    }


def team_out(t):
    return {
        "id": t["id"],
        "league_id": t["league_id"],
        "name": t["name"],
        "captain_member_id": t["captain_member_id"],
        "skill_rating": t["skill_rating"],
        "division_name": t["division_name"],
        "status": t["status"],
        "wins": t["wins"],
        "losses": t["losses"],
        "ties": t["ties"],
        "points": t["points"],
        "forfeit_count": t["forfeit_count"],
        "sportsmanship_points_total": t["sportsmanship_points_total"],
        "sportsmanship_rating_count": t["sportsmanship_rating_count"],
        "sportsmanship_rating": (float(t["sportsmanship_rating"]) if t["sportsmanship_rating"] is not None else None),
        "active_roster_count": t["active_roster_count"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def roster_out(r):
    return {
        "id": r["id"],
        "team_id": r["team_id"],
        "member_id": r["member_id"],
        "role": r["role"],
        "status": r["status"],
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def facility_out(f):
    closures = [{
        "closure_id": c["closure_id"],
        "start_at": fmt_dt(c["start_at"]),
        "end_at": fmt_dt(c["end_at"]),
        "reason": c["reason"],
    } for c in f["closures"]]
    windows = [{
        "day_of_week": w["day_of_week"],
        "open_minute": w["open_minute"],
        "close_minute": w["close_minute"],
    } for w in f["operating_windows"]]
    return {
        "id": f["id"],
        "name": f["name"],
        "kind": f["kind"],
        "operating_windows": windows,
        "closures": closures,
        "created_at": fmt_dt(f["created_at"]),
        "updated_at": fmt_dt(f["updated_at"]),
        "version": f["version"],
    }


def _report_out(rep):
    if rep is None:
        return None
    return {
        "home_score": rep["home_score"],
        "away_score": rep["away_score"],
        "opponent_sportsmanship": rep["opponent_sportsmanship"],
        "reported_at": fmt_dt(rep["reported_at"]),
    }


def game_out(gm):
    return {
        "id": gm["id"],
        "league_id": gm["league_id"],
        "division_name": gm["division_name"],
        "home_team_id": gm["home_team_id"],
        "away_team_id": gm["away_team_id"],
        "facility_id": gm["facility_id"],
        "start_at": fmt_dt(gm["start_at"]),
        "end_at": fmt_dt(gm["end_at"]),
        "duration_minutes": gm["duration_minutes"],
        "status": gm["status"],
        "bracket_round": gm["bracket_round"],
        "next_game_id": gm["next_game_id"],
        "report_home": _report_out(gm["report_home"]),
        "report_away": _report_out(gm["report_away"]),
        "final_home_score": gm["final_home_score"],
        "final_away_score": gm["final_away_score"],
        "actual_duration_minutes": gm["actual_duration_minutes"],
        "forfeiting_team_id": gm["forfeiting_team_id"],
        "created_at": fmt_dt(gm["created_at"]),
        "updated_at": fmt_dt(gm["updated_at"]),
        "version": gm["version"],
    }


def staff_out(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "staff_role": s["staff_role"],
        "certification_level": s["certification_level"],
        "certified_class_types": s["certified_class_types"],
        "base_hourly_rate_cents": s["base_hourly_rate_cents"],
        "payroll_pending_cents": s["payroll_pending_cents"],
        "payroll_paid_cents": s["payroll_paid_cents"],
        "created_at": fmt_dt(s["created_at"]),
        "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def assignment_out(a):
    return {
        "id": a["id"],
        "game_id": a["game_id"],
        "staff_id": a["staff_id"],
        "status": a["status"],
        "provisional_pay_cents": a["provisional_pay_cents"],
        "final_pay_cents": a["final_pay_cents"],
        "created_at": fmt_dt(a["created_at"]),
        "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def injury_out(ir):
    return {
        "id": ir["id"],
        "member_id": ir["member_id"],
        "game_id": ir["game_id"],
        "severity": ir["severity"],
        "description": ir["description"],
        "status": ir["status"],
        "clearance_note": ir["clearance_note"],
        "created_at": fmt_dt(ir["created_at"]),
        "updated_at": fmt_dt(ir["updated_at"]),
        "version": ir["version"],
    }


def pool_out(p):
    return {
        "id": p["id"],
        "item_type": p["item_type"],
        "total_qty": p["total_qty"],
        "daily_late_fee_cents": p["daily_late_fee_cents"],
        "unit_replacement_cents": p["unit_replacement_cents"],
        "available_qty": p["available_qty"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def checkout_out(c):
    return {
        "id": c["id"],
        "equipment_pool_id": c["equipment_pool_id"],
        "member_id": c["member_id"],
        "quantity": c["quantity"],
        "due_at": fmt_dt(c["due_at"]),
        "status": c["status"],
        "returned_at": fmt_dt(c["returned_at"]),
        "late_fee_cents": c["late_fee_cents"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def locker_out(lk):
    return {
        "id": lk["id"],
        "locker_number": lk["locker_number"],
        "size": lk["size"],
        "status": lk["status"],
        "rented_by_member_id": lk["rented_by_member_id"],
        "rental_term": lk["rental_term"],
        "rental_fee_cents": lk["rental_fee_cents"],
        "created_at": fmt_dt(lk["created_at"]),
        "updated_at": fmt_dt(lk["updated_at"]),
        "version": lk["version"],
    }


def class_out(fc):
    return {
        "id": fc["id"],
        "title": fc["title"],
        "class_type": fc["class_type"],
        "instructor_staff_id": fc["instructor_staff_id"],
        "facility_id": fc["facility_id"],
        "start_at": fmt_dt(fc["start_at"]),
        "end_at": fmt_dt(fc["end_at"]),
        "duration_minutes": fc["duration_minutes"],
        "capacity": fc["capacity"],
        "registered_count": fc["registered_count"],
        "waitlist_count": fc["waitlist_count"],
        "status": fc["status"],
        "attendance_count": fc["attendance_count"],
        "instructor_pay_estimate_cents": fc["instructor_pay_estimate_cents"],
        "instructor_pay_cents": fc["instructor_pay_cents"],
        "created_at": fmt_dt(fc["created_at"]),
        "updated_at": fmt_dt(fc["updated_at"]),
        "version": fc["version"],
    }


def registration_out(rg):
    return {
        "id": rg["id"],
        "fitness_class_id": rg["fitness_class_id"],
        "member_id": rg["member_id"],
        "status": rg["status"],
        "created_at": fmt_dt(rg["created_at"]),
        "updated_at": fmt_dt(rg["updated_at"]),
        "version": rg["version"],
    }


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(table, rec_id):
    rec = table.get(rec_id)
    if rec is None:
        raise E.err_not_found(f"Resource not found: {rec_id}")
    return rec


# ---------------------------------------------------------------------------
# Membership fee + lazy expiry + waiver
# ---------------------------------------------------------------------------

def membership_fee(term, affiliation, purchase_date):
    """Return (pricing_variant, fee_cents). Raises ERR_VALIDATION after term end."""
    term_start, term_end = TERM_WINDOWS[term]
    if purchase_date > term_end:
        raise E.err_validation("Cannot purchase a membership after the term end date")
    days_total = (term_end - term_start).days + 1
    weeks_total = (days_total + 6) // 7
    if purchase_date <= term_start + timedelta(days=FULL_WINDOW_DAYS - 1):
        return "FULL", TERM_FEE_CENTS[affiliation]
    weekly_rate = rhu_cents(Decimal(TERM_FEE_CENTS[affiliation]) / Decimal(weeks_total))
    days_remaining = (term_end - purchase_date).days + 1
    weeks_remaining = (days_remaining + 6) // 7
    return "PRORATED", weekly_rate * weeks_remaining


def lazy_expire_membership(ms):
    """Lazy expiry: on read / eligibility check, ACTIVE -> EXPIRED when the
    logical current date is past the term end date (end date inclusive-active)."""
    if ms["status"] == "ACTIVE":
        _, term_end = TERM_WINDOWS[ms["term"]]
        if today() > term_end:
            ms["status"] = "EXPIRED"
            touch(ms)


def member_active_membership(member_id):
    """Return the member's lazily-evaluated ACTIVE membership, or None."""
    active = None
    for ms in DB.memberships.values():
        if ms["member_id"] != member_id:
            continue
        lazy_expire_membership(ms)
        if ms["status"] == "ACTIVE":
            active = ms
    return active


def academic_year_start(d):
    """Academic year of a date: Aug-Dec -> Aug 1 same year; Jan-Jul -> Aug 1 prior year."""
    if d.month >= 8:
        return date(d.year, 8, 1)
    return date(d.year - 1, 8, 1)


def waiver_valid(member):
    signed = member["waiver_signed_date"]
    if signed is None:
        return False
    return academic_year_start(signed) == academic_year_start(today())


def eligibility_gate(member, check_fines=False):
    """PRD 2.9 gates, in order: suspension -> waiver -> membership -> fines."""
    if member["status"] != "ACTIVE":
        raise E.err_member_suspended()
    if not waiver_valid(member):
        raise E.err_waiver_invalid()
    if member_active_membership(member["id"]) is None:
        raise E.err_membership_inactive()
    if check_fines and member["outstanding_fines_cents"] > 0:
        raise E.err_outstanding_fines()


# ---------------------------------------------------------------------------
# Facility booking fit (PRD 2.10) -- half-open intervals throughout
# ---------------------------------------------------------------------------

def overlaps(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


def check_booking_fit(facility, start_at, end_at, exclude_game_id=None, exclude_class_id=None):
    """Runs the priority-9 temporal sub-order after ERR_GAME_IN_PAST:
    OUTSIDE_HOURS -> CLOSED -> DOUBLE_BOOKED. Caller handles GAME_IN_PAST."""
    # Operating window fit: one window of the booking's weekday must contain it.
    weekday = start_at.date().weekday()
    start_sec = start_at.hour * 3600 + start_at.minute * 60 + start_at.second + start_at.microsecond / 1e6
    end_sec = end_at.hour * 3600 + end_at.minute * 60 + end_at.second + end_at.microsecond / 1e6
    fits = False
    for w in facility["operating_windows"]:
        if w["day_of_week"] != weekday:
            continue
        if start_sec >= w["open_minute"] * 60 and end_sec <= w["close_minute"] * 60:
            fits = True
            break
    if not fits:
        raise E.err_outside_hours()
    # Closure exclusion: half-open [cs, ce); start_at == ce is allowed.
    for c in facility["closures"]:
        if overlaps(start_at, end_at, c["start_at"], c["end_at"]):
            raise E.err_facility_closed()
    # Double booking: SCHEDULED games and SCHEDULED classes at this facility.
    for gm in DB.games.values():
        if gm["facility_id"] != facility["id"] or gm["status"] != "SCHEDULED":
            continue
        if exclude_game_id is not None and gm["id"] == exclude_game_id:
            continue
        if gm["start_at"] is None:
            continue
        if overlaps(start_at, end_at, gm["start_at"], gm["end_at"]):
            raise E.err_double_booked()
    for fc in DB.fitness_classes.values():
        if fc["facility_id"] != facility["id"] or fc["status"] != "SCHEDULED":
            continue
        if exclude_class_id is not None and fc["id"] == exclude_class_id:
            continue
        if overlaps(start_at, end_at, fc["start_at"], fc["end_at"]):
            raise E.err_double_booked()


def check_team_time_conflict(home_team_id, away_team_id, start_at, end_at, exclude_game_id=None):
    for gm in DB.games.values():
        if gm["status"] != "SCHEDULED":
            continue
        if exclude_game_id is not None and gm["id"] == exclude_game_id:
            continue
        if gm["start_at"] is None:
            continue
        if gm["home_team_id"] not in (home_team_id, away_team_id) and \
           gm["away_team_id"] not in (home_team_id, away_team_id):
            continue
        if overlaps(start_at, end_at, gm["start_at"], gm["end_at"]):
            raise E.err_team_time_conflict()


def check_official_travel_buffer(staff_id, cand_start, cand_end):
    """30-minute travel buffer vs the official's other live assignments."""
    buf = timedelta(minutes=TRAVEL_BUFFER_MINUTES)
    for a in DB.assignments.values():
        if a["staff_id"] != staff_id:
            continue
        if a["status"] not in ("ASSIGNED", "ACCEPTED", "WORKED"):
            continue
        gm = DB.games.get(a["game_id"])
        if gm is None or gm["status"] not in ("SCHEDULED", "PLAYED_PENDING_CONFIRM", "DISPUTED", "FINAL", "FORFEITED"):
            continue
        if gm["start_at"] is None or gm["end_at"] is None:
            continue
        if (cand_start - gm["end_at"]) >= buf or (gm["start_at"] - cand_end) >= buf:
            continue
        raise E.err_official_double_booked()


# ---------------------------------------------------------------------------
# Pay calculations
# ---------------------------------------------------------------------------

def official_provisional_pay(duration_minutes, staff):
    mult = CERT_MULTIPLIER[staff["certification_level"]]
    return rhu_cents(Decimal(duration_minutes) * staff["base_hourly_rate_cents"] * mult / Decimal(60))


def official_final_pay(game, staff):
    if game["status"] == "FORFEITED":
        return staff["base_hourly_rate_cents"] * FORFEIT_FLAT_HOURS
    minutes = game["actual_duration_minutes"] if game["actual_duration_minutes"] is not None else game["duration_minutes"]
    mult = CERT_MULTIPLIER[staff["certification_level"]]
    return rhu_cents(Decimal(minutes) * staff["base_hourly_rate_cents"] * mult / Decimal(60))


def instructor_estimate_pay(duration_minutes, staff):
    return rhu_cents(Decimal(duration_minutes) * staff["base_hourly_rate_cents"] / Decimal(60))


def instructor_final_pay(duration_minutes, staff, attendance_count, capacity):
    if attendance_count * 5 >= 4 * capacity:
        bonus = Decimal("0.20")
    elif attendance_count * 2 >= capacity:
        bonus = Decimal("0.10")
    else:
        bonus = Decimal("0")
    return rhu_cents(Decimal(duration_minutes) * staff["base_hourly_rate_cents"] * (Decimal(1) + bonus) / Decimal(60))


def equipment_late_fee(checkout, pool):
    seconds_late = max(0.0, (now() - checkout["due_at"]).total_seconds())
    days_late = int(math.ceil(seconds_late / 86400.0)) if seconds_late > 0 else 0
    raw = days_late * pool["daily_late_fee_cents"] * checkout["quantity"]
    return min(raw, checkout["quantity"] * pool["unit_replacement_cents"])


# ---------------------------------------------------------------------------
# Sportsmanship + standings
# ---------------------------------------------------------------------------

def apply_rating(team, rating):
    team["sportsmanship_points_total"] += rating
    team["sportsmanship_rating_count"] += 1
    team["sportsmanship_rating"] = rhu2(team["sportsmanship_points_total"], team["sportsmanship_rating_count"])


# ---------------------------------------------------------------------------
# Assignment / payroll plumbing
# ---------------------------------------------------------------------------

def cancel_assignment(a):
    """System cancellation of a non-terminal assignment with provisional reversal."""
    if a["status"] not in ("ASSIGNED", "ACCEPTED"):
        return
    a["status"] = "CANCELLED"
    touch(a)
    staff = DB.staff.get(a["staff_id"])
    if staff is not None:
        staff["payroll_pending_cents"] -= a["provisional_pay_cents"]
        touch(staff)


# ---------------------------------------------------------------------------
# Game result effects / forfeits / suspension sweep / playoff advancement
# ---------------------------------------------------------------------------

def game_winner_id(game):
    if game["status"] == "FORFEITED":
        return game["away_team_id"] if game["forfeiting_team_id"] == game["home_team_id"] else game["home_team_id"]
    if game["final_home_score"] is None or game["final_away_score"] is None:
        return None
    if game["final_home_score"] > game["final_away_score"]:
        return game["home_team_id"]
    if game["final_away_score"] > game["final_home_score"]:
        return game["away_team_id"]
    return None


def apply_forfeit_effects(game, forfeiting_team_id, manual):
    """Shared by manual declare-forfeit and system cascade-forfeits.
    Standings + automatic sportsmanship 1 + officials handling + sweeps."""
    home = DB.teams.get(game["home_team_id"])
    away = DB.teams.get(game["away_team_id"])
    loser = home if home and home["id"] == forfeiting_team_id else away
    winner = away if loser is home else home
    game["status"] = "FORFEITED"
    game["forfeiting_team_id"] = forfeiting_team_id
    touch(game)
    if loser is not None:
        loser["losses"] += 1
        loser["forfeit_count"] += 1
        apply_rating(loser, 1)
        touch(loser)
    if winner is not None:
        winner["wins"] += 1
        winner["points"] += WIN_POINTS
        touch(winner)
    # Officials handling differs sharply by trigger.
    for a in list(DB.assignments.values()):
        if a["game_id"] != game["id"]:
            continue
        if manual:
            if a["status"] == "ACCEPTED":
                a["status"] = "WORKED"
                touch(a)
            elif a["status"] == "ASSIGNED":
                cancel_assignment(a)
        else:
            cancel_assignment(a)
    # Suspension sweep on the forfeiting team.
    if loser is not None:
        suspension_sweep(loser)
    playoff_advancement(game)


def suspension_sweep(team):
    """If the team is ACTIVE with forfeit_count >= 3: suspend and cascade-forfeit
    its remaining SCHEDULED | RESCHEDULE_REQUIRED games."""
    if team["status"] != "ACTIVE" or team["forfeit_count"] < FORFEIT_SUSPENSION_THRESHOLD:
        return
    team["status"] = "SUSPENDED"
    touch(team)
    targets = [g for g in DB.games.values()
               if g["status"] in ("SCHEDULED", "RESCHEDULE_REQUIRED")
               and (g["home_team_id"] == team["id"] or g["away_team_id"] == team["id"])]
    targets.sort(key=lambda g: g["_seq"])
    for g in targets:
        apply_forfeit_effects(g, team["id"], manual=False)


def apply_final_effects(game, home_score, away_score, home_rating, away_rating):
    """FINAL effects: standings, sportsmanship, WORKED assignments, sweeps,
    playoff advancement. Ratings are the ones credited to each team."""
    game["status"] = "FINAL"
    game["final_home_score"] = home_score
    game["final_away_score"] = away_score
    touch(game)
    home = DB.teams.get(game["home_team_id"])
    away = DB.teams.get(game["away_team_id"])
    if home_score > away_score:
        if home is not None:
            home["wins"] += 1
            home["points"] += WIN_POINTS
        if away is not None:
            away["losses"] += 1
    elif away_score > home_score:
        if away is not None:
            away["wins"] += 1
            away["points"] += WIN_POINTS
        if home is not None:
            home["losses"] += 1
    else:
        # Tie possible only in REGULAR round (playoff ties rejected upstream).
        if home is not None:
            home["ties"] += 1
            home["points"] += TIE_POINTS
        if away is not None:
            away["ties"] += 1
            away["points"] += TIE_POINTS
    if home is not None:
        apply_rating(home, home_rating)
        touch(home)
    if away is not None:
        apply_rating(away, away_rating)
        touch(away)
    for a in list(DB.assignments.values()):
        if a["game_id"] == game["id"] and a["status"] == "ACCEPTED":
            a["status"] = "WORKED"
            touch(a)
    if home is not None:
        suspension_sweep(home)
    if away is not None:
        suspension_sweep(away)
    playoff_advancement(game)


def playoff_advancement(game):
    """Semifinal pair resolution -> championship creation; championship
    resolution -> league completion check."""
    if game["bracket_round"] == "SEMIFINAL":
        group = game.get("_sf_group")
        if not group:
            return
        siblings = [g for g in DB.games.values()
                    if g.get("_sf_group") == group and g["bracket_round"] == "SEMIFINAL"]
        if len(siblings) != 2:
            return
        if not all(g["status"] in ("FINAL", "FORFEITED") for g in siblings):
            return
        league = DB.leagues.get(game["league_id"])
        if league is None:
            return
        bracket = None
        for b in league.get("_brackets", []):
            if b.get("sf_group") == group:
                bracket = b
                break
        if bracket is None or bracket.get("championship_id") is not None:
            return
        winners = []
        for g in siblings:
            w_id = game_winner_id(g)
            if w_id is None:
                return
            seed = g["_home_seed"] if w_id == g["home_team_id"] else g["_away_seed"]
            winners.append((seed, w_id))
        winners.sort(key=lambda x: x[0])
        champ = {
            "league_id": league["id"],
            "division_name": None,
            "home_team_id": winners[0][1],
            "away_team_id": winners[1][1],
            "facility_id": None,
            "start_at": None,
            "end_at": None,
            "duration_minutes": None,
            "status": "RESCHEDULE_REQUIRED",
            "bracket_round": "CHAMPIONSHIP",
            "next_game_id": None,
            "report_home": None,
            "report_away": None,
            "final_home_score": None,
            "final_away_score": None,
            "actual_duration_minutes": None,
            "forfeiting_team_id": None,
            "_division": bracket.get("division"),
            "_home_seed": winners[0][0],
            "_away_seed": winners[1][0],
            "_sf_group": None,
        }
        stamp_new(champ)
        DB.games[champ["id"]] = champ
        bracket["championship_id"] = champ["id"]
        for g in siblings:
            g["next_game_id"] = champ["id"]
            touch(g)
    elif game["bracket_round"] == "CHAMPIONSHIP":
        league_completion_check(game["league_id"])


def league_completion_check(league_id):
    league = DB.leagues.get(league_id)
    if league is None or league["status"] != "PLAYOFFS":
        return
    brackets = league.get("_brackets", [])
    if not brackets:
        return
    for b in brackets:
        champ_id = b.get("championship_id")
        if champ_id is None:
            return
        champ = DB.games.get(champ_id)
        if champ is None or champ["status"] not in ("FINAL", "FORFEITED"):
            return
    league["status"] = "COMPLETED"
    touch(league)
    for t in DB.teams.values():
        if t["league_id"] == league["id"] and t["status"] in ("ACTIVE", "SUSPENDED"):
            t["status"] = "COMPLETED"
            touch(t)


# ---------------------------------------------------------------------------
# Playoff eligibility + seeding
# ---------------------------------------------------------------------------

def team_eligible(team):
    rating = team["sportsmanship_rating"] if team["sportsmanship_rating"] is not None else Decimal("0.00")
    return (team["status"] == "ACTIVE"
            and rating >= PLAYOFF_MIN_RATING
            and team["forfeit_count"] <= PLAYOFF_MAX_FORFEITS)


def _head_to_head_points(team_id, tied_ids, league_id):
    total = 0
    for g in DB.games.values():
        if g["league_id"] != league_id or g["status"] not in ("FINAL", "FORFEITED"):
            continue
        pair = {g["home_team_id"], g["away_team_id"]}
        if team_id not in pair or not pair.issubset(tied_ids):
            continue
        if g["status"] == "FORFEITED":
            if g["forfeiting_team_id"] != team_id:
                total += WIN_POINTS
        else:
            hs, as_ = g["final_home_score"], g["final_away_score"]
            if hs is None or as_ is None:
                continue
            if hs == as_:
                total += TIE_POINTS
            else:
                winner = g["home_team_id"] if hs > as_ else g["away_team_id"]
                if winner == team_id:
                    total += WIN_POINTS
    return total


def seed_division(teams, league_id):
    """Rank eligible ACTIVE teams per calculations.playoff_seeding."""
    def keyfn(t):
        rating = t["sportsmanship_rating"] if t["sportsmanship_rating"] is not None else Decimal("0.00")
        tied_ids = {u["id"] for u in teams if u["points"] == t["points"]}
        h2h = _head_to_head_points(t["id"], tied_ids, league_id) if len(tied_ids) > 1 else 0
        return (-t["points"], -h2h, -rating, t["forfeit_count"], t["created_at"], t["_seq"])
    return sorted(teams, key=keyfn)


# ---------------------------------------------------------------------------
# Waitlist promotion
# ---------------------------------------------------------------------------

def promote_waitlist_head(fitness_class):
    """Promote the head WAITLISTED registration to REGISTERED. Never runs on a
    CANCELLED or COMPLETED class; empty waitlist -> no-op."""
    if fitness_class["status"] in ("CANCELLED", "COMPLETED"):
        return
    candidates = [r for r in DB.registrations.values()
                  if r["fitness_class_id"] == fitness_class["id"] and r["status"] == "WAITLISTED"]
    if not candidates:
        return

    def rank(r):
        member = DB.members.get(r["member_id"])
        m_created = member["created_at"] if member else r["created_at"]
        m_seq = member["_seq"] if member else r["_seq"]
        return (r["created_at"], m_created, r["_seq"], m_seq)

    head = min(candidates, key=rank)
    head["status"] = "REGISTERED"
    touch(head)
    fitness_class["waitlist_count"] -= 1
    fitness_class["registered_count"] += 1
    touch(fitness_class)
