"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_market(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["display_name"], str)
    assert isinstance(data["pricing_multiplier_bps"], int)
    assert isinstance(data["standard_turnaround_hours"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_photographer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["equipment_packages"], list) and len(data["equipment_packages"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data.get("committed_minutes_by_day", {}), dict)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_client_agent(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["brokerage_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data.get("credit_balance_cents", 0), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["order_ref"], str)
    assert data["equipment_package"] in ("STANDARD", "PREMIUM", "LUXURY")
    assert isinstance(data["photo_count"], int)
    assert data["state"] in (
        "DRAFT", "AWAITING_READINESS", "READY", "ASSIGNED", "AUTHORIZATION_PENDING",
        "CONFIRMED", "SHOT", "IN_EDIT", "DELIVERED", "REVISION_REQUESTED",
        "ACCEPTED", "CANCELLED_BY_CLIENT", "CANCELLED_WEATHER", "EXPIRED",
    )
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data.get("reschedule_count", 0), int)
    assert isinstance(data.get("revisions_used", 0), int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start_utc", ""))


def assert_checklist_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert isinstance(data["item_key"], str)
    assert isinstance(data["required"], bool)
    assert isinstance(data["checked"], bool)


def assert_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["kind"] in ("TWILIGHT_UPGRADE", "DRONE_STILLS", "DRONE_VIDEO", "RUSH_EDIT", "VIRTUAL_STAGING")
    assert data["state"] in ("PENDING", "ACTIVE", "CANCELLED", "REFUSED")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["extra_minutes"], int)


def assert_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["state"] in ("PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED")
    assert isinstance(data["attempt_number"], int)
    assert is_iso8601_timestamp(data.get("window_start_utc", ""))
    assert is_iso8601_timestamp(data.get("window_end_utc", ""))


def assert_bundle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["state"] in ("EDITING", "DELIVERED", "SUPERSEDED", "FINALIZED")
    assert isinstance(data["photo_asset_count"], int)
    assert isinstance(data["round_number"], int)


def assert_revision(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["state"] in ("OPEN", "IN_PROGRESS", "RESOLVED", "REJECTED_LATE", "REJECTED_EXHAUSTED")
    assert isinstance(data["is_free"], bool)
    assert isinstance(data["fee_cents"], int)


def assert_virtual_tour(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["variant"] in ("BRANDED", "UNBRANDED")
    assert data["state"] in ("HOSTED", "PUBLISHED", "SUSPENDED", "UNPUBLISHED")
    assert isinstance(data.get("hosted_url"), str) and data["hosted_url"]


def assert_license_grant(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert data["tier"] in ("MLS_COMPLIANT", "STANDARD_MARKETING", "EXTENDED")
    assert data["state"] in ("DORMANT", "ACTIVE", "SUSPENDED", "REVOKED")
    assert isinstance(data["fee_cents"], int)


def assert_reschedule_event(data: dict):
    """Append-only audit record: id + created_at only, no updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["kind"] in ("WEATHER", "CLIENT")
    assert is_iso8601_timestamp(data.get("old_start_utc", ""))
    assert is_iso8601_timestamp(data.get("new_start_utc", ""))
    assert isinstance(data["credit_applied_cents"], int)
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
