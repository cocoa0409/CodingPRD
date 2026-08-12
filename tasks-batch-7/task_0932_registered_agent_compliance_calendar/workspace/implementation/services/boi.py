"""The federal beneficial-ownership axis (PRD 3.10)."""

import timeutil
from constants import (
    BOI_2024_BAND_START_DATE,
    BOI_2024_FORMATION_DAYS,
    BOI_2025_BAND_START_DATE,
    BOI_POST_2024_FORMATION_DAYS,
    BOI_PRE_2024_DEADLINE_DATE,
    BOI_UPDATE_DAYS,
    COMPANY_APPLICANT_CUTOVER_DATE,
)
from store import touch

_BAND_2024 = timeutil.parse_date(BOI_2024_BAND_START_DATE)
_BAND_2025 = timeutil.parse_date(BOI_2025_BAND_START_DATE)
_PRE_2024_DEADLINE = timeutil.parse_date(BOI_PRE_2024_DEADLINE_DATE)
_APPLICANT_CUTOVER = timeutil.parse_date(COMPANY_APPLICANT_CUTOVER_DATE)


def initial_deadline(formation_date, boi_exempt_class):
    """No weekend or holiday roll: this is a federal filing deadline.  Both
    band comparisons are strict."""
    if boi_exempt_class != "NONE":
        return None
    if formation_date < _BAND_2024:
        return _PRE_2024_DEADLINE
    if formation_date < _BAND_2025:
        return timeutil.add_days(formation_date, BOI_2024_FORMATION_DAYS)
    return timeutil.add_days(formation_date, BOI_POST_2024_FORMATION_DAYS)


def company_applicant_required(formation_date):
    return formation_date >= _APPLICANT_CUTOVER


def arm_update_clock(entity, change_date):
    """A reportable change arms the 30-day update clock -- but only when the
    axis is FILED, UPDATE_DUE or DELINQUENT, and never on an exempt entity.
    Returns True when the entity row actually moved."""
    if entity["boi_exempt_class"] != "NONE":
        return False
    if entity["boi_status"] not in ("FILED", "UPDATE_DUE", "DELINQUENT"):
        # while the axis is PENDING_INITIAL a reportable change arms nothing
        return False
    entity["boi_update_deadline"] = timeutil.add_days(change_date, BOI_UPDATE_DAYS)
    entity["boi_status"] = "UPDATE_DUE"
    entity["_boi_last_change_date"] = change_date
    return True


def apply_exempt_class_change(entity, new_class):
    """Returns True when the axis or a deadline actually moved."""
    moved = False
    previous = entity["boi_exempt_class"]
    entity["boi_exempt_class"] = new_class
    if new_class != "NONE":
        if entity["boi_status"] == "PENDING_INITIAL":
            entity["boi_status"] = "NOT_REQUIRED"
            entity["boi_initial_deadline"] = None
            entity["boi_update_deadline"] = None
            moved = True
        elif previous == "NONE":
            # The declared axis edge into NOT_REQUIRED originates at
            # PENDING_INITIAL only; from any other reading the class still
            # suppresses the deadlines it governs.
            entity["boi_initial_deadline"] = None
            entity["boi_update_deadline"] = None
            moved = True
    else:
        if entity["boi_status"] == "NOT_REQUIRED" and entity["lifecycle_status"] != "DISSOLVED":
            entity["boi_status"] = "PENDING_INITIAL"
            entity["boi_initial_deadline"] = initial_deadline(entity["formation_date"], "NONE")
            moved = True
    return moved


def record_accepted_report(entity):
    """An ACCEPTED outcome drives the axis to FILED and clears the update
    deadline.  Returns True when the entity actually moved."""
    if entity["boi_status"] == "NOT_REQUIRED":
        return False
    if entity["boi_status"] == "FILED" and entity["boi_update_deadline"] is None:
        return False
    entity["boi_status"] = "FILED"
    entity["boi_update_deadline"] = None
    return True


def advance_axis(entity, clock_date):
    """The ops-run drives the axis to DELINQUENT past its deadline.  On the
    deadline date itself the axis does not move."""
    if entity["boi_status"] == "UPDATE_DUE":
        deadline = entity["boi_update_deadline"]
        if deadline is not None and clock_date > deadline:
            entity["boi_status"] = "DELINQUENT"
            touch(entity)
            return True
    elif entity["boi_status"] == "PENDING_INITIAL":
        deadline = entity["boi_initial_deadline"]
        if deadline is not None and clock_date > deadline:
            entity["boi_status"] = "DELINQUENT"
            touch(entity)
            return True
    return False
