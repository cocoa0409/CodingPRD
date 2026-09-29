"""Domain assertion helpers for the interconnection access billing suite.

The numeric helpers encode the PRD's precision policy: monetary amounts at two
decimals, tariffed and reciprocal rates at six, minute quantities at four,
percentages at two and the traffic balance ratio at four.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _num(value):
    """Coerce a JSON numeric field to float, tolerating a decimal string."""
    assert value is not None, "expected a numeric value, found null"
    return float(value)


def assert_money(actual, expected, label="amount"):
    """Assert a monetary field equals ``expected`` at two decimal places."""
    assert round(_num(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_rate(actual, expected, label="rate"):
    """Assert a rate field equals ``expected`` at six decimal places."""
    assert round(_num(actual), 6) == round(float(expected), 6), (
        f"{label}: expected {expected:.6f}, got {actual}"
    )


def assert_minutes(actual, expected, label="minutes"):
    """Assert a minute quantity equals ``expected`` at four decimal places."""
    assert round(_num(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_pct(actual, expected, label="percentage"):
    """Assert a percentage field equals ``expected`` at two decimal places."""
    assert round(_num(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected:.2f}, got {actual}"
    )


def assert_ratio(actual, expected, label="ratio"):
    """Assert a traffic balance ratio equals ``expected`` at four decimal places."""
    assert round(_num(actual), 4) == round(float(expected), 4), (
        f"{label}: expected {expected:.4f}, got {actual}"
    )


def assert_identity_fields(entity, label="entity"):
    """Assert the entity carries a UUID id and an ISO-8601 created_at."""
    assert is_valid_uuid(entity.get("id")), f"{label}: id is not a UUID: {entity.get('id')}"
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{label}: created_at is not ISO-8601: {entity.get('created_at')}"
    )


def assert_versioned_entity(entity, expected_version=None, label="entity"):
    """Assert the entity carries the full mutable common-field set."""
    assert_identity_fields(entity, label)
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{label}: updated_at is not ISO-8601: {entity.get('updated_at')}"
    )
    assert isinstance(entity.get("version"), int), (
        f"{label}: version must be an integer, got {entity.get('version')!r}"
    )
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"{label}: expected version {expected_version}, got {entity['version']}"
        )


def assert_immutable_entity(entity, label="entity"):
    """Assert the entity carries only id and created_at (no updated_at, no version)."""
    assert_identity_fields(entity, label)
    assert "updated_at" not in entity, f"{label}: must not expose updated_at"
    assert "version" not in entity, f"{label}: must not expose version"


def assert_fields_absent(entity, field_names, label="entity"):
    """Assert none of ``field_names`` appear on the payload."""
    for name in field_names:
        assert name not in entity, f"{label}: must not expose {name}"


def assert_envelope(response, response_type):
    """Assert the response envelope carries a well-formed meta block."""
    body = response.json()
    meta = body.get("meta")
    assert isinstance(meta, dict), "response is missing its meta block"
    request_id = meta.get("api_request_id")
    assert isinstance(request_id, str) and request_id.startswith("req_"), (
        f"api_request_id must be prefixed req_, got {request_id!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"api_request_timestamp is not ISO-8601: {meta.get('api_request_timestamp')}"
    )
    assert body.get("response_type") == response_type, (
        f"expected response_type {response_type!r}, got {body.get('response_type')!r}"
    )
    return body


def assert_error_payload_shape(response):
    """Assert an error body's data carries only error_id and message."""
    body = response.json()
    data = body.get("data")
    assert isinstance(data, dict), "error body is missing its data object"
    assert set(data.keys()) == {"error_id", "message"}, (
        f"error data must carry only error_id and message, got {sorted(data.keys())}"
    )
    return data


def assert_created_at_ascending(items, label="collection"):
    """Assert a collection is ordered by created_at ascending."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"{label}: not in created_at ASC order: {stamps}"


def assert_id_order(items, expected_ids, label="collection"):
    """Assert the collection contains exactly ``expected_ids`` in that order."""
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), (
        f"{label}: expected ids {list(expected_ids)}, got {actual}"
    )


def find_by_id(items, entity_id):
    """Return the single element of ``items`` whose id matches, or fail."""
    matches = [item for item in items if item.get("id") == entity_id]
    assert len(matches) == 1, f"expected exactly one element with id {entity_id}, found {len(matches)}"
    return matches[0]


def assert_invoice_dimensions(invoice, lifecycle, payment, dispute):
    """Assert all three independent invoice status dimensions at once."""
    assert invoice["lifecycle_status"] == lifecycle, (
        f"lifecycle_status: expected {lifecycle}, got {invoice['lifecycle_status']}"
    )
    assert invoice["payment_status"] == payment, (
        f"payment_status: expected {payment}, got {invoice['payment_status']}"
    )
    assert invoice["dispute_status"] == dispute, (
        f"dispute_status: expected {dispute}, got {invoice['dispute_status']}"
    )


def assert_trunk_group_statuses(trunk_group, service_status, augment_status):
    """Assert both trunk group status dimensions at once."""
    assert trunk_group["service_status"] == service_status, (
        f"service_status: expected {service_status}, got {trunk_group['service_status']}"
    )
    assert trunk_group["augment_status"] == augment_status, (
        f"augment_status: expected {augment_status}, got {trunk_group['augment_status']}"
    )


def assert_reserve_summary(
    summary,
    open_receivable_usd=None,
    disputed_receivable_usd=None,
    net_receivable_usd=None,
    tier_pct=None,
    uncollectible_reserve_balance_usd=None,
    regulatory_disputed_reserve_usd=None,
    gaap_disputed_reserve_usd=None,
    disputed_reserve_basis_delta_usd=None,
):
    """Assert whichever of the eight reserve summary figures were supplied."""
    checks = (
        ("open_receivable_usd", open_receivable_usd),
        ("disputed_receivable_usd", disputed_receivable_usd),
        ("net_receivable_usd", net_receivable_usd),
        ("tier_pct", tier_pct),
        ("uncollectible_reserve_balance_usd", uncollectible_reserve_balance_usd),
        ("regulatory_disputed_reserve_usd", regulatory_disputed_reserve_usd),
        ("gaap_disputed_reserve_usd", gaap_disputed_reserve_usd),
        ("disputed_reserve_basis_delta_usd", disputed_reserve_basis_delta_usd),
    )
    for field, expected in checks:
        if expected is not None:
            assert_money(summary[field], expected, field)


def assert_ledger_entry(
    entry,
    entry_type=None,
    source_event=None,
    amount_usd=None,
    balance_after_usd=None,
    reserve_bucket=None,
):
    """Assert the shape and figures of one reserve ledger entry."""
    if entry_type is not None:
        assert entry["entry_type"] == entry_type, (
            f"entry_type: expected {entry_type}, got {entry['entry_type']}"
        )
    if source_event is not None:
        assert entry["source_event"] == source_event, (
            f"source_event: expected {source_event}, got {entry['source_event']}"
        )
    if reserve_bucket is not None:
        assert entry["reserve_bucket"] == reserve_bucket, (
            f"reserve_bucket: expected {reserve_bucket}, got {entry['reserve_bucket']}"
        )
    if amount_usd is not None:
        assert_money(entry["amount_usd"], amount_usd, "amount_usd")
    if balance_after_usd is not None:
        assert_money(entry["balance_after_usd"], balance_after_usd, "balance_after_usd")


def assert_ledger_amounts(entries, expected_amounts, label="ledger"):
    """Assert the ledger movement amounts, in order."""
    actual = [round(_num(entry["amount_usd"]), 2) for entry in entries]
    expected = [round(float(value), 2) for value in expected_amounts]
    assert actual == expected, f"{label}: expected movements {expected}, got {actual}"


def assert_decimal_places(value, places, label="value"):
    """Assert the field is expressed with no more than ``places`` decimals."""
    quantised = round(_num(value), places)
    assert abs(_num(value) - quantised) < 1e-9, (
        f"{label}: {value} carries more than {places} decimal places"
    )
