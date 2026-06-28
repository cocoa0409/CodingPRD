"""Payload factories — one per entity, input fields only.

Field names mirror the PRD verbatim. Computed/system fields (net_proceeds,
cash_applied, priority, settlement_status, etc.) are never included.
"""
import uuid


def _unique_taxpayer_id() -> str:
    return f"TP-{uuid.uuid4().hex[:10].upper()}"


def create_exchanger_payload(**overrides) -> dict:
    """POST /exchangers — legal_name, taxpayer_id, email."""
    defaults = {
        "legal_name": "Test Taxpayer",
        "taxpayer_id": _unique_taxpayer_id(),
        "email": "taxpayer@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_exchange_payload(exchanger_id, exchange_type="FORWARD", **overrides) -> dict:
    """POST /exchanges — exchanger_id, exchange_type."""
    defaults = {
        "exchanger_id": exchanger_id,
        "exchange_type": exchange_type,
    }
    defaults.update(overrides)
    return defaults


def create_relinquished_property_payload(**overrides) -> dict:
    """POST /exchanges/{id}/relinquished-properties.

    Defaults yield net_proceeds = 500000 - 30000 - 120000 = 350000 and
    realized_gain = (500000 - 30000) - 180000 = 290000.
    """
    defaults = {
        "address": "1 Relinquished St",
        "fair_market_value": 500000,
        "selling_expenses": 30000,
        "mortgage_payoff": 120000,
        "adjusted_basis": 180000,
    }
    defaults.update(overrides)
    return defaults


def create_identification_payload(method="THREE_PROPERTY", **overrides) -> dict:
    """POST /exchanges/{id}/identifications — method."""
    defaults = {"method": method}
    defaults.update(overrides)
    return defaults


def create_candidate_payload(estimated_fmv=420000, **overrides) -> dict:
    """POST /identifications/{id}/candidates — description, estimated_fmv."""
    defaults = {
        "description": "Candidate replacement property",
        "estimated_fmv": estimated_fmv,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_property_payload(identified_property_id, purchase_price=420000,
                                        replacement_debt=120000, **overrides) -> dict:
    """POST /exchanges/{id}/replacement-properties.

    improvement_value defaults to omitted (server default 0) unless provided.
    """
    defaults = {
        "identified_property_id": identified_property_id,
        "purchase_price": purchase_price,
        "replacement_debt": replacement_debt,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(exchange_id, purpose, amount, expected_qualified_trust_version,
                                **overrides) -> dict:
    """POST /disbursements.

    expected_qualified_trust_version is mandatory (PRD §2.11). replacement_property_id
    is optional and meaningful only for ACQUISITION / IMPROVEMENT_DRAW purposes.
    """
    defaults = {
        "exchange_id": exchange_id,
        "purpose": purpose,
        "amount": amount,
        "expected_qualified_trust_version": expected_qualified_trust_version,
    }
    defaults.update(overrides)
    return defaults
