"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict, entity_label: str = "entity"):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer >= 1, got {data.get('version')}"
    )


def assert_membership_category(data: dict):
    _assert_common(data, "MembershipCategory")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["is_voting"], bool)
    assert isinstance(data["is_directory_eligible"], bool)
    assert isinstance(data["allows_auto_renew"], bool)
    assert isinstance(data["lapse_grace_days"], int)
    assert isinstance(data["reinstatement_window_days"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_dues_schedule(data: dict):
    _assert_common(data, "DuesSchedule")
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["annual_amount_cents"], int)
    assert isinstance(data["chapter_share_bps"], int)
    assert isinstance(data["increase_notice_days"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED"]


def assert_chapter(data: dict):
    _assert_common(data, "Chapter")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["is_affiliate"], bool)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DISSOLVED"]


def assert_renewal_cycle_policy(data: dict):
    _assert_common(data, "RenewalCyclePolicy")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["mode"] in ["ANNIVERSARY", "CALENDAR"]
    assert isinstance(data["calendar_anchor_month"], int)
    assert 1 <= data["calendar_anchor_month"] <= 12
    assert isinstance(data["calendar_anchor_day"], int)
    assert 1 <= data["calendar_anchor_day"] <= 31
    assert data["proration_method"] in ["PRO_RATA_DAILY", "FULL_PERIOD", "NONE"]
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("category_id", ""))
    assert is_valid_uuid(data.get("home_chapter_id", ""))
    assert is_valid_uuid(data.get("cycle_policy_id", ""))
    assert is_iso8601_timestamp(data.get("joined_at", ""))
    assert data["status"] in [
        "PENDING_VERIFICATION", "ACTIVE", "GRACE", "LAPSED",
        "REINSTATED", "EXPELLED", "RESIGNED",
    ]
    assert isinstance(data["lifetime_dues_paid_cents"], int)
    assert data["lifetime_dues_paid_cents"] >= 0


def assert_membership_term(data: dict):
    _assert_common(data, "MembershipTerm")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["opened_by"] in ["JOIN", "RENEWAL", "REINSTATEMENT", "ADMIN_ADJUST"]
    assert data["status"] in ["OPEN", "CLOSED", "VOID"]


def assert_dues_invoice(data: dict):
    _assert_common(data, "DuesInvoice")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("membership_term_id", ""))
    assert is_valid_uuid(data.get("dues_schedule_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["amount_cents"] >= 0
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    if data.get("settled_at") is not None:
        assert is_iso8601_timestamp(data["settled_at"])
    assert data["payment_status"] in [
        "PENDING", "SETTLED", "FAILED_RETRYABLE",
        "FAILED_FINAL", "REFUNDED", "WRITTEN_OFF",
    ]
    assert data["fulfillment_status"] in [
        "NOT_DUE", "COVERAGE_ACTIVE", "COVERAGE_SUSPENDED", "COVERAGE_ENDED",
    ]


def assert_payment_attempt(data: dict):
    _assert_common(data, "PaymentAttempt")
    assert is_valid_uuid(data.get("invoice_id", ""))
    assert isinstance(data["attempt_index"], int) and data["attempt_index"] >= 1
    assert is_iso8601_timestamp(data.get("attempted_at", ""))
    assert data["outcome"] in ["SUCCEEDED", "DECLINED_TRANSIENT", "DECLINED_HARD"]


def assert_auto_renew_authorization(data: dict):
    _assert_common(data, "AutoRenewAuthorization")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("authorized_at", ""))
    if data.get("revoked_at") is not None:
        assert is_iso8601_timestamp(data["revoked_at"])
    assert data["status"] in ["ACTIVE", "REVOKED", "SUSPENDED_HARD_DECLINE"]


def assert_benefit_entitlement(data: dict):
    _assert_common(data, "BenefitEntitlement")
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["benefit_code"] in [
        "JOURNAL_ACCESS", "CONFERENCE_DISCOUNT", "CERTIFICATION_REGISTRY",
        "VOTING_BALLOT", "DIRECTORY_LISTING",
    ]
    assert is_iso8601_timestamp(data.get("granted_at", ""))
    assert data["status"] in ["ACTIVE", "SUSPENDED", "REVOKED"]


def assert_directory_listing(data: dict):
    _assert_common(data, "DirectoryListing")
    assert is_valid_uuid(data.get("member_id", ""))
    assert isinstance(data["display_name"], str)
    assert isinstance(data["specialty_tags"], list)
    assert isinstance(data["is_public"], bool)
    assert data["visibility_state"] in [
        "VISIBLE", "HIDDEN_LAPSE", "HIDDEN_OPT_OUT", "HIDDEN_CATEGORY",
    ]


def assert_dues_increase_notice(data: dict):
    _assert_common(data, "DuesIncreaseNotice")
    assert is_valid_uuid(data.get("schedule_id", ""))
    assert is_iso8601_timestamp(data.get("noticed_at", ""))
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert isinstance(data["audience_size"], int) and data["audience_size"] >= 0
    assert data["status"] in ["SCHEDULED", "SENT", "CANCELLED"]


def assert_revenue_attribution(data: dict):
    _assert_common(data, "RevenueAttribution")
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["revenue_kind"] in [
        "CONFERENCE_REGISTRATION", "PUBLICATION_SALE", "CERTIFICATION_FEE", "DONATION",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    # fiscal_period is a computed YYYY-MM string
    fp = data.get("fiscal_period", "")
    assert isinstance(fp, str) and len(fp) == 7 and fp[4] == "-"


def assert_reinstatement_request(data: dict):
    _assert_common(data, "ReinstatementRequest")
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert is_valid_uuid(data.get("back_dues_invoice_id", ""))
    if data.get("decided_at") is not None:
        assert is_iso8601_timestamp(data["decided_at"])
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "EXPIRED"]
