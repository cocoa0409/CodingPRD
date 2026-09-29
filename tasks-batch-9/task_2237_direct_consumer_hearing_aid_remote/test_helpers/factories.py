"""Payload factories — one per entity, request-input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for natural keys that must be globally unique."""
    return f"{next(_counter):04d}"


def create_state_policy_payload(**overrides) -> dict:
    payload = {
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "otc_sales_permitted": True,
        "telehealth_fitting_permitted": True,
        "min_age_years": TEST_DEFAULTS["MIN_AGE_YEARS"],
        "trial_period_days": TEST_DEFAULTS["TRIAL_PERIOD_DAYS"],
        "restocking_fee_mode": "FLAT_PCT",
        "restocking_fee_pct": TEST_DEFAULTS["RESTOCKING_FEE_PCT"],
        "restocking_fee_cap_cents": 0,
        "shipping_refundable": False,
        "referral_validity_days": TEST_DEFAULTS["REFERRAL_VALIDITY_DAYS"],
        "waiver_required": False,
        "max_loss_damage_claims": TEST_DEFAULTS["MAX_LOSS_DAMAGE_CLAIMS"],
    }
    payload.update(overrides)
    return payload


def create_patient_payload(state_policy_id: str, **overrides) -> dict:
    payload = {
        "state_policy_id": state_policy_id,
        "email": f"patient{unique_suffix()}@x.test",
        "full_name": "Test Patient",
        "age_years": 70,
    }
    payload.update(overrides)
    return payload


def create_provider_payload(**overrides) -> dict:
    payload = {
        "provider_type": "LICENSED_AUDIOLOGIST",
        "npi": f"100000{unique_suffix()}",
        "full_name": "Test Provider",
        "licensed_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
        "daily_capacity_minutes": TEST_DEFAULTS["DAILY_CAPACITY_MINUTES"],
        "buffer_minutes": TEST_DEFAULTS["BUFFER_MINUTES"],
    }
    payload.update(overrides)
    return payload


def screening_measurements_payload(**overrides) -> dict:
    payload = {
        "pure_tone_avg_db": 45.0,
        "asymmetry_db": 5.0,
        "self_reported_difficulty_score": 20,
        "speech_in_noise_pct": 70.0,
        "symptom_codes": [],
    }
    payload.update(overrides)
    return payload


def create_device_payload(**overrides) -> dict:
    payload = {
        "serial_number": f"SN-{unique_suffix()}",
        "model": TEST_DEFAULTS["MODEL"],
        "firmware_version": TEST_DEFAULTS["FIRMWARE_VERSION"],
    }
    payload.update(overrides)
    return payload


def create_inventory_pool_payload(**overrides) -> dict:
    payload = {
        "model": TEST_DEFAULTS["MODEL"],
        "dome_size": TEST_DEFAULTS["DOME_SIZE"],
        "tip_type": TEST_DEFAULTS["TIP_TYPE"],
    }
    payload.update(overrides)
    # The sku is the model, dome size and tip type joined by hyphens.
    payload.setdefault("sku", f"{payload['model']}-{payload['dome_size']}-{payload['tip_type']}")
    return payload


def create_device_order_payload(**overrides) -> dict:
    payload = {
        "model": TEST_DEFAULTS["MODEL"],
        "dome_size": TEST_DEFAULTS["DOME_SIZE"],
        "tip_type": TEST_DEFAULTS["TIP_TYPE"],
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "discount_cents": TEST_DEFAULTS["DISCOUNT_CENTS"],
        "accessory_subtotal_cents": TEST_DEFAULTS["ACCESSORY_SUBTOTAL_CENTS"],
        "shipping_cents": TEST_DEFAULTS["SHIPPING_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_fitting_session_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "session_type": "INITIAL_FIT",
        "scheduled_start_utc": "2026-08-03T10:00:00Z",
        "scheduled_end_utc": "2026-08-03T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_fit_exchange_payload(expected_device_order_version, **overrides) -> dict:
    payload = {
        "to_dome_size": "L",
        "to_tip_type": "CLOSED",
        "expected_device_order_version": expected_device_order_version,
    }
    payload.update(overrides)
    return payload


def create_repair_order_payload(device_id: str, **overrides) -> dict:
    payload = {"device_id": device_id, "fault_code": "NO_SOUND"}
    payload.update(overrides)
    return payload


def create_warranty_claim_payload(device_id: str, **overrides) -> dict:
    payload = {"device_id": device_id, "claim_kind": "DEFECT"}
    payload.update(overrides)
    return payload


def create_reimbursement_claim_payload(patient_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "subject_kind": "DEVICE_ORDER",
        "claimed_amount_cents": 100000,
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(patient_id: str, device_order_id: str, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "device_order_id": device_order_id,
        "plan_tier": TEST_DEFAULTS["PLAN_TIER"],
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_firmware_campaign_payload(**overrides) -> dict:
    payload = {
        "campaign_code": f"FW-{unique_suffix()}",
        "model": TEST_DEFAULTS["MODEL"],
        "from_version": TEST_DEFAULTS["FIRMWARE_VERSION"],
        "to_version": "4.1.0",
        "window_start_utc": "2026-08-01T00:00:00Z",
        "window_end_utc": "2026-08-31T00:00:00Z",
        "batch_size": 5,
        "max_concurrent_installs": 5,
        "is_mandatory_safety": True,
    }
    payload.update(overrides)
    return payload
