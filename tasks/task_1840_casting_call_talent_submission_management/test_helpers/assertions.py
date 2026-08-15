"""Entity assertions and domain invariant checkers.

Field presence follows PRD section 2.5 (every resource carries id, created_at,
updated_at, version) plus the entity fields named in the section 3 workflows.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_production(data: dict):
    _assert_common(data, "Production")
    assert isinstance(data["title"], str) and data["title"]
    assert data["production_type"] in ["FILM", "TV_SERIES", "COMMERCIAL", "THEATER", "NEW_MEDIA"]
    assert isinstance(data["union_signatory"], bool)
    assert data["status"] in ["SETUP", "CASTING", "LOCKED", "COMPLETED"]
    assert isinstance(data["active_breakdown_count"], int) and data["active_breakdown_count"] >= 0


def assert_role(data: dict):
    _assert_common(data, "Role")
    assert isinstance(data["character_name"], str) and data["character_name"]
    assert isinstance(data["is_minor_role"], bool)
    assert isinstance(data["is_union_covered"], bool)
    assert data["status"] in ["OPEN", "CAST", "CANCELLED"]


def assert_breakdown(data: dict):
    _assert_common(data, "Breakdown")
    assert data["distribution"] in ["AGENT_ONLY", "OPEN_CALL"]
    assert data["status"] in ["DRAFT", "RELEASED_AGENT_ONLY", "RELEASED_OPEN", "CLOSED", "CANCELLED"]
    assert isinstance(data["rate_weekly_cents"], int) and data["rate_weekly_cents"] > 0
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0


def assert_talent(data: dict):
    _assert_common(data, "Talent")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["is_minor"], bool)
    assert data["union_status"] in ["UNION_MEMBER", "NON_UNION", "ELIGIBLE_PENDING"]
    assert isinstance(data["union_engagement_count_365d"], int) and data["union_engagement_count_365d"] >= 0


def assert_agent(data: dict):
    _assert_common(data, "AgentProfile")
    assert data["franchise_status"] in ["FRANCHISED", "NON_FRANCHISED"]
    assert isinstance(data["active"], bool)


def assert_guardian(data: dict):
    _assert_common(data, "Guardian")
    assert isinstance(data["full_name"], str) and data["full_name"]


def assert_submission(data: dict):
    _assert_common(data, "Submission")
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "SHORTLISTED", "REJECTED", "CALLBACK_INVITED",
        "CALLBACK_COMPLETED", "OFFER_PENDING", "BOOKED", "NOT_BOOKED", "WITHDRAWN",
    ]
    assert data["submitted_via"] in ["AGENT", "SELF"]


def assert_self_tape(data: dict):
    _assert_common(data, "SelfTape")
    assert isinstance(data["duration_seconds"], int)
    assert isinstance(data["tape_index"], int) and data["tape_index"] >= 1
    assert data["status"] in ["RECEIVED", "ACCEPTED", "REJECTED"]


def assert_session(data: dict):
    _assert_common(data, "AuditionSession")
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0


def assert_appointment(data: dict):
    _assert_common(data, "CallbackAppointment")
    assert data["status"] in ["PROPOSED", "CONFIRMED", "DECLINED", "CANCELLED", "NO_SHOW"]


def assert_hold(data: dict):
    _assert_common(data, "AvailabilityHold")
    assert data["hold_kind"] in ["PIN", "AVAIL"]
    assert data["status"] in ["ACTIVE", "CONFIRMED", "RELEASED", "EXPIRED", "OUTBID"]
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1


def assert_offer(data: dict):
    _assert_common(data, "Offer")
    assert data["status"] in ["EXTENDED", "COUNTERED", "ACCEPTED", "DECLINED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["weekly_rate_cents"], int) and data["weekly_rate_cents"] > 0
    assert isinstance(data["guarantee_cents"], int) and data["guarantee_cents"] >= 0
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_deal_memo(data: dict):
    _assert_common(data, "DealMemo")
    assert data["status"] in ["EXECUTED", "VOIDED"]
    assert data["proration_mode"] in ["CALENDAR_SPAN", "WORKDAY_SPAN"]
    assert isinstance(data["computed_fee_cents"], int) and data["computed_fee_cents"] >= 0
    assert isinstance(data["cancellation_penalty_cents"], int) and data["cancellation_penalty_cents"] >= 0


def assert_permit(data: dict):
    _assert_common(data, "MinorWorkPermit")
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "EXPIRED", "REVOKED"]
    assert isinstance(data["max_daily_hours_school_day"], int)
    assert isinstance(data["max_daily_hours_non_school_day"], int)


def assert_booking(data: dict):
    _assert_common(data, "Booking")
    assert data["status"] in ["PENDING", "CONFIRMED", "CANCELLED"]


def assert_taft_hartley_report(data: dict):
    _assert_common(data, "TaftHartleyReport")
    assert data["status"] in ["PENDING", "FILED", "LATE", "WAIVED"]
    assert data["reason_code"] in ["SPECIAL_SKILL", "FIRST_EMPLOYMENT", "EXIGENCY"]
