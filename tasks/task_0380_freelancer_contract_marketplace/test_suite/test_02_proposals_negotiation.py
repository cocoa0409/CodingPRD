"""Proposal submission, the cyclic counter-offer negotiation, acceptance, and turn rules.

Queue A: non_linear_state_machine / proposal_cyclic_counter_rounds.
Queue B: skills coverage, turn alternation, double-accept idempotency, accept-after-cancel.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_job_posting_payload, create_proposal_payload, counter_payload, accept_payload,
    assert_proposal,
    make_client_headers, make_freelancer_headers,
    create_client, create_freelancer,
)


def _open_posting_with_proposal(billing_type="FIXED", required_skills=("ui",),
                                freelancer_skills=("ui",), bid_amount_cents=60000,
                                budget_cents=50000):
    """Client + freelancer + OPEN posting + one SUBMITTED proposal (last_actor FREELANCER).
    Returns (client, freelancer, posting, proposal, ch, fh)."""
    required_skills = list(required_skills)
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=list(freelancer_skills))
    fh = make_freelancer_headers(freelancer["id"])
    posting = validate_success(api_client.create_job_posting(
        create_job_posting_payload(client["id"], billing_type=billing_type,
                                   budget_cents=budget_cents, required_skills=required_skills), ch), 201)
    proposal = validate_success(api_client.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"],
                                bid_amount_cents=bid_amount_cents), fh), 201)
    return client, freelancer, posting, proposal, ch, fh


def test_proposal_submitted_defaults_last_actor_freelancer(api):
    """PRD §3.2: "A new proposal opens in SUBMITTED status with last_actor set to
    FREELANCER, a round_count of zero, and the very first proposal on a posting moves that
    posting from OPEN to UNDER_REVIEW while bumping its proposal_count to one."

    Design: Difficulty/non_linear_state_machine/proposal_cyclic_counter_rounds
    """
    client, freelancer, posting, proposal, ch, fh = _open_posting_with_proposal()
    assert_proposal(proposal)
    assert proposal["status"] == "SUBMITTED"
    assert proposal["last_actor"] == "FREELANCER"
    assert proposal["round_count"] == 0
    posting_after = validate_success(api.get_job_posting(posting["id"], ch), 200)
    assert posting_after["status"] == "UNDER_REVIEW"
    assert posting_after["proposal_count"] == 1


def test_proposal_cyclic_two_counter_rounds(api):
    """PRD §3.2: "this drives the proposal into COUNTERED status from either SUBMITTED or
    COUNTERED, overwrites the live bid_amount_cents with the new offer, increments
    round_count by one, and flips last_actor to the party that just acted."
    PRD §3.2: "Because a proposal can cycle from COUNTERED back to COUNTERED many times,
    the negotiation may run for several rounds before either side settles."

    Design: Difficulty/non_linear_state_machine/proposal_cyclic_counter_rounds
    """
    client, freelancer, posting, proposal, ch, fh = _open_posting_with_proposal()
    # Client counters (last_actor was FREELANCER, so CLIENT may act).
    after1 = validate_success(api.counter_proposal(
        proposal["id"], counter_payload("CLIENT", 45000), ch), 200)
    assert after1["status"] == "COUNTERED"
    assert after1["round_count"] == 1
    assert after1["last_actor"] == "CLIENT"
    assert after1["bid_amount_cents"] == 45000
    # Freelancer counters back (cycle COUNTERED -> COUNTERED).
    after2 = validate_success(api.counter_proposal(
        proposal["id"], counter_payload("FREELANCER", 52000), fh), 200)
    assert after2["status"] == "COUNTERED"
    assert after2["round_count"] == 2
    assert after2["last_actor"] == "FREELANCER"
    assert after2["bid_amount_cents"] == 52000


def test_counter_wrong_turn_rejected(api):
    """PRD §3.2: "A counter is permitted only while the posting is OPEN or UNDER_REVIEW,
    only while round_count is below the ceiling of five rounds, and only when the acting
    party is the opposite of the proposal's current last_actor so that turns strictly
    alternate. A counter that violates the turn rule or that has reached the five-round
    ceiling is rejected with ERR_NOT_YOUR_TURN."

    Design: Corner/validations/counter_wrong_turn_rejected
    """
    client, freelancer, posting, proposal, ch, fh = _open_posting_with_proposal(
        required_skills=("x",), freelancer_skills=("x",), bid_amount_cents=20000, budget_cents=30000)
    # last_actor is FREELANCER; freelancer countering again violates alternation.
    res = api.counter_proposal(proposal["id"], counter_payload("FREELANCER", 19000), fh)
    validate_error(res, "ERR_NOT_YOUR_TURN", expected_status=409)
    after = validate_success(api.get_proposal(proposal["id"], ch), 200)
    assert after["bid_amount_cents"] == 20000


def test_skills_not_covered_on_proposal(api):
    """PRD §3.2: "Before a proposal is accepted the system requires that the freelancer's
    skills cover every tag in the posting's required_skills; a proposal whose freelancer
    does not cover all required skills is rejected with ERR_SKILLS_NOT_COVERED."

    Design: Corner/validations/skills_not_covered_on_proposal
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["python"])
    fh = make_freelancer_headers(freelancer["id"])
    posting = validate_success(api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["rust"]), ch), 201)
    res = api.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=20000), fh)
    validate_error(res, "ERR_SKILLS_NOT_COVERED", expected_status=422)


def test_idempotency_double_accept_proposal(api):
    """PRD §3.2: "Acceptance moves the proposal to ACCEPTED" and "The terminal proposal
    states are ACCEPTED, DECLINED, and WITHDRAWN."
    PRD §5: re-acting on a proposal not in an acceptable state yields ERR_INVALID_PROPOSAL_STATE.

    Design: Corner/state_machines/idempotency_double_accept_proposal
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["x"])
    fh = make_freelancer_headers(freelancer["id"])
    posting = validate_success(api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["x"]), ch), 201)
    proposal = validate_success(api.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=20000), fh), 201)
    validate_success(api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch), 200)
    res = api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch)
    validate_error(res, "ERR_INVALID_PROPOSAL_STATE", expected_status=409)


def test_accept_after_posting_cancelled_rejected(api):
    """PRD §3.2: "A Client may cancel a posting while it is OPEN or UNDER_REVIEW;
    cancellation moves it to CANCELLED and declines every proposal still in SUBMITTED or
    COUNTERED."
    PRD §3.2: acceptance is "permitted from SUBMITTED or COUNTERED" — a DECLINED proposal
    therefore cannot be accepted (ERR_INVALID_PROPOSAL_STATE).

    Design: Difficulty/cross_entity_state_dependency/cross_proposal_accept_requires_posting_open
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["ui"], tax_id_on_file=False)
    fh = make_freelancer_headers(freelancer["id"])
    posting = validate_success(api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["ui"]), ch), 201)
    proposal = validate_success(api.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=20000), fh), 201)
    validate_success(api.cancel_job_posting(posting["id"], ch), 200)
    declined = validate_success(api.get_proposal(proposal["id"], ch), 200)
    assert declined["status"] == "DECLINED"
    res = api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch)
    validate_error(res, "ERR_INVALID_PROPOSAL_STATE", expected_status=409)


def test_accept_requires_posting_open_via_proposal_state(api):
    """PRD §3.2: acceptance is "permitted from SUBMITTED or COUNTERED, only while the
    posting is OPEN or UNDER_REVIEW". After a cancel cascades the proposal to DECLINED, the
    accept is rejected with ERR_INVALID_PROPOSAL_STATE.

    Design: Difficulty/cross_entity_state_dependency/cross_proposal_accept_requires_posting_open
    """
    client = create_client()
    ch = make_client_headers(client["id"])
    freelancer = create_freelancer(skills=["ui"])
    fh = make_freelancer_headers(freelancer["id"])
    posting = validate_success(api.create_job_posting(
        create_job_posting_payload(client["id"], required_skills=["ui"]), ch), 201)
    proposal = validate_success(api.create_proposal(
        create_proposal_payload(posting["id"], freelancer["id"], bid_amount_cents=25000), fh), 201)
    validate_success(api.cancel_job_posting(posting["id"], ch), 200)
    res = api.accept_proposal(proposal["id"], accept_payload("CLIENT"), ch)
    validate_error(res, "ERR_INVALID_PROPOSAL_STATE", expected_status=409)
