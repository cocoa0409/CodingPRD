"""Domain assertions for the Licensure Portability API.

These build on the framework's structural helpers and encode the invariants the
PRD states about identity, audit fields, ledger shape, money conservation,
requirement-hour conservation and numeric precision.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ENTRY_ASSESSMENT,
    ENTRY_PERMIT_FEE,
    INDEX_CEILING,
    LICENSE_SEQUENCE_WIDTH,
    SCORE_MAX,
    SCORE_MIN,
)

# ─── Instant comparison ───────────────────────────────
#
# The requirements pin the *instant* a domain timestamp denotes — `submitted_at`
# is the logical clock at submission, `review_deadline_at` is that instant plus a
# whole-day allowance, `expires_at` is the earlier of two whole-day candidates —
# and separately pin a three-fractional-digit rendering for the audit fields
# `created_at` / `updated_at`.  Nothing fixes the rendering of the domain
# timestamps, so `2026-08-01T00:00:00Z` and `2026-08-01T00:00:00.000Z` denote the
# same required instant.  Equality checks therefore compare instants, while the
# audit-field format assertions above continue to police the rendering.

_ISO_INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def normalize_instant(value: Any) -> Any:
    """Parse an ISO 8601 instant to a UTC datetime; pass anything else through."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not _ISO_INSTANT_RE.match(text):
        return value
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def instants_equal(actual: Any, expected: Any) -> bool:
    """True when two values are equal, comparing ISO 8601 strings as instants."""
    if actual == expected:
        return True
    return normalize_instant(actual) == normalize_instant(expected)


def assert_instant_equals(actual: Any, expected: Any, label: str) -> None:
    """Assert two timestamps denote the same instant, whatever their rendering."""
    assert instants_equal(actual, expected), (
        f"{label}: expected the instant {expected!r}, got {actual!r}"
    )


# ─── Identity and audit fields ────────────────────────

def assert_uuid_id(resource: Dict[str, Any]) -> str:
    """Assert the resource carries a server-minted UUID `id` with no prefix."""
    resource_id = resource.get("id")
    assert is_valid_uuid(resource_id), f"`id` must be a bare UUID string, got {resource_id!r}"
    return resource_id


def assert_audit_triplet(
    resource: Dict[str, Any], expected_version: Optional[int] = None
) -> None:
    """Assert `created_at`, `updated_at` and `version` are all present and well formed."""
    assert_uuid_id(resource)
    for field in ("created_at", "updated_at"):
        value = resource.get(field)
        assert is_iso8601_timestamp(value), f"`{field}` must be an ISO 8601 UTC instant, got {value!r}"
    version = resource.get("version")
    assert isinstance(version, int), f"`version` must be an integer, got {version!r}"
    assert version >= 1, f"`version` starts at 1, got {version}"
    if expected_version is not None:
        assert version == expected_version, f"Expected version {expected_version}, got {version}"


def assert_no_audit_triplet(entry: Dict[str, Any]) -> None:
    """Assert an append-only ledger entry carries only `id` and `created_at`."""
    assert_uuid_id(entry)
    assert is_iso8601_timestamp(entry.get("created_at")), (
        f"ledger entry `created_at` must be an ISO 8601 UTC instant, got {entry.get('created_at')!r}"
    )
    assert "updated_at" not in entry, "a ledger entry must not carry an `updated_at` key"
    assert "version" not in entry, "a ledger entry must not carry a `version` key"


def assert_timestamps_ordered_ascending(rows: Sequence[Dict[str, Any]], field: str = "created_at") -> None:
    """Assert a list came back ordered by the given timestamp field ascending."""
    values = [row.get(field) for row in rows]
    assert values == sorted(values), f"rows are not ordered by {field} ascending: {values}"


# ─── Numeric precision ────────────────────────────────

def assert_decimal_places(value: Any, places: int, label: str) -> None:
    """Assert a numeric value carries at most `places` decimal places."""
    assert value is not None, f"{label} must not be null"
    quantised = Decimal(str(value)).normalize()
    exponent = -quantised.as_tuple().exponent
    assert exponent <= places, f"{label} must carry at most {places} decimal places, got {value!r}"


def assert_score_in_range(score: Any, label: str = "equivalency_score") -> None:
    """Assert a score sits in the closed range 0.00 through 100.00 at two decimals."""
    assert_decimal_places(score, 2, label)
    assert SCORE_MIN <= float(score) <= SCORE_MAX, f"{label} must fall within 0.00-100.00, got {score}"


def assert_risk_index_in_range(index: Any, label: str) -> None:
    """Assert a disciplinary risk index sits in 0.00 through 100.00 at two decimals."""
    assert_decimal_places(index, 2, label)
    assert 0.00 <= float(index) <= INDEX_CEILING, f"{label} must fall within 0.00-100.00, got {index}"


def assert_hours_precision(hours: Any, label: str) -> None:
    """Assert a requirement-hours figure carries exactly one decimal place at most."""
    assert_decimal_places(hours, 1, label)


def assert_cents(value: Any, label: str) -> None:
    """Assert a money figure is whole integer cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


# ─── Applications ─────────────────────────────────────

def assert_application_fields(application: Dict[str, Any], **expected: Any) -> None:
    """Assert the named application fields equal the expected values exactly."""
    for field, value in expected.items():
        actual = application.get(field)
        assert instants_equal(actual, value), (
            f"application.{field}: expected {value!r}, got {actual!r}"
        )


def assert_draft_application(application: Dict[str, Any], requirement_hours_total: float) -> None:
    """Assert a freshly opened application carries the documented DRAFT seed values."""
    assert_application_fields(
        application,
        status="DRAFT",
        submitted_at=None,
        review_deadline_at=None,
        decided_at=None,
        processing_elapsed_days=0,
        processing_standard_met=None,
        deficiency_cycle_count=0,
        statutory_waiver_pct=0.00,
        gross_total_cents=0,
        fee_balance_cents=0,
        national_exam_passed=False,
        jurisprudence_exam_passed=False,
        scope_reviewed_by_user_id=None,
        decided_by_user_id=None,
        requirement_hours_satisfied=0.0,
        requirement_hours_remaining=requirement_hours_total,
    )


def assert_hours_conserved(application: Dict[str, Any], requirement_hours_total: float) -> None:
    """Assert satisfied plus remaining equals the profession's total, remaining never negative."""
    satisfied = application.get("requirement_hours_satisfied")
    remaining = application.get("requirement_hours_remaining")
    assert_hours_precision(satisfied, "requirement_hours_satisfied")
    assert_hours_precision(remaining, "requirement_hours_remaining")
    assert remaining >= 0.0, f"requirement_hours_remaining must never be negative, got {remaining}"
    total = round(float(satisfied) + float(remaining), 1)
    assert total == requirement_hours_total, (
        f"satisfied ({satisfied}) + remaining ({remaining}) must equal "
        f"requirement_hours_total ({requirement_hours_total}), got {total}"
    )


# ─── Fee ledger ───────────────────────────────────────

def ledger_signature(entries: Iterable[Dict[str, Any]]) -> List[Tuple[str, int]]:
    """Reduce a ledger listing to an ordered list of (entry_type, amount_cents)."""
    return [(entry.get("entry_type"), entry.get("amount_cents")) for entry in entries]


def assert_ledger_signature(
    entries: Sequence[Dict[str, Any]], expected: Sequence[Tuple[str, int]]
) -> None:
    """Assert the ledger reads exactly as the expected ordered (type, amount) pairs."""
    actual = ledger_signature(entries)
    assert actual == list(expected), f"ledger expected {list(expected)}, got {actual}"
    for entry in entries:
        assert_no_audit_triplet(entry)
        assert_cents(entry.get("amount_cents"), "ledger amount_cents")


def assert_ledger_signs(entries: Iterable[Dict[str, Any]]) -> None:
    """Assert ASSESSMENT and PERMIT_FEE rows are positive and every other type negative or zero."""
    for entry in entries:
        entry_type = entry.get("entry_type")
        amount = entry.get("amount_cents")
        if entry_type in (ENTRY_ASSESSMENT, ENTRY_PERMIT_FEE):
            assert amount > 0, f"{entry_type} must carry a positive amount, got {amount}"
        else:
            assert amount <= 0, f"{entry_type} must carry a negative amount, got {amount}"


def ledger_sum(entries: Iterable[Dict[str, Any]]) -> int:
    """The arithmetic sum of every entry's `amount_cents`."""
    return sum(entry.get("amount_cents", 0) for entry in entries)


def assert_balance_matches_ledger(application: Dict[str, Any], entries: Iterable[Dict[str, Any]]) -> None:
    """Assert `fee_balance_cents` is by construction the sum of the whole ledger."""
    rows = list(entries)
    expected = ledger_sum(rows)
    actual = application.get("fee_balance_cents")
    assert actual == expected, (
        f"fee_balance_cents ({actual}) must equal the sum of the ledger ({expected})"
    )


def assert_memo(entry: Dict[str, Any], expected_memo: str) -> None:
    """Assert a ledger entry carries the fixed machine memo for its type."""
    assert entry.get("memo") == expected_memo, (
        f"expected memo {expected_memo!r}, got {entry.get('memo')!r}"
    )


# ─── Permits, licences, evaluators ────────────────────

def assert_permit_fields(permit: Dict[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        actual = permit.get(field)
        assert instants_equal(actual, value), (
            f"permit.{field}: expected {value!r}, got {actual!r}"
        )


def assert_fresh_permit(permit: Dict[str, Any]) -> None:
    """Assert a newly issued permit starts ACTIVE with all terminal fields null."""
    assert_permit_fields(
        permit, status="ACTIVE", converted_at=None, revoked_at=None, revocation_reason_code=None
    )


def assert_license_number(license_number: str, profession_code: str, sequence: int) -> None:
    """Assert the licence number is the profession code, a hyphen, then a padded sequence."""
    expected = f"{profession_code}-{str(sequence).zfill(LICENSE_SEQUENCE_WIDTH)}"
    assert license_number == expected, f"expected license_number {expected!r}, got {license_number!r}"


def assert_evaluation_fields(evaluation: Dict[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        actual = evaluation.get(field)
        assert instants_equal(actual, value), (
            f"evaluation.{field}: expected {value!r}, got {actual!r}"
        )


def assert_evaluator_fields(evaluator: Dict[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        actual = evaluator.get(field)
        assert instants_equal(actual, value), (
            f"evaluator.{field}: expected {value!r}, got {actual!r}"
        )


def assert_assignment_fields(assignment: Dict[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        actual = assignment.get(field)
        assert instants_equal(actual, value), (
            f"review assignment.{field}: expected {value!r}, got {actual!r}"
        )


def assert_applicant_fields(applicant: Dict[str, Any], **expected: Any) -> None:
    for field, value in expected.items():
        actual = applicant.get(field)
        assert instants_equal(actual, value), (
            f"applicant.{field}: expected {value!r}, got {actual!r}"
        )


def assert_fields(resource: Dict[str, Any], label: str, **expected: Any) -> None:
    """Generic exact-field comparison for any resource."""
    for field, value in expected.items():
        actual = resource.get(field)
        assert instants_equal(actual, value), (
            f"{label}.{field}: expected {value!r}, got {actual!r}"
        )
