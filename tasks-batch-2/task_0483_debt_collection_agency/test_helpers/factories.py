"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "CREDITOR_NAME": "Test Creditor",
    "CONSUMER_NAME": "Test Consumer",
    "COMMISSION_RATE_BPS": 2500,
    "PRINCIPAL_CENTS": 100000,
    "CHARGE_OFF_DATE": "2025-06-01T00:00:00Z",
    "SOL_YEARS": 6,
}


def create_creditor_payload(**overrides) -> dict:
    """Creditor: name + commission terms (PRD §3.1). commission_basis optional
    (defaults GROSS_OF_FEES), expense_recovery_cents optional (defaults 0)."""
    payload = {
        "name": DEFAULTS["CREDITOR_NAME"],
        "commission_rate_bps": DEFAULTS["COMMISSION_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_consumer_payload(**overrides) -> dict:
    """Consumer: full_name required; timezone_offset_minutes/phone/address optional
    (PRD §3.1)."""
    payload = {
        "full_name": DEFAULTS["CONSUMER_NAME"],
        "timezone_offset_minutes": 0,
    }
    payload.update(overrides)
    return payload


def create_account_payload(creditor_id: str, consumer_id: str, **overrides) -> dict:
    """Account placement (PRD §3.2). sol_anchor_basis optional (defaults CHARGE_OFF)."""
    payload = {
        "creditor_id": creditor_id,
        "consumer_id": consumer_id,
        "original_principal_cents": DEFAULTS["PRINCIPAL_CENTS"],
        "charge_off_date": DEFAULTS["CHARGE_OFF_DATE"],
        "sol_years": DEFAULTS["SOL_YEARS"],
    }
    payload.update(overrides)
    return payload


def create_skip_trace_payload(consumer_id: str, result: str, **overrides) -> dict:
    """SkipTrace (PRD §3.1). new_phone/new_address optional."""
    payload = {
        "consumer_id": consumer_id,
        "result": result,
    }
    payload.update(overrides)
    return payload


def create_communication_attempt_payload(account_id: str, channel: str,
                                          attempted_at: str, outcome: str,
                                          **overrides) -> dict:
    """CommunicationAttempt (PRD §3.5)."""
    payload = {
        "account_id": account_id,
        "channel": channel,
        "attempted_at": attempted_at,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(dispute_type: str, **overrides) -> dict:
    """Dispute raise (PRD §3.4). account_id comes from the URL path."""
    payload = {"dispute_type": dispute_type}
    payload.update(overrides)
    return payload


def create_arrangement_payload(account_id: str, arrangement_type: str, **overrides) -> dict:
    """PaymentArrangement (PRD §3.6). offer_pct_bps required for SETTLEMENT,
    installment_count optional (defaults 1), good_through optional."""
    payload = {
        "account_id": account_id,
        "arrangement_type": arrangement_type,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(account_id: str, amount_cents: int, **overrides) -> dict:
    """Payment (PRD §3.7). arrangement_id optional."""
    payload = {
        "account_id": account_id,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_bureau_furnishing_payload(account_id: str, bureau: str, **overrides) -> dict:
    """BureauFurnishing (PRD §3.11)."""
    payload = {
        "account_id": account_id,
        "bureau": bureau,
    }
    payload.update(overrides)
    return payload


def create_bureau_dispute_payload(furnishing_id: str, **overrides) -> dict:
    """BureauDispute / e-OSCAR ACDV (PRD §3.11)."""
    payload = {"furnishing_id": furnishing_id}
    payload.update(overrides)
    return payload
