"""Domain services: entity stamping, connection recompute, calculations,
state-transition cascades."""

from decimal import Decimal
from datetime import timedelta

import store
from util import (
    add_months, whole_days_between, round_half_up_cents, round_half_up_2,
    fmt_dt,
)

RANK = {"LOW": 0, "MODERATE": 1, "HIGH": 2}
RANK_INV = {0: "LOW", 1: "MODERATE", 2: "HIGH"}
GRACE_DAYS = {"LOW": 30, "MODERATE": 14, "HIGH": 7}
PENALTY_MULT = {"LOW": Decimal("1.0"), "MODERATE": Decimal("1.5"), "HIGH": Decimal("2.0")}
BASE_DAILY_RATE_CENTS = 333
REMINDER_LEAD_DAYS = 30
MIN_RELIEF_DIFFERENTIAL_PSID = 2.0
MIN_CHECK_PSID = 1.0
PREMISES_BUFFER_MINUTES = 60


# ---------------------------------------------------------------------------
# Entity stamping / mutation bookkeeping
# ---------------------------------------------------------------------------
def stamp_new(d):
    now = store.wall_now()
    d["id"] = store.new_id()
    d["created_at"] = now
    d["updated_at"] = now
    d["version"] = 1
    d["_seq"] = store.next_seq()
    return d


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = store.wall_now()


# ---------------------------------------------------------------------------
# Connection recompute (derived counts, penalty, posture)
# ---------------------------------------------------------------------------
def _conn_devices(conn):
    return [d for d in store.devices.values()
            if d["service_connection_id"] == conn["id"]]


def _snapshot(conn):
    return (
        conn["risk_tier"], conn["water_service_active"], conn["compliance_posture"],
        conn["protected_device_count"], conn["overdue_device_count"],
        conn["open_notice_count"], conn["total_penalty_cents"],
    )


def recompute_conn(conn):
    now = store.current_utc()
    devs = _conn_devices(conn)
    active_set = [d for d in devs if d["status"] in ("ACTIVE", "NEEDS_REPAIR")]

    protected = len(active_set)
    overdue_devs = [d for d in active_set
                    if d["next_test_due_date"] is not None
                    and d["next_test_due_date"] < now]
    overdue = len(overdue_devs)
    open_notices = [n for n in store.notices.values()
                    if n["service_connection_id"] == conn["id"]
                    and n["status"] == "ISSUED"]
    open_count = len(open_notices)

    mult = PENALTY_MULT[conn["risk_tier"]]
    total_penalty = 0
    for d in overdue_devs:
        days = whole_days_between(now, d["next_test_due_date"])
        days = max(1, days)
        raw = Decimal(BASE_DAILY_RATE_CENTS) * mult * Decimal(days)
        total_penalty += round_half_up_cents(raw)

    has_needs_repair = any(d["status"] == "NEEDS_REPAIR" for d in devs)
    if not conn["water_service_active"]:
        posture = "SHUTOFF"
    elif overdue > 0 or has_needs_repair or open_count > 0:
        posture = "NON_COMPLIANT"
    elif any(0 <= whole_days_between(d["next_test_due_date"], now) <= REMINDER_LEAD_DAYS
             for d in active_set if d["next_test_due_date"] is not None):
        posture = "AT_RISK"
    else:
        posture = "COMPLIANT"

    conn["protected_device_count"] = protected
    conn["overdue_device_count"] = overdue
    conn["open_notice_count"] = open_count
    conn["total_penalty_cents"] = total_penalty
    conn["compliance_posture"] = posture


def begin(conn):
    return _snapshot(conn)


def finish(conn, before, extra_increments=0):
    recompute_conn(conn)
    if _snapshot(conn) != before:
        touch(conn)
    for _ in range(extra_increments):
        touch(conn)


def read_recompute(conn):
    """Read-time recompute that bumps version/updated_at only on change."""
    before = begin(conn)
    finish(conn, before)


# ---------------------------------------------------------------------------
# Helpers for cascade conditions
# ---------------------------------------------------------------------------
def has_needs_repair_device(conn):
    return any(d["service_connection_id"] == conn["id"] and d["status"] == "NEEDS_REPAIR"
               for d in store.devices.values())


def overdue_count(conn):
    now = store.current_utc()
    return sum(1 for d in _conn_devices(conn)
               if d["status"] in ("ACTIVE", "NEEDS_REPAIR")
               and d["next_test_due_date"] is not None
               and d["next_test_due_date"] < now)


def device_is_overdue(device):
    now = store.current_utc()
    return (device["next_test_due_date"] is not None
            and device["next_test_due_date"] < now)


# ---------------------------------------------------------------------------
# Notice creation (manual issue + cascade auto-issue)
# ---------------------------------------------------------------------------
def create_notice(conn, reason):
    now = store.current_utc()
    grace = GRACE_DAYS[conn["risk_tier"]]
    n = {
        "service_connection_id": conn["id"],
        "reason": reason,
        "issued_date": now,
        "grace_days": grace,
        "enforcement_due_date": now + timedelta(days=grace),
        "status": "ISSUED",
    }
    stamp_new(n)
    store.notices[n["id"]] = n
    return n


def auto_rescind_repair_notices(conn):
    """Rescind ISSUED FAILED_TEST/UNREPAIRED_DEVICE notices once the connection
    has no NEEDS_REPAIR device and no overdue device."""
    if has_needs_repair_device(conn) or overdue_count(conn) > 0:
        return
    for n in store.notices.values():
        if (n["service_connection_id"] == conn["id"] and n["status"] == "ISSUED"
                and n["reason"] in ("FAILED_TEST", "UNREPAIRED_DEVICE")):
            n["status"] = "RESCINDED"
            touch(n)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def compute_test_result(device_type, relief, cv1, cv2):
    if device_type == "RP":
        ok = (relief is not None and relief >= MIN_RELIEF_DIFFERENTIAL_PSID
              and cv1 >= MIN_CHECK_PSID)
    elif device_type in ("DC", "DCDA"):
        ok = (cv1 >= MIN_CHECK_PSID and cv2 is not None and cv2 >= MIN_CHECK_PSID)
    else:  # PVB
        ok = cv1 >= MIN_CHECK_PSID
    return "PASS" if ok else "FAIL"


def compute_risk_tiers(conn, survey):
    p = survey["premise_use_score"]
    c = survey["chemical_exposure_score"]
    a = survey["auxiliary_supply_score"]
    weighted = round_half_up_2(
        Decimal(p) * Decimal("0.3") + Decimal(c) * Decimal("0.4") + Decimal(a) * Decimal("0.3"))
    if weighted >= Decimal(70):
        base = "HIGH"
    elif weighted >= Decimal(40):
        base = "MODERATE"
    else:
        base = "LOW"
    if c >= 35:
        floor = "HIGH"
    elif a >= 30:
        floor = "MODERATE"
    else:
        floor = "LOW"
    assessed = RANK_INV[max(RANK[base], RANK[floor])]
    device_floor = "HIGH" if any(
        d["status"] in ("ACTIVE", "NEEDS_REPAIR") and d["hazard_rating"] == "HIGH"
        for d in _conn_devices(conn)) else "LOW"
    effective = RANK_INV[max(RANK[assessed], RANK[device_floor])]
    return assessed, effective


def next_due_from(baseline, interval_months):
    return add_months(baseline, interval_months)
