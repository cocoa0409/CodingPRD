"""Domain logic: computed fields, posture engine, cascades, selector, sweep.

Implements the calculation rules of scaffold §1.3 and the state-machine side
effects of §1.2 exactly as specified in the PRD.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import db
from errors import raise_err, ERR_NO_ELIGIBLE_BOXES, ERR_PLAN_STALE


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BOOK_CATEGORIES = {"FICTION", "NONFICTION", "CHILDREN", "YOUNG_ADULT", "REFERENCE"}

SEASON_BY_MONTH = {
    12: "WINTER", 1: "WINTER", 2: "WINTER",
    3: "SPRING", 4: "SPRING", 5: "SPRING",
    6: "SUMMER", 7: "SUMMER", 8: "SUMMER",
    9: "FALL", 10: "FALL", 11: "FALL",
}

SLA_BASE_HOURS = {"LOW": 336, "MEDIUM": 168, "HIGH": 72, "CRITICAL": 24}

TIER_LIMITS = {"NONE": 1, "BRONZE": 1, "SILVER": 2, "GOLD": 3, "PLATINUM": 5}

OPEN_MAINTENANCE_STATUSES = {"SCHEDULED", "REOPENED"}
UPHELD_COMPLAINT_STATUSES = {"RESOLVED_UPHELD", "ADJUDICATED_UPHELD"}
ACCEPTED_ITEM_STATUSES = {"AVAILABLE", "ALLOCATED", "DISPATCHED", "PLACED"}
TERMINAL_ITEM_STATUSES = {"PLACED", "RECYCLED"}
NON_TERMINAL_DRIVE_STATUSES = {"PROPOSED", "APPROVED", "OPEN", "COLLECTION_CLOSED"}


# ---------------------------------------------------------------------------
# Small time helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return db.clock()


def _parse(dt_str: str) -> datetime:
    return db.parse_iso(dt_str)


def _days_between(earlier: datetime, later: datetime) -> int:
    """Whole days: floor of elapsed-second difference / 86400 (PRD §2.9)."""
    return int((later - earlier).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Steward computed fields (recognition ledger aggregation — §3.2)
# ---------------------------------------------------------------------------

def steward_recognition(steward: dict) -> dict:
    """Compute lifetime_points, rolling_points, recognition_tier, strike_count,
    training_level for a steward against the current logical clock."""
    now = _now()
    events = [e for e in db.recognition_events.values() if e["steward_id"] == steward["id"]]
    lifetime = max(0, sum(e["points_delta"] for e in events))
    window_start = now - timedelta(days=365)
    rolling_raw = sum(
        e["points_delta"] for e in events
        if window_start <= _parse(e["created_at"]) <= now
    )
    rolling = max(0, rolling_raw)
    if rolling >= 1000:
        tier = "PLATINUM"
    elif rolling >= 600:
        tier = "GOLD"
    elif rolling >= 300:
        tier = "SILVER"
    elif rolling >= 100:
        tier = "BRONZE"
    else:
        tier = "NONE"
    # strike_count: upheld complaints against boxes owned by this steward
    strike = 0
    for c in db.complaints.values():
        if c["status"] not in UPHELD_COMPLAINT_STATUSES:
            continue
        box = db.boxes.get(c["box_id"])
        if box is not None and box["steward_id"] == steward["id"]:
            strike += 1
    # training_level: distinct modules with a PASSED completion
    passed_modules = {
        t["module_id"]
        for t in db.training_completions.values()
        if t["steward_id"] == steward["id"] and t["result"] == "PASSED"
    }
    return {
        "lifetime_points": lifetime,
        "rolling_points": rolling,
        "recognition_tier": tier,
        "strike_count": strike,
        "training_level": len(passed_modules),
    }


def add_recognition_event(steward_id: str, event_type: str, points_delta: int,
                          source_type: str, source_id: str) -> dict:
    """Append an immutable RecognitionEvent and bump the steward's version —
    a cascaded recognition/level recompute advances Steward.version (§2.7)."""
    evt = {
        "steward_id": steward_id,
        "event_type": event_type,
        "points_delta": points_delta,
        "source_type": source_type,
        "source_id": source_id,
    }
    db.stamp_new_light(evt)
    db.recognition_events[evt["id"]] = evt
    steward = db.stewards.get(steward_id)
    if steward is not None:
        db.touch(steward)
    return evt


def has_passed(steward_id: str, module_id: str) -> bool:
    return any(
        t["steward_id"] == steward_id and t["module_id"] == module_id and t["result"] == "PASSED"
        for t in db.training_completions.values()
    )


def prerequisite_chain_passed(steward_id: str, module: dict) -> bool:
    """Every module in the prerequisite chain must be PASSED (PRD §3.1)."""
    visited = set()
    current = module.get("prerequisite_module_id")
    while current:
        if current in visited:
            break  # defensive; graph is kept acyclic
        visited.add(current)
        if not has_passed(steward_id, current):
            return False
        prereq = db.training_modules.get(current)
        if prereq is None:
            return False
        current = prereq.get("prerequisite_module_id")
    return True


def module_would_cycle(module_id: str | None, prerequisite_id: str | None) -> bool:
    """True if setting module_id's prerequisite to prerequisite_id closes a loop."""
    if not module_id or not prerequisite_id:
        return False
    if module_id == prerequisite_id:
        return True
    visited = set()
    current = prerequisite_id
    while current:
        if current in visited:
            break
        visited.add(current)
        if current == module_id:
            return True
        mod = db.training_modules.get(current)
        if mod is None:
            break
        current = mod.get("prerequisite_module_id")
    return False


# ---------------------------------------------------------------------------
# Box computed fields (§3.3 / §3.4)
# ---------------------------------------------------------------------------

def box_current_stock(box: dict) -> int:
    return sum(
        1 for a in db.allocations.values()
        if a["box_id"] == box["id"] and a["status"] == "PLACED"
    )


def box_open_maintenance_count(box: dict, severity: str) -> int:
    return sum(
        1 for m in db.maintenance_requests.values()
        if m["box_id"] == box["id"]
        and m.get("severity") == severity
        and m["status"] in OPEN_MAINTENANCE_STATUSES
    )


def box_upheld_complaints_90d(box: dict) -> int:
    now = _now()
    window_start = now - timedelta(days=90)
    count = 0
    for c in db.complaints.values():
        if c["box_id"] != box["id"] or c["status"] not in UPHELD_COMPLAINT_STATUSES:
            continue
        upheld_at = c.get("upheld_at")
        if upheld_at and window_start <= _parse(upheld_at) <= now:
            count += 1
    return count


def box_days_since_activity(box: dict):
    """floor((now - last_activity_at) / 86400); null while last_activity_at null."""
    last = box.get("last_activity_at")
    if not last:
        return None
    return _days_between(_parse(last), _now())


def compute_posture(box: dict) -> str:
    """box_listing_posture (§1.3): fixed precedence order."""
    cs = box["charter_status"]
    if cs in ("DRAFT", "CHARTERED"):
        return "UNLISTED"
    if cs in ("SUSPENDED", "DECOMMISSIONED"):
        return "DELISTED"
    crit = box_open_maintenance_count(box, "CRITICAL")
    high = box_open_maintenance_count(box, "HIGH")
    upheld90 = box_upheld_complaints_90d(box)
    stale = box_days_since_activity(box) or 0
    if crit >= 1 or upheld90 >= 3 or stale >= 180:
        return "DELISTED"
    if upheld90 >= 1 or high >= 1 or stale >= 120:
        return "FLAGGED"
    return "LISTED"


def recompute_posture(box: dict) -> bool:
    """Recompute and store listing_posture. Entering DELISTED from LISTED or
    FLAGGED fires the recall cascade (§3.4). Returns True if posture changed."""
    new = compute_posture(box)
    old = box["listing_posture"]
    if new == old:
        return False
    box["listing_posture"] = new
    db.touch(box)
    if new == "DELISTED" and old in ("LISTED", "FLAGGED"):
        recall_cascade(box)
    return True


def refresh_box_activity(box: dict) -> None:
    """Set last_activity_at to now and recompute posture (bump on mutation)."""
    box["last_activity_at"] = db.now_logical_iso()
    db.touch(box)
    recompute_posture(box)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------

def bubble_up_run(run_id: str) -> None:
    """Run completes when every allocation is PLACED or CANCELLED (§3.8)."""
    run = db.distribution_runs.get(run_id)
    if run is None or run["status"] not in ("CONFIRMED", "DISPATCHED"):
        return
    allocs = [a for a in db.allocations.values() if a["run_id"] == run_id]
    if allocs and all(a["status"] in ("PLACED", "CANCELLED") for a in allocs):
        run["status"] = "COMPLETED"
        db.touch(run)


def bubble_up_batch(batch_id: str) -> None:
    """A SORTED batch closes itself once every item is PLACED or RECYCLED."""
    batch = db.batches.get(batch_id)
    if batch is None or batch["status"] != "SORTED":
        return
    items = [i for i in db.book_items.values() if i["batch_id"] == batch_id]
    if items and all(i["status"] in TERMINAL_ITEM_STATUSES for i in items):
        batch["status"] = "CLOSED"
        db.touch(batch)


def _cancel_allocation(alloc: dict) -> None:
    """RESERVED/DISPATCHED -> CANCELLED; its book returns to AVAILABLE."""
    alloc["status"] = "CANCELLED"
    db.touch(alloc)
    item = db.book_items.get(alloc["book_item_id"])
    if item is not None and item["status"] in ("ALLOCATED", "DISPATCHED"):
        item["status"] = "AVAILABLE"
        item["box_id"] = None
        db.touch(item)


def recall_cascade(box: dict) -> None:
    """In-flight allocations for the box are cancelled and their books return
    to AVAILABLE; run bubble-up checks fire (§3.4)."""
    for alloc in list(db.allocations.values()):
        if alloc["box_id"] == box["id"] and alloc["status"] in ("RESERVED", "DISPATCHED"):
            _cancel_allocation(alloc)
            bubble_up_run(alloc["run_id"])


def suspend_box(box: dict) -> None:
    """ACTIVE -> SUSPENDED: stamps suspended_at, DELISTED, recall cascade."""
    box["charter_status"] = "SUSPENDED"
    box["suspended_at"] = db.now_logical_iso()
    box["listing_posture"] = "DELISTED"
    db.touch(box)
    recall_cascade(box)


def decommission_box(box: dict) -> None:
    """-> DECOMMISSIONED with the full allocation/item unwind (§3.3)."""
    for alloc in list(db.allocations.values()):
        if alloc["box_id"] != box["id"]:
            continue
        if alloc["status"] in ("RESERVED", "DISPATCHED"):
            _cancel_allocation(alloc)
        elif alloc["status"] == "PLACED":
            alloc["status"] = "REMOVED"
            db.touch(alloc)
            item = db.book_items.get(alloc["book_item_id"])
            if item is not None and item["status"] in ("PLACED", "QUARANTINED"):
                item["status"] = "RECYCLED"
                item["box_id"] = None
                db.touch(item)
                bubble_up_batch(item["batch_id"])
    box["charter_status"] = "DECOMMISSIONED"
    box["listing_posture"] = "DELISTED"
    db.touch(box)


# ---------------------------------------------------------------------------
# Complaint upheld / compensation cascades (§3.6)
# ---------------------------------------------------------------------------

def complaint_upheld_cascade(complaint: dict) -> None:
    """Fire the upheld cascade: -60 event, target-category quarantine,
    posture recompute. strike_count recomputes from the live complaint set."""
    box = db.boxes.get(complaint["box_id"])
    if box is not None:
        add_recognition_event(
            box["steward_id"], "COMPLAINT_UPHELD", -60, "COMPLAINT", complaint["id"]
        )
    target = complaint.get("target_category")
    if target:
        for item in list(db.book_items.values()):
            if (
                item.get("box_id") == complaint["box_id"]
                and item["category"] == target
                and item["status"] == "PLACED"
            ):
                item["status"] = "QUARANTINED"
                item["_quarantined_by"] = complaint["id"]
                db.touch(item)
    if box is not None:
        recompute_posture(box)


def complaint_dismissal_compensation(complaint: dict) -> None:
    """Adjudicated DISMISSED after an upheld ruling: +60 compensation event and
    every book quarantined by this complaint returns QUARANTINED -> PLACED."""
    box = db.boxes.get(complaint["box_id"])
    if box is not None:
        add_recognition_event(
            box["steward_id"], "COMPLAINT_UPHELD", 60, "COMPLAINT", complaint["id"]
        )
    for item in list(db.book_items.values()):
        if item.get("_quarantined_by") == complaint["id"] and item["status"] == "QUARANTINED":
            item["status"] = "PLACED"
            db.touch(item)
    if box is not None:
        recompute_posture(box)


# ---------------------------------------------------------------------------
# Maintenance calculations (§3.5)
# ---------------------------------------------------------------------------

def season_for(dt: datetime) -> str:
    return SEASON_BY_MONTH[dt.astimezone(timezone.utc).month]


def sla_deadline(triaged_at: datetime, severity: str, season_multiplier: float) -> datetime:
    hours = SLA_BASE_HOURS[severity] * season_multiplier
    return triaged_at + timedelta(hours=hours)


def parts_reimbursement(parts: list, labor_hours) -> int:
    """Per-line round_half_up(qty * unit_cost_cents * 0.8), then sum, then add
    round_half_up(labor_hours * 500), capped at 15000 (§1.3, §2.9)."""
    subtotal = 0
    for line in parts:
        line_amount = Decimal(line["qty"]) * Decimal(line["unit_cost_cents"]) * Decimal("0.8")
        quantized = line_amount.quantize(Decimal("1"), rounding="ROUND_HALF_UP")
        subtotal += int(quantized)
    labor = int((Decimal(str(labor_hours)) * 500).quantize(Decimal("1"), rounding="ROUND_HALF_UP"))
    return min(subtotal + labor, 15000)


# ---------------------------------------------------------------------------
# Drive computed fields (§3.7)
# ---------------------------------------------------------------------------

def drive_linked_batch(drive: dict):
    batch_id = drive.get("_linked_batch_id")
    if batch_id:
        return db.batches.get(batch_id)
    for b in db.batches.values():
        if b.get("drive_id") == drive["id"]:
            return b
    return None


def drive_metrics(drive: dict) -> dict:
    """drive_fulfillment (§1.3): gross counts every item; net excludes
    QUARANTINED and RECYCLED; percentages are floor-divided integers."""
    batch = drive_linked_batch(drive)
    items = []
    if batch is not None:
        items = [i for i in db.book_items.values() if i["batch_id"] == batch["id"]]
    collected = len(items)
    accepted = sum(1 for i in items if i["status"] in ACCEPTED_ITEM_STATUSES)
    goal = drive["goal_books"]
    gross = (collected * 100) // goal if goal else 0
    net = (accepted * 100) // goal if goal else 0
    return {
        "collected_count": collected,
        "accepted_count": accepted,
        "fulfillment_pct_gross": gross,
        "fulfillment_pct_net": net,
        "qualifies_for_bonus": net >= 80,
    }


def school_drives_completed(school: dict) -> int:
    return sum(
        1 for d in db.drives.values()
        if d["school_id"] == school["id"] and d["status"] == "COMPLETED"
    )


def batch_counters(batch: dict) -> tuple[int, int]:
    items = [i for i in db.book_items.values() if i["batch_id"] == batch["id"]]
    graded = sum(1 for i in items if i.get("condition_grade") is not None)
    return len(items), graded


# ---------------------------------------------------------------------------
# Distribution selector — need_score (§1.3 / §3.8)
# ---------------------------------------------------------------------------

def build_plan(batch: dict) -> list[dict]:
    """Compute the plan_snapshot for a new DistributionRun.

    Eligible boxes: charter ACTIVE, posture LISTED, free capacity > 0.
    need_score = min(capacity_remaining, 10) * 2 + min(days_since_activity, 60)
                 + (20 if region matches batch)
    Ranked need_score DESC, ties box.created_at ASC. qty = min(capacity
    remaining, 10, remaining items). Empty plan -> ERR_NO_ELIGIBLE_BOXES.
    """
    available = [
        i for i in db.book_items.values()
        if i["batch_id"] == batch["id"]
        and i["status"] == "AVAILABLE"
        and i.get("condition_grade") is not None
    ]
    available = sorted(available, key=lambda i: (i["created_at"], i["_seq"]))

    eligible = []
    for box in db.boxes.values():
        if box["charter_status"] != "ACTIVE" or box["listing_posture"] != "LISTED":
            continue
        cap_remaining = box["capacity_books"] - box_current_stock(box)
        if cap_remaining <= 0:
            continue
        staleness = min(box_days_since_activity(box) or 0, 60)
        bonus = 20 if box["region_code"] == batch["region_code"] else 0
        score = min(cap_remaining, 10) * 2 + staleness + bonus
        eligible.append((box, cap_remaining, score))

    eligible.sort(key=lambda t: (-t[2], t[0]["created_at"], t[0]["_seq"]))

    remaining = len(available)
    plan = []
    for box, cap_remaining, score in eligible:
        qty = min(cap_remaining, 10, remaining)
        if qty <= 0:
            continue
        plan.append({"box_id": box["id"], "quantity": qty, "need_score": score})
        remaining -= qty

    if not plan:
        raise_err(ERR_NO_ELIGIBLE_BOXES, "No eligible boxes or no available graded items")
    return plan


def validate_plan_fresh(run: dict) -> None:
    """Confirm-time re-validation of the frozen plan (ERR_PLAN_STALE)."""
    batch = db.batches.get(run["batch_id"])
    for entry in run["plan_snapshot"]:
        box = db.boxes.get(entry["box_id"])
        if (
            box is None
            or box["charter_status"] != "ACTIVE"
            or box["listing_posture"] != "LISTED"
            or (box["capacity_books"] - box_current_stock(box)) < entry["quantity"]
        ):
            raise_err(ERR_PLAN_STALE, "A planned box no longer satisfies the plan")
    available_graded = sum(
        1 for i in db.book_items.values()
        if batch is not None
        and i["batch_id"] == batch["id"]
        and i["status"] == "AVAILABLE"
        and i.get("condition_grade") is not None
    )
    if available_graded < run["planned_item_count"]:
        raise_err(ERR_PLAN_STALE, "Batch lacks enough available graded items")


def materialize_allocations(run: dict) -> None:
    """Create one RESERVED allocation per planned item: boxes in snapshot
    order, items drawn from the AVAILABLE graded pool created_at ASC; the
    allocations receive monotonically increasing created_at in plan order."""
    batch = db.batches[run["batch_id"]]
    pool = sorted(
        (
            i for i in db.book_items.values()
            if i["batch_id"] == batch["id"]
            and i["status"] == "AVAILABLE"
            and i.get("condition_grade") is not None
        ),
        key=lambda i: (i["created_at"], i["_seq"]),
    )
    now = _now()
    idx = 0
    cursor = 0
    for entry in run["plan_snapshot"]:
        for _ in range(entry["quantity"]):
            item = pool[cursor]
            cursor += 1
            alloc = {
                "run_id": run["id"],
                "book_item_id": item["id"],
                "box_id": entry["box_id"],
                "status": "RESERVED",
                "placed_at": None,
            }
            db.stamp_new(alloc)
            alloc["created_at"] = db.format_iso(now + timedelta(milliseconds=idx))
            alloc["updated_at"] = alloc["created_at"]
            db.allocations[alloc["id"]] = alloc
            item["status"] = "ALLOCATED"
            item["box_id"] = entry["box_id"]
            db.touch(item)
            idx += 1


# ---------------------------------------------------------------------------
# Map sweep (§3.9)
# ---------------------------------------------------------------------------

def run_sweep() -> dict:
    """The ops checkpoint. Idempotent: no clock movement -> no changes."""
    now = _now()
    counts = {
        "expired_response_count": 0,
        "opened_drive_count": 0,
        "closed_drive_count": 0,
        "suspended_box_count": 0,
        "decommissioned_box_count": 0,
        "recycled_item_count": 0,
        "posture_change_count": 0,
    }
    posture_before = {b["id"]: b["listing_posture"] for b in db.boxes.values()}

    # 1. Expire complaint response windows.
    for c in list(db.complaints.values()):
        if c["status"] == "STEWARD_RESPONSE_PENDING" and c.get("response_due_at"):
            if now >= _parse(c["response_due_at"]):
                c["status"] = "UNDER_REVIEW"
                db.touch(c)
                counts["expired_response_count"] += 1

    # 2. Open APPROVED drives whose window has started.
    for d in list(db.drives.values()):
        if d["status"] == "APPROVED" and now >= _parse(d["starts_at"]):
            d["status"] = "OPEN"
            db.touch(d)
            counts["opened_drive_count"] += 1

    # 3. Close OPEN drives whose window has ended.
    for d in list(db.drives.values()):
        if d["status"] == "OPEN" and now >= _parse(d["ends_at"]):
            d["status"] = "COLLECTION_CLOSED"
            db.touch(d)
            counts["closed_drive_count"] += 1

    # 4. Recompute every box posture (recall cascades fire on DELISTED entry).
    for box in list(db.boxes.values()):
        recompute_posture(box)

    # 5. Suspend ACTIVE boxes stale for >= 180 days.
    for box in list(db.boxes.values()):
        if box["charter_status"] == "ACTIVE":
            stale = box_days_since_activity(box) or 0
            if stale >= 180:
                suspend_box(box)
                counts["suspended_box_count"] += 1

    # 6. Decommission boxes suspended for >= 30 days.
    for box in list(db.boxes.values()):
        if box["charter_status"] == "SUSPENDED" and box.get("suspended_at"):
            if (now - _parse(box["suspended_at"])).total_seconds() >= 30 * 86400:
                decommission_box(box)
                counts["decommissioned_box_count"] += 1

    # 7. Recycle books still QUARANTINED 30 days after the upholding decision.
    for item in list(db.book_items.values()):
        if item["status"] != "QUARANTINED":
            continue
        complaint = db.complaints.get(item.get("_quarantined_by"))
        if complaint is None or not complaint.get("upheld_at"):
            continue
        if (now - _parse(complaint["upheld_at"])).total_seconds() >= 30 * 86400:
            alloc = next(
                (a for a in db.allocations.values()
                 if a["book_item_id"] == item["id"] and a["status"] == "PLACED"),
                None,
            )
            if alloc is not None:
                alloc["status"] = "REMOVED"
                db.touch(alloc)
            box_id = item.get("box_id")
            item["status"] = "RECYCLED"
            item["box_id"] = None
            db.touch(item)
            if box_id and box_id in db.boxes:
                db.touch(db.boxes[box_id])  # current_stock decremented
            bubble_up_batch(item["batch_id"])
            counts["recycled_item_count"] += 1

    counts["posture_change_count"] = sum(
        1 for b in db.boxes.values()
        if b["listing_posture"] != posture_before.get(b["id"])
    )
    return counts
