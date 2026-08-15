"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "SITE_NAME": "Site 1",
    "SITE_CODE": "S1",
    "STUDENT_NUMBER": "ST-1",
    "LEGAL_NAME": "Stu One",
    "GUARDIAN": "guard-1",
    "CYCLE_NAME": "Fall ES",
    "SCHOOL_YEAR": "2026-2027",
    "GRADE_BAND": "ELEMENTARY",
    "OPEN_ON": "2026-08-15",
    "CLOSE_ON": "2026-12-15",
    "REFERRAL_CLOSE_ON": "2026-09-30",
    "EXTERNAL_DISTRICT": "ExtDist",
    "EXTERNAL_IDENTIFIED_ON": "2026-03-01",
    "MEASURE_DATE": "2026-08-20",
    "PLACEMENT_START": "2026-09-01",
    "SPED_STARTED_ON": "2026-01-15",
}


def create_school_site_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SITE_NAME"],
        "code": DEFAULTS["SITE_CODE"],
        "pull_out_capacity": 5,
        "cluster_capacity": 5,
        "acceleration_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "student_number": DEFAULTS["STUDENT_NUMBER"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "grade_level": 3,
        "school_site_id": None,
        "demographic_group": "WHITE",
        "primary_guardian_user_id": DEFAULTS["GUARDIAN"],
    }
    defaults.update(overrides)
    return defaults


def create_bulk_enroll_payload(**overrides) -> dict:
    defaults = {
        "school_site_id": None,
        "grade_level": 3,
        "demographic_group": "WHITE",
        "count": 10,
    }
    defaults.update(overrides)
    return defaults


def create_sped_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_type": "IEP",
        "started_on": DEFAULTS["SPED_STARTED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_screening_cycle_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CYCLE_NAME"],
        "school_year": DEFAULTS["SCHOOL_YEAR"],
        "grade_band": DEFAULTS["GRADE_BAND"],
        "screening_open_on": DEFAULTS["OPEN_ON"],
        "screening_close_on": DEFAULTS["CLOSE_ON"],
        "referral_close_on": DEFAULTS["REFERRAL_CLOSE_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_cut_score_profile_payload(**overrides) -> dict:
    """P_BAND canonical profile: weights 0.40/0.30/0.20/0.10, cut 95,
    floor 88, cut_2e 90, floor_2e 82 (default measure validity 730 days)."""
    defaults = {
        "label": "P_BAND",
        "ability_weight": 0.40,
        "achievement_weight": 0.30,
        "rating_weight": 0.20,
        "portfolio_weight": 0.10,
        "cut_score": 95,
        "review_band_floor": 88,
        "cut_score_2e": 90,
        "review_band_floor_2e": 82,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "student_id": None,
        "cycle_id": None,
        "pathway": "UNIVERSAL_SCREEN",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_honor_case_payload(**overrides) -> dict:
    defaults = {
        "student_id": None,
        "cycle_id": None,
        "pathway": "TRANSFER_HONOR",
        "external_district_name": DEFAULTS["EXTERNAL_DISTRICT"],
        "external_identified_on": DEFAULTS["EXTERNAL_IDENTIFIED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_measure_score_payload(**overrides) -> dict:
    defaults = {
        "measure_type": "ABILITY",
        "percentile": 90,
        "administered_on": DEFAULTS["MEASURE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_review_payload(**overrides) -> dict:
    defaults = {
        "review_kind": "BAND_REVIEW",
        "grounds": "band review",
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {
        "verdict": "QUALIFY",
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "service_model": "PULL_OUT",
        "start_on": DEFAULTS["PLACEMENT_START"],
    }
    defaults.update(overrides)
    return defaults


def create_re_evaluation_payload(**overrides) -> dict:
    defaults = {
        "due_on": "2027-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_re_eval_conclusion_payload(**overrides) -> dict:
    defaults = {
        "growth_percentile": 80,
        "service_rating": 4,
        "teacher_rating": 5,
        "outcome": "RETAINED",
    }
    defaults.update(overrides)
    return defaults
