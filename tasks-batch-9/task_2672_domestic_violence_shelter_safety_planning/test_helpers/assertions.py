"""Entity assertions and domain invariant checkers for this API."""

from datetime import datetime
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import types as t
from .constants import KEY_VOCABULARY


# --- Shared shape helpers ----------------------------------------------------


def assert_audit_triple(data: dict) -> None:
    """Every living record carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_immutable_event(data: dict) -> None:
    """An append-only event carries only id and created_at from the audit triple."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, "an immutable event must not expose updated_at"
    assert "version" not in data, "an immutable event must not expose version"


def assert_timestamp_with_millis(value: str) -> None:
    """Server-written timestamps are ISO 8601 UTC with three fractional digits."""
    assert isinstance(value, str) and value.endswith("Z"), f"not a UTC instant: {value!r}"
    assert "." in value, f"missing fractional seconds: {value!r}"
    fraction = value.split(".")[1][:-1]
    assert len(fraction) == 3, f"expected three fractional digits, got {value!r}"


def assert_same_instant(actual, expected) -> None:
    """Two ISO 8601 UTC strings denote the same instant.

    Client-supplied timestamps (`checked_on_utc`, `hearing_start_utc`,
    `hearing_end_utc`) are specified only as "ISO 8601 UTC instants"; the PRD
    fixes no serialisation for them on the way back out, so equality is compared
    as instants rather than byte for byte.
    """
    assert isinstance(actual, str), f"expected an ISO 8601 UTC instant, got {actual!r}"
    parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    parsed_expected = datetime.fromisoformat(str(expected).replace("Z", "+00:00"))
    assert parsed_actual == parsed_expected, (
        f"{actual!r} is not the same instant as {expected!r}"
    )


def assert_decimal_places(value: float, places: int) -> None:
    """A computed number must be carried at exactly the declared precision."""
    assert isinstance(value, (int, float)), f"expected a number, got {value!r}"
    assert round(float(value), places) == float(value), (
        f"{value!r} carries more than {places} decimal place(s)"
    )


def assert_whole_cents(value) -> None:
    """Money is carried in whole cents as an integer."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"a _cents field must be an integer number of cents, got {value!r}"
    )


def assert_meta_envelope(body: dict) -> None:
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), "api_request_id must start with req_"
    assert_timestamp_with_millis(meta["api_request_timestamp"])


# --- Per-entity assertions ---------------------------------------------------


def assert_staff_member(data: dict) -> None:
    assert_audit_triple(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_type"] in t.STAFF_ROLE_TYPES
    assert isinstance(data["max_caseload"], int)
    assert isinstance(data["active_caseload_count"], int)
    assert_decimal_places(data["secondary_trauma_index"], 1)
    assert data["wellness_posture"] in t.WELLNESS_POSTURES
    assert data["last_wellness_check_at"] is None or isinstance(
        data["last_wellness_check_at"], str
    )


def assert_wellness_check(data: dict) -> None:
    assert_immutable_event(data)
    assert isinstance(data["distress_scale"], int)
    assert_decimal_places(data["contribution_points"], 1)
    assert isinstance(data["debrief_completed"], bool)


def assert_client(data: dict) -> None:
    assert_audit_triple(data)
    assert isinstance(data["client_code"], str) and data["client_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["household_size"], int)
    assert isinstance(data["minor_children_count"], int)
    assert isinstance(data["accessibility_required"], bool)
    assert isinstance(data["location_confidential"], bool)
    assert data["hmis_disclosure_consent"] in t.HMIS_CONSENT_VALUES
    assert data["status"] in t.CLIENT_STATUSES
    assert data["confidentiality_posture"] in t.CONFIDENTIALITY_POSTURES
    assert data["current_risk_band"] is None or data["current_risk_band"] in t.RISK_BANDS
    if data["current_danger_score"] is not None:
        assert_decimal_places(data["current_danger_score"], 1)
    assert isinstance(data["protective_order_active"], bool)
    assert isinstance(data["resource_referral_count"], int)


def assert_hotline_call(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert data["caller_type"] in t.CALLER_TYPES
    assert isinstance(data["presenting_concerns"], str) and data["presenting_concerns"]
    assert data["status"] in t.HOTLINE_CALL_STATUSES
    assert isinstance(data["taken_by_staff_id"], str) and data["taken_by_staff_id"]
    assert isinstance(data["received_at_utc"], str)


def assert_risk_assessment(data: dict) -> None:
    assert_immutable_event(data)
    assert data["variant_applied"] in t.RISK_VARIANTS
    assert isinstance(data["corroborating_fact_count"], int)
    assert_decimal_places(data["base_subtotal"], 1)
    assert_decimal_places(data["danger_score"], 1)
    assert data["danger_score"] <= 100.0, "danger_score is capped at 100.0"
    assert data["risk_band"] in t.RISK_BANDS


def assert_safety_plan(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert data["status"] in t.SAFETY_PLAN_STATUSES
    assert_decimal_places(data["coverage_score"], 2)
    assert 0.0 <= data["coverage_score"] <= 11.10, "coverage_score cannot exceed 11.10"
    assert isinstance(data["revision_count"], int)


def assert_plan_component(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["safety_plan_id"])
    assert data["component_type"] in t.COMPONENT_TYPES
    assert data["status"] in t.COMPONENT_STATUSES
    assert_decimal_places(data["weight_effective"], 2)
    assert_decimal_places(data["subscore"], 2)


def assert_shelter(data: dict) -> None:
    assert_audit_triple(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["confidential_location"], bool)
    for key in ("nightly_rate_cents", "weekend_surcharge_cents", "child_supplement_cents",
                "settled_revenue_cents"):
        assert_whole_cents(data[key])
    assert isinstance(data["total_bed_capacity"], int)
    assert isinstance(data["available_beds"], int)
    assert data["capacity_posture"] in t.CAPACITY_POSTURES


def assert_shelter_unit(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["shelter_id"])
    assert isinstance(data["unit_label"], str) and data["unit_label"]
    assert data["unit_type"] in t.UNIT_TYPES
    assert data["status"] in t.UNIT_STATUSES
    assert_bed_ledger_invariant(data)


def assert_screening_request(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["hotline_call_id"])
    assert is_valid_uuid(data["requested_shelter_id"])
    assert data["status"] in t.SCREENING_STATUSES
    assert isinstance(data["household_size"], int)
    assert isinstance(data["minor_children_count"], int)
    assert isinstance(data["accessibility_required"], bool)
    assert isinstance(data["promoted_from_waitlist"], bool)
    assert data["waitlist_position"] is None or isinstance(data["waitlist_position"], int)


def assert_shelter_admission(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["screening_request_id"])
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["shelter_unit_id"])
    assert is_valid_uuid(data["shelter_id"])
    assert data["occupancy_status"] in t.OCCUPANCY_STATUSES
    assert data["location_security_status"] in t.LOCATION_SECURITY_STATUSES
    assert data["school_enrollment_status"] in t.SCHOOL_ENROLLMENT_STATUSES
    assert_whole_cents(data["projected_stay_cost_cents"])
    if data["settled_stay_cost_cents"] is not None:
        assert_whole_cents(data["settled_stay_cost_cents"])


def assert_protective_order_case(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert data["order_type"] in t.ORDER_TYPES
    assert data["status"] in t.PROTECTIVE_ORDER_STATUSES
    assert isinstance(data["refile_count"], int)
    assert 0 <= data["refile_count"] <= 2, "refile_count is bounded by the refile loop"


def assert_landlord_partner(data: dict) -> None:
    assert_audit_triple(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["accepts_subsidy_type"] in t.SUBSIDY_TYPES
    assert_whole_cents(data["base_incentive_cents"])
    assert_whole_cents(data["incentive_accrued_cents"])
    assert_decimal_places(data["engagement_score"], 1)
    assert data["incentive_tier"] in t.INCENTIVE_TIERS
    assert_landlord_ledger_invariant(data)


def assert_housing_referral(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert is_valid_uuid(data["landlord_partner_id"])
    assert data["program_type"] in t.PROGRAM_TYPES
    assert data["subsidy_type"] in t.SUBSIDY_TYPES
    assert data["status"] in t.REFERRAL_STATUSES
    assert isinstance(data["withdraw_count"], int)
    if data["incentive_fee_cents"] is not None:
        assert_whole_cents(data["incentive_fee_cents"])
    if data["incentive_tier_applied"] is not None:
        assert data["incentive_tier_applied"] in t.INCENTIVE_TIERS


def assert_disclosure_event(data: dict) -> None:
    assert_audit_triple(data)
    assert is_valid_uuid(data["client_id"])
    assert data["kind"] in t.DISCLOSURE_KINDS
    assert data["status"] in t.DISCLOSURE_STATUSES
    assert isinstance(data["late_filed"], bool)
    assert isinstance(data["released_field_keys"], list)
    assert isinstance(data["suppressed_field_keys"], list)
    assert_canonical_key_order(data["released_field_keys"])
    assert_canonical_key_order(data["suppressed_field_keys"])


# --- Domain invariant checkers ----------------------------------------------


def assert_bed_ledger_invariant(unit: dict) -> None:
    """bed_capacity always equals available_beds + reserved_beds + occupied_beds."""
    assert (
        unit["available_beds"] + unit["reserved_beds"] + unit["occupied_beds"]
        == unit["bed_capacity"]
    ), (
        "bed ledger broken: "
        f"{unit['available_beds']} + {unit['reserved_beds']} + {unit['occupied_beds']} "
        f"!= {unit['bed_capacity']}"
    )


def assert_unit_status_derived(unit: dict) -> None:
    """A unit's status is OCCUPIED, else HOLD, else AVAILABLE, from its counters."""
    if unit["occupied_beds"] > 0:
        expected = "OCCUPIED"
    elif unit["reserved_beds"] > 0:
        expected = "HOLD"
    else:
        expected = "AVAILABLE"
    assert unit["status"] == expected, (
        f"unit status {unit['status']} does not follow from the counters "
        f"(reserved={unit['reserved_beds']}, occupied={unit['occupied_beds']})"
    )


def assert_landlord_ledger_invariant(partner: dict) -> None:
    """units_pledged always equals units_available plus units_committed."""
    assert (
        partner["units_available"] + partner["units_committed"] == partner["units_pledged"]
    ), (
        "landlord ledger broken: "
        f"{partner['units_available']} + {partner['units_committed']} "
        f"!= {partner['units_pledged']}"
    )


def assert_canonical_key_order(keys: Iterable[str]) -> None:
    """Disclosure key arrays are always emitted in the canonical vocabulary order."""
    keys = list(keys)
    for key in keys:
        assert key in KEY_VOCABULARY, f"{key!r} is outside the field vocabulary"
    ordered = [key for key in KEY_VOCABULARY if key in keys]
    assert keys == ordered, f"keys must be in canonical vocabulary order: {keys} != {ordered}"


def assert_risk_scoring(
    assessment: dict,
    base_subtotal: float,
    escalation_multiplier: float,
    danger_score: float,
    risk_band: str,
    variant_applied: Optional[str] = None,
    corroborating_fact_count: Optional[int] = None,
) -> None:
    """Pin every stored step of the lethality arithmetic, not just the final score."""
    assert assessment["base_subtotal"] == base_subtotal
    assert assessment["escalation_multiplier"] == escalation_multiplier
    assert assessment["danger_score"] == danger_score
    assert assessment["risk_band"] == risk_band
    if variant_applied is not None:
        assert assessment["variant_applied"] == variant_applied
    if corroborating_fact_count is not None:
        assert assessment["corroborating_fact_count"] == corroborating_fact_count


def assert_component_scoring(
    component: dict, weight_effective: float, subscore: float, status: str
) -> None:
    assert component["status"] == status
    assert component["weight_effective"] == weight_effective
    assert component["subscore"] == subscore


def assert_ids_in_order(rows: List[dict], expected_ids: List[str]) -> None:
    assert [row["id"] for row in rows] == expected_ids, (
        f"row order {[row['id'] for row in rows]} != expected {expected_ids}"
    )
