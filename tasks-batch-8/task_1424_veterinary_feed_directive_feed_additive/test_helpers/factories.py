"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools
import uuid

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Unique suffix for unique-constrained fields (license numbers, PINs, etc.)."""
    return f"{prefix}-{next(_counter)}-{uuid.uuid4().hex[:8]}"


def create_clinic_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Clinic",
        "license_number": _uniq("LIC"),
        "state_code": "IA",
    }
    defaults.update(overrides)
    return defaults


def create_veterinarian_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr. Test Vet",
        "license_number": _uniq("DVM"),
        "state_code": "IA",
    }
    defaults.update(overrides)
    return defaults


def create_producer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Farm",
        "premise_id": _uniq("PIN"),
        "state_code": "IA",
    }
    defaults.update(overrides)
    return defaults


def create_animal_group_payload(**overrides) -> dict:
    defaults = {
        "species": "CATTLE",
        "production_class": "BEEF",
        "head_count": 100,
        "average_weight_lbs": 1200,
        "earliest_market_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults


def create_drug_payload(**overrides) -> dict:
    defaults = {
        "drug_code": _uniq("DRUG"),
        "label_name": "Test Medication",
        "withdrawal_hours": 24,
        "allowed_species_classes": ["CATTLE:BEEF"],
        "max_duration_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_vcp_verification_payload(vet_id: str, producer_id: str, **overrides) -> dict:
    defaults = {
        "vet_id": vet_id,
        "producer_id": producer_id,
        "expires_on": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vfd_authorization_payload(
    producer_id: str, animal_group_id: str, vet_id: str, drug_id: str, **overrides
) -> dict:
    defaults = {
        "producer_id": producer_id,
        "animal_group_id": animal_group_id,
        "vet_id": vet_id,
        "drug_id": drug_id,
        "authorized_animal_count": 50,
        "feed_duration_days": 7,
        "expiration_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_feed_mill_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Mill",
        "fda_registration": _uniq("FDA"),
        "state_code": "IA",
    }
    defaults.update(overrides)
    return defaults


def create_feed_order_payload(vfd_authorization_id: str, producer_id: str, **overrides) -> dict:
    defaults = {
        "vfd_authorization_id": vfd_authorization_id,
        "producer_id": producer_id,
        "animal_count": 5,
        "tons_of_feed": 1,
        "intended_use_label": "label use",
    }
    defaults.update(overrides)
    return defaults


def create_distributor_acknowledgment_payload(covers_drug_id: str, **overrides) -> dict:
    defaults = {
        "distributor_name": "Test Distributor",
        "covers_drug_id": covers_drug_id,
        "statement_text": "Acknowledgment of VFD feed distribution responsibilities.",
    }
    defaults.update(overrides)
    return defaults


def create_residue_case_payload(feed_order_id: str, **overrides) -> dict:
    defaults = {
        "feed_order_id": feed_order_id,
        "detected_at": "2026-08-05T00:00:00Z",
        "investigator_id": "inv-1",
    }
    defaults.update(overrides)
    return defaults


def create_audit_bundle_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-07-01T00:00:00Z",
        "window_end": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
