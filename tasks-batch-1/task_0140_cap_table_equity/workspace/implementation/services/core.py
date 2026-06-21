"""Core domain helpers: lookups, ledger recomputation, vesting, serialization.

PRD §2.4 (computed-field freshness), §2.7 (referential integrity),
§2.8 (cascading consistency / ledger totals), §3.7 (vesting mechanics).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import db
from common import iso_format, touch
from errors import APIError, ERR_NOT_FOUND


# --------------------------------------------------------------------------
# Lookups (ERR_NOT_FOUND on miss). PRD §2.7: ids resolved left-to-right.
# --------------------------------------------------------------------------

def _lookup(store: dict, entity_id: str, label: str) -> dict:
    ent = store.get(entity_id)
    if ent is None:
        raise APIError(ERR_NOT_FOUND, f"{label} not found.", 404)
    return ent


def get_cap_table(cid: str) -> dict:
    return _lookup(db.cap_tables, cid, "CapTable")


def get_security_class(cid: str) -> dict:
    return _lookup(db.security_classes, cid, "SecurityClass")


def get_shareholder(cid: str) -> dict:
    return _lookup(db.shareholders, cid, "Shareholder")


def get_valuation(cid: str) -> dict:
    return _lookup(db.valuations, cid, "Valuation")


def get_option_pool(cid: str) -> dict:
    return _lookup(db.option_pools, cid, "OptionPool")


def get_option_grant(cid: str) -> dict:
    return _lookup(db.option_grants, cid, "OptionGrant")


def get_exercise(cid: str) -> dict:
    return _lookup(db.exercises, cid, "Exercise")


def get_safe_note(cid: str) -> dict:
    return _lookup(db.safe_notes, cid, "SafeNote")


def get_liquidation_event(cid: str) -> dict:
    return _lookup(db.liquidation_events, cid, "LiquidationEvent")


def get_election(cid: str) -> dict:
    return _lookup(db.section_83b_elections, cid, "Section83bElection")


def get_form_3921(cid: str) -> dict:
    return _lookup(db.forms_3921, cid, "Form3921")


def get_blackout(cid: str) -> dict:
    return _lookup(db.blackout_windows, cid, "BlackoutWindow")


def get_waterfall_distribution(cid: str) -> dict:
    return _lookup(db.waterfall_distributions, cid, "WaterfallDistribution")


# --------------------------------------------------------------------------
# Collection accessors scoped to a cap table.
# --------------------------------------------------------------------------

def classes_of(cap_table_id: str) -> list:
    return [c for c in db.security_classes.values() if c["cap_table_id"] == cap_table_id]


def pools_of(cap_table_id: str) -> list:
    return [p for p in db.option_pools.values() if p["cap_table_id"] == cap_table_id]


def grants_of(cap_table_id: str) -> list:
    return [g for g in db.option_grants.values() if g["cap_table_id"] == cap_table_id]


def notes_of(cap_table_id: str) -> list:
    return [n for n in db.safe_notes.values() if n["cap_table_id"] == cap_table_id]


def valuations_of(cap_table_id: str) -> list:
    return [v for v in db.valuations.values() if v["cap_table_id"] == cap_table_id]


def grants_of_pool(pool_id: str) -> list:
    return [g for g in db.option_grants.values() if g["option_pool_id"] == pool_id]


# --------------------------------------------------------------------------
# Vesting. PRD §3.7 / SCAFFOLD calc vested_share_count.
# --------------------------------------------------------------------------

def whole_months_between(start: datetime, now: datetime) -> int:
    """Whole calendar months elapsed, partial months floored down."""
    if now <= start:
        return 0
    months = (now.year - start.year) * 12 + (now.month - start.month)
    # If the day-of-month / time-of-day has not yet been reached this month,
    # the final month is still partial -> floor it off.
    if (now.day, now.hour, now.minute, now.second, now.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return max(0, months)


def compute_vested_shares(grant: dict, now: datetime) -> int:
    share_count = grant["share_count"]
    cliff_months = grant["cliff_months"]
    vesting_months = grant["vesting_months"]
    style = grant["vesting_style"]
    months_elapsed = whole_months_between(grant["grant_date"], now)
    if months_elapsed < cliff_months:
        vested = 0
    elif style == "CLIFF_ONLY":
        vested = share_count
    else:  # GRADED
        capped_months = min(months_elapsed, vesting_months)
        vested = (share_count * capped_months) // vesting_months
    return min(vested, share_count)


# --------------------------------------------------------------------------
# Pool allocation. PRD §3.5 / SCAFFOLD calc pool_allocation.
# allocated = sum of share_count for grants in {ACTIVE, EXERCISED}.
# --------------------------------------------------------------------------

def compute_pool_allocation(pool: dict):
    allocated = 0
    for g in grants_of_pool(pool["id"]):
        if g["status"] in ("ACTIVE", "EXERCISED"):
            allocated += g["share_count"]
    authorized = pool["authorized_shares"]
    available = max(0, authorized - allocated)
    return allocated, available


def refresh_pool_totals(pool: dict) -> None:
    allocated, available = compute_pool_allocation(pool)
    pool["allocated_shares"] = allocated
    pool["available_shares"] = available


def maybe_flip_pool_status(pool: dict) -> None:
    """ACTIVE<->EXHAUSTED based on available_shares. PRD §3.5. CLOSED is terminal."""
    if pool["status"] == "CLOSED":
        return
    if pool["available_shares"] == 0 and pool["status"] == "ACTIVE":
        pool["status"] = "EXHAUSTED"
    elif pool["available_shares"] > 0 and pool["status"] == "EXHAUSTED":
        pool["status"] = "ACTIVE"


# --------------------------------------------------------------------------
# Ledger totals. PRD §2.8 / SCAFFOLD calc issued_share_count, fully_diluted_count.
# --------------------------------------------------------------------------

def compute_issued_shares(cap_table_id: str) -> int:
    return sum(c["shares_outstanding"] for c in classes_of(cap_table_id))


def latest_effective_valuation(cap_table_id: str) -> Optional[dict]:
    eff = [v for v in valuations_of(cap_table_id) if v["status"] == "EFFECTIVE"]
    if not eff:
        return None
    # at most one EFFECTIVE per cap table; if more, take the newest by created_at
    return max(eff, key=lambda v: (v["created_at"], v["id"]))


def as_converted_shares(note: dict, valuation: Optional[dict], cap_table: dict) -> int:
    """As-converted share equivalent of an OUTSTANDING note at the latest
    EFFECTIVE valuation's implied price. Floored to whole shares. PRD §2.8.

    The implied price is the valuation's fmv_per_share_cents (the 409A FMV per
    common share). Without an effective valuation, the note contributes 0.
    """
    if valuation is None:
        return 0
    price = valuation["fmv_per_share_cents"]
    if price <= 0:
        return 0
    invested = note["principal_cents"]  # base for as-converted dilution estimate
    return invested // price


def compute_fully_diluted_shares(cap_table: dict) -> int:
    cap_table_id = cap_table["id"]
    fd = compute_issued_shares(cap_table_id)
    for g in grants_of(cap_table_id):
        if g["status"] == "ACTIVE":
            fd += g["share_count"] - g["exercised_shares"]
    for p in pools_of(cap_table_id):
        if p["status"] == "ACTIVE":
            _, available = compute_pool_allocation(p)
            fd += available
    eff = latest_effective_valuation(cap_table_id)
    for n in notes_of(cap_table_id):
        if n["status"] == "OUTSTANDING":
            fd += as_converted_shares(n, eff, cap_table)
    return fd


def recompute_ledger(cap_table: dict, now: datetime, *, bump: bool = True) -> None:
    """Recompute issued_shares + fully_diluted_shares on the cap table.

    PRD §2.8: each action that recomputes these totals explicitly bumps the
    cap table's version + updated_at. The side-effect contracts in §3 state the
    version increment unconditionally, so when `bump` is True we always bump.
    """
    cap_table["issued_shares"] = compute_issued_shares(cap_table["id"])
    cap_table["fully_diluted_shares"] = compute_fully_diluted_shares(cap_table)
    if bump:
        touch(cap_table, now)


def refresh_cap_table_read(cap_table: dict) -> None:
    """GET-time recompute -- no version bump (a read is not a mutation)."""
    cap_table["issued_shares"] = compute_issued_shares(cap_table["id"])
    cap_table["fully_diluted_shares"] = compute_fully_diluted_shares(cap_table)


# --------------------------------------------------------------------------
# Serialization: datetimes -> ISO strings; inject live computed fields.
# --------------------------------------------------------------------------

_DATETIME_FIELDS = {
    "created_at", "updated_at", "locked_at", "valuation_date", "expires_at",
    "issued_at", "grant_date", "issue_date", "filed_date", "exercise_date",
    "starts_at", "ends_at",
}


def _serialize_value(key: str, value):
    if value is None:
        return None
    if key in _DATETIME_FIELDS and isinstance(value, datetime):
        return iso_format(value)
    return value


def serialize(entity: dict) -> dict:
    return {k: _serialize_value(k, v) for k, v in entity.items()}


def serialize_cap_table(cap_table: dict) -> dict:
    refresh_cap_table_read(cap_table)
    return serialize(cap_table)


def serialize_pool(pool: dict) -> dict:
    allocated, available = compute_pool_allocation(pool)
    pool["allocated_shares"] = allocated
    pool["available_shares"] = available
    return serialize(pool)


def serialize_grant(grant: dict, now: datetime) -> dict:
    grant["vested_shares"] = compute_vested_shares(grant, now)
    return serialize(grant)
