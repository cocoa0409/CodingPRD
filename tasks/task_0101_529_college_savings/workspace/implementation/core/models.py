"""Model construction helpers + serialization helpers.

Entities with common_fields=true expose id/created_at/updated_at/version.
Contribution, EducationExpense, and TaxReport expose only id/created_at.
"""

from core.store import STORE, gen_id
from core.clock import CLOCK


def _new_common(common: bool):
    """Allocate common fields. created_at is the current logical clock instant.
    Returns (id, created_seq, base_dict)."""
    rid = gen_id()
    seq = STORE.next_seq()
    iso = CLOCK.now_iso()
    base = {
        "id": rid,
        "created_at": iso,
        "_created_seq": seq,
    }
    if common:
        base["updated_at"] = iso
        base["version"] = 1
    return rid, seq, base


def touch(row):
    """Refresh updated_at and bump version for rows that carry those fields."""
    if "version" in row:
        row["updated_at"] = CLOCK.now_iso()
        row["version"] = row["version"] + 1


def _public(row, drop=None):
    """Strip private underscore-prefixed fields for response."""
    drop = drop or set()
    return {k: v for k, v in row.items() if not k.startswith("_") and k not in drop}


# ----------------- Donor -----------------
def donor_view(row):
    return _public(row)


def donor_create(full_name, state_of_residence, ssn_last_four):
    _id, _seq, base = _new_common(True)
    base.update({
        "full_name": full_name,
        "state_of_residence": state_of_residence,
        "ssn_last_four": ssn_last_four,
        "ytd_contribution_total_cents": 0,
        "ytd_state_deduction_used_cents": 0,
        "_ytd_year": None,           # for annual reset bookkeeping
        "_ytd_deduction_year": None,
    })
    STORE.donors[_id] = base
    return base


# ----------------- Beneficiary -----------------
def beneficiary_view(row):
    return _public(row)


def beneficiary_create(full_name, date_of_birth, ssn_last_four, relationship_family_code):
    _id, _seq, base = _new_common(True)
    base.update({
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "ssn_last_four": ssn_last_four,
        "relationship_family_code": relationship_family_code,
        "k12_ytd_qualified_cents": 0,
        "_k12_ytd_year": None,
    })
    STORE.beneficiaries[_id] = base
    return base


# ----------------- Account -----------------
def account_view(row):
    return _public(row)


def account_create(primary_donor_id, beneficiary_id, state_plan_code, state_rule):
    _id, _seq, base = _new_common(True)
    base.update({
        "primary_donor_id": primary_donor_id,
        "beneficiary_id": beneficiary_id,
        "state_plan_code": state_plan_code,
        "status": "OPEN",
        "basis_balance_cents": 0,
        "earnings_balance_cents": 0,
        "total_balance_cents": 0,
        "lifetime_contribution_cap_cents": state_rule["lifetime_aggregate_cap_cents"],
        "state_rule_version_at_open": state_rule["version"],
    })
    STORE.accounts[_id] = base
    return base


# ----------------- Contribution -----------------
def contribution_view(row):
    return _public(row)


def contribution_create(account_id, donor_id, amount_cents, contribution_kind, recurring_plan_id):
    _id, _seq, base = _new_common(False)
    base.update({
        "account_id": account_id,
        "donor_id": donor_id,
        "amount_cents": amount_cents,
        "contribution_kind": contribution_kind,
        "recurring_plan_id": recurring_plan_id,
        "status": "PENDING",
        "settled_at": None,
    })
    STORE.contributions[_id] = base
    return base


# ----------------- Withdrawal -----------------
def withdrawal_view(row):
    return _public(row, drop={"_disbursed_at"})


def withdrawal_create(account_id, requested_amount_cents, expense_category):
    _id, _seq, base = _new_common(True)
    base.update({
        "account_id": account_id,
        "requested_amount_cents": requested_amount_cents,
        "expense_category": expense_category,
        "status": "REQUESTED",
        "basis_portion_cents": None,
        "earnings_portion_cents": None,
        "qualified_amount_cents": None,
        "non_qualified_amount_cents": None,
        "penalty_cents": None,
        "rejected_reason": None,
        "_disbursed_at": None,        # internal: tax-year membership
    })
    STORE.withdrawals[_id] = base
    return base


# ----------------- RecurringPlan -----------------
def recurring_plan_view(row):
    return _public(row)


def recurring_plan_create(account_id, donor_id, amount_cents, cadence_days, next_run_at_iso):
    _id, _seq, base = _new_common(True)
    base.update({
        "account_id": account_id,
        "donor_id": donor_id,
        "amount_cents": amount_cents,
        "cadence_days": cadence_days,
        "next_run_at": next_run_at_iso,
        "status": "ACTIVE",
    })
    STORE.recurring_plans[_id] = base
    return base


# ----------------- BeneficiaryChangeRequest -----------------
def bcr_view(row):
    return _public(row)


def bcr_create(account_id, current_beneficiary_id, proposed_beneficiary_id):
    _id, _seq, base = _new_common(True)
    base.update({
        "account_id": account_id,
        "current_beneficiary_id": current_beneficiary_id,
        "proposed_beneficiary_id": proposed_beneficiary_id,
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    STORE.beneficiary_change_requests[_id] = base
    return base


# ----------------- EducationExpense -----------------
def expense_view(row):
    return _public(row)


def expense_create(withdrawal_id, institution_name, category, amount_cents, incurred_on):
    _id, _seq, base = _new_common(False)
    base.update({
        "withdrawal_id": withdrawal_id,
        "institution_name": institution_name,
        "category": category,
        "amount_cents": amount_cents,
        "incurred_on": incurred_on,
    })
    STORE.education_expenses[_id] = base
    return base


# ----------------- TaxReport -----------------
def tax_report_view(row):
    return _public(row)


def tax_report_create(account_id, tax_year):
    _id, _seq, base = _new_common(False)
    base.update({
        "account_id": account_id,
        "tax_year": tax_year,
        "gross_distribution_cents": 0,
        "earnings_cents": 0,
        "basis_cents": 0,
        "total_penalty_cents": 0,
        "locked": False,
    })
    STORE.tax_reports[_id] = base
    return base


# ----------------- StateRule -----------------
def state_rule_view(row):
    return _public(row)


def state_rule_create(state_code, deduction_cap_cents, parity, lifetime_aggregate_cap_cents, k12_qualified):
    _id, _seq, base = _new_common(True)
    base.update({
        "state_code": state_code,
        "deduction_cap_cents": deduction_cap_cents,
        "parity": parity,
        "lifetime_aggregate_cap_cents": lifetime_aggregate_cap_cents,
        "k12_qualified": k12_qualified,
    })
    STORE.state_rules[state_code] = base
    STORE.state_rules_by_id[base["id"]] = base
    return base


def state_rule_replace(existing, deduction_cap_cents, parity, lifetime_aggregate_cap_cents, k12_qualified):
    existing["deduction_cap_cents"] = deduction_cap_cents
    existing["parity"] = parity
    existing["lifetime_aggregate_cap_cents"] = lifetime_aggregate_cap_cents
    existing["k12_qualified"] = k12_qualified
    touch(existing)
    return existing
