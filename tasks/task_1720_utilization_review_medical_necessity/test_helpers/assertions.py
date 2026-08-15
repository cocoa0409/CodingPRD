"""Entity assertions and domain invariant checkers.

Each assert_* checks the resource's structural contract from the PRD:
server-minted UUID id (§2.6), ISO 8601 timestamps (§2.6), and enum
membership for every status/enum field (§3). Assertions deliberately avoid
fields the PRD leaves to server discretion.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdmissionReviewStatus,
    AdmissionStatus,
    AppealStatus,
    AuthRequestStatus,
    AuthStatus,
    AvoidableDayStatus,
    BarrierCode,
    BenchmarkBasis,
    BenchmarkMet,
    Cc44Status,
    ConcurrentReviewStatus,
    ConferenceOutcome,
    ConferenceStatus,
    CriteriaSet,
    DenialReasonCode,
    DenialStatus,
    DenialType,
    EscalationStatus,
    PlanClass,
    ReviewDetermination,
    ReviewStatus,
    AttributionMethod,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def _assert_enum(data: dict, field: str, enum_cls, entity: str):
    values = {m.value for m in enum_cls}
    assert data.get(field) in values, (
        f"{entity}.{field} must be one of {sorted(values)}, got {data.get(field)!r}"
    )


def assert_payer(data: dict):
    _assert_common_fields(data, "Payer")
    assert isinstance(data["name"], str) and data["name"]
    _assert_enum(data, "plan_class", PlanClass, "Payer")
    assert isinstance(data["requires_inpatient_auth"], bool)
    assert isinstance(data["concurrent_review_cadence_hours"], int)
    assert data["concurrent_review_cadence_hours"] >= 1
    assert isinstance(data["p2p_window_hours"], int) and data["p2p_window_hours"] >= 1
    assert isinstance(data["appeal_deadline_days"], int)
    assert data["appeal_deadline_days"] >= 1
    assert isinstance(data["bed_day_budget_per_case"], int)
    assert data["bed_day_budget_per_case"] >= 1
    _assert_enum(data, "avoidable_attribution_method", AttributionMethod, "Payer")


def assert_physician(data: dict):
    _assert_common_fields(data, "Physician")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["specialty"], str) and data["specialty"]
    assert isinstance(data["is_advisor"], bool)


def assert_utilization_case(data: dict):
    _assert_common_fields(data, "UtilizationCase")
    assert isinstance(data["patient_mrn"], str) and data["patient_mrn"]
    assert is_valid_uuid(data.get("payer_id", ""))
    assert is_valid_uuid(data.get("attending_physician_id", ""))
    assert is_iso8601_timestamp(data.get("admit_at", ""))
    assert is_iso8601_timestamp(data.get("expected_discharge_at", ""))
    _assert_enum(data, "requested_admission_status", AdmissionStatus, "UtilizationCase")
    _assert_enum(data, "current_admission_status", AdmissionStatus, "UtilizationCase")
    _assert_enum(data, "review_status", ReviewStatus, "UtilizationCase")
    _assert_enum(data, "auth_status", AuthStatus, "UtilizationCase")
    assert isinstance(data["expected_midnight_count"], int)
    _assert_enum(data, "two_midnight_benchmark_met", BenchmarkMet, "UtilizationCase")
    _assert_enum(data, "benchmark_basis", BenchmarkBasis, "UtilizationCase")
    for counter in ("certified_day_count", "certified_inpatient_day_count",
                    "certified_observation_day_count", "open_avoidable_day_count",
                    "escalation_tier"):
        assert isinstance(data[counter], int), f"UtilizationCase.{counter} must be int"


def assert_admission_review(data: dict):
    _assert_common_fields(data, "AdmissionReview")
    assert is_valid_uuid(data.get("case_id", ""))
    _assert_enum(data, "criteria_set", CriteriaSet, "AdmissionReview")
    assert 0 <= data["severity_of_illness_points"] <= 20
    assert 0 <= data["intensity_of_service_points"] <= 20
    assert 0 <= data["comorbidity_count"] <= 10
    assert isinstance(data["two_midnight_attestation"], bool)
    _assert_enum(data, "determination", ReviewDetermination, "AdmissionReview")
    _assert_enum(data, "status", AdmissionReviewStatus, "AdmissionReview")


def assert_authorization_request(data: dict):
    _assert_common_fields(data, "AuthorizationRequest")
    assert is_valid_uuid(data.get("case_id", ""))
    _assert_enum(data, "level_of_care", AdmissionStatus, "AuthorizationRequest")
    assert isinstance(data["requested_day_count"], int)
    assert data["requested_day_count"] >= 1
    assert isinstance(data["clinical_summary"], str)
    assert isinstance(data["submission_round"], int) and data["submission_round"] >= 1
    _assert_enum(data, "status", AuthRequestStatus, "AuthorizationRequest")
    if data.get("denial_reason_code") is not None:
        _assert_enum(data, "denial_reason_code", DenialReasonCode,
                     "AuthorizationRequest")


def assert_concurrent_review(data: dict):
    _assert_common_fields(data, "ConcurrentReview")
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert isinstance(data["clinical_update"], str)
    assert isinstance(data["requested_additional_day_count"], int)
    assert data["requested_additional_day_count"] >= 1
    assert is_iso8601_timestamp(data.get("review_due_at", ""))
    _assert_enum(data, "status", ConcurrentReviewStatus, "ConcurrentReview")


def assert_p2p_conference(data: dict):
    _assert_common_fields(data, "PeerToPeerConference")
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    assert is_valid_uuid(data.get("attending_physician_id", ""))
    assert is_valid_uuid(data.get("advisor_physician_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert is_iso8601_timestamp(data.get("window_deadline_at", ""))
    assert isinstance(data["reschedule_count"], int) and data["reschedule_count"] >= 0
    _assert_enum(data, "status", ConferenceStatus, "PeerToPeerConference")
    _assert_enum(data, "outcome", ConferenceOutcome, "PeerToPeerConference")


def assert_cc44_request(data: dict):
    _assert_common_fields(data, "ConditionCode44Request")
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["rationale"], str) and data["rationale"]
    assert isinstance(data["service_lines"], list)
    for line in data["service_lines"]:
        assert isinstance(line["description"], str)
        assert isinstance(line["charge_cents"], int)
        assert isinstance(line["rate_milli"], int)
    assert isinstance(data["rebill_estimate_cents"], int)
    assert data["attending_concurrence"] in {"PENDING", "CONCURRED", "DECLINED"}
    _assert_enum(data, "status", Cc44Status, "ConditionCode44Request")


def assert_avoidable_day(data: dict):
    _assert_common_fields(data, "AvoidableDay")
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["day_date"], str) and len(data["day_date"]) == 10
    _assert_enum(data, "barrier_code", BarrierCode, "AvoidableDay")
    assert 1 <= data["barrier_weight"] <= 5
    assert isinstance(data["is_attributed"], bool)
    _assert_enum(data, "status", AvoidableDayStatus, "AvoidableDay")


def assert_escalation_case(data: dict):
    _assert_common_fields(data, "EscalationCase")
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["tier"], int) and 0 <= data["tier"] <= 3
    assert isinstance(data["trigger_open_day_count"], int)
    assert isinstance(data["director_credit_days"], int)
    assert data["director_credit_days"] >= 0
    assert isinstance(data["effective_tier"], int) and 0 <= data["effective_tier"] <= 3
    _assert_enum(data, "status", EscalationStatus, "EscalationCase")


def assert_denial_case(data: dict):
    _assert_common_fields(data, "DenialCase")
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    _assert_enum(data, "denial_type", DenialType, "DenialCase")
    assert is_iso8601_timestamp(data.get("denied_at", ""))
    assert isinstance(data["denied_day_count"], int) and data["denied_day_count"] >= 1
    assert is_iso8601_timestamp(data.get("appeal_deadline_at", ""))
    _assert_enum(data, "status", DenialStatus, "DenialCase")


def assert_appeal_case(data: dict):
    _assert_common_fields(data, "AppealCase")
    assert is_valid_uuid(data.get("denial_id", ""))
    assert data["appeal_level"] in (1, 2)
    assert isinstance(data["argument_summary"], str) and data["argument_summary"]
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    _assert_enum(data, "status", AppealStatus, "AppealCase")


def assert_audit_event(data: dict):
    """Append-only AuditEvent (PRD §2.6): id and created_at only — both
    updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), "AuditEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "AuditEvent.created_at must be ISO 8601 UTC"
    )
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert is_valid_uuid(data.get("case_id", ""))
    assert isinstance(data["event_type"], str) and data["event_type"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_id"], str) and data["actor_id"]
    assert isinstance(data["payload_summary"], str)


def assert_timestamp_instant_equal(actual: str, expected_iso: str,
                                   context: str = "timestamp"):
    """Compare two ISO 8601 UTC timestamps as instants.

    The PRD pins the *instant* of computed deadline fields (e.g., §3.3
    `appeal_deadline_at` = denied_at + appeal_deadline_days; §3.4
    `review_due_at` = anchor + cadence hours; §3.5 `window_deadline_at` =
    decided_at + p2p_window_hours) but pins a string rendering — three
    fractional digits — only for `created_at`/`updated_at` (§2.6) and
    `api_request_timestamp` (§2.2). Computed-deadline rendering is therefore
    compared by instant, not by byte equality.
    """
    from datetime import datetime, timezone

    def _parse(s: str):
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    assert _parse(actual) == _parse(expected_iso), (
        f"{context} instant mismatch: {actual!r} != {expected_iso!r}")


def assert_certified_counters_consistent(case: dict):
    """Domain invariant (PRD §2.9): the total certified day count is the sum
    of the two per-level counters."""
    assert case["certified_day_count"] == (
        case["certified_inpatient_day_count"]
        + case["certified_observation_day_count"]
    ), (
        "certified_day_count must equal inpatient + observation splits: "
        f"{case['certified_day_count']} != {case['certified_inpatient_day_count']}"
        f" + {case['certified_observation_day_count']}"
    )
