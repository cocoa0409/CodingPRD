"""Domain service: ledger recomputation, ssi posture, eligibility, serialization.

The Account stores running ledger figures (balance/basis/earnings) directly,
mutated by each operation. Year-to-date accumulators are derived dynamically
from the children, scoped to the calendar year of the logical clock, so that
advancing the clock changes them correctly.
"""
from datetime import date

from clock import clock
from db import db


def _parse_date(s):
    """Parse an ISO 8601 date (YYYY-MM-DD or full datetime) into a date."""
    if s is None:
        return None
    s = str(s)
    return date.fromisoformat(s[:10])


# ---------------------------------------------------------------------------
# Year-to-date accumulators (calendar year of the logical clock)
# ---------------------------------------------------------------------------
def regular_ytd(account_id):
    year = clock.current_year()
    total = 0
    for c in db.contributions.values():
        if c["account_id"] != account_id:
            continue
        if c["status"] != "POSTED":
            continue
        if c["contribution_type"] not in ("REGULAR", "ROLLOVER_529"):
            continue
        if _parse_date(c["contribution_date"]).year != year:
            continue
        total += c["amount_cents"]
    return total


def atw_ytd(account_id):
    year = clock.current_year()
    total = 0
    for c in db.contributions.values():
        if c["account_id"] != account_id:
            continue
        if c["status"] != "POSTED":
            continue
        if c["contribution_type"] != "ABLE_TO_WORK":
            continue
        if _parse_date(c["contribution_date"]).year != year:
            continue
        total += c["amount_cents"]
    return total


def investment_changes_ytd(account):
    year = clock.current_year()
    return sum(1 for d in account.get("_investment_change_dates", [])
               if _parse_date(d).year == year)


# ---------------------------------------------------------------------------
# SSI posture (ssi_asset_disregard calculation)
# ---------------------------------------------------------------------------
def ssi_able_countable(account, program):
    return max(0, account["balance_cents"] - program["ssi_suspension_threshold_cents"])


def ssi_total_countable(account, program, beneficiary):
    return beneficiary["other_countable_resources_cents"] + ssi_able_countable(account, program)


def compute_ssi_posture(account, program, beneficiary):
    total = ssi_total_countable(account, program, beneficiary)
    if total > program["ssi_resource_limit_cents"]:
        return "SSI_SUSPENDED"
    return "SSI_OK"


def recompute_ssi_posture(account):
    program = db.programs[
        db.beneficiaries[account["beneficiary_id"]]["program_id"]
    ]
    beneficiary = db.beneficiaries[account["beneficiary_id"]]
    account["ssi_posture"] = compute_ssi_posture(account, program, beneficiary)


# ---------------------------------------------------------------------------
# Eligibility status (computed on Beneficiary)
# ---------------------------------------------------------------------------
def compute_eligibility_status(beneficiary_id):
    certs = [c for c in db.certifications.values()
             if c["beneficiary_id"] == beneficiary_id]
    if not certs:
        return "UNCERTIFIED"
    today = clock.now_date()
    # CERTIFIED when a CERTIFIED cert's half-open window [effective, expires) contains now
    for c in certs:
        if c["status"] == "CERTIFIED":
            eff = _parse_date(c["effective_date"])
            exp = _parse_date(c["expires_on"])
            if eff <= today < exp:
                return "CERTIFIED"
    # otherwise mirror the cert with greatest effective_date, tie-break greatest created_at
    def keyfn(c):
        return (_parse_date(c["effective_date"]), c["created_at"], c["_seq"])
    chosen = max(certs, key=keyfn)
    return chosen["status"]


# ---------------------------------------------------------------------------
# Clock advance side effects: expire certs, suspend accounts
# ---------------------------------------------------------------------------
def apply_clock_effects():
    today = clock.now_date()
    for c in list(db.certifications.values()):
        if c["status"] == "CERTIFIED":
            exp = _parse_date(c["expires_on"])
            if today >= exp:
                c["status"] = "EXPIRED"
                from db import touch
                touch(c)
                # suspend owning OPEN account
                ben_id = c["beneficiary_id"]
                for acct in db.accounts.values():
                    if acct["beneficiary_id"] == ben_id and acct["status"] == "OPEN":
                        acct["status"] = "SUSPENDED"
                        touch(acct)


# ---------------------------------------------------------------------------
# Serializers — produce public representation (strip internals, add computed)
# ---------------------------------------------------------------------------
COMMON = ["id", "created_at", "updated_at", "version"]


def _base(obj, fields):
    out = {}
    for f in COMMON:
        out[f] = obj[f]
    for f in fields:
        out[f] = obj.get(f)
    return out


def serialize_program(p):
    return _base(p, [
        "name", "state_code", "annual_contribution_cap_cents",
        "able_to_work_fpl_cents", "ssi_suspension_threshold_cents",
        "ssi_resource_limit_cents", "program_fee_bps",
        "nonqualified_additional_tax_pct", "max_investment_changes_per_year",
        "disability_onset_max_age",
    ])


def serialize_investment_option(o):
    return _base(o, ["program_id", "name", "risk_tier", "is_open"])


def serialize_beneficiary(b):
    out = _base(b, [
        "program_id", "full_name", "birth_date", "disability_onset_date",
        "state_code", "other_countable_resources_cents", "receives_ssi",
        "receives_medicaid", "employer_retirement_plan_participant",
        "gross_employment_income_ytd_cents", "is_deceased",
    ])
    out["eligibility_status"] = compute_eligibility_status(b["id"])
    return out


def serialize_certification(c):
    return _base(c, [
        "beneficiary_id", "basis", "diagnosis_code", "effective_date",
        "expires_on", "status",
    ])


def serialize_account(a):
    out = _base(a, [
        "beneficiary_id", "investment_option_id", "status",
        "balance_cents", "basis_cents", "earnings_cents", "ssi_posture",
        "medicaid_paid_since_open_cents", "premiums_paid_by_beneficiary_cents",
    ])
    out["regular_contrib_ytd_cents"] = regular_ytd(a["id"])
    out["atw_contrib_ytd_cents"] = atw_ytd(a["id"])
    out["investment_changes_ytd"] = investment_changes_ytd(a)
    return out


def serialize_representative(r):
    return _base(r, [
        "account_id", "full_name", "relationship", "authority_start",
        "authority_end", "status",
    ])


def serialize_contribution(c):
    return _base(c, [
        "account_id", "contribution_type", "amount_cents", "source_529_plan",
        "contribution_date", "status",
    ])


def serialize_distribution(d):
    return _base(d, [
        "account_id", "amount_cents", "category", "status",
        "earnings_portion_cents", "qualified_amount_cents",
        "nonqualified_amount_cents", "additional_tax_cents",
        "counts_against_ssi_housing",
    ])


def serialize_qde_record(q):
    return _base(q, [
        "distribution_id", "expense_category", "amount_cents",
        "receipt_reference", "expense_date",
    ])


def serialize_medicaid_claim(m):
    return _base(m, [
        "account_id", "claimed_amount_cents", "allowed_payback_cents",
        "residual_to_estate_cents", "status",
    ])
