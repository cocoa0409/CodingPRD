"""Entity assertion helpers and domain invariant checks.

PRD §2.4 sets the canonical envelope rules:
  - Mutable entities (TestEvent, TestCenter, TestCenterCapacity,
    Candidate, Registration, AccommodationRequest, IDVerification) carry
    id + created_at + updated_at + version.
  - Immutable / append-only entities (ScoreReport, CLEPCreditAward,
    RefundTransaction) carry only id + created_at — updated_at and
    version are absent.

PRD §2.6 pins integer-cent precision everywhere. Helpers in this file
encode each rule from the PRD prose.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


VALID_TEST_TYPES = {"SAT", "ACT", "AP", "CLEP"}
VALID_TEST_EVENT_STATUSES = {
    "REGISTRATION_OPEN", "REGISTRATION_CLOSED", "SCORES_PENDING", "COMPLETED",
}
VALID_TEST_CENTER_STATUSES = {"ACTIVE", "SUSPENDED"}
VALID_REGISTRATION_STATUSES = {
    "STANDBY", "CONFIRMED", "CHECKED_IN", "NO_SHOW", "COMPLETED", "CANCELLED",
}
VALID_REGISTRATION_CHANNELS = {"SELF_INITIATED", "OFFICIAL_CANCELLATION"}
VALID_ID_DOCUMENT_TYPES = {
    "DRIVERS_LICENSE", "STATE_ID", "PASSPORT", "SCHOOL_ID_WITH_PHOTO",
}
VALID_ID_VERIFICATION_STATUSES = {
    "NOT_STARTED", "DOCS_SUBMITTED", "CLEARED", "REJECTED",
}
VALID_ACCOMMODATION_STATUSES = {
    "SUBMITTED", "UNDER_REVIEW", "NEEDS_MORE_INFO",
    "APPROVED", "DENIED", "EXPIRED",
}
VALID_ACCOMMODATION_KINDS = {
    "EXTENDED_TIME_50", "EXTENDED_TIME_100", "BREAKS_EXTENDED",
    "READER", "SCRIBE", "LARGE_PRINT",
}
VALID_SCORE_REPORT_TYPES = {"OFFICIAL", "RESCORED"}
VALID_CLEP_STATUSES = {"AWARDED", "DENIED"}
VALID_REFUND_TIER_LABELS = {"FULL", "PARTIAL_75", "PARTIAL_50", "NONE"}


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: id + created_at + updated_at + version (integer >= 1)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_common_append_only(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: append-only entities carry only id + created_at.

    "A `ScoreReport`, a `CLEPCreditAward`, and a `RefundTransaction`
    each carry only an `id` and a `created_at` — they have no
    `updated_at` and no `version`, because they are never updated in
    place after they are first created."
    """
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    # PRD says these fields are not present on append-only rows; tolerate
    # only an explicit None if the key is present.
    if "updated_at" in data:
        assert data["updated_at"] is None, (
            f"{label} is append-only per PRD §2.4 and must not carry "
            f"updated_at; got {data['updated_at']!r}"
        )
    if "version" in data:
        assert data["version"] is None, (
            f"{label} is append-only per PRD §2.4 and must not carry "
            f"version; got {data['version']!r}"
        )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------
def assert_test_event(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "TestEvent")
    assert data.get("test_type") in VALID_TEST_TYPES
    assert isinstance(data.get("form_code"), str) and data["form_code"]
    # subject is optional / nullable per PRD §3.1.
    assert "subject" in data
    assert is_iso8601_timestamp(data["test_date"])
    assert is_iso8601_timestamp(data["registration_deadline"])
    assert is_iso8601_timestamp(data["late_registration_deadline"])
    assert is_iso8601_timestamp(data["score_release_date"])
    assert isinstance(data["base_fee_cents"], int) and data["base_fee_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data["status"] in VALID_TEST_EVENT_STATUSES


def assert_test_center(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "TestCenter")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("address"), str) and data["address"]
    assert isinstance(data.get("state_code"), str)
    assert len(data["state_code"]) == 2
    assert isinstance(data.get("timezone"), str) and data["timezone"]
    assert data.get("status") in VALID_TEST_CENTER_STATUSES


def assert_test_center_capacity(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "TestCenterCapacity")
    assert is_valid_uuid(data.get("test_event_id", ""))
    assert is_valid_uuid(data.get("test_center_id", ""))
    assert isinstance(data["total_capacity"], int) and data["total_capacity"] >= 0
    assert isinstance(data["accommodation_capacity"], int)
    assert 0 <= data["accommodation_capacity"] <= data["total_capacity"]
    for f in ("confirmed_seats_used", "accommodation_seats_used",
              "standby_seats_pending", "available_seats"):
        assert isinstance(data[f], int) and data[f] >= 0, (
            f"TestCenterCapacity.{f} must be a non-negative integer"
        )
    # PRD §2.8 invariant: available_seats + confirmed_seats_used == total_capacity.
    assert data["available_seats"] + data["confirmed_seats_used"] == data["total_capacity"], (
        "PRD §2.8: available_seats + confirmed_seats_used must equal total_capacity"
    )


def assert_candidate(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Candidate")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("home_state_code"), str) and len(data["home_state_code"]) == 2
    assert isinstance(data.get("has_iep_or_504"), bool)


def assert_registration(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "Registration")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("test_event_id", ""))
    assert is_valid_uuid(data.get("test_center_id", ""))
    assert data.get("status") in VALID_REGISTRATION_STATUSES
    assert is_iso8601_timestamp(data.get("registered_at", ""))
    assert data.get("registration_channel") in VALID_REGISTRATION_CHANNELS
    assert isinstance(data.get("accommodation_required"), bool)
    for f in ("base_fee_cents_charged", "late_fee_cents_charged",
              "accommodation_fee_cents_charged", "amount_charged_cents",
              "amount_refunded_cents", "amount_retained_cents"):
        assert isinstance(data[f], int), f"Registration.{f} must be int (PRD §2.6)"
        assert data[f] >= 0, f"Registration.{f} must be >= 0"
    # PRD §2.6 money invariant: charged == refunded + retained.
    assert data["amount_charged_cents"] == data["amount_refunded_cents"] + data["amount_retained_cents"], (
        "PRD §3.4 / §3.8: amount_charged_cents must equal "
        "amount_refunded_cents + amount_retained_cents"
    )


def assert_id_verification(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "IDVerification")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert data.get("id_document_type") in VALID_ID_DOCUMENT_TYPES
    # issuing_state_code is optional (PASSPORT exempt).
    if data.get("issuing_state_code") is not None:
        assert isinstance(data["issuing_state_code"], str)
        assert len(data["issuing_state_code"]) == 2
    assert isinstance(data.get("id_expires_on"), str)
    assert data.get("status") in VALID_ID_VERIFICATION_STATUSES
    assert isinstance(data.get("cross_state_override_granted"), bool)


def assert_accommodation_request(data: Dict[str, Any]) -> None:
    _assert_common_mutable(data, "AccommodationRequest")
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert is_valid_uuid(data.get("test_event_id", ""))
    accs = data.get("requested_accommodations") or []
    assert isinstance(accs, list)
    for a in accs:
        assert a in VALID_ACCOMMODATION_KINDS, (
            f"unexpected accommodation kind {a!r}"
        )
    docs = data.get("supporting_documents") or []
    assert isinstance(docs, list)
    assert data.get("status") in VALID_ACCOMMODATION_STATUSES
    assert is_iso8601_timestamp(data.get("submission_deadline_at", ""))
    assert is_iso8601_timestamp(data.get("review_deadline_at", ""))


def assert_score_report(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "ScoreReport")
    assert is_valid_uuid(data.get("registration_id", ""))
    sections = data.get("section_scores")
    assert isinstance(sections, dict) and sections
    for v in sections.values():
        assert isinstance(v, int)
    assert isinstance(data.get("total_score"), int)
    assert data.get("report_type") in VALID_SCORE_REPORT_TYPES


def assert_clep_credit_award(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "CLEPCreditAward")
    assert is_valid_uuid(data.get("score_report_id", ""))
    assert is_valid_uuid(data.get("candidate_id", ""))
    assert data.get("credit_status") in VALID_CLEP_STATUSES
    assert isinstance(data.get("credit_units"), int) and data["credit_units"] >= 0
    # PRD §3.10: "the field is recorded on both `AWARDED` and `DENIED` outcomes."
    assert isinstance(data.get("posted_by_user_id"), str) and data["posted_by_user_id"]


def assert_refund_transaction(data: Dict[str, Any]) -> None:
    _assert_common_append_only(data, "RefundTransaction")
    assert is_valid_uuid(data.get("registration_id", ""))
    assert isinstance(data.get("amount_cents"), int)
    # PRD §3.8: "the maximum of zero and the computed total; it can be
    # zero but is never negative."
    assert data["amount_cents"] >= 0
    assert data.get("tier_label") in VALID_REFUND_TIER_LABELS
    assert data.get("refund_channel") in VALID_REGISTRATION_CHANNELS


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_money_invariant(registration: Dict[str, Any]) -> None:
    """PRD §3.4 / §3.8 / §2.6: amount_charged_cents must equal
    amount_refunded_cents + amount_retained_cents at every observable
    instant."""
    charged = registration["amount_charged_cents"]
    refunded = registration["amount_refunded_cents"]
    retained = registration["amount_retained_cents"]
    assert charged == refunded + retained, (
        f"Money conservation broken: charged={charged}, "
        f"refunded={refunded}, retained={retained}; "
        f"PRD §3.4 / §3.8 require charged == refunded + retained"
    )


def assert_capacity_invariant(capacity: Dict[str, Any]) -> None:
    """PRD §2.8: total_capacity == confirmed_seats_used + available_seats."""
    total = capacity["total_capacity"]
    used = capacity["confirmed_seats_used"]
    avail = capacity["available_seats"]
    assert total == used + avail, (
        f"PRD §2.8 capacity invariant broken: total={total}, "
        f"confirmed_seats_used={used}, available_seats={avail}"
    )
    assert avail >= 0, (
        "PRD §2.8: available_seats must never be negative"
    )


def assert_version_bumped(before: Dict[str, Any],
                          after: Dict[str, Any]) -> None:
    """PRD §2.4: "version ... begins at 1 on creation and increments by
    1 on every mutating write"."""
    assert after["version"] == before["version"] + 1, (
        f"PRD §2.4: version must increment by 1 on a mutating write; "
        f"before={before['version']}, after={after['version']}"
    )


__all__ = [
    "VALID_TEST_TYPES",
    "VALID_TEST_EVENT_STATUSES",
    "VALID_TEST_CENTER_STATUSES",
    "VALID_REGISTRATION_STATUSES",
    "VALID_REGISTRATION_CHANNELS",
    "VALID_ID_DOCUMENT_TYPES",
    "VALID_ID_VERIFICATION_STATUSES",
    "VALID_ACCOMMODATION_STATUSES",
    "VALID_ACCOMMODATION_KINDS",
    "VALID_SCORE_REPORT_TYPES",
    "VALID_CLEP_STATUSES",
    "VALID_REFUND_TIER_LABELS",
    "assert_test_event",
    "assert_test_center",
    "assert_test_center_capacity",
    "assert_candidate",
    "assert_registration",
    "assert_id_verification",
    "assert_accommodation_request",
    "assert_score_report",
    "assert_clep_credit_award",
    "assert_refund_transaction",
    "assert_money_invariant",
    "assert_capacity_invariant",
    "assert_version_bumped",
]
