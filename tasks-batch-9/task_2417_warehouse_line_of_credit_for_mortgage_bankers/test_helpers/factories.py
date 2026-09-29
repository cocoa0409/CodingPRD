"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def facility_payload(**overrides) -> dict:
    """Body for `POST /facilities`."""
    payload = {
        "borrower_legal_name": TEST_DEFAULTS["BORROWER_LEGAL_NAME"],
        "committed_amount_cents": TEST_DEFAULTS["COMMITTED_AMOUNT_CENTS"],
        "wet_sublimit_cents": TEST_DEFAULTS["WET_SUBLIMIT_CENTS"],
        "aged_sublimit_cents": TEST_DEFAULTS["AGED_SUBLIMIT_CENTS"],
        "scratch_and_dent_sublimit_cents": TEST_DEFAULTS[
            "SCRATCH_AND_DENT_SUBLIMIT_CENTS"
        ],
        "min_tangible_net_worth_cents": TEST_DEFAULTS["MIN_TANGIBLE_NET_WORTH_CENTS"],
        "min_liquidity_cents": TEST_DEFAULTS["MIN_LIQUIDITY_CENTS"],
        "min_ttm_net_income_cents": TEST_DEFAULTS["MIN_TTM_NET_INCOME_CENTS"],
        "max_investor_concentration_pct": TEST_DEFAULTS[
            "MAX_INVESTOR_CONCENTRATION_PCT"
        ],
        "bailee_period_days": 30,
        "unused_line_fee_rate": TEST_DEFAULTS["UNUSED_LINE_FEE_RATE"],
        "settlement_account_last4": TEST_DEFAULTS["SETTLEMENT_ACCOUNT_LAST4"],
    }
    payload.update(overrides)
    return payload


def product_advance_rate_payload(**overrides) -> dict:
    """Body for `POST /facilities/{id}/product-advance-rates`."""
    payload = {
        "product_code": "CONFORMING",
        "advance_rate": TEST_DEFAULTS["CONFORMING_ADVANCE_RATE"],
        "wet_funding_allowed": True,
        "wet_haircut": 0.02,
        "dwell_limit_days": TEST_DEFAULTS["CONFORMING_DWELL_LIMIT_DAYS"],
        "aging_step_days": 15,
        "curtailment_step_rate": 0.005,
        "product_sublimit_cents": TEST_DEFAULTS["CONFORMING_PRODUCT_SUBLIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def custodian_payload(**overrides) -> dict:
    """Body for `POST /facilities/{id}/custodians`."""
    payload = {
        "custodian_name": TEST_DEFAULTS["CUSTODIAN_NAME"],
        "wet_receipt_deadline_hours": TEST_DEFAULTS["WET_RECEIPT_DEADLINE_HOURS"],
    }
    payload.update(overrides)
    return payload


def investor_payload(**overrides) -> dict:
    """Body for `POST /facilities/{id}/investors`."""
    payload = {
        "investor_name": TEST_DEFAULTS["INVESTOR_NAME"],
        "counterparty_rating": TEST_DEFAULTS["COUNTERPARTY_RATING"],
        "concentration_limit_pct": TEST_DEFAULTS["CONCENTRATION_LIMIT_PCT"],
    }
    payload.update(overrides)
    return payload


def commitment_payload(investor_id, **overrides) -> dict:
    """Body for `POST /facilities/{id}/commitments`."""
    payload = {
        "investor_id": investor_id,
        "product_code": "CONFORMING",
        "committed_amount_cents": TEST_DEFAULTS["COMMITMENT_AMOUNT_CENTS"],
        "price_pct": TEST_DEFAULTS["PRICE_PCT"],
        "effective_on": TEST_DEFAULTS["EFFECTIVE_ON"],
        "expires_on": TEST_DEFAULTS["EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def advance_payload(
    facility_id,
    custodian_id,
    expected_facility_version,
    investor_commitment_id=None,
    **overrides,
) -> dict:
    """Body for `POST /advances`."""
    payload = {
        "facility_id": facility_id,
        "custodian_id": custodian_id,
        "investor_commitment_id": investor_commitment_id,
        "product_code": "CONFORMING",
        "loan_amount_cents": TEST_DEFAULTS["LOAN_AMOUNT_CENTS"],
        "note_rate": TEST_DEFAULTS["NOTE_RATE"],
        "funding_type": "DRY",
        "payee_name": TEST_DEFAULTS["PAYEE_NAME"],
        "payee_account_last4": TEST_DEFAULTS["PAYEE_ACCOUNT_LAST4"],
        "payee_routing_last4": TEST_DEFAULTS["PAYEE_ROUTING_LAST4"],
        "expected_facility_version": expected_facility_version,
    }
    payload.update(overrides)
    return payload


def wire_decision_payload(decision="VERIFY", **overrides) -> dict:
    """Body for `POST /wire-instructions/{id}/decision`."""
    payload = {"decision": decision}
    if decision == "VERIFY":
        payload["callback_reference"] = "CB-301"
    payload.update(overrides)
    return payload


def receipt_payload(custodian_id, **overrides) -> dict:
    """Body for `POST /advances/{id}/receipts`."""
    payload = {
        "custodian_id": custodian_id,
        "document_types": ["NOTE", "MORTGAGE", "ASSIGNMENT", "TITLE_POLICY"],
    }
    payload.update(overrides)
    return payload


def receipt_cure_payload(cured_exception_codes, **overrides) -> dict:
    """Body for `POST /receipts/{id}/cure`."""
    payload = {"cured_exception_codes": list(cured_exception_codes)}
    payload.update(overrides)
    return payload


def valuation_payload(market_value_cents, expected_advance_version, **overrides) -> dict:
    """Body for `POST /advances/{id}/valuation`."""
    payload = {
        "market_value_cents": market_value_cents,
        "expected_advance_version": expected_advance_version,
    }
    payload.update(overrides)
    return payload


def ship_payload(investor_id, **overrides) -> dict:
    """Body for `POST /advances/{id}/ship`."""
    payload = {"investor_id": investor_id}
    payload.update(overrides)
    return payload


def purchase_payload(proceeds_reference="WIRE-IN-20260806-01", **overrides) -> dict:
    """Body for `POST /advances/{id}/purchase`."""
    payload = {"proceeds_reference": proceeds_reference}
    payload.update(overrides)
    return payload


def repurchase_payload(payment_amount_cents, **overrides) -> dict:
    """Body for `POST /advances/{id}/repurchase`."""
    payload = {"payment_amount_cents": payment_amount_cents}
    payload.update(overrides)
    return payload


def repurchase_demand_payload(reason="DWELL_EXCEEDED", **overrides) -> dict:
    """Body for `POST /advances/{id}/repurchase-demands`."""
    payload = {"reason": reason}
    payload.update(overrides)
    return payload


def margin_call_payload(facility_id, trigger_reason="COVENANT_BREACH", **overrides) -> dict:
    """Body for `POST /margin-calls`."""
    payload = {"facility_id": facility_id, "trigger_reason": trigger_reason}
    payload.update(overrides)
    return payload


def cure_payment_payload(amount_cents, expected_margin_call_version, **overrides) -> dict:
    """Body for `POST /margin-calls/{id}/cure-payments`."""
    payload = {
        "amount_cents": amount_cents,
        "expected_margin_call_version": expected_margin_call_version,
    }
    payload.update(overrides)
    return payload


def covenant_test_payload(
    period_end,
    tangible_net_worth_cents=2_000_000_000,
    liquidity_cents=800_000_000,
    net_income_cents=200_000_000,
    **overrides,
) -> dict:
    """Body for `POST /facilities/{id}/covenant-tests`."""
    payload = {
        "period_end": period_end,
        "tangible_net_worth_cents": tangible_net_worth_cents,
        "liquidity_cents": liquidity_cents,
        "net_income_cents": net_income_cents,
    }
    payload.update(overrides)
    return payload


def reason_payload(reason="Operational review", **overrides) -> dict:
    """Body for the endpoints whose only field is a `reason`."""
    payload = {"reason": reason}
    payload.update(overrides)
    return payload
