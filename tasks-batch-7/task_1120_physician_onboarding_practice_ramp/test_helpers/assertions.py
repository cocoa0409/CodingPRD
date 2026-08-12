"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_physician(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["specialty"] in [
        "FAMILY_MEDICINE", "INTERNAL_MEDICINE", "CARDIOLOGY", "ORTHOPEDICS", "PEDIATRICS",
    ]
    assert isinstance(data["email"], str) and data["email"]
    assert data["hire_type"] in ["NEW_GRAD", "EXPERIENCED", "LEADERSHIP"]
    assert data["status"] in ["PROSPECT", "ONBOARDING", "ACTIVE", "SEPARATED"]


def assert_onboarding_case(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("physician_id", ""))
    assert data["case_status"] in ["IN_PROGRESS", "HIRED", "SEPARATED"]
    assert data["credential_status"] in ["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "BLOCKED"]
    assert data["training_status"] in ["NOT_STARTED", "IN_PROGRESS", "COMPLETE"]
    assert data["practice_status"] in ["PLANNING", "BUILDING", "READY"]
    assert data["posture"] in ["PRE_CONTRACT", "CREDENTIALING", "RAMP_PREP", "GO_LIVE_READY", "LIVE"]
    assert isinstance(data["weekly_active_minutes"], int)
    assert isinstance(data["attained_milestone_count"], int)
    assert isinstance(data["missed_milestone_count"], int)
    assert isinstance(data["at_risk"], bool)


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["base_salary_cents"], int)
    assert isinstance(data["signing_bonus_cents"], int)
    assert isinstance(data["guarantee_monthly_cents"], int)
    assert isinstance(data["guarantee_term_months"], int)
    assert isinstance(data["panel_capacity"], int)
    assert isinstance(data["negotiation_round"], int)
    assert data["status"] in [
        "DRAFT", "EXTENDED", "COUNTERED", "ACCEPTED", "EXECUTED",
        "SUPERSEDED", "WITHDRAWN", "DECLINED", "EXPIRED",
    ]


def assert_credential_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert data["item_type"] in [
        "STATE_LICENSE", "DEA_REGISTRATION", "BOARD_CERTIFICATION",
        "PAYER_ENROLLMENT_MEDICARE", "PAYER_ENROLLMENT_COMMERCIAL", "HOSPITAL_PRIVILEGES",
    ]
    assert data["status"] in [
        "PENDING", "DOCS_SUBMITTED", "VERIFIED", "FILED", "APPROVED",
        "REJECTED", "BLOCKED", "EXPIRED", "LAPSED",
    ]


def assert_training_plan(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["required_module_count"], int)
    assert isinstance(data["templates_required"], int)
    assert data["status"] in ["PLANNED", "IN_PROGRESS", "AWAITING_SIGNOFF", "COMPLETE"]


def assert_training_module(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("training_plan_id", ""))
    assert data["module_code"] in ["EHR_FUNDAMENTALS", "ORDER_ENTRY", "NOTE_TEMPLATES", "BILLING"]
    assert data["status"] in ["NOT_STARTED", "SCHEDULED", "COMPLETED", "FAILED"]


def assert_schedule_template(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["weekday"], int) and 1 <= data["weekday"] <= 7
    assert isinstance(data["start_minute"], int)
    assert isinstance(data["end_minute"], int)
    assert data["start_minute"] < data["end_minute"]
    assert data["block_type"] in ["CLINIC", "PROCEDURE", "OR", "ADMIN"]
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_panel(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["capacity"], int)
    assert isinstance(data["current_size"], int)
    assert data["status"] in ["NOT_OPEN", "OPEN", "FROZEN", "CLOSED"]


def assert_referral_campaign(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["budget_cents"], int)
    assert isinstance(data["spent_cents"], int)
    assert isinstance(data["referrals_attributed"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED"]


def assert_campaign_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert data["event_type"] in ["COMMUNITY_TALK", "REFERRAL_DINNER", "MEDIA", "OPEN_HOUSE"]
    assert isinstance(data["cost_cents"], int)
    assert data["status"] in ["PLANNED", "HELD", "CANCELLED"]


def assert_income_guarantee(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["monthly_guarantee_cents"], int)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["months_reconciled"], int)
    assert isinstance(data["total_advanced_cents"], int)
    assert isinstance(data["projected_total_draw_cents"], int)
    assert isinstance(data["forgiveness_accrued_cents"], int)
    assert isinstance(data["total_repaid_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SETTLED"]


def assert_ramp_milestone(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert isinstance(data["month_offset"], int)
    assert isinstance(data["target_wrvu"], int)
    assert data["status"] in ["PENDING", "REPORTED", "ATTESTED", "LAPSED"]


def assert_mentorship_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert is_valid_uuid(data.get("mentor_physician_id", ""))
    assert isinstance(data["checkins_recorded"], int)
    assert isinstance(data["escalated"], bool)
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "COMPLETED"]


def assert_check_in(data: dict):
    """CheckIn is a point-in-time record: id and created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CheckIn must not expose updated_at"
    assert "version" not in data, "CheckIn must not expose version"
    assert is_valid_uuid(data.get("mentorship_id", ""))
    assert data["day_marker"] in ["D30", "D90", "D180", "D270", "D365"]
    assert data["sentiment"] in ["POSITIVE", "NEUTRAL", "CONCERN", "CRISIS"]


def assert_retention_snapshot(data: dict):
    """RetentionRiskSnapshot is a point-in-time record: no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "RetentionRiskSnapshot must not expose updated_at"
    assert "version" not in data, "RetentionRiskSnapshot must not expose version"
    assert is_valid_uuid(data.get("onboarding_case_id", ""))
    assert data["variant"] in ["TRAILING", "LEADING"]
    assert data["risk_band"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    for component in ("milestone_risk", "panel_risk", "sentiment_risk", "schedule_risk", "score"):
        assert isinstance(data[component], (int, float)), f"{component} must be numeric"


def assert_guarantee_ledger_invariants(data: dict):
    """Income guarantee ledger invariants from the pinned draw evaluation order."""
    assert data["outstanding_balance_cents"] >= 0
    assert data["outstanding_balance_cents"] == max(
        0,
        data["total_advanced_cents"]
        - data["total_repaid_cents"]
        - data["forgiveness_accrued_cents"],
    ), "outstanding must equal max(0, advanced - repaid - forgiveness)"
    assert data["projected_total_draw_cents"] >= data["total_advanced_cents"]
    assert 0 <= data["months_reconciled"] <= data["term_months"]
