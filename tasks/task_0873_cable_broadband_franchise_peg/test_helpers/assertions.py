"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_franchise(data: dict):
    _assert_common(data)
    assert isinstance(data["operator_name"], str) and data["operator_name"]
    assert isinstance(data["territory_name"], str) and data["territory_name"]
    assert data["lifecycle_status"] in (
        "DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED", "TRANSFERRED", "EXPIRED", "REVOKED",
    )
    assert data["compliance_status"] in ("COMPLIANT", "IN_VIOLATION", "CURED")
    assert isinstance(data["homes_in_territory"], int) and data["homes_in_territory"] >= 1
    assert isinstance(data["unresolved_complaint_count"], int) and data["unresolved_complaint_count"] >= 0
    assert isinstance(data["total_owed_cents"], int)
    assert isinstance(data["peg_credit_cents"], int)


def assert_row_segment(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["length_miles"] > 0
    assert data["homes_along"] >= 0


def assert_row_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED")
    assert is_valid_uuid(data["franchise_id"])
    assert is_valid_uuid(data["row_segment_id"])


def assert_milestone(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "MET", "MISSED")
    assert isinstance(data["required_homes"], int) and data["required_homes"] >= 1
    assert isinstance(data["provisional_damage_cents"], int) and data["provisional_damage_cents"] >= 0
    assert isinstance(data["final_damage_cents"], int) and data["final_damage_cents"] >= 0


def assert_revenue_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "ACCEPTED", "UNDER_AUDIT", "ADJUSTED", "PAID")
    assert data["fee_basis"] in ("AS_FILED", "AS_AUDITED")
    assert isinstance(data["fee_due_cents"], int)
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0


def assert_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "COMPLETED_CLEAN", "COMPLETED_FINDING")
    assert is_valid_uuid(data["franchise_id"])
    assert is_valid_uuid(data["target_report_id"])


def assert_assessment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "DISPUTED", "PAID", "WAIVED")
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["interest_cents"], int)
    assert isinstance(data["penalty_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["principal_cents"] + data["interest_cents"] + data["penalty_cents"]


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "REOPENED", "ESCALATED", "CLOSED")
    assert data["category"] in ("SERVICE_INTERRUPTION", "BILLING", "OTHER")
    assert is_iso8601_timestamp(data.get("filed_at", "")), "filed_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("sla_deadline", "")), "sla_deadline must be ISO 8601"


def assert_peg_contribution(data: dict):
    _assert_common(data)
    assert data["status"] in ("RECORDED", "VOIDED")
    assert data["contribution_type"] in ("CAPITAL_GRANT", "INET")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SUBMITTED", "HELD", "APPROVED", "DENIED", "DEEMED_APPROVED", "WITHDRAWN",
    )
    assert data["application_type"] in ("TRANSFER", "RENEWAL")
    assert is_iso8601_timestamp(data.get("submitted_at", "")), "submitted_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("decision_deadline", "")), "decision_deadline must be ISO 8601"
