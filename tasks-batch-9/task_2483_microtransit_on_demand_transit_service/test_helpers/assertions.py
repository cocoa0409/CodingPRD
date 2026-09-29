"""Domain assertion helpers.

These wrap the repeated shape checks so the test bodies can stay focused on the
behaviour under test: system-field presence per resource kind, exact logical
instant comparison, and the ledger's net-amount invariant.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ─── System-field shape ────────────────────────────────────────────────────


def assert_versioned_entity(entity: dict) -> None:
    """A versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]


def assert_ledger_row_shape(row: dict) -> None:
    """A fare transaction carries only id and created_at as system fields: it
    has no updated_at field and no version field at all."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']}"
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert "updated_at" not in row, "fare transaction must not expose updated_at"
    assert "version" not in row, "fare transaction must not expose version"


def assert_version_advanced(before: dict, after: dict, by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )


def assert_version_unchanged(before: dict, after: dict) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )


# ─── Instants ──────────────────────────────────────────────────────────────


def normalize_instant(value):
    """Reduce an ISO-8601 UTC instant to second precision with a Z suffix so an
    exact-instant comparison is not defeated by optional fractional digits."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    elif "+" in text[10:]:
        text = text[: text.index("+", 10)]
    if "." in text:
        text = text[: text.index(".")]
    return text + "Z"


def assert_instant_equals(actual, expected) -> None:
    assert normalize_instant(actual) == normalize_instant(expected), (
        f"expected instant {expected}, got {actual}"
    )


# ─── Field bundles ─────────────────────────────────────────────────────────


def assert_fields(entity: dict, **expected) -> None:
    """Assert a bundle of exact field values, reporting every mismatch at once."""
    mismatches = []
    for field, want in expected.items():
        assert field in entity, f"field {field!r} missing from response"
        got = entity[field]
        if want is None or got is None:
            ok = got is want
        else:
            ok = got == want
        if not ok:
            mismatches.append(f"{field}: expected {want!r}, got {got!r}")
    assert not mismatches, "; ".join(mismatches)


def assert_null_fields(entity: dict, *fields) -> None:
    for field in fields:
        assert field in entity, f"field {field!r} missing from response"
        assert entity[field] is None, f"{field} should be null, got {entity[field]!r}"


# ─── Trip / assignment / block / report shorthands ─────────────────────────


def assert_trip_state(trip: dict, status: str, fare_status: str = None) -> None:
    assert trip["status"] == status, (
        f"expected trip status {status}, got {trip['status']}"
    )
    if fare_status is not None:
        assert trip["fare_status"] == fare_status, (
            f"expected fare status {fare_status}, got {trip['fare_status']}"
        )


def assert_assignment_state(assignment: dict, state: str) -> None:
    assert assignment["state"] == state, (
        f"expected assignment state {state}, got {assignment['state']}"
    )


def assert_block_state(block: dict, state: str) -> None:
    assert block["state"] == state, (
        f"expected block state {state}, got {block['state']}"
    )


def assert_block_commitments(
    block: dict,
    seats_committed: int = None,
    wav_positions_committed: int = None,
    committed_index_min=...,
    committed_index_max=...,
) -> None:
    if seats_committed is not None:
        assert block["seats_committed"] == seats_committed, block["seats_committed"]
    if wav_positions_committed is not None:
        assert block["wav_positions_committed"] == wav_positions_committed, block[
            "wav_positions_committed"
        ]
    if committed_index_min is not ...:
        assert block["committed_index_min"] == committed_index_min, block[
            "committed_index_min"
        ]
    if committed_index_max is not ...:
        assert block["committed_index_max"] == committed_index_max, block[
            "committed_index_max"
        ]


def assert_report_state(report: dict, state: str) -> None:
    assert report["state"] == state, (
        f"expected report state {state}, got {report['state']}"
    )


# ─── Ledger invariants ─────────────────────────────────────────────────────


def ledger_net_cents(rows) -> int:
    return sum(row["amount_cents"] for row in rows)


def assert_ledger_nets_to(rows, expected_cents: int) -> None:
    net = ledger_net_cents(rows)
    assert net == expected_cents, (
        f"ledger net {net} cents, expected {expected_cents}; rows="
        f"{[(r['kind'], r['amount_cents']) for r in rows]}"
    )


def assert_ledger_kinds(rows, expected_kinds) -> None:
    """Assert the multiset of ledger kinds, order-independently."""
    got = sorted(row["kind"] for row in rows)
    want = sorted(expected_kinds)
    assert got == want, f"expected ledger kinds {want}, got {got}"


def ledger_rows_of_kind(rows, kind):
    return [row for row in rows if row["kind"] == kind]


# ─── Listing helpers ───────────────────────────────────────────────────────


def ids_of(rows):
    return [row["id"] for row in rows]


def assert_contains_ids(rows, *expected_ids) -> None:
    present = set(ids_of(rows))
    missing = [i for i in expected_ids if i not in present]
    assert not missing, f"rows missing expected ids {missing}"


def assert_excludes_ids(rows, *forbidden_ids) -> None:
    present = set(ids_of(rows))
    leaked = [i for i in forbidden_ids if i in present]
    assert not leaked, f"rows unexpectedly include ids {leaked}"


def assert_row_count(rows, expected: int) -> None:
    assert len(rows) == expected, (
        f"expected {expected} rows, got {len(rows)}: {ids_of(rows)}"
    )
