"""Truancy-case opening, the non-linear tier-determination formula, the
record -> tier -> mentor-referral cascade, tier monotonicity, and the parallel
tier/status dimensions."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    fixtures as fx, TEST_USERS,
)

ADMIN = TEST_USERS["administrator_headers"]


def test_elementary_band_escalates_one_absence_sooner(api):
    """PRD §3.3: "For a student in the `ELEMENTARY` band, each of the four thresholds
    is lowered by one absence — an elementary student escalates one unexcused absence
    sooner — while a `SECONDARY` student's thresholds apply unchanged."

    Design: Difficulty/combinatorial_formula/tier_determination_nonlinear
    """
    school = fx.make_school(
        api, tier1_unexcused_threshold=2, tier2_unexcused_threshold=4,
        tier3_unexcused_threshold=6, court_unexcused_threshold=8,
    )
    student = fx.make_student(api, school["id"], grade_level=3)  # ELEMENTARY
    case = fx.make_case(api, student["id"])
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    data = validate_success(api.get_case(case["id"], ADMIN), 200)
    # effective tier1 = 2 - 1 (elementary adj) = 1; unexcused_count 1 meets it
    assert data["tier"] == "TIER_1"


def test_secondary_band_thresholds_unchanged(api):
    """PRD §3.3: "The base tier is the highest band the count reaches: ... otherwise
    `TIER_1` at the tier-1 threshold, and otherwise `NONE`."

    Design: Difficulty/combinatorial_formula/tier_determination_nonlinear
    """
    school = fx.make_school(
        api, tier1_unexcused_threshold=2, tier2_unexcused_threshold=4,
        tier3_unexcused_threshold=6, court_unexcused_threshold=8,
    )
    student = fx.make_student(api, school["id"], grade_level=9)  # SECONDARY
    case = fx.make_case(api, student["id"])
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    data = validate_success(api.get_case(case["id"], ADMIN), 200)
    # secondary adj = 0; tier1 threshold 2, unexcused_count 1 < 2 -> stays NONE
    assert data["tier"] == "NONE"


def test_second_unexcused_raises_case_to_tier_2(api):
    """PRD §2.7: "the student's counters are recomputed, which may raise the case's
    tier, which — on first entry into `TIER_2` — may synthesize a service referral."

    Design: Difficulty/transitive_cascade/record_to_tier_to_referral
    """
    school = fx.make_school(api, low_thresholds=True)
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")  # TIER_1
    fx.record_attendance(api, student["id"], "2026-09-02", "UNEXCUSED")  # TIER_2
    data = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert data["tier"] == "TIER_2"


def test_tier_2_entry_auto_creates_mentor_referral(api):
    """PRD §3.3: "On the case's first entry into `TIER_2` from any lower tier, the
    system automatically synthesizes a single `ServiceReferral` of `service_type`
    `MENTOR` with `auto_created` set to true — but only if the case has no existing
    referral currently in `REFERRED`, `ACCEPTED`, or `IN_PROGRESS`."

    Design: Difficulty/transitive_cascade/record_to_tier_to_referral
    """
    school = fx.make_school(api, low_thresholds=True)
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    fx.record_attendance(api, student["id"], "2026-09-02", "UNEXCUSED")
    data, meta = validate_paginated(api.list_service_referrals(case["id"], ADMIN))
    assert len(data) == 1
    assert data[0]["service_type"] == "MENTOR"
    assert data[0]["auto_created"] is True


def test_court_threshold_exact_flips_to_court_referred(api):
    """PRD §3.3: "The base tier is the highest band the count reaches: it is
    `COURT_REFERRED` when `unexcused_count` is at least the court threshold (minus one
    for elementary)."

    Design: Difficulty/boundary_precision_check/court_tier_threshold_exact
    """
    school = fx.make_school(api, low_thresholds=True)  # court threshold = 4
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    fx.add_unexcused_run(api, student["id"], 4)
    data = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert data["tier"] == "COURT_REFERRED"


def test_just_below_court_threshold_stays_tier_3(api):
    """PRD §3.3: "otherwise `TIER_3` when it is at least the tier-3 threshold (so
    adjusted), otherwise `TIER_2` at the tier-2 threshold."

    Design: Difficulty/boundary_precision_check/court_tier_threshold_exact
    """
    school = fx.make_school(api, low_thresholds=True)  # tier3 = 3, court = 4
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    fx.add_unexcused_run(api, student["id"], 3)
    data = validate_success(api.get_case(case["id"], ADMIN), 200)
    assert data["tier"] == "TIER_3"


def test_status_advances_independently_of_tier(api):
    """PRD §3.9: "The case status dimension advances under a `CaseManager`. A case moves
    `OPEN → MONITORING` only when it has a conference in `HELD`."

    Design: Difficulty/non_linear_state_machine/case_parallel_tier_status_dimensions
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api, low_thresholds=True)
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    fx.record_attendance(api, student["id"], "2026-09-02", "UNEXCUSED")  # TIER_2
    res = api.transition_case(case["id"], {"to_status": "MONITORING"}, ADMIN)
    data = validate_success(res, 200)
    assert data["status"] == "MONITORING"


def test_tier_unchanged_by_status_transition(api):
    """PRD §2.7: "Its `status` — one of `OPEN`, `MONITORING`, `RESOLVED`, or `CLOSED` —
    moves independently of the tier and governs the operational lifecycle."

    Design: Difficulty/non_linear_state_machine/case_parallel_tier_status_dimensions
    """
    school, staff, student, case, conf = fx.make_case_with_held_conference(api, low_thresholds=True)
    fx.record_attendance(api, student["id"], "2026-09-01", "UNEXCUSED")
    fx.record_attendance(api, student["id"], "2026-09-02", "UNEXCUSED")  # TIER_2
    res = api.transition_case(case["id"], {"to_status": "MONITORING"}, ADMIN)
    data = validate_success(res, 200)
    assert data["tier"] == "TIER_2"  # status advance did not touch tier


def test_manual_tier_regression_rejected(api):
    """PRD §3.3: "Any `to_tier` that is not strictly above the current tier, or that
    skips a step from an established tier, is rejected with `ERR_TIER_REGRESSION`."

    Design: Corner/state_machines/tier_manual_regression_rejected
    """
    school = fx.make_school(api, low_thresholds=True)
    student = fx.make_student(api, school["id"], grade_level=9)
    case = fx.make_case(api, student["id"])
    fx.add_unexcused_run(api, student["id"], 3)  # TIER_3
    res = api.transition_case(case["id"], {"to_tier": "TIER_1"}, ADMIN)
    validate_error(res, ApiErrorId.ERR_TIER_REGRESSION.value)


def test_get_case_not_found(api):
    """PRD §2.5: "the server validates them from left to right and rejects the request
    with `ERR_NOT_FOUND` at the first identifier that does not resolve to an existing
    resource."

    Design: Corner/entities/get_case_not_found
    """
    res = api.get_case("00000000-0000-0000-0000-000000000000", ADMIN)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
