"""Payload factories — one per entity, input fields only.

Field names are exactly as named in the PRD. Only source-input fields appear;
computed and system fields are never sent.
"""


def create_household_payload(**overrides) -> dict:
    defaults = {
        "primary_email": "household@example.test",
        "display_name": "Test Household",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(role="OWNER", **overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": "member@example.test",
        "role": role,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(tier="BASIC",
                                period_start="2025-01-01T00:00:00Z",
                                period_end="2027-01-01T00:00:00Z",
                                **overrides) -> dict:
    defaults = {
        "tier": tier,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults


def create_manufacturer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Manufacturer",
        "contact_email": "mfr@example.test",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(household_id, manufacturer_id,
                           model_number="MODEL-1",
                           serial_number=1,
                           purchase_date="2025-01-01T00:00:00Z",
                           purchase_price_cents=10000,
                           warranty_months=24,
                           **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "manufacturer_id": manufacturer_id,
        "model_number": model_number,
        "serial_number": serial_number,
        "purchase_date": purchase_date,
        "purchase_price_cents": purchase_price_cents,
        "warranty_months": warranty_months,
    }
    defaults.update(overrides)
    return defaults


def create_recall_notice_payload(manufacturer_id,
                                 affected_model_number="MODEL-1",
                                 serial_range_start=1,
                                 serial_range_end=100,
                                 severity="HIGH",
                                 remedy_type="REPAIR",
                                 effective_from="2025-06-01T00:00:00Z",
                                 effective_to="2026-06-01T00:00:00Z",
                                 **overrides) -> dict:
    defaults = {
        "manufacturer_id": manufacturer_id,
        "affected_model_number": affected_model_number,
        "serial_range_start": serial_range_start,
        "serial_range_end": serial_range_end,
        "severity": severity,
        "remedy_type": remedy_type,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(product_id, filed_by_member_id,
                         claim_type="WARRANTY",
                         resolution_preference="REFUND",
                         issue_description="Test issue",
                         **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "filed_by_member_id": filed_by_member_id,
        "claim_type": claim_type,
        "resolution_preference": resolution_preference,
        "issue_description": issue_description,
    }
    defaults.update(overrides)
    return defaults


def create_claim_document_payload(doc_type="RECEIPT",
                                  file_uri="s3://receipts/test",
                                  **overrides) -> dict:
    defaults = {
        "doc_type": doc_type,
        "file_uri": file_uri,
    }
    defaults.update(overrides)
    return defaults
