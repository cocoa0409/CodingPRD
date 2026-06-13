"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Immutable upload entities (recommendation, transcript)
carry only id + created_at — no updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_upload_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable upload must not carry updated_at"
    assert "version" not in data, "immutable upload must not carry version"


def assert_fund(data: dict):
    _assert_common(data)
    assert isinstance(data["fund_name"], str) and len(data["fund_name"]) > 0
    assert isinstance(data["endowment_cents"], int)
    assert isinstance(data["committed_cents"], int)
    assert isinstance(data["disbursed_cents"], int)
    assert isinstance(data["available_cents"], int)
    assert data["award_term"] in ("FALL", "SPRING", "SUMMER")
    assert data["status"] in ("DRAFT", "OPEN", "REVIEW", "AWARDING", "CLOSED")
    assert_fund_ledger_invariants(data)


def assert_fund_ledger_invariants(data: dict):
    """PRD §2.7: available_cents == endowment_cents - committed_cents."""
    assert data["available_cents"] == data["endowment_cents"] - data["committed_cents"], (
        "available_cents must equal endowment_cents - committed_cents"
    )
    assert data["committed_cents"] >= 0, "committed_cents must be non-negative"
    assert data["disbursed_cents"] >= 0, "disbursed_cents must be non-negative"


def assert_criteria(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fund_id"])
    assert 0.0 <= data["min_gpa"] <= 4.0
    assert isinstance(data["required_residency_state"], str)
    assert isinstance(data["required_field_of_study"], str)
    assert isinstance(data["max_award_cents"], int) and data["max_award_cents"] > 0


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert 0.0 <= data["self_reported_gpa"] <= 4.0
    assert isinstance(data["residency_state"], str)
    assert isinstance(data["field_of_study"], str)
    assert isinstance(data["institution_id"], str)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["fund_id"])
    assert is_valid_uuid(data["applicant_id"])
    assert isinstance(data["requested_amount_cents"], int) and data["requested_amount_cents"] > 0
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_REVISION",
        "SCORED", "AWARDED", "REJECTED", "WITHDRAWN",
    )


def assert_recommendation(data: dict):
    _assert_upload_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["recommender_name"], str)
    assert isinstance(data["document_uri"], str)


def assert_transcript(data: dict):
    _assert_upload_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["document_uri"], str)
    assert 0.0 <= data["verified_gpa"] <= 4.0


def assert_committee_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["expertise_field"], str)
    assert isinstance(data["active_assignment_count"], int) and data["active_assignment_count"] >= 0


def assert_committee_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["committee_member_id"])
    assert data["status"] in ("ASSIGNED", "DECLINED", "COMPLETED", "REVOKED")


def assert_rubric_score(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["committee_member_id"])
    assert 0 <= data["academic_score"] <= 100
    assert 0 <= data["need_score"] <= 100
    assert 0 <= data["essay_score"] <= 100
    assert data["status"] in ("DRAFT", "SUBMITTED", "RETRACTED")


def assert_award(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["fund_id"])
    assert isinstance(data["provisional_award_cents"], int)
    assert isinstance(data["term_index"], int) and data["term_index"] >= 1
    assert 0.0 <= data["renewal_gpa_floor"] <= 4.0
    assert data["status"] in (
        "COMMITTED", "ACTIVE", "RENEWAL_PENDING", "LAPSED", "REVOKED", "COMPLETED",
    )


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["award_id"])
    assert is_valid_uuid(data["fund_id"])
    assert isinstance(data["institution_id"], str)
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("PENDING", "SETTLED", "RETURNED")


def assert_renewal_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["award_id"])
    assert 0.0 <= data["reported_gpa"] <= 4.0
    assert isinstance(data["meets_floor"], bool)
    assert data["status"] in ("PENDING", "APPROVED", "DENIED")


def assert_stewardship_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["award_id"])
    assert isinstance(data["thank_you_text"], str)
    assert data["status"] in ("DRAFT", "ACKNOWLEDGED")
