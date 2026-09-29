"""Schedule compliance scoring and host eligibility (PRD sections 3.4 and 3.5)."""

from datetime import timedelta

import calc
from db import db, touch

COUNTED_GAME_STATUSES = ("SCHEDULED", "PLAYED")


def _current_fiscal_year():
    conference = db.conference
    return conference["current_fiscal_year"] if conference else None


def _counted_games(fiscal_year):
    return [
        game
        for game in db.schedule_games.values()
        if game["fiscal_year"] == fiscal_year and game["status"] in COUNTED_GAME_STATUSES
    ]


def _rivalries_for(member_id):
    return [
        rivalry
        for rivalry in db.protected_rivalries.values()
        if rivalry["member_a_id"] == member_id or rivalry["member_b_id"] == member_id
    ]


def breakdown(member):
    """The whole compliance breakdown of PRD section 3.4."""
    fiscal_year = _current_fiscal_year()
    member_id = member["id"]

    if fiscal_year is None:
        return {
            "member_id": member_id,
            "unmet_rivalry_count": 0,
            "travel_partner_gap_count": 0,
            "home_game_count": 0,
            "away_game_count": 0,
            "schedule_compliance_score": calc.COMPLIANCE_BASE_SCORE,
        }

    games = _counted_games(fiscal_year)

    # Penalty one: unmet protected rivalries.
    unmet_rivalry_count = 0
    for rivalry in _rivalries_for(member_id):
        if rivalry["status"] == "LAPSED":
            unmet_rivalry_count += 1
            continue
        meetings = len(
            [game for game in games if game.get("protected_rivalry_id") == rivalry["id"]]
        )
        if meetings < rivalry["required_annual_meetings"]:
            unmet_rivalry_count += 1

    # Penalty two: travel-partner gaps.
    travel_partner_gap_count = 0
    partner_id = member.get("travel_partner_member_id")
    own_away_games = [game for game in games if game["away_member_id"] == member_id]
    if partner_id:
        partner_away_games = [
            game for game in games if game["away_member_id"] == partner_id
        ]
        window = timedelta(days=calc.TRAVEL_PAIR_WINDOW_DAYS)
        for game in own_away_games:
            paired = False
            for partner_game in partner_away_games:
                if partner_game["venue_id"] != game["venue_id"]:
                    continue
                delta = partner_game["game_date"] - game["game_date"]
                if delta < timedelta(0):
                    delta = -delta
                if delta <= window:
                    paired = True
                    break
            if not paired:
                travel_partner_gap_count += 1

    # Penalty three: home-schedule imbalance.
    home_game_count = len([game for game in games if game["home_member_id"] == member_id])
    away_game_count = len(own_away_games)
    imbalance = max(0, home_game_count - away_game_count - 1)

    score = (
        calc.COMPLIANCE_BASE_SCORE
        - calc.RIVALRY_PENALTY * unmet_rivalry_count
        - calc.TRAVEL_PARTNER_PENALTY * travel_partner_gap_count
        - calc.HOME_IMBALANCE_PENALTY * imbalance
    )
    score = max(0, score)

    return {
        "member_id": member_id,
        "unmet_rivalry_count": unmet_rivalry_count,
        "travel_partner_gap_count": travel_partner_gap_count,
        "home_game_count": home_game_count,
        "away_game_count": away_game_count,
        "schedule_compliance_score": score,
    }


def score(member):
    return breakdown(member)["schedule_compliance_score"]


def apply_host_eligibility(member):
    """PRD section 3.5: host eligibility oscillates with the recomputed score."""
    current = score(member)
    for event in db.championship_events.values():
        if event["host_member_id"] != member["id"]:
            continue
        if event["status"] == "SCHEDULED" and current < calc.HOST_MINIMUM_SCORE:
            event["status"] = "HOST_AT_RISK"
            touch(event)
        elif event["status"] == "HOST_AT_RISK" and current >= calc.HOST_MINIMUM_SCORE:
            event["status"] = "SCHEDULED"
            touch(event)


def recompute(member):
    """Persist a recomputed score and cascade into host eligibility."""
    if member is None:
        return
    current = score(member)
    if member.get("schedule_compliance_score") != current:
        member["schedule_compliance_score"] = current
        touch(member)
    apply_host_eligibility(member)


def recompute_many(members):
    seen = set()
    for member in members:
        if member is None or member["id"] in seen:
            continue
        seen.add(member["id"])
        recompute(member)


def lapse_rivalry_if_unmet(rivalry):
    """A rivalry with no non-cancelled meeting in the current year lapses."""
    if rivalry is None or rivalry["status"] != "ACTIVE":
        return False
    fiscal_year = _current_fiscal_year()
    remaining = [
        game
        for game in db.schedule_games.values()
        if game.get("protected_rivalry_id") == rivalry["id"]
        and game["fiscal_year"] == fiscal_year
        and game["status"] in COUNTED_GAME_STATUSES
    ]
    if remaining:
        return False
    rivalry["status"] = "LAPSED"
    touch(rivalry)
    return True


def counterparts(rivalry):
    return [
        db.members.get(rivalry["member_a_id"]),
        db.members.get(rivalry["member_b_id"]),
    ]
