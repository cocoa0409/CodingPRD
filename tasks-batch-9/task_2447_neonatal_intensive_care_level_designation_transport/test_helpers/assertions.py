"""Domain assertions: resource shape checks and the invariants the PRD states.

The invariant helpers exist so a test can state the rule once — the bed ledger,
the milk three-way split, the effective level, the census posture band — instead
of re-deriving arithmetic in every test body.
"""

import math
from decimal import Decimal
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import (
    assert_timestamp_format,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import CONSTRAINED_POSTURE_FRACTION
from .types import LEVEL_RANKS

# ---------------------------------------------------------------------------
# Generic shape helpers
# ---------------------------------------------------------------------------


def assert_common_fields(resource: Dict[str, Any]) -> None:
    """Every versioned resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])
    assert_timestamp_format(resource["updated_at"])
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1


def assert_immutable_resource_fields(resource: Dict[str, Any]) -> None:
    """A designation standard is immutable, so it carries only id and created_at."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert_timestamp_format(resource["created_at"])
    assert "updated_at" not in resource
    assert "version" not in resource


def assert_enum_value(value: Any, allowed) -> None:
    allowed_values = {member.value if hasattr(member, "value") else member for member in allowed}
    assert value in allowed_values, f"{value!r} is not one of {sorted(allowed_values)}"


def assert_decimal_places(value: Any, places: int) -> None:
    """A numeric field is reported with at most `places` decimal places."""
    assert value is not None
    quantum = Decimal(1).scaleb(-places)
    as_decimal = Decimal(str(value))
    assert as_decimal == as_decimal.quantize(quantum), (
        f"{value!r} is not reported to {places} decimal places"
    )


def assert_close(actual: Any, expected: float, tolerance: float = 1e-9) -> None:
    assert actual is not None
    assert math.isclose(float(actual), float(expected), abs_tol=tolerance), (
        f"expected {expected}, got {actual}"
    )


def assert_nullable_timestamp(value: Optional[str]) -> None:
    if value is not None:
        assert is_iso8601_timestamp(value), f"not an ISO-8601 instant: {value!r}"


# ---------------------------------------------------------------------------
# NicuUnit invariants
# ---------------------------------------------------------------------------


def assert_bed_ledger_balanced(unit: Dict[str, Any]) -> None:
    """available = staffed_bed_target + escalation - occupied - held, never clamped."""
    expected = (
        unit["staffed_bed_target"]
        + unit["escalation_bed_count"]
        - unit["occupied_bed_count"]
        - unit["held_bed_count"]
    )
    assert unit["available_bed_count"] == expected, (
        "bed ledger does not balance: "
        f"target={unit['staffed_bed_target']} escalation={unit['escalation_bed_count']} "
        f"occupied={unit['occupied_bed_count']} held={unit['held_bed_count']} "
        f"available={unit['available_bed_count']} (expected {expected})"
    )


def expected_census_posture(unit: Dict[str, Any]) -> str:
    available = unit["available_bed_count"]
    if available <= 0:
        return "CLOSED"
    if available <= math.floor(unit["staffed_bed_target"] * CONSTRAINED_POSTURE_FRACTION):
        return "CONSTRAINED"
    return "OPEN"


def assert_census_posture_consistent(unit: Dict[str, Any]) -> None:
    expected = expected_census_posture(unit)
    assert unit["census_posture"] == expected, (
        f"posture {unit['census_posture']} disagrees with the ledger (expected {expected})"
    )


def assert_effective_level_consistent(unit: Dict[str, Any]) -> None:
    """effective_level is the lower-ranking of designated_level and capability_level."""
    designated = unit["designated_level"]
    capability = unit["capability_level"]
    expected = designated if LEVEL_RANKS[designated] <= LEVEL_RANKS[capability] else capability
    assert unit["effective_level"] == expected, (
        f"effective_level {unit['effective_level']} is not the lower of "
        f"{designated} and {capability}"
    )


def assert_unit_counts(
    unit: Dict[str, Any],
    occupied: Optional[int] = None,
    held: Optional[int] = None,
    available: Optional[int] = None,
    escalation: Optional[int] = None,
    posture: Optional[str] = None,
) -> None:
    if occupied is not None:
        assert unit["occupied_bed_count"] == occupied
    if held is not None:
        assert unit["held_bed_count"] == held
    if available is not None:
        assert unit["available_bed_count"] == available
    if escalation is not None:
        assert unit["escalation_bed_count"] == escalation
    if posture is not None:
        assert unit["census_posture"] == posture
    assert_bed_ledger_balanced(unit)
    assert_census_posture_consistent(unit)


def assert_nicu_unit(unit: Dict[str, Any]) -> None:
    assert_common_fields(unit)
    assert isinstance(unit["name"], str) and unit["name"]
    assert_enum_value(unit["hospital_type"], {"REGIONAL_CENTER", "COMMUNITY"})
    assert_enum_value(
        unit["designation_status"], {"PROVISIONAL", "DESIGNATED", "CONDITIONAL", "SUSPENDED"}
    )
    assert_enum_value(unit["census_posture"], {"OPEN", "CONSTRAINED", "CLOSED"})
    assert_enum_value(unit["quality_flag"], {"WITHIN_BENCHMARK", "ABOVE_BENCHMARK"})
    for level_field in ("designated_level", "capability_level", "effective_level"):
        assert_enum_value(unit[level_field], set(LEVEL_RANKS))
    assert isinstance(unit["staffing_compliant"], bool)
    assert isinstance(unit["equipment_compliant"], bool)
    assert isinstance(unit["transport_capable"], bool)
    assert isinstance(unit["required_nurse_count"], int)
    assert isinstance(unit["deferral_queue_depth"], int)
    assert_bed_ledger_balanced(unit)
    assert_census_posture_consistent(unit)
    assert_effective_level_consistent(unit)


# ---------------------------------------------------------------------------
# DesignationStandard / StaffCredential / EquipmentAsset
# ---------------------------------------------------------------------------


def assert_designation_standard(standard: Dict[str, Any]) -> None:
    assert_immutable_resource_fields(standard)
    assert_enum_value(standard["level"], set(LEVEL_RANKS))
    assert isinstance(standard["required_credential_codes"], list)
    assert isinstance(standard["required_equipment_codes"], list)
    assert isinstance(standard["transport_capability_required"], bool)


def assert_staff_credential(credential: Dict[str, Any]) -> None:
    assert_common_fields(credential)
    assert is_valid_uuid(credential["unit_id"])
    assert_enum_value(credential["status"], {"VALID", "EXPIRED", "REVOKED"})
    assert_nullable_timestamp(credential.get("revoked_at"))


def assert_equipment_asset(asset: Dict[str, Any]) -> None:
    assert_common_fields(asset)
    assert is_valid_uuid(asset["unit_id"])
    assert_enum_value(asset["status"], {"IN_SERVICE", "SERVICE_DUE", "OUT_OF_SERVICE"})
    assert_nullable_timestamp(asset.get("out_of_service_at"))
    assert_nullable_timestamp(asset.get("decontamination_ready_at"))
    assert_timestamp_format(asset["next_service_due_at"])


# ---------------------------------------------------------------------------
# DesignationReview
# ---------------------------------------------------------------------------


def assert_designation_review(review: Dict[str, Any]) -> None:
    assert_common_fields(review)
    assert is_valid_uuid(review["unit_id"])
    assert_enum_value(
        review["status"], {"DRAFT", "SUBMITTED", "RETURNED", "VERIFIED", "CERTIFIED", "DENIED"}
    )
    assert_enum_value(review["requested_level"], set(LEVEL_RANKS))
    for subscore in ("staffing_subscore", "equipment_subscore", "volume_subscore", "compliance_score"):
        assert_decimal_places(review[subscore], 2)
    if review.get("denial_basis") is not None:
        assert_enum_value(review["denial_basis"], {"ROUNDS_EXHAUSTED", "SCORE_BELOW_FLOOR"})


# ---------------------------------------------------------------------------
# Referral / BedReservation
# ---------------------------------------------------------------------------


def assert_referral(referral: Dict[str, Any]) -> None:
    assert_common_fields(referral)
    assert is_valid_uuid(referral["referring_unit_id"])
    assert is_valid_uuid(referral["receiving_unit_id"])
    assert_enum_value(
        referral["referral_kind"], {"INBOUND_NEONATAL", "MATERNAL_ANTENATAL", "BACK_TRANSFER"}
    )
    assert_enum_value(
        referral["status"],
        {
            "PENDING",
            "INFO_REQUESTED",
            "ACCEPTED",
            "DEFERRED",
            "DECLINED",
            "DIVERTED",
            "WITHDRAWN",
            "REVOKED",
            "SUPERSEDED",
            "COMPLETED",
        },
    )
    for level_field in ("current_support_level", "anticipated_need_level", "required_level"):
        assert_enum_value(referral[level_field], set(LEVEL_RANKS))
    assert_enum_value(referral["level_basis"], {"CURRENT_SUPPORT", "ANTICIPATED_NEED"})
    assert_decimal_places(referral["triage_priority"], 2)
    assert isinstance(referral["info_request_rounds"], int)
    assert isinstance(referral["maternal_transfer_preferred"], bool)


def assert_bed_reservation(reservation: Dict[str, Any]) -> None:
    assert_common_fields(reservation)
    assert is_valid_uuid(reservation["unit_id"])
    assert is_valid_uuid(reservation["referral_id"])
    assert_enum_value(reservation["bed_class"], {"STAFFED", "ESCALATION"})
    assert_enum_value(reservation["status"], {"HELD", "OCCUPIED", "RELEASED", "EXPIRED"})
    assert_timestamp_format(reservation["held_at"])
    assert_timestamp_format(reservation["expires_at"])


# ---------------------------------------------------------------------------
# TransportRun
# ---------------------------------------------------------------------------


def assert_transport_run(run: Dict[str, Any]) -> None:
    assert_common_fields(run)
    assert is_valid_uuid(run["reservation_id"])
    assert is_valid_uuid(run["receiving_unit_id"])
    assert is_valid_uuid(run["isolette_asset_id"])
    assert_enum_value(run["mode"], {"GROUND", "ROTOR_WING", "FIXED_WING"})
    assert_enum_value(
        run["status"],
        {
            "ACTIVATED",
            "GROUND_ROLLING",
            "AIR_LAUNCHED",
            "ON_SCENE",
            "STABILIZING",
            "EN_ROUTE",
            "ARRIVED",
            "ABORTED",
        },
    )
    assert isinstance(run["crew_composition"], list)
    assert isinstance(run["weather_minimums_met"], bool)
    assert isinstance(run["stabilization_bundle_complete"], bool)
    assert_timestamp_format(run["depart_at"])
    assert_timestamp_format(run["planned_return_at"])
    assert_nullable_timestamp(run.get("arrived_at"))
    if run.get("stabilization_score") is not None:
        assert_decimal_places(run["stabilization_score"], 2)


# ---------------------------------------------------------------------------
# Admission / MilkBatch
# ---------------------------------------------------------------------------


def assert_admission(admission: Dict[str, Any]) -> None:
    assert_common_fields(admission)
    assert is_valid_uuid(admission["unit_id"])
    assert is_valid_uuid(admission["referral_id"])
    assert_enum_value(
        admission["care_status"],
        {
            "ADMITTED",
            "STABILIZED",
            "BACK_TRANSFER_READY",
            "BACK_TRANSFER_REQUIRED",
            "TRANSFERRED",
            "DISCHARGED",
            "DECEASED",
        },
    )
    assert_enum_value(
        admission["infection_status"],
        {"SURVEILLANCE_CLEAR", "SUSPECTED", "CONFIRMED_CLABSI", "RESOLVED"},
    )
    assert_enum_value(admission["current_care_level"], set(LEVEL_RANKS))
    assert isinstance(admission["high_risk_graduate"], bool)
    assert_decimal_places(admission["developmental_bundle_score"], 2)
    assert_nullable_timestamp(admission.get("infection_confirmed_at"))
    assert_nullable_timestamp(admission.get("discharged_at"))


def assert_milk_ledger_balanced(batch: Dict[str, Any]) -> None:
    """volume_ml always equals administered_ml plus discarded_ml plus remaining_ml."""
    total = batch["administered_ml"] + batch["discarded_ml"] + batch["remaining_ml"]
    assert_close(total, batch["volume_ml"], tolerance=1e-6)


def assert_milk_batch(batch: Dict[str, Any]) -> None:
    assert_common_fields(batch)
    assert is_valid_uuid(batch["admission_id"])
    assert_enum_value(batch["donor_type"], {"MOTHERS_OWN", "DONOR_PASTEURIZED"})
    assert_enum_value(
        batch["status"],
        {
            "RECEIVED",
            "VERIFIED",
            "PARTIALLY_ADMINISTERED",
            "ADMINISTERED",
            "QUARANTINED",
            "DISCARDED",
        },
    )
    assert_timestamp_format(batch["expressed_at"])
    assert_timestamp_format(batch["expires_at"])
    assert_milk_ledger_balanced(batch)


# ---------------------------------------------------------------------------
# SurgeEscalation / SurveillanceReport / FollowUpEnrollment
# ---------------------------------------------------------------------------


def assert_surge_escalation(escalation: Dict[str, Any]) -> None:
    assert_common_fields(escalation)
    assert is_valid_uuid(escalation["unit_id"])
    assert_enum_value(
        escalation["status"], {"REQUESTED", "ACTIVE", "DENIED", "EXPIRED", "STOOD_DOWN"}
    )
    if escalation.get("escalation_tier") is not None:
        assert_enum_value(escalation["escalation_tier"], {"TIER_1", "TIER_2", "TIER_3"})
    if escalation.get("census_ratio_at_request") is not None:
        assert_decimal_places(escalation["census_ratio_at_request"], 4)
    assert_timestamp_format(escalation["effective_from"])
    assert_timestamp_format(escalation["effective_to"])


def assert_surveillance_report(report: Dict[str, Any]) -> None:
    assert_common_fields(report)
    assert is_valid_uuid(report["unit_id"])
    assert_enum_value(report["status"], {"DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"})
    assert_enum_value(report["variant_applied"], {"CRUDE", "DEVICE_ADJUSTED"})
    assert_enum_value(report["data_completeness_flag"], {"COMPLETE", "DENOMINATOR_MISSING"})
    assert_enum_value(report["network_benchmark_flag"], {"WITHIN_BENCHMARK", "ABOVE_BENCHMARK"})
    assert_decimal_places(report["crude_clabsi_rate"], 2)
    assert_decimal_places(report["device_adjusted_clabsi_rate"], 2)
    assert_decimal_places(report["birth_weight_risk_weight"], 4)


def assert_follow_up_enrollment(enrollment: Dict[str, Any]) -> None:
    assert_common_fields(enrollment)
    assert is_valid_uuid(enrollment["admission_id"])
    assert is_valid_uuid(enrollment["clinic_unit_id"])
    assert_enum_value(
        enrollment["status"],
        {"ENROLLED", "SCHEDULED", "ATTENDED", "NO_SHOW", "LOST_TO_FOLLOWUP"},
    )
    assert_enum_value(enrollment["risk_tier"], {"HIGH", "MODERATE"})
    assert_enum_value(
        enrollment["eligibility_basis"],
        {
            "BW_UNDER_1500",
            "GA_UNDER_32",
            "HIE_COOLED",
            "SURGICAL_NEC",
            "VENT_OVER_7D",
            "NOT_ELIGIBLE",
        },
    )
    assert_timestamp_format(enrollment["appointment_window_start"])
    assert_timestamp_format(enrollment["appointment_window_end"])


# ---------------------------------------------------------------------------
# Sweep response
# ---------------------------------------------------------------------------


def assert_sweep_result(
    result: Dict[str, Any],
    holds_expired: Optional[int] = None,
    escalations_expired: Optional[int] = None,
    enrollments_lapsed: Optional[int] = None,
    referrals_promoted: Optional[int] = None,
    units_touched: Optional[int] = None,
) -> None:
    for key in (
        "holds_expired",
        "escalations_expired",
        "enrollments_lapsed",
        "referrals_promoted",
        "units_touched",
    ):
        assert key in result, f"sweep result is missing {key}"
        assert isinstance(result[key], int)
    expectations = {
        "holds_expired": holds_expired,
        "escalations_expired": escalations_expired,
        "enrollments_lapsed": enrollments_lapsed,
        "referrals_promoted": referrals_promoted,
        "units_touched": units_touched,
    }
    for key, expected in expectations.items():
        if expected is not None:
            assert result[key] == expected, f"{key}: expected {expected}, got {result[key]}"
