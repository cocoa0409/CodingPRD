"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, and uses the lenient success validator so a broken setup step
reports as a setup failure rather than as a confusing assertion error.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    calibration_review_payload, educator_payload, evaluation_cycle_payload,
    evaluation_policy_payload, evaluator_payload, evidence_artifact_payload,
    growth_measure_payload, next_employee_number, observation_payload,
    rubric_score_payload, school_payload,
)
from .test_users import (
    TEST_USERS, make_appeal_panelist_headers, make_evaluator_headers,
    make_teacher_headers,
)
from .types import DOMAIN_ORDER

HR = TEST_USERS["hr_admin_headers"]
UNION = TEST_USERS["union_rep_headers"]


# ─── Reads ────────────────────────────────────────────────────────────────

def get_policy(policy_id, headers=HR):
    return get_success_data(api.get_evaluation_policy(policy_id, headers))


def get_school(school_id, headers=HR):
    return get_success_data(api.get_school(school_id, headers))


def get_educator(educator_id, headers=HR):
    return get_success_data(api.get_educator(educator_id, headers))


def get_evaluator(evaluator_id, headers=HR):
    return get_success_data(api.get_evaluator(evaluator_id, headers))


def get_cycle(cycle_id, headers=HR):
    return get_success_data(api.get_evaluation_cycle(cycle_id, headers))


def get_observation(observation_id, headers=HR):
    return get_success_data(api.get_observation(observation_id, headers))


def get_plan(plan_id, headers=HR):
    return get_success_data(api.get_improvement_plan(plan_id, headers))


def get_appeal(appeal_id, headers=HR):
    return get_success_data(api.get_appeal(appeal_id, headers))


def get_grievance(grievance_id, headers=HR):
    return get_success_data(api.get_grievance(grievance_id, headers))


def list_plans(headers=HR, **params):
    return get_success_data(api.list_improvement_plans(headers, params=params))


def list_observations_of_cycle(cycle_id, headers=HR):
    return get_success_data(api.list_observations(headers, params={"cycle_id": cycle_id}))


def cycle_version(cycle_id, headers=HR) -> int:
    return get_cycle(cycle_id, headers)["version"]


def observation_version(observation_id, headers=HR) -> int:
    return get_observation(observation_id, headers)["version"]


# ─── Tier 0: single-step creators ─────────────────────────────────────────

def set_clock(to_iso8601: str, headers=HR):
    """Drive the logical district clock (PRD §3.9)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, headers))


def create_policy(**overrides) -> dict:
    return get_success_data(
        api.create_evaluation_policy(evaluation_policy_payload(**overrides), HR)
    )


def create_school(**overrides) -> dict:
    return get_success_data(api.create_school(school_payload(**overrides), HR))


def create_educator(school_id, **overrides) -> dict:
    return get_success_data(
        api.create_educator(educator_payload(school_id, **overrides), HR)
    )


def create_evaluator(**overrides) -> dict:
    return get_success_data(api.create_evaluator(evaluator_payload(**overrides), HR))


def create_calibration_review(evaluator_id, **overrides) -> dict:
    return get_success_data(
        api.create_calibration_review(
            calibration_review_payload(evaluator_id, **overrides), HR)
    )


def decide_calibration_review(review_id, policy_id) -> dict:
    return get_success_data(
        api.decide_calibration_review(review_id, {"policy_id": policy_id}, HR)
    )


def record_calibration(evaluator_id, policy_id, evaluator_score, anchor_score=3.00,
                       anchor_lesson_code="ANCH-1") -> dict:
    """Create a calibration review and immediately resolve it against the policy."""
    review = create_calibration_review(
        evaluator_id, anchor_score=anchor_score, evaluator_score=evaluator_score,
        anchor_lesson_code=anchor_lesson_code,
    )
    return decide_calibration_review(review["id"], policy_id)


def certify_evaluator(evaluator_id, policy_id, evaluator_score=3.10) -> dict:
    """Walk a PROVISIONAL evaluator to CERTIFIED with one passing review."""
    record_calibration(evaluator_id, policy_id, evaluator_score,
                       anchor_lesson_code="ANCH-CERT")
    return get_evaluator(evaluator_id)


def suspend_evaluator(evaluator_id, policy_id) -> dict:
    """Suspend a CERTIFIED evaluator with two consecutive failing reviews."""
    record_calibration(evaluator_id, policy_id, 3.80, anchor_lesson_code="ANCH-B")
    record_calibration(evaluator_id, policy_id, 3.90, anchor_lesson_code="ANCH-C")
    return get_evaluator(evaluator_id)


def create_cycle(educator_id, policy_id, **overrides) -> dict:
    return get_success_data(
        api.create_evaluation_cycle(
            evaluation_cycle_payload(educator_id, policy_id, **overrides), HR)
    )


def schedule_observation(cycle_id, evaluator_id, headers=None, **overrides) -> dict:
    headers = headers or make_evaluator_headers(evaluator_id)
    return get_success_data(
        api.create_observation(observation_payload(cycle_id, evaluator_id, **overrides),
                               headers)
    )


def conduct_observation(observation_id, evaluator_id) -> dict:
    return get_success_data(
        api.conduct_observation(observation_id, make_evaluator_headers(evaluator_id))
    )


def score_domain(observation_id, evaluator_id, domain_code, raw_score,
                 expected_observation_version) -> dict:
    return get_success_data(
        api.create_rubric_score(
            observation_id,
            rubric_score_payload(domain_code, raw_score, expected_observation_version),
            make_evaluator_headers(evaluator_id),
        )
    )


def score_all_domains(observation_id, evaluator_id, scores=(3, 3, 4, 3),
                      start_version=None) -> dict:
    """Record all four rubric domains, chaining observation_version_after."""
    version = start_version if start_version is not None else observation_version(observation_id)
    for domain_code, raw_score in zip(DOMAIN_ORDER, scores):
        row = score_domain(observation_id, evaluator_id, domain_code, raw_score, version)
        version = row["observation_version_after"]
    return get_observation(observation_id)


def attach_artifact(observation_id, headers, **overrides) -> dict:
    return get_success_data(
        api.create_evidence_artifact(
            observation_id, evidence_artifact_payload(**overrides), headers)
    )


def withdraw_artifact(artifact_id, headers) -> dict:
    return get_success_data(api.withdraw_evidence_artifact(artifact_id, headers))


def submit_observation(observation_id, evaluator_id) -> dict:
    return get_success_data(
        api.submit_observation(observation_id, make_evaluator_headers(evaluator_id))
    )


def return_observation(observation_id, return_reason="Rescore domain four") -> dict:
    return get_success_data(
        api.return_observation(observation_id, {"return_reason": return_reason}, HR)
    )


def accept_observation(observation_id) -> dict:
    return get_success_data(api.accept_observation(observation_id, HR))


def void_observation(observation_id, void_reason="Observation rescheduled") -> dict:
    return get_success_data(
        api.void_observation(observation_id, {"void_reason": void_reason}, HR)
    )


def report_growth_measure(cycle_id, index_value=3.00, coverage_pct=100,
                          measure_code="STATE_ASSESSMENT",
                          expected_cycle_version=None) -> dict:
    if expected_cycle_version is None:
        expected_cycle_version = cycle_version(cycle_id)
    return get_success_data(
        api.create_growth_measure(
            growth_measure_payload(cycle_id, expected_cycle_version,
                                   measure_code=measure_code,
                                   index_value=index_value,
                                   coverage_pct=coverage_pct),
            HR)
    )


def certify_growth_measure(measure_id) -> dict:
    return get_success_data(api.certify_growth_measure(measure_id, HR))


def submit_cycle(cycle_id, headers=HR) -> dict:
    return get_success_data(api.submit_evaluation_cycle(cycle_id, headers))


def finalize_cycle(cycle_id) -> dict:
    return get_success_data(api.finalize_evaluation_cycle(cycle_id, HR))


def close_cycle(cycle_id) -> dict:
    return get_success_data(api.close_evaluation_cycle(cycle_id, HR))


def file_appeal(cycle_id, educator_id, grounds="PROCEDURAL",
                statement="The required pre-conference never happened") -> dict:
    return get_success_data(
        api.create_appeal(
            {"cycle_id": cycle_id, "grounds": grounds, "statement": statement},
            make_teacher_headers(educator_id))
    )


def review_appeal(appeal_id, panelist_evaluator_id) -> dict:
    return get_success_data(
        api.review_appeal(appeal_id, make_appeal_panelist_headers(panelist_evaluator_id))
    )


def decide_appeal(appeal_id, panelist_evaluator_id, outcome, adjusted_composite=None) -> dict:
    payload = {"outcome": outcome}
    if adjusted_composite is not None:
        payload["adjusted_composite"] = adjusted_composite
    return get_success_data(
        api.decide_appeal(appeal_id, payload,
                          make_appeal_panelist_headers(panelist_evaluator_id))
    )


def file_grievance(appeal_id, article_code="ART_12_EVALUATION") -> dict:
    return get_success_data(
        api.create_grievance({"appeal_id": appeal_id, "article_code": article_code}, UNION)
    )


def decide_grievance(grievance_id, outcome, remedy=None, headers=HR) -> dict:
    payload = {"outcome": outcome}
    if remedy is not None:
        payload["remedy"] = remedy
    return get_success_data(api.decide_grievance(grievance_id, payload, headers))


# ─── Tier 1: district set-up ──────────────────────────────────────────────

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def setup_district(clock=DEFAULT_CLOCK, policy_overrides=None, school_overrides=None,
                   educator_overrides=None, second_evaluator=False, certify=True,
                   extra_educators=0) -> dict:
    """Clock + policy + building + educator + one (optionally certified) evaluator.

    Returns a context dict carrying every created resource plus the role headers
    that the entity-backed roles must use for ownership-gated calls.
    """
    set_clock(clock)
    policy = create_policy(**(policy_overrides or {}))
    school = create_school(**(school_overrides or {}))
    educator = create_educator(school["id"], **(educator_overrides or {}))
    evaluator = create_evaluator()
    if certify:
        evaluator = certify_evaluator(evaluator["id"], policy["id"])

    ctx = {
        "clock": clock,
        "policy": policy,
        "school": school,
        "educator": educator,
        "evaluator": evaluator,
        "hr_headers": HR,
        "evaluator_headers": make_evaluator_headers(evaluator["id"]),
        "teacher_headers": make_teacher_headers(educator["id"]),
    }

    if second_evaluator:
        evaluator2 = create_evaluator(full_name="Noor Haddad")
        if certify:
            evaluator2 = certify_evaluator(evaluator2["id"], policy["id"],
                                           evaluator_score=3.05)
        ctx["evaluator2"] = evaluator2
        ctx["panelist_headers"] = make_appeal_panelist_headers(evaluator2["id"])

    if extra_educators:
        others = []
        for index in range(extra_educators):
            others.append(create_educator(
                school["id"],
                employee_number=next_employee_number("X"),
                full_name=f"Extra Educator {index + 1}",
            ))
        ctx["other_educators"] = others

    return ctx


def open_cycle(ctx, educator=None, **overrides) -> dict:
    """Open an evaluation cycle for the district context's educator."""
    educator = educator or ctx["educator"]
    cycle = create_cycle(educator["id"], ctx["policy"]["id"], **overrides)
    ctx.setdefault("cycles", []).append(cycle)
    ctx["cycle"] = cycle
    return cycle


def setup_cycle(clock=DEFAULT_CLOCK, policy_overrides=None, school_overrides=None,
                educator_overrides=None, second_evaluator=False, certify=True,
                cycle_overrides=None) -> dict:
    """District plus one freshly opened cycle in SCHEDULING."""
    ctx = setup_district(clock=clock, policy_overrides=policy_overrides,
                         school_overrides=school_overrides,
                         educator_overrides=educator_overrides,
                         second_evaluator=second_evaluator, certify=certify)
    open_cycle(ctx, **(cycle_overrides or {}))
    return ctx


# ─── Tier 2: observation lifecycle shortcuts ──────────────────────────────

_ARTIFACT_TYPES = ["LESSON_PLAN", "STUDENT_WORK", "REFLECTION", "VIDEO"]


def add_observation(ctx, observation_type="FORMAL", scores=(3, 3, 4, 3),
                    announced=True, scheduled_start="2026-09-10T09:00:00Z",
                    scheduled_end="2026-09-10T10:00:00Z", artifacts=0,
                    stop_at="SUBMITTED", evaluator=None, cycle=None) -> dict:
    """Schedule an observation and walk it to `stop_at`.

    stop_at is one of SCHEDULED, CONDUCTED, SCORED, SUBMITTED or ACCEPTED.
    `artifacts` artifacts are attached once the observation is CONDUCTED,
    alternating between the observing evaluator and the observed teacher.
    """
    evaluator = evaluator or ctx["evaluator"]
    cycle = cycle or ctx["cycle"]
    observation = schedule_observation(
        cycle["id"], evaluator["id"],
        observation_type=observation_type, announced=announced,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    ctx.setdefault("observations", []).append(observation)
    if stop_at == "SCHEDULED":
        return observation

    conducted = conduct_observation(observation["id"], evaluator["id"])
    for index in range(artifacts):
        headers = (make_evaluator_headers(evaluator["id"]) if index % 2 == 0
                   else make_teacher_headers(ctx["educator"]["id"]))
        artifact = attach_artifact(
            observation["id"], headers,
            artifact_type=_ARTIFACT_TYPES[index % len(_ARTIFACT_TYPES)],
            title=f"Artifact {index + 1}",
        )
        ctx.setdefault("artifacts", []).append(artifact)
    if stop_at == "CONDUCTED":
        return get_observation(observation["id"])

    # Attaching an artifact mutates the observation (its `evidence_count`), so its
    # `version` may have moved past the one the conduct call returned. Re-read the
    # current version before opening the guarded rubric-score chain.
    start_version = (observation_version(observation["id"]) if artifacts
                     else conducted["version"])
    score_all_domains(observation["id"], evaluator["id"], scores,
                      start_version=start_version)
    if stop_at == "SCORED":
        return get_observation(observation["id"])

    submit_observation(observation["id"], evaluator["id"])
    if stop_at == "SUBMITTED":
        return get_observation(observation["id"])

    if stop_at == "ACCEPTED":
        accept_observation(observation["id"])
        return get_observation(observation["id"])

    raise ValueError(f"unsupported stop_at {stop_at!r}")


# ─── Tier 3: whole-cycle lifecycles ───────────────────────────────────────

SINGLE_FORMAL_POLICY = {"required_formal_count": 1, "required_informal_count": 0}


def setup_submitted_cycle(clock=DEFAULT_CLOCK, policy_overrides=None,
                          formal_scores=(3, 3, 4, 3), informal_scores=None,
                          artifacts=0, growth_index=3.00, growth_coverage=100,
                          certify_growth=True, educator_overrides=None,
                          school_overrides=None, second_evaluator=False,
                          announced=True) -> dict:
    """Build a cycle carrying its observations and growth measure, then submit it.

    The PROVISIONAL composite is computed by the submit call.
    """
    if policy_overrides is None:
        policy_overrides = dict(SINGLE_FORMAL_POLICY)
    ctx = setup_cycle(clock=clock, policy_overrides=policy_overrides,
                      school_overrides=school_overrides,
                      educator_overrides=educator_overrides,
                      second_evaluator=second_evaluator)

    ctx["formal_observation"] = add_observation(
        ctx, observation_type="FORMAL", scores=formal_scores, announced=announced,
        scheduled_start="2026-09-10T09:00:00Z", scheduled_end="2026-09-10T10:00:00Z",
        artifacts=artifacts, stop_at="SUBMITTED",
    )
    if informal_scores is not None:
        ctx["informal_observation"] = add_observation(
            ctx, observation_type="INFORMAL", scores=informal_scores,
            scheduled_start="2026-09-11T09:00:00Z",
            scheduled_end="2026-09-11T09:30:00Z", stop_at="SUBMITTED",
        )

    if growth_index is not None:
        measure = report_growth_measure(ctx["cycle"]["id"], index_value=growth_index,
                                        coverage_pct=growth_coverage)
        ctx["growth_measure"] = measure
        if certify_growth:
            ctx["growth_measure"] = certify_growth_measure(measure["id"])

    ctx["cycle"] = submit_cycle(ctx["cycle"]["id"])
    return ctx


def setup_finalized_cycle(**kwargs) -> dict:
    """Full lifecycle through FINALIZED, where the FINAL composite is computed."""
    ctx = setup_submitted_cycle(**kwargs)
    ctx["cycle"] = finalize_cycle(ctx["cycle"]["id"])
    return ctx


def setup_ineffective_cycle_with_plan(clock=DEFAULT_CLOCK, policy_overrides=None,
                                      second_evaluator=False,
                                      educator_overrides=None) -> dict:
    """Finalize a cycle to INEFFECTIVE so the district's remediation obligation
    creates an ACTIVE improvement plan and holds the educator's tenure track."""
    if policy_overrides is None:
        policy_overrides = dict(SINGLE_FORMAL_POLICY)
    ctx = setup_finalized_cycle(
        clock=clock, policy_overrides=policy_overrides,
        formal_scores=(1, 1, 1, 1), growth_index=1.00, growth_coverage=100,
        artifacts=0, second_evaluator=second_evaluator,
        educator_overrides=educator_overrides,
    )
    plans = list_plans(cycle_id=ctx["cycle"]["id"])
    assert plans, "Setup failed: finalizing an INEFFECTIVE cycle must create a plan"
    ctx["plan"] = plans[0]
    return ctx


def setup_appeal_under_review(ctx) -> dict:
    """File an appeal on the context's finalized cycle and open its review with
    the second evaluator, who observed nothing in that cycle."""
    appeal = file_appeal(ctx["cycle"]["id"], ctx["educator"]["id"])
    ctx["appeal"] = review_appeal(appeal["id"], ctx["evaluator2"]["id"])
    return ctx["appeal"]


def setup_upheld_appeal(ctx) -> dict:
    """Take the context's finalized cycle through a decided UPHELD appeal, which
    is the only status from which a union grievance may be filed."""
    appeal = setup_appeal_under_review(ctx)
    ctx["appeal"] = decide_appeal(appeal["id"], ctx["evaluator2"]["id"], "UPHELD")
    return ctx["appeal"]
