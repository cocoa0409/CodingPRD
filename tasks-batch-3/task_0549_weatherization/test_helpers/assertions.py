"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names and enum value-sets track the PRD exactly.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"


def assert_dwelling(data: dict):
    _assert_common(data)
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert isinstance(data["year_built"], int)
    assert data["foundation_type"] in ("SLAB", "CRAWLSPACE", "BASEMENT")
    assert data["heating_fuel_type"] in ("GAS", "ELECTRIC", "OIL", "PROPANE")


def assert_wap_application(data: dict):
    _assert_common(data)
    assert isinstance(data["income_limit_cents"], int)
    assert data["status"] in ("ELIGIBLE", "INELIGIBLE")


def assert_job(data: dict):
    _assert_common(data)
    assert data["job_status"] in ("ACTIVE", "COMPLETED", "CANCELLED")
    assert data["install_status"] in ("PLANNED", "SCHEDULED", "INSTALLED")
    assert data["verification_status"] in ("PENDING", "PASSED", "FAILED")
    for f in (
        "total_estimated_cost_cents",
        "approved_rebate_total_cents",
        "tax_credit_cents",
        "estimated_out_of_pocket_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"
        assert data[f] >= 0, f"{f} must be >= 0"


def assert_energy_audit(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED")


def assert_diagnostic_test(data: dict):
    # Append-only event: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("BLOWER_DOOR", "DUCT_LEAKAGE")
    assert data["stage"] in ("BASELINE", "POST")
    assert data["cfm_measured"] > 0


def assert_scope_item(data: dict):
    _assert_common(data)
    assert data["category"] in (
        "ATTIC_INSULATION",
        "WALL_INSULATION",
        "CRAWL_INSULATION",
        "AIR_SEALING",
        "DUCT_SEALING",
    )
    assert data["status"] in (
        "PROPOSED",
        "APPROVED",
        "REJECTED",
        "INSTALLED",
        "VERIFIED",
        "FAILED_VERIFICATION",
        "CANCELLED",
    )


def assert_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["committed_days"], int)
    assert isinstance(data["available_days"], int)
    assert data["available_days"] == data["capacity_days"] - data["committed_days"]


def assert_crew_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CANCELLED")
    assert isinstance(data["duration_days"], int)


def assert_rebate_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "APPROVED", "DENIED", "VOIDED")
    assert isinstance(data["provisional_amount_cents"], int)


def assert_financing_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "SUPERSEDED")
    assert isinstance(data["monthly_payment_cents"], int)


def assert_job_money_invariants(data: dict):
    """Money invariants that must hold on any job read."""
    assert data["estimated_out_of_pocket_cents"] >= 0, "out-of-pocket is floored at 0"
    assert data["approved_rebate_total_cents"] >= 0
    assert data["tax_credit_cents"] >= 0
