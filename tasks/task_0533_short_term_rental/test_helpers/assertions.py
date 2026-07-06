"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0
    assert isinstance(data["str_eligible"], bool)
    assert isinstance(data["whole_home_allowed"], bool)
    assert isinstance(data["permit_cap"], int) and data["permit_cap"] >= 0
    assert isinstance(data["active_permit_count"], int) and data["active_permit_count"] >= 0
    assert isinstance(data["lottery_enabled"], bool)


def assert_host(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["strike_total"], int) and data["strike_total"] >= 0
    assert data["standing"] in ("GOOD", "BARRED")


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["street_address"], str) and len(data["street_address"]) > 0
    assert isinstance(data["bedroom_count"], int) and data["bedroom_count"] >= 1
    assert isinstance(data["is_primary_residence"], bool)
    assert isinstance(data["max_occupancy"], int)


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["host_id"], str)
    assert isinstance(data["zone_id"], str)
    assert data["permit_type"] in ("PRIMARY_RESIDENCE", "WHOLE_HOME")
    assert isinstance(data["attested_occupancy"], int)
    assert isinstance(data["safety_attested"], bool)
    assert isinstance(data["nightly_base_rate_cents"], int)
    assert data["status"] in (
        "DRAFT", "LOTTERY_PENDING", "ISSUED", "ACTIVE",
        "SUSPENDED", "REVOKED", "EXPIRED", "REJECTED",
    )


def assert_complaint(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert data["category"] in ("NOISE", "TRASH", "OVER_OCCUPANCY", "UNPERMITTED")
    assert isinstance(data["strike_points"], int)
    assert data["status"] in ("OPEN", "DISMISSED", "UPHELD")


def assert_tax_filing(data: dict):
    _assert_common(data)
    assert isinstance(data["permit_id"], str)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert isinstance(data["nights_booked"], int)
    assert isinstance(data["gross_revenue_cents"], int)
    assert isinstance(data["amount_remitted_cents"], int)
    assert data["status"] in ("DRAFT", "FILED", "REMITTED", "DELINQUENT")


def assert_lottery_round(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_id"], str)
    assert isinstance(data["seats_available"], int) and data["seats_available"] >= 0
    assert isinstance(data["awarded_permit_ids"], list)
    assert data["status"] in ("OPEN", "DRAWN")


def assert_platform(data: dict):
    _assert_common(data)
    assert isinstance(data["platform_name"], str) and len(data["platform_name"]) > 0


def assert_listing_report(data: dict):
    """ListingReport is append-only: id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["match_result"] in (
        "MATCHED", "ADDRESS_MISMATCH", "NO_PERMIT", "PERMIT_INACTIVE",
    )
