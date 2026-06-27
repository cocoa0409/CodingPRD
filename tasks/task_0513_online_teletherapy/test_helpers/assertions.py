"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the shape the PRD promises for that resource;
field names are PRD-exact. SessionCredit and Message carry only id + created_at
(PRD §2.4), so their assertions forbid updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------
def assert_client(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Client.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["state_code"] in ("CA", "NY", "TX", "FL", "WA", "IL")
    assert data["status"] in (
        "PENDING_INTAKE", "AWAITING_MATCH", "ACTIVE", "SUSPENDED", "CLOSED"
    ), f"bad client status {data['status']}"
    assert data["financial_aid_tier"] in ("NONE", "TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert data["risk_flag"] in ("NONE", "ELEVATED", "ACUTE")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_therapist(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Therapist.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ONBOARDING", "ACCEPTING", "FULL", "INACTIVE")
    assert isinstance(data["max_active_caseload"], int) and data["max_active_caseload"] >= 1
    assert isinstance(data["active_caseload"], int) and data["active_caseload"] >= 0
    assert isinstance(data["specialties"], list)


def assert_therapist_license(data: dict):
    assert is_valid_uuid(data.get("id", "")), "TherapistLicense.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["state_code"] in ("CA", "NY", "TX", "FL", "WA", "IL")
    assert data["status"] in ("VALID", "EXPIRED", "REVOKED")


def assert_intake(data: dict):
    assert is_valid_uuid(data.get("id", "")), "IntakeQuestionnaire.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["presenting_concerns"], list) and len(data["presenting_concerns"]) > 0
    assert isinstance(data["severity_score"], int) and 0 <= data["severity_score"] <= 10


def assert_match(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Match.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PROPOSED", "ACTIVE", "SWITCH_REQUESTED", "ENDED")
    assert isinstance(data["match_score"], int)


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Subscription.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "TRIALING", "ACTIVE", "PAUSED", "CANCEL_SCHEDULED", "CANCELLED"
    )
    assert isinstance(data["base_weekly_fee_cents"], int) and data["base_weekly_fee_cents"] >= 0
    assert isinstance(data["weekly_credit_grant"], int) and 0 <= data["weekly_credit_grant"] <= 4


def assert_billing_cycle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BillingCycle.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PENDING", "PAID", "REFUNDED", "VOID")
    assert isinstance(data["list_amount_cents"], int)
    assert isinstance(data["wallet_applied_cents"], int)
    assert isinstance(data["charged_amount_cents"], int)


def assert_session_credit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SessionCredit.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("AVAILABLE", "RESERVED", "CONSUMED", "EXPIRED")
    # SessionCredit is common_fields:false — no version, no updated_at (PRD §2.4).
    assert "version" not in data, "SessionCredit must not expose version"
    assert "updated_at" not in data, "SessionCredit must not expose updated_at"


def assert_live_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "LiveSession.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["cancelled_within_window"], bool)


def assert_message_thread(data: dict):
    assert is_valid_uuid(data.get("id", "")), "MessageThread.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "FROZEN", "ARCHIVED")
    assert isinstance(data["unread_for_therapist"], int) and data["unread_for_therapist"] >= 0


def assert_message(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Message.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["sender_role"] in ("CLIENT", "THERAPIST")
    assert isinstance(data["body"], str) and len(data["body"]) > 0
    # Message is common_fields:false — no version, no updated_at (PRD §2.4).
    assert "version" not in data, "Message must not expose version"
    assert "updated_at" not in data, "Message must not expose updated_at"


def assert_crisis_escalation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "CrisisEscalation.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["severity"] in ("ELEVATED", "ACUTE")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert isinstance(data["safety_resources_sent"], bool)


def assert_financial_aid_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "FinancialAidApplication.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED")
    assert data["awarded_tier"] in ("NONE", "TIER_1", "TIER_2", "TIER_3")


def assert_superbill(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Superbill.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DRAFT", "ISSUED", "VOID")
    assert isinstance(data["session_count"], int) and data["session_count"] >= 0
    assert isinstance(data["reimbursable_amount_cents"], int) and data["reimbursable_amount_cents"] >= 0


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_billing_cycle_amounts_consistent(cycle: dict):
    """charged = list - wallet_applied (PRD §3.6); wallet never goes negative."""
    assert cycle["charged_amount_cents"] == (
        cycle["list_amount_cents"] - cycle["wallet_applied_cents"]
    ), (
        f"charged {cycle['charged_amount_cents']} != list {cycle['list_amount_cents']} "
        f"- wallet_applied {cycle['wallet_applied_cents']}"
    )
    assert cycle["wallet_applied_cents"] >= 0
    assert cycle["charged_amount_cents"] >= 0
