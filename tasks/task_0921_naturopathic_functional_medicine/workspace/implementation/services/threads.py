"""Message threads: service-level target and e-visit conversion eligibility."""

import config
from clock import clock, parse_instant
from services.dispensary import messaging_included


def sla_breached(thread):
    """Refreshed whenever the thread is read (PRD 2.4)."""
    due = parse_instant(thread.get("sla_due_at"))
    if due is None:
        return False
    first = parse_instant(thread.get("first_clinical_reply_at"))
    if first is not None:
        return first > due
    return clock.now() > due


def threshold_met(thread):
    return (
        thread["patient_message_count"] >= config.EVISIT_PATIENT_MESSAGE_THRESHOLD
        or thread["clinical_minutes_total"] >= config.EVISIT_CLINICAL_MINUTES_THRESHOLD
    )


def conversion_eligible(thread):
    """Volume threshold crossed AND the tier does not already pay for messaging."""
    return threshold_met(thread) and not messaging_included(thread["patient_id"])


def refresh(thread):
    thread["sla_breached"] = sla_breached(thread)
    thread["evisit_conversion_eligible"] = conversion_eligible(thread)
    return thread
