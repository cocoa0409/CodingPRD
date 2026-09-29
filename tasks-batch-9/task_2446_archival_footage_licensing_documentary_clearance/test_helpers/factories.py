"""Payload factories — one per operation input list, client-supplied fields only.

Path-derived foreign keys (PRD §2.5) are never put in a body: `production_id` on
an asset, subject release, clearance chart, E&O application and delivery package;
`archive_id` on a rate card; `asset_id` on a source candidate and a fair-use
analysis; `license_id` on a negotiation round; and `fair_use_analysis_id` on an
opinion letter are all taken from the URL.
"""
from typing import Any, Dict

from .constants import TEST_DEFAULTS


def create_production_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "title": "Salt Flats",
        "delivery_deadline_date": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def create_archive_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "name": "Pathe Vault",
        "holder_type": "FILM_ARCHIVE",
    }
    payload.update(overrides)
    return payload


def create_rate_card_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "base_rate_per_30s_cents": TEST_DEFAULTS["base_rate_per_30s_cents"],
        "minimum_fee_cents": TEST_DEFAULTS["minimum_fee_cents"],
        "festival_minimum_fee_cents": TEST_DEFAULTS["festival_minimum_fee_cents"],
        "effective_from_date": TEST_DEFAULTS["effective_from_date"],
    }
    payload.update(overrides)
    return payload


def create_asset_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "asset_type": "ARCHIVAL_FOOTAGE",
        "title": "Dockside crane",
        "timecode_in_seconds": 0,
        "timecode_out_seconds": 45,
        "usage_purpose": "CRITICAL_COMMENTARY",
    }
    payload.update(overrides)
    return payload


def create_source_candidate_payload(archive_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "archive_id": archive_id,
        "availability_status": "AVAILABLE",
    }
    payload.update(overrides)
    return payload


def select_source_payload(source_candidate_id: str, **overrides) -> Dict[str, Any]:
    payload = {"source_candidate_id": source_candidate_id}
    payload.update(overrides)
    return payload


def create_license_payload(production_id: str, asset_id: str, archive_id: str,
                           **overrides) -> Dict[str, Any]:
    """The one resource that names its own graph edges in the body (PRD §2.5)."""
    payload = {
        "production_id": production_id,
        "asset_id": asset_id,
        "archive_id": archive_id,
        "rights_leg": "FOOTAGE",
        "media": "BROADCAST",
        "territory": "WORLD",
        "window_class": "ALL_MEDIA_WINDOW",
        "term_months": TEST_DEFAULTS["term_months"],
        "term_start_date": TEST_DEFAULTS["term_start_date"],
        "term_end_date": TEST_DEFAULTS["term_end_date"],
    }
    payload.update(overrides)
    return payload


def create_negotiation_round_payload(proposed_fee_cents: int,
                                     expected_license_version: int,
                                     party: str = "LICENSOR",
                                     **overrides) -> Dict[str, Any]:
    payload = {
        "party": party,
        "proposed_fee_cents": proposed_fee_cents,
        "expected_license_version": expected_license_version,
    }
    payload.update(overrides)
    return payload


def create_fair_use_analysis_payload(**overrides) -> Dict[str, Any]:
    """The four favourability scores. 90/60/40/50 is the PRD §3.5 worked example."""
    payload = {
        "transformative_score": 90,
        "nature_score": 60,
        "amount_used_score": 40,
        "market_harm_score": 50,
    }
    payload.update(overrides)
    return payload


def create_opinion_letter_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "counsel_firm": "Harrow & Vance",
        "letter_reference": "HV-2026-014",
        "risk_rating": "MODERATE",
    }
    payload.update(overrides)
    return payload


def create_subject_release_payload(subject_person_key: str, **overrides) -> Dict[str, Any]:
    payload = {
        "subject_person_key": subject_person_key,
        "release_type": "SUBJECT_RELEASE",
        "depiction_from_date": "2026-03-01",
        "depiction_to_date": "2026-03-31",
    }
    payload.update(overrides)
    return payload


def pin_clearance_chart_payload(expected_production_version: int,
                                chart_label: str = "v1", **overrides) -> Dict[str, Any]:
    payload = {
        "chart_label": chart_label,
        "expected_production_version": expected_production_version,
    }
    payload.update(overrides)
    return payload


def create_eo_application_payload(clearance_chart_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "clearance_chart_id": clearance_chart_id,
        "coverage_limit_cents": 4000000,
        "retention_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_eo_review_payload(review_type: str, outcome: str = "PASS",
                             **overrides) -> Dict[str, Any]:
    payload = {
        "review_type": review_type,
        "outcome": outcome,
    }
    payload.update(overrides)
    return payload


def create_delivery_package_payload(clearance_chart_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "clearance_chart_id": clearance_chart_id,
        "distributor_name": "Northgate Docs",
        "window_class": "ALL_MEDIA_WINDOW",
    }
    payload.update(overrides)
    return payload


def state_payload(to_status: str, **overrides) -> Dict[str, Any]:
    """Body for any of the state-driving operations."""
    payload = {"to_status": to_status}
    payload.update(overrides)
    return payload


def renew_license_payload(additional_term_months: int, **overrides) -> Dict[str, Any]:
    payload = {"additional_term_months": additional_term_months}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
