"""Entity assertions and domain invariant checkers.

Each assert_* checks the structural contract of one resource: UUID id,
ISO 8601 timestamps, integer version, and membership of status/category
fields in their PRD-defined enums.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be a positive integer"


def assert_payer(data: dict):
    _assert_common(data, "Payer")
    assert data["payer_type"] in ("RAC", "COMMERCIAL")
    assert data["appeal_track"] in ("MEDICARE", "COMMERCIAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for field in ("records_submission_days", "l1_deadline_days",
                  "l2_deadline_days", "l3_deadline_days", "l4_deadline_days",
                  "l5_deadline_days", "external_review_deadline_days",
                  "concurrent_audit_cap", "interest_rate_bps_tier1",
                  "interest_rate_bps_tier2", "interest_cap_pct"):
        assert isinstance(data[field], int), f"Payer.{field} must be int"
    assert isinstance(data["hold_levels"], list)


def assert_issue_code(data: dict):
    _assert_common(data, "IssueCode")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["category"] in ("CLINICAL", "TECHNICAL")
    assert isinstance(data["description"], str)
    assert data["active"] is True, "Issue codes are created active and never deactivated"


def assert_audit_case(data: dict):
    _assert_common(data, "AuditCase")
    assert is_valid_uuid(data["payer_id"])
    assert data["audit_type"] in (
        "RAC_COMPLEX", "RAC_AUTOMATED", "COMMERCIAL_POSTPAY",
        "COMMERCIAL_PREPAY", "TARGETED_PROBE")
    assert data["status"] in (
        "RECEIVED", "RECORDS_SUBMITTED", "UNDER_PAYER_REVIEW",
        "DETERMINATION_ISSUED", "MISSED_DEADLINE", "CLOSED")
    assert is_iso8601_timestamp(data["records_due_at"])
    assert isinstance(data["late_submission"], bool)
    for field in ("total_billed_cents", "total_upheld_cents",
                  "total_denied_active_cents", "total_overturned_cents",
                  "total_final_denied_cents"):
        assert isinstance(data[field], int), f"AuditCase.{field} must be int cents"


def assert_case_conservation(case: dict):
    """PRD conservation invariant on the case totals."""
    total = case["total_billed_cents"]
    parts = (case["total_upheld_cents"] + case["total_denied_active_cents"]
             + case["total_final_denied_cents"])
    assert total == parts, (
        f"Conservation violated: billed {total} != upheld "
        f"{case['total_upheld_cents']} + denied_active "
        f"{case['total_denied_active_cents']} + final_denied "
        f"{case['total_final_denied_cents']}")


def assert_claim_line(data: dict):
    _assert_common(data, "AuditClaimLine")
    assert is_valid_uuid(data["audit_case_id"])
    assert data["status"] in (
        "UNDER_AUDIT", "PAID_AS_BILLED", "DENIED", "PARTIALLY_DENIED",
        "OVERTURNED", "FINAL")
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["denied_amount_cents"], int)
    assert isinstance(data["auto_denied"], bool)


def assert_appeal(data: dict):
    _assert_common(data, "Appeal")
    assert is_valid_uuid(data["audit_claim_line_id"])
    assert is_valid_uuid(data["audit_case_id"])
    assert data["level"] in ("LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4",
                             "LEVEL_5")
    assert data["status"] in (
        "DRAFT", "PENDING_DECISION", "DECIDED_FAVORABLE", "DECIDED_PARTIAL",
        "DECIDED_UNFAVORABLE", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["appealed_denied_cents"], int)
    assert is_iso8601_timestamp(data["filed_deadline_at"])


def assert_evidence_packet(data: dict):
    _assert_common(data, "EvidencePacket")
    assert is_valid_uuid(data["appeal_id"])
    assert data["status"] in ("ASSEMBLING", "READY", "SUBMITTED")


def assert_packet_item(data: dict):
    _assert_common(data, "PacketItem")
    assert is_valid_uuid(data["evidence_packet_id"])
    assert data["item_type"] in (
        "MEDICAL_RECORD", "PHYSICIAN_LETTER", "POLICY_CITATION",
        "EXPERT_REVIEW", "PRIOR_AUTH_DOC")
    assert data["status"] in ("PENDING", "ATTACHED", "WAIVED")
    assert isinstance(data["required"], bool)


def assert_recoupment_demand(data: dict):
    _assert_common(data, "RecoupmentDemand")
    assert is_valid_uuid(data["audit_case_id"])
    assert is_valid_uuid(data["payer_id"])
    assert data["status"] in (
        "DEMANDED", "ON_HOLD", "PARTIALLY_RECOUPED", "FULLY_RECOUPED",
        "REVERSED", "WRITTEN_OFF")
    for field in ("principal_cents", "outstanding_principal_cents",
                  "accrued_interest_cents", "written_off_cents",
                  "accumulated_hold_seconds", "rate_bps_tier1_snapshot",
                  "rate_bps_tier2_snapshot", "interest_cap_pct_snapshot"):
        assert isinstance(data[field], int), f"RecoupmentDemand.{field} must be int"


def assert_remittance(data: dict):
    _assert_common(data, "Remittance")
    assert is_valid_uuid(data["payer_id"])
    assert data["status"] in ("RECEIVED", "PARTIALLY_ALLOCATED",
                              "FULLY_ALLOCATED")
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["available_cents"], int)


def assert_offset_transaction(data: dict):
    _assert_common(data, "OffsetTransaction")
    assert is_valid_uuid(data["remittance_id"])
    assert is_valid_uuid(data["recoupment_demand_id"])
    assert data["status"] in ("APPLIED", "REVERSED")
    assert data["allocation_mode"] in ("AUTO_WATERFALL", "MANUAL")
    assert data["amount_cents"] == (
        data["interest_portion_cents"] + data["principal_portion_cents"]), (
        "offset amount_cents must equal interest + principal portions")


def assert_corrective_action_plan(data: dict):
    _assert_common(data, "CorrectiveActionPlan")
    assert is_valid_uuid(data["payer_id"])
    assert is_valid_uuid(data["issue_code_id"])
    assert data["status"] in (
        "PROPOSED", "ACTIVE", "EFFECTIVENESS_CHECK", "VERIFIED", "FAILED")
    assert isinstance(data["proposed_by_user_id"], str)
    assert isinstance(data["cycle_count"], int)


def assert_case_event(data: dict):
    """Append-only event: id + created_at present; updated_at/version absent."""
    assert is_valid_uuid(data.get("id", "")), "AuditCaseEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "events carry no updated_at"
    assert "version" not in data, "events carry no version"
    assert is_valid_uuid(data["audit_case_id"])
    assert data["event_type"] in (
        "CASE_CREATED", "RECORDS_SUBMITTED", "REVIEW_BEGAN",
        "DETERMINATION_ISSUED", "CASE_MISSED_DEADLINE", "LINES_AUTO_DENIED",
        "DEMAND_CREATED", "OFFSET_APPLIED", "OFFSET_REVERSED", "CASE_CLOSED")
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)
    assert is_iso8601_timestamp(data["occurred_at"])
