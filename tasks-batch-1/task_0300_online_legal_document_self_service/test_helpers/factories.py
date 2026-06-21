"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the PRD-declared input fields with sensible defaults;
tests override anything they need to control. Computed/system/derived fields are
never included.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="user") -> str:
    """Generate a unique email for a fresh customer (email is unique among customers)."""
    return f"{prefix}{next(_email_counter)}@example.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("cust"),
        "full_name": "Test Customer",
        "state_of_residence": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "STANDARD",
        "monthly_fee_cents": 0,
        "included_project_credits": 3,
        "included_clause_count": 5,
        "subscription_discount_pct": 0.15,
        "review_discount_pct": 0.15,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, plan_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_clause_template_payload(clause_key, document_type, state_code,
                                   is_mandatory, body_text, **overrides) -> dict:
    defaults = {
        "clause_key": clause_key,
        "document_type": document_type,
        "state_code": state_code,
        "is_mandatory": is_mandatory,
        "body_text": body_text,
    }
    defaults.update(overrides)
    return defaults


def create_document_project_payload(customer_id, subscription_id, document_type,
                                    state_code, title="Test Project", **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "subscription_id": subscription_id,
        "document_type": document_type,
        "state_code": state_code,
        "title": title,
    }
    defaults.update(overrides)
    return defaults


def create_attorney_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Attorney",
        "bar_state": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_attorney_review_payload(document_project_id, attorney_id,
                                   window_start, window_end, **overrides) -> dict:
    defaults = {
        "document_project_id": document_project_id,
        "attorney_id": attorney_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_document_revision_payload(document_project_id,
                                     expected_document_project_version, **overrides) -> dict:
    defaults = {
        "document_project_id": document_project_id,
        "expected_document_project_version": expected_document_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_signature_request_payload(document_revision_id, signer_emails, **overrides) -> dict:
    defaults = {
        "document_revision_id": document_revision_id,
        "signer_emails": signer_emails,
    }
    defaults.update(overrides)
    return defaults


def create_notary_referral_payload(signature_request_id, referral_state_code, **overrides) -> dict:
    defaults = {
        "signature_request_id": signature_request_id,
        "referral_state_code": referral_state_code,
    }
    defaults.update(overrides)
    return defaults


def full_answers(document_type: str) -> dict:
    """A complete answers map (all required questions answered) for a document type."""
    from .constants import TOTAL_REQUIRED_QUESTIONS
    n = TOTAL_REQUIRED_QUESTIONS[document_type]
    return {f"q{i}": "a" for i in range(1, n + 1)}


def partial_answers(count: int) -> dict:
    """An answers map with `count` non-empty answers (q1..q{count})."""
    return {f"q{i}": "a" for i in range(1, count + 1)}
