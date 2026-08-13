"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every primary resource carries id, created_at, updated_at, version (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("landfill_tip_fee_per_ton_cents"), int)
    assert isinstance(data.get("max_rebate_rate_per_ton_cents"), int)
    assert data.get("certification_tier") in ["NONE", "BRONZE", "SILVER", "GOLD", "ZERO_WASTE"]
    assert data.get("program_standing") in ["GOOD_STANDING", "WATCH", "PROBATION"]


def assert_vendor(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("vendor_type") in ["HAULER", "RECYCLER", "PROCESSOR"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED"]


def assert_contract(data: dict):
    assert_common_fields(data)
    for f in ("site_id", "vendor_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a valid UUID"
    assert data.get("material_stream") in [
        "MIXED_RECYCLABLES", "CARDBOARD", "COMPOST_ORGANICS", "MIXED_SOLID_WASTE", "E_WASTE",
    ]
    assert isinstance(data.get("rebate_per_ton_cents"), int)
    assert isinstance(data.get("contamination_penalty_per_ton_cents"), int)
    assert data.get("status") in ["DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED", "EXPIRED"]


def assert_ticket(data: dict):
    assert_common_fields(data)
    for f in ("site_id", "vendor_id", "contract_id"):
        assert is_valid_uuid(data.get(f, "")), f"{f} must be a valid UUID"
    assert data.get("disposal_route") in [
        "RECYCLING", "COMPOSTING", "REUSE", "LANDFILL", "ENERGY_RECOVERY",
    ]
    assert isinstance(data.get("gross_weight_lbs"), int)
    assert isinstance(data.get("tare_weight_lbs"), int)
    assert isinstance(data.get("net_weight_lbs"), int)
    assert data.get("validation_status") in ["PENDING", "VALIDATED", "REJECTED", "VOIDED"]


def assert_audit(data: dict):
    """WasteAudit is the immutable exception (§2.4): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "audit must not carry updated_at"
    assert "version" not in data, "audit must not carry version"


def assert_contamination_event(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data.get("severity") in ["MINOR", "MAJOR", "CRITICAL"]
    assert data.get("status") in [
        "OPEN", "TRAINING_ASSIGNED", "TRAINING_COMPLETED", "VERIFIED_CLOSED", "DISMISSED",
    ]


def assert_goal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data.get("metric") in ["DIVERSION_RATE", "COST_AVOIDANCE", "CONTAMINATION_EVENTS"]
    assert data.get("status") in ["ACTIVE", "ACHIEVED", "MISSED", "CANCELLED"]


def assert_period(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert data.get("status") in ["OPEN", "CLOSED"]
    for f in (
        "total_waste_lbs_validated", "diverted_lbs_validated",
        "total_waste_lbs_provisional", "diverted_lbs_provisional",
        "rebate_estimate_cents", "contamination_event_count",
    ):
        assert isinstance(data.get(f), int), f"{f} must be int"
    for f in ("diversion_rate_certified_pct", "diversion_rate_provisional_pct"):
        assert isinstance(data.get(f), (int, float)), f"{f} must be numeric"


def assert_application(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("site_id", ""))
    assert is_valid_uuid(data.get("reporting_period_id", ""))
    assert data.get("level_requested") in ["BRONZE", "SILVER", "GOLD", "ZERO_WASTE"]
    assert data.get("status") in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED",
        "REJECTED", "WITHDRAWN", "SUPERSEDED", "LAPSED",
    ]
