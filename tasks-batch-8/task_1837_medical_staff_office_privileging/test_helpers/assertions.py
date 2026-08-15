"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), (
        f"version must be an int, got {data.get('version')!r}")


def assert_member(data: dict):
    """MedicalStaffMember response structure."""
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["npdb_subject_id"], str) and data["npdb_subject_id"]
    assert isinstance(data["primary_specialty_code"], str)
    assert data["membership_status"] in (
        "APPLICANT", "ACTIVE", "SUSPENDED", "TERMINATED", "LAPSED")
    assert data["privilege_posture"] in (
        "NONE", "FULL", "PARTIAL", "EMERGENCY_ONLY")
    assert isinstance(data["active_privilege_line_count"], int)
    assert isinstance(data["credential_expiry_risk_score"], (int, float))
    assert isinstance(data["sod_exclusion_tags"], list)


def assert_specialty_criteria(data: dict):
    """SpecialtyCriteria response structure."""
    _assert_common_fields(data)
    assert isinstance(data["specialty_code"], str) and data["specialty_code"]
    assert isinstance(data["privilege_line"], str) and data["privilege_line"]
    assert isinstance(data["min_training_months"], int)
    assert isinstance(data["min_case_volume_24mo"], int)
    assert isinstance(data["required_board_cert"], bool)
    assert isinstance(data["fppe_case_count"], int)
    assert isinstance(data["volume_tier_table"], list)


def assert_application(data: dict):
    """AppointmentApplication response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["application_kind"] in ("INITIAL", "REAPPOINTMENT")
    assert data["application_status"] in (
        "DRAFT", "SUBMITTED", "PSV_IN_PROGRESS", "PSV_COMPLETE",
        "COMMITTEE_REVIEW", "BOARD_REVIEW", "APPROVED", "DENIED",
        "WITHDRAWN", "EXPIRED")
    assert isinstance(data["verification_complete_count"], int)
    assert isinstance(data["verification_required_count"], int)


def assert_verification_item(data: dict):
    """VerificationItem response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["item_kind"] in (
        "MEDICAL_SCHOOL", "RESIDENCY", "BOARD_CERT", "STATE_LICENSE", "DEA",
        "MALPRACTICE_HISTORY", "WORK_HISTORY", "NPDB_QUERY", "REFERENCES")
    assert data["item_status"] in (
        "PENDING", "REQUESTED", "RECEIVED", "VERIFIED", "DISCREPANCY", "WAIVED")
    assert isinstance(data["is_primary_source"], bool)


def assert_delineation(data: dict):
    """PrivilegeDelineation response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["privilege_line"], str) and data["privilege_line"]
    assert isinstance(data["documented_training_months"], int)
    assert isinstance(data["documented_cases_24mo"], int)
    assert data["delineation_status"] in (
        "REQUESTED", "CRITERIA_MET", "CRITERIA_UNMET", "GRANTED", "DENIED")


def assert_privilege_grant(data: dict):
    """PrivilegeGrant response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("delineation_id", ""))
    assert isinstance(data["privilege_line"], str) and data["privilege_line"]
    assert data["grant_status"] in (
        "PROVISIONAL", "ACTIVE", "SUSPENDED", "EXPIRED", "REVOKED",
        "RELINQUISHED")
    assert isinstance(data["fppe_cases_completed"], int)


def assert_performance_review(data: dict):
    """PerformanceReview response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("privilege_grant_id", ""))
    assert data["review_kind"] in ("FPPE", "OPPE")
    assert data["review_status"] in (
        "COLLECTING", "EVALUATION", "PROVISIONAL_RESULT", "FINAL_RESULT",
        "CLOSED")
    assert isinstance(data["metric_count"], int)
    assert isinstance(data["retracted_metric_count"], int)


def assert_performance_metric(data: dict):
    """PerformanceMetric response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("review_id", ""))
    assert data["metric_domain"] in (
        "CLINICAL_QUALITY", "PATIENT_SAFETY", "DOCUMENTATION", "CITIZENSHIP",
        "UTILIZATION")
    assert isinstance(data["raw_value"], (int, float))
    assert isinstance(data["normalized_value"], (int, float))
    assert isinstance(data["domain_weight"], (int, float))
    assert is_iso8601_timestamp(data.get("collected_at", ""))
    assert data["metric_status"] in ("ACTIVE", "RETRACTED")


def assert_expirable_credential(data: dict):
    """ExpirableCredential response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["credential_kind"] in (
        "STATE_LICENSE", "DEA", "BOARD_CERT", "MALPRACTICE_INSURANCE", "ACLS")
    assert isinstance(data["credential_number"], str)
    assert is_iso8601_timestamp(data.get("issued_on", ""))
    assert is_iso8601_timestamp(data.get("expires_on", ""))
    assert data["credential_status"] in ("CURRENT", "LAPSED", "RENEWED", "REVOKED")


def assert_temporary_privilege(data: dict):
    """TemporaryPrivilege response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", ""))
    assert is_valid_uuid(data.get("sponsor_member_id", ""))
    assert data["temp_kind"] in ("TEMPORARY", "EMERGENCY", "DISASTER")
    assert isinstance(data["privilege_line"], str)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["temp_status"] in (
        "PENDING_SPONSOR", "ACTIVE", "EXPIRED", "TERMINATED_EARLY")


def assert_adverse_action_case(data: dict):
    """AdverseActionCase response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("subject_member_id", ""))
    assert is_valid_uuid(data.get("proposed_by_member_id", ""))
    assert data["case_kind"] in (
        "SUSPENSION", "REVOCATION", "DENIAL_OF_REAPPOINTMENT", "RESTRICTION")
    assert data["case_status"] in (
        "PROPOSED", "MEC_ENDORSED", "HEARING_REQUESTED", "HEARING_HELD",
        "REMANDED", "FINAL_ADVERSE", "FINAL_NO_ACTION", "WITHDRAWN")
    assert is_iso8601_timestamp(data.get("proposed_at", ""))
    assert is_iso8601_timestamp(data.get("hearing_request_deadline", ""))


def assert_hearing_panel(data: dict):
    """HearingPanel response structure."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("case_id", ""))
    assert is_valid_uuid(data.get("panel_member_id", ""))
    assert data["panel_role"] in ("CHAIR", "MEMBER")
    assert data["panel_status"] in ("SEATED", "RECUSED", "DISQUALIFIED")
    assert is_iso8601_timestamp(data.get("seated_at", ""))


def assert_npdb_report(data: dict):
    """NpdbReport response structure — immutable filing record per PRD §2.4:
    carries only id and created_at from the standard set; updated_at and
    version are absent."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert "updated_at" not in data, "NpdbReport must not carry updated_at"
    assert "version" not in data, "NpdbReport must not carry version"
    assert is_valid_uuid(data.get("member_id", ""))
    assert data["report_kind"] in (
        "QUERY_INITIAL", "QUERY_REAPPOINTMENT", "REPORT_ADVERSE_ACTION",
        "REPORT_CORRECTION", "REPORT_VOID")
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert data["report_status"] in ("SUBMITTED", "ACKNOWLEDGED", "LATE", "VOIDED")
    assert isinstance(data["is_late"], bool)


def assert_agenda_item(data: dict):
    """CommitteeAgendaItem response structure."""
    _assert_common_fields(data)
    assert data["item_kind"] in (
        "APPLICATION_APPROVAL", "PRIVILEGE_GRANT", "ADVERSE_ACTION",
        "POLICY_CHANGE")
    assert data["committee_status"] in (
        "AGENDA", "COMMITTEE_APPROVED", "COMMITTEE_REJECTED", "MEC_ENDORSED",
        "BOARD_RATIFIED", "BOARD_DECLINED", "DEFERRED")
    assert isinstance(data["committee_votes_for"], int)
    assert isinstance(data["committee_votes_against"], int)
    assert isinstance(data["mec_voter_ids"], list)


def assert_score_2dp(value: float):
    """Every score/risk value is carried at exactly 2 decimal places (PRD §2.6)."""
    rounded = round(float(value), 2)
    assert abs(rounded - float(value)) < 1e-9, (
        f"Value {value} has more than 2 decimal places")
