"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_utc(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating with/without fractional digits."""
    assert isinstance(value, str), f"expected ISO timestamp string, got {value!r}"
    v = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_talent(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Talent.id must be a UUID"
    assert isinstance(data["stage_name"], str) and data["stage_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["voice_profile"] in [
        "MALE_DEEP", "MALE_LIGHT", "FEMALE_DEEP", "FEMALE_LIGHT", "NONBINARY", "CHILD",
    ]
    assert isinstance(data["languages"], list)
    assert data["union_status"] in ["UNION", "NON_UNION", "FICORE"]
    assert isinstance(data["base_session_fee_cents"], int)
    assert data["roster_status"] in ["ACTIVE", "SUSPENDED", "OFFBOARDED"]
    assert isinstance(data["active_conflict_categories"], list)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_client(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Client.id must be a UUID"
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["contact_email"], str) and "@" in data["contact_email"]
    assert isinstance(data["billing_email"], str)
    assert data["account_status"] in ["ACTIVE", "SUSPENDED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_project(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Project.id must be a UUID"
    assert is_valid_uuid(data.get("client_id", "")), "Project.client_id must be a UUID"
    assert isinstance(data["title"], str)
    assert data["product_category"] in [
        "AUTOMOTIVE", "PHARMA", "FAST_FOOD", "FINANCE", "TECH", "RETAIL",
        "ALCOHOL", "GAMING",
    ]
    assert data["usage_type"] in ["BROADCAST", "DIGITAL", "TERM"]
    assert isinstance(data["spots_count"], int) and data["spots_count"] >= 1
    assert isinstance(data["brief_text"], str)
    assert is_iso8601_timestamp(data.get("audition_deadline", ""))
    assert data["status"] in [
        "DRAFT", "CASTING", "CAST", "IN_SESSION", "DELIVERED", "CLOSED", "CANCELLED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_self_audition(data: dict):
    assert is_valid_uuid(data.get("id", "")), "SelfAudition.id must be a UUID"
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("talent_id", ""))
    assert isinstance(data["audio_file_url"], str) and data["audio_file_url"]
    assert data["status"] in ["SUBMITTED", "SHORTLISTED", "REJECTED", "SELECTED"]
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_studio(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Studio.id must be a UUID"
    assert isinstance(data["studio_name"], str) and data["studio_name"]
    assert isinstance(data["has_directed_patch"], bool)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["operating_tz"], str) and data["operating_tz"]
    assert data["status"] in ["OPEN", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Session.id must be a UUID"
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("studio_id", ""))
    assert data["session_kind"] in ["PRIMARY", "PICKUP", "RETAKE"]
    assert isinstance(data["directed_patch"], bool)
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] >= 15
    assert data["status"] in ["TENTATIVE", "CONFIRMED", "COMPLETED", "CANCELLED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    if "end_at" in data and data["end_at"] is not None:
        # PRD §3.6: end_at is derived server-side as start_at plus duration_minutes.
        start = parse_utc(data["start_at"])
        end = parse_utc(data["end_at"])
        assert (end - start).total_seconds() == data["duration_minutes"] * 60


def assert_usage_terms(data: dict):
    assert is_valid_uuid(data.get("id", "")), "UsageTerms.id must be a UUID"
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["usage_type"] in ["BROADCAST", "DIGITAL", "TERM"]
    assert isinstance(data["buyout_cents"], int)
    assert isinstance(data["agent_commission_cents"], int)
    assert isinstance(data["talent_payout_cents"], int)
    assert data["locked_at_cast"] is True
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Invoice.id must be a UUID"
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["invoice_kind"] in ["BUYOUT", "SESSION_FEE", "PICKUP_FEE"]
    assert isinstance(data["talent_amount_cents"], int)
    assert isinstance(data["agent_commission_cents"], int)
    assert isinstance(data["total_cents"], int)
    # PRD §3.9: total_cents is exactly the sum of the other two amounts.
    assert data["total_cents"] == data["talent_amount_cents"] + data["agent_commission_cents"], (
        "invoice total_cents must equal talent_amount_cents + agent_commission_cents"
    )
    assert data["status"] in ["PENDING", "ISSUED", "PAID", "VOID"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_conflict_exclusion(data: dict):
    assert is_valid_uuid(data.get("id", "")), "ConflictExclusion.id must be a UUID"
    assert is_valid_uuid(data.get("talent_id", ""))
    assert data["product_category"] in [
        "AUTOMOTIVE", "PHARMA", "FAST_FOOD", "FINANCE", "TECH", "RETAIL",
        "ALCOHOL", "GAMING",
    ]
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["source"] in ["PROJECT_CAST", "MANUAL_HOLD"]
    assert data["status"] in ["ACTIVE", "RELEASED", "EXPIRED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_delivery(data: dict):
    """Delivery carries only id + created_at of the common fields (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "Delivery.id must be a UUID"
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("session_id", ""))
    assert isinstance(data["file_url"], str) and data["file_url"]
    assert is_iso8601_timestamp(data.get("delivered_at", ""))
    assert data["revision_window_hours"] == 72
    assert is_iso8601_timestamp(data.get("revision_window_closes_at", ""))
    assert isinstance(data["revision_requested"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "Delivery must not carry updated_at"
    assert "version" not in data, "Delivery must not carry version"


def assert_revision_window_math(delivery: dict):
    """revision_window_closes_at == delivered_at + 72 hours (PRD §3.8)."""
    delivered = parse_utc(delivery["delivered_at"])
    closes = parse_utc(delivery["revision_window_closes_at"])
    assert (closes - delivered).total_seconds() == 72 * 3600, (
        f"revision window must close exactly 72h after delivery; "
        f"delivered_at={delivery['delivered_at']}, closes_at={delivery['revision_window_closes_at']}"
    )
