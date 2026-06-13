"""Derived-field reconciliation (PRD §2.4, §2.6, §2.8, §3).

These functions recompute denormalized counters/balances from the underlying
rows and write them back onto the owning record, refreshing updated_at and
bumping version exactly as any other mutation does (PRD §2.4: "Because these
reconciliations mutate the owning resource, they refresh its updated_at and
increment its version exactly as any other mutation does.").

To avoid gratuitous version churn on pure reads where nothing changed, each
reconcile only touches (updated_at + version bump) the record when a derived
value actually changes value.
"""

import db


# ---- Patron --------------------------------------------------------------

def reconcile_patron(patron):
    pid = patron["id"]

    active_loan_count = sum(
        1 for ln in db.loans.values()
        if ln["patron_id"] == pid and ln["status"] in ("ACTIVE", "OVERDUE")
    )
    active_hold_count = sum(
        1 for h in db.holds.values()
        if h["patron_id"] == pid and h["status"] in ("WAITING", "READY")
    )
    ready_pickup_count = sum(
        1 for h in db.holds.values()
        if h["patron_id"] == pid and h["status"] == "READY"
    )
    total_owed_cents = sum(
        f["amount_cents"] for f in db.fines.values()
        if f["patron_id"] == pid and f["settlement_status"] == "UNPAID"
    )

    branch = db.branches.get(patron["branch_id"])
    threshold = branch["block_threshold_cents"] if branch else 0
    borrowing_status = "BLOCKED" if total_owed_cents >= threshold else "CLEAR"

    changed = (
        patron.get("active_loan_count") != active_loan_count
        or patron.get("active_hold_count") != active_hold_count
        or patron.get("ready_pickup_count") != ready_pickup_count
        or patron.get("total_owed_cents") != total_owed_cents
        or patron.get("borrowing_status") != borrowing_status
    )

    patron["active_loan_count"] = active_loan_count
    patron["active_hold_count"] = active_hold_count
    patron["ready_pickup_count"] = ready_pickup_count
    patron["total_owed_cents"] = total_owed_cents
    patron["borrowing_status"] = borrowing_status

    if changed:
        db.touch(patron)
    return patron


def reconcile_patron_by_id(patron_id):
    p = db.patrons.get(patron_id)
    if p is not None:
        reconcile_patron(p)
    return p


# ---- Title ---------------------------------------------------------------

def reconcile_title(title):
    tid = title["id"]
    title_copies = [c for c in db.copies.values() if c["title_id"] == tid]

    available_copy_count = sum(1 for c in title_copies if c["status"] == "AVAILABLE")
    total_copy_count = sum(1 for c in title_copies if c["status"] != "WITHDRAWN")
    waiting_hold_count = sum(
        1 for h in db.holds.values()
        if h["title_id"] == tid and h["status"] == "WAITING"
    )

    changed = (
        title.get("available_copy_count") != available_copy_count
        or title.get("total_copy_count") != total_copy_count
        or title.get("waiting_hold_count") != waiting_hold_count
    )

    title["available_copy_count"] = available_copy_count
    title["total_copy_count"] = total_copy_count
    title["waiting_hold_count"] = waiting_hold_count

    if changed:
        db.touch(title)
    return title


def reconcile_title_by_id(title_id):
    t = db.titles.get(title_id)
    if t is not None:
        reconcile_title(t)
    return t


# ---- LicensePool ---------------------------------------------------------

def reconcile_pool(pool):
    pid = pool["id"]
    loaned = sum(
        1 for e in db.ebook_loans.values()
        if e["pool_id"] == pid and e["status"] == "ACTIVE"
    )
    available = max(0, pool["total_licenses"] - loaned)

    changed = (
        pool.get("loaned_licenses") != loaned
        or pool.get("available_licenses") != available
    )
    pool["loaned_licenses"] = loaned
    pool["available_licenses"] = available
    if changed:
        db.touch(pool)
    return pool


def reconcile_pool_by_id(pool_id):
    p = db.license_pools.get(pool_id)
    if p is not None:
        reconcile_pool(p)
    return p


# ---- Hold queue position -------------------------------------------------

def waiting_holds_for_title(title_id):
    """All WAITING holds on a title, ordered by created_at ASC (tie-break _seq)."""
    waiting = [
        h for h in db.holds.values()
        if h["title_id"] == title_id and h["status"] == "WAITING"
    ]
    return db.sorted_by_created(waiting)


def queue_position_of(hold):
    """1-based rank among WAITING holds on the hold's title. 0 for non-WAITING."""
    if hold["status"] != "WAITING":
        return 0
    ordered = waiting_holds_for_title(hold["title_id"])
    for idx, h in enumerate(ordered):
        if h["id"] == hold["id"]:
            return idx + 1
    return 0
