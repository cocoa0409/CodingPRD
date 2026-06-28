"""Benchmark results, verification, personal records, and leaderboards.

Queue A: leaderboard time-ascending multi-input ranking, empty leaderboard.
Queue B: first-verified-is-PR, load-tie-is-not-PR, load-descending order,
value <= 0 invalid request.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    make_member_headers, make_coach_headers,
    set_clock, create_coach, create_track, register_member,
    create_unlimited_plan,
    record_and_verify_result, make_leaderboard_eligible_member,
)
from test_helpers import api_client

BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ==========================================================================
# Queue A — combinatorial_formula / leaderboard_multi_input_conditional_tiebreak_mode_a
# ==========================================================================

def test_leaderboard_time_ascending_three_members(api):
    """PRD §3.6: "The ranking then orders these bests: ascending for `TIME_SECONDS`, so the fastest time ranks first, and descending for `LOAD_KG`, so the heaviest load ranks first."

    Design: Difficulty/combinatorial_formula/leaderboard_multi_input_conditional_tiebreak_mode_a
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(requires_foundations=False)
    a = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-01T18:00:00Z")
    b = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-02T18:00:00Z")
    c = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-03T18:00:00Z")
    record_and_verify_result(a["id"], coach["id"], "FRAN", "TIME_SECONDS", 180,
                             "2026-05-01T10:00:00Z")
    record_and_verify_result(b["id"], coach["id"], "FRAN", "TIME_SECONDS", 200,
                             "2026-05-01T10:00:00Z")
    record_and_verify_result(c["id"], coach["id"], "FRAN", "TIME_SECONDS", 210,
                             "2026-05-01T10:00:00Z")

    resp = api.get_leaderboard(track["id"], make_member_headers(a["id"]),
                               params={"benchmark_name": "FRAN"})
    data, meta = validate_paginated(resp)
    assert len(data) == 3
    assert data[0]["member_id"] == a["id"] and data[0]["value"] == 180
    assert data[1]["member_id"] == b["id"] and data[1]["value"] == 200
    assert data[2]["member_id"] == c["id"] and data[2]["value"] == 210


def test_leaderboard_time_tie_broken_by_earlier_recorded_at(api):
    """PRD §3.6: "When two members' bests tie, the earlier `recorded_at` of the best-defining result ranks higher".
    PRD §3.6: "ascending for `TIME_SECONDS`, so the fastest time ranks first".

    Design: Difficulty/combinatorial_formula/leaderboard_multi_input_conditional_tiebreak_mode_a
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(requires_foundations=False)
    a = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-01T18:00:00Z")
    b = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-02T18:00:00Z")
    # Equal best time 190s; member a recorded earlier -> ranks first.
    record_and_verify_result(a["id"], coach["id"], "GRACE", "TIME_SECONDS", 190,
                             "2026-05-01T10:00:00Z")
    record_and_verify_result(b["id"], coach["id"], "GRACE", "TIME_SECONDS", 190,
                             "2026-05-02T10:00:00Z")

    resp = api.get_leaderboard(track["id"], make_member_headers(a["id"]),
                               params={"benchmark_name": "GRACE"})
    data, meta = validate_paginated(resp)
    assert len(data) == 2
    assert data[0]["member_id"] == a["id"]
    assert data[1]["member_id"] == b["id"]


# ==========================================================================
# Queue A — boundary_precision_check / empty_leaderboard_returns_empty_array
# ==========================================================================

def test_empty_leaderboard_returns_empty_array(api):
    """PRD §3.6: "The candidate set is the verified benchmark results for that `benchmark_name` belonging to members who hold an `ACTIVE` membership on a plan attached to a session of the requested track, reduced to one best row per member."

    Design: Difficulty/boundary_precision_check/empty_leaderboard_returns_empty_array
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    member = register_member()
    # An UNVERIFIED FRAN result exists; verified filter excludes it.
    get = validate_success(api.create_benchmark_result(
        {"member_id": member["id"], "benchmark_name": "FRAN",
         "metric_kind": "TIME_SECONDS", "value": 190,
         "recorded_at": "2026-05-01T10:00:00Z"},
        make_member_headers(member["id"]),
    ), expected_status=201)
    assert get["verified"] is False

    resp = api.get_leaderboard(track["id"], make_member_headers(member["id"]),
                               params={"benchmark_name": "FRAN"})
    data, meta = validate_paginated(resp)
    assert len(data) == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


def test_leaderboard_no_results_at_all_returns_empty_array(api):
    """PRD §3.6: "The candidate set is the verified benchmark results for that `benchmark_name` belonging to members who hold an `ACTIVE` membership on a plan attached to a session of the requested track, reduced to one best row per member."

    Design: Difficulty/boundary_precision_check/empty_leaderboard_returns_empty_array
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    # No benchmark results recorded at all.
    resp = api.get_leaderboard(track["id"], BOX, params={"benchmark_name": "MURPH"})
    data, meta = validate_paginated(resp)
    assert len(data) == 0
    assert meta["total_count"] == 0
    assert meta["has_more"] is False


# ==========================================================================
# Queue B — calculations / pr_determination_first_verified_is_pr
# ==========================================================================

def test_first_verified_result_is_pr(api):
    """PRD §3.6: "If there is no such prior verified result, this result is a
    personal record."
    PRD §3.6: "Verification sets the result's `verified` flag to true, recomputes its `is_pr` flag, and increments the result's `version`."

    Design: Corner/calculations/pr_determination_first_verified_is_pr
    """
    coach = create_coach(certified=True)
    member = register_member()
    result = record_and_verify_result(member["id"], coach["id"], "FRAN",
                                       "TIME_SECONDS", 180, "2026-05-01T10:00:00Z")
    assert result["verified"] is True
    assert result["is_pr"] is True


# ==========================================================================
# Queue B — calculations / pr_determination_load_tie_is_not_pr
# ==========================================================================

def test_load_equal_value_is_not_pr(api):
    """PRD §3.6: "for a `LOAD_KG` benchmark (higher is better) it is a personal record exactly when its `value` is strictly greater than the best — that is, the largest — prior verified value. Equal values are never a personal record."

    Design: Corner/calculations/pr_determination_load_tie_is_not_pr
    """
    coach = create_coach(certified=True)
    member = register_member()
    record_and_verify_result(member["id"], coach["id"], "BACK_SQUAT_1RM",
                             "LOAD_KG", 100, "2026-05-01T10:00:00Z")
    second = record_and_verify_result(member["id"], coach["id"], "BACK_SQUAT_1RM",
                                      "LOAD_KG", 100, "2026-05-08T10:00:00Z")
    assert second["verified"] is True
    assert second["is_pr"] is False


# ==========================================================================
# Queue B — calculations / leaderboard_load_descending_order
# ==========================================================================

def test_leaderboard_load_descending_order(api):
    """PRD §3.6: "descending for `LOAD_KG`, so the heaviest load ranks first."

    Design: Corner/calculations/leaderboard_load_descending_order
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    plan = create_unlimited_plan(requires_foundations=False)
    a = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-01T18:00:00Z")
    b = make_leaderboard_eligible_member(coach["id"], track["id"], plan["id"],
                                         "2026-02-02T18:00:00Z")
    record_and_verify_result(a["id"], coach["id"], "DEADLIFT_1RM", "LOAD_KG", 200,
                             "2026-05-01T10:00:00Z")
    record_and_verify_result(b["id"], coach["id"], "DEADLIFT_1RM", "LOAD_KG", 220,
                             "2026-05-01T10:00:00Z")

    resp = api.get_leaderboard(track["id"], make_member_headers(a["id"]),
                               params={"benchmark_name": "DEADLIFT_1RM"})
    data, meta = validate_paginated(resp)
    assert data[0]["member_id"] == b["id"] and data[0]["value"] == 220
    assert data[1]["member_id"] == a["id"] and data[1]["value"] == 200


# ==========================================================================
# Queue B — errors / error_invalid_request_value_not_positive
# ==========================================================================

def test_benchmark_value_not_positive_returns_invalid_request(api):
    """PRD §3.6: "the `value` (interpreted as seconds for `TIME_SECONDS` benchmarks and kilograms for `LOAD_KG` benchmarks, and required to be strictly greater than 0)".
    PRD §2.10: "Only then are request-body shape and type checks applied, yielding `ERR_INVALID_REQUEST` for missing required fields, wrong types, out-of-range numbers, or out-of-set enum values".

    Design: Corner/errors/error_invalid_request_value_not_positive
    """
    member = register_member()
    resp = api.create_benchmark_result(
        {"member_id": member["id"], "benchmark_name": "FRAN",
         "metric_kind": "TIME_SECONDS", "value": 0,
         "recorded_at": "2026-05-01T10:00:00Z"},
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)
