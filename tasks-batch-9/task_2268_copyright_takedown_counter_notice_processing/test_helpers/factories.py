"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def _hash(seed: int) -> str:
    """A well-formed 32-character lowercase hexadecimal fingerprint."""
    return f"{seed:032x}"


def create_provider_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"{TEST_DEFAULTS['PROVIDER_LEGAL_NAME']} {n}",
        "service_domain": TEST_DEFAULTS["PROVIDER_SERVICE_DOMAIN"],
    }
    defaults.update(overrides)
    return defaults


def create_designated_agent_payload(provider_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "agent_name": TEST_DEFAULTS["AGENT_NAME"],
        "agent_email": TEST_DEFAULTS["AGENT_EMAIL"],
        "agent_phone": TEST_DEFAULTS["AGENT_PHONE"],
        "mailing_address": TEST_DEFAULTS["MAILING_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(provider_id: str, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "policy_text": TEST_DEFAULTS["POLICY_TEXT"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(provider_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "provider_id": provider_id,
        "handle": f"{TEST_DEFAULTS['ACCOUNT_HANDLE']}_{n}",
        "email": f"subscriber-{n}@subscriber.example",
    }
    defaults.update(overrides)
    return defaults


def create_content_item_payload(account_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "account_id": account_id,
        "content_url": f"https://{TEST_DEFAULTS['PROVIDER_SERVICE_DOMAIN']}/v/{n}",
        "title": f"Clip {n}",
        "fingerprint_hash": _hash(n),
    }
    defaults.update(overrides)
    return defaults


def create_rights_holder_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"{TEST_DEFAULTS['RIGHTS_HOLDER_LEGAL_NAME']} {n}",
        "contact_email": f"legal-{n}@orbit.example",
    }
    defaults.update(overrides)
    return defaults


def create_reference_file_payload(rights_holder_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "rights_holder_id": rights_holder_id,
        "work_title": f"Reference Work {n}",
        "fingerprint_hash": _hash(n),
    }
    defaults.update(overrides)
    return defaults


def create_ingestion_batch_payload(rights_holder_id: str, item_count: int,
                                   **overrides) -> dict:
    defaults = {"rights_holder_id": rights_holder_id, "item_count": item_count}
    defaults.update(overrides)
    return defaults


def create_notice_payload(rights_holder_id: str, claimed_urls, **overrides) -> dict:
    """A statutorily complete notice: every element present, score 100."""
    defaults = {
        "rights_holder_id": rights_holder_id,
        "submission_channel": "WEB_FORM",
        "claimed_urls": list(claimed_urls),
        "signature_present": True,
        "work_identification": "Sound recording: Orbit Vol. 1, track 3",
        "material_identification": "Track 3 posted at the claimed URL",
        "contact_email": TEST_DEFAULTS["RIGHTS_HOLDER_CONTACT_EMAIL"],
        "good_faith_statement": True,
        "accuracy_statement": True,
        "authority_statement": True,
        "sworn_under_penalty": True,
    }
    defaults.update(overrides)
    return defaults


def create_counter_notice_payload(claim_id: str, expected_claim_version: int,
                                  **overrides) -> dict:
    """A statutorily complete counter-notice: every element present, score 100."""
    defaults = {
        "claim_id": claim_id,
        "expected_claim_version": expected_claim_version,
        "subscriber_name": "Ada Lovelace",
        "contact_email": TEST_DEFAULTS["ACCOUNT_EMAIL"],
        "material_identification": "Clip formerly published at the disabled URL",
        "signature_present": True,
        "good_faith_mistake_statement": True,
        "consent_to_jurisdiction": True,
        "consent_to_service_of_process": True,
    }
    defaults.update(overrides)
    return defaults


def create_misrepresentation_case_payload(rights_holder_id: str, claim_id: str,
                                          **overrides) -> dict:
    defaults = {
        "rights_holder_id": rights_holder_id,
        "claim_id": claim_id,
        "allegation": (
            "The complainant does not hold rights in the material identified "
            "by this notice."
        ),
    }
    defaults.update(overrides)
    return defaults
