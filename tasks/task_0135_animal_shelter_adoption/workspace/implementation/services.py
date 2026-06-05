"""Shared business-logic services: kennel occupancy, board release, animal cascades.

These helpers are invoked by route handlers under db.LOCK so each cascade is atomic
within its triggering request (PRD §2.5).
"""
import calculations
import clock
import db


# --------------------------------------------------------------------------
# Shelter / singleton config
# --------------------------------------------------------------------------
def get_shelter():
    """Return the single shelter config, or None if not yet bootstrapped.

    The system is described as a singleton config; if multiple were ever created we
    return the most recently created so fee calcs read live policy. In practice tests
    bootstrap exactly one.
    """
    if not db.shelters:
        return None
    # last inserted
    return list(db.shelters.values())[-1]


# --------------------------------------------------------------------------
# Kennel occupancy derivations
# --------------------------------------------------------------------------
def recompute_kennel(kennel):
    """Recompute occupied_count (count of ACTIVE assignments) and OPEN/FULL status."""
    count = sum(
        1 for a in db.kennel_assignments.values()
        if a["kennel_id"] == kennel["id"] and a["status"] == "ACTIVE"
    )
    kennel["occupied_count"] = count
    kennel["status"] = "FULL" if count >= kennel["capacity"] else "OPEN"


# --------------------------------------------------------------------------
# Foster home occupancy
# --------------------------------------------------------------------------
def recompute_foster_home(home):
    """Recompute active_placement_count (count of ACTIVE placements at the home)."""
    count = sum(
        1 for p in db.foster_placements.values()
        if p["foster_home_id"] == home["id"] and p["status"] == "ACTIVE"
    )
    home["active_placement_count"] = count


# --------------------------------------------------------------------------
# Kennel assignment release (manual or cascade tail)
# --------------------------------------------------------------------------
def release_assignment(assignment):
    """Release an ACTIVE assignment: set end_at, compute board, decrement kennel, bump.

    Caller must ensure assignment is ACTIVE. Updates the kennel's occupied_count,
    status, updated_at and version (kennel is a touched, versioned entity).
    """
    now = clock.now()
    animal = db.animals[assignment["animal_id"]]
    shelter = get_shelter()
    daily_base = _daily_base_for(animal, shelter)

    assignment["end_at"] = clock.to_iso(now)
    assignment["status"] = "RELEASED"
    # Board cost uses real start/end interval.
    start_dt = clock.parse_iso(assignment["start_at"])
    assignment["actual_board_cents"] = calculations.board_cost_cents(daily_base, start_dt, now)
    db.touch(assignment)

    kennel = db.kennels.get(assignment["kennel_id"])
    if kennel is not None:
        recompute_kennel(kennel)
        db.touch(kennel)


def release_active_assignment_for_animal(animal_id):
    """Release the animal's currently ACTIVE kennel assignment, if any (cascade tail)."""
    for assignment in db.kennel_assignments.values():
        if assignment["animal_id"] == animal_id and assignment["status"] == "ACTIVE":
            release_assignment(assignment)
            return assignment
    return None


def _daily_base_for(animal, shelter):
    if animal["species"] == "DOG":
        return shelter["dog_daily_board_cents"]
    return shelter["cat_daily_board_cents"]
