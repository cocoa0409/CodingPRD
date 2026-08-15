"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def create_pack_out_job_payload(**overrides) -> dict:
    defaults = {
        "claim_number": _unique("CLM"),
        "property_address": "1 Test Way",
        "carrier_name": "Acme Mutual",
        "policy_coverage_type": "ACV",
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Room",
        "room_type": "LIVING",
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "barcode": _unique("BC"),
        "description": "Test item",
        "item_category": "GENERAL",
        "declared_value_cents": 1000,
        "volume_cu_ft": 5,
    }
    defaults.update(overrides)
    return defaults


def create_vault_payload(**overrides) -> dict:
    defaults = {
        "code": _unique("V"),
        "climate_class": "CLIMATE_CONTROLLED",
        "capacity_cu_ft": 1000,
        "monthly_rate_cents_per_cu_ft": 100,
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {
        "name": _unique("Vendor"),
        "specialty_types": ["ART_CONSERVATION"],
        "max_concurrent_referrals": 5,
    }
    defaults.update(overrides)
    return defaults


def create_specialty_referral_payload(subcontractor_id: str, **overrides) -> dict:
    defaults = {
        "subcontractor_id": subcontractor_id,
        "specialty_type": "ART_CONSERVATION",
        "quoted_cost_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_custody_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "PICKED_UP",
        "event_at": "2026-08-05T10:00:00Z",
        "actor_name": "tech-1",
    }
    defaults.update(overrides)
    return defaults


def create_handling_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "DAMAGE",
        "description": "Damaged during handling",
        "replacement_cost_cents": 10000,
        "item_age_years": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pack_back_schedule_payload(**overrides) -> dict:
    defaults = {
        "crew_id": "crew-1",
        "service_date": "2026-09-10",
        "window_start_hour": 8,
        "window_end_hour": 12,
    }
    defaults.update(overrides)
    return defaults


def create_storage_statement_payload(expected_job_version: int, **overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01",
        "period_end": "2026-09-01",
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def create_carrier_invoice_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def triage_payload(expected_item_version: int, determination: str = "SALVAGEABLE") -> dict:
    return {
        "determination": determination,
        "expected_item_version": expected_item_version,
    }


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
