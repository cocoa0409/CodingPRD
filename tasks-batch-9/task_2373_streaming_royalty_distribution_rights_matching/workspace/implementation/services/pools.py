"""Pool sizing, rate-schedule selection and attribution (§3.6)."""

from constants import MATCHED_SET, MAX_POOL_CAP_MULTIPLE
from db import db, now, parse_date, parse_dt, touch
from services import derive
from validation import ceil_div, floor_div, round_half_up


# --------------------------------------------------------------------------
# rate_schedule_selection
# --------------------------------------------------------------------------

def select_rate_schedule(pool, period):
    """Returns the governing EFFECTIVE schedule or None (§3.6)."""
    usage_end = parse_date(period["usage_end"])
    candidates = []
    for sched in db.rate_schedules.values():
        if sched["status"] != "EFFECTIVE":
            continue
        if sched["subscription_tier"] != pool["subscription_tier"]:
            continue
        if sched["territory_code"] != pool["territory_code"] \
                and sched["territory_code"] != "WORLD":
            continue
        eff_from = parse_date(sched["effective_from"])
        eff_to = parse_date(sched["effective_to"])
        if eff_from is None or eff_to is None or usage_end is None:
            continue
        if eff_from <= usage_end <= eff_to:
            candidates.append(sched)
    if not candidates:
        return None

    def rank(sched):
        specificity = 0 if sched["territory_code"] == pool["territory_code"] else 1
        return (
            specificity,
            _descending_date_key(sched["effective_from"]),
            sched["created_at"],
            sched["proceeding_ref"],
            sched["_seq"],
        )

    candidates.sort(key=rank)
    return candidates[0]


def _descending_date_key(date_str):
    """Sort key giving later dates a smaller value."""
    dt = parse_date(date_str)
    if dt is None:
        return 0
    return -int(dt.timestamp())


# --------------------------------------------------------------------------
# pool_distributable_amount
# --------------------------------------------------------------------------

def size_pool(pool, schedule, total_play_count):
    revenue_share = round_half_up(
        pool["gross_revenue_cents"] * schedule["revenue_share_bps"], 10000)
    minimum = pool["subscriber_count"] * schedule["per_subscriber_minimum_cents"]
    statutory_floor = ceil_div(
        total_play_count * schedule["statutory_floor_per_play_millicents"], 1000)

    capped_revenue_share = min(revenue_share, MAX_POOL_CAP_MULTIPLE * minimum)
    distributable = max(capped_revenue_share, minimum, statutory_floor)

    if revenue_share >= minimum and revenue_share >= statutory_floor \
            and revenue_share <= MAX_POOL_CAP_MULTIPLE * minimum:
        basis = "REVENUE_SHARE"
    elif minimum >= statutory_floor:
        basis = "PER_SUBSCRIBER_MINIMUM"
    else:
        basis = "STATUTORY_FLOOR"

    return {
        "revenue_share_pool_cents": revenue_share,
        "minimum_pool_cents": minimum,
        "statutory_floor_cents": statutory_floor,
        "distributable_cents": distributable,
        "allocation_basis": basis,
    }


# --------------------------------------------------------------------------
# pool_attribution
# --------------------------------------------------------------------------

def select_denominator(pool, period, in_scope, total_play_count):
    closes = parse_dt(period["claim_window_closes_at"])
    current = now()
    if closes is not None and current <= closes:
        return "ALL_USAGE", total_play_count
    matched = sum(l["play_count"] for l in in_scope
                  if l["match_status"] in MATCHED_SET)
    return "MATCHED_ONLY", matched


def attribute(pool, in_scope, distributable, basis, denominator):
    for line in in_scope:
        if denominator == 0:
            amount = 0
        elif basis == "MATCHED_ONLY" and line["match_status"] not in MATCHED_SET:
            amount = 0
        else:
            amount = floor_div(distributable * line["play_count"], denominator)
        if line["attributed_revenue_cents"] != amount:
            line["attributed_revenue_cents"] = amount
            touch(line)
    return sum(l["attributed_revenue_cents"] for l in in_scope)


def calculate_pool(pool, period, schedule):
    """Size the pool, attribute it, and leave it at status CALCULATED."""
    in_scope = derive.in_scope_lines(pool)
    total_play_count = sum(l["play_count"] for l in in_scope)

    sized = size_pool(pool, schedule, total_play_count)
    basis, denominator = select_denominator(pool, period, in_scope, total_play_count)
    attributed_total = attribute(
        pool, in_scope, sized["distributable_cents"], basis, denominator)

    pool["applied_rate_schedule_id"] = schedule["id"]
    pool["total_play_count"] = total_play_count
    pool["revenue_share_pool_cents"] = sized["revenue_share_pool_cents"]
    pool["minimum_pool_cents"] = sized["minimum_pool_cents"]
    pool["statutory_floor_cents"] = sized["statutory_floor_cents"]
    pool["distributable_cents"] = sized["distributable_cents"]
    pool["allocation_basis"] = sized["allocation_basis"]
    pool["denominator_basis"] = basis
    pool["denominator_play_count"] = denominator
    pool["rounding_residual_cents"] = sized["distributable_cents"] - attributed_total
    pool["status"] = "CALCULATED"
    touch(pool)
    return pool


# --------------------------------------------------------------------------
# residual_payee_selection (§3.6)
# --------------------------------------------------------------------------

def select_residual_payee(pool, period):
    from services import statements

    totals = statements.pool_payee_gross_totals(pool, period)
    best = None
    for holder_id, gross in totals.items():
        holder = db.rights_holders.get(holder_id)
        if holder is None:
            continue
        key = (-gross, holder["created_at"], holder["legal_name"], holder["_seq"])
        if best is None or key < best[0]:
            best = (key, holder_id)
    return best[1] if best else None
