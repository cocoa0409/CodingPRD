"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssignmentRole,
    AuditStatus,
    CallAssignmentStatus,
    CaseAssignmentStatus,
    CaseStatus,
    ClaimStatus,
    FindingSeverity,
    FindingStatus,
    FindingType,
    ModifierCode,
    PhysicalStatus,
    ProviderStatus,
    ProviderType,
    RiskBand,
    SiteStatus,
    RosterLifecycle,
    RosterPosture,
    StipendEntryStatus,
    StipendEntryType,
)


def _assert_common(data: dict, context: str):
    """The four common properties every persisted resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{context}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{context}: version must be an integer"


def assert_site(data: dict):
    _assert_common(data, "Site")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("status") in [s.value for s in SiteStatus]


def assert_provider(data: dict):
    _assert_common(data, "Provider")
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert data.get("provider_type") in [t.value for t in ProviderType]
    assert isinstance(data.get("npi"), str) and len(data["npi"]) > 0
    assert isinstance(data.get("credential_expires_on"), str)
    assert isinstance(data.get("dea_expires_on"), str)
    assert data.get("status") in [s.value for s in ProviderStatus]


def assert_roster(data: dict):
    _assert_common(data, "DailyRoster")
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data.get("service_date"), str)
    assert isinstance(data.get("required_primary_slots"), int)
    assert data["required_primary_slots"] >= 0
    assert isinstance(data.get("scheduled_day_end_minute"), int)
    assert 0 <= data["scheduled_day_end_minute"] <= 1438
    assert data.get("lifecycle") in [s.value for s in RosterLifecycle]
    assert data.get("posture") in [s.value for s in RosterPosture]


def assert_case(data: dict):
    _assert_common(data, "AnesthesiaCase")
    assert is_valid_uuid(data.get("roster_id", ""))
    assert isinstance(data.get("procedure_code"), str) and len(data["procedure_code"]) > 0
    assert data.get("physical_status") in [s.value for s in PhysicalStatus]
    assert isinstance(data.get("emergency_flag"), bool)
    assert isinstance(data.get("scheduled_start_minute"), int)
    assert isinstance(data.get("scheduled_end_minute"), int)
    assert 0 <= data["scheduled_start_minute"] < data["scheduled_end_minute"] <= 1439
    assert data.get("status") in [s.value for s in CaseStatus]
    assert data.get("actual_start_minute") is None or isinstance(data["actual_start_minute"], int)
    assert data.get("actual_end_minute") is None or isinstance(data["actual_end_minute"], int)
    assert data.get("cancellation_reason") is None or isinstance(data["cancellation_reason"], str)
    assert data.get("cancellation_notice_minutes") is None \
        or isinstance(data["cancellation_notice_minutes"], int)
    assert data.get("provisional_charge_cents") is None \
        or isinstance(data["provisional_charge_cents"], int)
    assert data.get("final_charge_cents") is None or isinstance(data["final_charge_cents"], int)


def assert_assignment(data: dict):
    _assert_common(data, "CaseAssignment")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("roster_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data.get("assignment_role") in [r.value for r in AssignmentRole]
    assert data.get("status") in [s.value for s in CaseAssignmentStatus]


def assert_call_assignment(data: dict):
    _assert_common(data, "CallAssignment")
    assert is_valid_uuid(data.get("roster_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data.get("window_start_minute"), int)
    assert isinstance(data.get("window_end_minute"), int)
    assert 0 <= data["window_start_minute"] < data["window_end_minute"] <= 1439
    assert data.get("status") in [s.value for s in CallAssignmentStatus]
    assert data.get("released_at_minute") is None or isinstance(data["released_at_minute"], int)


def assert_attestation(data: dict):
    _assert_common(data, "DirectionAttestation")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("physician_id", ""))
    for step in ("step_preanesthetic_exam", "step_prescribes_plan",
                 "step_participates_key_portions", "step_ensures_qualified_personnel",
                 "step_monitors_course", "step_available_for_emergencies",
                 "step_post_anesthesia_care"):
        assert isinstance(data.get(step), bool), f"DirectionAttestation: {step} must be boolean"
    assert isinstance(data.get("submitted_count"), int) and data["submitted_count"] >= 0
    assert data.get("rejection_reason") is None or isinstance(data["rejection_reason"], str)
    assert data.get("status") in ["IN_PROGRESS", "SUBMITTED", "VERIFIED", "REJECTED"]


def assert_claim(data: dict):
    _assert_common(data, "BillingClaim")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data.get("modifier_code") in [m.value for m in ModifierCode]
    assert isinstance(data.get("units_total"), (int, float))
    assert isinstance(data.get("charge_cents"), int)
    assert data.get("status") in [s.value for s in ClaimStatus]
    assert data.get("denial_reason") is None or isinstance(data["denial_reason"], str)
    assert data.get("paid_amount_cents") is None or isinstance(data["paid_amount_cents"], int)
    assert isinstance(data.get("resubmission_count"), int) and data["resubmission_count"] >= 0


def assert_fee_schedule(data: dict):
    _assert_common(data, "ProcedureFeeSchedule")
    assert isinstance(data.get("procedure_code"), str) and len(data["procedure_code"]) > 0
    assert isinstance(data.get("base_units"), int) and 1 <= data["base_units"] <= 50
    assert isinstance(data.get("contracted_max_cents"), int)


def assert_stipend_agreement(data: dict):
    _assert_common(data, "StipendAgreement")
    assert is_valid_uuid(data.get("site_id", ""))
    assert isinstance(data.get("effective_from"), str)
    assert isinstance(data.get("effective_to"), str)
    assert data["effective_from"] <= data["effective_to"]
    for f in ("call_stipend_cents", "late_stay_rate_cents_per_minute",
              "standby_full_cents", "standby_partial_cents"):
        assert isinstance(data.get(f), int) and data[f] >= 0


def assert_stipend_entry(data: dict):
    _assert_common(data, "StipendLedgerEntry")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("roster_id", ""))
    assert data.get("entry_type") in [t.value for t in StipendEntryType]
    assert isinstance(data.get("occurred_date"), str)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("applied_amount_cents"), int)
    assert data.get("status") in [s.value for s in StipendEntryStatus]


def assert_audit(data: dict):
    _assert_common(data, "ComplianceAudit")
    assert is_valid_uuid(data.get("roster_id", ""))
    assert data.get("status") in [s.value for s in AuditStatus]
    assert isinstance(data.get("realtime_score"), int)
    assert isinstance(data.get("period_score"), int)
    assert data.get("risk_band") in [b.value for b in RiskBand]


def assert_finding(data: dict):
    _assert_common(data, "AuditFinding")
    assert is_valid_uuid(data.get("audit_id", ""))
    assert data.get("case_id") is None or is_valid_uuid(data["case_id"])
    assert data.get("assignment_id") is None or is_valid_uuid(data["assignment_id"])
    assert data.get("finding_type") in [t.value for t in FindingType]
    assert data.get("severity") in [s.value for s in FindingSeverity]
    assert data.get("status") in [s.value for s in FindingStatus]
    assert data.get("resolution_note") is None or isinstance(data["resolution_note"], str)


def assert_stipend_summary(data: dict):
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data.get("month"), str)
    for f in ("gross_cents", "applied_cents", "capped_cents", "entry_count"):
        assert isinstance(data.get(f), int), f"summary: {f} must be an integer"
    assert data["applied_cents"] <= data["gross_cents"]
    assert data["capped_cents"] == data["gross_cents"] - data["applied_cents"]


def assert_version_incremented(before: int, after: int, context: str = "resource"):
    """PRD §2.5: version increments by exactly one on every mutation."""
    assert after == before + 1, \
        f"{context}: version must increment by exactly one (was {before}, now {after})"
