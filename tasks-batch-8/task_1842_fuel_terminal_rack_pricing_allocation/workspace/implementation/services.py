"""Business logic: pricing, additives, tax, allocation, exposure, cascades.

Every formula here traces to SCAFFOLD.yaml §1.3 and PRD §3.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from clock import clock, now_iso, today_str
from db import db
from helpers import new_audit, touch

# --- rack_price_determination constants (SCAFFOLD §1.3) ---
TIER_DISCOUNT = {"RACK": 0, "RACK_MINUS_1": 1, "RACK_MINUS_2": 2}

# --- additive_injection_cost recipes: (rate_millicents_per_gal, flat_fee_cents) ---
ADDITIVE_RECIPES = {
    "PKG_A": [(250, 500), (100, 0)],
    "PKG_B": [(175, 750)],
    "PKG_C": [(333, 0), (167, 250), (100, 0)],
}

# Branded loads at a California terminal carry +2 cents/gal at STATE level.
CA_BRANDED_UPLIFT_CENTS_PER_GAL = 2


# ---------------------------------------------------------------------------
# Price schedules
# ---------------------------------------------------------------------------

def find_published_schedule(terminal_id, product_id, date_str):
    """Single PUBLISHED schedule for the (terminal, product, date) triple.

    Race rule: latest published_at wins; tie-break by created_at ASC
    (creation sequence breaks any residual tie deterministically).
    """
    cands = [
        s for s in db.price_schedules.values()
        if s["terminal_id"] == terminal_id
        and s["product_id"] == product_id
        and s["effective_date"] == date_str
        and s["status"] == "PUBLISHED"
    ]
    if not cands:
        return None
    cands.sort(key=lambda s: (s["created_at"], s["_seq"]))
    cands.sort(key=lambda s: s["published_at"] or "", reverse=True)  # stable
    return cands[0]


def compute_unit_price(schedule, branded, pricing_tier):
    base = schedule["posted_rack_cents_per_gal"]
    if branded:
        base += schedule.get("branded_premium_cents_per_gal") or 0
    return max(0, base - TIER_DISCOUNT.get(pricing_tier, 0))


# ---------------------------------------------------------------------------
# Additive injection: round HALF_UP per line to whole cents, THEN sum
# ---------------------------------------------------------------------------

def compute_additive_cost(branded, package_code, gallons):
    if not branded:
        return 0
    recipe = ADDITIVE_RECIPES.get(package_code)
    if recipe is None:
        return 0
    total = 0
    for rate_mc, flat in recipe:
        line = (Decimal(gallons * rate_mc) / Decimal(1000)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        total += int(line) + flat
    return total


# ---------------------------------------------------------------------------
# Tax jurisdiction determination: FEDERAL + STATE + COUNTY + CITY stack
# ---------------------------------------------------------------------------

def select_tax_rule(level, code, family, date_str):
    cands = [
        r for r in db.tax_rules.values()
        if r["jurisdiction_level"] == level
        and r["jurisdiction_code"] == code
        and r["product_family"] == family
        and r["status"] == "ACTIVE"
        and r["effective_start_date"] <= date_str <= r["effective_end_date"]
    ]
    if not cands:
        return None
    cands.sort(key=lambda r: (r["created_at"], r["_seq"]))
    cands.sort(key=lambda r: r["effective_start_date"], reverse=True)  # stable
    return cands[0]


def compute_tax(terminal, product, branded, gallons, date_str):
    total = 0
    level_codes = [
        ("FEDERAL", "US"),
        ("STATE", terminal.get("state_code")),
        ("COUNTY", terminal.get("county_code")),
        ("CITY", terminal.get("city_code")),
    ]
    for level, code in level_codes:
        if not code:
            continue
        rule = select_tax_rule(level, code, product["product_family"], date_str)
        if rule is not None:
            total += gallons * rule["rate_cents_per_gal"]
        if level == "STATE" and branded and terminal.get("state_code") == "CA":
            total += CA_BRANDED_UPLIFT_CENTS_PER_GAL * gallons
    return total


# ---------------------------------------------------------------------------
# Price components (provisional at reservation / final at BOL post)
# ---------------------------------------------------------------------------

def price_components(terminal, product, contract, branded, package_code,
                     gallons, date_str):
    """Returns (unit_price, additive_cost, tax, gross) in integer cents.

    Without a PUBLISHED schedule covering the date the price is not
    determinable, so all components are zero (reservation is still allowed;
    the published-price gate exists only at post-bol).
    """
    schedule = find_published_schedule(terminal["id"], product["id"], date_str)
    if schedule is None:
        return 0, 0, 0, 0
    unit = compute_unit_price(schedule, branded, contract["pricing_tier"])
    additive = compute_additive_cost(branded, package_code, gallons)
    tax = compute_tax(terminal, product, branded, gallons, date_str)
    gross = gallons * unit + additive + tax
    return unit, additive, tax, gross


# ---------------------------------------------------------------------------
# Credit exposure and holds (PRD §2.9, §3.2)
# ---------------------------------------------------------------------------

def adjust_exposure(customer, delta_cents):
    customer["open_lifting_exposure_cents"] += delta_cents
    touch(customer)


def log_credit_event(customer, event_type, trigger_reason):
    e = new_audit({
        "customer_id": customer["id"],
        "event_type": event_type,
        "trigger_reason": trigger_reason,
        "open_exposure_cents_at_event": customer["open_lifting_exposure_cents"],
    })
    db.credit_hold_logs[e["id"]] = e
    return e


def place_hold(customer, hold_reason, trigger_reason):
    """GOOD -> HOLD with audit log. No-op if the customer is already on HOLD."""
    if customer["credit_status"] != "GOOD":
        return
    customer["credit_status"] = "HOLD"
    customer["hold_reason"] = hold_reason
    touch(customer)
    log_credit_event(customer, "PLACED", trigger_reason)


# ---------------------------------------------------------------------------
# BOL events
# ---------------------------------------------------------------------------

def add_bol_event(ticket, event_type, payload):
    e = new_audit({
        "lifting_ticket_id": ticket["id"],
        "event_type": event_type,
        "event_payload": payload,
    })
    db.bol_events[e["id"]] = e
    return e


def latest_posted_event(ticket_id):
    evs = [
        e for e in db.bol_events.values()
        if e["lifting_ticket_id"] == ticket_id and e["event_type"] == "POSTED"
    ]
    if not evs:
        return None
    evs.sort(key=lambda e: (e["created_at"], e["_seq"]))
    return evs[-1]


def next_bol_seq(terminal_id, yyyymmdd):
    key = (terminal_id, yyyymmdd)
    db.bol_counters[key] = db.bol_counters.get(key, 0) + 1
    return db.bol_counters[key]


# ---------------------------------------------------------------------------
# Allocation notices: publish cascade + ratable allocation (PRD §3.4)
# ---------------------------------------------------------------------------

def published_notice_exists(terminal_id, date_str):
    return any(
        n for n in db.allocation_notices.values()
        if n["terminal_id"] == terminal_id
        and n["effective_date"] == date_str
        and n["status"] == "PUBLISHED"
    )


def _allocation_order(rights):
    return sorted(
        rights,
        key=lambda r: (-r["daily_ratable_gallons"], r["created_at"], r["_seq"]),
    )


def apply_allocation_notice(notice):
    """Side effects of AllocationNotice DRAFT -> PUBLISHED (PRD §3.4)."""
    terminal = db.terminals.get(notice["terminal_id"])
    if terminal is None:
        return
    pool = notice["total_pool_gallons"]
    rights = [
        r for r in db.lifting_rights.values()
        if r["terminal_id"] == terminal["id"] and r["status"] == "ACTIVE"
    ]

    # Every ACTIVE right at the terminal resets lifted_today for the new date.
    for r in rights:
        r["lifted_today_gallons"] = 0

    # Ratable allocation writes each participating right's allocated_gallons.
    if rights:
        if notice["allocation_method"] == "PRO_RATA":
            total_ratable = sum(r["daily_ratable_gallons"] for r in rights)
            if total_ratable > 0:
                for r in rights:
                    r["allocated_gallons"] = (
                        pool * r["daily_ratable_gallons"]
                    ) // total_ratable
            else:
                for r in rights:
                    r["allocated_gallons"] = 0
            remainder = pool - sum(r["allocated_gallons"] for r in rights)
            ordered = _allocation_order(rights)
            idx = 0
            while remainder > 0 and ordered:
                ordered[idx % len(ordered)]["allocated_gallons"] += 1
                remainder -= 1
                idx += 1
        else:  # RATCHET: equal-share cap, then surplus to rights still short
            equal_share = pool // len(rights)
            for r in rights:
                r["allocated_gallons"] = min(r["daily_ratable_gallons"], equal_share)
            surplus = pool - sum(r["allocated_gallons"] for r in rights)
            while surplus > 0:
                shorts = [
                    r for r in rights
                    if r["allocated_gallons"] < r["daily_ratable_gallons"]
                ]
                if not shorts:
                    break
                progressed = False
                for r in _allocation_order(shorts):
                    if surplus == 0:
                        break
                    r["allocated_gallons"] += 1
                    surplus -= 1
                    progressed = True
                if not progressed:
                    break

        for r in rights:
            touch(r)

    # Terminal posture re-evaluation + pool + version bump.
    sum_ratable = sum(r["daily_ratable_gallons"] for r in rights)
    terminal["daily_allocation_pool_gallons"] = pool
    if pool < sum_ratable:
        if terminal["rack_status"] == "OPEN":
            terminal["rack_status"] = "SHORTAGE"
    else:
        if terminal["rack_status"] == "SHORTAGE":
            terminal["rack_status"] = "OPEN"
    touch(terminal)


# ---------------------------------------------------------------------------
# Clock cascade: contract end_date passed -> rights EXPIRE (PRD §2.4)
# ---------------------------------------------------------------------------

def expire_rights_for_passed_contracts():
    today = today_str()
    for c in list(db.supply_contracts.values()):
        end = c.get("end_date")
        if end and end < today:
            for r in list(db.lifting_rights.values()):
                if r["contract_id"] == c["id"] and r["status"] in ("ACTIVE", "SUSPENDED"):
                    r["status"] = "EXPIRED"
                    touch(r)


REVERSAL_WINDOW = timedelta(hours=24)
