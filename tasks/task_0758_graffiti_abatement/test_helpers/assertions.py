"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_append_only(data: dict):
    """Append-only records carry id + created_at ONLY (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_property_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["mailing_address"], str)
    assert isinstance(data["contact_email"], str)


def assert_site(data: dict):
    _assert_common(data)
    assert data["ownership_type"] in ("PUBLIC", "PRIVATE")
    assert data["status"] in ("NORMAL", "MONITORED", "HOTSPOT")
    assert isinstance(data["report_count_90d"], int)
    assert isinstance(data["open_report_count"], int)
    assert isinstance(data["hotspot_severity_index_rolling"], int)
    assert isinstance(data["hotspot_severity_index_confirmed"], int)
    assert isinstance(data["outstanding_recovery_cents"], int)
    assert isinstance(data["lien_count"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert data["reported_via"] in ("PHONE_311", "WEB", "MOBILE_APP")
    assert data["surface_type"] in ("WALL", "FENCE", "SIGN", "SIDEWALK", "VEHICLE")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "SEVERE")
    assert isinstance(data["is_offensive"], bool)
    assert data["status"] in (
        "SUBMITTED", "TRIAGED", "DISPATCHED", "IN_PROGRESS", "REMEDIATED", "CLOSED"
    )


def assert_crew(data: dict):
    _assert_common(data)
    assert data["crew_type"] in ("CITY", "CONTRACTOR")
    assert isinstance(data["is_offensive_certified"], bool)
    assert data["status"] in ("AVAILABLE", "DISPATCHED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["method"] in ("PAINT_OVER", "PRESSURE_WASH", "CHEMICAL")
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", "RECALLED"
    )


def assert_material(data: dict):
    _assert_common(data)
    assert data["category"] in ("PAINT", "SOLVENT", "ABRASIVE")
    assert data["unit"] in ("LITERS", "GALLONS")
    assert isinstance(data["unit_cost_cents"], int)
    assert data["status"] in ("AVAILABLE", "LOW", "DEPLETED")


def assert_material_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "CONSUMED", "RELEASED")


def assert_cost_recovery(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "ASSESSED", "DISPUTED", "WAIVED", "LIEN_PENDING", "PAID", "VOID"
    )
    for f in ("estimated_cost_cents", "labor_cost_cents", "material_cost_cents",
              "admin_fee_cents", "recoverable_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer count of cents"


def assert_notice(data: dict):
    _assert_common(data)
    assert data["notice_type"] in ("ABATEMENT_NOTICE", "COST_RECOVERY_NOTICE")
    assert data["status"] in ("SENT", "CONSENTED", "DISPUTED", "EXPIRED", "WITHDRAWN")


def assert_photo(data: dict):
    _assert_append_only(data)
    assert data["phase"] in ("BEFORE", "AFTER")


def assert_removal_log(data: dict):
    _assert_append_only(data)
    assert data["action"] in ("STARTED", "COMPLETED", "RECALLED")
