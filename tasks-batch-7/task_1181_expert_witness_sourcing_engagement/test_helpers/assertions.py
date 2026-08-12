"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_expert(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["specialty_area"], str) and len(data["specialty_area"]) > 0
    assert data["roster_status"] in ["ACTIVE", "PROBATION", "REMOVED"]
    assert isinstance(data["daubert_challenge_count"], int) and data["daubert_challenge_count"] >= 0
    assert isinstance(data["daubert_exclusion_count"], int) and data["daubert_exclusion_count"] >= 0
    assert isinstance(data["max_concurrent_engagements"], int) and data["max_concurrent_engagements"] >= 1
    assert isinstance(data["active_engagement_count"], int) and data["active_engagement_count"] >= 0
    assert isinstance(data["evaluation_count"], int) and data["evaluation_count"] >= 0
    assert isinstance(data["rating_simple"], (int, float))
    assert isinstance(data["rating_decayed"], (int, float))


def assert_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert isinstance(data["court"], str) and len(data["court"]) > 0
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["status"] in ["INTAKE", "SOURCING", "ENGAGED", "DISCOVERY", "TRIAL_PREP", "CLOSED"]
    assert isinstance(data["actuals_paid_cents"], int) and data["actuals_paid_cents"] >= 0
    assert isinstance(data["committed_cents"], int) and data["committed_cents"] >= 0
    assert isinstance(data["approved_outstanding_cents"], int) and data["approved_outstanding_cents"] >= 0


def assert_engagement_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["specialty_area"], str) and len(data["specialty_area"]) > 0
    assert data["status"] in ["OPEN", "SCREENING", "READY", "FILLED"]


def assert_conflict_check(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_request_id", ""))
    assert is_valid_uuid(data.get("expert_id", ""))
    assert isinstance(data["adverse_parties"], list)
    assert data["status"] in ["PENDING", "CLEARED", "FLAGGED", "WAIVED"]


def assert_credential_review(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_request_id", ""))
    assert is_valid_uuid(data.get("expert_id", ""))
    assert data["status"] in ["PENDING", "PASSED", "FAILED", "PASSED_WITH_CONDITIONS"]


def assert_engagement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_request_id", ""))
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("expert_id", ""))
    assert data["status"] in ["DRAFT", "PROPOSED", "NEGOTIATING", "SIGNED", "ACTIVE", "CLOSED", "TERMINATED"]
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] > 0
    assert isinstance(data["retainer_cents"], int) and data["retainer_cents"] >= 0
    assert isinstance(data["expense_cap_cents"], int) and data["expense_cap_cents"] >= 0
    assert isinstance(data["negotiation_round_count"], int) and data["negotiation_round_count"] >= 0
    assert isinstance(data["nda_executed"], bool)
    assert isinstance(data["retainer_funded_cents"], int)
    assert isinstance(data["retainer_drawn_cents"], int)
    assert isinstance(data["retainer_refunded_cents"], int)
    assert isinstance(data["retainer_remaining_cents"], int)
    assert isinstance(data["expenses_approved_cents"], int)
    assert isinstance(data["created_by_user_id"], str)


def assert_document_production(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["privilege_tier"] in ["DISCOVERABLE", "WORK_PRODUCT", "PRIVILEGED"]
    assert isinstance(data["content_ref"], str)
    assert data["status"] in ["REQUESTED", "DELIVERED", "ACKNOWLEDGED", "RECALLED"]


def assert_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["report_type"] in ["LIABILITY", "DAMAGES", "REBUTTAL"]
    assert is_iso8601_timestamp(data.get("deadline_at", ""))
    assert data["status"] in ["DRAFT", "IN_REVIEW", "REVISION_REQUESTED", "FINALIZED", "DISCLOSED", "WITHDRAWN"]
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])


def assert_venue(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["location"], str) and len(data["location"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_testimony_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert data.get("venue_id") is None or is_valid_uuid(data["venue_id"])
    assert data["kind"] in ["DEPOSITION", "TRIAL"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["estimated_hours"], (int, float)) and data["estimated_hours"] > 0
    assert isinstance(data["travel_required"], bool)
    assert isinstance(data["actual_hours"], (int, float))
    assert isinstance(data["cancellation_fee_cents"], int)
    assert data["status"] in ["PROPOSED", "CONFIRMED", "COMPLETED", "CANCELLED"]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert isinstance(data["line_items"], list)
    assert isinstance(data["travel_expense_cents"], int) and data["travel_expense_cents"] >= 0
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["computed_total_cents"], int)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DISPUTED", "PAID", "REJECTED"]
    assert isinstance(data["dispute_count"], int) and data["dispute_count"] >= 0
    assert isinstance(data["retainer_draw_cents"], int)
    assert isinstance(data["billed_to_client_cents"], int)


def assert_evaluation(data: dict):
    """Evaluation is the immutable-record exception: only id + created_at from the
    standard property set; updated_at and version MUST be absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Evaluation must not carry updated_at"
    assert "version" not in data, "Evaluation must not carry version"
    assert is_valid_uuid(data.get("engagement_id", ""))
    assert is_valid_uuid(data.get("expert_id", ""))
    assert isinstance(data["overall_score"], (int, float))
    assert 0.0 <= data["overall_score"] <= 5.0
    assert is_iso8601_timestamp(data.get("evaluated_at", ""))


def assert_retainer_invariant(engagement: dict):
    """The retainer ledger conservation invariant: funded == drawn + refunded + remaining,
    and remaining never goes negative."""
    funded = engagement["retainer_funded_cents"]
    drawn = engagement["retainer_drawn_cents"]
    refunded = engagement["retainer_refunded_cents"]
    remaining = engagement["retainer_remaining_cents"]
    assert funded == drawn + refunded + remaining, (
        f"retainer invariant broken: funded {funded} != drawn {drawn} + refunded {refunded} + remaining {remaining}"
    )
    assert remaining >= 0, "retainer_remaining_cents must never go negative"
