"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_drug_payload(**overrides) -> dict:
    """DrugCatalog create payload (PRD 3.1). is_specialty and requires_trough_lab
    are optional and default to false server-side when omitted."""
    defaults = {
        "ndc_code": _unique("NDC"),
        "generic_name": "ceftriaxone",
        "therapy_category": "ANTI_INFECTIVE",
        "vial_size_mg": 1000,
        "awp_per_vial_cents": 2000,
        "is_specialty": False,
        "requires_trough_lab": False,
        "lot_total_vials": 100,
    }
    defaults.update(overrides)
    return defaults


def create_payer_plan_payload(**overrides) -> dict:
    """PayerPlan create payload (PRD 3.1)."""
    defaults = {
        "plan_code": _unique("PLAN"),
        "per_diem_rate_cents": {"ANTI_INFECTIVE": 12500},
        "awp_discount_pct": 0.10,
        "coinsurance_pct": 0.20,
        "deductible_remaining_cents": 10000,
        "oop_max_remaining_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_nurse_payload(**overrides) -> dict:
    """Nurse create payload (PRD 3.1). status is optional, defaults to ACTIVE."""
    defaults = {
        "full_name": "Nurse Test",
        "license_state": "CA",
        "status": "ACTIVE",
    }
    defaults.update(overrides)
    return defaults


def create_pump_payload(**overrides) -> dict:
    """Pump create payload (PRD 3.1). status is optional, defaults to AVAILABLE."""
    defaults = {
        "asset_tag": _unique("PUMP"),
        "model": "AMBULATORY",
        "status": "AVAILABLE",
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    """Patient create payload (PRD 3.1)."""
    defaults = {
        "full_name": "Patient Test",
        "service_state": "CA",
        # payer_plan_id must be supplied by the caller.
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    """Referral create payload (PRD 3.2)."""
    defaults = {
        # patient_id must be supplied by the caller.
        "referring_provider_npi": "1234567890",
        "diagnosis_code": "A41.9",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    """InfusionOrder create payload (PRD 3.2)."""
    defaults = {
        # referral_id and drug_id must be supplied by the caller.
        "route": "IV",
        "daily_dose_mg": 1000,
        "frequency_per_day": 1,
        "start_date": "2026-06-10T00:00:00Z",
        "scheduled_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_prior_auth_payload(**overrides) -> dict:
    """PriorAuthorization create payload (PRD 3.3)."""
    defaults = {
        # order_id must be supplied by the caller.
        "requested_units": 10,
    }
    defaults.update(overrides)
    return defaults


def create_compound_payload(**overrides) -> dict:
    """Compound create payload (PRD 3.4)."""
    defaults = {
        # order_id and pump_id must be supplied by the caller.
        "delivery_at": "2026-06-10T09:00:00Z",
        "retrieval_at": "2026-06-17T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_supply_kit_payload(**overrides) -> dict:
    """SupplyKit create payload (PRD 3.8)."""
    defaults = {
        # order_id must be supplied by the caller.
        "kit_type": "START_OF_CARE",
        "line_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(**overrides) -> dict:
    """NursingVisit create payload (PRD 3.6). compound_id is optional (teach-only)."""
    defaults = {
        # order_id and nurse_id must be supplied by the caller.
        "visit_type": "ADMINISTER",
        "start_at": "2026-06-10T09:00:00Z",
        "duration_min": 120,
    }
    defaults.update(overrides)
    return defaults


def create_lab_result_payload(**overrides) -> dict:
    """LabResult create payload (PRD 3.7). is_critical is optional, defaults false."""
    defaults = {
        # order_id must be supplied by the caller.
        "lab_type": "TROUGH",
        "value_num": 15.0,
        "collected_at": "2026-06-10T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(**overrides) -> dict:
    """AdverseEvent create payload (PRD 3.9). visit_id is optional (null if not bound)."""
    defaults = {
        # order_id must be supplied by the caller.
        "severity_grade": 1,
        "reaction_count": 0,
        "vital_instability": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    """Claim create payload (PRD 3.12)."""
    defaults = {
        # order_id and expected_order_version must be supplied by the caller.
    }
    defaults.update(overrides)
    return defaults
