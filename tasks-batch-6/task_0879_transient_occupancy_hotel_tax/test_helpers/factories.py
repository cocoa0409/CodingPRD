"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Every factory accepts **overrides so tests can pin
the specific values a claim asserts.
"""

DEFAULTS = {
    "JURISDICTION_NAME": "Test City",
    "TAX_RATE_BPS": 1200,          # 12%
    "OPERATOR_NAME": "Test Lodging Operator",
    "FILING_FREQUENCY": "MONTHLY",
    "PROPERTY_NAME": "Test Property",
    "PROPERTY_ADDRESS": "1 Main St",
    "PLATFORM_NAME": "Test OTA",
    "PERIOD_START": "2026-04-01T00:00:00Z",
    "PERIOD_END": "2026-04-30T00:00:00Z",
    "GROSS_RECEIPTS_CENTS": 1000000,
}


def create_jurisdiction_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["JURISDICTION_NAME"],
        "tax_rate_bps": DEFAULTS["TAX_RATE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_operator_payload(jurisdiction_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "legal_name": DEFAULTS["OPERATOR_NAME"],
        "filing_frequency": DEFAULTS["FILING_FREQUENCY"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(operator_id, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "name": DEFAULTS["PROPERTY_NAME"],
        "address": DEFAULTS["PROPERTY_ADDRESS"],
    }
    payload.update(overrides)
    return payload


def create_ota_platform_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["PLATFORM_NAME"]}
    payload.update(overrides)
    return payload


def create_ota_agreement_payload(operator_id, platform_id, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "platform_id": platform_id,
        "collection_method": "GROSS",
        "effective_date": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_return_payload(operator_id, line_items, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


def single_line(property_id, gross_receipts_cents=DEFAULTS["GROSS_RECEIPTS_CENTS"]) -> list:
    """A one-property line_items array."""
    return [{"property_id": property_id, "gross_receipts_cents": gross_receipts_cents}]


def create_exemption_payload(tax_return_id, exemption_type, amount_cents, **overrides) -> dict:
    payload = {
        "tax_return_id": tax_return_id,
        "exemption_type": exemption_type,
        "guest_ref": "G-TEST",
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_remittance_payload(tax_return_id, amount_cents, remitter="OPERATOR", **overrides) -> dict:
    payload = {
        "tax_return_id": tax_return_id,
        "remitter": remitter,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(operator_id, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def propose_assessment_payload(audited_taxable_cents, classification="NEGLIGENCE", **overrides) -> dict:
    payload = {
        "audited_taxable_cents": audited_taxable_cents,
        "classification": classification,
    }
    payload.update(overrides)
    return payload


def submit_appeal_payload(grounds="taxpayer disagrees", **overrides) -> dict:
    payload = {"grounds": grounds}
    payload.update(overrides)
    return payload


def decide_appeal_payload(decision, **overrides) -> dict:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def create_refund_claim_payload(operator_id, reason, principal_cents, overpayment_date, **overrides) -> dict:
    payload = {
        "operator_id": operator_id,
        "reason": reason,
        "principal_cents": principal_cents,
        "overpayment_date": overpayment_date,
    }
    payload.update(overrides)
    return payload
