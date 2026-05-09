"""Payload factories — one per entity, input fields only.

Each factory emits the exact PRD-declared input schema for the corresponding
endpoint and supports **overrides for tests that need to vary specific fields.

Field name authority is the PRD; tests and assertions assume the implementation
will return responses keyed by the same names. Computed/system fields are NOT
present in factories — those come back on the response body.
"""
from typing import Any, Dict, List, Optional
import uuid


# --- counters / unique-value helpers ----------------------------------------

_BATCH_COUNTER = 0
_BIN_COUNTER = 0
_REG_COUNTER = 0


def unique_batch_code() -> str:
    """PRD §3.2: ^PB-[A-Z0-9]{8}$ — uppercase alphanumeric, 8 chars after the prefix."""
    global _BATCH_COUNTER
    _BATCH_COUNTER += 1
    suffix = f"{_BATCH_COUNTER:08X}"  # zero-padded uppercase hex, exactly 8 chars
    return f"PB-{suffix}"


def unique_bin_code() -> str:
    """PRD §3.4: ^WH-[A-Z][0-9]{3}$ — single uppercase letter + three digits."""
    global _BIN_COUNTER
    _BIN_COUNTER += 1
    # spread across letters A..Z to avoid collisions over many calls
    letter = chr(ord("A") + (_BIN_COUNTER // 1000) % 26)
    digits = f"{_BIN_COUNTER % 1000:03d}"
    return f"WH-{letter}{digits}"


def unique_pesticide_registration_no() -> str:
    """PRD §3.1: ^PD-[0-9]{6}$ for pesticides."""
    global _REG_COUNTER
    _REG_COUNTER += 1
    return f"PD-{_REG_COUNTER:06d}"


def unique_fertilizer_registration_no() -> str:
    """PRD §3.1: ^FT-[0-9]{6}$ for fertilizers."""
    global _REG_COUNTER
    _REG_COUNTER += 1
    return f"FT-{_REG_COUNTER:06d}"


def unique_idempotency_key() -> str:
    return f"idem-{uuid.uuid4().hex}"


# --- PesticideRegistry ------------------------------------------------------

def create_registry_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 — register a pesticide or fertilizer entry."""
    defaults: Dict[str, Any] = {
        "registration_no": unique_pesticide_registration_no(),
        "product_name": "Test Pesticide",
        "category": "PESTICIDE",
        "withdrawal_period_days": 14,
        "max_dosage_per_hectare_g": 200.0,
    }
    defaults.update(overrides)
    return defaults


def prohibit_registry_payload(prohibited_since: str) -> Dict[str, Any]:
    """PRD §3.1: prohibition records `prohibited_since` (date)."""
    return {"prohibited_since": prohibited_since}


# --- PlantingBatch ----------------------------------------------------------

def create_planting_batch_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2 — register a planting batch.

    PRD: registering grower's `X-User-ID` is captured as `grower_id`; the
    payload itself does NOT carry grower_id.
    """
    defaults: Dict[str, Any] = {
        "batch_code": unique_batch_code(),
        "field_plot_id": "FIELD-001",
        "plot_area_hectares": 1.5,
        "crop_variety": "Tomato-Roma-VF",
        "planting_date": "2026-01-01T00:00:00.000Z",
        "expected_harvest_start": "2026-04-01T00:00:00.000Z",
        "expected_harvest_end": "2026-05-01T00:00:00.000Z",
        "grower_name": "Test Grower Co",
    }
    defaults.update(overrides)
    return defaults


# --- AgrochemicalApplication ------------------------------------------------

def create_agrochemical_application_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3 — record a pesticide/fertilizer application."""
    defaults: Dict[str, Any] = {
        "registration_no": "PD-000001",
        "application_date": "2026-02-01T00:00:00.000Z",
        "dosage_g_per_hectare": 50.0,
    }
    defaults.update(overrides)
    return defaults


# --- HarvestRecord ----------------------------------------------------------

def create_harvest_record_payload(storage_bin_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.4 — record a harvest entry."""
    defaults: Dict[str, Any] = {
        "harvest_date": "2026-04-15T00:00:00.000Z",
        "quantity_kg": 50.0,
        "quality_grade": "A",
        "packaging_spec": "5kg-carton-ventilated",
        "storage_bin_id": storage_bin_id,
    }
    defaults.update(overrides)
    return defaults


# --- StorageBin -------------------------------------------------------------

def create_storage_bin_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.4 — create a warehouse bin."""
    defaults: Dict[str, Any] = {
        "bin_code": unique_bin_code(),
        "warehouse_zone": "COLD",
        "capacity_kg": 100.0,
    }
    defaults.update(overrides)
    return defaults


# --- LogisticsLeg -----------------------------------------------------------

def create_logistics_leg_payload(
    leg_index: int,
    from_party_id: str,
    to_party_id: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6 — plan a logistics leg."""
    defaults: Dict[str, Any] = {
        "leg_index": leg_index,
        "from_party_id": from_party_id,
        "to_party_id": to_party_id,
        "depart_at": "2026-04-20T00:00:00.000Z",
        "arrive_at": "2026-04-21T00:00:00.000Z",
        "temperature_min_c": 2.0,
        "temperature_max_c": 4.0,
    }
    defaults.update(overrides)
    return defaults


# --- SensorReading ----------------------------------------------------------

def create_sensor_reading_payload(
    reading_at: str,
    temperature_c: float,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6 — submit an IoT temperature reading.

    Each reading carries device_id, idempotency_key (unique within the leg),
    reading_at, and temperature_c.
    """
    defaults: Dict[str, Any] = {
        "device_id": "sensor-device-001",
        "idempotency_key": unique_idempotency_key(),
        "reading_at": reading_at,
        "temperature_c": temperature_c,
    }
    defaults.update(overrides)
    return defaults


# --- InspectionReport -------------------------------------------------------

def create_inspection_report_payload(
    test_items: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5 — create a draft inspection report.

    PRD §3.5: required measurement fields per selected test_item:
      PESTICIDE_RESIDUE -> pesticide_residue_mg_per_kg
      HEAVY_METALS      -> heavy_metals_mg_per_kg
      MICROORGANISMS    -> microorganism_cfu_per_g
    Default factory selects all three with PASS values to keep tests simple.
    """
    if test_items is None:
        test_items = ["PESTICIDE_RESIDUE", "HEAVY_METALS", "MICROORGANISMS"]
    defaults: Dict[str, Any] = {
        "sampling_rule": "RANDOM_5PCT",
        "test_items": list(test_items),
    }
    if "PESTICIDE_RESIDUE" in test_items:
        defaults["pesticide_residue_mg_per_kg"] = 0.10
    if "HEAVY_METALS" in test_items:
        defaults["heavy_metals_mg_per_kg"] = 0.05
    if "MICROORGANISMS" in test_items:
        defaults["microorganism_cfu_per_g"] = 50000
    defaults.update(overrides)
    return defaults


# --- Distributor ------------------------------------------------------------

def create_distributor_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.8 — register a distributor."""
    defaults: Dict[str, Any] = {
        "name": "Test Distributor LLC",
        "contact_email": "ops@dist.example.com",
        "tier": "WHOLESALE",
        "notification_endpoint": "https://hooks.example.com/recall",
    }
    defaults.update(overrides)
    return defaults


# --- RecallOrder ------------------------------------------------------------

def create_recall_payload(planting_batch_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.8 — initiate a recall."""
    defaults: Dict[str, Any] = {
        "planting_batch_id": planting_batch_id,
        "recall_class": "CLASS_II",
        "reason_code": "CONSUMER_COMPLAINT",
    }
    defaults.update(overrides)
    return defaults


def create_disposal_payload(distributor_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.8 — distributor records a disposal entry."""
    defaults: Dict[str, Any] = {
        "distributor_id": distributor_id,
        "disposed_kg": 10.0,
        "disposed_at": "2026-04-22T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# --- QR trace ---------------------------------------------------------------

def trace_qr_payload(anti_counterfeit_token: str) -> Dict[str, Any]:
    """PRD §3.7 — consumer trace request body carries the anti-counterfeit token."""
    return {"anti_counterfeit_token": anti_counterfeit_token}
