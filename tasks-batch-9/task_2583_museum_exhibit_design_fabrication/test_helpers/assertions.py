"""Domain assertion helpers for the invariants the PRD states as identities."""

import decimal

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def round_half_up(value, places=0):
    """Round half away from zero, the rounding mode the PRD names throughout."""
    quantum = decimal.Decimal(1).scaleb(-places)
    rounded = decimal.Decimal(str(value)).quantize(
        quantum, rounding=decimal.ROUND_HALF_UP
    )
    return int(rounded) if places == 0 else float(rounded)


def assert_common_fields(row, expected_version=None):
    """Every entity except a vote row carries id, timestamps and a version."""
    assert is_valid_uuid(row["id"]), "id must be a bare UUID: %r" % (row["id"],)
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int)
    assert row["version"] >= 1
    if expected_version is not None:
        assert row["version"] == expected_version, (
            "expected version %s, got %s" % (expected_version, row["version"])
        )


def assert_money_identity(project):
    """The five money buckets always sum to the contract value."""
    buckets = [
        project["committed_fabrication_cents"] or 0,
        project["retainage_held_cents"] or 0,
        project["warranty_reserve_cents"] or 0,
        project["released_cents"] or 0,
        project["uncommitted_cents"] or 0,
    ]
    assert sum(buckets) == project["contract_value_cents"], (
        "five-bucket identity drifted: %s != %s"
        % (sum(buckets), project["contract_value_cents"])
    )


def assert_ledger(project, committed, uncommitted):
    """Assert the committed / uncommitted split and the identity together."""
    assert project["committed_fabrication_cents"] == committed, (
        "committed_fabrication_cents expected %s, got %s"
        % (committed, project["committed_fabrication_cents"])
    )
    assert project["uncommitted_cents"] == uncommitted, (
        "uncommitted_cents expected %s, got %s"
        % (uncommitted, project["uncommitted_cents"])
    )
    assert_money_identity(project)


def assert_zone_slot_identity(zone):
    """Zone capacity always equals reserved plus available slots."""
    assert (
        zone["reserved_case_slots"] + zone["available_case_slots"]
        == zone["case_slot_capacity"]
    ), (
        "zone slot identity drifted: %s + %s != %s"
        % (
            zone["reserved_case_slots"],
            zone["available_case_slots"],
            zone["case_slot_capacity"],
        )
    )


def assert_zone_slots(zone, reserved, available):
    assert zone["reserved_case_slots"] == reserved, (
        "reserved_case_slots expected %s, got %s"
        % (reserved, zone["reserved_case_slots"])
    )
    assert zone["available_case_slots"] == available, (
        "available_case_slots expected %s, got %s"
        % (available, zone["available_case_slots"])
    )
    assert_zone_slot_identity(zone)


def assert_envelope(
    case,
    placed_artifact_count=None,
    required_rh_min_pct=None,
    required_rh_max_pct=None,
    allowed_lux=None,
    env_feasible=None,
    security_ok=None,
):
    """Assert the derived strictest-wins envelope of a case."""
    if placed_artifact_count is not None:
        assert case["placed_artifact_count"] == placed_artifact_count
    if required_rh_min_pct is not None:
        assert case["required_rh_min_pct"] == pytest.approx(
            required_rh_min_pct, abs=0.01
        )
    if required_rh_max_pct is not None:
        assert case["required_rh_max_pct"] == pytest.approx(
            required_rh_max_pct, abs=0.01
        )
    if allowed_lux is not None:
        assert case["allowed_lux"] == pytest.approx(allowed_lux, abs=0.01)
    if env_feasible is not None:
        assert case["env_feasible"] is env_feasible
    if security_ok is not None:
        assert case["security_ok"] is security_ok


def assert_empty_envelope(case):
    """An empty case reports null bounds and both feasibility flags true."""
    assert case["placed_artifact_count"] == 0
    assert case["required_rh_min_pct"] is None
    assert case["required_rh_max_pct"] is None
    assert case["allowed_lux"] is None
    assert case["env_feasible"] is True
    assert case["security_ok"] is True


def assert_geometry(case, case_volume_m3, silica_gel_kg):
    assert case["case_volume_m3"] == pytest.approx(case_volume_m3, abs=0.00005)
    assert case["silica_gel_kg"] == pytest.approx(silica_gel_kg, abs=0.005)


def assert_counters(project, **expected):
    """Assert any subset of the six derived project counters plus posture."""
    for field, value in expected.items():
        assert project[field] == value, (
            "%s expected %s, got %s" % (field, value, project[field])
        )


def assert_index(actual, expected):
    """Two-decimal comparison for durability indices and flow scores."""
    assert actual == pytest.approx(expected, abs=0.005)


def assert_only_keys(mapping, keys):
    assert set(mapping.keys()) == set(keys), (
        "expected exactly the keys %s, got %s"
        % (sorted(keys), sorted(mapping.keys()))
    )


def assert_error_envelope_shape(response):
    """The error envelope carries nothing beyond an id and a message."""
    body = response.json()
    assert body["response_type"] == "error"
    assert_only_keys(body["meta"], ["api_request_id", "api_request_timestamp"])
    assert_only_keys(body["data"], ["error_id", "message"])
    return body["data"]


def assert_unchanged(before, after, fields):
    """Assert a rejected call left the named fields exactly as they were."""
    for field in fields:
        assert before[field] == after[field], (
            "%s changed from %r to %r" % (field, before[field], after[field])
        )


def assert_ids_in_order(rows, expected_ids):
    assert [row["id"] for row in rows] == list(expected_ids), (
        "row order differs: %s vs %s"
        % ([row["id"] for row in rows], list(expected_ids))
    )
