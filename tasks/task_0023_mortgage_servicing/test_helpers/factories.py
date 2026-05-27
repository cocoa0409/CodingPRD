"""Payload factories — one per entity, input fields only."""


def create_borrower_payload(
    email: str = "borrower@example.com",
    full_name: str = "Test Borrower",
    ssn_last4: str = "1234",
    **overrides,
) -> dict:
    """POST /borrowers input fields (PRD §3.1)."""
    defaults = {
        "email": email,
        "full_name": full_name,
        "ssn_last4": ssn_last4,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(
    borrower_id: str,
    origination_date: str = "2026-01-01T00:00:00Z",
    original_principal_cents: int = 30000000,
    original_property_value_cents: int = 35000000,
    interest_rate_bps: int = 600,
    term_months: int = 360,
    pmi_monthly_cents: int = 12500,
    **overrides,
) -> dict:
    """POST /loans input fields (PRD §3.1)."""
    defaults = {
        "borrower_id": borrower_id,
        "origination_date": origination_date,
        "original_principal_cents": original_principal_cents,
        "original_property_value_cents": original_property_value_cents,
        "interest_rate_bps": interest_rate_bps,
        "term_months": term_months,
        "pmi_monthly_cents": pmi_monthly_cents,
    }
    if "current_appraised_value_cents" in overrides:
        defaults["current_appraised_value_cents"] = overrides.pop(
            "current_appraised_value_cents"
        )
    defaults.update(overrides)
    return defaults


def create_payment_payload(
    amount_cents: int,
    received_at: str,
    posting_strategy: str = None,
    **overrides,
) -> dict:
    """POST /loans/{id}/payments input fields (PRD §3.2)."""
    payload: dict = {
        "amount_cents": amount_cents,
        "received_at": received_at,
    }
    if posting_strategy is not None:
        payload["posting_strategy"] = posting_strategy
    payload.update(overrides)
    return payload


def create_escrow_account_payload(
    loan_id: str,
    annual_tax_cents: int = 480000,
    annual_insurance_cents: int = 120000,
    cushion_months: int = None,
    **overrides,
) -> dict:
    """POST /escrow-accounts input fields (PRD §3.6).
    cushion_months omitted -> server applies default 2.
    """
    payload = {
        "loan_id": loan_id,
        "annual_tax_cents": annual_tax_cents,
        "annual_insurance_cents": annual_insurance_cents,
    }
    if cushion_months is not None:
        payload["cushion_months"] = cushion_months
    payload.update(overrides)
    return payload


def create_disbursement_payload(
    kind: str,
    amount_cents: int,
    scheduled_for: str,
    **overrides,
) -> dict:
    """POST /escrow-accounts/{id}/disbursements input fields (PRD §3.6)."""
    payload = {
        "kind": kind,
        "amount_cents": amount_cents,
        "scheduled_for": scheduled_for,
    }
    payload.update(overrides)
    return payload


def create_escrow_analysis_payload(
    as_of_date: str,
    variant: str,
    expected_escrow_account_version: int,
    **overrides,
) -> dict:
    """POST /escrow-accounts/{id}/analyses input fields (PRD §3.7)."""
    payload = {
        "as_of_date": as_of_date,
        "variant": variant,
        "expected_escrow_account_version": expected_escrow_account_version,
    }
    payload.update(overrides)
    return payload


def create_forbearance_plan_payload(
    start_date: str,
    end_date: str,
    reduced_payment_cents: int = 50000,
    **overrides,
) -> dict:
    """POST /loans/{id}/forbearance-plans input fields (PRD §3.4)."""
    payload = {
        "start_date": start_date,
        "end_date": end_date,
        "reduced_payment_cents": reduced_payment_cents,
    }
    payload.update(overrides)
    return payload


def create_pmi_removal_request_payload(
    loan_id: str,
    appraisal_value_cents: int = None,
    **overrides,
) -> dict:
    """POST /pmi-removal-requests input fields (PRD §3.8)."""
    payload = {"loan_id": loan_id}
    if appraisal_value_cents is not None:
        payload["appraisal_value_cents"] = appraisal_value_cents
    payload.update(overrides)
    return payload


def create_mediation_session_payload(
    scheduled_for: str,
    **overrides,
) -> dict:
    """POST /foreclosure-cases/{id}/mediation-sessions input fields (PRD §3.5)."""
    payload = {"scheduled_for": scheduled_for}
    payload.update(overrides)
    return payload


def record_outcome_payload(
    outcome: str,
    modification_pi_cents: int = None,
    **overrides,
) -> dict:
    """POST /mediation-sessions/{id}/record-outcome input fields (PRD §3.5)."""
    payload = {"outcome": outcome}
    if modification_pi_cents is not None:
        payload["modification_pi_cents"] = modification_pi_cents
    payload.update(overrides)
    return payload


def schedule_sale_payload(
    sale_date: str,
    **overrides,
) -> dict:
    """POST /foreclosure-cases/{id}/schedule-sale input fields (PRD §3.5)."""
    payload = {"sale_date": sale_date}
    payload.update(overrides)
    return payload
