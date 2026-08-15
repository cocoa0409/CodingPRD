"""Committee decisions and their side effects: the RETURNED resubmission
loop, terminal-state lockdowns, immediate consistency of mutating responses,
withdrawal ledger effects, term reassignment, and the course-number hold
conservation invariant.
"""
from test_helpers import (
    ApiErrorId,
    create_and_activate_new_course,
    create_department,
    create_new_course_proposal,
    create_submitted_new_course_proposal,
    create_term,
    create_term_2027sp,
    fully_approve_proposal,
    get_proposal,
    get_term,
    list_decision_records,
    make_chair_headers,
    make_proposer_headers,
    make_registrar_headers,
    post_decision,
    reassign_effective_term,
    submit_proposal,
    validate_error,
    validate_success,
)


# -------------------------------------------------------------------------
# The RETURNED -> DEPT_REVIEW resubmission cycle
# -------------------------------------------------------------------------

def test_returned_proposal_resubmits_to_dept_review(api):
    """PRD §3.5: "A return sends the proposal to `RETURNED` — from
    `DEPT_REVIEW`, from `COMMITTEE_REVIEW`, from `SENATE_REVIEW`, or from
    `REGISTRAR_REVIEW` — while a reject terminates it in `REJECTED`."
    PRD §3.5: "A returned proposal is not dead; its author may edit it and
    resubmit, at which point the full submission battery runs again and fresh
    links are created — the links removed at return stay removed."

    Design: Difficulty/non_linear_state_machine/proposal_return_resubmit_cycle
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")

    returned = post_decision(proposal["id"], "RETURN",
                             make_chair_headers(dept["id"]),
                             rationale="expand outcomes")
    assert returned["status"] == "RETURNED", "cycle entry"

    resubmitted = submit_proposal(proposal["id"])
    assert resubmitted["status"] == "DEPT_REVIEW", (
        "the loop returns to the same review stage, not a new state")


def test_return_resubmit_cycle_appends_ordered_decision_records(api):
    """PRD §3.11: "Every action taken on a proposal — submit, approve, return,
    reject, withdraw, notify, reassign-term, and activate — is preserved as an
    immutable `DecisionRecord`."
    PRD §3.11: "A proposal's decision log is retrievable in chronological
    order."

    Design: Difficulty/non_linear_state_machine/proposal_return_resubmit_cycle
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")
    post_decision(proposal["id"], "RETURN", make_chair_headers(dept["id"]),
                  rationale="expand outcomes")
    submit_proposal(proposal["id"])

    records = list_decision_records(proposal["id"])
    assert [r["action"] for r in records] == ["SUBMIT", "RETURN", "SUBMIT"], (
        "the append-only log preserves the cycle in creation order")
    assert len(records) == 3


# -------------------------------------------------------------------------
# Terminal-state lockdowns
# -------------------------------------------------------------------------

def test_withdraw_effective_proposal_rejected(api):
    """PRD §3.5: "The author may also withdraw at any point before a terminal
    state."
    PRD §3.7: "Every activation appends the `ACTIVATE` decision record and
    increments the proposal's `version`, leaving the proposal in the terminal
    `EFFECTIVE` state."
    PRD §2.8: "sixth, whether the requested transition exists from the
    resource's current state (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/withdraw_effective_proposal_rejected
    """
    dept = create_department()
    term = create_term()
    activated, _course = create_and_activate_new_course(
        dept["id"], term["id"], "450", proposed_title="A",
        learning_outcomes=["a"])
    assert activated["status"] == "EFFECTIVE"

    resp = api.withdraw_proposal(activated["id"],
                                 make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_proposal(activated["id"])["status"] == "EFFECTIVE"


def test_decision_on_rejected_proposal_rejected(api):
    """PRD §3.5: "A return sends the proposal to `RETURNED` — from
    `DEPT_REVIEW`, from `COMMITTEE_REVIEW`, from `SENATE_REVIEW`, or from
    `REGISTRAR_REVIEW` — while a reject terminates it in `REJECTED`."
    PRD §2.8: "sixth, whether the requested transition exists from the
    resource's current state (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/decision_on_rejected_proposal_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450")
    rejected = post_decision(proposal["id"], "REJECT",
                             make_chair_headers(dept["id"]),
                             rationale="not needed")
    assert rejected["status"] == "REJECTED"

    resp = api.post_decision(proposal["id"], {"action": "APPROVE"},
                             make_chair_headers(dept["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_proposal(proposal["id"])["status"] == "REJECTED"


# -------------------------------------------------------------------------
# Immediate consistency of mutating responses
# -------------------------------------------------------------------------

def test_immediate_visibility_after_decision(api):
    """PRD §1: "Every mutation is visible in its own response, and every
    governance decision is preserved in an append-only audit trail."
    PRD §3.5: "Approval moves the proposal one stage forward — `DEPT_REVIEW →
    COMMITTEE_REVIEW`, `COMMITTEE_REVIEW → SENATE_REVIEW`, `SENATE_REVIEW →
    REGISTRAR_REVIEW` — appending a `DecisionRecord` with action `APPROVE` and
    the appropriate from/to statuses and incrementing `version` at each hop."

    Design: Corner/consistency_model/immediate_visibility_after_decision
    """
    dept = create_department()
    term = create_term()
    draft = create_new_course_proposal(dept["id"], term["id"], "450",
                                       proposed_title="A",
                                       learning_outcomes=["a"])
    created_version = draft["version"]
    submit_proposal(draft["id"])

    approved = post_decision(draft["id"], "APPROVE",
                             make_chair_headers(dept["id"]))
    assert approved["status"] == "COMMITTEE_REVIEW", (
        "the mutating response itself carries the new status")
    assert approved["version"] == created_version + 2, (
        "one increment at submit and one at the approve hop")


# -------------------------------------------------------------------------
# Withdrawal ledger effects and term reassignment
# -------------------------------------------------------------------------

def test_withdraw_from_approved_releases_term_count(api):
    """PRD §3.5: "Withdrawal from any review stage removes the proposal's
    `PROPOSED` links and releases the number hold, and withdrawal from
    `APPROVED` additionally decrements the effective term's
    `scheduled_proposal_count` by one."
    PRD §3.7: "On success the proposal's `effective_term_id` is set, the chosen
    term's `scheduled_proposal_count` increments by one, a `DecisionRecord` is
    appended with the action `APPROVE` and the assigned term captured in its
    denormalized `recorded_term_id`, and the proposal lands in `APPROVED`."

    Design: Corner/endpoints/withdraw_from_approved_releases_term_count
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450", proposed_title="A",
                                                    learning_outcomes=["a"])
    fully_approve_proposal(proposal["id"], dept["id"], term["id"])
    assert get_term(term["id"])["scheduled_proposal_count"] == 1

    withdrawn = validate_success(
        api.withdraw_proposal(proposal["id"], make_proposer_headers("fac-001")))
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_term(term["id"])["scheduled_proposal_count"] == 0, (
        "the approval had booked 1; withdrawal released it")


def test_reassign_same_term_rejected(api):
    """PRD §3.7: "While `APPROVED`, the registrar may reassign the effective
    term by supplying a different `effective_term_id`; supplying the term
    already assigned, or a term that does not exist, is `ERR_VALIDATION`."

    Design: Corner/endpoints/reassign_same_term_rejected
    """
    dept = create_department()
    term = create_term()
    proposal = create_submitted_new_course_proposal(dept["id"], term["id"],
                                                    "450", proposed_title="A",
                                                    learning_outcomes=["a"])
    fully_approve_proposal(proposal["id"], dept["id"], term["id"])

    resp = api.post_decision(
        proposal["id"],
        {"action": "REASSIGN_TERM", "effective_term_id": term["id"]},
        make_registrar_headers())
    validate_error(resp, ApiErrorId.ERR_VALIDATION)
    assert get_proposal(proposal["id"])["effective_term_id"] == term["id"]


def test_reassign_term_moves_scheduled_count_between_terms(api):
    """PRD §3.7: "Reassignment decrements the old term's
    `scheduled_proposal_count` by one, increments the new term's by one,
    re-points the proposal, appends the corresponding decision record with the
    new term in `recorded_term_id`, and increments `version`."
    PRD §3.1: "A term also exposes the computed `scheduled_proposal_count`, the
    number of proposals whose assigned effective term is this one and whose
    status is either `APPROVED` or `EFFECTIVE`."

    Design: Difficulty/compensating_invariant/term_scheduled_count_reassignment_conservation
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    proposal = create_submitted_new_course_proposal(dept["id"], t1["id"],
                                                    "470", proposed_title="Net",
                                                    learning_outcomes=["x"],
                                                    justification="new")
    fully_approve_proposal(proposal["id"], dept["id"], t1["id"])
    assert get_term(t1["id"])["scheduled_proposal_count"] == 1, (
        "the registrar's approval booked the count on T1")

    moved = reassign_effective_term(proposal["id"], t2["id"])
    assert moved["effective_term_id"] == t2["id"]
    assert get_term(t1["id"])["scheduled_proposal_count"] == 0
    assert get_term(t2["id"])["scheduled_proposal_count"] == 1
    # Conservation: the two ledgers sum to the single in-flight approval.
    assert (get_term(t1["id"])["scheduled_proposal_count"]
            + get_term(t2["id"])["scheduled_proposal_count"]) == 1


def test_compensating_reassign_restores_both_term_ledgers(api):
    """PRD §3.7: "Reassignment decrements the old term's
    `scheduled_proposal_count` by one, increments the new term's by one,
    re-points the proposal, appends the corresponding decision record with the
    new term in `recorded_term_id`, and increments `version`."

    Design: Difficulty/compensating_invariant/term_scheduled_count_reassignment_conservation
    """
    dept = create_department()
    t1 = create_term()
    t2 = create_term_2027sp()
    proposal = create_submitted_new_course_proposal(dept["id"], t1["id"],
                                                    "470", proposed_title="Net",
                                                    learning_outcomes=["x"],
                                                    justification="new")
    fully_approve_proposal(proposal["id"], dept["id"], t1["id"])

    reassign_effective_term(proposal["id"], t2["id"])
    reassign_effective_term(proposal["id"], t1["id"])

    assert get_term(t1["id"])["scheduled_proposal_count"] == 1, (
        "the compensating move restores T1's ledger exactly")
    assert get_term(t2["id"])["scheduled_proposal_count"] == 0
    assert get_proposal(proposal["id"])["effective_term_id"] == t1["id"]


# -------------------------------------------------------------------------
# Course-number hold conservation
# -------------------------------------------------------------------------

def test_second_proposal_blocked_while_number_held(api):
    """PRD §3.4: "For a new course, the proposed combination of subject code
    and course number must be free. The combination is considered held when any
    course in `ACTIVE` or `DEACTIVATING` status already carries it, or when
    another in-flight proposal — one in `DEPT_REVIEW`, `COMMITTEE_REVIEW`,
    `SENATE_REVIEW`, `REGISTRAR_REVIEW`, or `APPROVED` — holds it; a conflict
    is rejected with `ERR_COURSE_NUMBER_HELD`."

    Design: Difficulty/compensating_invariant/course_number_hold_release_conservation
    """
    dept = create_department()
    term = create_term()
    create_submitted_new_course_proposal(dept["id"], term["id"], "499",
                                         proposed_title="P1",
                                         learning_outcomes=["x"],
                                         justification="first")
    p2 = create_new_course_proposal(dept["id"], term["id"], "499",
                                    proposed_title="P2",
                                    learning_outcomes=["x"],
                                    justification="second")

    resp = api.submit_proposal(p2["id"], make_proposer_headers("fac-001"))
    validate_error(resp, ApiErrorId.ERR_COURSE_NUMBER_HELD)


def test_number_pool_restored_after_withdraw(api):
    """PRD §3.5: "Withdrawal from any review stage removes the proposal's
    `PROPOSED` links and releases the number hold, and withdrawal from
    `APPROVED` additionally decrements the effective term's
    `scheduled_proposal_count` by one. Every withdrawal requires authorship
    (else `ERR_NOT_RESOURCE_OWNER`), lands the proposal in the terminal
    `WITHDRAWN` state, and increments `version`."

    Design: Difficulty/compensating_invariant/course_number_hold_release_conservation
    """
    dept = create_department()
    term = create_term()
    p1 = create_submitted_new_course_proposal(dept["id"], term["id"], "499",
                                              proposed_title="P1",
                                              learning_outcomes=["x"],
                                              justification="first")
    p2 = create_new_course_proposal(dept["id"], term["id"], "499",
                                    proposed_title="P2",
                                    learning_outcomes=["x"],
                                    justification="second")
    validate_error(
        api.submit_proposal(p2["id"], make_proposer_headers("fac-001")),
        ApiErrorId.ERR_COURSE_NUMBER_HELD)

    withdrawn = validate_success(
        api.withdraw_proposal(p1["id"], make_proposer_headers("fac-001")))
    assert withdrawn["status"] == "WITHDRAWN", (
        "the compensating action releases the hold")

    resubmitted = validate_success(
        api.submit_proposal(p2["id"], make_proposer_headers("fac-001")))
    assert resubmitted["status"] == "DEPT_REVIEW", (
        "hold-then-release leaves the available-number pool unchanged")
