"""Core shared services: posture derivation, hold/release accounting,
void cascade, epoch sweeps, common mutation helpers, and numeric utilities.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import STORE, now_utc, month_of, date_str

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GGE_KG = Decimal("2.567")
CNG_CREDIT_CENTS_PER_GGE = 50
RNG_CREDIT_CENTS_PER_GGE = 100
TOLERANCE_PCT = Decimal("0.50")
CALIBRATION_INTERVAL_DAYS = 90
TIER1_CAP_PCT = Decimal("0.10")
TURNAROUND_HOURS = 2
HOLD_TIMEOUT_MINUTES = 30

INSPECTION_INTERVALS_DAYS = {
    "ANNUAL_COMPREHENSIVE": 365,
    "ODORIZATION_CHECK": 90,
    "PRESSURE_VESSEL": 730,
}


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def to_decimal(value) -> Decimal:
    """Convert int/float/str input to Decimal, via str to avoid float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        return Decimal(value)
    raise ValueError(f"not numeric: {type(value)}")


def round_half_up_3(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round_half_up_4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round_half_up_cents(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def touch(entity: dict) -> None:
    """Increment version and refresh updated_at (system/common fields)."""
    entity["version"] += 1
    entity["updated_at"] = now_utc()


# ---------------------------------------------------------------------------
# Station uptime posture (PRD §2.7) and OUTAGE void cascade
# ---------------------------------------------------------------------------

def derive_uptime_posture(station_id: str) -> str:
    online_compressors = sum(
        1 for c in STORE.compressors.values()
        if c["station_id"] == station_id and c["condition"] in ("ONLINE", "DEGRADED")
    )
    inservice_dispensers = sum(
        1 for d in STORE.dispensers.values()
        if d["station_id"] == station_id and d["status"] == "IN_SERVICE"
    )
    if online_compressors == 0 or inservice_dispensers == 0:
        return "OUTAGE"
    any_degraded = any(
        c["condition"] == "DEGRADED"
        for c in STORE.compressors.values()
        if c["station_id"] == station_id
    )
    any_hold = any(
        d["status"] == "CALIBRATION_HOLD"
        for d in STORE.dispensers.values()
        if d["station_id"] == station_id
    )
    if any_degraded or any_hold:
        return "DEGRADED"
    return "OPERATIONAL"


def recompute_station_posture(station_id: str) -> None:
    """Recompute posture; fire void cascade when posture CHANGES to OUTAGE.

    Note: uptime_posture is a computed field — changing it does NOT bump
    Station.version (version only moves on explicit station mutations per
    state machine side effects).
    """
    station = STORE.stations.get(station_id)
    if station is None:
        return
    old = station["uptime_posture"]
    new = derive_uptime_posture(station_id)
    if new != old:
        station["uptime_posture"] = new
        if new == "OUTAGE":
            void_sessions_for_station_outage(station_id)


def void_session(session: dict, void_reason: str) -> None:
    """Void an AUTHORIZED or COMPLETED session with its accounting effects."""
    status = session["status"]
    if status not in ("AUTHORIZED", "COMPLETED"):
        return
    account_id = session["fleet_account_id"]
    if session["access_type"] == "PRIVATE" and account_id is not None:
        account = STORE.fleet_accounts.get(account_id)
        if account is not None:
            if status == "AUTHORIZED":
                account["outstanding_balance_cents"] -= session["hold_amount_cents"]
            else:  # COMPLETED
                account["outstanding_balance_cents"] -= session["total_amount_cents"]
            touch(account)
    if status == "COMPLETED" and session["fleet_card_id"] is not None:
        card = STORE.fleet_cards.get(session["fleet_card_id"])
        if card is not None:
            new_val = card["current_day_gge"] - session["settled_gge"]
            card["current_day_gge"] = new_val if new_val > 0 else Decimal("0")
            touch(card)
    session["status"] = "VOIDED"
    session["void_reason"] = void_reason
    session["voided_at"] = now_utc()
    touch(session)


def _authorized_sessions_at_station_sorted(station_id: str) -> list[dict]:
    sessions = [
        s for s in STORE.fueling_sessions.values()
        if s["station_id"] == station_id and s["status"] == "AUTHORIZED"
    ]
    sessions.sort(key=lambda s: (s["created_at"], s["id"]))
    return sessions


def void_sessions_for_station_outage(station_id: str) -> None:
    for s in _authorized_sessions_at_station_sorted(station_id):
        void_session(s, "STATION_OUTAGE")


def void_sessions_for_station_suspend(station_id: str) -> None:
    for s in _authorized_sessions_at_station_sorted(station_id):
        void_session(s, "MANAGER_VOID")


def void_sessions_for_inspection_fail(station_id: str) -> None:
    for s in _authorized_sessions_at_station_sorted(station_id):
        void_session(s, "INSPECTION_FAIL")


def station_has_overdue_inspection(station_id: str) -> bool:
    return any(
        i["station_id"] == station_id and i["status"] == "OVERDUE"
        for i in STORE.safety_inspections.values()
    )


# ---------------------------------------------------------------------------
# Epoch sweeps (PRD §2.5)
# ---------------------------------------------------------------------------

def run_epoch_sweeps() -> int:
    """Run all nine sweeps in the pinned PRD order. Returns count of sweeps applied."""
    now = now_utc()
    applied = 0

    # 1. Hold timeouts: AUTHORIZED sessions older than 30 minutes -> VOIDED(TIMEOUT)
    timeout_cutoff = now - timedelta(minutes=HOLD_TIMEOUT_MINUTES)
    timed_out = [
        s for s in STORE.fueling_sessions.values()
        if s["status"] == "AUTHORIZED" and s["authorized_at"] <= timeout_cutoff
    ]
    timed_out.sort(key=lambda s: (s["created_at"], s["id"]))
    affected_station_ids = set()
    for s in timed_out:
        void_session(s, "TIMEOUT")
        applied += 1

    # 2. Calibration due: IN_SERVICE dispenser past calibration_due_at -> CALIBRATION_HOLD
    for d in STORE.dispensers.values():
        if d["status"] == "IN_SERVICE" and now > d["calibration_due_at"]:
            d["status"] = "CALIBRATION_HOLD"
            touch(d)
            affected_station_ids.add(d["station_id"])
            applied += 1

    # 3. Pricing policy expiry: ACTIVE policy past effective_to -> EXPIRED
    for p in STORE.pricing_policies.values():
        if p["status"] == "ACTIVE" and now > p["effective_to"]:
            p["status"] = "EXPIRED"
            touch(p)
            applied += 1

    # 4. Window lapse: SCHEDULED window past ends_at -> LAPSED
    for w in STORE.maintenance_windows.values():
        if w["status"] == "SCHEDULED" and now > w["ends_at"]:
            w["status"] = "LAPSED"
            touch(w)
            applied += 1

    # 5. Backup expiry: RESERVED/ACTIVATED past available_until -> EXPIRED
    for b in STORE.backup_arrangements.values():
        if b["status"] in ("RESERVED", "ACTIVATED") and now > b["available_until"]:
            b["status"] = "EXPIRED"
            touch(b)
            applied += 1

    # 6. Inspection overdue: SCHEDULED inspection past scheduled_for -> OVERDUE
    for i in STORE.safety_inspections.values():
        if i["status"] == "SCHEDULED" and now > i["scheduled_for"]:
            i["status"] = "OVERDUE"
            touch(i)
            applied += 1

    # 7. Contract expiry: ACTIVE contract with end_month < current month -> EXPIRED
    current_month = month_of(now)
    for c in STORE.supply_contracts.values():
        if c["status"] == "ACTIVE" and c["end_month"] < current_month:
            c["status"] = "EXPIRED"
            touch(c)
            applied += 1

    # 8. Daily usage rollover
    today = date_str(now)
    for card in STORE.fleet_cards.values():
        if card["current_day_date"] < today:
            card["current_day_gge"] = Decimal("0")
            card["current_day_date"] = today
            touch(card)
            applied += 1

    # 9. Month-close settlement: COMPLETED sessions from prior months -> SETTLED
    for s in STORE.fueling_sessions.values():
        if s["status"] == "COMPLETED" and s["completed_at"] is not None:
            if month_of(s["completed_at"]) < current_month:
                s["status"] = "SETTLED"
                s["settled_at"] = now
                touch(s)
                applied += 1

    # Posture recompute for stations whose dispensers moved to CALIBRATION_HOLD
    for sid in affected_station_ids:
        recompute_station_posture(sid)

    return applied
