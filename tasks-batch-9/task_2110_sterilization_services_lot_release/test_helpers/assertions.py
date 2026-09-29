"""Entity assertions and domain invariant checkers."""

from decimal import Decimal

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ------------------------------------------------------------ helpers ----
def assert_common_fields(data: dict, entity_name: str = "resource"):
    """id is a bare UUID with no type prefix; created_at / updated_at are ISO
    8601 UTC instants; version is an integer."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_name}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"


def assert_append_only_fields(data: dict, entity_name: str = "resource"):
    """A dose audit is immutable: it carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a bare UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_name}.created_at must be an ISO 8601 timestamp"
    assert "updated_at" not in data, f"{entity_name} must not carry updated_at"
    assert "version" not in data, f"{entity_name} must not carry version"


def assert_decimal_places(value, places: int, label: str):
    """The value carries at most `places` decimal places."""
    assert value is not None, f"{label} must not be null"
    quantum = Decimal(1).scaleb(-places)
    as_decimal = Decimal(str(value))
    assert as_decimal == as_decimal.quantize(
        quantum
    ), f"{label} must be carried to {places} decimal places, got {value}"


def assert_timestamp_millis(value: str, label: str):
    """Timestamps are ISO 8601 UTC with three fractional digits."""
    assert is_iso8601_timestamp(value), f"{label} must be an ISO 8601 timestamp, got {value}"


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Compare two ISO 8601 instants to the second, tolerating the fractional
    digits the server stamps."""
    from datetime import datetime

    def _parse(raw: str) -> datetime:
        assert raw is not None, f"{label} must not be null"
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))

    got = _parse(actual)
    want = _parse(expected_iso)
    assert got == want, f"{label}: expected {expected_iso}, got {actual}"


# ---------------------------------------------------- entity checkers ----
def assert_customer(data: dict):
    assert_common_fields(data, "Customer")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["account_code"], str)
    assert isinstance(data["contracted_modalities"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["open_lot_count"], int)


def assert_product(data: dict):
    assert_common_fields(data, "Product")
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["product_code"], str)
    assert data["pallet_mass_kg"] > 0
    assert data["pallet_volume_m3"] > 0
    assert data["max_allowed_dose_kgy"] > 0
    assert data["max_cumulative_dose_kgy"] > 0
    assert data["eto_residual_limit_ppm"] >= 0
    assert data["ech_residual_limit_ppm"] >= 0
    assert isinstance(data["requires_aeration"], bool)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_emission_permit(data: dict):
    assert_common_fields(data, "EmissionPermit")
    assert isinstance(data["permit_code"], str)
    assert data["permit_year"] >= 2000
    assert data["annual_allowance_kg"] > 0
    assert data["max_concurrent_eto_cycles"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert_decimal_places(data["consumed_kg_ytd"], 3, "EmissionPermit.consumed_kg_ytd")
    assert_decimal_places(
        data["total_emission_fee_usd"], 2, "EmissionPermit.total_emission_fee_usd"
    )


def assert_chamber(data: dict):
    assert_common_fields(data, "Chamber")
    assert isinstance(data["permit_id"], str)
    assert data["modality"] in ("ETO", "GAMMA", "EBEAM")
    assert data["pallet_capacity"] >= 1
    assert data["turnaround_minutes"] >= 0
    assert 0 <= data["abatement_efficiency_pct"] <= 100
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "DECOMMISSIONED")


def assert_cycle_recipe(data: dict):
    assert_common_fields(data, "CycleRecipe")
    assert data["modality"] in ("ETO", "GAMMA", "EBEAM")
    assert data["density_max_g_per_cm3"] > data["density_min_g_per_cm3"]
    assert data["max_dose_kgy"] > data["min_dose_kgy"]
    assert data["dose_basis"] in ("ROUTINE_MEAN", "MIN_ZONE")
    assert data["status"] in ("DRAFT", "APPROVED")


def assert_qualification(data: dict):
    assert_common_fields(data, "ProductQualification")
    assert data["method"] in ("VDMAX_15", "VDMAX_25", "METHOD_1")
    assert data["status"] in (
        "PENDING",
        "QUALIFIED",
        "CONDITIONAL",
        "AUDIT_DUE",
        "SUSPENDED",
        "REVOKED",
    )
    assert isinstance(data["audit_interval_days"], int)
    assert isinstance(data["consecutive_conditional_count"], int)


def assert_dose_audit(data: dict):
    assert_append_only_fields(data, "DoseAudit")
    assert data["outcome"] in ("PASS", "CONDITIONAL_PASS", "FAIL")
    assert data["qualification_status_after"] in (
        "QUALIFIED",
        "CONDITIONAL",
        "SUSPENDED",
        "REVOKED",
    )
    assert data["samples_tested"] == 100


def assert_lot(data: dict):
    assert_common_fields(data, "Lot")
    assert data["status"] in (
        "RECEIVED",
        "STAGED",
        "IN_PROCESS",
        "PROCESSED",
        "QUARANTINE",
        "RELEASED",
        "REJECTED",
        "SCRAPPED",
        "RECALLED",
    )
    assert data["residual_status"] in (
        "NOT_APPLICABLE",
        "PENDING_AERATION",
        "AERATING",
        "RESIDUAL_PASS",
        "RESIDUAL_FAIL",
    )
    assert data["quarantine_reason"] in (
        "NONE",
        "ROUTINE",
        "DOSE_DEVIATION",
        "BI_POSITIVE",
        "RESIDUAL_FAIL",
        "ADVERSE_EVENT",
    )
    assert data["release_mode"] in ("NONE", "PARAMETRIC", "DOSIMETRIC")
    assert isinstance(data["schedulable"], bool)
    assert_pallet_conservation(data)


def assert_cycle(data: dict):
    assert_common_fields(data, "Cycle")
    assert data["status"] in (
        "PLANNED",
        "LOADING",
        "READY",
        "RUNNING",
        "COMPLETED",
        "DOSIMETRY_REVIEW",
        "DOSE_CONFORMING",
        "DOSE_DEVIATION",
        "CANCELLED",
    )
    assert data["deviation_code"] in ("NONE", "BI_POSITIVE", "UNDERDOSE", "OVERDOSE")
    assert isinstance(data["loaded_pallet_count"], int)
    assert_decimal_places(
        data["load_density_g_per_cm3"], 4, "Cycle.load_density_g_per_cm3"
    )
    assert_decimal_places(data["abated_eto_kg"], 3, "Cycle.abated_eto_kg")
    assert_decimal_places(data["emission_fee_usd"], 2, "Cycle.emission_fee_usd")


def assert_load_position(data: dict):
    assert_common_fields(data, "LoadPosition")
    assert data["zone"] in ("MIN_DOSE", "MAX_DOSE", "INTERIOR", "EDGE")
    assert data["position_index"] >= 1
    assert data["pallet_count"] >= 1
    assert isinstance(data["cycle_version_after"], int)


def assert_indicator(data: dict):
    assert_common_fields(data, "Indicator")
    assert data["indicator_type"] in ("DOSIMETER", "BIOLOGICAL")
    assert data["placement_zone"] in ("MIN_DOSE", "MAX_DOSE", "ROUTINE")
    assert data["bi_result"] in ("PENDING", "NEGATIVE", "POSITIVE")
    assert data["reading_status"] in ("UNREAD", "READ")


def assert_aeration_record(data: dict):
    assert_common_fields(data, "AerationRecord")
    assert data["status"] in ("IN_PROGRESS", "RETEST_REQUIRED", "PASSED", "EXHAUSTED")
    assert data["variant_applied"] in ("STANDARD", "EXTENDED_RETEST")
    assert isinstance(data["required_hours"], int)
    assert isinstance(data["retest_count"], int)


def assert_adverse_event(data: dict):
    assert_common_fields(data, "AdverseEvent")
    assert data["event_type"] in (
        "STERILITY_COMPLAINT",
        "RESIDUAL_EXCEEDANCE",
        "FIELD_DOSE_DEVIATION",
        "PACKAGING_BREACH",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in (
        "REPORTED",
        "RESTERILIZE_APPROVED",
        "SCRAP_APPROVED",
        "DISMISSED",
    )
    assert isinstance(data["lot_version_after"], int)


# ------------------------------------------------ conserved quantities ---
def assert_pallet_conservation(lot: dict):
    """staged_pallet_count + available_pallet_count == total_pallet_count, and
    available_pallet_count is never negative."""
    assert lot["available_pallet_count"] >= 0, "available_pallet_count must never be negative"
    assert (
        lot["staged_pallet_count"] + lot["available_pallet_count"]
        == lot["total_pallet_count"]
    ), (
        f"pallet conservation broken on lot {lot.get('lot_code')}: "
        f"{lot['staged_pallet_count']} + {lot['available_pallet_count']} "
        f"!= {lot['total_pallet_count']}"
    )


def assert_cycle_pallet_sum(cycle: dict, positions: list):
    """Cycle.loaded_pallet_count equals the sum of its positions'
    pallet_count."""
    total = sum(p["pallet_count"] for p in positions)
    assert cycle["loaded_pallet_count"] == total, (
        f"loaded_pallet_count {cycle['loaded_pallet_count']} != sum of load "
        f"positions {total}"
    )
