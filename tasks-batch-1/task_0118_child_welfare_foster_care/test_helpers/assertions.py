"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_REFERRAL_STATES = {"RECEIVED", "SCREENED_IN", "SCREENED_OUT", "LINKED"}
_INVESTIGATION_STATES = {"ASSIGNED", "IN_PROGRESS", "SAFE", "UNSAFE", "CONDITIONALLY_SAFE"}
_CASE_STATES = {"OPEN", "IN_PLACEMENT", "PERMANENCY_PLANNING",
                "CLOSED_REUNIFIED", "CLOSED_ADOPTED", "CLOSED_APPLA"}
_CHILD_STATES = {"IN_HOME", "REMOVED", "PLACED", "TRIAL_HOME_VISIT", "PERMANENT", "AGED_OUT"}
_LICENSE_STATES = {"PENDING", "LICENSED", "PROVISIONAL", "SUSPENDED", "EXPIRED"}
_SCREENING_STATES = {"PENDING", "CLEARED", "FLAGGED"}
_PLACEMENT_STATES = {"ACTIVE", "DISRUPTED", "ENDED_REUNIFIED", "ENDED_ADOPTED"}
_PLAN_STATES = {"DRAFT", "ACTIVE", "REVISION", "COMPLETED"}
_VISIT_STATES = {"SCHEDULED", "OCCURRED", "MISSED", "CANCELLED"}
_HEARING_STATES = {"SCHEDULED", "HELD", "CONTINUED", "VACATED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_caseworker(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["role_type"] in {"SCREENER", "INVESTIGATOR", "CASEWORKER", "LICENSING"}
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["active"], bool)


def assert_referral(data: dict):
    _assert_common(data)
    assert data["status"] in _REFERRAL_STATES, f"bad referral status {data['status']}"
    assert data["reporter_type"] in {"MANDATED", "ANONYMOUS", "RELATIVE", "SELF"}
    assert isinstance(data["child_name"], str)
    assert data["alleged_maltreatment"] in {"PHYSICAL_ABUSE", "SEXUAL_ABUSE", "NEGLECT", "EMOTIONAL_ABUSE"}
    assert isinstance(data["priority_factors"], list)


def assert_investigation(data: dict):
    _assert_common(data)
    assert data["status"] in _INVESTIGATION_STATES, f"bad investigation status {data['status']}"
    assert is_valid_uuid(data.get("referral_id", "")), "referral_id must be a UUID"
    assert is_valid_uuid(data.get("investigator_id", "")), "investigator_id must be a UUID"


def assert_case(data: dict):
    _assert_common(data)
    assert data["status"] in _CASE_STATES, f"bad case status {data['status']}"
    assert data["permanency_goal"] in {"REUNIFICATION", "ADOPTION", "APPLA"}
    assert isinstance(data["months_in_care"], int)
    assert isinstance(data["tpr_clock_breached"], bool)


def assert_child(data: dict):
    _assert_common(data)
    assert data["status"] in _CHILD_STATES, f"bad child status {data['status']}"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["age_years"], int)


def assert_foster_home(data: dict):
    _assert_common(data)
    assert data["license_status"] in _LICENSE_STATES, f"bad license_status {data['license_status']}"
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert isinstance(data["max_age_years"], int)
    assert isinstance(data["accepts_maltreatment"], list)
    assert isinstance(data["active_placement_count"], int)
    assert isinstance(data["clearances_complete"], bool)


def assert_caregiver_screening(data: dict):
    _assert_common(data)
    assert data["status"] in _SCREENING_STATES, f"bad screening status {data['status']}"
    assert is_valid_uuid(data.get("foster_home_id", "")), "foster_home_id must be a UUID"
    assert isinstance(data["disqualifying"], bool)


def assert_placement(data: dict):
    _assert_common(data)
    assert data["status"] in _PLACEMENT_STATES, f"bad placement status {data['status']}"
    assert is_valid_uuid(data.get("child_id", "")), "child_id must be a UUID"
    assert is_valid_uuid(data.get("foster_home_id", "")), "foster_home_id must be a UUID"
    assert isinstance(data["match_score"], int)


def assert_case_plan(data: dict):
    _assert_common(data)
    assert data["status"] in _PLAN_STATES, f"bad case plan status {data['status']}"
    assert is_valid_uuid(data.get("case_id", "")), "case_id must be a UUID"
    assert isinstance(data["objectives_total"], int)
    assert isinstance(data["objectives_met"], int)
    assert isinstance(data["compliance_pct"], (int, float))


def assert_visitation(data: dict):
    _assert_common(data)
    assert data["status"] in _VISIT_STATES, f"bad visitation status {data['status']}"
    assert data["supervision"] in {"SUPERVISED", "UNSUPERVISED"}


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in _HEARING_STATES, f"bad hearing status {data['status']}"
    assert data["hearing_type"] in {"SHELTER", "ADJUDICATION", "DISPOSITION", "REVIEW", "PERMANENCY", "TPR"}
