"""Composite setup helpers.

The harness restarts the service before every individual test, so every helper
below builds its state from scratch through the public API and never assumes
a pre-seeded row.  Setup calls go through `get_success_data`, which raises a
descriptive AssertionError when a setup step itself fails, so a broken prelude
never masquerades as a failed assertion.

The helpers are layered:

* tier 1 - single-call primitives (clock, form, agent, evaluator, interaction);
* tier 2 - a published scorecard plus a registered population;
* tier 3 - an OPEN sampling plan with selections, assigned or not;
* tier 4 - evaluations in each review/feedback posture;
* tier 5 - disputes, calibration sessions and coaching plans.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    make_agent_headers,
    make_compliance_auditor_headers,
    make_evaluator_headers,
    make_headers,
    make_quality_manager_headers,
    make_supervisor_headers,
)

#: The instant most scenarios operate from: inside the August monitoring
#: period and after the interactions they score.
DEFAULT_NOW = "2026-08-05T09:00:00Z"


class Env(dict):
    """A dictionary of created rows with attribute access for readability."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error only
            raise AttributeError(item) from exc

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


# ==========================================================================
# Tier 1 - single-call primitives
# ==========================================================================
def set_clock(api: ApiClient, to_iso8601: str) -> str:
    """Move the logical clock and return the resulting `current_utc`."""
    data = get_success_data(api.set_clock(to_iso8601, make_quality_manager_headers()))
    return data["current_utc"]


def create_form(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create a DRAFT evaluation form together with its behaviours."""
    payload = f.evaluation_form_payload(**kwargs)
    return get_success_data(api.create_form(payload, make_quality_manager_headers()), 201)


def activate_form(api: ApiClient, form_id: str) -> Dict[str, Any]:
    """Publish a DRAFT form."""
    return get_success_data(api.activate_form(form_id, make_quality_manager_headers()))


def retire_form(api: ApiClient, form_id: str) -> Dict[str, Any]:
    """Retire an ACTIVE form."""
    return get_success_data(api.retire_form(form_id, make_quality_manager_headers()))


def create_active_form(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Create and publish a scorecard in one step."""
    form = create_form(api, **kwargs)
    return activate_form(api, form["id"])


def create_agent(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a contact-centre agent."""
    return get_success_data(
        api.create_agent(f.agent_payload(**kwargs), make_quality_manager_headers()), 201
    )


def create_evaluator(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Register a quality evaluator."""
    return get_success_data(
        api.create_evaluator(f.evaluator_payload(**kwargs), make_quality_manager_headers()), 201
    )


def create_interaction(api: ApiClient, agent_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Record a handled contact; recording consent starts PENDING."""
    return get_success_data(
        api.create_interaction(
            f.interaction_payload(agent_id, **kwargs), make_quality_manager_headers()
        ),
        201,
    )


def consent_review(
    api: ApiClient,
    interaction_id: str,
    outcome: str,
    captured_disclosures: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Record a recording-consent outcome as the ComplianceAuditor."""
    return get_success_data(
        api.consent_review(
            interaction_id,
            f.consent_review_payload(outcome, captured_disclosures=captured_disclosures),
            make_compliance_auditor_headers(),
        )
    )


def create_verified_interaction(
    api: ApiClient,
    agent_id: str,
    *,
    required_disclosures: Optional[List[str]] = None,
    captured_disclosures: Optional[List[str]] = None,
    consent_outcome: str = "VERIFIED",
    **kwargs: Any,
) -> Dict[str, Any]:
    """Record a contact and clear its recording consent in one step."""
    required = ["RECORDING"] if required_disclosures is None else list(required_disclosures)
    captured = list(required) if captured_disclosures is None else list(captured_disclosures)
    interaction = create_interaction(
        api, agent_id, required_disclosures=required, **kwargs
    )
    return consent_review(api, interaction["id"], consent_outcome, captured)


def create_scan(
    api: ApiClient,
    interaction_id: str,
    expected_interaction_version: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Attach an analytics screening result to a contact."""
    return get_success_data(
        api.create_scan(
            f.analytics_scan_payload(interaction_id, expected_interaction_version, **kwargs),
            make_quality_manager_headers(),
        ),
        201,
    )


def create_plan(api: ApiClient, form_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Draft a sampling plan."""
    return get_success_data(
        api.create_plan(f.sample_plan_payload(form_id, **kwargs), make_quality_manager_headers()),
        201,
    )


def open_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    """Open a DRAFT plan, pinning the form's guidance revision."""
    return get_success_data(api.open_plan(plan_id, make_quality_manager_headers()))


def close_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    """Close an OPEN plan and sweep its live selections."""
    return get_success_data(api.close_plan(plan_id, make_quality_manager_headers()))


def create_open_plan(api: ApiClient, form_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Draft and open a sampling plan in one step."""
    plan = create_plan(api, form_id, **kwargs)
    return open_plan(api, plan["id"])


def create_selection(
    api: ApiClient, plan_id: str, interaction_id: str, source: str = "RANDOM"
) -> Dict[str, Any]:
    """Pull one contact into an OPEN plan's review pool."""
    return get_success_data(
        api.create_selection(
            f.sample_selection_payload(plan_id, interaction_id, source=source),
            make_quality_manager_headers(),
        ),
        201,
    )


def assign_selection(
    api: ApiClient,
    selection_id: str,
    evaluator_id: str,
    *,
    review_window_start: str = "2026-08-05T09:00:00Z",
    review_window_end: str = "2026-08-05T11:00:00Z",
) -> Dict[str, Any]:
    """Reserve a half-open review window for one evaluator."""
    return get_success_data(
        api.assign_selection(
            selection_id,
            f.assign_payload(
                evaluator_id,
                review_window_start=review_window_start,
                review_window_end=review_window_end,
            ),
            make_quality_manager_headers(),
        )
    )


def exclude_selection(
    api: ApiClient, selection_id: str, reason: str = "EVALUATOR_UNAVAILABLE"
) -> Dict[str, Any]:
    """Drop a live selection out of the pool."""
    return get_success_data(
        api.exclude_selection(
            selection_id, f.exclude_payload(reason), make_quality_manager_headers()
        )
    )


def open_evaluation(api: ApiClient, selection_id: str, evaluator_id: str) -> Dict[str, Any]:
    """Open a DRAFT evaluation as the evaluator holding the assignment."""
    return get_success_data(
        api.create_evaluation(
            f.evaluation_payload(selection_id), make_evaluator_headers(evaluator_id)
        ),
        201,
    )


def submit_evaluation(
    api: ApiClient,
    evaluation_id: str,
    evaluator_id: str,
    item_scores: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score the contact."""
    scores = f.PASSING_ITEM_SCORES if item_scores is None else item_scores
    return get_success_data(
        api.submit_evaluation(
            evaluation_id, f.submit_payload(scores), make_evaluator_headers(evaluator_id)
        )
    )


def deliver_evaluation(api: ApiClient, evaluation_id: str, evaluator_id: str) -> Dict[str, Any]:
    """Deliver the scored feedback, starting the dispute window."""
    return get_success_data(
        api.deliver_evaluation(evaluation_id, make_evaluator_headers(evaluator_id))
    )


def acknowledge_evaluation(
    api: ApiClient, evaluation_id: str, agent_id: str, agreement: str = "AGREE"
) -> Dict[str, Any]:
    """Record the agent's stance on delivered feedback."""
    return get_success_data(
        api.acknowledge_evaluation(
            evaluation_id, f.acknowledge_payload(agreement), make_agent_headers(agent_id)
        )
    )


def file_dispute(
    api: ApiClient,
    evaluation_id: str,
    agent_id: str,
    expected_evaluation_version: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Contest delivered feedback as the agent."""
    return get_success_data(
        api.create_dispute(
            f.dispute_payload(evaluation_id, expected_evaluation_version, **kwargs),
            make_agent_headers(agent_id),
        ),
        201,
    )


def review_dispute(api: ApiClient, dispute_id: str, reviewer_id: str) -> Dict[str, Any]:
    """Pick up a submitted dispute as a different evaluator."""
    return get_success_data(
        api.review_dispute(dispute_id, make_evaluator_headers(reviewer_id))
    )


def resolve_dispute(
    api: ApiClient, dispute_id: str, reviewer_id: str, outcome: str, **kwargs: Any
) -> Dict[str, Any]:
    """Resolve a dispute under review."""
    return get_success_data(
        api.resolve_dispute(
            dispute_id, f.resolve_payload(outcome, **kwargs), make_evaluator_headers(reviewer_id)
        )
    )


def respond_dispute(api: ApiClient, dispute_id: str, agent_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Supply the additional rationale a dispute asked for."""
    return get_success_data(
        api.respond_dispute(dispute_id, f.respond_payload(**kwargs), make_agent_headers(agent_id))
    )


def create_session(api: ApiClient, form_id: str, interaction_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Schedule a calibration session."""
    return get_success_data(
        api.create_session(
            f.calibration_session_payload(form_id, interaction_id, **kwargs),
            make_quality_manager_headers(),
        ),
        201,
    )


def start_scoring(api: ApiClient, session_id: str) -> Dict[str, Any]:
    """Open the calibration floor for submissions."""
    return get_success_data(api.start_scoring(session_id, make_quality_manager_headers()))


def create_submission(
    api: ApiClient, session_id: str, evaluator_id: str, item_scores: Dict[str, Any]
) -> Dict[str, Any]:
    """Record one evaluator's independent reading of the calibration contact."""
    return get_success_data(
        api.create_submission(
            f.calibration_submission_payload(session_id, item_scores),
            make_evaluator_headers(evaluator_id),
        ),
        201,
    )


def close_session(
    api: ApiClient, session_id: str, guidance_updates: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Close a scoring session."""
    return get_success_data(
        api.close_session(
            session_id,
            f.close_session_payload(guidance_updates),
            make_quality_manager_headers(),
        )
    )


def create_coaching_plan(
    api: ApiClient,
    agent_id: str,
    source_evaluation_id: str,
    expected_agent_version: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Assign a coaching plan off a scored evaluation."""
    return get_success_data(
        api.create_coaching_plan(
            f.coaching_plan_payload(agent_id, source_evaluation_id, expected_agent_version, **kwargs),
            make_supervisor_headers(),
        ),
        201,
    )


def log_coaching_session(api: ApiClient, plan_id: str, **kwargs: Any) -> Dict[str, Any]:
    """Record one delivered coaching session."""
    return get_success_data(
        api.log_coaching_session(plan_id, f.log_session_payload(**kwargs), make_supervisor_headers())
    )


def read_agent(api: ApiClient, agent_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_agent(agent_id, make_quality_manager_headers()))


def read_evaluator(api: ApiClient, evaluator_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_evaluator(evaluator_id, make_quality_manager_headers()))


def read_interaction(api: ApiClient, interaction_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_interaction(interaction_id, make_quality_manager_headers()))


def read_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_plan(plan_id, make_quality_manager_headers()))


def read_selection(api: ApiClient, selection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_selection(selection_id, make_quality_manager_headers()))


def read_evaluation(api: ApiClient, evaluation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_evaluation(evaluation_id, make_quality_manager_headers()))


def read_dispute(api: ApiClient, dispute_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_dispute(dispute_id, make_quality_manager_headers()))


def read_session(api: ApiClient, session_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_session(session_id, make_quality_manager_headers()))


def read_submission(api: ApiClient, submission_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_submission(submission_id, make_quality_manager_headers()))


def read_coaching_plan(api: ApiClient, plan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_coaching_plan(plan_id, make_quality_manager_headers()))


def read_form(api: ApiClient, form_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_form(form_id, make_quality_manager_headers()))


def read_scan(api: ApiClient, scan_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_scan(scan_id, make_quality_manager_headers()))


def read_quality_summary(api: ApiClient, agent_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_quality_summary(agent_id, make_quality_manager_headers()))


def list_data(response: Any) -> List[Dict[str, Any]]:
    """The `data` array of a list response, for setup-time discovery."""
    body = response.json()
    return body["data"]


# ==========================================================================
# Tier 2 - a published scorecard plus a registered population
# ==========================================================================
AUGUST_PERIOD = ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59Z")


def program_env(
    api: ApiClient,
    *,
    now: str = DEFAULT_NOW,
    behaviors: Optional[List[Dict[str, Any]]] = None,
    auto_fail_policy: str = "COMPLIANCE_SECTION_ZERO",
    min_compliance_item_score: Optional[int] = None,
    per_agent_target_volume: int = 4,
    mix: Optional[Dict[str, int]] = None,
    period_start: str = AUGUST_PERIOD[0],
    period_end: str = AUGUST_PERIOD[1],
    max_open_assignments: Optional[int] = None,
    csat_score: Optional[int] = 4,
    interaction_kwargs: Optional[Dict[str, Any]] = None,
    open_the_plan: bool = True,
) -> Env:
    """A published scorecard, one agent, one evaluator, one consent-cleared
    contact and a sampling plan over the August period.

    This is the prelude every scoring scenario starts from.
    """
    set_clock(api, now)
    form = create_active_form(
        api,
        behaviors=behaviors,
        auto_fail_policy=auto_fail_policy,
        min_compliance_item_score=min_compliance_item_score,
    )
    agent = create_agent(api)
    evaluator = create_evaluator(api, max_open_assignments=max_open_assignments)
    interaction = create_verified_interaction(
        api,
        agent["id"],
        csat_score=csat_score,
        **(interaction_kwargs or {}),
    )
    plan = create_plan(
        api,
        form["id"],
        period_start=period_start,
        period_end=period_end,
        per_agent_target_volume=per_agent_target_volume,
        mix=mix,
    )
    if open_the_plan:
        plan = open_plan(api, plan["id"])
    return Env(
        form=form,
        agent=agent,
        evaluator=evaluator,
        interaction=interaction,
        plan=plan,
    )


def two_evaluator_program_env(api: ApiClient, **kwargs: Any) -> Env:
    """A program with a second evaluator, for the segregation-of-duties path."""
    env = program_env(api, **kwargs)
    env.reviewer = create_evaluator(api, full_name="Ravi Reviewer")
    return env


# ==========================================================================
# Tier 3 - selections inside an OPEN plan
# ==========================================================================
def selected_env(api: ApiClient, *, source: str = "RANDOM", **kwargs: Any) -> Env:
    """A program whose contact has been pulled into the review pool."""
    env = program_env(api, **kwargs)
    env.selection = create_selection(api, env.plan["id"], env.interaction["id"], source)
    return env


def assigned_env(
    api: ApiClient,
    *,
    source: str = "RANDOM",
    review_window_start: str = "2026-08-05T09:00:00Z",
    review_window_end: str = "2026-08-05T11:00:00Z",
    **kwargs: Any,
) -> Env:
    """A selection with a reserved review window on the program's evaluator."""
    env = selected_env(api, source=source, **kwargs)
    env.selection = assign_selection(
        api,
        env.selection["id"],
        env.evaluator["id"],
        review_window_start=review_window_start,
        review_window_end=review_window_end,
    )
    return env


def two_selection_env(
    api: ApiClient,
    *,
    per_agent_target_volume: int = 4,
    assign_both: bool = True,
    **kwargs: Any,
) -> Env:
    """Two consent-cleared contacts of the same agent, both pulled and
    optionally both assigned to the same evaluator on adjacent windows."""
    env = program_env(api, per_agent_target_volume=per_agent_target_volume, **kwargs)
    env.interaction2 = create_verified_interaction(
        api,
        env.agent["id"],
        started_at="2026-08-04T10:00:00Z",
        ended_at="2026-08-04T10:10:00Z",
        csat_score=3,
    )
    env.selection = create_selection(api, env.plan["id"], env.interaction["id"], "RANDOM")
    env.selection2 = create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
    if assign_both:
        env.selection = assign_selection(
            api,
            env.selection["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T09:00:00Z",
            review_window_end="2026-08-05T11:00:00Z",
        )
        env.selection2 = assign_selection(
            api,
            env.selection2["id"],
            env.evaluator["id"],
            review_window_start="2026-08-05T11:00:00Z",
            review_window_end="2026-08-05T13:00:00Z",
        )
    return env


# ==========================================================================
# Tier 4 - evaluations in each posture
# ==========================================================================
def draft_evaluation_env(api: ApiClient, **kwargs: Any) -> Env:
    """An evaluation opened but not yet scored."""
    env = assigned_env(api, **kwargs)
    env.evaluation = open_evaluation(api, env.selection["id"], env.evaluator["id"])
    return env


def submitted_evaluation_env(
    api: ApiClient, *, item_scores: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Env:
    """A scored evaluation sitting at SUBMITTED / PENDING."""
    env = draft_evaluation_env(api, **kwargs)
    env.evaluation = submit_evaluation(
        api, env.evaluation["id"], env.evaluator["id"], item_scores
    )
    return env


def delivered_evaluation_env(
    api: ApiClient, *, item_scores: Optional[Dict[str, Any]] = None, **kwargs: Any
) -> Env:
    """A scored evaluation whose feedback has been delivered, opening the
    seven-day dispute window."""
    env = submitted_evaluation_env(api, item_scores=item_scores, **kwargs)
    env.evaluation = deliver_evaluation(api, env.evaluation["id"], env.evaluator["id"])
    return env


def acknowledged_evaluation_env(
    api: ApiClient,
    *,
    item_scores: Optional[Dict[str, Any]] = None,
    agreement: str = "AGREE",
    **kwargs: Any,
) -> Env:
    """Delivered feedback the agent has acknowledged."""
    env = delivered_evaluation_env(api, item_scores=item_scores, **kwargs)
    env.evaluation = acknowledge_evaluation(
        api, env.evaluation["id"], env.agent["id"], agreement
    )
    return env


# ==========================================================================
# Tier 5 - disputes, calibration and coaching
# ==========================================================================
def disputed_evaluation_env(
    api: ApiClient,
    *,
    item_scores: Optional[Dict[str, Any]] = None,
    disputed_behavior_codes: Optional[List[str]] = None,
    **kwargs: Any,
) -> Env:
    """Delivered feedback contested by the agent, plus a second evaluator who
    is free to adjudicate it."""
    env = delivered_evaluation_env(api, item_scores=item_scores, **kwargs)
    env.reviewer = create_evaluator(api, full_name="Ravi Reviewer")
    env.dispute = file_dispute(
        api,
        env.evaluation["id"],
        env.agent["id"],
        env.evaluation["version"],
        disputed_behavior_codes=disputed_behavior_codes,
    )
    env.evaluation = read_evaluation(api, env.evaluation["id"])
    return env


def under_review_dispute_env(api: ApiClient, **kwargs: Any) -> Env:
    """A dispute picked up by the second evaluator."""
    env = disputed_evaluation_env(api, **kwargs)
    env.dispute = review_dispute(api, env.dispute["id"], env.reviewer["id"])
    return env


def calibration_scoring_env(
    api: ApiClient,
    *,
    now: str = DEFAULT_NOW,
    benchmark_item_scores: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Env:
    """A calibration session in SCORING on a published scorecard, with two
    registered evaluators ready to submit."""
    env = program_env(api, now=now, **kwargs)
    env.reviewer = create_evaluator(api, full_name="Ravi Reviewer")
    env.session = create_session(
        api,
        env.form["id"],
        env.interaction["id"],
        benchmark_item_scores=benchmark_item_scores,
    )
    env.session = start_scoring(api, env.session["id"])
    return env


def coaching_plan_env(
    api: ApiClient,
    *,
    item_scores: Optional[Dict[str, Any]] = None,
    target_score: float = 85.00,
    **kwargs: Any,
) -> Env:
    """A scored evaluation plus a coaching plan sized off the agent's rolling
    index at the instant the plan was written."""
    env = submitted_evaluation_env(api, item_scores=item_scores, **kwargs)
    env.agent = read_agent(api, env.agent["id"])
    env.coaching_plan = create_coaching_plan(
        api,
        env.agent["id"],
        env.evaluation["id"],
        env.agent["version"],
        target_score=target_score,
    )
    env.agent = read_agent(api, env.agent["id"])
    return env


def recognition_history_env(api: ApiClient, **kwargs: Any) -> Env:
    """An agent with two scored evaluations, the population the recognition
    history gate counts."""
    env = submitted_evaluation_env(api, item_scores=f.HIGH_ITEM_SCORES_93, **kwargs)
    env.interaction2 = create_verified_interaction(
        api,
        env.agent["id"],
        started_at="2026-08-04T10:00:00Z",
        ended_at="2026-08-04T10:10:00Z",
        csat_score=5,
    )
    env.selection2 = create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
    env.selection2 = assign_selection(
        api,
        env.selection2["id"],
        env.evaluator["id"],
        review_window_start="2026-08-05T11:00:00Z",
        review_window_end="2026-08-05T13:00:00Z",
    )
    env.evaluation2 = open_evaluation(api, env.selection2["id"], env.evaluator["id"])
    env.evaluation2 = submit_evaluation(
        api, env.evaluation2["id"], env.evaluator["id"], f.HIGH_ITEM_SCORES_93
    )
    env.agent = read_agent(api, env.agent["id"])
    return env


def indexed_agent_env(api: ApiClient, **kwargs: Any) -> Env:
    """One agent with two scored evaluations of unequal duration.

    The ten-minute contact scores 78.82 with SURVEY marked not applicable and
    the half-hour contact scores 52.00 by automatic fail, so the agent ends with
    `quality_index_rolling` at 65.41, `quality_index_period` at 58.71 and one
    open compliance finding.
    """
    kwargs.setdefault("mix", f.source_mix(50, 25, 25))
    env = submitted_evaluation_env(api, item_scores=f.NA_ITEM_SCORES, **kwargs)
    env.interaction2 = create_verified_interaction(
        api,
        env.agent["id"],
        started_at="2026-08-04T14:00:00Z",
        ended_at="2026-08-04T14:30:00Z",
        csat_score=2,
        repeat_contact_within_72h=True,
    )
    env.selection2 = create_selection(api, env.plan["id"], env.interaction2["id"], "RANDOM")
    env.selection2 = assign_selection(
        api,
        env.selection2["id"],
        env.evaluator["id"],
        review_window_start="2026-08-05T11:00:00Z",
        review_window_end="2026-08-05T13:00:00Z",
    )
    env.evaluation2 = open_evaluation(api, env.selection2["id"], env.evaluator["id"])
    env.evaluation2 = submit_evaluation(
        api, env.evaluation2["id"], env.evaluator["id"], f.AUTO_FAIL_ITEM_SCORES
    )
    env.agent = read_agent(api, env.agent["id"])
    env.plan = read_plan(api, env.plan["id"])
    return env


def thirds_form_env(api: ApiClient, **kwargs: Any) -> Env:
    """A five-behaviour scorecard of equal 20.00 weights scored out of three
    points, on a CHAT contact whose recording consent is NOT_REQUIRED."""
    kwargs.setdefault("behaviors", f.THIRDS_BEHAVIORS)
    kwargs.setdefault("min_compliance_item_score", 1)
    kwargs.setdefault("per_agent_target_volume", 2)
    kwargs.setdefault(
        "interaction_kwargs",
        {
            "channel": "CHAT",
            "started_at": "2026-08-04T09:00:00Z",
            "ended_at": "2026-08-04T09:20:00Z",
            "required_disclosures": [],
            "consent_outcome": "NOT_REQUIRED",
        },
    )
    kwargs.setdefault("csat_score", 3)
    return draft_evaluation_env(api, **kwargs)
