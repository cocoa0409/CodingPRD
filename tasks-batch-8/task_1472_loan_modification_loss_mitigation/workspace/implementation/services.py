"""Business logic: calculations, state-machine cascades, serializers."""
from datetime import timedelta, date
from decimal import Decimal

import clock
import store
from util import (
    annuity_cents,
    bump,
    fmt_value,
    month_index,
    new_record,
    round_half_up_cents,
    serialize,
)

# ---------------------------------------------------------------------------
# domain constants
# ---------------------------------------------------------------------------
HARDSHIP_TYPES = ["UNEMPLOYMENT", "INCOME_REDUCTION", "MEDICAL", "DIVORCE", "DISASTER", "OTHER"]
DOC_TYPES = ["PAYSTUB", "TAX_RETURN", "PROFIT_LOSS", "BANK_STATEMENT", "HARDSHIP_AFFIDAVIT"]
PAY_FREQUENCIES = ["WEEKLY", "BIWEEKLY", "SEMIMONTHLY", "MONTHLY"]
ANALYSIS_TYPES = ["STANDARD_ANNUAL", "POST_MODIFICATION"]
APPEAL_OUTCOMES = ["AFFIRMED", "OVERTURNED"]

BLOCKING_APP_STATES = {"COMPLETE_PACKAGE", "EVALUATED_OFFER", "APPEAL_REVIEW", "TRIAL_ACTIVE", "TRIAL_PASSED"}
NON_TERMINAL_APP_STATES = {
    "SUBMITTED", "ACKNOWLEDGED", "COMPLETE_PACKAGE", "EVALUATED_OFFER",
    "EVALUATED_DENIAL", "APPEAL_REVIEW", "TRIAL_ACTIVE", "TRIAL_PASSED",
}
TERMINAL_APP_STATES = {"APPROVED", "CLOSED_DENIED", "WITHDRAWN"}

ACK_SLA_DAYS = 5
EVAL_SLA_DAYS = 30
TRIAL_PERIODS = 3
TRIAL_INTERVAL_DAYS = 30
OFFER_VALIDITY_DAYS = 30
APPEAL_WINDOW_DAYS = 14
APPEAL_ELIGIBILITY_MIN_DAYS = 90
SALE_BLOCK_MIN_DAYS = 37
REFERRAL_MIN_DELINQUENCY_DAYS = 120
MIN_SALE_NOTICE_DAYS = 14
RESCISSION_WINDOW_DAYS = 3
SURPLUS_REFUND_MIN_CENTS = 5000

# ---------------------------------------------------------------------------
# serialization field lists (exact entity fields from the scaffold)
# ---------------------------------------------------------------------------
BORROWER_FIELDS = ["id", "full_name", "email", "mailing_address", "status",
                   "created_at", "updated_at", "version"]
LOAN_FIELDS = ["id", "borrower_id", "loan_number", "property_state_code",
               "unpaid_principal_balance_cents", "interest_rate_bp", "remaining_term_months",
               "arrears_cents", "suspense_cents", "deferred_principal_cents",
               "escrow_balance_cents", "escrow_monthly_cents", "current_pi_cents",
               "delinquency_days", "workout_status", "foreclosure_status",
               "created_at", "updated_at", "version"]
APPLICATION_FIELDS = ["id", "loan_id", "hardship_type", "stated_monthly_income_cents",
                      "status", "verified_monthly_income_cents", "outstanding_doc_categories",
                      "completed_at", "acknowledgement_due_at", "acknowledged_at",
                      "evaluation_deadline", "active_evaluation_id",
                      "superseded_by_application_id", "created_at", "updated_at", "version"]
DOCUMENT_FIELDS = ["id", "application_id", "doc_type", "status", "gross_per_period_cents",
                   "pay_frequency", "pay_period_end_date", "annual_gross_cents",
                   "ytd_net_income_cents", "ytd_months", "rejection_reason", "received_at",
                   "created_at", "updated_at", "version"]
PROGRAM_FIELDS = ["id", "code", "waterfall_rank", "target_dti_bp", "rate_floor_bp",
                  "rate_step_bp", "max_term_months", "max_forbearance_pct_bp",
                  "min_delinquency_days", "max_delinquency_days", "status",
                  "created_at", "updated_at", "version"]
EVALUATION_FIELDS = ["id", "application_id", "underwriter_user_id", "evaluated_at",
                     "status", "result", "selected_program_id", "denial_reasons",
                     "eval_base_cents", "target_payment_cents", "offered_rate_bp",
                     "offered_term_months", "offered_forbearance_cents", "offered_pi_cents",
                     "created_at", "updated_at", "version"]
STEP_FIELDS = ["id", "evaluation_id", "program_code", "step_rank", "eligible",
               "achieved_pi_cents", "met_target", "selected", "created_at"]
PLAN_FIELDS = ["id", "application_id", "evaluation_id", "program_code",
               "trial_payment_cents", "periods", "first_due_date", "offer_deadline",
               "accepted_at", "suspense_total_cents", "status",
               "created_at", "updated_at", "version"]
PAYMENT_FIELDS = ["id", "trial_plan_id", "period_index", "due_date",
                  "scheduled_amount_cents", "received_amount_cents", "paid_at", "status",
                  "created_at", "updated_at", "version"]
MODIFICATION_FIELDS = ["id", "application_id", "trial_plan_id", "final_base_cents",
                       "final_rate_bp", "final_term_months", "final_forbearance_cents",
                       "final_pi_cents", "capitalized_arrears_cents",
                       "prior_terms_snapshot", "status", "recorded_at", "rescission_deadline",
                       "created_at", "updated_at", "version"]
NOTICE_FIELDS = ["id", "application_id", "evaluation_id", "underwriter_user_id",
                 "reasons", "issued_at", "appeal_deadline", "appeal_eligible", "status",
                 "created_at", "updated_at", "version"]
APPEAL_FIELDS = ["id", "denial_notice_id", "grounds", "submitted_at",
                 "reviewer_user_id", "decided_at", "status",
                 "created_at", "updated_at", "version"]
CASE_FIELDS = ["id", "loan_id", "county", "docket_number", "referred_at", "sale_date",
               "status", "created_at", "updated_at", "version"]
ANALYSIS_FIELDS = ["id", "loan_id", "modification_id", "analysis_type",
                   "comp_year_start_month", "comp_year_months",
                   "projected_annual_disbursements_cents", "cushion_cents",
                   "balance_at_analysis_cents", "shortage_cents", "surplus_cents",
                   "monthly_spread_cents", "spread_last_month_cents",
                   "new_monthly_escrow_cents", "refund_cents", "credit_cents", "status",
                   "created_at", "updated_at", "version"]


# ---------------------------------------------------------------------------
# graph traversal helpers
# ---------------------------------------------------------------------------
def loan_of_application(app):
    return store.loans.get(app["loan_id"])


def loan_of_plan(plan):
    return loan_of_application(store.applications[plan["application_id"]])


def loan_of_payment(payment):
    return loan_of_plan(store.plans[payment["trial_plan_id"]])


def loan_of_modification(mod):
    return loan_of_application(store.applications[mod["application_id"]])


def loan_of_notice(notice):
    return loan_of_application(store.applications[notice["application_id"]])


def loan_of_appeal(appeal):
    return loan_of_notice(store.notices[appeal["denial_notice_id"]])


def latest_active_case(loan_id):
    """Latest non-CANCELLED foreclosure case for the loan (or None)."""
    active = [c for c in store.cases.values()
              if c["loan_id"] == loan_id and c["status"] != "CANCELLED"]
    if not active:
        return None
    return max(active, key=lambda c: (c["created_at"], c["_seq"]))


def foreclosure_status_of(loan):
    case = latest_active_case(loan["id"])
    return "NONE" if case is None else case["status"]


# ---------------------------------------------------------------------------
# serializers
# ---------------------------------------------------------------------------
def loan_out(loan):
    extra = {
        "current_pi_cents": annuity_cents(
            loan["unpaid_principal_balance_cents"],
            loan["interest_rate_bp"],
            loan["remaining_term_months"],
        ),
        "foreclosure_status": foreclosure_status_of(loan),
    }
    return serialize(loan, LOAN_FIELDS, extra)


def borrower_out(rec):
    return serialize(rec, BORROWER_FIELDS)


def application_out(rec):
    return serialize(rec, APPLICATION_FIELDS)


def document_out(rec):
    return serialize(rec, DOCUMENT_FIELDS)


def program_out(rec):
    return serialize(rec, PROGRAM_FIELDS)


def evaluation_out(rec):
    return serialize(rec, EVALUATION_FIELDS)


def step_out(rec):
    return serialize(rec, STEP_FIELDS)


def plan_out(rec):
    return serialize(rec, PLAN_FIELDS)


def payment_out(rec):
    return serialize(rec, PAYMENT_FIELDS)


def modification_out(rec):
    return serialize(rec, MODIFICATION_FIELDS)


def notice_out(rec):
    return serialize(rec, NOTICE_FIELDS)


def appeal_out(rec):
    return serialize(rec, APPEAL_FIELDS)


def case_out(rec):
    return serialize(rec, CASE_FIELDS)


def analysis_out(rec):
    return serialize(rec, ANALYSIS_FIELDS)


# ---------------------------------------------------------------------------
# 3.4 verified income aggregation (per-source round-half-up, then sum)
# ---------------------------------------------------------------------------
def compute_verified_income(application_id):
    docs = [d for d in store.documents.values()
            if d["application_id"] == application_id and d["status"] == "ACCEPTED"]

    paystub_monthly = 0
    paystubs = [d for d in docs if d["doc_type"] == "PAYSTUB"]
    if paystubs:
        winner = max(paystubs, key=lambda d: (
            d.get("pay_period_end_date") or date.min,
            d["received_at"],
            d["_seq"],
        ))
        gross = winner.get("gross_per_period_cents") or 0
        mult = {"WEEKLY": (52, 12), "BIWEEKLY": (26, 12),
                "SEMIMONTHLY": (2, 1), "MONTHLY": (1, 1)}.get(winner.get("pay_frequency"))
        if mult is not None:
            paystub_monthly = round_half_up_cents(
                Decimal(gross) * mult[0] / Decimal(mult[1]))

    tax_total = 0
    for d in docs:
        if d["doc_type"] == "TAX_RETURN":
            tax_total += round_half_up_cents(
                Decimal(d.get("annual_gross_cents") or 0) / Decimal(12))

    pl_total = 0
    for d in docs:
        if d["doc_type"] == "PROFIT_LOSS" and d.get("ytd_months"):
            pl_total += round_half_up_cents(
                Decimal(d.get("ytd_net_income_cents") or 0) / Decimal(d["ytd_months"]))

    return paystub_monthly + tax_total + pl_total


def compute_outstanding_categories(application_id):
    docs = [d for d in store.documents.values()
            if d["application_id"] == application_id and d["status"] == "ACCEPTED"]
    out = []
    if not any(d["doc_type"] in ("PAYSTUB", "TAX_RETURN", "PROFIT_LOSS") for d in docs):
        out.append("INCOME_PROOF")
    if not any(d["doc_type"] == "HARDSHIP_AFFIDAVIT" for d in docs):
        out.append("HARDSHIP_AFFIDAVIT")
    if not any(d["doc_type"] == "BANK_STATEMENT" for d in docs):
        out.append("BANK_STATEMENT")
    return out


def recompute_application_package(app):
    """Recompute verified income + outstanding categories after a document
    accept/supersede; drives ACKNOWLEDGED <-> COMPLETE_PACKAGE transitions."""
    app["verified_monthly_income_cents"] = compute_verified_income(app["id"])
    outstanding = compute_outstanding_categories(app["id"])
    app["outstanding_doc_categories"] = outstanding
    if not outstanding and app["status"] == "ACKNOWLEDGED":
        app["status"] = "COMPLETE_PACKAGE"
        if app["completed_at"] is None:
            app["completed_at"] = clock.now()
        app["evaluation_deadline"] = app["completed_at"] + timedelta(days=EVAL_SLA_DAYS)
    elif outstanding and app["status"] == "COMPLETE_PACKAGE":
        app["status"] = "ACKNOWLEDGED"  # completed_at retained (first-completion anchor)
    bump(app)


# ---------------------------------------------------------------------------
# 3.6 waterfall modified payment (provisional and final variants)
# ---------------------------------------------------------------------------
def target_payment_cents(verified_income_cents, program):
    return round_half_up_cents(
        Decimal(verified_income_cents) * program["target_dti_bp"] / Decimal(10000))


def run_waterfall_variant(loan, verified_income_cents, program):
    base = loan["unpaid_principal_balance_cents"] + loan["arrears_cents"]
    target = target_payment_cents(verified_income_cents, program)
    rate = loan["interest_rate_bp"]
    term = loan["remaining_term_months"]

    # Step 1 - rate reduction loop (stop at floor)
    while rate > program["rate_floor_bp"] and annuity_cents(base, rate, term) > target:
        rate = max(program["rate_floor_bp"], rate - program["rate_step_bp"])

    # Step 2 - term extension (single jump to max)
    if annuity_cents(base, rate, term) > target:
        term = program["max_term_months"]

    # Step 3 - principal forbearance
    forborne = 0
    if annuity_cents(base, rate, term) > target:
        cap = round_half_up_cents(
            Decimal(base) * program["max_forbearance_pct_bp"] / Decimal(10000))
        r = rate / 10000.0 / 12.0
        if r == 0 or term <= 0:
            needed = base - target * max(term, 0)
        else:
            needed = round_half_up_cents(
                base - target * (1.0 - (1.0 + r) ** (-term)) / r)
        forborne = max(0, min(cap, needed))

    achieved = annuity_cents(base - forborne, rate, term)
    return {
        "base": base,
        "target": target,
        "rate": rate,
        "term": term,
        "forborne": forborne,
        "pi": achieved,
        "met": achieved <= target,
    }


# ---------------------------------------------------------------------------
# workout revert helper (application reached terminal / withdrawn)
# ---------------------------------------------------------------------------
def maybe_revert_workout(loan):
    if loan["workout_status"] != "LOSS_MIT_REVIEW":
        return
    for a in store.applications.values():
        if a["loan_id"] == loan["id"] and a["status"] in NON_TERMINAL_APP_STATES:
            return
    loan["workout_status"] = "DELINQUENT"
    bump(loan)


def withdraw_application(app, superseded_by_id=None):
    app["status"] = "WITHDRAWN"
    if superseded_by_id is not None:
        app["superseded_by_application_id"] = superseded_by_id
    bump(app)
    for p in store.plans.values():
        if p["application_id"] == app["id"] and p["status"] == "OFFERED":
            p["status"] = "CANCELLED"
            bump(p)
    loan = loan_of_application(app)
    if loan is not None:
        maybe_revert_workout(loan)


# ---------------------------------------------------------------------------
# denial notices / appeal eligibility (3.8)
# ---------------------------------------------------------------------------
def compute_appeal_eligible(loan, app):
    case = latest_active_case(loan["id"])
    if case is None or case["status"] not in ("SALE_SCHEDULED", "SALE_HOLD"):
        return True
    sale_date = case.get("sale_date")
    if sale_date is None or app.get("completed_at") is None:
        return False
    return app["completed_at"].date() <= sale_date - timedelta(days=APPEAL_ELIGIBILITY_MIN_DAYS)


def create_denial_notice(app, evaluation_id, underwriter_user_id, reasons):
    loan = loan_of_application(app)
    rec = new_record()
    rec.update({
        "application_id": app["id"],
        "evaluation_id": evaluation_id,
        "underwriter_user_id": underwriter_user_id,
        "reasons": list(reasons),
        "issued_at": clock.now(),
        "appeal_deadline": clock.now() + timedelta(days=APPEAL_WINDOW_DAYS),
        "appeal_eligible": compute_appeal_eligible(loan, app) if loan else True,
        "status": "ISSUED",
    })
    store.notices[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# 3.7 trial plan terminal cascades
# ---------------------------------------------------------------------------
def _apply_suspense(loan, suspense_total):
    arrears = loan["arrears_cents"]
    loan["arrears_cents"] = max(0, arrears - suspense_total)
    overflow = suspense_total - arrears
    if overflow > 0:
        loan["unpaid_principal_balance_cents"] -= overflow
    loan["suspense_cents"] = 0


def complete_plan(plan):
    loan = loan_of_plan(plan)
    app = store.applications[plan["application_id"]]
    _apply_suspense(loan, plan["suspense_total_cents"])
    plan["status"] = "COMPLETED"
    bump(plan)
    if app["status"] == "TRIAL_ACTIVE":
        app["status"] = "TRIAL_PASSED"
        bump(app)
    if loan["workout_status"] == "TRIAL":
        loan["workout_status"] = "MOD_PENDING"
    bump(loan)


def fail_plan(plan):
    loan = loan_of_plan(plan)
    app = store.applications[plan["application_id"]]
    _apply_suspense(loan, plan["suspense_total_cents"])
    plan["status"] = "FAILED"
    bump(plan)
    if app["status"] == "TRIAL_ACTIVE":
        app["status"] = "EVALUATED_DENIAL"
        bump(app)
        create_denial_notice(app, None, "system", ["TRIAL_PLAN_FAILED"])
    if loan["workout_status"] == "TRIAL":
        loan["workout_status"] = "LOSS_MIT_REVIEW"
    bump(loan)


# ---------------------------------------------------------------------------
# 3.6 evaluation creation (OFFER / DENIAL + side effects)
# ---------------------------------------------------------------------------
def run_evaluation(app, underwriter_user_id):
    loan = loan_of_application(app)
    verified = app["verified_monthly_income_cents"]
    base = loan["unpaid_principal_balance_cents"] + loan["arrears_cents"]

    ev = new_record()
    ev.update({
        "application_id": app["id"],
        "underwriter_user_id": underwriter_user_id,
        "evaluated_at": clock.now(),
        "status": "ACTIVE",
        "result": None,
        "selected_program_id": None,
        "denial_reasons": [],
        "eval_base_cents": base,
        "target_payment_cents": None,
        "offered_rate_bp": None,
        "offered_term_months": None,
        "offered_forbearance_cents": None,
        "offered_pi_cents": None,
    })

    created_steps = []

    def add_step(program, eligible, achieved, met, selected):
        st = {
            "id": store.new_id(),
            "created_at": clock.now(),
            "_seq": store.next_seq(),
            "evaluation_id": ev["id"],
            "program_code": program["code"],
            "step_rank": program["waterfall_rank"],
            "eligible": eligible,
            "achieved_pi_cents": achieved,
            "met_target": met,
            "selected": selected,
        }
        store.steps[st["id"]] = st
        created_steps.append(st)

    selected_program = None
    selected_result = None

    if verified == 0:
        ev["result"] = "DENIAL"
        ev["denial_reasons"] = ["INCOME_UNVERIFIABLE"]
    else:
        programs = sorted(
            [p for p in store.programs.values() if p["status"] == "ACTIVE"],
            key=lambda p: (p["waterfall_rank"], p["created_at"], p["_seq"]),
        )
        any_eligible = False
        last_target = None
        for prog in programs:
            eligible = (prog["min_delinquency_days"] <= loan["delinquency_days"]
                        <= prog["max_delinquency_days"])
            if not eligible:
                add_step(prog, False, None, None, False)
                continue
            any_eligible = True
            res = run_waterfall_variant(loan, verified, prog)
            last_target = res["target"]
            is_selected = res["met"] and selected_program is None
            add_step(prog, True, res["pi"], res["met"], is_selected)
            if is_selected:
                selected_program = prog
                selected_result = res
                break  # waterfall stops at the first qualifying program
        if selected_program is not None:
            ev["result"] = "OFFER"
            ev["selected_program_id"] = selected_program["id"]
            ev["target_payment_cents"] = selected_result["target"]
            ev["offered_rate_bp"] = selected_result["rate"]
            ev["offered_term_months"] = selected_result["term"]
            ev["offered_forbearance_cents"] = selected_result["forborne"]
            ev["offered_pi_cents"] = selected_result["pi"]
        else:
            ev["result"] = "DENIAL"
            ev["target_payment_cents"] = last_target
            ev["denial_reasons"] = (
                ["NO_ELIGIBLE_PROGRAM"] if not any_eligible else ["TARGET_NOT_ACHIEVABLE"])

    # supersede prior ACTIVE evaluation on the same application
    for other in store.evaluations.values():
        if (other["application_id"] == app["id"] and other["status"] == "ACTIVE"
                and other["id"] != ev["id"]):
            other["status"] = "SUPERSEDED"
            bump(other)
    store.evaluations[ev["id"]] = ev
    app["active_evaluation_id"] = ev["id"]

    if ev["result"] == "OFFER":
        app["status"] = "EVALUATED_OFFER"
        bump(app)
        _create_trial_plan(app, ev, selected_program, loan)
    else:
        app["status"] = "EVALUATED_DENIAL"
        bump(app)
        create_denial_notice(app, ev["id"], underwriter_user_id, ev["denial_reasons"])
    return ev


def _create_trial_plan(app, ev, program, loan):
    created = clock.now()
    first_due = created.date() + timedelta(days=TRIAL_INTERVAL_DAYS)
    plan = new_record()
    plan.update({
        "application_id": app["id"],
        "evaluation_id": ev["id"],
        "program_code": program["code"],
        "trial_payment_cents": ev["offered_pi_cents"] + loan["escrow_monthly_cents"],
        "periods": TRIAL_PERIODS,
        "first_due_date": first_due,
        "offer_deadline": created + timedelta(days=OFFER_VALIDITY_DAYS),
        "accepted_at": None,
        "suspense_total_cents": 0,
        "status": "OFFERED",
    })
    store.plans[plan["id"]] = plan
    for i in range(1, TRIAL_PERIODS + 1):
        pay = new_record()
        pay.update({
            "trial_plan_id": plan["id"],
            "period_index": i,
            "due_date": first_due + timedelta(days=TRIAL_INTERVAL_DAYS * (i - 1)),
            "scheduled_amount_cents": plan["trial_payment_cents"],
            "received_amount_cents": None,
            "paid_at": None,
            "status": "SCHEDULED",
        })
        store.payments[pay["id"]] = pay
    return plan


# ---------------------------------------------------------------------------
# 3.11 escrow analysis computed fields
# ---------------------------------------------------------------------------
def compute_escrow_fields(disbursements, balance, months):
    cushion = round_half_up_cents(Decimal(disbursements) * 2 / Decimal(12))
    base_monthly = round_half_up_cents(Decimal(disbursements) / Decimal(12))
    shortage = max(0, cushion - balance)
    surplus = max(0, balance - cushion)
    monthly_spread = round_half_up_cents(Decimal(shortage) / Decimal(months))
    last_month = shortage - monthly_spread * (months - 1)
    new_monthly = base_monthly + monthly_spread
    refund = surplus if surplus >= SURPLUS_REFUND_MIN_CENTS else 0
    credit = surplus if 0 < surplus < SURPLUS_REFUND_MIN_CENTS else 0
    return {
        "cushion_cents": cushion,
        "balance_at_analysis_cents": balance,
        "shortage_cents": shortage,
        "surplus_cents": surplus,
        "monthly_spread_cents": monthly_spread,
        "spread_last_month_cents": last_month,
        "new_monthly_escrow_cents": new_monthly,
        "refund_cents": refund,
        "credit_cents": credit,
    }


def create_escrow_analysis(loan, analysis_type, start_month, months,
                           disbursements, modification_id=None):
    rec = new_record()
    rec.update({
        "loan_id": loan["id"],
        "modification_id": modification_id,
        "analysis_type": analysis_type,
        "comp_year_start_month": start_month,
        "comp_year_months": months,
        "projected_annual_disbursements_cents": disbursements,
        "status": "DRAFT",
    })
    rec.update(compute_escrow_fields(disbursements, loan["escrow_balance_cents"], months))
    store.analyses[rec["id"]] = rec
    return rec


def escrow_window_overlaps(loan_id, start_month, months):
    new_start = month_index(start_month)
    new_end = new_start + months
    for a in store.analyses.values():
        if a["loan_id"] != loan_id or a["status"] in ("VOIDED", "CANCELLED"):
            continue
        s = month_index(a["comp_year_start_month"])
        e = s + a["comp_year_months"]
        if new_start < e and s < new_end:
            return True
    return False
