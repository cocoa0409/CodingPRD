"""The employer-review response loop: legal may reject back into drafting without bound."""
from prd_bench_local_runner.testing import validate_error

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMMUNITY_MANAGER_USER_ID,
    COMPLIANCE_REVIEWER_USER_ID,
    compliance_reviewer_headers,
)

FIRST_DRAFT = "Thank you for the feedback - draft 1."
SECOND_DRAFT = "Thank you for the feedback - draft 2."
THIRD_DRAFT = "Thank you for the feedback - draft 3."


def _review_awaiting_legal(api):
    """A three-star review, triaged, drafted once and sitting with legal."""
    program = fx.create_program(api)
    review = fx.ingest_review(
        api,
        program["id"],
        external_ref="gd-88120",
        rating=3,
        posted_at="2026-07-31T12:00:00Z",
    )
    fx.triage_review(api, review["id"], note="needs a public response")
    fx.draft_review_response(api, review["id"], FIRST_DRAFT)
    return program, fx.submit_review_to_legal(api, review["id"])


def test_a_legal_rejection_sends_the_review_back_to_drafting_with_its_text_intact(api):
    """PRD §3.8: "A rating of 1 or 2 gives 24 hours; a rating of exactly 3 gives 72 hours — three
    days; a rating of 4 or 5 gives 168 hours — a full week."
    PRD §3.8: "`REJECT` moves the review `LEGAL_REVIEW → DRAFTING`, increments `rejection_count` by
    1, retains the existing `response_body` for editing, and versions the review; it does not touch
    `responded_at`, `sla_status` or the brand health score."

    Design: Difficulty/non_linear_state_machine/employer_review_legal_rejection_cycle_revisits_drafting_twice
    """
    _, review = _review_awaiting_legal(api)

    rejected = fx.decide_legal_review(api, review["id"], "REJECT", note="tone too defensive")

    assert review["response_due_at"] == "2026-08-03T12:00:00.000Z", review
    assert rejected["state"] == "DRAFTING", rejected
    assert rejected["rejection_count"] == 1, rejected
    assert rejected["response_body"] == FIRST_DRAFT, rejected
    assert rejected["responded_at"] is None, rejected
    assert rejected["sla_status"] == "PENDING", rejected
    assert rejected["approved_by_user_id"] is None, rejected


def test_a_second_rejection_is_told_apart_from_the_first_only_by_its_counter(api):
    """PRD §3.8: "The same manager then drafts the public response by supplying a `response_body`
    of 1 to 2,000 characters; drafting is accepted from `TRIAGED` or from `DRAFTING` — redrafting is
    normal — and refused from any other state with `ERR_REVIEW_NOT_DRAFTABLE`."
    PRD §3.8: "The `DRAFTING → LEGAL_REVIEW → DRAFTING` loop may repeat without bound."

    Design: Difficulty/non_linear_state_machine/employer_review_legal_rejection_cycle_revisits_drafting_twice
    """
    _, review = _review_awaiting_legal(api)

    fx.decide_legal_review(api, review["id"], "REJECT", note="tone too defensive")
    redrafted = fx.draft_review_response(api, review["id"], SECOND_DRAFT)
    fx.submit_review_to_legal(api, review["id"])
    rejected_again = fx.decide_legal_review(
        api, review["id"], "REJECT", note="one unverifiable claim remains"
    )

    assert redrafted["state"] == "DRAFTING", redrafted
    assert redrafted["rejection_count"] == 1, redrafted
    assert rejected_again["state"] == "DRAFTING", rejected_again
    assert rejected_again["rejection_count"] == 2, rejected_again
    assert rejected_again["response_body"] == SECOND_DRAFT, rejected_again


def test_approval_after_two_rejections_publishes_and_closes_the_cycle(api):
    """PRD §3.8: "`APPROVE` moves the review `LEGAL_REVIEW → RESPONSE_PUBLISHED`, sets
    `approved_by_user_id` to the acting `X-User-ID` and `responded_at` to the logical clock, sets
    `sla_status` to `MET` when `responded_at` is at or before `response_due_at` and to `BREACHED`
    otherwise, recomputes the program's `brand_health_score`, and versions both the review and the
    program."
    PRD §3.8: "Both branches require the review to be in `LEGAL_REVIEW`, refusing otherwise with
    `ERR_REVIEW_NOT_IN_LEGAL_REVIEW`, and both require the acting `X-User-ID` to differ from
    `drafted_by_user_id`, refusing otherwise with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.8: "The rating penalty is the sum over the windowed reviews of the star shortfall —
    three less the review's `rating`, treated as zero when the rating is 3 or above — multiplied by
    2.5 points per missing star and then multiplied by that review's recency weight."

    Design: Difficulty/non_linear_state_machine/employer_review_legal_rejection_cycle_revisits_drafting_twice
    """
    program, review = _review_awaiting_legal(api)
    fx.decide_legal_review(api, review["id"], "REJECT", note="tone too defensive")
    fx.draft_review_response(api, review["id"], SECOND_DRAFT)
    fx.submit_review_to_legal(api, review["id"])
    fx.decide_legal_review(api, review["id"], "REJECT", note="one unverifiable claim remains")
    fx.draft_review_response(api, review["id"], THIRD_DRAFT)
    fx.submit_review_to_legal(api, review["id"])

    published = fx.decide_legal_review(
        api, review["id"], "APPROVE", note="cleared for publication"
    )
    refused = api.legal_review(
        review["id"],
        f.legal_review_payload("REJECT", "too late"),
        compliance_reviewer_headers(),
    )

    assert published["state"] == "RESPONSE_PUBLISHED", published
    assert published["rejection_count"] == 2, published
    assert published["response_body"] == THIRD_DRAFT, published
    assert published["drafted_by_user_id"] == COMMUNITY_MANAGER_USER_ID, published
    assert published["approved_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID, published
    assert published["sla_status"] == "MET", published
    assert published["responded_at"].startswith("2026-08-01T00:00:00"), published
    a.assert_brand_health(fx.read_program(api, program["id"])["brand_health_score"], 100.00)
    validate_error(refused, ApiErrorId.REVIEW_NOT_IN_LEGAL_REVIEW, 409)
    assert fx.read_review(api, review["id"])["state"] == "RESPONSE_PUBLISHED"
