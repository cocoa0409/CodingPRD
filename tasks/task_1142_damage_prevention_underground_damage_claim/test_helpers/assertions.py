"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp, tolerating 'Z' and fractional digits."""
    assert isinstance(value, str) and len(value) > 0, f"expected ISO timestamp, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only_fields(data: dict):
    """EvidenceItem / TimelineEvent carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "updated_at must be absent on this entity"
    assert "version" not in data, "version must be absent on this entity"


def assert_excavator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert data["program_status"] in ["GOOD_STANDING", "WATCH", "PROBATION", "SUSPENDED"]
    assert isinstance(data["offender_points"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["total_outstanding_cents"], int)


def assert_locator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert data["contract_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["performance_score_bp"], int)
    assert isinstance(data["total_responses"], int)


def assert_locate_ticket(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["excavator_id"], str) and data["excavator_id"]
    assert isinstance(data["dig_site_address"], str) and data["dig_site_address"]
    assert isinstance(data["ticket_number"], str) and data["ticket_number"]
    assert data["status"] in ["OPEN", "COMPLETED", "EXPIRED"]
    assert isinstance(data["renewal_count"], int)


def assert_locate_response(data: dict):
    _assert_common_fields(data)
    assert data["response_code"] in ["MARKED", "CLEAR", "PARTIAL"]
    assert data["accuracy_verdict"] in ["UNAUDITED", "ACCURATE", "INACCURATE"]


def assert_damage_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_number"], str) and data["case_number"]
    assert data["facility_type"] in ["GAS", "ELECTRIC", "TELECOM", "WATER"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["investigation_status"] in [
        "REPORTED", "DOCUMENTING", "INVESTIGATING", "FAULT_PROPOSED", "FAULT_FINAL", "CLOSED",
    ]
    assert data["recovery_status"] in ["UNBILLED", "COSTING", "INVOICED", "COLLECTING", "RECOVERED"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["total_invoiced_cents"], int)
    assert isinstance(data["total_recovered_cents"], int)
    assert isinstance(data["evidence_count"], int)
    assert isinstance(data["reconstruction_flags"], list)


def assert_evidence_item(data: dict):
    _assert_append_only_fields(data)
    assert data["evidence_type"] in ["PHOTO", "MEASUREMENT", "WITNESS_STATEMENT", "SKETCH"]
    assert isinstance(data["damage_case_id"], str) and data["damage_case_id"]


def assert_timeline_event(data: dict):
    _assert_append_only_fields(data)
    assert data["event_kind"] in [
        "TICKET_SUBMITTED", "RESPONSE_SUBMITTED", "EVIDENCE_CAPTURED", "DAMAGE_OCCURRED",
    ]
    assert data["flag"] in ["NONE", "LATE_MARK", "STALE_MARKS", "POST_DAMAGE_MARK"]


def assert_fault_allocation(data: dict):
    _assert_common_fields(data)
    assert data["root_cause_code"] in [
        "NO_TICKET", "EXPIRED_TICKET", "MISMARK", "LOCATE_LATE", "OWNER_ABANDONED",
    ]
    assert data["basis"] in ["RULE_DEFAULT", "ADJUDICATED"]
    assert data["status"] in ["DRAFT", "PROPOSED", "CONTESTED", "FINAL", "SUPERSEDED"]
    assert isinstance(data["revision_no"], int)
    assert isinstance(data["shares"], list)
    for share in data["shares"]:
        assert share["party_type"] in ["EXCAVATOR", "LOCATOR", "FACILITY_OWNER"]
        assert isinstance(share["share_bp"], int)


def assert_cost_line_item(data: dict):
    _assert_common_fields(data)
    assert data["category"] in ["LABOR", "MATERIAL", "EQUIPMENT", "RESTORATION"]
    assert data["quantity"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert isinstance(data["line_total_cents"], int)


def assert_claim_invoice(data: dict):
    _assert_common_fields(data)
    assert data["debtor_type"] in ["EXCAVATOR", "LOCATOR", "FACILITY_OWNER"]
    assert isinstance(data["debtor_id"], str) and data["debtor_id"]
    assert data["status"] in [
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED", "WRITTEN_OFF",
    ]
    assert isinstance(data["invoiced_cents"], int)
    assert isinstance(data["standard_basis_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_due_cents"], int)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert data["payer_type"] in ["EXCAVATOR", "LOCATOR"]
    assert data["status"] in ["APPLIED", "REVERSED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["allocations"], list)
    for leg in data["allocations"]:
        assert isinstance(leg["claim_invoice_id"], str) and leg["claim_invoice_id"]
        assert isinstance(leg["amount_cents"], int)


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert data["target_type"] in ["FAULT_ALLOCATION", "CLAIM_INVOICE"]
    assert data["reason"] in ["FAULT_SHARE", "AMOUNT", "EVIDENCE", "OTHER"]
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "COUNTERED", "RESOLVED", "ESCALATED", "EXPIRED",
    ]
    assert isinstance(data["rounds"], int)


def assert_subrogation_case(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DEMANDED", "SETTLED", "CLOSED"]
    assert isinstance(data["demand_amount_cents"], int)
    assert isinstance(data["recovered_cents"], int)
    assert isinstance(data["legal_cost_cents"], int)
    assert isinstance(data["owner_share_cents"], int)


def assert_regulatory_report(data: dict):
    _assert_common_fields(data)
    assert data["report_type"] in ["INCIDENT", "QUARTERLY_SUMMARY"]
    assert data["status"] in ["DRAFT", "FILED", "SUPERSEDED"]
    assert isinstance(data["days_late"], int)
    assert isinstance(data["penalty_cents"], int)


def assert_violation_record(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "OVERTURNED"]
    assert isinstance(data["points"], int)


def assert_training_course(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert data["required_for_status"] in ["WATCH", "PROBATION", "SUSPENDED"]
    assert isinstance(data["credit_hours"], int) and data["credit_hours"] > 0


def assert_training_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ASSIGNED", "COMPLETED", "EXPIRED"]


def assert_case_invoice_conservation(case: dict, invoices: list):
    """Domain invariant (PRD §3.5): the invoiced split conserves the subtotal."""
    total = sum(inv["invoiced_cents"] for inv in invoices)
    assert total == case["subtotal_cents"], (
        f"invoice split {total} must equal case subtotal {case['subtotal_cents']}"
    )
