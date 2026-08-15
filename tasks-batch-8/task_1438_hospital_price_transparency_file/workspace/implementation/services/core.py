"""Business logic: rate materialization, charge-record derivation, cycle
aggregates/posture, cascade chains, and penalty accrual (scaffold section 1.3,
PRD sections 2.5/2.7/2.8/3.3/3.6/3.8).

Aggregate and posture fields on PublicationCycle are pure functions of child
state, so they are computed on demand at read time — recomputation can never
drift. Version bumps remain explicit per the mutation rules of PRD 2.4/2.8.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

import db
from db import bump

DEID_MIN_PAYERS = 3

RATE_TYPE_PERCENT_OF_GROSS = "PERCENT_OF_GROSS"
RATE_TYPE_FEE_SCHEDULE_FLAT = "FEE_SCHEDULE_FLAT"
RATE_TYPE_PERCENT_OF_MEDICARE = "PERCENT_OF_MEDICARE"
RATE_TYPES = {RATE_TYPE_PERCENT_OF_GROSS, RATE_TYPE_FEE_SCHEDULE_FLAT, RATE_TYPE_PERCENT_OF_MEDICARE}
PERCENT_RATE_TYPES = {RATE_TYPE_PERCENT_OF_GROSS, RATE_TYPE_PERCENT_OF_MEDICARE}

COUNTED_RECORD_STATUSES = ("VALIDATED", "PUBLISHED", "FLAGGED")

# Penalty accrual constants (scaffold calculations.penalty_accrual)
SIMPLE_DAILY_CENTS = 30000
TIER1_MAX_BEDS = 30
TIER1_DAILY_CENTS = 10000
TIER2_MAX_BEDS = 199
TIER2_DAILY_CENTS = 20000
TIER3_DAILY_CENTS = 40000
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Negotiated amount materialization (PRD 3.2)
# ---------------------------------------------------------------------------

def materialize_rate(rate: dict) -> int:
    """Integer cents, floor truncation. FEE_SCHEDULE_FLAT is item-independent;
    the percent branches read the item's CURRENT field values, never a snapshot."""
    rt = rate["rate_type"]
    if rt == RATE_TYPE_FEE_SCHEDULE_FLAT:
        return int(rate["flat_amount_cents"])
    item = db.service_items.get(rate["service_item_id"])
    pct = Decimal(str(rate["rate_percent"]))
    if rt == RATE_TYPE_PERCENT_OF_GROSS:
        base = item["gross_charge_cents"] if item else 0
    else:  # PERCENT_OF_MEDICARE
        base = (item.get("medicare_base_cents") or 0) if item else 0
    return int((Decimal(base) * pct / Decimal(100)).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Standard-charge extrema + derived disclosure (PRD 3.3)
# ---------------------------------------------------------------------------

def _active_rate_partitions(facility_id: str, item_id: str):
    """Partition the facility+item rate universe by confidentiality clause.
    Only ACTIVE rates under ACTIVE contracts of the same facility participate."""
    disclose, derived_only, aggregate = [], [], []
    payer_ids: set[str] = set()
    for r in db.payer_negotiated_rates.values():
        if r["service_item_id"] != item_id or r["status"] != "ACTIVE":
            continue
        c = db.payer_contracts.get(r["contract_id"])
        if not c or c["status"] != "ACTIVE" or c["facility_id"] != facility_id:
            continue
        payer_ids.add(c["payer_id"])
        clause = c["confidentiality_clause"]
        if clause == "DISCLOSE_ALLOWED":
            disclose.append((r, c))
        elif clause == "DERIVED_ONLY":
            derived_only.append((r, c))
        elif clause == "AGGREGATE_ONLY":
            aggregate.append((r, c))
    return disclose, derived_only, aggregate, len(payer_ids)


def payer_count_for_item(facility_id: str, item_id: str) -> int:
    """Distinct payers whose ACTIVE contracts at the facility hold an ACTIVE
    rate for the item (de-identification payer floor; never circular)."""
    return _active_rate_partitions(facility_id, item_id)[3]


def recompute_record(rec: dict) -> None:
    """Recompute min/max/derived in place from live rate+contract state."""
    disclose, derived_only, aggregate, pcount = _active_rate_partitions(
        rec["facility_id"], rec["service_item_id"]
    )
    if disclose:
        rec["min_negotiated_cents"] = min(r["negotiated_amount_cents"] for r, _ in disclose)
        rec["max_negotiated_cents"] = max(r["negotiated_amount_cents"] for r, _ in disclose)
    else:
        rec["min_negotiated_cents"] = None
        rec["max_negotiated_cents"] = None

    agg_incl = aggregate if pcount >= DEID_MIN_PAYERS else []
    if not derived_only and not agg_incl:
        rec["derivation_method"] = "EXACT_MIN"
        rec["derived_disclosure_cents"] = rec["min_negotiated_cents"]
    else:
        pool = disclose + derived_only + agg_incl
        if not pool:
            rec["derivation_method"] = "NONE"
            rec["derived_disclosure_cents"] = None
        else:
            num = sum(r["negotiated_amount_cents"] * c["annual_volume"] for r, c in pool)
            den = sum(c["annual_volume"] for _, c in pool)
            if den <= 0:
                rec["derivation_method"] = "NONE"
                rec["derived_disclosure_cents"] = None
            else:
                rec["derivation_method"] = "MIX_WEIGHTED"
                # Non-negative integer arithmetic: // is exactly floor.
                rec["derived_disclosure_cents"] = num // den


# ---------------------------------------------------------------------------
# Cycle aggregates and posture (computed on demand — pure functions)
# ---------------------------------------------------------------------------

def cycle_records(cycle_id: str) -> list:
    return [r for r in db.standard_charge_records.values() if r["publication_cycle_id"] == cycle_id]


def cycle_aggregates(cycle_id: str) -> tuple[int, int, int]:
    counted = [r for r in cycle_records(cycle_id) if r["status"] in COUNTED_RECORD_STATUSES]
    return (
        len(counted),
        sum(r["gross_charge_cents"] for r in counted),
        sum(r["derived_disclosure_cents"] or 0 for r in counted),
    )


def cycle_sealed_file(cycle_id: str):
    sealed = [
        f for f in db.machine_readable_files.values()
        if f["publication_cycle_id"] == cycle_id and f["generation_status"] == "SEALED"
    ]
    sealed.sort(key=lambda f: f.get("_seq", 0))
    return sealed[0] if sealed else None


def cycle_posture(cycle: dict) -> str:
    st = cycle["status"]
    if st == "OPEN":
        fac = db.facilities.get(cycle["facility_id"])
        floor = fac["min_records_per_cycle"] if fac else 1
        count, _, _ = cycle_aggregates(cycle["id"])
        return "FREEZABLE" if count >= floor else "COLLECTING"
    if st == "FROZEN":
        f = cycle_sealed_file(cycle["id"])
        if f is None:
            return "AWAITING_FILE"
        return {
            "UNVALIDATED": "FILE_UNVALIDATED",
            "VALID": "PUBLISHABLE",
            "INVALID": "FILE_INVALID",
        }[f["validation_status"]]
    if st == "PUBLISHED":
        return "CURRENT"
    return "ARCHIVED"  # SUPERSEDED


def cycle_view(cycle: dict) -> dict:
    out = db.public(cycle)
    count, gross, rollup = cycle_aggregates(cycle["id"])
    out["validated_record_count"] = count
    out["total_gross_cents"] = gross
    out["derived_rollup_cents"] = rollup
    out["posture"] = cycle_posture(cycle)
    return out


# ---------------------------------------------------------------------------
# Cascade chains (PRD 2.8 / 3.8) — atomic within the triggering request
# ---------------------------------------------------------------------------

def cascade_records_cycles(facility_id: str, item_ids: set) -> None:
    """Links 2+3: DRAFT/VALIDATED records of the facility covering the given
    items recompute (bump); each affected cycle recomputes and bumps once."""
    if not item_ids:
        return
    touched_cycle_ids: list[str] = []
    for rec in db.standard_charge_records.values():
        if (
            rec["facility_id"] == facility_id
            and rec["service_item_id"] in item_ids
            and rec["status"] in ("DRAFT", "VALIDATED")
        ):
            recompute_record(rec)
            bump(rec)
            if rec["publication_cycle_id"] not in touched_cycle_ids:
                touched_cycle_ids.append(rec["publication_cycle_id"])
    for cid in touched_cycle_ids:
        cyc = db.publication_cycles.get(cid)
        if cyc is not None:
            bump(cyc)


def contract_rates(contract_id: str) -> list:
    return [r for r in db.payer_negotiated_rates.values() if r["contract_id"] == contract_id]


def cascade_contract_activate(contract: dict) -> None:
    """Link 1: DRAFT rates -> ACTIVE with amounts recomputed; then links 2+3."""
    items: set = set()
    for r in contract_rates(contract["id"]):
        if r["status"] == "DRAFT":
            r["status"] = "ACTIVE"
            r["negotiated_amount_cents"] = materialize_rate(r)
            bump(r)
            items.add(r["service_item_id"])
    cascade_records_cycles(contract["facility_id"], items)


def cascade_contract_renegotiate(contract: dict) -> None:
    """Link 1: ACTIVE rates -> DRAFT; then links 2+3 (draft rates excluded)."""
    items: set = set()
    for r in contract_rates(contract["id"]):
        if r["status"] == "ACTIVE":
            r["status"] = "DRAFT"
            bump(r)
            items.add(r["service_item_id"])
    cascade_records_cycles(contract["facility_id"], items)


def cascade_contract_deactivate(contract: dict) -> None:
    """Link 1: ACTIVE rates -> INACTIVE; then links 2+3. Used by both
    termination and clock-driven expiry."""
    items: set = set()
    for r in contract_rates(contract["id"]):
        if r["status"] == "ACTIVE":
            r["status"] = "INACTIVE"
            bump(r)
            items.add(r["service_item_id"])
    cascade_records_cycles(contract["facility_id"], items)


def cascade_item_prices(item: dict) -> None:
    """Cascade A (PRD 3.8): DRAFT+ACTIVE rates of the item re-materialize;
    then records and cycles."""
    for r in db.payer_negotiated_rates.values():
        if r["service_item_id"] == item["id"] and r["status"] in ("DRAFT", "ACTIVE"):
            r["negotiated_amount_cents"] = materialize_rate(r)
            bump(r)
    cascade_records_cycles(item["facility_id"], {item["id"]})


# ---------------------------------------------------------------------------
# Penalty accrual (PRD 3.6) — dual variant SIMPLE / TIERED
# ---------------------------------------------------------------------------

def compute_penalty(fac: dict, now=None) -> int:
    rejected_raw = fac.get("rejected_at")
    if not rejected_raw:
        return int(fac.get("penalty_accrued_cents", 0))
    now = now or db.clock()
    rejected = db.parse_dt(rejected_raw)
    days = int((now - rejected).total_seconds() // SECONDS_PER_DAY)
    if days < 0:
        days = 0
    if fac.get("penalty_policy") == "TIERED":
        beds = fac.get("bed_count", 0)
        if beds <= TIER1_MAX_BEDS:
            daily = TIER1_DAILY_CENTS
        elif beds <= TIER2_MAX_BEDS:
            daily = TIER2_DAILY_CENTS
        else:
            daily = TIER3_DAILY_CENTS
    else:
        daily = SIMPLE_DAILY_CENTS
    return days * daily


def facility_view(fac: dict) -> dict:
    out = db.public(fac)
    if fac["attestation_status"] in ("REJECTED", "ESCALATED"):
        # Computed on every read while accruing; persists the last computed value.
        pen = compute_penalty(fac)
        fac["penalty_accrued_cents"] = pen
        out["penalty_accrued_cents"] = pen
    return out
