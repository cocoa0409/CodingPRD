"""Leak-event construction and the auto-detection trigger (PRD 3.4)."""
import constants
import db
import util
from services import ledger


def open_leak_event(system, detected_at, detection_method,
                    triggering_service_record_id=None):
    """Create a leak event in OPEN and stamp its immutable deadline."""
    event = db.new_entity()
    initial_deadline = util.add_days(detected_at, constants.INITIAL_REPAIR_WINDOW_DAYS)
    event.update({
        "system_id": system["id"],
        "triggering_service_record_id": triggering_service_record_id,
        "detected_at": detected_at,
        "detection_method": detection_method,
        "leak_rate_pct_at_detection": system["leak_rate_pct"],
        "threshold_pct_applied": system["threshold_pct"],
        "status": "OPEN",
        "initial_repair_deadline": initial_deadline,
        "repair_deadline": initial_deadline,
        "verification_deadline": None,
        "extension_days_granted_total": 0,
        "extension_days_remaining": constants.EXTENSION_DAY_CAP,
        "repair_attempt_count": 0,
        "failed_verification_count": 0,
        "late_repair_flag": False,
        "last_repair_completed_at": None,
        "closed_at": None,
    })
    db.insert("leak_events", event)
    return event


def maybe_auto_open(system, record):
    """PRD 3.4: an exceedance opens an event unless one is already live.

    The comparison is inclusive: a leak rate exactly equal to the threshold
    trips the trigger. Only REGULATED systems are eligible.
    """
    if system["applicability"] != "REGULATED":
        return None
    if system["leak_rate_pct"] < system["threshold_pct"]:
        return None
    if ledger.non_terminal_event(system["id"]) is not None:
        return None
    return open_leak_event(system, record["performed_at"], "LEAK_RATE_CALCULATION",
                           triggering_service_record_id=record["id"])
