"""Scenario builders.

The harness restarts the server before every test, so each test begins against
an empty database and builds every precondition from scratch through the
endpoints PRD S4 declares. Nothing here reaches into storage.

The logical clock starts at exactly ``2026-08-01T00:00:00Z`` (PRD S2.5), so a
builder never sets the clock unless the scenario needs it moved forward.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import PlaApiClient
from .constants import PER_CREDIT_FEE_CENTS
from .test_users import (
    COORDINATOR,
    OFFICER_APPROVER,
    OFFICER_REVIEWER,
    REGISTRAR,
    make_assessor_headers,
    make_student_headers,
)
from .types import Alignment, PaymentMethod, PortfolioStatus, Recommendation, SourceType

Json = Dict[str, Any]

CLOCK_EPOCH = "2026-08-01T00:00:00Z"


# --------------------------------------------------------------------------
# Tier 1: catalogue
# --------------------------------------------------------------------------
def new_program(client: PlaApiClient, **overrides: Any) -> Json:
    return get_success_data(client.create_program(f.program_payload(**overrides), headers=COORDINATOR))


def new_course(client: PlaApiClient, **overrides: Any) -> Json:
    return get_success_data(client.create_course(f.course_payload(**overrides), headers=COORDINATOR))


def outcomes_of(client: PlaApiClient, course_id: str) -> List[Json]:
    """The course's learning outcomes in ascending ``outcome_code`` order."""
    response = client.list_learning_outcomes({"course_id": course_id}, headers=COORDINATOR)
    rows, _meta = validate_paginated(response)
    return sorted(rows, key=lambda row: row["outcome_code"])


def new_recommendation(client: PlaApiClient, **overrides: Any) -> Json:
    return get_success_data(
        client.create_recommendation(f.recommendation_payload(**overrides), headers=OFFICER_REVIEWER)
    )


def published_recommendation(client: PlaApiClient, **overrides: Any) -> Json:
    rec = new_recommendation(client, **overrides)
    return get_success_data(client.publish_recommendation(rec["id"], headers=OFFICER_REVIEWER))


def approved_rule(
    client: PlaApiClient,
    recommendation_id: str,
    course_id: str,
    awarded_credits: int = 3,
    **overrides: Any,
) -> Json:
    """A crosswalk rule walked DRAFT -> UNDER_REVIEW -> APPROVED.

    Review and approval are performed by two distinct operator identifiers,
    because a self-approval is refused (PRD S3.2).
    """
    rule = get_success_data(
        client.create_rule(
            f.rule_payload(recommendation_id, course_id, awarded_credits=awarded_credits, **overrides),
            headers=OFFICER_REVIEWER,
        )
    )
    get_success_data(client.submit_rule_for_review(rule["id"], headers=OFFICER_REVIEWER))
    rec = get_success_data(client.get_recommendation(recommendation_id, headers=OFFICER_APPROVER))
    return get_success_data(
        client.approve_rule(
            rule["id"],
            {"expected_recommendation_version": rec["version"]},
            headers=OFFICER_APPROVER,
        )
    )


def articulated_course(
    client: PlaApiClient,
    source_type: str = SourceType.CREDIT_BY_EXAM,
    credits: int = 3,
    awarded_credits: int = 3,
    course_overrides: Optional[Json] = None,
    recommendation_overrides: Optional[Json] = None,
    rule_overrides: Optional[Json] = None,
) -> Json:
    """A course plus a published recommendation plus an APPROVED rule pinning it."""
    course = new_course(client, credits=credits, **(course_overrides or {}))
    rec_kwargs: Json = {
        "source_type": source_type,
        "recommended_credits": max(awarded_credits, credits),
        "recommended_level": course["level"],
    }
    rec_kwargs.update(recommendation_overrides or {})
    rec = published_recommendation(client, **rec_kwargs)
    rule = approved_rule(
        client, rec["id"], course["id"], awarded_credits=awarded_credits, **(rule_overrides or {})
    )
    return {"course": course, "recommendation": rec, "rule": rule}


# --------------------------------------------------------------------------
# Tier 2: people
# --------------------------------------------------------------------------
def new_student(client: PlaApiClient, program_id: str, **overrides: Any) -> Json:
    return get_success_data(
        client.create_student(f.student_payload(program_id, **overrides), headers=COORDINATOR)
    )


def new_assessor(client: PlaApiClient, **overrides: Any) -> Json:
    return get_success_data(
        client.create_assessor(f.assessor_payload(**overrides), headers=COORDINATOR)
    )


# --------------------------------------------------------------------------
# Tier 3: claims, portfolios and artifacts
# --------------------------------------------------------------------------
def new_claim(client: PlaApiClient, student_id: str, course_id: str, **overrides: Any) -> Json:
    return get_success_data(
        client.create_claim(
            f.claim_payload(student_id, course_id, **overrides),
            headers=make_student_headers(student_id),
        )
    )


def new_portfolio(client: PlaApiClient, claim_id: str, student_id: str, **overrides: Any) -> Json:
    return get_success_data(
        client.create_portfolio(
            f.portfolio_payload(claim_id, **overrides), headers=make_student_headers(student_id)
        )
    )


def attach_artifact(
    client: PlaApiClient,
    portfolio_id: str,
    student_id: str,
    outcome_mappings: List[Json],
    **overrides: Any,
) -> Json:
    return get_success_data(
        client.add_artifact(
            portfolio_id,
            f.artifact_payload(outcome_mappings, **overrides),
            headers=make_student_headers(student_id),
        )
    )


def portfolio_covering_all_outcomes(
    client: PlaApiClient,
    claim_id: str,
    student_id: str,
    outcomes: List[Json],
    artifact_count: int = 1,
    alignment: str = Alignment.PRIMARY,
) -> Json:
    """A DRAFT portfolio holding ``artifact_count`` artifacts.

    The first artifact maps every outcome of the course at ``alignment``; the
    remaining artifacts are padding that map the first outcome, which changes the
    artifact tier without changing coverage.
    """
    portfolio = new_portfolio(client, claim_id, student_id)
    attach_artifact(
        client,
        portfolio["id"],
        student_id,
        [f.mapping(outcome["id"], alignment) for outcome in outcomes],
    )
    for _ in range(artifact_count - 1):
        attach_artifact(client, portfolio["id"], student_id, [f.mapping(outcomes[0]["id"], alignment)])
    return get_success_data(client.get_portfolio(portfolio["id"], headers=COORDINATOR))


def submit_portfolio(client: PlaApiClient, portfolio_id: str, student_id: str) -> Json:
    return get_success_data(
        client.submit_portfolio(portfolio_id, headers=make_student_headers(student_id))
    )


# --------------------------------------------------------------------------
# Tier 4: submission and money
# --------------------------------------------------------------------------
def submit_claim(client: PlaApiClient, claim_id: str, student_id: str) -> Json:
    return get_success_data(client.submit_claim(claim_id, headers=make_student_headers(student_id)))


def invoice_for_claim(client: PlaApiClient, claim_id: str) -> Json:
    """The single invoice of a claim (PRD S3.10: exactly one invoice per claim)."""
    response = client.list_invoices({"claim_id": claim_id}, headers=COORDINATOR)
    rows, _meta = validate_paginated(response)
    assert len(rows) == 1, "expected exactly one invoice for claim %s, got %d" % (claim_id, len(rows))
    return rows[0]


def pay_invoice_in_full(client: PlaApiClient, claim_id: str, student_id: str) -> Json:
    invoice = invoice_for_claim(client, claim_id)
    return get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.payment_payload(invoice["balance_due_cents"], PaymentMethod.CARD),
            headers=make_student_headers(student_id),
        )
    )


def submitted_paid_claim(
    client: PlaApiClient,
    student_id: str,
    course_id: str,
    outcomes: Optional[List[Json]] = None,
    artifact_count: int = 1,
    **claim_overrides: Any,
) -> Json:
    """A claim in ``SUBMITTED`` whose invoice is ``PAID``.

    For a ``PORTFOLIO`` claim the portfolio is built and submitted first, which
    is a precondition of claim submission (PRD S3.5).
    """
    claim = new_claim(client, student_id, course_id, **claim_overrides)
    if claim["source_type"] == SourceType.PORTFOLIO:
        assert outcomes is not None, "a PORTFOLIO claim needs the course's outcomes"
        portfolio = portfolio_covering_all_outcomes(
            client, claim["id"], student_id, outcomes, artifact_count=artifact_count
        )
        submit_portfolio(client, portfolio["id"], student_id)
    submit_claim(client, claim["id"], student_id)
    pay_invoice_in_full(client, claim["id"], student_id)
    return get_success_data(client.get_claim(claim["id"], headers=COORDINATOR))


# --------------------------------------------------------------------------
# Tier 5: assessment
# --------------------------------------------------------------------------
def assign_assessor(
    client: PlaApiClient, claim_id: str, assessor_id: Optional[str] = None
) -> Json:
    payload: Json = {} if assessor_id is None else {"assessor_id": assessor_id}
    return get_success_data(client.create_assignment(claim_id, payload, headers=COORDINATOR))


def accept_assignment(client: PlaApiClient, assignment_id: str, assessor_id: str) -> Json:
    return get_success_data(
        client.accept_assignment(assignment_id, headers=make_assessor_headers(assessor_id))
    )


def score_all_outcomes(
    client: PlaApiClient,
    assignment_id: str,
    assessor_id: str,
    outcomes: List[Json],
    points: List[int],
) -> List[Json]:
    """One rubric score per outcome, in ascending ``outcome_code`` order."""
    assert len(points) == len(outcomes), "one points value per outcome"
    scores = []
    for outcome, awarded in zip(outcomes, points):
        scores.append(
            get_success_data(
                client.create_rubric_score(
                    assignment_id,
                    f.rubric_score_payload(outcome["id"], awarded),
                    headers=make_assessor_headers(assessor_id),
                )
            )
        )
    return scores


def complete_assignment(
    client: PlaApiClient,
    assignment_id: str,
    assessor_id: str,
    recommendation: str = Recommendation.PASS,
) -> Json:
    return get_success_data(
        client.complete_assignment(
            assignment_id, {"recommendation": recommendation}, headers=make_assessor_headers(assessor_id)
        )
    )


def scored_claim(
    client: PlaApiClient,
    claim_id: str,
    assessor_id: str,
    outcomes: List[Json],
    points: List[int],
    recommendation: str = Recommendation.PASS,
) -> Json:
    """Walk a ``SUBMITTED``, settled claim all the way to ``SCORED``."""
    assignment = assign_assessor(client, claim_id, assessor_id)
    accept_assignment(client, assignment["id"], assessor_id)
    score_all_outcomes(client, assignment["id"], assessor_id, outcomes, points)
    complete_assignment(client, assignment["id"], assessor_id, recommendation)
    return get_success_data(client.get_claim(claim_id, headers=COORDINATOR))


def award_claim(client: PlaApiClient, claim_id: str, student_id: str, **extra: Any) -> Json:
    student = get_success_data(client.get_student(student_id, headers=COORDINATOR))
    payload: Json = {"expected_student_version": student["version"]}
    payload.update(extra)
    return get_success_data(client.award_claim(claim_id, payload, headers=COORDINATOR))


def post_transcript(client: PlaApiClient, claim_id: str, posted_term: str = "2026FA") -> Json:
    return get_success_data(
        client.post_transcript(claim_id, {"posted_term": posted_term}, headers=REGISTRAR)
    )


def set_clock(client: PlaApiClient, current_utc: str) -> Json:
    return get_success_data(client.set_clock(current_utc, headers=COORDINATOR))
