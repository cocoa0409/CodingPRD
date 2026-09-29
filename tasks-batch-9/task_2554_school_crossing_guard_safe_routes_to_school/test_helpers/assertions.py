"""Entity shape assertions and cross-entity invariant checkers."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant into a timezone-aware datetime.

    The PRD pins the *value* every minted stamp carries ("derived from that clock's
    current value") but never pins a serialization for the domain stamps, so a
    comparison against an expected stamp is made on the instant, not on the string.
    """
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Any, expected: str, label: str) -> None:
    """The stamp names the same UTC instant as `expected`."""
    assert actual is not None, f"{label} must not be null"
    assert is_iso8601_timestamp(actual), \
        f"{label} must be an ISO 8601 UTC timestamp, got {actual!r}"
    assert parse_instant(actual) == parse_instant(expected), \
        f"expected {label} at instant {expected}, got {actual!r}"


def _assert_common_fields(data: Dict[str, Any], label: str) -> None:
    """Every resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be a positive integer, got {data.get('version')!r}"


def assert_two_decimals(value: float, label: str) -> None:
    """Scores and percentages are stored to two decimal places."""
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 2) == float(value), \
        f"{label} must carry at most 2 decimal places, got {value!r}"


def assert_four_decimals(value: float, label: str) -> None:
    assert value is not None, f"{label} must not be null"
    assert round(float(value), 4) == float(value), \
        f"{label} must carry at most 4 decimal places, got {value!r}"


def assert_integer_cents(value: Any, label: str) -> None:
    assert isinstance(value, int) and not isinstance(value, bool), \
        f"{label} must be an integer count of cents, got {value!r}"


def assert_school(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "School")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_code"], str) and data["district_code"]
    assert isinstance(data["enrollment_count"], int) and data["enrollment_count"] >= 1
    assert isinstance(data["no_school_dates"], list)
    assert isinstance(data["early_dismissal_dates"], list)
    assert isinstance(data["mode_share_surveys"], list)
    assert data["coverage_posture"] in ("OPEN", "RESTRICTED", "SUSPENDED"), \
        f"unexpected coverage_posture {data['coverage_posture']!r}"
    for counter in ("active_post_count", "covered_post_count", "uncovered_post_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0, \
            f"School.{counter} must be a non-negative integer"
    assert_two_decimals(data["coverage_rate_pct"], "School.coverage_rate_pct")
    assert_school_coverage_partition(data)


def assert_school_coverage_partition(data: Dict[str, Any]) -> None:
    """covered_post_count plus uncovered_post_count always equals active_post_count,
    and coverage_rate_pct and coverage_posture follow from that partition."""
    active = data["active_post_count"]
    covered = data["covered_post_count"]
    uncovered = data["uncovered_post_count"]
    assert covered + uncovered == active, (
        f"coverage partition broken: {covered} covered + {uncovered} uncovered "
        f"!= {active} active")
    rate = data["coverage_rate_pct"]
    if active == 0:
        expected_rate = 100.00
    else:
        expected_rate = round(100.0 * covered / active + 1e-9, 2)
    assert abs(rate - expected_rate) < 0.005, \
        f"coverage_rate_pct {rate} does not match {covered}/{active}"
    if uncovered == 0:
        expected_posture = "OPEN"
    elif rate < 50.00:
        expected_posture = "SUSPENDED"
    else:
        expected_posture = "RESTRICTED"
    assert data["coverage_posture"] == expected_posture, (
        f"coverage_posture {data['coverage_posture']} does not follow from "
        f"rate {rate} with {uncovered} uncovered posts")


def assert_intersection(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Intersection")
    assert is_valid_uuid(data["school_id"]), "Intersection.school_id must be a UUID"
    assert data["control_type"] in ("UNCONTROLLED", "STOP_SIGN", "SIGNALIZED")
    assert 5 <= data["speed_limit_mph"] <= 65, \
        f"speed_limit_mph must be between 5 and 65, got {data['speed_limit_mph']}"
    assert data["lanes_crossed"] >= 1
    assert isinstance(data["posted_school_zone"], bool)
    assert data["warrant_status"] in (
        "NOT_STUDIED", "UNDER_STUDY", "WARRANTED", "CONDITIONAL", "NOT_WARRANTED")
    assert isinstance(data["crash_history"], list)
    assert isinstance(data["pedestrian_crash_count_window"], int)
    assert isinstance(data["crash_severity_points"], int)
    assert isinstance(data["open_complaint_count"], int)
    assert data["open_complaint_count"] >= 0
    if data.get("latest_warrant_score") is not None:
        assert_two_decimals(data["latest_warrant_score"],
                            "Intersection.latest_warrant_score")


def assert_warrant_study(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WarrantStudy")
    assert is_valid_uuid(data["intersection_id"])
    assert data["status"] in (
        "DRAFT", "COUNTING", "ANALYZED", "WARRANTED", "CONDITIONAL", "NOT_WARRANTED")
    assert isinstance(data["count_sessions"], list)
    assert isinstance(data["recount_round"], int) and data["recount_round"] >= 0
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]
    if data.get("scoring_variant") is not None:
        assert data["scoring_variant"] in ("GAP_ADEQUACY", "EXPOSURE_INDEX")
    if data.get("warrant_score") is not None:
        assert_two_decimals(data["warrant_score"], "WarrantStudy.warrant_score")
        assert 0.0 <= data["warrant_score"] <= 100.0, \
            "warrant_score is capped at 100.0"
    if data.get("determination") is not None:
        assert data["determination"] in ("WARRANTED", "CONDITIONAL", "NOT_WARRANTED")


def assert_count_session(session: Dict[str, Any]) -> None:
    assert session["period"] in ("AM_ARRIVAL", "MIDDAY", "PM_DISMISSAL")
    assert session["observed_minutes"] >= 1
    for field in ("child_count", "adult_count", "vehicle_count", "adequate_gaps"):
        assert session[field] >= 0, f"count session {field} must be at least 0"
    assert isinstance(session["voided"], bool)


def assert_guard(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Guard")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_zone_code"], str) and data["home_zone_code"]
    assert data["certification_status"] in (
        "APPLICANT", "IN_TRAINING", "CERTIFIED", "SUSPENDED")
    assert data["duty_status"] in ("UNASSIGNED", "ASSIGNED", "ON_LEAVE")
    assert isinstance(data["substitute_pool_optin"], bool)
    assert isinstance(data["equipment_issued"], list)
    assert isinstance(data["equipment_complete"], bool)
    assert data["training_hours_completed"] >= 0
    assert data["hours_since_last_certification"] >= 0
    assert_two_decimals(data["reliability_score_rolling_90d"],
                        "Guard.reliability_score_rolling_90d")
    assert_two_decimals(data["reliability_score_season_to_date"],
                        "Guard.reliability_score_season_to_date")
    assert_equipment_completeness(data)


def assert_equipment_completeness(data: Dict[str, Any]) -> None:
    """equipment_complete is true exactly when all three required item types
    have been issued at least once."""
    issued = {item["item_type"] for item in data.get("equipment_issued", [])}
    expected = {"HIGH_VIS_VEST", "STOP_PADDLE", "WHISTLE"}.issubset(issued)
    assert data["equipment_complete"] is expected, (
        f"equipment_complete is {data['equipment_complete']} but issued item types "
        f"are {sorted(issued)}")


def assert_guard_post(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "GuardPost")
    assert is_valid_uuid(data["intersection_id"])
    assert data["required_shift"] in ("AM", "PM", "BOTH")
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED")
    assert data["coverage_status"] in ("UNSTAFFED", "UNCOVERED", "COVERED")
    assert isinstance(data["open_gap_count"], int) and data["open_gap_count"] >= 0
    assert isinstance(data["zone_code"], str) and data["zone_code"]


def assert_post_assignment(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "PostAssignment")
    assert is_valid_uuid(data["guard_post_id"])
    assert is_valid_uuid(data["guard_id"])
    assert data["shift"] in ("AM", "PM", "BOTH")
    assert data["status"] in (
        "SCHEDULED", "ACTIVE", "ENDED", "VACATED", "SUPERSEDED")
    assert data["start_date"] <= data["end_date"], \
        "assignment start_date must not be after end_date"
    assert isinstance(data["open_absence_count"], int)
    assert data["open_absence_count"] >= 0
    assert data["coverage_state"] in ("STAFFED", "GAP")
    expected_state = "GAP" if data["open_absence_count"] > 0 else "STAFFED"
    assert data["coverage_state"] == expected_state, (
        f"coverage_state {data['coverage_state']} does not follow from "
        f"open_absence_count {data['open_absence_count']}")


def assert_absence_report(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "AbsenceReport")
    assert is_valid_uuid(data["post_assignment_id"])
    assert is_valid_uuid(data["guard_id"])
    assert data["shift"] in ("AM", "PM", "BOTH")
    assert data["reason"] in ("ILLNESS", "FAMILY", "WEATHER", "TRAINING", "UNEXCUSED")
    assert data["status"] in (
        "DISPATCH_PENDING", "OFFER_OUT", "UNCOVERED_GAP", "COVERED", "RESCINDED")
    assert data["urgency_tier"] in ("SAME_DAY", "SHORT", "STANDARD")
    assert is_iso8601_timestamp(data["shift_start_utc"]), \
        "shift_start_utc must be an ISO 8601 UTC instant"
    assert isinstance(data["dispatch_offers"], list)
    assert isinstance(data["excluded_guard_ids"], list)
    assert isinstance(data["dispatch_attempt_count"], int)
    assert data["dispatch_attempt_count"] >= 0
    assert_urgency_tier_matches_notice(data)
    if data.get("substitute_cost_cents") is not None:
        assert_integer_cents(data["substitute_cost_cents"],
                             "AbsenceReport.substitute_cost_cents")
    if data["status"] != "COVERED":
        assert data.get("substitute_cost_cents") is None, (
            "substitute_cost_cents stays null on a report that never reached COVERED")


def assert_urgency_tier_matches_notice(data: Dict[str, Any]) -> None:
    """SAME_DAY below 12 hours of notice, SHORT from 12 up to 48, STANDARD at 48+."""
    notice = float(data["notice_hours"])
    if notice < 12:
        expected = "SAME_DAY"
    elif notice < 48:
        expected = "SHORT"
    else:
        expected = "STANDARD"
    assert data["urgency_tier"] == expected, (
        f"urgency_tier {data['urgency_tier']} does not follow from "
        f"notice_hours {notice}")


def assert_dispatch_offer(offer: Dict[str, Any], attempt_number: int,
                          offered_guard_id: str, offer_status: str) -> None:
    assert offer["attempt_number"] == attempt_number, (
        f"expected attempt_number {attempt_number}, got {offer['attempt_number']}")
    assert offer["offered_guard_id"] == offered_guard_id
    assert offer["offer_status"] == offer_status, (
        f"expected offer_status {offer_status}, got {offer['offer_status']}")
    assert is_iso8601_timestamp(offer["offered_at"])
    assert is_iso8601_timestamp(offer["offer_expires_at"])


def assert_walking_route(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WalkingRoute")
    assert is_valid_uuid(data["school_id"])
    assert data["status"] in ("DRAFT", "PUBLISHED", "ADVISORY_HOLD", "RETIRED")
    assert isinstance(data["segments"], list) and len(data["segments"]) >= 1
    assert data["segment_count"] == len(data["segments"]), (
        f"segment_count {data['segment_count']} must equal the number of segments "
        f"({len(data['segments'])})")
    orders = sorted(seg["segment_order"] for seg in data["segments"])
    assert orders == list(range(1, len(orders) + 1)), \
        f"segment_order values must be exactly 1..N, got {orders}"
    for seg in data["segments"]:
        assert seg["hazard_type"] in (
            "NO_SIDEWALK", "UNCONTROLLED_CROSSING", "HIGH_SPEED_ARTERIAL",
            "RAIL_CROSSING", "DRIVEWAY_CONFLICT", "POOR_LIGHTING")
        assert seg["length_ft"] >= 1
        assert isinstance(seg["mitigated"], bool)
    assert_two_decimals(data["hazard_score"], "WalkingRoute.hazard_score")
    if data["status"] == "DRAFT":
        assert data["published_at"] is None, "a DRAFT route has no published_at"
        assert data["hold_reason"] is None
    if data["status"] == "ADVISORY_HOLD":
        assert data["hold_reason"] == "SCHOOL_COVERAGE_SUSPENDED"
    if data["status"] == "PUBLISHED":
        assert data["hold_reason"] is None, \
            "hold_reason is cleared when a route returns to PUBLISHED"


def assert_complaint(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Complaint")
    assert is_valid_uuid(data["intersection_id"])
    assert data["complaint_type"] in (
        "SPEEDING", "NEAR_MISS", "FAILURE_TO_YIELD", "SIGHT_OBSTRUCTION",
        "SIGNAL_TIMING")
    assert data["severity_claim"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in (
        "RECEIVED", "TRIAGED", "REFERRED", "RESOLVED", "CLOSED_NO_ACTION")
    if data.get("disposition") is not None:
        assert data["disposition"] in ("REFER_TO_ENGINEERING", "CLOSE_NO_ACTION")
    assert isinstance(data["reporter_name"], str) and data["reporter_name"]


def assert_grant_program(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "GrantProgram")
    assert_integer_cents(data["total_cents"], "GrantProgram.total_cents")
    assert_integer_cents(data["committed_cents"], "GrantProgram.committed_cents")
    assert_integer_cents(data["remaining_cents"], "GrantProgram.remaining_cents")
    assert data["total_cents"] >= 1
    assert data["committed_cents"] >= 0
    assert data["remaining_cents"] >= 0
    assert isinstance(data["funded_project_count"], int)
    assert isinstance(data["deferred_project_count"], int)
    assert_integer_cents(data["next_cycle_carryover_cents"],
                         "GrantProgram.next_cycle_carryover_cents")
    assert_grant_ledger_conserved(data)


def assert_grant_ledger_conserved(data: Dict[str, Any]) -> None:
    """total_cents always equals committed_cents plus remaining_cents."""
    assert data["committed_cents"] + data["remaining_cents"] == data["total_cents"], (
        f"grant ledger broken: committed {data['committed_cents']} + remaining "
        f"{data['remaining_cents']} != total {data['total_cents']}")


def assert_infrastructure_project(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "InfrastructureProject")
    assert is_valid_uuid(data["grant_program_id"])
    assert is_valid_uuid(data["intersection_id"])
    assert data["project_type"] in (
        "RRFB", "CURB_EXTENSION", "SIDEWALK_INFILL", "SIGNAL_RETIMING",
        "RAISED_CROSSWALK")
    assert data["status"] in ("PROPOSED", "SCORED", "FUNDED", "DEFERRED")
    assert_integer_cents(data["requested_cost_cents"],
                         "InfrastructureProject.requested_cost_cents")
    assert data["requested_cost_cents"] >= 1
    assert data["students_benefited"] >= 0
    assert_integer_cents(data["awarded_cents"], "InfrastructureProject.awarded_cents")
    if data.get("benefit_points") is not None:
        assert_four_decimals(data["benefit_points"],
                             "InfrastructureProject.benefit_points")
    if data.get("cost_factor") is not None:
        assert_four_decimals(data["cost_factor"], "InfrastructureProject.cost_factor")
        assert data["cost_factor"] >= 1.00, "cost_factor is floored at 1.00"
    if data.get("benefit_cost_score") is not None:
        assert_two_decimals(data["benefit_cost_score"],
                            "InfrastructureProject.benefit_cost_score")
    if data["status"] == "FUNDED":
        assert data["awarded_cents"] == data["requested_cost_cents"], \
            "a FUNDED project's awarded_cents equals its requested_cost_cents"
    else:
        assert data["awarded_cents"] == 0, \
            "awarded_cents is 0 on any project that is not FUNDED"


def assert_clock_response(data: Dict[str, Any], expected_utc: str,
                          activated: Optional[int] = None,
                          ended: Optional[int] = None) -> None:
    assert_same_instant(data.get("current_utc"), expected_utc, "current_utc")
    if activated is not None:
        assert data["activated_assignment_count"] == activated, (
            f"expected activated_assignment_count {activated}, got "
            f"{data.get('activated_assignment_count')}")
    if ended is not None:
        assert data["ended_assignment_count"] == ended, (
            f"expected ended_assignment_count {ended}, got "
            f"{data.get('ended_assignment_count')}")


def assert_pagination_meta(meta: Dict[str, Any], limit: int, offset: int,
                           total_count: int, has_more: bool) -> None:
    assert meta["limit"] == limit, f"expected limit {limit}, got {meta.get('limit')}"
    assert meta["offset"] == offset, f"expected offset {offset}, got {meta.get('offset')}"
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta.get('total_count')}")
    assert meta["has_more"] is has_more, (
        f"expected has_more {has_more}, got {meta.get('has_more')}")


def assert_ascending_created_at(items: List[Dict[str, Any]]) -> None:
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), \
        f"collection must be ordered by ascending created_at, got {stamps}"


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any],
                     *fields: str) -> None:
    """A rejected write leaves the named fields exactly as they were."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"{field} changed from {before.get(field)!r} to {after.get(field)!r} "
            f"even though the request was rejected")
