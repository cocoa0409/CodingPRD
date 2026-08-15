"""Entity lookup helpers and state machine side-effect executors."""

import uuid
from datetime import timedelta

import db
import errors
from clock import CLOCK, format_iso, _parse_iso
from services import audit
from services import calculations as calc
from services.util import (add_months, add_years, last_day_of_next_quarter,
                           new_id, now_iso, today, touch, iso, date_iso, parse)


# ---------------------------------------------------------------------------
# Lookup helpers (raise the scaffold's specific not-found errors)
# ---------------------------------------------------------------------------
def get_plan(plan_id):
    p = db.plans.get(plan_id)
    if p is None:
        raise errors.err(errors.ERR_PLAN_NOT_FOUND, f"Plan {plan_id} not found", 404)
    return p


def get_participant(participant_id):
    p = db.participants.get(participant_id)
    if p is None:
        raise errors.err(errors.ERR_PARTICIPANT_NOT_FOUND,
                         f"Participant {participant_id} not found", 404)
    return p


def get_participant_in_plan(plan_id, participant_id):
    p = db.participants.get(participant_id)
    if p is None or p["plan_id"] != plan_id:
        raise errors.err(errors.ERR_PARTICIPANT_NOT_FOUND,
                         f"Participant {participant_id} not found", 404)
    return p


def get_loan(loan_id):
    l = db.loans.get(loan_id)
    if l is None:
        raise errors.err(errors.ERR_LOAN_NOT_FOUND, f"Loan {loan_id} not found", 404)
    return l


def get_hardship(hardship_id):
    h = db.hardship_requests.get(hardship_id)
    if h is None:
        raise errors.err(errors.ERR_HARDSHIP_NOT_FOUND,
                         f"Hardship request {hardship_id} not found", 404)
    return h


def get_remittance(remittance_id):
    r = db.payroll_remittances.get(remittance_id)
    if r is None:
        raise errors.err(errors.ERR_REMITTANCE_NOT_FOUND,
                         f"Remittance {remittance_id} not found", 404)
    return r


def get_approval_task(task_id):
    t = db.approval_tasks.get(task_id)
    if t is None:
        raise errors.err(errors.ERR_APPROVAL_TASK_NOT_FOUND,
                         f"Approval task {task_id} not found", 404)
    return t


def get_tax_event(tax_event_id):
    t = db.tax_events.get(tax_event_id)
    if t is None:
        raise errors.err(errors.ERR_TAX_EVENT_NOT_FOUND,
                         f"Tax event {tax_event_id} not found", 404)
    return t


def plan_of_participant(participant):
    return get_plan(participant["plan_id"])


def plan_of_loan(loan):
    return get_plan(loan["plan_id"])


def plan_of_hardship(hardship):
    return get_plan(hardship["plan_id"])


def require_plan_active(plan):
    if plan["status"] != "ACTIVE":
        raise errors.err(errors.ERR_PLAN_NOT_ACTIVE,
                         f"Plan is {plan['status']}; operation requires ACTIVE", 409)


# ---------------------------------------------------------------------------
# Election / participant computed fields
# ---------------------------------------------------------------------------
def election_of_participant(participant_id):
    eid = db.election_by_participant.get(participant_id)
    if eid:
        return db.contribution_elections.get(eid)
    return None


def set_contribution_status(participant, status):
    participant["contribution_status"] = status


def active_suspension_records(participant_id, today_dt):
    out = []
    for s in db.suspension_records.values():
        if s["participant_id"] != participant_id:
            continue
        if s["status"] == "ACTIVE":
            out.append(s)
    return out


def has_active_suspension(participant_id, today_dt):
    return len(active_suspension_records(participant_id, today_dt)) > 0


# ---------------------------------------------------------------------------
# Tax event creation + participant accounting
# ---------------------------------------------------------------------------
def create_tax_event(participant, source_type, source_id, taxable_amount_cents, event_date_dt):
    evt = {
        "id": new_id(),
        "participant_id": participant["id"],
        "source_type": source_type,
        "source_id": source_id,
        "taxable_amount_cents": taxable_amount_cents,
        "event_date": date_iso(event_date_dt),
        "tax_year": event_date_dt.year,
        "status": "PENDING",
    }
    evt["created_at"] = now_iso()
    evt["updated_at"] = evt["created_at"]
    evt["version"] = 1
    db.tax_events[evt["id"]] = evt
    # participant accounting
    participant["ytd_taxable_distributions_cents"] = \
        (participant.get("ytd_taxable_distributions_cents", 0) or 0) + taxable_amount_cents
    return evt


def set_loan_lock_from_event(participant, event_date_dt):
    lock = add_months(event_date_dt, 12)
    existing = participant.get("loan_eligibility_locked_until")
    if existing:
        existing_dt = parse(existing)
        if existing_dt >= lock:
            return
    participant["loan_eligibility_locked_until"] = date_iso(lock)


# ---------------------------------------------------------------------------
# Loan: schedule generation, disbursement side effects
# ---------------------------------------------------------------------------
def generate_schedule_for_loan(loan, disbursed_on_dt):
    scheduled_payment, rows = calc.build_amortization_schedule(
        loan["principal_amount_cents"], loan["interest_rate_bps"], loan["term_months"],
        loan["day_count_convention"], disbursed_on_dt)
    loan["scheduled_payment_cents"] = scheduled_payment
    loan["outstanding_principal_cents"] = loan["principal_amount_cents"]
    loan["accrued_unpaid_interest_cents"] = 0
    for row in rows:
        inst = {
            "id": new_id(),
            "created_at": now_iso(),
            "loan_id": loan["id"],
            "installment_number": row["installment_number"],
            "due_date": row["due_date"],
            "scheduled_amount_cents": row["scheduled_amount_cents"],
            "principal_portion_cents": row["principal_portion_cents"],
            "interest_portion_cents": row["interest_portion_cents"],
            "paid_amount_cents": 0,
            "status": "PENDING",
        }
        db.loan_installments[inst["id"]] = inst


def disburse_loan(loan):
    today_dt = today()
    loan["lifecycle_status"] = "DISBURSED"
    loan["disbursed_on"] = date_iso(today_dt)
    loan["delinquency_status"] = "CURRENT"
    generate_schedule_for_loan(loan, today_dt)


# ---------------------------------------------------------------------------
# Loan: delinquency / deemed evaluation (called on clock advance)
# ---------------------------------------------------------------------------
def recompute_loan_outstanding(loan):
    """outstanding = principal - sum over installments of max(0, paid - interest_portion)."""
    total_principal_covered = 0
    for inst in calc.loan_installments(loan["id"]):
        principal_cov = max(0, inst["paid_amount_cents"] - inst["interest_portion_cents"])
        total_principal_covered += principal_cov
    loan["outstanding_principal_cents"] = loan["principal_amount_cents"] - total_principal_covered


def evaluate_loan_after_remittance(loan, remittance_pay_date_dt):
    """After a posting: mark PAID/CURED, evaluate cure, evaluate REPAID."""
    today_dt = today()
    recompute_loan_outstanding(loan)
    # Installment statuses
    for inst in calc.loan_installments(loan["id"]):
        if inst["status"] in ("REBUILT", "CLOSED"):
            continue
        if inst["paid_amount_cents"] >= inst["scheduled_amount_cents"]:
            if inst["status"] == "PENDING":
                inst["status"] = "PAID"
            elif inst["status"] == "MISSED":
                # cure valid when pay_date <= cure_deadline_on
                if loan.get("cure_deadline_on") and \
                        remittance_pay_date_dt <= parse(loan["cure_deadline_on"]):
                    inst["status"] = "CURED"
    # Delinquency re-evaluation: cure when no MISSED with shortfall remains
    if loan["delinquency_status"] == "DELINQUENT":
        any_missed_unpaid = any(
            i["status"] == "MISSED" and i["paid_amount_cents"] < i["scheduled_amount_cents"]
            for i in calc.loan_installments(loan["id"]))
        if not any_missed_unpaid and loan.get("cure_deadline_on") and \
                remittance_pay_date_dt <= parse(loan["cure_deadline_on"]):
            loan["delinquency_status"] = "CURRENT"
            loan["cure_deadline_on"] = None
    # REPAID evaluation
    if loan["lifecycle_status"] == "DISBURSED" and \
            (loan.get("outstanding_principal_cents") or 0) == 0:
        loan["lifecycle_status"] = "REPAID"
        for inst in calc.loan_installments(loan["id"]):
            if inst["status"] == "PENDING":
                inst["status"] = "CLOSED"
    calc.recompute_accrued_unpaid_interest(loan, today_dt)


def mark_missed_and_delinquency(today_dt):
    """On clock advance: mark past-due PENDING installments MISSED; enter DELINQUENT;
    fire DEEMED when past cure deadline."""
    # First pass: mark MISSED and enter DELINQUENT / fix cure deadlines
    for loan in db.loans.values():
        if loan["lifecycle_status"] != "DISBURSED":
            continue
        if loan["delinquency_status"] == "DEEMED":
            continue
        newly_missed = False
        for inst in calc.loan_installments(loan["id"]):
            if inst["status"] == "PENDING" and \
                    inst["paid_amount_cents"] < inst["scheduled_amount_cents"] and \
                    parse(inst["due_date"]) < today_dt:
                inst["status"] = "MISSED"
                newly_missed = True
        # Recompute cure deadline if there are unpaid MISSED
        earliest = calc.earliest_unpaid_missed_due_date(loan["id"])
        if earliest is not None:
            if loan["delinquency_status"] in ("CURRENT", "NONE"):
                loan["delinquency_status"] = "DELINQUENT"
            # cure_deadline_on: last day of quarter following earliest MISSED quarter
            loan["cure_deadline_on"] = date_iso(last_day_of_next_quarter(earliest))
    # Second pass: DEEMED when past cure deadline
    for loan in db.loans.values():
        if loan["lifecycle_status"] != "DISBURSED":
            continue
        if loan["delinquency_status"] != "DELINQUENT":
            continue
        if not loan.get("cure_deadline_on"):
            continue
        cure_dt = parse(loan["cure_deadline_on"])
        if today_dt <= cure_dt:
            continue
        any_missed_unpaid = any(
            i["status"] == "MISSED" and i["paid_amount_cents"] < i["scheduled_amount_cents"]
            for i in calc.loan_installments(loan["id"]))
        if not any_missed_unpaid:
            continue
        # Fire the deemed distribution cascade
        fire_deemed(loan, today_dt)


def fire_deemed(loan, today_dt):
    participant = get_participant(loan["participant_id"])
    loan["delinquency_status"] = "DEEMED"
    loan["deemed_on"] = date_iso(today_dt)
    # taxable: cutoff = cure_deadline_on (quarter-end), regardless of fire date
    cutoff = parse(loan["cure_deadline_on"]) if loan.get("cure_deadline_on") else today_dt
    taxable = calc.taxable_amount_for_loan(loan, cutoff)
    create_tax_event(participant, "LOAN_DEEMED", loan["id"], taxable, today_dt)
    set_loan_lock_from_event(participant, today_dt)
    touch(loan)
    touch(participant)
    audit.append(loan["plan_id"], "system", "system",
                 "LOAN_DEEMED", "Loan", loan["id"],
                 {"deemed_on": loan["deemed_on"],
                  "taxable_amount_cents": taxable})


def expire_suspensions(today_dt):
    for s in db.suspension_records.values():
        if s["status"] == "ACTIVE" and today_dt >= parse(s["ends_on"]):
            s["status"] = "EXPIRED"
            s["updated_at"] = now_iso()
            s["version"] = s.get("version", 1) + 1


def clock_advance(to_dt):
    """Evaluate clock-driven transitions after advancing the logical clock."""
    mark_missed_and_delinquency(to_dt)
    expire_suspensions(to_dt)
