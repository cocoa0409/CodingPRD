"""Calculation rules: priority, estimated minutes, minibar totals, sampling, discrepancy."""

from decimal import Decimal

from services.common import round_half_up
from services.time_util import now_utc, parse_iso, start_of_today_utc
from db import DB


# --------------------------------------------------------------------------- #
# Cleaning task estimated minutes
# --------------------------------------------------------------------------- #
BASE_MINUTES = {"STANDARD": 25, "SUITE": 45, "PRESIDENTIAL": 75}
SOURCE_OVERHEAD = {"CHECK_OUT": 15, "STAYOVER": 0, "SCHEDULED": 10}


def compute_estimated_minutes(room: dict, task_source: str) -> int:
    return BASE_MINUTES[room["room_type"]] + SOURCE_OVERHEAD[task_source]


# --------------------------------------------------------------------------- #
# Cleaning task priority
# --------------------------------------------------------------------------- #
TASK_SOURCE_BASE = {"CHECK_OUT": 50, "STAYOVER": 30, "SCHEDULED": 20}
VIP_PRIORITY_BONUS = 30
EXPEDITE_PRIORITY_BONUS = 20
EARLY_CHECK_IN_PRIORITY_BONUS = 25
EARLY_CHECK_IN_WINDOW_HOURS = 4
SYNERGY_MULTIPLIER = Decimal("1.20")
URGENT_THRESHOLD = 100
HIGH_THRESHOLD = 70


def compute_priority(task: dict, room: dict):
    """Return (priority_score, priority_tier)."""
    base = TASK_SOURCE_BASE[task["task_source"]]
    vip_bonus = VIP_PRIORITY_BONUS if room.get("vip_flag") else 0
    expedite_bonus = EXPEDITE_PRIORITY_BONUS if task.get("expedite_flag") else 0

    early_bonus = 0
    eci = task.get("early_check_in_at")
    if eci:
        eci_dt = parse_iso(eci)
        if eci_dt is not None:
            delta = (eci_dt - now_utc()).total_seconds()
            if 0 <= delta <= EARLY_CHECK_IN_WINDOW_HOURS * 3600:
                early_bonus = EARLY_CHECK_IN_PRIORITY_BONUS

    bonus_sum = vip_bonus + expedite_bonus + early_bonus
    if vip_bonus > 0 and expedite_bonus > 0 and early_bonus > 0:
        bonus_sum = round_half_up(Decimal(bonus_sum) * SYNERGY_MULTIPLIER)

    score = base + bonus_sum
    if score >= URGENT_THRESHOLD:
        tier = "URGENT"
    elif score >= HIGH_THRESHOLD:
        tier = "HIGH"
    else:
        tier = "NORMAL"
    return score, tier


def refresh_priority(task: dict, room: dict):
    score, tier = compute_priority(task, room)
    task["priority_score"] = score
    task["priority_tier"] = tier


# --------------------------------------------------------------------------- #
# Minibar charge
# --------------------------------------------------------------------------- #
MINIBAR_TAX_RATE = Decimal("0.10")


def compute_minibar_totals(line_items, item_lookup):
    gross = 0
    for line in line_items:
        item = item_lookup[line["minibar_item_id"]]
        gross += int(item["unit_price_cents"]) * int(line["quantity"])
    tax = round_half_up(Decimal(gross) * MINIBAR_TAX_RATE)
    posted = gross + tax
    return gross, tax, posted


# --------------------------------------------------------------------------- #
# Discrepancy detection
# --------------------------------------------------------------------------- #
OCCUPIED_STATUSES = {"OCCUPIED_CLEAN", "OCCUPIED_DIRTY", "INSPECTED"}
PMS_OCCUPIED = {"OCCUPIED", "DUE_OUT"}


def compute_discrepancy(room: dict) -> bool:
    pms = room.get("pms_occupancy")
    hk = room.get("status")
    pms_says_occupied = pms in PMS_OCCUPIED
    hk_says_occupied = hk in OCCUPIED_STATUSES
    return pms_says_occupied != hk_says_occupied


def recompute_discrepancy(room: dict, *, audit_on_flip=True):
    """Recompute discrepancy_flag and emit a STATUS_DISCREPANCY audit on false->true."""
    from services.audit import append_audit
    prev = bool(room.get("discrepancy_flag", False))
    new = compute_discrepancy(room)
    room["discrepancy_flag"] = new
    if audit_on_flip and (not prev) and new:
        append_audit(
            actor_id=room.get("_last_actor", "system"),
            actor_role=None,
            action_type="EVENT_INGESTED",
            subject_entity="Room",
            subject_id=room["id"],
            detail={"alert": "STATUS_DISCREPANCY"},
        )


# --------------------------------------------------------------------------- #
# Inspection sampling
# --------------------------------------------------------------------------- #
SAMPLE_EVERY_N = 3


def compute_sampled_flag(submitting_task: dict) -> bool:
    """Compute whether THIS submission requires sampling.

    Called when a task transitions IN_PROGRESS → SUBMITTED. The
    submitting_task has already had its submitted_at populated.
    """
    housekeeper_id = submitting_task.get("assigned_housekeeper_id")
    if not housekeeper_id:
        return False
    start = start_of_today_utc()
    pivot = parse_iso(submitting_task["submitted_at"])

    # Collect today's submissions by this housekeeper at or before pivot
    candidates = []
    for t in DB["cleaning_tasks"].values():
        if t.get("assigned_housekeeper_id") != housekeeper_id:
            continue
        if t["status"] not in {"SUBMITTED", "COMPLETED", "CANCELLED"}:
            continue
        sub_at = parse_iso(t.get("submitted_at"))
        if sub_at is None or sub_at < start:
            continue
        if sub_at > pivot:
            continue
        candidates.append(t)

    candidates.sort(key=lambda t: (parse_iso(t["submitted_at"]), t["id"]))
    # n = position of submitting_task in this ordered list (1-indexed)
    n = None
    for idx, t in enumerate(candidates, start=1):
        if t["id"] == submitting_task["id"]:
            n = idx
            break
    if n is None:
        # Fallback: append at end
        n = len(candidates) + 1

    sampled = (n % SAMPLE_EVERY_N == 0)

    # Check previous submission for FAIL
    if n >= 2:
        prev_task = candidates[n - 2]
        prev_id = prev_task["id"]
        for rec in DB["inspection_records"].values():
            if rec.get("cleaning_task_id") == prev_id and rec.get("outcome") == "FAIL":
                sampled = True
                break

    return sampled


# --------------------------------------------------------------------------- #
# Linen replacement required
# --------------------------------------------------------------------------- #
def compute_linen_replacement_required(room: dict, task: dict, linen_type: dict) -> bool:
    """Return True if the given LinenType needs replacement on this room/task visit."""
    movements = [
        m for m in DB["linen_movements"].values()
        if m.get("room_id") == room["id"]
        and m.get("linen_type_id") == linen_type["id"]
        and m.get("status") in {"SENT_TO_LAUNDRY", "RETURNED", "LOSS_REPORTED", "RESOLVED"}
    ]
    last = None
    if movements:
        movements.sort(key=lambda m: parse_iso(m["created_at"]))
        last = movements[-1]

    policy = linen_type["replacement_policy"]
    if policy == "PER_STAY":
        if task["task_source"] == "CHECK_OUT":
            return True
        if room.get("status") == "OCCUPIED_DIRTY" and last is None:
            return True
        return False
    elif policy == "SCHEDULED":
        if last is None:
            return True
        last_created = parse_iso(last["created_at"])
        elapsed_seconds = (now_utc() - last_created).total_seconds()
        elapsed_days = int(elapsed_seconds // 86400)
        return elapsed_days >= int(linen_type.get("scheduled_interval_days") or 0)
    else:  # ON_REQUEST
        task_created = parse_iso(task["created_at"])
        for m in DB["linen_movements"].values():
            if (m.get("room_id") == room["id"]
                and m.get("linen_type_id") == linen_type["id"]
                and m.get("status") == "COLLECTED"):
                m_created = parse_iso(m["created_at"])
                if m_created is not None and task_created is not None and m_created >= task_created:
                    return True
        return False
