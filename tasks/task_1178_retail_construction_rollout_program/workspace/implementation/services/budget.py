"""Derived budget state: site variance (§3.6), program rollup (§3.6),
punch counts (§3.7), readiness posture (§3.5).

All monetary math is integer cents; basis-point ratios round half up via
Decimal. Recompute helpers bump a resource's version only when a stored
value actually changes (§2.4).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import store
from util import apply_changes


def _rh_bp(numerator, denominator):
    """round_half_up(numerator * 10000 / denominator) as integer bp."""
    q = (Decimal(numerator) * Decimal(10000)) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_site_budget(site):
    """site_committed_cost + site_budget_variance."""
    approved = sum(
        co["amount_cents"]
        for co in store.change_orders.values()
        if co["site_id"] == site["id"] and co["status"] == "APPROVED"
    )
    proposed = sum(
        co["amount_cents"]
        for co in store.change_orders.values()
        if co["site_id"] == site["id"] and co["status"] == "PROPOSED"
    )
    base = site["base_contract_cents"]
    committed = base + approved
    if base == 0:
        final_bp = 0
        prov_bp = 0
    else:
        final_bp = _rh_bp(committed - base, base)
        prov_bp = _rh_bp(committed + proposed - base, base)
    if final_bp <= 500:
        posture = "WITHIN"
    elif final_bp <= 1500:
        posture = "WATCH"
    else:
        posture = "OVERRUN"
    apply_changes(site, {
        "approved_co_cents": approved,
        "proposed_co_cents": proposed,
        "committed_cents": committed,
        "variance_ratio_final_bp": final_bp,
        "variance_ratio_provisional_bp": prov_bp,
        "budget_posture": posture,
    })


def recompute_program_rollup(program):
    """program_budget_rollup over sites with status != REMOVED."""
    sites = [
        s for s in store.sites.values()
        if s["program_id"] == program["id"] and s["status"] != "REMOVED"
    ]
    committed = sum(s["committed_cents"] for s in sites)
    actuals = sum(s["actuals_cents"] for s in sites)
    reserved = 0
    for s in sites:
        over = max(0, s["committed_cents"] - s["base_contract_cents"])
        if s["budget_posture"] == "WATCH":
            term = (Decimal(over) * Decimal("0.25")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
            reserved += int(term)
        elif s["budget_posture"] == "OVERRUN":
            reserved += over
    pool = program["contingency_pool_cents"]
    free = pool - reserved
    if free < 0:
        posture = "OVERRUN"
    elif reserved * 2 > pool:
        posture = "GUARDED"
    else:
        posture = "WITHIN_PLAN"
    apply_changes(program, {
        "committed_cents": committed,
        "actuals_cents": actuals,
        "contingency_reserved_cents": reserved,
        "contingency_free_cents": free,
        "budget_posture": posture,
    })


def recompute_punch_counts(site):
    items = [p for p in store.punch_items.values() if p["site_id"] == site["id"]]
    open_statuses = ("OPEN", "RESOLVED")
    total = sum(1 for p in items if p["status"] in open_statuses)
    critical = sum(
        1 for p in items
        if p["status"] in open_statuses and p["severity"] == "CRITICAL"
    )
    apply_changes(site, {
        "punch_open_critical_count": critical,
        "punch_open_total_count": total,
    })


def recompute_readiness(site):
    """Highest completed vendor type drives readiness (§3.5)."""
    mobs = [m for m in store.mobilizations.values() if m["site_id"] == site["id"]]
    done = {m["vendor_type"] for m in mobs if m["status"] == "COMPLETE"}
    if "SIGNAGE" in done:
        posture = "SIGNAGE_HUNG"
    elif "IT" in done:
        posture = "IT_LIVE"
    elif "FIXTURE" in done:
        posture = "FIXTURE_SET"
    else:
        posture = "ROUGH"
    apply_changes(site, {"readiness_posture": posture})


def program_of_site(site):
    return store.programs.get(site["program_id"])


def recompute_site_and_program(site):
    recompute_site_budget(site)
    program = program_of_site(site)
    if program is not None:
        recompute_program_rollup(program)
