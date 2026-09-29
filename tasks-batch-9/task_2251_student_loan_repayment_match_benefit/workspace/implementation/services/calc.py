"""Calculations of SCAFFOLD 1.3 / PRD 2.6-2.8, 3.3-3.9.

Every monetary quantity is an integer number of cents. Intermediate tier
ceilings are carried at full Decimal precision; reductions to whole cents use
ROUND_HALF_UP (PRD 2.7). Ratios are carried to four decimals, also
ROUND_HALF_UP, and rounded twice -- per participant and again on the group
average (PRD 2.7).
"""

from decimal import Decimal, ROUND_HALF_UP

import db
from db import order_key

ZERO = Decimal(0)
CENT = Decimal(1)
FOUR_DP = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu_cents(value):
    """Reduce a full-precision amount to whole cents, round half up."""
    return int(dec(value).quantize(CENT, rounding=ROUND_HALF_UP))


def rhu4(value):
    return dec(value).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def as_float4(value):
    return float(rhu4(value))


# --------------------------------------------------------------------------
# collection queries
# --------------------------------------------------------------------------

def open_plan_year():
    """The unique plan year in OPEN, or None."""
    for py in db.rows("plan_years"):
        if py["status"] == "OPEN":
            return py
    return None


def periods_of_plan_year(plan_year_id):
    return [p for p in db.rows("payroll_periods")
            if p["plan_year_id"] == plan_year_id]


def contribution_records_of_plan_year(plan_year_id):
    return [c for c in db.rows("contribution_records")
            if c["_plan_year_id"] == plan_year_id]


def contribution_records_of(employee_id, plan_year_id):
    """The employee's payroll lines in the plan year, ordered by the owning
    period's period_number ascending, ties broken by created_at ascending."""
    rows = [c for c in db.rows("contribution_records")
            if c["_plan_year_id"] == plan_year_id
            and c["employee_id"] == employee_id]
    return sorted(rows, key=lambda c: (c["_period_number"], order_key(c)))


def allocations_of(employee_id, plan_year_id):
    return [a for a in db.rows("match_allocations")
            if a["plan_year_id"] == plan_year_id
            and a["employee_id"] == employee_id]


def allocations_of_plan_year(plan_year_id):
    return [a for a in db.rows("match_allocations")
            if a["plan_year_id"] == plan_year_id]


def allocations_of_batch(batch_id):
    return [a for a in db.rows("match_allocations")
            if a["funding_batch_id"] == batch_id]


def certifications_of(employee_id, plan_year_id):
    return [c for c in db.rows("loan_certifications")
            if c["plan_year_id"] == plan_year_id
            and c["employee_id"] == employee_id]


def lines_of(certification_id):
    return [l for l in db.rows("certification_lines")
            if l["certification_id"] == certification_id]


def adjustments_of(employee_id, plan_year_id):
    return [a for a in db.rows("correction_adjustments")
            if a["plan_year_id"] == plan_year_id
            and a["employee_id"] == employee_id]


def forfeitures_of_plan_year(plan_year_id):
    return [f for f in db.rows("forfeiture_records")
            if f["plan_year_id"] == plan_year_id]


def batches_of_plan_year(plan_year_id):
    return [b for b in db.rows("funding_batches")
            if b["plan_year_id"] == plan_year_id]


RESERVED_CERT_STATUSES = ("SUBMITTED", "ACCEPTED", "AUDIT_HOLD")
CLAIMED_CERT_STATUSES = ("ACCEPTED", "AUDIT_HOLD")
LIVE_FUNDING_STATUSES = ("SCHEDULED", "FUNDED")
OCCUPYING_FUNDING_STATUSES = ("UNFUNDED", "SCHEDULED", "FUNDED")


# --------------------------------------------------------------------------
# employee year-to-date aggregates (PRD 3.2)
# --------------------------------------------------------------------------

def ytd_eligible_compensation(employee_id, plan_year_id):
    return sum(c["counted_compensation_cents"]
               for c in contribution_records_of(employee_id, plan_year_id))


def ytd_deferral(employee_id, plan_year_id):
    return sum(c["elective_deferral_cents"]
               for c in contribution_records_of(employee_id, plan_year_id))


def ytd_deferral_match(employee_id, plan_year_id):
    return sum(c["deferral_match_cents"]
               for c in contribution_records_of(employee_id, plan_year_id))


def ytd_qslp_match(employee_id, plan_year_id):
    return sum(a["amount_cents"]
               for a in allocations_of(employee_id, plan_year_id)
               if a["funding_status"] in LIVE_FUNDING_STATUSES)


def reserved_certified(employee_id, plan_year_id, exclude_id=None):
    total = 0
    for cert in certifications_of(employee_id, plan_year_id):
        if exclude_id is not None and cert["id"] == exclude_id:
            continue
        if cert["status"] in RESERVED_CERT_STATUSES:
            total += certified_total(cert)
    return total


def remaining_qslp_space(employee_id):
    """PRD 3.2 -- null when no plan year is OPEN."""
    py = open_plan_year()
    if py is None:
        return None
    limit = py["annual_deferral_limit_cents"]
    value = (limit
             - ytd_deferral(employee_id, py["id"])
             - reserved_certified(employee_id, py["id"]))
    return max(value, 0)


def vested_pct(months):
    months = int(months or 0)
    if months < 24:
        return Decimal("0.00")
    if months < 36:
        return Decimal("0.40")
    if months < 48:
        return Decimal("0.60")
    if months < 60:
        return Decimal("0.80")
    return Decimal("1.00")


def hce_flag_against(employee, plan_year):
    if plan_year is None:
        return False
    return (employee["prior_year_compensation_cents"]
            > plan_year["hce_prior_comp_threshold_cents"])


def hce_flag(employee):
    return hce_flag_against(employee, open_plan_year())


# --------------------------------------------------------------------------
# leave (PRD 3.2 / SCAFFOLD calculations.unpaid_leave_days)
# --------------------------------------------------------------------------

def whole_days_inclusive(start, end):
    """The whole number of days between start and end, plus one."""
    delta = end - start
    return delta.days + 1


def unpaid_leave_days_ytd(employee_id, plan_year=None, extra=None):
    """Merged unpaid-leave day count inside the OPEN plan-year window."""
    py = plan_year if plan_year is not None else open_plan_year()
    if py is None:
        return 0
    window_start = py["_period_start_dt"]
    window_end = py["_period_end_dt"]
    buffer_days = int(py["leave_merge_buffer_days"])

    events = [e for e in db.rows("leave_events")
              if e["employee_id"] == employee_id and e["leave_type"] == "UNPAID"]
    intervals = [(e["_start_dt"], e["_end_dt"]) for e in events]
    if extra is not None:
        intervals.append(extra)

    spans = []
    for start, end in intervals:
        if end < window_start or start > window_end:
            continue
        spans.append((max(start, window_start), min(end, window_end)))
    if not spans:
        return 0
    spans.sort(key=lambda s: (s[0], s[1]))

    from datetime import timedelta
    merged = [list(spans[0])]
    for start, end in spans[1:]:
        prev = merged[-1]
        if start <= prev[1] + timedelta(days=buffer_days):
            if end > prev[1]:
                prev[1] = end
        else:
            merged.append([start, end])
    return sum(whole_days_inclusive(s, e) for s, e in merged)


# --------------------------------------------------------------------------
# certification derived totals (PRD 3.4 / 3.5)
# --------------------------------------------------------------------------

def certified_total(cert):
    return sum(l["amount_cents"] for l in lines_of(cert["id"]))


def live_allocations_of_cert(cert_id):
    return [a for a in db.rows("match_allocations")
            if a["certification_id"] == cert_id
            and a["funding_status"] in LIVE_FUNDING_STATUSES]


def matched_total(cert):
    return sum(a["amount_cents"] for a in live_allocations_of_cert(cert["id"]))


def unmatched_eligible(cert):
    applied = sum(a["tier1_applied_cents"] + a["tier2_applied_cents"]
                  for a in live_allocations_of_cert(cert["id"]))
    return cert["eligible_total_cents"] - applied


# --------------------------------------------------------------------------
# funding batch derived totals + forfeiture offset waterfall (PRD 3.6)
# --------------------------------------------------------------------------

def batch_allocations_live(batch_id):
    return [a for a in allocations_of_batch(batch_id)
            if a["funding_status"] != "REVERSED"]


def batch_total_allocated(batch):
    return sum(a["amount_cents"] for a in batch_allocations_live(batch["id"]))


def batch_allocation_count(batch):
    return len(batch_allocations_live(batch["id"]))


def forfeiture_waterfall(plan_year_id):
    """Returns ({batch_id: offset}, leftover_pool) over PENDING batches."""
    pool = sum(f["amount_cents"] for f in forfeitures_of_plan_year(plan_year_id))
    offsets = {}
    for batch in batches_of_plan_year(plan_year_id):
        if batch["status"] != "PENDING":
            continue
        total = batch_total_allocated(batch)
        offset = min(pool, total)
        pool -= offset
        offsets[batch["id"]] = offset
    return offsets, pool


def batch_forfeiture_offset(batch):
    if batch["status"] == "PENDING":
        offsets, _ = forfeiture_waterfall(batch["plan_year_id"])
        return offsets.get(batch["id"], 0)
    return int(batch.get("_frozen_offset") or 0)


def batch_net_funding(batch):
    return batch_total_allocated(batch) - batch_forfeiture_offset(batch)


def freeze_batch_offset(batch):
    offsets, _ = forfeiture_waterfall(batch["plan_year_id"])
    batch["_frozen_offset"] = offsets.get(batch["id"], 0)


def plan_year_forfeiture_balance(plan_year_id):
    _, leftover = forfeiture_waterfall(plan_year_id)
    return leftover


# --------------------------------------------------------------------------
# plan-year rollups (PRD 2.8)
# --------------------------------------------------------------------------

def plan_year_total_deferral_match_funded(plan_year_id):
    total = sum(c["deferral_match_cents"]
                for c in contribution_records_of_plan_year(plan_year_id))
    total += sum(a["amount_cents"] for a in db.rows("correction_adjustments")
                 if a["plan_year_id"] == plan_year_id
                 and a["reason_code"] == "ACP_CORRECTIVE_FORFEITURE")
    return total


def plan_year_total_qslp_match_funded(plan_year_id):
    total = sum(a["amount_cents"] for a in allocations_of_plan_year(plan_year_id)
                if a["funding_status"] in LIVE_FUNDING_STATUSES)
    total += sum(a["amount_cents"] for a in db.rows("correction_adjustments")
                 if a["plan_year_id"] == plan_year_id
                 and a["reason_code"] == "TRUE_UP_RECOUPMENT")
    return total


def plan_year_accepted_certification_count(plan_year_id):
    return len([c for c in db.rows("loan_certifications")
                if c["plan_year_id"] == plan_year_id
                and c["status"] in CLAIMED_CERT_STATUSES])


def period_total_eligible_compensation(period):
    return sum(c["counted_compensation_cents"]
               for c in db.rows("contribution_records")
               if c["payroll_period_id"] == period["id"])


def period_total_deferral_match(period):
    return sum(c["deferral_match_cents"]
               for c in db.rows("contribution_records")
               if c["payroll_period_id"] == period["id"])


# --------------------------------------------------------------------------
# calculations.deferral_match_per_period (PRD 3.3)
# --------------------------------------------------------------------------

def deferral_match_per_period(plan_year, employee_id, period_number,
                             eligible_cents, deferral_cents):
    prior_counted = sum(
        c["counted_compensation_cents"]
        for c in contribution_records_of(employee_id, plan_year["id"])
        if c["_period_number"] < period_number)
    cap = plan_year["compensation_cap_cents"]
    counted = min(eligible_cents, max(cap - prior_counted, 0))

    tier1_pct = dec(plan_year["tier1_pct"])
    tier2_pct = dec(plan_year["tier2_pct"])
    rate1 = dec(plan_year["tier1_match_rate"])
    rate2 = dec(plan_year["tier2_match_rate"])

    ceiling1 = dec(counted) * tier1_pct
    ceiling2 = dec(counted) * tier2_pct
    deferral = dec(deferral_cents)

    used1 = min(deferral, ceiling1)
    excess = deferral - ceiling1
    if excess < ZERO:
        excess = ZERO
    used2 = min(ceiling2, excess)

    match = rhu_cents(used1 * rate1 + used2 * rate2)
    space1 = ceiling1 - used1
    space2 = ceiling2 - used2
    return {
        "counted_compensation_cents": counted,
        "deferral_match_cents": match,
        "qslp_space_tier1_cents": rhu_cents(space1 if space1 > ZERO else ZERO),
        "qslp_space_tier2_cents": rhu_cents(space2 if space2 > ZERO else ZERO),
    }


# --------------------------------------------------------------------------
# calculations.qslp_eligible_amount (PRD 3.5)
# --------------------------------------------------------------------------

def qslp_eligible_amount(cert, plan_year):
    employee_id = cert["employee_id"]
    prior_claimed = 0
    for other in certifications_of(employee_id, plan_year["id"]):
        if other["id"] == cert["id"]:
            continue
        if other["status"] in CLAIMED_CERT_STATUSES:
            prior_claimed += other["eligible_total_cents"]
    room = (plan_year["annual_deferral_limit_cents"]
            - ytd_deferral(employee_id, plan_year["id"])
            - prior_claimed)
    room = max(room, 0)
    certified = certified_total(cert)
    eligible = min(certified, room)
    return eligible, (eligible < certified)


# --------------------------------------------------------------------------
# calculations.qslp_mirror_allocation (PRD 3.5)
# --------------------------------------------------------------------------

def qslp_mirror_plan(cert, plan_year):
    """Returns (list of allocation drafts, leftover pool)."""
    employee_id = cert["employee_id"]
    remaining = cert["eligible_total_cents"]
    rate1 = dec(plan_year["tier1_match_rate"])
    rate2 = dec(plan_year["tier2_match_rate"])
    drafts = []
    for record in contribution_records_of(employee_id, plan_year["id"]):
        if remaining <= 0:
            break
        period_id = record["payroll_period_id"]
        used1 = 0
        used2 = 0
        for alloc in allocations_of(employee_id, plan_year["id"]):
            if (alloc["payroll_period_id"] == period_id
                    and alloc["funding_status"] in OCCUPYING_FUNDING_STATUSES):
                used1 += alloc["tier1_applied_cents"]
                used2 += alloc["tier2_applied_cents"]
        free1 = max(record["qslp_space_tier1_cents"] - used1, 0)
        free2 = max(record["qslp_space_tier2_cents"] - used2, 0)
        take1 = min(remaining, free1)
        remaining -= take1
        take2 = min(remaining, free2)
        remaining -= take2
        amount = rhu_cents(dec(take1) * rate1 + dec(take2) * rate2)
        if amount > 0:
            drafts.append({
                "payroll_period_id": period_id,
                "tier1_applied_cents": take1,
                "tier2_applied_cents": take2,
                "amount_cents": amount,
            })
    return drafts, remaining


# --------------------------------------------------------------------------
# calculations.qslp_annual_true_up (PRD 3.8)
# --------------------------------------------------------------------------

def annual_true_up_delta(employee_id, plan_year, run_seq):
    """The four pinned steps, in order."""
    records = contribution_records_of(employee_id, plan_year["id"])

    # Step one.
    comp_year = min(sum(c["counted_compensation_cents"] for c in records),
                    plan_year["compensation_cap_cents"])

    # Step two.
    qslp_eligible_year = sum(
        c["eligible_total_cents"]
        for c in certifications_of(employee_id, plan_year["id"])
        if c["status"] in CLAIMED_CERT_STATUSES)
    combined = dec(sum(c["elective_deferral_cents"] for c in records)
                   + qslp_eligible_year)
    tier1_pct = dec(plan_year["tier1_pct"])
    tier2_pct = dec(plan_year["tier2_pct"])
    rate1 = dec(plan_year["tier1_match_rate"])
    rate2 = dec(plan_year["tier2_match_rate"])
    ceiling1 = dec(comp_year) * tier1_pct
    ceiling2 = dec(comp_year) * tier2_pct
    portion1 = min(combined, ceiling1)
    excess = combined - ceiling1
    if excess < ZERO:
        excess = ZERO
    portion2 = min(ceiling2, excess)
    entitlement = rhu_cents(portion1 * rate1 + portion2 * rate2)

    # Step three.
    funded_deferral = sum(c["deferral_match_cents"] for c in records)
    funded_qslp = sum(a["amount_cents"]
                      for a in allocations_of(employee_id, plan_year["id"])
                      if a["funding_status"] in LIVE_FUNDING_STATUSES
                      and a["_seq"] < run_seq)
    recouped = sum(a["amount_cents"]
                   for a in adjustments_of(employee_id, plan_year["id"])
                   if a["reason_code"] == "TRUE_UP_RECOUPMENT")

    # Step four.
    return entitlement - funded_deferral - funded_qslp - recouped


def true_up_target_batch(plan_year_id):
    """Highest period_number among PENDING batches, ties earliest created_at."""
    candidates = []
    for batch in batches_of_plan_year(plan_year_id):
        if batch["status"] != "PENDING":
            continue
        period = db.db.payroll_periods.get(batch["payroll_period_id"])
        number = period["period_number"] if period else 0
        candidates.append((-number, order_key(batch), batch))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


# --------------------------------------------------------------------------
# calculations.acp_test (PRD 3.9)
# --------------------------------------------------------------------------

def acp_participants(plan_year, include_qslp_match):
    """Ordered by Employee.created_at ascending."""
    out = []
    for employee in db.rows("employees"):
        records = contribution_records_of(employee["id"], plan_year["id"])
        if not records:
            continue
        denominator = sum(c["counted_compensation_cents"] for c in records)
        if denominator <= 0:
            continue
        numerator = sum(c["deferral_match_cents"] for c in records)
        if include_qslp_match:
            numerator += sum(
                a["amount_cents"]
                for a in allocations_of(employee["id"], plan_year["id"])
                if a["funding_status"] in LIVE_FUNDING_STATUSES)
        numerator += sum(
            a["amount_cents"]
            for a in adjustments_of(employee["id"], plan_year["id"])
            if a["reason_code"] in ("ACP_CORRECTIVE_FORFEITURE",
                                    "TRUE_UP_RECOUPMENT"))
        ratio = rhu4(dec(numerator) / dec(denominator))
        out.append({
            "employee": employee,
            "hce": hce_flag_against(employee, plan_year),
            "denominator": denominator,
            "ratio": ratio,
        })
    return out


def acp_test(plan_year, test_method, include_qslp_match):
    """Returns a result dict, or {'error': 'ERR_NO_NHCE_POPULATION'}."""
    participants = acp_participants(plan_year, include_qslp_match)
    hces = [p for p in participants if p["hce"]]
    nhces = [p for p in participants if not p["hce"]]
    if not nhces:
        return {"error": "ERR_NO_NHCE_POPULATION"}

    if hces:
        hce_acp = rhu4(sum((p["ratio"] for p in hces), ZERO) / dec(len(hces)))
    else:
        hce_acp = rhu4(ZERO)

    if test_method == "CURRENT_YEAR":
        nhce_acp = rhu4(sum((p["ratio"] for p in nhces), ZERO)
                        / dec(len(nhces)))
    else:
        nhce_acp = rhu4(plan_year["prior_year_nhce_acp"])

    candidate_a = nhce_acp * dec("1.25")
    candidate_b = min(nhce_acp * dec(2), nhce_acp + dec("0.02"))
    limit_acp = rhu4(max(candidate_a, candidate_b))

    return {
        "hce_acp": hce_acp,
        "nhce_acp": nhce_acp,
        "limit_acp": limit_acp,
        "hce_count": len(hces),
        "nhce_count": len(nhces),
        "participants": participants,
        "passed": hce_acp <= limit_acp,
    }
