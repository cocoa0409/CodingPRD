"""Derived aggregates (§2.9). Every function here is a pure read over the store."""

from constants import HELD_SET, MATCHED_SET
from db import by_created, db


# --------------------------------------------------------------------------
# navigation helpers
# --------------------------------------------------------------------------

def lines_of_batch(batch_id):
    return by_created([l for l in db.usage_lines.values() if l["batch_id"] == batch_id])


def batches_of_period(period_id):
    return by_created([b for b in db.batches.values() if b["period_id"] == period_id])


def pools_of_period(period_id):
    return by_created([p for p in db.pools.values() if p["period_id"] == period_id])


def lines_of_period(period_id):
    batch_ids = set(b["id"] for b in db.batches.values() if b["period_id"] == period_id)
    return by_created([l for l in db.usage_lines.values() if l["batch_id"] in batch_ids])


def period_of_line(line):
    batch = db.batches.get(line["batch_id"])
    if batch is None:
        return None
    return db.periods.get(batch["period_id"])


def in_scope_lines(pool):
    """Lines whose batch belongs to the pool's period and whose territory and
    tier equal the pool's, regardless of match_status (§3.6)."""
    result = []
    for line in lines_of_period(pool["period_id"]):
        if line["territory_code"] != pool["territory_code"]:
            continue
        if line["subscription_tier"] != pool["subscription_tier"]:
            continue
        result.append(line)
    return by_created(result)


def pool_for_line(line):
    period = period_of_line(line)
    if period is None:
        return None
    for pool in db.pools.values():
        if (pool["period_id"] == period["id"]
                and pool["territory_code"] == line["territory_code"]
                and pool["subscription_tier"] == line["subscription_tier"]):
            return pool
    return None


def statement_lines_of(statement_id):
    return by_created([l for l in db.statement_lines.values()
                       if l["statement_id"] == statement_id])


def registrations_of_work(work_id):
    return by_created([r for r in db.registrations.values() if r["work_id"] == work_id])


# --------------------------------------------------------------------------
# UsageBatch aggregates
# --------------------------------------------------------------------------

def batch_line_count(batch_id):
    return len([l for l in db.usage_lines.values() if l["batch_id"] == batch_id])


def batch_play_totals(batch_id):
    total = matched = unmatched = disputed = 0
    for line in db.usage_lines.values():
        if line["batch_id"] != batch_id:
            continue
        total += line["play_count"]
        if line["match_status"] in MATCHED_SET:
            matched += line["play_count"]
        elif line["match_status"] == "UNMATCHED":
            unmatched += line["play_count"]
        elif line["match_status"] == "DISPUTED":
            disputed += line["play_count"]
    return total, matched, unmatched, disputed


def batch_unmatched_play_count(batch_id):
    return batch_play_totals(batch_id)[2]


# --------------------------------------------------------------------------
# RoyaltyPool aggregates
# --------------------------------------------------------------------------

def pool_matched_attributed_cents(pool):
    return sum(l["attributed_revenue_cents"] for l in in_scope_lines(pool)
               if l["match_status"] in MATCHED_SET)


def pool_holding_cents(pool):
    return sum(l["attributed_revenue_cents"] for l in in_scope_lines(pool)
               if l["match_status"] in HELD_SET)


def period_total_holding_cents(period_id):
    return sum(pool_holding_cents(p) for p in pools_of_period(period_id))


# --------------------------------------------------------------------------
# Work derived posture
# --------------------------------------------------------------------------

def work_rights_state(work):
    registrations = registrations_of_work(work["id"])
    if any(r["status"] == "DISPUTED" for r in registrations):
        return "DISPUTED"
    for reg in registrations:
        if reg["status"] != "APPROVED":
            continue
        if work["work_type"] == "RECORDING" and reg["right_type"] == "MASTER":
            return "REGISTERED"
        if work["work_type"] == "COMPOSITION" and reg["right_type"] in ("MECHANICAL", "PERFORMANCE"):
            return "REGISTERED"
    if any(r["status"] in ("SUBMITTED", "UNDER_REVIEW", "NEEDS_EVIDENCE")
           for r in registrations):
        return "PROVISIONAL"
    return "UNMATCHED"


def work_approved_master_share_bps(work):
    total = 0
    for reg in registrations_of_work(work["id"]):
        if reg["status"] == "APPROVED" and reg["right_type"] == "MASTER" \
                and "WORLD" in reg["territory_set"]:
            total += reg["share_bps"]
    return total


# --------------------------------------------------------------------------
# RoyaltyStatement aggregates
# --------------------------------------------------------------------------

def statement_totals(statement_id):
    gross = fee = net = 0
    count = 0
    for line in db.statement_lines.values():
        if line["statement_id"] != statement_id:
            continue
        gross += line["gross_cents"]
        fee += line["admin_fee_cents"]
        net += line["net_cents"]
        count += 1
    return gross, fee, net, count


# --------------------------------------------------------------------------
# RightsHolder aggregates
# --------------------------------------------------------------------------

def holder_receivable_balance_cents(holder_id):
    total = 0
    for line in db.statement_lines.values():
        if line["payee_holder_id"] != holder_id:
            continue
        statement = db.statements.get(line["statement_id"])
        if statement is not None and statement["status"] == "ISSUED":
            total += line["net_cents"]
    for engagement in db.engagements.values():
        if engagement["rights_holder_id"] == holder_id \
                and engagement["finding_status"] == "SETTLED":
            total += engagement["settled_amount_cents"] + engagement["interest_cents"]
    return total


def holder_issued_statement_count(holder_id):
    return len([s for s in db.statements.values()
                if s["rights_holder_id"] == holder_id and s["status"] == "ISSUED"])


# --------------------------------------------------------------------------
# AuditEngagement dimensions
# --------------------------------------------------------------------------

def production_status(engagement):
    produced = engagement["produced_line_count"]
    required = engagement["required_line_count"]
    if produced == 0:
        return "PENDING"
    if produced < required:
        return "PARTIAL"
    return "COMPLETE"
