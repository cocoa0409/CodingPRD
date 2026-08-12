"""Entity assertions and domain invariant checkers (PRD sections 2 and 3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert not data["id"].split("-")[0].isalpha() or "-" in data["id"], (
        "id must be a bare UUID without a type prefix"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_pod(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["pod_code"], str) and 4 <= len(data["pod_code"]) <= 24
    assert isinstance(data["academic_year"], str)
    assert isinstance(data["seat_capacity"], int) and 5 <= data["seat_capacity"] <= 30
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["tuition_full_year_cents"], int) and data["tuition_full_year_cents"] > 0
    assert isinstance(data["min_guides_required"], int) and data["min_guides_required"] >= 1
    assert isinstance(data["facility_site_id"], str)
    assert data["status"] in [
        "DRAFT", "FORMING", "LICENSING_REVIEW", "ACTIVE",
        "SUSPENDED", "DISSOLVING", "DISSOLVED",
    ]
    assert data["posture"] in ["OPEN", "RESTRICTED", "FROZEN", "CLOSED"]
    assert data["compliance_flag"] in ["COMPLIANT", "AT_RISK", "VIOLATION"]


def assert_facility_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_name"], str)
    assert isinstance(data["address_line1"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data["zoning_class"] in [
        "RESIDENTIAL_SINGLE", "RESIDENTIAL_MULTI", "COMMERCIAL",
        "MIXED_USE", "RELIGIOUS", "AGRICULTURAL",
    ]
    assert isinstance(data["max_occupancy"], int) and data["max_occupancy"] > 0
    assert isinstance(data["indoor_sqft"], int) and data["indoor_sqft"] > 0
    assert data["site_status"] in ["AVAILABLE", "LEASED", "ARCHIVED"]


def assert_family(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["family_name"], str)
    assert isinstance(data["primary_contact_email"], str)
    assert isinstance(data["billing_address_state"], str)
    assert data["family_status"] in ["PROSPECT", "ACTIVE", "INACTIVE"]


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["family_id"], str)
    assert isinstance(data["legal_first_name"], str)
    assert isinstance(data["legal_last_name"], str)
    assert data["student_status"] in ["APPLICANT", "ENROLLED", "WITHDRAWN", "GRADUATED"]


def assert_seat(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["student_id"], str)
    assert data["seat_status"] in ["RESERVED", "ENROLLED", "WITHDRAWN", "RELEASED"]


def assert_guide(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["certification_tier"] in ["APPRENTICE", "CERTIFIED", "LEAD"]
    assert data["guide_status"] in ["CANDIDATE", "ACTIVE", "INACTIVE"]


def assert_guide_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["guide_id"], str)
    assert isinstance(data["weekly_hours"], int) and 4 <= data["weekly_hours"] <= 40
    assert data["assignment_status"] in ["SCHEDULED", "ACTIVE", "ENDED", "TERMINATED_EARLY"]


def assert_curriculum_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["plan_name"], str)
    assert isinstance(data["grade_bands_covered"], list)
    for band in data["grade_bands_covered"]:
        assert band in ["LOWER_EL", "UPPER_EL", "MIDDLE", "HIGH"]
    assert isinstance(data["total_instructional_minutes_per_week"], int)
    assert data["plan_status"] in ["DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED"]


def assert_progress_conference(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["curriculum_plan_id"], str)
    assert data["conference_status"] in [
        "REQUESTED", "SCHEDULED", "COMPLETED", "NO_SHOW", "RESCHEDULED", "CANCELLED",
    ]
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0


def assert_licensing_determination(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["jurisdiction_code"], str)
    assert data["submission_kind"] in ["EXEMPTION_CLAIM", "FULL_LICENSE"]
    assert data["determination_status"] in [
        "SUBMITTED", "UNDER_REVIEW", "EXEMPT_GRANTED", "LICENSE_REQUIRED",
        "LICENSE_GRANTED", "DENIED", "RESUBMITTED",
    ]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 0


def assert_safety_policy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["policy_version"], int) and data["policy_version"] >= 1
    assert isinstance(data["emergency_plan_text"], str)
    assert data["immunization_policy"] in ["REQUIRED", "EXEMPTION_ALLOWED", "NOT_REQUIRED"]
    assert isinstance(data["background_check_required"], bool)
    assert isinstance(data["drill_cadence_days"], int)
    assert data["policy_status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]


def assert_voucher_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["program_code"], str)
    assert isinstance(data["awarded_annual_cents"], int) and data["awarded_annual_cents"] > 0
    assert isinstance(data["disbursable_balance_cents"], int)
    assert data["verification_status"] in ["PENDING_VERIFICATION", "VERIFIED", "REJECTED"]
    assert data["funding_status"] in ["FUNDED", "PARTIALLY_DEPLETED", "DEPLETED", "FROZEN"]


def assert_tuition_invoice(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["line_items"], list)
    assert data["invoice_status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE", "WRITTEN_OFF",
    ]


def assert_payment(data: dict):
    # Payment is an immutable ledger entry: id + created_at only (PRD 2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 timestamp"
    )
    assert "updated_at" not in data, "Payment must not carry updated_at"
    assert "version" not in data, "Payment must not carry version"
    assert isinstance(data["invoice_id"], str)
    assert isinstance(data["seat_id"], str)
    assert data["source_kind"] in ["FAMILY", "VOUCHER", "SCHOLARSHIP", "REFUND_REVERSAL"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["payment_status"] in ["PENDING", "CLEARED", "FAILED", "REVERSED"]


def assert_refund_claim(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["pod_id"], str)
    assert isinstance(data["seat_id"], str)
    assert data["claim_kind"] in ["WITHDRAWAL", "DISSOLUTION", "OVERPAYMENT"]
    assert isinstance(data["claimed_amount_cents"], int)
    assert data["claim_status"] in ["FILED", "UNDER_REVIEW", "APPROVED", "DENIED", "PAID"]


def assert_envelope_object(body: dict):
    """PRD 2.2: success envelope carries meta + response_type + data."""
    assert "meta" in body and isinstance(body["meta"], dict)
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert is_iso8601_timestamp(body["meta"].get("api_request_timestamp", ""))
    assert body.get("response_type") in ("object", "array")
    assert "data" in body


def assert_error_envelope(body: dict):
    """PRD 2.2: error envelope shape."""
    assert "meta" in body and isinstance(body["meta"], dict)
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body.get("response_type") == "error"
    assert isinstance(body.get("data"), dict)
    assert isinstance(body["data"].get("error_id"), str) and len(body["data"]["error_id"]) > 0
    assert isinstance(body["data"].get("message"), str) and len(body["data"]["message"]) > 0
