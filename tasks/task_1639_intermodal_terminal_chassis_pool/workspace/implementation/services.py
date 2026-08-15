"""Business logic: posture recompute, yard-slot selector, billing, cascades.

All functions mutate the in-memory stores in db.py and call db.touch() on every
mutated resource so updated_at / version advance per PRD §2.5.
"""
import math
from datetime import timedelta

import db
from db import now, now_clock_iso, touch
from errors import ApiError, ERR_NO_YARD_SLOT_AVAILABLE

CONGESTED_RATIO_NUM = 15  # floor(yard_slot_count * 0.15)
CONGESTED_RATIO_DEN = 100
CONGESTED_MAX_WINDOW_SECONDS = 3600
DEPARTED_AFTER_MINUTES = 60


# ---------------------------------------------------------------------------
# Terminal posture (scaffold calculation: terminal_posture, PRD §2.7)
# ---------------------------------------------------------------------------

def recompute_posture(terminal):
    """Recompute yard_slots_in_use / yard_slots_free / posture from live slots.

    Counts YardSlot rows in OCCUPIED, BLOCKED, or RESERVED status.
    """
    in_use = sum(
        1
        for s in db.slots.values()
        if s["terminal_id"] == terminal["id"] and s["status"] in ("OCCUPIED", "BLOCKED", "RESERVED")
    )
    terminal["yard_slots_in_use"] = in_use
    terminal["yard_slots_free"] = terminal["yard_slot_count"] - in_use
    threshold = (terminal["yard_slot_count"] * CONGESTED_RATIO_NUM) // CONGESTED_RATIO_DEN
    free = terminal["yard_slots_free"]
    if free == 0:
        posture = "CLOSED"
    elif free <= threshold:
        posture = "CONGESTED"
    else:
        posture = "OPEN"
    terminal["posture"] = posture
    return terminal


# ---------------------------------------------------------------------------
# Yard slot selector (scaffold calculation: yard_slot_selector, PRD §3.3)
# ---------------------------------------------------------------------------

def select_yard_slot(terminal_id):
    """Pick the grounding slot: EMPTY or RESERVED, tier_max >= 1,
    ordered by row ASC, slot_code ASC, created_at ASC."""
    candidates = [
        s
        for s in db.slots.values()
        if s["terminal_id"] == terminal_id
        and s["status"] in ("EMPTY", "RESERVED")
        and s["tier_max"] >= 1
    ]
    if not candidates:
        raise ApiError(
            ERR_NO_YARD_SLOT_AVAILABLE, 409, "No eligible yard slot available"
        )
    candidates.sort(key=lambda s: (s["row"], s["slot_code"], s["created_at"]))
    return candidates[0]


def occupy_slot(slot, container, terminal):
    """Ground a container into the chosen slot (EMPTY or RESERVED -> OCCUPIED)."""
    slot["status"] = "OCCUPIED"
    slot["occupied_container_id"] = container["id"]
    slot["current_height"] = 1
    touch(slot)
    container["yard_slot_id"] = slot["id"]
    container["stack_height"] = 1
    recompute_posture(terminal)
    touch(terminal)


def release_slot(container, terminal):
    """Release the container's yard slot (mount / void cascade, PRD §3.3)."""
    slot_id = container.get("yard_slot_id")
    if slot_id:
        slot = db.slots.get(slot_id)
        if slot is not None:
            slot["status"] = "EMPTY"
            slot["occupied_container_id"] = None
            slot["current_height"] = 0
            touch(slot)
    container["yard_slot_id"] = None
    container["stack_height"] = None
    recompute_posture(terminal)
    touch(terminal)


# ---------------------------------------------------------------------------
# Billing helpers (PRD §3.8, calculations per_diem_charge / storage_charge)
# ---------------------------------------------------------------------------

def _days_overdue(evaluation_time, free_time_expires_at):
    """ceil((evaluation - expiry)/86400); 0 when evaluation <= expiry."""
    if free_time_expires_at is None:
        return 0
    delta = (evaluation_time - free_time_expires_at).total_seconds()
    if delta <= 0:
        return 0
    return math.ceil(delta / 86400)


def create_ledger_entry(terminal_id, carrier_id, entry_kind, amount_cents,
                        container_id=None, chassis_id=None,
                        period_start=None, period_end=None):
    entry = db.stamp_new({
        "terminal_id": terminal_id,
        "container_id": container_id,
        "chassis_id": chassis_id,
        "carrier_id": carrier_id,
        "entry_kind": entry_kind,
        "amount_cents": amount_cents,
        "applied_cents": 0,
        "status": "OPEN",
        "period_start_utc": _iso(period_start),
        "period_end_utc": _iso(period_end),
    })
    db.ledger[entry["id"]] = entry
    if carrier_id is not None:
        carrier = db.carriers.get(carrier_id)
        if carrier is not None:
            carrier["outstanding_billing_cents"] = carrier.get("outstanding_billing_cents", 0) + amount_cents
            touch(carrier)
    return entry


def _iso(dt):
    """Ledger period bounds are logical-clock instants — render in clock format."""
    return db._fmt_clock(dt) if dt is not None else None


def waive_entry(entry):
    """Transition an OPEN / PARTIALLY_APPLIED entry to WAIVED, refunding the
    carrier's outstanding balance by the unapplied remainder."""
    remainder = entry["amount_cents"] - entry["applied_cents"]
    entry["status"] = "WAIVED"
    touch(entry)
    carrier = db.carriers.get(entry["carrier_id"]) if entry.get("carrier_id") else None
    if carrier is not None and remainder:
        carrier["outstanding_billing_cents"] = carrier.get("outstanding_billing_cents", 0) - remainder
        touch(carrier)


def waive_open_entries_for_container(container_id, kinds=None):
    """Waive every OPEN ledger entry for a container (void / train-depart cascades)."""
    for e in db.ledger.values():
        if e.get("container_id") == container_id and e["status"] == "OPEN":
            if kinds is None or e["entry_kind"] in kinds:
                waive_entry(e)


def container_billing_carrier(container):
    """Resolve the carrier billed for a container's per-diem/storage.

    The scaffold gives Container no carrier field; the only carrier-container
    linkage in the API surface is GateAppointment. Bill the carrier of the most
    recently created appointment for the container; None when none exists.
    """
    appts = [a for a in db.appointments.values() if a["container_id"] == container["id"]]
    if not appts:
        return None
    appts.sort(key=lambda a: a["created_at"])
    return appts[-1]["carrier_id"]


def compute_per_diem(terminal, container, evaluation_time):
    days = _days_overdue(evaluation_time, db._parse_iso(container["free_time_expires_at"]))
    return days * terminal["per_diem_rate_cents"] if days > 0 else 0


def compute_storage(terminal, container, evaluation_time):
    if container["status"] != "ON_GROUND":
        return 0
    days = _days_overdue(evaluation_time, db._parse_iso(container["free_time_expires_at"]))
    return days * terminal["storage_rate_cents"] if days > 0 else 0


# ---------------------------------------------------------------------------
# Chassis helpers
# ---------------------------------------------------------------------------

def pool_of(chassis_rec):
    return db.pools.get(chassis_rec["pool_id"])


def release_reserved_chassis(chassis_rec):
    """RESERVED -> AVAILABLE with pool counter adjustment (reservation voided)."""
    pool = pool_of(chassis_rec)
    chassis_rec["status"] = "AVAILABLE"
    touch(chassis_rec)
    if pool is not None:
        pool["reserved_chassis_count"] = max(0, pool["reserved_chassis_count"] - 1)
        pool["available_chassis_count"] += 1
        touch(pool)


def recompute_roadability(chassis_rec):
    """After repair/waive: restore ROADABLE when no OPEN MAJOR/SAFETY_CRITICAL
    damage remains on the chassis. Stamps last_inspection_at on transition."""
    if chassis_rec["roadability_status"] != "UNROADABLE":
        return
    blocking = any(
        d for d in db.damage.values()
        if d.get("chassis_id") == chassis_rec["id"]
        and d["status"] == "OPEN"
        and d["severity"] in ("MAJOR", "SAFETY_CRITICAL")
    )
    if not blocking:
        chassis_rec["roadability_status"] = "ROADABLE"
        chassis_rec["last_inspection_at"] = now_clock_iso()
        touch(chassis_rec)


def carrier_membership_on_pool(carrier_id, pool_id):
    for m in db.memberships.values():
        if m["carrier_id"] == carrier_id and m["pool_id"] == pool_id:
            return m
    return None


def terminal_pool(terminal_id):
    """The chassis pool serving a terminal (membership checks are 'on the
    terminal's chassis pool' per PRD §3.5). Returns the first pool, or None."""
    for p in db.pools.values():
        if p["terminal_id"] == terminal_id:
            return p
    return None


def release_carrier_reserved_chassis(carrier_id, pool_id):
    """Membership suspend/terminate cascade: release every RESERVED chassis this
    carrier holds in the pool back to AVAILABLE (PRD §3.4).

    A chassis is 'held by' a carrier when it is RESERVED against a CHECKED_IN
    appointment booked by that carrier (the reservation linkage). We find such
    chassis via appointments: RESERVED chassis whose reserving appointment belongs
    to the carrier. The appointment id stored on a reserved chassis is tracked in
    the chassis record's `reserved_appointment_id` (implementation-internal).
    """
    for ch in db.chassis.values():
        if ch["pool_id"] != pool_id or ch["status"] != "RESERVED":
            continue
        aid = ch.get("reserved_appointment_id")
        appt = db.appointments.get(aid) if aid else None
        if appt is not None and appt["carrier_id"] == carrier_id:
            ch["reserved_appointment_id"] = None
            release_reserved_chassis(ch)


# ---------------------------------------------------------------------------
# Flip-fee settlement (scaffold calculation: flip_fee_charge, PRD §3.6)
# ---------------------------------------------------------------------------

def settle_flip_fee(terminal, carrier_id, pool_id, chassis_id, evaluation_time):
    """Debit membership credit when it covers the fee; otherwise bill the carrier."""
    fee = terminal["flip_fee_cents"]
    membership = carrier_membership_on_pool(carrier_id, pool_id) if pool_id else None
    if membership is not None and membership.get("flip_fee_credit_cents", 0) >= fee:
        membership["flip_fee_credit_cents"] -= fee
        touch(membership)
        return None
    entry = create_ledger_entry(
        terminal_id=terminal["id"],
        carrier_id=carrier_id,
        entry_kind="FLIP_FEE",
        amount_cents=fee,
        container_id=None,
        chassis_id=chassis_id,
        period_start=evaluation_time,
        period_end=evaluation_time,
    )
    pool = db.pools.get(pool_id) if pool_id else None
    if pool is not None:
        pool["flip_fee_balance_cents"] = pool.get("flip_fee_balance_cents", 0) + fee
        touch(pool)
    return entry


# ---------------------------------------------------------------------------
# run_ops checkpoint (PRD §3.8)
# ---------------------------------------------------------------------------

def run_ops(terminal):
    clock = now()
    terminal["ops_run_index"] = terminal.get("ops_run_index", 0) + 1

    # 1. BOOKED appointments past their window -> NO_SHOW
    for a in db.appointments.values():
        if a["terminal_id"] != terminal["id"] or a["status"] != "BOOKED":
            continue
        if db._parse_iso(a["window_end_utc"]) < clock:
            a["status"] = "NO_SHOW"
            touch(a)

    # 2. Provisional billing snapshot
    for c in db.containers.values():
        if c["terminal_id"] != terminal["id"]:
            continue
        if c["status"] not in ("ON_GROUND", "MOUNTED"):
            continue
        expiry = db._parse_iso(c["free_time_expires_at"]) if c.get("free_time_expires_at") else None
        if expiry is None or expiry >= clock:
            continue
        # Per-diem accrues for ON_GROUND and MOUNTED
        pd_amount = compute_per_diem(terminal, c, clock)
        if pd_amount > 0:
            create_ledger_entry(
                terminal_id=terminal["id"],
                carrier_id=container_billing_carrier(c),
                entry_kind="PER_DIEM",
                amount_cents=pd_amount,
                container_id=c["id"],
                chassis_id=None,
                period_start=expiry,
                period_end=clock,
            )
        # Storage accrues only while ON_GROUND
        if c["status"] == "ON_GROUND":
            st_amount = compute_storage(terminal, c, clock)
            if st_amount > 0:
                create_ledger_entry(
                    terminal_id=terminal["id"],
                    carrier_id=container_billing_carrier(c),
                    entry_kind="STORAGE",
                    amount_cents=st_amount,
                    container_id=c["id"],
                    chassis_id=None,
                    period_start=expiry,
                    period_end=clock,
                )

    # 3. Retire stale out-gates: OUTBOUND_TRUCK whose transaction processed_at
    #    is at least 60 minutes in the past -> DEPARTED
    cutoff = clock - timedelta(minutes=DEPARTED_AFTER_MINUTES)
    for c in db.containers.values():
        if c["terminal_id"] != terminal["id"] or c["status"] != "OUTBOUND_TRUCK":
            continue
        txid = c.get("out_gate_transaction_id")
        tx = db.transactions.get(txid) if txid else None
        if tx is None or not tx.get("processed_at"):
            continue
        if db._parse_iso(tx["processed_at"]) <= cutoff:
            c["status"] = "DEPARTED"
            touch(c)

    touch(terminal)
    return terminal
