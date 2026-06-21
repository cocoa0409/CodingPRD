"""Derived / denormalized field reconciliation (PRD §2.5, §3.7, §3.11, §3.12).

These helpers recompute denormalized counters on the stored records and bump
version/updated_at when the owning resource's derived state changes
(PRD §2.4: "When a derived or denormalized field changes on a resource ...
that change is itself a mutation").
"""
import db
from services import calc


def ledger_for(official_id):
    """The singleton SeasonLedger row for an official (one per official per
    league). Returns the record dict or None."""
    for led in db.season_ledgers.values():
        if led["official_id"] == official_id:
            return led
    return None


def evaluations_for_official(official_id):
    """Evaluations tied to this official's COMPLETED assignments."""
    return [e for e in db.evaluations.values() if e["official_id"] == official_id]


def compute_games_worked(official_id):
    return sum(1 for a in db.assignments.values()
               if a["official_id"] == official_id and a["status"] == "COMPLETED")


def compute_noshow_count(official_id):
    """Count of this official's NO_SHOW assignments, excluding any whose
    no-show penalty was reversed by an UPHELD appeal (PRD §3.13: the upheld
    no-show is permanently dropped from noshow_count, which can in turn flip
    postseason_eligible)."""
    n = 0
    for a in db.assignments.values():
        if a["official_id"] != official_id:
            continue
        if a["status"] != "NO_SHOW":
            continue
        if a.get("noshow_excluded"):
            continue
        n += 1
    return n


def compute_mean_rating(official_id):
    scores = [e["score"] for e in evaluations_for_official(official_id)]
    return calc.mean_rating(scores)


def recompute_official_derived(official):
    """Recompute all denormalized official fields from ground truth and bump
    the official's version if anything changed. Returns the official."""
    led = ledger_for(official["id"])
    penalty_points = led["penalty_points"] if led else 0

    new_vals = {
        "games_worked_count": compute_games_worked(official["id"]),
        "noshow_count": compute_noshow_count(official["id"]),
        "penalty_points": penalty_points,
        "mean_rating": compute_mean_rating(official["id"]),
        "reliability_score": calc.reliability_score(penalty_points),
    }
    new_vals["postseason_eligible"] = _compute_eligible(official, new_vals)

    changed = any(official.get(k) != v for k, v in new_vals.items())
    official.update(new_vals)
    if changed:
        db.touch(official)
    return official


def _compute_eligible(official, vals):
    league = db.leagues.get(official["league_id"])
    if league is None:
        return False
    games = vals["games_worked_count"]
    mean = vals["mean_rating"]
    noshows = vals["noshow_count"]
    eligible = (
        games >= league["postseason_min_games"]
        and mean is not None and mean >= league["postseason_min_rating"]
        and noshows <= league["postseason_max_noshows"]
        and official["status"] == "ACTIVE"
    )
    return bool(eligible)


def compute_eligibility_breakdown(official):
    """Read-only recompute used by GET /officials/{id}/eligibility and the
    postseason offer gate. Does NOT mutate, returns a dict snapshot."""
    led = ledger_for(official["id"])
    penalty_points = led["penalty_points"] if led else 0
    vals = {
        "games_worked_count": compute_games_worked(official["id"]),
        "noshow_count": compute_noshow_count(official["id"]),
        "penalty_points": penalty_points,
        "mean_rating": compute_mean_rating(official["id"]),
        "reliability_score": calc.reliability_score(penalty_points),
    }
    vals["postseason_eligible"] = _compute_eligible(official, vals)
    return vals


def recompute_game_filled_count(game):
    """Recompute Game.crew_filled_count from FILLED slots; bump version if it
    changed. Returns the game."""
    cnt = sum(1 for s in db.crew_slots.values()
              if s["game_id"] == game["id"] and s["status"] == "FILLED")
    if game.get("crew_filled_count") != cnt:
        game["crew_filled_count"] = cnt
        db.touch(game)
    return game


def recompute_game_settlement_total(game):
    total = sum(a["final_pay_cents"] for a in db.assignments.values()
                if a["game_id"] == game["id"] and a["status"] == "COMPLETED")
    if game.get("settlement_total_cents") != total:
        game["settlement_total_cents"] = total
        db.touch(game)
    return game
