"""Domain services: the inventory partition, the loss waterfall, fund cash,
posture derivation and the lazy transitions.

Derived figures (the stand's four claim buckets, the audit finding counts, the
project's dedicated tonnage, the fund's NAV and exposure counters) are computed
from the stored rows on demand, so the conserved identity of PRD 2.7 can never
drift out of line with the rows that claim the wood.
"""

from decimal import Decimal

from flask import g

import calc
import db
from calc import D, rhu, rhu_int
from db import store
from errors import ApiError

# --------------------------------------------------------------- mutation log


def mark(rec):
    """Record a mutation once per request: refresh updated_at, bump version."""
    if rec is None or "version" not in rec:
        return
    key = id(rec)
    dirty = getattr(g, "dirty_records", None)
    if dirty is None:
        dirty = set()
        g.dirty_records = dirty
    if key in dirty:
        return
    dirty.add(key)
    db.touch(rec)


# ------------------------------------------------------------------- lookups

def find(collection, record_id, error_id):
    if not isinstance(record_id, str):
        raise ApiError(error_id)
    rec = collection.get(record_id)
    if rec is None:
        raise ApiError(error_id)
    return rec


def rows(collection, **filters):
    out = []
    for rec in collection.values():
        if all(rec.get(k) == v for k, v in filters.items()):
            out.append(rec)
    return db.sorted_records(out)


def property_of_stand(stand):
    return store.properties.get(stand["property_id"])


def fund_of_property(prop):
    return store.funds.get(prop["fund_id"])


def fund_of_stand(stand):
    prop = property_of_stand(stand)
    return fund_of_property(prop) if prop else None


def stands_of_property(property_id):
    return rows(store.stands, property_id=property_id)


def properties_of_fund(fund_id):
    return rows(store.properties, fund_id=fund_id)


# --------------------------------------------------- stand inventory buckets

def reserved_tons(stand_id):
    total = sum((D(b["planned_tons"]) for b in store.harvest_blocks.values()
                 if b["stand_id"] == stand_id and b["status"] == "RESERVED"), Decimal(0))
    return rhu(total, 2)


def committed_tons(stand_id):
    total = sum((D(b["planned_tons"]) for b in store.harvest_blocks.values()
                 if b["stand_id"] == stand_id and b["status"] == "COMMITTED"), Decimal(0))
    return rhu(total, 2)


def dedicated_tons(stand_id):
    total = Decimal(0)
    for ded in store.carbon_dedications.values():
        if ded["stand_id"] == stand_id and ded["status"] in ("PENDING", "ACTIVE", "REDUCED"):
            total += D(ded["dedicated_tons"]) - D(ded["reduced_tons"])
    return rhu(total, 2)


def hbu_withdrawn_tons(stand_id):
    total = sum((D(p["withdrawn_tons"]) for p in store.hbu_parcels.values()
                 if p["stand_id"] == stand_id and p["status"] == "CLOSED"), Decimal(0))
    return rhu(total, 2)


def stand_buckets(stand):
    reserved = reserved_tons(stand["id"])
    committed = committed_tons(stand["id"])
    dedicated = dedicated_tons(stand["id"])
    withdrawn = hbu_withdrawn_tons(stand["id"])
    net = D(stand["net_merch_tons"])
    available = rhu(net - reserved - committed - dedicated - withdrawn, 2)
    return {
        "reserved_tons": reserved,
        "committed_tons": committed,
        "dedicated_tons": dedicated,
        "hbu_withdrawn_tons": withdrawn,
        "available_tons": available,
    }


def available_tons(stand):
    return stand_buckets(stand)["available_tons"]


def allocated_tons(stand):
    buckets = stand_buckets(stand)
    return rhu(buckets["reserved_tons"] + buckets["committed_tons"]
               + buckets["dedicated_tons"] + buckets["hbu_withdrawn_tons"], 2)


# ------------------------------------------------------------- carbon totals

def dedicated_tons_total(project_id):
    total = Decimal(0)
    for ded in store.carbon_dedications.values():
        if ded["carbon_project_id"] == project_id and ded["status"] in (
                "PENDING", "ACTIVE", "REDUCED"):
            total += D(ded["dedicated_tons"]) - D(ded["reduced_tons"])
    return rhu(total, 2)


# -------------------------------------------------------- inventory-loss waterfall

def run_waterfall(stand, shortfall, voided_reason):
    """The ordered claw-back of PRD 3.8, shared by hazard loss and HBU closing.

    Bucket one is the stand's RESERVED blocks oldest first, bucket two its
    COMMITTED blocks, bucket three its dedications with ACTIVE before PENDING.
    hbu_withdrawn_tons is never clawed back.
    """
    remaining = rhu(shortfall, 2)
    log = []
    if remaining <= 0:
        return log

    prop = property_of_stand(stand)
    targets = []
    targets.extend(("BLOCK", b) for b in rows(store.harvest_blocks,
                                              stand_id=stand["id"], status="RESERVED"))
    targets.extend(("BLOCK", b) for b in rows(store.harvest_blocks,
                                              stand_id=stand["id"], status="COMMITTED"))
    targets.extend(("DEDICATION", d) for d in rows(store.carbon_dedications,
                                                   stand_id=stand["id"], status="ACTIVE"))
    targets.extend(("DEDICATION", d) for d in rows(store.carbon_dedications,
                                                   stand_id=stand["id"], status="PENDING"))

    for kind, target in targets:
        if remaining <= 0:
            break
        if kind == "BLOCK":
            target_remaining = D(target["planned_tons"])
        else:
            target_remaining = D(target["dedicated_tons"]) - D(target["reduced_tons"])
        if target_remaining <= 0:
            continue
        cut = min(remaining, target_remaining)
        if kind == "BLOCK":
            target["planned_tons"] = rhu(D(target["planned_tons"]) - cut, 2)
            if target["planned_tons"] == Decimal("0.00"):
                target["status"] = "VOIDED"
                target["voided_reason"] = voided_reason
            mark(target)
            if prop is not None:
                set_harvest_plan_status(prop, "REPLAN_REQUIRED")
            target_type = "HARVEST_BLOCK"
        else:
            target["reduced_tons"] = rhu(D(target["reduced_tons"]) + cut, 2)
            target["status"] = "REDUCED"
            mark(target)
            project = store.carbon_projects.get(target["carbon_project_id"])
            if project is not None:
                project["buffer_deficit_tons"] = rhu(
                    D(project["buffer_deficit_tons"])
                    + rhu(cut * calc.CARBON_BUFFER_POOL_PCT / 100, 2), 2)
                project["status"] = "REVERSAL_PENDING"
                mark(project)
            target_type = "CARBON_DEDICATION"
        log.append({
            "target_type": target_type,
            "target_id": target["id"],
            "tons_cut": rhu(cut, 2),
            "resulting_status": target["status"],
        })
        remaining = rhu(remaining - cut, 2)
    return log


def set_harvest_plan_status(prop, value):
    if prop["harvest_plan_status"] != value:
        prop["harvest_plan_status"] = value
        mark(prop)


# ------------------------------------------------------------------ appraisal

def property_carry_value(prop):
    """The property's contribution to fund NAV (PRD 3.3)."""
    if prop["status"] not in ("OWNED", "HBU_MARKETED"):
        return Decimal("0.00")
    status = prop["appraisal_status"]
    if status == "SIGNED":
        return rhu(D(prop["appraised_value_usd"] or 0), 2)
    if status == "STALE":
        return rhu(D(prop["appraised_value_usd"] or 0)
                   * (Decimal(1) - calc.STALE_APPRAISAL_HAIRCUT_PCT / 100), 2)
    return rhu(D(prop["acquisition_price_usd"] or 0), 2)


def apply_lazy_appraisal_stale(prop):
    """SIGNED -> STALE when the signature is more than 365 days old."""
    if prop["appraisal_status"] != "SIGNED" or not prop.get("_appraisal_signed_dt"):
        return False
    elapsed = db.logical_now() - prop["_appraisal_signed_dt"]
    if elapsed > db.TIMEDELTA(days=calc.APPRAISAL_STALE_DAYS):
        prop["appraisal_status"] = "STALE"
        mark(prop)
        return True
    return False


def apply_lazy_stale_for_fund(fund):
    for prop in properties_of_fund(fund["id"]):
        apply_lazy_appraisal_stale(prop)


# ----------------------------------------------------------------- fund cash

def recompute_fund(fund):
    """Refresh every derived figure on the fund (PRD 2.11 / 3.3)."""
    carry_total = Decimal(0)
    owned_count = 0
    replan_count = 0
    stale_count = 0
    inventory = Decimal(0)
    for prop in properties_of_fund(fund["id"]):
        if prop["status"] in ("OWNED", "HBU_MARKETED"):
            owned_count += 1
            carry_total += property_carry_value(prop)
            if prop["appraisal_status"] != "SIGNED":
                stale_count += 1
        if prop["harvest_plan_status"] == "REPLAN_REQUIRED":
            replan_count += 1
        for stand in stands_of_property(prop["id"]):
            if stand["status"] != "DISPOSED":
                inventory += D(stand["net_merch_tons"])
    fund["nav_usd"] = rhu(D(fund["cash_balance_usd"]) + carry_total, 2)
    fund["cash_yield_bps"] = rhu_int(
        D(fund["net_operating_cash_usd"]) / D(fund["committed_capital_usd"]) * calc.BPS_SCALE)
    fund["harvest_acceleration_required"] = (
        fund["cash_yield_bps"] < fund["target_cash_yield_bps"])
    fund["replan_property_count"] = replan_count
    fund["valuation_basis_stale_count"] = stale_count
    return {
        "owned_property_count": owned_count,
        "appraised_value_total_usd": rhu(carry_total, 2),
        "standing_inventory_tons": rhu(inventory, 2),
    }


def credit_fund(fund, amount, operating=True):
    amount = rhu(amount, 2)
    fund["cash_balance_usd"] = rhu(D(fund["cash_balance_usd"]) + amount, 2)
    if operating:
        fund["net_operating_cash_usd"] = rhu(
            D(fund["net_operating_cash_usd"]) + amount, 2)
    recompute_fund(fund)
    mark(fund)


def guard_fund_cash(fund, amount):
    if D(fund["cash_balance_usd"]) < rhu(amount, 2):
        raise ApiError("ERR_FUND_CASH_INSUFFICIENT")


def debit_fund(fund, amount, operating=True):
    amount = rhu(amount, 2)
    fund["cash_balance_usd"] = rhu(D(fund["cash_balance_usd"]) - amount, 2)
    if operating:
        fund["net_operating_cash_usd"] = rhu(
            D(fund["net_operating_cash_usd"]) - amount, 2)
    recompute_fund(fund)
    mark(fund)


# --------------------------------------------------------- dominant species

def dominant_species(property_id, inventoried_only=False):
    candidates = stands_of_property(property_id)
    if inventoried_only:
        candidates = [s for s in candidates if s["status"] == "INVENTORIED"]
    best = None
    for stand in candidates:
        if best is None or D(stand["acres"]) > D(best["acres"]):
            best = stand
    return best["species_code"] if best else None


def inventoried_totals(property_id):
    base_tons = Decimal(0)
    acres = Decimal(0)
    for stand in stands_of_property(property_id):
        if stand["status"] == "INVENTORIED":
            base_tons += D(stand["net_merch_tons"])
            acres += D(stand["acres"])
    return rhu(base_tons, 2), rhu(acres, 2)


# ----------------------------------------------------- certification posture

def audit_counts(audit):
    major = 0
    open_major = 0
    open_minor = 0
    for finding in store.audit_findings.values():
        if finding["certification_audit_id"] != audit["id"]:
            continue
        if finding["severity"] == "MAJOR":
            major += 1
            if finding["status"] in ("OPEN", "CAR_SUBMITTED"):
                open_major += 1
        elif finding["severity"] == "MINOR":
            if finding["status"] in ("OPEN", "CAR_SUBMITTED"):
                open_minor += 1
    return {
        "major_finding_count": major,
        "open_major_count": open_major,
        "open_minor_count": open_minor,
    }


def property_open_counts(property_id):
    open_major = 0
    open_minor = 0
    audit_ids = {a["id"] for a in store.certification_audits.values()
                 if a["property_id"] == property_id}
    for finding in store.audit_findings.values():
        if finding["certification_audit_id"] not in audit_ids:
            continue
        if finding["status"] not in ("OPEN", "CAR_SUBMITTED"):
            continue
        if finding["severity"] == "MAJOR":
            open_major += 1
        elif finding["severity"] == "MINOR":
            open_minor += 1
    return open_major, open_minor


def revert_committed_blocks(prop):
    """Any transition INTO SUSPENDED unwinds committed harvest volume."""
    for stand in stands_of_property(prop["id"]):
        for block in rows(store.harvest_blocks, stand_id=stand["id"], status="COMMITTED"):
            block["status"] = "RESERVED"
            mark(block)


def recompute_posture(prop):
    if prop["certification_scheme"] == "NONE":
        posture = "UNCERTIFIED"
    else:
        suspended_audit = any(
            a["status"] == "SUSPENDED"
            for a in store.certification_audits.values()
            if a["property_id"] == prop["id"])
        open_major, open_minor = property_open_counts(prop["id"])
        if suspended_audit:
            posture = "SUSPENDED"
        elif open_major >= calc.MAJOR_SUSPENSION_THRESHOLD:
            posture = "SUSPENDED"
        elif open_major == 1 or open_minor >= 1:
            posture = "CONDITIONAL"
        else:
            posture = "CERTIFIED"
    if posture != prop["certification_posture"]:
        prop["certification_posture"] = posture
        mark(prop)
        if posture == "SUSPENDED":
            revert_committed_blocks(prop)
    return posture


# ------------------------------------------------------------------- leases

def apply_lazy_lease_expiry(lease):
    if lease["status"] != "ACTIVE":
        return False
    if db.logical_date() >= lease["_term_end"]:
        lease["status"] = "EXPIRED"
        mark(lease)
        return True
    return False


def lease_coverage_conflict(prop, candidate):
    """Aggregate leased acreage over overlapping half-open terms (PRD 3.6)."""
    capacity = calc.lease_capacity(prop["total_acres"])
    total = Decimal(0)
    for lease in rows(store.recreational_leases, property_id=prop["id"]):
        if lease["id"] == candidate["id"]:
            continue
        if lease["status"] not in ("PENDING", "ACTIVE"):
            continue
        if (candidate["_term_start"] < lease["_term_end"]
                and lease["_term_start"] < candidate["_term_end"]):
            total += D(lease["leased_acres"])
    return rhu(total + D(candidate["leased_acres"]), 2) > capacity


def blackout_conflict(prop, start_date, end_date):
    """A closed block window against every ACTIVE lease's half-open blackout."""
    for lease in rows(store.recreational_leases, property_id=prop["id"]):
        if lease["status"] != "ACTIVE":
            continue
        if start_date < lease["_blackout_end"] and lease["_blackout_start"] <= end_date:
            return True
    return False


# ------------------------------------------------------------------- hazard

def trailing_settled_claims(property_id):
    cutoff = db.logical_now() - db.TIMEDELTA(days=calc.TRAILING_CLAIM_WINDOW_DAYS)
    stand_ids = {s["id"] for s in stands_of_property(property_id)}
    total = Decimal(0)
    for event in store.hazard_events.values():
        if event["stand_id"] not in stand_ids or event["status"] != "SETTLED":
            continue
        if event["_occurred_dt"] >= cutoff:
            total += D(event["settled_claim_usd"] or 0)
    return rhu(total, 2)
