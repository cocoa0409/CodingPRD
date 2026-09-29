"""Domain assertion helpers for the circulation audit contract."""

import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import PCT_TOLERANCE


# --------------------------------------------------------------------------
# Common fields (PRD §2.4)
# --------------------------------------------------------------------------
def assert_common_fields(entity, expected_version=None):
    """Every entity but a hygiene run carries id, created_at, updated_at, version."""
    assert is_valid_uuid(entity["id"]), f"id is not a UUID: {entity['id']}"
    assert is_iso8601_timestamp(entity["created_at"])
    assert is_iso8601_timestamp(entity["updated_at"])
    assert isinstance(entity["version"], int)
    assert entity["version"] >= 1
    if expected_version is not None:
        assert entity["version"] == expected_version


def assert_immutable_record_fields(entity):
    """A hygiene run carries only id and created_at from the common set."""
    assert is_valid_uuid(entity["id"])
    assert is_iso8601_timestamp(entity["created_at"])
    assert "updated_at" not in entity
    assert "version" not in entity


def assert_envelope_meta(response):
    meta = response.json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
    return meta


# --------------------------------------------------------------------------
# Percentages and money (PRD §2.8)
# --------------------------------------------------------------------------
def assert_pct(actual, expected):
    """Percentages are carried to exactly two decimal places."""
    assert actual == pytest.approx(expected, abs=PCT_TOLERANCE), (
        f"expected percentage {expected}, got {actual}"
    )


def assert_cents(actual, expected):
    """Money is carried in whole cents as integers."""
    assert isinstance(actual, int), f"cent amount is not an integer: {actual!r}"
    assert actual == expected, f"expected {expected} cents, got {actual}"


# --------------------------------------------------------------------------
# Copies-on-file ledger (PRD §2.10)
# --------------------------------------------------------------------------
def assert_class_axis_conserved(publication):
    """copies_on_file_total equals the sum of the three class buckets."""
    assert publication["copies_on_file_total"] == (
        publication["paid_copies_on_file"]
        + publication["qualified_non_paid_copies_on_file"]
        + publication["controlled_copies_on_file"]
    )


def assert_delivery_axis_conserved(publication):
    """copies_on_file_total equals the sum of the three delivery buckets."""
    assert publication["copies_on_file_total"] == (
        publication["deliverable_copies"]
        + publication["undeliverable_copies"]
        + publication["removed_copies"]
    )


def assert_ledger_conserved(publication):
    assert_class_axis_conserved(publication)
    assert_delivery_axis_conserved(publication)


def assert_hygiene_ratio(publication):
    """undeliverable_pct is (undeliverable + removed) * 100 / total, 0.00 when empty."""
    total = publication["copies_on_file_total"]
    if total == 0:
        assert_pct(publication["undeliverable_pct"], 0.00)
        return
    numerator = publication["undeliverable_copies"] + publication["removed_copies"]
    expected = round(numerator * 100 / total + 1e-9, 2)
    assert_pct(publication["undeliverable_pct"], expected)


def assert_ledger_buckets(
    publication,
    total=None,
    paid=None,
    qualified_non_paid=None,
    controlled=None,
    deliverable=None,
    undeliverable=None,
    removed=None,
):
    if total is not None:
        assert publication["copies_on_file_total"] == total
    if paid is not None:
        assert publication["paid_copies_on_file"] == paid
    if qualified_non_paid is not None:
        assert publication["qualified_non_paid_copies_on_file"] == qualified_non_paid
    if controlled is not None:
        assert publication["controlled_copies_on_file"] == controlled
    if deliverable is not None:
        assert publication["deliverable_copies"] == deliverable
    if undeliverable is not None:
        assert publication["undeliverable_copies"] == undeliverable
    if removed is not None:
        assert publication["removed_copies"] == removed
    assert_ledger_conserved(publication)


# --------------------------------------------------------------------------
# Make-good credit conservation (PRD §2.11)
# --------------------------------------------------------------------------
def assert_credit_pool_conserved(contract):
    """pool equals committed plus waived plus available."""
    assert contract["makegood_credit_pool_cents"] == (
        contract["makegood_credit_committed_cents"]
        + contract["makegood_credit_waived_cents"]
        + contract["makegood_credit_available_cents"]
    )


def assert_credit_buckets(
    contract, pool=None, committed=None, waived=None, available=None
):
    if pool is not None:
        assert_cents(contract["makegood_credit_pool_cents"], pool)
    if committed is not None:
        assert_cents(contract["makegood_credit_committed_cents"], committed)
    if waived is not None:
        assert_cents(contract["makegood_credit_waived_cents"], waived)
    if available is not None:
        assert_cents(contract["makegood_credit_available_cents"], available)
    assert_credit_pool_conserved(contract)


# --------------------------------------------------------------------------
# Statement breakdown (PRD §3.7)
# --------------------------------------------------------------------------
def assert_breakdown(
    statement,
    paid=None,
    qualified_non_paid=None,
    controlled_included=None,
    controlled_excess=None,
    total_qualified=None,
    digital_reach=None,
):
    if paid is not None:
        assert statement["paid_copies"] == paid
    if qualified_non_paid is not None:
        assert statement["qualified_non_paid_copies"] == qualified_non_paid
    if controlled_included is not None:
        assert statement["controlled_copies_included"] == controlled_included
    if controlled_excess is not None:
        assert statement["controlled_copies_excess"] == controlled_excess
    if total_qualified is not None:
        assert statement["total_qualified_copies"] == total_qualified
    if digital_reach is not None:
        assert statement["digital_reach_verified"] == digital_reach
    # total_qualified_copies is paid + qualified_non_paid + controlled_included.
    assert statement["total_qualified_copies"] == (
        statement["paid_copies"]
        + statement["qualified_non_paid_copies"]
        + statement["controlled_copies_included"]
    )


def controlled_allowance(core, cap_pct):
    """core * cap_pct / (100 - cap_pct), truncated down to whole copies."""
    return int(core * cap_pct / (100 - cap_pct))


def assert_statement_status(statement, expected_status):
    assert statement["status"] == expected_status, (
        f"expected statement status {expected_status}, got {statement['status']}"
    )


def assert_posture(publication, expected_posture):
    assert publication["audit_posture"] == expected_posture, (
        f"expected posture {expected_posture}, got {publication['audit_posture']}"
    )


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
def assert_created_at_ascending(rows):
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows are not in created_at ascending order: {stamps}"
