"""Business logic: calculations (SCAFFOLD §1.3), ledger recompute, state cascades.

All money math uses Decimal with ROUND_HALF_UP per PRD §2.5.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

import db
import errors

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
STEP_PCT = {1: Decimal("0.50"), 2: Decimal("0.60"), 3: Decimal("0.70"),
            4: Decimal("0.80"), 5: Decimal("0.90")}
STEP_HOURS = {2: 2000, 3: 4000, 4: 6000, 5: 8000}
STEP_RTI = {2: 144, 3: 288, 4: 432, 5: 576}
TURNOVER_MINUTES = 30
OVERTIME_CAP = Decimal("1.25")


def round_half_up_cents(value):
    """Round a Decimal to whole cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Entity touch helper — version++/updated_at refresh on any modification
# ---------------------------------------------------------------------------

def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = db.now_iso()


# ---------------------------------------------------------------------------
# Wage step determination (§1.3 wage_step_determination, PRD §3.6)
# ---------------------------------------------------------------------------

def recompute_wage(apprentice):
    """Recompute current_wage_step and current_wage_rate_cents from accumulators.

    Highest step whose BOTH gates hold; rate = base * pct, round-half-up cents.
    Bidirectional — lowering accumulators can lower the step.
    """
    hours = apprentice["ojt_hours_accumulated"]
    rti = apprentice["rti_credits_accumulated"]
    step = 1
    for s in (5, 4, 3, 2):
        if hours >= STEP_HOURS[s] and rti >= STEP_RTI[s]:
            step = s
            break
    apprentice["current_wage_step"] = step
    rate = Decimal(apprentice["journeyman_base_rate_cents"]) * STEP_PCT[step]
    apprentice["current_wage_rate_cents"] = round_half_up_cents(rate)


# ---------------------------------------------------------------------------
# Contribution due (§1.3 contribution_due_cents, PRD §3.3)
# Pinned order: round each line first, then sum.
# ---------------------------------------------------------------------------

def compute_due_cents(lines, rate_cents_per_hour):
    total = 0
    for line in lines:
        line_val = Decimal(str(line["ojt_hours"])) * Decimal(rate_cents_per_hour)
        total += round_half_up_cents(line_val)
    return total


def compute_due_date(period_year, period_month):
    """15th of the month after the period, 00:00:00Z; Dec rolls to next January.

    PRD pins the rendering as "the 15th, 00:00:00Z" — whole seconds, no
    fractional digits.
    """
    if period_month == 12:
        dt = datetime(period_year + 1, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    else:
        dt = datetime(period_year, period_month + 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Instructor payable (§1.3 instructor_payable_cents, PRD §3.5)
# ---------------------------------------------------------------------------

def compute_payable_cents(cls, pay_basis, actual_minutes):
    scheduled_minutes = cls["end_minute"] - cls["start_minute"]
    if pay_basis == "SCHEDULED":
        minutes = scheduled_minutes
    else:  # ACTUAL
        cap = round_half_up_cents(Decimal(scheduled_minutes) * OVERTIME_CAP)
        if actual_minutes > cap:
            raise errors.err_overtime_cap()
        minutes = actual_minutes
    val = Decimal(cls["instructor_rate_cents_per_hour"]) * Decimal(minutes) / Decimal(60)
    return round_half_up_cents(val)


# ---------------------------------------------------------------------------
# Ledger recomputes (PRD §2.6) — eager, in-request
# ---------------------------------------------------------------------------

def recompute_employer_outstanding(employer):
    """outstanding = sum(contribution_due_cents) over SUBMITTED|FLAGGED|DELINQUENT."""
    total = 0
    for r in db.contribution_reports.values():
        if r["employer_id"] == employer["id"] and r["status"] in ("SUBMITTED", "FLAGGED", "DELINQUENT"):
            total += r["contribution_due_cents"] or 0
    if employer["outstanding_cents"] != total:
        employer["outstanding_cents"] = total
        touch(employer)


def recompute_allocation(allocation):
    """encumbered = APPROVED purchases; spent = PURCHASED; remaining = amount - both."""
    enc = 0
    spent = 0
    for p in db.equipment_purchases.values():
        if p["allocation_id"] == allocation["id"]:
            if p["status"] == "APPROVED":
                enc += p["amount_cents"]
            elif p["status"] == "PURCHASED":
                spent += p["amount_cents"]
    remaining = allocation["amount_cents"] - enc - spent
    if (allocation["encumbered_cents"] != enc or allocation["spent_cents"] != spent
            or allocation["remaining_cents"] != remaining):
        allocation["encumbered_cents"] = enc
        allocation["spent_cents"] = spent
        allocation["remaining_cents"] = remaining
        touch(allocation)


def recompute_fund(fund, bump_version=False):
    """Recompute the four ledger counters + delinquent count + posture.

    When bump_version is True this is one of the five version-advancing events
    of PRD §2.9, so the fund's version/updated_at advance even if the derived
    values happen not to change.
    """
    contribs = 0
    for r in db.contribution_reports.values():
        if r["status"] == "PAID":
            emp = db.employers.get(r["employer_id"])
            if emp and emp["trust_fund_id"] == fund["id"]:
                contribs += r["contribution_due_cents"] or 0

    disbursed = 0
    for c in db.instructor_pay_claims.values():
        if c["status"] == "PAID":
            cls = db.training_classes.get(c["class_id"])
            if cls and cls["trust_fund_id"] == fund["id"]:
                disbursed += c["payable_cents"]
    for p in db.equipment_purchases.values():
        if p["status"] == "PURCHASED":
            alloc = db.funding_allocations.get(p["allocation_id"])
            if alloc and alloc["trust_fund_id"] == fund["id"]:
                disbursed += p["amount_cents"]

    alloc_remaining = 0
    for a in db.funding_allocations.values():
        if a["trust_fund_id"] == fund["id"] and a["status"] == "ACTIVE":
            alloc_remaining += a["remaining_cents"]

    delinq_count = 0
    for e in db.employers.values():
        if e["trust_fund_id"] == fund["id"] and e["status"] == "DELINQUENT":
            delinq_count += 1

    changed = (
        fund["contributions_received_cents"] != contribs
        or fund["disbursed_cents"] != disbursed
        or fund["allocated_remaining_cents"] != alloc_remaining
        or fund["delinquent_employer_count"] != delinq_count
    )
    fund["contributions_received_cents"] = contribs
    fund["disbursed_cents"] = disbursed
    fund["allocated_remaining_cents"] = alloc_remaining
    fund["available_cents"] = contribs - disbursed - alloc_remaining
    fund["delinquent_employer_count"] = delinq_count
    fund["posture"] = "COMPLIANCE_HOLD" if delinq_count >= 1 else "OPERATING"
    if changed or bump_version:
        touch(fund)


def recompute_enrolled_count(cls):
    count = 0
    for e in db.class_enrollments.values():
        if e["class_id"] == cls["id"] and e["status"] == "ENROLLED":
            count += 1
    if cls["enrolled_count"] != count:
        cls["enrolled_count"] = count
        touch(cls)


# ---------------------------------------------------------------------------
# Employer delinquency recompute (drives posture)
# ---------------------------------------------------------------------------

def recompute_employer_status(employer):
    """Employer is DELINQUENT iff it has >= 1 DELINQUENT report."""
    has_delinq = any(
        r["employer_id"] == employer["id"] and r["status"] == "DELINQUENT"
        for r in db.contribution_reports.values()
    )
    new_status = "DELINQUENT" if has_delinq else "ACTIVE"
    if employer["status"] != new_status:
        employer["status"] = new_status
        touch(employer)


def recompute_fund_posture(fund):
    """Lightweight posture/count recompute without touching the ledger counters."""
    delinq_count = 0
    for e in db.employers.values():
        if e["trust_fund_id"] == fund["id"] and e["status"] == "DELINQUENT":
            delinq_count += 1
    new_posture = "COMPLIANCE_HOLD" if delinq_count >= 1 else "OPERATING"
    if fund["delinquent_employer_count"] != delinq_count or fund["posture"] != new_posture:
        fund["delinquent_employer_count"] = delinq_count
        fund["posture"] = new_posture
        touch(fund)


# ---------------------------------------------------------------------------
# Report line validation (shared by submit / resubmit)
# ---------------------------------------------------------------------------

def validate_report_lines(employer, lines):
    """Line rules: non-empty, one line per apprentice, apprentice exists,
    belongs to this employer, and is INDENTURED or SUSPENDED.

    Priority ordering within line checks per PRD §3.3: employer match first
    (ERR_LINE_EMPLOYER_MISMATCH), then hour eligibility.
    """
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.err_invalid_request("lines must be a non-empty array")
    seen = set()
    # First pass: shape + existence + employer match
    for line in lines:
        if not isinstance(line, dict):
            raise errors.err_invalid_request("each line must be an object")
        if "apprentice_id" not in line or line["apprentice_id"] is None:
            raise errors.err_invalid_request("line missing apprentice_id")
        if "ojt_hours" not in line or line["ojt_hours"] is None:
            raise errors.err_invalid_request("line missing ojt_hours")
        if not isinstance(line["apprentice_id"], str):
            raise errors.err_invalid_request("apprentice_id must be a string")
        if not (isinstance(line["ojt_hours"], (int, float)) and not isinstance(line["ojt_hours"], bool)):
            raise errors.err_invalid_request("ojt_hours must be a number")
        if line["ojt_hours"] < 0:
            raise errors.err_invalid_request("ojt_hours must be >= 0")
        ap_id = line["apprentice_id"]
        if ap_id in seen:
            raise errors.err_invalid_request("one line per apprentice")
        seen.add(ap_id)
        appr = db.apprentices.get(ap_id)
        if appr is None:
            raise errors.err_apprentice_not_found()
        if appr["employer_id"] != employer["id"]:
            raise errors.err_line_employer_mismatch()
    # Second pass: hour eligibility
    for line in lines:
        appr = db.apprentices[line["apprentice_id"]]
        if appr["program_status"] not in ("INDENTURED", "SUSPENDED"):
            raise errors.err_apprentice_not_hour_eligible()


def apply_hours_delta(old_lines, new_lines):
    """Debit old line hours, credit new line hours; recompute wage each direction."""
    affected = set()
    for line in old_lines or []:
        appr = db.apprentices.get(line["apprentice_id"])
        if appr is not None:
            appr["ojt_hours_accumulated"] -= line["ojt_hours"]
            affected.add(appr["id"])
    for line in new_lines or []:
        appr = db.apprentices.get(line["apprentice_id"])
        if appr is not None:
            appr["ojt_hours_accumulated"] += line["ojt_hours"]
            affected.add(appr["id"])
    for ap_id in affected:
        appr = db.apprentices[ap_id]
        recompute_wage(appr)
        touch(appr)
