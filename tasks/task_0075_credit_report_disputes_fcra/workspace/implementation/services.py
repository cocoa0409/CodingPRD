from datetime import timedelta

from db import db
from util import new_id, SATURDAY, SUNDAY

# Status sets
DISPUTE_NONTERMINAL = {"FILED", "INVESTIGATING", "REVERIFYING", "REOPENED"}
TRADELINE_COUNTED = {"REPORTING", "DISPUTED", "CORRECTED", "VERIFIED"}


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def stamp_new(entity):
    now = db.clock
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    return entity


def touch(entity):
    entity["updated_at"] = db.clock
    entity["version"] += 1


def stamp_event(entity):
    """Append-only records: id + created_at only."""
    entity["created_at"] = db.clock
    entity["_seq"] = db.next_seq()
    return entity


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

def compute_deadline(filed_at, clock_mode):
    if clock_mode == "CALENDAR":
        return filed_at + timedelta(days=30)
    # EXPEDITED: 15 business days, skipping Sat/Sun, preserving time-of-day
    d = filed_at
    added = 0
    while added < 15:
        d = d + timedelta(days=1)
        if d.weekday() not in (SATURDAY, SUNDAY):
            added += 1
    return d


def compute_purge_due_at(dofd):
    return dofd + timedelta(days=2555) + timedelta(days=180)


def compute_reage_violation(reported_delinquency_date, dofd):
    return reported_delinquency_date > dofd


def compute_priority_score(dispute, tradeline):
    reason_weight = {
        "IDENTITY_THEFT": 50,
        "ILLEGAL_REAGE": 40,
        "NOT_MINE": 35,
        "INACCURATE_BALANCE": 20,
        "PAID_IN_FULL": 15,
    }[dispute["dispute_reason"]]
    reage_bonus = 25 if tradeline["reage_violation"] else 0
    balance_factor = min(20, tradeline["balance_cents"] // 50000)
    reopen_penalty = 10 * dispute["reopen_count"]
    raw = reason_weight + reage_bonus + balance_factor - reopen_penalty
    return max(0, min(100, raw))


def compute_protection_state(credit_file):
    clock = db.clock
    file_id = credit_file["id"]
    active = []
    for f in db.security_freezes.values():
        if f["credit_file_id"] != file_id:
            continue
        if f["status"] != "ACTIVE":
            continue
        if not (f["effective_at"] <= clock):
            continue
        if f["expires_at"] is not None and not (clock < f["expires_at"]):
            continue
        active.append(f)
    if any(f["freeze_type"] == "FREEZE" for f in active):
        return "FROZEN"
    if any(f["freeze_type"] == "LOCK" for f in active):
        return "LOCKED"
    return "OPEN"


def recompute_protection_state(credit_file):
    credit_file["protection_state"] = compute_protection_state(credit_file)


def recompute_counts(credit_file):
    file_id = credit_file["id"]
    odc = 0
    for d in db.disputes.values():
        if d["credit_file_id"] == file_id and d["status"] in DISPUTE_NONTERMINAL:
            odc += 1
    tc = 0
    for t in db.tradelines.values():
        if t["credit_file_id"] == file_id and t["status"] in TRADELINE_COUNTED:
            tc += 1
    credit_file["open_dispute_count"] = odc
    credit_file["tradeline_count"] = tc


# ---------------------------------------------------------------------------
# Notification minting
# ---------------------------------------------------------------------------

def mint_notification(credit_file_id, subject_type, subject_id, event_code):
    n = {
        "id": new_id(),
        "credit_file_id": credit_file_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_code": event_code,
        "dispatched_at": db.clock,
    }
    stamp_event(n)
    db.notifications[n["id"]] = n
    return n


def append_reage_event(tradeline_id, prior, new, was_violation, source_dispute_id):
    e = {
        "id": new_id(),
        "tradeline_id": tradeline_id,
        "prior_delinquency_date": prior,
        "new_delinquency_date": new,
        "was_violation": was_violation,
        "source_dispute_id": source_dispute_id,
    }
    stamp_event(e)
    db.reage_events[e["id"]] = e
    return e


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def cascade_delete(dispute, credit_file, tradeline, auto_deleted):
    """Shared DELETE / AUTO_DELETED cascade depth-3."""
    tradeline["status"] = "DELETED"
    touch(tradeline)
    recompute_counts(credit_file)
    if auto_deleted:
        mint_notification(credit_file["id"], "DISPUTE", dispute["id"], "DISPUTE_AUTO_DELETED")
        mint_notification(credit_file["id"], "TRADELINE", tradeline["id"], "TRADELINE_DELETED")
    else:
        mint_notification(credit_file["id"], "TRADELINE", tradeline["id"], "TRADELINE_DELETED")
        mint_notification(credit_file["id"], "DISPUTE", dispute["id"], "DISPUTE_RESOLVED")
    touch(credit_file)
    credit_file["protection_state"] = compute_protection_state(credit_file)


def expire_pending_reverifications(dispute):
    for r in db.reverifications.values():
        if r["dispute_id"] == dispute["id"] and r["status"] == "PENDING":
            r["status"] = "EXPIRED"
            touch(r)
            furnisher = db.furnishers.get(r["furnisher_id"])
            if furnisher:
                furnisher["open_reverification_count"] -= 1
                touch(furnisher)


def cancel_pending_reverifications(dispute):
    for r in db.reverifications.values():
        if r["dispute_id"] == dispute["id"] and r["status"] == "PENDING":
            r["status"] = "CANCELLED"
            touch(r)
            furnisher = db.furnishers.get(r["furnisher_id"])
            if furnisher:
                furnisher["open_reverification_count"] -= 1
                touch(furnisher)


def auto_delete_dispute(dispute):
    credit_file = db.credit_files[dispute["credit_file_id"]]
    tradeline = db.tradelines[dispute["tradeline_id"]]
    dispute["status"] = "AUTO_DELETED"
    dispute["outcome_reason"] = "DEADLINE_BREACH"
    touch(dispute)
    # expire pending reverifications first (decrement furnisher counts)
    expire_pending_reverifications(dispute)
    cascade_delete(dispute, credit_file, tradeline, auto_deleted=True)


def run_deadline_sweep():
    clock = db.clock
    # deterministic order by creation
    for d in sorted(db.disputes.values(), key=lambda x: x["_seq"]):
        if d["status"] in DISPUTE_NONTERMINAL and d["deadline_at"] < clock:
            auto_delete_dispute(d)
