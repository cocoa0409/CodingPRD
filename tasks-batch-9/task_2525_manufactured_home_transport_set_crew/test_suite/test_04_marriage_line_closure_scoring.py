"""Closure scoring rounds twice, deliberately, and the order is observable.

Each joint's `deviation_score` is rounded to two decimals as the joint is
recorded, and the job's `closure_score` is the sum of those already-rounded
figures rounded again. Two joints whose raw deviation is exactly 0.125 inches
therefore close the line at 0.26 rather than at the 0.25 a single final rounding
would produce.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_marriage_joint,
    assert_set_job,
    make_set_crew_lead_headers,
    read_set_job,
    record_marriage_joint,
    setup_dispatched_set_job,
    validate_success,
)

# A gap of 0.375 inches exceeds the quarter-inch allowance by 0.125 inches at
# weight 1.0, with no offset and no shim contribution — so each joint's raw
# deviation is exactly 0.1250 and rounds half up to 0.13.
JOINT_GAP_IN = 0.375
EXPECTED_JOINT_DEVIATION = 0.13
EXPECTED_CLOSURE_SCORE = 0.26
MISTAKEN_CLOSURE_SCORE = 0.25
# Half of the last decimal place the closure score is carried to, so the
# assertion still separates 0.26 from 0.25.
SCORE_TOLERANCE = 0.005


def _build_dispatched_three_section_job_with_two_joints():
    """A dispatched three-section AZ set job carrying two half-tolerance joints.

    Every floor is delivered and the site passes readiness with six piers per
    section, so the crew can be dispatched; two marriage joints are then recorded
    with a 0.375-inch gap, a zero vertical offset and no ridge-beam shim.
    """
    scenario = setup_dispatched_set_job(section_count=3)
    job_id = scenario["set_job"]["id"]
    crew_id = scenario["set_crew"]["id"]
    scenario["joints"] = [
        record_marriage_joint(
            job_id,
            crew_id,
            joint_index=index,
            gap_in=JOINT_GAP_IN,
            vertical_offset_in=0.0,
            ridge_beam_shim_in=0.0,
        )
        for index in (1, 2)
    ]
    return scenario


def _close_the_line(job_id, crew_id):
    return validate_success(
        api_client.close_marriage_line(
            job_id, {}, make_set_crew_lead_headers(crew_id)
        ),
        200,
    )


def test_closure_score_sums_already_rounded_per_joint_deviations():
    """PRD §3.7: "Each joint's `deviation_score` is computed at the moment it is
    recorded and is a penalty for exceeding tolerance rather than a measure of the
    raw reading: the gap contributes, at weight 1.0, however much the gap exceeds
    a quarter of an inch (0.25 inches), and nothing at all if the gap is 0.25
    inches or less; the vertical offset contributes, at weight 0.6, however much
    the *absolute value* of the offset exceeds half an inch (0.5 inches), and
    nothing at all if that absolute value is 0.5 inches or less; and the shim
    contributes its full thickness at weight 0.4, with no tolerance allowance.
    Those three contributions are added and the sum is rounded half up to two
    decimal places, and that rounded figure is stored as the joint's
    `deviation_score`."
    PRD §3.7: "The job's `closure_score` is then the sum of the
    **already-rounded** per-joint `deviation_score` values, taken in ascending
    `joint_index` order, with that sum itself rounded half up to two decimal
    places."
    PRD §3.7: "The rounding order is pinned and it matters: rounding each joint
    first and then summing the rounded values is the specified reading, and
    summing the unrounded deviations and rounding once at the end is the wrong one
    — three joints whose raw deviations are each 0.125 give a `closure_score` of
    0.39 under the pinned order and 0.38 under the mistaken one."

    Design: Difficulty/combinatorial_formula/marriage_line_round_per_joint_then_sum
    """
    scenario = _build_dispatched_three_section_job_with_two_joints()

    for joint in scenario["joints"]:
        assert_marriage_joint(joint)
        assert joint["deviation_score"] == pytest.approx(
            EXPECTED_JOINT_DEVIATION, abs=SCORE_TOLERANCE
        ), (
            "a raw deviation of 0.125 rounds half up to "
            f"{EXPECTED_JOINT_DEVIATION}, got {joint['deviation_score']}"
        )

    closed = _close_the_line(
        scenario["set_job"]["id"], scenario["set_crew"]["id"]
    )
    assert closed["closure_score"] == pytest.approx(
        EXPECTED_CLOSURE_SCORE, abs=SCORE_TOLERANCE
    ), (
        "summing the two already-rounded 0.13 figures gives "
        f"{EXPECTED_CLOSURE_SCORE}, got {closed['closure_score']}"
    )
    assert closed["closure_score"] != pytest.approx(
        MISTAKEN_CLOSURE_SCORE, abs=SCORE_TOLERANCE
    ), (
        "summing the raw 0.125 deviations and rounding once at the end would give "
        f"{MISTAKEN_CLOSURE_SCORE}, which is the wrong reading, got "
        f"{closed['closure_score']}"
    )


def test_closing_the_line_writes_the_verdict_and_moves_progress_only():
    """PRD §3.7: "The job's `SetCrewLead` closes the marriage line, which moves
    `progress_status` `DISPATCHED → SET_COMPLETE`."
    PRD §3.7: "The verdict lands in `closure_status`: `NOT_APPLICABLE` when the
    joint count is zero, otherwise `PASS` when the `closure_score` is at most
    1.00, otherwise `FAIL`."
    PRD §3.7: "Closing raises the job's `version`, re-derives the order's
    posture, and leaves `scope_status` unchanged."
    PRD §3.7: "Dispatching, closing the marriage line and the final inspection
    move `progress_status` only and leave `scope_status` untouched; recording the
    scope split and recording the utility crossover move `scope_status` only and
    leave `progress_status` untouched."

    Design: Difficulty/combinatorial_formula/marriage_line_round_per_joint_then_sum
    """
    scenario = _build_dispatched_three_section_job_with_two_joints()
    job_id = scenario["set_job"]["id"]

    before = read_set_job(job_id)
    assert before["progress_status"] == "DISPATCHED", (
        f"the line is closed from DISPATCHED, got {before['progress_status']}"
    )
    assert before["scope_status"] == "SCOPE_PENDING", (
        "the scope dimension starts at SCOPE_PENDING, got "
        f"{before['scope_status']}"
    )

    closed = _close_the_line(job_id, scenario["set_crew"]["id"])
    assert_set_job(closed)

    assert closed["closure_status"] == "PASS", (
        "a closure score of 0.26 is at most 1.00, so the verdict is PASS, got "
        f"{closed['closure_status']}"
    )
    assert closed["progress_status"] == "SET_COMPLETE", (
        "closing the line moves DISPATCHED -> SET_COMPLETE, got "
        f"{closed['progress_status']}"
    )
    assert closed["scope_status"] == "SCOPE_PENDING", (
        "closing the line leaves scope_status untouched at SCOPE_PENDING, got "
        f"{closed['scope_status']}"
    )
    assert closed["version"] > before["version"], (
        "closing the line raises the job's version, got "
        f"{closed['version']} against {before['version']}"
    )
