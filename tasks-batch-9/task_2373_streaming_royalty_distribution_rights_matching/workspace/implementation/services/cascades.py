"""Bubble-ups and the three multi-link cascades (§3.3, §3.5, §3.6, §3.8)."""

from db import by_created, db, parse_date, touch
from services import derive, matching


# --------------------------------------------------------------------------
# bubble-ups
# --------------------------------------------------------------------------

def period_bubble_usage_sealed(period):
    """OPEN -> USAGE_SEALED when every batch of the period has finished
    matching (§3.3)."""
    if period is None or period["status"] != "OPEN":
        return False
    batches = derive.batches_of_period(period["id"])
    if not batches:
        return False
    if all(b["status"] in ("MATCHED", "PARTIALLY_MATCHED") for b in batches):
        period["status"] = "USAGE_SEALED"
        touch(period)
        return True
    return False


def period_bubble_distributed(period):
    """USAGE_SEALED/REOPENED -> DISTRIBUTED when every pool is FINALIZED
    (§3.6)."""
    if period is None or period["status"] not in ("USAGE_SEALED", "REOPENED"):
        return False
    pools = derive.pools_of_period(period["id"])
    if not pools:
        return False
    if not all(p["status"] == "FINALIZED" for p in pools):
        return False
    from_usage_sealed = period["status"] == "USAGE_SEALED"
    period["status"] = "DISTRIBUTED"
    touch(period)
    if from_usage_sealed:
        for batch in derive.batches_of_period(period["id"]):
            if batch["status"] in ("MATCHED", "PARTIALLY_MATCHED"):
                batch["status"] = "RECONCILED"
                touch(batch)
    return True


def reconcile_batches_for_lines(lines):
    """Recompute batch aggregates for the batches owning these lines and
    promote PARTIALLY_MATCHED -> MATCHED where nothing is unmatched."""
    batch_ids = []
    for line in lines:
        if line["batch_id"] not in batch_ids:
            batch_ids.append(line["batch_id"])
    periods = []
    for batch_id in batch_ids:
        batch = db.batches.get(batch_id)
        if batch is None:
            continue
        if batch["status"] == "PARTIALLY_MATCHED" \
                and derive.batch_unmatched_play_count(batch_id) == 0:
            batch["status"] = "MATCHED"
        touch(batch)
        period = db.periods.get(batch["period_id"])
        if period is not None and period not in periods:
            periods.append(period)
    return periods


def reconcile_pools_for_lines(lines):
    """A pool whose classification of value changed is re-versioned; the
    frozen distributable and residual amounts are never touched, which keeps
    the conservation identity of §2.9 intact."""
    seen = []
    for line in lines:
        pool = derive.pool_for_line(line)
        if pool is None:
            continue
        if pool["id"] in seen:
            continue
        seen.append(pool["id"])
        touch(pool)
    return seen


# --------------------------------------------------------------------------
# approval cascade (§3.5)
# --------------------------------------------------------------------------

def approval_cascade(work):
    """Links two and three of the approval cascade."""
    attached = matching.run_claim_match(work)
    if not attached:
        return attached
    periods = reconcile_batches_for_lines(attached)
    reconcile_pools_for_lines(attached)
    for period in periods:
        period_bubble_usage_sealed(period)
    return attached


# --------------------------------------------------------------------------
# compensating dispute cascade (§3.5)
# --------------------------------------------------------------------------

def dispute_cascade(registration):
    work_id = registration["work_id"]
    affected = []
    for line in by_created(list(db.usage_lines.values())):
        if line["match_status"] != "CLAIM_MATCHED":
            continue
        if line["work_id"] != work_id:
            continue
        line["match_status"] = "DISPUTED"
        touch(line)
        affected.append(line)

    if affected:
        for line in affected:
            batch = db.batches.get(line["batch_id"])
            if batch is not None:
                touch(batch)
        reconcile_pools_for_lines(affected)

    # Issued statements that released holding money for this work are voided.
    for statement in by_created(list(db.statements.values())):
        if statement["status"] != "ISSUED":
            continue
        lines = derive.statement_lines_of(statement["id"])
        if not any(l["line_type"] == "HOLDING_RELEASE" and l["work_id"] == work_id
                   for l in lines):
            continue
        statement["status"] = "SUPERSEDED"
        touch(statement)
        holder = db.rights_holders.get(statement["rights_holder_id"])
        if holder is not None:
            touch(holder)
    return affected


# --------------------------------------------------------------------------
# rate promulgation cascade (§3.8)
# --------------------------------------------------------------------------

def promulgation_cascade(schedule, supersede_incumbent):
    """Links two, three and four; link one is applied by the caller."""
    if supersede_incumbent:
        for other in by_created(list(db.rate_schedules.values())):
            if other["id"] == schedule["id"]:
                continue
            if other["status"] != "EFFECTIVE":
                continue
            if other["territory_code"] != schedule["territory_code"]:
                continue
            if other["subscription_tier"] != schedule["subscription_tier"]:
                continue
            if not _closed_windows_overlap(other, schedule):
                continue
            other["status"] = "SUPERSEDED"
            touch(other)

    if not schedule["retroactive"]:
        return []

    reopened_pools = []
    for pool in by_created(list(db.pools.values())):
        if pool["status"] != "FINALIZED":
            continue
        if pool["subscription_tier"] != schedule["subscription_tier"]:
            continue
        if schedule["territory_code"] != "WORLD" \
                and pool["territory_code"] != schedule["territory_code"]:
            continue
        period = db.periods.get(pool["period_id"])
        if period is None:
            continue
        usage_end = parse_date(period["usage_end"])
        eff_from = parse_date(schedule["effective_from"])
        eff_to = parse_date(schedule["effective_to"])
        if usage_end is None or eff_from is None or eff_to is None:
            continue
        if not (eff_from <= usage_end <= eff_to):
            continue
        pool["status"] = "REOPENED_FOR_ADJUSTMENT"
        touch(pool)
        reopened_pools.append(pool)

    if not reopened_pools:
        return reopened_pools

    reopened_ids = set(p["id"] for p in reopened_pools)

    for statement in by_created(list(db.statements.values())):
        if statement["status"] != "ISSUED":
            continue
        lines = derive.statement_lines_of(statement["id"])
        if not any(l["pool_id"] in reopened_ids for l in lines):
            continue
        statement["status"] = "SUPERSEDED"
        touch(statement)
        holder = db.rights_holders.get(statement["rights_holder_id"])
        if holder is not None:
            touch(holder)

    for period_id in _ordered_unique(p["period_id"] for p in reopened_pools):
        period = db.periods.get(period_id)
        if period is None:
            continue
        if period["status"] in ("DISTRIBUTED", "CLOSED"):
            period["status"] = "REOPENED"
            touch(period)
    return reopened_pools


def _closed_windows_overlap(left, right):
    left_from = parse_date(left["effective_from"])
    left_to = parse_date(left["effective_to"])
    right_from = parse_date(right["effective_from"])
    right_to = parse_date(right["effective_to"])
    if None in (left_from, left_to, right_from, right_to):
        return False
    return left_from <= right_to and right_from <= left_to


def _ordered_unique(values):
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen
