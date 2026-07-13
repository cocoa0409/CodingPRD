"""Entity assertions and domain invariant checkers for the APS API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_report(data: dict):
    _common(data)
    assert data["status"] in ("RECEIVED", "SCREENED_IN", "SCREENED_OUT")
    assert data["reporter_type"] in ("MANDATORY", "VOLUNTARY", "ANONYMOUS")
    assert data["priority"] in ("EMERGENCY", "PRIORITY", "ROUTINE")
    assert isinstance(data["allegation_types"], list) and len(data["allegation_types"]) >= 1
    assert isinstance(data["client_id"], str)


def assert_client(data: dict):
    _common(data)
    assert data["capacity_status"] in ("UNKNOWN", "INTACT", "IMPAIRED")
    assert data["status"] in (
        "INTAKE", "UNDER_INVESTIGATION", "SERVICES_PENDING", "SERVICES_ACTIVE", "CLOSED",
    )
    assert data["placement_status"] in ("NONE", "PLACED")
    assert data["risk_level"] in (None, "LOW", "MODERATE", "HIGH")
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0


def assert_account(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "FROZEN")
    assert_account_money_invariant(data)


def assert_account_money_invariant(data: dict):
    """available + frozen == total; every amount is a non-negative integer (PRD 3.5)."""
    total = data["total_balance_cents"]
    avail = data["available_balance_cents"]
    frozen = data["frozen_amount_cents"]
    assert isinstance(total, int) and total >= 0
    assert isinstance(avail, int) and avail >= 0
    assert isinstance(frozen, int) and frozen >= 0
    assert avail + frozen == total, (
        f"available({avail}) + frozen({frozen}) must equal total({total})"
    )


def assert_facility(data: dict):
    _common(data)
    assert_facility_bed_invariant(data)


def assert_facility_bed_invariant(data: dict):
    """available + occupied == total beds (PRD 3.4)."""
    total = data["total_beds"]
    avail = data["available_beds"]
    occ = data["occupied_beds"]
    assert avail + occ == total, (
        f"available({avail}) + occupied({occ}) must equal total_beds({total})"
    )


def assert_case(data: dict):
    _common(data)
    assert data["status"] in ("OPEN", "UNDER_INVESTIGATION", "READY_FOR_CLOSURE", "CLOSED")
    assert data["guardianship_status"] in ("NONE", "REFERRED")
    assert data["service_plan_status"] in ("NONE", "ACTIVE", "TERMINATED")


def assert_investigation(data: dict):
    _common(data)
    assert data["status"] in ("IN_PROGRESS", "FINDINGS_SUBMITTED", "DISPOSED")
    assert data["disposition"] in (None, "SUBSTANTIATED", "UNSUBSTANTIATED", "INCONCLUSIVE")
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0


def assert_placement(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "DISCHARGED", "EXPIRED")


def assert_freeze(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "LIFTED")
