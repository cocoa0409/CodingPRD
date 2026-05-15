"""Entity assertions and domain invariant checkers.

Per PRD §2.4: Company, HrUser, JobPosting, Candidate, Application,
InterviewRound, Offer, Onboarding, HeadhunterContract carry
id/created_at/updated_at/version. CommissionRecord and AuditEvent
carry only id + created_at (no updated_at, no version).
"""
from __future__ import annotations

from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field assertion helpers
# ---------------------------------------------------------------------------
def _assert_mutable_common(data: dict, entity_label: str) -> None:
    """id/created_at/updated_at/version present and well-formed."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be positive integer, "
        f"got {data.get('version')!r}"
    )


def _assert_append_only_common(data: dict, entity_label: str) -> None:
    """id + created_at present; updated_at/version must NOT appear
    (PRD §2.4: CommissionRecord and AuditEvent omit updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, "
        f"got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Company
# ---------------------------------------------------------------------------
COMPANY_VERIFICATION_STATES = (
    "DRAFT", "PENDING", "VERIFIED", "EXPIRED", "BLACKLISTED",
)
COMPANY_TIERS = ("BASIC", "PREMIUM")
COMPANY_INDUSTRIES = (
    "TECH", "FINANCE", "MANUFACTURING", "RETAIL",
    "HEALTHCARE", "EDUCATION", "OTHER",
)
COMPANY_SIZE_BANDS = ("SMALL", "MEDIUM", "LARGE", "ENTERPRISE")


def assert_company(data: dict) -> None:
    _assert_mutable_common(data, "Company")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["business_license_number"], str)
    assert data["industry"] in COMPANY_INDUSTRIES, (
        f"Company.industry={data['industry']!r}"
    )
    assert data["size_band"] in COMPANY_SIZE_BANDS, (
        f"Company.size_band={data['size_band']!r}"
    )
    assert data["verification_status"] in COMPANY_VERIFICATION_STATES, (
        f"Company.verification_status={data['verification_status']!r}"
    )
    assert data["verification_tier"] in COMPANY_TIERS, (
        f"Company.verification_tier={data['verification_tier']!r}"
    )
    assert isinstance(data["active_job_posting_count"], int)
    assert data["active_job_posting_count"] >= 0
    assert isinstance(data["posting_quota_limit"], int)
    assert data["posting_quota_limit"] >= 0


# ---------------------------------------------------------------------------
# HrUser
# ---------------------------------------------------------------------------
HR_BINDING_STATES = ("PENDING", "ACTIVE", "REVOKED")


def assert_hr_user(data: dict) -> None:
    _assert_mutable_common(data, "HrUser")
    assert isinstance(data["company_id"], str) and data["company_id"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["display_name"], str)
    assert data["binding_status"] in HR_BINDING_STATES, (
        f"HrUser.binding_status={data['binding_status']!r}"
    )


# ---------------------------------------------------------------------------
# JobPosting
# ---------------------------------------------------------------------------
POSTING_STATES = (
    "DRAFT", "UNDER_REVIEW", "REJECTED", "LIVE", "OFF_SHELF", "EXPIRED",
)
POSTING_REJECTION_REASONS = (
    "DISCRIMINATORY_WORDING", "ILLEGAL_TERMS", "DUPLICATE", "OTHER",
)


def assert_job_posting(data: dict) -> None:
    _assert_mutable_common(data, "JobPosting")
    assert isinstance(data["company_id"], str) and data["company_id"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["description"], str)
    assert isinstance(data["salary_min_cents"], int)
    assert isinstance(data["salary_max_cents"], int)
    assert isinstance(data["benefits"], list)
    assert data["posting_status"] in POSTING_STATES, (
        f"JobPosting.posting_status={data['posting_status']!r}"
    )
    rrr = data.get("review_rejection_reason")
    if rrr is not None:
        assert rrr in POSTING_REJECTION_REASONS, (
            f"JobPosting.review_rejection_reason={rrr!r}"
        )
    assert isinstance(data["application_count"], int)
    assert data["application_count"] >= 0


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
VISIBILITY_MODES = ("PUBLIC", "COMPANY_ONLY", "HIDDEN")


def assert_candidate(data: dict) -> None:
    _assert_mutable_common(data, "Candidate")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["visibility_mode"] in VISIBILITY_MODES, (
        f"Candidate.visibility_mode={data['visibility_mode']!r}"
    )


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
APPLICATION_STATES = (
    "SUBMITTED", "READ", "FORWARDED", "INTERVIEW", "REJECTED", "CLOSED",
)
SOURCE_CHANNELS = ("DIRECT", "ONE_CLICK", "HEADHUNTER")


def assert_application(data: dict) -> None:
    _assert_mutable_common(data, "Application")
    assert isinstance(data["candidate_id"], str)
    assert isinstance(data["job_posting_id"], str)
    assert isinstance(data["company_id"], str)
    assert data["application_status"] in APPLICATION_STATES, (
        f"Application.application_status={data['application_status']!r}"
    )
    assert data["source_channel"] in SOURCE_CHANNELS, (
        f"Application.source_channel={data['source_channel']!r}"
    )


# ---------------------------------------------------------------------------
# InterviewRound
# ---------------------------------------------------------------------------
INTERVIEW_MODES = ("ONSITE", "PHONE", "VIDEO")
ROUND_STATES = (
    "DRAFT", "AWAITING_CANDIDATE", "SCHEDULED",
    "FEEDBACK_PENDING", "PASSED", "FAILED", "CANCELLED",
)
FEEDBACK_DECISIONS = ("PASS", "FAIL", "HOLD")


def assert_interview_round(data: dict) -> None:
    _assert_mutable_common(data, "InterviewRound")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["mode"] in INTERVIEW_MODES, (
        f"InterviewRound.mode={data['mode']!r}"
    )
    assert isinstance(data["interviewer_user_ids"], list)
    assert data["round_status"] in ROUND_STATES, (
        f"InterviewRound.round_status={data['round_status']!r}"
    )
    fd = data.get("feedback_decision")
    if fd is not None:
        assert fd in FEEDBACK_DECISIONS, (
            f"InterviewRound.feedback_decision={fd!r}"
        )


# ---------------------------------------------------------------------------
# Offer
# ---------------------------------------------------------------------------
OFFER_STATES = (
    "DRAFT", "PENDING_HM", "PENDING_HR", "PENDING_FINANCE",
    "ISSUED", "ACCEPTED", "DECLINED", "EXPIRED", "RESCINDED",
)
RESCISSION_REASONS = (
    "BUSINESS_NEED", "BACKGROUND_FAIL", "CANDIDATE_MISREP", "OTHER",
)


def assert_offer(data: dict) -> None:
    _assert_mutable_common(data, "Offer")
    assert isinstance(data["application_id"], str)
    assert isinstance(data["company_id"], str)
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["sign_on_bonus_cents"], int)
    assert data["offer_status"] in OFFER_STATES, (
        f"Offer.offer_status={data['offer_status']!r}"
    )
    rr = data.get("rescission_reason")
    if rr is not None:
        assert rr in RESCISSION_REASONS, (
            f"Offer.rescission_reason={rr!r}"
        )


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------
CHECK_STATES = ("PENDING", "PASSED", "FAILED", "WAIVED")
ONBOARDING_STATES = (
    "SCHEDULED", "CHECKS_RUNNING", "READY", "ONBOARDED",
    "NO_SHOW", "PROBATION_PASSED", "PROBATION_FAILED",
)


def assert_onboarding(data: dict) -> None:
    _assert_mutable_common(data, "Onboarding")
    assert isinstance(data["offer_id"], str)
    assert data["background_check_status"] in CHECK_STATES, (
        f"Onboarding.background_check_status="
        f"{data['background_check_status']!r}"
    )
    assert data["medical_check_status"] in CHECK_STATES, (
        f"Onboarding.medical_check_status={data['medical_check_status']!r}"
    )
    assert data["onboarding_status"] in ONBOARDING_STATES, (
        f"Onboarding.onboarding_status={data['onboarding_status']!r}"
    )


# ---------------------------------------------------------------------------
# HeadhunterContract
# ---------------------------------------------------------------------------
FEE_MODELS = ("SUCCESS_FEE", "RETAINER", "HYBRID")
TRIGGER_EVENTS = ("OFFER_ACCEPTED", "ONBOARDED", "PROBATION_PASSED")
CONTRACT_STATES = ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_headhunter_contract(data: dict) -> None:
    _assert_mutable_common(data, "HeadhunterContract")
    assert isinstance(data["headhunter_user_id"], str)
    assert isinstance(data["company_id"], str)
    assert data["fee_model"] in FEE_MODELS, (
        f"HeadhunterContract.fee_model={data['fee_model']!r}"
    )
    assert data["trigger_event"] in TRIGGER_EVENTS, (
        f"HeadhunterContract.trigger_event={data['trigger_event']!r}"
    )
    assert data["contract_status"] in CONTRACT_STATES, (
        f"HeadhunterContract.contract_status={data['contract_status']!r}"
    )


# ---------------------------------------------------------------------------
# CommissionRecord (append-only — no updated_at/version, PRD §2.4)
# ---------------------------------------------------------------------------
SETTLEMENT_STATES = ("ACCRUED", "SETTLED", "CLAWED_BACK")


def assert_commission_record(data: dict) -> None:
    _assert_append_only_common(data, "CommissionRecord")
    # PRD §2.4: CommissionRecord does not expose updated_at or version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "CommissionRecord must not expose updated_at "
        "(PRD §2.4: 'expose only id and created_at')"
    )
    assert "version" not in data or data.get("version") is None, (
        "CommissionRecord must not expose version "
        "(PRD §2.4: 'expose only id and created_at')"
    )
    assert isinstance(data["headhunter_contract_id"], str)
    assert isinstance(data["application_id"], str)
    assert isinstance(data["gross_commission_cents"], int)
    assert isinstance(data["tax_withheld_cents"], int)
    assert isinstance(data["net_settlement_cents"], int)
    assert data["settlement_status"] in SETTLEMENT_STATES, (
        f"CommissionRecord.settlement_status={data['settlement_status']!r}"
    )
    assert data["trigger_kind"] in TRIGGER_EVENTS, (
        f"CommissionRecord.trigger_kind={data['trigger_kind']!r}"
    )
    assert isinstance(data["clawback_amount_cents"], int)


def assert_commission_settlement_invariant(data: dict) -> None:
    """PRD §3.8 closing invariant: 'At any terminal state, the invariant
    net_settlement_cents plus clawback_amount_cents equals
    gross_commission_cents minus tax_withheld_cents holds by construction.'
    """
    if data["settlement_status"] in ("SETTLED", "CLAWED_BACK"):
        lhs = data["net_settlement_cents"] + data["clawback_amount_cents"]
        rhs = data["gross_commission_cents"] - data["tax_withheld_cents"]
        assert lhs == rhs, (
            f"Commission invariant breach: net+clawback={lhs} != "
            f"gross-tax={rhs} for record id={data.get('id')}, "
            f"status={data['settlement_status']}"
        )


# ---------------------------------------------------------------------------
# AuditEvent (append-only)
# ---------------------------------------------------------------------------
AUDIT_EVENT_KINDS = (
    "STATE_TRANSITION", "COMMISSION_ACCRUED",
    "COMMISSION_SETTLED", "COMMISSION_CLAWBACK",
)
AUDIT_SUBJECT_ENTITIES = (
    "Company", "JobPosting", "Application", "InterviewRound",
    "Offer", "Onboarding", "CommissionRecord",
)


def assert_audit_event(data: dict) -> None:
    _assert_append_only_common(data, "AuditEvent")
    # PRD §2.4: AuditEvent does not expose updated_at or version.
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "AuditEvent must not expose updated_at"
    )
    assert "version" not in data or data.get("version") is None, (
        "AuditEvent must not expose version"
    )
    assert data["subject_entity"] in AUDIT_SUBJECT_ENTITIES, (
        f"AuditEvent.subject_entity={data['subject_entity']!r}"
    )
    assert isinstance(data["subject_id"], str)
    assert data["event_kind"] in AUDIT_EVENT_KINDS, (
        f"AuditEvent.event_kind={data['event_kind']!r}"
    )
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)


# ---------------------------------------------------------------------------
# Helpers for finding rows in lists / audit logs.
# ---------------------------------------------------------------------------
def find_audit_events(
    events: Iterable[dict],
    *,
    subject_entity: Optional[str] = None,
    subject_id: Optional[str] = None,
    event_kind: Optional[str] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
) -> list:
    out = []
    for ev in events:
        if subject_entity is not None and ev.get("subject_entity") != subject_entity:
            continue
        if subject_id is not None and ev.get("subject_id") != subject_id:
            continue
        if event_kind is not None and ev.get("event_kind") != event_kind:
            continue
        if from_state is not None and ev.get("from_state") != from_state:
            continue
        if to_state is not None and ev.get("to_state") != to_state:
            continue
        out.append(ev)
    return out


def assert_version_bumped(before: dict, after: dict) -> None:
    """PRD §2.4: 'a monotonically increasing integer that starts at 1 on
    creation and increments by one on every persisted mutation.'"""
    assert after["version"] == before["version"] + 1, (
        f"version expected {before['version'] + 1}, got {after['version']}"
    )


__all__ = [
    "assert_company",
    "assert_hr_user",
    "assert_job_posting",
    "assert_candidate",
    "assert_application",
    "assert_interview_round",
    "assert_offer",
    "assert_onboarding",
    "assert_headhunter_contract",
    "assert_commission_record",
    "assert_commission_settlement_invariant",
    "assert_audit_event",
    "find_audit_events",
    "assert_version_bumped",
]
