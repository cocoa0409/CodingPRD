"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """id (UUID), created_at, updated_at, version — carried by all entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_protected_person(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["annual_income_cents"], int) and data["annual_income_cents"] >= 0
    assert isinstance(data["liquid_estate_cents"], int) and data["liquid_estate_cents"] >= 0
    assert data["capacity_status"] in (
        "PRESUMED_COMPETENT",
        "ADJUDICATED_INCAPACITATED",
        "RESTORED",
    )
    assert data["active_case_id"] is None or is_valid_uuid(data["active_case_id"])


def assert_fiduciary(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["fiduciary_kind"] in ("FAMILY", "PROFESSIONAL", "PUBLIC_AGENCY")
    assert isinstance(data["is_disqualified"], bool)
    assert isinstance(data["open_appointment_count"], int) and data["open_appointment_count"] >= 0


def assert_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["protected_person_id"])
    assert data["case_type"] in ("GUARDIANSHIP", "CONSERVATORSHIP", "PLENARY")
    assert data["status"] in (
        "DRAFT",
        "PENDING_EVALUATION",
        "AWAITING_APPOINTMENT",
        "ACTIVE",
        "UNDER_REVIEW",
        "TERMINATED",
        "RESTORED",
    )
    assert data["protection_posture"] in ("GREEN", "AMBER", "RED")
    assert isinstance(data["requires_bond"], bool)


def assert_petition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["nominated_fiduciary_id"])
    assert data["requested_authority"] in ("PERSON", "ESTATE", "BOTH")
    assert isinstance(data["alleged_grounds"], str)
    assert data["status"] in (
        "FILED",
        "PROBABLE_CAUSE",
        "EVALUATION_ORDERED",
        "READY_FOR_HEARING",
        "GRANTED",
        "DISMISSED",
    )


def assert_evaluation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["petition_id"])
    assert data["finding"] in ("INCAPACITATED", "PARTIALLY_INCAPACITATED", "COMPETENT")
    assert data["recommended_scope"] in ("NONE", "PERSON", "ESTATE", "BOTH")
    assert data["status"] in ("DRAFT", "FILED")


def assert_appointment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["fiduciary_id"])
    assert data["granted_authority"] in ("PERSON", "ESTATE", "BOTH")
    assert data["status"] in (
        "PENDING_QUALIFICATION",
        "ACTIVE",
        "SUSPENDED",
        "REVOKED",
    )


def assert_bond(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["required_amount_cents"], int) and data["required_amount_cents"] >= 0
    assert isinstance(data["posted_amount_cents"], int) and data["posted_amount_cents"] >= 0
    assert data["status"] in ("REQUIRED", "POSTED", "APPROVED", "EXONERATED")


def assert_restricted_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["principal_balance_cents"], int)
    assert isinstance(data["encumbered_cents"], int)
    assert isinstance(data["available_balance_cents"], int)
    assert data["status"] in ("OPEN", "FROZEN", "CLOSED")


def assert_inventory(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    for f in ("real_property_cents", "liquid_assets_cents", "tangible_property_cents", "total_estate_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert data["status"] in ("DRAFT", "FILED", "APPROVED")


def assert_budget(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["period_year"], int)
    for f in (
        "care_cap_cents",
        "medical_cap_cents",
        "admin_cap_cents",
        "care_spent_cents",
        "medical_spent_cents",
        "admin_spent_cents",
    ):
        assert isinstance(data[f], int) and data[f] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED")


def assert_expenditure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert is_valid_uuid(data["budget_id"])
    assert data["category"] in ("CARE", "MEDICAL", "ADMIN")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["payee_name"], str)
    assert isinstance(data["requires_court_approval"], bool)
    assert data["disbursed_at"] is None or is_iso8601_timestamp(data["disbursed_at"])
    assert data["status"] in (
        "REQUESTED",
        "PENDING_COURT",
        "APPROVED",
        "DISBURSED",
        "DENIED",
    )


def assert_accounting(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert isinstance(data["period_year"], int)
    for f in ("opening_balance_cents", "reported_income_cents", "reported_disbursed_cents"):
        assert isinstance(data[f], int) and data[f] >= 0
    for f in ("ledger_disbursed_cents", "projected_disbursed_cents", "variance_cents", "fiduciary_fee_cents"):
        assert isinstance(data[f], int)
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "RETURNED_FOR_CORRECTION",
        "APPROVED",
    )


def assert_care_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert data["residence_type"] in ("HOME", "ASSISTED_LIVING", "NURSING_FACILITY", "HOSPITAL")
    assert isinstance(data["visitation_min_per_month"], int) and data["visitation_min_per_month"] >= 0
    assert isinstance(data["window_start_iso"], str)
    assert isinstance(data["window_end_iso"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED", "REPLACED")


def assert_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["case_id"])
    assert data["subject_kind"] in ("ACCOUNTING", "CARE_PLAN")
    assert is_valid_uuid(data["subject_ref_id"])
    assert data["outcome"] in ("PENDING", "ACCEPTED", "CONTINUED", "SANCTIONED")
    assert data["status"] in ("SCHEDULED", "HELD", "CLOSED")


def assert_account_balance_invariant(data: dict):
    """available_balance_cents == principal_balance_cents - encumbered_cents."""
    expected = data["principal_balance_cents"] - data["encumbered_cents"]
    assert data["available_balance_cents"] == expected, (
        f"available_balance_cents must equal principal - encumbered: "
        f"{data['available_balance_cents']} != {expected}"
    )
