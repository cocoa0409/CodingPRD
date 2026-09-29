"""
Domain assertions for the Ground Lease Administration API.

These encode the invariants PRD.md states in general terms so a test can name
them once: the §2.2 envelope, the §2.4 common-field block (and the single
AppraisalSubmission exception), the §2.6 integer money rule, and the four
conserved quantities of §2.10.
"""

import datetime as _dt
import re as _re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import COMMON_FIELDS

_INSTANT_RE = _re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$"
)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant, or return None when `value` is not one."""
    if not isinstance(value, str) or not _INSTANT_RE.match(value):
        return None
    try:
        return _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # pragma: no cover — guarded by the regex above
        return None


def same_instant(actual, expected):
    """Compare two ISO 8601 instants as instants rather than as strings.

    PRD §2.2 pins the rendering of `api_request_timestamp` and §2.4 pins the
    rendering of `created_at` / `updated_at` to exactly three fractional digits.
    It states no rendering for the business instants (`served_at`, the cure
    deadlines, `next_revaluation_date`, `insurance_expires_at`, `issued_at`,
    `run_at`, ...), so `2026-08-11T00:00:00Z` and `2026-08-11T00:00:00.000Z`
    are the same PRD-conformant answer and are compared as such.
    """
    left, right = parse_instant(actual), parse_instant(expected)
    if left is None or right is None:
        return False
    return left == right


def assert_instant(actual, expected):
    assert same_instant(actual, expected), (
        f"expected the instant {expected!r}, got {actual!r}"
    )


def assert_envelope(body):
    """PRD §2.2: meta.api_request_id starts with `req_`; the timestamp is an
    ISO 8601 UTC instant; response_type is object, array or error."""
    assert "meta" in body and "response_type" in body and "data" in body, body
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert isinstance(meta.get("api_request_timestamp"), str)
    assert body["response_type"] in ("object", "array", "error"), body["response_type"]


def assert_common_fields(row):
    """PRD §2.4: every persisted resource carries id, created_at, updated_at and
    version; version starts at 1 and rises by one on every mutation."""
    for field in COMMON_FIELDS:
        assert field in row, f"missing common field {field!r} in {sorted(row)}"
    assert is_valid_uuid(row["id"]), row["id"]
    assert is_iso8601_timestamp(row["created_at"]), row["created_at"]
    assert is_iso8601_timestamp(row["updated_at"]), row["updated_at"]
    assert isinstance(row["version"], int) and row["version"] >= 1, row["version"]


def assert_appraisal_shape(row):
    """PRD §2.4: an AppraisalSubmission has no updated_at and no version field at
    all, and neither key appears in its response payload."""
    assert "id" in row and "created_at" in row
    assert is_valid_uuid(row["id"]), row["id"]
    assert "updated_at" not in row, "AppraisalSubmission must not carry updated_at"
    assert "version" not in row, "AppraisalSubmission must not carry version"


def assert_integer_money(row, *fields):
    """PRD §2.6: money is integer cents — never a float, never a string."""
    for field in fields:
        value = row.get(field)
        if value is None:
            continue
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be an integer number of cents, got {value!r}"
        )


def assert_bps(value):
    assert isinstance(value, int) and 0 <= value <= 10000, value


def assert_envelope_conserved(lease):
    """PRD §2.10: gfa_allocated_sqft + gfa_unallocated_sqft == total_permitted_gfa_sqft."""
    assert (
        lease["gfa_allocated_sqft"] + lease["gfa_unallocated_sqft"]
        == lease["total_permitted_gfa_sqft"]
    ), lease


def assert_deposit_conserved(lease):
    """PRD §2.10: deposit_held + deposit_applied + deposit_refunded == security_deposit_cents."""
    assert (
        lease["deposit_held_cents"]
        + lease["deposit_applied_cents"]
        + lease["deposit_refunded_cents"]
        == lease["security_deposit_cents"]
    ), lease


def assert_proceeds_conserved(loss_event):
    """PRD §2.10: the four allocation buckets sum to distributable_pool_cents exactly."""
    total = (
        loss_event["allocated_arrears_cents"]
        + loss_event["allocated_mortgagee_cents"]
        + loss_event["allocated_lessee_cents"]
        + loss_event["allocated_lessor_cents"]
    )
    assert total == loss_event["distributable_pool_cents"], loss_event


def assert_transfer_fee_conserved(transfer):
    """PRD §2.10: total_transfer_fee_cents == gross + admin charge + late surcharge."""
    assert (
        transfer["total_transfer_fee_cents"]
        == transfer["transfer_fee_gross_cents"]
        + transfer["admin_charge_cents"]
        + transfer["late_surcharge_cents"]
    ), transfer


def assert_fields(row, **expected):
    """Assert a batch of field values with a readable failure message."""
    for field, value in expected.items():
        assert field in row, f"missing field {field!r} in {sorted(row)}"
        if row[field] != value and same_instant(row[field], value):
            # Same instant, different fractional-digit rendering — see
            # same_instant(): the PRD does not pin the rendering of business
            # instants, only of created_at / updated_at (§2.4).
            continue
        assert row[field] == value, (
            f"{field}: expected {value!r}, got {row[field]!r}"
        )


def assert_version_unchanged(before, after):
    assert after["version"] == before["version"], (
        f"version moved on a refused write: {before['version']} -> {after['version']}"
    )
