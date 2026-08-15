"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` checks only properties the PRD guarantees: a
server-minted UUID ``id``, ISO 8601 ``created_at``, the common ``updated_at`` /
``version`` pair for versioned entities (absent on the two append-only ledger
entities per PRD section 2.4), and membership of the entity's status fields in
their PRD-declared value sets.
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Timestamp comparison tolerant to fractional-second rendering. The PRD
# requires computed UTC deadlines and timestamps to be precise to the second;
# a serializer may or may not render a ".000" fractional suffix.
# ---------------------------------------------------------------------------

def _parse_iso8601(value: str) -> datetime:
    assert isinstance(value, str), f"Expected ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_timestamp_equals(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant (second precision)."""
    actual_dt = _parse_iso8601(actual)
    expected_dt = _parse_iso8601(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def _assert_append_only_fields(data: dict, entity: str):
    """Append-only ledger rows carry only id + created_at (no updated_at/version)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "version" not in data, f"{entity} is append-only; unexpected 'version' key present"
    assert "updated_at" not in data, f"{entity} is append-only; unexpected 'updated_at' key present"


def assert_vessel(data: dict):
    _assert_common_fields(data, "Vessel")
    assert isinstance(data.get("imo_number"), str) and data["imo_number"], "imo_number required"
    assert isinstance(data.get("vessel_name"), str) and data["vessel_name"], "vessel_name required"
    assert data.get("flag_state") == "US", f"flag_state must be US, got {data.get('flag_state')!r}"
    assert data.get("bwms_type") in [
        "NONE", "EXCHANGE_ONLY", "TREATMENT_USCG_TYPE_APPROVED", "TREATMENT_ALTERNATIVE",
    ], f"bad bwms_type {data.get('bwms_type')!r}"
    assert data.get("compliance_posture") in ["OPEN", "RESTRICTED", "FROZEN"], (
        f"bad compliance_posture {data.get('compliance_posture')!r}"
    )


def assert_plan(data: dict):
    _assert_common_fields(data, "BallastWaterManagementPlan")
    assert isinstance(data.get("plan_revision"), int) and data["plan_revision"] >= 1
    assert data.get("approval_authority") in ["USCG", "CLASS_SOCIETY_ON_BEHALF"]
    assert data.get("status") in ["DRAFT", "SUBMITTED", "APPROVED", "SUPERSEDED", "WITHDRAWN"]


def assert_voyage(data: dict):
    _assert_common_fields(data, "Voyage")
    assert isinstance(data.get("voyage_number"), str) and data["voyage_number"]
    assert data.get("compliance_status") in [
        "PENDING", "IN_PROGRESS", "COMPLIANT", "NONCOMPLIANT", "EXEMPT",
    ], f"bad compliance_status {data.get('compliance_status')!r}"
    assert data.get("reporting_status") in [
        "NOT_DUE", "DUE", "SUBMITTED", "ACKNOWLEDGED", "OVERDUE",
    ], f"bad reporting_status {data.get('reporting_status')!r}"


def assert_ballast_event(data: dict):
    _assert_append_only_fields(data, "BallastWaterEvent")
    assert data.get("event_kind") in [
        "UPTAKE", "DISCHARGE", "EXCHANGE_START", "EXCHANGE_COMPLETE",
        "TREATMENT_START", "TREATMENT_COMPLETE", "TANK_FLUSH", "SEDIMENT_DISPOSAL",
    ], f"bad event_kind {data.get('event_kind')!r}"
    assert isinstance(data.get("tank_id"), str) and data["tank_id"]
    assert data.get("volume_m3") is not None and data["volume_m3"] > 0


def assert_determination(data: dict):
    _assert_common_fields(data, "ComplianceDetermination")
    assert data.get("determination_basis") in [
        "EXCHANGE_COMPLIANT", "TREATMENT_COMPLIANT", "EXEMPT_SAME_COTP", "EXEMPT_NO_US_EEZ",
        "NONCOMPLIANT_MIXED", "NONCOMPLIANT_NO_METHOD", "INSUFFICIENT_DATA",
    ], f"bad determination_basis {data.get('determination_basis')!r}"
    assert data.get("trigger_reason") in [
        "VOYAGE_DEPARTURE", "BALLAST_EVENT_RECORDED", "VOYAGE_ARRIVAL",
        "MANUAL_RECOMPUTE", "PLAN_AMENDMENT",
    ], f"bad trigger_reason {data.get('trigger_reason')!r}"
    assert isinstance(data.get("is_current"), bool)


def assert_report(data: dict):
    _assert_common_fields(data, "BallastWaterReport")
    assert data.get("report_type") in ["PRE_ARRIVAL", "POST_DISCHARGE", "ANNUAL_SUMMARY"]
    assert data.get("status") in ["DRAFT", "SUBMITTED", "ACKNOWLEDGED", "REJECTED"]
    assert isinstance(data.get("is_overdue"), bool)


def assert_inspection(data: dict):
    _assert_common_fields(data, "SamplingInspection")
    assert data.get("inspection_kind") in [
        "PORT_STATE_CONTROL", "FLAG_STATE", "CLASS_SOCIETY", "COMPANY_INTERNAL",
    ]
    assert data.get("sampled_by_role") in ["PSC_OFFICER", "FLAG_SURVEYOR", "COMPANY_AUDITOR"]
    assert data.get("status") in ["RECORDED", "EVALUATED", "CLOSED", "REOPENED"]


def assert_noncompliance_record(data: dict):
    _assert_common_fields(data, "NoncomplianceRecord")
    assert data.get("source_type") in [
        "SAMPLING_EXCEEDANCE", "REPORT_OVERDUE", "MISSING_METHOD",
        "PSC_DEFICIENCY", "DETERMINATION_NONCOMPLIANT",
    ]
    assert data.get("severity") in ["MINOR", "MAJOR", "CRITICAL"]
    assert data.get("response_status") in ["OPEN", "RESPONDED", "CLOSED", "ESCALATED"]


def assert_deficiency(data: dict):
    _assert_common_fields(data, "PortStateControlDeficiency")
    assert data.get("action_code") in ["A10", "A15", "A16", "A17", "A99"]
    assert data.get("rectification_status") in [
        "OPEN", "RECTIFYING", "RECTIFIED", "VERIFIED", "REOPENED",
    ]
    assert isinstance(data.get("is_priority_one"), bool)


def assert_record_book(data: dict):
    _assert_common_fields(data, "RecordBook")
    assert data.get("book_kind") in ["BALLAST_WATER", "GARBAGE", "SEWAGE", "OILY_WATER"]
    assert data.get("status") in ["OPEN", "SEALED"]


def assert_record_book_entry(data: dict):
    _assert_append_only_fields(data, "RecordBookEntry")
    assert data.get("entry_kind") in [
        "UPTAKE", "DISCHARGE", "EXCHANGE", "TREATMENT", "TANK_FLUSH",
        "DISCHARGE_SEA", "DISCHARGE_RECEPTION", "INCINERATION",
        "DISCHARGE_TREATED", "DISCHARGE_UNTREATED",
        "BILGE_DISCHARGE", "SLUDGE_DISPOSAL", "ODM_FLUSH",
    ]
    assert data.get("quantity") is not None and data["quantity"] > 0
    assert isinstance(data.get("signed_by"), str) and data["signed_by"]


def assert_emissions_record(data: dict):
    _assert_common_fields(data, "EmissionsFuelRecord")
    assert data.get("fuel_type") in ["HFO", "VLSFO", "MGO", "MDO", "LNG", "BIOFUEL_BLEND"]
    assert data.get("compliance_status") in [
        "PENDING_EVAL", "COMPLIANT", "NONCOMPLIANT", "EXEMPT_SCRUBBER",
    ]


def assert_drill(data: dict):
    _assert_common_fields(data, "CrewTrainingDrill")
    assert data.get("drill_kind") in [
        "BWMS_OPERATION", "EMERGENCY_BALLAST_EXCHANGE", "OIL_SPILL_RESPONSE",
        "SEWAGE_SYSTEM", "GARBAGE_MANAGEMENT", "MARPOL_AWARENESS",
    ]
    assert data.get("completion_status") in ["SCHEDULED", "COMPLETED", "OVERDUE", "CANCELLED"]


def assert_enforcement_case(data: dict):
    _assert_common_fields(data, "EnforcementCase")
    assert data.get("status") in [
        "ACTIVE", "UNDER_REVIEW", "CLOSED_COMPLIANT", "CLOSED_PENALTY", "WITHDRAWN",
    ]


def assert_determination_partition_conserved(data: dict):
    """Domain invariant: the discharged volume always partitions exactly into
    exchange + treatment + noncompliant buckets."""
    total = data["total_discharged_volume_m3"]
    parts = (
        data["exchange_compliant_volume_m3"]
        + data["treatment_compliant_volume_m3"]
        + data["noncompliant_volume_m3"]
    )
    assert abs(total - parts) < 1e-6, (
        f"Determination partition broken: total {total} != "
        f"exchange {data['exchange_compliant_volume_m3']} + "
        f"treatment {data['treatment_compliant_volume_m3']} + "
        f"noncompliant {data['noncompliant_volume_m3']}"
    )
