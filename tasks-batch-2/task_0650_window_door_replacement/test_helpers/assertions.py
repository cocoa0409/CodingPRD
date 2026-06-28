"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_homeowner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["property_zip"], str)
    assert data["agi_band"] in ("LOW", "STANDARD", "HIGH")
    assert isinstance(data["referral_credit_cents"], int) and data["referral_credit_cents"] >= 0


def assert_project(data: dict):
    _assert_common(data)
    assert isinstance(data["homeowner_id"], str)
    assert data["jurisdiction_code"] in ("WEST_STRICT", "NORTHEAST_STD", "CENTRAL_LIGHT")
    assert data["status"] in (
        "LEAD", "CONSULTING", "QUOTING", "CONTRACTED", "IN_PRODUCTION",
        "INSTALLING", "INSPECTION", "COMPLETED", "CANCELLED",
    )


def assert_consultation(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["status"] in ("BOOKED", "MEASURED", "CANCELLED")
    assert isinstance(data["total_opening_count"], int) and data["total_opening_count"] >= 0


def assert_opening(data: dict):
    _assert_common(data)
    assert isinstance(data["consultation_id"], str)
    assert data["product_type"] in (
        "DOUBLE_HUNG", "CASEMENT", "PICTURE", "SLIDING_PATIO_DOOR", "ENTRY_DOOR",
    )
    assert data["glass_package"] in ("STANDARD", "LOWE_DUAL", "LOWE_TRIPLE")
    assert data["width_in"] > 0 and data["height_in"] > 0
    assert isinstance(data["energy_qualified"], bool)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0


def assert_quote(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["status"] in ("DRAFT", "SENT", "ACCEPTED", "REJECTED", "EXPIRED", "SUPERSEDED")


def assert_financing_application(data: dict):
    _assert_common(data)
    assert isinstance(data["quote_id"], str)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED", "CANCELLED")
    assert data["term_months"] in (12, 24, 36, 60)


def assert_manufacture_order(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["quote_id"], str)
    assert data["status"] in ("QUEUED", "IN_BUILD", "READY", "CANCELLED")


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["home_jurisdiction"] in ("WEST_STRICT", "NORTHEAST_STD", "CENTRAL_LIGHT")
    assert isinstance(data["daily_capacity_openings"], int) and data["daily_capacity_openings"] >= 1


def assert_install_job(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert isinstance(data["crew_id"], str)
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "COMPLETED", "CANCELLED")


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["status"] in ("FILED", "APPROVED", "INSPECTION_PASSED", "INSPECTION_FAILED")


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["project_id"], str)
    assert data["category"] in ("WARRANTY", "BILLABLE")
    assert data["status"] in ("OPEN", "DISPATCHED", "RESOLVED", "REOPENED", "CLOSED")


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["referrer_project_id"], str)
    assert isinstance(data["referred_project_id"], str)
    assert data["status"] in ("PENDING", "SETTLED", "VOID")
    assert isinstance(data["reward_amount_cents"], int) and data["reward_amount_cents"] >= 0
