"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_cell_payload(**overrides) -> dict:
    defaults = {
        "age_band": "AGE_18_29",
        "district": "D1",
        "tenure_bucket": "RENTER",
        "target_size": 5,
    }
    defaults.update(overrides)
    return defaults


def create_panelist_payload(**overrides) -> dict:
    defaults = {
        "external_ref": f"{_uniq('ref')}@example.test",
        "full_name": "Test Panelist",
        "age_band": "AGE_18_29",
        "district": "D1",
        "tenure_bucket": "RENTER",
        "preferred_locale": "en",
    }
    defaults.update(overrides)
    return defaults


def create_instrument_payload(**overrides) -> dict:
    defaults = {
        "title": _uniq("Survey"),
        "question_count": 5,
        "required_locales": ["en"],
        "base_locale": "en",
    }
    defaults.update(overrides)
    return defaults


def create_translation_payload(instrument_id, **overrides) -> dict:
    defaults = {
        "instrument_id": instrument_id,
        "locale": "en",
        "translator_ref": _uniq("tr"),
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(instrument_id, **overrides) -> dict:
    defaults = {
        "wave_code": _uniq("W"),
        "instrument_id": instrument_id,
        "opens_at": TEST_DEFAULTS["OPENS_AT"],
        "closes_at": TEST_DEFAULTS["CLOSES_AT"],
        "min_response_rate": TEST_DEFAULTS["MIN_RESPONSE_RATE"],
        "incentive_pool_total_cents": TEST_DEFAULTS["POOL_TOTAL_CENTS"],
        "base_incentive_cents": TEST_DEFAULTS["BASE_INCENTIVE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(wave_id, panelist_id, **overrides) -> dict:
    defaults = {"wave_id": wave_id, "panelist_id": panelist_id}
    defaults.update(overrides)
    return defaults


def create_response_payload(invitation_id, **overrides) -> dict:
    defaults = {
        "invitation_id": invitation_id,
        "answers_payload": {"q1": 4},
        "completeness_pct": 100,
        "completion_seconds": 300,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(expected_wave_version, **overrides) -> dict:
    defaults = {"method": "POST_STRAT", "expected_wave_version": expected_wave_version}
    defaults.update(overrides)
    return defaults


def create_publication_payload(wave_id, weight_snapshot_id, **overrides) -> dict:
    defaults = {
        "wave_id": wave_id,
        "weight_snapshot_id": weight_snapshot_id,
        "title": "Results",
        "k_threshold": 1,
    }
    defaults.update(overrides)
    return defaults


def create_commitment_payload(publication_id, **overrides) -> dict:
    defaults = {
        "publication_id": publication_id,
        "department_name": "DEPT_TRANSPORT",
        "summary": "Act on findings",
        "due_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_privacy_hold_payload(panelist_id, **overrides) -> dict:
    defaults = {
        "panelist_id": panelist_id,
        "scope": "NO_CONTACT",
        "reason": "audit check",
    }
    defaults.update(overrides)
    return defaults


def create_refresh_run_payload(**overrides) -> dict:
    defaults = {"run_label": _uniq("refresh")}
    defaults.update(overrides)
    return defaults
