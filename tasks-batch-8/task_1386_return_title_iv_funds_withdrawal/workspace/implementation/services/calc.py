"""R2T4 calculation engine (SCAFFOLD §1.3, PRD §3.4-§3.7).

Covers: withdrawal_date_determination, percentage_completed,
r2t4_earned_unearned, return_responsibility_split,
post_withdrawal_disbursement, institutional_refund, student_balance,
return_deadline, offer_deadlines, and the case auto-close evaluation.
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import db
from services.term_days import parse_date, date_str, deductible_days_within

EARNED_CAP_THRESHOLD = Decimal("0.6")
PCT_DECIMALS = 3
GRANT_PROTECTION_RATE = Decimal("0.5")
RETURN_WINDOW_DAYS = 45
OFFER_RESPONSE_DAYS = 14
OFFER_CREATION_DAYS = 30

_ONE_DAY = timedelta(days=1)


def round_pct(value: Decimal) -> Decimal:
    """Round to 3 decimal places, half-up."""
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def round_cents(value: Decimal) -> int:
    """Round a Decimal to whole cents, half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# withdrawal_date_determination + percentage_completed
# ---------------------------------------------------------------------------

def determine_dates_and_progress(case: dict, term: dict, processing_date: date):
    """Compute withdrawal_date / determination_date / completed_days /
    percentage_completed / earned_pct for the case from its (possibly
    corrected) inputs. Mutates the case dict.
    """
    total_days = term["total_days"]
    start = parse_date(term["start_date"])

    if case["withdrawal_type"] == "OFFICIAL":
        withdrawal_date = parse_date(case["notification_date"])
        determination_date = withdrawal_date
    elif term["attendance_taking_required"]:
        withdrawal_date = parse_date(case["last_attendance_date"])
        determination_date = processing_date
    else:
        midpoint_day = (total_days + 1) // 2
        withdrawal_date = start + timedelta(days=midpoint_day - 1)
        determination_date = processing_date

    completed_days = (withdrawal_date - start).days + 1
    completed_days -= deductible_days_within(term["id"], start, withdrawal_date)

    percentage_completed = round_pct(Decimal(completed_days) / Decimal(total_days))
    if percentage_completed > EARNED_CAP_THRESHOLD:
        earned_pct = Decimal("1.000")
    else:
        earned_pct = percentage_completed
    unearned_pct = round_pct(Decimal("1") - earned_pct)

    case["withdrawal_date"] = date_str(withdrawal_date)
    case["determination_date"] = date_str(determination_date)
    case["total_days"] = total_days
    case["completed_days"] = completed_days
    case["percentage_completed"] = float(percentage_completed)
    case["earned_pct"] = float(earned_pct)
    return earned_pct, unearned_pct


# ---------------------------------------------------------------------------
# Student account ledger helpers
# ---------------------------------------------------------------------------

def post_entry(enrollment_id, entry_type, amount_cents, source_ref="",
               reversal_of_entry_id=None):
    entry = {
        "id": _uuid(),
        "enrollment_id": enrollment_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "reversal_of_entry_id": reversal_of_entry_id,
        "source_ref": source_ref,
        "posted_at": clock.now_iso(),
        "created_at": clock.now_iso(),
        "_seq": db.next_seq(),
    }
    db.account_entries[entry["id"]] = entry
    return entry


def recompute_balance(enrollment_id: str, evaluate_notification: bool = True):
    """balance_cents = sum of signed entry amounts. When recomputed while a
    linked case is CALCULATED and balance > 0, emit the notification."""
    enrollment = db.enrollments[enrollment_id]
    total = sum(e["amount_cents"] for e in db.account_entries.values()
                if e["enrollment_id"] == enrollment_id)
    enrollment["balance_cents"] = total
    if evaluate_notification:
        case_id = enrollment.get("current_withdrawal_case_id")
        case = db.withdrawal_cases.get(case_id) if case_id else None
        if case is not None and case["status"] == "CALCULATED" and total > 0:
            enrollment["balance_notification_sent"] = True
            enrollment["balance_notified_at"] = clock.now_iso()
    return total


# ---------------------------------------------------------------------------
# Auto-close evaluation (CALCULATED -> CLOSED)
# ---------------------------------------------------------------------------

def evaluate_auto_close(case_id: str):
    """Close the case when: all obligations terminal, all offers terminal, and
    (balance <= 0 OR balance_notification_sent)."""
    case = db.withdrawal_cases.get(case_id)
    if case is None or case["status"] != "CALCULATED":
        return
    enrollment = db.enrollments[case["enrollment_id"]]

    obligations = [o for o in db.obligations.values()
                   if o["withdrawal_case_id"] == case_id]
    offers = [o for o in db.offers.values()
              if o["withdrawal_case_id"] == case_id]

    obligations_terminal = all(o["status"] in ("RETURNED", "VOIDED")
                               for o in obligations)
    offers_terminal = all(o["status"] in ("ACCEPTED", "DECLINED", "EXPIRED", "VOIDED")
                          for o in offers)
    balance_ok = (enrollment["balance_cents"] <= 0
                  or enrollment["balance_notification_sent"])

    if obligations_terminal and offers_terminal and balance_ok:
        case["status"] = "CLOSED"
        case["version"] += 1
        case["updated_at"] = clock.now_iso()
        if enrollment.get("current_withdrawal_case_id") == case_id:
            enrollment["current_withdrawal_case_id"] = None
            enrollment["updated_at"] = clock.now_iso()


# ---------------------------------------------------------------------------
# Full R2T4 calculation cascade (OPEN -> CALCULATED, and recalculate)
# ---------------------------------------------------------------------------

def run_calculation(case: dict, acting_user_id: str):
    """Run the full CALCULATED side-effect chain on the case. Assumes date
    determination has already been applied to the case dict. Mutates state.
    """
    enrollment = db.enrollments[case["enrollment_id"]]
    term = db.terms[enrollment["term_id"]]
    earned_pct = Decimal(str(case["earned_pct"]))
    unearned_pct = round_pct(Decimal("1") - earned_pct)

    # r2t4_earned_unearned over ACCEPTED awards. The disbursable snapshot
    # captures disbursed + scheduled BEFORE the scheduled rows are cancelled
    # (PRD §3.5: "everything that has been or was planned to be paid").
    enrollment_awards = [a for a in db.awards.values()
                         if a["enrollment_id"] == enrollment["id"]]
    eligible = [a for a in enrollment_awards if a["status"] == "ACCEPTED"]
    eligible.sort(key=lambda a: (a["created_at"], a["_seq"]))

    per_award = []
    aid_disbursable = 0
    aid_disbursed = 0
    aid_earned = 0
    for award in eligible:
        award_disbursable = award["disbursed_amount_cents"] + award["scheduled_amount_cents"]
        award_earned = round_cents(Decimal(award_disbursable) * earned_pct)
        per_award.append({
            "award": award,
            "disbursable": award_disbursable,
            "earned": award_earned,
            "disbursed": award["disbursed_amount_cents"],
        })
        aid_disbursable += award_disbursable
        aid_disbursed += award["disbursed_amount_cents"]
        aid_earned += award_earned

    # Cancel all remaining SCHEDULED disbursements of the enrollment's awards.
    for award in enrollment_awards:
        for d in db.disbursements.values():
            if d["award_id"] == award["id"] and d["status"] == "SCHEDULED":
                d["status"] = "CANCELLED"
                d["updated_at"] = clock.now_iso()
                d["version"] += 1
                award["scheduled_amount_cents"] -= d["amount_cents"]
        award["updated_at"] = clock.now_iso()

    aid_unearned = aid_disbursable - aid_earned
    return_amount = max(0, aid_disbursed - aid_earned)

    case["aid_disbursable_cents"] = aid_disbursable
    case["aid_disbursed_cents"] = aid_disbursed
    case["aid_earned_cents"] = aid_earned
    case["aid_unearned_cents"] = aid_unearned
    case["return_amount_cents"] = return_amount

    pwd_grant_total = 0
    pwd_loan_total = 0

    if aid_earned < aid_disbursed:
        # ---- Return path ----
        school_return = min(
            round_cents(Decimal(enrollment["institutional_charges_cents"]) * unearned_pct),
            return_amount,
        )
        student_share = return_amount - school_return

        grant_unearned_disbursed = 0
        for row in per_award:
            if row["award"]["is_grant"]:
                grant_unearned_disbursed += max(0, row["disbursed"] - row["earned"])
        student_grant_base = min(student_share, grant_unearned_disbursed)
        student_grant_return = round_cents(Decimal(student_grant_base) * GRANT_PROTECTION_RATE)
        student_loan_deferred = student_share - student_grant_base

        case["school_return_cents"] = school_return
        case["student_grant_return_cents"] = student_grant_return
        case["student_loan_deferred_cents"] = student_loan_deferred
        case["pwd_grant_cents"] = 0
        case["pwd_loan_cents"] = 0

        due_date = parse_date(case["determination_date"]) + timedelta(days=RETURN_WINDOW_DAYS)
        # SCHOOL obligation first, then STUDENT (fixed creation order).
        if school_return > 0:
            obligation = _new_obligation(case["id"], "SCHOOL", school_return,
                                         date_str(due_date))
            post_entry(enrollment["id"], "R2T4_CHARGEBACK", school_return,
                       source_ref=obligation["id"])
        if student_grant_return > 0:
            _new_obligation(case["id"], "STUDENT", student_grant_return,
                            date_str(due_date))
    else:
        # ---- Post-withdrawal disbursement path (or exact break-even) ----
        case["school_return_cents"] = 0
        case["student_grant_return_cents"] = 0
        case["student_loan_deferred_cents"] = 0

        for row in per_award:
            award = row["award"]
            award_pwd = max(0, row["earned"] - row["disbursed"])
            if award_pwd <= 0:
                continue
            if award["is_grant"]:
                pwd_grant_total += award_pwd
                disb = _new_disbursement(
                    award_id=award["id"],
                    amount_cents=award_pwd,
                    status="DISBURSED",
                    pwd_offer_id=None,
                    disbursed_on=date_str(clock.current_date()),
                )
                award["disbursed_amount_cents"] += award_pwd
                award["updated_at"] = clock.now_iso()
                award["version"] += 1
                post_entry(enrollment["id"], "AID_CREDIT", -award_pwd,
                           source_ref=disb["id"])
            else:
                pwd_loan_total += award_pwd
                _new_offer(case["id"], award["id"], award_pwd,
                           parse_date(case["determination_date"]))

        case["pwd_grant_cents"] = pwd_grant_total
        case["pwd_loan_cents"] = pwd_loan_total

    # ---- Institutional refund (both paths) ----
    refund_cents = compute_institutional_refund(term, enrollment, case)
    if refund_cents > 0:
        post_entry(enrollment["id"], "REFUND_CREDIT", -refund_cents,
                   source_ref=case["id"])

    # ---- Balance + notification ----
    # The case is stamped CALCULATED before the balance recompute so that the
    # notification rule ("recomputed while a linked case is CALCULATED") fires
    # within this same action (PRD §3.5).
    case["calculated_by_user_id"] = acting_user_id
    case["calculated_at"] = clock.now_iso()
    case["status"] = "CALCULATED"
    case["version"] += 1
    case["updated_at"] = clock.now_iso()

    recompute_balance(enrollment["id"])

    evaluate_auto_close(case["id"])


def compute_institutional_refund(term: dict, enrollment: dict, case: dict) -> int:
    """institutional_refund calculation: TIERED schedule or PRO_RATA."""
    charges = enrollment["institutional_charges_cents"]
    if term["refund_method"] == "PRO_RATA":
        refund_pct = Decimal("1") - Decimal(str(case["percentage_completed"]))
    else:
        schedule = term["refund_schedule"] or []
        refund_pct = Decimal("0")
        for tier in schedule:
            if case["completed_days"] <= int(tier["through_day"]):
                refund_pct = Decimal(str(tier["refund_pct"]))
                break
    return round_cents(Decimal(charges) * refund_pct)


def _new_obligation(case_id, party, amount_cents, due_date):
    obligation = {
        "id": _uuid(),
        "withdrawal_case_id": case_id,
        "party": party,
        "amount_cents": amount_cents,
        "due_date": due_date,
        "status": "PENDING",
        "returned_at": None,
        "returned_amount_cents": None,
        "recorded_by_user_id": None,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.obligations[obligation["id"]] = obligation
    return obligation


def _new_offer(case_id, award_id, amount_cents, determination_date):
    offered_at = clock.now()
    offered_date = offered_at.date()
    offer = {
        "id": _uuid(),
        "withdrawal_case_id": case_id,
        "award_id": award_id,
        "amount_cents": amount_cents,
        "offered_at": clock.iso(offered_at),
        "response_deadline": date_str(offered_date + timedelta(days=OFFER_RESPONSE_DAYS)),
        "late_offer": offered_date > determination_date + timedelta(days=OFFER_CREATION_DAYS),
        "status": "SENT",
        "responded_at": None,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.offers[offer["id"]] = offer
    return offer


def _new_disbursement(award_id, amount_cents, status, pwd_offer_id, disbursed_on):
    disb = {
        "id": _uuid(),
        "award_id": award_id,
        "pwd_offer_id": pwd_offer_id,
        "amount_cents": amount_cents,
        "status": status,
        "disbursed_on": disbursed_on,
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.disbursements[disb["id"]] = disb
    return disb


def _uuid():
    import uuid
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Compensation cascade (recalculate / rescind)
# ---------------------------------------------------------------------------

def compensate_case_artifacts(case: dict):
    """Void outstanding obligations/offers and post REVERSAL entries negating
    each of the case's not-yet-reversed REFUND_CREDIT and R2T4_CHARGEBACK
    entries. An entry already negated by an earlier compensation (a prior
    recalculation) is skipped — reversing it twice would corrupt the ledger.
    """
    for obligation in db.obligations.values():
        if (obligation["withdrawal_case_id"] == case["id"]
                and obligation["status"] in ("PENDING", "OVERDUE")):
            obligation["status"] = "VOIDED"
            obligation["updated_at"] = clock.now_iso()
            obligation["version"] += 1

    for offer in db.offers.values():
        if (offer["withdrawal_case_id"] == case["id"]
                and offer["status"] == "SENT"):
            offer["status"] = "VOIDED"
            offer["updated_at"] = clock.now_iso()
            offer["version"] += 1

    case_obligation_ids = {o["id"] for o in db.obligations.values()
                           if o["withdrawal_case_id"] == case["id"]}
    already_reversed = {e["reversal_of_entry_id"]
                        for e in db.account_entries.values()
                        if e["entry_type"] == "REVERSAL"
                        and e.get("reversal_of_entry_id")}
    for entry in list(db.account_entries.values()):
        if entry["enrollment_id"] != case["enrollment_id"]:
            continue
        if entry["id"] in already_reversed:
            continue
        if entry["entry_type"] == "REFUND_CREDIT" and entry["source_ref"] == case["id"]:
            post_entry(case["enrollment_id"], "REVERSAL", -entry["amount_cents"],
                       source_ref=case["id"], reversal_of_entry_id=entry["id"])
        elif entry["entry_type"] == "R2T4_CHARGEBACK" and entry["source_ref"] in case_obligation_ids:
            post_entry(case["enrollment_id"], "REVERSAL", -entry["amount_cents"],
                       source_ref=entry["source_ref"], reversal_of_entry_id=entry["id"])


# ---------------------------------------------------------------------------
# Deadline sweep (clock set)
# ---------------------------------------------------------------------------

def run_deadline_sweep():
    """PENDING obligations past due_date -> OVERDUE; SENT offers past
    response_deadline -> EXPIRED; then auto-close evaluation on touched cases.
    """
    current = clock.current_date()
    touched_cases = set()

    for obligation in db.obligations.values():
        if obligation["status"] == "PENDING":
            if current > parse_date(obligation["due_date"]):
                obligation["status"] = "OVERDUE"
                obligation["updated_at"] = clock.now_iso()
                obligation["version"] += 1
                touched_cases.add(obligation["withdrawal_case_id"])

    for offer in db.offers.values():
        if offer["status"] == "SENT":
            if current > parse_date(offer["response_deadline"]):
                offer["status"] = "EXPIRED"
                offer["updated_at"] = clock.now_iso()
                offer["version"] += 1
                touched_cases.add(offer["withdrawal_case_id"])

    for case_id in touched_cases:
        evaluate_auto_close(case_id)
