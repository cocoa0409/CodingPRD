"""Serialize entities to their PRD/scaffold output shape (drops internal fields)."""

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(e):
    return {k: e[k] for k in _COMMON}


def grantor(e):
    out = _base(e)
    out.update({
        "full_name": e["full_name"],
        "generation_level": e["generation_level"],
        "gst_exemption_total_cents": e["gst_exemption_total_cents"],
        "gst_exemption_remaining_cents": e["gst_exemption_remaining_cents"],
    })
    return out


def trustee(e):
    out = _base(e)
    out.update({
        "full_name": e["full_name"],
        "is_corporate": e["is_corporate"],
    })
    return out


def beneficiary(e):
    out = _base(e)
    out.update({
        "full_name": e["full_name"],
        "grantor_id": e["grantor_id"],
        "generation_level": e["generation_level"],
        "is_skip_person": e["is_skip_person"],
    })
    return out


def trust(e):
    out = _base(e)
    out.update({
        "name": e["name"],
        "grantor_id": e["grantor_id"],
        "trust_type": e["trust_type"],
        "is_grantor_trust": e["is_grantor_trust"],
        "capital_gains_to_income": e["capital_gains_to_income"],
        "status": e["status"],
        "principal_balance_cents": e["principal_balance_cents"],
        "income_balance_cents": e["income_balance_cents"],
        "gst_exemption_allocated_cents": e["gst_exemption_allocated_cents"],
        "inclusion_ratio": e["inclusion_ratio"],
    })
    return out


def trustee_appointment(e):
    out = _base(e)
    out.update({
        "trust_id": e["trust_id"],
        "trustee_id": e["trustee_id"],
        "term_start": e["term_start"],
        "term_end": e["term_end"],
        "status": e["status"],
    })
    return out


def account(e):
    out = _base(e)
    out.update({
        "trust_id": e["trust_id"],
        "tax_year": e["tax_year"],
        "period_start": e["period_start"],
        "period_end": e["period_end"],
        "status": e["status"],
        "dni_cents": e["dni_cents"],
        "dni_carried_out_cents": e["dni_carried_out_cents"],
        "taxable_income_cents": e["taxable_income_cents"],
    })
    return out


def receipt(e):
    out = _base(e)
    out.update({
        "account_id": e["account_id"],
        "amount_cents": e["amount_cents"],
        "receipt_kind": e["receipt_kind"],
        "ledger_side": e["ledger_side"],
    })
    return out


def disbursement(e):
    out = _base(e)
    out.update({
        "account_id": e["account_id"],
        "amount_cents": e["amount_cents"],
        "expense_kind": e["expense_kind"],
        "ledger_side": e["ledger_side"],
        "is_system_generated": e["is_system_generated"],
    })
    return out


def distribution(e):
    out = _base(e)
    out.update({
        "account_id": e["account_id"],
        "beneficiary_id": e["beneficiary_id"],
        "amount_cents": e["amount_cents"],
        "distribution_kind": e["distribution_kind"],
        "proposer_trustee_id": e["proposer_trustee_id"],
        "approver_trustee_id": e["approver_trustee_id"],
        "status": e["status"],
        "funded_from_income_cents": e["funded_from_income_cents"],
        "funded_from_principal_cents": e["funded_from_principal_cents"],
        "dni_carried_amount_cents": e["dni_carried_amount_cents"],
    })
    return out


def k1(e):
    out = _base(e)
    out.update({
        "account_id": e["account_id"],
        "beneficiary_id": e["beneficiary_id"],
        "ordinary_income_cents": e["ordinary_income_cents"],
        "qualified_dividend_cents": e["qualified_dividend_cents"],
        "capital_gain_cents": e["capital_gain_cents"],
        "total_carried_cents": e["total_carried_cents"],
    })
    return out


def filing(e):
    out = _base(e)
    out.update({
        "account_id": e["account_id"],
        "taxable_income_snapshot_cents": e["taxable_income_snapshot_cents"],
        "tax_due_cents": e["tax_due_cents"],
        "status": e["status"],
        "supersedes_filing_id": e["supersedes_filing_id"],
    })
    return out


def gst_allocation(e):
    out = _base(e)
    out.update({
        "trust_id": e["trust_id"],
        "grantor_id": e["grantor_id"],
        "amount_cents": e["amount_cents"],
        "status": e["status"],
    })
    return out


def gst_event(e):
    out = _base(e)
    out.update({
        "trust_id": e["trust_id"],
        "beneficiary_id": e["beneficiary_id"],
        "distribution_id": e["distribution_id"],
        "event_type": e["event_type"],
        "taxable_amount_cents": e["taxable_amount_cents"],
        "gst_tax_cents": e["gst_tax_cents"],
        "inclusion_ratio_snapshot": e["inclusion_ratio_snapshot"],
    })
    return out
