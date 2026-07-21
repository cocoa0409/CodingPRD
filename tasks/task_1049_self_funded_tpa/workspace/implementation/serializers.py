"""Explicit per-entity serializers (public schema only; drops internal keys)."""

_COMMON = ["id", "created_at", "updated_at", "version"]


def _pick(entity, fields):
    return {f: entity.get(f) for f in fields}


def plan(e):
    return _pick(e, [
        "id", "sponsor_name", "sponsor_tax_id", "plan_year_start", "plan_year_end",
        "individual_deductible_cents", "oop_max_cents", "plan_coinsurance_pct",
        "run_out_days", "terminated_at", "status", "created_at", "updated_at", "version",
    ])


def provider(e):
    return _pick(e, [
        "id", "name", "tax_id", "npi", "in_network", "ppo_discount_pct",
        "ytd_paid_cents", "created_at", "updated_at", "version",
    ])


def member(e):
    return _pick(e, [
        "id", "plan_id", "first_name", "last_name", "coverage_effective_date",
        "coverage_term_date", "status", "deductible_met_cents", "oop_met_cents",
        "member_plan_paid_ytd_cents", "spec_reimbursed_cents",
        "created_at", "updated_at", "version",
    ])


def policy(e):
    return _pick(e, [
        "id", "plan_id", "carrier_name", "contract_basis", "effective_date", "expiry_date",
        "specific_deductible_cents", "aggregate_attachment_cents",
        "total_specific_reimbursed_cents", "total_aggregate_reimbursed_cents",
        "status", "created_at", "updated_at", "version",
    ])


def laser(e):
    return _pick(e, [
        "id", "stop_loss_policy_id", "member_id", "laser_deductible_cents",
        "effective_date", "expiry_date", "created_at", "updated_at", "version",
    ])


def claim(e):
    return _pick(e, [
        "id", "member_id", "provider_id", "service_date", "billed_lines",
        "billed_total_cents", "ucr_amount_cents", "allowed_amount_cents",
        "deductible_applied_cents", "member_coinsurance_cents",
        "member_responsibility_cents", "plan_paid_cents", "denial_reason",
        "pended_by_user_id", "paid_at", "status", "created_at", "updated_at", "version",
    ])


def fund(e):
    return _pick(e, [
        "id", "plan_id", "balance_cents", "total_deposited_cents",
        "total_disbursed_cents", "status", "created_at", "updated_at", "version",
    ])


def checkrun(e):
    return _pick(e, [
        "id", "fund_account_id", "claim_ids", "total_amount_cents",
        "released_at", "status", "created_at", "updated_at", "version",
    ])


def reimbursement(e):
    return _pick(e, [
        "id", "stop_loss_policy_id", "claim_id", "member_id", "reimbursement_type",
        "amount_cents", "basis_note", "created_at", "updated_at", "version",
    ])


def form1099(e):
    return _pick(e, [
        "id", "provider_id", "tax_year", "total_paid_cents", "reportable",
        "created_at", "updated_at", "version",
    ])
