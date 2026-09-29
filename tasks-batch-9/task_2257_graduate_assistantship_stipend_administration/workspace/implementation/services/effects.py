"""Recomputations and server-driven cascades."""
from decimal import Decimal

import calc
from db import db, force_update, update, now_iso, today
from services import queries


# ---------------------------------------------------------------------------
# funding_source_balance (PRD 2.7)
# ---------------------------------------------------------------------------
def recompute_source_balances(source_ids):
    for source_id in sorted(set(sid for sid in source_ids if sid)):
        source = db.funding_sources.get(source_id)
        if source is None:
            continue
        committed = 0
        expended = 0
        for alloc in db.funding_allocations.values():
            if alloc["funding_source_id"] != source_id:
                continue
            if alloc["status"] == "COMMITTED":
                committed += (alloc["allocated_stipend_cents"]
                              + alloc["allocated_remission_cents"]
                              - alloc["disbursed_amount_cents"])
                expended += alloc["disbursed_amount_cents"]
            elif alloc["status"] == "EXPENDED":
                expended += (alloc["allocated_stipend_cents"]
                             + alloc["allocated_remission_cents"])
        available = source["authorized_amount_cents"] - committed - expended
        update(source,
               committed_amount_cents=committed,
               expended_amount_cents=expended,
               available_amount_cents=available)


def auto_reinstate(source_ids):
    """Only OVERCOMMITMENT suspensions clear themselves (PRD 3.3)."""
    for source_id in sorted(set(sid for sid in source_ids if sid)):
        source = db.funding_sources.get(source_id)
        if source is None:
            continue
        if (source["status"] == "SUSPENDED"
                and source["suspension_reason"] == "OVERCOMMITMENT"
                and source["available_amount_cents"] >= source["auto_reinstate_threshold_cents"]):
            update(source, status="ACTIVE", suspension_reason=None)


def release_allocations(allocations, release_reason):
    """Move allocations to RELEASED with amounts zeroed; returns touched sources."""
    touched = []
    for alloc in allocations:
        update(alloc,
               status="RELEASED",
               allocated_stipend_cents=0,
               allocated_remission_cents=0,
               release_reason=release_reason)
        touched.append(alloc["funding_source_id"])
    recompute_source_balances(touched)
    auto_reinstate(touched)
    return touched


# ---------------------------------------------------------------------------
# student_effort_aggregate
# ---------------------------------------------------------------------------
def counted_appointments(student_id):
    return [a for a in db.appointments.values()
            if a["student_id"] == student_id
            and a["lifecycle_status"] in calc.COUNTED_EFFORT_STATUSES]


def overlapping_counted(student_id, candidate):
    """Counted appointments of the student, other than the candidate, whose
    inclusive window intersects the candidate's inclusive window."""
    return [a for a in counted_appointments(student_id)
            if a["id"] != candidate["id"]
            and a["start_date"] <= candidate["end_date"]
            and a["end_date"] >= candidate["start_date"]]


def candidate_effort_total(student_id, candidate):
    overlapping = overlapping_counted(student_id, candidate)
    total = candidate["effort_pct"] + sum(a["effort_pct"] for a in overlapping)
    return total, overlapping


def recompute_student_effort(student):
    """Persisted aggregate: reference window taken from the most recently
    mutated counted appointment; 0 when the student holds none."""
    counted = counted_appointments(student["id"])
    if not counted:
        total = 0
    else:
        reference = max(counted, key=lambda a: a["_mut"])
        total = sum(a["effort_pct"] for a in counted
                    if a["start_date"] <= reference["end_date"]
                    and a["end_date"] >= reference["start_date"])
    hours = calc.hours_1dp(Decimal(total) * calc.FULL_TIME_WEEKLY_HOURS / Decimal(100))
    force_update(student, total_effort_pct=total, assigned_hours_per_week=hours)


def _effort_figures(student):
    counted = counted_appointments(student["id"])
    if not counted:
        total = 0
    else:
        reference = max(counted, key=lambda a: a["_mut"])
        total = sum(a["effort_pct"] for a in counted
                    if a["start_date"] <= reference["end_date"]
                    and a["end_date"] >= reference["start_date"])
    hours = calc.hours_1dp(Decimal(total) * calc.FULL_TIME_WEEKLY_HOURS / Decimal(100))
    return total, hours


def _ytd_figures(student, tax_calendar_year):
    benefit = 0
    taxable = 0
    for row in db.tax_assessments.values():
        if (row["student_id"] == student["id"]
                and row["status"] == "FINAL"
                and row["tax_calendar_year"] == tax_calendar_year):
            benefit += row["benefit_cents"]
            taxable += row["taxable_cents"]
    return benefit, taxable


def recompute_student_aggregates(student, tax_calendar_year):
    """Effort aggregates and tuition-benefit YTD in a single mutation."""
    total, hours = _effort_figures(student)
    benefit, taxable = _ytd_figures(student, tax_calendar_year)
    force_update(student,
                 total_effort_pct=total,
                 assigned_hours_per_week=hours,
                 tuition_benefit_ytd_cents=benefit,
                 taxable_tuition_benefit_ytd_cents=taxable)


def recompute_student_tax_ytd(student, tax_calendar_year, bump=True):
    benefit = 0
    taxable = 0
    for row in db.tax_assessments.values():
        if (row["student_id"] == student["id"]
                and row["status"] == "FINAL"
                and row["tax_calendar_year"] == tax_calendar_year):
            benefit += row["benefit_cents"]
            taxable += row["taxable_cents"]
    if bump:
        force_update(student,
                     tuition_benefit_ytd_cents=benefit,
                     taxable_tuition_benefit_ytd_cents=taxable)
    else:
        update(student,
               tuition_benefit_ytd_cents=benefit,
               taxable_tuition_benefit_ytd_cents=taxable)


# ---------------------------------------------------------------------------
# tuition_remission_entitlement
# ---------------------------------------------------------------------------
def remission_eligible_allocations(allocations):
    eligible = []
    for alloc in allocations:
        source = db.funding_sources.get(alloc["funding_source_id"])
        if source is not None and source["allows_tuition_remission"]:
            eligible.append(alloc)
    return eligible


def eligible_share_pct(eligible):
    total = Decimal(0)
    for alloc in eligible:
        total += alloc["share_pct"]
    return total


def compute_remission(appointment, student, policy, allocations):
    """Band -> credit cap -> gross -> funding-eligible share -> policy ceiling."""
    band_pct = appointment["tuition_remission_pct"]
    remitted_credits = min(student["enrolled_credit_hours"],
                           calc.MAX_REMITTED_CREDITS[student["degree_level"]])
    gross = calc.rhu_cents(Decimal(remitted_credits)
                           * Decimal(policy["per_credit_tuition_cents"])
                           * Decimal(band_pct) / Decimal(100))
    eligible = remission_eligible_allocations(allocations)
    share = eligible_share_pct(eligible)
    funded = calc.rhu_cents(Decimal(gross) * share / Decimal(100))
    total = min(funded, policy["max_remission_cents_per_term"])
    per_alloc = split_remission_over(total, allocations)
    return total, per_alloc


def split_remission_over(total_cents, allocations):
    """Split total_cents across the remission-eligible allocations only."""
    eligible = remission_eligible_allocations(allocations)
    share = eligible_share_pct(eligible)
    _, amounts = calc.split_remission(total_cents, eligible, share)
    per_alloc = dict((a["id"], 0) for a in allocations)
    per_alloc.update(amounts)
    return per_alloc


# ---------------------------------------------------------------------------
# tuition_benefit_tax_assessment
# ---------------------------------------------------------------------------
def benefit_for(student_id, term_id):
    total = 0
    for appointment in db.appointments.values():
        if (appointment["student_id"] == student_id
                and appointment["term_id"] == term_id
                and appointment["lifecycle_status"] in calc.TAX_COUNTED_STATUSES):
            total += appointment["tuition_remission_cents"]
    return total


def assess_term_provisional(student_id, term_id, cap):
    benefit = benefit_for(student_id, term_id)
    exempt = min(benefit, cap)
    taxable = benefit - exempt
    return benefit, exempt, taxable, calc.withholding(taxable)


def assess_calendar_year_final(assessment, cap):
    benefit = benefit_for(assessment["student_id"], assessment["term_id"])
    prior_final = [row for row in db.tax_assessments.values()
                   if row["student_id"] == assessment["student_id"]
                   and row["tax_calendar_year"] == assessment["tax_calendar_year"]
                   and row["status"] == "FINAL"
                   and row["id"] != assessment["id"]]
    year_benefit = benefit + sum(row["benefit_cents"] for row in prior_final)
    year_exempt = min(year_benefit, cap)
    remaining_cap = max(0, year_exempt - sum(row["exempt_cents"] for row in prior_final))
    exempt = min(benefit, remaining_cap)
    taxable = benefit - exempt
    return benefit, exempt, taxable, calc.withholding(taxable)


# ---------------------------------------------------------------------------
# renewal certification revocation (PRD 3.2)
# ---------------------------------------------------------------------------
def revoke_certifications(student_id):
    appointment_ids = set(a["id"] for a in db.appointments.values()
                          if a["student_id"] == student_id)
    for decision in db.renewal_decisions.values():
        if (decision["appointment_id"] in appointment_ids
                and decision["status"] == "SAP_CERTIFIED"):
            update(decision,
                   status="DRAFT",
                   sap_certified=False,
                   certified_by_user_id=None,
                   certified_at=None,
                   revision_count=decision["revision_count"] + 1)


# ---------------------------------------------------------------------------
# successor cancellation cascade (PRD 3.8)
# ---------------------------------------------------------------------------
CANCELLABLE = ("DRAFT", "SUBMITTED", "RETURNED", "FUNDING_VERIFIED")


def cancel_successors(appointment):
    successors = [a for a in db.appointments.values()
                  if a["renewed_from_appointment_id"] == appointment["id"]
                  and a["lifecycle_status"] in CANCELLABLE]
    for successor in sorted(successors, key=lambda a: a["_seq"]):
        update(successor, lifecycle_status="CANCELLED")
        allocations = queries.active_allocations(successor["id"])
        release_allocations(allocations, "PREDECESSOR_NON_RENEWED")
        student = db.students.get(successor["student_id"])
        if student is not None:
            recompute_student_effort(student)


# ---------------------------------------------------------------------------
# term close cascade (PRD 3.9)
# ---------------------------------------------------------------------------
def close_term_cascade(term):
    for period in sorted(queries.pay_periods_of_term(term["id"]),
                         key=lambda p: (p["sequence_no"], p["_seq"])):
        if period["status"] == "LOCKED":
            update(period, status="CLOSED")

    appointments = sorted(queries.appointments_of_term(term["id"]),
                          key=lambda a: a["_seq"])
    touched_sources = []
    for appointment in appointments:
        if appointment["lifecycle_status"] not in ("ACTIVE", "NON_RENEWAL_PENDING"):
            continue
        if appointment["end_date"] > term["term_end"]:
            continue
        update(appointment, lifecycle_status="COMPLETED")
        for alloc in sorted(queries.allocations_of_appointment(appointment["id"]),
                            key=lambda a: (a["plan_sequence"], a["_seq"])):
            if alloc["status"] != "COMMITTED":
                continue
            update(alloc,
                   status="EXPENDED",
                   disbursed_amount_cents=(alloc["allocated_stipend_cents"]
                                           + alloc["allocated_remission_cents"]))
            touched_sources.append(alloc["funding_source_id"])
    recompute_source_balances(touched_sources)
