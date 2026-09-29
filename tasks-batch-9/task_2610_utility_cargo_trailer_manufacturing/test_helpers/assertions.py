"""Domain assertion helpers for the trailer plant.

These wrap the invariants PRD sections 2.5, 2.9, 2.10, 3.5 and 3.7 state
about every response, so a test can spend its lines on the rule it is
actually pinning.
"""

import re

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as K
from .types import APPEND_ONLY_AUDIT_FIELDS, FULL_AUDIT_FIELDS


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def assert_full_audit_fields(row):
    """PRD 2.5: a server-minted bare UUID plus created_at, updated_at and version."""
    for field in FULL_AUDIT_FIELDS:
        assert field in row, "missing audit field %s" % field
    assert is_valid_uuid(row["id"]), "id is not a UUID: %r" % (row["id"],)
    assert UUID_RE.match(row["id"]), "id carries a prefix or encoding: %r" % (row["id"],)
    assert is_iso8601_timestamp(row["created_at"])
    assert is_iso8601_timestamp(row["updated_at"])
    assert isinstance(row["version"], int)


def assert_append_only_audit_fields(row):
    """PRD 2.5: a frame inspection carries only `id` and `created_at`."""
    for field in APPEND_ONLY_AUDIT_FIELDS:
        assert field in row, "missing audit field %s" % field
    assert is_valid_uuid(row["id"])
    assert is_iso8601_timestamp(row["created_at"])
    assert "updated_at" not in row or row["updated_at"] is None
    assert "version" not in row or row["version"] is None


def assert_timestamp_with_millis(value, expected=None):
    """PRD 2.5: an ISO 8601 UTC timestamp with three fractional digits."""
    assert value is not None
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", value), value
    if expected is not None:
        assert value == expected


def assert_weight_budget_balances(unit):
    """PRD 3.5: curb_weight_lbs plus payload_capacity_lbs equals the pinned gvwr_lbs."""
    assert unit["curb_weight_lbs"] + unit["payload_capacity_lbs"] == unit["gvwr_lbs"]


def assert_unit_dimensions(unit, build_status, compliance_status):
    """PRD 1: a trailer carries two independent status dimensions at once."""
    assert unit["build_status"] == build_status, (
        "build_status %r, expected %r" % (unit["build_status"], build_status)
    )
    assert unit["compliance_status"] == compliance_status, (
        "compliance_status %r, expected %r" % (unit["compliance_status"], compliance_status)
    )


def assert_floor_plan_conserved(dealer, expected_outstanding_cents):
    """PRD 2.10: floor_plan_available_cents is the limit less the outstanding sum."""
    assert dealer["floor_plan_outstanding_cents"] == expected_outstanding_cents
    assert (
        dealer["floor_plan_available_cents"]
        == dealer["floor_plan_limit_cents"] - dealer["floor_plan_outstanding_cents"]
    )


def assert_vin_composition(vin, frame_design_code, axle_count, braked, year, sequence):
    """PRD 3.7: the VIN is exactly 17 characters assembled from nine pieces."""
    assert len(vin) == K.VIN_LENGTH, "VIN length %d: %r" % (len(vin), vin)
    expected = "".join(
        [
            K.VIN_WMI,
            frame_design_code,
            str(axle_count),
            "E" if braked else "N",
            K.VIN_BODY_STYLE_CHAR,
            K.VIN_CHECK_PLACEHOLDER,
            K.VIN_YEAR_CHARS[year],
            K.VIN_PLANT_CHAR,
            "%06d" % sequence,
        ]
    )
    assert vin == expected, "VIN %r, expected %r" % (vin, expected)


def assert_mco_number(mco_number, sequence):
    """PRD 3.7: `MCO-` followed by the vin_sequence zero-padded to six digits."""
    assert mco_number == K.MCO_PREFIX + "%06d" % sequence


def assert_money(actual, expected):
    """PRD 2.9: money is whole cents, never a decimal string."""
    assert isinstance(actual, int) and not isinstance(actual, bool), (
        "monetary value is not a whole-cent integer: %r" % (actual,)
    )
    assert actual == expected, "%r cents, expected %r" % (actual, expected)


def assert_one_decimal(actual, expected):
    """PRD 2.9: deviations, widths, distances and labor hours run to one decimal place."""
    assert actual == pytest.approx(expected, abs=0.01)


def assert_pagination_meta(meta, limit, offset, total_count, has_more):
    """PRD 2.3: list responses carry limit, offset, total_count and has_more."""
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is has_more


def assert_no_money_computed(claim):
    """PRD 3.9: no money is computed at filing."""
    for field in (
        "coverage_variant",
        "coverage_factor",
        "labor_cents",
        "parts_subtotal_cents",
        "freight_cents",
        "reimbursement_total_cents",
    ):
        assert claim[field] is None, "%s should still be null, got %r" % (field, claim[field])


def assert_version_advanced(new_row, old_version, by=1):
    """PRD 2.5: version increments by exactly one on every mutation of that row."""
    assert new_row["version"] == old_version + by, (
        "version %r, expected %r" % (new_row["version"], old_version + by)
    )


def assert_instant(value, expected):
    """PRD 2.5: an ISO 8601 UTC instant, compared to the second.

    Tolerates the three fractional digits the envelope carries so a test can
    pin the instant it set on the logical clock.
    """

    def norm(text):
        return text.replace("Z", "").replace("+00:00", "").split(".")[0]

    assert value is not None, "expected the instant %s, got null" % expected
    assert norm(value) == norm(expected), "instant %r, expected %r" % (value, expected)
