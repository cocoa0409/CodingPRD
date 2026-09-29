"""Cure deadline derivation with its pinned evaluation order (PRD 3.6)."""
import db
import lookups
from constants import (
    CANVASS_DAYS_EXTENDED,
    CANVASS_DAYS_STANDARD,
    EXTENDED_CANVASS_OPEN_CURE_THRESHOLD,
)


def open_notice_count(election_rec):
    return sum(
        1 for n in lookups.notices_of_election(election_rec)
        if n["status"] in ("ISSUED", "UNDER_EVIDENCE_REVIEW")
    )


def derive_deadline(election_rec):
    """Called with the new notice already inserted in ISSUED.

    Step 1 count open notices inclusive of the new one; step 2 pick the canvass
    length; step 3 recompute canvass_lock_at; step 4 the cure base deadline;
    step 5 the earlier of the base deadline and the lock instant less one day.
    """
    n_open = open_notice_count(election_rec)

    computed_days = (
        CANVASS_DAYS_EXTENDED
        if n_open >= EXTENDED_CANVASS_OPEN_CURE_THRESHOLD
        else CANVASS_DAYS_STANDARD
    )
    # The election's canvass length is monotone: once extended it never returns.
    canvass_days = max(election_rec["canvass_days"], computed_days)

    lock_at = db.whole_second(
        db.add_days(election_rec["return_deadline_at"], canvass_days)
    )
    if canvass_days != election_rec["canvass_days"] or election_rec["canvass_lock_at"] != lock_at:
        election_rec["canvass_days"] = canvass_days
        election_rec["canvass_lock_at"] = lock_at
        db.touch(election_rec)

    cure_base = db.whole_second(
        db.add_days(election_rec["return_deadline_at"], election_rec["cure_window_days"])
    )
    lock_minus_one = db.whole_second(db.add_days(lock_at, -1))
    cure_deadline_at = cure_base if cure_base <= lock_minus_one else lock_minus_one
    return cure_deadline_at, canvass_days, n_open


def newest_evidence(notice):
    rows = [
        e for e in db.cure_evidence.values() if e["cure_notice_id"] == notice["id"]
    ]
    if not rows:
        return None
    rows.sort(key=lambda e: (e["received_at"], e["created_at"], e["_seq"]))
    return rows[-1]
