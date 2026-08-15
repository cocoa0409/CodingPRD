"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _parse_instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str):
    """Compare two ISO-8601 UTC timestamps by instant, not by string form.

    The PRD pins the instant (e.g., the §2.4 clock default, the §3.3
    deadline math) while §2.5/§2.2 render timestamps with three fractional
    digits — an implementation may therefore serialize the same instant as
    ``...T00:00:00Z`` or ``...T00:00:00.000Z``. Assertions on business
    timestamps must compare the instant both denote.
    """
    assert is_iso8601_timestamp(actual), \
        f"not an ISO-8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"instant mismatch: {actual!r} denotes a different instant than "
        f"{expected_iso!r}")


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert isinstance(data.get("member_ref"), str) and len(data["member_ref"]) > 0
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert data.get("program") in ("MEDICARE", "MEDI_CAL", "DUAL")
    assert data.get("enrollment_status") in ("ACTIVE", "DISENROLLED", "DECEASED")
    assert isinstance(data.get("open_case_count"), int)
    assert isinstance(data.get("ctm_linked_case_count"), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int)


def assert_provider(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    npi = data.get("npi", "")
    assert isinstance(npi, str) and len(npi) == 10 and npi.isdigit(), \
        "npi must be exactly 10 digits"
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert data.get("contract_status") in ("CONTRACTED", "NON_CONTRACTED")
    assert isinstance(data.get("w9_on_file"), bool)
    assert isinstance(data.get("version"), int)


def assert_deadline_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert data.get("program") in ("MEDICARE", "MEDI_CAL", "DUAL")
    assert data.get("case_kind") in ("GRIEVANCE", "ORG_DETERMINATION", "APPEAL")
    assert data.get("priority_track") in ("STANDARD", "EXPEDITED")
    assert 0 < data.get("resolution_hours", 0) <= 720
    assert 0 <= data.get("extension_hours", -1) <= 336
    assert 0 < data.get("effectuation_hours", 0) <= 720
    assert isinstance(data.get("business_hours_only"), bool)
    assert isinstance(data.get("active"), bool)
    assert isinstance(data.get("version"), int)


def assert_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert data.get("case_kind") in ("GRIEVANCE", "ORG_DETERMINATION", "APPEAL")
    assert data.get("priority_track") in ("STANDARD", "EXPEDITED")
    assert data.get("status") in (
        "RECEIVED", "TRIAGED", "IN_REVIEW", "PENDING_CLINICAL", "DECIDED",
        "NOTIFIED", "IRE_REFERRED", "REOPENED", "CLOSED", "WITHDRAWN",
    )
    assert data.get("decision_outcome") in (
        None, "FULLY_FAVORABLE", "PARTIALLY_FAVORABLE", "UNFAVORABLE",
    )
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data.get("version"), int)


def assert_case_event(data: dict):
    # Append-only snapshot: id + created_at only — updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("event_type") in (
        "NOTE", "DOCUMENT", "EXTENSION_REQUEST", "EXTENSION_GRANTED",
        "CTM_LINKED", "CTM_UNLINKED", "PRIORITY_UPGRADE", "DECISION_RECORDED",
        "NOTIFICATION_SENT", "IRE_FORWARDED", "REOPEN_REQUESTED",
        "REOPEN_GRANTED", "REOPEN_DENIED", "EFFECTUATION_STARTED",
        "EFFECTUATION_COMPLETED",
    )
    assert isinstance(data.get("actor_role"), str) and len(data["actor_role"]) > 0
    assert isinstance(data.get("actor_id"), str) and len(data["actor_id"]) > 0
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "CaseEvent must not carry version"
    assert "updated_at" not in data, "CaseEvent must not carry updated_at"


def assert_clinical_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("status") in (
        "REQUESTED", "ASSIGNED", "DETERMINATION_DRAFT", "DETERMINED", "SUPERSEDED",
    )
    assert data.get("determination") in (None, "UPHOLD_SERVICE", "OVERTURN_SERVICE", "PARTIAL")
    score = data.get("medical_necessity_score")
    if score is not None:
        assert 0.00 <= score <= 100.00
        assert_cost_precision(score)
    assert isinstance(data.get("version"), int)


def assert_notification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("recipient_kind") in ("MEMBER", "PROVIDER")
    assert data.get("notification_kind") in (
        "ACKNOWLEDGEMENT", "EXTENSION_NOTICE", "DECISION",
        "IRE_FORWARD_NOTICE", "REOPEN_OUTCOME", "EFFECTUATION_CONFIRMATION",
    )
    assert data.get("status") in ("QUEUED", "SENT", "DELIVERED", "FAILED", "RETRIED")
    assert isinstance(data.get("required_elements"), list)
    assert isinstance(data.get("supplied_elements"), list)
    score = data.get("completeness_score")
    assert isinstance(score, (int, float))
    assert 0.00 <= score <= 1.00
    assert_cost_precision(score)
    assert isinstance(data.get("version"), int)


def assert_ire_referral(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data.get("ire_organization_code"), str)
    assert data.get("status") in (
        "FORWARDED", "ACKNOWLEDGED_BY_IRE", "DECISION_RECEIVED", "EFFECTUATED",
    )
    assert data.get("ire_decision") in (None, "UPHOLD_PLAN", "OVERTURN_PLAN", "PARTIAL")
    assert is_iso8601_timestamp(data.get("forwarded_at", ""))
    assert isinstance(data.get("version"), int)


def assert_effectuation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("status") in (
        "PENDING", "IN_PROGRESS", "EFFECTUATED", "OVERDUE", "ESCALATED", "WAIVED",
    )
    assert isinstance(data.get("payment_amount_cents"), int)
    assert data["payment_amount_cents"] >= 0
    tp = data.get("timeliness_percent")
    if tp is not None:
        assert isinstance(tp, (int, float))
        assert tp >= 0.0
        assert_cost_precision(tp)
    assert isinstance(data.get("version"), int)


def assert_reopening(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("request_reason") in (
        "NEW_EVIDENCE", "CLERICAL_ERROR", "FRAUD_OR_SIMILAR_FAULT",
    )
    assert data.get("status") in ("REQUESTED", "UNDER_REVIEW", "GRANTED", "DENIED")
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert isinstance(data.get("version"), int)


def assert_audit_record(data: dict):
    # Append-only snapshot: id + created_at only — updated_at and version absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert isinstance(data.get("report_period"), str) and len(data["report_period"]) == 7
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert data.get("case_kind") in ("GRIEVANCE", "ORG_DETERMINATION", "APPEAL")
    assert data.get("priority_track") in ("STANDARD", "EXPEDITED")
    assert isinstance(data.get("resolution_timely"), bool)
    assert data.get("effectuation_timely") in (None, True, False)
    assert is_iso8601_timestamp(data.get("snapshot_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "AuditUniverseRecord must not carry version"
    assert "updated_at" not in data, "AuditUniverseRecord must not carry updated_at"
