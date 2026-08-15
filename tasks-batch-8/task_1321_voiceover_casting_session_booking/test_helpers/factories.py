"""Payload factories — one per creatable entity, input fields only.

Emails are auto-uniquified per call so multiple talents/clients can be created
inside a single test without tripping the uniqueness rule.
"""
import itertools

from .constants import DEFAULT_AUDITION_DEADLINE, TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def create_talent_payload(**overrides) -> dict:
    n = _uniq("talent")
    defaults = {
        "stage_name": f"Stage {n}",
        "email": f"{n}@talents.example.com",
        "voice_profile": "MALE_DEEP",
        "languages": ["en"],
        "union_status": "UNION",
        "base_session_fee_cents": TEST_DEFAULTS["TALENT_BASE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = _uniq("client")
    defaults = {
        "company_name": f"Company {n}",
        "contact_email": f"{n}@clients.example.com",
        "billing_email": f"{n}-billing@clients.example.com",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "title": "Test Project",
        "product_category": "TECH",
        "usage_type": "DIGITAL",
        "spots_count": 1,
        "brief_text": "Direction notes and script excerpt.",
        "audition_deadline": DEFAULT_AUDITION_DEADLINE,
    }
    defaults.update(overrides)
    return defaults


def create_self_audition_payload(talent_id: str, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "audio_file_url": "https://files.example.com/audition.mp3",
    }
    defaults.update(overrides)
    return defaults


def create_studio_payload(**overrides) -> dict:
    n = _uniq("studio")
    defaults = {
        "studio_name": f"Studio {n}",
        "location": "Los Angeles / Room A",
        "has_directed_patch": False,
        "hourly_rate_cents": TEST_DEFAULTS["STUDIO_HOURLY_RATE_CENTS"],
        "operating_tz": "America/Los_Angeles",
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(studio_id: str, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "session_kind": "PRIMARY",
        "directed_patch": False,
        "start_at": "2026-08-02T10:00:00Z",
        "duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(session_id: str, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "file_url": "https://files.example.com/final-mix.wav",
    }
    defaults.update(overrides)
    return defaults
