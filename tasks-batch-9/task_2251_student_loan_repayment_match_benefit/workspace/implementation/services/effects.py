"""Cascading side effects (PRD 2.8, 3.5, 3.6, 3.7, 3.8, 3.9).

Every cascade runs to completion inside the request that triggers it.
"""

import db
from db import order_key
from services import calc


# --------------------------------------------------------------------------
# nondiscrimination test staling
# --------------------------------------------------------------------------

def stale_completed_tests(plan_year_id):
    for test in db.rows("nondiscrimination_tests"):
        if test["plan_year_id"] != plan_year_id:
            continue
        if test["status"] in ("PASSED", "FAILED"):
            test["status"] = "STALE"
            db.touch(test)


# --------------------------------------------------------------------------
# allocations
# --------------------------------------------------------------------------

def pending_batch_for(plan_year_id, payroll_period_id):
    for batch in db.rows("funding_batches"):
        if (batch["plan_year_id"] == plan_year_id
                and batch["payroll_period_id"] == payroll_period_id
                and batch["status"] == "PENDING"):
            return batch
    return None


def create_allocation(employee, plan_year, allocation_type, amount_cents,
                      tier1_applied_cents, tier2_applied_cents,
                      certification_id, payroll_period_id, batch):
    row = {
        "employee_id": employee["id"],
        "plan_year_id": plan_year["id"],
        "certification_id": certification_id,
        "payroll_period_id": payroll_period_id,
        "funding_batch_id": None,
        "allocation_type": allocation_type,
        "amount_cents": amount_cents,
        "tier1_applied_cents": tier1_applied_cents,
        "tier2_applied_cents": tier2_applied_cents,
        "funding_status": "UNFUNDED",
        "vesting_status": "UNVESTED",
        "vested_cents": 0,
        "forfeited_cents": 0,
    }
    db.stamp_new(row)
    # PRD 3.5: a fully vested participant's allocation goes straight to
    # FULLY_VESTED at allocation creation.
    if calc.vested_pct(employee["vesting_service_months"]) == 1:
        row["vesting_status"] = "FULLY_VESTED"
        row["vested_cents"] = amount_cents
    if batch is not None:
        row["funding_status"] = "SCHEDULED"
        row["funding_batch_id"] = batch["id"]
    db.db.match_allocations[row["id"]] = row
    return row


def create_adjustment(reason_code, amount_cents, employee_id, plan_year_id,
                      created_by_user_id, match_allocation_id=None,
                      nondiscrimination_test_id=None, note=None):
    row = {
        "match_allocation_id": match_allocation_id,
        "employee_id": employee_id,
        "plan_year_id": plan_year_id,
        "nondiscrimination_test_id": nondiscrimination_test_id,
        "reason_code": reason_code,
        "amount_cents": amount_cents,
        "created_by_user_id": created_by_user_id,
        "note": note,
    }
    db.stamp_new(row, versioned=False)
    db.db.correction_adjustments[row["id"]] = row
    return row


def reverse_allocations_of_certification(cert, reason_code, user_id):
    """Compensating reversal: every SCHEDULED/FUNDED allocation of the claim
    moves to REVERSED and produces one signed adjustment."""
    reversed_rows = []
    allocations = [a for a in db.rows("match_allocations")
                   if a["certification_id"] == cert["id"]
                   and a["funding_status"] in calc.LIVE_FUNDING_STATUSES]
    for alloc in allocations:
        alloc["funding_status"] = "REVERSED"
        db.touch(alloc)
        create_adjustment(
            reason_code=reason_code,
            amount_cents=-alloc["amount_cents"],
            employee_id=alloc["employee_id"],
            plan_year_id=alloc["plan_year_id"],
            created_by_user_id=user_id,
            match_allocation_id=alloc["id"],
        )
        reversed_rows.append(alloc)
    return reversed_rows


# --------------------------------------------------------------------------
# claim acceptance (PRD 3.5)
# --------------------------------------------------------------------------

def accept_certification(cert, plan_year, employee, user_id):
    cert["status"] = "ACCEPTED"
    cert["accepted_by_user_id"] = user_id
    cert["decided_at"] = db.now_iso()

    eligible, capped = calc.qslp_eligible_amount(cert, plan_year)
    cert["eligible_total_cents"] = eligible
    cert["capped_by_statutory_room"] = capped

    drafts, _leftover = calc.qslp_mirror_plan(cert, plan_year)
    for draft in drafts:
        batch = pending_batch_for(plan_year["id"], draft["payroll_period_id"])
        create_allocation(
            employee=employee,
            plan_year=plan_year,
            allocation_type="MIRROR",
            amount_cents=draft["amount_cents"],
            tier1_applied_cents=draft["tier1_applied_cents"],
            tier2_applied_cents=draft["tier2_applied_cents"],
            certification_id=cert["id"],
            payroll_period_id=draft["payroll_period_id"],
            batch=batch,
        )

    stale_completed_tests(plan_year["id"])

    superseded_id = cert["supersedes_certification_id"]
    if superseded_id:
        superseded = db.db.loan_certifications.get(superseded_id)
        if superseded is not None and superseded["status"] == "ACCEPTED":
            superseded["status"] = "SUPERSEDED"
            reverse_allocations_of_certification(
                superseded, "ERRONEOUS_MATCH", user_id)
            db.touch(superseded)

    db.touch(cert)
    db.touch(employee)
    db.touch(plan_year)


def void_certification(cert, plan_year, employee, user_id, note):
    cert["status"] = "VOIDED"
    cert["void_reason"] = note
    reverse_allocations_of_certification(cert, "CERTIFICATION_VOID", user_id)
    stale_completed_tests(plan_year["id"])
    db.touch(cert)
    db.touch(employee)
    db.touch(plan_year)


# --------------------------------------------------------------------------
# vesting and forfeiture (PRD 3.7)
# --------------------------------------------------------------------------

def run_vesting_and_forfeiture(employee):
    pct = calc.vested_pct(employee["vesting_service_months"])
    allocations = [a for a in db.rows("match_allocations")
                   if a["employee_id"] == employee["id"]
                   and a["funding_status"] in calc.LIVE_FUNDING_STATUSES
                   and a["vesting_status"] in ("UNVESTED", "PARTIALLY_VESTED")]
    allocations.sort(key=order_key)
    for alloc in allocations:
        vested = calc.rhu_cents(calc.dec(alloc["amount_cents"]) * pct)
        forfeited = alloc["amount_cents"] - vested
        alloc["vested_cents"] = vested
        alloc["forfeited_cents"] = forfeited
        if forfeited == 0:
            alloc["vesting_status"] = "FULLY_VESTED"
        elif vested == 0:
            alloc["vesting_status"] = "FORFEITED"
        else:
            alloc["vesting_status"] = "PARTIALLY_VESTED"
        db.touch(alloc)
        if forfeited > 0:
            row = {
                "match_allocation_id": alloc["id"],
                "employee_id": employee["id"],
                "plan_year_id": alloc["plan_year_id"],
                "amount_cents": forfeited,
                "reason_code": ("TERMINATION_UNVESTED" if vested == 0
                                else "TERMINATION_PARTIAL_VESTING"),
            }
            db.stamp_new(row, versioned=False)
            db.db.forfeiture_records[row["id"]] = row


# --------------------------------------------------------------------------
# annual true-up (PRD 3.8)
# --------------------------------------------------------------------------

def run_true_up(plan_year, employees, user_id):
    # The run's start instant: rows written by this run are excluded from the
    # already-funded snapshot of step three.
    run_seq = db.db.next_seq()

    allocation_count = 0
    recoupment_count = 0
    total_true_up = 0
    total_recoupment = 0

    for employee in employees:
        delta = calc.annual_true_up_delta(employee["id"], plan_year, run_seq)
        if delta > 0:
            batch = calc.true_up_target_batch(plan_year["id"])
            create_allocation(
                employee=employee,
                plan_year=plan_year,
                allocation_type="TRUE_UP",
                amount_cents=delta,
                tier1_applied_cents=0,
                tier2_applied_cents=0,
                certification_id=None,
                payroll_period_id=None,
                batch=batch,
            )
            allocation_count += 1
            total_true_up += delta
        elif delta < 0:
            create_adjustment(
                reason_code="TRUE_UP_RECOUPMENT",
                amount_cents=delta,
                employee_id=employee["id"],
                plan_year_id=plan_year["id"],
                created_by_user_id=user_id,
            )
            recoupment_count += 1
            total_recoupment += delta
        db.touch(employee)

    plan_year["true_up_completed"] = True
    stale_completed_tests(plan_year["id"])
    db.touch(plan_year)

    return {
        "true_up_allocation_count": allocation_count,
        "recoupment_count": recoupment_count,
        "total_true_up_cents": total_true_up,
        "total_recoupment_cents": total_recoupment,
        "employee_count": len(employees),
    }
