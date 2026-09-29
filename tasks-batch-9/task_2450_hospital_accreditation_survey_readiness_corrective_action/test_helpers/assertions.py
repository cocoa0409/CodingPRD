"""Entity assertions and domain invariant checkers."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import SEVERITY_POINTS, THRESHOLDS


# ---------------------------------------------------------------------------
# Shared shape helpers
# ---------------------------------------------------------------------------

def assert_common_fields(data: dict) -> None:
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict) -> None:
    """Append-only records carry ONLY id and created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "version" not in data, "append-only records must not carry version"
    assert "updated_at" not in data, "append-only records must not carry updated_at"


def assert_three_fractional_digits(value: str) -> None:
    """Instants render as ISO 8601 UTC with three fractional digits (PRD §2.6)."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    assert value.endswith("Z"), f"instant must be UTC and end with Z, got {value!r}"
    assert "." in value, f"instant must carry fractional digits, got {value!r}"
    fraction = value.split(".")[-1][:-1]
    assert len(fraction) == 3, f"instant must carry three fractional digits, got {value!r}"


def assert_two_decimal_places(value: float) -> None:
    assert value == round(float(value) + 0.0, 2), f"{value} must carry two decimal places"


def assert_four_decimal_places(value: float) -> None:
    assert value == round(float(value) + 0.0, 4), f"{value} must carry four decimal places"


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------

def assert_chapter(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 4
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 < float(data["weight_pct"]) <= 100
    assert int(data["evidence_min_count"]) >= 1
    for counter in (
        "standard_count",
        "mapped_standard_count",
        "evidence_complete_standard_count",
        "deficient_standard_count",
        "ppr_escalation_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, f"{counter} must be >= 0"
    assert data["readiness_flag"] in ("ON_TRACK", "AT_RISK")


def assert_standard(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["chapter_id"])
    assert isinstance(data["standard_code"], str) and len(data["standard_code"]) > 0
    assert isinstance(data["title"], str)
    assert data["risk_tier"] in (
        "DIRECT_IMPACT",
        "INDIRECT_IMPACT",
        "SITUATIONAL_DECISION_RULE",
    )
    assert data["compliance_state"] in ("UNMAPPED", "MAPPED", "EVIDENCE_COMPLETE", "DEFICIENT")
    assert data["active_owner_count"] >= 0
    assert data["validated_evidence_count"] >= 0


def assert_owner_assignment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["standard_id"])
    assert isinstance(data["owner_user_id"], str) and len(data["owner_user_id"]) > 0
    assert data["designation"] in ("PRIMARY", "SECONDARY")
    assert data["status"] in ("ACTIVE", "REVOKED")


def assert_evidence_item(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["standard_id"])
    assert data["doc_type"] in (
        "POLICY",
        "LOG",
        "TRAINING_RECORD",
        "INSPECTION_REPORT",
        "CONTRACT",
    )
    assert data["validation_state"] in (
        "DRAFT",
        "SUBMITTED",
        "VALIDATED",
        "REJECTED",
        "EXPIRED",
    )
    assert data["rejection_count"] >= 0


def assert_hospital_unit(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["unit_type"] in (
        "MED_SURG",
        "ICU",
        "ED",
        "OR",
        "BEHAVIORAL_HEALTH",
        "AMBULATORY",
    )
    assert data["bed_count"] >= 0
    assert data["posture"] in ("OPEN", "RESTRICTED", "LOCKED_FOR_SURVEY")
    assert data["open_deficiency_penalty_points"] >= 0
    assert data["scheduled_tracer_count"] >= 0
    assert 0.00 <= float(data["readiness_score"]) <= 100.00
    assert_two_decimal_places(float(data["readiness_score"]))
    assert data["readiness_band"] in (
        "READY",
        "CONDITIONAL",
        "AT_RISK",
        "NOT_READY",
        "NOT_ASSESSED",
    )


def assert_mock_tracer(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["chapter_id"])
    assert data["tracer_type"] in ("PATIENT", "SYSTEM", "INDIVIDUAL")
    assert data["state"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
    assert float(data["scored_weight"]) >= 0
    assert float(data["earned_weight"]) >= 0
    assert 0.00 <= float(data["tracer_score"]) <= 100.00
    assert_two_decimal_places(float(data["tracer_score"]))
    assert isinstance(data["contributes_to_readiness"], bool)


def assert_tracer_observation(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["mock_tracer_id"])
    assert is_valid_uuid(data["standard_id"])
    assert data["result"] in ("COMPLIANT", "PARTIAL", "NON_COMPLIANT", "NOT_APPLICABLE")
    assert float(data["weight"]) > 0
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]


def assert_rounding_session(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["unit_id"])
    assert data["round_type"] in ("LIFE_SAFETY", "ENVIRONMENT_OF_CARE")
    assert data["state"] in ("OPEN", "CLOSED")
    assert data["deficiency_count"] >= 0


def assert_deficiency_ticket(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["rounding_session_id"])
    assert is_valid_uuid(data["standard_id"])
    assert data["severity"] in ("LOW", "MODERATE", "HIGH", "IMMEDIATE_THREAT")
    assert data["state"] in ("OPEN", "IN_PROGRESS", "REMEDIATED", "ESCALATED", "VERIFIED")
    assert data["penalty_points"] == SEVERITY_POINTS[data["severity"]], (
        f"penalty_points must follow severity {data['severity']}"
    )
    assert isinstance(data["accelerated"], bool)
    assert_three_fractional_digits(data["due_at"])
    assert data["failed_verification_count"] >= 0


def assert_survey_window(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["cycle_label"], str) and data["cycle_label"]
    for instant in (
        "predicted_open_date",
        "predicted_close_date",
        "command_center_activation_allowed_from",
    ):
        assert_three_fractional_digits(data[instant])
    assert data["window_state"] in ("PROJECTED", "ELIGIBLE", "ACTIVE_SURVEY", "CLOSED")
    assert data["command_center_state"] in ("STANDBY", "ACTIVATED", "DEMOBILIZED")
    assert data["condition_level_finding_count"] >= 0
    assert isinstance(data["follow_up_required"], bool)


def assert_survey_finding(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["survey_window_id"])
    assert is_valid_uuid(data["standard_id"])
    assert is_valid_uuid(data["unit_id"])
    assert data["sampled_count"] >= 1
    assert 1 <= data["observed_noncompliance_count"] <= data["sampled_count"]
    assert isinstance(data["patient_harm_observed"], bool)
    assert_four_decimal_places(float(data["noncompliance_rate"]))
    assert data["classification"] in ("LIMITED", "PATTERN", "WIDESPREAD")
    assert data["risk_level"] in ("LOW", "MODERATE", "HIGH", "IMMEDIATE_THREAT")
    assert isinstance(data["condition_level"], bool)
    assert data["response_deadline_days"] in (
        THRESHOLDS["RESPONSE_DEADLINE_DAYS_HIGH"],
        THRESHOLDS["RESPONSE_DEADLINE_DAYS_OTHER"],
    )
    assert data["state"] in (
        "DRAFT",
        "RESPONSE_PENDING",
        "CONDITION_LEVEL_ESCALATED",
        "RESPONSE_SUBMITTED",
        "CLARIFICATION_REQUESTED",
        "FOLLOW_UP_PENDING",
        "ACCEPTED",
    )
    assert data["clarification_round_count"] >= 0
    assert data["submission_count"] >= 0


def assert_esc_submission(data: dict) -> None:
    assert_append_only_fields(data)
    assert is_valid_uuid(data["survey_finding_id"])
    assert data["submission_round"] >= 1
    assert data["decision"] in ("PENDING", "CLARIFICATION_REQUESTED", "ACCEPTED", "REJECTED")


def assert_ppr_self_assessment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["chapter_id"])
    assert isinstance(data["period_label"], str) and data["period_label"]
    for score in ("self_score", "verified_score", "gap"):
        assert_two_decimal_places(float(data[score]))
    assert isinstance(data["flagged_overstatement"], bool)
    assert data["state"] in ("SUBMITTED", "RETURNED_FOR_REASSESSMENT", "ATTESTED")
    assert isinstance(data["requires_reassessment"], bool)


def assert_unit_readiness(data: dict) -> None:
    assert is_valid_uuid(data["unit_id"])
    assert data["mode"] in ("ATTESTED", "PROJECTED")
    assert_two_decimal_places(float(data["base_score"]))
    assert data["penalty_points_applied"] >= 0
    assert data["penalty_points_applied"] <= THRESHOLDS["PENALTY_CAP"], (
        "penalty_points_applied is capped at forty"
    )
    assert_two_decimal_places(float(data["readiness_score"]))
    assert float(data["readiness_score"]) >= 0.00
    assert isinstance(data["chapter_breakdown"], list)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_band_matches_score(score: float, band: str) -> None:
    """The band is read off the four thresholds of PRD §3.3 step five."""
    score = float(score)
    if score >= THRESHOLDS["BAND_READY"]:
        expected = "READY"
    elif score >= THRESHOLDS["BAND_CONDITIONAL"]:
        expected = "CONDITIONAL"
    elif score >= THRESHOLDS["BAND_AT_RISK"]:
        expected = "AT_RISK"
    else:
        expected = "NOT_READY"
    assert band == expected, f"score {score} must land in {expected}, got {band}"


def assert_penalty_ledger(unit: dict, expected_points: int) -> None:
    assert unit["open_deficiency_penalty_points"] == expected_points, (
        f"open_deficiency_penalty_points must be {expected_points}, "
        f"got {unit['open_deficiency_penalty_points']}"
    )


def assert_posture_for_points(unit: dict) -> None:
    """Fifteen points or more restricts a unit that is not locked for survey."""
    if unit["posture"] == "LOCKED_FOR_SURVEY":
        return
    if unit["open_deficiency_penalty_points"] >= THRESHOLDS["POSTURE_RESTRICT_POINTS"]:
        assert unit["posture"] == "RESTRICTED", (
            f"{unit['open_deficiency_penalty_points']} points must restrict the unit"
        )
    else:
        assert unit["posture"] == "OPEN"


def assert_chapter_flag_consistent(chapter: dict) -> None:
    at_risk = (
        chapter["deficient_standard_count"] >= THRESHOLDS["CHAPTER_DEFICIENT_LIMIT"]
        or chapter["ppr_escalation_count"] >= THRESHOLDS["CHAPTER_PPR_ESCALATION_LIMIT"]
    )
    if at_risk:
        assert chapter["readiness_flag"] == "AT_RISK"


def assert_instant_equals(actual: Optional[str], expected: str) -> None:
    assert actual == expected, f"expected instant {expected}, got {actual}"
