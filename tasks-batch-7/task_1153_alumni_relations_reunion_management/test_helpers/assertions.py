"""Entity assertions and domain invariant checkers.

Every assertion helper validates the standard system-managed fields from
PRD §2.5 plus the entity's own fields and enum memberships.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert isinstance(data, dict), f"{entity} payload must be an object"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_alumni_record(data: dict):
    _assert_common(data, "AlumniRecord")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["primary_email"], str) and data["primary_email"]
    assert isinstance(data["class_year"], int)
    assert isinstance(data["degree_code"], str) and data["degree_code"]
    assert data["status"] in ("ACTIVE", "LOST", "DECEASED", "DO_NOT_CONTACT")
    assert data["engagement_tier"] in ("HIGH", "MEDIUM", "LOW")
    assert 0.0 <= float(data["engagement_score"]) <= 100.0
    assert 0.0 <= float(data["giving_propensity"]) <= 1.0
    assert isinstance(data["lifetime_giving_cents"], int) and data["lifetime_giving_cents"] >= 0


def assert_research_case(data: dict):
    _assert_common(data, "LostAlumniResearchCase")
    assert is_valid_uuid(data.get("alumni_id", ""))
    assert data["lead_source"] in (
        "SOCIAL_MEDIA", "PUBLIC_RECORDS", "PEER_TIP", "PROFESSIONAL_DATABASE"
    )
    assert isinstance(data["lead_detail"], str)
    assert isinstance(data["lead_confidence"], int)
    assert 1 <= data["lead_confidence"] <= 100
    assert data["status"] in ("OPEN", "LEAD_LOGGED", "VERIFIED", "REUNITED", "DEAD_END")
    assert isinstance(data["reopened_count"], int) and data["reopened_count"] >= 0


def assert_reunion_event(data: dict):
    _assert_common(data, "ReunionEvent")
    assert isinstance(data["class_year"], int)
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in (
        "PLANNING", "COMMITTEE_FORMED", "OPEN_FOR_REGISTRATION",
        "HELD", "RECONCILED", "CANCELLED",
    )
    assert data["posture"] in ("GATED", "OPEN", "SOLD_OUT", "CLOSED")
    assert isinstance(data["committee_count"], int) and data["committee_count"] >= 0
    assert isinstance(data["committee_quorum_required"], int)
    assert isinstance(data["total_revenue_cents"], int)


def assert_committee(data: dict):
    _assert_common(data, "ReunionCommittee")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["locked"], bool)


def assert_membership(data: dict):
    _assert_common(data, "CommitteeMembership")
    assert is_valid_uuid(data.get("committee_id", ""))
    assert is_valid_uuid(data.get("alumni_id", ""))
    assert data["role"] in ("CHAIR", "TREASURER", "LOGISTICS", "OUTREACH", "MEMBER")
    assert data["status"] in ("INVITED", "ACTIVE", "ENDED", "DECLINED")


def assert_ticket_tier(data: dict):
    _assert_common(data, "TicketTier")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert isinstance(data["early_bird_discount_pct"], int)


def assert_registration(data: dict):
    _assert_common(data, "EventRegistration")
    assert is_valid_uuid(data.get("event_id", ""))
    assert is_valid_uuid(data.get("tier_id", ""))
    assert is_valid_uuid(data.get("alumni_id", ""))
    assert data["payment_status"] in (
        "PENDING_PAYMENT", "CONFIRMED", "REFUNDED", "CANCELLED"
    )
    assert data["attendance_status"] in ("NOT_CHECKED_IN", "CHECKED_IN")


def assert_affinity_group(data: dict):
    _assert_common(data, "AffinityGroup")
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("AFFINITY", "REGIONAL_CHAPTER")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DISSOLVED")
    assert isinstance(data["annual_budget_cents"], int)
    assert isinstance(data["budget_committed_cents"], int)
    assert isinstance(data["budget_spent_cents"], int)
    assert isinstance(data["budget_remaining_cents"], int)


def assert_program(data: dict):
    _assert_common(data, "ChapterProgram")
    assert is_valid_uuid(data.get("group_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["budget_allocated_cents"], int)
    assert data["status"] in (
        "DRAFT", "PROPOSED", "APPROVED", "PUBLISHED", "COMPLETED", "CANCELLED"
    )
    assert is_valid_uuid(data.get("leader_id", ""))


def assert_preference(data: dict):
    _assert_common(data, "CommunicationPreference")
    assert is_valid_uuid(data.get("alumni_id", ""))
    assert data["channel"] in ("EMAIL", "MAIL", "PHONE")
    assert isinstance(data["opt_in"], bool)
    assert isinstance(data["suppressed"], bool)
    assert data["suppression_reason"] in (
        "NONE", "GLOBAL_LIST", "DO_NOT_CONTACT_RECORD", "HARD_BOUNCE"
    )


def assert_campaign(data: dict):
    _assert_common(data, "GiftCampaign")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["goal_cents"], int)
    assert isinstance(data["matching_multiplier_bps"], int)
    assert isinstance(data["pledged_total_cents"], int)
    assert isinstance(data["fulfilled_total_cents"], int)
    assert isinstance(data["matched_credit_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "ABANDONED")


def assert_pledge(data: dict):
    _assert_common(data, "GiftPledge")
    assert is_valid_uuid(data.get("campaign_id", ""))
    assert is_valid_uuid(data.get("alumni_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 100
    assert isinstance(data["matched_credit_cents"], int)
    assert data["status"] in ("PLEDGED", "FULFILLED", "LAPSED", "WRITTEN_OFF")


def assert_publication(data: dict):
    _assert_common(data, "MemorabiliaPublication")
    assert is_valid_uuid(data.get("event_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["class_notes_body"], str)
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    assert data["status"] in ("DRAFT", "IN_REVIEW", "APPROVED", "PUBLISHED")


def assert_group_budget_invariant(group: dict):
    """PRD §3.5: remaining budget equals annual minus committed minus spent."""
    assert group["budget_remaining_cents"] == (
        group["annual_budget_cents"]
        - group["budget_committed_cents"]
        - group["budget_spent_cents"]
    ), (
        f"Budget invariant violated: remaining {group['budget_remaining_cents']} != "
        f"{group['annual_budget_cents']} - {group['budget_committed_cents']} - "
        f"{group['budget_spent_cents']}"
    )
    assert group["budget_remaining_cents"] >= 0, "remaining budget must never go negative"
