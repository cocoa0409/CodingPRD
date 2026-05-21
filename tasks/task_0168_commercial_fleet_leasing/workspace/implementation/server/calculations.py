"""Core domain calculations — §1.3 overage settlement, IFTA tax, collision deductible,
odometer reconciliation, monthly card spend. All money is integer cents; rounding is
half-up per-line-item then sum (§2.7)."""
from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .clock import parse_iso
from .constants import (
    GOOD_TELEMATICS_DISCOUNT_BPS,
    IFTA_ELIGIBLE_CLASSES,
    IFTA_RATES,
    TIER1_BREAK,
    TIER2_BREAK,
    TIER2_MULT_BPS,
    TIER3_MULT_BPS,
)
from .store import store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def round_half_up(value: Decimal | int | float) -> int:
    """Half-up rounding to a whole cent (§2.7)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_window(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59, 999_000, tzinfo=timezone.utc)
    return start, end


def quarter_window(year: int, quarter: int) -> tuple[datetime, datetime]:
    first_month = (quarter - 1) * 3 + 1
    last_month = first_month + 2
    start = datetime(year, first_month, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, last_month)[1]
    end = datetime(year, last_month, last_day, 23, 59, 59, 999_000, tzinfo=timezone.utc)
    return start, end


def quarter_end_date(year: int, quarter: int) -> datetime:
    return quarter_window(year, quarter)[1]


# ---------------------------------------------------------------------------
# Odometer reconciliation (§1.3 odometer_reconciliation, §2.10)
# ---------------------------------------------------------------------------

def reconcile_telematics(vehicle: dict[str, Any], reading: int) -> str:
    """Returns ACCEPTED or REJECTED_STALE; advances the vehicle's odometer on accept."""
    current = int(vehicle.get("odometer_current_miles", 0))
    if reading < current:
        return "REJECTED_STALE"
    vehicle["odometer_current_miles"] = reading
    return "ACCEPTED"


# ---------------------------------------------------------------------------
# Overage settlement (§1.3 overage_settlement, §3.6)
# ---------------------------------------------------------------------------

def _accepted_events_for(vehicle_id: str) -> list[dict[str, Any]]:
    return [
        e
        for e in store.telematics_events.values()
        if e.get("vehicle_id") == vehicle_id and e.get("ingest_status") == "ACCEPTED"
    ]


def _start_odometer(vehicle: dict[str, Any], period_start: datetime) -> int:
    """Latest ACCEPTED reading with event_ts <= period_start, else baseline."""
    candidates = [
        e for e in _accepted_events_for(vehicle["id"])
        if parse_iso(e["event_ts"]) <= period_start
    ]
    if not candidates:
        return int(vehicle.get("odometer_baseline_miles", 0))
    # PRD says "latest" — by event_ts, then id for determinism
    candidates.sort(key=lambda e: (parse_iso(e["event_ts"]), e["id"]))
    return int(candidates[-1]["odometer_reading"])


def _end_odometer_final(vehicle: dict[str, Any], period_end: datetime) -> int:
    """Largest ACCEPTED odometer_reading whose event_ts <= period_end."""
    candidates = [
        e for e in _accepted_events_for(vehicle["id"])
        if parse_iso(e["event_ts"]) <= period_end
    ]
    if not candidates:
        return int(vehicle.get("odometer_baseline_miles", 0))
    return max(int(e["odometer_reading"]) for e in candidates)


def _end_odometer_provisional(vehicle: dict[str, Any], now_dt: datetime) -> int:
    """Latest ACCEPTED reading as of now_dt — forward-looking (§3.6)."""
    candidates = [
        e for e in _accepted_events_for(vehicle["id"])
        if parse_iso(e["event_ts"]) <= now_dt
    ]
    if not candidates:
        return int(vehicle.get("odometer_current_miles") or vehicle.get("odometer_baseline_miles", 0))
    candidates.sort(key=lambda e: (parse_iso(e["event_ts"]), e["id"]))
    return int(candidates[-1]["odometer_reading"])


def _price_overage(overage_miles: int, lease: dict[str, Any]) -> int:
    """Apply the flat or tiered pricing (§3.6)."""
    rate = int(lease["overage_rate_cents_per_mile"])
    if not lease.get("tiered_overage_enabled"):
        return overage_miles * rate

    tier1_miles = min(overage_miles, TIER1_BREAK)
    tier2_miles = max(0, min(overage_miles, TIER2_BREAK) - TIER1_BREAK)
    tier3_miles = max(0, overage_miles - TIER2_BREAK)

    tier1 = tier1_miles * rate  # integer, no rounding
    tier2 = round_half_up(Decimal(tier2_miles) * Decimal(rate) * Decimal(TIER2_MULT_BPS) / Decimal(10_000))
    tier3 = round_half_up(Decimal(tier3_miles) * Decimal(rate) * Decimal(TIER3_MULT_BPS) / Decimal(10_000))
    return tier1 + tier2 + tier3


def compute_overage(
    lease: dict[str, Any],
    vehicle: dict[str, Any],
    period_year: int,
    period_month: int,
    variant: str,
    now_dt: datetime,
) -> tuple[int, int]:
    """Returns (overage_miles, balance_cents) for the given variant."""
    period_start, period_end = month_window(period_year, period_month)
    start_odo = _start_odometer(vehicle, period_start)
    if variant == "provisional":
        end_odo = _end_odometer_provisional(vehicle, now_dt)
    else:
        end_odo = _end_odometer_final(vehicle, period_end)
    period_miles = max(0, end_odo - start_odo)
    allowance = int(lease["monthly_mileage_allowance"])
    overage_miles = max(0, period_miles - allowance)
    balance_cents = _price_overage(overage_miles, lease)
    return overage_miles, balance_cents


# ---------------------------------------------------------------------------
# IFTA tax (§1.3 ifta_tax, §3.9)
# ---------------------------------------------------------------------------

def collect_quarter_txns(lessee_id: str, year: int, quarter: int) -> list[dict[str, Any]]:
    """Eligible POSTED + ifta_eligible txns in the quarter window, ordered (posted_at, id)."""
    w_start, w_end = quarter_window(year, quarter)
    # Cards owned by this lessee
    lease_ids_for_lessee = {
        la["id"] for la in store.lease_agreements.values() if la.get("lessee_id") == lessee_id
    }
    card_ids_for_lessee = {
        c["id"] for c in store.fuel_cards.values()
        if c.get("lease_agreement_id") in lease_ids_for_lessee
    }
    txns: list[dict[str, Any]] = []
    for t in store.fuel_card_transactions.values():
        if t.get("fuel_card_id") not in card_ids_for_lessee:
            continue
        if t.get("txn_status") != "POSTED":
            continue
        if not t.get("ifta_eligible"):
            continue
        posted_at = parse_iso(t["posted_at"])
        if not (w_start <= posted_at <= w_end):
            continue
        txns.append(t)
    txns.sort(key=lambda t: (parse_iso(t["posted_at"]), t["id"]))
    return txns


def compute_ifta(lessee: dict[str, Any], year: int, quarter: int) -> tuple[float, int]:
    """Returns (total_taxable_gallons, total_tax_cents); per_jurisdiction_then_sum (§2.7)."""
    txns = collect_quarter_txns(lessee["id"], year, quarter)
    per_j: dict[str, Decimal] = {}
    for t in txns:
        j = t["jurisdiction"]
        per_j[j] = per_j.get(j, Decimal("0")) + Decimal(str(t["gallons"]))

    total_gallons = sum(per_j.values(), Decimal("0"))

    tax_owed_cents = 0
    for j, gallons in per_j.items():
        rate = Decimal(IFTA_RATES[j])
        tax_owed_cents += round_half_up(gallons * rate)

    base_rate = Decimal(IFTA_RATES[lessee["base_jurisdiction"]])
    tax_credit_cents = round_half_up(total_gallons * base_rate)

    total_tax_cents = tax_owed_cents - tax_credit_cents

    # gallons stored as float; gallons input has up to 3 decimal places
    return float(total_gallons), total_tax_cents


# ---------------------------------------------------------------------------
# Collision settlement (§1.3 collision_settlement, §3.7)
# ---------------------------------------------------------------------------

def _has_fault_code_in_window(vehicle_id: str, incident_ts: datetime) -> bool:
    """ACCEPTED telematics on same vehicle, event_ts in (incident_ts - 24h, incident_ts]."""
    lower = incident_ts - timedelta(hours=24)
    for e in _accepted_events_for(vehicle_id):
        ts = parse_iso(e["event_ts"])
        if ts <= lower:
            continue
        if ts > incident_ts:
            continue
        fc = e.get("fault_code", "")
        if isinstance(fc, str) and fc != "":
            return True
    return False


def compute_collision_deductible(claim: dict[str, Any]) -> int:
    """Compute lessee_deductible_cents per §1.3 collision_settlement."""
    from .constants import DEDUCTIBLE_CAP_CENTS

    revised = int(claim.get("revised_estimate_cents") or 0)
    original = int(claim["estimate_cents"])
    base = revised if revised > 0 else original
    raw = min(base, DEDUCTIBLE_CAP_CENTS)

    incident_ts = parse_iso(claim["incident_ts"])
    has_fault = _has_fault_code_in_window(claim["vehicle_id"], incident_ts)

    if has_fault:
        return raw

    if revised > 0 and int(claim.get("revision_round") or 0) >= 1:
        discounted = (
            Decimal(raw) * Decimal(10_000 - GOOD_TELEMATICS_DISCOUNT_BPS) / Decimal(10_000)
        )
        return round_half_up(discounted)
    return raw


# ---------------------------------------------------------------------------
# Monthly fuel-card spend (§1.3 monthly_card_spend, §3.3)
# ---------------------------------------------------------------------------

def recompute_card_spend(card: dict[str, Any], now_dt: datetime) -> int:
    """Sum POSTED txn amounts for this card whose posted_at falls in the current calendar month."""
    m_start, m_end = month_window(now_dt.year, now_dt.month)
    total = 0
    for t in store.fuel_card_transactions.values():
        if t.get("fuel_card_id") != card["id"]:
            continue
        if t.get("txn_status") != "POSTED":
            continue
        posted_at = parse_iso(t["posted_at"])
        if m_start <= posted_at <= m_end:
            total += int(t["amount_cents"])
    card["current_period_spend_cents"] = total
    return total


def card_spend_in_window_of(card: dict[str, Any], posted_at: datetime) -> int:
    """Sum POSTED txn amounts for the card in the calendar month containing posted_at."""
    m_start, m_end = month_window(posted_at.year, posted_at.month)
    total = 0
    for t in store.fuel_card_transactions.values():
        if t.get("fuel_card_id") != card["id"]:
            continue
        if t.get("txn_status") != "POSTED":
            continue
        ts = parse_iso(t["posted_at"])
        if m_start <= ts <= m_end:
            total += int(t["amount_cents"])
    return total


def vehicle_for_card(card: dict[str, Any]) -> dict[str, Any] | None:
    lease = store.lease_agreements.get(card["lease_agreement_id"])
    if lease is None:
        return None
    return store.vehicles.get(lease["vehicle_id"])


def is_txn_ifta_eligible_for(card: dict[str, Any]) -> bool:
    v = vehicle_for_card(card)
    if v is None:
        return False
    return v.get("vehicle_class") in IFTA_ELIGIBLE_CLASSES
