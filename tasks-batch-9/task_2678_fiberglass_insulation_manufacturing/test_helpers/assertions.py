"""Domain assertions layered on the runner's generic assertion helpers.

Decimal scales come from PRD 2.5; common-field expectations from PRD 2.4.
"""

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    AREA_DP,
    BALE_VOLUME_DP,
    COST_DP,
    EMISSIONS_DP,
    MASS_DP,
    RATIO_DP,
)


def _dp(value: Any) -> int:
    """Number of decimal places in a JSON number rendered as a decimal."""
    d = Decimal(str(value))
    exponent = d.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def assert_scale(value: Any, decimal_places: int, label: str = "value") -> None:
    """Assert value carries at most `decimal_places` decimals (PRD 2.5)."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, (int, float)), (
        f"{label} must be a JSON number, got {type(value).__name__}: {value!r}"
    )
    assert _dp(value) <= decimal_places, (
        f"{label} must carry at most {decimal_places} decimals, got {value!r}"
    )


def assert_close(actual: Any, expected: float, decimal_places: int, label: str = "value") -> None:
    """Assert a numeric field equals expected when rounded to the PRD's scale."""
    assert actual is not None, f"{label} must not be null"
    quantum = Decimal(1).scaleb(-decimal_places)
    a = Decimal(str(actual)).quantize(quantum)
    e = Decimal(str(expected)).quantize(quantum)
    assert a == e, f"{label}: expected {e}, got {a} (raw {actual!r})"


def assert_mass(value: Any, expected: Optional[float] = None, label: str = "mass") -> None:
    assert_scale(value, MASS_DP, label)
    if expected is not None:
        assert_close(value, expected, MASS_DP, label)


def assert_area(value: Any, expected: Optional[float] = None, label: str = "area") -> None:
    assert_scale(value, AREA_DP, label)
    if expected is not None:
        assert_close(value, expected, AREA_DP, label)


def assert_ratio(value: Any, expected: Optional[float] = None, label: str = "ratio") -> None:
    assert_scale(value, RATIO_DP, label)
    if expected is not None:
        assert_close(value, expected, RATIO_DP, label)


def assert_emissions(value: Any, expected: Optional[float] = None, label: str = "emissions") -> None:
    assert_scale(value, EMISSIONS_DP, label)
    if expected is not None:
        assert_close(value, expected, EMISSIONS_DP, label)


def assert_bale_volume(value: Any, expected: Optional[float] = None, label: str = "compressed_bale_volume_ft3") -> None:
    assert_scale(value, BALE_VOLUME_DP, label)
    if expected is not None:
        assert_close(value, expected, BALE_VOLUME_DP, label)


def assert_per_sqft_cost(value: Any, expected: Optional[float] = None, label: str = "cost_per_sqft") -> None:
    assert_scale(value, COST_DP, label)
    if expected is not None:
        assert_close(value, expected, COST_DP, label)


# --- Common fields ------------------------------------------------------------


def assert_versioned_entity(entity: Dict[str, Any], label: str = "entity") -> None:
    """id/created_at/updated_at/version on every mutable entity (PRD 2.4)."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}.created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{label}.updated_at must be ISO 8601, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), (
        f"{label}.version must be an integer, got {entity.get('version')!r}"
    )


def assert_immutable_entity(entity: Dict[str, Any], label: str = "entity") -> None:
    """id/created_at only - no updated_at and no version (PRD 2.4)."""
    assert is_valid_uuid(entity.get("id")), f"{label}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}.created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert "updated_at" not in entity, f"{label} must not carry updated_at"
    assert "version" not in entity, f"{label} must not carry version"


def assert_no_prefix_id(value: Any, label: str = "id") -> None:
    """PRD 2.4: ids are bare UUIDs with no entity prefix."""
    assert is_valid_uuid(value), f"{label} must be a bare UUID, got {value!r}"


# --- Collections -------------------------------------------------------------


def ids_of(rows: Iterable[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


def assert_created_at_ascending(rows: List[Dict[str, Any]], label: str = "rows") -> None:
    """PRD 2.3 default ordering."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"{label} must be ordered by created_at ascending, got {stamps}"


def find_by_id(rows: Iterable[Dict[str, Any]], entity_id: str) -> Dict[str, Any]:
    for row in rows:
        if row.get("id") == entity_id:
            return row
    raise AssertionError(f"no row with id {entity_id!r} in collection")


def assert_field_equals(entity: Dict[str, Any], field: str, expected: Any) -> None:
    assert entity.get(field) == expected, (
        f"{field}: expected {expected!r}, got {entity.get(field)!r}"
    )
