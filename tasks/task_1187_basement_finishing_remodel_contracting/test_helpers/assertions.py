"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AssessmentKind,
    AssessmentStatus,
    CertificateStatus,
    ChangeOrderKind,
    ChangeOrderStatus,
    DesignPackageStatus,
    InspectionStatus,
    InspectionType,
    PermitStatus,
    PriceVariant,
    ProjectStatus,
    RiskBand,
    Trade,
    WarrantyClaimStatus,
    WorkPhaseStatus,
)

_ALL_TRADES = [t.value for t in Trade]


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int starting at 1, got {data.get('version')!r}"
    )


def assert_contractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["license_no"], str) and data["license_no"]


def assert_homeowner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]


def assert_subcontractor(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["trade"] in _ALL_TRADES, f"trade must be a declared enum member, got {data.get('trade')!r}"


def assert_project(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("homeowner_id", "")), "homeowner_id must be a UUID"
    assert is_valid_uuid(data.get("contractor_id", "")), "contractor_id must be a UUID"
    assert isinstance(data["address"], str) and data["address"]
    assert isinstance(data["basement_sqft"], int)
    assert isinstance(data["base_contract_cents"], int) and data["base_contract_cents"] > 0
    assert data["status"] in [s.value for s in ProjectStatus]
    assert isinstance(data["strike_count"], int) and data["strike_count"] >= 0
    assert isinstance(data["contract_price_cents"], int)
    assert data["price_variant"] in [v.value for v in PriceVariant]


def assert_moisture_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["assessment_kind"] in [k.value for k in AssessmentKind]
    assert isinstance(data["slab_moisture_lbs"], (int, float))
    assert isinstance(data["interior_rh_pct"], (int, float))
    assert isinstance(data["efflorescence_observed"], bool)
    assert isinstance(data["grading_deficit"], bool)
    assert isinstance(data["egress_windows_existing"], int)
    assert isinstance(data["ceiling_height_in"], (int, float))
    assert data["status"] in [s.value for s in AssessmentStatus]
    if data["status"] in (AssessmentStatus.ACCEPTED.value, AssessmentStatus.REJECTED.value):
        assert isinstance(data["moisture_risk_score"], int), "score persisted after submit"
        assert data["risk_band"] in [b.value for b in RiskBand]


def assert_design_package(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["layout_notes"], str)
    assert isinstance(data["mechanical_relocations"], list)
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert data["status"] in [s.value for s in DesignPackageStatus]


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["bedroom_count"], int) and data["bedroom_count"] >= 0
    assert isinstance(data["windows"], list)
    assert isinstance(data["finished_area_sqft"], int)
    assert isinstance(data["low_area_sqft"], int)
    assert isinstance(data["prohibited_area_sqft"], int)
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    assert data["status"] in [s.value for s in PermitStatus]


def assert_allowance_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["budgeted_cents"], int) and data["budgeted_cents"] >= 0
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["drawn_cents"], int)
    assert isinstance(data["selected"], bool)
    assert isinstance(data["actual_cents"], int)
    assert isinstance(data["remaining_cents"], int)


def assert_change_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["scope_description"], str)
    assert data["kind"] in [k.value for k in ChangeOrderKind]
    assert isinstance(data["scope_items"], list)
    assert isinstance(data["allowance_draws"], list)
    assert isinstance(data["price_delta_cents"], int)
    assert data["status"] in [s.value for s in ChangeOrderStatus]


def assert_work_phase(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("subcontractor_id", "")), "subcontractor_id must be a UUID"
    assert data["trade"] in _ALL_TRADES
    assert isinstance(data["zone"], str) and data["zone"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["crew_count"], int)
    assert isinstance(data["predecessor_ids"], list)
    assert isinstance(data["requires_rough_in"], bool)
    assert data["status"] in [s.value for s in WorkPhaseStatus]


def assert_daily_site_log(data: dict):
    """DailySiteLog is the sole exception to common fields (PRD §2.4):
    it carries only id and created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a prefix-less UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DailySiteLog must not carry updated_at"
    assert "version" not in data, "DailySiteLog must not carry version"
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("subcontractor_id", "")), "subcontractor_id must be a UUID"
    assert isinstance(data["work_date"], str)
    assert isinstance(data["containment_intact"], bool)
    assert isinstance(data["hepa_run_hours"], (int, float))
    assert isinstance(data["noise_db_max"], (int, float))
    assert isinstance(data["cleanup_completed"], bool)
    assert isinstance(data["violation"], bool)
    assert isinstance(data["strike_applied"], bool)


def assert_inspection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert data["type"] in [t.value for t in InspectionType]
    assert data["status"] in [s.value for s in InspectionStatus]


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert isinstance(data["warranty_start"], str)
    assert isinstance(data["warranty_end"], str)
    assert data["status"] in [s.value for s in CertificateStatus]


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("project_id", "")), "project_id must be a UUID"
    assert is_valid_uuid(data.get("certificate_id", "")), "certificate_id must be a UUID"
    assert isinstance(data["description"], str)
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] > 0
    assert isinstance(data["fresh_slab_moisture_lbs"], (int, float))
    assert isinstance(data["fresh_interior_rh_pct"], (int, float))
    assert data["status"] in [s.value for s in WarrantyClaimStatus]


def assert_allowance_conservation(line: dict):
    """PRD §3.5 invariant: remaining_cents is always the budget minus the
    reserved, drawn, and actual amounts."""
    expected = (
        line["budgeted_cents"]
        - line["reserved_cents"]
        - line["drawn_cents"]
        - line["actual_cents"]
    )
    assert line["remaining_cents"] == expected, (
        f"remaining_cents {line['remaining_cents']} != budgeted {line['budgeted_cents']} "
        f"- reserved {line['reserved_cents']} - drawn {line['drawn_cents']} "
        f"- actual {line['actual_cents']}"
    )
