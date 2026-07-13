"""Payload factories — one per creatable entity, input fields only."""

from .constants import REQUIRED_FIELDS


def create_plan_catalog_payload(**overrides) -> dict:
    defaults = {
        "plan_tier": "PLUS",
        "base_price_cents": 20000,
        "included_document_types": ["WILL"],
        "max_documents": 10,
        "allows_trust": False,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": "member@example.com",
        "full_name": "Test Member",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "plan_tier": "PLUS",
        "bundle_type": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_questionnaire_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "document_type": "WILL",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def full_answers(document_type: str) -> dict:
    """A distinct set of answer keys equal in number to the document type's
    required-field count, so a single submission drives completeness to 100."""
    n = REQUIRED_FIELDS[document_type]
    return {f"q{i}": chr(ord("a") + i - 1) for i in range(1, n + 1)}


def partial_answers(count: int) -> dict:
    """`count` distinct answer keys."""
    return {f"q{i}": chr(ord("a") + i - 1) for i in range(1, count + 1)}


def create_beneficiary_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "full_name": "Test Heir",
        "relationship": "CHILD",
        "allocation_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "asset_type": "BANK",
        "description": "Test Asset",
        "estimated_value_cents": 50000,
        "funding_status": "UNFUNDED",
    }
    defaults.update(overrides)
    return defaults


def create_executor_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "full_name": "Test Executor",
        "email": "executor@example.com",
        "priority_order": 1,
    }
    defaults.update(overrides)
    return defaults


def create_share_grant_payload(document_id: str, **overrides) -> dict:
    defaults = {
        "document_id": document_id,
        "grantee_email": "grantee@example.com",
        "scope": "VIEW",
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
