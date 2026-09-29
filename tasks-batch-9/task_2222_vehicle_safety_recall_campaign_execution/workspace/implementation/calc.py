"""Calculation rules (SCAFFOLD 1.3 / PRD 3.x)."""
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from db import (UTC, clock_date, clock_now, fmt_instant, order_key, parse_date,
                parse_instant, store)

# ---- constants ------------------------------------------------------------
FILING_BUSINESS_DAYS = 5
FEDERAL_HOLIDAYS = {
    date(2026, 1, 1), date(2026, 7, 3), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25), date(2027, 1, 1),
}

PARTS_PER_REPAIR_MAX = 1
ADMIN_ALLOWANCE_USD = Decimal("12.00")
PARTS_HANDLING_MARKUP_PCT = Decimal("0.15")
RATE_CAP_BY_REGION = {
    "NE": Decimal("152.00"),
    "SE": Decimal("128.50"),
    "MW": Decimal("121.75"),
    "WE": Decimal("165.25"),
}
CLAIM_HOURS_TOLERANCE = Decimal("1.5")

FOLLOWUP_TRIGGER_PCT = Decimal("85.00")
CLOSURE_COMPLETION_MIN = Decimal("95.00")
CLOSURE_QUARTERLY_FILINGS_MIN = 2

REQUIRED_MIN_RATIO_BY_SEVERITY = {
    "HIGH": Decimal("1.0000"),
    "MODERATE": Decimal("0.6000"),
    "LOW": Decimal("0.3000"),
}

PREVAILING_LABOR_RATE_USD = Decimal("115.00")
OWNER_PARTS_MSRP_FACTOR = Decimal("1.40")
TOWING_CAP_USD = Decimal("100.00")
OWNER_INVOICE_MAX_USD = Decimal("5000.00")
REIMBURSEMENT_LOOKBACK_DAYS = 365
REIMBURSEMENT_TAIL_DAYS = 30

REPEAT_WEIGHT = Decimal("60.00")
UNREACHABLE_WEIGHT = Decimal("20.00")
LATE_FILING_PENALTY_POINTS = Decimal("5.00")
REMEDY_EFFECTIVENESS_MIN = Decimal("70.00")

MAX_DOCUMENT_ROUNDS = 2
UNREACHABLE_ATTEMPT_THRESHOLD = 3
FOLLOWUP_LEAD_DAYS = 21
MIN_WAVE_SEPARATION_DAYS = 14

TWO = Decimal("0.01")
FOUR = Decimal("0.0001")


def q2(value):
    return Decimal(value).quantize(TWO, rounding=ROUND_HALF_UP)


def q4(value):
    return Decimal(value).quantize(FOUR, rounding=ROUND_HALF_UP)


def to_cents(usd):
    return int((q2(usd) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Serialize a Decimal for JSON."""
    if value is None:
        return None
    return float(value)


# ---- collection helpers ---------------------------------------------------
def campaign_avs(campaign_id):
    return [av for av in store.affected_vehicles.values()
            if av["campaign_id"] == campaign_id]


def campaign_waves(campaign_id):
    return [w for w in store.waves.values() if w["campaign_id"] == campaign_id]


def campaign_parts(campaign_id):
    return sorted([p for p in store.remedy_parts.values()
                   if p["campaign_id"] == campaign_id], key=order_key)


def campaign_first_part(campaign_id):
    parts = campaign_parts(campaign_id)
    return parts[0] if parts else None


def campaign_allocations(campaign_id):
    return sorted([a for a in store.allocations.values()
                   if a["campaign_id"] == campaign_id], key=order_key)


def campaign_labor_ops(campaign_id):
    return sorted([lo for lo in store.labor_operations.values()
                   if lo["campaign_id"] == campaign_id], key=order_key)


def campaign_filings(campaign_id):
    return sorted([f for f in store.filings.values()
                   if f["campaign_id"] == campaign_id], key=order_key)


def av_claims(av_id):
    return [c for c in store.repair_claims.values()
            if c["affected_vehicle_id"] == av_id]


def approved_claim_count(av_id):
    return sum(1 for c in av_claims(av_id) if c["status"] == "APPROVED")


def outreach_for(av_id):
    return sorted([o for o in store.outreach_attempts.values()
                   if o["affected_vehicle_id"] == av_id], key=order_key)


def labor_op_claim_count(labor_operation_id):
    return sum(1 for c in store.repair_claims.values()
               if c["labor_operation_id"] == labor_operation_id
               and c["status"] in ("SUBMITTED", "APPROVED"))


def rule_matched_count(rule_id):
    return sum(1 for av in store.affected_vehicles.values()
               if av["matched_by_rule_id"] == rule_id)


# ---- calculation: filing_deadline ----------------------------------------
def filing_deadline(determination_dt):
    d = determination_dt.astimezone(UTC).date()
    counted = 0
    while counted < FILING_BUSINESS_DAYS:
        d = d + timedelta(days=1)
        if d.weekday() < 5 and d not in FEDERAL_HOLIDAYS:
            counted += 1
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=UTC)


def fmt_deadline(dt):
    """PRD 3.1 - filing_deadline_utc is the counted date 'pinned to 23:59:59Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def filing_lateness(filed_at, deadline):
    """Returns (late_filing_flag, days_late)."""
    if deadline is None:
        return False, 0
    if filed_at > deadline:
        delta = (filed_at - deadline).total_seconds()
        days = int(delta // 86400)
        if delta % 86400 > 0:
            days += 1
        return True, days
    return False, 0


# ---- calculation: completion_rate ---------------------------------------
def population_buckets(campaign_id):
    rows = campaign_avs(campaign_id)
    total = len(rows)
    removed = sum(1 for r in rows if r["remedy_status"] == "REMOVED_FROM_POPULATION")
    unreachable = sum(1 for r in rows if r["remedy_status"] == "UNREACHABLE")
    remedied = sum(1 for r in rows if r["remedy_status"] == "REMEDIED")
    scheduled = sum(1 for r in rows if r["remedy_status"] == "SCHEDULED")
    return {
        "total": total,
        "removed": removed,
        "unreachable": unreachable,
        "remedied": remedied,
        "scheduled": scheduled,
        "recall_population": total - removed,
    }


def regulatory_completion_rate(campaign_id, buckets=None):
    b = buckets or population_buckets(campaign_id)
    if b["recall_population"] == 0:
        return Decimal("0.00")
    return q2(Decimal(100) * Decimal(b["remedied"]) / Decimal(b["recall_population"]))


def operational_completion_rate(campaign_id, buckets=None):
    b = buckets or population_buckets(campaign_id)
    denom = b["total"] - b["removed"] - b["unreachable"]
    if denom == 0:
        return Decimal("0.00")
    numer = Decimal(b["remedied"] + b["scheduled"])
    return q2(Decimal(100) * numer / Decimal(denom))


def repeat_claim_count(campaign_id):
    total = 0
    for av in campaign_avs(campaign_id):
        total += max(0, approved_claim_count(av["id"]) - 1)
    return total


# ---- calculation: remedy_effectiveness_score -----------------------------
def remedy_effectiveness_score(campaign):
    b = population_buckets(campaign["id"])
    remedied = b["remedied"]
    recall_population = b["recall_population"]
    unreachable = b["unreachable"]
    repeats = repeat_claim_count(campaign["id"])

    repeat_rate = Decimal("0.0000") if remedied == 0 else q4(
        Decimal(repeats) / Decimal(remedied))
    unreachable_rate = Decimal("0.0000") if recall_population == 0 else q4(
        Decimal(unreachable) / Decimal(recall_population))
    late_penalty = LATE_FILING_PENALTY_POINTS if campaign.get("late_filing_flag") else Decimal("0.00")

    raw = (Decimal("100.00") - (REPEAT_WEIGHT * repeat_rate)
           - (UNREACHABLE_WEIGHT * unreachable_rate) - late_penalty)
    if raw < Decimal("0.00"):
        raw = Decimal("0.00")
    if raw > Decimal("100.00"):
        raw = Decimal("100.00")
    return q2(raw)


# ---- calculation: obligation ledger --------------------------------------
def reimbursement_obligation_cents(campaign_id):
    total = 0
    for c in store.repair_claims.values():
        if c["campaign_id"] == campaign_id and c["status"] == "APPROVED":
            total += c["final_amount_cents"] or 0
    for r in store.reimbursements.values():
        if r["campaign_id"] == campaign_id and r["status"] == "APPROVED":
            total += r["approved_amount_cents"] or 0
    return total


def open_followup_wave_count(campaign_id):
    return sum(1 for w in campaign_waves(campaign_id)
               if w["wave_type"] == "FOLLOW_UP"
               and w["status"] in ("PLANNED", "RELEASE_APPROVED"))


# ---- calculation: claim_reimbursement ------------------------------------
def provisional_amount_cents(claim_hours, parts_qty, dealer, part):
    labor_p = q2(claim_hours * dealer["labor_rate_per_hour"])
    unit_cost = part["unit_cost"] if part else Decimal("0.00")
    parts_p = q2(Decimal(parts_qty) * unit_cost * (Decimal(1) + PARTS_HANDLING_MARKUP_PCT))
    total = q2(labor_p + parts_p + ADMIN_ALLOWANCE_USD)
    return to_cents(total)


def final_amount_cents(claim, dealer, labor_op, part, campaign):
    effective_hours = min(claim["claimed_labor_hours"], labor_op["flat_hours"])
    effective_rate = min(dealer["labor_rate_per_hour"],
                         RATE_CAP_BY_REGION[dealer["region_code"]])
    labor_f = q2(effective_hours * effective_rate)
    unit_cost = part["unit_cost"] if part else Decimal("0.00")
    kits = min(claim["parts_used_qty"], PARTS_PER_REPAIR_MAX)
    parts_f = q2(Decimal(kits) * unit_cost * (Decimal(1) + PARTS_HANDLING_MARKUP_PCT))
    admin_f = Decimal("0.00")
    released = parse_instant(campaign["remedy_released_at"]) if campaign["remedy_released_at"] else None
    if released is not None and parse_date(claim["repair_date"]) >= released.astimezone(UTC).date():
        admin_f = ADMIN_ALLOWANCE_USD
    total = q2(labor_f + parts_f + admin_f)
    return to_cents(total)


# ---- calculation: owner_reimbursement_amount ----------------------------
def owner_reimbursement_amount_cents(request_row, campaign, labor_op, part):
    labor_c = q2(min(request_row["labor_hours_claimed"], labor_op["flat_hours"])
                 * PREVAILING_LABOR_RATE_USD)
    unit_cost = part["unit_cost"] if part else Decimal("0.00")
    parts_cap = q2(unit_cost * Decimal(PARTS_PER_REPAIR_MAX) * OWNER_PARTS_MSRP_FACTOR)
    parts_c = q2(min(request_row["parts_amount"], parts_cap))
    if campaign["do_not_drive_flag"]:
        tow_c = q2(min(request_row["towing_amount"], TOWING_CAP_USD))
    else:
        tow_c = Decimal("0.00")
    cap = q2(labor_c + parts_c + tow_c)
    payable = q2(min(request_row["invoice_amount"], cap))
    return to_cents(payable)


# ---- calculation: wave candidate set / release quota ---------------------
def wave_candidates(wave):
    campaign_id = wave["campaign_id"]
    region = wave["target_region_code"]
    rows = []
    for av in campaign_avs(campaign_id):
        vehicle = store.vehicles.get(av["vehicle_id"])
        if vehicle is None or vehicle["region_code"] != region:
            continue
        rows.append(av)
    wave_type = wave["wave_type"]
    if wave_type == "INTERIM":
        rows = [r for r in rows
                if r["remedy_status"] == "UNREPAIRED" and r["notice_count"] == 0]
    elif wave_type == "REMEDY":
        rows = [r for r in rows
                if r["remedy_status"] in ("UNREPAIRED", "SCHEDULED")
                and (r["last_notice_type"] is None or r["last_notice_type"] == "INTERIM")]
    else:  # FOLLOW_UP
        rows = [r for r in rows
                if r["remedy_status"] == "UNREPAIRED"
                and r["notice_count"] >= 1
                and r["last_notice_type"] in ("REMEDY", "FOLLOW_UP")]
    return rows


def wave_mailing_order(rows):
    def key(av):
        vehicle = store.vehicles.get(av["vehicle_id"])
        production = vehicle["production_date"] if vehicle else ""
        return (production, av["created_at"], av["_seq"])
    return sorted(rows, key=key)


def wave_parts_capacity(wave):
    if wave["wave_type"] == "INTERIM":
        return None  # caller substitutes eligible_vehicle_count
    total = 0
    for alloc in campaign_allocations(wave["campaign_id"]):
        if alloc["status"] != "ALLOCATED":
            continue
        dealer = store.dealers.get(alloc["dealer_id"])
        if dealer is None or dealer["region_code"] != wave["target_region_code"]:
            continue
        total += alloc["allocated_qty"] - alloc["consumed_qty"]
    return total


def coverage_tier_factor(ratio):
    if ratio >= Decimal("1.0000"):
        return Decimal("1.00")
    if ratio >= Decimal("0.6000"):
        return Decimal("0.75")
    if ratio >= Decimal("0.3000"):
        return Decimal("0.40")
    return Decimal("0.00")


# ---- calculation: parts_allocation_pick ---------------------------------
def pick_allocation(dealer_id, campaign_id):
    candidates = [a for a in store.allocations.values()
                  if a["dealer_id"] == dealer_id
                  and a["campaign_id"] == campaign_id
                  and a["status"] == "ALLOCATED"
                  and (a["allocated_qty"] - a["consumed_qty"]) >= PARTS_PER_REPAIR_MAX]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a["created_at"], -a["allocated_qty"], a["_seq"]))
    return candidates[0]


# ---- calculation: affected_population_match -----------------------------
def rule_matches(rule, vehicle):
    if vehicle["plant_code"] != rule["plant_code"]:
        return False
    if vehicle["model_code"] != rule["model_code"]:
        return False
    if vehicle["model_year"] != rule["model_year"]:
        return False
    production = parse_date(vehicle["production_date"])
    if not (parse_date(rule["production_start_date"]) <= production
            < parse_date(rule["production_end_date"])):
        return False
    if not (rule["part_number_low"] <= vehicle["suspect_part_number"]
            <= rule["part_number_high"]):
        return False
    return True


def campaign_rules(campaign_id, inclusion_mode=None):
    rules = [r for r in store.population_rules.values()
             if r["campaign_id"] == campaign_id
             and (inclusion_mode is None or r["inclusion_mode"] == inclusion_mode)]
    return sorted(rules, key=order_key)


def include_rules_ordered(campaign_id):
    rules = campaign_rules(campaign_id, "INCLUDE")
    return sorted(rules, key=lambda r: (r["production_start_date"],
                                        r["created_at"], r["_seq"]))


def vehicles_ordered():
    return sorted(store.vehicles.values(),
                  key=lambda v: (v["production_date"], v["created_at"], v["_seq"]))
