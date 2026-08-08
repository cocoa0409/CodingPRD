"""Entity assertions, instant comparison helpers and domain invariant checkers."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    BARRIER_BLOCKING_TYPES,
    BARRIER_OWNER_ROLE,
    BARRIER_SLA_HOURS,
    END_OF_DAY_SUFFIX,
)

# ---------------------------------------------------------------------------
# Instant handling. An instant may legitimately be rendered as
# 2026-05-01T00:00:00Z or as 2026-05-01T00:00:00.000Z; both name the same
# moment, so every timestamp comparison in the suite goes through these.
# ---------------------------------------------------------------------------


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant with or without fractional seconds."""
    assert isinstance(value, str) and value, f"expected an instant string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def same_instant(actual: Optional[str], expected: Optional[str]) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    return parse_instant(actual) == parse_instant(expected)


def assert_same_instant(actual, expected, label: str = "instant"):
    """Compare two instants semantically, never as raw strings."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    got = parse_instant(actual)
    want = parse_instant(expected)
    assert got == want, f"{label}: expected {expected!r} ({want}), got {actual!r} ({got})"


def assert_instant_shape(value, label: str = "instant"):
    """Assert the value is a parseable ISO 8601 UTC instant."""
    assert value is not None, f"{label} must not be null"
    assert isinstance(value, str), f"{label} must be a string, got {type(value)}"
    parse_instant(value)


def end_of_day(date_str: str) -> str:
    """The instant a date-valued deadline expires."""
    return f"{date_str}{END_OF_DAY_SUFFIX}"


def add_days(date_str: str, days: int) -> str:
    """Calendar-date arithmetic in YYYY-MM-DD form."""
    base = datetime.strptime(date_str, "%Y-%m-%d")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def shift_instant(instant: str, **delta) -> str:
    """Move an instant by a timedelta and render it with three fractional digits."""
    moved = parse_instant(instant) + timedelta(**delta)
    return moved.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moved.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Common resource properties. Every persisted resource carries id, created_at,
# updated_at and version.
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict, label: str = "resource"):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID: {data.get('id')!r}"
    assert not str(data.get("id", "")).startswith(
        ("pat_", "ep_", "clm_", "rf_", "b_")
    ), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_patient(data: dict):
    assert_common_fields(data, "Patient")
    assert isinstance(data["external_mrn"], str) and data["external_mrn"]
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["primary_language"], str)
    for counter in (
        "open_episode_count",
        "lifetime_episode_count",
        "lifetime_readmission_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_facility(data: dict):
    assert_common_fields(data, "Facility")
    assert data["facility_type"] in [
        "ACUTE_HOSPITAL",
        "CRITICAL_ACCESS",
        "REHAB",
        "LTACH_FACILITY",
    ]
    assert data["network_status"] in ["IN_NETWORK", "OUT_OF_NETWORK"]


def assert_payer(data: dict):
    assert_common_fields(data, "Payer")
    assert isinstance(data["tcm_covered"], bool)
    assert 0 < float(data["tcm_rate_multiplier"]) <= 2.0
    assert 0 <= float(data["coinsurance_rate"]) <= 0.5
    assert data["contact_deadline_basis"] in ["BUSINESS_DAYS", "CALENDAR_HOURS"]


def assert_navigator(data: dict):
    assert_common_fields(data, "Navigator")
    assert 1 <= int(data["active_episode_cap"]) <= 40
    assert data["cap_policy"] in ["COUNT", "WEIGHTED"]
    assert isinstance(data["active_episode_count"], int)
    assert data["availability_status"] in ["AVAILABLE", "AT_CAP"]
    expected = (
        "AVAILABLE"
        if float(data["workload_score"]) < int(data["active_episode_cap"])
        else "AT_CAP"
    )
    assert data["availability_status"] == expected, (
        "availability_status reads AVAILABLE while workload_score is strictly "
        f"below active_episode_cap: got {data['availability_status']} for "
        f"score {data['workload_score']} / cap {data['active_episode_cap']}"
    )


def assert_referral(data: dict):
    assert_common_fields(data, "DischargeReferral")
    assert data["status"] in ["RECEIVED", "ACCEPTED", "DENIED", "WITHDRAWN"]
    assert data["stay_type"] in ["INPATIENT", "OBSERVATION"]
    assert data["admission_acuity"] in ["ELECTIVE", "URGENT", "EMERGENT"]
    assert_instant_shape(data["referred_at"], "DischargeReferral.referred_at")


def assert_episode(data: dict):
    assert_common_fields(data, "CareEpisode")
    assert data["status"] in [
        "INTAKE",
        "ACTIVE",
        "SERVICE_PERIOD_CLOSED",
        "BILLED",
        "CLOSED_READMITTED",
        "ADMIN_CLOSED",
    ]
    assert data["record_posture"] in ["OPEN", "FROZEN"]
    assert data["risk_tier"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]
    assert data["contact_status"] in [
        "NOT_STARTED",
        "IN_PROGRESS",
        "SUCCESSFUL",
        "REFUSED",
    ]
    assert data["escalation_state"] in ["NONE", "ACTIVE"]
    assert data["required_visit_complexity"] in [
        "MODERATE_COMPLEXITY",
        "HIGH_COMPLEXITY",
    ]
    assert 0 <= int(data["risk_score"]) <= 60
    assert_episode_readmission_conservation(data)
    expected_escalation = "ACTIVE" if int(data["open_red_flag_count"]) > 0 else "NONE"
    assert data["escalation_state"] == expected_escalation


def assert_episode_readmission_conservation(data: dict):
    """readmission_event_count == counted + excluded + retracted, always."""
    total = int(data["readmission_event_count"])
    parts = (
        int(data["counted_readmission_count"])
        + int(data["excluded_readmission_count"])
        + int(data["retracted_readmission_count"])
    )
    assert total == parts, (
        "readmission_event_count must equal counted + excluded + retracted: "
        f"{total} != {parts}"
    )


def assert_risk_assessment(data: dict):
    assert_common_fields(data, "RiskAssessment")
    assert data["los_variant"] in ["INPATIENT_DAYS", "OBSERVATION_HOURS"]
    assert data["risk_tier"] in ["LOW", "MODERATE", "HIGH", "SEVERE"]
    assert isinstance(data["is_current"], bool)
    for component in (
        "los_points",
        "acuity_points",
        "comorbidity_points",
        "utilization_points",
        "social_modifier_points",
        "risk_score",
    ):
        assert isinstance(data[component], int), f"{component} must be a whole number"
    assert_instant_shape(data["assessed_at"], "RiskAssessment.assessed_at")


def assert_risk_components(data: dict, **expected):
    """Assert the five component scores and the total, field by field."""
    for field, value in expected.items():
        assert data[field] == value, (
            f"RiskAssessment.{field}: expected {value}, got {data[field]}"
        )


def assert_contact_attempt(data: dict):
    assert_common_fields(data, "ContactAttempt")
    assert data["modality"] in ["PHONE", "SECURE_MESSAGE", "HOME_VISIT"]
    assert data["attempt_status"] in [
        "LOGGED",
        "CONNECTED",
        "NO_ANSWER",
        "VOICEMAIL",
        "REFUSED",
    ]
    assert 1 <= int(data["attempt_number"]) <= 4
    assert_instant_shape(data["attempted_at"], "ContactAttempt.attempted_at")


def assert_visit(data: dict):
    assert_common_fields(data, "TcmVisit")
    assert data["encounter_status"] in ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]
    assert data["documentation_status"] in ["DRAFT", "ATTESTED", "AMENDED"]
    assert data["confirmation_status"] in ["UNCONFIRMED", "CONFIRMED"]
    assert data["deadline_status"] in [
        "SCHEDULED_IN_WINDOW",
        "SCHEDULED_LATE",
        "MET",
        "MISSED",
    ]
    assert data["required_complexity"] in ["MODERATE_COMPLEXITY", "HIGH_COMPLEXITY"]
    assert data["achieved_complexity"] in [
        None,
        "MODERATE_COMPLEXITY",
        "HIGH_COMPLEXITY",
    ]
    assert isinstance(data["documented_elements"], list)
    assert isinstance(data["amendment_count"], int)


def assert_med_reconciliation(data: dict):
    assert_common_fields(data, "MedReconciliation")
    assert data["status"] in ["OPEN", "IN_REVIEW", "COMPLETED"]
    assert_medrec_conservation(data)
    assert isinstance(data["reopen_count"], int)


def assert_medrec_conservation(data: dict):
    """discrepancy_count == resolved + unresolved + deferred, after every mutation."""
    total = int(data["discrepancy_count"])
    parts = (
        int(data["resolved_count"])
        + int(data["unresolved_count"])
        + int(data["deferred_count"])
    )
    assert total == parts, (
        "discrepancy_count must equal resolved_count + unresolved_count + "
        f"deferred_count: {total} != {parts}"
    )
    assert 0 <= int(data["blocking_unresolved_count"]) <= int(data["unresolved_count"])


def assert_medrec_counters(data: dict, **expected):
    for field, value in expected.items():
        assert data[field] == value, (
            f"MedReconciliation.{field}: expected {value}, got {data[field]}"
        )
    assert_medrec_conservation(data)


def assert_discrepancy(data: dict):
    assert_common_fields(data, "MedDiscrepancy")
    assert data["discrepancy_type"] in [
        "OMISSION",
        "DUPLICATION",
        "DOSE_MISMATCH",
        "INTERACTION",
        "ALLERGY_CONFLICT",
    ]
    assert data["severity"] in ["LOW", "MODERATE", "HIGH", "CRITICAL"]
    assert data["status"] in ["UNRESOLVED", "RESOLVED", "DEFERRED"]


def assert_barrier(data: dict):
    assert_common_fields(data, "Barrier")
    assert data["barrier_type"] in BARRIER_SLA_HOURS
    assert data["status"] in [
        "OPEN",
        "ESCALATED",
        "RESOLVED",
        "WAIVED",
        "CLOSED_ADMINISTRATIVE",
    ]
    assert data["sla_hours"] == BARRIER_SLA_HOURS[data["barrier_type"]]
    assert data["owner_role"] == BARRIER_OWNER_ROLE[data["barrier_type"]]
    assert data["blocking_class"] is (data["barrier_type"] in BARRIER_BLOCKING_TYPES)
    assert_same_instant(
        data["sla_due_at"],
        shift_instant(data["opened_at"], hours=data["sla_hours"]),
        "Barrier.sla_due_at",
    )


def assert_red_flag(data: dict):
    assert_common_fields(data, "RedFlag")
    assert data["category"] in [
        "CLINICAL_SYMPTOM",
        "MEDICATION_ISSUE",
        "BARRIER_SLA_BREACH",
        "CONTACT_REFUSED",
        "VISIT_WINDOW_AT_RISK",
    ]
    assert data["tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["initial_tier"] in ["TIER_1", "TIER_2", "TIER_3"]
    assert data["status"] in [
        "RAISED",
        "ACKNOWLEDGED",
        "RESOLVED",
        "BREACHED",
        "CLOSED_ADMINISTRATIVE",
    ]
    assert 0 <= int(data["promotion_count"]) <= 2


def assert_readmission_event(data: dict):
    assert_common_fields(data, "ReadmissionEvent")
    assert data["classification"] in [
        "UNPLANNED_INPATIENT",
        "PLANNED_INPATIENT",
        "OBSERVATION_ONLY",
        "ED_TREAT_AND_RELEASE",
    ]
    assert data["status"] in ["RECORDED", "RETRACTED"]
    assert 1 <= int(data["day_index"]) <= 30
    assert data["counts_toward_rate"] is (
        data["classification"] == "UNPLANNED_INPATIENT"
    )


def assert_claim(data: dict):
    assert_common_fields(data, "TcmClaim")
    assert data["status"] in [
        "PREPARED",
        "SUBMITTED",
        "PAID",
        "DENIED",
        "APPEALED",
        "DENIED_FINAL",
        "VOIDED",
    ]
    assert str(data["payable_code"]) in ["99495", "99496"]
    assert data["payable_variant"] in ["FULL", "DOWNGRADED"]
    for cents in (
        "base_rate_cents",
        "allowed_cents",
        "coinsurance_cents",
        "net_before_withhold_cents",
        "withhold_cents",
        "net_payable_cents",
    ):
        assert isinstance(data[cents], int), f"{cents} must be a whole-cent integer"
    assert 0 <= int(data["appeal_count"]) <= 2


def assert_claim_money(data: dict, **expected):
    """Assert every money field of the claim waterfall, field by field."""
    for field, value in expected.items():
        if field == "withhold_pct":
            assert abs(float(data[field]) - value) < 1e-9, (
                f"TcmClaim.withhold_pct: expected {value}, got {data[field]}"
            )
        else:
            assert data[field] == value, (
                f"TcmClaim.{field}: expected {value}, got {data[field]}"
            )


def assert_handoff(data: dict):
    assert_common_fields(data, "HandoffRequest")
    assert data["status"] in [
        "PROPOSED",
        "ACCEPTED",
        "DECLINED",
        "EXPIRED",
        "SUPERSEDED",
    ]
    assert data["handoff_type"] in [
        "INTERNAL_NAVIGATOR",
        "COMMUNITY_PROGRAM",
        "PCP_PROGRAM",
    ]
    assert_same_instant(
        data["expires_at"],
        shift_instant(data["proposed_at"], hours=24),
        "HandoffRequest.expires_at",
    )
