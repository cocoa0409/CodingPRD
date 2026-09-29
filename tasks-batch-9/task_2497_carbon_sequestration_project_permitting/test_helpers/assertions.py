"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

_PROJECT_STATUSES = [
    "DRAFT",
    "SITE_CHARACTERIZATION",
    "PERMITTING",
    "INJECTION_AUTHORIZED",
    "INJECTION_ACTIVE",
    "PISC",
    "CLOSED",
]
_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
_UNITIZATION_STATUSES = ["NOT_FILED", "FILED", "GRANTED", "DENIED"]
_CLOSURE_STATUSES = ["NOT_REQUESTED", "CERTIFIED"]
_COVERAGE_STATUSES = ["UNFUNDED", "FUNDED", "UNDERFUNDED"]
_MODEL_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "ACCEPTED",
    "REJECTED",
    "SUPERSEDED",
]
_PLUME_STATUSES = ["NOT_RUN", "SIMULATED", "AOR_FINALIZED"]
_SEAL_CLASSIFICATIONS = ["PASS", "CONDITIONAL", "FAIL"]
_CA_STATUSES = [
    "OUT_OF_AOR",
    "IDENTIFIED",
    "CA_REQUIRED",
    "CA_SCHEDULED",
    "CA_COMPLETE",
    "CA_WAIVED",
]
_LEASE_STATUSES = [
    "UNLEASED",
    "OFFER_SENT",
    "COUNTERED",
    "EXECUTED",
    "REJECTED",
    "UNITIZED",
    "TERMINATED",
]
_PERMIT_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "TECHNICAL_REVIEW",
    "REVISION_REQUESTED",
    "APPROVED",
    "DENIED",
    "ACTIVE",
    "SUSPENDED",
]
_CONSTRUCTION_STATUSES = [
    "NOT_STARTED",
    "DRILLING",
    "CASING_SET",
    "CEMENT_LOGGED",
    "MIT_PENDING",
    "COMPLETED",
]
_PLAN_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "REVIEW_COMPLETE",
    "REVISION_REQUESTED",
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "REJECTED",
]
_METHOD_STATUSES = ["ACTIVE", "RETIRED"]
_INSTRUMENT_STATUSES = ["POSTED", "ALLOCATED", "DRAWN", "RELEASED"]
_PERIOD_STATUSES = ["ACCEPTED", "VOIDED"]
_CLAIM_STATUSES = ["DRAFT", "SUBMITTED", "ALLOWED", "DISALLOWED"]
_ORDER_STATUSES = ["OPEN", "RESOLVED"]


def _assert_common_fields(data: dict, entity: str) -> None:
    """Assert id, created_at, updated_at and version, which most entities carry."""
    assert is_valid_uuid(data.get("id", "")), f"{entity} id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity} created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity} updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity} version must be an integer"
    assert data["version"] >= 1, f"{entity} version starts at 1"


def assert_storage_project(data: dict) -> None:
    _assert_common_fields(data, "storage project")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["operator_name"], str) and data["operator_name"]
    assert isinstance(data["basin_code"], str) and data["basin_code"]
    assert data["status"] in _PROJECT_STATUSES
    assert data["operational_posture"] in _POSTURES
    assert data["unitization_status"] in _UNITIZATION_STATUSES
    assert data["closure_status"] in _CLOSURE_STATUSES
    assert data["assurance_coverage_status"] in _COVERAGE_STATUSES
    assert data["total_project_acreage"] > 0
    assert data["requested_annual_injection_rate_tpy"] > 0
    assert data["annual_monitoring_cost_usd"] >= 0
    assert 0 < data["required_consent_pct"] <= 100
    assert data["ca_rig_slots"] >= 1
    assert isinstance(data["non_endangerment_demonstrated"], bool)
    assert isinstance(data["open_remediation_count"], int)
    assert_storage_project_invariants(data)


def assert_storage_project_invariants(data: dict) -> None:
    """Project-level invariants that must hold after any operation."""
    assert data["secured_acreage"] >= 0
    assert data["outstanding_acreage"] >= 0
    assert data["pore_space_consent_pct"] >= 0
    assert data["pore_space_bonus_total_usd"] >= 0
    assert 0 <= data["corrective_action_completion_pct"] <= 100
    assert data["cumulative_stored_tonnes"] >= 0
    assert data["pending_credit_usd"] >= 0
    assert data["required_financial_assurance_usd"] >= 0
    assert data["allocated_assurance_usd"] >= 0
    assert data["pisc_duration_years"] >= 0
    assert data["pisc_elapsed_years"] >= 0
    assert data["open_remediation_count"] >= 0
    assert_cost_precision(data["required_financial_assurance_usd"])
    assert_cost_precision(data["allocated_assurance_usd"])
    assert_cost_precision(data["pore_space_bonus_total_usd"])


def assert_geologic_model(data: dict) -> None:
    _assert_common_fields(data, "geologic model")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["model_label"], str) and data["model_label"]
    assert data["status"] in _MODEL_STATUSES
    assert data["plume_status"] in _PLUME_STATUSES
    assert data["seal_classification"] in _SEAL_CLASSIFICATIONS
    assert data["assessment_variant"] in ["DETERMINISTIC", "PROBABILISTIC_P10"]
    assert data["fracture_pressure_psi"] > data["reservoir_pressure_psi"]
    assert 0 < data["porosity_fraction"] < 1
    assert data["revision_round_count"] >= 0
    assert data["seal_integrity_index"] >= 0
    assert data["seal_integrity_index_p10"] >= 0
    assert data["max_injection_rate_tpy"] >= 0
    assert data["effective_injection_rate_tpy"] >= 0
    assert data["plume_radius_km"] >= 0
    assert data["pressure_front_radius_km"] >= 0
    assert data["aor_radius_km"] >= 0


def assert_legacy_wellbore(data: dict) -> None:
    _assert_common_fields(data, "legacy wellbore")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["api_number"], str) and data["api_number"]
    assert data["distance_from_injector_km"] >= 0
    assert data["total_depth_m"] > 0
    assert isinstance(data["penetrates_seal"], bool)
    assert isinstance(data["plug_record_available"], bool)
    assert data["plug_condition"] in [
        "CEMENTED",
        "PARTIALLY_PLUGGED",
        "OPEN_HOLE",
        "UNKNOWN",
    ]
    assert data["corrective_action_status"] in _CA_STATUSES
    assert data["risk_score"] >= 0
    assert data["ca_cost_estimate_usd"] >= 0
    assert_cost_precision(data["ca_cost_estimate_usd"])
    assert_cost_precision(data["risk_score"])


def assert_pore_space_tract(data: dict) -> None:
    _assert_common_fields(data, "pore space tract")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["tract_label"], str) and data["tract_label"]
    assert data["acreage"] > 0
    assert 0 < data["ownership_pct"] <= 100
    assert isinstance(data["landowner_user_id"], str) and data["landowner_user_id"]
    assert data["lease_status"] in _LEASE_STATUSES
    assert data["negotiation_round_count"] >= 0
    assert data["bonus_settlement_usd"] >= 0
    assert data["net_acreage"] >= 0
    assert_cost_precision(data["bonus_settlement_usd"])


def assert_injection_well_permit(data: dict) -> None:
    _assert_common_fields(data, "injection well permit")
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("geologic_model_id", ""))
    assert isinstance(data["well_name"], str) and data["well_name"]
    assert data["casing_program"] in [
        "LONG_STRING_CEMENTED_TO_SURFACE",
        "LINER",
        "SINGLE_STRING",
    ]
    assert isinstance(data["corrosion_resistant_material"], bool)
    assert isinstance(data["tubing_packer_installed"], bool)
    assert data["requested_injection_pressure_psi"] > 0
    assert data["max_injection_pressure_psi"] >= 0
    assert data["authorized_injection_rate_tpy"] >= 0
    assert data["permit_status"] in _PERMIT_STATUSES
    assert data["construction_status"] in _CONSTRUCTION_STATUSES
    assert data["last_mit_type"] in [
        None,
        "ANNULUS_PRESSURE",
        "TEMPERATURE_LOG",
        "CASING_INSPECTION_LOG",
    ]
    assert data["last_mit_result"] in [None, "PASS", "FAIL"]
    assert data["mit_pass_count"] >= 0
    assert data["revision_round_count"] >= 0
    assert_cost_precision(data["max_injection_pressure_psi"])


def assert_monitoring_plan(data: dict) -> None:
    _assert_common_fields(data, "monitoring plan")
    assert is_valid_uuid(data.get("project_id", ""))
    assert isinstance(data["plan_label"], str) and data["plan_label"]
    assert data["status"] in _PLAN_STATUSES
    assert isinstance(data["technical_review_complete"], bool)
    assert isinstance(data["public_comment_complete"], bool)
    assert_monitoring_plan_invariants(data)


def assert_monitoring_plan_invariants(data: dict) -> None:
    """Each domain subscore saturates at 1.0000 and the weighted score at 100."""
    for field in ("subsurface_subscore", "surface_subscore", "atmospheric_subscore"):
        assert 0 <= data[field] <= 1.0, f"{field} saturates at 1.0000"
    assert 0 <= data["coverage_score"] <= 100
    assert data["condition_count"] >= 0
    assert data["revision_round_count"] >= 0


def assert_monitoring_method(data: dict) -> None:
    _assert_common_fields(data, "monitoring method")
    assert is_valid_uuid(data.get("monitoring_plan_id", ""))
    assert data["domain"] in ["SUBSURFACE", "SURFACE", "ATMOSPHERIC"]
    assert isinstance(data["technique"], str) and data["technique"]
    assert data["detection_threshold_tpy"] > 0
    assert data["frequency_per_year"] >= 1
    assert 0 < data["spatial_coverage_pct"] <= 100
    assert 0 <= data["method_score"] <= 1.0
    assert data["status"] in _METHOD_STATUSES


def assert_financial_instrument(data: dict) -> None:
    _assert_common_fields(data, "financial instrument")
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["instrument_type"] in [
        "TRUST_FUND",
        "SURETY_BOND",
        "LETTER_OF_CREDIT",
        "INSURANCE",
    ]
    assert data["face_amount_usd"] > 0
    assert data["status"] in _INSTRUMENT_STATUSES
    assert_dollar_conservation(data)


def assert_dollar_conservation(data: dict) -> None:
    """The four allocated buckets plus unallocated plus drawn add back to the face."""
    total = round(
        data["allocated_ca_usd"]
        + data["allocated_plugging_usd"]
        + data["allocated_pisc_usd"]
        + data["allocated_emergency_usd"]
        + data["unallocated_usd"]
        + data["drawn_usd"],
        2,
    )
    assert total == round(float(data["face_amount_usd"]), 2), (
        "the four allocated buckets plus unallocated_usd plus drawn_usd must add "
        f"back to face_amount_usd, got {total} against {data['face_amount_usd']}"
    )


def assert_injection_period_record(data: dict) -> None:
    """An injection period record carries only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), "injection period id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), "injection period created_at must be ISO 8601"
    assert "updated_at" not in data, "an injection period record carries no updated_at"
    assert "version" not in data, "an injection period record carries no version"
    assert is_valid_uuid(data.get("permit_id", ""))
    assert data["mass_injected_tonnes"] >= 0
    assert data["measured_leakage_tonnes"] >= 0
    assert data["measured_leakage_tonnes"] <= data["mass_injected_tonnes"]
    assert data["status"] in _PERIOD_STATUSES


def assert_tax_credit_claim(data: dict) -> None:
    _assert_common_fields(data, "tax credit claim")
    assert is_valid_uuid(data.get("project_id", ""))
    assert is_valid_uuid(data.get("monitoring_plan_id", ""))
    assert 2020 <= data["tax_year"] <= 2100
    assert data["claim_variant"] in ["REPORTED", "VERIFIED"]
    assert 0 <= data["lca_upstream_emissions_factor"] <= 0.5
    assert data["reported_tonnes"] >= 0
    assert data["credit_rate_usd_per_tonne"] >= 0
    assert data["status"] in _CLAIM_STATUSES
    assert_cost_precision(data["credit_amount_usd"])


def assert_remediation_order(data: dict) -> None:
    _assert_common_fields(data, "remediation order")
    assert is_valid_uuid(data.get("project_id", ""))
    assert data["trigger_type"] in [
        "SEAL_BREACH_INDICATION",
        "WELL_INTEGRITY_LOSS",
        "PLUME_EXCURSION",
        "GROUNDWATER_IMPACT",
    ]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert data["status"] in _ORDER_STATUSES
    assert data["reserve_draw_usd"] >= 0
    assert_cost_precision(data["reserve_draw_usd"])
