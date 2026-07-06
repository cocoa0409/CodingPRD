"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be int >= 1: {data.get('version')}"
    )


def assert_homeowner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data.get("is_board_member"), bool)
    assert data["standing"] in ("GOOD_STANDING", "MARGINAL", "DELINQUENT"), (
        f"invalid standing {data['standing']}"
    )
    assert isinstance(data["delinquency_score"], int) and data["delinquency_score"] >= 0
    assert data["booking_privilege"] in ("ALLOWED", "FROZEN")
    # Standing/booking_privilege coupling — PRD §2.6
    if data["standing"] == "DELINQUENT":
        assert data["booking_privilege"] == "FROZEN", (
            "DELINQUENT standing must yield FROZEN booking_privilege"
        )
    else:
        assert data["booking_privilege"] == "ALLOWED", (
            "GOOD_STANDING/MARGINAL must yield ALLOWED booking_privilege"
        )


def assert_property(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["homeowner_id"], str)
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["monthly_dues_cents"], int) and data["monthly_dues_cents"] >= 0
    assert data["compliance_flag"] in ("OPEN", "APPROVED_MOD", "SUSPENDED")
    assert isinstance(data["total_outstanding_cents"], int) and data["total_outstanding_cents"] >= 0
    assert isinstance(data["fine_balance_cents"], int) and data["fine_balance_cents"] >= 0


def assert_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0
    assert data["status"] in (
        "OPEN", "PARTIALLY_PAID", "PAID", "OVERDUE", "DELINQUENT", "ON_LIEN"
    )


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["assessment_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("MANUAL", "AUTOPAY")
    assert data["status"] in ("POSTED", "REVERSED")


def assert_autopay_mandate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["homeowner_id"], str)
    assert isinstance(data["max_charge_cents"], int) and data["max_charge_cents"] > 0
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "CANCELLED")


def assert_arc_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["submitter_homeowner_id"], str)
    assert data["category"] in ("SIMPLE", "MEDIUM", "COMPLEX")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISION_REQUESTED",
        "APPROVED", "REJECTED",
    )
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0


def assert_arc_review(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["arc_request_id"], str)
    assert isinstance(data["reviewer_homeowner_id"], str)
    assert isinstance(data["weight"], int) and 1 <= data["weight"] <= 5
    assert data["verdict"] in ("APPROVE", "REJECT", "REVISE")


def assert_violation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["property_id"], str)
    assert data["category"] in ("NUISANCE", "LANDSCAPE", "STRUCTURAL", "SAFETY")
    assert data["status"] in (
        "REPORTED", "CONFIRMED", "CURED", "FINED",
        "APPEALED", "UPHELD", "OVERTURNED",
    )


def assert_amenity(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert 0 <= data["reservation_window_start_hour"] <= 23
    assert 1 <= data["reservation_window_end_hour"] <= 24
    assert data["reservation_window_end_hour"] > data["reservation_window_start_hour"]


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["amenity_id"], str)
    assert isinstance(data["homeowner_id"], str)
    assert isinstance(data["guest_count"], int) and data["guest_count"] >= 1
    assert data["status"] in (
        "BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW"
    )


def assert_motion(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ("BUDGET", "POLICY", "ELECTION")
    assert data["status"] in ("OPEN", "CLOSED_PASSED", "CLOSED_FAILED", "QUORUM_FAILED")
    assert isinstance(data["eligible_voter_count"], int) and data["eligible_voter_count"] >= 1
    assert 1 <= data["quorum_pct"] <= 100
    assert isinstance(data["yes_count"], int) and data["yes_count"] >= 0
    assert isinstance(data["no_count"], int) and data["no_count"] >= 0


def assert_ballot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["motion_id"], str)
    assert isinstance(data["homeowner_id"], str)
    assert data["choice"] in ("YES", "NO", "ABSTAIN")


def assert_work_order(data: dict):
    _assert_common_fields(data)
    assert data["work_status"] in ("NEW", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in ("UNBILLED", "INVOICED", "PAID")
    assert data["source"] in ("MANUAL", "AUTO_ARC")


def assert_document(data: dict):
    # Document has common_fields=false: only id + created_at.
    assert is_valid_uuid(data.get("id", "")), "document id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "document created_at must be ISO 8601"
    )
    assert "updated_at" not in data, "Document must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "Document must not carry version (PRD §2.4)"
    assert data["category"] in ("CCR", "POLICY", "MINUTES", "BUDGET")
