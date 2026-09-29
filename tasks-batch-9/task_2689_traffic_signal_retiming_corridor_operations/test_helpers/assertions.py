"""Entity assertions and domain invariant checkers for the retiming API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import MAX_PRIORITY_FRACTION


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: dict):
    """id + created_at only; updated_at and version must be absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only records must not expose updated_at"
    assert "version" not in data, "append-only records must not expose version"


def assert_intersection(data: dict):
    assert_common_fields(data)
    assert isinstance(data["location_name"], str) and 1 <= len(data["location_name"]) <= 120
    assert data["controller_type"] in ("TS2_CABINET", "ATC_CABINET", "LEGACY_170")
    assert data["detection_status"] in ("FULL", "PARTIAL", "FAILED", "NONE")
    assert data["comm_status"] in ("ONLINE", "INTERMITTENT", "OFFLINE")
    assert isinstance(data["aps_installed"], bool)
    assert data["walking_speed_standard"] in ("STD_3_5_FPS", "EXTENDED_3_0_FPS")
    assert isinstance(data["pedestrian_recall"], bool)
    assert 60 <= data["max_cycle_length_sec"] <= 240
    assert data["operational_posture"] in ("READY", "RESTRICTED", "BLOCKED")
    assert isinstance(data["timing_plan_age_days"], int)
    assert_intersection_posture(data)
    assert_priority_budget_invariant(data)


def assert_intersection_posture(data: dict):
    """The posture ladder of PRD §2.10, derived from comm_status and detection_status."""
    if data["comm_status"] == "OFFLINE" or data["detection_status"] == "FAILED":
        expected = "BLOCKED"
    elif data["comm_status"] == "INTERMITTENT" or data["detection_status"] in ("PARTIAL", "NONE"):
        expected = "RESTRICTED"
    else:
        expected = "READY"
    assert data["operational_posture"] == expected, (
        f"posture for comm={data['comm_status']} detection={data['detection_status']} "
        f"must be {expected}, got {data['operational_posture']}"
    )


def assert_priority_budget_invariant(data: dict):
    """granted + unallocated == budget, per PRD §2.12."""
    granted = data["granted_priority_extension_total_sec"]
    unallocated = data["unallocated_priority_budget_sec"]
    budget = data["priority_budget_sec"]
    assert granted + unallocated == budget, (
        f"priority budget invariant broken: {granted} + {unallocated} != {budget}"
    )
    cycle = data.get("deployed_coordinated_cycle_sec")
    if cycle is None:
        assert budget == 0, f"budget must be 0 with no deployed cycle, got {budget}"
    else:
        assert budget == int(cycle * MAX_PRIORITY_FRACTION), (
            f"budget must be floor(0.20 * {cycle}), got {budget}"
        )


def assert_corridor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["jurisdiction_class"] in ("ARTERIAL", "COLLECTOR", "LOCAL")
    assert data["selection_status"] in ("UNSCREENED", "SCREENED", "SELECTED", "DEFERRED")
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert 0 <= data["priority_score"] <= 100, f"priority_score out of range: {data['priority_score']}"
    assert data["priority_score_variant"] in ("SCREENING", "PROGRAMMING", None)
    assert_complaint_partition(data)


def assert_complaint_partition(data: dict):
    """The three buckets always sum to complaint_total_count, per PRD §2.12."""
    total = (
        data["complaint_open_count"]
        + data["complaint_linked_count"]
        + data["complaint_terminal_count"]
    )
    assert total == data["complaint_total_count"], (
        f"complaint partition broken: {data['complaint_open_count']} + "
        f"{data['complaint_linked_count']} + {data['complaint_terminal_count']} "
        f"!= {data['complaint_total_count']}"
    )


def assert_corridor_member(data: dict):
    assert_append_only_fields(data)
    assert isinstance(data["sequence_index"], int) and data["sequence_index"] >= 1
    assert data["distance_from_prev_ft"] >= 0


def assert_requester(data: dict):
    assert_common_fields(data)
    assert isinstance(data["display_name"], str) and 1 <= len(data["display_name"]) <= 80
    assert "@" in data["email"]
    assert data["contact_pref"] in ("EMAIL", "PHONE", "NONE")
    assert isinstance(data["open_complaint_count"], int) and data["open_complaint_count"] >= 0


def assert_complaint(data: dict):
    assert_common_fields(data)
    assert data["category"] in ("COORDINATION", "PEDESTRIAN", "DETECTION", "TIMING_OTHER")
    assert data["status"] in ("OPEN", "TRIAGED", "LINKED", "RESOLVED", "CLOSED_NO_ACTION")
    assert is_iso8601_timestamp(data["received_at"])
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert isinstance(data["narrative"], str) and 1 <= len(data["narrative"]) <= 1000


def assert_retiming_project(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DATA_COLLECTION",
        "PLAN_DEVELOPMENT",
        "IMPLEMENTED",
        "FIELD_TUNING",
        "EVALUATION",
        "CLOSED",
        "ABANDONED",
    )
    assert 30 <= data["study_window_days"] <= 730
    assert isinstance(data["tuning_round"], int) and 0 <= data["tuning_round"] <= 3
    assert isinstance(data["eligible_member_count"], int) and data["eligible_member_count"] >= 0


def assert_turning_movement_count(data: dict):
    assert_append_only_fields(data)
    assert data["study_role"] in ("BEFORE", "AFTER")
    assert data["period"] in ("AM_PEAK", "MID_DAY", "PM_PEAK")
    assert isinstance(data["phase_volumes"], dict) and 1 <= len(data["phase_volumes"]) <= 8
    assert data["critical_flow_ratio_sum"] < 0.95, (
        "a stored count must have a critical flow ratio below the oversaturation ratio"
    )
    assert isinstance(data["recommended_cycle_sec"], int)
    assert data["recommended_cycle_sec"] % 5 == 0 or data["recommended_cycle_sec"] == 60, (
        f"recommended_cycle_sec must be a whole multiple of 5 seconds, got {data['recommended_cycle_sec']}"
    )
    assert data["recommended_cycle_sec"] >= 60


def assert_travel_time_run(data: dict):
    assert_append_only_fields(data)
    assert data["study_role"] in ("BEFORE", "AFTER")
    assert data["direction"] in ("NB", "SB", "EB", "WB")
    assert 0 < data["duration_sec"] <= 3600
    assert data["stops_count"] >= 0
    assert data["total_arrivals"] >= 1
    assert data["arrivals_on_green_count"] <= data["total_arrivals"]
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_timing_plan(data: dict):
    assert_common_fields(data)
    assert data["tod_period"] in ("AM_PEAK", "MID_DAY", "PM_PEAK", "OFF_PEAK")
    assert 0 <= data["tod_start_min"] <= 1439
    assert 1 <= data["tod_end_min"] <= 1440
    assert data["tod_end_min"] > data["tod_start_min"]
    assert data["coordination_ref"] in ("MASTER", "LOCAL_FREE")
    assert 60 <= data["cycle_length_sec"] <= 240
    assert data["status"] in (
        "DRAFT",
        "COORDINATED",
        "SUBMITTED",
        "CERTIFIED",
        "DEPLOYED",
        "SUPERSEDED",
    )
    assert data["ped_compliance_state"] in ("PENDING", "COMPLIANT", "NON_COMPLIANT", "WAIVED")
    assert isinstance(data["return_count"], int) and data["return_count"] >= 0
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


def assert_split_second_invariant(plan: dict):
    """Past DRAFT, the effective splits sum to the operating cycle exactly (PRD §2.12)."""
    if plan["status"] == "DRAFT":
        return
    assert plan["effective_split_total_sec"] == plan["cycle_length_sec"], (
        f"split-second invariant broken: effective_split_total_sec "
        f"{plan['effective_split_total_sec']} != cycle_length_sec {plan['cycle_length_sec']}"
    )


def assert_phase_split(data: dict):
    assert_common_fields(data)
    assert 1 <= data["phase_number"] <= 8
    assert 5 <= data["split_sec"] <= 240
    assert 1 <= data["min_green_sec"] <= 60
    assert 3.0 <= data["yellow_sec"] <= 6.0
    assert 0.0 <= data["red_clearance_sec"] <= 6.0
    assert isinstance(data["is_pedestrian_phase"], bool)
    assert data["walk_sec"] >= 0
    assert data["ped_clear_sec"] >= 0
    assert data["crosswalk_length_ft"] >= 0
    if data["is_pedestrian_phase"]:
        assert data["walk_sec"] > 0 and data["ped_clear_sec"] > 0 and data["crosswalk_length_ft"] > 0


def assert_pedestrian_check(data: dict):
    assert_common_fields(data)
    assert 1 <= data["phase_number"] <= 8
    assert data["walking_speed_fps"] in (3.5, 3.0)
    assert data["result"] in ("PASS", "FAIL", "WAIVED")
    assert data["failure_reason"] in ("PED_CLEAR_SHORT", "WALK_SHORT", "PHASE_TOO_SHORT", None)
    if data["result"] == "PASS":
        assert data["failure_reason"] is None, "a passing check carries a null failure_reason"


def assert_priority_config(data: dict):
    assert_common_fields(data)
    assert data["priority_type"] in ("TSP", "EVP")
    assert data["approval_status"] in ("PROPOSED", "APPROVED", "REJECTED")
    assert data["deployment_status"] in ("NOT_DEPLOYED", "DEPLOYED", "SUSPENDED")
    assert 1 <= data["requested_max_extension_sec"] <= 40
    assert 0 <= data["max_early_green_sec"] <= 20
    assert 1 <= data["conflict_resolution_rank"] <= 9
    assert data["granted_extension_sec"] >= 0
    if data["deployment_status"] != "DEPLOYED":
        assert data["granted_extension_sec"] == 0, (
            "a configuration that is not DEPLOYED carries granted_extension_sec 0"
        )


def assert_field_observation(data: dict):
    assert_common_fields(data)
    assert data["tod_period"] in ("AM_PEAK", "MID_DAY", "PM_PEAK", "OFF_PEAK")
    assert data["finding_code"] in (
        "QUEUE_SPILLBACK",
        "EARLY_RETURN_TO_GREEN",
        "PED_CALL_MISSED",
        "DETECTION_FAULT",
        "PROGRESSION_BREAK",
        "NONE",
    )
    assert isinstance(data["requires_adjustment"], bool)
    assert data["resolution_status"] in ("OPEN", "ADDRESSED", "DISMISSED")
    assert isinstance(data["observer_user_id"], str) and data["observer_user_id"]


def assert_performance_evaluation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PROVISIONAL", "CERTIFIED", "INVALIDATED", "SUPERSEDED")
    assert data["metric_variant"] in ("PROVISIONAL_UNWEIGHTED", "CERTIFIED_WEIGHTED")
    assert isinstance(data["included_after_run_count"], int)


def assert_two_decimal_places(value: float, label: str = "value"):
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


def assert_four_decimal_places(value: float, label: str = "value"):
    assert round(float(value), 4) == float(value), (
        f"{label} must carry at most 4 decimal places, got {value}"
    )


def _instant(value):
    """Normalise an ISO 8601 UTC instant to (y, m, d, H, M, S, microsecond)."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    assert text.endswith("Z") or text.endswith("z"), (
        f"expected a UTC instant ending in Z, got {value!r}"
    )
    body = text[:-1]
    date_part, _, time_part = body.partition("T")
    seconds_part, _, frac = time_part.partition(".")
    micro = int((frac + "000000")[:6]) if frac else 0
    y, mo, d = (int(x) for x in date_part.split("-"))
    h, mi, s = (int(x) for x in seconds_part.split(":"))
    return (y, mo, d, h, mi, s, micro)


def assert_instant_equals(actual, expected, label: str = "timestamp"):
    """Compare two ISO 8601 UTC instants by value rather than by rendering.

    The PRD fixes a wire rendering only for `api_request_timestamp` (§2.2) and for
    `created_at` / `updated_at` (§2.4).  For the clock-stamped instants of §2.5 —
    `received_at`, `recorded_at`, `last_retimed_at`, `screened_at`,
    `last_tuning_completed_at` — and for client-supplied instants such as a run's
    `started_at`, the PRD states only the *value* the field takes ("the logical
    clock's current value", "the instant the probe vehicle entered the corridor")
    and never how many fractional digits the server renders.  The PRD-derivable
    assertion is therefore instant equality, not string equality.
    """
    assert _instant(actual) == _instant(expected), (
        f"{label} must be the instant {expected}, got {actual!r}"
    )
