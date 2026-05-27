"""Entity assertion helpers and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ─── Common-field assertions ──────────────────────────────────────────

def assert_common_fields(data: dict):
    """PRD §2.4 common fields for full business entities: id (UUID),
    created_at + updated_at (ISO 8601 UTC w/ three fractional digits),
    version (int starting at 1, increments on every mutation)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_lighter_common_fields(data: dict):
    """PRD §2.4 — Jurisdiction / SystemClock / AuditLog carry id + created_at
    ONLY (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")) or data.get("id") == "singleton", \
        f"id must be UUID or 'singleton': {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')!r}"


# ─── Per-entity assertions ────────────────────────────────────────────

def assert_jurisdiction(data: dict):
    """PRD §3.1: Jurisdiction carries state_code (2 uppercase letters),
    ban_the_box_enabled, salary_history_ban_enabled, pre_adverse_waiting_days."""
    assert_lighter_common_fields(data)
    sc = data.get("state_code", "")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isupper(), \
        f"state_code must be 2 uppercase letters, got {sc!r}"
    assert isinstance(data.get("ban_the_box_enabled"), bool), \
        "ban_the_box_enabled must be bool"
    assert isinstance(data.get("salary_history_ban_enabled"), bool), \
        "salary_history_ban_enabled must be bool"
    assert isinstance(data.get("pre_adverse_waiting_days"), int), \
        "pre_adverse_waiting_days must be int"
    assert data["pre_adverse_waiting_days"] >= 5, \
        "pre_adverse_waiting_days must be >= 5 (federal floor)"


def assert_applicant(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("email"), str) and data["email"]
    assert isinstance(data.get("date_of_birth"), str) and data["date_of_birth"]


def assert_application(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("applicant_id"), str)
    assert isinstance(data.get("jurisdiction_id"), str)
    assert isinstance(data.get("position_title"), str)
    assert data.get("status") in {
        "DRAFT", "SUBMITTED", "CONDITIONAL_OFFER", "HIRED", "REJECTED", "WITHDRAWN",
    }, f"unknown application status {data.get('status')!r}"


def assert_consent(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("disclosure_text_version"), str)
    assert isinstance(data.get("signed_at"), str)
    assert isinstance(data.get("ip_address"), str)
    assert data.get("consent_status") in {"PENDING", "GRANTED", "REVOKED"}, \
        f"unknown consent_status {data.get('consent_status')!r}"


def assert_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("application_id"), str)
    assert isinstance(data.get("consent_id"), str)
    assert data.get("status") in {"PENDING", "IN_REVIEW", "COMPLETE", "CANCELLED"}, \
        f"unknown order status {data.get('status')!r}"
    if data["status"] == "COMPLETE":
        assert data.get("overall_result") in {"CLEAR", "CONSIDER"}, \
            f"order COMPLETE must have CLEAR/CONSIDER overall_result, got {data.get('overall_result')!r}"


def assert_verification(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("order_id"), str)
    assert data.get("verification_type") in {"CRIMINAL", "MVR", "EDUCATION"}, \
        f"unknown verification_type {data.get('verification_type')!r}"
    assert data.get("status") in {"PENDING", "REPORTED", "DISPUTED", "RESOLVED"}, \
        f"unknown verification status {data.get('status')!r}"


def assert_adverse_action(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("order_id"), str)
    assert data.get("status") in {"PRE_ADVERSE_SENT", "DISPUTED", "FINALIZED", "CANCELLED"}, \
        f"unknown adverse-action status {data.get('status')!r}"
    assert isinstance(data.get("pre_adverse_sent_at"), str), "pre_adverse_sent_at required"
    assert isinstance(data.get("earliest_final_at"), str), "earliest_final_at required"


def assert_no_version_on_lighter_entity(data: dict):
    """PRD §2.4: Jurisdiction / SystemClock / AuditLog carry NEITHER version
    NOR updated_at — assert they are absent (a faithful implementer omits
    them; a hallucinated version=1 would fail this)."""
    # The PRD states these fields are NOT carried; we accept either complete
    # absence or null. A non-null integer/version on a lighter entity is wrong.
    assert "version" not in data or data["version"] is None, \
        f"lighter entity must not carry version, got {data.get('version')!r}"
    assert "updated_at" not in data or data["updated_at"] is None, \
        f"lighter entity must not carry updated_at, got {data.get('updated_at')!r}"
