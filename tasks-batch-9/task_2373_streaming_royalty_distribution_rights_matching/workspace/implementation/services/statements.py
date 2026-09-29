"""Statement assembly, administration fees, delta assembly (§3.7, §3.8)."""

from collections import OrderedDict

from constants import (
    ADMIN_TIER_1_BPS,
    ADMIN_TIER_1_CEILING_CENTS,
    ADMIN_TIER_2_BPS,
    ADMIN_TIER_2_CEILING_CENTS,
    ADMIN_TIER_3_BPS,
    MASTER_SHARE_OF_ATTRIBUTED_BPS,
    MATCHED_SET,
)
from db import by_created, db, stamp_new
from services import derive
from validation import round_half_up, territory_matches


# --------------------------------------------------------------------------
# slicing and participation
# --------------------------------------------------------------------------

def slice_line(attributed, schedule):
    master = round_half_up(attributed * MASTER_SHARE_OF_ATTRIBUTED_BPS, 10000)
    publishing = attributed - master
    mechanical = round_half_up(publishing * schedule["mechanical_share_bps"], 10000)
    performance = publishing - mechanical
    return {
        "MASTER": master,
        "MECHANICAL": mechanical,
        "PERFORMANCE": performance,
    }


def _participates(reg, line, usage_end, holder_id):
    if reg["status"] != "APPROVED":
        return False
    if not territory_matches(reg["territory_set"], line["territory_code"]):
        return False
    if holder_id is not None and reg["payee_holder_id"] != holder_id:
        return False
    if not (reg["effective_from"] <= usage_end < reg["effective_to"]):
        return False
    if reg["right_type"] == "MASTER":
        return reg["work_id"] == line["work_id"]
    recording = db.works.get(line["work_id"])
    if recording is None:
        return False
    linked = recording.get("linked_work_id")
    return linked is not None and reg["work_id"] == linked


def iter_contributions(pool, period, holder_id=None):
    """Yield (usage_line, registration, contribution_cents, slices) triples in
    the pinned walk order: usage lines by created_at, then registrations by
    created_at."""
    schedule = db.rate_schedules.get(pool["applied_rate_schedule_id"])
    if schedule is None:
        return
    usage_end = period["usage_end"]
    registrations = by_created(list(db.registrations.values()))
    for line in derive.in_scope_lines(pool):
        if line["match_status"] not in MATCHED_SET:
            continue
        slices = slice_line(line["attributed_revenue_cents"], schedule)
        for reg in registrations:
            if not _participates(reg, line, usage_end, holder_id):
                continue
            base = slices[reg["right_type"]]
            contribution = round_half_up(base * reg["share_bps"], 10000)
            yield line, reg, contribution


def pool_payee_gross_totals(pool, period):
    """Gross each holder would receive in non-residual lines from this pool."""
    totals = {}
    for line, reg, contribution in iter_contributions(pool, period):
        payee = reg["payee_holder_id"]
        totals[payee] = totals.get(payee, 0) + contribution
    return totals


# --------------------------------------------------------------------------
# admin_fee_resolution (§3.7)
# --------------------------------------------------------------------------

def admin_fee_rate_bps(routing, payee_holder, gross_cents):
    if routing == "COLLECTIVE":
        if gross_cents < ADMIN_TIER_1_CEILING_CENTS:
            return ADMIN_TIER_1_BPS
        if gross_cents < ADMIN_TIER_2_CEILING_CENTS:
            return ADMIN_TIER_2_BPS
        return ADMIN_TIER_3_BPS
    rate = None
    if payee_holder is not None:
        rate = payee_holder.get("direct_deal_rate_bps")
    return rate if rate is not None else 0


def resolve_admin_fee(routing, payee_holder, gross_cents):
    rate = admin_fee_rate_bps(routing, payee_holder, gross_cents)
    fee = round_half_up(gross_cents * rate, 10000)
    return fee


# --------------------------------------------------------------------------
# ordinary assembly
# --------------------------------------------------------------------------

def assemble_groups(period, holder_id):
    """Ordered map of group key -> resolved line payload for one payee."""
    holder = db.rights_holders.get(holder_id)
    groups = OrderedDict()
    for pool in derive.pools_of_period(period["id"]):
        if pool["status"] != "FINALIZED":
            continue
        for line, reg, contribution in iter_contributions(pool, period, holder_id):
            line_type = "HOLDING_RELEASE" if line["match_status"] == "CLAIM_MATCHED" else "USAGE"
            key = (
                pool["id"],
                reg["work_id"],
                reg["right_type"],
                line["territory_code"],
                line["subscription_tier"],
                reg["routing"],
                line_type,
            )
            group = groups.get(key)
            if group is None:
                group = {
                    "pool_id": pool["id"],
                    "work_id": reg["work_id"],
                    "right_type": reg["right_type"],
                    "routing": reg["routing"],
                    "territory_code": line["territory_code"],
                    "subscription_tier": line["subscription_tier"],
                    "line_type": line_type,
                    "share_bps": reg["share_bps"],
                    "play_count": 0,
                    "gross_cents": 0,
                }
                groups[key] = group
            group["gross_cents"] += contribution
            group["play_count"] += line["play_count"]

        if pool["residual_payee_holder_id"] == holder_id \
                and pool["rounding_residual_cents"] != 0:
            groups[(pool["id"], "RESIDUAL")] = {
                "pool_id": pool["id"],
                "work_id": None,
                "right_type": None,
                "routing": None,
                "territory_code": pool["territory_code"],
                "subscription_tier": pool["subscription_tier"],
                "line_type": "RESIDUAL",
                "share_bps": 10000,
                "play_count": 0,
                "gross_cents": pool["rounding_residual_cents"],
            }

    for group in groups.values():
        if group["line_type"] == "RESIDUAL":
            group["admin_fee_cents"] = 0
        else:
            group["admin_fee_cents"] = resolve_admin_fee(
                group["routing"], holder, group["gross_cents"])
        group["net_cents"] = group["gross_cents"] - group["admin_fee_cents"]
    return groups


def key_of_line(line):
    if line["line_type"] == "RESIDUAL":
        return (line["pool_id"], "RESIDUAL")
    return (
        line["pool_id"],
        line["work_id"],
        line["right_type"],
        line["territory_code"],
        line["subscription_tier"],
        line["routing"],
        line["line_type"],
    )


def _new_line(statement, payload, adjustment_of_line_id=None, line_type=None):
    record = {
        "statement_id": statement["id"],
        "pool_id": payload["pool_id"],
        "work_id": payload["work_id"],
        "adjustment_of_line_id": adjustment_of_line_id,
        "payee_holder_id": statement["rights_holder_id"],
        "line_type": line_type or payload["line_type"],
        "right_type": payload["right_type"],
        "routing": payload["routing"],
        "territory_code": payload["territory_code"],
        "subscription_tier": payload["subscription_tier"],
        "play_count": payload["play_count"],
        "share_bps": payload["share_bps"],
        "gross_cents": payload["gross_cents"],
        "admin_fee_cents": payload["admin_fee_cents"],
        "net_cents": payload["net_cents"],
    }
    stamp_new(record, versioned=False)
    db.statement_lines[record["id"]] = record
    return record


def superseded_predecessors(holder_id, period_id):
    rows = [s for s in db.statements.values()
            if s["rights_holder_id"] == holder_id
            and s["period_id"] == period_id
            and s["status"] == "SUPERSEDED"]
    return by_created(rows)


def build_lines(statement, period):
    """Materialise the statement's immutable lines (ordinary or delta)."""
    holder_id = statement["rights_holder_id"]
    groups = assemble_groups(period, holder_id)
    predecessors = superseded_predecessors(holder_id, period["id"])

    if not predecessors:
        return [_new_line(statement, payload) for payload in groups.values()]

    created = []
    for old_statement in predecessors:
        for old_line in derive.statement_lines_of(old_statement["id"]):
            if old_line["line_type"] not in ("USAGE", "HOLDING_RELEASE", "RESIDUAL"):
                continue
            new = groups.get(key_of_line(old_line))
            new_gross = new["gross_cents"] if new else 0
            new_fee = new["admin_fee_cents"] if new else 0
            gross_delta = new_gross - old_line["gross_cents"]
            fee_delta = new_fee - old_line["admin_fee_cents"]
            if gross_delta == 0 and fee_delta == 0:
                continue
            payload = {
                "pool_id": old_line["pool_id"],
                "work_id": old_line["work_id"],
                "right_type": old_line["right_type"],
                "routing": old_line["routing"],
                "territory_code": old_line["territory_code"],
                "subscription_tier": old_line["subscription_tier"],
                "share_bps": old_line["share_bps"],
                "play_count": 0,
                "gross_cents": gross_delta,
                "admin_fee_cents": fee_delta,
                "net_cents": gross_delta - fee_delta,
            }
            created.append(_new_line(statement, payload,
                                     adjustment_of_line_id=old_line["id"],
                                     line_type="ADJUSTMENT"))
    return created
