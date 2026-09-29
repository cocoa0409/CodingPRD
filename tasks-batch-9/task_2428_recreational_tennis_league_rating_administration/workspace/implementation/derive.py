"""Derived counters, the dynamic rating engine and the cascade recomputations."""

from decimal import Decimal

import credit
from credit import round3, verified_scorecard
from store import db, touch

LEVEL_FLOOR = Decimal("2.5")
LEVEL_CEILING = Decimal("5.0")


def _dec(value):
    return None if value is None else Decimal(str(value))


def _card_line(card, line_number):
    for line in (card or {}).get("lines") or []:
        if int(line.get("line_number")) == int(line_number):
            return line
    return None


def counted_lines(player_id, team_id=None):
    """The counted-line set of PRD 3.2 (optionally restricted to one team)."""
    out = []
    for match in db.matches.values():
        if match.get("result_status") not in credit.OFFICIAL_RESULT_STATUSES:
            continue
        card = verified_scorecard(match)
        if card is None:
            continue
        for entry in match.get("line_results") or []:
            if entry.get("credit_source") != "PLAYED":
                continue
            line = _card_line(card, entry.get("line_number"))
            if line is None:
                continue
            if player_id in (line.get("home_player_ids") or []):
                side = "home"
            elif player_id in (line.get("away_player_ids") or []):
                side = "away"
            else:
                continue
            side_team = match.get("home_team_id") if side == "home" else match.get("away_team_id")
            if team_id is not None and side_team != team_id:
                continue
            out.append({"match": match, "entry": entry, "line": line, "side": side,
                        "team_id": side_team})
    return out


def _pinned_level(opponent_id, opposing_team_id):
    best = None
    for spot in db.roster_spots.values():
        if spot.get("team_id") != opposing_team_id or spot.get("player_id") != opponent_id:
            continue
        if spot.get("level_at_add") is not None:
            return _dec(spot.get("level_at_add"))
        best = spot
    if best is not None:
        player = db.players.get(opponent_id) or {}
        return _dec(player.get("rating_level"))
    player = db.players.get(opponent_id) or {}
    return _dec(player.get("rating_level"))


def line_rating(player_id, item):
    match = item["match"]
    entry = item["entry"]
    line = item["line"]
    if item["side"] == "home":
        opponents = list(line.get("away_player_ids") or [])
        opposing_team = match.get("away_team_id")
        games_for = int(entry.get("home_games") or 0)
        games_against = int(entry.get("away_games") or 0)
    else:
        opponents = list(line.get("home_player_ids") or [])
        opposing_team = match.get("home_team_id")
        games_for = int(entry.get("away_games") or 0)
        games_against = int(entry.get("home_games") or 0)
    levels = []
    for opponent in opponents:
        level = _pinned_level(opponent, opposing_team)
        levels.append(level if level is not None else Decimal("0"))
    if not levels:
        return None
    pinned = round3(sum(levels) / Decimal(len(levels)))
    total = games_for + games_against
    ratio = Decimal("0") if total == 0 else (Decimal(games_for - games_against) / Decimal(total))
    return round3(pinned + credit.GAME_DIFF_COEFFICIENT * ratio)


def dynamic_rating(player_id, variant="provisional"):
    items = counted_lines(player_id)
    if not items:
        return None
    if variant == "provisional":
        items = sorted(items,
                       key=lambda i: (i["match"].get("scheduled_start_at") or "",
                                      i["match"].get("created_at") or "",
                                      -int(i["entry"].get("line_number"))),
                       reverse=True)[:credit.RECENCY_WINDOW_LINES]
        weighted = [(credit.REGULAR_LINE_WEIGHT, line_rating(player_id, i)) for i in items]
    else:
        weighted = []
        for item in items:
            stage = item["match"].get("stage")
            weight = credit.PLAYOFF_LINE_WEIGHT if stage == "PLAYOFF" else credit.REGULAR_LINE_WEIGHT
            weighted.append((weight, line_rating(player_id, item)))
    weighted = [(w, r) for (w, r) in weighted if r is not None]
    if not weighted:
        return None
    numerator = sum(w * r for (w, r) in weighted)
    denominator = sum(w for (w, _) in weighted)
    if denominator == 0:
        return None
    return round3(numerator / denominator)


def recompute_player_ratings(player):
    items = counted_lines(player["id"])
    matches = set(i["match"]["id"] for i in items)
    value = dynamic_rating(player["id"], "provisional")
    changed = (player.get("verified_match_count") != len(matches)
               or player.get("verified_line_count") != len(items)
               or player.get("dynamic_rating") != (float(value) if value is not None else None))
    player["verified_match_count"] = len(matches)
    player["verified_line_count"] = len(items)
    player["dynamic_rating"] = float(value) if value is not None else None
    if changed:
        touch(player)
    return player


def recompute_roster_spot(spot):
    section = _section_of_team(db.teams.get(spot.get("team_id")))
    minimum = int((section or {}).get("min_matches_for_playoff_eligibility") or 1)
    items = counted_lines(spot.get("player_id"), spot.get("team_id"))
    matches = set(i["match"]["id"] for i in items)
    eligible = len(matches) >= minimum
    changed = (spot.get("verified_match_count") != len(matches)
               or spot.get("playoff_eligible") != eligible)
    spot["verified_match_count"] = len(matches)
    spot["playoff_eligible"] = eligible
    if changed:
        touch(spot)
    return spot


def _section_of_team(team):
    if team is None:
        return None
    league = db.leagues.get(team.get("league_id"))
    if league is None:
        return None
    return db.sections.get(league.get("section_id"))


def recompute_team_roster(team):
    if team is None:
        return None
    league = db.leagues.get(team.get("league_id")) or {}
    active = 0
    eligible = 0
    for spot in db.roster_spots.values():
        if spot.get("team_id") != team["id"]:
            continue
        if spot.get("status") == "ACTIVE":
            active += 1
            if spot.get("playoff_eligible"):
                eligible += 1
    compliant = active >= int(league.get("min_active_roster_size") or 0)
    changed = (team.get("active_roster_size") != active
               or team.get("playoff_eligible_roster_size") != eligible
               or team.get("roster_compliant") != compliant)
    team["active_roster_size"] = active
    team["playoff_eligible_roster_size"] = eligible
    team["roster_compliant"] = compliant
    if changed:
        touch(team)
    return team


def recompute_team_standings(team):
    if team is None:
        return None
    figures = credit.standings_figures(team, "official")
    changed = any(team.get(key) != value for key, value in figures.items())
    team.update(figures)
    if changed:
        touch(team)
    return team


def recompute_league_counters(league):
    if league is None:
        return None
    registered = 0
    noncompliant = 0
    seeded = 0
    for team in db.teams.values():
        if team.get("league_id") != league["id"]:
            continue
        if team.get("status") in ("REGISTERED", "ROSTER_LOCKED", "IN_PLAY", "ELIMINATED", "ADVANCED"):
            registered += 1
        if team.get("status") in ("ROSTER_LOCKED", "IN_PLAY") and not team.get("roster_compliant"):
            noncompliant += 1
        if team.get("playoff_seed") is not None:
            seeded += 1
    finalized = sum(1 for m in db.matches.values()
                    if m.get("league_id") == league["id"] and m.get("result_status") == "FINALIZED")
    figures = {"registered_team_count": registered, "noncompliant_team_count": noncompliant,
               "seeded_team_count": seeded, "finalized_match_count": finalized}
    changed = any(league.get(key) != value for key, value in figures.items())
    league.update(figures)
    if changed:
        touch(league)
    return league


# ------------------------------------------------------------ result cascade ---

def cascade_result_change(match):
    """Levels 2-5 of the verification cascade (PRD 3.6)."""
    league = db.leagues.get(match.get("league_id"))
    teams = []
    for side in ("home_team_id", "away_team_id"):
        team = db.teams.get(match.get(side))
        if team is not None:
            teams.append(team)

    player_ids = set()
    for card in db.scorecards.values():
        if card.get("match_id") != match["id"]:
            continue
        for line in card.get("lines") or []:
            for pid in (line.get("home_player_ids") or []) + (line.get("away_player_ids") or []):
                player_ids.add(pid)

    for team in teams:
        recompute_team_standings(team)

    for pid in sorted(player_ids):
        player = db.players.get(pid)
        if player is not None:
            recompute_player_ratings(player)

    for spot in list(db.roster_spots.values()):
        if spot.get("player_id") in player_ids and spot.get("team_id") in [t["id"] for t in teams]:
            recompute_roster_spot(spot)

    for team in teams:
        recompute_team_roster(team)

    recompute_league_counters(league)


# ------------------------------------------------------------- strike ledger ---

def recompute_strike_ledger(player, source_strike_id=None):
    section = db.sections.get(player.get("section_id")) or {}
    total = 0
    for strike in db.strikes.values():
        if strike.get("player_id") == player["id"] and strike.get("status") == "ACTIVE":
            total += int(strike.get("weight") or 0)
    previous_status = player.get("status")
    new_status = previous_status
    if total >= int(section.get("disqualification_strike_limit") or 6):
        new_status = "DISQUALIFIED"
    elif total >= int(section.get("strike_limit") or 3):
        new_status = "STRIKE_SUSPENDED" if previous_status != "DISQUALIFIED" else "DISQUALIFIED"
    elif previous_status == "STRIKE_SUSPENDED":
        new_status = "ACTIVE"
    if previous_status == "DISQUALIFIED":
        new_status = "DISQUALIFIED"

    changed = player.get("strike_count") != total or previous_status != new_status
    player["strike_count"] = total
    player["status"] = new_status
    if changed:
        touch(player)

    if new_status in ("STRIKE_SUSPENDED", "DISQUALIFIED") and previous_status == "ACTIVE":
        suspend_roster_spots(player, "PLAYER_SUSPENDED", source_strike_id)
    return player


def suspend_roster_spots(player, reason, source_strike_id=None, league_filter=None):
    teams = {}
    for spot in list(db.roster_spots.values()):
        if spot.get("player_id") != player["id"] or spot.get("status") != "ACTIVE":
            continue
        team = db.teams.get(spot.get("team_id"))
        if team is None:
            continue
        if league_filter is not None and not league_filter(team):
            continue
        spot["status"] = "INELIGIBLE"
        spot["ineligible_reason"] = reason
        spot["source_strike_id"] = source_strike_id
        touch(spot)
        teams[team["id"]] = team
    leagues = {}
    for team in teams.values():
        recompute_team_roster(team)
        league = db.leagues.get(team.get("league_id"))
        if league is not None:
            leagues[league["id"]] = league
    for league in leagues.values():
        recompute_league_counters(league)
    return list(teams.values())


STRIKE_WEIGHTS = {
    "SELF_RATE_VIOLATION": 2,
    "INELIGIBLE_LINEUP": 2,
    "NO_SHOW_DEFAULT": 1,
    "SCORECARD_FALSIFICATION": 3,
}


def issue_strike(player, kind, reason, match_id=None, source_grievance_id=None):
    from store import insert, new_id
    record = {
        "id": new_id(),
        "player_id": player["id"],
        "match_id": match_id,
        "source_grievance_id": source_grievance_id,
        "kind": kind,
        "weight": STRIKE_WEIGHTS[kind],
        "status": "ACTIVE",
        "reason": reason,
        "rescinded_reason": None,
    }
    insert("strikes", record)
    recompute_strike_ledger(player, record["id"])
    return record


def append_rating_history(player, source, level, dynamic, effective_season_year, recorded_at):
    history = player.setdefault("rating_history", [])
    history.append({
        "source": source,
        "level": float(level) if level is not None else None,
        "dynamic_rating": float(dynamic) if dynamic is not None else None,
        "effective_season_year": effective_season_year,
        "recorded_at": recorded_at,
    })


def clamp_level(value):
    if value < LEVEL_FLOOR:
        return LEVEL_FLOOR
    if value > LEVEL_CEILING:
        return LEVEL_CEILING
    return value
