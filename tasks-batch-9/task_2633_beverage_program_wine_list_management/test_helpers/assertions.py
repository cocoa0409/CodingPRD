"""Domain assertion helpers for the beverage-program API."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
)

from .api_client import api_client


def assert_common_fields(entity, name="entity"):
    """Every entity except DepletionEntry carries id, created_at, updated_at
    and version."""
    assert is_valid_uuid(entity["id"]), (
        "%s.id must be a uuid, got %r" % (name, entity.get("id")))
    assert is_iso8601_timestamp(entity["created_at"]), (
        "%s.created_at must be ISO 8601, got %r" % (name, entity.get("created_at")))
    assert is_iso8601_timestamp(entity["updated_at"]), (
        "%s.updated_at must be ISO 8601, got %r" % (name, entity.get("updated_at")))
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        "%s.version must be a positive integer, got %r" % (name, entity.get("version")))


def assert_append_only_fields(entry):
    """A DepletionEntry carries id and created_at but no updated_at/version."""
    assert is_valid_uuid(entry["id"]), "DepletionEntry.id must be a uuid"
    assert is_iso8601_timestamp(entry["created_at"]), (
        "DepletionEntry.created_at must be ISO 8601")
    assert "updated_at" not in entry, (
        "DepletionEntry must not carry updated_at: %r" % (entry.get("updated_at"),))
    assert "version" not in entry, (
        "DepletionEntry must not carry version: %r" % (entry.get("version"),))


def assert_fields_equal(entity, expected, name="entity"):
    """Assert every key of ``expected`` matches the entity."""
    for key, value in expected.items():
        assert key in entity, "%s is missing field %r" % (name, key)
        assert entity[key] == value, (
            "%s.%s expected %r, got %r" % (name, key, value, entity[key]))


def assert_decimal_equals(actual, expected, field="value"):
    """Compare a PRD ``decimal`` field (two decimal places) numerically."""
    assert actual is not None, "%s must not be null" % field
    assert abs(float(actual) - float(expected)) < 1e-9, (
        "%s expected %s, got %s" % (field, expected, actual))


def assert_two_decimal_places(actual, field="value"):
    text = ("%s" % actual)
    if "." in text:
        assert len(text.split(".")[1]) <= 2, (
            "%s must carry at most two decimal places, got %s" % (field, actual))


def assert_null_fields(entity, *field_names):
    for field in field_names:
        assert field in entity, "expected field %r to be present" % field
        assert entity[field] is None, (
            "expected %s to be null, got %r" % (field, entity[field]))


def get_all(list_callable, headers, params=None, limit=100):
    """Drain a paginated collection endpoint into a single list."""
    collected = []
    offset = 0
    while True:
        query = dict(params or {})
        query["limit"] = limit
        query["offset"] = offset
        response = list_callable(headers, params=query)
        page, meta = validate_paginated(response)
        collected.extend(page)
        if not meta["has_more"]:
            return collected
        offset += limit


def depletion_entries_for(headers, **filters):
    """All DepletionEntry rows matching the given filters, oldest first.

    The server already returns the collection "ordered by `occurred_at`
    ascending then `created_at` ascending", and PRD 2.3 states that
    "Records are never ordered by `id`" — so the response order is taken
    as-is rather than re-sorted client-side.
    """
    return get_all(api_client.list_depletion_entries, headers, params=filters)


def assert_ledger_sums_to_zero(entries, field):
    total = sum(entry[field] for entry in entries)
    assert total == 0, (
        "expected the %s column of %d ledger rows to sum to 0, got %d"
        % (field, len(entries), total))


def assert_entry_unchanged(before, after, name="entity"):
    """Assert an append-only row was neither mutated nor re-stamped."""
    assert before == after, (
        "%s must never be mutated; before=%r after=%r" % (name, before, after))
