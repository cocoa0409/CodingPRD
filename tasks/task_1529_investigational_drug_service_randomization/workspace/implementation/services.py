"""Business logic: cascades, calculations, serializers.

Implements PRD §3 workflows and the scaffold's state-machine side effects.
All mutation helpers operate on db.store dicts; nothing is persisted to disk.
"""

import math
from datetime import datetime, timedelta, timezone

import db as dbmod
import errors as E
from db import store, new_id, clock_iso, stamp_created, touch

USABLE_KIT_STATES = {"QUARANTINED_RECEIPT", "AVAILABLE", "QUARANTINED_EXCURSION", "ALLOCATED"}
ON_HAND_STATES = {"AVAILABLE", "ALLOCATED", "QUARANTINED_EXCURSION", "EXPIRED", "RETURNED", "DESTRUCTION_PENDING"}
STORAGE_FEE_STATES = {"AVAILABLE", "ALLOCATED", "QUARANTINED_EXCURSION"}

MAX_CREDITABLE_MINUTES = 1440
DEGREE_STEP = 2

STUDY_TERMINAL = {"CLOSED"}
SITE_TERMINAL = {"CLOSED"}
KIT_TERMINAL = {"DESTROYED"}
SUBJECT_TERMINAL = {"COMPLETED", "WITHDRAWN"}
DESTRUCTION_TERMINAL = {"FINALIZED", "VOIDED"}
VISIT_TERMINAL = {"CLOSED_RECONCILED", "CLOSED_DISCREPANCY"}
EXCURSION_TERMINAL = {"RESOLVED_ACCEPTABLE", "RESOLVED_UNACCEPTABLE", "VOIDED"}
SLOT_TERMINAL = {"RELEASED"}


# ---------------------------------------------------------------------------
# Serializers (arm-code masking per PRD §2.8)
# ---------------------------------------------------------------------------

def serialize(entity, kind, ctx=None):
    """Return a shallow copy of the stored entity dict with masking applied."""
    out = {k: v for k, v in entity.items() if not k.startswith("_")}
    if kind == "slot":
        if ctx is not None and not ctx.can_see_arm_codes:
            out["arm_code"] = None
    elif kind == "unblinding_request":
        if ctx is not None and not ctx.can_see_arm_codes:
            out["revealed_arm_code"] = None
    return out


def serialize_list(items, kind, ctx=None):
    return [serialize(i, kind, ctx) for i in items]


# ---------------------------------------------------------------------------
# Kit ledger (PRD §2.10)
# ---------------------------------------------------------------------------

def book_on_hand(kit):
    return (kit["units_received"] - kit["units_dispensed"] + kit["units_returned"]
            - kit["units_destroyed"] - kit["units_lost"])


def recompute_kit_balance(kit):
    kit["on_hand_units"] = book_on_hand(kit)


# ---------------------------------------------------------------------------
# Lot usable-count recompute + auto-resupply (PRD §3.2)
# ---------------------------------------------------------------------------

def kits_of_lot(lot_id):
    return [k for k in store.kits.values() if k["lot_id"] == lot_id]


def usable_count(lot_id):
    return sum(1 for k in store.kits.values()
               if k["lot_id"] == lot_id and k["status"] in USABLE_KIT_STATES)


def _next_resupply_number(lot_id):
    n = store.resupply_seq.get(lot_id, 0) + 1
    store.resupply_seq[lot_id] = n
    return n


def create_resupply(lot, site_id, count):
    """Auto-create replacement kits in IN_TRANSIT for lot at site.

    kit_number = 'RS-' + lot_number + '-' + N, N continuing the lot's resupply
    sequence (1-based count of resupply kits ever created for the lot).
    """
    created = []
    for _ in range(count):
        n = _next_resupply_number(lot["id"])
        kit = {
            "id": new_id(),
            "lot_id": lot["id"],
            "site_id": site_id,
            "kit_number": f"RS-{lot['lot_number']}-{n}",
            "status": "IN_TRANSIT",
            "pre_quarantine_status": None,
            "excursion_id": None,
            "allocated_subject_id": None,
            "units_received": 0,
            "units_dispensed": 0,
            "units_returned": 0,
            "units_destroyed": 0,
            "units_lost": 0,
            "on_hand_units": 0,
        }
        stamp_created(kit)
        store.kits[kit["id"]] = kit
        created.append(kit)
    return created


def recompute_lot_usable(lot_id, left_usable_site_counts=None):
    """After kit mutations: if lot ACTIVE and zero usable kits -> DEPLETED + resupply.

    left_usable_site_counts: optional dict {site_id: n_kits_that_left_usable_in_triggering_mutation}
    used to size the auto-resupply. When None, no resupply sizing info — resupply count is 0
    per site (still flips to DEPLETED).
    """
    lot = store.lots.get(lot_id)
    if lot is None:
        return []
    if lot["status"] != "ACTIVE":
        return []
    if usable_count(lot_id) > 0:
        return []
    lot["status"] = "DEPLETED"
    touch(lot)
    resupplied = []
    study = store.studies.get(lot["study_id"])
    if study is not None and study["status"] == "ACTIVE" and left_usable_site_counts:
        for site_id, n in left_usable_site_counts.items():
            if n <= 0:
                continue
            site = store.sites.get(site_id)
            if site is not None and site["status"] == "ACTIVE":
                resupplied.extend(create_resupply(lot, site_id, n))
    return resupplied


# ---------------------------------------------------------------------------
# Temperature excursions (PRD §3.4)
# ---------------------------------------------------------------------------

def site_lot_ranges(site_id):
    """Distinct (min,max) ranges of lots having kits physically at the site.

    A lot 'has kits stored at the site' when any of its kits carries site_id == site
    (regardless of kit status, but excluding DESTROYED/IN_TRANSIT since those are
    not in storage). We consider kits in any status except DESTROYED.
    """
    ranges = []
    seen_lots = set()
    for kit in store.kits.values():
        if kit["site_id"] != site_id or kit["status"] == "DESTROYED":
            continue
        if kit["lot_id"] in seen_lots:
            continue
        lot = store.lots.get(kit["lot_id"])
        if lot is None:
            continue
        seen_lots.add(lot["id"])
        ranges.append((lot["storage_temp_min_celsius"], lot["storage_temp_max_celsius"], lot))
    return ranges


def violated_lots_at_site(site_id, celsius):
    """Lots with kits stored at site whose inclusive range is violated by celsius."""
    out = []
    for lo, hi, lot in site_lot_ranges(site_id):
        if celsius < lo or celsius > hi:
            out.append(lot)
    return out


def _find_open_excursion(site_id):
    for ex in store.excursions.values():
        if ex["site_id"] == site_id and ex["status"] == "OPEN":
            return ex
    return None


def record_temperature(site_id, celsius, source):
    """Create a TemperatureLog; open/extend excursion and cascade-quarantine kits
    when out of range for any stored lot. Returns (log, excursion_or_None)."""
    now = store.clock
    violated = violated_lots_at_site(site_id, celsius)
    log = {
        "id": new_id(),
        "site_id": site_id,
        "celsius": celsius,
        "source": source,
        "recorded_at": clock_iso(),
        "excursion_id": None,
    }
    # TemperatureLog carries only id + created_at among the common fields (PRD §2.4)
    log["created_at"] = clock_iso()

    excursion = None
    if violated:
        excursion = _find_open_excursion(site_id)
        if excursion is None:
            excursion = {
                "id": new_id(),
                "site_id": site_id,
                "status": "OPEN",
                "window_start": clock_iso(),
                "window_end": clock_iso(),
                "min_observed_celsius": celsius,
                "max_observed_celsius": celsius,
                "severity_minutes_charged": 0,
                "resolution_rationale": None,
                "reference_temp_min_celsius": None,
                "reference_temp_max_celsius": None,
            }
            stamp_created(excursion)
            store.excursions[excursion["id"]] = excursion
        else:
            excursion["window_end"] = clock_iso()
            excursion["min_observed_celsius"] = min(excursion["min_observed_celsius"], celsius)
            excursion["max_observed_celsius"] = max(excursion["max_observed_celsius"], celsius)
            touch(excursion)
        log["excursion_id"] = excursion["id"]

        # Cascade-quarantine every AVAILABLE/ALLOCATED kit at the site whose lot's
        # range is violated by this reading.
        violated_lot_ids = {lot["id"] for lot in violated}
        for kit in store.kits.values():
            if kit["site_id"] != site_id:
                continue
            if kit["status"] not in ("AVAILABLE", "ALLOCATED"):
                continue
            if kit["lot_id"] not in violated_lot_ids:
                continue
            kit["pre_quarantine_status"] = kit["status"]
            kit["status"] = "QUARANTINED_EXCURSION"
            kit["excursion_id"] = excursion["id"]
            touch(kit)

    store.temperature_logs[log["id"]] = log
    return log, excursion


def compute_severity(excursion):
    """PRD §3.4 six-step severity math against the snapshot reference range."""
    ref_min = excursion["reference_temp_min_celsius"]
    ref_max = excursion["reference_temp_max_celsius"]
    ws = excursion["window_start"]
    we = excursion["window_end"]
    start = _parse_stored(ws)
    end = _parse_stored(we)
    duration_minutes = int((end - start).total_seconds() // 60)
    capped = min(duration_minutes, MAX_CREDITABLE_MINUTES)
    below = excursion["min_observed_celsius"] < ref_min
    above = excursion["max_observed_celsius"] > ref_max
    if below and above:
        side_multiplier = 4
    elif below:
        side_multiplier = 3
    elif above:
        side_multiplier = 2
    else:
        side_multiplier = 0
    dev_below = (ref_min - excursion["min_observed_celsius"]) if below else 0
    dev_above = (excursion["max_observed_celsius"] - ref_max) if above else 0
    peak_deviation = max(dev_below, dev_above)
    degree_band = max(1, math.ceil(peak_deviation / DEGREE_STEP))
    return capped * side_multiplier * degree_band


def _parse_stored(ts):
    s = ts
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def kits_linked_to_excursion(excursion_id):
    """Kits currently linked (excursion_id == excursion.id)."""
    return [k for k in store.kits.values() if k.get("excursion_id") == excursion_id]


def assess_excursion(excursion, outcome, rationale):
    """TemperatureExcursion machine: OPEN -> RESOLVED_ACCEPTABLE / RESOLVED_UNACCEPTABLE,
    RESOLVED_ACCEPTABLE -> VOIDED."""
    if outcome == "VOID":
        if excursion["status"] != "RESOLVED_ACCEPTABLE":
            raise E.excursion_already_resolved()
        # reverse the budget charge
        charged_lots = _charged_lots(excursion)
        for lot in charged_lots:
            lot["stability_minutes_consumed"] = lot.get("stability_minutes_consumed", 0) - excursion["severity_minutes_charged"]
            touch(lot)
        excursion["status"] = "VOIDED"
        if rationale is not None:
            excursion["resolution_rationale"] = rationale
        touch(excursion)
        return excursion

    if excursion["status"] != "OPEN":
        raise E.excursion_already_resolved()

    linked_kits = kits_linked_to_excursion(excursion["id"])
    # Snapshot the reference range: min over lower bounds, max over upper bounds of
    # the affected kits' lots.
    lots_by_id = {}
    for kit in linked_kits:
        lot = store.lots.get(kit["lot_id"])
        if lot is not None:
            lots_by_id[lot["id"]] = lot
    if lots_by_id:
        excursion["reference_temp_min_celsius"] = min(l["storage_temp_min_celsius"] for l in lots_by_id.values())
        excursion["reference_temp_max_celsius"] = max(l["storage_temp_max_celsius"] for l in lots_by_id.values())
    else:
        excursion["reference_temp_min_celsius"] = excursion["min_observed_celsius"]
        excursion["reference_temp_max_celsius"] = excursion["max_observed_celsius"]

    severity = compute_severity(excursion)
    excursion["severity_minutes_charged"] = severity
    excursion["resolution_rationale"] = rationale

    # Charge every distinct lot owning a linked kit; remember the charged set so a
    # later VOID can reverse it exactly (kits' excursion_id is cleared on restore).
    excursion["_charged_lot_ids"] = list(lots_by_id.keys())
    for lot in lots_by_id.values():
        lot["stability_minutes_consumed"] = lot.get("stability_minutes_consumed", 0) + severity
        touch(lot)

    # Count kits leaving usable states per (lot, site) in this mutation so a
    # lot that depletes triggers the §3.2 auto-resupply at the right size.
    left_usable = {}
    if outcome == "ACCEPTABLE":
        excursion["status"] = "RESOLVED_ACCEPTABLE"
        # Restore per pre_quarantine_status except stability-exhausted lots.
        for kit in linked_kits:
            lot = store.lots.get(kit["lot_id"])
            if lot is not None and lot["stability_minutes_consumed"] >= lot["stability_budget_minutes"]:
                continue  # remains QUARANTINED_EXCURSION
            restore_to = kit.get("pre_quarantine_status") or "QUARANTINED_RECEIPT"
            kit["status"] = restore_to
            kit["excursion_id"] = None
            kit["pre_quarantine_status"] = None
            touch(kit)
    else:  # UNACCEPTABLE
        excursion["status"] = "RESOLVED_UNACCEPTABLE"
        for kit in linked_kits:
            if kit["status"] in USABLE_KIT_STATES:
                per_site = left_usable.setdefault(kit["lot_id"], {})
                per_site[kit["site_id"]] = per_site.get(kit["site_id"], 0) + 1
            kit["status"] = "DESTRUCTION_PENDING"
            kit["pre_quarantine_status"] = None
            # excursion_id retained for audit
            touch(kit)

    touch(excursion)

    # Trigger lot usable-count recompute for affected lots.
    for lot in lots_by_id.values():
        recompute_lot_usable(lot["id"],
                             left_usable_site_counts=left_usable.get(lot["id"]))
    return excursion


def _charged_lots(excursion):
    """Lots charged at assessment. We reconstruct from the excursion's charge
    footprint: every distinct lot that owned a kit linked at assessment time.
    Since kits keep excursion_id only while quarantined, we instead track the
    charged lot ids on the excursion at charge time."""
    ids = excursion.get("_charged_lot_ids") or []
    return [store.lots[i] for i in ids if i in store.lots]


# ---------------------------------------------------------------------------
# Study auto-suspension (PRD §3.8)
# ---------------------------------------------------------------------------

def recompute_unblinded_count_and_maybe_suspend(study):
    count = sum(1 for s in store.subjects.values()
                if s["site_id"] in _study_site_ids(study["id"]) and s["blinded_status"] == "UNBLINDED")
    study["unblinded_subject_count"] = count
    randomized = study.get("randomized_subject_count", 0)
    threshold = study.get("unblinding_suspension_threshold_pct", 10)
    if (randomized > 0 and study["status"] == "ACTIVE"
            and count * 100 >= threshold * randomized):
        study["status"] = "SUSPENDED"
        # cascade ACTIVE sites to ON_HOLD
        for site in store.sites.values():
            if site["study_id"] == study["id"] and site["status"] == "ACTIVE":
                site["status"] = "ON_HOLD"
                touch(site)
    touch(study)


def _study_site_ids(study_id):
    return {s["id"] for s in store.sites.values() if s["study_id"] == study_id}


# ---------------------------------------------------------------------------
# Expiry sweep (PRD §3.2, ops endpoint)
# ---------------------------------------------------------------------------

def expiry_sweep():
    """Three-phase expiry sweep. Returns counters dict."""
    now = store.clock
    kits_expired = 0
    expired_by_lot_site = {}  # (lot_id, site_id) -> count
    affected_lot_ids = set()

    # Phase 1: kits in usable states whose lot's expiry_date has been reached -> EXPIRED
    for kit in list(store.kits.values()):
        if kit["status"] not in ("QUARANTINED_RECEIPT", "AVAILABLE", "QUARANTINED_EXCURSION", "ALLOCATED"):
            continue
        lot = store.lots.get(kit["lot_id"])
        if lot is None:
            continue
        expiry = _parse_stored(lot["expiry_date"]) if isinstance(lot["expiry_date"], str) else lot["expiry_date"]
        if now >= expiry:
            kit["status"] = "EXPIRED"
            touch(kit)
            kits_expired += 1
            key = (lot["id"], kit["site_id"])
            expired_by_lot_site[key] = expired_by_lot_site.get(key, 0) + 1
            affected_lot_ids.add(lot["id"])

    # Phase 2: lot lifecycle transitions at expiry
    lots_expired = 0
    for lot in list(store.lots.values()):
        expiry = _parse_stored(lot["expiry_date"]) if isinstance(lot["expiry_date"], str) else lot["expiry_date"]
        if now < expiry:
            continue
        if lot["status"] == "ACTIVE":
            lot["status"] = "EXPIRED"
            touch(lot)
            lots_expired += 1
        elif lot["status"] == "DEPLETED":
            lot["status"] = "CLOSED"
            touch(lot)

    # Phase 3: resupply for lots left with zero usable kits whose study+site are ACTIVE
    resupply_kits_created = 0
    for lot_id in affected_lot_ids:
        lot = store.lots.get(lot_id)
        if lot is None:
            continue
        if lot["status"] == "ACTIVE":
            # shouldn't normally happen since expiry transitions ACTIVE->EXPIRED above,
            # but guard anyway
            pass
        if usable_count(lot_id) > 0:
            continue
        if lot["status"] == "ACTIVE":
            lot["status"] = "DEPLETED"
            touch(lot)
        study = store.studies.get(lot["study_id"])
        if study is None or study["status"] != "ACTIVE":
            continue
        for (lid, site_id), n in expired_by_lot_site.items():
            if lid != lot_id or n <= 0:
                continue
            site = store.sites.get(site_id)
            if site is not None and site["status"] == "ACTIVE":
                created = create_resupply(lot, site_id, n)
                resupply_kits_created += len(created)

    return {"kits_expired": kits_expired, "lots_expired": lots_expired,
            "resupply_kits_created": resupply_kits_created}
