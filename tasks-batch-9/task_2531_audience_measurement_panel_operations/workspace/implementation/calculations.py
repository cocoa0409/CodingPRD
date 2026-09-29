"""Pure calculation rules: rates, money, scores and the weight redistribution."""
import math
from decimal import Decimal

from util import D, round_half_up, rhu_int

# --- fixed domain constants -------------------------------------------------
AGE_BANDS = ("P18_34", "P35_54", "P55_PLUS")
INCOME_BANDS = ("LOW", "MID", "HIGH")
GEO_ZONES = ("URBAN", "SUBURBAN", "RURAL")
RECRUITMENT_SOURCES = ("ADDRESS_SAMPLE", "RDD_PHONE", "ONLINE_PANEL_TRANSFER")
METER_TYPES = ("TV_TUNER", "STREAMING_ROUTER", "PORTABLE_OOH")
FAULT_CODES = ("NO_SIGNAL", "POWER_LOSS", "TAMPER", "CLOCK_DRIFT",
               "MISSING_INTERVALS")
SOURCE_METHODOLOGIES = ("INHOME_TUNER", "STREAMING_SDK", "PORTABLE_OOH")
METHODOLOGY_FOR_METER_TYPE = {
    "TV_TUNER": "INHOME_TUNER",
    "STREAMING_ROUTER": "STREAMING_SDK",
    "PORTABLE_OOH": "PORTABLE_OOH",
}
CREDIT_FACTOR = {
    "INHOME_TUNER": D("1.0"),
    "STREAMING_SDK": D("1.0"),
    "PORTABLE_OOH": D("0.5"),
}
WEIGHT_VARIANTS = ("DESIGN", "FINAL")
DESIGN_DENOMINATOR_STATUSES = ("RECRUITED", "INSTALL_SCHEDULED", "ENUM_PENDING",
                               "ACTIVE", "FAULT_HOLD", "NONCOMPLIANT_HOLD")
CLIENT_TIERS = ("BASIC", "STANDARD", "PREMIUM")
TIER_TABLE = {
    "BASIC": {"tier_base_fee_cents": 25000, "delivery_sla_hours": 168,
              "custom_analysis_quota": 0},
    "STANDARD": {"tier_base_fee_cents": 65000, "delivery_sla_hours": 72,
                 "custom_analysis_quota": 3},
    "PREMIUM": {"tier_base_fee_cents": 120000, "delivery_sla_hours": 24,
                "custom_analysis_quota": 10},
}
PER_CELL_SURCHARGE_CENTS = 5000
INCENTIVE_PERIOD_CAP_CENTS = 5000
REVISION_LIMIT = 2
NOTIFICATION_LEAD_HOURS = {"MINOR": 72, "MODERATE": 336, "MATERIAL": 720}
HOLD_REASONS = ("CLIENT_REQUESTED", "DATA_QUALITY_REVIEW", "UPSTREAM_RUN_REPIN")
MANUAL_HOLD_REASONS = ("CLIENT_REQUESTED", "DATA_QUALITY_REVIEW")
AUDIT_OUTCOMES = ("ACCREDITED", "QUALIFIED", "DENIED")


# --- quota cell fill --------------------------------------------------------
def fill_grade(intab_count, target_households):
    rate = round_half_up(D(intab_count) / D(target_households), 4)
    if rate >= D("1.0000"):
        status = "FILLED"
    elif rate >= D("0.8000"):
        status = "ON_TARGET"
    else:
        status = "UNDER_TARGET"
    return rate, status


def boost_reservation_cents(base_incentive_cents, target_households):
    return rhu_int(D(base_incentive_cents) * D("0.25") * D(target_households))


# --- enumeration ------------------------------------------------------------
def enumeration_verdict(sequence, roster_persons_count, persons_count,
                        tv_sets_count, age_days):
    roster_ok = roster_persons_count == persons_count
    sets_ok = tv_sets_count >= 1
    due_ok = True if sequence != 1 else (age_days is not None and age_days <= 14)
    return "COMPLIANT" if (roster_ok and sets_ok and due_ok) else "NONCOMPLIANT"


def whole_days(seconds):
    return int(math.floor(seconds / 86400.0))


def tenure_months(seconds):
    return int(math.floor(seconds / 2592000.0))


def tenure_multiplier(months):
    if months < 6:
        return D("1.000")
    if months < 24:
        return D("1.075")
    return D("1.150")


# --- cooperation incentive (nine rounded steps) -----------------------------
def incentive_period_amount(base_incentive_cents, effective_multiplier,
                            months, compliance_rate, has_installed_ooh,
                            has_faulted_meter):
    multiplier = tenure_multiplier(months)
    cell_base = round_half_up(D(base_incentive_cents) * D(effective_multiplier), 0)
    tenure_amount = round_half_up(cell_base * multiplier, 0)
    bonus = (round_half_up(tenure_amount * D("0.0855"), 0)
             if D(compliance_rate) >= D("0.90") else Decimal(0))
    ooh = (round_half_up(tenure_amount * D("0.0405"), 0)
           if has_installed_ooh else Decimal(0))
    gross = tenure_amount + bonus + ooh
    penalty = (round_half_up(gross * D("0.25"), 0)
               if has_faulted_meter else Decimal(0))
    return min(int(gross - penalty), INCENTIVE_PERIOD_CAP_CENTS)


# --- deliverable billing (seven rounded steps) ------------------------------
def volume_discount_rate(gross_cents):
    if gross_cents < 80000:
        return D("0.00")
    if gross_cents < 150000:
        return D("0.10")
    return D("0.15")


def late_penalty_rate(gross_cents):
    if gross_cents < 80000:
        return D("0.000")
    if gross_cents < 150000:
        return D("0.015")
    return D("0.025")


def days_late_from_seconds(seconds):
    if seconds <= 0:
        return 0
    return max(0, int(math.ceil(seconds / 86400.0)))


def billing(tier_base_fee_cents, requested_cell_count, days_late):
    gross = int(tier_base_fee_cents) + int(requested_cell_count) * PER_CELL_SURCHARGE_CENTS
    discount = rhu_int(D(gross) * volume_discount_rate(gross))
    penalty = rhu_int(D(gross) * late_penalty_rate(gross) * D(days_late))
    total = max(0, gross - discount - penalty)
    return {
        "gross_cents": gross,
        "discount_cents": discount,
        "late_penalty_cents": penalty,
        "total_cents": total,
        "days_late": int(days_late),
    }


# --- methodology impact -----------------------------------------------------
def impact_delta(target_rule_set, proposed_rule_set):
    cap_sub = min(D(1), abs(D(proposed_rule_set["outlier_weight_ratio_cap"])
                            - D(target_rule_set["outlier_weight_ratio_cap"]))
                  / D("2.5"))
    tuning_sub = min(D(1), abs(D(proposed_rule_set["invalid_tuning_max_minutes"])
                               - D(target_rule_set["invalid_tuning_max_minutes"]))
                     / D(300))
    ascr_sub = min(D(1),
                   abs(D(proposed_rule_set["missing_interval_ascription_minutes"])
                       - D(target_rule_set["missing_interval_ascription_minutes"]))
                   / D(60))
    pct = round_half_up(D("0.40") * cap_sub + D("0.35") * tuning_sub
                        + D("0.25") * ascr_sub, 4)
    if pct >= D("0.1500"):
        tier = "MATERIAL"
    elif pct >= D("0.0500"):
        tier = "MODERATE"
    else:
        tier = "MINOR"
    return pct, tier, NOTIFICATION_LEAD_HOURS[tier]


# --- weight capping and redistribution --------------------------------------
def redistribute(rows, ratio_cap):
    """rows: list of dicts with base_weight, already in created_at ASC order.

    Sets adjusted_weight and capped on each row; returns total_weight_mass.
    Single pass: a receiver lifted above the cap is never re-capped.
    """
    count = len(rows)
    if count == 0:
        return Decimal("0.0000")
    mass = sum((D(row["base_weight"]) for row in rows), Decimal(0))
    mean_base = round_half_up(mass / D(count), 4)
    cap = round_half_up(mean_base * D(ratio_cap), 4)
    capped_rows = [row for row in rows if D(row["base_weight"]) > cap]
    if not capped_rows:
        for row in rows:
            row["adjusted_weight"] = round_half_up(D(row["base_weight"]), 4)
            row["capped"] = False
        return round_half_up(mass, 4)
    excess = sum((D(row["base_weight"]) - cap for row in capped_rows), Decimal(0))
    for row in capped_rows:
        row["adjusted_weight"] = cap
        row["capped"] = True
    receivers = [row for row in rows if D(row["base_weight"]) <= cap]
    receiver_mass = sum((D(row["base_weight"]) for row in receivers), Decimal(0))
    for row in receivers:
        row["capped"] = False
        if receiver_mass > 0:
            share = round_half_up(excess * D(row["base_weight"]) / receiver_mass, 4)
        else:
            share = Decimal("0.0000")
        row["adjusted_weight"] = round_half_up(D(row["base_weight"]) + share, 4)
    if receivers:
        adjusted_total = sum((D(row["adjusted_weight"]) for row in rows), Decimal(0))
        drift = round_half_up(mass - adjusted_total, 4)
        if drift != 0:
            receivers[0]["adjusted_weight"] = round_half_up(
                D(receivers[0]["adjusted_weight"]) + drift, 4)
    return round_half_up(mass, 4)
