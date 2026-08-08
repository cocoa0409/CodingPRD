"""Entity assertions and register-wide invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdvisoryStatus,
    CertificateGrade,
    ComplianceStatus,
    ConstructionPermitStatus,
    ContractorEffectiveStatus,
    ContractorStatus,
    FieldCondition,
    InspectionMode,
    InspectionStatus,
    InspectionType,
    LicenseClass,
    OperatingPermitStatus,
    RepairOrderStatus,
    RepairSeverity,
    RiskTier,
    SetbackStatus,
    SiteEvaluationStatus,
    SoilGroup,
    SystemDesignStatus,
    SystemType,
    TransferInspectionStatus,
    WaterSampleResult,
    WaterSourceType,
    WellType,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_housekeeping(data: dict) -> None:
    """Records that carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_evidence_housekeeping(data: dict) -> None:
    """Immutable evidence records carry id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "evidence records carry no updated_at"
    assert "version" not in data, "evidence records carry no version"


def assert_rendered_timestamp(value: str, field_name: str = "timestamp") -> None:
    """Every datetime is rendered with exactly three fractional digits and a Z."""
    assert isinstance(value, str), f"{field_name} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{field_name} must be ISO 8601 UTC: {value!r}"
    assert value.endswith("Z"), f"{field_name} must end with Z: {value!r}"
    assert (
        len(value) == 24 and value[19] == "."
    ), f"{field_name} must carry exactly three fractional digits: {value!r}"


def assert_parcel(data: dict) -> None:
    assert_housekeeping(data)
    assert isinstance(data["apn"], str) and data["apn"], "apn must be non-empty"
    assert isinstance(data["county_code"], str) and data["county_code"]
    assert isinstance(data["site_address"], str) and data["site_address"]
    assert isinstance(data["lot_size_sqft"], int) and data["lot_size_sqft"] >= 1
    assert data["water_source"] in _values(WaterSourceType)
    assert isinstance(data["owner_user_id"], str) and data["owner_user_id"]
    for field in (
        "max_design_flow_gpd",
        "permitted_design_flow_gpd",
        "fees_assessed_cents",
        "fees_paid_cents",
        "fees_credited_cents",
        "fee_balance_cents",
        "open_repair_order_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["water_quality_flag"], bool)
    assert isinstance(data["transfer_hold"], bool)
    assert data["risk_tier"] in _values(RiskTier)
    assert_parcel_ledger_invariants(data)


def assert_parcel_ledger_invariants(data: dict) -> None:
    """The outstanding balance is the assessed total less paid less credited."""
    assert data["fee_balance_cents"] == (
        data["fees_assessed_cents"] - data["fees_paid_cents"] - data["fees_credited_cents"]
    ), (
        "fee_balance_cents must equal fees_assessed_cents - fees_paid_cents - "
        f"fees_credited_cents; got {data['fee_balance_cents']} against "
        f"{data['fees_assessed_cents']}/{data['fees_paid_cents']}/{data['fees_credited_cents']}"
    )
    assert data["fees_assessed_cents"] >= 0
    assert data["fees_paid_cents"] >= 0
    assert data["fees_credited_cents"] >= 0
    assert data["permitted_design_flow_gpd"] >= 0
    assert data["open_repair_order_count"] >= 0


def assert_well(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["parcel_id"])
    assert data["well_type"] in _values(WellType)
    assert isinstance(data["location_x_ft"], (int, float))
    assert isinstance(data["location_y_ft"], (int, float))
    assert isinstance(data["depth_ft"], int) and data["depth_ft"] >= 1
    assert data["advisory_status"] in _values(AdvisoryStatus)
    if data.get("last_sample_collected_at") is not None:
        assert_rendered_timestamp(
            data["last_sample_collected_at"], "last_sample_collected_at"
        )


def assert_water_sample(data: dict) -> None:
    assert_evidence_housekeeping(data)
    assert is_valid_uuid(data["well_id"])
    assert_rendered_timestamp(data["collected_at"], "collected_at")
    assert isinstance(data["nitrate_mg_l"], (int, float)) and data["nitrate_mg_l"] >= 0
    assert isinstance(data["coliform_present"], bool)
    assert data["result"] in _values(WaterSampleResult)
    assert isinstance(data["exceedance_reasons"], list)
    assert data["exceedance_reasons"] == sorted(
        data["exceedance_reasons"]
    ), "exceedance_reasons must be sorted"
    if data["result"] == WaterSampleResult.PASS.value:
        assert data["exceedance_reasons"] == [], "a PASS carries no reason codes"


def assert_site_evaluation(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["parcel_id"])
    assert isinstance(data["evaluator_user_id"], str) and data["evaluator_user_id"]
    assert_rendered_timestamp(data["evaluated_on"], "evaluated_on")
    assert data["soil_group"] in _values(SoilGroup)
    assert (
        isinstance(data["depth_to_limiting_layer_in"], int)
        and data["depth_to_limiting_layer_in"] >= 0
    )
    assert isinstance(data["perc_holes"], list)
    assert data["status"] in _values(SiteEvaluationStatus)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert_rendered_timestamp(data["valid_until"], "valid_until")


def assert_perc_hole(hole: dict) -> None:
    """Each stored reading keeps its four supplied values plus two derived ones."""
    assert isinstance(hole["hole_number"], int)
    assert isinstance(hole["drop_inches"], (int, float))
    assert isinstance(hole["elapsed_minutes"], (int, float))
    assert isinstance(hole["presoak_ok"], bool)
    assert isinstance(hole["valid"], bool)
    expected_valid = (
        hole["presoak_ok"] and hole["drop_inches"] > 0 and hole["elapsed_minutes"] > 0
    )
    assert hole["valid"] == expected_valid, (
        "a reading is valid only when presoak_ok is true, drop_inches is greater than "
        f"zero and elapsed_minutes is greater than zero; got {hole}"
    )
    if not hole["valid"]:
        assert hole.get("rate_min_per_in") is None, "an invalid reading carries no rate"


def assert_system_design(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["site_evaluation_id"])
    assert isinstance(data["designer_user_id"], str) and data["designer_user_id"]
    assert data["system_type"] in _values(SystemType)
    assert isinstance(data["bedrooms"], int) and 1 <= data["bedrooms"] <= 8
    assert isinstance(data["tank_capacity_gal"], int) and data["tank_capacity_gal"] >= 750
    assert isinstance(data["design_flow_gpd"], int)
    assert data["setback_status"] in _values(SetbackStatus)
    assert data["status"] in _values(SystemDesignStatus)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_drainfield_within_clamp(data: dict) -> None:
    """The required area is never below 150 square feet and never above 4000."""
    area = data["required_drainfield_sqft"]
    assert isinstance(area, int), "required_drainfield_sqft is a whole number"
    assert 150 <= area <= 4000, f"required_drainfield_sqft out of clamp range: {area}"


def assert_contractor(data: dict) -> None:
    assert_housekeeping(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_class"] in _values(LicenseClass)
    assert_rendered_timestamp(data["license_expires_on"], "license_expires_on")
    assert isinstance(data["bond_amount_cents"], int) and data["bond_amount_cents"] >= 0
    assert data["status"] in _values(ContractorStatus)
    assert data["effective_status"] in _values(ContractorEffectiveStatus)


def assert_construction_permit(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["system_design_id"])
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["contractor_id"])
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert_rendered_timestamp(data["valid_from"], "valid_from")
    assert_rendered_timestamp(data["valid_until"], "valid_until")
    assert isinstance(data["design_flow_gpd"], int)
    assert isinstance(data["fee_cents"], int) and data["fee_cents"] >= 0
    assert data["status"] in _values(ConstructionPermitStatus)
    if data.get("cover_inspection_passed_at") is not None:
        assert_rendered_timestamp(
            data["cover_inspection_passed_at"], "cover_inspection_passed_at"
        )


def assert_inspection(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["construction_permit_id"])
    assert is_valid_uuid(data["contractor_id"])
    assert data["inspection_type"] in _values(InspectionType)
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert_rendered_timestamp(data["scheduled_start"], "scheduled_start")
    assert_rendered_timestamp(data["scheduled_end"], "scheduled_end")
    assert data["scheduled_end"] > data["scheduled_start"]
    assert data["status"] in _values(InspectionStatus)
    assert isinstance(data["deficiency_codes"], list)
    assert isinstance(data["reinspection_round"], int)


def assert_operating_permit(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["construction_permit_id"])
    assert isinstance(data["household_size"], int) and 1 <= data["household_size"] <= 12
    assert isinstance(data["tank_capacity_gal"], int)
    assert_rendered_timestamp(data["issued_on"], "issued_on")
    assert_rendered_timestamp(data["expires_on"], "expires_on")
    assert_rendered_timestamp(data["next_pumping_due_on"], "next_pumping_due_on")
    assert isinstance(data["pumping_interval_months"], int)
    assert isinstance(data["monitoring_required"], bool)
    assert data["status"] in _values(OperatingPermitStatus)
    assert data["compliance_status"] in _values(ComplianceStatus)
    if data.get("last_pumped_on") is not None:
        assert_rendered_timestamp(data["last_pumped_on"], "last_pumped_on")


def assert_pumping_record(data: dict) -> None:
    assert_evidence_housekeeping(data)
    assert is_valid_uuid(data["operating_permit_id"])
    assert is_valid_uuid(data["contractor_id"])
    assert_rendered_timestamp(data["pumped_on"], "pumped_on")
    assert isinstance(data["gallons_removed"], int) and data["gallons_removed"] >= 1
    assert isinstance(data["sludge_depth_in"], (int, float)) and data["sludge_depth_in"] >= 0
    assert isinstance(data["scum_depth_in"], (int, float)) and data["scum_depth_in"] >= 0


def assert_repair_order(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["operating_permit_id"])
    assert data["failure_type"] in [
        "SURFACING_EFFLUENT",
        "BACKUP",
        "STRUCTURAL",
        "GROUNDWATER_CONTAMINATION",
    ]
    assert_rendered_timestamp(data["reported_on"], "reported_on")
    assert data["status"] in _values(RepairOrderStatus)
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= 2
    if data.get("severity") is not None:
        assert data["severity"] in _values(RepairSeverity)
    if data.get("compliance_deadline") is not None:
        assert_rendered_timestamp(data["compliance_deadline"], "compliance_deadline")


def assert_transfer_inspection(data: dict) -> None:
    assert_housekeeping(data)
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["operating_permit_id"])
    assert_rendered_timestamp(data["requested_on"], "requested_on")
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert isinstance(data["seller_name"], str) and data["seller_name"]
    assert data["inspection_mode"] in _values(InspectionMode)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["expedite_fee_cents"], int)
    assert isinstance(data["total_due_cents"], int)
    assert data["total_due_cents"] == data["subtotal_cents"] + data["expedite_fee_cents"], (
        "total_due_cents must be the subtotal plus the expedite fee; got "
        f"{data['total_due_cents']} against {data['subtotal_cents']} + "
        f"{data['expedite_fee_cents']}"
    )
    assert data["status"] in _values(TransferInspectionStatus)
    if data.get("certificate_grade") is not None:
        assert data["certificate_grade"] in _values(CertificateGrade)
    if data.get("certified_at") is not None:
        assert_rendered_timestamp(data["certified_at"], "certified_at")
    if data.get("certificate_valid_until") is not None:
        assert_rendered_timestamp(
            data["certificate_valid_until"], "certificate_valid_until"
        )


def assert_field_condition(value) -> None:
    assert value in _values(FieldCondition), f"unexpected field condition {value!r}"


def assert_compliance_dossier(data: dict) -> None:
    """The dossier reports eleven fields, computed on read."""
    for field in (
        "parcel_id",
        "risk_tier",
        "transfer_hold",
        "fee_balance_cents",
        "permitted_design_flow_gpd",
        "max_design_flow_gpd",
        "open_repair_order_count",
        "water_quality_flag",
        "well_count",
        "active_operating_permit_count",
        "latest_certificate_grade",
    ):
        assert field in data, f"compliance dossier is missing {field}"
    assert data["risk_tier"] in _values(RiskTier)
    assert isinstance(data["transfer_hold"], bool)
    assert isinstance(data["water_quality_flag"], bool)
    assert isinstance(data["well_count"], int)
    assert isinstance(data["active_operating_permit_count"], int)


def assert_compliance_summary(data: dict) -> None:
    """The department-wide roll-up reports eight integer figures."""
    for field in (
        "parcel_count",
        "active_operating_permit_count",
        "delinquent_permit_count",
        "due_soon_permit_count",
        "open_repair_order_count",
        "high_risk_parcel_count",
        "total_fee_balance_cents",
        "advisory_well_count",
    ):
        assert field in data, f"compliance summary is missing {field}"
        assert isinstance(data[field], int), f"{field} must be an integer"
