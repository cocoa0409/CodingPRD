"""Entity assertions for the Carbon Accounting API.

Uses the framework's generic helpers (is_valid_uuid, is_iso8601_timestamp)
under the hood. Each asserter accepts the dict shape returned by the
respective endpoint and verifies the PRD-required fields and value
constraints.

PRD §2.4: most entities carry id + created_at + updated_at + version;
BoundaryChange and AuditLog are append-only (id + created_at only).
"""
from __future__ import annotations
from typing import Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common envelope helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Every resource has an id that is a server-minted UUID
    ... Timestamps created_at and updated_at are ISO 8601 UTC strings
    with three fractional digits. The version field is an integer
    starting at 1 on creation, and increments by exactly 1 on every
    server-side mutation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'BoundaryChange and AuditLog carry only id and
    created_at — neither has updated_at nor version, because both are
    append-only event records that are never edited after they are
    written.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Organization (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_organization(data: dict) -> None:
    _assert_common_mutable(data, "Organization")
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert data.get("consolidation_approach") in {
        "EQUITY_SHARE", "FINANCIAL_CONTROL", "OPERATIONAL_CONTROL",
    }
    assert isinstance(data.get("base_year"), int)
    assert 1990 <= data["base_year"] <= 2100
    assert isinstance(data.get("functional_currency"), str)
    assert len(data["functional_currency"]) == 3
    assert data["functional_currency"].isupper()
    assert isinstance(data.get("materiality_threshold_pct"), (int, float))
    assert 0.0 <= float(data["materiality_threshold_pct"]) <= 5.0
    assert data.get("status") in {"ACTIVE", "ARCHIVED"}


# ---------------------------------------------------------------------------
# Facility (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_facility(data: dict) -> None:
    _assert_common_mutable(data, "Facility")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("country_code"), str)
    assert len(data["country_code"]) == 2
    assert data["country_code"].isupper()
    assert isinstance(data.get("ownership_share_pct"), (int, float))
    assert 0.0 <= float(data["ownership_share_pct"]) <= 100.0
    assert isinstance(data.get("financial_control"), bool)
    assert isinstance(data.get("operational_control"), bool)
    # PRD §3.1: 'included_in_boundary field is derived.'
    assert isinstance(data.get("included_in_boundary"), bool), (
        "Facility.included_in_boundary must be a boolean (PRD §3.1)"
    )
    assert data.get("status") in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# BoundaryChange (PRD §3.1, append-only)
# ---------------------------------------------------------------------------
def assert_boundary_change(data: dict) -> None:
    _assert_common_appendonly(data, "BoundaryChange")
    assert data.get("change_type") in {
        "ADD_FACILITY", "REMOVE_FACILITY",
        "APPROACH_SWITCH", "OWNERSHIP_ADJUSTMENT",
    }
    # facility_id must be null exactly when change_type == APPROACH_SWITCH
    if data["change_type"] == "APPROACH_SWITCH":
        assert data.get("facility_id") is None, (
            "BoundaryChange.facility_id must be null on APPROACH_SWITCH "
            "(PRD §3.1)"
        )
    else:
        assert data.get("facility_id") is not None
    assert is_iso8601_timestamp(data.get("effective_date", ""))
    assert isinstance(data.get("rationale"), str)
    assert 5 <= len(data["rationale"]) <= 1000


# ---------------------------------------------------------------------------
# ReportingPeriod (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_reporting_period(data: dict) -> None:
    _assert_common_mutable(data, "ReportingPeriod")
    assert isinstance(data.get("label"), str)
    assert 1 <= len(data["label"]) <= 50
    assert is_iso8601_timestamp(data.get("start_date", ""))
    assert is_iso8601_timestamp(data.get("end_date", ""))
    assert isinstance(data.get("revenue"), (int, float))
    assert float(data["revenue"]) >= 0
    assert isinstance(data.get("headcount"), int)
    assert data["headcount"] >= 0
    assert isinstance(data.get("unit_output"), (int, float))
    assert float(data["unit_output"]) >= 0
    assert data.get("status") in {"OPEN", "CLOSED", "CANCELLED"}


# ---------------------------------------------------------------------------
# EmissionSource (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_emission_source(data: dict) -> None:
    _assert_common_mutable(data, "EmissionSource")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data.get("code"), str)
    assert 1 <= len(data["code"]) <= 50
    assert data.get("category") in {
        "STATIONARY_COMBUSTION", "MOBILE_COMBUSTION", "PROCESS",
        "FUGITIVE", "PURCHASED_ENERGY", "VALUE_CHAIN",
    }
    # PRD §3.3: 'scope is derived, not entered.'
    assert data.get("scope") in {"SCOPE_1", "SCOPE_2", "SCOPE_3"}
    assert data.get("gas_type") in {
        "CO2", "CH4", "N2O", "HFC", "PFC", "SF6", "NF3",
    }
    assert isinstance(data.get("factor_code"), str)
    assert 1 <= len(data["factor_code"]) <= 50
    assert data.get("status") in {"ACTIVE", "RETIRED"}
    # scope3_category rule (PRD §3.3)
    if data["category"] == "VALUE_CHAIN":
        assert data.get("scope3_category") is not None, (
            "scope3_category must be set for VALUE_CHAIN sources (PRD §3.3)"
        )
        assert 1 <= int(data["scope3_category"]) <= 15
    else:
        assert data.get("scope3_category") is None, (
            "scope3_category must be null for non-VALUE_CHAIN sources "
            "(PRD §3.3)"
        )


# ---------------------------------------------------------------------------
# EmissionFactor (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_emission_factor(data: dict) -> None:
    _assert_common_mutable(data, "EmissionFactor")
    assert isinstance(data.get("code"), str)
    assert 1 <= len(data["code"]) <= 50
    assert isinstance(data.get("version"), int)
    assert data["version"] >= 1
    assert data.get("library") in {
        "IPCC_DEFAULT", "NATIONAL_PUBLISHED",
        "SUPPLIER_SPECIFIC", "MEASURED",
    }
    assert data.get("gas_type") in {
        "CO2", "CH4", "N2O", "HFC", "PFC", "SF6", "NF3",
    }
    if data.get("scope2_method") is not None:
        assert data["scope2_method"] in {"LOCATION_BASED", "MARKET_BASED"}
    assert isinstance(data.get("kg_per_unit"), (int, float))
    assert float(data["kg_per_unit"]) >= 0
    assert data.get("uncertainty_rating") in {"LOW", "MEDIUM", "HIGH"}
    assert is_iso8601_timestamp(data.get("effective_from", ""))
    assert data.get("status") in {"DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"}
    assert isinstance(data.get("traceability_url"), str)
    assert 1 <= len(data["traceability_url"]) <= 500


# ---------------------------------------------------------------------------
# ActivityData (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_activity_data(data: dict) -> None:
    _assert_common_mutable(data, "ActivityData")
    assert is_valid_uuid(data.get("emission_source_id", ""))
    assert data.get("data_source") in {
        "METER_READING", "INVOICE", "SUPPLIER_DATA", "ESTIMATION",
    }
    assert isinstance(data.get("quantity"), (int, float))
    assert float(data["quantity"]) >= 0
    assert isinstance(data.get("unit"), str)
    assert 1 <= len(data["unit"]) <= 20
    assert is_iso8601_timestamp(data.get("activity_start", ""))
    assert is_iso8601_timestamp(data.get("activity_end", ""))
    assert isinstance(data.get("data_quality_score"), (int, float))
    assert 0.0 <= float(data["data_quality_score"]) <= 1.0
    assert data.get("status") in {"RECORDED", "ARCHIVED"}
    # PRD §3.5: estimation_basis is non-null iff data_source==ESTIMATION
    if data["data_source"] == "ESTIMATION":
        assert data.get("estimation_basis") is not None
    else:
        assert data.get("estimation_basis") is None, (
            "estimation_basis must be null for non-ESTIMATION data sources "
            "(PRD §3.5)"
        )


# ---------------------------------------------------------------------------
# EmissionRecord (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_emission_record(data: dict) -> None:
    _assert_common_mutable(data, "EmissionRecord")
    assert is_valid_uuid(data.get("activity_data_id", ""))
    assert is_valid_uuid(data.get("emission_factor_id", ""))
    assert data.get("gas_type") in {
        "CO2", "CH4", "N2O", "HFC", "PFC", "SF6", "NF3",
    }
    assert isinstance(data.get("gwp_factor"), (int, float))
    assert isinstance(data.get("kg_co2e"), (int, float))
    assert float(data["kg_co2e"]) >= 0
    assert data.get("status") in {"FRESH", "STALE", "ARCHIVED"}
    if data.get("scope2_method") is not None:
        assert data["scope2_method"] in {"LOCATION_BASED", "MARKET_BASED"}


# ---------------------------------------------------------------------------
# ReductionProject (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_reduction_project(data: dict) -> None:
    _assert_common_mutable(data, "ReductionProject")
    assert isinstance(data.get("name"), str)
    assert 1 <= len(data["name"]) <= 200
    assert data.get("project_type") in {"INTERNAL_REDUCTION", "EXTERNAL_OFFSET"}
    assert isinstance(data.get("reduction_kg_co2e"), (int, float))
    assert float(data["reduction_kg_co2e"]) >= 0
    assert is_valid_uuid(data.get("reporting_period_id", ""))
    assert data.get("status") in {"PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"}
    # PRD §3.6: facility_id required iff project_type==INTERNAL_REDUCTION
    if data["project_type"] == "INTERNAL_REDUCTION":
        assert data.get("facility_id") is not None
    else:
        assert data.get("facility_id") is None, (
            "facility_id must be null for EXTERNAL_OFFSET projects "
            "(PRD §3.6)"
        )


# ---------------------------------------------------------------------------
# CarbonCredit (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_carbon_credit(data: dict) -> None:
    _assert_common_mutable(data, "CarbonCredit")
    assert data.get("registry") in {"VCS", "GOLD_STANDARD", "CCER"}
    assert isinstance(data.get("serial_number"), str)
    assert 1 <= len(data["serial_number"]) <= 100
    assert isinstance(data.get("vintage_year"), int)
    assert data["vintage_year"] >= 1990
    assert isinstance(data.get("quantity_kg_co2e"), (int, float))
    assert float(data["quantity_kg_co2e"]) > 0
    assert is_valid_uuid(data.get("linked_reduction_project_id", ""))
    assert is_valid_uuid(data.get("reporting_period_id", ""))
    assert data.get("status") in {"PURCHASED", "RETIRED", "TRANSFERRED"}
    # PRD §3.6: retired_at set on RETIRED, null while PURCHASED
    if data["status"] == "RETIRED":
        assert is_iso8601_timestamp(data.get("retired_at") or "")
    elif data["status"] == "PURCHASED":
        assert data.get("retired_at") is None


# ---------------------------------------------------------------------------
# Report (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_report(data: dict) -> None:
    _assert_common_mutable(data, "Report")
    assert is_valid_uuid(data.get("reporting_period_id", ""))
    assert data.get("standard") in {
        "GHG_PROTOCOL", "ISO_14064", "CDP", "TCFD", "LOCAL_MANDATORY",
    }
    assert data.get("status") in {
        "DRAFT", "UNDER_REVIEW", "REVISIONS_REQUIRED",
        "VERIFIED", "PUBLISHED", "RECOMPUTE_REQUIRED",
    }


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.9, append-only)
# ---------------------------------------------------------------------------
def assert_audit_log(data: dict) -> None:
    _assert_common_appendonly(data, "AuditLog")
    assert isinstance(data.get("actor_user_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert data.get("event_type") in {
        "ACTIVITY_ENTRY", "ACTIVITY_ARCHIVE", "FACTOR_APPROVE",
        "FACTOR_SUPERSEDE", "REPORT_COMPILE", "REPORT_VERIFY",
        "REPORT_PUBLISH", "BOUNDARY_CHANGE", "CREDIT_RETIRE",
        "EXTERNAL_SYNC",
    }
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)


# ---------------------------------------------------------------------------
# Precision invariants
# ---------------------------------------------------------------------------
def assert_emissions_precision(value: float) -> None:
    """PRD §2.6: 'Per-record emission output kg_co2e is rounded half up to
    four decimal places. The pinned report totals ... are also rounded
    half up to four decimal places.'"""
    assert isinstance(value, (int, float))
    rounded = round(float(value) * 10000) / 10000
    assert abs(float(value) - rounded) < 1e-9, (
        f"emissions value must carry at most four decimal places; got {value}"
    )


def assert_completeness_precision(value: float) -> None:
    """PRD §2.6: 'The materiality and completeness numbers
    materiality_threshold_pct and completeness_pct are rounded half up
    to two decimal places.'"""
    assert isinstance(value, (int, float))
    rounded = round(float(value) * 100) / 100
    assert abs(float(value) - rounded) < 1e-9, (
        f"completeness value must carry at most two decimal places; got {value}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_audit_event(entries: list, event_type: str,
                     target_id: Optional[str] = None) -> Optional[dict]:
    """Return the latest AuditLog entry whose event_type matches (and
    optional target_id matches), or None."""
    for entry in reversed(entries):
        if entry.get("event_type") != event_type:
            continue
        if target_id is not None and entry.get("target_id") != target_id:
            continue
        return entry
    return None


__all__ = [
    "assert_organization",
    "assert_facility",
    "assert_boundary_change",
    "assert_reporting_period",
    "assert_emission_source",
    "assert_emission_factor",
    "assert_activity_data",
    "assert_emission_record",
    "assert_reduction_project",
    "assert_carbon_credit",
    "assert_report",
    "assert_audit_log",
    "assert_emissions_precision",
    "assert_completeness_precision",
    "find_audit_event",
]
