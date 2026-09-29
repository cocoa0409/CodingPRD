"""Entity assertions and domain invariant checkers for the Nature Center API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AidStatus,
    AnimalCareStatus,
    ContactRule,
    DeliveryMode,
    DeliveryStatus,
    EducatorStatus,
    EmploymentType,
    EquityTier,
    EvaluationStatus,
    FundStatus,
    FundingStatus,
    GradeBand,
    HabitatSensitivity,
    HandlingTier,
    ManifestStatus,
    MaterialPhase,
    MaterialStatus,
    OfferingStatus,
    PermitStatus,
    SchoolStatus,
    TrailStatus,
    TrainingStatus,
    WelfarePosture,
)

_ENUM_VALUES = {
    "grade_band": [e.value for e in GradeBand],
    "delivery_mode": [e.value for e in DeliveryMode],
    "offering_status": [e.value for e in OfferingStatus],
    "material_phase": [e.value for e in MaterialPhase],
    "material_status": [e.value for e in MaterialStatus],
    "school_status": [e.value for e in SchoolStatus],
    "equity_tier": [e.value for e in EquityTier],
    "employment_type": [e.value for e in EmploymentType],
    "educator_status": [e.value for e in EducatorStatus],
    "training_status": [e.value for e in TrainingStatus],
    "handling_tier": [e.value for e in HandlingTier],
    "permit_status": [e.value for e in PermitStatus],
    "animal_care_status": [e.value for e in AnimalCareStatus],
    "welfare_posture": [e.value for e in WelfarePosture],
    "contact_rule": [e.value for e in ContactRule],
    "habitat_sensitivity": [e.value for e in HabitatSensitivity],
    "trail_status": [e.value for e in TrailStatus],
    "delivery_status": [e.value for e in DeliveryStatus],
    "funding_status": [e.value for e in FundingStatus],
    "fund_status": [e.value for e in FundStatus],
    "aid_status": [e.value for e in AidStatus],
    "manifest_status": [e.value for e in ManifestStatus],
    "evaluation_status": [e.value for e in EvaluationStatus],
}


# --- Shared identity / timestamp / version envelope --------------------------------

def assert_common_fields(data: dict, entity_label: str = "entity") -> None:
    """PRD §2.4: every mutable resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601 with three fractional digits"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO 8601 with three fractional digits"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be int"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_millisecond_timestamp(value: str, label: str = "timestamp") -> None:
    """PRD §2.4 renders instants with exactly three fractional digits."""
    assert isinstance(value, str), f"{label} must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label} must be ISO 8601 UTC: {value!r}"
    assert value.endswith("Z"), f"{label} must be UTC (trailing Z): {value!r}"
    assert "." in value, f"{label} must carry fractional digits: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"{label} must carry three fractional digits: {value!r}"


def assert_decimal_places(value, places: int, label: str = "value") -> None:
    """Assert a number is representable with at most ``places`` decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), places) == float(
        value
    ), f"{label} must carry at most {places} decimal places, got {value!r}"


def assert_integer_cents(value, label: str = "amount_cents") -> None:
    """PRD §2.7: money is always an integer count of cents, never a string."""
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{label} must be an integer number of cents, got {value!r}"


# --- Per-entity assertions ---------------------------------------------------------

def assert_program_offering(data: dict) -> None:
    assert_common_fields(data, "ProgramOffering")
    assert isinstance(data["title"], str) and data["title"]
    assert data["grade_band"] in _ENUM_VALUES["grade_band"]
    assert data["delivery_mode"] in _ENUM_VALUES["delivery_mode"]
    assert 30 <= data["duration_minutes"] <= 480
    assert 1 <= data["max_group_size"] <= 500
    assert 1 <= data["min_chaperone_ratio_students_per_adult"] <= 30
    assert_integer_cents(data["base_fee_cents_per_student"], "base_fee_cents_per_student")
    assert 0 <= data["base_fee_cents_per_student"] <= 100000
    assert isinstance(data["requires_live_animal"], bool)
    assert isinstance(data["requires_trail_segment"], bool)
    assert isinstance(data["public_contact_required"], bool)
    assert data["status"] in _ENUM_VALUES["offering_status"]
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0
    assert (
        isinstance(data["standard_alignment_count"], int)
        and data["standard_alignment_count"] >= 0
    )
    assert isinstance(data["materials_ready"], bool)
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


def assert_standard_alignment(data: dict) -> None:
    """PRD §2.4: a StandardAlignment carries only ``id`` and ``created_at``."""
    assert is_valid_uuid(data.get("id", "")), "StandardAlignment.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "StandardAlignment must not carry updated_at"
    assert "version" not in data, "StandardAlignment must not carry version"
    assert isinstance(data["standard_code"], str) and data["standard_code"]
    assert data["dimension"] in [
        "DISCIPLINARY_CORE_IDEA",
        "SCIENCE_PRACTICE",
        "CROSSCUTTING_CONCEPT",
    ]
    assert is_valid_uuid(data.get("offering_id", ""))


def assert_curriculum_material(data: dict) -> None:
    assert_common_fields(data, "CurriculumMaterial")
    assert is_valid_uuid(data.get("offering_id", ""))
    assert data["phase"] in _ENUM_VALUES["material_phase"]
    assert isinstance(data["url_slug"], str) and data["url_slug"]
    assert data["status"] in _ENUM_VALUES["material_status"]


def assert_school_partner(data: dict) -> None:
    assert_common_fields(data, "SchoolPartner")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert 0 <= data["title_i_pct"] <= 1
    assert 0 < data["distance_miles"] <= 400
    assert data["equity_tier"] in _ENUM_VALUES["equity_tier"]
    assert data["status"] in _ENUM_VALUES["school_status"]
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0
    assert_integer_cents(data["outstanding_balance_cents"], "outstanding_balance_cents")


def assert_educator(data: dict) -> None:
    assert_common_fields(data, "Educator")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["employment_type"] in _ENUM_VALUES["employment_type"]
    assert data["status"] in _ENUM_VALUES["educator_status"]
    assert data["animal_handling_tier"] in _ENUM_VALUES["handling_tier"]
    assert isinstance(data["curriculum_certified_grade_bands"], list)
    for band in data["curriculum_certified_grade_bands"]:
        assert band in _ENUM_VALUES["grade_band"]
    assert isinstance(data["delivery_load_minutes_this_week"], int)
    assert data["delivery_load_minutes_this_week"] >= 0


def assert_training_record(data: dict) -> None:
    assert_common_fields(data, "TrainingRecord")
    assert is_valid_uuid(data.get("educator_id", ""))
    assert data["track"] in ["CURRICULUM", "LIVE_ANIMAL_HANDLING"]
    assert data["status"] in _ENUM_VALUES["training_status"]
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0
    assert isinstance(data["enrolled_by_user_id"], str) and data["enrolled_by_user_id"]


def assert_permit(data: dict) -> None:
    assert_common_fields(data, "Permit")
    assert data["agency"] in ["USFWS", "STATE_DNR", "USDA"]
    assert isinstance(data["permit_number"], str) and data["permit_number"]
    assert is_iso8601_timestamp(data["valid_from"])
    assert is_iso8601_timestamp(data["valid_to"])
    assert data["status"] in _ENUM_VALUES["permit_status"]


def assert_animal_ambassador(data: dict) -> None:
    assert_common_fields(data, "AnimalAmbassador")
    assert isinstance(data["common_name"], str) and data["common_name"]
    assert isinstance(data["species_code"], str) and data["species_code"]
    assert is_valid_uuid(data.get("permit_id", ""))
    assert data["handling_tier_required"] in ["TIER_1", "TIER_2"]
    assert data["contact_rule"] in _ENUM_VALUES["contact_rule"]
    assert 0 < data["weekly_exposure_cap_minutes"] <= 1200
    assert data["status"] in _ENUM_VALUES["animal_care_status"]
    assert data["welfare_posture"] in _ENUM_VALUES["welfare_posture"]
    assert data["effective_contact_rule"] in _ENUM_VALUES["contact_rule"]
    assert isinstance(data["projected_exposure_minutes_7d"], int)
    assert data["projected_exposure_minutes_7d"] >= 0
    assert isinstance(data["realized_exposure_minutes_7d"], int)
    assert data["realized_exposure_minutes_7d"] >= 0


def assert_trail_segment(data: dict) -> None:
    assert_common_fields(data, "TrailSegment")
    assert isinstance(data["name"], str) and data["name"]
    assert 1 <= data["capacity_persons"] <= 400
    assert data["habitat_sensitivity"] in _ENUM_VALUES["habitat_sensitivity"]
    assert 1 <= data["weekly_visitor_budget_persons"] <= 5000
    assert 0 <= data["recovery_buffer_minutes"] <= 240
    assert data["status"] in _ENUM_VALUES["trail_status"]
    assert isinstance(data["visitors_this_week"], int)
    assert data["visitors_this_week"] >= 0


def assert_booking(data: dict) -> None:
    assert_common_fields(data, "Booking")
    assert is_valid_uuid(data.get("school_id", ""))
    assert is_valid_uuid(data.get("offering_id", ""))
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert 1 <= data["student_count"] <= 500
    assert 0 <= data["chaperone_count"] <= 200
    assert data["delivery_status"] in _ENUM_VALUES["delivery_status"]
    assert data["funding_status"] in _ENUM_VALUES["funding_status"]
    assert isinstance(data["required_chaperones"], int)
    assert_integer_cents(data["provisional_gross_fee_cents"], "provisional_gross_fee_cents")
    assert_integer_cents(data["net_due_cents"], "net_due_cents")
    assert data["net_due_cents"] >= 0, "net_due_cents has a lower bound of zero"


def assert_scholarship_fund(data: dict) -> None:
    assert_common_fields(data, "ScholarshipFund")
    assert isinstance(data["funder_name"], str) and data["funder_name"]
    assert 2020 <= data["fiscal_year"] <= 2100
    assert_integer_cents(data["total_cents"], "total_cents")
    assert 0 < data["total_cents"] <= 100000000
    assert 0 <= data["transport_sublimit_pct"] <= 1
    assert data["status"] in _ENUM_VALUES["fund_status"]
    for field in (
        "pending_cents",
        "committed_cents",
        "disbursed_cents",
        "transport_awarded_cents",
        "available_cents",
    ):
        assert_integer_cents(data[field], field)


def assert_aid_application(data: dict) -> None:
    assert_common_fields(data, "AidApplication")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert is_valid_uuid(data.get("fund_id", ""))
    assert_integer_cents(data["requested_scholarship_cents"], "requested_scholarship_cents")
    assert_integer_cents(data["requested_transport_cents"], "requested_transport_cents")
    assert_integer_cents(data["awarded_scholarship_cents"], "awarded_scholarship_cents")
    assert_integer_cents(data["awarded_transport_cents"], "awarded_transport_cents")
    assert data["status"] in _ENUM_VALUES["aid_status"]


def assert_equipment_manifest(data: dict) -> None:
    assert_common_fields(data, "EquipmentManifest")
    assert is_valid_uuid(data.get("booking_id", ""))
    assert isinstance(data["kit_codes"], list)
    assert 0 < data["total_weight_kg"] <= 4000
    assert data["status"] in _ENUM_VALUES["manifest_status"]
    assert isinstance(data["shortage_kit_codes"], list)


def assert_evaluation_report(data: dict) -> None:
    assert_common_fields(data, "EvaluationReport")
    assert is_valid_uuid(data.get("booking_id", ""))
    for field in (
        "teacher_score_standards_alignment",
        "teacher_score_logistics",
        "teacher_score_engagement",
    ):
        assert 1 <= data[field] <= 5, f"{field} is a 1-to-5 rating"
    assert 0 <= data["student_pre_score_avg"] <= 20
    assert 0 <= data["student_post_score_avg"] <= 20
    assert data["status"] in _ENUM_VALUES["evaluation_status"]
    assert 0.00 <= data["learning_gain_index"] <= 1.00
    assert_decimal_places(data["learning_gain_index"], 2, "learning_gain_index")


# --- Domain invariant checkers -----------------------------------------------------

def assert_fund_ledger_conserved(fund: dict) -> None:
    """PRD §3.8: ``available_cents`` is ``total_cents`` less ``pending_cents``
    less ``committed_cents`` less ``disbursed_cents``."""
    expected = (
        fund["total_cents"]
        - fund["pending_cents"]
        - fund["committed_cents"]
        - fund["disbursed_cents"]
    )
    assert fund["available_cents"] == expected, (
        "Fund ledger drifted: available_cents "
        f"{fund['available_cents']} != total {fund['total_cents']} - pending "
        f"{fund['pending_cents']} - committed {fund['committed_cents']} - disbursed "
        f"{fund['disbursed_cents']}"
    )
    for field in (
        "pending_cents",
        "committed_cents",
        "disbursed_cents",
        "transport_awarded_cents",
        "available_cents",
    ):
        assert fund[field] >= 0, f"{field} must never go negative, got {fund[field]}"


def assert_outcome_report(report: dict) -> None:
    """PRD §3.9: the funder rollup reports three-decimal indices and integer cents."""
    assert is_valid_uuid(report.get("fund_id", ""))
    for field in ("total_cents", "committed_cents", "disbursed_cents", "available_cents"):
        assert_integer_cents(report[field], field)
    assert isinstance(report["awarded_application_count"], int)
    assert isinstance(report["students_served_count"], int)
    assert_decimal_places(
        report["weighted_learning_gain_index"], 3, "weighted_learning_gain_index"
    )
    assert_decimal_places(report["tier_1_student_share_pct"], 3, "tier_1_student_share_pct")


def assert_three_decimal_string_value(value, expected: float, label: str) -> None:
    """Compare a three-decimal rollup figure without float noise."""
    assert round(float(value), 3) == round(expected, 3), (
        f"{label} expected {expected:.3f}, got {value}"
    )
