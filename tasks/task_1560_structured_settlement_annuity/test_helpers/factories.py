"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

PROFILE_DEFAULTS = {
    "state_code": "CA",
    "age_of_majority": 18,
    "sspa_max_discount_rate_bps": 700,
    "disclosure_cooling_off_days": 10,
    "ipa_required": True,
    "dormancy_years": 3,
    "commutation_permitted": True,
}

PAYEE_DEFAULTS = {
    "full_name": "Test Payee",
    "date_of_birth": "1980-06-15",
    "tax_id": "000-00-0000",
    "address_line1": "1 Main St",
    "address_city": "Sacramento",
    "address_state_code": "CA",
    "address_postal_code": "95814",
}

AGREEMENT_DEFAULTS = {
    "case_number": "CASE-001",
    "court_state_code": "CA",
    "obligor_name": "Acme Insurance",
    "injury_type": "PHYSICAL",
    "agreement_date": "2026-01-15",
}

ASSIGNMENT_DEFAULTS = {
    "assignment_company_name": "QAC Corp",
    "executed_date": "2026-01-20",
}

POLICY_DEFAULTS = {
    "policy_number": "POL-1",
    "insurer_name": "LifeCo",
    "premium_cents": 10000000,
    "contract_discount_rate_bps": 500,
    "commutation_rider": "NONE",
    "certain_period_end_date": "2036-12-31",
}

SCHEDULE_DEFAULTS = {
    "effective_from_date": "2026-02-01",
    "escalation_anchor_date": "2026-02-01",
}


def create_state_profile_payload(**overrides) -> dict:
    defaults = dict(PROFILE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_payee_payload(**overrides) -> dict:
    defaults = dict(PAYEE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_guardianship_case_payload(payee_id, **overrides) -> dict:
    defaults = {
        "payee_id": payee_id,
        "court_state_code": "CA",
        "guardian_full_name": "Grace Guardian",
        "effective_from_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_agreement_payload(primary_payee_id, **overrides) -> dict:
    defaults = dict(AGREEMENT_DEFAULTS)
    defaults["primary_payee_id"] = primary_payee_id
    defaults.update(overrides)
    return defaults


def create_qualified_assignment_payload(settlement_agreement_id, **overrides) -> dict:
    defaults = dict(ASSIGNMENT_DEFAULTS)
    defaults["settlement_agreement_id"] = settlement_agreement_id
    defaults.update(overrides)
    return defaults


def create_annuity_policy_payload(settlement_agreement_id, qualified_assignment_id, **overrides) -> dict:
    defaults = dict(POLICY_DEFAULTS)
    defaults["settlement_agreement_id"] = settlement_agreement_id
    defaults["qualified_assignment_id"] = qualified_assignment_id
    defaults.update(overrides)
    return defaults


def create_payment_schedule_payload(settlement_agreement_id, **overrides) -> dict:
    defaults = dict(SCHEDULE_DEFAULTS)
    defaults["settlement_agreement_id"] = settlement_agreement_id
    defaults.update(overrides)
    return defaults


def create_scheduled_payment_payload(payment_schedule_id, payee_id, payment_seq_no,
                                     due_date, base_amount_cents, **overrides) -> dict:
    defaults = {
        "payment_schedule_id": payment_schedule_id,
        "payee_id": payee_id,
        "payment_seq_no": payment_seq_no,
        "due_date": due_date,
        "base_amount_cents": base_amount_cents,
        "escalation_rate_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payee_change_request_payload(payee_id, change_type, **overrides) -> dict:
    defaults = {"payee_id": payee_id, "change_type": change_type}
    defaults.update(overrides)
    return defaults


def create_transfer_petition_payload(settlement_agreement_id, payee_id, **overrides) -> dict:
    defaults = {
        "settlement_agreement_id": settlement_agreement_id,
        "payee_id": payee_id,
        "factoring_company_name": "FactorCo",
        "purchase_price_cents": 100000,
        "transfer_start_date": "2030-01-01",
        "transfer_end_date": "2030-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_death_claim_payload(payee_id, settlement_agreement_id, **overrides) -> dict:
    defaults = {
        "payee_id": payee_id,
        "settlement_agreement_id": settlement_agreement_id,
        "date_of_death": "2028-12-20",
        "claimant_type": "ESTATE",
        "claimant_name": "Estate of Payee",
    }
    defaults.update(overrides)
    return defaults


def create_commutation_request_payload(annuity_policy_id, settlement_agreement_id, reason,
                                       expected_annuity_policy_version, **overrides) -> dict:
    defaults = {
        "annuity_policy_id": annuity_policy_id,
        "settlement_agreement_id": settlement_agreement_id,
        "reason": reason,
        "expected_annuity_policy_version": expected_annuity_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_escheatment_batch_payload(state_code, batch_period, **overrides) -> dict:
    defaults = {"state_code": state_code, "batch_period": batch_period}
    defaults.update(overrides)
    return defaults
