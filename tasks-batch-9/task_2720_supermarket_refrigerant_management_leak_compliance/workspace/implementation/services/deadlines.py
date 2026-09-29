"""Leak-event deadlines, the extension budget and attempt ordering (PRD 3.5, 3.6)."""
import constants
import db
import util


def event_attempts(leak_event_id):
    """Repair attempts of an event in canonical order (PRD 3.5)."""
    attempts = [
        attempt for attempt in db.values("repair_attempts")
        if attempt["leak_event_id"] == leak_event_id
    ]
    attempts.sort(key=lambda a: (a["repair_completed_at"], a["created_at"], a["_seq"]))
    return attempts


def event_tests(leak_event_id):
    tests = [
        test for test in db.values("verification_tests")
        if test["leak_event_id"] == leak_event_id
    ]
    tests.sort(key=lambda t: (t["performed_at"], t["created_at"], t["_seq"]))
    return tests


def current_attempt(event):
    """The event's current attempt: the newest one awaiting verification.

    Once an initial PASS has promoted that attempt to VERIFIED and the event to
    FOLLOWUP_PENDING, the follow-up test is filed against that same attempt, so
    it remains the current attempt for the follow-up stage.
    """
    attempts = event_attempts(event["id"])
    awaiting = [a for a in attempts if a["outcome"] == "AWAITING_VERIFICATION"]
    if awaiting:
        return awaiting[-1]
    if event["status"] == "FOLLOWUP_PENDING":
        verified = [a for a in attempts if a["outcome"] == "VERIFIED"]
        if verified:
            return verified[-1]
    return None


def approved_extension_days(leak_event_id, exclude_id=None):
    total = 0
    for request in db.values("extension_requests"):
        if request["leak_event_id"] != leak_event_id:
            continue
        if request["status"] != "APPROVED":
            continue
        if exclude_id is not None and request["id"] == exclude_id:
            continue
        if request["granted_days"]:
            total += int(request["granted_days"])
    return total


def recompute_extension_budget(event, exclude_id=None):
    """PRD 3.6: the granted total is re-summed from APPROVED requests, and the
    repair deadline is rebuilt from the immutable initial deadline."""
    total = approved_extension_days(event["id"], exclude_id=exclude_id)
    event["extension_days_granted_total"] = total
    event["extension_days_remaining"] = constants.EXTENSION_DAY_CAP - total
    event["repair_deadline"] = util.add_days(event["initial_repair_deadline"], total)
    return event["repair_deadline"]


def is_overdue(deadline, instant):
    """PRD 3.6: overdue is strict -- equality is on time."""
    return deadline is not None and deadline < instant
