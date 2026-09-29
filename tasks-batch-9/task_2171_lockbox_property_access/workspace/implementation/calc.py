"""Calculation rules (PRD §2.7, §2.8, §2.10, §3.4, §3.7, §3.8, §3.9)."""
from datetime import timedelta
from decimal import Decimal

from core import (
    cents, db, end_of_day, iso, now, num2, ordered, parse_date, parse_dt,
    round_half_up, start_of_day,
)

# --- constants -------------------------------------------------------------
ADMIN_SURCHARGE_RATE = Decimal("0.025")

MONTHLY_DEPRECIATION_RATE = Decimal("0.02")
DEPRECIATION_CAP = Decimal("0.60")
THEFT_SECURITY_OFFSET = Decimal("0.50")

TIER_1_CEILING_CENTS = 4500
TIER_2_CEILING_CENTS = 10500
TIER_FEE_PCT = {"T1": Decimal("0.00"), "T2": Decimal("0.05"), "T3": Decimal("0.10")}

FROZEN_MISSING_BOXES = 3
FROZEN_DELINQUENT_RATIO = Decimal("0.50")
RESTRICTED_MISSING_BOXES = 1
RESTRICTED_DELINQUENT_RATIO = Decimal("0.25")

OUTCOME_WEIGHT = {
    "GRANTED": Decimal(2),
    "DENIED_OUTSIDE_WINDOW": Decimal(9),
    "DENIED_NO_CREDENTIAL": Decimal(12),
    "DENIED_CREDENTIAL_INACTIVE": Decimal(18),
    "DENIED_BOX_MISSING": Decimal(25),
}
ACTOR_MULTIPLIER = {
    "MEMBER": Decimal("1.0"),
    "CONTRACTOR": Decimal("1.25"),
    "UNKNOWN": Decimal("2.0"),
}
AFTER_HOURS_MULTIPLIER = Decimal("1.5")
UNMATCHED_SHOWING_PENALTY = Decimal(10)
SCORE_FLOOR = Decimal("0.00")
SCORE_CEILING = Decimal("100.00")
ELEVATED_THRESHOLD = Decimal("35.00")
CRITICAL_THRESHOLD = Decimal("70.00")

AFTER_HOURS_START_HOUR = 8
AFTER_HOURS_END_HOUR = 20

DEFAULT_WINDOW_DAYS = 90

ACTIVE_PLACEMENT_STATES = ("PLACED", "REMOVAL_DUE", "DELINQUENT")
OPEN_CHARGE_STATES = ("PENDING", "INVOICED")


# --- collection helpers ----------------------------------------------------
def association_lockboxes(association_id):
    return [lb for lb in db.lockboxes.values() if lb["association_id"] == association_id]


def association_placements(association_id):
    out = []
    for p in db.placements.values():
        lb = db.lockboxes.get(p["lockbox_id"])
        if lb is not None and lb["association_id"] == association_id:
            out.append(p)
    return out


def member_credentials(member_id):
    return [c for c in db.credentials.values() if c["member_id"] == member_id]


def member_charges(member_id):
    return [c for c in db.charges.values() if c["member_id"] == member_id]


# --- Member computed fields (PRD §2.7, §3.2, §3.5, §3.7) -------------------
def active_credential_count(member_id):
    return sum(1 for c in member_credentials(member_id) if c["status"] == "ACTIVE")


def member_statement_balance(member_id):
    total = 0
    for charge in member_charges(member_id):
        if charge["status"] in OPEN_CHARGE_STATES:
            total += cents(Decimal(charge["amount_cents"]) * (1 + ADMIN_SURCHARGE_RATE))
    return total


def loss_report_count(member_id):
    return sum(
        1 for lb in db.lockboxes.values()
        if lb.get("assigned_member_id") == member_id
        and lb["status"] in ("MISSING", "QUARANTINE")
    )


def temp_codes_issued_today(member_id):
    today = now().date()
    count = 0
    for grant in db.grants.values():
        if grant.get("issued_by_member_id") != member_id:
            continue
        if grant["grant_type"] != "ONE_DAY_MEMBER":
            continue
        if grant["status"] == "DENIED":
            continue
        created = parse_dt(grant["created_at"])
        if created is not None and created.date() == today:
            count += 1
    return count


# --- Association counters and posture (PRD §2.8, §3.1) ---------------------
def association_counters(association_id):
    boxes = association_lockboxes(association_id)
    placements = association_placements(association_id)
    active = sum(1 for p in placements if p["placement_status"] in ACTIVE_PLACEMENT_STATES)
    delinquent = sum(1 for p in placements if p["placement_status"] == "DELINQUENT")
    return {
        "lockbox_total_count": sum(1 for b in boxes if b["status"] != "RETIRED"),
        "boxes_in_field_count": sum(1 for b in boxes if b["status"] in ("ASSIGNED", "PLACED")),
        "unplaced_inventory_count": sum(1 for b in boxes if b["status"] in ("IN_STOCK", "ASSIGNED")),
        "missing_box_count": sum(1 for b in boxes if b["status"] == "MISSING"),
        "active_placement_count": active,
        "delinquent_placement_count": delinquent,
    }


def association_posture(association_id):
    counters = association_counters(association_id)
    missing = counters["missing_box_count"]
    active = counters["active_placement_count"]
    delinquent = counters["delinquent_placement_count"]
    ratio = Decimal(delinquent) / Decimal(max(1, active))
    if missing >= FROZEN_MISSING_BOXES or ratio >= FROZEN_DELINQUENT_RATIO:
        return "FROZEN"
    if missing >= RESTRICTED_MISSING_BOXES or ratio >= RESTRICTED_DELINQUENT_RATIO:
        return "RESTRICTED"
    return "OPEN"


# --- Replacement charge (PRD §3.7) -----------------------------------------
def replacement_charge_amount(lockbox, loss_type, police_report_number, prior_loss_count):
    cost = Decimal(lockbox["replacement_cost_cents"])
    if loss_type == "STOLEN" and police_report_number:
        variant = "DEPRECIATED_BOOK"
        started = parse_date(lockbox.get("in_service_since"))
        today = now().date()
        days = (today - started).days if started is not None else 0
        if days < 0:
            days = 0
        months = days // 30
        depreciation = min(DEPRECIATION_CAP, Decimal(months) * MONTHLY_DEPRECIATION_RATE)
        amount = cents(cost * (Decimal(1) - depreciation) * THEFT_SECURITY_OFFSET)
        basis = "variant=DEPRECIATED_BOOK months=%d depreciation=%s offset=0.50" % (
            months, str(depreciation),
        )
    else:
        variant = "FLAT_SCHEDULE"
        if prior_loss_count == 0:
            multiplier = Decimal("1.00")
        elif prior_loss_count == 1:
            multiplier = Decimal("1.50")
        else:
            multiplier = Decimal("2.00")
        amount = cents(cost * multiplier)
        basis = "variant=FLAT_SCHEDULE cost=%d prior_losses=%d multiplier=%s" % (
            int(cost), prior_loss_count, str(multiplier),
        )
    return amount, variant, basis


# --- Late removal penalty (PRD §3.4) ---------------------------------------
def ceil_days(delta):
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return int(-(-seconds // 86400))


def late_removal_penalty(association, removal_deadline_dt):
    late_days = max(0, ceil_days(now() - removal_deadline_dt))
    base = min(
        int(association["late_removal_cap_cents"]),
        late_days * int(association["late_removal_daily_fee_cents"]),
    )
    if base <= TIER_1_CEILING_CENTS:
        tier = "T1"
    elif base <= TIER_2_CEILING_CENTS:
        tier = "T2"
    else:
        tier = "T3"
    admin_fee = cents(Decimal(base) * TIER_FEE_PCT[tier])
    total = base + admin_fee
    basis = "base=%d tier=%s admin_fee=%d" % (base, tier, admin_fee)
    return late_days, total, basis


# --- Recovery rate (PRD §3.9) ----------------------------------------------
def recovery_window_defaults():
    end = now()
    return end - timedelta(days=DEFAULT_WINDOW_DAYS), end


def placement_on_time(placement):
    if not placement.get("removed_at"):
        return False
    deadline = placement.get("removal_deadline")
    if not deadline:
        return True
    return parse_dt(placement["removed_at"]) <= parse_dt(deadline)


def lockbox_recovery_rate(association_id, variant, window_start, window_end):
    placements = association_placements(association_id)
    denom = []
    if variant == "removal_activity":
        for p in placements:
            if p["placement_status"] == "REMOVED" and p.get("removed_at"):
                moment = parse_dt(p["removed_at"])
                if moment is not None and window_start <= moment <= window_end:
                    denom.append(p)
            elif p["placement_status"] == "DELINQUENT" and p.get("removal_deadline"):
                moment = parse_dt(p["removal_deadline"])
                if moment is not None and window_start <= moment <= window_end:
                    denom.append(p)
        numer = [p for p in denom if p["placement_status"] == "REMOVED"]
    else:
        for p in placements:
            listing = db.listings.get(p["listing_id"])
            if listing is None or listing["status"] != "CLOSED":
                continue
            close_date = parse_date(listing.get("close_date"))
            if close_date is None:
                continue
            moment = start_of_day(close_date)
            if window_start <= moment <= window_end:
                denom.append(p)
        numer = [
            p for p in denom
            if p["placement_status"] == "REMOVED" and placement_on_time(p)
        ]
    denominator = len(denom)
    numerator = len(numer)
    if denominator == 0:
        rate = 0.00
    else:
        rate = num2(Decimal(numerator) * Decimal(100) / Decimal(denominator))
    return denominator, numerator, rate


def recompute_recovery_rate(association):
    start, end = recovery_window_defaults()
    _, _, rate = lockbox_recovery_rate(association["id"], "closing_cohort", start, end)
    association["recovery_rate_pct"] = rate
    return rate


# --- Access outcome resolution (PRD §3.6) ----------------------------------
def compute_after_hours(occurred_at):
    hour = occurred_at.hour
    return hour < AFTER_HOURS_START_HOUR or hour >= AFTER_HOURS_END_HOUR


def event_risk_weight(event):
    weight = OUTCOME_WEIGHT.get(event["outcome"], Decimal(0))
    hours = AFTER_HOURS_MULTIPLIER if event.get("after_hours") else Decimal("1.0")
    actor = ACTOR_MULTIPLIER.get(event["actor_type"], Decimal("1.0"))
    return round_half_up(weight * hours * actor, 2)


# --- Incident risk score (PRD §3.8) ----------------------------------------
def incident_risk_score(events):
    base = Decimal("0")
    unmatched = 0
    for event in events:
        base += round_half_up(Decimal(str(event.get("risk_weight", 0))), 2)
        if (event["outcome"] == "GRANTED"
                and event["actor_type"] == "MEMBER"
                and not event.get("matched_appointment_id")):
            unmatched += 1
    raw = base + UNMATCHED_SHOWING_PENALTY * Decimal(unmatched)
    score = round_half_up(raw, 2)
    if score < SCORE_FLOOR:
        score = SCORE_FLOOR
    if score > SCORE_CEILING:
        score = SCORE_CEILING
    if score >= CRITICAL_THRESHOLD:
        severity = "CRITICAL"
    elif score >= ELEVATED_THRESHOLD:
        severity = "ELEVATED"
    else:
        severity = "LOW"
    return float(score), severity


# --- Interval arithmetic (PRD §2.10) ---------------------------------------
def grants_conflict(grant_a, grant_b, buffer_minutes):
    buffer = timedelta(minutes=buffer_minutes)
    a_start = parse_dt(grant_a["window_start"])
    a_end = parse_dt(grant_a["window_end"]) + buffer
    b_start = parse_dt(grant_b["window_start"])
    b_end = parse_dt(grant_b["window_end"]) + buffer
    return a_start < b_end and b_start < a_end


def showings_overlap(app_a, app_b):
    a_start = parse_dt(app_a["window_start"])
    a_end = parse_dt(app_a["window_end"])
    b_start = parse_dt(app_b["window_start"])
    b_end = parse_dt(app_b["window_end"])
    return a_start <= b_end and b_start <= a_end
