"""Request payload factories.

Each factory returns a valid payload for one write endpoint with sensible
defaults drawn from the PRD's stated ranges, and accepts keyword overrides so a
test can vary exactly the one field it cares about. Passing ``None`` for an
optional field omits it; to omit a required field for a shape test, pop the key
from the returned dict.
"""

from typing import Any, Dict, List, Optional

from .constants import BOX_SIZE
from .types import Breed, LabSubjectType, LabTestCode, UnitType

# ---------------------------------------------------------------------------
# Configuration (PRD 3.1)
# ---------------------------------------------------------------------------


def flock_program_payload(
    code: str = "P1",
    breed: str = Breed.ROSS_308.value,
    stimulation_week: int = 21,
    lighting_steps: Optional[List[Dict[str, Any]]] = None,
    feed_steps: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "breed": breed,
        "stimulation_week": stimulation_week,
        "lighting_steps": lighting_steps
        if lighting_steps is not None
        else [
            {"age_weeks": 21, "photoperiod_hours": 12.0},
            {"age_weeks": 24, "photoperiod_hours": 14.0},
            {"age_weeks": 30, "photoperiod_hours": 16.0},
        ],
        "feed_steps": feed_steps
        if feed_steps is not None
        else [
            {"age_weeks": 21, "feed_grams_per_hen_day": 150.0},
            {"age_weeks": 26, "feed_grams_per_hen_day": 168.0},
        ],
    }
    payload.update(overrides)
    return payload


def incubation_profile_payload(
    code: str = "PR1",
    breed: str = Breed.ROSS_308.value,
    transfer_hours: int = 456,
    total_hours: int = 504,
    stages: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "breed": breed,
        "transfer_hours": transfer_hours,
        "total_hours": total_hours,
        "stages": stages
        if stages is not None
        else [
            {"from_hour": 0, "to_hour": 240, "temp_c": 37.8, "humidity_pct": 55.0},
            {"from_hour": 240, "to_hour": 456, "temp_c": 37.5, "humidity_pct": 52.0},
            {"from_hour": 456, "to_hour": 504, "temp_c": 36.9, "humidity_pct": 65.0},
        ],
    }
    payload.update(overrides)
    return payload


def incubation_unit_payload(
    code: str = "U1",
    unit_type: str = UnitType.SETTER.value,
    capacity_eggs: int = 20000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "unit_type": unit_type,
        "capacity_eggs": capacity_eggs,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Breeder flocks (PRD 3.2)
# ---------------------------------------------------------------------------


def breeder_flock_payload(
    program_id: str,
    code: str = "F1",
    breed: str = Breed.ROSS_308.value,
    house_code: str = "H1",
    hatch_date: str = "2026-01-05T00:00:00Z",
    placed_at: str = "2026-05-01T00:00:00Z",
    hen_count: int = 9000,
    source_flock_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "program_id": program_id,
        "breed": breed,
        "house_code": house_code,
        "hatch_date": hatch_date,
        "placed_at": placed_at,
        "hen_count": hen_count,
    }
    if source_flock_id is not None:
        payload["source_flock_id"] = source_flock_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Egg lots (PRD 3.4)
# ---------------------------------------------------------------------------


def egg_lot_payload(
    flock_id: str,
    collected_at: str = "2026-07-30T00:00:00Z",
    collected_count: int = 10500,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "flock_id": flock_id,
        "collected_at": collected_at,
        "collected_count": collected_count,
    }
    payload.update(overrides)
    return payload


def grade_payload(
    grade_a_count: int = 10000,
    cracked_count: int = 300,
    dirty_count: int = 150,
    small_count: int = 50,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "grade_a_count": grade_a_count,
        "cracked_count": cracked_count,
        "dirty_count": dirty_count,
        "small_count": small_count,
    }
    payload.update(overrides)
    return payload


def store_payload(storage_temp_c: float = 15.0, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"storage_temp_c": storage_temp_c}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Setter loads (PRD 3.5)
# ---------------------------------------------------------------------------


def setter_load_payload(
    unit_id: str,
    profile_id: str,
    planned_set_at: str = "2026-08-01T18:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "profile_id": profile_id,
        "planned_set_at": planned_set_at,
    }
    payload.update(overrides)
    return payload


def draw_payload(
    egg_lot_id: str,
    eggs_taken: int,
    expected_egg_lot_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "egg_lot_id": egg_lot_id,
        "eggs_taken": eggs_taken,
        "expected_egg_lot_version": expected_egg_lot_version,
    }
    payload.update(overrides)
    return payload


def environment_reading_payload(
    recorded_at: str,
    temp_c: float = 37.8,
    humidity_pct: float = 55.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recorded_at": recorded_at,
        "temp_c": temp_c,
        "humidity_pct": humidity_pct,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Chick processing (PRD 3.7)
# ---------------------------------------------------------------------------


def sexing_payload(
    male_count: int = 4600,
    female_count: int = 4700,
    unsexed_count: int = 0,
    sexing_cull_count: int = 100,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "male_count": male_count,
        "female_count": female_count,
        "unsexed_count": unsexed_count,
        "sexing_cull_count": sexing_cull_count,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Grower farms and placement orders (PRD 3.3, 3.8)
# ---------------------------------------------------------------------------


def grower_farm_payload(
    code: str = "FM1",
    operator_user_id: str = "u_grower_1",
    capacity_chicks: int = 20000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code,
        "operator_user_id": operator_user_id,
        "capacity_chicks": capacity_chicks,
    }
    payload.update(overrides)
    return payload


def placement_order_payload(
    farm_id: str,
    requested_breed: str = Breed.ROSS_308.value,
    requested_placement_date: str = "2026-08-22T00:00:00Z",
    requested_chicks: int = 5000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "farm_id": farm_id,
        "requested_breed": requested_breed,
        "requested_placement_date": requested_placement_date,
        "requested_chicks": requested_chicks,
    }
    payload.update(overrides)
    return payload


def whole_boxes(chicks: int) -> int:
    """The whole-box figure for ``chicks`` (PRD 3.8: never splits a box)."""
    return (chicks // BOX_SIZE) * BOX_SIZE


# ---------------------------------------------------------------------------
# Laboratory tests (PRD 3.3)
# ---------------------------------------------------------------------------


def lab_test_payload(
    subject_id: str,
    subject_type: str = LabSubjectType.BREEDER_FLOCK.value,
    test_code: str = LabTestCode.SALMONELLA_PULLORUM.value,
    collected_at: str = "2026-07-20T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "test_code": test_code,
        "collected_at": collected_at,
    }
    payload.update(overrides)
    return payload
