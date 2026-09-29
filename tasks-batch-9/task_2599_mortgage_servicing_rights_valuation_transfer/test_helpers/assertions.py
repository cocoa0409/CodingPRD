"""
Domain assertions and small readers for the transfer-desk test suite.

The helpers here fall into three groups: envelope readers that pull the payload
out of a response, arithmetic helpers that reproduce the documented rounding
conventions, and invariant checks for the two conserved quantities the desk
tracks (custodial funds and the holdback split).
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .types import JsonDict, JsonList

# ---------------------------------------------------------------------------
# Envelope readers
# ---------------------------------------------------------------------------


def data_of(response, expected_status: int = 200) -> JsonDict:
    """The `data` object of a successful response."""
    return validate_success(response, expected_status)


def rows_of(response) -> JsonList:
    """The row list of a successful collection response."""
    rows, _meta = validate_paginated(response)
    return rows


def meta_of(response) -> JsonDict:
    """The pagination metadata of a successful collection response."""
    _rows, meta = validate_paginated(response)
    return meta


def payload_of(response) -> JsonDict:
    """The payload of a response without asserting on its status code."""
    return get_success_data(response)


def find_row(rows: JsonList, row_id: str) -> JsonDict:
    """The single row in a collection carrying the given identifier."""
    matches = [row for row in rows if row.get("id") == row_id]
    assert len(matches) == 1, (
        f"expected exactly one row with id {row_id}, found {len(matches)} "
        f"among {[row.get('id') for row in rows]}"
    )
    return matches[0]


def ids_of(rows: JsonList) -> list:
    """Identifiers of a collection, in the order the collection returned them."""
    return [row["id"] for row in rows]


def has_row(rows: JsonList, row_id: str) -> bool:
    """Whether a collection contains a row with the given identifier."""
    return any(row.get("id") == row_id for row in rows)


# ---------------------------------------------------------------------------
# Arithmetic conventions
# ---------------------------------------------------------------------------


def round_half_up(value, places: int = 0):
    """Round a value half-away-from-zero to the given number of decimals."""
    quantum = Decimal(1).scaleb(-places)
    amount = Decimal(str(value))
    rounded = amount.copy_abs().quantize(quantum, rounding=ROUND_HALF_UP)
    if amount < 0:
        rounded = -rounded
    return int(rounded) if places == 0 else float(rounded)


def floor_cents(value) -> int:
    """Truncate a value downward to whole cents."""
    return int(Decimal(str(value)).quantize(Decimal(1), rounding=ROUND_FLOOR))


def bps_of_upb(value_cents: int, total_upb_cents: int) -> float:
    """The documented basis-point expression of a value against pool UPB."""
    if total_upb_cents == 0:
        return 0.00
    return round_half_up(Decimal(value_cents) * 10000 / Decimal(total_upb_cents), 2)


def price_at_bps(upb_cents: int, price_bps: int) -> int:
    """A single-rounding price over one UPB figure at a basis-point price."""
    return round_half_up(Decimal(upb_cents) * Decimal(price_bps) / Decimal(10000))


def pct_of(amount_cents: int, pct) -> int:
    """A percentage of a cent amount, rounded half-up to whole cents."""
    return round_half_up(Decimal(amount_cents) * Decimal(str(pct)) / Decimal(100))


# ---------------------------------------------------------------------------
# Field-shape assertions
# ---------------------------------------------------------------------------


def assert_identified(row: JsonDict) -> None:
    """A created row carries a well-formed identifier and creation stamp."""
    assert is_valid_uuid(row["id"]), f"id is not a uuid: {row['id']!r}"
    assert is_iso8601_timestamp(row["created_at"]), (
        f"created_at is not an ISO 8601 timestamp: {row['created_at']!r}"
    )


def assert_versioned(row: JsonDict, expected_version: int = None) -> None:
    """A row that carries the optimistic-concurrency version and update stamp."""
    assert_identified(row)
    assert isinstance(row["version"], int), (
        f"version is not an integer: {row['version']!r}"
    )
    assert is_iso8601_timestamp(row["updated_at"]), (
        f"updated_at is not an ISO 8601 timestamp: {row['updated_at']!r}"
    )
    if expected_version is not None:
        assert row["version"] == expected_version, (
            f"expected version {expected_version}, got {row['version']}"
        )


def assert_unversioned(row: JsonDict) -> None:
    """A row the documented model does not version or timestamp on update."""
    assert_identified(row)
    assert "version" not in row, (
        f"unexpected version field on an unversioned row: {row.get('version')!r}"
    )
    assert "updated_at" not in row, (
        "unexpected updated_at field on an unversioned row: "
        f"{row.get('updated_at')!r}"
    )


def assert_fields_present(row: JsonDict, *names: str) -> None:
    """Every named field is present on the row."""
    missing = [name for name in names if name not in row]
    assert not missing, f"missing fields {missing} on {sorted(row)}"


def assert_status(row: JsonDict, expected: str) -> None:
    """The row's lifecycle state is exactly the expected one."""
    assert row["status"] == expected, (
        f"expected status {expected}, got {row['status']}"
    )


# ---------------------------------------------------------------------------
# Conserved quantities
# ---------------------------------------------------------------------------


def assert_holdback_split(agreement: JsonDict, retained: int = None,
                          released: int = None, applied: int = None) -> None:
    """
    The holdback split adds back to the sized holdback, and optionally matches
    an expected retained / released / applied triple.
    """
    total = agreement["holdback_cents"]
    parts = (
        agreement["holdback_retained_cents"],
        agreement["holdback_released_cents"],
        agreement["holdback_applied_cents"],
    )
    assert sum(parts) == total, (
        f"holdback split {parts} does not add back to holdback_cents {total}"
    )
    if retained is not None:
        assert parts[0] == retained, (
            f"expected retained {retained}, got {parts[0]}"
        )
    if released is not None:
        assert parts[1] == released, (
            f"expected released {released}, got {parts[1]}"
        )
    if applied is not None:
        assert parts[2] == applied, f"expected applied {applied}, got {parts[2]}"


def assert_settlement_wire(agreement: JsonDict) -> None:
    """The settlement wire is the purchase price net of the sized holdback."""
    expected = agreement["purchase_price_cents"] - agreement["holdback_cents"]
    assert agreement["settlement_wire_cents"] == expected, (
        f"expected settlement_wire_cents {expected}, "
        f"got {agreement['settlement_wire_cents']}"
    )


def assert_custodial_funds(portfolio: JsonDict, expected_cents: int) -> None:
    """The portfolio's custodial funds total is exactly the expected figure."""
    assert portfolio["custodial_funds_total_cents"] == expected_cents, (
        f"expected custodial_funds_total_cents {expected_cents}, "
        f"got {portfolio['custodial_funds_total_cents']}"
    )


def loan_custodial_total(loans: JsonList) -> int:
    """Escrow plus suspense held on a set of loans."""
    return sum(
        loan["escrow_balance_cents"] + loan["suspense_balance_cents"]
        for loan in loans
    )


def assert_readiness(transfer: JsonDict, expected: str) -> None:
    """
    The transfer's readiness matches the expected value and is consistent with
    the three work-stream dimensions it is derived from.
    """
    assert transfer["readiness"] == expected, (
        f"expected readiness {expected}, got {transfer['readiness']}"
    )
    all_done = (
        transfer["notice_status"] == "NOTICES_ATTESTED"
        and transfer["data_status"] == "RECONCILED"
        and transfer["pipeline_status"] == "PIPELINE_TRANSFERRED"
    )
    assert transfer["readiness"] == ("READY" if all_done else "NOT_READY"), (
        "readiness disagrees with the three dimensions: "
        f"{transfer['notice_status']} / {transfer['data_status']} / "
        f"{transfer['pipeline_status']} -> {transfer['readiness']}"
    )


def assert_dimensions(transfer: JsonDict, notice: str = None, data: str = None,
                      pipeline: str = None) -> None:
    """The three transfer work streams stand where they are expected to."""
    if notice is not None:
        assert transfer["notice_status"] == notice, (
            f"expected notice_status {notice}, got {transfer['notice_status']}"
        )
    if data is not None:
        assert transfer["data_status"] == data, (
            f"expected data_status {data}, got {transfer['data_status']}"
        )
    if pipeline is not None:
        assert transfer["pipeline_status"] == pipeline, (
            f"expected pipeline_status {pipeline}, "
            f"got {transfer['pipeline_status']}"
        )


def assert_scenario_map(run: JsonDict, expected: JsonDict) -> None:
    """The shock-weighted run reports exactly the expected scenario values."""
    actual = run["scenario_values"]
    assert actual == expected, f"expected scenario_values {expected}, got {actual}"


def assert_stratum_breakdown(agreement: JsonDict, expected_labels: list) -> None:
    """
    The per-stratum audit trail names exactly the expected labels, and the
    per-stratum prices add back to the contractual purchase price.
    """
    breakdown = agreement["stratum_price_breakdown"]
    assert list(breakdown.keys()) == expected_labels, (
        f"expected strata {expected_labels} in ascending order, "
        f"got {list(breakdown.keys())}"
    )
    total = sum(entry["price_cents"] for entry in breakdown.values())
    assert total == agreement["purchase_price_cents"], (
        f"stratum prices sum to {total} but purchase_price_cents is "
        f"{agreement['purchase_price_cents']}"
    )
