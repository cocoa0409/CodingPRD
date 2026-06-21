"""Derived-field recomputation and selector calculations (scaffold §1.3)."""
from datetime import datetime, timezone

from db import store
from common import round_volume

# Dispositions counted in on-hand / location volume (PRD §3.1, §3.5).
ON_HAND_DISPOSITIONS = {"STORED", "ALLOCATED", "PICKED_STAGED"}
# Allocation statuses that consume availability (PRD §3.1, §3.6).
ACTIVE_ALLOC = {"RESERVED", "COMMITTED"}

CADENCE_DAYS = {"A": 30, "B": 60, "C": 90}


# ---------------------------------------------------------------------------
# Sku derived fields
# ---------------------------------------------------------------------------
def sku_on_hand(sku_id):
    return sum(
        lp["qty"]
        for lp in store.license_plates.values()
        if lp["sku_id"] == sku_id and lp["disposition"] in ON_HAND_DISPOSITIONS
    )


def sku_reserved(sku_id):
    total = 0
    for a in store.allocations.values():
        if a["status"] not in ACTIVE_ALLOC:
            continue
        lp = store.license_plates.get(a["lpn_id"])
        if lp is not None and lp["sku_id"] == sku_id:
            total += a["allocated_qty"]
    return total


def sku_available(sku_id):
    return sku_on_hand(sku_id) - sku_reserved(sku_id)


def _parse_iso(ts):
    # stored timestamps look like 2025-05-24T10:30:00.123Z
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def cycle_count_due(sku):
    last = None
    for cc in store.cycle_counts.values():
        if cc["sku_id"] == sku["id"] and cc["status"] == "RECONCILED":
            ts = _parse_iso(cc["updated_at"])
            if last is None or ts > last:
                last = ts
    if last is None:
        return True
    now = store.now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - last
    days = delta.days  # whole-day floor for non-negative deltas
    if delta.total_seconds() < 0:
        days = 0
    cadence = CADENCE_DAYS[sku["abc_class"]]
    return days >= cadence


def refresh_sku(sku):
    sku["on_hand_qty"] = sku_on_hand(sku["id"])
    sku["available_qty"] = sku_available(sku["id"])
    sku["cycle_count_due"] = cycle_count_due(sku)
    return sku


# ---------------------------------------------------------------------------
# Location derived field
# ---------------------------------------------------------------------------
def location_used_volume(location_id):
    total = 0.0
    for lp in store.license_plates.values():
        if lp["location_id"] == location_id and lp["disposition"] in ON_HAND_DISPOSITIONS:
            sku = store.skus.get(lp["sku_id"])
            if sku is not None:
                total += lp["qty"] * sku["each_volume_cm3"]
    return round_volume(total)


def refresh_location(loc):
    loc["used_volume_cm3"] = location_used_volume(loc["id"])
    return loc


# ---------------------------------------------------------------------------
# AsnLine derived fields
# ---------------------------------------------------------------------------
def asn_line_received(line_id):
    return sum(
        r["received_qty"]
        for r in store.receipt_events.values()
        if r["asn_line_id"] == line_id
    )


def asn_line_status(received, expected):
    if received < expected:
        return "OPEN"
    if received == expected:
        return "SATISFIED"
    return "OVER"


def refresh_asn_line(line):
    line["received_qty"] = asn_line_received(line["id"])
    line["line_status"] = asn_line_status(line["received_qty"], line["expected_qty"])
    return line


# ---------------------------------------------------------------------------
# OrderLine derived fields
# ---------------------------------------------------------------------------
def order_line_allocated(line_id):
    return sum(
        a["allocated_qty"]
        for a in store.allocations.values()
        if a["order_line_id"] == line_id and a["status"] in ACTIVE_ALLOC
    )


def order_line_picked(line_id):
    return sum(
        a["allocated_qty"]
        for a in store.allocations.values()
        if a["order_line_id"] == line_id and a["status"] == "COMMITTED"
    )


def refresh_order_line(line):
    line["allocated_qty"] = order_line_allocated(line["id"])
    line["picked_qty"] = order_line_picked(line["id"])
    return line


# ---------------------------------------------------------------------------
# LPN reservation helpers
# ---------------------------------------------------------------------------
def lpn_reserved(lpn_id):
    """Eaches RESERVED+COMMITTED against a given LPN."""
    return sum(
        a["allocated_qty"]
        for a in store.allocations.values()
        if a["lpn_id"] == lpn_id and a["status"] in ACTIVE_ALLOC
    )


def lpn_free(lpn):
    return lpn["qty"] - lpn_reserved(lpn["id"])


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------
def putaway_location_select(lpn):
    """Tightest-fit ABC slotting (PRD §3.4). Returns a Location dict or None."""
    sku = store.skus.get(lpn["sku_id"])
    need = lpn["qty"] * sku["each_volume_cm3"]
    candidates = []
    for loc in store.locations.values():
        if loc["status"] != "AVAILABLE":
            continue
        if loc["zone"] not in ("RESERVE", "PICK_FACE"):
            continue
        residual = loc["max_volume_cm3"] - location_used_volume(loc["id"])
        if residual < need:
            continue
        if loc["zone"] == "PICK_FACE" and loc.get("pick_face_for_sku_id") != sku["id"]:
            continue
        candidates.append((loc, round_volume(residual)))
    if not candidates:
        return None

    def rank(item):
        loc, residual = item
        # A-class prefers PICK_FACE (0), B/C prefers RESERVE (0); mismatch -> 1.
        matches = (sku["abc_class"] == "A") == (loc["zone"] == "PICK_FACE")
        zone_pref = 0 if matches else 1
        return (zone_pref, residual, loc["created_at"], loc.get("_seq", 0))

    return min(candidates, key=rank)[0]


def crossdock_location_select(lpn):
    """Most-open-first (PRD §3.3). Returns a Location dict or None."""
    sku = store.skus.get(lpn["sku_id"])
    need = lpn["qty"] * sku["each_volume_cm3"]
    candidates = []
    for loc in store.locations.values():
        if loc["status"] != "AVAILABLE":
            continue
        if loc["zone"] != "CROSS_DOCK":
            continue
        residual = loc["max_volume_cm3"] - location_used_volume(loc["id"])
        if residual < need:
            continue
        candidates.append((loc, round_volume(residual)))
    if not candidates:
        return None

    def rank(item):
        loc, residual = item
        # most open: largest residual first -> negate
        return (-residual, loc["created_at"], loc.get("_seq", 0))

    return min(candidates, key=rank)[0]


def replen_source_select(task):
    """Accumulate STORED RESERVE-zone LPNs of the SKU, oldest created_at first,
    until running sum >= replen_qty. Returns the chosen source LPN or None.
    (PRD §3.11)"""
    sku_id = task["sku_id"]
    need = task["replen_qty"]
    candidates = []
    for lp in store.license_plates.values():
        if lp["sku_id"] != sku_id:
            continue
        if lp["disposition"] != "STORED":
            continue
        if lp["qty"] <= 0:
            continue
        loc = store.locations.get(lp["location_id"]) if lp["location_id"] else None
        if loc is None or loc["zone"] != "RESERVE":
            continue
        candidates.append(lp)
    candidates.sort(key=lambda lp: (lp["created_at"], lp.get("_seq", 0)))
    # Accumulate oldest-first; the winner is the plate at which the running sum
    # first reaches replen_qty (scaffold replen_source_select: "winner = first lp
    # such that running sum of selected lp.qty >= task.replen_qty"). The completion
    # contract requires that single plate to hold >= replen_qty on its own.
    running = 0
    for lp in candidates:
        running += lp["qty"]
        if running >= need:
            return lp
    # whole pool insufficient (or empty)
    return None
