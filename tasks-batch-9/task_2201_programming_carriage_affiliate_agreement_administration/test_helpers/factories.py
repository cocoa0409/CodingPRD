"""Payload factories — one per resource, client-supplied input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for uniqueness-constrained fields."""
    return str(next(_counter))


def create_distributor_payload(**overrides) -> dict:
    payload = {
        "legal_name": f"Northgate Cable Systems {unique_suffix()}",
        "distributor_type": "CABLE_MSO",
        "rate_card_class": "CLASS_A",
        "total_subscribers": TEST_DEFAULTS["TOTAL_SUBSCRIBERS"],
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(distributor_id: str, **overrides) -> dict:
    payload = {
        "distributor_id": distributor_id,
        "contract_code": f"NG-2024-{unique_suffix()}",
        "term_start_date": TEST_DEFAULTS["TERM_START_DATE"],
        "term_end_date": TEST_DEFAULTS["TERM_END_DATE"],
        "base_license_fee_cents_per_sub": TEST_DEFAULTS["BASE_LICENSE_FEE_CENTS_PER_SUB"],
        "escalator_pct": TEST_DEFAULTS["ESCALATOR_PCT"],
        "penetration_floor_pct": TEST_DEFAULTS["PENETRATION_FLOOR_PCT"],
        "committed_tier": "EXPANDED_BASIC",
        "launch_fee_cents": 0,
        "marketing_commitment_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_rate_card_entry_payload(**overrides) -> dict:
    payload = {
        "rate_card_class": "CLASS_A",
        "tier": "EXPANDED_BASIC",
        "published_rate_cents_per_sub": 45.0000,
        "min_subscribers": 0,
        "effective_from": "2024-01-01T00:00:00Z",
        "effective_to": None,
    }
    payload.update(overrides)
    return payload


def create_mfn_clause_payload(agreement_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "mfn_scope": "DOMESTIC",
        "min_peer_subscribers": 0,
        "rate_floor_cents": 0.0000,
    }
    payload.update(overrides)
    return payload


def create_subscriber_report_payload(
    agreement_id: str, expected_agreement_version: int, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "period_month": "2026-06",
        "reported_subscribers": 3_500_000,
        "reported_tier": "EXPANDED_BASIC",
        "expected_agreement_version": expected_agreement_version,
    }
    payload.update(overrides)
    return payload


def create_audit_engagement_payload(agreement_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "sample_period_start": "2026-06",
        "sample_period_end": "2026-06",
        "rate_basis": "PERIOD_RATE",
    }
    payload.update(overrides)
    return payload


def create_audit_finding_payload(subscriber_report_id: str, audited_subscribers: int, **overrides) -> dict:
    payload = {
        "subscriber_report_id": subscriber_report_id,
        "audited_subscribers": audited_subscribers,
    }
    payload.update(overrides)
    return payload


def create_content_title_payload(**overrides) -> dict:
    payload = {
        "title": f"Midnight Circuit {unique_suffix()}",
        "home_territory_code": "US",
        "linear_premiere_at": "2026-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_rights_window_payload(agreement_id: str, content_title_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "content_title_id": content_title_id,
        "platform": "LINEAR",
        "territory_code": "US",
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-10-01T00:00:00Z",
        "exclusivity": "EXCLUSIVE",
    }
    payload.update(overrides)
    return payload


def create_blackout_rule_payload(agreement_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "territory_code": "US",
        "blackout_start": "2026-09-10T00:00:00Z",
        "blackout_end": "2026-09-11T00:00:00Z",
        "substitution_required": False,
    }
    payload.update(overrides)
    return payload


def create_marketing_commitment_payload(agreement_id: str, **overrides) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "commitment_type": "COOP_ADVERTISING",
        "committed_cents": 10_000_000,
        "performance_deadline": "2027-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(
    distributor_id: str,
    agreement_id: str,
    period_month: str,
    expected_distributor_version: int,
    **overrides,
) -> dict:
    payload = {
        "distributor_id": distributor_id,
        "agreement_id": agreement_id,
        "period_month": period_month,
        "invoice_kind": "LICENSE_FEE",
        "audit_engagement_id": None,
        "expected_distributor_version": expected_distributor_version,
    }
    payload.update(overrides)
    return payload


def create_renewal_analysis_payload(agreement_id: str, **overrides) -> dict:
    payload = {"agreement_id": agreement_id, "variant": "BASE_CASE"}
    payload.update(overrides)
    return payload


def earn_payload(earned_cents: int, proof_reference: str = "PROOF-001", **overrides) -> dict:
    payload = {"earned_cents": earned_cents, "proof_reference": proof_reference}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
