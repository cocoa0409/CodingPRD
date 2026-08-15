"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import round_half_up_ratio
from .types import (
    AllocationStatus,
    AmendmentStatus,
    ConsultationStatus,
    EligibilityFlag,
    EquitableCountMethod,
    ExpenditureStatus,
    FindingSeverity,
    FindingStatus,
    FunctionCode,
    GrantStatus,
    MonitoringClearance,
    PovertyMeasure,
    ProgramModel,
    SetAsideCategory,
    SnapshotStatus,
    SnsMethodology,
    SnsStatus,
    VisitScope,
    VisitStatus,
    WaiverStatus,
)


def _assert_common_fields(data: dict, label: str):
    """PRD §2.4: every primary resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer"


def assert_grant(data: dict):
    _assert_common_fields(data, "grant")
    assert isinstance(data["fiscal_year"], int)
    assert isinstance(data["total_allocation_cents"], int)
    assert data["total_allocation_cents"] > 0
    assert isinstance(data["carryover_in_cents"], int)
    assert isinstance(data["admin_reserve_cents"], int)
    assert data["poverty_measure"] in [m.value for m in PovertyMeasure]
    assert data["equitable_count_method"] in \
        [m.value for m in EquitableCountMethod]
    assert data["status"] in [s.value for s in GrantStatus]
    assert data["carryover_waiver_status"] in [s.value for s in WaiverStatus]
    assert data["monitoring_clearance"] in \
        [c.value for c in MonitoringClearance]
    # PRD §3.1: net_allocable_cents is derived as total + carryover - reserve.
    assert data["net_allocable_cents"] == (
        data["total_allocation_cents"] + data["carryover_in_cents"]
        - data["admin_reserve_cents"]
    ), "grant.net_allocable_cents must equal total + carryover_in - admin_reserve"
    assert isinstance(data["ranking_version"], int)
    assert isinstance(data["liquidated_cents"], int)
    assert isinstance(data["pending_cents"], int)
    assert isinstance(data["provisional_carryover_cents"], int)
    assert isinstance(data["provisional_carryover_pct_bp"], int)


def assert_school(data: dict):
    _assert_common_fields(data, "school")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nces_id"], str) and data["nces_id"]
    assert isinstance(data["grade_span_low"], int)
    assert isinstance(data["grade_span_high"], int)
    assert data["grade_span_low"] <= data["grade_span_high"]
    assert isinstance(data["is_active"], bool)


def assert_private_school(data: dict):
    _assert_common_fields(data, "private_school")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["nonprofit_verified"], bool)
    assert isinstance(data["low_income_resident_count"], int)
    assert data["low_income_resident_count"] >= 0


def assert_snapshot(data: dict):
    _assert_common_fields(data, "snapshot")
    assert is_valid_uuid(data["grant_id"])
    assert data["measure"] in [m.value for m in PovertyMeasure]
    assert data["status"] in [s.value for s in SnapshotStatus]
    assert isinstance(data["entries"], list)
    for entry in data["entries"]:
        assert is_valid_uuid(entry["school_id"])
        assert isinstance(entry["low_income_student_count"], int)
        assert isinstance(entry["total_student_count"], int)


def assert_school_allocation(data: dict):
    _assert_common_fields(data, "allocation")
    assert is_valid_uuid(data["grant_id"])
    assert is_valid_uuid(data["school_id"])
    assert is_valid_uuid(data["snapshot_id"])
    assert isinstance(data["low_income_student_count"], int)
    assert isinstance(data["total_student_count"], int)
    assert isinstance(data["poverty_pct_bp"], int)
    assert isinstance(data["rank_position"], int) and data["rank_position"] >= 1
    assert data["eligibility_flag"] in [f.value for f in EligibilityFlag]
    assert data["program_model"] in [m.value for m in ProgramModel]
    assert isinstance(data["serve_elected"], bool)
    assert isinstance(data["served"], bool)
    # PRD §3.3: an allocation counts as served when its eligibility_flag is
    # anything other than BELOW_THRESHOLD or when it was elected.
    assert data["served"] == (
        data["eligibility_flag"] != EligibilityFlag.BELOW_THRESHOLD.value
        or data["serve_elected"]
    ), "allocation.served must equal (not BELOW_THRESHOLD) or serve_elected"
    assert isinstance(data["per_pupil_cents"], int)
    assert isinstance(data["allocation_amount_cents"], int)
    assert isinstance(data["liquidated_cents"], int)
    assert isinstance(data["pending_cents"], int)
    assert isinstance(data["supplement_ok"], bool)
    assert data["status"] in [s.value for s in AllocationStatus]


def assert_set_aside(data: dict):
    _assert_common_fields(data, "set_aside")
    assert is_valid_uuid(data["grant_id"])
    assert data["category"] in [c.value for c in SetAsideCategory]
    assert isinstance(data["minimum_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    # PRD §3.4: reserved may be lowered "downward only to the floor".
    assert data["reserved_cents"] >= data["minimum_cents"], \
        "set_aside.reserved_cents must never drop below minimum_cents"
    # PRD §3.4: the parent-engagement row carries ninety percent of its
    # reserved_cents (rounded half up); for the other categories it is zero.
    if data["category"] == SetAsideCategory.PARENT_ENGAGEMENT.value:
        expected = round_half_up_ratio(90 * data["reserved_cents"], 100)
        assert data["school_distributed_minimum_cents"] == expected, (
            f"PE school_distributed_minimum_cents must be round_half_up("
            f"0.90 * {data['reserved_cents']}) == {expected}, got "
            f"{data['school_distributed_minimum_cents']}"
        )
    else:
        assert data["school_distributed_minimum_cents"] == 0


def assert_sns_document(data: dict):
    _assert_common_fields(data, "sns_document")
    assert is_valid_uuid(data["school_allocation_id"])
    assert data["methodology"] in [m.value for m in SnsMethodology]
    assert isinstance(data["coverage_start_date"], str)
    assert isinstance(data["coverage_end_date"], str)
    assert data["coverage_end_date"] > data["coverage_start_date"]
    assert isinstance(data["narrative"], str)
    assert len(data["narrative"]) >= 50
    assert data["status"] in [s.value for s in SnsStatus]
    assert isinstance(data["attempt_count"], int)


def assert_consultation(data: dict):
    _assert_common_fields(data, "consultation")
    assert is_valid_uuid(data["grant_id"])
    assert is_valid_uuid(data["private_school_id"])
    assert data["status"] in [s.value for s in ConsultationStatus]
    assert isinstance(data["sessions"], list)
    assert isinstance(data["sessions_count"], int)
    assert data["sessions_count"] == len(data["sessions"]), \
        "consultation.sessions_count must equal len(sessions)"


def assert_expenditure(data: dict):
    _assert_common_fields(data, "expenditure")
    assert is_valid_uuid(data["grant_id"])
    # PRD §3.7: exactly one charge target.
    has_alloc = data.get("school_allocation_id") is not None
    has_set_aside = data.get("set_aside_id") is not None
    assert has_alloc != has_set_aside, \
        "expenditure must name exactly one of school_allocation_id/set_aside_id"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["function_code"] in [f.value for f in FunctionCode]
    assert data["status"] in [s.value for s in ExpenditureStatus]


def assert_amendment(data: dict):
    _assert_common_fields(data, "amendment")
    assert is_valid_uuid(data["grant_id"])
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert line["target_type"] in ("SCHOOL_ALLOCATION", "SET_ASIDE")
        assert is_valid_uuid(line["target_id"])
        assert isinstance(line["new_amount_cents"], int)
    assert data["status"] in [s.value for s in AmendmentStatus]


def assert_visit(data: dict):
    _assert_common_fields(data, "visit")
    assert is_valid_uuid(data["grant_id"])
    assert data["visit_end_date"] >= data["visit_start_date"]
    assert data["scope"] in [s.value for s in VisitScope]
    assert data["status"] in [s.value for s in VisitStatus]


def assert_finding(data: dict):
    _assert_common_fields(data, "finding")
    assert is_valid_uuid(data["visit_id"])
    assert data["severity"] in [s.value for s in FindingSeverity]
    assert data["status"] in [s.value for s in FindingStatus]
    assert isinstance(data["cap_attempt_count"], int)
