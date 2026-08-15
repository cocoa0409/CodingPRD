"""Satisfaction surveys and agent coaching (PRD §3.8): single-survey issuance,
submit lockdown, the pinned recency-weighted calculation, and the coaching-hold
ticket-release cascade."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    make_employee_headers,
    assert_csat,
    setup_queue,
    setup_ticket_resolved,
    create_ticket_for,
    assign_ticket,
    resolve_ticket,
    survey_for_ticket,
    submit_survey_score,
    resolve_and_submit_survey,
    get_ticket,
    events_of,
)

ADMIN = TEST_USERS["admin_headers"]


def test_survey_double_submit_rejected(api):
    """PRD §3.8: "Two distinct rejections guard the calendar and the state. Lazy
    expiry means a survey whose `expires_at` has passed fails submission with
    `ERR_SURVEY_EXPIRED` even if its stored status still reads `ISSUED`; separately,
    submitting a survey that is already `SUBMITTED`, or one the clock sweep has
    already moved to `EXPIRED` — the sweep flips any `ISSUED` survey whose expiry is
    strictly in the past — fails the state check with `ERR_SURVEY_INVALID_STATE`."

    Design: Corner/state_machines/survey_double_submit_rejected
    """
    ctx = setup_ticket_resolved()
    survey = ctx["survey"]
    assert survey["status"] == "ISSUED"

    submitted = submit_survey_score(survey["id"], ctx["employee"]["id"], 4)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["score"] == 4

    resp = api.submit_survey(survey["id"], {"score": 5},
                             make_employee_headers(ctx["employee"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SURVEY_INVALID_STATE.value)

    after = validate_success(api.get_survey(survey["id"], ADMIN))
    assert after["score"] == 4, "a rejected resubmission must not overwrite the score"


def _csat_history_5_4_2(api):
    """Scores 5, 4, 2 submitted at ages 0, 7, 28 days (read at 2026-08-29)."""
    ctx = setup_queue(first_response_minutes=480, resolution_minutes=480)
    resolve_and_submit_survey(ctx, "t1", 2)                                  # 2026-08-01
    resolve_and_submit_survey(ctx, "t2", 4, clock_iso="2026-08-22T00:00:00Z")  # age 7d
    resolve_and_submit_survey(ctx, "t3", 5, clock_iso="2026-08-29T00:00:00Z")  # age 0d
    return ctx


def test_csat_metrics_reports_simple_mean(api):
    """PRD §3.8: "A `simple_mean` — the sum of the scores divided by their count,
    rounded half-up to two decimals — is computed alongside: scores of 5, 4, and 2 at
    ages 0, 7, and 28 days give a simple mean of 3.67 against a recency-weighted mean
    of 4.26."
    PRD §3.6: "The satisfaction metric for an `agent_id` recomputes the figures of
    §3.8 on read, reporting `window_days`, the in-window `survey_count`, the
    `simple_mean`, and the `recency_weighted_mean`."

    Design: Difficulty/dual_variant_calc/csat_simple_vs_recency_weighted
    """
    ctx = _csat_history_5_4_2(api)

    metrics = validate_success(api.get_csat_metrics(ADMIN, params={"agent_id": ctx["agent"]["id"]}))
    assert metrics["survey_count"] == 3
    assert_csat(metrics["simple_mean"], 3.67)


def test_csat_metrics_reports_recency_weighted_mean(api):
    """PRD §3.8: "Each weighted term — the score times the weight — is rounded
    half-up to two decimal places first; only then are the terms summed, the sum
    divided by the sum of the weights, and the quotient rounded half-up to two
    decimal places to form the `recency_weighted_mean`."
    PRD §3.8: "A `simple_mean` — the sum of the scores divided by their count,
    rounded half-up to two decimals — is computed alongside: scores of 5, 4, and 2 at
    ages 0, 7, and 28 days give a simple mean of 3.67 against a recency-weighted mean
    of 4.26."

    Design: Difficulty/dual_variant_calc/csat_simple_vs_recency_weighted
    """
    ctx = _csat_history_5_4_2(api)

    metrics = validate_success(api.get_csat_metrics(ADMIN, params={"agent_id": ctx["agent"]["id"]}))
    assert metrics["survey_count"] == 3
    assert_csat(metrics["recency_weighted_mean"], 4.26)
    assert metrics["simple_mean"] != metrics["recency_weighted_mean"], (
        "recency weighting must diverge from the flat mean for aged scores"
    )


def _csat_history_1_1_2(api):
    """Scores 1, 1, 2 at ages 0, 0, 12 days (read at 2026-08-13)."""
    ctx = setup_queue(first_response_minutes=480, resolution_minutes=480)
    resolve_and_submit_survey(ctx, "t1", 2)                                  # 2026-08-01 (12d old)
    resolve_and_submit_survey(ctx, "t2", 1, clock_iso="2026-08-13T00:00:00Z")  # age 0d
    resolve_and_submit_survey(ctx, "t3", 1)                                  # age 0d
    return ctx


def test_csat_recency_weighted_mean_follows_pinned_rounding_order(api):
    """PRD §3.8: "The rounding order is part of the contract: scores of 1, 1, and 2
    at ages 0, 0, and 12 days yield 1.21 under the pinned order, where summing the
    unrounded products and rounding once would yield 1.22."

    Design: Difficulty/combinatorial_formula/csat_rounding_order_pinned
    """
    ctx = _csat_history_1_1_2(api)

    metrics = validate_success(api.get_csat_metrics(ADMIN, params={"agent_id": ctx["agent"]["id"]}))
    assert metrics["survey_count"] == 3
    assert_csat(metrics["recency_weighted_mean"], 1.21)
    assert_csat(metrics["simple_mean"], 1.33)


def test_csat_below_threshold_sets_coaching_hold(api):
    """PRD §3.8: "The same recomputation drives coaching. An agent's `coaching_hold`
    is set true when the window holds at least three submitted surveys and the
    recency-weighted mean falls below 3.00; it is cleared when a later recomputation
    brings the mean back to the threshold or above."
    PRD §3.8: "The weighted mean is what lands on the agent as `rolling_csat`, and it
    stays null until the agent has at least one submitted survey in the window."

    Design: Difficulty/combinatorial_formula/csat_rounding_order_pinned
    """
    ctx = _csat_history_1_1_2(api)

    agent = validate_success(api.get_agent(ctx["agent"]["id"], ADMIN))
    assert_csat(agent["rolling_csat"], 1.21)
    assert agent["coaching_hold"] is True, "1.21 < 3.00 with three submitted surveys must set the hold"


def _coaching_scenario(api):
    """Agent with four assigned tickets; three resolved, their surveys issued; the
    fourth left IN_PROGRESS. Returns (ctx, t4_id, survey_ids)."""
    ctx = setup_queue(first_response_minutes=480, resolution_minutes=480, capacity_max=10)
    survey_ids = []
    for subject in ("t1", "t2", "t3"):
        ticket = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"], subject=subject)
        assign_ticket(ticket["id"], ctx["agent"]["id"])
        resolve_ticket(ticket["id"], ctx["agent"]["id"], resolution_summary=f"{subject} done")
        survey_ids.append(survey_for_ticket(ticket["id"])["id"])
    t4 = create_ticket_for(ctx["employee"]["id"], ctx["category"]["id"], subject="t4")
    t4 = assign_ticket(t4["id"], ctx["agent"]["id"])
    assert t4["workflow_status"] == "IN_PROGRESS"
    return ctx, t4["id"], survey_ids


def test_third_low_survey_flips_coaching_hold(api):
    """PRD §3.8: "The same recomputation drives coaching. An agent's `coaching_hold`
    is set true when the window holds at least three submitted surveys and the
    recency-weighted mean falls below 3.00; it is cleared when a later recomputation
    brings the mean back to the threshold or above."

    Design: Difficulty/transitive_cascade/survey_submit_coaching_hold_releases_tickets
    """
    ctx, _t4_id, survey_ids = _coaching_scenario(api)

    for survey_id in survey_ids:
        submit_survey_score(survey_id, ctx["employee"]["id"], 1)

    agent = validate_success(api.get_agent(ctx["agent"]["id"], ADMIN))
    assert_csat(agent["rolling_csat"], 1.0)
    assert agent["coaching_hold"] is True, (
        "the third submitted survey reaches the three-survey floor with the mean below 3.00"
    )


def test_coaching_hold_releases_assigned_open_tickets(api):
    """PRD §3.8: "The moment the hold flips from false to true, the agent's open
    workload is released: every ticket currently assigned to the agent in `TRIAGED`,
    `IN_PROGRESS`, or `ESCALATED` has its `assigned_agent_id` cleared and its
    `workflow_status` returned to `TRIAGED`, with a `COACHING_RELEASE` event appended
    per ticket — a depth-three cascade running from the survey, through the agent's
    recomputed standing, into the ticket queue."

    Design: Difficulty/transitive_cascade/survey_submit_coaching_hold_releases_tickets
    """
    ctx, t4_id, survey_ids = _coaching_scenario(api)
    for survey_id in survey_ids:
        submit_survey_score(survey_id, ctx["employee"]["id"], 1)

    t4 = get_ticket(t4_id)
    assert t4["assigned_agent_id"] is None, "the coaching release clears the assignee"
    assert t4["workflow_status"] == "TRIAGED"

    events = events_of(t4_id)
    assert any(e["event_type"] == "COACHING_RELEASE" for e in events), (
        "a COACHING_RELEASE event must be appended per released ticket"
    )


def test_coaching_threshold_exactly_three_point_zero_no_hold(api):
    """PRD §3.8: "The same recomputation drives coaching. An agent's `coaching_hold`
    is set true when the window holds at least three submitted surveys and the
    recency-weighted mean falls below 3.00; it is cleared when a later recomputation
    brings the mean back to the threshold or above."

    Design: Corner/cross_cutting_layers/coaching_threshold_exactly_three_no_hold
    """
    ctx = setup_queue(first_response_minutes=480, resolution_minutes=480)
    for subject in ("t1", "t2", "t3"):
        resolve_and_submit_survey(ctx, subject, 3)

    agent = validate_success(api.get_agent(ctx["agent"]["id"], ADMIN))
    assert_csat(agent["rolling_csat"], 3.0)
    assert agent["coaching_hold"] is False, (
        "3.00 < 3.00 is false: the strict inequality must leave coaching_hold clear"
    )
