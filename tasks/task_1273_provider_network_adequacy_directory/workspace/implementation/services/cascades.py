"""Cross-entity cascades: cycle counters, listing removal, provider lifecycle."""

import db
import helpers


def recompute_cycle_counters(cycle):
    """Recompute counters over records of this cycle with status != CANCELLED."""
    total = pending = responded = non_responsive = 0
    for rec in db.records.values():
        if rec["cycle_id"] != cycle["id"]:
            continue
        if rec["status"] == "CANCELLED":
            continue
        total += 1
        if rec["status"] == "PENDING":
            pending += 1
        elif rec["status"] in ("ATTESTED", "CORRECTION_REQUESTED"):
            responded += 1
        elif rec["status"] == "NON_RESPONSIVE":
            non_responsive += 1
    cycle["total_records"] = total
    cycle["pending_count"] = pending
    cycle["responded_count"] = responded
    cycle["non_responsive_count"] = non_responsive


def remove_listing_cascade(listing):
    """Listing -> REMOVED: cancel PENDING attestation records in non-CLOSED cycles,
    recompute owning cycle counters. Assumes listing.status already set to REMOVED
    and listing version already bumped by caller."""
    touched_cycles = set()
    for rec in db.records.values():
        if rec["listing_id"] != listing["id"]:
            continue
        if rec["status"] != "PENDING":
            continue
        cycle = db.cycles.get(rec["cycle_id"])
        if cycle is None or cycle["status"] == "CLOSED":
            continue
        rec["status"] = "CANCELLED"
        helpers.touch(rec)
        touched_cycles.add(rec["cycle_id"])
    for cid in touched_cycles:
        recompute_cycle_counters(db.cycles[cid])


def provider_suspend_cascade(provider):
    """EFFECTIVE -> SUSPENDED: each LISTED listing of this provider -> SUPPRESSED
    with suppress_reason=PROVIDER_SUSPENDED."""
    for lst in db.listings.values():
        if lst["provider_id"] != provider["id"]:
            continue
        if lst["status"] != "LISTED":
            continue
        lst["status"] = "SUPPRESSED"
        lst["suppress_reason"] = "PROVIDER_SUSPENDED"
        lst["suppressed_at"] = helpers.now_iso()
        helpers.touch(lst)


def provider_reinstate_cascade(provider):
    """SUSPENDED -> EFFECTIVE: restore exactly the listings the suspend cascade
    suppressed (SUPPRESSED with reason PROVIDER_SUSPENDED)."""
    for lst in db.listings.values():
        if lst["provider_id"] != provider["id"]:
            continue
        if lst["status"] == "SUPPRESSED" and lst["suppress_reason"] == "PROVIDER_SUSPENDED":
            lst["status"] = "LISTED"
            lst["suppress_reason"] = "NONE"
            helpers.touch(lst)


def provider_terminate_cascade(provider):
    """TERMINATED 3-link cascade: listings -> REMOVED; their PENDING records ->
    CANCELLED; owning cycle counters recompute."""
    touched_cycles = set()
    for lst in db.listings.values():
        if lst["provider_id"] != provider["id"]:
            continue
        if lst["status"] in ("DRAFT", "LISTED", "UNDER_REVIEW", "SUPPRESSED"):
            lst["status"] = "REMOVED"
            helpers.touch(lst)
            for rec in db.records.values():
                if rec["listing_id"] != lst["id"]:
                    continue
                if rec["status"] != "PENDING":
                    continue
                cycle = db.cycles.get(rec["cycle_id"])
                if cycle is None or cycle["status"] == "CLOSED":
                    continue
                rec["status"] = "CANCELLED"
                helpers.touch(rec)
                touched_cycles.add(rec["cycle_id"])
    for cid in touched_cycles:
        recompute_cycle_counters(db.cycles[cid])


def provider_effectuation_sweep():
    """PENDING_LOAD providers whose contract_effective_date <= new clock date
    become EFFECTIVE. Returns effectuated provider ids."""
    effectuated = []
    cdate = helpers.clock_date()
    for p in db.providers.values():
        if p["status"] != "PENDING_LOAD":
            continue
        eff = helpers.parse_date(p["contract_effective_date"], "contract_effective_date")
        if eff <= cdate:
            p["status"] = "EFFECTIVE"
            helpers.touch(p)
            effectuated.append(p["id"])
    return effectuated
