"""Entity assertions for the Medicare Advantage Enrollment API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-typed."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_immutable(data: dict):
    """id + created_at only (EnrollmentPeriod, DrugClaim)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_beneficiary(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["part_a_status"] in ("NONE", "ENROLLED")
    assert data["part_b_status"] in ("NONE", "ENROLLED")
    assert isinstance(data["enrollment_lock"], bool)
    assert data["status"] in ("ACTIVE", "FRAUD_HOLD", "DECEASED")


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["part_type"] in ("PART_C", "PART_D")
    assert isinstance(data["monthly_premium_cents"], int) and data["monthly_premium_cents"] >= 0
    assert data["star_rating"] in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
    assert isinstance(data["includes_drug_coverage"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_enrollment_period(data: dict):
    _assert_immutable(data)
    assert data["period_type"] in ("IEP", "AEP", "SEP_5STAR", "GI_MEDIGAP")
    assert is_iso8601_timestamp(data["window_start"]), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data["window_end"]), "window_end must be ISO 8601"


def assert_part_b_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("FILED", "ACTIVE", "DROPPED", "VOIDED")


def assert_part_c_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUPERSEDED", "DISENROLLED", "VOIDED")


def assert_part_d_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["total_drug_cost_cents"], int) and data["total_drug_cost_cents"] >= 0
    assert isinstance(data["member_oop_cents"], int) and data["member_oop_cents"] >= 0
    assert isinstance(data["lep_premium_cents"], int) and data["lep_premium_cents"] >= 0
    assert data["status"] in ("PENDING", "ACTIVE", "DISENROLLED", "VOIDED")


def assert_drug_claim(data: dict):
    _assert_immutable(data)
    assert data["phase_at_post"] in ("DEDUCTIBLE", "INITIAL", "GAP", "CATASTROPHIC")
    assert isinstance(data["member_share_cents"], int) and data["member_share_cents"] >= 0


def assert_medigap_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "LAPSED", "VOIDED")


def assert_penalty_assessment(data: dict):
    _assert_common(data)
    assert data["penalty_type"] in ("PART_B", "PART_D")
    assert isinstance(data["monthly_penalty_cents"], int) and data["monthly_penalty_cents"] >= 0
    assert data["status"] in ("ASSESSED", "WAIVED")
