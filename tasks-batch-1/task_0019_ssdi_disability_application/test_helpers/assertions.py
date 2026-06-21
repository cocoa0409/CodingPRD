"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# ---------- Common-fields entity assertions ----------

def assert_claimant(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"Claimant.id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be >= 1"
    assert isinstance(data["ssn_last4"], str) and len(data["ssn_last4"]) == 4
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["filing_state"], str) and len(data["filing_state"]) == 2


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Application.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in {
        "DRAFT", "QC_REVIEW", "MEDICAL_REVIEW", "DENIED_QC", "DENIED_MEDICAL",
        "APPROVED_INITIAL", "RECONSIDERATION", "ALJ_PENDING", "ALJ_APPROVED",
        "ALJ_DENIED", "AWARDED", "CDR_FROZEN", "CESSATION", "CLOSED",
    }, f"unknown Application.status: {data.get('status')!r}"


def assert_work_credit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "WorkCreditRecord.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["year"], int) and 1990 <= data["year"] <= 2099
    assert isinstance(data["credits_earned"], int) and 0 <= data["credits_earned"] <= 4
    assert isinstance(data["earnings_cents"], int) and data["earnings_cents"] >= 0


def assert_hearing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "HearingRequest.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in {"REQUESTED", "SCHEDULED", "HELD", "APPROVED", "DENIED", "CANCELLED"}


def assert_award(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BenefitAward.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in {"ACTIVE", "SUSPENDED", "TERMINATED"}
    assert isinstance(data["primary_insurance_amount_cents"], int)
    assert isinstance(data["monthly_benefit_cents"], int)
    assert isinstance(data["back_pay_cents"], int) and data["back_pay_cents"] >= 0
    assert data["back_pay_variant"] in {"INITIAL_APPROVAL", "ALJ_APPROVAL"}


def assert_child_auxiliary(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ChildAuxiliaryBenefit.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in {"ACTIVE", "TERMINATED_AGE", "TERMINATED_PARENT"}
    assert isinstance(data["monthly_amount_cents"], int) and data["monthly_amount_cents"] >= 0


def assert_ssi_supplement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SSISupplement.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in {"ACTIVE", "INELIGIBLE_RESOURCES", "TERMINATED"}
    assert isinstance(data["monthly_supplement_cents"], int) and data["monthly_supplement_cents"] >= 0
    assert isinstance(data["state_supplement_cents"], int) and data["state_supplement_cents"] >= 0


def assert_cdr_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CDRReview.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["diary_classification"] in {"MIE", "MIP", "MINE"}
    assert data["outcome"] in {"PENDING", "CONTINUED", "CESSATION"}


def assert_decision(data: dict):
    assert is_valid_uuid(data.get("id", "")), "MedicalDeterminationDecision.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["decision_type"] in {"LISTING_MET", "RFC_DISABLED", "NOT_DISABLED"}


def assert_evidence(data: dict):
    """MedicalEvidence is append-only: only id + created_at common fields."""
    assert is_valid_uuid(data.get("id", "")), "MedicalEvidence.id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # PRD §2.4: evidence carries neither updated_at nor version.
    assert data["source_type"] in {
        "TREATING_PHYSICIAN", "CONSULTATIVE_EXAM", "HOSPITAL_RECORD", "SPECIALIST_REPORT",
    }
    assert isinstance(data["severity_score"], int) and 0 <= data["severity_score"] <= 100
