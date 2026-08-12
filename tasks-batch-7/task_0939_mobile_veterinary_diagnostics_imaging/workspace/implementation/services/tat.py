"""The turnaround clock (PRD 3.8) — anchor, target, elapsed, paused, accrued,
deadline and the strict breach test."""

from core import clock
from core.constants import (
    ROUTINE_TAT_TARGET_BUSINESS_MINUTES,
    STAT_TAT_TARGET_WALLCLOCK_MINUTES,
)
from services import derive
from services.timecalc import (
    advance_business_minutes,
    business_minutes_between,
    wall_minutes_between,
)


def target_minutes(study):
    if study["priority"] == "STAT":
        return STAT_TAT_TARGET_WALLCLOCK_MINUTES
    return ROUTINE_TAT_TARGET_BUSINESS_MINUTES


def anchor_at(study):
    if study.get("priority_source") == "NATIVE":
        return study["created_at"]
    acquired = study.get("acquired_at")
    if acquired is not None:
        return acquired
    return study.get("escalated_at")


def _minutes_in_mode(study, t0, t1):
    if study["priority"] == "STAT":
        return wall_minutes_between(t0, t1)
    return business_minutes_between(t0, t1, derive.clinic_of_study(study))


def paused_minutes(study):
    if study.get("_tat_frozen_paused") is not None:
        return study["_tat_frozen_paused"]
    total = 0
    for window in study.get("_pause_windows", []):
        total += _minutes_in_mode(study, window[0], window[1])
    if study.get("pause_started_at") is not None and study["tat_status"] == "PAUSED":
        total += _minutes_in_mode(study, study["pause_started_at"], clock.now())
    return total


def elapsed_minutes(study):
    if study.get("_tat_frozen_elapsed") is not None:
        return study["_tat_frozen_elapsed"]
    return _minutes_in_mode(study, anchor_at(study), clock.now())


def accrued_minutes(study):
    return elapsed_minutes(study) - paused_minutes(study)


def deadline_at(study):
    anchor = anchor_at(study)
    if anchor is None:
        return None
    budget = target_minutes(study) + paused_minutes(study)
    if study["priority"] == "STAT":
        return clock.plus_minutes(anchor, budget)
    return advance_business_minutes(anchor, budget, derive.clinic_of_study(study))


def _freeze(study):
    study["_tat_frozen_elapsed"] = elapsed_minutes(study)
    study["_tat_frozen_paused"] = paused_minutes(study)


def mark_breached(study):
    """Move the clock to BREACHED, freeze the figures, notify once."""
    from services import notify

    if study["tat_status"] == "BREACHED":
        return
    _freeze(study)
    study["tat_status"] = "BREACHED"
    if not study.get("_tat_breach_notified"):
        study["_tat_breach_notified"] = True
        notify.append(
            derive.clinic_id_of_study(study),
            study["id"],
            "TAT_BREACHED",
            "Turnaround breached for study %s." % study["id"],
        )


def mark_met(study):
    if study["tat_status"] in ("MET", "BREACHED"):
        return
    _freeze(study)
    study["tat_status"] = "MET"


def evaluate(study):
    """The strict breach test — run on every read of a study and after every
    mutation of it.  `accrued > target` breaches; `accrued == target` does not."""
    if study["tat_status"] in ("MET", "BREACHED"):
        return
    if accrued_minutes(study) > target_minutes(study):
        mark_breached(study)


def settle_on_final(study):
    """Publication of a FINAL report settles the axis (PRD 3.8)."""
    if study["tat_status"] in ("MET", "BREACHED"):
        return
    if accrued_minutes(study) <= target_minutes(study):
        mark_met(study)
    else:
        mark_breached(study)
