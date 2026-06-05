"""Satisfaction surveys and the departmental satisfaction average.

Queue A (Difficulty): the round-half-up satisfaction average ({5,5,4} -> 4.67).
Queue B (Corner): the empty-set null average and the invalid-score response
rejection.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    fixtures as fx,
    TEST_USERS,
    make_agent_headers,
    make_citizen_headers,
)
from test_helpers.api_errors import ApiErrorId

DISPATCHER = TEST_USERS["dispatcher_headers"]


def _resolve_and_score(api, dept_id, category_id, agent_id, score):
    """File -> triage -> route -> assign -> start -> complete -> respond with score.
    Returns nothing; the survey reaches COMPLETED for this department."""
    citizen = fx.create_citizen()
    request = fx.create_request(citizen["id"], category_id)
    fx.triage_request(request["id"])
    fx.route_request(request["id"])
    wo = fx.get_work_order_for_request(request["id"])
    fx.assign_and_start(wo["id"], agent_id)
    validate_success(
        api.complete_work_order(wo["id"], {"completion_note": "done"}, make_agent_headers(agent_id)),
        200,
    )
    survey = fx.get_survey_for_request(request["id"])
    validate_success(
        api.respond_survey(survey["id"], {"score": score}, make_citizen_headers(citizen["id"])),
        200,
    )


# ---------------------------------------------------------------------------
# Queue A — Difficulty: round-half-up satisfaction average
# ---------------------------------------------------------------------------
def test_satisfaction_average_round_half_up(api):
    """PRD §2.11: "Where the system computes an average, it produces a value rounded to
    exactly two decimal places using the round-half-up convention. This applies to the
    departmental satisfaction average, where a set of scores `{5, 5, 4}` averages to
    fourteen thirds and is reported as 4.67 rather than the truncated 4.66."

    Design: Difficulty/dual_variant_calc/avg_satisfaction_round_half_up_vs_truncate
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=50)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"])
    agent = fx.create_agent(dept["id"])
    for score in (5, 5, 4):
        _resolve_and_score(api, dept["id"], category["id"], agent["id"], score)
    data = validate_success(api.get_department_satisfaction(dept["id"], DISPATCHER), 200)
    assert data["avg_score"] == pytest.approx(4.67, abs=0.001)
    assert data["completed_count"] == 3


def test_satisfaction_average_excludes_truncation(api):
    """PRD §2.11: "a set of scores `{5, 5, 4}` averages to fourteen thirds and is
    reported as 4.67 rather than the truncated 4.66."

    Design: Difficulty/dual_variant_calc/avg_satisfaction_round_half_up_vs_truncate
    """
    fx.set_clock("2026-06-01T08:00:00Z")
    dept = fx.create_department(backlog_threshold=50)
    category = fx.create_category(dept["id"], requires_geolocation=False)
    fx.create_sla_policy(category["id"])
    agent = fx.create_agent(dept["id"])
    for score in (5, 5, 4):
        _resolve_and_score(api, dept["id"], category["id"], agent["id"], score)
    data = validate_success(api.get_department_satisfaction(dept["id"], DISPATCHER), 200)
    assert data["avg_score"] != pytest.approx(4.66, abs=0.001), (
        "truncated 4.66 is the rejected interpretation"
    )


# ---------------------------------------------------------------------------
# Queue B — Corner: empty set yields null average
# ---------------------------------------------------------------------------
def test_satisfaction_empty_set_yields_null(api):
    """PRD §3.10: "a department with no completed surveys reports a null `avg_score`
    and a `completed_count` of zero rather than a zero average."

    Design: Corner/calculations/avg_satisfaction_empty_set_yields_null
    """
    dept = fx.create_department(backlog_threshold=5)
    data = validate_success(api.get_department_satisfaction(dept["id"], DISPATCHER), 200)
    assert data["completed_count"] == 0
    assert data["avg_score"] is None


# ---------------------------------------------------------------------------
# Queue B — Corner: invalid score rejected
# ---------------------------------------------------------------------------
def test_survey_invalid_score_rejected(api):
    """PRD §3.10: "and the `score` to be an integer within 1 through 5; a score outside
    that range is rejected with `ERR_INVALID_SCORE` (HTTP 422)."

    Design: Corner/validations/survey_invalid_score_rejected
    """
    env = fx.setup_resolved_request()
    survey = fx.get_survey_for_request(env["request"]["id"])
    resp = api.respond_survey(
        survey["id"], {"score": 6}, make_citizen_headers(env["citizen"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SCORE.value, 422)
