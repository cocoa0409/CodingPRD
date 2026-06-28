"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version (entities with the full system field set)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def assert_homeowner(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["hoa_governed"], bool)
    assert isinstance(data["ground_snow_load_psf"], (int, float)) and data["ground_snow_load_psf"] >= 0
    assert isinstance(data["design_wind_speed_mph"], int) and data["design_wind_speed_mph"] >= 0


def assert_project(data: dict):
    _assert_common(data)
    assert data["structure_type"] in ("SCREEN_ROOM", "THREE_SEASON", "FOUR_SEASON")
    assert data["material"] in ("ALUMINUM", "VINYL", "THERMAL_BREAK_ALUMINUM")
    assert data["status"] in (
        "DRAFT", "MEASURED", "DESIGNED", "QUOTED", "PERMITTING", "APPROVED_TO_BUILD",
        "IN_MANUFACTURE", "INSTALLING", "INSPECTING", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["footprint_sqft"], (int, float))
    assert isinstance(data["requires_hoa"], bool)
    assert isinstance(data["requires_engineering"], bool)


def assert_measurement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACCEPTED", "SUPERSEDED")
    assert data["width_in"] > 0 and data["depth_in"] > 0 and data["wall_height_in"] > 0


def assert_quote(data: dict):
    _assert_common(data)
    assert data["variant"] in ("ESTIMATE", "FINAL")
    assert data["status"] in ("ISSUED", "ACCEPTED", "REJECTED", "SUPERSEDED")
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 1
    for f in ("base_price_cents", "addons_cents", "tax_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    # Total is the sum of base + addons + tax (PRD §3.2).
    assert data["total_cents"] == data["base_price_cents"] + data["addons_cents"] + data["tax_cents"]


def assert_financing_application(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DECLINED")
    assert isinstance(data["amount_financed_cents"], int)
    assert data["term_months"] in (12, 24, 36, 60)


def assert_permit_application(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "IN_REVIEW", "REJECTED", "APPROVED", "EXPIRED")
    assert data["hoa_status"] in ("NOT_REQUIRED", "PENDING", "HOA_APPROVED", "HOA_DENIED")
    assert isinstance(data["hoa_required"], bool)
    assert isinstance(data["resubmission_count"], int) and data["resubmission_count"] >= 0


def assert_engineering_review(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "PASSED", "FAILED")


def assert_manufacture_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "IN_PRODUCTION", "READY", "CANCELLED")
    assert isinstance(data["lead_time_days"], int)


def assert_install_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["max_wind_mph"], int) and data["max_wind_mph"] >= 0
    assert isinstance(data["certified_four_season"], bool)
    assert isinstance(data["active"], bool)


def assert_install_job(data: dict):
    _assert_common(data)
    assert data["progress_status"] in ("SCHEDULED", "IN_PROGRESS", "INSTALLED")
    assert data["weather_status"] in ("CLEAR", "WEATHER_HOLD")


def assert_inspection(data: dict):
    _assert_common(data)
    assert data["result"] in ("SCHEDULED", "PASSED", "FAILED_PUNCHLIST")
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert isinstance(data["punchlist_items"], int) and data["punchlist_items"] >= 0


def assert_warranty(data: dict):
    """Warranty is immutable: id + created_at only — NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["structure_type"] in ("SCREEN_ROOM", "THREE_SEASON", "FOUR_SEASON")
    assert isinstance(data["term_years"], int)
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("expires_at", "")), "expires_at must be ISO 8601"


def count_accepted(items: list, field: str = "status") -> int:
    """Count entities in a list whose status/result field equals ACCEPTED."""
    return sum(1 for it in items if it.get(field) == "ACCEPTED")
