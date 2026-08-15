"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CycleStatus, EngagementStatus, EvidenceStatus, FactorStatus,
    InstrumentStatus, InventoryStatus, QuestionnaireStatus, RecordStatus,
    SiteStatus, TargetStatus, TrajectoryStatus, BaselineSource,
)


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: id, created_at, updated_at, version on every resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def _assert_enum(data: dict, field: str, enum, entity: str):
    allowed = {e.value for e in enum}
    assert data.get(field) in allowed, (
        f"{entity}.{field} must be one of {sorted(allowed)}, got {data.get(field)!r}"
    )


def assert_site(data: dict):
    _assert_common_fields(data, "Site")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("country_code"), str) and data["country_code"]
    assert isinstance(data.get("grid_region_code"), str) and data["grid_region_code"]
    _assert_enum(data, "status", SiteStatus, "Site")


def assert_emission_factor(data: dict):
    _assert_common_fields(data, "EmissionFactor")
    assert isinstance(data.get("scope_category"), str)
    assert isinstance(data.get("region_code"), str) and data["region_code"]
    assert isinstance(data.get("unit"), str) and data["unit"]
    assert isinstance(data.get("value_tco2e_per_unit"), (int, float))
    assert isinstance(data.get("library_version"), int)
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))
    _assert_enum(data, "status", FactorStatus, "EmissionFactor")


def assert_reporting_cycle(data: dict):
    _assert_common_fields(data, "ReportingCycle")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("reporting_year"), int)
    _assert_enum(data, "status", CycleStatus, "ReportingCycle")
    assert isinstance(data.get("readiness_pct"), (int, float))
    assert data.get("pinned_library_version") is None or isinstance(data["pinned_library_version"], int)
    assert data.get("assurance_statement") is None or isinstance(data["assurance_statement"], str)


def assert_activity_record(data: dict):
    _assert_common_fields(data, "ActivityRecord")
    for fk in ("cycle_id", "site_id", "factor_id"):
        assert is_valid_uuid(data.get(fk, "")), f"ActivityRecord.{fk} must be a UUID"
    assert isinstance(data.get("activity_type"), str)
    assert isinstance(data.get("quantity"), (int, float)) and data["quantity"] > 0
    assert isinstance(data.get("unit"), str) and data["unit"]
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    _assert_enum(data, "status", RecordStatus, "ActivityRecord")
    assert isinstance(data.get("submitted_by_user_id"), str) and data["submitted_by_user_id"]
    assert data.get("reviewed_by_user_id") is None or isinstance(data["reviewed_by_user_id"], str)
    assert data.get("reject_reason") is None or isinstance(data["reject_reason"], str)
    assert data.get("factor_value_snapshot") is None or isinstance(data["factor_value_snapshot"], (int, float))
    assert data.get("tco2e") is None or isinstance(data["tco2e"], (int, float))


def assert_evidence_item(data: dict):
    _assert_common_fields(data, "EvidenceItem")
    assert is_valid_uuid(data.get("activity_record_id", ""))
    assert isinstance(data.get("file_name"), str) and data["file_name"]
    sha = data.get("sha256_hex", "")
    assert isinstance(sha, str) and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha), (
        f"EvidenceItem.sha256_hex must be 64 lowercase hex chars, got {sha!r}"
    )
    _assert_enum(data, "status", EvidenceStatus, "EvidenceItem")
    assert isinstance(data.get("uploaded_by_user_id"), str) and data["uploaded_by_user_id"]
    assert data.get("verified_by_user_id") is None or isinstance(data["verified_by_user_id"], str)
    assert is_iso8601_timestamp(data.get("retention_until", ""))


def assert_inventory_result(data: dict):
    _assert_common_fields(data, "InventoryResult")
    assert is_valid_uuid(data.get("cycle_id", ""))
    _assert_enum(data, "status", InventoryStatus, "InventoryResult")
    for field in ("scope1_tco2e", "scope2_location_tco2e", "scope2_market_tco2e",
                  "scope3_tco2e", "scope3_provisional_tco2e", "total_tco2e"):
        assert isinstance(data.get(field), (int, float)), (
            f"InventoryResult.{field} must be numeric, got {data.get(field)!r}"
        )
    assert data.get("computed_at") is None or is_iso8601_timestamp(data["computed_at"])


def assert_supplier_engagement(data: dict):
    _assert_common_fields(data, "SupplierEngagement")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert isinstance(data.get("supplier_name"), str) and data["supplier_name"]
    assert isinstance(data.get("category"), str)
    assert isinstance(data.get("spend_usd"), (int, float)) and data["spend_usd"] >= 0
    assert isinstance(data.get("contact_user_id"), str) and data["contact_user_id"]
    assert is_iso8601_timestamp(data.get("due_date", ""))
    _assert_enum(data, "status", EngagementStatus, "SupplierEngagement")
    assert isinstance(data.get("round"), int) and data["round"] >= 1
    assert data.get("supplier_tco2e") is None or isinstance(data["supplier_tco2e"], (int, float))
    assert data.get("responded_at") is None or is_iso8601_timestamp(data["responded_at"])


def assert_emission_target(data: dict):
    _assert_common_fields(data, "EmissionTarget")
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("base_year"), int)
    assert isinstance(data.get("target_year"), int)
    assert isinstance(data.get("reduction_pct"), (int, float))
    assert 0 < data["reduction_pct"] < 100
    assert data.get("scope_coverage") in ("SCOPE1_2", "SCOPE1_2_3")
    assert isinstance(data.get("base_year_total_tco2e"), (int, float))
    _assert_enum(data, "baseline_source", BaselineSource, "EmissionTarget")
    assert data.get("baseline_shift_pct") is None or isinstance(data["baseline_shift_pct"], (int, float))
    assert data.get("baseline_shift_significant") is None or isinstance(data["baseline_shift_significant"], bool)
    _assert_enum(data, "status", TargetStatus, "EmissionTarget")
    _assert_enum(data, "trajectory_status", TrajectoryStatus, "EmissionTarget")


def assert_renewable_instrument(data: dict):
    _assert_common_fields(data, "RenewableInstrument")
    assert isinstance(data.get("registry"), str) and data["registry"]
    assert isinstance(data.get("serial_number"), str) and data["serial_number"]
    assert isinstance(data.get("technology"), str)
    assert isinstance(data.get("vintage_year"), int)
    assert isinstance(data.get("quantity_mwh"), (int, float)) and data["quantity_mwh"] > 0
    _assert_enum(data, "status", InstrumentStatus, "RenewableInstrument")
    assert data.get("retired_for_cycle_id") is None or is_valid_uuid(data["retired_for_cycle_id"])
    assert data.get("retired_for_site_id") is None or is_valid_uuid(data["retired_for_site_id"])


def assert_questionnaire_response(data: dict):
    _assert_common_fields(data, "QuestionnaireResponse")
    assert is_valid_uuid(data.get("cycle_id", ""))
    assert data.get("framework") in ("CDP", "GRI", "ECOVADIS")
    assert isinstance(data.get("prepared_by_user_id"), str) and data["prepared_by_user_id"]
    assert isinstance(data.get("sections"), dict)
    assert isinstance(data.get("completeness_pct"), (int, float))
    assert isinstance(data.get("emissions_section_stale"), bool)
    _assert_enum(data, "status", QuestionnaireStatus, "QuestionnaireResponse")
    assert data.get("review_decision_by") is None or isinstance(data["review_decision_by"], str)
    assert data.get("review_notes") is None or isinstance(data["review_notes"], str)
