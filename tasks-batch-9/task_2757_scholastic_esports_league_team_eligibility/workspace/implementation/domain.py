"""Domain calculations, derived-field reconciliation and the cascade machinery."""

import datetime as _dt
from decimal import Decimal

from store import (
    completed_years,
    db,
    dec,
    find,
    rhu,
    touch,
)

# ---- pinned constants -----------------------------------------------------
RATING_ORDINAL = {"E": 0, "E10": 1, "T": 2, "M": 3}

SEVERITY_WEIGHT = {"MINOR": 5, "MAJOR": 15, "SEVERE": 40}
TYPE_SURCHARGE = {
    "ACCOUNT_SHARING": 5,
    "SMURFING": 10,
    "CHEAT_DETECTION": 20,
    "SPECTATOR_CONDUCT": 0,
}
CLEAN_CREDIT_CAP = 10
CLEAN_CREDIT_STEP = 5
CLEAN_DAYS_PER_STEP = 30
INTEGRITY_SUSPENSION_FLOOR = Decimal("40")

POINTS_WIN = 3
POINTS_DRAW = 1
POINTS_LOSS = 0

BASE_AWARD_CENTS = 150000
SEED_BONUS_PER_RANK_CENTS = 45000
SEED_BONUS_RANK_CUTOFF = 5
SILVER_FLOOR_CENTS = 200000
GOLD_FLOOR_CENTS = 350000
ACADEMIC_MULTIPLIER = {
    "GOOD": Decimal("1.0"),
    "PROBATION": Decimal("0.5"),
    "UNEVALUATED": Decimal("0.0"),
    "INELIGIBLE": Decimal("0.0"),
}
PERFORMANCE_BONUS_RATE = {
    "BRONZE": Decimal("0.05"),
    "SILVER": Decimal("0.12"),
    "GOLD": Decimal("0.20"),
}

TEAM_COUNTERS = (
    "match_points",
    "wins",
    "losses",
    "draws",
    "forfeits_charged",
    "forfeit_wins",
    "games_won",
    "games_lost",
)


# ---------------------------------------------------------------------------
# generic write helper
# ---------------------------------------------------------------------------
def update(rec, **fields):
    """Write fields; refresh updated_at / version only when something changed."""
    changed = False
    for key, value in fields.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


# ---------------------------------------------------------------------------
# cross-entity resolution chains
# ---------------------------------------------------------------------------
def school_of(record):
    return find("school", record.get("school_id"))


def district_of_school(school):
    if school is None:
        return None
    return find("district", school.get("district_id"))


def district_of_student(student):
    return district_of_school(school_of(student))


def district_of_team(team):
    return district_of_school(school_of(team))


def season_of(record):
    return find("season", record.get("season_id"))


def slots_of_team(team_id):
    return [s for s in db.all("roster_slot") if s["team_id"] == team_id]


def slots_of_student(student_id):
    return [s for s in db.all("roster_slot") if s["student_id"] == student_id]


def teams_of_season(season_id):
    return [t for t in db.all("team") if t["season_id"] == season_id]


def matches_of_season(season_id):
    return [m for m in db.all("match") if m["season_id"] == season_id]


def matches_of_team(team_id):
    return [
        m
        for m in db.all("match")
        if m["home_team_id"] == team_id or m["away_team_id"] == team_id
    ]


def cases_of_team(team_id):
    return [c for c in db.all("fair_play_case") if c["team_id"] == team_id]


def live_approval(district_id, title_id):
    for approval in db.all("title_approval"):
        if (
            approval["district_id"] == district_id
            and approval["title_id"] == title_id
            and approval["status"] in ("PENDING", "APPROVED")
        ):
            return approval
    return None


def approved_approval(district_id, title_id):
    for approval in db.all("title_approval"):
        if (
            approval["district_id"] == district_id
            and approval["title_id"] == title_id
            and approval["status"] == "APPROVED"
        ):
            return approval
    return None


# ---------------------------------------------------------------------------
# academic standing evaluation
# ---------------------------------------------------------------------------
def evaluate_standing(student, district):
    """Return (effective_gpa, academic_standing, standing_basis_applied)."""
    basis = district["academic_standing_basis"] if district else "TERM_SNAPSHOT"
    latest_gpa = student.get("latest_term_gpa")
    if latest_gpa is None:
        return None, "UNEVALUATED", basis
    if basis == "TERM_SNAPSHOT":
        effective = rhu(latest_gpa, 3)
    else:
        latest_credits = dec(student.get("latest_term_credits") or 0)
        prior_gpa = dec(student.get("prior_term_gpa") or 0)
        prior_credits = dec(student.get("prior_term_credits") or 0)
        numerator = dec(latest_gpa) * latest_credits + prior_gpa * prior_credits
        denominator = latest_credits + prior_credits
        if denominator == 0:
            effective = rhu(latest_gpa, 3)
        else:
            effective = rhu(numerator / denominator, 3)
    min_gpa = rhu(district["min_gpa"], 3) if district else Decimal("2.000")
    floor_gpa = rhu(district["probation_gpa_floor"], 3) if district else Decimal("1.750")
    if effective >= min_gpa:
        standing = "GOOD"
    elif effective >= floor_gpa:
        standing = "PROBATION"
    else:
        standing = "INELIGIBLE"
    return effective, standing, basis


def apply_standing(student):
    """Recompute and persist the student's standing triple."""
    district = district_of_student(student)
    effective, standing, basis = evaluate_standing(student, district)
    update(
        student,
        effective_gpa=effective,
        academic_standing=standing,
        standing_basis_applied=basis if effective is not None else student.get("standing_basis_applied"),
    )
    return effective, standing, basis


# ---------------------------------------------------------------------------
# roster slot participation and team roll-ups
# ---------------------------------------------------------------------------
def derive_participation(slot):
    if slot.get("released_at") is not None:
        return "RELEASED"
    if slot.get("ineligibility_reason") is not None:
        return "INELIGIBLE"
    if (
        slot.get("verification_status") == "ENROLLMENT_VERIFIED"
        and slot.get("academic_status") == "CLEARED"
    ):
        return "ACTIVE"
    return "PROSPECTIVE"


def reconcile_slot(slot):
    update(slot, participation_status=derive_participation(slot))
    return slot


def recompute_team_rollups(team):
    if team is None:
        return
    season = season_of(team)
    max_starters = season["max_starters"] if season else 0
    slots = slots_of_team(team["id"])
    used = len(
        [
            s
            for s in slots
            if s["slot_role"] == "STARTER"
            and s["participation_status"] in ("PROSPECTIVE", "ACTIVE", "INELIGIBLE")
        ]
    )
    active = len(
        [
            s
            for s in slots
            if s["slot_role"] == "STARTER" and s["participation_status"] == "ACTIVE"
        ]
    )
    update(
        team,
        starter_slots_used=used,
        starter_slots_available=max_starters - used,
        active_starter_count=active,
    )


def reconcile_slot_and_team(slot):
    reconcile_slot(slot)
    recompute_team_rollups(find("team", slot["team_id"]))


# ---------------------------------------------------------------------------
# integrity scoring
# ---------------------------------------------------------------------------
def sustained_cases(team_id):
    cases = [
        c
        for c in cases_of_team(team_id)
        if c["status"] in ("SUSTAINED", "SUSTAINED_FINAL")
    ]
    cases.sort(key=lambda c: c["created_at"])
    return cases


def recompute_integrity(team):
    """Re-index the team's sustained set, restate penalties and rewrite the score."""
    cases = sustained_cases(team["id"])
    penalty = Decimal("0.00")
    for index, case in enumerate(cases, start=1):
        weight = dec(
            SEVERITY_WEIGHT.get(case.get("severity"), 0)
            + TYPE_SURCHARGE.get(case.get("case_type"), 0)
        )
        multiplier = Decimal("1.0") if index == 1 else (Decimal("1.5") if index == 2 else Decimal("2.0"))
        applied = rhu(weight * multiplier, 2)
        update(case, severity_weight=weight, repeat_index=index, applied_penalty=applied)
        penalty += applied
    if not cases:
        days_clean = 0
    else:
        last_decided = max(
            [c["decided_at"] for c in cases if c.get("decided_at") is not None]
            or [db.now]
        )
        elapsed = (db.now - last_decided).total_seconds()
        days_clean = int(elapsed // 86400) if elapsed > 0 else 0
    credit = min(CLEAN_CREDIT_CAP, (days_clean // CLEAN_DAYS_PER_STEP) * CLEAN_CREDIT_STEP)
    score = rhu(Decimal("100.00") - penalty + dec(credit), 2)
    if score < 0:
        score = Decimal("0.00")
    if score > 100:
        score = Decimal("100.00")
    update(team, integrity_score=score)
    return score


def select_sanction(case, score):
    if case.get("severity") == "SEVERE":
        sanction = "TEAM_SUSPENSION"
    elif case.get("subject_type") == "MATCH_BROADCAST":
        sanction = "WARNING"
    else:
        sanction = "STUDENT_SUSPENSION"
    if score < INTEGRITY_SUSPENSION_FLOOR:
        sanction = "TEAM_SUSPENSION"
    if score == 0:
        sanction = "DISQUALIFICATION"
    return sanction


# ---------------------------------------------------------------------------
# season seeding freshness
# ---------------------------------------------------------------------------
def mark_seeding_stale(season, teams=()):
    if season is None:
        return
    if season.get("seeding_state") == "SEEDED":
        update(season, seeding_state="STALE")
    for team in teams:
        if team is not None and team.get("seed_position") is not None:
            update(team, seed_stale=True)


def mark_all_seeded_stale(season):
    if season is None:
        return
    if season.get("seeding_state") == "SEEDED":
        update(season, seeding_state="STALE")
    for team in teams_of_season(season["id"]):
        if team.get("seed_position") is not None:
            update(team, seed_stale=True)


# ---------------------------------------------------------------------------
# match point award (revert-then-apply is pinned)
# ---------------------------------------------------------------------------
def _snap(team):
    if team is None:
        return None
    return dict((k, team[k]) for k in TEAM_COUNTERS)


def _settle(team, snapshot):
    if team is None or snapshot is None:
        return
    differential = team["games_won"] - team["games_lost"]
    changed = any(team[k] != snapshot[k] for k in TEAM_COUNTERS)
    if team.get("game_differential") != differential:
        changed = True
    team["game_differential"] = differential
    if changed:
        touch(team)


def _revert_award(match, home, away, season):
    award = match.get("_award")
    if not award:
        return
    if home is not None:
        home["match_points"] -= award["home_points"]
    if away is not None:
        away["match_points"] -= award["away_points"]
    if award["mode"] == "FORFEIT":
        winner = home if award["winner"] == "home" else away
        loser = away if award["winner"] == "home" else home
        if winner is not None:
            winner["forfeit_wins"] -= 1
        if loser is not None:
            loser["forfeits_charged"] -= 1
    else:
        if award["winner"] == "home":
            if home is not None:
                home["wins"] -= 1
            if away is not None:
                away["losses"] -= 1
        elif award["winner"] == "away":
            if away is not None:
                away["wins"] -= 1
            if home is not None:
                home["losses"] -= 1
        else:
            if home is not None:
                home["draws"] -= 1
            if away is not None:
                away["draws"] -= 1
        if home is not None:
            home["games_won"] -= award["home_games"]
            home["games_lost"] -= award["away_games"]
        if away is not None:
            away["games_won"] -= award["away_games"]
            away["games_lost"] -= award["home_games"]
    if season is not None:
        season["match_point_pool"] -= award["home_points"] + award["away_points"]
    match["_award"] = None


def _apply_award(match, home, away, season):
    if match["play_status"] == "FORFEITED":
        forfeiter = match.get("forfeiting_team_id")
        winner_side = "away" if forfeiter == match["home_team_id"] else "home"
        home_points = POINTS_WIN if winner_side == "home" else 0
        away_points = POINTS_WIN if winner_side == "away" else 0
        winner = home if winner_side == "home" else away
        loser = away if winner_side == "home" else home
        if winner is not None:
            winner["forfeit_wins"] += 1
        if loser is not None:
            loser["forfeits_charged"] += 1
        award = {
            "mode": "FORFEIT",
            "winner": winner_side,
            "home_points": home_points,
            "away_points": away_points,
            "home_games": 0,
            "away_games": 0,
        }
    else:
        home_games = match.get("home_games_won") or 0
        away_games = match.get("away_games_won") or 0
        if home_games > away_games:
            home_points, away_points, winner_side = POINTS_WIN, POINTS_LOSS, "home"
            if home is not None:
                home["wins"] += 1
            if away is not None:
                away["losses"] += 1
        elif home_games < away_games:
            home_points, away_points, winner_side = POINTS_LOSS, POINTS_WIN, "away"
            if away is not None:
                away["wins"] += 1
            if home is not None:
                home["losses"] += 1
        else:
            home_points, away_points, winner_side = POINTS_DRAW, POINTS_DRAW, None
            if home is not None:
                home["draws"] += 1
            if away is not None:
                away["draws"] += 1
        if home is not None:
            home["games_won"] += home_games
            home["games_lost"] += away_games
        if away is not None:
            away["games_won"] += away_games
            away["games_lost"] += home_games
        award = {
            "mode": "NORMAL",
            "winner": winner_side,
            "home_points": home_points,
            "away_points": away_points,
            "home_games": home_games,
            "away_games": away_games,
        }
    if home is not None:
        home["match_points"] += award["home_points"]
    if away is not None:
        away["match_points"] += award["away_points"]
    if season is not None:
        season["match_point_pool"] += award["home_points"] + award["away_points"]
    match["_award"] = award
    match["home_points_awarded"] = award["home_points"]
    match["away_points_awarded"] = award["away_points"]


def award_points(match):
    home = find("team", match["home_team_id"])
    away = find("team", match["away_team_id"])
    season = find("season", match["season_id"])
    snap_home, snap_away = _snap(home), _snap(away)
    pool_before = season["match_point_pool"] if season else None
    _revert_award(match, home, away, season)
    _apply_award(match, home, away, season)
    _settle(home, snap_home)
    _settle(away, snap_away)
    if season is not None and season["match_point_pool"] != pool_before:
        touch(season)
    touch(match)


def revert_award_only(match):
    home = find("team", match["home_team_id"])
    away = find("team", match["away_team_id"])
    season = find("season", match["season_id"])
    snap_home, snap_away = _snap(home), _snap(away)
    pool_before = season["match_point_pool"] if season else None
    _revert_award(match, home, away, season)
    match["home_points_awarded"] = 0
    match["away_points_awarded"] = 0
    _settle(home, snap_home)
    _settle(away, snap_away)
    if season is not None and season["match_point_pool"] != pool_before:
        touch(season)


# ---------------------------------------------------------------------------
# dispute window
# ---------------------------------------------------------------------------
def compute_dispute_deadline(match):
    if match.get("result_confirmed_at") is None:
        return None
    home = find("team", match["home_team_id"])
    district = district_of_team(home) if home else None
    hours = district["dispute_window_hours"] if district else 48
    return match["result_confirmed_at"] + _dt.timedelta(hours=hours)


# ---------------------------------------------------------------------------
# forfeits
# ---------------------------------------------------------------------------
def apply_forfeit(match, forfeiting_team_id, cause):
    season = find("season", match["season_id"])
    other = (
        match["away_team_id"]
        if forfeiting_team_id == match["home_team_id"]
        else match["home_team_id"]
    )
    match["play_status"] = "FORFEITED"
    match["result_status"] = "ADJUDICATED"
    match["winner_team_id"] = other
    match["forfeiting_team_id"] = forfeiting_team_id
    match["result_confirmed_at"] = db.now
    match["dispute_deadline_at"] = compute_dispute_deadline(match)
    match["_forfeit_cause"] = cause
    touch(match)
    award_points(match)
    mark_seeding_stale(
        season, [find("team", match["home_team_id"]), find("team", match["away_team_id"])]
    )


def forfeit_unplayed_for_team(team, cause):
    for match in matches_of_team(team["id"]):
        if match["play_status"] in ("SCHEDULED", "SERVER_READY"):
            apply_forfeit(match, team["id"], cause)


def restore_suspension_forfeit(match):
    revert_award_only(match)
    restored_play = "SERVER_READY" if match.get("region_code") else "SCHEDULED"
    match["_forfeit_cause"] = None
    update(
        match,
        play_status=restored_play,
        result_status="AWAITING_REPORTS",
        winner_team_id=None,
        forfeiting_team_id=None,
        result_confirmed_at=None,
        dispute_deadline_at=None,
        home_points_awarded=0,
        away_points_awarded=0,
    )
    touch(match)


# ---------------------------------------------------------------------------
# registration economics
# ---------------------------------------------------------------------------
def starter_line_slots(team):
    return [
        s
        for s in slots_of_team(team["id"])
        if s["slot_role"] == "STARTER"
        and s["participation_status"] in ("PROSPECTIVE", "ACTIVE", "INELIGIBLE")
    ]


def compute_entry_fee(team, season, district):
    """Per-line-item subsidy rounding is pinned: round each line, then sum."""
    line_items = [season["base_entry_fee_cents"]]
    line_items.extend([season["per_starter_fee_cents"]] * len(starter_line_slots(team)))
    pct = dec(district["subsidy_pct"]) if district else Decimal("0")
    subsidy = 0
    for item in line_items:
        subsidy += int(rhu(dec(item) * pct, 0))
    entry = sum(line_items)
    return entry, subsidy, entry - subsidy


# ---------------------------------------------------------------------------
# showcase scholarship projection (four pinned steps)
# ---------------------------------------------------------------------------
def project_scholarship(student, team):
    multiplier = ACADEMIC_MULTIPLIER.get(student.get("academic_standing"), Decimal("0"))
    base = int(rhu(dec(BASE_AWARD_CENTS) * multiplier, 0))
    seed_rank = team.get("seed_position")
    if seed_rank is None:
        seed_rank = SEED_BONUS_RANK_CUTOFF
    ranks_bettered = SEED_BONUS_RANK_CUTOFF - seed_rank
    if ranks_bettered < 0:
        ranks_bettered = 0
    provisional = base + SEED_BONUS_PER_RANK_CENTS * ranks_bettered
    if provisional >= GOLD_FLOOR_CENTS:
        tier = "GOLD"
    elif provisional >= SILVER_FLOOR_CENTS:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    bonus = int(rhu(dec(provisional) * PERFORMANCE_BONUS_RATE[tier], 0))
    return provisional, tier, provisional + bonus


# ---------------------------------------------------------------------------
# seeding
# ---------------------------------------------------------------------------
SEED_ELIGIBLE_STATUSES = ("COMPETING", "PLAYOFF_SEEDED", "ELIMINATED", "SUSPENDED")


def eligible_seed_teams(season):
    return [
        t for t in teams_of_season(season["id"]) if t["status"] in SEED_ELIGIBLE_STATUSES
    ]


def compute_seed_points(team, basis):
    if basis == "MATCH_POINT_BASIS":
        return rhu(dec(team["match_points"]), 4)
    denominator = team["wins"] + team["losses"] + team["draws"]
    if denominator == 0:
        return rhu(Decimal("0"), 4)
    return rhu(dec(team["wins"]) / dec(denominator), 4)


def _head_to_head_points(team, group_ids, season_id):
    total = 0
    for match in matches_of_season(season_id):
        if match["play_status"] not in ("FINALIZED", "FORFEITED"):
            continue
        if match["home_team_id"] not in group_ids or match["away_team_id"] not in group_ids:
            continue
        if match["home_team_id"] == team["id"]:
            total += match.get("home_points_awarded") or 0
        elif match["away_team_id"] == team["id"]:
            total += match.get("away_points_awarded") or 0
    return total


def order_seed_teams(teams, season):
    """Six pinned sort keys; head-to-head is recomputed per seed_points-tied group."""
    ranked = sorted(teams, key=lambda t: dec(t["seed_points"]), reverse=True)
    ordered = []
    index = 0
    while index < len(ranked):
        end = index + 1
        while end < len(ranked) and dec(ranked[end]["seed_points"]) == dec(ranked[index]["seed_points"]):
            end += 1
        group = ranked[index:end]
        group_ids = set(t["id"] for t in group)
        h2h = dict(
            (t["id"], _head_to_head_points(t, group_ids, season["id"])) for t in group
        )
        group.sort(
            key=lambda t: (
                -h2h[t["id"]],
                -(t["games_won"] - t["games_lost"]),
                t["forfeits_charged"],
                -dec(t["integrity_score"]),
                t["created_at"],
            )
        )
        ordered.extend(group)
        index = end
    return ordered


def run_seeding(season, basis):
    teams = eligible_seed_teams(season)
    for team in teams:
        recompute_integrity(team)
    for team in teams:
        update(team, seed_points=compute_seed_points(team, basis))
    ordered = order_seed_teams(teams, season)
    for position, team in enumerate(ordered, start=1):
        fields = {"seed_position": position, "seed_stale": False}
        if team["status"] != "SUSPENDED":
            fields["status"] = (
                "PLAYOFF_SEEDED" if position <= season["playoff_slots"] else "ELIMINATED"
            )
        update(team, **fields)
        touch(team)
    update(
        season,
        seed_order=[t["id"] for t in ordered],
        seeding_basis_applied=basis,
        seeding_state="SEEDED",
    )
    touch(season)
    return ordered


# ---------------------------------------------------------------------------
# fair-play sanction cascade and its inverse
# ---------------------------------------------------------------------------
def suspension_reason_for(team, case):
    season = season_of(team)
    if season is not None and team["active_starter_count"] < season["min_starters"]:
        return "ROSTER_MINIMUM_BREACH"
    if case is not None and case.get("sanction_type") in ("TEAM_SUSPENSION", "DISQUALIFICATION"):
        return "FAIR_PLAY_SANCTION"
    if dec(team["integrity_score"]) < INTEGRITY_SUSPENSION_FLOOR:
        return "INTEGRITY_FLOOR_BREACH"
    return None


def maybe_suspend_team(team, case):
    if team["status"] != "COMPETING":
        return False
    reason = suspension_reason_for(team, case)
    if reason is None:
        return False
    update(team, status="SUSPENDED", suspension_reason=reason)
    forfeit_unplayed_for_team(
        team,
        {
            "type": "SUSPENSION",
            "team_id": team["id"],
            "case_id": case["id"] if case is not None else None,
        },
    )
    return True


def sanction_student(student, case):
    """Cascade links 2-5 of a sustained STUDENT case."""
    update(student, fair_play_status="SANCTIONED")
    touched_teams = []
    for slot in slots_of_student(student["id"]):
        if slot["participation_status"] == "ACTIVE":
            update(slot, ineligibility_reason="FAIR_PLAY")
            reconcile_slot(slot)
            team = find("team", slot["team_id"])
            if team is not None and team not in touched_teams:
                touched_teams.append(team)
    for team in touched_teams:
        recompute_team_rollups(team)
    charged = find("team", case["team_id"])
    if charged is not None:
        recompute_team_rollups(charged)
        maybe_suspend_team(charged, case)


def clear_student(student, case):
    """Compensation links 2-5 of an overturned STUDENT case."""
    for other in db.all("fair_play_case"):
        if (
            other["id"] != case["id"]
            and other.get("subject_student_id") == student["id"]
            and other["status"] in ("SUSTAINED", "SUSTAINED_FINAL")
        ):
            return
    update(student, fair_play_status="CLEAR")
    touched_teams = []
    for slot in slots_of_student(student["id"]):
        if (
            slot["participation_status"] == "INELIGIBLE"
            and slot.get("ineligibility_reason") == "FAIR_PLAY"
            and slot.get("verification_status") == "ENROLLMENT_VERIFIED"
            and slot.get("academic_status") == "CLEARED"
        ):
            update(slot, ineligibility_reason=None)
            reconcile_slot(slot)
            team = find("team", slot["team_id"])
            if team is not None and team not in touched_teams:
                touched_teams.append(team)
    for team in touched_teams:
        recompute_team_rollups(team)


def maybe_restore_team(team, case):
    if team is None or team["status"] != "SUSPENDED":
        return
    season = season_of(team)
    if season is not None and team["active_starter_count"] < season["min_starters"]:
        return
    for other in sustained_cases(team["id"]):
        if other["sanction_type"] in ("TEAM_SUSPENSION", "DISQUALIFICATION"):
            return
    update(team, status="COMPETING", suspension_reason=None)
    for match in matches_of_team(team["id"]):
        cause = match.get("_forfeit_cause")
        if (
            match["play_status"] == "FORFEITED"
            and cause is not None
            and cause.get("type") == "SUSPENSION"
            and cause.get("team_id") == team["id"]
            and cause.get("case_id") == case["id"]
        ):
            restore_suspension_forfeit(match)


def release_all_slots(team):
    changed_any = False
    for slot in slots_of_team(team["id"]):
        if slot["participation_status"] != "RELEASED":
            update(slot, released_at=db.now)
            reconcile_slot(slot)
            changed_any = True
    if changed_any:
        recompute_team_rollups(team)


def disqualify_team(team):
    if team is None or team["status"] not in ("SUSPENDED", "COMPETING"):
        return
    update(team, status="DISQUALIFIED")
    release_all_slots(team)
    forfeit_unplayed_for_team(team, {"type": "DISQUALIFICATION", "team_id": team["id"]})
    mark_seeding_stale(season_of(team), [team])


# ---------------------------------------------------------------------------
# interval resources
# ---------------------------------------------------------------------------
def server_pool_conflict(pool_id, start_at, end_at, capacity, exclude_id=None):
    peers = [
        m
        for m in db.all("match")
        if m.get("server_pool_id") == pool_id
        and m["id"] != exclude_id
        and m["play_status"] in ("SCHEDULED", "SERVER_READY", "PLAYED")
    ]
    probes = [start_at]
    for peer in peers:
        peer_start = peer["scheduled_start_at"]
        if start_at <= peer_start < end_at:
            probes.append(peer_start)
    for instant in probes:
        occupancy = 1
        for peer in peers:
            if peer["scheduled_start_at"] <= instant < peer["scheduled_end_at"]:
                occupancy += 1
        if occupancy > capacity:
            return True
    return False


def broadcast_channel_conflict(school, start_at, end_at, exclude_id=None):
    district = district_of_school(school)
    buffer_minutes = district["broadcast_buffer_minutes"] if district else 15
    buffer = _dt.timedelta(minutes=buffer_minutes)
    candidate_start = start_at - buffer
    candidate_end = end_at + buffer
    conflicts = 0
    for peer in db.all("match"):
        if peer["id"] == exclude_id:
            continue
        if peer.get("broadcast_school_id") != school["id"]:
            continue
        if peer.get("broadcast_status") not in ("SCHEDULED", "LIVE", "SUSPENDED"):
            continue
        if (
            peer["broadcast_start_at"] <= candidate_end
            and peer["broadcast_end_at"] >= candidate_start
        ):
            conflicts += 1
    return conflicts >= school["concurrent_broadcast_capacity"]


def age_at_cutoff(birthdate, cutoff_date):
    return completed_years(birthdate, cutoff_date)
