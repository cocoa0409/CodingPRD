"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"


def assert_payer(data: dict):
    _assert_common_fields(data, "payer")
    assert isinstance(data["name"], str) and data["name"]
    assert data["plan_type"] in ("COMMERCIAL", "MEDICARE", "MEDICAID", "MANAGED_CARE")
    assert isinstance(data["default_timely_filing_days"], int)
    assert data["default_timely_filing_days"] > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["appeal_policy_review_required"], bool)


def assert_payer_appeal_policy(data: dict):
    _assert_common_fields(data, "policy")
    assert is_valid_uuid(data["payer_id"])
    assert data["level_number"] in (1, 2, 3)
    assert isinstance(data["timely_filing_days"], int) and data["timely_filing_days"] > 0
    assert isinstance(data["response_window_days"], int)
    assert isinstance(data["required_attachment_types"], list)
    assert isinstance(data["effective_from"], str)


def assert_remittance_code(data: dict):
    _assert_common_fields(data, "remittance_code")
    assert isinstance(data["code"], str) and data["code"]
    assert data["category"] in (
        "REGISTRATION", "AUTHORIZATION", "CODING",
        "CLINICAL_DOCUMENTATION", "BILLING", "CONTRACTUAL",
    )
    assert data["default_department"] in ("REGISTRATION", "AUTHORIZATION", "CODING")
    assert isinstance(data["appealable"], bool)


def assert_denial_case(data: dict):
    _assert_common_fields(data, "denial")
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert is_valid_uuid(data["payer_id"])
    assert is_valid_uuid(data["remittance_code_id"])
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "QUEUED", "IN_APPEAL",
        "RESOLVED_PAID", "RESOLVED_WRITTEN_OFF", "CLOSED_EXHAUSTED", "CLOSED_EXPIRED",
    )
    assert isinstance(data["billed_amount_cents"], int)
    assert isinstance(data["denied_amount_cents"], int)
    assert isinstance(data["recovered_amount_cents"], int)
    assert isinstance(data["written_off_cents"], int)
    assert isinstance(data["open_balance_cents"], int)
    assert isinstance(data["current_appeal_level"], int)
    assert data["queue_bucket"] in ("CRITICAL", "HIGH", "MEDIUM", "LOW")


def assert_appeal(data: dict):
    _assert_common_fields(data, "appeal")
    assert is_valid_uuid(data["denial_case_id"])
    assert isinstance(data["level_number"], int) and 1 <= data["level_number"] <= 3
    assert data["status"] in (
        "DRAFT", "LETTER_GENERATED", "SUBMITTED",
        "OVERTURNED", "PARTIALLY_OVERTURNED", "UPHELD", "WITHDRAWN",
    )
    assert isinstance(data["outcome_amount_cents"], int)


def assert_appeal_attachment(data: dict):
    _assert_common_fields(data, "attachment")
    assert is_valid_uuid(data["appeal_id"])
    assert data["document_type"] in (
        "CLINICAL_NOTES", "PHYSICIAN_LETTER", "LAB_RESULTS",
        "AUTH_RECORD", "ITEMIZED_BILL", "REMITTANCE_COPY",
    )
    assert data["status"] in ("ACTIVE", "VOIDED")


def assert_root_cause_task(data: dict):
    _assert_common_fields(data, "task")
    assert is_valid_uuid(data["denial_case_id"])
    assert data["department"] in ("REGISTRATION", "AUTHORIZATION", "CODING")
    assert data["task_type"] in ("PROCESS_FIX", "TRAINING", "SYSTEM_CONFIG", "DATA_QUALITY")
    assert data["status"] in (
        "OPEN", "ACKNOWLEDGED", "FIX_IMPLEMENTED", "VERIFIED", "REOPENED", "CLOSED",
    )
    assert isinstance(data["reopened_count"], int)


def assert_write_off_request(data: dict):
    _assert_common_fields(data, "write_off")
    assert is_valid_uuid(data["denial_case_id"])
    assert isinstance(data["requested_amount_cents"], int)
    assert data["reason_code"] in (
        "TIMELY_FILING_EXPIRED", "SMALL_BALANCE", "APPEALS_EXHAUSTED",
        "CONTRACTUAL_ADJUSTMENT", "OTHER",
    )
    assert data["status"] in (
        "PENDING_MANAGER", "ESCALATED_DIRECTOR", "APPROVED", "REJECTED", "RESCINDED",
    )
    assert data["approval_tier"] in ("STANDARD", "ESCALATED")
    assert isinstance(data["projected_recovery_cents"], int)
    assert isinstance(data["recommended_writeoff_cents"], int)


def assert_department_scorecard(data: dict):
    _assert_common_fields(data, "scorecard")
    assert data["department"] in ("REGISTRATION", "AUTHORIZATION", "CODING")
    assert data["status"] in ("OPEN", "FINALIZED")
    for counter in (
        "denial_count", "preventable_denial_count", "denied_cents",
        "preventable_denied_cents", "recovered_cents", "written_off_cents",
        "expired_denial_count", "auto_writeoff_request_count",
        "verified_fix_count", "recurrence_count",
        "verified_linked_denied_cents", "recurrence_linked_denied_cents",
        "open_task_count",
    ):
        assert isinstance(data[counter], int), f"scorecard.{counter} must be an integer"


def assert_prevention_program(data: dict):
    _assert_common_fields(data, "program")
    assert data["department"] in ("REGISTRATION", "AUTHORIZATION", "CODING")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED")


def assert_denial_event(data: dict):
    # Append-only audit record: id + created_at only (PRD §2.5); no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "event.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "event.created_at must be ISO 8601"
    assert "updated_at" not in data, "events carry no updated_at (PRD §2.5)"
    assert "version" not in data, "events carry no version (PRD §2.5)"
    assert is_valid_uuid(data["denial_case_id"])
    assert data["event_type"] in (
        "INTAKE", "TRIAGED", "ASSIGNED", "INTAKE_CORRECTED", "APPEAL_CREATED",
        "LETTER_GENERATED", "APPEAL_SUBMITTED", "OUTCOME_RECORDED", "OUTCOME_REVERSED",
        "APPEAL_WITHDRAWN", "WRITE_OFF_REQUESTED", "WRITE_OFF_APPROVED",
        "WRITE_OFF_REJECTED", "WRITE_OFF_REVISED", "WRITE_OFF_RESCINDED",
        "EXPIRED", "TASK_AUTO_CREATED", "TASK_CREATED", "TASK_VERIFIED", "TASK_REOPENED",
    )
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]


def assert_denial_dollar_conservation(denial: dict):
    """PRD §2.9 money conservation: open + recovered + written_off == denied."""
    total = (
        denial["open_balance_cents"]
        + denial["recovered_amount_cents"]
        + denial["written_off_cents"]
    )
    assert total == denial["denied_amount_cents"], (
        f"Dollar conservation violated: {denial['open_balance_cents']} open + "
        f"{denial['recovered_amount_cents']} recovered + {denial['written_off_cents']} "
        f"written off != {denial['denied_amount_cents']} denied"
    )
