"""Payload factories — one per write endpoint, input fields only.

Every monetary amount is an integer count of cents (PRD §2.6) and every rate is
a decimal fraction between 0 and 1.
"""

DEFAULTS = {
    "SCHEDULE_NAME": "Standard 2026",
    "SUPPLIER_NAME": "Meridian Air",
    "ADVISOR_NAME": "Dana Reyes",
    "ADVISOR_EMAIL": "dana.reyes@example.com",
    "ADVISOR_STATE": "NY",
    "CLIENT_NAME": "Nadia Okoye",
    "GROSS_SALE_CENTS": 1_000_000,
}


# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------


def standard_tiers():
    """The two-rung production ladder used across most scenarios."""
    return [
        {"tier_level": 1, "min_production_cents": 0, "advisor_pct": 0.70},
        {"tier_level": 2, "min_production_cents": 5_000_000, "advisor_pct": 0.80},
    ]


def standard_platform_fee_tiers():
    """A single flat five-percent host fee from a floor of zero."""
    return [{"min_share_cents": 0, "fee_pct": 0.05}]


def tiered_platform_fee_tiers():
    """The two-rung fee ladder the PRD demonstrates: five percent from zero and
    three percent from a floor of one million cents."""
    return [
        {"min_share_cents": 0, "fee_pct": 0.05},
        {"min_share_cents": 1_000_000, "fee_pct": 0.03},
    ]


def create_split_schedule_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SCHEDULE_NAME"],
        "tiers": standard_tiers(),
        "platform_fee_tiers": standard_platform_fee_tiers(),
        "chargeback_retention_pct": 0.10,
    }
    payload.update(overrides)
    return payload


def create_consortium_payload(**overrides) -> dict:
    payload = {
        "name": "Voyager Collective",
        "membership_fee_cents": 50_000,
        "marketing_fund_accrual_pct": 0.02,
        "consortium_channel_bonus_pct": 0.04,
    }
    payload.update(overrides)
    return payload


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SUPPLIER_NAME"],
        "accreditation_scheme": "ARC",
        "base_commission_pct": 0.10,
        "preferred_override_commission_pct": 0.12,
        "rate_ceiling_pct": 0.20,
        "max_commission_per_booking_cents": 9_000_000,
        "remit_terms_days": 30,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Advisors, agreements and credentials
# ---------------------------------------------------------------------------


def create_advisor_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["ADVISOR_NAME"],
        "email": DEFAULTS["ADVISOR_EMAIL"],
        "seller_of_travel_state": DEFAULTS["ADVISOR_STATE"],
    }
    payload.update(overrides)
    return payload


def create_advisor_agreement_payload(split_schedule_id, expected_advisor_version, **overrides) -> dict:
    payload = {
        "split_schedule_id": split_schedule_id,
        "effective_date": "2026-01-01",
        "post_departure_advisor_pct": 0.50,
        "expected_advisor_version": expected_advisor_version,
    }
    payload.update(overrides)
    return payload


def seller_of_travel_credential_payload(
    jurisdiction_state_code="NY",
    credential_number="NY-SOT-40118",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    **overrides,
) -> dict:
    payload = {
        "credential_type": "SELLER_OF_TRAVEL",
        "credential_number": credential_number,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "jurisdiction_state_code": jurisdiction_state_code,
    }
    payload.update(overrides)
    return payload


def eo_policy_credential_payload(
    coverage_amount_cents=100_000_000,
    credential_number="EO-99881",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    **overrides,
) -> dict:
    payload = {
        "credential_type": "EO_POLICY",
        "credential_number": credential_number,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "coverage_amount_cents": coverage_amount_cents,
    }
    payload.update(overrides)
    return payload


def training_cert_credential_payload(
    credential_number="TRN-2026-A",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    **overrides,
) -> dict:
    payload = {
        "credential_type": "TRAINING_CERT",
        "credential_number": credential_number,
        "effective_on": effective_on,
        "expires_on": expires_on,
    }
    payload.update(overrides)
    return payload


def supplier_accreditation_credential_payload(
    supplier_id,
    credential_number="ARC-33290",
    effective_on="2026-01-01",
    expires_on="2027-01-01",
    **overrides,
) -> dict:
    payload = {
        "credential_type": "SUPPLIER_ACCREDITATION",
        "credential_number": credential_number,
        "effective_on": effective_on,
        "expires_on": expires_on,
        "supplier_id": supplier_id,
    }
    payload.update(overrides)
    return payload


def credential_decision_payload(decision="VERIFY", **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def suspend_advisor_payload(reason="Documentation audit in progress", **overrides) -> dict:
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def declare_departure_payload(transition_advisor_id, effective_date="2026-09-01", **overrides) -> dict:
    payload = {
        "effective_date": effective_date,
        "transition_advisor_id": transition_advisor_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clients and trust ledger lines
# ---------------------------------------------------------------------------


def create_client_payload(owner_advisor_id, **overrides) -> dict:
    payload = {
        "owner_advisor_id": owner_advisor_id,
        "full_name": DEFAULTS["CLIENT_NAME"],
        "home_state_code": "NY",
    }
    payload.update(overrides)
    return payload


def trust_ledger_entry_payload(
    direction, amount_cents, expected_client_version, memo="Trip funding", **overrides
) -> dict:
    payload = {
        "direction": direction,
        "amount_cents": amount_cents,
        "memo": memo,
        "expected_client_version": expected_client_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Bookings
# ---------------------------------------------------------------------------


def create_booking_payload(
    advisor_id,
    supplier_id,
    client_id,
    channel="SUPPLIER_DIRECT",
    payment_method="MERCHANT_DIRECT",
    gross_sale_cents=DEFAULTS["GROSS_SALE_CENTS"],
    deposit_amount_cents=0,
    travel_start_date="2026-10-01",
    travel_end_date="2026-10-10",
    **overrides,
) -> dict:
    payload = {
        "advisor_id": advisor_id,
        "supplier_id": supplier_id,
        "client_id": client_id,
        "channel": channel,
        "payment_method": payment_method,
        "gross_sale_cents": gross_sale_cents,
        "deposit_amount_cents": deposit_amount_cents,
        "travel_start_date": travel_start_date,
        "travel_end_date": travel_end_date,
    }
    payload.update(overrides)
    return payload


def cancel_booking_payload(cancellation_reason="CLIENT_INITIATED", **overrides) -> dict:
    payload = {"cancellation_reason": cancellation_reason}
    payload.update(overrides)
    return payload


def commission_receipt_payload(amount_cents, received_on, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "received_on": received_on}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Claims and settlement
# ---------------------------------------------------------------------------


def commission_claim_payload(claimed_amount_cents, **overrides) -> dict:
    payload = {"claimed_amount_cents": claimed_amount_cents}
    payload.update(overrides)
    return payload


def claim_denial_payload(denial_reason="Commission already remitted in full", **overrides) -> dict:
    payload = {"denial_reason": denial_reason}
    payload.update(overrides)
    return payload


def claim_resolution_payload(resolution="PAID", recovered_amount_cents=None, **overrides) -> dict:
    payload = {"resolution": resolution}
    if recovered_amount_cents is not None:
        payload["recovered_amount_cents"] = recovered_amount_cents
    payload.update(overrides)
    return payload


def create_settlement_run_payload(period_month="2026-08", **overrides) -> dict:
    payload = {"period_month": period_month}
    payload.update(overrides)
    return payload


def pay_statement_payload(payment_reference="ACH-2026-08-0001", **overrides) -> dict:
    payload = {"payment_reference": payment_reference}
    payload.update(overrides)
    return payload
