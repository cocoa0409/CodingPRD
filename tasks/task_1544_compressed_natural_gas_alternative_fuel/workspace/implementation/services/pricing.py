"""Pricing resolution, claim computation, settlement penalty calculation."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from db import STORE, now_utc, month_of, month_start_dt, next_month
from errors import ApiError, ERR_NO_ACTIVE_PRICE
from services.core import (
    CNG_CREDIT_CENTS_PER_GGE,
    RNG_CREDIT_CENTS_PER_GGE,
    TIER1_CAP_PCT,
    round_half_up_cents,
)


def resolve_unit_price_private(account_id: str, station_id: str, dispenser: dict,
                               excluding_session_id: str | None = None) -> int:
    """Pinned order: contract override -> policy -> tier."""
    now = now_utc()
    current_month = month_of(now)

    # 1. Contract override
    for c in STORE.supply_contracts.values():
        if (c["status"] == "ACTIVE"
                and c["fleet_account_id"] == account_id
                and c["station_id"] == station_id
                and c["start_month"] <= current_month <= c["end_month"]):
            return c["contract_price_per_gge_cents"]

    # 2. Policy
    policy = _find_active_policy(station_id, "PRIVATE", dispenser["fuel_type"], now)
    if policy is None:
        raise ApiError(
            ERR_NO_ACTIVE_PRICE, 422,
            "No ACTIVE pricing policy (and no covering contract) resolves a unit price",
        )

    # 3. Tier (only when policy has tier fields)
    if policy["tier_threshold_gge"] is not None:
        mtd = account_station_mtd_gge(account_id, station_id, current_month,
                                      excluding_session_id=excluding_session_id)
        if mtd >= policy["tier_threshold_gge"]:
            return policy["tier_price_cents"]
    return policy["price_per_gge_cents"]


def resolve_unit_price_public(station_id: str, dispenser: dict) -> int:
    now = now_utc()
    policy = _find_active_policy(station_id, "PUBLIC", dispenser["fuel_type"], now)
    if policy is None:
        raise ApiError(
            ERR_NO_ACTIVE_PRICE, 422,
            "No ACTIVE pricing policy resolves a unit price",
        )
    return policy["price_per_gge_cents"]


def _find_active_policy(station_id: str, access_scope: str, fuel_type: str,
                        now: datetime) -> dict | None:
    for p in STORE.pricing_policies.values():
        if (p["station_id"] == station_id
                and p["access_scope"] == access_scope
                and p["fuel_type"] == fuel_type
                and p["status"] == "ACTIVE"
                and p["effective_from"] <= now < p["effective_to"]):
            return p
    return None


def account_station_mtd_gge(account_id: str, station_id: str, month: str,
                            excluding_session_id: str | None = None) -> Decimal:
    """Sum settled_gge over account's non-voided COMPLETED/SETTLED private
    sessions at this station with completed_at in the given calendar month."""
    total = Decimal("0")
    for s in STORE.fueling_sessions.values():
        if s["access_type"] != "PRIVATE":
            continue
        if s["fleet_account_id"] != account_id or s["station_id"] != station_id:
            continue
        if s["status"] not in ("COMPLETED", "SETTLED"):
            continue
        if s["id"] == excluding_session_id:
            continue
        if s["completed_at"] is None:
            continue
        if month_of(s["completed_at"]) != month:
            continue
        total += s["settled_gge"]
    return total


# ---------------------------------------------------------------------------
# Tax credit claim computation (pinned nested-rounding discipline)
# ---------------------------------------------------------------------------

def _claim_session_sets(station_id: str, period_start: datetime, period_end: datetime):
    """Return (provisional_sessions, final_sessions)."""
    provisional = []
    final = []
    # Other open claims at the station (for double-claim exclusion)
    other_open_claims = [
        c for c in STORE.tax_credit_claims.values()
        if c["station_id"] == station_id and c["status"] in ("FINALIZED", "SUBMITTED", "APPROVED")
    ]
    for s in STORE.fueling_sessions.values():
        if s["station_id"] != station_id:
            continue
        if s["status"] not in ("COMPLETED", "SETTLED"):
            continue
        if s["completed_at"] is None:
            continue
        if not (period_start <= s["completed_at"] < period_end):
            continue
        provisional.append(s)
        if s["status"] == "SETTLED":
            # Exclude sessions captured by another FINALIZED/SUBMITTED/APPROVED claim
            captured = False
            for oc in other_open_claims:
                if oc["period_start"] <= s["completed_at"] < oc["period_end"]:
                    captured = True
                    break
            if not captured:
                final.append(s)
    return provisional, final


def _price_sessions(sessions, field: str) -> tuple[Decimal, int]:
    """Sum per-session rounded GGE per fuel type, then price.

    Returns (total_gge, amount_cents).
    """
    sum_cng = Decimal("0")
    sum_rng = Decimal("0")
    for s in sessions:
        dispenser = STORE.dispensers.get(s["dispenser_id"])
        fuel_type = dispenser["fuel_type"] if dispenser is not None else "CNG"
        if fuel_type == "RNG":
            sum_rng += s[field]
        else:
            sum_cng += s[field]
    total_gge = sum_cng + sum_rng
    amount = round_half_up_cents(
        sum_cng * CNG_CREDIT_CENTS_PER_GGE + sum_rng * RNG_CREDIT_CENTS_PER_GGE
    )
    return total_gge, amount


def compute_provisional_claim(station_id: str, period_start: datetime,
                              period_end: datetime) -> tuple[Decimal, int]:
    provisional, _ = _claim_session_sets(station_id, period_start, period_end)
    return _price_sessions(provisional, "provisional_gge")


def compute_final_claim(station_id: str, period_start: datetime,
                        period_end: datetime) -> tuple[Decimal, int]:
    _, final = _claim_session_sets(station_id, period_start, period_end)
    return _price_sessions(final, "settled_gge")


# ---------------------------------------------------------------------------
# Minimum-volume settlement
# ---------------------------------------------------------------------------

def compute_settlement(contract: dict, month: str) -> tuple[Decimal, Decimal, int]:
    """Returns (delivered_gge, shortfall_gge, penalty_cents)."""
    start_dt = month_start_dt(month)
    end_dt = month_start_dt(next_month(month))
    delivered = Decimal("0")
    for s in STORE.fueling_sessions.values():
        if s["access_type"] != "PRIVATE":
            continue
        if s["fleet_account_id"] != contract["fleet_account_id"]:
            continue
        if s["station_id"] != contract["station_id"]:
            continue
        if s["status"] not in ("COMPLETED", "SETTLED"):
            continue
        if s["completed_at"] is None:
            continue
        if not (start_dt <= s["completed_at"] < end_dt):
            continue
        delivered += s["settled_gge"]
    committed = contract["committed_monthly_gge"]
    shortfall = committed - delivered
    if shortfall < 0:
        shortfall = Decimal("0")
    tier_cap = committed * TIER1_CAP_PCT
    tier1_portion = min(shortfall, tier_cap)
    tier2_portion = shortfall - tier_cap
    if tier2_portion < 0:
        tier2_portion = Decimal("0")
    penalty = round_half_up_cents(
        tier1_portion * contract["shortfall_tier1_rate_cents"]
        + tier2_portion * contract["shortfall_tier2_rate_cents"]
    )
    return delivered, shortfall, penalty
