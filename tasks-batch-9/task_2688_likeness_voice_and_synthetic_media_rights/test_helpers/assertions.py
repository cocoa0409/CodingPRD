"""Domain assertions for the Likeness Rights Clearance API."""

SWEEP_COUNT_FIELDS = (
    "expired_consent_count",
    "retired_replica_count",
    "expired_license_count",
    "removal_pending_count",
    "overdue_removal_count",
    "auto_rejected_performance_count",
    "purge_scheduled_count",
    "purged_count",
    "opened_case_count",
)


def assert_versioned(record: dict, expected_version: int = None) -> None:
    """A versioned row exposes updated_at and an integer version."""
    assert "updated_at" in record, f"expected updated_at on {record}"
    assert "version" in record, f"expected version on {record}"
    assert isinstance(record["version"], int), (
        f"version must be an integer, got {record['version']!r}"
    )
    if expected_version is not None:
        assert record["version"] == expected_version, (
            f"expected version {expected_version}, got {record['version']}"
        )


def assert_immutable_record(record: dict) -> None:
    """An immutable row carries neither updated_at nor version at all."""
    assert "id" in record and "created_at" in record, f"expected id and created_at on {record}"
    assert "updated_at" not in record, (
        f"an immutable record must not expose updated_at: {record}"
    )
    assert "version" not in record, f"an immutable record must not expose version: {record}"


def assert_version_advanced_by(record: dict, baseline: int, steps: int = 1) -> None:
    """The row's version moved by exactly the stated number of steps."""
    assert record["version"] == baseline + steps, (
        f"expected version {baseline + steps}, got {record['version']}"
    )


def assert_money_is_number(value) -> None:
    """Monetary amounts are JSON numbers, never strings."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"monetary amount must be a JSON number, got {value!r}"
    )


def assert_split_reconstructs_amount(entry: dict) -> None:
    """The three stored slices always reconstruct amount_cents exactly."""
    total = (
        entry["talent_share_cents"]
        + entry["agency_share_cents"]
        + entry["administrator_share_cents"]
    )
    assert total == entry["amount_cents"], (
        f"slices {entry['talent_share_cents']}/{entry['agency_share_cents']}/"
        f"{entry['administrator_share_cents']} sum to {total}, "
        f"expected {entry['amount_cents']}"
    )


def assert_ledger_entry(
    entry: dict,
    entry_type: str,
    amount_cents: int,
    talent_share_cents: int = None,
    agency_share_cents: int = None,
    administrator_share_cents: int = None,
) -> None:
    """A ledger entry's type, signed amount and — when given — its three slices."""
    assert entry["entry_type"] == entry_type, (
        f"expected entry_type {entry_type}, got {entry['entry_type']}"
    )
    assert_money_is_number(entry["amount_cents"])
    assert entry["amount_cents"] == amount_cents, (
        f"expected amount_cents {amount_cents}, got {entry['amount_cents']}"
    )
    if talent_share_cents is not None:
        assert entry["talent_share_cents"] == talent_share_cents, (
            f"expected talent_share_cents {talent_share_cents}, "
            f"got {entry['talent_share_cents']}"
        )
    if agency_share_cents is not None:
        assert entry["agency_share_cents"] == agency_share_cents, (
            f"expected agency_share_cents {agency_share_cents}, "
            f"got {entry['agency_share_cents']}"
        )
    if administrator_share_cents is not None:
        assert entry["administrator_share_cents"] == administrator_share_cents, (
            f"expected administrator_share_cents {administrator_share_cents}, "
            f"got {entry['administrator_share_cents']}"
        )
    assert_split_reconstructs_amount(entry)


def assert_exact_negation(reversal: dict, reversed_entry: dict) -> None:
    """A reversal negates the reversed entry in every column and names it."""
    assert reversal["entry_type"] == "REVERSAL", (
        f"expected a REVERSAL entry, got {reversal['entry_type']}"
    )
    assert reversal["reverses_entry_id"] == reversed_entry["id"], (
        f"expected reverses_entry_id {reversed_entry['id']}, "
        f"got {reversal['reverses_entry_id']}"
    )
    for column in (
        "amount_cents",
        "talent_share_cents",
        "agency_share_cents",
        "administrator_share_cents",
    ):
        assert reversal[column] == -reversed_entry[column], (
            f"expected {column} of {-reversed_entry[column]}, got {reversal[column]}"
        )


def assert_ledger_sums_to(entries: list, expected_total: int) -> None:
    """The signed sum of amount_cents over the supplied entries."""
    total = sum(entry["amount_cents"] for entry in entries)
    assert total == expected_total, (
        f"ledger sums to {total}, expected {expected_total}"
    )


def assert_entry_types(entries: list, expected_types: list) -> None:
    """The entry types in the order the ledger returned them."""
    actual = [entry["entry_type"] for entry in entries]
    assert actual == expected_types, f"expected entry types {expected_types}, got {actual}"


def assert_posture(talent: dict, expected: str) -> None:
    """The talent's derived rights posture."""
    assert talent["rights_posture"] == expected, (
        f"expected rights_posture {expected}, got {talent['rights_posture']}"
    )


def assert_talent_counters(
    talent: dict,
    open_removal_obligation_count: int = None,
    legal_hold_asset_count: int = None,
    lifetime_compensation_cents: int = None,
) -> None:
    """The talent's derived counters and lifetime roll-up."""
    if open_removal_obligation_count is not None:
        assert talent["open_removal_obligation_count"] == open_removal_obligation_count, (
            f"expected open_removal_obligation_count {open_removal_obligation_count}, "
            f"got {talent['open_removal_obligation_count']}"
        )
    if legal_hold_asset_count is not None:
        assert talent["legal_hold_asset_count"] == legal_hold_asset_count, (
            f"expected legal_hold_asset_count {legal_hold_asset_count}, "
            f"got {talent['legal_hold_asset_count']}"
        )
    if lifetime_compensation_cents is not None:
        assert talent["lifetime_compensation_cents"] == lifetime_compensation_cents, (
            f"expected lifetime_compensation_cents {lifetime_compensation_cents}, "
            f"got {talent['lifetime_compensation_cents']}"
        )


def assert_sweep_counts(report: dict, **expected) -> None:
    """Named sweep counts as given; every other reported count must be zero."""
    for field in SWEEP_COUNT_FIELDS:
        assert field in report, f"sweep report is missing {field}"
        wanted = expected.get(field, 0)
        assert report[field] == wanted, (
            f"expected {field} of {wanted}, got {report[field]}"
        )


def assert_sweep_changed_nothing(report: dict) -> None:
    """Every phase of the run moved no rows at all."""
    assert_sweep_counts(report)


def assert_pagination(
    meta: dict, limit: int, offset: int, total_count: int, has_more: bool
) -> None:
    """The four pagination fields a list response reports inside meta."""
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta['offset']}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_fields_absent(record: dict, *field_names) -> None:
    """None of the named fields appears in the representation."""
    for name in field_names:
        assert name not in record, f"expected {name} to be absent, found {record[name]!r}"


def assert_fields_null(record: dict, *field_names) -> None:
    """Each named field is present and null."""
    for name in field_names:
        assert name in record, f"expected {name} to be present"
        assert record[name] is None, f"expected {name} to be null, got {record[name]!r}"


def assert_subset_equal(record: dict, expected: dict) -> None:
    """Every named field on the record equals the expected value."""
    for name, wanted in expected.items():
        assert name in record, f"expected field {name} on {record}"
        assert record[name] == wanted, (
            f"expected {name} of {wanted!r}, got {record[name]!r}"
        )
