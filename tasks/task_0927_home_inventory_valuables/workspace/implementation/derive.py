"""Derived counters, the two posture hooks of PRD 2.7 and the shared cascades.

Every recompute takes an explicit ``bump`` flag so the version-bump ledger of
PRD 2.9 can be honoured operation by operation: a derived counter that moves is
written either way, but the owning row's ``version`` moves only where the ledger
names it.
"""

import calc
import store
from constants import (
    APPRAISAL_VALIDITY_DAYS,
    COUNTED_ITEM_STATES,
    FREEZING_CLAIM_STATES,
    LIVE_PLAN_STATES,
    REFRESH_DUE_BAND_DAYS,
    REFRESH_GRACE_DAYS,
    VALUED_ITEM_STATES,
)
from timeutil import add_days, clock, render_server


def stamp(row, field, dt):
    """Write a server-derived instant: rendered with three fractional digits
    (PRD 2.5 rules 1 and 2) plus the datetime kept alongside for comparisons."""
    row[field] = render_server(dt) if dt is not None else None
    row["_" + field + "_dt"] = dt


def keep_raw(row, field, raw):
    """Write a caller-supplied instant: echoed byte for byte (PRD 2.5 rule 3),
    with the parsed value kept alongside for semantic comparison (rule 5)."""
    from timeutil import parse_instant

    row[field] = raw
    row["_" + field + "_dt"] = parse_instant(raw) if raw is not None else None


# ---------------------------------------------------------------- lookups
def subscription_of(household_id):
    for sub in store.all_of(store.subscriptions):
        if sub["household_id"] == household_id:
            return sub
    return None


def household_items(household_id):
    return [i for i in store.all_of(store.items) if i["household_id"] == household_id]


def household_policies(household_id):
    return [p for p in store.all_of(store.policies) if p["household_id"] == household_id]


# ---------------------------------------------------- subscription refresh axis
def refresh_band(sub):
    due = sub.get("_refresh_due_at_dt")
    if due is None:
        return sub["refresh_state"]
    now = clock.now
    if now < due:
        return "CURRENT"
    if now < add_days(due, REFRESH_DUE_BAND_DAYS):
        return "DUE"
    if now < add_days(due, REFRESH_GRACE_DAYS):
        return "GRACE"
    return "OVERDUE"


def recompute_refresh_state(sub, bump=True):
    band = refresh_band(sub)
    if band == sub["refresh_state"]:
        return False
    sub["refresh_state"] = band
    if bump:
        store.touch(sub)
    return True


def write_gate_for(household):
    sub = subscription_of(household["id"])
    if sub is None:
        return "OPEN"
    if sub["status"] in ("LAPSED", "CLOSED"):
        return "READ_ONLY"
    if sub["refresh_state"] == "OVERDUE":
        return "RESTRICTED"
    return "OPEN"


def recompute_write_gate(household, bump=True):
    gate = write_gate_for(household)
    if gate == household["write_gate_state"]:
        return False
    household["write_gate_state"] = gate
    if bump:
        store.touch(household)
    return True


def hook_h2(household_ids):
    """PRD 2.7 hook H2: first step of any /vault request, before ladder rung 1.
    Read-modify-write; bumps the rows whose value actually changed."""
    for hid in household_ids:
        household = store.households.get(hid)
        if household is None:
            continue
        sub = subscription_of(hid)
        if sub is not None:
            recompute_refresh_state(sub, bump=True)
        recompute_write_gate(household, bump=True)


# --------------------------------------------------------- derived roll-ups
def recompute_household(household, bump=True):
    hid = household["id"]
    item_count = 0
    frozen_count = 0
    total_effective = 0
    for i in store.items.values():
        if i["household_id"] != hid:
            continue
        if i["lifecycle_state"] in COUNTED_ITEM_STATES:
            item_count += 1
        if i["lifecycle_state"] == "FROZEN":
            frozen_count += 1
        if i["lifecycle_state"] in VALUED_ITEM_STATES:
            total_effective += i["effective_value_cents"]
    asset_count = 0
    bytes_used = 0
    for a in store.assets.values():
        if a["status"] != "STORED":
            continue
        item = store.items.get(a["item_id"])
        if item is not None and item["household_id"] == hid:
            asset_count += 1
            bytes_used += a["byte_size"]
    active_shares = sum(
        1 for g in store.share_grants.values() if g["household_id"] == hid and g["status"] == "ACTIVE"
    )
    updates = {
        "item_count": item_count,
        "asset_count": asset_count,
        "asset_bytes_used": bytes_used,
        "frozen_item_count": frozen_count,
        "records_freeze_active": frozen_count > 0,
        "active_share_count": active_shares,
        "total_effective_value_cents": total_effective,
    }
    changed = any(household.get(k) != v for k, v in updates.items())
    if changed:
        household.update(updates)
        if bump:
            store.touch(household)
    # The live plan's conservation counter follows the catalogued item set.
    plan = live_plan_of(hid)
    if plan is not None:
        recompute_plan(plan, bump=False)
    return changed


def recompute_room(room, bump=False):
    count = sum(
        1
        for i in store.items.values()
        if i["room_id"] == room["id"] and i["lifecycle_state"] in COUNTED_ITEM_STATES
    )
    if room["item_count"] == count:
        return False
    room["item_count"] = count
    if bump:
        store.touch(room)
    return True


def recompute_rooms_for(household_id, bump=False):
    for room in store.all_of(store.rooms):
        if room["household_id"] == household_id:
            recompute_room(room, bump=bump)


def recompute_policy(policy, bump=False):
    remaining = policy["scheduled_allowance_cents"] - policy["scheduled_consumed_cents"]
    total_effective = calc.policy_total_effective_value(policy)
    gap = calc.coverage_gap_report(policy, "SCHEDULED_FIRST")["coverage_gap_cents"]
    updates = {
        "scheduled_remaining_cents": remaining,
        "total_effective_value_cents": total_effective,
        "coverage_gap_cents": gap,
    }
    changed = any(policy.get(k) != v for k, v in updates.items())
    if changed:
        policy.update(updates)
        if bump:
            store.touch(policy)
    return changed


def recompute_policies_for(household_id, bump=False):
    for policy in household_policies(household_id):
        recompute_policy(policy, bump=bump)


def recompute_claim_counts(claim, bump=False):
    lines = [l for l in store.claim_lines.values() if l["claim_id"] == claim["id"]]
    updates = {
        "line_count": len(lines),
        "approved_line_count": sum(1 for l in lines if l["status"] == "APPROVED"),
        "denied_line_count": sum(1 for l in lines if l["status"] == "DENIED"),
        "blocked_line_count": sum(1 for l in lines if l["settlement_hold"]),
    }
    changed = any(claim.get(k) != v for k, v in updates.items())
    if changed:
        claim.update(updates)
        if bump:
            store.touch(claim)
    return changed


def plan_allocations(plan_id):
    return [a for a in store.all_of(store.allocations) if a["estate_plan_id"] == plan_id]


def item_allocated_quantity(item_id):
    total = 0
    for a in store.allocations.values():
        if a["item_id"] != item_id:
            continue
        plan = store.estate_plans.get(a["estate_plan_id"])
        if plan is not None and plan["status"] in LIVE_PLAN_STATES:
            total += a["quantity"]
    return total


def recompute_item_allocation(item, bump=False):
    value = item_allocated_quantity(item["id"])
    if item["allocated_quantity"] == value:
        return False
    item["allocated_quantity"] = value
    if bump:
        store.touch(item)
    return True


def recompute_plan(plan, bump=False):
    count = 0
    for i in store.items.values():
        if i["household_id"] != plan["household_id"] or i["lifecycle_state"] != "CATALOGED":
            continue
        allocated = 0
        for a in store.allocations.values():
            if a["item_id"] == i["id"] and a["estate_plan_id"] == plan["id"]:
                allocated += a["quantity"]
        if allocated < i["quantity"]:
            count += 1
    if plan["unallocated_item_count"] == count:
        return False
    plan["unallocated_item_count"] = count
    if bump:
        store.touch(plan)
    return True


def live_plan_of(household_id):
    for plan in store.all_of(store.estate_plans):
        if plan["household_id"] == household_id and plan["status"] in LIVE_PLAN_STATES:
            return plan
    return None


# --------------------------------------------------- item valuation refresh
def refresh_item(item, bump=False):
    """Re-runs the valuation resolution in place.  PRD 2.9: recomputing a
    derived valuation does not bump a version unless a named transition says so.
    """
    before_basis = item["effective_value_basis"]
    item["acv_value_cents"] = calc.acv_cents(item, clock.now)
    value, basis, state = calc.resolve_effective_value(item)
    changed = (
        item["effective_value_cents"] != value
        or item["effective_value_basis"] != basis
        or item["valuation_state"] != state
    )
    item["effective_value_cents"] = value
    item["effective_value_basis"] = basis
    item["valuation_state"] = state
    if before_basis == "APPRAISAL" and basis != "APPRAISAL":
        mark_basis_downgraded(item)
    refresh_stale_flags(item)
    if changed and bump:
        store.touch(item)
    return changed


def mark_basis_downgraded(item):
    """PRD 3.7: a line records whether the ground beneath it moved."""
    for line in store.claim_lines.values():
        if line["item_id"] != item["id"]:
            continue
        if line.get("_basis_at_create") == "APPRAISAL" and not line["basis_downgraded"]:
            line["basis_downgraded"] = True


def refresh_stale_flags(item, force=False, bump=False):
    """PRD 3.6: a package line goes stale when the item behind it no longer
    matches the frozen snapshot."""
    touched_packages = set()
    for line in store.package_lines.values():
        if line["item_id"] != item["id"]:
            continue
        diverged = force or (
            line["snapshot_effective_value_basis"] != item["effective_value_basis"]
            or line["snapshot_effective_value_cents"] != item["effective_value_cents"]
        )
        if diverged and not line["stale"]:
            line["stale"] = True
            touched_packages.add(line["package_id"])
        elif not diverged and line["stale"] and not force:
            line["stale"] = False
            touched_packages.add(line["package_id"])
    for pid in touched_packages:
        package = store.packages.get(pid)
        if package is None:
            continue
        count = sum(1 for l in store.package_lines.values() if l["package_id"] == pid and l["stale"])
        if package["stale_line_count"] != count:
            package["stale_line_count"] = count
            if bump:
                store.touch(package)


def maybe_catalog(item):
    """PRD 3.3: the automatic DRAFT -> CATALOGED gate, evaluated at the end of
    every asset upload and every value declaration."""
    if item["lifecycle_state"] != "DRAFT":
        return False
    if item["evidence_tier"] != "NONE" and item["declared_value_cents"] > 0:
        item["lifecycle_state"] = "CATALOGED"
        return True
    return False


# ------------------------------------------------------------- share grants
def void_grants(grants, reason):
    """ACTIVE -> VOIDED_BY_SCOPE for each grant, with its reason."""
    voided = []
    for grant in grants:
        if grant["status"] != "ACTIVE":
            continue
        grant["status"] = "VOIDED_BY_SCOPE"
        grant["voided_reason"] = reason
        store.touch(grant)
        voided.append(grant)
    return voided


def grants_scoped_to_package(package_id):
    return [g for g in store.all_of(store.share_grants) if g.get("scope_package_id") == package_id]


def grants_scoped_to_claim(claim_id):
    return [g for g in store.all_of(store.share_grants) if g.get("scope_claim_id") == claim_id]


# --------------------------------------------------------------- packages
def expire_package(package, bump=True):
    """PRD 3.6: however a package expires, two consequences follow."""
    package["status"] = "EXPIRED"
    if bump:
        store.touch(package)
    held_lines = []
    for claim in store.all_of(store.claims):
        if claim["package_id"] != package["id"]:
            continue
        changed_any = False
        for line in store.all_of(store.claim_lines):
            if line["claim_id"] != claim["id"] or line["status"] != "PENDING":
                continue
            if not line["settlement_hold"]:
                line["settlement_hold"] = True
                store.touch(line)
                held_lines.append(line)
                changed_any = True
        if changed_any:
            recompute_claim_counts(claim, bump=False)
    void_grants(grants_scoped_to_package(package["id"]), "SCOPE_SUPERSEDED")
    return held_lines


# --------------------------------------------------------------- claim freeze
def unfreeze_items_of_claim(claim, bump=True):
    unfrozen = []
    for item in store.all_of(store.items):
        if item.get("frozen_by_claim_id") != claim["id"]:
            continue
        item["lifecycle_state"] = "CATALOGED"
        item["frozen_by_claim_id"] = None
        if bump:
            store.touch(item)
        unfrozen.append(item)
    return unfrozen


def records_freeze_active(household_id):
    for claim in store.claims.values():
        if claim["household_id"] == household_id and claim["status"] in FREEZING_CLAIM_STATES:
            return True
    return False


# ------------------------------------------------------------- appraisals
def expire_due_appraisals(bump=True):
    """CERTIFIED -> EXPIRED once the clock reaches valid_until_at.  Evaluated by
    hook H1 and as the first step of package generation."""
    expired = []
    for appraisal in store.all_of(store.appraisals):
        if appraisal["status"] != "CERTIFIED":
            continue
        valid_until = appraisal.get("_valid_until_at_dt")
        if valid_until is None or clock.now < valid_until:
            continue
        appraisal["status"] = "EXPIRED"
        if bump:
            store.touch(appraisal)
        item = store.items.get(appraisal["item_id"])
        if item is not None:
            refresh_item(item, bump=False)
            if bump:
                store.touch(item)
        expired.append(appraisal)
    return expired


def certified_valid_until(certified_dt):
    return add_days(certified_dt, APPRAISAL_VALIDITY_DAYS)


# ------------------------------------------------------------------- hook H1
def hook_h1():
    """PRD 2.7 hook H1, in its fixed order, run at the end of a successful
    clock advance."""
    counters = {
        "subscriptions_repostured": 0,
        "share_grants_expired": 0,
        "appraisals_expired": 0,
        "packages_expired": 0,
    }

    for sub in store.all_of(store.subscriptions):
        if recompute_refresh_state(sub, bump=True):
            counters["subscriptions_repostured"] += 1

    for household in store.all_of(store.households):
        recompute_write_gate(household, bump=True)

    for grant in store.all_of(store.share_grants):
        if grant["status"] != "ACTIVE":
            continue
        expires = grant.get("_expires_at_dt")
        if expires is not None and clock.now >= expires:
            grant["status"] = "EXPIRED"
            store.touch(grant)
            counters["share_grants_expired"] += 1

    counters["appraisals_expired"] = len(expire_due_appraisals(bump=True))

    for package in store.all_of(store.packages):
        if package["status"] not in ("GENERATED", "DELIVERED"):
            continue
        expires = package.get("_expires_at_dt")
        if expires is not None and clock.now >= expires:
            expire_package(package, bump=True)
            counters["packages_expired"] += 1

    # Every ordinary derived value follows the clock, silently: PRD 2.9 pins the
    # clock advance's version movement to exactly the rows counted above.
    for item in store.all_of(store.items):
        refresh_item(item, bump=False)
    for household in store.all_of(store.households):
        recompute_household(household, bump=False)
    for policy in store.all_of(store.policies):
        recompute_policy(policy, bump=False)
    return counters
