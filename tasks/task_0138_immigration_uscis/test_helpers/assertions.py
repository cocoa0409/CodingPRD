"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract.

PRD §2.5: every persisted resource carries id + created_at +
updated_at + version EXCEPT CaseTypeConfig, VisaBulletin, and
CaseEvent which are lean (id + created_at + own immutable fields
only).
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    CASE_STATUSES,
    CASE_TYPES,
    CHART_TYPES,
    INTERVIEW_OUTCOMES,
    PREFERENCE_CATEGORIES,
    PREFERENCE_CATEGORIES_BULLETIN,
    PRIORITY_DATE_STATUSES,
    RECEIPT_NUMBER_LENGTH,
    RECEIPT_PREFIXES,
    RELATIONSHIPS,
    RFE_REASON_CODES,
    SCORE_CEILING,
    SCORE_FLOOR,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.5
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.5: 'a monotonic integer version that increments by one
    on every mutation'."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got "
        f"{data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Petitioner — PRD §3.1
# ---------------------------------------------------------------------------
def assert_petitioner(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    coc = data.get("country_of_citizenship")
    assert isinstance(coc, str) and len(coc) == 3 and coc.isupper()
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    a_number = data.get("a_number")
    assert a_number is None or (
        isinstance(a_number, str)
        and len(a_number) == 10
        and a_number[0] == "A"
        and a_number[1:].isdigit()
    ), f"a_number must match A\\d{{9}} when present, got {a_number!r}"


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.1
# ---------------------------------------------------------------------------
def assert_beneficiary(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("petitioner_id"), str)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    coc = data.get("country_of_chargeability")
    assert isinstance(coc, str) and len(coc) == 3 and coc.isupper()
    assert data.get("preference_category") in PREFERENCE_CATEGORIES
    assert data.get("relationship_to_petitioner") in RELATIONSHIPS


# ---------------------------------------------------------------------------
# CaseTypeConfig — PRD §3.3 (append-only)
# ---------------------------------------------------------------------------
def assert_case_type_config(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.5: "a CaseTypeConfig row only carries id and created_at".
    # The other fields below are the row's own immutable fields.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "CaseTypeConfig must NOT carry updated_at per PRD §2.5"
    )
    assert "version" not in data or data.get("version") is None, (
        "CaseTypeConfig must NOT carry version per PRD §2.5"
    )
    assert data.get("case_type") in CASE_TYPES
    assert isinstance(data.get("requires_biometrics"), bool)
    assert isinstance(data.get("requires_interview"), bool)
    assert isinstance(data.get("rfe_response_window_days"), int)
    assert data["rfe_response_window_days"] > 0
    assert isinstance(data.get("requires_priority_date_current"), bool)
    assert data.get("receipt_prefix") in RECEIPT_PREFIXES


# ---------------------------------------------------------------------------
# Case — PRD §3.2
# ---------------------------------------------------------------------------
def assert_case(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("petitioner_id"), str)
    assert isinstance(data.get("beneficiary_id"), str)
    assert data.get("case_type") in CASE_TYPES
    assert data.get("status") in CASE_STATUSES
    assert data.get("priority_date_status") in PRIORITY_DATE_STATUSES
    # receipt_number is null in DRAFT, minted on FILED.
    rn = data.get("receipt_number")
    assert rn is None or (
        isinstance(rn, str) and len(rn) == RECEIPT_NUMBER_LENGTH
    ), (
        f"receipt_number must be null or exactly "
        f"{RECEIPT_NUMBER_LENGTH} chars, got {rn!r}"
    )


def assert_receipt_number_format(receipt_number: str,
                                 expected_prefix: str) -> None:
    """PRD §2.7: 'Receipt Numbers are exactly 13 characters long'. The
    layout is 3-letter prefix + 2-digit year + 3-digit day-of-fiscal-
    year + 5-digit sequence.
    """
    assert isinstance(receipt_number, str)
    assert len(receipt_number) == RECEIPT_NUMBER_LENGTH, (
        f"receipt_number must be {RECEIPT_NUMBER_LENGTH} chars, "
        f"got {len(receipt_number)} ({receipt_number!r})"
    )
    assert receipt_number[:3] == expected_prefix, (
        f"receipt_number prefix must be {expected_prefix!r}, got "
        f"{receipt_number[:3]!r}"
    )
    assert receipt_number[3:].isdigit(), (
        f"receipt_number trailing must be 10 digits, got "
        f"{receipt_number[3:]!r}"
    )


# ---------------------------------------------------------------------------
# Biometrics — PRD §3.4
# ---------------------------------------------------------------------------
def assert_biometrics(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("case_id"), str)
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    lc = data.get("location_code")
    assert isinstance(lc, str) and 4 <= len(lc) <= 6, (
        f"location_code must be 4..6 chars, got {lc!r}"
    )
    assert data.get("status") in {
        "SCHEDULED", "COMPLETED", "NO_SHOW", "RESCHEDULED", "CANCELLED",
    }
    rc = data.get("reschedule_count")
    assert isinstance(rc, int) and 0 <= rc <= 3, (
        f"reschedule_count must be int in [0,3], got {rc!r}"
    )


# ---------------------------------------------------------------------------
# RFE — PRD §3.5
# ---------------------------------------------------------------------------
def assert_rfe(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("case_id"), str)
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("deadline_at", ""))
    assert data.get("reason_code") in RFE_REASON_CODES
    notes = data.get("officer_notes")
    assert isinstance(notes, str) and 1 <= len(notes) <= 2000
    assert data.get("status") in {"OUTSTANDING", "RESPONDED", "EXPIRED"}


# ---------------------------------------------------------------------------
# Interview — PRD §3.6
# ---------------------------------------------------------------------------
def assert_interview(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("case_id"), str)
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    foc = data.get("field_office_code")
    assert isinstance(foc, str) and 3 <= len(foc) <= 5
    assert data.get("status") in {
        "SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED",
    }
    outcome = data.get("outcome")
    assert outcome is None or outcome in INTERVIEW_OUTCOMES


# ---------------------------------------------------------------------------
# VisaBulletin — PRD §3.9 (append-only)
# ---------------------------------------------------------------------------
def assert_visa_bulletin(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.5: VisaBulletin carries id, created_at, and published_at
    # only — no updated_at / version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "VisaBulletin must NOT carry updated_at per PRD §2.5"
    )
    assert "version" not in data or data.get("version") is None, (
        "VisaBulletin must NOT carry version per PRD §2.5"
    )
    bm = data.get("bulletin_month")
    assert isinstance(bm, str) and len(bm) == 7 and bm[4] == "-", (
        f"bulletin_month must be YYYY-MM, got {bm!r}"
    )
    assert data.get("chart_type") in CHART_TYPES
    assert data.get("preference_category") in PREFERENCE_CATEGORIES_BULLETIN
    country = data.get("country")
    assert country == "ROW" or (
        isinstance(country, str)
        and len(country) == 3
        and country.isupper()
    )
    assert isinstance(data.get("cutoff_date"), str)
    assert is_iso8601_timestamp(data.get("published_at", ""))


# ---------------------------------------------------------------------------
# CaseEvent — PRD §2.10 (append-only)
# ---------------------------------------------------------------------------
def assert_case_event(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.5: "a CaseEvent carries only id, created_at, and its own
    # occurred_at" — append-only.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "CaseEvent must NOT carry updated_at per PRD §2.5"
    )
    assert "version" not in data or data.get("version") is None, (
        "CaseEvent must NOT carry version per PRD §2.5"
    )
    assert isinstance(data.get("case_id"), str)
    assert isinstance(data.get("event_type"), str) and data["event_type"]
    assert isinstance(data.get("actor_role"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# ---------------------------------------------------------------------------
# Case-summary completeness score — PRD §3.11
# ---------------------------------------------------------------------------
def assert_completeness_score(score: Any) -> None:
    """PRD §3.11: 'the result is clamped into the inclusive 0-to-100
    integer range'."""
    assert isinstance(score, int), (
        f"case_completeness_score must be int, got {score!r}"
    )
    assert SCORE_FLOOR <= score <= SCORE_CEILING, (
        f"case_completeness_score must be in [{SCORE_FLOOR},"
        f"{SCORE_CEILING}], got {score}"
    )


def assert_version_incremented_by_one(before: Dict[str, Any],
                                      after: Dict[str, Any]) -> None:
    """PRD §2.6: 'Successful mutation increments version by exactly
    one'."""
    assert "version" in before and "version" in after
    assert after["version"] == before["version"] + 1, (
        f"version must advance by 1: before={before['version']} "
        f"after={after['version']}"
    )


__all__ = [
    "assert_petitioner",
    "assert_beneficiary",
    "assert_case_type_config",
    "assert_case",
    "assert_receipt_number_format",
    "assert_biometrics",
    "assert_rfe",
    "assert_interview",
    "assert_visa_bulletin",
    "assert_case_event",
    "assert_completeness_score",
    "assert_version_incremented_by_one",
]
