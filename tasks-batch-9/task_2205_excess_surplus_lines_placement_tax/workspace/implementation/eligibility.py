"""White-list window semantics (PRD 2.11 items 13 and 14).

Two different interval conventions live side by side and must not be confused:

* The *containment* test used at policy issuance treats a listing window as
  half-open: `listed_on` inclusive, `removed_on` exclusive.
* The *collision* test used when adding an entry treats windows as closed —
  `listed_on` through `removed_on` inclusive — and additionally demands a
  thirty-day cooling-off gap after an existing window's `removed_on`, so windows
  that merely touch are refused.
"""

from datetime import timedelta

import store

COOLING_OFF_DAYS = 30


def window_conflict(carrier_id, state_program_id, listed_at):
    """True when a new window starting at listed_at collides with an existing one."""
    for rec in store.eligibilities_of(carrier_id, state_program_id):
        removed_at = rec.get("_removed_at")
        if removed_at is None:
            # An open-ended existing window always collides.
            return True
        if listed_at <= removed_at + timedelta(days=COOLING_OFF_DAYS):
            return True
    return False


def white_listed_for(carrier_id, state_program_id, effective_at):
    """True when a WHITE_LISTED entry's window contains effective_at."""
    for rec in store.eligibilities_of(carrier_id, state_program_id):
        if rec.get("listing_status") != "WHITE_LISTED":
            continue
        listed_at = rec.get("_listed_at")
        if listed_at is not None and effective_at < listed_at:
            continue
        removed_at = rec.get("_removed_at")
        if removed_at is not None and effective_at >= removed_at:
            continue
        return True
    return False
