"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

POSTURES = {"ON_TRACK", "AT_RISK", "NON_COMPLIANT"}
DRILL_TYPES = {"FIRE", "LOCKDOWN", "EVACUATION", "SHELTER_IN_PLACE", "EARTHQUAKE"}
EOP_STATUSES = {"DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "ACTIVE",
                "SUPERSEDED", "EXPIRED"}
SITE_PLAN_STATUSES = {"CURRENT", "SUPERSEDED", "EXPIRED"}
WALKTHROUGH_STATUSES = {"SCHEDULED", "COMPLETED", "MISSED"}
DRILL_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CLOSED",
                  "CANCELLED", "MISSED"}
ROSTER_STATUSES = {"UNACCOUNTED", "ACCOUNTED", "RELEASED"}
REVIEW_STATUSES = {"DRAFT", "SUBMITTED", "ACCEPTED", "RETURNED", "CLOSED"}
CA_STATUSES = {"OPEN", "PENDING_VERIFICATION", "REOPENED", "VERIFIED"}
ACCOMMODATION_STATUSES = {"ACTIVE", "INACTIVE"}
REPORT_STATUSES = {"DRAFT", "STALE", "SUBMITTED", "ACCEPTED", "REJECTED"}


def assert_common_fields(data: dict):
    """The four common fields every entity carries."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}")


def _assert_optional_timestamp(data: dict, field: str):
    value = data.get(field)
    if value is not None:
        assert is_iso8601_timestamp(value), f"{field} must be ISO 8601, got {value!r}"


def assert_school_site(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("enrollment_count"), int)
    assert data.get("compliance_posture") in POSTURES
    for field in ("drills_scheduled_count", "drills_completed_count",
                  "drills_missed_count", "drills_cancelled_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"


def assert_drill_requirement(data: dict):
    assert_common_fields(data)
    assert data.get("drill_type") in DRILL_TYPES
    assert isinstance(data.get("required_per_year"), int)
    assert data["required_per_year"] >= 1
    assert isinstance(data.get("min_spacing_days"), int)
    assert data["min_spacing_days"] >= 0
    assert isinstance(data.get("target_evac_seconds"), int)
    assert data["target_evac_seconds"] >= 1


def assert_eop(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("title"), str) and data["title"]
    assert isinstance(data.get("plan_version_label"), str)
    assert data.get("status") in EOP_STATUSES
    _assert_optional_timestamp(data, "activated_at")


def assert_site_plan_document(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("document_title"), str) and data["document_title"]
    assert data.get("status") in SITE_PLAN_STATUSES
    tags = data.get("coverage_tags")
    assert isinstance(tags, list)


def assert_walkthrough(data: dict):
    assert_common_fields(data)
    assert data.get("agency") in {"FIRE", "POLICE", "EMS"}
    assert data.get("status") in WALKTHROUGH_STATUSES


def assert_drill_event(data: dict):
    assert_common_fields(data)
    assert data.get("drill_type") in DRILL_TYPES
    assert data.get("status") in DRILL_STATUSES
    for field in ("roster_total", "unaccounted_count", "accounted_count",
                  "released_count"):
        assert isinstance(data.get(field), int), f"{field} must be an integer"
    _assert_optional_timestamp(data, "actual_start_at")
    _assert_optional_timestamp(data, "all_clear_at")
    _assert_optional_timestamp(data, "last_accountability_at")


def assert_roster_entry(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("student_ref"), str) and data["student_ref"]
    assert data.get("status") in ROSTER_STATUSES
    _assert_optional_timestamp(data, "accounted_at")
    _assert_optional_timestamp(data, "released_at")


def assert_after_action_review(data: dict):
    assert_common_fields(data)
    assert data.get("overall_rating") in {"EXCEEDS", "MEETS", "NEEDS_IMPROVEMENT",
                                          "UNSATISFACTORY"}
    assert data.get("evacuation_assessment") in {"MET_STANDARD", "MET_ADJUSTED",
                                                 "NOT_MET"}
    assert data.get("status") in REVIEW_STATUSES
    assert isinstance(data.get("ca_total_count"), int)
    assert isinstance(data.get("ca_verified_count"), int)


def assert_corrective_action(data: dict):
    assert_common_fields(data)
    assert data.get("priority") in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert data.get("status") in CA_STATUSES
    assert isinstance(data.get("is_overdue"), bool)


def assert_accommodation_plan(data: dict):
    assert_common_fields(data)
    assert data.get("need_type") in {"MOBILITY", "VISUAL", "AUDITORY", "SENSORY",
                                     "COGNITIVE"}
    assert data.get("status") in ACCOMMODATION_STATUSES


def assert_compliance_report(data: dict):
    assert_common_fields(data)
    assert data.get("status") in REPORT_STATUSES
    assert isinstance(data.get("type_attainments"), list)
    for entry in data["type_attainments"]:
        assert entry.get("drill_type") in DRILL_TYPES
        assert isinstance(entry.get("required_count"), int)
        assert isinstance(entry.get("completed_count"), int)
        assert isinstance(entry.get("spacing_compliant"), bool)
        assert isinstance(entry.get("attainment_count_only"), bool)
        assert isinstance(entry.get("attainment_strict"), bool)
    assert isinstance(data.get("overall_compliant_count_only"), bool)
    assert isinstance(data.get("overall_compliant_strict"), bool)
    assert isinstance(data.get("overall_score_pct"), (int, float))


def assert_roster_counters_invariant(drill: dict):
    """unaccounted + accounted + released always equals roster_total."""
    total = drill["roster_total"]
    bucket_sum = (drill["unaccounted_count"] + drill["accounted_count"]
                  + drill["released_count"])
    assert bucket_sum == total, (
        f"Roster buckets {bucket_sum} != roster_total {total}")


def assert_drill_counter_sum(site: dict, expected_total: int):
    """The four site drill counters sum to the number of drills created in scope."""
    counter_sum = (site["drills_scheduled_count"] + site["drills_completed_count"]
                   + site["drills_missed_count"] + site["drills_cancelled_count"])
    assert counter_sum == expected_total, (
        f"Drill counters sum {counter_sum} != expected total {expected_total}")


__all__ = [
    "assert_common_fields", "assert_school_site", "assert_drill_requirement",
    "assert_eop", "assert_site_plan_document", "assert_walkthrough",
    "assert_drill_event", "assert_roster_entry", "assert_after_action_review",
    "assert_corrective_action", "assert_accommodation_plan",
    "assert_compliance_report", "assert_roster_counters_invariant",
    "assert_drill_counter_sum",
]
