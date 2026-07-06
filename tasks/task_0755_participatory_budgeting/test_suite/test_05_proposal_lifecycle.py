"""Proposal & cycle lifecycle: cross-entity ON_BALLOT, phase pipeline, window validation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    scenario_costed_proposal,
    new_cycle, new_category, new_resident, verify_resident, transition,
    new_proposal, submit_proposal, create_budget_cycle_payload,
    make_resident_headers, TEST_USERS,
)

ADMIN = TEST_USERS["budget_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#             proposal_reaches_on_ballot_only_when_cycle_enters_voting
# ---------------------------------------------------------------------------

def test_costed_proposal_stays_costed_while_cycle_in_development(api):
    """PRD §2.4: "This is the sole path by which a proposal reaches `ON_BALLOT`: it happens
    as a side effect of its owning cycle entering `VOTING`, never by a direct request."

    Design: Difficulty/cross_entity_state_dependency/proposal_reaches_on_ballot_only_when_cycle_enters_voting
    """
    sc = scenario_costed_proposal(api)
    prop = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert prop["status"] == "COSTED", f"stays COSTED while cycle is DEVELOPMENT, got {prop['status']}"


def test_costed_proposal_cascades_to_on_ballot_when_cycle_enters_voting(api):
    """PRD §2.4: "When a cycle moves from `DEVELOPMENT` into `VOTING`, the system
    automatically transitions every proposal in that cycle whose status is `COSTED` from
    `COSTED` to `ON_BALLOT`, and each such automatic transition increments that proposal's
    `version` by one."

    Design: Difficulty/cross_entity_state_dependency/proposal_reaches_on_ballot_only_when_cycle_enters_voting
    """
    sc = scenario_costed_proposal(api)
    transition(api, sc["cyc"], "VOTING")
    prop = validate_success(api.get_proposal(sc["pid"], ADMIN))
    assert prop["status"] == "ON_BALLOT", f"cycle entering VOTING cascades COSTED->ON_BALLOT, got {prop['status']}"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / cycle_phase_windows_overlap_rejected_halfopen
# ---------------------------------------------------------------------------

def test_overlapping_submission_and_voting_windows_rejected(api):
    """PRD §2.8: "the two windows must not overlap, and submission must not run past the
    start of voting — specifically `submission_end` must be at or before `voting_start`, so
    exact adjacency (`submission_end` equal to `voting_start`) is allowed but any true
    overlap is not. A cycle whose windows violate any of these conditions is rejected with
    `ERR_PHASE_WINDOW_OVERLAP` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cycle_phase_windows_overlap_rejected_halfopen
    """
    payload = create_budget_cycle_payload(
        name="PBt1",
        submission_start="2026-03-01T00:00:00Z",
        submission_end="2026-04-01T00:00:00Z",
        voting_start="2026-03-15T00:00:00Z",  # strictly before submission_end -> overlap
        voting_end="2026-05-01T00:00:00Z",
    )
    resp = api.create_budget_cycle(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP.value)


def test_window_with_start_not_before_end_rejected(api):
    """PRD §2.8: "each window's start must be strictly before its own end ... A cycle whose
    windows violate any of these conditions is rejected with `ERR_PHASE_WINDOW_OVERLAP`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cycle_phase_windows_overlap_rejected_halfopen
    """
    payload = create_budget_cycle_payload(
        name="PBt1b",
        submission_start="2026-03-01T00:00:00Z",
        submission_end="2026-03-01T00:00:00Z",  # start == end -> not strictly before
        voting_start="2026-04-01T00:00:00Z",
        voting_end="2026-05-01T00:00:00Z",
    )
    resp = api.create_budget_cycle(payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_PHASE_WINDOW_OVERLAP.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_phase_transition_skip_rejected
# ---------------------------------------------------------------------------

def test_phase_skip_from_draft_to_voting_rejected(api):
    """PRD §2.4: "The request is honored only when `target_phase` is exactly the single next
    phase in the pipeline; naming any other phase — whether a skip forward, a repeat, or a
    move backward — is rejected with `ERR_INVALID_PHASE_TRANSITION` (HTTP 409)."

    Design: Corner/state_machines/corner_phase_transition_skip_rejected
    """
    cyc = new_cycle(api, name="PBsk")
    new_category(api, cyc["id"])
    resp = api.transition_phase(cyc["id"], {"target_phase": "VOTING"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_PHASE_TRANSITION.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_submit_already_submitted_proposal_rejected
# ---------------------------------------------------------------------------

def test_submitting_already_submitted_proposal_rejected(api):
    """PRD §3.3: "The submitter advances their own draft: submitting a proposal moves it from
    `DRAFT` to `SUBMITTED`. This is permitted only while the proposal is still in `DRAFT`"

    Design: Corner/state_machines/corner_submit_already_submitted_proposal_rejected
    """
    cyc = new_cycle(api, name="PBss")
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    transition(api, cyc["id"], "SUBMISSION")
    prop = new_proposal(api, cyc["id"], cat["id"], res["id"])
    submit_proposal(api, prop["id"], res["id"])
    resp = api.submit_proposal(prop["id"], make_resident_headers(res["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_review_decision_on_rejected_proposal_locked
# ---------------------------------------------------------------------------

def test_review_decision_on_rejected_proposal_rejected(api):
    """PRD §3.3: "Both branches require the proposal to be in `SUBMITTED` and the cycle to be
    in `DEVELOPMENT` ... A review decision against a proposal not in `SUBMITTED` is rejected
    with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_review_decision_on_rejected_proposal_locked
    """
    cyc = new_cycle(api, name="PBrj")
    cat = new_category(api, cyc["id"])
    res = new_resident(api)
    transition(api, cyc["id"], "SUBMISSION")
    prop = new_proposal(api, cyc["id"], cat["id"], res["id"])
    submit_proposal(api, prop["id"], res["id"])
    transition(api, cyc["id"], "DEVELOPMENT")
    validate_success(api.review_proposal(prop["id"], {"decision": "REJECT", "rejection_reason": "out of scope"}, REVIEWER))
    resp = api.review_proposal(prop["id"], {"decision": "APPROVE"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: state_machines / corner_verify_decision_on_verified_resident_rejected
# ---------------------------------------------------------------------------

def test_verification_decision_on_verified_resident_rejected(api):
    """PRD §3.1: "a decision is only valid against a resident currently in
    `PENDING_VERIFICATION`; otherwise it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_verify_decision_on_verified_resident_rejected
    """
    res = new_resident(api)
    verify_resident(api, res["id"])  # now VERIFIED
    resp = api.decide_verification(res["id"], {"decision": "REJECT", "rejection_reason": "x"}, REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Corner: validations / corner_proposal_category_from_other_cycle_rejected
# ---------------------------------------------------------------------------

def test_proposal_with_category_from_other_cycle_rejected(api):
    """PRD §3.3: "A proposal must be filed into a category that belongs to the very same
    cycle; if the named `category_id` resolves to a category under a different cycle than the
    proposal's `budget_cycle_id`, the request is rejected with `ERR_CATEGORY_CYCLE_MISMATCH`
    (HTTP 422)."

    Design: Corner/validations/corner_proposal_category_from_other_cycle_rejected
    """
    cyc_a = new_cycle(api, name="A")
    cyc_b = new_cycle(api, name="B")
    cat_b = new_category(api, cyc_b["id"], name="GenB")
    new_category(api, cyc_a["id"], name="GenA")
    res = new_resident(api)
    transition(api, cyc_a["id"], "SUBMISSION")
    resp = api.create_proposal(
        cyc_a["id"], {"category_id": cat_b["id"], "title": "X", "summary": "s"}, make_resident_headers(res["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CATEGORY_CYCLE_MISMATCH.value)
