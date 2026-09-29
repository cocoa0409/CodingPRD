"""Shape and value assertions for aquarium resources."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BREACH_PARAMETER_ORDER


# --------------------------------------------------------------------------
# Common shape
# --------------------------------------------------------------------------
def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Resources carry a uuid id, ISO-8601 stamps and an integer version."""
    assert is_valid_uuid(resource["id"]), f"id is not a uuid: {resource['id']}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int), resource["version"]
    assert resource["version"] >= 1, resource["version"]


def assert_append_only_record(record: Dict[str, Any]) -> None:
    """Observations carry `id` and `created_at` and nothing else of the common set."""
    assert is_valid_uuid(record["id"]), f"id is not a uuid: {record['id']}"
    assert is_iso8601_timestamp(record["created_at"]), record["created_at"]
    assert "updated_at" not in record, "append-only record must not expose updated_at"
    assert "version" not in record, "append-only record must not expose version"


def assert_fields_present(resource: Dict[str, Any], fields: List[str]) -> None:
    missing = [f for f in fields if f not in resource]
    assert not missing, f"missing fields {missing} in {sorted(resource)}"


# --------------------------------------------------------------------------
# Numeric precision
# --------------------------------------------------------------------------
def assert_two_decimals(value: Any) -> None:
    """A monetary-style quantity must be expressible in exactly two decimals."""
    assert isinstance(value, (int, float)), value
    assert round(float(value), 2) == float(value), f"{value} carries more than 2 decimals"


def assert_scaled_equal(actual: Any, expected: float) -> None:
    """Compare two two-decimal quantities."""
    assert isinstance(actual, (int, float)), actual
    assert abs(float(actual) - float(expected)) < 0.005, f"expected {expected}, got {actual}"


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------
def assert_life_support_system(system: Dict[str, Any]) -> None:
    assert_common_fields(system)
    assert_fields_present(
        system,
        [
            "system_code",
            "system_type",
            "design_habitat",
            "redundancy_class",
            "redundancy_test_interval_days",
            "last_redundancy_test_at",
            "last_redundancy_test_result",
            "redundancy_overdue",
            "alarm_state",
            "consecutive_normal_readings",
            "consecutive_breach_readings",
            "water_quality_index",
        ],
    )
    assert_two_decimals(system["water_quality_index"])


def assert_water_quality_reading(reading: Dict[str, Any]) -> None:
    assert_append_only_record(reading)
    assert_fields_present(
        reading,
        [
            "life_support_system_id",
            "taken_at",
            "temperature_c",
            "salinity_ppt",
            "ph",
            "dissolved_oxygen_mg_l",
            "ammonia_mg_l",
            "nitrite_mg_l",
            "severity",
            "breach_parameters",
            "water_quality_index_snapshot",
        ],
    )
    assert_two_decimals(reading["water_quality_index_snapshot"])
    assert_canonical_breach_order(reading["breach_parameters"])


def assert_canonical_breach_order(breach_parameters: List[str]) -> None:
    """Breached parameters are always emitted in the fixed canonical order."""
    positions = [BREACH_PARAMETER_ORDER.index(p) for p in breach_parameters]
    assert positions == sorted(positions), f"not in canonical order: {breach_parameters}"


def assert_exhibit(exhibit: Dict[str, Any]) -> None:
    assert_common_fields(exhibit)
    assert_fields_present(
        exhibit,
        [
            "exhibit_code",
            "name",
            "habitat_type",
            "life_support_system_id",
            "display_volume_liters",
            "bioload_capacity_units",
            "occupied_bioload_units",
            "bioload_utilization_pct",
            "posture",
            "last_posture_reason",
            "interaction_program_enabled",
            "suspended_session_count",
        ],
    )
    assert_two_decimals(exhibit["occupied_bioload_units"])
    assert_two_decimals(exhibit["bioload_utilization_pct"])


def assert_species(species: Dict[str, Any]) -> None:
    assert_common_fields(species)
    assert_fields_present(
        species,
        [
            "scientific_name",
            "common_name",
            "taxon_group",
            "protection_status",
            "sustainability_rating",
            "bioload_units_per_specimen",
            "base_quarantine_days",
            "wild_take_quota_annual",
            "wild_take_quota_reserved",
            "permit_required",
        ],
    )


def assert_institution(institution: Dict[str, Any]) -> None:
    assert_common_fields(institution)
    assert_fields_present(
        institution,
        [
            "name",
            "institution_code",
            "accreditation_status",
            "welfare_audit_score",
            "last_audit_at",
            "is_receiving_eligible",
        ],
    )
    assert_two_decimals(institution["welfare_audit_score"])


def assert_collection_plan_entry(entry: Dict[str, Any]) -> None:
    assert_common_fields(entry)
    assert_fields_present(
        entry,
        [
            "exhibit_id",
            "species_id",
            "planned_count",
            "sustainability_requirement",
            "status",
            "approved_by_user_id",
            "approved_at",
            "superseded_by_entry_id",
            "suspension_reason",
        ],
    )


def assert_acquisition_request(request: Dict[str, Any]) -> None:
    assert_common_fields(request)
    assert_fields_present(
        request,
        [
            "collection_plan_entry_id",
            "source_type",
            "source_institution_id",
            "requested_count",
            "justification",
            "status",
            "permit_required",
            "permit_deadline_at",
            "sustainability_score",
            "sustainability_score_variant",
            "quota_units_reserved",
            "fulfilled_count",
            "cleared_by_user_id",
            "cleared_at",
            "closure_reason",
        ],
    )
    assert_two_decimals(request["sustainability_score"])


def assert_permit(permit: Dict[str, Any]) -> None:
    assert_common_fields(permit)
    assert_fields_present(
        permit,
        [
            "acquisition_request_id",
            "permit_type",
            "authority_reference",
            "document_codes",
            "status",
            "submission_round",
            "missing_document_codes",
            "valid_from",
            "valid_until",
            "issued_at",
            "decision_reason",
        ],
    )


def assert_specimen(specimen: Dict[str, Any]) -> None:
    assert_common_fields(specimen)
    assert_fields_present(
        specimen,
        [
            "accession_code",
            "species_id",
            "acquisition_request_id",
            "exhibit_id",
            "holding_area",
            "arrival_at",
            "disposition_status",
            "health_status",
            "pre_transfer_disposition",
            "bioload_units",
            "quarantine_required_days",
            "welfare_score",
            "welfare_score_variant",
            "sire_specimen_id",
            "dam_specimen_id",
            "captive_bred",
            "treatment_withdrawal_until",
        ],
    )


def assert_quarantine_case(case: Dict[str, Any]) -> None:
    assert_common_fields(case)
    assert_fields_present(
        case,
        [
            "specimen_id",
            "protocol_days",
            "started_at",
            "projected_release_at",
            "status",
            "extension_count",
            "total_extension_days",
            "clearance_exam_count",
            "cleared_by_user_id",
            "cleared_at",
            "failure_reason",
        ],
    )


def assert_veterinary_case(case: Dict[str, Any]) -> None:
    assert_common_fields(case)
    assert_fields_present(
        case,
        [
            "specimen_id",
            "case_type",
            "opened_at",
            "treatment_start_at",
            "withdrawal_days",
            "diagnosis_code",
            "status",
            "outcome",
            "findings_severity",
            "opened_by_user_id",
            "closed_by_user_id",
            "closed_at",
        ],
    )


def assert_husbandry_log(log: Dict[str, Any]) -> None:
    assert_append_only_record(log)
    assert_fields_present(
        log,
        [
            "specimen_id",
            "log_type",
            "logged_at",
            "appetite_score",
            "behavior_code",
            "feed_grams",
            "weight_grams",
            "note",
            "recorded_by_user_id",
        ],
    )


def assert_transfer_request(transfer: Dict[str, Any]) -> None:
    assert_common_fields(transfer)
    assert_fields_present(
        transfer,
        [
            "specimen_id",
            "receiving_institution_id",
            "transport_permit_id",
            "proposed_transfer_at",
            "welfare_conditions",
            "counter_conditions",
            "status",
            "negotiation_round",
            "decided_by_user_id",
            "decided_at",
            "completed_at",
            "decline_reason",
        ],
    )


def assert_interaction_session(session: Dict[str, Any]) -> None:
    assert_common_fields(session)
    assert_fields_present(
        session,
        [
            "exhibit_id",
            "program_type",
            "starts_at",
            "ends_at",
            "max_guests",
            "guest_count",
            "safety_briefing_confirmed",
            "status",
            "suspension_reason",
        ],
    )


def assert_accreditation_audit(audit: Dict[str, Any]) -> None:
    assert_common_fields(audit)
    assert_fields_present(
        audit,
        [
            "audit_code",
            "scope",
            "scheduled_for",
            "status",
            "readiness_score",
            "domain_subscores",
            "blocking_finding_count",
            "opened_by_user_id",
            "closed_by_user_id",
            "started_at",
            "closed_at",
            "determination_note",
        ],
    )


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
def assert_posture(exhibit: Dict[str, Any], posture: str, reason: Optional[str]) -> None:
    assert exhibit["posture"] == posture, f"posture {exhibit['posture']} != {posture}"
    assert exhibit["last_posture_reason"] == reason, (
        f"last_posture_reason {exhibit['last_posture_reason']} != {reason}"
    )


def assert_alarm(system: Dict[str, Any], alarm_state: str, normals: Optional[int] = None, breaches: Optional[int] = None) -> None:
    assert system["alarm_state"] == alarm_state, f"{system['alarm_state']} != {alarm_state}"
    if normals is not None:
        assert system["consecutive_normal_readings"] == normals, system["consecutive_normal_readings"]
    if breaches is not None:
        assert system["consecutive_breach_readings"] == breaches, system["consecutive_breach_readings"]
