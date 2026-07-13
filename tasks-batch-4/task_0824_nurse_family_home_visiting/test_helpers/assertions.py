"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_nurse(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["credential_type"] in ("RN", "BSN", "APRN")
    assert data["status"] in ("ACTIVE", "ON_LEAVE", "INACTIVE")
    assert isinstance(data["max_caseload_weight"], (int, float))
    assert isinstance(data["current_caseload_weight"], (int, float))
    assert data["current_caseload_weight"] >= 0
    assert isinstance(data["pending_supervision_count"], int)
    assert data["pending_supervision_count"] >= 0


def assert_supervisor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["first_time_mother"], bool)
    assert isinstance(data["gestational_age_weeks"], int)
    assert data["gestational_age_weeks"] >= 0
    assert isinstance(data["consent_signed"], bool)
    assert data["risk_tier"] in ("LOW", "MODERATE", "HIGH")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("client_id", "")), "client_id must be a UUID"
    assert data["status"] in ("PROSPECT", "ENROLLED", "ACTIVE", "GRADUATED", "EXITED")
    assert data["program_phase"] in ("PREGNANCY", "INFANCY", "TODDLERHOOD")
    assert isinstance(data["completed_visit_count"], int)
    assert data["completed_visit_count"] >= 0
    assert isinstance(data["dosage_alert"], bool)
    assert data["risk_tier_at_enrollment"] in ("LOW", "MODERATE", "HIGH")


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("nurse_id", ""))
    assert data["phase_at_assignment"] in ("PREGNANCY", "INFANCY", "TODDLERHOOD")
    assert isinstance(data["high_needs"], bool)
    assert isinstance(data["caseload_weight"], (int, float))
    assert data["caseload_weight"] >= 0
    assert data["status"] in ("ACTIVE", "ENDED")
    assert isinstance(data["review_required"], bool)


def assert_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("nurse_id", ""))
    assert data["phase"] in ("PREGNANCY", "INFANCY", "TODDLERHOOD")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELED", "RESCHEDULED")
    assert isinstance(data["on_time"], bool)


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["benefit_type"] in ("WIC", "MEDICAID", "HOUSING", "CHILDCARE", "MENTAL_HEALTH")
    assert data["status"] in ("OPEN", "CONTACTED", "CONNECTED", "DECLINED", "CLOSED")
    assert isinstance(data["attempts"], int)
    assert data["attempts"] >= 0


def assert_assessment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("visit_id", ""))
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert data["instrument_type"] in ("INTAKE", "ASQ", "EDINBURGH", "ASQ_SE")
    assert data["result_band"] in ("ON_TRACK", "MONITOR", "REFER")
    assert isinstance(data["domain_flags"], list)


def assert_supervision_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("nurse_id", ""))
    assert is_valid_uuid(data.get("supervisor_id", ""))
    assert data["status"] in ("DRAFT", "SIGNED")


def assert_miechv_report(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_domain_flags_sorted(flags: list):
    """domain_flags must be ordered by domain key ascending (PRD Section 3.7)."""
    assert flags == sorted(flags), f"domain_flags must be sorted ascending, got {flags}"
