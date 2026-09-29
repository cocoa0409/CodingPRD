"""Payload factories — one per creating operation, input fields only."""
from typing import Optional

from .constants import TEST_DEFAULTS

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_show_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SHOW_NAME"],
        "federation_show_id": TEST_DEFAULTS["FEDERATION_SHOW_ID"],
        "venue": TEST_DEFAULTS["VENUE"],
        "competition_level": TEST_DEFAULTS["COMPETITION_LEVEL"],
        "start_utc": TEST_DEFAULTS["SHOW_START_UTC"],
        "end_utc": TEST_DEFAULTS["SHOW_END_UTC"],
        "entry_close_utc": TEST_DEFAULTS["ENTRY_CLOSE_UTC"],
        "prize_money_pool_cents": TEST_DEFAULTS["PRIZE_POOL_CENTS"],
        "stall_capacity": TEST_DEFAULTS["STALL_CAPACITY"],
        "stall_fee_cents": TEST_DEFAULTS["STALL_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_ring_payload(**overrides) -> dict:
    payload = {
        "name": "Ring A",
        "surface_type": "SAND_FIBER",
        "footing_condition_score": 100,
        "turnover_buffer_minutes": 10,
        "warmup_capacity_horses": 12,
    }
    payload.update(overrides)
    return payload


def create_division_payload(**overrides) -> dict:
    payload = {
        "name": "Open Jumper",
        "discipline": "JUMPER",
        "age_group": "OPEN",
        "min_jump_height_cm": 100,
        "max_jump_height_cm": 130,
        "division_share_bp": TEST_DEFAULTS["DIVISION_SHARE_BP"],
        "jumpoff_enabled": True,
    }
    payload.update(overrides)
    return payload


def create_class_payload(**overrides) -> dict:
    payload = {
        "class_number": 101,
        "name": "Open Jumper 1.20m",
        "jump_height_cm": TEST_DEFAULTS["JUMP_HEIGHT_CM"],
        "entry_fee_cents": TEST_DEFAULTS["ENTRY_FEE_CENTS"],
        "class_share_bp": TEST_DEFAULTS["CLASS_SHARE_BP"],
        "max_entries": TEST_DEFAULTS["MAX_ENTRIES"],
    }
    payload.update(overrides)
    return payload


def create_rider_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "federation_member_number": f"M-{1000 + n}",
        "full_name": f"Rider {n}",
        "membership_expires_on": TEST_DEFAULTS["MEMBERSHIP_EXPIRES_ON"],
        "trainer_name": f"Barn {n}",
    }
    payload.update(overrides)
    return payload


def create_horse_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "federation_registration_number": f"H-{2000 + n}",
        "name": f"Horse {n}",
        "owner_name": f"Owner {n}",
        "coggins_drawn_on": TEST_DEFAULTS["COGGINS_DRAWN_ON"],
    }
    payload.update(overrides)
    return payload


def create_official_payload(**overrides) -> dict:
    n = _next()
    payload = {
        "federation_official_id": f"OF-{3000 + n}",
        "full_name": f"Official {n}",
        "license_roles": ["JUDGE"],
        "license_level": 2,
        "licensed_disciplines": ["JUMPER"],
        "license_expires_on": TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
    }
    payload.update(overrides)
    return payload


def create_entry_payload(rider_id: str, horse_id: str, **overrides) -> dict:
    payload = {"rider_id": rider_id, "horse_id": horse_id, "requested_stall_count": 0}
    payload.update(overrides)
    return payload


def create_class_entry_payload(entry_id: str, class_id: str, **overrides) -> dict:
    payload = {"entry_id": entry_id, "class_id": class_id}
    payload.update(overrides)
    return payload


def create_ring_slot_payload(ring_id: str, class_id: str, start_utc: str,
                             expected_ring_version: int, **overrides) -> dict:
    payload = {
        "ring_id": ring_id,
        "class_id": class_id,
        "start_utc": start_utc,
        "expected_ring_version": expected_ring_version,
    }
    payload.update(overrides)
    return payload


def create_official_assignment_payload(official_id: str, slot_id: str,
                                       official_role: str = "JUDGE", **overrides) -> dict:
    payload = {"official_id": official_id, "slot_id": slot_id, "official_role": official_role}
    payload.update(overrides)
    return payload


def create_coverage_shift_payload(**overrides) -> dict:
    payload = {
        "coverage_type": "VETERINARIAN",
        "provider_name": "Ridgeline Equine Vets",
        "start_utc": TEST_DEFAULTS["COVERAGE_START_UTC"],
        "end_utc": TEST_DEFAULTS["COVERAGE_END_UTC"],
    }
    payload.update(overrides)
    return payload


def create_footing_maintenance_payload(**overrides) -> dict:
    payload = {
        "start_utc": "2026-09-10T18:00:00Z",
        "duration_minutes": 60,
        "new_footing_condition_score": 90,
    }
    payload.update(overrides)
    return payload


def create_results_payload(placings: list, actual_minutes: int, **overrides) -> dict:
    payload = {"placings": placings, "actual_minutes": actual_minutes}
    payload.update(overrides)
    return payload


def placing_row(class_entry_id: str, placing: int, round_seconds: float) -> dict:
    return {"class_entry_id": class_entry_id, "placing": placing, "round_seconds": round_seconds}


def create_compliance_case_payload(opened_by_official_id: str, case_type: str = "DRUG_TEST",
                                   sample_code: Optional[str] = "SMP-4001",
                                   welfare_rule_code: Optional[str] = None, **overrides) -> dict:
    payload = {"opened_by_official_id": opened_by_official_id, "case_type": case_type}
    if case_type == "DRUG_TEST" and sample_code is not None:
        payload["sample_code"] = sample_code
    if case_type == "WELFARE_CITATION":
        payload["welfare_rule_code"] = welfare_rule_code or "WR-12"
    payload.update(overrides)
    return payload


def acknowledgement_payload(standings_body: str, outcome: str,
                            body_reference: Optional[str] = None, **overrides) -> dict:
    payload = {"standings_body": standings_body, "outcome": outcome}
    if body_reference is not None:
        payload["body_reference"] = body_reference
    payload.update(overrides)
    return payload
