"""Payload factories — one per creatable resource, client-supplied fields only."""
import itertools

from .constants import REFERENCE_SPEC, TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so human-readable codes stay unique inside one test."""
    return f"{next(_counter):04d}"


def create_grower_payload(**overrides) -> dict:
    n = unique_suffix()
    payload = {
        "name": f"Test Vineyards {n}",
        "license_number": f"CA-LIC-{n}",
        "region_code": TEST_DEFAULTS["region_code"],
    }
    payload.update(overrides)
    return payload


def create_vineyard_block_payload(grower_id: str, **overrides) -> dict:
    n = unique_suffix()
    payload = {
        "grower_id": grower_id,
        "block_code": f"BLK-{n}",
        "varietal": TEST_DEFAULTS["varietal"],
        "acres": TEST_DEFAULTS["acres"],
        "expected_yield_tons_per_acre": TEST_DEFAULTS["expected_yield_tons_per_acre"],
        "ava_code": TEST_DEFAULTS["ava_code"],
    }
    payload.update(overrides)
    return payload


def create_quality_spec_payload(**overrides) -> dict:
    """The reference specification: the five mandatory thresholds only, so every
    optional threshold falls back to its documented default."""
    payload = {
        "spec_code": f"SPEC-{unique_suffix()}",
        "min_brix_accept": REFERENCE_SPEC["min_brix_accept"],
        "brix_bonus_start": REFERENCE_SPEC["brix_bonus_start"],
        "brix_penalty_start": REFERENCE_SPEC["brix_penalty_start"],
        "rot_rejection_pct": REFERENCE_SPEC["rot_rejection_pct"],
    }
    payload.update(overrides)
    return payload


def single_installment_plan() -> list:
    return [
        {
            "installment_no": 1,
            "pct_of_settlement": 100.0,
            "due_offset_days": 30,
            "lien_protected": True,
        }
    ]


def two_installment_plan(first_pct: float = 60.0, second_pct: float = 40.0) -> list:
    return [
        {
            "installment_no": 1,
            "pct_of_settlement": first_pct,
            "due_offset_days": 30,
            "lien_protected": True,
        },
        {
            "installment_no": 2,
            "pct_of_settlement": second_pct,
            "due_offset_days": 60,
            "lien_protected": True,
        },
    ]


def three_installment_plan(pcts=(45.5, 27.25, 27.25), offsets=(30, 60, 90)) -> list:
    return [
        {
            "installment_no": i + 1,
            "pct_of_settlement": pcts[i],
            "due_offset_days": offsets[i],
            "lien_protected": True,
        }
        for i in range(3)
    ]


def create_grape_contract_payload(grower_id: str, quality_spec_id: str, **overrides) -> dict:
    payload = {
        "grower_id": grower_id,
        "quality_spec_id": quality_spec_id,
        "contract_code": f"GC-{unique_suffix()}",
        "contract_basis": "TONNAGE",
        "committed_tons": TEST_DEFAULTS["committed_tons"],
        "base_price_per_ton_cents": TEST_DEFAULTS["base_price_per_ton_cents"],
        "over_delivery_policy": "ACCEPT_AT_CONTRACT",
        "term_start_vintage": TEST_DEFAULTS["term_start_vintage"],
        "term_end_vintage": TEST_DEFAULTS["term_end_vintage"],
        "installment_plan": single_installment_plan(),
    }
    payload.update(overrides)
    return payload


def create_allocation_payload(contract_id: str, block_id: str, **overrides) -> dict:
    payload = {"contract_id": contract_id, "block_id": block_id}
    payload.update(overrides)
    return payload


def create_lane_payload(**overrides) -> dict:
    payload = {
        "lane_code": f"LN-{unique_suffix()}",
        "daily_capacity_tons": TEST_DEFAULTS["daily_capacity_tons"],
    }
    payload.update(overrides)
    return payload


def create_sampling_crew_payload(**overrides) -> dict:
    payload = {
        "crew_code": f"CRW-{unique_suffix()}",
        "region_code": TEST_DEFAULTS["region_code"],
    }
    payload.update(overrides)
    return payload


def create_sampling_visit_payload(
    contract_id: str, block_id: str, crew_id: str, window_start: str, window_end: str, **overrides
) -> dict:
    payload = {
        "contract_id": contract_id,
        "block_id": block_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def record_sampling_visit_payload(**overrides) -> dict:
    payload = {
        "measured_brix": 24.5,
        "measured_ta_gl": 6.5,
        "measured_ph": 3.55,
        "measured_rot_pct": 1.0,
    }
    payload.update(overrides)
    return payload


def create_pick_call_payload(
    contract_id: str, block_id: str, target_pick_at: str, estimated_tons: float, **overrides
) -> dict:
    payload = {
        "contract_id": contract_id,
        "block_id": block_id,
        "target_pick_at": target_pick_at,
        "estimated_tons": estimated_tons,
    }
    payload.update(overrides)
    return payload


def create_delivery_appointment_payload(
    pick_call_id: str, lane_id: str, window_start: str, window_end: str, planned_tons: float, **overrides
) -> dict:
    payload = {
        "pick_call_id": pick_call_id,
        "lane_id": lane_id,
        "window_start": window_start,
        "window_end": window_end,
        "planned_tons": planned_tons,
    }
    payload.update(overrides)
    return payload


def create_weigh_tag_payload(
    appointment_id: str, block_id: str, gross_weight_lbs: int, expected_appointment_version: int, **overrides
) -> dict:
    payload = {
        "appointment_id": appointment_id,
        "block_id": block_id,
        "gross_weight_lbs": gross_weight_lbs,
        "expected_appointment_version": expected_appointment_version,
    }
    payload.update(overrides)
    return payload


def tare_payload(tare_weight_lbs: int, **overrides) -> dict:
    payload = {"tare_weight_lbs": tare_weight_lbs}
    payload.update(overrides)
    return payload


def create_grading_payload(expected_weigh_tag_version: int, **overrides) -> dict:
    payload = {
        "brix": 24.0,
        "ta_gl": 6.5,
        "ph": 3.55,
        "rot_pct": 2.0,
        "mog_pct": 1.0,
        "expected_weigh_tag_version": expected_weigh_tag_version,
    }
    payload.update(overrides)
    return payload
