"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_same_instant(actual, expected, label="timestamp"):
    """Assert two ISO-8601 datetime strings denote the same instant.

    PRD §1.3 pins only the value: "Datetimes are compared and stored at second
    precision". PRD fixes the three-fractional-digit string form solely for
    `api_request_timestamp`, `created_at`, and `updated_at`; stamped/computed
    datetimes (e.g. `terminated_at`, `due_at`, `sealed_at`,
    `confidentiality_end`) are therefore compared by instant, not string form.
    """
    def _parse(s):
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    assert _parse(actual) == _parse(expected), \
        f"{label}: {actual!r} is not the same instant as {expected!r}"


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_asset(data: dict):
    _assert_common(data, "SecretAsset")
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["classification"] in ["INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CROWN_JEWEL"]
    assert data["status"] in ["DRAFT", "REGISTERED", "SUSPENDED", "RETIRED"]
    assert isinstance(data["exposure_estimate_cents"], int) and data["exposure_estimate_cents"] >= 0
    assert data["protection_posture"] in ["DEFICIENT", "ADEQUATE", "STRONG"]
    assert isinstance(data["active_grant_count"], int) and data["active_grant_count"] >= 0


def assert_measure(data: dict):
    _assert_common(data, "ReasonableMeasure")
    assert data["measure_type"] in ["POLICY", "TRAINING", "PHYSICAL", "CONTRACTUAL", "TECHNICAL"]
    assert data["status"] in ["PLANNED", "IMPLEMENTED", "VERIFIED", "LAPSED", "ABANDONED"]
    assert isinstance(data["weight_points"], int)
    assert data["weight_points"] == {
        "POLICY": 10, "TRAINING": 10, "PHYSICAL": 15, "CONTRACTUAL": 20, "TECHNICAL": 25,
    }[data["measure_type"]], "weight_points must match the measure_type constant"


def assert_counterparty(data: dict):
    _assert_common(data, "Counterparty")
    assert data["counterparty_type"] in ["VENDOR", "PARTNER", "CUSTOMER", "CONSULTANT"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "BARRED"]
    assert data["risk_tier"] in ["LOW", "MEDIUM", "HIGH"]


def assert_nda(data: dict):
    _assert_common(data, "NdaAgreement")
    assert data["status"] in [
        "DRAFT", "SENT", "EXECUTED", "ACTIVE", "BREACH_ALLEGED",
        "SUPERSEDED", "TERMINATED", "EXPIRED",
    ]
    assert data["classification_ceiling"] in ["INTERNAL", "CONFIDENTIAL", "RESTRICTED", "CROWN_JEWEL"]
    assert isinstance(data["obligations_total_count"], int)
    assert isinstance(data["obligations_open_count"], int)
    assert isinstance(data["obligations_fulfilled_count"], int)
    assert isinstance(data["obligations_waived_count"], int)


def assert_nda_obligation_bucket_invariant(nda: dict):
    """The open, fulfilled, and waived buckets always sum to the total (PRD §3.2)."""
    total = nda["obligations_total_count"]
    summed = (
        nda["obligations_open_count"]
        + nda["obligations_fulfilled_count"]
        + nda["obligations_waived_count"]
    )
    assert summed == total, f"obligation buckets {summed} must equal total {total}"


def assert_obligation(data: dict):
    _assert_common(data, "NdaObligation")
    assert data["obligation_type"] in [
        "NON_DISCLOSURE", "NON_USE", "RETURN_OR_DESTROY", "NO_REVERSE_ENGINEERING", "AUDIT_RIGHT",
    ]
    assert data["status"] in ["PENDING", "FULFILLED", "WAIVED", "OVERDUE", "ESCALATED"]


def assert_employee(data: dict):
    _assert_common(data, "Employee")
    assert data["access_clearance"] in ["STANDARD", "ELEVATED", "PRIVILEGED"]
    assert data["status"] in ["PREBOARDING", "ACTIVE", "NOTICE", "DEPARTED"]
    assert isinstance(data["training_current"], bool)


def assert_acknowledgment(data: dict):
    _assert_common(data, "Acknowledgment")
    assert data["status"] in ["PENDING", "SIGNED", "SUPERSEDED", "EXPIRED"]


def assert_exit_interview(data: dict):
    _assert_common(data, "ExitInterview")
    assert data["status"] in ["SCHEDULED", "CONDUCTED", "NO_SHOW", "CERTIFIED", "ESCALATED", "CANCELLED"]
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0


def assert_grant(data: dict):
    _assert_common(data, "AccessGrant")
    assert data["status"] in [
        "REQUESTED", "APPROVED", "DENIED", "PROVISIONED", "SUSPENDED", "REVOKED", "EXPIRED",
    ]


def assert_disclosure(data: dict):
    _assert_common(data, "DisclosureRequest")
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED", "REJECTED", "RETURNED",
        "WITHDRAWN", "EXECUTED",
    ]
    assert data["marking_protocol"] in ["STAMPED_CONFIDENTIAL", "ORAL_WITH_FOLLOWUP", "ENCRYPTED_DELIVERY"]


def assert_forensic_review(data: dict):
    _assert_common(data, "ForensicReview")
    assert data["trigger_reason"] in [
        "VOLUNTARY_DEPARTURE", "INVOLUNTARY_DEPARTURE", "POLICY", "LITIGATION",
    ]
    assert data["status"] in [
        "OPENED", "IMAGING", "FINDINGS_DRAFTED", "COUNSEL_REVIEW", "CLOSED_NO_ACTION", "ESCALATED",
    ]


def assert_demand_letter(data: dict):
    _assert_common(data, "DemandLetter")
    assert data["status"] in [
        "DRAFTED", "COUNSEL_APPROVED", "ISSUED", "ACKNOWLEDGED", "COMPLIED",
        "IGNORED", "LITIGATION", "WITHDRAWN",
    ]
    assert isinstance(data["damages_estimate_cents"], int)


def assert_preservation_notice(data: dict):
    _assert_common(data, "PreservationNotice")
    assert data["status"] in ["DRAFT", "ISSUED", "ACTIVE", "RELEASED"]


def assert_evidence_item(data: dict):
    _assert_common(data, "EvidenceItem")
    assert data["source"] in ["FORENSIC_IMAGE", "EMAIL_EXPORT", "ACCESS_LOG", "DEVICE_IMAGE", "MARKED_COPY"]
    assert data["status"] in ["COLLECTED", "SEALED", "RELEASED"]


def assert_training_assignment(data: dict):
    _assert_common(data, "TrainingAssignment")
    assert data["module"] in ["BASIC_TS", "CLEAN_DESK", "ADVANCED_IP"]
    assert data["status"] in ["ASSIGNED", "COMPLETED", "OVERDUE", "ESCALATED", "EXCUSED"]


def assert_clean_desk_audit(data: dict):
    _assert_common(data, "CleanDeskAudit")
    assert data["status"] in ["SCHEDULED", "CONDUCTED", "REPORTED", "REMEDIATING", "CLOSED", "CANCELLED"]
