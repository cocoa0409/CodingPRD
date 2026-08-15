"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "FRAMEWORK_CODE": "FW-MATH-K5",
    "SUBJECT_AREA": "MATHEMATICS",
    "GRADE_BAND": "K_5",
    "STANDARDS_REQUIRED_COUNT": 1,
    "EFFECTIVE_YEAR": 2026,
    "SCHOOL_YEAR_START": 2027,
    "DISTRICT_ENROLLMENT": 100,
    "MATERIAL_TITLE": "Math Text",
    "PUBLISHER_NAME": "PubA",
    "SCHOOL_CODE": "SCH-A",
    "STARTS_ON": "2026-08-01",
    "ENDS_ON": "2026-08-15",
    "TEACHER_COUNT": 1,
    "STANDARD_CODE": "S1",
    "COVERAGE_RATING": "FULL",
    "REVIEW_SCORE": 4,
    "PRINT_UNIT_PRICE": 10.00,
    "PRINT_QUANTITY": 10,
    "DIGITAL_SEAT_RATE": 0,
    "DIGITAL_SEAT_COUNT": 0,
    "TRAINING_SESSIONS": 0,
    "LICENSE_YEARS": 0,
    "CLASSROOM_LABEL": "RM-101",
    "DO_QUANTITY": 1,
    "NEED_PRIORITY": 1,
    "SR_TITLE": "Novel Set",
    "SR_ESTIMATED_COST": 100.00,
    "CHALLENGE_GROUNDS": "CONTENT_OBJECTION",
    "VOTE": "UPHOLD",
    "APPROPRIATION_AMOUNT": 1000,
}


def create_framework_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["FRAMEWORK_CODE"],
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "grade_band": DEFAULTS["GRADE_BAND"],
        "standards_required_count": DEFAULTS["STANDARDS_REQUIRED_COUNT"],
        "effective_year": DEFAULTS["EFFECTIVE_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "grade_band": DEFAULTS["GRADE_BAND"],
        "school_year_start": DEFAULTS["SCHOOL_YEAR_START"],
        "district_enrollment": DEFAULTS["DISTRICT_ENROLLMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_material_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["MATERIAL_TITLE"],
        "publisher_name": DEFAULTS["PUBLISHER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_alignment_payload(**overrides) -> dict:
    defaults = {
        "standard_code": DEFAULTS["STANDARD_CODE"],
        "coverage_rating": DEFAULTS["COVERAGE_RATING"],
    }
    defaults.update(overrides)
    return defaults


def create_pilot_payload(**overrides) -> dict:
    defaults = {
        "school_code": DEFAULTS["SCHOOL_CODE"],
        "starts_on": DEFAULTS["STARTS_ON"],
        "ends_on": DEFAULTS["ENDS_ON"],
        "teacher_count": DEFAULTS["TEACHER_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(**overrides) -> dict:
    defaults = {
        "pedagogy_score": DEFAULTS["REVIEW_SCORE"],
        "alignment_score": DEFAULTS["REVIEW_SCORE"],
        "usability_score": DEFAULTS["REVIEW_SCORE"],
        "equity_score": DEFAULTS["REVIEW_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {
        "publisher_name": DEFAULTS["PUBLISHER_NAME"],
        "print_unit_price": DEFAULTS["PRINT_UNIT_PRICE"],
        "print_quantity": DEFAULTS["PRINT_QUANTITY"],
        "digital_seat_rate": DEFAULTS["DIGITAL_SEAT_RATE"],
        "digital_seat_count": DEFAULTS["DIGITAL_SEAT_COUNT"],
        "training_sessions": DEFAULTS["TRAINING_SESSIONS"],
        "license_years": DEFAULTS["LICENSE_YEARS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(**overrides) -> dict:
    defaults = {
        "print_quantity": DEFAULTS["PRINT_QUANTITY"],
        "digital_seat_count": DEFAULTS["DIGITAL_SEAT_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_order_payload(**overrides) -> dict:
    defaults = {
        "school_code": DEFAULTS["SCHOOL_CODE"],
        "classroom_label": DEFAULTS["CLASSROOM_LABEL"],
        "quantity": DEFAULTS["DO_QUANTITY"],
        "need_priority": DEFAULTS["NEED_PRIORITY"],
    }
    defaults.update(overrides)
    return defaults


def create_supplemental_request_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["SR_TITLE"],
        "publisher_name": DEFAULTS["PUBLISHER_NAME"],
        "estimated_cost": DEFAULTS["SR_ESTIMATED_COST"],
        "subject_area": DEFAULTS["SUBJECT_AREA"],
        "grade_band": DEFAULTS["GRADE_BAND"],
        "school_code": DEFAULTS["SCHOOL_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_challenge_payload(**overrides) -> dict:
    defaults = {
        "target_type": "MATERIAL",
        "grounds": DEFAULTS["CHALLENGE_GROUNDS"],
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {"vote": DEFAULTS["VOTE"]}
    defaults.update(overrides)
    return defaults


def create_appropriation_payload(**overrides) -> dict:
    defaults = {"amount": DEFAULTS["APPROPRIATION_AMOUNT"]}
    defaults.update(overrides)
    return defaults
