"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a comparable datetime."""
    assert isinstance(ts, str), f"Expected ISO timestamp string, got {ts!r}"
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _assert_mutable_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_registration_common(data: dict):
    """Immutable registration records carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "registration records carry no updated_at"
    assert "version" not in data, "registration records carry no version"


def assert_code_version(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["version_label"], str) and data["version_label"]
    assert is_iso8601_timestamp(data["effective_from"])
    assert isinstance(data["zero_tolerance_categories"], list)
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_supplier(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert data["sector"] in ("APPAREL", "ELECTRONICS", "FOOD", "HARDLINES")
    assert data["status"] in ("ONBOARDING", "ACTIVE", "PROBATION", "TERMINATED")
    assert isinstance(data["provisional_score"], int)
    assert isinstance(data["verified_score"], int)
    assert data["consequence_tier"] in (
        "PREFERRED", "QUALIFIED", "PROBATION_WATCH", "SOURCING_EXIT",
    )
    assert isinstance(data["escalation_penalty_points"], int)


def assert_code_acknowledgment(data: dict):
    _assert_registration_common(data)
    assert is_valid_uuid(data["supplier_id"])
    assert is_valid_uuid(data["code_version_id"])
    assert isinstance(data["signer_name"], str) and data["signer_name"]
    assert isinstance(data["signer_title"], str) and data["signer_title"]
    assert is_iso8601_timestamp(data["acknowledged_at"])
    assert "supersedes_acknowledgment_id" in data


def assert_facility(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert isinstance(data["worker_count"], int) and data["worker_count"] >= 1
    assert isinstance(data["processes"], list)
    assert data["status"] in ("ACTIVE", "EXITED")
    assert isinstance(data["risk_score_baseline"], (int, float))
    assert data["risk_score_baseline"] == pytest.approx(
        round(data["risk_score_baseline"], 1), abs=1e-9
    ), "risk_score_baseline is carried to one decimal place"
    assert "risk_score_history" in data
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert isinstance(data["next_audit_interval_months"], int)
    assert "next_audit_due_date" in data


def assert_auditor(data: dict):
    _assert_mutable_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert isinstance(data["certifications"], list)
    assert isinstance(data["country_codes_covered"], list)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_audit(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["auditor_id"])
    assert data["audit_type"] in ("INITIAL", "ANNUAL", "RE_AUDIT", "FOLLOW_UP")
    assert data["announcement"] in ("ANNOUNCED", "SEMI_ANNOUNCED")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "REPORT_SUBMITTED",
        "COMPLETED", "FAILED_ZT", "CANCELLED",
    )
    assert isinstance(data["zt_count"], int) and data["zt_count"] >= 0
    assert isinstance(data["major_count"], int) and data["major_count"] >= 0
    assert isinstance(data["minor_count"], int) and data["minor_count"] >= 0


def assert_finding(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["audit_id"])
    assert data["classification"] in ("ZERO_TOLERANCE", "MAJOR", "MINOR")
    assert data["category"] in (
        "FORCED_LABOR", "CHILD_LABOR", "WORKING_HOURS", "WAGES",
        "HEALTH_SAFETY", "ENVIRONMENT", "HARASSMENT", "RECRUITMENT_FEES",
    )
    assert isinstance(data["description"], str) and data["description"]
    assert data["status"] in ("OPEN", "VERIFIED_CLOSED", "VOIDED")
    assert is_iso8601_timestamp(data["remediation_due_date"])


def assert_cap(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["finding_id"])
    assert is_valid_uuid(data["supplier_id"])
    assert isinstance(data["actions"], list) and len(data["actions"]) >= 1
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "REJECTED", "VERIFICATION_REQUESTED",
        "VERIFICATION_FAILED", "VERIFIED_PASSED",
    )
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_grievance(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["channel"] in ("HOTLINE", "WORKER_COMMITTEE", "AUDIT_INTERVIEW")
    assert data["category"] in (
        "WAGES", "HARASSMENT", "FORCED_LABOR", "SAFETY", "RECRUITMENT_FEES", "OTHER",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert isinstance(data["description"], str) and data["description"]
    assert data["is_anonymized"] is True, "reporter identity is never persisted"
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "ESCALATED", "RESOLVED")


def assert_worker_interview_record(data: dict):
    _assert_registration_common(data)
    assert is_valid_uuid(data["audit_id"])
    assert isinstance(data["interview_count"], int) and data["interview_count"] >= 1
    assert isinstance(data["forced_labor_indicators"], bool)
    assert isinstance(data["recruitment_fee_indicators"], bool)


def assert_fee_review(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["audit_id"])
    assert isinstance(data["workers_assessed"], int) and data["workers_assessed"] >= 1
    assert isinstance(data["fee_items"], list)
    assert isinstance(data["total_reimbursement_cents"], int)
    assert isinstance(data["reimbursed_cents"], int)
    assert isinstance(data["outstanding_reimbursement_cents"], int)
    assert data["status"] in (
        "PENDING_CONFIRMATION", "VIOLATION_CONFIRMED", "REIMBURSED", "CLEARED",
    )


def assert_reimbursement(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["review_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("RECORDED", "REVERSED")


def assert_claim(data: dict):
    _assert_mutable_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["program_name"] in ("BSCI", "SMETA", "RBA", "WRAP")
    assert isinstance(data["external_audit_ref"], str) and data["external_audit_ref"]
    assert is_iso8601_timestamp(data["external_audit_date"])
    assert isinstance(data["external_score"], (int, float))
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


# ---------------------------------------------------------------------------
# Domain invariants (PRD §2.10, §3.4, §3.8)
# ---------------------------------------------------------------------------

def assert_audit_tally_conservation(audit: dict, non_voided_total: int):
    """The three tallies always sum to the count of non-voided findings."""
    tally_sum = audit["zt_count"] + audit["major_count"] + audit["minor_count"]
    assert tally_sum == non_voided_total, (
        f"tally sum {tally_sum} != {non_voided_total} non-voided findings"
    )


def assert_reimbursement_balance(review: dict):
    """total_reimbursement_cents == reimbursed_cents + outstanding at all times."""
    total = review["total_reimbursement_cents"]
    paid_plus_due = (
        review["reimbursed_cents"] + review["outstanding_reimbursement_cents"]
    )
    assert total == paid_plus_due, (
        f"conserved money violated: total {total} != "
        f"reimbursed {review['reimbursed_cents']} + "
        f"outstanding {review['outstanding_reimbursement_cents']}"
    )
