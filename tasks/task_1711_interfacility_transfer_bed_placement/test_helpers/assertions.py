"""Entity assertions and domain invariant checkers.

Timestamp comparisons parse ISO 8601 strings into instants so assertions pin
the instant (which the PRD fixes via the logical clock) without depending on
the rendering of fractional seconds.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_timestamp(value):
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds)."""
    assert isinstance(value, str), f"expected timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not ISO 8601 UTC: {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def assert_timestamp_equals(value, expected_iso):
    """Assert two timestamps denote the same instant."""
    assert parse_timestamp(value) == parse_timestamp(expected_iso), (
        f"timestamp {value!r} != expected {expected_iso!r}"
    )


def _assert_common(data, versioned=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601: {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1, (
            f"version must be a positive int: {data.get('version')!r}"
        )
    else:
        assert "updated_at" not in data, "append-only record must omit updated_at"
        assert "version" not in data, "append-only record must omit version"


def assert_facility(data):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert data["trauma_level"] in [
        "LEVEL_1", "LEVEL_2", "LEVEL_3", "COMMUNITY", "CRITICAL_ACCESS"]
    assert isinstance(data["capabilities"], list)
    assert data["diversion_status"] in ["OPEN", "SOFT_DIVERSION", "HARD_DIVERSION"]
    assert isinstance(data["operational_bed_count"], int)
    assert isinstance(data["unavailable_bed_count"], int)
    assert data["unavailable_bed_count"] <= data["operational_bed_count"]
    assert isinstance(data["occupancy_pct"], (int, float))


def assert_bed(data):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["bed_code"], str) and data["bed_code"]
    assert data["unit_type"] in [
        "ICU", "CVICU", "NICU", "PICU", "TELEMETRY", "MED_SURG", "BURN", "ED_HOLD"]
    assert isinstance(data["isolation_capable"], bool)
    assert data["status"] in ["AVAILABLE", "HELD", "OCCUPIED", "OUT_OF_SERVICE"]


def assert_physician(data):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_valid_uuid(data["facility_id"])
    assert data["specialty"] in [
        "EMERGENCY", "CARDIOLOGY", "NEUROLOGY", "SURGERY",
        "INTENSIVIST", "PEDIATRICS", "GENERAL"]
    assert isinstance(data["is_on_call"], bool)


def assert_transfer_case(data):
    _assert_common(data)
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert is_valid_uuid(data["sending_facility_id"])
    assert is_valid_uuid(data["sending_physician_id"])
    assert data["acuity_level"] in ["CRITICAL", "EMERGENT", "URGENT", "STABLE"]
    assert data["required_unit_type"] in [
        "ICU", "CVICU", "NICU", "PICU", "TELEMETRY", "MED_SURG", "BURN", "ED_HOLD"]
    assert isinstance(data["requires_isolation"], bool)
    assert isinstance(data["required_capability"], str) and data["required_capability"]
    assert data["status"] in [
        "INTAKE", "EMTALA_DETERMINED", "AWAITING_ACCEPTANCE", "ACCEPTED",
        "TRANSPORT_ARRANGED", "EN_ROUTE", "ARRIVED", "COMPLETED",
        "REFUSED", "CANCELLED"]
    assert data["emtala_obligation"] in [
        "UNDETERMINED", "EMTALA_APPLIES", "EMTALA_NOT_APPLIES", "EMERGENCY_EXCEPTION"]
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 0
    assert isinstance(data["refusal_count"], int) and data["refusal_count"] >= 0


def assert_emtala_screening(data):
    _assert_common(data)
    assert is_valid_uuid(data["transfer_case_id"])
    assert isinstance(data["has_emergency_medical_condition"], bool)
    assert isinstance(data["is_stabilized"], bool)
    assert isinstance(data["benefits_outweigh_risks"], bool)
    assert isinstance(data["physician_certification"], str)
    assert data["determination"] in [
        "EMTALA_NOT_APPLIES", "EMTALA_APPLIES", "EMERGENCY_EXCEPTION"]
    assert data["status"] in ["DRAFT", "CERTIFIED", "AMENDED"]
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0


def assert_physician_communication(data):
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["transfer_case_id"])
    assert is_valid_uuid(data["from_physician_id"])
    assert is_valid_uuid(data["to_physician_id"])
    assert isinstance(data["round"], int) and data["round"] >= 1
    assert data["contact_method"] in ["PHONE", "SECURE_MESSAGE", "TELEMEDICINE"]
    assert data["outcome"] in ["PENDING", "ACCEPTED", "REFUSED", "VOIDED"]


def assert_bed_hold(data):
    _assert_common(data)
    assert is_valid_uuid(data["bed_id"])
    assert is_valid_uuid(data["transfer_case_id"])
    assert data["status"] in ["ACTIVE", "CONFIRMED", "RELEASED", "EXPIRED"]
    assert is_iso8601_timestamp(data["hold_started_at"])
    assert is_iso8601_timestamp(data["hold_expires_at"])
    if data.get("release_reason") is not None:
        assert data["release_reason"] in [
            "MANUAL", "SUPERSEDED", "CASE_CANCELLED", "ARRIVAL_CONFIRMED", "EXPIRED"]


def assert_transport_dispatch(data):
    _assert_common(data)
    assert is_valid_uuid(data["transfer_case_id"])
    assert data["mode"] in ["GROUND_BLS", "GROUND_ALS", "AIR_ROTOR", "AIR_FIXED_WING"]
    assert data["crew_capability"] in ["BLS", "ALS", "CCT", "CRITICAL_CARE"]
    assert data["distance_miles"] > 0
    assert isinstance(data["estimated_minutes_optimistic"], int)
    assert isinstance(data["estimated_minutes_conservative"], int)
    assert data["estimated_minutes_conservative"] >= data["estimated_minutes_optimistic"]
    assert data["status"] in ["DISPATCHED", "EN_ROUTE", "ARRIVED", "CANCELLED"]
    assert is_iso8601_timestamp(data["dispatched_at"])


def assert_insurance_notification(data):
    _assert_common(data)
    assert is_valid_uuid(data["transfer_case_id"])
    assert isinstance(data["payer_id"], str) and data["payer_id"]
    assert data["channel"] in ["PORTAL", "PHONE", "FAX"]
    assert is_iso8601_timestamp(data["sla_due_at"])
    assert data["status"] in ["PENDING", "NOTIFIED", "EXCEPTION_CLAIMED", "VOIDED"]
    assert isinstance(data["is_late"], bool)


def assert_clinical_packet(data):
    _assert_common(data)
    assert is_valid_uuid(data["transfer_case_id"])
    assert isinstance(data["required_documents"], list)
    assert len(data["required_documents"]) > 0
    assert isinstance(data["received_documents"], list)
    assert isinstance(data["imaging_studies"], list)
    assert isinstance(data["exchanged_study_refs"], list)
    assert data["document_status"] in ["DOCUMENTS_COMPLETE", "INCOMPLETE"]
    assert data["imaging_status"] in ["IMAGING_COMPLETE", "IMAGING_PENDING"]
    assert data["overall_status"] in ["READY", "INCOMPLETE"]


def assert_refusal_record(data):
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["transfer_case_id"])
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["refusing_physician_id"])
    assert data["refusal_category"] in [
        "NO_BED_AVAILABLE", "CAPABILITY_UNAVAILABLE", "DIVERSION_ACTIVE",
        "UNSTABLE_FOR_TRANSFER", "CAPACITY_EXCEEDED"]
    assert isinstance(data["narrative"], str)
    assert isinstance(data["emtala_risk_score"], int)
    assert data["emtala_risk_flag"] in ["HIGH", "ELEVATED", "LOW"]
    assert isinstance(data["round"], int) and data["round"] >= 1


def assert_transfer_outcome(data):
    _assert_common(data, versioned=False)
    assert is_valid_uuid(data["transfer_case_id"])
    assert data["arrival_condition"] in ["STABLE", "DETERIORATED", "CRITICAL_DECLINE"]
    assert isinstance(data["deterioration_en_route"], bool)
    assert isinstance(data["receiving_physician_confirmed"], bool)
    assert isinstance(data["door_to_arrival_minutes"], int)
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_quality_review(data):
    _assert_common(data)
    assert is_valid_uuid(data["transfer_case_id"])
    assert data["trigger"] in ["ROUTINE", "REFUSAL_RISK", "DETERIORATION"]
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "CLOSED"]


def assert_diversion_event(data):
    _assert_common(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["scope"] in ["ALL_UNITS", "SPECIFIC_UNIT"]
    if data["scope"] == "SPECIFIC_UNIT":
        assert data["unit_type"] in [
            "ICU", "CVICU", "NICU", "PICU", "TELEMETRY", "MED_SURG", "BURN",
            "ED_HOLD"]
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert parse_timestamp(data["ends_at"]) > parse_timestamp(data["starts_at"])
    assert isinstance(data["reason"], str)
    assert isinstance(data["auto_created"], bool)
    assert data["effective_status"] in ["SCHEDULED", "ACTIVE", "EXPIRED", "LIFTED"]


def assert_occupancy_consistent(facility):
    """PRD occupancy invariant: counts and percentage stay mutually consistent."""
    op = facility["operational_bed_count"]
    un = facility["unavailable_bed_count"]
    pct = facility["occupancy_pct"]
    if op == 0:
        assert float(pct) == 100.0, (
            f"zero operational beds must pin occupancy_pct to 100.0, got {pct}")
    else:
        expected = round(un / op * 100 + 1e-9, 2)
        assert abs(float(pct) - expected) < 0.01, (
            f"occupancy_pct {pct} != {expected} from {un}/{op}")
