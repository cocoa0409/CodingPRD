"""Payload factories — one per entity, input fields only.

Each factory provides PRD-required fields plus sensible defaults and accepts **overrides.
license_number / email / table label / modality code are uniquified per call so that the
uniqueness constraints in the PRD do not collide across a fixture's many creates.
"""
import itertools

_seq = itertools.count(1)


def _uid() -> int:
    return next(_seq)


def _letters(n: int) -> str:
    """Bijective base-26 (A-Z) encoding of a positive int -> uppercase letters only.

    PRD §2.4: a modality `code` is two to eight *letters* (no digits). This yields a
    unique, letters-only suffix per counter value so the per-modality code uniqueness
    constraint never collides across a fixture's many creates.
    """
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return s or "A"


def create_modality_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "name": f"Swedish {n}",
        "code": ("MOD" + _letters(n))[:8],
        "base_price_cents": 12000,
    }
    defaults.update(overrides)
    return defaults


def create_therapist_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "full_name": f"Therapist {n}",
        "license_number": f"LMT-{(700000 + n) % 1000000:06d}",
        "license_expiry": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(therapist_id, modality_code, **overrides) -> dict:
    defaults = {
        "therapist_id": therapist_id,
        "modality_code": modality_code,
        "cert_expiry": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_table_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "label": f"Table {n}",
        "room": f"Room {n}",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "full_name": f"Client {n}",
        "email": f"client{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_intake_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "draping_policy": "FULL_DRAPE",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    n = _uid()
    defaults = {
        "name": f"Plan {n}",
        "monthly_fee_cents": 9000,
        "included_sessions": 1,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(client_id, plan_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_commission_tier_payload(tier_index, floor_revenue_cents, commission_pct, **overrides) -> dict:
    defaults = {
        "tier_index": tier_index,
        "floor_revenue_cents": floor_revenue_cents,
        "commission_pct": commission_pct,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(client_id, therapist_id, table_id, modality_id,
                               consent_id, expected_table_version, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "therapist_id": therapist_id,
        "table_id": table_id,
        "modality_id": modality_id,
        "consent_id": consent_id,
        "start_at": "2026-01-05T09:00:00Z",
        "duration_minutes": 60,
        "payer": "CASH",
        "expected_table_version": expected_table_version,
    }
    defaults.update(overrides)
    return defaults


def create_soap_note_payload(appointment_id, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "subjective": "s",
        "objective": "o",
        "assessment": "a",
        "plan": "p",
    }
    defaults.update(overrides)
    return defaults


def create_superbill_payload(appointment_id, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "diagnosis_codes": ["M54.5"],
        "cpt_code": "97124",
    }
    defaults.update(overrides)
    return defaults
