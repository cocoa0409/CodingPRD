"""The fifteen calculations of PRD section 3 / SCAFFOLD calculations."""

from decimal import Decimal

import store
from constants import (
    APPRAISAL_REQUIRED_THRESHOLD_CENTS,
    BILLING_PERIOD_DAYS,
    EVIDENCE_RANK,
    FAIR_DIVISION_TOLERANCE_PCT,
    MONTH_DAYS_FOR_AGE,
    PACKAGE_MIN_EVIDENCE_TIER_RANK,
    SCHEDULE_REQUIRED_THRESHOLD_CENTS,
    SELL_DISPOSITION_COST_PCT,
    SUBSCRIPTION_TIERS,
    VALUED_ITEM_STATES,
)
from money import D, round_half_up, round_half_up_2
from timeutil import clock, parse_instant, whole_days_between


# --------------------------------------------------------------------------
# 1. item_actual_cash_value  (decay curve, three as-of variants)
# --------------------------------------------------------------------------
def category_schedule_for(category):
    for row in store.all_of(store.category_schedules):
        if row["category"] == category:
            return row
    return None


def acv_exact(item, as_of):
    """The unrounded max(raw, salvage floor).  Returns a Decimal, or None when
    the ACV regime is unavailable for this item."""
    if item.get("purchase_price_cents") is None:
        return None
    sched = category_schedule_for(item["category"])
    if sched is None:
        return None
    acquired = parse_instant(item["acquired_at"])
    if acquired is None:
        return None
    elapsed_days = whole_days_between(acquired, as_of)
    age_months = elapsed_days // MONTH_DAYS_FOR_AGE
    if age_months < 0:
        age_months = 0
    price = D(item["purchase_price_cents"])
    depreciated_pct = (D(sched["annual_depreciation_pct"]) / D(12)) * D(age_months)
    if depreciated_pct > D(100):
        depreciated_pct = D(100)
    raw_cents = price * (D(1) - depreciated_pct / D(100))
    floor_cents = price * (D(sched["salvage_floor_pct"]) / D(100))
    return raw_cents if raw_cents > floor_cents else floor_cents


def acv_cents(item, as_of):
    exact = acv_exact(item, as_of)
    if exact is None:
        return 0
    return round_half_up(exact)


# --------------------------------------------------------------------------
# 2. item_evidence_tier  (threshold over the item's STORED assets)
# --------------------------------------------------------------------------
def stored_assets_of(item_id):
    return [a for a in store.all_of(store.assets) if a["item_id"] == item_id and a["status"] == "STORED"]


def evidence_tier_for(item):
    kinds = {a["asset_kind"] for a in stored_assets_of(item["id"])}
    photo = "PHOTO" in kinds
    serial = ("SERIAL_PLATE" in kinds) or (item.get("serial_number") is not None)
    document = ("RECEIPT" in kinds) or ("PROVENANCE_DOC" in kinds)
    if photo and serial and document:
        return "DOCUMENTED"
    if photo and serial:
        return "PHOTO_SERIAL"
    if photo:
        return "PHOTO_ONLY"
    return "NONE"


# --------------------------------------------------------------------------
# 3. effective_value_resolution  (strict precedence, first match wins)
# --------------------------------------------------------------------------
def live_certified_appraisals(item_id, now=None):
    now = now or clock.now
    out = []
    for a in store.all_of(store.appraisals):
        if a["item_id"] != item_id or a["status"] != "CERTIFIED":
            continue
        valid_until = a.get("_valid_until_at_dt")
        if valid_until is None or not (now < valid_until):
            continue
        out.append(a)
    return out


def resolve_effective_value(item):
    """Returns (effective_value_cents, effective_value_basis, valuation_state)."""
    candidates = live_certified_appraisals(item["id"])
    if candidates:
        winner = candidates[0]
        for cand in candidates[1:]:
            if cand["_certified_at_dt"] > winner["_certified_at_dt"]:
                winner = cand
        return (winner["appraised_value_cents"], "APPRAISAL", "CERTIFIED")

    basis = "NONE"
    value = 0
    exact = acv_exact(item, clock.now)
    if exact is not None:
        value = round_half_up(exact)
        basis = "ACV"
    elif item.get("declared_value_cents", 0) > 0:
        value = item["declared_value_cents"]
        basis = "DECLARED"

    if item.get("declared_value_cents", 0) >= APPRAISAL_REQUIRED_THRESHOLD_CENTS:
        state = "APPRAISAL_REQUIRED"
    elif basis in ("ACV", "DECLARED"):
        state = "DECLARED_ONLY"
    else:
        state = "UNVALUED"
    return (value, basis, state)


# --------------------------------------------------------------------------
# 4. policy_coverage_gap  (two waterfall variants)
# --------------------------------------------------------------------------
def gap_candidates(household_id):
    rows = [
        i
        for i in store.all_of(store.items)
        if i["household_id"] == household_id
        and i["lifecycle_state"] in VALUED_ITEM_STATES
        and i["evidence_tier"] != "NONE"
    ]
    return rows


def _sublimit_pools():
    pools = {}
    for sched in store.all_of(store.category_schedules):
        pools[sched["category"]] = sched["blanket_sublimit_cents"]
    return pools


def coverage_waterfall(policy, candidates, basis="SCHEDULED_FIRST"):
    """Returns a dict item_id -> covered cents.  Every input is already whole
    cents so nothing is rounded anywhere in the waterfall."""
    covered = {i["id"]: 0 for i in candidates}
    residual = {}
    ev = {i["id"]: i["effective_value_cents"] for i in candidates}

    if basis == "SCHEDULED_FIRST":
        allowance_left = policy["scheduled_allowance_cents"]
        for i in candidates:
            if i["coverage_mode"] == "SCHEDULED" and i.get("scheduled_policy_id") == policy["id"]:
                take = min(i["scheduled_value_cents"], ev[i["id"]], allowance_left)
                covered[i["id"]] = take
                allowance_left -= take
            else:
                covered[i["id"]] = 0
            residual[i["id"]] = ev[i["id"]] - covered[i["id"]]
        sub_left = _sublimit_pools()
        for i in candidates:
            pool = sub_left.get(i["category"], 0)
            take2 = min(residual[i["id"]], pool)
            if take2 < 0:
                take2 = 0
            covered[i["id"]] += take2
            sub_left[i["category"]] = pool - take2
    else:  # BLANKET_FIRST
        sub_left = _sublimit_pools()
        for i in candidates:
            pool = sub_left.get(i["category"], 0)
            take = min(ev[i["id"]], pool)
            if take < 0:
                take = 0
            covered[i["id"]] = take
            sub_left[i["category"]] = pool - take
            residual[i["id"]] = ev[i["id"]] - covered[i["id"]]
        allowance_left = policy["scheduled_allowance_cents"]
        for i in candidates:
            if i["coverage_mode"] == "SCHEDULED" and i.get("scheduled_policy_id") == policy["id"]:
                take2 = min(residual[i["id"]], i["scheduled_value_cents"], allowance_left)
                if take2 < 0:
                    take2 = 0
                covered[i["id"]] += take2
                allowance_left -= take2
    return covered


def coverage_gap_report(policy, basis="SCHEDULED_FIRST", candidates=None):
    if candidates is None:
        candidates = gap_candidates(policy["household_id"])
    covered = coverage_waterfall(policy, candidates, basis)
    total_value = sum(i["effective_value_cents"] for i in candidates)
    total_covered = sum(covered[i["id"]] for i in candidates)
    required = sum(
        1
        for i in candidates
        if i["effective_value_cents"] >= SCHEDULE_REQUIRED_THRESHOLD_CENTS
        and i["coverage_mode"] == "BLANKET"
    )
    return {
        "policy_id": policy["id"],
        "basis": basis,
        "total_value_cents": total_value,
        "total_covered_cents": total_covered,
        "coverage_gap_cents": total_value - total_covered,
        "item_count": len(candidates),
        "schedule_required_unscheduled_count": required,
    }


def policy_total_effective_value(policy):
    """PRD 3.5: the policy figure adds the evidence condition the household
    figure does not have."""
    total = 0
    for i in store.all_of(store.items):
        if (
            i["household_id"] == policy["household_id"]
            and i["lifecycle_state"] in VALUED_ITEM_STATES
            and i["evidence_tier"] != "NONE"
        ):
            total += i["effective_value_cents"]
    return total


# --------------------------------------------------------------------------
# 5. package_totals_snapshot
# --------------------------------------------------------------------------
def package_eligible_items(household_id):
    return [
        i
        for i in store.all_of(store.items)
        if i["household_id"] == household_id
        and i["lifecycle_state"] in VALUED_ITEM_STATES
        and EVIDENCE_RANK[i["evidence_tier"]] >= PACKAGE_MIN_EVIDENCE_TIER_RANK
        and i["valuation_state"] != "APPRAISAL_REQUIRED"
    ]


def snapshot_exact_value(item, generated_at):
    """The item's exact, unrounded effective value at as_of = generated_at.
    ACV-basis items keep the pre-rounding max(raw, salvage floor); appraisal and
    declared bases are already whole cents."""
    if item["effective_value_basis"] == "ACV":
        exact = acv_exact(item, generated_at)
        if exact is not None:
            return exact
    return D(item["effective_value_cents"])


# --------------------------------------------------------------------------
# 6. claim_settlement_allocation
# --------------------------------------------------------------------------
def claim_gross_value(claim, line, item):
    quantity = item["quantity"] or 1
    if claim["settlement_basis"] == "ACV":
        loss_dt = parse_instant(claim["loss_date"])
        exact = acv_exact(item, loss_dt) if loss_dt is not None else None
        base = exact if exact is not None else Decimal(0)
    else:
        base = D(item.get("replacement_cost_cents") or 0)
    unit = base / D(quantity)
    return round_half_up(unit * D(line["claimed_quantity"]))


def apply_capping(claim, lines, items_by_id):
    sub_left = _sublimit_pools()
    for line in lines:
        item = items_by_id[line["item_id"]]
        if item["coverage_mode"] == "SCHEDULED" and item.get("scheduled_policy_id") == claim["policy_id"]:
            cap = item["scheduled_value_cents"]
        else:
            cap = sub_left.get(item["category"], 0)
            sub_left[item["category"]] = cap - min(line["gross_value_cents"], cap)
        line["capped_value_cents"] = min(line["gross_value_cents"], cap)


def allocate_deductible(claim, policy, scope_lines):
    """Step 3 of the pinned evaluation order, over the lines in scope."""
    deductible = policy["deductible_cents"] if policy else 0
    base = sum(l["capped_value_cents"] for l in scope_lines)
    if base == 0:
        for line in scope_lines:
            line["deductible_share_cents"] = 0
        return
    if claim["deductible_mode"] == "PRO_RATA":
        anchor = None
        for line in scope_lines:
            if anchor is None or line["capped_value_cents"] > anchor["capped_value_cents"]:
                anchor = line
        others_total = 0
        for line in scope_lines:
            if line is anchor:
                continue
            share = round_half_up(D(deductible) * D(line["capped_value_cents"]) / D(base))
            line["deductible_share_cents"] = share
            others_total += share
        anchor["deductible_share_cents"] = min(deductible, base) - others_total
    else:  # HIGHEST_VALUE_FIRST
        remaining = deductible
        ordered_lines = sorted(
            scope_lines,
            key=lambda l: (-l["capped_value_cents"], l["_created_dt"], l["_seq"]),
        )
        for line in ordered_lines:
            share = min(remaining, line["capped_value_cents"])
            line["deductible_share_cents"] = share
            remaining -= share


def finish_net(scope_lines):
    for line in scope_lines:
        net = line["capped_value_cents"] - line["deductible_share_cents"]
        line["net_settlement_cents"] = net if net > 0 else 0


# --------------------------------------------------------------------------
# 7. estate_fair_division_balance
# --------------------------------------------------------------------------
def allocation_value(item, quantity):
    return round_half_up(D(item["effective_value_cents"]) * D(quantity) / D(item["quantity"] or 1))


def fair_division(plan, plan_allocations, valuation_mode):
    """Returns (heir_count, balance_spread_pct, balanced)."""
    heir_ids = []
    for a in plan_allocations:
        hid = a.get("heir_member_id")
        if hid is not None and hid not in heir_ids:
            heir_ids.append(hid)
    # ordered by the heir member's created_at ascending, creation-order tie-break
    def heir_sort_key(hid):
        member = store.members.get(hid)
        if member is None:
            return (clock.now, 0)
        return store.order_key(member)

    heir_ids.sort(key=heir_sort_key)
    n = len(heir_ids)
    if n == 0:
        return (0, 0.0, True)

    keep_value = {hid: 0 for hid in heir_ids}
    sell_pool = 0
    for a in plan_allocations:
        if a["disposition"] == "KEEP" and a.get("heir_member_id") in keep_value:
            keep_value[a["heir_member_id"]] += a["allocated_value_cents"]
        elif a["disposition"] == "SELL":
            sell_pool += a["allocated_value_cents"]

    if valuation_mode == "GROSS":
        distributable = sell_pool
    else:
        distributable = round_half_up(D(sell_pool) * (D(1) - D(SELL_DISPOSITION_COST_PCT) / D(100)))

    share = distributable // n
    remainder = distributable - share * n
    totals = []
    for idx, hid in enumerate(heir_ids):
        heir_share = share + 1 if idx < remainder else share
        totals.append(keep_value[hid] + heir_share)

    mean = D(sum(totals)) / D(n)
    if mean == 0:
        spread = 0.0
    else:
        spread = round_half_up_2((D(max(totals)) - D(min(totals))) / mean * D(100))
    balanced = spread <= FAIR_DIVISION_TOLERANCE_PCT
    return (n, spread, balanced)


# --------------------------------------------------------------------------
# 8. subscription_proration
# --------------------------------------------------------------------------
def proration(sub, new_tier, mode):
    old_fee = SUBSCRIPTION_TIERS[sub["tier"]]["monthly_fee_cents"]
    new_fee = SUBSCRIPTION_TIERS[new_tier]["monthly_fee_cents"]
    period_start = sub.get("_period_start_at_dt")
    if period_start is None:
        elapsed_days = 0
    else:
        elapsed_days = whole_days_between(period_start, clock.now)
    if elapsed_days < 0:
        elapsed_days = 0
    if elapsed_days > BILLING_PERIOD_DAYS:
        elapsed_days = BILLING_PERIOD_DAYS
    remaining_days = BILLING_PERIOD_DAYS - elapsed_days
    if mode == "WHOLE_PERIOD":
        return new_fee - old_fee
    credit = round_half_up(D(old_fee) * D(remaining_days) / D(BILLING_PERIOD_DAYS))
    charge = round_half_up(D(new_fee) * D(remaining_days) / D(BILLING_PERIOD_DAYS))
    return charge - credit


# --------------------------------------------------------------------------
# 9. vault_quota_usage
# --------------------------------------------------------------------------
def quota_usage(household_id):
    item_usage = 0
    for i in store.items.values():
        if i["household_id"] == household_id and i["lifecycle_state"] in ("DRAFT", "CATALOGED", "FROZEN"):
            item_usage += 1
    asset_usage = 0
    bytes_usage = 0
    for a in store.assets.values():
        if a["status"] != "STORED":
            continue
        item = store.items.get(a["item_id"])
        if item is not None and item["household_id"] == household_id:
            asset_usage += 1
            bytes_usage += a["byte_size"]
    return item_usage, asset_usage, bytes_usage
