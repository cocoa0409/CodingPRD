"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def _assert_immutable_record_fields(data: dict):
    """Waiver / TempLog / DonationReceipt carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable record must not expose updated_at"
    assert "version" not in data, "immutable record must not expose version"


def assert_farm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["farm_name"], str) and data["farm_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert isinstance(data["donor_tin"], str) and data["donor_tin"]
    assert isinstance(data["active_flag"], bool)
    assert isinstance(data["lifetime_donated_lbs"], (int, float))
    assert data["lifetime_donated_lbs"] >= 0


def assert_offer(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["crop_code"], str) and data["crop_code"]
    assert isinstance(data["estimated_lbs"], (int, float)) and data["estimated_lbs"] > 0
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["perishability_class"] in ("HIGH", "MEDIUM", "LOW")
    assert isinstance(data["requires_refrigeration"], bool)
    assert data["status"] in (
        "OFFERED", "SCHEDULED", "GLEANED", "CLOSED", "CANCELLED", "EXPIRED",
    )
    assert isinstance(data["actual_lbs"], (int, float)) and data["actual_lbs"] >= 0


def assert_volunteer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["crew_leader_certified"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0


def assert_waiver(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert is_valid_uuid(data.get("witness_volunteer_id", ""))
    assert data["volunteer_id"] != data["witness_volunteer_id"], (
        "witness must differ from signer"
    )
    assert isinstance(data["signature_payload"], str)
    assert is_iso8601_timestamp(data.get("signed_at", ""))


def assert_agency(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert isinstance(data["weekly_capacity_lbs"], (int, float))
    assert data["weekly_capacity_lbs"] > 0
    assert isinstance(data["refrigeration_capable"], bool)
    assert isinstance(data["active_flag"], bool)
    assert isinstance(data["current_week_committed_lbs"], (int, float))
    assert data["current_week_committed_lbs"] >= 0


def assert_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("surplus_offer_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert is_valid_uuid(data.get("crew_leader_volunteer_id", ""))
    assert is_valid_uuid(data.get("assigned_vehicle_id", ""))
    assert isinstance(data["crew_capacity"], int) and data["crew_capacity"] > 0
    assert data["status"] in (
        "DRAFT", "OPEN", "FULL", "IN_PROGRESS", "HARVESTED", "RECONCILED", "CANCELLED",
    )
    assert isinstance(data["crew_confirmed_count"], int) and data["crew_confirmed_count"] >= 0
    assert isinstance(data["total_harvested_lbs"], (int, float))
    assert isinstance(data["total_distributed_lbs"], (int, float))
    assert isinstance(data["undistributed_lbs"], (int, float))


def assert_assignment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert is_valid_uuid(data.get("volunteer_id", ""))
    assert data["status"] in ("PENDING", "CONFIRMED", "DECLINED", "NO_SHOW", "COMPLETED")


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert is_valid_uuid(data.get("container_id", ""))
    assert isinstance(data["gross_lbs"], (int, float)) and data["gross_lbs"] > 0
    assert isinstance(data["tare_lbs"], (int, float)) and data["tare_lbs"] >= 0
    assert isinstance(data["cull_lbs"], (int, float)) and data["cull_lbs"] >= 0
    assert isinstance(data["net_lbs"], (int, float))
    assert is_valid_uuid(data.get("recorded_by_volunteer_id", ""))
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_distribution(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert is_valid_uuid(data.get("agency_id", ""))
    assert isinstance(data["planned_lbs"], (int, float)) and data["planned_lbs"] > 0
    assert is_iso8601_timestamp(data.get("delivery_date", ""))
    assert data["status"] in ("SCHEDULED", "DELIVERED", "SHORTFALL", "CANCELLED")
    assert isinstance(data["cold_chain_intact"], bool)


def assert_container(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert isinstance(data["tare_lbs"], (int, float)) and data["tare_lbs"] > 0
    assert isinstance(data["capacity_lbs"], (int, float)) and data["capacity_lbs"] > 0
    assert isinstance(data["refrigerated"], bool)
    assert data["status"] in ("AVAILABLE", "IN_USE", "RETIRED")


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plate"], str) and data["plate"]
    assert isinstance(data["payload_capacity_lbs"], (int, float))
    assert data["payload_capacity_lbs"] > 0
    assert isinstance(data["refrigerated"], bool)
    assert data["status"] in ("AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE")


def assert_templog(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert isinstance(data["temp_f"], (int, float))
    assert isinstance(data["breach_flag"], bool)


def assert_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("glean_event_id", ""))
    assert data["severity"] in ("MINOR", "CRITICAL")
    assert isinstance(data["condemned_lbs"], (int, float)) and data["condemned_lbs"] > 0
    assert is_valid_uuid(data.get("reported_by_volunteer_id", ""))
    assert data["disposition"] in (
        "OPEN", "RESOLVED_COMPOST", "RESOLVED_ANIMAL_FEED", "RESOLVED_LANDFILL",
    )


def assert_receipt(data: dict):
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data.get("surplus_offer_id", ""))
    assert is_valid_uuid(data.get("farm_id", ""))
    assert isinstance(data["receipt_lbs"], (int, float)) and data["receipt_lbs"] >= 0
    assert isinstance(data["fair_market_value_cents"], int)
    assert data["fair_market_value_cents"] >= 0
    assert is_iso8601_timestamp(data.get("issued_at", ""))


def assert_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED")
    assert isinstance(data["total_gleaned_lbs"], (int, float))
    assert isinstance(data["meals_equivalent"], int)
    assert isinstance(data["agency_count"], int)
