"""Entity assertions and domain invariant checkers (PRD-anchored)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    if with_version:
        assert is_iso8601_timestamp(
            data.get("updated_at", "")
        ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_specialty_track(data: dict):
    _assert_common(data)
    assert data["specialty_code"] in [
        "CARDIOLOGY", "ENDOCRINOLOGY", "NEUROLOGY", "DERMATOLOGY", "RHEUMATOLOGY",
    ]
    for field in (
        "response_time_target_hours", "urgent_target_hours", "base_response_fee_cents",
        "conversion_response_fee_cents", "clarification_fee_cents", "late_penalty_cents",
        "monthly_billing_cap_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["response_time_target_hours"] > 0
    assert 0 < data["urgent_target_hours"] < data["response_time_target_hours"]


def assert_referring_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_specialist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert data["status"] in ["ACTIVE", "DEACTIVATED"]


def assert_panel_membership(data: dict):
    _assert_common(data)
    assert data["standing"] in ["GOOD_STANDING", "PROBATION", "SUSPENDED"]
    for field in (
        "quality_score_bps", "reviews_count", "reviews_score_sum", "responded_count",
        "on_time_count", "rebuke_count", "expired_count", "open_consult_count",
        "provisional_balance_cents", "posted_balance_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert 0 <= data["quality_score_bps"] <= 10000
    assert isinstance(data["is_accepting"], bool)


def assert_consult_request(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SUBMITTED", "QUEUED", "ASSIGNED", "CLARIFICATION_REQUESTED",
        "ANSWERED", "CLOSED", "EXPIRED", "CANCELLED",
    ]
    assert data["billing_status"] in [
        "UNBILLABLE", "PENDING_DOCUMENTATION", "CHARGEABLE", "CLAIMED", "VOID",
    ]
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert isinstance(data["question_text"], str) and len(data["question_text"]) >= 20
    assert isinstance(data["icd10_primary"], str) and data["icd10_primary"]
    assert data["urgency"] in ["ROUTINE", "URGENT"]
    assert isinstance(data["clarification_rounds"], int)
    assert isinstance(data["sla_breached"], bool)


def assert_consult_response(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "FINALIZED", "REBUKED"]
    assert data["disposition"] in [
        "MANAGE_IN_PRIMARY_CARE", "MANAGE_WITH_PLAN", "CONVERT_TO_VISIT",
    ]
    assert isinstance(data["recommendation_text"], str) and len(data["recommendation_text"]) >= 20
    for field in (
        "on_time", "pcp_note_documented", "specialist_note_documented",
        "documentation_complete", "review_required",
    ):
        assert isinstance(data[field], bool), f"{field} must be a boolean"
    assert isinstance(data["response_minutes"], int)
    assert isinstance(data["revision_count"], int)
    # documentation_complete is the conjunction of the two note flags.
    assert data["documentation_complete"] == (
        data["pcp_note_documented"] and data["specialist_note_documented"]
    )


def assert_clarification_message(data: dict):
    # Append-only record: id + created_at only; NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ClarificationMessage must not expose version"
    assert "updated_at" not in data, "ClarificationMessage must not expose updated_at"
    assert data["author_role"] in ["REFERRING_PROVIDER", "SPECIALIST"]
    assert isinstance(data["body"], str) and data["body"]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1


def assert_in_person_conversion(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert is_iso8601_timestamp(data["appointment_start"])
    assert is_iso8601_timestamp(data["appointment_end"])


def assert_quality_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "COMPLETED"]


def assert_compensation_entry(data: dict):
    _assert_common(data)
    assert data["entry_type"] in ["RESPONSE_FEE", "CLARIFICATION_FEE"]
    assert data["posture"] in ["PROVISIONAL", "POSTED", "REVERSED"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["period_key"], str) and len(data["period_key"]) == 7


def assert_availability_window(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "CANCELLED"]
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_billing_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "PAID", "DENIED", "VOID"]
    assert isinstance(data["claim_code"], str) and data["claim_code"].startswith("ECONSULT-")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["period_key"], str) and len(data["period_key"]) == 7


def assert_measurement(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "FINALIZED"]
    for field in (
        "responded_count", "conversions_count",
        "avoided_attributed_count", "avoided_conservative_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"


def assert_routing_decision(data: dict):
    # Append-only audit row: id + created_at only; NO updated_at, NO version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "RoutingDecision must not expose version"
    assert "updated_at" not in data, "RoutingDecision must not expose updated_at"
    assert data["outcome"] in ["ASSIGNED", "QUEUED"]
    assert isinstance(data["candidate_count"], int) and data["candidate_count"] >= 0


def assert_membership_invariants(data: dict):
    """Domain invariants that must hold for a membership after any operation."""
    assert data["provisional_balance_cents"] >= 0, "provisional balance never negative here"
    assert data["posted_balance_cents"] >= 0, "posted balance never negative here"
    assert data["open_consult_count"] >= 0
    assert data["on_time_count"] <= data["responded_count"]
