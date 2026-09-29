"""Allocation rounds, the waterfall stock selector, the unmet-need waitlist,
and the compensating stock releases (PRD 3.3, 3.6).
"""

from core import CONDITION_RANK, clock
from db import (
    db, new_entity, touch, lines_of_voucher, units_of_line, waitlist_of_line,
    client_of_voucher, referral_of_voucher,
)
from services.calc import (
    candidate_ranking_key, line_processing_key, recompute_fill_ratio,
    waitlist_score, write_provisional_fee,
)

PARTICIPATING_LINE_STATUSES = ("OPEN", "PARTIAL", "WAITLISTED")


def _upsert_waitlist_entry(voucher, line, remaining):
    client = client_of_voucher(voucher)
    referral = referral_of_voucher(voucher)
    existing = waitlist_of_line(line["id"], ("WAITING",))
    if existing:
        entry = existing[0]
        changed = False
        if entry["quantity_unmet"] != remaining:
            entry["quantity_unmet"] = remaining
            changed = True
        score = waitlist_score(referral, client, entry["waiting_since"])
        if entry["priority_score"] != score:
            entry["priority_score"] = score
            changed = True
        if changed:
            touch(entry)
        return entry

    now = clock.now()
    entry = new_entity(
        voucher_line_id=line["id"],
        client_id=client["id"],
        category=line["category"],
        county=client["county"],
        quantity_unmet=remaining,
        priority_score=waitlist_score(referral, client, now),
        waiting_since=now,
        status="WAITING",
    )
    db.waitlist_entries[entry["id"]] = entry
    return entry


def _promote_entries_for_line(line):
    promoted = 0
    for entry in waitlist_of_line(line["id"], ("WAITING",)):
        entry["status"] = "PROMOTED"
        entry["quantity_unmet"] = 0
        touch(entry)
        promoted += 1
    return promoted


def _select_candidates(line):
    candidates = []
    max_rank = CONDITION_RANK[line["min_condition"]]
    for unit in db.inventory_items.values():
        if unit["status"] != "AVAILABLE":
            continue
        if unit["category"] != line["category"]:
            continue
        if CONDITION_RANK[unit["condition"]] > max_rank:
            continue
        candidates.append(unit)
    candidates.sort(key=candidate_ranking_key)
    return candidates


def allocate_lines(voucher):
    """Walk the voucher's unfilled lines in the pinned order and reserve stock.

    Returns (units_taken, promoted_entry_count).
    """
    lines = [l for l in lines_of_voucher(voucher["id"])
             if l["status"] in PARTICIPATING_LINE_STATUSES]
    lines.sort(key=line_processing_key)

    taken_total = 0
    promoted_total = 0
    for line in lines:
        before_status = line["status"]
        before_allocated = line["quantity_allocated"]
        shortfall = line["quantity_requested"] - line["quantity_allocated"]
        if shortfall <= 0:
            continue
        for unit in _select_candidates(line)[:shortfall]:
            unit["status"] = "RESERVED"
            unit["reserved_for_voucher_line_id"] = line["id"]
            touch(unit)
            line["quantity_allocated"] += 1
            taken_total += 1

        remaining = line["quantity_requested"] - line["quantity_allocated"]
        if remaining > 0:
            line["status"] = "WAITLISTED" if line["quantity_allocated"] == 0 else "PARTIAL"
            _upsert_waitlist_entry(voucher, line, remaining)
        else:
            line["status"] = "FILLED"
            promoted_total += _promote_entries_for_line(line)

        if line["status"] != before_status or line["quantity_allocated"] != before_allocated:
            touch(line)

    return taken_total, promoted_total


def run_allocation_round(voucher):
    """One allocation round over a voucher in ISSUED or PARTIALLY_ALLOCATED.

    Returns the number of waitlist entries promoted by this round.
    """
    previous_status = voucher["status"]
    _taken, promoted = allocate_lines(voucher)

    lines = lines_of_voucher(voucher["id"])
    total_allocated = sum(l["quantity_allocated"] for l in lines)
    total_requested = sum(l["quantity_requested"] for l in lines)

    if previous_status == "ISSUED" and total_allocated == 0:
        # Zero-yield round: no stock is held, so fill_ratio stays 0.0 and the
        # money fields and fee_basis are left untouched.
        voucher["status"] = "ISSUED"
    else:
        voucher["status"] = "ALLOCATED" if total_allocated >= total_requested \
            else "PARTIALLY_ALLOCATED"
        voucher["fill_ratio"] = recompute_fill_ratio(voucher)
        write_provisional_fee(voucher)
    touch(voucher)
    return promoted


def release_reserved_stock(voucher):
    """Compensating half of the stock conservation invariant: every unit still
    RESERVED for this voucher returns to AVAILABLE at the back of the queue."""
    released = 0
    for line in lines_of_voucher(voucher["id"]):
        for unit in units_of_line(line["id"], ("RESERVED",)):
            unit["status"] = "AVAILABLE"
            unit["reserved_for_voucher_line_id"] = None
            unit["available_since"] = clock.now()
            touch(unit)
            line["quantity_allocated"] -= 1
            released += 1
    return released


def cancel_voucher(voucher):
    """PRD 3.3 withdrawal, from ISSUED, PARTIALLY_ALLOCATED or ALLOCATED."""
    if voucher["status"] in ("PARTIALLY_ALLOCATED", "ALLOCATED"):
        release_reserved_stock(voucher)
    for line in lines_of_voucher(voucher["id"]):
        line["status"] = "CANCELLED"
        touch(line)
        for entry in waitlist_of_line(line["id"], ("WAITING",)):
            entry["status"] = "CANCELLED"
            touch(entry)
    voucher["status"] = "CANCELLED"
    touch(voucher)


def expire_voucher(voucher):
    """PRD 3.3 expiry, step 2 of the operational cycle. Returns released units."""
    released = 0
    if voucher["status"] in ("PARTIALLY_ALLOCATED", "ALLOCATED"):
        released = release_reserved_stock(voucher)
    for line in lines_of_voucher(voucher["id"]):
        line["status"] = "CANCELLED"
        touch(line)
        for entry in waitlist_of_line(line["id"], ("WAITING",)):
            entry["status"] = "EXPIRED"
            touch(entry)
    voucher["status"] = "EXPIRED"
    touch(voucher)
    return released
