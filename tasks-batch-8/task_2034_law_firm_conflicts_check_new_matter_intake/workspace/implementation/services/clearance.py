"""Matter clearance derivation and check supersession (PRD 2.8, 3.3, 3.4;
scaffold state_machines Matter clearance rule / ConflictCheck supersede)."""

import db


def matter_checks(matter_id):
    return [c for c in db.store.conflict_checks.values()
            if c["matter_id"] == matter_id]


def check_hits(check_id):
    return [h for h in db.store.conflict_hits.values()
            if h["check_id"] == check_id]


def matter_roster(matter_id):
    return [mp for mp in db.store.matter_parties.values()
            if mp["matter_id"] == matter_id]


def recompute_clearance(matter):
    """Derived dimension over the hits of the matter's NON-SUPERSEDED checks
    (both kinds); first matching precedence rule wins:
      1 any CONFIRMED -> BLOCKED
      2 any PENDING   -> HITS_PENDING
      3 any WAIVED    -> WAIVED
      4 >=1 COMPLETED check exists -> CLEARED
      5 else -> UNCHECKED
    A flip is itself a mutation of the matter row (version +1, updated_at)."""
    live_checks = [c for c in matter_checks(matter["id"])
                   if c["status"] == "COMPLETED"]
    live_hits = []
    for c in live_checks:
        live_hits.extend(check_hits(c["id"]))

    statuses = {h["review_status"] for h in live_hits}
    if "CONFIRMED" in statuses:
        new_status = "BLOCKED"
    elif "PENDING" in statuses:
        new_status = "HITS_PENDING"
    elif "WAIVED" in statuses:
        new_status = "WAIVED"
    elif live_checks:
        new_status = "CLEARED"
    else:
        new_status = "UNCHECKED"

    if matter["clearance_status"] != new_status:
        matter["clearance_status"] = new_status
        db.bump(matter)
    return matter


def supersede_checks(matter, check_kind):
    """Move every COMPLETED check of the given kind on the matter to
    SUPERSEDED; cascade each of its PENDING hits to STALE (per-hit version
    +1). Returns True when at least one check was superseded."""
    superseded = False
    for c in matter_checks(matter["id"]):
        if c["check_kind"] == check_kind and c["status"] == "COMPLETED":
            c["status"] = "SUPERSEDED"
            db.bump(c)
            superseded = True
            for h in check_hits(c["id"]):
                if h["review_status"] == "PENDING":
                    h["review_status"] = "STALE"
                    db.bump(h)
    return superseded
