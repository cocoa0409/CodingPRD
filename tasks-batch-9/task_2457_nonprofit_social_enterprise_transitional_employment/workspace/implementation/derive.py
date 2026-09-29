"""Derived fields, the cost ledger and every cascade (PRD 2.11 and section 3).

Derived values are never client-supplied: each helper recomputes from its inputs
and refreshes the owning row only when a value actually changed.
"""

from decimal import Decimal

import calc
import constants as C
from calc import dec, rhu
from store import (all_records, create_record, days, iso_week_start, set_fields,
                   sort_key, store, touch)

ZERO = Decimal("0")


# --------------------------------------------------------------------------- #
# small query helpers
# --------------------------------------------------------------------------- #

def participants_of_line(line_id):
    return [p for p in all_records("participants") if p["business_line_id"] == line_id]


def shifts_of_line(line_id):
    return [s for s in all_records("work_shifts") if s["business_line_id"] == line_id]


def assignments_of_shift(shift_id):
    return [a for a in all_records("shift_assignments") if a["work_shift_id"] == shift_id]


def assignments_of_participant(participant_id):
    return [a for a in all_records("shift_assignments") if a["participant_id"] == participant_id]


def activities_of_participant(participant_id):
    return [a for a in all_records("support_activities") if a["participant_id"] == participant_id]


def entries_of_period(period_id):
    return [e for e in all_records("cost_entries") if e["subsidy_period_id"] == period_id]


def periods_of_line(line_id):
    return [p for p in all_records("subsidy_periods") if p["business_line_id"] == line_id]


def placements_of_employer(employer_id):
    return [p for p in all_records("placements") if p["employer_id"] == employer_id]


def checkpoints_of_placement(placement_id):
    return [c for c in all_records("retention_checkpoints") if c["placement_id"] == placement_id]


def referrals_of_partner(partner_id):
    return [r for r in all_records("referrals") if r["referral_partner_id"] == partner_id]


def shift_of(assignment):
    return store.work_shifts[assignment["work_shift_id"]]


def participant_of(record):
    return store.participants[record["participant_id"]]


# --------------------------------------------------------------------------- #
# BusinessLine derived fields (intake_posture_recompute)
# --------------------------------------------------------------------------- #

def recompute_line_posture(line):
    filled = len([p for p in participants_of_line(line["id"])
                  if p["status"] in C.SLOT_OCCUPYING_STATUSES])
    incidents = 0
    for shift in shifts_of_line(line["id"]):
        for assignment in assignments_of_shift(shift["id"]):
            if assignment["status"] == "COMPLETED":
                incidents += assignment["quality_defect_count"] + assignment["customer_complaint_count"]
    posture = "CLOSED"
    if (line["status"] == "LAUNCHED"
            and filled < line["training_slots_total"]
            and incidents < C.QUALITY_INCIDENT_LIMIT):
        posture = "OPEN"
    set_fields(line, training_slots_filled=filled, quality_incident_count=incidents,
               intake_posture=posture)


def recompute_cumulative_subsidy(line):
    total = 0
    for period in periods_of_line(line["id"]):
        if period["status"] == "CLOSED" and period["subsidy_draw_cents"] is not None:
            total += period["subsidy_draw_cents"]
    set_fields(line, cumulative_subsidy_cents=total)


# --------------------------------------------------------------------------- #
# ReferralPartner derived fields (partner_conversion_rate)
# --------------------------------------------------------------------------- #

def recompute_partner(partner):
    referrals = referrals_of_partner(partner["id"])
    submitted = len(referrals)
    enrolled = len([r for r in referrals if r["status"] == "ENROLLED"])
    set_fields(partner,
               referrals_submitted_count=submitted,
               enrolled_referral_count=enrolled,
               conversion_rate=calc.ratio_or_none(enrolled, submitted, 4))


# --------------------------------------------------------------------------- #
# Participant derived fields (participant_progress_metrics)
# --------------------------------------------------------------------------- #

def scheduled_week_hours(participant):
    """Sum of duration_hours over ASSIGNED seats inside the ISO week (Mon 00:00Z,
    half-open, seven days) containing the logical clock's current instant."""
    week_start = iso_week_start(store.now)
    week_end = week_start + days(7)
    scheduled = ZERO
    for assignment in assignments_of_participant(participant["id"]):
        if assignment["status"] != "ASSIGNED":
            continue
        shift = shift_of(assignment)
        if week_start <= shift["starts_at"] < week_end:
            scheduled += dec(shift["duration_hours"])
    return rhu(scheduled, 3)


def recompute_participant_metrics(participant):
    assignments = assignments_of_participant(participant["id"])
    worked = ZERO
    for assignment in assignments:
        if assignment["status"] == "COMPLETED" and assignment["actual_hours"] is not None:
            worked += dec(assignment["actual_hours"])
    scheduled = scheduled_week_hours(participant)
    minutes = 0
    coaching = 0
    for activity in activities_of_participant(participant["id"]):
        if activity["status"] == "DELIVERED":
            minutes += activity["duration_minutes"]
            if activity["category"] == "JOB_COACHING":
                coaching += 1
    set_fields(participant,
               transitional_hours_worked=rhu(worked, 3),
               scheduled_hours_current_week=scheduled,
               support_activity_minutes=minutes,
               delivered_coaching_count=coaching)


# --------------------------------------------------------------------------- #
# WorkShift derived fields and the compound auto-close
# --------------------------------------------------------------------------- #

def recompute_shift_counters(shift):
    assignments = assignments_of_shift(shift["id"])
    assigned = len([a for a in assignments if a["status"] == "ASSIGNED"])
    defects = sum(a["quality_defect_count"] for a in assignments if a["status"] == "COMPLETED")
    complaints = sum(a["customer_complaint_count"] for a in assignments if a["status"] == "COMPLETED")
    set_fields(shift, assigned_count=assigned, quality_defect_count=defects,
               customer_complaint_count=complaints)


def evaluate_shift_close(shift):
    """SCHEDULED -> CLOSED: the parent state is a function of its children."""
    if shift["status"] != "SCHEDULED":
        return False
    assignments = assignments_of_shift(shift["id"])
    if not assignments:
        return False
    if any(a["status"] not in ("COMPLETED", "RELEASED") for a in assignments):
        return False
    completed = [a for a in assignments if a["status"] == "COMPLETED"]
    if not completed:
        return False
    billable = sum((a["wage_cost_cents"] or 0) for a in completed)
    set_fields(shift,
               status="CLOSED",
               billable_labor_cost_cents=billable,
               quality_defect_count=sum(a["quality_defect_count"] for a in completed),
               customer_complaint_count=sum(a["customer_complaint_count"] for a in completed))
    return True


# --------------------------------------------------------------------------- #
# Employer derived fields (employer_retention_reliability)
# --------------------------------------------------------------------------- #

def recompute_employer(employer):
    placements = placements_of_employer(employer["id"])
    failed = len([p for p in placements if p["retention_outcome"] in ("FAILED_EARLY", "FAILED_LATE")])
    confirmed = len([p for p in placements if p["retention_outcome"] == "RETAINED_180"])
    set_fields(employer,
               failed_retention_count=failed,
               confirmed_retention_count=confirmed,
               placement_count=len(placements),
               retention_reliability_pct=calc.ratio_or_none(confirmed, failed + confirmed, 4))


def flag_active_placements_at_risk(employer):
    """Cascade hop 4 of the separation chain: hire_date ASC, then created_at ASC."""
    rows = [p for p in placements_of_employer(employer["id"]) if p["employment_status"] == "ACTIVE"]
    rows.sort(key=lambda row: (row["hire_date"], row["created_at"], row["_seq"]))
    for placement in rows:
        set_fields(placement, at_risk_flag=True)


def apply_employer_thresholds(employer):
    """Cascade hop 3 of the separation chain."""
    failed = employer["failed_retention_count"]
    if (employer["partnership_status"] == "ACTIVE"
            and C.EMPLOYER_PROBATION_THRESHOLD <= failed < C.EMPLOYER_TERMINATION_THRESHOLD):
        set_fields(employer, partnership_status="PROBATION")
        flag_active_placements_at_risk(employer)
        return
    if employer["partnership_status"] == "PROBATION" and failed >= C.EMPLOYER_TERMINATION_THRESHOLD:
        set_fields(employer, partnership_status="TERMINATED")
        flag_active_placements_at_risk(employer)


# --------------------------------------------------------------------------- #
# Placement derived fields
# --------------------------------------------------------------------------- #

def recompute_wage_progression(placement):
    if placement["wage_verification_status"] != "VERIFIED":
        set_fields(placement, wage_progression_pct=None)
        return
    participant = participant_of(placement)
    set_fields(placement, wage_progression_pct=calc.wage_progression_pct(
        placement["verified_wage_cents_per_hour"],
        participant["graduation_wage_cents_per_hour"]))


# --------------------------------------------------------------------------- #
# The subsidy ledger
# --------------------------------------------------------------------------- #

def period_trainee_hours(period):
    total = ZERO
    for shift in shifts_of_line(period["business_line_id"]):
        if not (period["period_start"] <= shift["starts_at"] <= period["period_end"]):
            continue
        for assignment in assignments_of_shift(shift["id"]):
            if assignment["status"] == "COMPLETED" and assignment["actual_hours"] is not None:
                total += dec(assignment["actual_hours"])
    return rhu(total, 3)


def compute_allocation(period, basis):
    """subsidy_cost_allocation + true_cost_analysis under one basis; no writes."""
    posted = [e for e in entries_of_period(period["id"]) if e["status"] == "POSTED"]
    trainee_hours = period_trainee_hours(period)
    gross = sum(e["amount_cents"] for e in posted)
    if basis == "REVENUE":
        share = calc.mission_share_revenue(period["revenue_cents"], gross)
    else:
        share = calc.mission_share_hours(trainee_hours, period["supervisor_hours"])
    allocations = {}
    mission_total = 0
    business_total = 0
    for entry in posted:
        mission, business = calc.allocate_entry(entry["amount_cents"], entry["classification"], share)
        allocations[entry["id"]] = (mission, business)
        mission_total += mission
        business_total += business
    total = mission_total + business_total
    return {
        "trainee_hours": trainee_hours,
        "gross_cost_cents": gross,
        "mission_share": share,
        "allocations": allocations,
        "mission_cost_cents": mission_total,
        "business_operating_cost_cents": business_total,
        "total_cost_cents": total,
        "true_cost_per_trainee_hour_cents": calc.per_trainee_hour(total, trainee_hours),
        "subsidy_per_trainee_hour_cents": calc.per_trainee_hour(mission_total, trainee_hours),
    }


def apply_allocation(period, basis=None):
    """Persist the allocation of a period under its active basis."""
    if basis is None:
        basis = period["allocation_basis"] if period["status"] == "CLOSED" else "HOURS"
    result = compute_allocation(period, basis)
    for entry_id, (mission, business) in result["allocations"].items():
        entry = store.cost_entries[entry_id]
        set_fields(entry, allocated_mission_cents=mission, allocated_business_cents=business)
    set_fields(period,
               trainee_hours=result["trainee_hours"],
               mission_share=result["mission_share"],
               mission_cost_cents=result["mission_cost_cents"],
               business_operating_cost_cents=result["business_operating_cost_cents"],
               total_cost_cents=result["total_cost_cents"],
               true_cost_per_trainee_hour_cents=result["true_cost_per_trainee_hour_cents"],
               subsidy_per_trainee_hour_cents=result["subsidy_per_trainee_hour_cents"])
    return result


def select_open_period(business_line_id, anchor):
    """open_period_selector: OPEN periods of one line covering the anchor,
    ranked period_start DESC, ties broken created_at ASC."""
    candidates = [p for p in periods_of_line(business_line_id)
                  if p["status"] == "OPEN"
                  and p["period_start"] <= anchor <= p["period_end"]]
    if not candidates:
        return None
    candidates.sort(key=lambda row: (-row["period_start"].timestamp(), row["created_at"], row["_seq"]))
    return candidates[0]


def post_cost_entry(period, category, classification, amount_cents, source_activity_id=None):
    entry = create_record("cost_entries", {
        "subsidy_period_id": period["id"],
        "source_activity_id": source_activity_id,
        "category": category,
        "classification": classification,
        "amount_cents": amount_cents,
        "status": "POSTED",
        "allocated_mission_cents": 0,
        "allocated_business_cents": 0,
        "voided_at": None,
    })
    touch(period)
    apply_allocation(period)
    return entry


def void_cost_entry(entry):
    period = store.subsidy_periods[entry["subsidy_period_id"]]
    set_fields(entry, status="VOIDED", voided_at=store.now)
    touch(period)
    apply_allocation(period)


# --------------------------------------------------------------------------- #
# Assignment release, used by three different cascades
# --------------------------------------------------------------------------- #

def release_assignment(assignment, reason):
    set_fields(assignment, status="RELEASED", released_reason=reason)


# --------------------------------------------------------------------------- #
# BusinessLine suspension cascade (hops 3-5 of the period close chain)
# --------------------------------------------------------------------------- #

def suspend_line_if_over_cap(line):
    if line["status"] != "LAUNCHED":
        return False
    if line["cumulative_subsidy_cents"] <= line["subsidy_cap_cents"]:
        return False
    set_fields(line, status="SUSPENDED")
    recompute_line_posture(line)
    future = [s for s in shifts_of_line(line["id"])
              if s["status"] == "SCHEDULED" and s["starts_at"] > store.now]
    future.sort(key=lambda row: (row["starts_at"], row["created_at"], row["_seq"]))
    for shift in future:
        set_fields(shift, status="CANCELLED")
        assigned = [a for a in assignments_of_shift(shift["id"]) if a["status"] == "ASSIGNED"]
        assigned.sort(key=sort_key)
        for assignment in assigned:
            release_assignment(assignment, "SHIFT_CANCELLED")
            recompute_participant_metrics(participant_of(assignment))
        recompute_shift_counters(shift)
    return True
