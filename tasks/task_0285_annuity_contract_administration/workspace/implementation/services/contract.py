"""Contract aggregate: computed fields, chronological replay, cascades.

This module owns the contract value model (PRD §3.2, §3.4, §3.5, §3.9) and the
helpers other services use to mutate a contract (version bumps, freeze checks,
cascades on surrender / annuitization / death claim).
"""

from clock import iso8601
from db import store

DAY_SECONDS = 86400
YEAR_SECONDS = 365 * DAY_SECONDS  # contract_year uses a flat 365-day year


# --- creation ---------------------------------------------------------------
def create_contract(product_id, owner_name, annuitant_age):
    now = store.clock.now()
    cid = store.new_id()
    contract = {
        "id": cid,
        "product_id": product_id,
        "owner_name": owner_name,
        "annuitant_age": annuitant_age,
        "issue_date": None,
        "status": "PENDING",
        # Stored ledger anchors (recomputed values are derived on read).
        "highest_anniversary_value_cents": 0,
        "free_withdrawal_used_cents": 0,
        "created_at": iso8601(now),
        "updated_at": iso8601(now),
        "version": 1,
        "_seq": store.next_seq(),
        # Cached contract_year value reflecting the last anniversary roll; the
        # live contract_year is recomputed from issue_date + clock on read.
    }
    store.contracts[cid] = contract
    return contract


# --- version / timestamp bumps ---------------------------------------------
def bump(contract):
    """Record a real mutation: advance version and updated_at (PRD §2.5)."""
    contract["version"] += 1
    contract["updated_at"] = iso8601(store.clock.now())


# --- computed: contract_year & surrender_charge_bps -------------------------
def contract_year(contract):
    """Completed contract years since issue_date: floor(elapsed / 365 days).
    0 throughout the first year; 0 while still PENDING (no issue_date)."""
    issue = contract.get("issue_date")
    if not issue:
        return 0
    from clock import parse_iso8601

    issued = parse_iso8601(issue)
    now = store.clock.now()
    elapsed = (now - issued).total_seconds()
    if elapsed < 0:
        return 0
    return int(elapsed // YEAR_SECONDS)


def surrender_charge_bps(contract):
    """Schedule row for the current completed contract_year; 0 once past the
    surrender period (PRD §3.4)."""
    product = store.products.get(contract["product_id"])
    schedule = product.get("surrender_charge_schedule") or []
    cy = contract_year(contract)
    if cy >= len(schedule):
        return 0
    row = schedule[cy]
    return int(row.get("charge_bps", 0))


# --- computed: chronological accumulation value -----------------------------
def _value_events(contract):
    """All value-bearing events on a contract, ordered by created_at ASC with
    ties broken by insertion sequence (never by id) — PRD §3.5."""
    cid = contract["id"]
    events = []
    for p in store.premiums.values():
        if p["contract_id"] == cid and p["status"] == "CLEARED":
            events.append((p["created_at"], p["_seq"], "premium", p))
    for c in store.crediting_events.values():
        if c["contract_id"] == cid:
            events.append((c["created_at"], c["_seq"], "credit", c))
    for w in store.withdrawals.values():
        if w["contract_id"] == cid and w["status"] == "SETTLED":
            events.append((w["created_at"], w["_seq"], "withdrawal", w))
    events.sort(key=lambda e: (e[0], e[1]))
    return events


def accumulation_value_cents(contract):
    """Chronological ledger replay, floored at 0 (PRD §3.5).

    SURRENDERED / ANNUITIZED / TERMINATED contracts have had their value
    converted away; their accumulation reads 0 regardless of ledger history.
    """
    if contract["status"] in ("SURRENDERED", "ANNUITIZED", "TERMINATED"):
        return 0
    acc = 0
    for _, _, kind, ev in _value_events(contract):
        if kind == "premium":
            acc += ev["net_premium_cents"]
        elif kind == "credit":
            acc += ev["credit_cents"]
        elif kind == "withdrawal":
            acc -= ev["gross_withdrawal_cents"]
    return max(acc, 0)


def cumulative_premium_cents(contract):
    """Sum of net_premium_cents across CLEARED premiums (PRD §3.2)."""
    cid = contract["id"]
    return sum(
        p["net_premium_cents"]
        for p in store.premiums.values()
        if p["contract_id"] == cid and p["status"] == "CLEARED"
    )


# --- freeze (open death claim) ----------------------------------------------
def is_frozen(contract):
    """True when an open DeathClaim (FILED/VERIFYING/VALUED) blocks the
    contract (PRD §3.9)."""
    cid = contract["id"]
    for dc in store.death_claims.values():
        if dc["contract_id"] == cid and dc["status"] in (
            "FILED",
            "VERIFYING",
            "VALUED",
        ):
            return True
    return False


def has_open_or_funded_claim(contract):
    """True if any claim is FILED/VERIFYING/VALUED/FUNDED — blocks new filing."""
    cid = contract["id"]
    for dc in store.death_claims.values():
        if dc["contract_id"] == cid and dc["status"] in (
            "FILED",
            "VERIFYING",
            "VALUED",
            "FUNDED",
        ):
            return True
    return False


# --- cascades ---------------------------------------------------------------
def liquidate_allocations(contract):
    cid = contract["id"]
    for alloc in store.sub_account_allocations.values():
        if alloc["contract_id"] == cid and alloc["status"] == "ACTIVE":
            alloc["status"] = "LIQUIDATED"
            alloc["version"] += 1
            alloc["updated_at"] = iso8601(store.clock.now())


# --- serialization ----------------------------------------------------------
def serialize(contract):
    return {
        "id": contract["id"],
        "product_id": contract["product_id"],
        "owner_name": contract["owner_name"],
        "annuitant_age": contract["annuitant_age"],
        "issue_date": contract["issue_date"],
        "contract_year": contract_year(contract),
        "accumulation_value_cents": accumulation_value_cents(contract),
        "cumulative_premium_cents": cumulative_premium_cents(contract),
        "highest_anniversary_value_cents": contract["highest_anniversary_value_cents"],
        "free_withdrawal_used_cents": contract["free_withdrawal_used_cents"],
        "status": contract["status"],
        "surrender_charge_bps": surrender_charge_bps(contract),
        "created_at": contract["created_at"],
        "updated_at": contract["updated_at"],
        "version": contract["version"],
    }
