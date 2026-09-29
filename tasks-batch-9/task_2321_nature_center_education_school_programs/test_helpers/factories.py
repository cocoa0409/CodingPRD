"""Payload factories — one per entity, PRD input fields only."""

from .constants import TEST_DEFAULTS


def create_program_offering_payload(**overrides) -> dict:
    payload = {
        "title": TEST_DEFAULTS["OFFERING_TITLE"],
        "grade_band": TEST_DEFAULTS["GRADE_BAND"],
        "delivery_mode": TEST_DEFAULTS["DELIVERY_MODE"],
        "duration_minutes": TEST_DEFAULTS["DURATION_MINUTES"],
        "max_group_size": TEST_DEFAULTS["MAX_GROUP_SIZE"],
        "min_chaperone_ratio_students_per_adult": TEST_DEFAULTS["MIN_CHAPERONE_RATIO"],
        "base_fee_cents_per_student": TEST_DEFAULTS["BASE_FEE_CENTS_PER_STUDENT"],
        "requires_live_animal": False,
        "requires_trail_segment": False,
        "public_contact_required": False,
    }
    payload.update(overrides)
    return payload


def create_standard_alignment_payload(**overrides) -> dict:
    payload = {"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"}
    payload.update(overrides)
    return payload


def create_curriculum_material_payload(**overrides) -> dict:
    payload = {"phase": "PRE_VISIT", "url_slug": "pond-pre"}
    payload.update(overrides)
    return payload


def create_school_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SCHOOL_NAME"],
        "district_code": TEST_DEFAULTS["DISTRICT_CODE"],
        "title_i_pct": TEST_DEFAULTS["TITLE_I_PCT"],
        "distance_miles": TEST_DEFAULTS["DISTANCE_MILES"],
    }
    payload.update(overrides)
    return payload


def create_educator_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["EDUCATOR_NAME"],
        "employment_type": "STAFF_NATURALIST",
    }
    payload.update(overrides)
    return payload


def create_training_record_payload(**overrides) -> dict:
    payload = {"track": "CURRICULUM", "grade_band": TEST_DEFAULTS["GRADE_BAND"]}
    payload.update(overrides)
    return payload


def assess_training_record_payload(**overrides) -> dict:
    payload = {"outcome": "PASS", "score": 88}
    payload.update(overrides)
    return payload


def create_permit_payload(**overrides) -> dict:
    payload = {
        "agency": TEST_DEFAULTS["PERMIT_AGENCY"],
        "permit_number": TEST_DEFAULTS["PERMIT_NUMBER"],
        "valid_from": TEST_DEFAULTS["PERMIT_VALID_FROM"],
        "valid_to": TEST_DEFAULTS["PERMIT_VALID_TO"],
    }
    payload.update(overrides)
    return payload


def create_animal_payload(permit_id: str, **overrides) -> dict:
    payload = {
        "common_name": TEST_DEFAULTS["ANIMAL_COMMON_NAME"],
        "species_code": TEST_DEFAULTS["ANIMAL_SPECIES_CODE"],
        "permit_id": permit_id,
        "handling_tier_required": "TIER_1",
        "contact_rule": "VIEW_ONLY",
        "weekly_exposure_cap_minutes": TEST_DEFAULTS["ANIMAL_CAP_MINUTES"],
    }
    payload.update(overrides)
    return payload


def create_trail_segment_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["TRAIL_NAME"],
        "capacity_persons": TEST_DEFAULTS["TRAIL_CAPACITY_PERSONS"],
        "habitat_sensitivity": "LOW",
        "weekly_visitor_budget_persons": TEST_DEFAULTS["TRAIL_WEEKLY_BUDGET_PERSONS"],
        "recovery_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(school_id: str, offering_id: str, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "offering_id": offering_id,
        "start_utc": TEST_DEFAULTS["BOOKING_START_UTC"],
        "end_utc": TEST_DEFAULTS["BOOKING_END_UTC"],
        "student_count": TEST_DEFAULTS["STUDENT_COUNT"],
        "chaperone_count": TEST_DEFAULTS["CHAPERONE_COUNT"],
    }
    payload.update(overrides)
    return payload


def assign_resources_payload(expected_booking_version: int, **overrides) -> dict:
    payload = {"expected_booking_version": expected_booking_version}
    payload.update(overrides)
    return payload


def deliver_booking_payload(**overrides) -> dict:
    payload = {"actual_student_count": 30, "actual_chaperone_count": 3}
    payload.update(overrides)
    return payload


def create_scholarship_fund_payload(**overrides) -> dict:
    payload = {
        "funder_name": TEST_DEFAULTS["FUNDER_NAME"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "total_cents": TEST_DEFAULTS["FUND_TOTAL_CENTS"],
        "transport_sublimit_pct": 0.25,
    }
    payload.update(overrides)
    return payload


def create_aid_application_payload(
    booking_id: str, fund_id: str, expected_fund_version: int, **overrides
) -> dict:
    payload = {
        "booking_id": booking_id,
        "fund_id": fund_id,
        "requested_scholarship_cents": 33300,
        "requested_transport_cents": 6500,
        "expected_fund_version": expected_fund_version,
    }
    payload.update(overrides)
    return payload


def create_equipment_manifest_payload(**overrides) -> dict:
    payload = {"kit_codes": ["KIT-PELTS", "KIT-SKULLS"], "total_weight_kg": 180}
    payload.update(overrides)
    return payload


def create_evaluation_report_payload(**overrides) -> dict:
    payload = {
        "teacher_score_standards_alignment": 5,
        "teacher_score_logistics": 4,
        "teacher_score_engagement": 5,
        "student_pre_score_avg": 8,
        "student_post_score_avg": 14,
    }
    payload.update(overrides)
    return payload
