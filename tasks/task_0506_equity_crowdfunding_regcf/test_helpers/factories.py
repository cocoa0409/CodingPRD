"""Payload factories — one per entity, input fields only."""
import itertools

_ein_counter = itertools.count(1)
_email_counter = itertools.count(1)


def unique_ein() -> str:
    """Generate a unique 9-digit EIN per call (uniqueness across all issuers, PRD §3.1)."""
    n = next(_ein_counter)
    return f"9{n:08d}"


def unique_email(prefix: str = "inv") -> str:
    """Generate a unique investor email per call (uniqueness across all investors, PRD §3.4)."""
    n = next(_email_counter)
    return f"{prefix}{n}@example.com"


def create_issuer_payload(**overrides) -> dict:
    """Input fields for POST /issuers. bad_actor_flag is optional (defaults false, PRD §3.1)."""
    payload = {
        "legal_name": "Test Issuer Co",
        "ein": unique_ein(),
        "home_state_code": "DE",
        "entity_type": "C_CORP",
    }
    payload.update(overrides)
    return payload


def create_investor_payload(**overrides) -> dict:
    """Input fields for POST /investors."""
    payload = {
        "email": unique_email(),
        "legal_name": "Test Investor",
        "annual_income_cents": 100_000_000,
        "net_worth_cents": 100_000_000,
    }
    payload.update(overrides)
    return payload


def create_accreditation_request_payload(investor_id, **overrides) -> dict:
    """Input fields for POST /accreditation-requests."""
    payload = {
        "investor_id": investor_id,
        "method": "INCOME",
    }
    payload.update(overrides)
    return payload


def create_offering_payload(issuer_id, **overrides) -> dict:
    """Input fields for POST /offerings. SAFE offering by default (no price_per_security_cents).
    per_investor_cap_cents is optional (defaults null, PRD §3.2)."""
    payload = {
        "issuer_id": issuer_id,
        "regulation": "REG_CF",
        "security_type": "SAFE",
        "min_target_cents": 100_000,
        "max_target_cents": 1_000_000,
        "deadline_at": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_investment_payload(offering_id, investor_id, expected_offering_version, **overrides) -> dict:
    """Input fields for POST /investments (PRD §3.4)."""
    payload = {
        "offering_id": offering_id,
        "investor_id": investor_id,
        "amount_cents": 200_000,
        "expected_offering_version": expected_offering_version,
    }
    payload.update(overrides)
    return payload


def create_investor_update_payload(offering_id, **overrides) -> dict:
    """Input fields for POST /investor-updates. supersedes_update_id is optional (PRD §3.8)."""
    payload = {
        "offering_id": offering_id,
        "title": "Quarterly update",
        "body": "Here is our progress.",
    }
    payload.update(overrides)
    return payload
