"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_apy_tier_payload(**overrides) -> dict:
    """ApyTier input fields (PRD §3.11): code, product_type, min_balance_cents, annual_rate_bps."""
    defaults = {
        "code": "CHK_STD",
        "product_type": "CHECKING",
        "min_balance_cents": 0,
        "annual_rate_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """Customer input fields (PRD §3.1): legal_name, date_of_birth, tax_id_last4,
    country_of_residence (optional, defaults US)."""
    defaults = {
        "legal_name": "Test Person",
        "date_of_birth": "1990-01-01",
        "tax_id_last4": "1234",
        "country_of_residence": "US",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(customer_id, **overrides) -> dict:
    """Application input fields (PRD §3.1): customer_id, product_type, requested_apy_tier_code."""
    defaults = {
        "customer_id": customer_id,
        "product_type": "CHECKING",
        "requested_apy_tier_code": "CHK_STD",
    }
    defaults.update(overrides)
    return defaults


def reject_application_payload(**overrides) -> dict:
    """Reject input fields (PRD §3.3): rejection_reason_code."""
    defaults = {"rejection_reason_code": "DUPLICATE"}
    defaults.update(overrides)
    return defaults


def courtesy_pay_payload(opted_in, limit_cents=None) -> dict:
    """Courtesy-pay input fields (PRD §3.5): courtesy_pay_opted_in, courtesy_pay_limit_cents?."""
    payload = {"courtesy_pay_opted_in": opted_in}
    if limit_cents is not None:
        payload["courtesy_pay_limit_cents"] = limit_cents
    return payload


def transaction_payload(txn_type, amount_cents, check_number=None) -> dict:
    """Transaction input fields (PRD §3.5): txn_type, amount_cents, check_number?."""
    payload = {"txn_type": txn_type, "amount_cents": amount_cents}
    if check_number is not None:
        payload["check_number"] = check_number
    return payload


def owner_payload(customer_id, ownership_role) -> dict:
    """AccountOwner input fields (PRD §3.9): customer_id, ownership_role."""
    return {"customer_id": customer_id, "ownership_role": ownership_role}


def stop_payment_payload(check_number, max_amount_cents, expires_on) -> dict:
    """StopPayment input fields (PRD §3.10): check_number, max_amount_cents, expires_on."""
    return {
        "check_number": check_number,
        "max_amount_cents": max_amount_cents,
        "expires_on": expires_on,
    }


def interest_posting_payload(period_start_date, period_end_date) -> dict:
    """InterestPosting input fields (PRD §3.11): period_start_date, period_end_date."""
    return {"period_start_date": period_start_date, "period_end_date": period_end_date}


def ach_origination_payload(debtor_account_id, creditor_account_id, posting_order=None) -> dict:
    """AchOrigination input fields (PRD §3.12): debtor_account_id, creditor_account_id, posting_order?."""
    payload = {
        "debtor_account_id": debtor_account_id,
        "creditor_account_id": creditor_account_id,
    }
    if posting_order is not None:
        payload["posting_order"] = posting_order
    return payload


def ach_leg_payload(leg_role, amount_cents, expected_ach_origination_version) -> dict:
    """AchLeg input fields (PRD §3.12): leg_role, amount_cents, expected_ach_origination_version."""
    return {
        "leg_role": leg_role,
        "amount_cents": amount_cents,
        "expected_ach_origination_version": expected_ach_origination_version,
    }


def settle_payload(expected_ach_origination_version) -> dict:
    """Settle input fields (PRD §3.13): expected_ach_origination_version."""
    return {"expected_ach_origination_version": expected_ach_origination_version}


def reverse_payload(expected_ach_origination_version) -> dict:
    """Reverse input fields (PRD §3.14): expected_ach_origination_version."""
    return {"expected_ach_origination_version": expected_ach_origination_version}


def clock_payload(to_iso8601) -> dict:
    """Clock input fields (PRD §3.15): to_iso8601."""
    return {"to_iso8601": to_iso8601}
