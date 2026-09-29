"""Line-credit resolution, standings arithmetic, seeding and calendar geometry."""

from decimal import Decimal, ROUND_HALF_UP

from store import db, parse_instant

DEC3 = Decimal("0.001")

GAME_DIFF_COEFFICIENT = Decimal("0.50")
RECENCY_WINDOW_LINES = 6
REGULAR_LINE_WEIGHT = Decimal("1.0")
PLAYOFF_LINE_WEIGHT = Decimal("1.5")
MATCH_WIN_POINTS = 3
LINE_WIN_POINTS = 1
DEFAULT_SETS_PER_LINE = 2
DEFAULT_GAMES_PER_LINE = 12
DOUBLEHEADER_MIN_GAP_MINUTES = 240

OFFICIAL_RESULT_STATUSES = ("VERIFIED", "FINALIZED")
PROVISIONAL_RESULT_STATUSES = ("REPORTED", "VERIFIED", "FINALIZED")
OCCUPYING_SCHEDULE_STATUSES = ("SCHEDULED", "CONFIRMED", "PLAYED")


def round3(value):
    return Decimal(value).quantize(DEC3, rounding=ROUND_HALF_UP)


def team_default_threshold(lines_per_match):
    return -((-int(lines_per_match)) // 2)


def open_scorecard(match):
    """The scorecard currently carrying the match's report, if any."""
    best = None
    for card in db.scorecards.values():
        if card.get("match_id") != match["id"]:
            continue
        if card.get("status") == "VERIFIED":
            return card
        if card.get("status") in ("SUBMITTED", "AMENDED", "DISPUTED"):
            if best is None or (card.get("created_at"), card.get("_seq")) > (best.get("created_at"), best.get("_seq")):
                best = card
    return best


def verified_scorecard(match):
    for card in db.scorecards.values():
        if card.get("match_id") == match["id"] and card.get("status") == "VERIFIED":
            return card
    return None


def _line_figures(set_scores):
    home_sets = 0
    away_sets = 0
    home_games = 0
    away_games = 0
    for entry in set_scores or []:
        hg = int(entry.get("home_games") or 0)
        ag = int(entry.get("away_games") or 0)
        home_games += hg
        away_games += ag
        if hg > ag:
            home_sets += 1
        elif ag > hg:
            away_sets += 1
    return home_sets, away_sets, home_games, away_games


def resolve_credit(league, home_team_id, away_team_id, lines, forced_side=None, forced_kind=None):
    """Pinned five-step line-credit resolution of PRD 3.6."""
    count = int(league.get("lines_per_match") or 3)
    by_number = {}
    for line in lines or []:
        by_number[int(line.get("line_number"))] = line

    home_def = {}
    away_def = {}
    for number in range(1, count + 1):
        if forced_side == "BOTH":
            home_def[number] = True
            away_def[number] = True
        elif forced_side == "HOME":
            home_def[number] = True
            away_def[number] = False
        elif forced_side == "AWAY":
            home_def[number] = False
            away_def[number] = True
        else:
            side = (by_number.get(number) or {}).get("default_side")
            home_def[number] = side == "HOME"
            away_def[number] = side == "AWAY"

    home_def_count = sum(1 for n in home_def if home_def[n])
    away_def_count = sum(1 for n in away_def if away_def[n])
    threshold = team_default_threshold(count)
    home_team_default = home_def_count >= threshold
    away_team_default = away_def_count >= threshold

    results = []
    default_side = None
    if home_team_default and away_team_default:
        for number in range(1, count + 1):
            results.append(_entry(number, None, 0, 0, 0, 0, "TEAM_DEFAULT"))
        default_side = "BOTH"
    elif home_team_default:
        for number in range(1, count + 1):
            results.append(_entry(number, away_team_id, 0, DEFAULT_SETS_PER_LINE, 0,
                                  DEFAULT_GAMES_PER_LINE, "TEAM_DEFAULT"))
        default_side = "HOME"
    elif away_team_default:
        for number in range(1, count + 1):
            results.append(_entry(number, home_team_id, DEFAULT_SETS_PER_LINE, 0,
                                  DEFAULT_GAMES_PER_LINE, 0, "TEAM_DEFAULT"))
        default_side = "AWAY"
    else:
        for number in range(1, count + 1):
            if home_def[number]:
                results.append(_entry(number, away_team_id, 0, DEFAULT_SETS_PER_LINE, 0,
                                      DEFAULT_GAMES_PER_LINE, "LINE_DEFAULT"))
            elif away_def[number]:
                results.append(_entry(number, home_team_id, DEFAULT_SETS_PER_LINE, 0,
                                      DEFAULT_GAMES_PER_LINE, 0, "LINE_DEFAULT"))
            else:
                line = by_number.get(number) or {}
                hs, as_, hg, ag = _line_figures(line.get("set_scores"))
                credited = home_team_id if hs > as_ else (away_team_id if as_ > hs else None)
                results.append(_entry(number, credited, hs, as_, hg, ag, "PLAYED"))
        if home_def_count > 0 and away_def_count > 0:
            default_side = "BOTH"
        elif home_def_count > 0:
            default_side = "HOME"
        elif away_def_count > 0:
            default_side = "AWAY"

    totals = rollup(results, home_team_id, away_team_id)
    if forced_side is not None:
        totals["default_side"] = forced_side
        totals["default_kind"] = forced_kind
    else:
        totals["default_side"] = default_side
        totals["default_kind"] = "LINE_MAJORITY" if (home_team_default or away_team_default) else None
    totals["line_results"] = results
    return totals


def _entry(number, credited_to, home_sets, away_sets, home_games, away_games, source):
    return {
        "line_number": number,
        "credited_to": credited_to,
        "home_sets": home_sets,
        "away_sets": away_sets,
        "home_games": home_games,
        "away_games": away_games,
        "credit_source": source,
    }


def rollup(results, home_team_id, away_team_id):
    home_lines = sum(1 for r in results if r["credited_to"] == home_team_id)
    away_lines = sum(1 for r in results if r["credited_to"] == away_team_id)
    totals = {
        "home_lines_won": home_lines,
        "away_lines_won": away_lines,
        "home_sets_won": sum(r["home_sets"] for r in results),
        "away_sets_won": sum(r["away_sets"] for r in results),
        "home_games_won": sum(r["home_games"] for r in results),
        "away_games_won": sum(r["away_games"] for r in results),
    }
    if home_lines > away_lines:
        totals["winner_team_id"] = home_team_id
    elif away_lines > home_lines:
        totals["winner_team_id"] = away_team_id
    else:
        totals["winner_team_id"] = None
    return totals


def forfeit_credit(league, home_team_id, away_team_id, aggrieved_team_id):
    count = int(league.get("lines_per_match") or 3)
    results = []
    for number in range(1, count + 1):
        if aggrieved_team_id == home_team_id:
            results.append(_entry(number, home_team_id, DEFAULT_SETS_PER_LINE, 0,
                                  DEFAULT_GAMES_PER_LINE, 0, "FORFEIT"))
        else:
            results.append(_entry(number, away_team_id, 0, DEFAULT_SETS_PER_LINE, 0,
                                  DEFAULT_GAMES_PER_LINE, "FORFEIT"))
    totals = rollup(results, home_team_id, away_team_id)
    totals["line_results"] = results
    return totals


# ------------------------------------------------------------- standings ---

def match_figures(match, team_id):
    """Per-match (lines, sets, games) for/against for one side, from stored fields."""
    is_home = match.get("home_team_id") == team_id
    if is_home:
        return (match.get("home_lines_won") or 0, match.get("away_lines_won") or 0,
                match.get("home_sets_won") or 0, match.get("away_sets_won") or 0,
                match.get("home_games_won") or 0, match.get("away_games_won") or 0)
    return (match.get("away_lines_won") or 0, match.get("home_lines_won") or 0,
            match.get("away_sets_won") or 0, match.get("home_sets_won") or 0,
            match.get("away_games_won") or 0, match.get("home_games_won") or 0)


def team_matches(team):
    rows = []
    for match in db.matches.values():
        if match.get("league_id") != team.get("league_id"):
            continue
        if team["id"] in (match.get("home_team_id"), match.get("away_team_id")):
            rows.append(match)
    return rows


def carries_forfeit_credit(match):
    """A voided match still holding the forfeit credit granted by a PRD 3.8 remedy."""
    if match.get("result_status") != "VOIDED":
        return False
    entries = match.get("line_results") or []
    return bool(entries) and all(e.get("credit_source") == "FORFEIT" for e in entries)


def standings_figures(team, basis="official"):
    inclusion = OFFICIAL_RESULT_STATUSES if basis == "official" else PROVISIONAL_RESULT_STATUSES
    league = db.leagues.get(team.get("league_id")) or {}
    agg = {"matches_won": 0, "matches_lost": 0, "lines_won": 0, "lines_lost": 0,
           "sets_won": 0, "sets_lost": 0, "games_won": 0, "games_lost": 0,
           "standings_points": 0}
    for match in team_matches(team):
        status = match.get("result_status")
        if status not in inclusion:
            # PRD 3.8 applies the forfeit credit to the aggrieved team, which "gains 3
            # lines, 6 sets and 36 games" while the forfeiting team takes the mirror
            # losses. A voided match is not decided under PRD 2.11, so ledger invariant
            # A forbids it contributing a match win or loss.
            if not carries_forfeit_credit(match):
                continue
            lf, la, sf, sa, gf, ga = match_figures(match, team["id"])
            agg["lines_won"] += lf
            agg["lines_lost"] += la
            agg["sets_won"] += sf
            agg["sets_lost"] += sa
            agg["games_won"] += gf
            agg["games_lost"] += ga
            continue
        if status == "REPORTED":
            card = open_scorecard(match)
            totals = resolve_credit(league, match.get("home_team_id"), match.get("away_team_id"),
                                    (card or {}).get("lines") or [])
            view = dict(match)
            view.update({k: totals[k] for k in ("home_lines_won", "away_lines_won", "home_sets_won",
                                                "away_sets_won", "home_games_won", "away_games_won",
                                                "winner_team_id")})
        else:
            view = match
        lf, la, sf, sa, gf, ga = match_figures(view, team["id"])
        winner = view.get("winner_team_id")
        if winner == team["id"]:
            agg["matches_won"] += 1
        elif winner is not None:
            agg["matches_lost"] += 1
        agg["lines_won"] += lf
        agg["lines_lost"] += la
        agg["sets_won"] += sf
        agg["sets_lost"] += sa
        agg["games_won"] += gf
        agg["games_lost"] += ga
    agg["standings_points"] = MATCH_WIN_POINTS * agg["matches_won"] + LINE_WIN_POINTS * agg["lines_won"]
    return agg


# --------------------------------------------------------------- seeding ---

def seeding_candidates(league):
    minimum = int(league.get("min_playoff_eligible_players") or 0)
    out = []
    for team in db.teams.values():
        if team.get("league_id") != league["id"]:
            continue
        if team.get("status") != "IN_PLAY":
            continue
        if not team.get("roster_compliant"):
            continue
        if (team.get("playoff_eligible_roster_size") or 0) < minimum:
            continue
        if (team.get("matches_won") or 0) + (team.get("matches_lost") or 0) < 1:
            continue
        out.append(team)
    return out


def _head_to_head(team, group_ids):
    total = 0
    for match in db.matches.values():
        if match.get("result_status") not in OFFICIAL_RESULT_STATUSES:
            continue
        home = match.get("home_team_id")
        away = match.get("away_team_id")
        if home not in group_ids or away not in group_ids:
            continue
        if team["id"] == home:
            total += match.get("home_lines_won") or 0
        elif team["id"] == away:
            total += match.get("away_lines_won") or 0
    return total


def rank_candidates(candidates):
    """Six ranking keys of PRD 3.9, head-to-head scoped to the tie group."""
    primary = sorted(candidates, key=lambda t: (-(t.get("standings_points") or 0),
                                                -(t.get("matches_won") or 0)))
    ordered = []
    index = 0
    while index < len(primary):
        key = ((primary[index].get("standings_points") or 0), (primary[index].get("matches_won") or 0))
        group = []
        while index < len(primary) and ((primary[index].get("standings_points") or 0),
                                       (primary[index].get("matches_won") or 0)) == key:
            group.append(primary[index])
            index += 1
        group_ids = set(t["id"] for t in group)
        ordered.extend(sorted(
            group,
            key=lambda t: (-_head_to_head(t, group_ids),
                           -((t.get("sets_won") or 0) - (t.get("sets_lost") or 0)),
                           -((t.get("games_won") or 0) - (t.get("games_lost") or 0)),
                           t.get("created_at") or "",
                           t.get("_seq") or 0)))
    return ordered


# -------------------------------------------------------------- calendar ---

def occupancy_end(match, facility):
    league = db.leagues.get(match.get("league_id")) or {}
    start = parse_instant(match.get("scheduled_start_at"))
    minutes = int(league.get("match_duration_minutes") or 0) + int(facility.get("turnaround_buffer_minutes") or 0)
    from datetime import timedelta
    return start + timedelta(minutes=minutes)


def intervals_intersect(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def facility_capacity_available(facility, league, match_id, start, end, courts_required):
    used = 0
    for other in db.matches.values():
        if other["id"] == match_id:
            continue
        if other.get("facility_id") != facility["id"]:
            continue
        if other.get("schedule_status") not in OCCUPYING_SCHEDULE_STATUSES:
            continue
        if not other.get("scheduled_start_at"):
            continue
        other_start = parse_instant(other.get("scheduled_start_at"))
        other_end = occupancy_end(other, facility)
        if intervals_intersect(start, end, other_start, other_end):
            used += int(other.get("courts_required") or 0)
    return used + int(courts_required) <= int(facility.get("court_count") or 0)


def team_has_conflict(team_id, league, match_id, start):
    from datetime import timedelta
    duration = int(league.get("match_duration_minutes") or 0)
    allow = bool(league.get("allow_same_day_doubleheader"))
    req_end = start + timedelta(minutes=duration)
    for other in db.matches.values():
        if other["id"] == match_id:
            continue
        if team_id not in (other.get("home_team_id"), other.get("away_team_id")):
            continue
        if other.get("schedule_status") not in OCCUPYING_SCHEDULE_STATUSES:
            continue
        if not other.get("scheduled_start_at"):
            continue
        other_start = parse_instant(other.get("scheduled_start_at"))
        if not allow:
            if other_start.date() == start.date():
                return True
            continue
        gap = abs(int((other_start - start).total_seconds() // 60))
        if gap <= DOUBLEHEADER_MIN_GAP_MINUTES:
            return True
        other_league = db.leagues.get(other.get("league_id")) or {}
        other_end = other_start + timedelta(minutes=int(other_league.get("match_duration_minutes") or 0))
        if intervals_intersect(start, req_end, other_start, other_end):
            return True
    return False
