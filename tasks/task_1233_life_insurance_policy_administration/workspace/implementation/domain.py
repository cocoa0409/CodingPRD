"""Domain constants, enums, record factories, and serializers.

Only fields declared in SCAFFOLD.yaml §1.1 (plus common fields) are serialized.
Internal bookkeeping attributes are prefixed with "_" and never serialized.
"""
from db import store
from util import fmt_ts, fmt_date

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
GENDERS = {"MALE", "FEMALE", "OTHER"}
PRODUCT_TYPES = {
    "WHOLE_LIFE_PARTICIPATING", "WHOLE_LIFE_NON_PARTICIPATING",
    "TERM_CONVERTIBLE", "UNIVERSAL_LIFE",
}
PREMIUM_MODES = {"MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL"}
MODE_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "SEMI_ANNUAL": 6, "ANNUAL": 12}
UNDERWRITING_CLASSES = {
    "PREFERRED_NON_TOBACCO", "STANDARD_NON_TOBACCO",
    "PREFERRED_TOBACCO", "STANDARD_TOBACCO",
    "SUBSTANDARD_TABLE_B", "SUBSTANDARD_TABLE_D",
}
NON_TOBACCO_CLASSES = {"PREFERRED_NON_TOBACCO", "STANDARD_NON_TOBACCO"}
TOBACCO_CLASSES = {"PREFERRED_TOBACCO", "STANDARD_TOBACCO"}
SUBSTANDARD_EXTRA_BPS = {"SUBSTANDARD_TABLE_B": 2500, "SUBSTANDARD_TABLE_D": 5000}

CLASS_MULT = {
    "PREFERRED_NON_TOBACCO": "0.90",
    "STANDARD_NON_TOBACCO": "1.00",
    "PREFERRED_TOBACCO": "1.50",
    "STANDARD_TOBACCO": "1.80",
    "SUBSTANDARD_TABLE_B": "2.00",
    "SUBSTANDARD_TABLE_D": "2.50",
}
MODE_FACTOR = {
    "MONTHLY": "1.00",
    "QUARTERLY": "2.94",
    "SEMI_ANNUAL": "5.82",
    "ANNUAL": "11.52",
}

DIVIDEND_OPTIONS = {"CASH", "PREMIUM_REDUCTION", "ACCUMULATE_AT_INTEREST", "PAID_UP_ADDITIONS"}
ELECTION_TYPES = {"CASH_SURRENDER", "REDUCED_PAID_UP", "EXTENDED_TERM"}
RIDER_TYPES = {"WAIVER_OF_PREMIUM", "ACCIDENTAL_DEATH_BENEFIT", "TERM_CHILD", "GUARANTEED_INSURABILITY"}
ZERO_FACE_RIDER_TYPES = {"WAIVER_OF_PREMIUM", "GUARANTEED_INSURABILITY"}
EXERCISABLE_RIDER_TYPES = {"WAIVER_OF_PREMIUM", "GUARANTEED_INSURABILITY"}

LOAN_ANNUAL_INTEREST_RATE_BPS = 500
GRACE_PERIOD_DAYS = 31
REINSTATEMENT_ANNUAL_RATE = "0.06"
FIVE_YEARS_DAYS = 5 * 365

# Terminal states (PRD §2.8 / state machines). PRD §3.2 names DECLINED alone
# as the application's terminal state; ISSUED is non-terminal, so operations
# on an issued application surface ERR_INVALID_STATE, not ERR_ALREADY_TERMINAL.
APP_TERMINAL = {"DECLINED"}
POLICY_FORM_TERMINAL = {"SURRENDERED", "DEATH_CLAIMED", "CONVERTED"}
CYCLE_TERMINAL = {"PAID", "LAPSED", "WAIVED"}
LOAN_TERMINAL = {"REPAID", "FORECLOSED"}
REINSTATEMENT_TERMINAL = {"APPROVED", "DECLINED"}
CONVERSION_TERMINAL = {"APPROVED", "DECLINED"}
RIDER_TERMINAL = {"TERMINATED", "EXERCISED"}
DIVIDEND_TERMINAL = {"APPLIED", "FORFEITED"}

# Cash-value ledger entry types
ENTRY_PREMIUM_CREDIT = "PREMIUM_CREDIT"
ENTRY_COI_DEBIT = "COI_DEBIT"
ENTRY_LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT"
ENTRY_LOAN_REPAYMENT_CREDIT = "LOAN_REPAYMENT_CREDIT"
ENTRY_DIVIDEND_CREDIT = "DIVIDEND_CREDIT"
ENTRY_RIDER_PREMIUM_DEBIT = "RIDER_PREMIUM_DEBIT"
ENTRY_SURRENDER_DEBIT = "SURRENDER_DEBIT"
ENTRY_MONTHLY_FEE_DEBIT = "MONTHLY_FEE_DEBIT"


# ---------------------------------------------------------------------------
# Record factory helpers
# ---------------------------------------------------------------------------
def stamp_new(rec):
    """Add id, created_at, updated_at, version, _seq to a new record."""
    now = store.current_datetime()
    rec["id"] = store.new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def stamp_append_only(rec):
    """LoanInterestAccrual / CashValueLedgerEntry: only id and created_at."""
    rec["id"] = store.new_id()
    rec["created_at"] = store.current_datetime()
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = store.current_datetime()
    rec["version"] = rec.get("version", 1) + 1


def touch_policy(policy):
    touch(policy)


def policy_year_of(policy):
    """Current policy year, 1-based, from issue_date and the logical clock."""
    days = (store.current_date() - policy["issue_date"]).days
    year = days // 365 + 1
    return max(1, year)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def serialize_insured(p):
    out = _common(p)
    out.update({
        "full_name": p["full_name"],
        "date_of_birth": fmt_date(p["date_of_birth"]),
        "tobacco_user": p["tobacco_user"],
        "gender": p["gender"],
    })
    return out


def serialize_template(t):
    out = _common(t)
    out.update({
        "product_code": t["product_code"],
        "product_type": t["product_type"],
        "participating": t["participating"],
        "allows_policy_loans": t["allows_policy_loans"],
        "min_face_amount_cents": t["min_face_amount_cents"],
        "max_face_amount_cents": t["max_face_amount_cents"],
        "base_monthly_premium_rate_per_thousand_cents":
            t["base_monthly_premium_rate_per_thousand_cents"],
        "coi_rate_table": t.get("coi_rate_table", []),
        "surrender_charge_schedule": t.get("surrender_charge_schedule", []),
    })
    return out


def serialize_application(a):
    out = _common(a)
    out.update({
        "insured_person_id": a["insured_person_id"],
        "product_template_id": a["product_template_id"],
        "requested_face_amount_cents": a["requested_face_amount_cents"],
        "premium_mode": a["premium_mode"],
        "underwriting_class": a.get("underwriting_class"),
        "substandard_extra_pct_bps": a.get("substandard_extra_pct_bps"),
        "status": a["status"],
    })
    return out


def serialize_policy(p):
    out = _common(p)
    out.update({
        "application_id": p["application_id"],
        "insured_person_id": p["insured_person_id"],
        "product_template_id": p["product_template_id"],
        "policy_number": p["policy_number"],
        "issue_date": fmt_date(p["issue_date"]),
        "face_amount_cents": p["face_amount_cents"],
        "premium_mode": p["premium_mode"],
        "modal_premium_cents": p["modal_premium_cents"],
        "underwriting_class": p["underwriting_class"],
        "premium_payment_status": p["premium_payment_status"],
        "form_status": p["form_status"],
        "grace_period_end_date": (fmt_date(p["grace_period_end_date"])
                                  if p.get("grace_period_end_date") else None),
        "cash_value_cents": p["cash_value_cents"],
        "outstanding_loan_principal_cents": p["outstanding_loan_principal_cents"],
        "accrued_loan_interest_cents": p["accrued_loan_interest_cents"],
        "dividend_accumulation_cents": p["dividend_accumulation_cents"],
        "dividend_option": p["dividend_option"],
        "paid_to_date": fmt_date(p["paid_to_date"]),
        "attained_age_at_issue": p["attained_age_at_issue"],
        "policy_year": policy_year_of(p),
    })
    return out


def serialize_cycle(c):
    out = _common(c)
    out.update({
        "policy_id": c["policy_id"],
        "cycle_index": c["cycle_index"],
        "period_start_date": fmt_date(c["period_start_date"]),
        "period_end_date": fmt_date(c["period_end_date"]),
        "due_amount_cents": c["due_amount_cents"],
        "paid_amount_cents": c["paid_amount_cents"],
        "status": c["status"],
    })
    return out


def serialize_loan(l):
    out = _common(l)
    out.update({
        "policy_id": l["policy_id"],
        "requested_amount_cents": l["requested_amount_cents"],
        "origination_date": fmt_date(l["origination_date"]),
        "annual_interest_rate_bps": l["annual_interest_rate_bps"],
        "outstanding_principal_cents": l["outstanding_principal_cents"],
        "accrued_interest_cents": l["accrued_interest_cents"],
        "last_accrual_date": fmt_date(l["last_accrual_date"]),
        "status": l["status"],
    })
    return out


def serialize_accrual(a):
    return {
        "id": a["id"],
        "created_at": fmt_ts(a["created_at"]),
        "loan_id": a["loan_id"],
        "accrual_period_start": fmt_date(a["accrual_period_start"]),
        "accrual_period_end": fmt_date(a["accrual_period_end"]),
        "principal_base_cents": a["principal_base_cents"],
        "days_accrued": a["days_accrued"],
        "interest_accrued_cents": a["interest_accrued_cents"],
    }


def serialize_dividend(d):
    out = _common(d)
    out.update({
        "policy_id": d["policy_id"],
        "policy_year": d["policy_year"],
        "declared_amount_cents": d["declared_amount_cents"],
        "applied_amount_cents": d["applied_amount_cents"],
        "status": d["status"],
    })
    return out


def serialize_election(e):
    out = _common(e)
    out.update({
        "policy_id": e["policy_id"],
        "election_type": e["election_type"],
        "effective_date": fmt_date(e["effective_date"]),
        "cash_value_at_election_cents": e["cash_value_at_election_cents"],
        "outstanding_loan_offset_cents": e["outstanding_loan_offset_cents"],
        "surrender_charge_cents": e["surrender_charge_cents"],
        "net_available_cents": e["net_available_cents"],
        "resulting_face_amount_cents": e["resulting_face_amount_cents"],
        "resulting_term_months": e["resulting_term_months"],
        "payout_cents": e["payout_cents"],
    })
    return out


def serialize_reinstatement(r):
    out = _common(r)
    out.update({
        "policy_id": r["policy_id"],
        "request_date": fmt_date(r["request_date"]),
        "back_premium_due_cents": r["back_premium_due_cents"],
        "back_premium_paid_cents": r["back_premium_paid_cents"],
        "evidence_of_insurability": r["evidence_of_insurability"],
        "underwriter_decision": r["underwriter_decision"],
        "status": r["status"],
    })
    return out


def serialize_rider(r):
    out = _common(r)
    out.update({
        "policy_id": r["policy_id"],
        "rider_type": r["rider_type"],
        "rider_face_amount_cents": r["rider_face_amount_cents"],
        "rider_monthly_premium_cents": r["rider_monthly_premium_cents"],
        "status": r["status"],
    })
    return out


def serialize_conversion(c):
    out = _common(c)
    out.update({
        "source_policy_id": c["source_policy_id"],
        "target_product_template_id": c["target_product_template_id"],
        "requested_face_amount_cents": c["requested_face_amount_cents"],
        "attained_age_at_conversion": c["attained_age_at_conversion"],
        "new_policy_id": c.get("new_policy_id"),
        "status": c["status"],
    })
    return out


def serialize_ledger_entry(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "policy_id": e["policy_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "posting_date": fmt_date(e["posting_date"]),
        "resulting_cash_value_cents": e["resulting_cash_value_cents"],
    }


def sorted_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def template_of(policy):
    return store.product_templates.get(policy["product_template_id"])


def insured_of(policy):
    return store.insured_persons.get(policy["insured_person_id"])


def policy_builds_cash_value(policy):
    """TERM_CONVERTIBLE policies do not accumulate cash value from premiums."""
    t = template_of(policy)
    return bool(t) and t["product_type"] != "TERM_CONVERTIBLE"
