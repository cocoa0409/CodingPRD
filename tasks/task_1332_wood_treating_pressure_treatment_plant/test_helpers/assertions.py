"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_THREE_FRACTIONAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_iso_timestamp_ms(value: str, field: str = "timestamp"):
    """PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and is_iso8601_timestamp(value), (
        f"{field} must be an ISO 8601 UTC timestamp, got {value!r}"
    )


def assert_common_fields(data: dict, entity: str = "resource"):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert_iso_timestamp_ms(data.get("created_at", ""), f"{entity}.created_at")
    assert_iso_timestamp_ms(data.get("updated_at", ""), f"{entity}.updated_at")
    assert isinstance(data.get("version"), int), f"{entity}.version must be an int"


def assert_append_only_fields(data: dict, entity: str = "record"):
    """PRD §2.4: RetentionAssay/DripPadLog/CylinderScheduleSlot carry only id +
    created_at; updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert_iso_timestamp_ms(data.get("created_at", ""), f"{entity}.created_at")
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_plant(data: dict):
    assert_common_fields(data, "TreatmentPlant")
    assert isinstance(data["plant_name"], str) and data["plant_name"]
    assert isinstance(data["alsc_license_number"], str) and data["alsc_license_number"]
    assert isinstance(data["compliance_score"], int)
    assert 0 <= data["compliance_score"] <= 1000, "compliance_score is floored at 0 (PRD §2.5)"
    assert isinstance(data["hazardous_waste_liability_cents"], int)
    assert data["hazardous_waste_liability_cents"] >= 0
    assert data["status"] in ("LICENSED", "SUSPENDED", "REVOKED")


def assert_cylinder(data: dict):
    assert_common_fields(data, "TreatmentCylinder")
    assert isinstance(data["cylinder_code"], str) and data["cylinder_code"]
    assert isinstance(data["max_volume_mbf"], (int, float)) and data["max_volume_mbf"] > 0
    assert isinstance(data["supported_process_types"], list)
    assert data["status"] in (
        "IDLE", "LOADED", "CYCLE_RUNNING", "DRAINING", "NEEDS_CLEANING", "DECOMMISSIONED",
    )


def assert_preservative(data: dict):
    assert_common_fields(data, "PreservativeConcentrate")
    assert data["chemical_family"] in ("CCA", "ACQ", "CA", "CREOSOTE", "PENTA")
    assert isinstance(data["concentrate_assay_pct"], (int, float))
    assert isinstance(data["inventory_gallons"], (int, float))
    assert isinstance(data["min_working_assay_pct"], (int, float))
    assert data["status"] in ("IN_STOCK", "LOW_STOCK", "QUARANTINED", "DEPLETED")


def assert_customer(data: dict):
    assert_common_fields(data, "CustomerAccount")
    assert isinstance(data["customer_name"], str) and data["customer_name"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "CLOSED")


def assert_charge(data: dict):
    assert_common_fields(data, "Charge")
    assert data["ownership_type"] in ("PLANT_STOCK", "CUSTOM_TREAT")
    assert data["species_group"] in ("SPF", "SYP", "DOUGLAS_FIR", "HEM_FIR", "PONDEROSA_PINE")
    assert data["use_category"] in ("UC3B", "UC4A", "UC4B", "UC4C")
    assert isinstance(data["volume_mbf"], (int, float)) and data["volume_mbf"] > 0
    assert isinstance(data["target_retention_pcf"], (int, float))
    assert isinstance(data["provisional_retention_pcf"], (int, float))
    assert isinstance(data["final_retention_pcf"], (int, float))
    assert isinstance(data["requires_incising"], bool)
    assert isinstance(data["is_custom_treat"], bool)
    assert isinstance(data["hazard_containment_flag"], bool)
    assert data["status"] in (
        "STAGED", "IN_CYLINDER", "CYCLE_COMPLETE", "ASSAYED_PASS", "ASSAYED_FAIL",
        "RE_TREAT_PENDING", "TAGGED", "RELEASED", "REJECTED", "SCRAPPED",
    )


def assert_piece(data: dict):
    assert_common_fields(data, "ChargePiece")
    assert isinstance(data["piece_tag"], str) and data["piece_tag"]
    assert isinstance(data["incised"], bool)
    assert data["status"] in (
        "RAW", "INCISED", "TREATED", "ASSAYED_PASS", "ASSAYED_FAIL",
        "TAGGED", "RELEASED", "SCRAPPED",
    )


def assert_cycle(data: dict):
    assert_common_fields(data, "TreatmentCycle")
    assert data["process_type"] in ("FULL_CELL", "LOWRY", "RUEPING", "SAP_DISPLACEMENT")
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert data["status"] in ("SCHEDULED", "RUNNING", "DRAINING", "COMPLETE", "ABORTED")


def assert_assay(data: dict):
    assert_append_only_fields(data, "RetentionAssay")
    assert data["assay_method"] in ("XYLENE_EXTRACTION", "ASHING", "TITRATION")
    assert isinstance(data["sample_count"], int) and data["sample_count"] >= 1
    assert isinstance(data["mean_retention_pcf"], (int, float))
    assert isinstance(data["min_sample_retention_pcf"], (int, float))
    assert data["recorded_by_agency"] in ("PLANT_LAB", "THIRD_PARTY_AGENCY")
    assert data["outcome"] in ("PASS", "FAIL_MARGINAL", "FAIL_GROSS")


def assert_inspection(data: dict):
    assert_common_fields(data, "QualityInspection")
    assert data["agency_code"] in ("ALSC", "SPIB", "TPI", "WCLIB")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in (
        "SCHEDULED", "IN_PROGRESS", "FINDINGS_ISSUED", "CLOSED_PASS", "CLOSED_FAIL",
    )


def assert_drip_log(data: dict):
    assert_append_only_fields(data, "DripPadLog")
    assert isinstance(data["pad_code"], str) and data["pad_code"]
    assert isinstance(data["drip_volume_liters"], (int, float))
    assert isinstance(data["containment_breach"], bool)
    assert isinstance(data["liability_cents"], int)


def assert_warranty(data: dict):
    assert_common_fields(data, "WarrantyRegistration")
    assert data["warranty_term_years"] in (5, 25, 50)
    assert isinstance(data["registration_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "VOIDED_BY_RETREAT", "LAPSED")


def assert_slot(data: dict):
    assert_append_only_fields(data, "CylinderScheduleSlot")
    assert data["slot_kind"] in ("TREATMENT", "CLEANING", "MAINTENANCE")
    assert_iso_timestamp_ms(data["slot_start"], "slot.slot_start")
    assert_iso_timestamp_ms(data["slot_end"], "slot.slot_end")
