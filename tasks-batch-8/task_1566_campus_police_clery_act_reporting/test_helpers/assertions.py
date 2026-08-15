"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_geography(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in [
        "ON_CAMPUS", "ON_CAMPUS_RESIDENTIAL", "NON_CAMPUS", "PUBLIC_PROPERTY",
    ]
    assert isinstance(data["is_residential_facility"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_csa(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["department"], str)
    assert data["csa_category"] in [
        "DEAN", "COACH", "RESIDENT_ADVISOR", "SECURITY_STAFF", "OTHER_OFFICIAL",
    ]
    assert data["status"] in ["PENDING_TRAINING", "ACTIVE", "LAPSED", "INACTIVE"]
    assert "certification_expires_at" in data
    assert "active_training_record_id" in data


def assert_training_record(data: dict):
    _assert_common(data)
    assert isinstance(data["csa_id"], str)
    assert is_iso8601_timestamp(data.get("completed_at", ""))
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert isinstance(data["passed"], bool)
    assert isinstance(data["training_year"], int)
    assert is_iso8601_timestamp(data.get("valid_from", ""))
    assert is_iso8601_timestamp(data.get("valid_to", ""))
    assert data["status"] in ["ACTIVE", "EXPIRED"]


def assert_referral(data: dict):
    _assert_common(data)
    assert isinstance(data["csa_id"], str)
    assert isinstance(data["geography_id"], str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data["status"] in ["RECEIVED", "FORWARDED", "LINKED", "DUPLICATE"]
    assert "forward_overdue" in data
    assert "forwarded_at" in data


def assert_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["report_number"], str) and data["report_number"].startswith("IR-")
    assert is_iso8601_timestamp(data.get("reported_at", ""))
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert isinstance(data["geography_id"], str)
    assert data["source"] in ["POLICE_DIRECT", "CSA_REFERRAL", "ANONYMOUS"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_CLASSIFICATION", "CLASSIFIED",
        "UNDER_RECLASSIFICATION", "UNFOUNDED", "WITHDRAWN",
    ]
    assert isinstance(data["is_clery_reportable"], bool)


def assert_offense_count(data: dict):
    _assert_common(data)
    assert data["offense_type"] in [
        "CRIMINAL_HOMICIDE", "SEX_OFFENSE", "ROBBERY", "AGGRAVATED_ASSAULT",
        "BURGLARY", "MOTOR_VEHICLE_THEFT", "ARSON", "DOMESTIC_VIOLENCE",
        "DATING_VIOLENCE", "STALKING", "HATE_CRIME", "LIQUOR_LAW_REFERRAL",
        "DRUG_LAW_REFERRAL", "WEAPONS_LAW_REFERRAL", "NON_CLERY",
    ]
    assert isinstance(data["victim_count"], int) and data["victim_count"] >= 1
    assert isinstance(data["referred_persons"], int) and data["referred_persons"] >= 0
    assert isinstance(data["hierarchy_rank"], int)
    assert isinstance(data["is_exempt_from_hierarchy"], bool)
    assert data["status"] in ["COUNTED", "EXCLUDED_BY_HIERARCHY", "EXCLUDED_UNFOUNDED"]


def assert_safety_alert(data: dict):
    _assert_common(data)
    assert isinstance(data["incident_id"], str)
    assert data["alert_type"] in ["TIMELY_WARNING", "EMERGENCY_NOTIFICATION"]
    assert data["status"] in [
        "PENDING_REVIEW", "DECIDED_ISSUE", "DECIDED_NO_ISSUE",
        "AUTHORIZED", "DISSEMINATED", "CLOSED",
    ]
    assert is_iso8601_timestamp(data.get("decision_deadline_at", ""))
    assert isinstance(data["decision_overdue"], bool)
    assert isinstance(data["dissemination_overdue"], bool)


def assert_log_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["entry_number"], str) and data["entry_number"].startswith("CL-")
    assert isinstance(data["incident_id"], str)
    assert isinstance(data["nature"], str)
    assert is_iso8601_timestamp(data.get("date_reported", ""))
    assert is_iso8601_timestamp(data.get("date_occurred", ""))
    assert data["disposition"] in [
        "OPEN", "INVESTIGATION_PENDING", "CLEARED_BY_ARREST",
        "CLEARED_EXCEPTIONAL", "UNFOUNDED",
    ]
    assert isinstance(data["entry_overdue"], bool)
    assert isinstance(data["disposition_update_overdue"], bool)
    assert isinstance(data["is_public"], bool)


def assert_inspection_request(data: dict):
    _assert_common(data)
    assert isinstance(data["requester_name"], str)
    assert isinstance(data["requester_contact"], str)
    assert isinstance(data["from_date"], str)
    assert isinstance(data["to_date"], str)
    assert is_iso8601_timestamp(data.get("requested_at", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert is_iso8601_timestamp(data.get("provisional_due_at", ""))
    assert isinstance(data["is_overdue"], bool)
    assert data["status"] in ["PENDING", "FULFILLED"]


def assert_asr(data: dict):
    _assert_common(data)
    assert isinstance(data["report_year"], int)
    assert isinstance(data["statistics_version"], int) and data["statistics_version"] >= 0
    assert isinstance(data["final_compile_done"], bool)
    assert isinstance(data["statistics_stale"], bool)
    assert data["status"] in [
        "COLLECTING", "UNDER_REVIEW", "PUBLISHED", "UNDER_AMENDMENT", "REPUBLISHED",
    ]


def assert_statistic_line(data: dict):
    _assert_common(data)
    assert isinstance(data["report_id"], str)
    assert isinstance(data["statistics_version"], int)
    assert data["compilation_variant"] in ["PROVISIONAL", "FINAL"]
    assert isinstance(data["offense_type"], str)
    assert data["geography_column"] in [
        "ON_CAMPUS", "ON_CAMPUS_RESIDENTIAL", "NON_CAMPUS", "PUBLIC_PROPERTY",
    ]
    assert isinstance(data["count"], int) and data["count"] >= 0
    assert isinstance(data["referred_persons_count"], int) and data["referred_persons_count"] >= 0
    assert data["status"] in ["CURRENT", "SUPERSEDED"]


def assert_fire_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["geography_id"], str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))
    assert data["cause_category"] in [
        "COOKING", "ELECTRICAL", "HEATING", "SMOKING_MATERIALS",
        "OPEN_FLAME", "INTENTIONAL", "UNDETERMINED",
    ]
    assert isinstance(data["injuries"], int) and data["injuries"] >= 0
    assert isinstance(data["deaths"], int) and data["deaths"] >= 0
    assert isinstance(data["estimated_damage_dollars"], (int, float))
    assert data["estimated_damage_dollars"] >= 0
    assert "final_damage_dollars" in data
    assert data["status"] in ["REPORTED", "FINALIZED", "UNDER_ADJUSTMENT"]


def assert_fire_report(data: dict):
    _assert_common(data)
    assert isinstance(data["report_year"], int)
    assert isinstance(data["total_fires"], int) and data["total_fires"] >= 0
    assert isinstance(data["total_injuries"], int) and data["total_injuries"] >= 0
    assert isinstance(data["total_deaths"], int) and data["total_deaths"] >= 0
    assert isinstance(data["total_damage_dollars"], int) and data["total_damage_dollars"] >= 0
    assert isinstance(data["provisional_total_damage_dollars"], (int, float))
    assert isinstance(data["totals_stale"], bool)
    assert data["status"] in [
        "DRAFT", "COMPILED", "PUBLISHED", "UNDER_AMENDMENT", "REPUBLISHED",
    ]


def assert_program_review(data: dict):
    _assert_common(data)
    assert isinstance(data["scope_year_start"], int)
    assert isinstance(data["scope_year_end"], int)
    assert data["scope_year_end"] >= data["scope_year_start"]
    assert isinstance(data["penalty_score"], int) and data["penalty_score"] >= 0
    assert isinstance(data["escalated"], bool)
    assert isinstance(data["open_action_count"], int) and data["open_action_count"] >= 0
    assert data["status"] in [
        "OPENED", "FINDINGS_ISSUED", "CORRECTIVE_ACTION", "UNDER_VERIFICATION", "CLOSED",
    ]


def assert_corrective_action(data: dict):
    _assert_common(data)
    assert isinstance(data["review_id"], str)
    assert isinstance(data["finding_code"], str)
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert isinstance(data["description"], str)
    assert isinstance(data["due_date"], str)
    assert isinstance(data["is_repeat_finding"], bool)
    assert isinstance(data["weight"], int) and data["weight"] > 0
    assert isinstance(data["rejection_count"], int) and data["rejection_count"] >= 0
    assert data["status"] in ["OPEN", "SUBMITTED", "VERIFIED"]
