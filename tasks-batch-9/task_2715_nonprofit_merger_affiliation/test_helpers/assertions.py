"""Domain assertion helpers.

These wrap the framework primitives with the precision and shape rules stated
in the PRD: integer cents, two-decimal and four-decimal derived figures, the
common-field sets, and the two conserved quantities.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

Json = Dict[str, Any]


# ----------------------------------------------------------------------
# Numeric shape
# ----------------------------------------------------------------------
def assert_integer_cents(value: Any, field: str) -> None:
    """A money field is an integer number of cents, never a float or string."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {type(value).__name__}: {value!r}"
    )


def assert_decimal_places(value: Any, places: int, field: str) -> None:
    """A derived ratio or score carries exactly `places` decimal places of precision."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {type(value).__name__}: {value!r}"
    )
    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    assert Decimal(str(value)) == rounded, (
        f"{field} must carry {places} decimal places, got {value!r}"
    )


def assert_money_equals(actual: Any, expected: int, field: str) -> None:
    assert_integer_cents(actual, field)
    assert actual == expected, f"{field} expected {expected} cents, got {actual}"


def assert_decimal_equals(actual: Any, expected: float, places: int, field: str) -> None:
    """Compare a derived decimal figure at the PRD's declared precision."""
    assert_decimal_places(actual, places, field)
    quantum = Decimal(1).scaleb(-places)
    a = Decimal(str(actual)).quantize(quantum, rounding=ROUND_HALF_UP)
    e = Decimal(str(expected)).quantize(quantum, rounding=ROUND_HALF_UP)
    assert a == e, f"{field} expected {expected} got {actual}"


def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def monthly_expense_cents(annual_expense_cents: int) -> int:
    """The PRD's per-organization divide-by-twelve, round-half-up step."""
    return int(round_half_up(Decimal(annual_expense_cents) / Decimal(12), 0))


# ----------------------------------------------------------------------
# Common fields
# ----------------------------------------------------------------------
def assert_full_common_fields(entity: Json, name: str = "entity") -> None:
    """id, created_at, updated_at and version, per the common-field rule."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{name}.created_at must be ISO-8601, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{name}.updated_at must be ISO-8601, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int), f"{name}.version must be an integer"


def assert_create_only_common_fields(entity: Json, name: str = "entity") -> None:
    """An immutable snapshot carries only id and created_at: no updated_at, no version."""
    assert is_valid_uuid(entity.get("id")), f"{name}.id must be a UUID, got {entity.get('id')!r}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{name}.created_at must be ISO-8601, got {entity.get('created_at')!r}"
    )
    assert "updated_at" not in entity, f"{name} must not carry updated_at"
    assert "version" not in entity, f"{name} must not carry version"


def assert_three_fractional_digits(value: Any, field: str) -> None:
    """Timestamps render exactly three fractional digits and a Z suffix."""
    assert isinstance(value, str), f"{field} must be a string timestamp, got {value!r}"
    assert value.endswith("Z"), f"{field} must end with Z, got {value!r}"
    assert "." in value, f"{field} must carry fractional seconds, got {value!r}"
    frac = value.split(".")[1][:-1]
    assert len(frac) == 3, f"{field} must carry exactly three fractional digits, got {value!r}"


# ----------------------------------------------------------------------
# Conserved quantities
# ----------------------------------------------------------------------
def assert_seat_ledger_conserved(dossier: Json) -> None:
    """reserved_seat_pool plus certified allocated seats equals combined_board_seats."""
    pool = dossier["reserved_seat_pool"]
    allocated = dossier["certified_allocated_seats_total"]
    total = dossier["seat_ledger_total"]
    combined = dossier["combined_board_seats"]
    assert pool + allocated == total, (
        f"seat_ledger_total {total} must equal reserved_seat_pool {pool} "
        f"plus certified_allocated_seats_total {allocated}"
    )
    assert total == combined, (
        f"seat_ledger_total {total} must equal combined_board_seats {combined}"
    )


def assert_pair_corpus_equals(dossier: Json, expected: int) -> None:
    """The pair restricted corpus is the conserved quantity of transfer and unwind."""
    assert_money_equals(
        dossier["pair_restricted_corpus_cents"], expected, "pair_restricted_corpus_cents"
    )


# ----------------------------------------------------------------------
# Field-value convenience
# ----------------------------------------------------------------------
def assert_field(entity: Json, field: str, expected: Any) -> None:
    assert field in entity, f"expected field {field} on {sorted(entity.keys())}"
    assert entity[field] == expected, (
        f"{field} expected {expected!r}, got {entity[field]!r}"
    )


def assert_null(entity: Json, field: str) -> None:
    assert entity.get(field, None) is None, f"{field} must be null, got {entity.get(field)!r}"


def assert_version_is(entity: Json, expected: int, name: str = "entity") -> None:
    assert entity.get("version") == expected, (
        f"{name}.version expected {expected}, got {entity.get('version')}"
    )


def assert_status(entity: Json, expected: str, field: str = "status") -> None:
    assert entity.get(field) == expected, (
        f"{field} expected {expected!r}, got {entity.get(field)!r}"
    )


def find_by_id(rows: Any, row_id: str) -> Optional[Json]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
