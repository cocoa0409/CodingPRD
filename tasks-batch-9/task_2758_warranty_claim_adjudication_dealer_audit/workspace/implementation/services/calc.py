"""The nine calculations of the specification (PRD 3.3 - 3.9)."""

from decimal import Decimal

import db
from util import as_date, dec, elapsed_months, rhu, rhu4

# ---- constants, all read from the specification ----
HIGH_VALUE_THRESHOLD_CENTS = 150000
NARRATIVE_THIN_CHARS = 20
NARRATIVE_FLOOR_CHARS = 10
OVERLAP_BUFFER_DAYS = 30
REPEAT_REPAIR_WINDOW_DAYS = 180
MAX_STEP_UP_PCT = Decimal("0.25")
TIME_AND_PRICE_STEP_PCT = Decimal("0.10")
NOT_AVAILABLE_SHARE = Decimal("0.50")
EXTRAPOLATION_FULL_TIER = Decimal("0.10")
EXTRAPOLATION_HALF_TIER = Decimal("0.05")
ADJUDICATOR_BASE_LIMIT_CENTS = Decimal("50000")
MANAGER_BASE_LIMIT_CENTS = Decimal("250000")
GOODWILL_DECAY_FACTOR = Decimal("2.0")
GOODWILL_MAX_SHARE = Decimal("0.80")
ANALYTICS_WINDOW_DAYS = 365
OUTLIER_RATIO_THRESHOLD = Decimal("1.50")
PROBATION_THRESHOLD_CENTS = 90000
SUSPENSION_THRESHOLD_CENTS = 200000

LIVE_CLAIM_STATUSES = ("SUBMITTED", "SUSPENDED", "APPROVED")


# ---------------------------------------------------------------- coverage
def months_and_miles(claim, vehicle):
    months = elapsed_months(as_date(vehicle["warranty_start_date"]), as_date(claim["repair_date"]))
    miles = claim["odometer_at_repair"] - vehicle["in_service_odometer"]
    return months, miles


def claim_coverage_determination(claim, vehicle, operation):
    """PRD 3.3: powertrain terms first and only for a POWERTRAIN operation."""
    months, miles = months_and_miles(claim, vehicle)
    if operation["category"] == "POWERTRAIN":
        if months <= vehicle["powertrain_months"] and miles <= vehicle["powertrain_miles"]:
            return "POWERTRAIN"
    if months <= vehicle["basic_months"] and miles <= vehicle["basic_miles"]:
        return "BASIC"
    return "NONE"


# ---------------------------------------------------------------- reimbursement
def price(rate_cents, markup_pct, hours, qty, part):
    """The two-step arithmetic shared by both pricing variants (PRD 3.4 / 3.6).

    Labor: exactly one rounding, on the product. Parts: the pinned rounding
    order -- the marked-up UNIT price is rounded first, then multiplied by the
    quantity as an exact integer multiplication.
    """
    labor = rhu(dec(hours) * dec(rate_cents))
    if part is None:
        parts = 0
    else:
        unit = rhu(dec(part["dealer_net_cents"]) * (Decimal("1") + dec(markup_pct)))
        parts = unit * int(qty or 0)
    return labor, parts, labor + parts


# ---------------------------------------------------------------- labor rate ceiling
def labor_rate_statutory_ceiling(profile, dealer, sample_median_rate_cents):
    current = dec(dealer["approved_labor_rate_cents"])
    absolute = profile["max_labor_rate_cents"]
    if profile["labor_rate_method"] == "RETAIL_SAMPLE":
        step_up_floor = rhu(current * (Decimal("1") + MAX_STEP_UP_PCT))
        candidate = max(int(sample_median_rate_cents), step_up_floor)
        return min(candidate, absolute)
    step_up = rhu(current * (Decimal("1") + TIME_AND_PRICE_STEP_PCT))
    return min(step_up, absolute)


# ---------------------------------------------------------------- edit engine
def repeat_repair_candidate(claim, operation):
    """PRD 3.4: latest qualifying prior claim, ties broken by earliest created_at."""
    repair_date = as_date(claim["repair_date"])
    best = None
    for other in db.ordered(db.claims):
        if other["id"] == claim["id"]:
            continue
        if other["dealer_id"] != claim["dealer_id"] or other["vehicle_id"] != claim["vehicle_id"]:
            continue
        if other["status"] not in LIVE_CLAIM_STATUSES:
            continue
        other_op = db.labor_operations.get(other["labor_operation_id"])
        if other_op is None or other_op["overlap_group"] != operation["overlap_group"]:
            continue
        gap = (repair_date - as_date(other["repair_date"])).days
        if gap <= OVERLAP_BUFFER_DAYS or gap > REPEAT_REPAIR_WINDOW_DAYS:
            continue
        if best is None:
            best = other
            continue
        best_date = as_date(best["repair_date"])
        other_date = as_date(other["repair_date"])
        if other_date > best_date:
            best = other
        elif other_date == best_date and db.sort_key(other) < db.sort_key(best):
            best = other
    return best


def claim_edit_engine(claim, operation):
    """Return the fresh edit set in its fixed append order."""
    edits = []
    hours = dec(claim["claimed_labor_hours"])
    standard = dec(operation["standard_time_hours"])
    if hours > standard:
        edits.append(
            (
                "EXCESSIVE_TIME",
                "SUSPEND",
                "Claimed labor hours %s exceed the operation's standard time of %s hours."
                % (hours, standard),
                None,
            )
        )
    if claim["provisional_total_cents"] >= HIGH_VALUE_THRESHOLD_CENTS:
        edits.append(
            (
                "HIGH_VALUE",
                "SUSPEND",
                "Provisional total %d cents reaches the high-value threshold of %d cents."
                % (claim["provisional_total_cents"], HIGH_VALUE_THRESHOLD_CENTS),
                None,
            )
        )
    if claim["coverage_type"] == "NONE":
        edits.append(("NO_COVERAGE", "SUSPEND", "The repair falls outside the vehicle's warranty terms.", None))
    correction = claim.get("correction_text") or ""
    if len(correction) < NARRATIVE_THIN_CHARS:
        edits.append(
            (
                "NARRATIVE_THIN",
                "WARN",
                "Correction text is shorter than %d characters." % NARRATIVE_THIN_CHARS,
                None,
            )
        )
    prior = repeat_repair_candidate(claim, operation)
    if prior is not None:
        edits.append(
            (
                "REPEAT_REPAIR",
                "WARN",
                "A prior repair in the same overlap group occurred between %d and %d days earlier."
                % (OVERLAP_BUFFER_DAYS + 1, REPEAT_REPAIR_WINDOW_DAYS),
                prior["id"],
            )
        )
    return edits


# ---------------------------------------------------------------- parts debit
def parts_non_return_debit(reason, claim):
    if reason == "DEFECT_CONFIRMED":
        return 0
    if reason == "NO_DEFECT_FOUND":
        return int(claim.get("approved_parts_amount_cents") or 0)
    if reason == "NOT_AVAILABLE":
        return rhu(dec(claim.get("approved_parts_amount_cents") or 0) * NOT_AVAILABLE_SHARE)
    if reason == "NOT_RETURNED":
        return int(claim.get("approved_total_cents") or 0)
    return 0


# ---------------------------------------------------------------- goodwill limits
def goodwill_authorization_limit(claim, vehicle):
    """PRD 3.5: the out-of-warranty margin and the two decaying authority limits."""
    if claim["coverage_type"] != "NONE":
        margin = Decimal("0.0000")
    else:
        months, _miles = months_and_miles(claim, vehicle)
        miles_overrun = claim["odometer_at_repair"] - vehicle["in_service_odometer"] - vehicle["basic_miles"]
        miles_overrun = max(0, miles_overrun)
        months_overrun = max(0, months - vehicle["basic_months"])
        miles_fraction = dec(miles_overrun) / dec(vehicle["basic_miles"])
        months_fraction = dec(months_overrun) / dec(vehicle["basic_months"])
        margin = rhu4(max(miles_fraction, months_fraction))
    decay = Decimal("1") - GOODWILL_DECAY_FACTOR * margin
    if decay < 0:
        decay = Decimal("0")
    share_cap = rhu(dec(claim["provisional_total_cents"]) * GOODWILL_MAX_SHARE)
    adjudicator_limit = min(share_cap, rhu(ADJUDICATOR_BASE_LIMIT_CENTS * decay))
    manager_limit = min(share_cap, rhu(MANAGER_BASE_LIMIT_CENTS * decay))
    return margin, adjudicator_limit, manager_limit


# ---------------------------------------------------------------- audit extrapolation
def in_period(claim, audit):
    repair_date = as_date(claim["repair_date"])
    return as_date(audit["period_start"]) <= repair_date < as_date(audit["period_end"])


def audit_findings_of(audit_id):
    return [f for f in db.ordered(db.findings) if f["audit_id"] == audit_id]


def extrapolation_steps_3_to_6(audit):
    """Steps 3-6, always against the audit's persisted snapshots."""
    sample_chargeback = 0
    for finding in audit_findings_of(audit["id"]):
        if finding["status"] in ("OPEN", "CHARGED_BACK", "UPHELD"):
            sample_chargeback += finding["unsupported_amount_cents"]
    if audit["sample_paid_snapshot_cents"] == 0:
        error_rate = Decimal("0.0000")
    else:
        error_rate = rhu4(dec(sample_chargeback) / dec(audit["sample_paid_snapshot_cents"]))
    if error_rate >= EXTRAPOLATION_FULL_TIER:
        factor = Decimal("1.00")
    elif error_rate >= EXTRAPOLATION_HALF_TIER:
        factor = Decimal("0.50")
    else:
        factor = Decimal("0.00")
    extrapolated = rhu(dec(audit["population_paid_snapshot_cents"]) * error_rate * factor)
    return sample_chargeback, error_rate, factor, extrapolated, sample_chargeback + extrapolated


def apply_steps_3_to_6(audit):
    sample, error_rate, factor, extrapolated, total = extrapolation_steps_3_to_6(audit)
    audit["sample_chargeback_cents"] = sample
    audit["error_rate"] = error_rate
    audit["extrapolation_factor"] = factor
    audit["extrapolated_chargeback_cents"] = extrapolated
    audit["total_chargeback_cents"] = total
    return audit


# ---------------------------------------------------------------- posture band
def posture_for(balance_cents):
    if balance_cents >= SUSPENSION_THRESHOLD_CENTS:
        return "SUSPENDED"
    if balance_cents >= PROBATION_THRESHOLD_CENTS:
        return "PROBATION"
    return "ACTIVE"


POSTURE_RANK = {"ACTIVE": 0, "PROBATION": 1, "SUSPENDED": 2}


# ---------------------------------------------------------------- expense analytics
def _in_window(claim, window_start, window_end):
    repair_date = as_date(claim["repair_date"])
    return window_start <= repair_date < window_end


def expense_bases(dealer_id, window_start, window_end):
    """Both numerators and both claim counts over the half-open repair-date window."""
    paid_total = 0
    paid_count = 0
    incurred_total = 0
    incurred_count = 0
    for claim in db.ordered(db.claims):
        if claim["dealer_id"] != dealer_id or claim["status"] != "APPROVED":
            continue
        if not _in_window(claim, window_start, window_end):
            continue
        amount = int(claim.get("approved_total_cents") or 0)
        incurred_total += amount
        incurred_count += 1
        if claim["payment_status"] == "PAID":
            paid_total += amount
            paid_count += 1
    return paid_total, paid_count, incurred_total, incurred_count


def per_vehicle(numerator_cents, vehicles_in_operation):
    if not vehicles_in_operation:
        return 0
    return rhu(dec(numerator_cents) / dec(vehicles_in_operation))


def peer_median_paid(window_start, window_end):
    """Paid-basis peer median: every dealer with vehicles_in_operation > 0 participates."""
    samples = []
    for peer in db.ordered(db.dealers):
        if peer["vehicles_in_operation"] <= 0:
            continue
        paid_total, _pc, _it, _ic = expense_bases(peer["id"], window_start, window_end)
        samples.append((per_vehicle(paid_total, peer["vehicles_in_operation"]), db.sort_key(peer)))
    if not samples:
        return 0
    samples.sort(key=lambda pair: (pair[0], pair[1]))
    values = [pair[0] for pair in samples]
    count = len(values)
    middle = count // 2
    if count % 2 == 1:
        return values[middle]
    return rhu(dec(values[middle - 1] + values[middle]) / Decimal("2"))


def outlier_ratio_of(own_per_vehicle, median):
    if median == 0:
        return Decimal("0.0000")
    return rhu4(dec(own_per_vehicle) / dec(median))
