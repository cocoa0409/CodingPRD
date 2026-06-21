"""State-machine transitions and cascading side effects (SCAFFOLD §1.2, PRD §3).

Holds the cross-aggregate ripple logic: assignment -> slot -> game bubbling,
penalty assessment into the SeasonLedger, and game cancellation cascade.
"""
import db
from services import calc, derive
from services.intervals import game_interval


# ---- Game staffing-dimension bubbling -----------------------------------

def bubble_game_after_fill_change(game):
    """Recompute crew_filled_count and bubble OPEN<->STAFFED per PRD §2.5.

    - OPEN -> STAFFED when crew_filled_count reaches required_crew_size.
    - STAFFED -> OPEN when it drops below required_crew_size.
    A LOCKED game with a vacated slot simply stays LOCKED (PRD §3.7).
    """
    derive.recompute_game_filled_count(game)
    if game["status"] == "OPEN" and game["crew_filled_count"] == game["required_crew_size"]:
        game["status"] = "STAFFED"
        db.touch(game)
    elif game["status"] == "STAFFED" and game["crew_filled_count"] < game["required_crew_size"]:
        game["status"] = "OPEN"
        db.touch(game)


# ---- Penalty assessment --------------------------------------------------

def _prior_penalised_declines(official_id, this_assignment):
    """Count of this official's terminal assignments with
    penalty_assessed_points > 0 created BEFORE this one (created_at ASC)."""
    n = 0
    this_seq = this_assignment["_seq"]
    for a in db.assignments.values():
        if a["official_id"] != official_id:
            continue
        if a["id"] == this_assignment["id"]:
            continue
        if a["_seq"] >= this_seq:
            continue
        if a.get("penalty_assessed_points", 0) > 0:
            n += 1
    return n


def _prior_noshows(official_id, this_assignment):
    """Count of this official's NO_SHOW assignments created before this one."""
    n = 0
    this_seq = this_assignment["_seq"]
    for a in db.assignments.values():
        if a["official_id"] != official_id:
            continue
        if a["id"] == this_assignment["id"]:
            continue
        if a["_seq"] >= this_seq:
            continue
        if a["status"] == "NO_SHOW":
            n += 1
    return n


def assess_decline_penalty(assignment, official, game):
    """Compute and apply the decline penalty (PRD §3.8). Returns the points."""
    g_start, _ = game_interval(game)
    from clock import now
    delta_seconds = (g_start - now()).total_seconds()
    hours_to_game = delta_seconds / 3600.0
    prior = _prior_penalised_declines(official["id"], assignment)
    pts = calc.decline_penalty(hours_to_game, prior, bool(game.get("is_postseason")))
    assignment["penalty_assessed_points"] = pts
    _add_ledger_penalty(official, pts)
    return pts


def assess_no_show_penalty(assignment, official, game):
    """Compute and apply the no-show penalty (PRD §3.8). Returns the points.

    The transitioning assignment is already in NO_SHOW when prior no-shows are
    counted; the _prior_noshows helper excludes this assignment by id."""
    prior = _prior_noshows(official["id"], assignment)
    pts = calc.no_show_penalty(prior, bool(game.get("is_postseason")))
    assignment["penalty_assessed_points"] = pts
    _add_ledger_penalty(official, pts)
    return pts


def _add_ledger_penalty(official, points):
    led = derive.ledger_for(official["id"])
    if led is not None:
        led["penalty_points"] = led.get("penalty_points", 0) + points
        db.touch(led)


def reverse_ledger_penalty(official, points):
    led = derive.ledger_for(official["id"])
    if led is not None:
        led["penalty_points"] = max(0, led.get("penalty_points", 0) - points)
        db.touch(led)


# ---- Slot release on decline/withdraw/no-show ---------------------------

def vacate_slot(slot):
    """Return a slot to VACANT and clear its live assignment back-pointer."""
    slot["current_assignment_id"] = None
    slot["status"] = "VACANT"
    db.touch(slot)


def fill_slot(slot):
    slot["status"] = "FILLED"
    db.touch(slot)
