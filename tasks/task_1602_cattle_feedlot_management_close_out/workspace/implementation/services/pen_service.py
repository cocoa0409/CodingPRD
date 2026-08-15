"""Pen business logic: occupancy management, state transitions."""
import store
from util import bump


def recompute_pen_occupancy(pen):
    """Recompute pen's current_occupancy_head from ACTIVE assignments.

    Flips EMPTY <-> OCCUPIED automatically based on occupancy.
    """
    active_assignments = [
        pa for pa in store.pen_assignments.values()
        if pa["pen_id"] == pen["id"] and pa["status"] == "ACTIVE"
    ]
    new_occupancy = sum(pa["head_count"] for pa in active_assignments)
    old_status = pen["status"]

    pen["current_occupancy_head"] = new_occupancy

    # Auto state transitions
    if old_status == "EMPTY" and new_occupancy > 0:
        pen["status"] = "OCCUPIED"
        bump(pen)
    elif old_status == "OCCUPIED" and new_occupancy == 0:
        pen["status"] = "EMPTY"
        bump(pen)
    elif new_occupancy != pen.get("_last_occupancy", -1):
        # Occupancy changed but status didn't flip - still bump version
        bump(pen)

    pen["_last_occupancy"] = new_occupancy


def recompute_all_pen_occupancies():
    """Recompute all pen occupancies."""
    for pen in store.pens.values():
        recompute_pen_occupancy(pen)


def check_pen_not_maintenance(pen):
    """Raise ERR_PEN_IN_MAINTENANCE if pen is in MAINTENANCE."""
    from errors import raise_err, ERR_PEN_IN_MAINTENANCE
    if pen["status"] == "MAINTENANCE":
        raise_err(ERR_PEN_IN_MAINTENANCE, "Pen %s is in MAINTENANCE" % pen["id"])


def check_pen_occupied(pen):
    """Raise ERR_PEN_NOT_OCCUPIED if pen has no ACTIVE assignments."""
    from errors import raise_err, ERR_PEN_NOT_OCCUPIED
    if pen["status"] != "OCCUPIED" or pen["current_occupancy_head"] == 0:
        raise_err(ERR_PEN_NOT_OCCUPIED, "Pen %s is not OCCUPIED" % pen["id"])


def check_pen_empty_for_maintenance(pen):
    """Raise ERR_PEN_OCCUPIED if pen is OCCUPIED."""
    from errors import raise_err, ERR_PEN_OCCUPIED
    if pen["status"] == "OCCUPIED":
        raise_err(ERR_PEN_OCCUPIED, "Pen %s is OCCUPIED, cannot enter MAINTENANCE" % pen["id"])


def enter_maintenance(pen):
    """EMPTY -> MAINTENANCE."""
    check_pen_empty_for_maintenance(pen)
    if pen["status"] != "EMPTY":
        from errors import raise_err, ERR_INVALID_STATE_TRANSITION
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Pen %s cannot transition to MAINTENANCE from %s" % (pen["id"], pen["status"]))
    pen["status"] = "MAINTENANCE"
    bump(pen)


def exit_maintenance(pen):
    """MAINTENANCE -> EMPTY."""
    if pen["status"] != "MAINTENANCE":
        from errors import raise_err, ERR_INVALID_STATE_TRANSITION
        raise_err(ERR_INVALID_STATE_TRANSITION,
                  "Pen %s cannot transition to EMPTY from %s" % (pen["id"], pen["status"]))
    pen["status"] = "EMPTY"
    bump(pen)
