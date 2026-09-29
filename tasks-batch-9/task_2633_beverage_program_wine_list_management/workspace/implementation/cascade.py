"""Cascading side effects: bins, list availability, version counters, venue ledgers, posture.

Every resource touched by a cascade gets its own updated_at refresh and its own
version increment of exactly 1 per operation (PRD 2.9).
"""
from core import D, new_record, now, rhu, store, touch
from calc import (
    LIVE_VERSION_STATES,
    contest_points,
    has_escalated_investigation,
    posture_for,
)

REPRINT_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Cellar bins
# ---------------------------------------------------------------------------
def recompute_bin(bin_rec):
    if bin_rec is None:
        return
    stored = sum(
        int(lot["bottles_on_hand"])
        for lot in store.inventory_lots.values()
        if lot["bin_id"] == bin_rec["id"] and lot["state"] == "ON_HAND"
    )
    utilization = rhu(D(stored) * 100 / D(bin_rec["capacity_bottles"]), 2)
    state = "FULL" if stored == int(bin_rec["capacity_bottles"]) else "ACTIVE"
    changed = (
        stored != bin_rec["bottles_stored"]
        or utilization != bin_rec["utilization_pct"]
        or state != bin_rec["bin_state"]
    )
    bin_rec["bottles_stored"] = stored
    bin_rec["utilization_pct"] = utilization
    bin_rec["bin_state"] = state
    if changed:
        touch(bin_rec)


def recompute_bin_of_lot(lot):
    recompute_bin(store.cellar_bins.get(lot["bin_id"]))


# ---------------------------------------------------------------------------
# Venue resolution through the list hierarchy
# ---------------------------------------------------------------------------
def venue_id_of_version(version):
    wine_list = store.wine_lists.get(version["wine_list_id"])
    return wine_list["venue_id"] if wine_list else None


def venue_id_of_entry(entry):
    version = store.list_versions.get(entry["list_version_id"])
    return venue_id_of_version(version) if version else None


def entries_of_version(version_id):
    rows = [e for e in store.list_entries.values() if e["list_version_id"] == version_id]
    return sorted(rows, key=lambda r: (r["sort_rank"], r["created_at"], r["_seq"]))


def entries_for_venue_wine(venue_id, wine_id):
    rows = []
    for entry in store.list_entries.values():
        if entry["wine_id"] != wine_id:
            continue
        if venue_id_of_entry(entry) != venue_id:
            continue
        rows.append(entry)
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def live_version_of_venue(venue_id):
    for version in store.list_versions.values():
        if version["state"] in LIVE_VERSION_STATES and venue_id_of_version(version) == venue_id:
            return version
    return None


# ---------------------------------------------------------------------------
# Availability of a wine at a venue and the entry / version cascade
# ---------------------------------------------------------------------------
def wine_available(venue_id, wine_id):
    """AVAILABLE when at least one lot of the pair is ON_HAND with bottles still on hand."""
    for lot in store.inventory_lots.values():
        if (
            lot["venue_id"] == venue_id
            and lot["wine_id"] == wine_id
            and lot["state"] == "ON_HAND"
            and int(lot["bottles_on_hand"]) > 0
        ):
            return True
    return False


def recount_out_of_stock(version):
    count = sum(
        1
        for entry in store.list_entries.values()
        if entry["list_version_id"] == version["id"]
        and entry["availability_state"] == "OUT_OF_STOCK"
    )
    if count != version["out_of_stock_entry_count"]:
        version["out_of_stock_entry_count"] = count
        touch(version)


def recount_stale(version):
    count = sum(
        1
        for entry in store.list_entries.values()
        if entry["list_version_id"] == version["id"] and entry["vintage_stale"]
    )
    required = count >= REPRINT_THRESHOLD
    changed = count != version["stale_entry_count"] or required != version["reprint_required"]
    version["stale_entry_count"] = count
    version["reprint_required"] = required
    if changed:
        touch(version)
    return required


def refresh_availability(venue_id, wine_id, live_only=False, direction=None):
    """Recompute availability_state for the venue-and-wine entries and rewrite the
    owning versions' out_of_stock_entry_count.

    direction "restock" only lifts OUT_OF_STOCK entries, "deplete" only drops
    AVAILABLE ones, None recomputes in both directions.
    """
    new_state = "AVAILABLE" if wine_available(venue_id, wine_id) else "OUT_OF_STOCK"
    touched_versions = []
    for entry in entries_for_venue_wine(venue_id, wine_id):
        version = store.list_versions.get(entry["list_version_id"])
        if version is None:
            continue
        if live_only and version["state"] not in LIVE_VERSION_STATES:
            continue
        if direction == "restock" and entry["availability_state"] != "OUT_OF_STOCK":
            continue
        if direction == "deplete" and entry["availability_state"] != "AVAILABLE":
            continue
        if entry["availability_state"] == new_state:
            continue
        entry["availability_state"] = new_state
        touch(entry)
        if version["id"] not in [v["id"] for v in touched_versions]:
            touched_versions.append(version)
    for version in touched_versions:
        recount_out_of_stock(version)


def mark_pinned_events_stale(version_id):
    for event in store.wine_dinner_events.values():
        if event["list_version_id"] != version_id:
            continue
        if event["state"] not in ("PLANNED", "PRICED", "CONFIRMED"):
            continue
        if not event["pinned_version_stale"]:
            event["pinned_version_stale"] = True
            touch(event)


# ---------------------------------------------------------------------------
# The append-only ledger and the venue's two running sums
# ---------------------------------------------------------------------------
def write_depletion(
    venue_id,
    wine_id,
    lot_id,
    reason,
    bottles,
    pours,
    cogs_cents,
    revenue_cents,
    list_entry_id=None,
    btg_slot_id=None,
    event_id=None,
    write_off_id=None,
):
    """A ledger entry is an immutable event: id and created_at only."""
    rec = new_record(
        {
            "venue_id": venue_id,
            "wine_id": wine_id,
            "lot_id": lot_id,
            "list_entry_id": list_entry_id,
            "btg_slot_id": btg_slot_id,
            "event_id": event_id,
            "write_off_id": write_off_id,
            "reason": reason,
            "bottles": int(bottles),
            "pours": int(pours),
            "cogs_cents": int(cogs_cents),
            "revenue_cents": int(revenue_cents),
            "occurred_at": now(),
        },
        common_fields=False,
    )
    store.depletion_entries[rec["id"]] = rec
    return rec


def apply_ledger_totals(venue, entries):
    """One venue mutation per operation carrying the summed signed movements."""
    cogs = sum(int(e["cogs_cents"]) for e in entries)
    revenue = sum(int(e["revenue_cents"]) for e in entries)
    if cogs == 0 and revenue == 0 and not entries:
        return
    venue["cogs_ledger_cents"] = int(venue["cogs_ledger_cents"]) + cogs
    venue["revenue_ledger_cents"] = int(venue["revenue_ledger_cents"]) + revenue
    touch(venue)


def refresh_contest_points(entry):
    venue_id = venue_id_of_entry(entry)
    venue = store.venues.get(venue_id)
    wine = store.wines.get(entry["wine_id"])
    if venue is None or wine is None:
        return
    points = contest_points(entry, venue, wine)
    if points != entry["contest_points"]:
        entry["contest_points"] = points
        touch(entry)


def refresh_contest_points_for_entries(entries):
    """entries: ledger entries just written; recompute each named listing once."""
    seen = []
    for ledger_entry in entries:
        entry_id = ledger_entry.get("list_entry_id")
        if entry_id and entry_id not in seen:
            seen.append(entry_id)
    for entry_id in seen:
        entry = store.list_entries.get(entry_id)
        if entry is not None:
            refresh_contest_points(entry)


# ---------------------------------------------------------------------------
# Fiscal posture
# ---------------------------------------------------------------------------
def recompute_posture(venue, force_touch=False):
    posture = posture_for(venue["last_variance_pct"], has_escalated_investigation(venue["id"]))
    if posture != venue["program_posture"]:
        venue["program_posture"] = posture
        touch(venue)
    elif force_touch:
        touch(venue)
    return posture


# ---------------------------------------------------------------------------
# Lot state transitions driven by bottle movement
# ---------------------------------------------------------------------------
def deplete_lot_if_empty(lot, terminal=False):
    """A lot at zero on hand goes DEPLETED, or terminally WRITTEN_OFF."""
    if int(lot["bottles_on_hand"]) <= 0 and lot["state"] == "ON_HAND":
        lot["state"] = "WRITTEN_OFF" if terminal else "DEPLETED"
        return True
    return False


def apply_stale_recount(version):
    """Recount stale entries, rewrite reprint_required and take a live version into
    REPRINT_PENDING when the obligation has just appeared. One mutation per version."""
    count = sum(
        1
        for entry in store.list_entries.values()
        if entry["list_version_id"] == version["id"] and entry["vintage_stale"]
    )
    required = count >= REPRINT_THRESHOLD
    was_required = bool(version["reprint_required"])
    changed = count != version["stale_entry_count"] or required != was_required
    version["stale_entry_count"] = count
    version["reprint_required"] = required
    moved = False
    if version["state"] == "PUBLISHED" and required and not was_required:
        version["state"] = "REPRINT_PENDING"
        moved = True
        changed = True
    if changed:
        touch(version)
    if moved:
        mark_pinned_events_stale(version["id"])
    return moved
