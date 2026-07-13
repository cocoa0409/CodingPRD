"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["permit_track"] in ("UNPERMITTED", "PERMIT_BY_RULE", "TITLE_V")
    assert data["compliance_status"] in ("COMPLIANT", "DEVIATION", "ENFORCEMENT", "SUSPENDED")
    assert isinstance(data["potential_to_emit_tpy"], (int, float))
    assert data["potential_to_emit_tpy"] >= 0
    assert isinstance(data["open_exceedance_count"], int) and data["open_exceedance_count"] >= 0
    assert isinstance(data["fee_balance_cents"], int)


def assert_source(data: dict):
    _assert_common(data)
    assert data["source_type"] in ("BOILER", "GENERATOR", "FLARE", "PROCESS_VENT", "STORAGE_TANK")
    assert data["pollutant"] in ("NOX", "SO2", "CO", "PM", "VOC")
    assert data["lifecycle_status"] in ("REGISTERED", "PERMITTED", "OPERATING", "SUSPENDED", "SHUTDOWN")
    assert data["monitoring_status"] in ("UNMONITORED", "STACK_TESTED", "CEM_ACTIVE")
    assert data["uncontrolled_pte_tpy"] >= 0
    assert data["controlled_pte_tpy"] >= 0


def assert_permit(data: dict):
    _assert_common(data)
    assert data["permit_type"] in ("PERMIT_BY_RULE", "TITLE_V")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PUBLIC_NOTICE", "ISSUED", "RENEWAL_PENDING", "REVOKED")
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0


def assert_inventory(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CERTIFIED", "AMENDED")
    assert isinstance(data["estimated_fee_cents"], int)
    assert isinstance(data["assessed_fee_cents"], int)
    assert isinstance(data["total_emissions_tons"], (int, float))


def assert_enforcement_action(data: dict):
    _assert_common(data)
    assert data["action_type"] in ("NOTICE_OF_VIOLATION", "VARIANCE", "PENALTY")
    assert data["status"] in (
        "INITIATED", "PENALTY_ASSESSED", "VARIANCE_GRANTED", "DISMISSED", "PAID", "CLOSED")
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0


def assert_fee_ledger_matches(facility: dict, certified_inventories: list):
    """PRD §2.8 invariant: fee_balance_cents == sum of assessed_fee_cents over
    the facility's CERTIFIED inventories."""
    expected = sum(inv["assessed_fee_cents"] for inv in certified_inventories)
    assert facility["fee_balance_cents"] == expected, (
        f"fee_balance_cents {facility['fee_balance_cents']} != sum of CERTIFIED "
        f"assessed fees {expected}")
