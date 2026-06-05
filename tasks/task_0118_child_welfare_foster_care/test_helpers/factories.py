"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "REPORTER_TYPE": "MANDATED",
    "CHILD_NAME": "Test Child",
    "ALLEGED_MALTREATMENT": "PHYSICAL_ABUSE",
    "PRIORITY_FACTORS": ["INJURY_VISIBLE", "PRIOR_REPORT"],  # -> base 40 + 15 + 10 + mandated 8 = 73 (SCREENED_IN)
    "DOB": "2016-01-01T00:00:00Z",
    "HOME_NAME": "Test Foster Home",
    "BED_CAPACITY": 1,
    "MAX_AGE_YEARS": 18,
    "ACCEPTS_MALTREATMENT": ["PHYSICAL_ABUSE"],
    "MEMBER_NAME": "Test Household Member",
    "SUPERVISION": "SUPERVISED",
    "REQUIRED_VISITS_PER_MONTH": 4,
    "OBJECTIVES_TOTAL": 5,
    "HEARING_TYPE": "REVIEW",
}


def create_caseworker_payload(role_type="CASEWORKER", **overrides) -> dict:
    defaults = {
        "full_name": "Test Worker",
        "role_type": role_type,
        "email": "worker@x.gov",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "reporter_type": DEFAULTS["REPORTER_TYPE"],
        "child_name": DEFAULTS["CHILD_NAME"],
        "alleged_maltreatment": DEFAULTS["ALLEGED_MALTREATMENT"],
        "priority_factors": list(DEFAULTS["PRIORITY_FACTORS"]),
    }
    defaults.update(overrides)
    return defaults


def create_investigation_payload(referral_id, investigator_id, **overrides) -> dict:
    defaults = {
        "referral_id": referral_id,
        "investigator_id": investigator_id,
    }
    defaults.update(overrides)
    return defaults


def decision_payload(safety_factors, protective_capacity, **overrides) -> dict:
    defaults = {
        "safety_factors": list(safety_factors),
        "protective_capacity": protective_capacity,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(investigation_id, **overrides) -> dict:
    defaults = {"investigation_id": investigation_id}
    defaults.update(overrides)
    return defaults


def create_child_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "full_name": DEFAULTS["CHILD_NAME"],
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_foster_home_payload(licensing_worker_id, **overrides) -> dict:
    defaults = {
        "licensing_worker_id": licensing_worker_id,
        "home_name": DEFAULTS["HOME_NAME"],
        "bed_capacity": DEFAULTS["BED_CAPACITY"],
        "max_age_years": DEFAULTS["MAX_AGE_YEARS"],
        "accepts_maltreatment": list(DEFAULTS["ACCEPTS_MALTREATMENT"]),
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(foster_home_id, **overrides) -> dict:
    defaults = {
        "foster_home_id": foster_home_id,
        "member_name": DEFAULTS["MEMBER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(child_id, foster_home_id, expected_foster_home_version, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "foster_home_id": foster_home_id,
        "expected_foster_home_version": expected_foster_home_version,
    }
    defaults.update(overrides)
    return defaults


def license_payload(expected_foster_home_version, **overrides) -> dict:
    defaults = {"expected_foster_home_version": expected_foster_home_version}
    defaults.update(overrides)
    return defaults


def create_case_plan_payload(case_id, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "required_visits_per_month": DEFAULTS["REQUIRED_VISITS_PER_MONTH"],
        "objectives_total": DEFAULTS["OBJECTIVES_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def objectives_payload(objectives_met, **overrides) -> dict:
    defaults = {"objectives_met": objectives_met}
    defaults.update(overrides)
    return defaults


def create_visitation_payload(case_plan_id, child_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "case_plan_id": case_plan_id,
        "child_id": child_id,
        "supervision": DEFAULTS["SUPERVISION"],
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(case_id, hearing_type, scheduled_at, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "hearing_type": hearing_type,
        "scheduled_at": scheduled_at,
    }
    defaults.update(overrides)
    return defaults


def hold_payload(ruling, **overrides) -> dict:
    defaults = {"ruling": ruling}
    defaults.update(overrides)
    return defaults


def reschedule_payload(scheduled_at, **overrides) -> dict:
    defaults = {"scheduled_at": scheduled_at}
    defaults.update(overrides)
    return defaults
