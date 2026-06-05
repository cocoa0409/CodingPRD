"""Entity assertions and domain invariant checkers.

Structural validators for each resource response, built on the framework's
generic checkers. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ORGAN_TYPES = ["LIVER", "KIDNEY", "HEART", "LUNG"]
BLOOD_TYPES = ["O", "A", "B", "AB"]


def _assert_common(data: dict):
    """Common fields for full first-class resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_transplant_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unos_center_code"], str) and len(data["unos_center_code"]) > 0
    assert 1 <= data["region_code"] <= 11, "region_code must be in 1..11"


def assert_opo(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["opo_code"], str) and len(data["opo_code"]) > 0
    assert 1 <= data["region_code"] <= 11, "region_code must be in 1..11"


def assert_candidate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["center_id"]), "center_id must be a valid UUID"
    assert data["organ_type"] in ORGAN_TYPES
    assert data["blood_type"] in BLOOD_TYPES
    assert data["listing_status"] in ["DRAFT", "LISTED", "TRANSPLANTED", "REMOVED"]
    assert data["medical_status"] in ["ACTIVE", "INACTIVE"]
    assert isinstance(data["current_meld_peld"], int)
    assert isinstance(data["waiting_time_days"], int)
    assert data["waiting_time_days"] >= 0
    assert isinstance(data["hla_a"], list) and len(data["hla_a"]) == 2
    assert isinstance(data["hla_b"], list) and len(data["hla_b"]) == 2
    assert isinstance(data["hla_dr"], list) and len(data["hla_dr"]) == 2


def assert_clinical_score(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"]), "candidate_id must be a valid UUID"
    assert data["status"] in ["DRAFT", "FINALIZED", "SUPERSEDED"]
    if data["status"] in ("FINALIZED", "SUPERSEDED"):
        assert data["score_kind"] in ["MELD_NA", "PELD"]
        assert isinstance(data["allocation_score"], int)
        assert 6 <= data["allocation_score"] <= 40, "allocation_score clamped to [6,40]"


def assert_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["candidate_id"]), "candidate_id must be a valid UUID"
    assert data["organ_type"] in ORGAN_TYPES
    assert data["status"] in ["ACTIVE", "SUSPENDED", "WITHDRAWN"]


def assert_donor_organ(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["opo_id"]), "opo_id must be a valid UUID"
    assert data["organ_type"] in ORGAN_TYPES
    assert data["blood_type"] in BLOOD_TYPES
    assert data["status"] in ["AVAILABLE", "MATCHING", "ALLOCATED", "TRANSPLANTED", "DISCARDED"]
    assert isinstance(data["open_offer_count"], int)
    assert data["open_offer_count"] >= 0, "open_offer_count is a non-negative conserved quantity"


def assert_match_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["donor_organ_id"]), "donor_organ_id must be a valid UUID"
    assert data["policy_code"] in ["STANDARD", "BROADER_SHARING"]
    assert data["status"] in ["COMPLETED", "INVALIDATED"]
    assert isinstance(data["ranked_count"], int)
    assert data["ranked_count"] >= 0


def assert_match_list_entry(data: dict):
    """Append-only ranking row: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["match_run_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert 0 <= data["hla_mismatch_count"] <= 6, "hla_mismatch_count is 0..6"


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["donor_organ_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["match_run_id"])
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "RESCINDED"]
    assert is_iso8601_timestamp(data["offered_at"])
    assert is_iso8601_timestamp(data["response_deadline_at"])


def assert_transplant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["offer_id"])
    assert is_valid_uuid(data["candidate_id"])
    assert is_valid_uuid(data["donor_organ_id"])
    assert data["graft_status"] in ["FUNCTIONING", "AT_RISK", "FAILED"]
    assert isinstance(data["cold_ischemia_hours_actual"], (int, float))


def assert_follow_up(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["transplant_id"])
    assert data["interval_label"] in ["M1", "M6", "M12", "M24"]
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED"]


def assert_unos_report(data: dict):
    _assert_common(data)
    assert data["report_kind"] in ["TRANSPLANT", "REMOVAL", "FOLLOWUP"]
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_open_offer_count_equals(organ: dict, expected: int):
    """Conserved-quantity invariant (PRD §3.5): open_offer_count always equals
    the number of OFFERED offers for the organ."""
    assert organ["open_offer_count"] == expected, (
        f"Expected open_offer_count {expected}, got {organ['open_offer_count']}"
    )
