"""
Domain assertions and typed reads.

The programme states every amount in whole cents and every rate in basis points,
so the assertions here compare integers exactly — a "close enough" money
comparison would hide precisely the rounding faults these tests look for.

Two entities — the program year and the investment option — carry only `id` and
`created_at`; every other row also carries `updated_at` and a `version` that
starts at 1 and rises by exactly one per write. `assert_common_fields` and
`assert_config_fields` express that split.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .api_client import ApiClient
from .test_users import ADMIN, RECORDKEEPER
from .types import ApiResponse, Headers, JsonDict, JsonList


# ---------------------------------------------------------------------------
# Exact integer comparisons
# ---------------------------------------------------------------------------
def assert_cents(actual: Any, expected: int, label: str = "amount") -> None:
    """Assert a cents field equals `expected` exactly."""
    assert actual is not None, f"{label} is missing"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of cents, got {actual!r}"
    )
    assert actual == expected, f"{label}: expected {expected} cents, got {actual}"


def assert_basis_points(actual: Any, expected: int, label: str = "rate") -> None:
    """Assert a basis-point field equals `expected` exactly."""
    assert actual is not None, f"{label} is missing"
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        f"{label} must be an integer number of basis points, got {actual!r}"
    )
    assert actual == expected, (
        f"{label}: expected {expected} basis points, got {actual}"
    )


def assert_amounts(row: JsonDict, expectations: Dict[str, int],
                   label: str = "row") -> None:
    """Assert several cents fields of one row in a single call."""
    for field_name, expected in expectations.items():
        assert_cents(row.get(field_name), expected, f"{label}.{field_name}")


def assert_fields(row: JsonDict, expectations: Dict[str, Any],
                  label: str = "row") -> None:
    """Assert several fields of one row hold exactly these values."""
    for field_name, expected in expectations.items():
        assert field_name in row, f"{label}.{field_name} is missing"
        assert row[field_name] == expected, (
            f"{label}.{field_name}: expected {expected!r}, got {row[field_name]!r}"
        )


def assert_nulls(row: JsonDict, field_names: List[str], label: str = "row") -> None:
    """Assert every named field is present and null."""
    for field_name in field_names:
        assert field_name in row, f"{label}.{field_name} is missing"
        assert row[field_name] is None, (
            f"{label}.{field_name} should be null, got {row[field_name]!r}"
        )


# ---------------------------------------------------------------------------
# Common properties
# ---------------------------------------------------------------------------
def assert_common_fields(row: JsonDict, expected_version: Optional[int] = None,
                         label: str = "row") -> None:
    """
    Assert the four properties a versioned row carries: a bare UUID `id`,
    ISO 8601 `created_at` and `updated_at`, and an integer `version`.
    """
    assert is_valid_uuid(row.get("id", "")), (
        f"{label}.id is not a bare UUID: {row.get('id')!r}"
    )
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"{label}.created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(row.get("updated_at", "")), (
        f"{label}.updated_at is not ISO 8601: {row.get('updated_at')!r}"
    )
    assert isinstance(row.get("version"), int), (
        f"{label}.version must be an integer, got {row.get('version')!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"{label}.version: expected {expected_version}, got {row['version']}"
        )


def assert_config_fields(row: JsonDict, label: str = "row") -> None:
    """
    Assert a configuration row carries only `id` and `created_at` from the common
    properties — no `updated_at` and no `version`.
    """
    assert is_valid_uuid(row.get("id", "")), (
        f"{label}.id is not a bare UUID: {row.get('id')!r}"
    )
    assert is_iso8601_timestamp(row.get("created_at", "")), (
        f"{label}.created_at is not ISO 8601: {row.get('created_at')!r}"
    )
    assert "updated_at" not in row, f"{label} must not carry updated_at"
    assert "version" not in row, f"{label} must not carry version"


def assert_fields_present(row: JsonDict, field_names: List[str],
                          label: str = "row") -> None:
    """Assert every named field is present in the row."""
    missing = [name for name in field_names if name not in row]
    assert not missing, f"{label} is missing fields: {missing}"


def assert_envelope_meta(response: ApiResponse) -> JsonDict:
    """Assert the response envelope's meta block, returning it."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be str"
    assert meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        "meta.api_request_timestamp is not ISO 8601: "
        f"{meta.get('api_request_timestamp')!r}"
    )
    return meta


# ---------------------------------------------------------------------------
# Fund-level conservation
# ---------------------------------------------------------------------------
def assert_fund_balances(account: JsonDict,
                         expected: List[Dict[str, Any]]) -> None:
    """
    Assert the account's fund split matches `expected` entry for entry, in order,
    and that the entries sum to exactly `balance_cents`.
    """
    actual = account.get("fund_balances")
    assert isinstance(actual, list), (
        f"fund_balances must be an array, got {actual!r}"
    )
    assert len(actual) == len(expected), (
        f"fund_balances: expected {len(expected)} entries, got {len(actual)}: {actual}"
    )
    for index, (got, want) in enumerate(zip(actual, expected)):
        for key, value in want.items():
            assert got.get(key) == value, (
                f"fund_balances[{index}].{key}: expected {value!r}, "
                f"got {got.get(key)!r}"
            )
    total = sum(entry.get("balance_cents", 0) for entry in actual)
    assert total == account["balance_cents"], (
        f"fund_balances sum to {total} but balance_cents is "
        f"{account['balance_cents']}"
    )


def assert_fund_balances_sum(account: JsonDict) -> None:
    """Assert the fund split adds up to the account balance to the cent."""
    entries = account.get("fund_balances") or []
    total = sum(entry.get("balance_cents", 0) for entry in entries)
    assert total == account["balance_cents"], (
        f"fund_balances sum to {total} but balance_cents is "
        f"{account['balance_cents']}"
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def read_employer(api: ApiClient, employer_id: str,
                  headers: Headers = ADMIN) -> JsonDict:
    """Fetch an employer."""
    return validate_success(api.get_employer(employer_id, headers))


def read_exemption(api: ApiClient, exemption_id: str,
                   headers: Headers = ADMIN) -> JsonDict:
    """Fetch an exemption certification."""
    return validate_success(api.get_exemption_certification(exemption_id, headers))


def read_participant(api: ApiClient, participant_id: str,
                     headers: Headers = ADMIN) -> JsonDict:
    """Fetch a saver."""
    return validate_success(api.get_participant(participant_id, headers))


def read_enrollment(api: ApiClient, enrollment_id: str,
                    headers: Headers = ADMIN) -> JsonDict:
    """Fetch an enrolment."""
    return validate_success(api.get_enrollment(enrollment_id, headers))


def read_account(api: ApiClient, account_id: str,
                 headers: Headers = ADMIN) -> JsonDict:
    """Fetch a participant account."""
    return validate_success(api.get_participant_account(account_id, headers))


def read_remittance(api: ApiClient, remittance_id: str,
                    headers: Headers = ADMIN) -> JsonDict:
    """Fetch a payroll remittance batch."""
    return validate_success(api.get_payroll_remittance(remittance_id, headers))


def read_excess_case(api: ApiClient, case_id: str,
                     headers: Headers = ADMIN) -> JsonDict:
    """Fetch an excess contribution case."""
    return validate_success(api.get_excess_case(case_id, headers))


def read_penalty(api: ApiClient, penalty_id: str,
                 headers: Headers = ADMIN) -> JsonDict:
    """Fetch a penalty assessment."""
    return validate_success(api.get_penalty_assessment(penalty_id, headers))


def read_transfer(api: ApiClient, transfer_id: str,
                  headers: Headers = ADMIN) -> JsonDict:
    """Fetch a portability transfer."""
    return validate_success(api.get_portability_transfer(transfer_id, headers))


def read_investment_option(api: ApiClient, option_id: str,
                           headers: Headers = ADMIN) -> JsonDict:
    """Fetch one fund menu option."""
    return validate_success(api.get_investment_option(option_id, headers))


def read_remittance_line(api: ApiClient, remittance_id: str, line_id: str,
                         headers: Headers = RECORDKEEPER) -> JsonDict:
    """Fetch one line of a batch through the batch's line listing."""
    rows, _ = validate_paginated(api.list_remittance_lines(remittance_id, headers))
    return find_row(rows, id=line_id)


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------
def assert_total_count(response: ApiResponse, expected: int,
                       label: str = "collection") -> JsonList:
    """Assert a listing reports `expected` matching rows. Returns the page."""
    rows, meta = validate_paginated(response)
    assert meta["total_count"] == expected, (
        f"{label}: expected total_count {expected}, got {meta['total_count']}"
    )
    return rows


def assert_pagination_meta(response: ApiResponse, limit: int, offset: int,
                           total_count: int, has_more: bool,
                           label: str = "collection") -> JsonList:
    """Assert all four pagination counters of one page."""
    rows, meta = validate_paginated(response)
    assert meta["limit"] == limit, (
        f"{label}: expected limit {limit}, got {meta['limit']}"
    )
    assert meta["offset"] == offset, (
        f"{label}: expected offset {offset}, got {meta['offset']}"
    )
    assert meta["total_count"] == total_count, (
        f"{label}: expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"{label}: expected has_more {has_more}, got {meta['has_more']}"
    )
    return rows


def parse_instant(value: str) -> datetime:
    """Read an ISO 8601 UTC instant, with or without fractional digits.

    The PRD renders instants in a UTC form with three fractional digits, but a
    caller may hand the clock setter a whole-second instant. Comparing parsed
    instants keeps an assertion about *which instant* free of any assumption
    about how many fractional digits the response prints.
    """
    assert isinstance(value, str) and value, f"expected an ISO instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = (parsed - parsed.utcoffset()).replace(tzinfo=None)
    return parsed


def assert_created_at_ascending(rows: JsonList, label: str = "collection") -> None:
    """Assert a page is ordered by creation instant, oldest first."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"{label} is not ordered by created_at ascending: {stamps}"
    )


def assert_ids_in_order(rows: JsonList, expected_ids: List[str],
                        label: str = "collection") -> None:
    """Assert the page carries exactly these identifiers, in this order."""
    actual = [row["id"] for row in rows]
    assert actual == expected_ids, (
        f"{label}: expected ids {expected_ids}, got {actual}"
    )


def collect_ids(rows: JsonList) -> List[str]:
    """Extract the identifiers of a page of rows."""
    return [row["id"] for row in rows]


def find_row(rows: JsonList, **match: Any) -> JsonDict:
    """Return the single row matching every keyword condition."""
    hits = [row for row in rows
            if all(row.get(key) == value for key, value in match.items())]
    assert len(hits) == 1, (
        f"Expected exactly one row matching {match}, found {len(hits)}"
    )
    return hits[0]


def data_of(response: ApiResponse) -> JsonDict:
    """Validate a successful write and return its data object."""
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Arithmetic mirrors — expressed the way the programme documents them
# ---------------------------------------------------------------------------
def round_half_up(numerator: int, denominator: int = 10000) -> int:
    """
    Divide and round half away from zero, the programme's single rounding rule
    for turning a basis-point product into whole cents.
    """
    assert denominator > 0
    if numerator >= 0:
        return (numerator * 2 + denominator) // (denominator * 2)
    return -((-numerator * 2 + denominator) // (denominator * 2))


def apply_bp(amount_cents: int, rate_bp: int) -> int:
    """Apply a basis-point rate to a cents amount, rounding half up once."""
    return round_half_up(amount_cents * rate_bp)
