"""Validation precedence pairs and LOSS_OF_USE displacement-interval overlap."""
from test_helpers import (
    add_claim_item,
    api_client,
    create_policyholder,
    file_lou_claim,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    setup_lapsed_policy,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["adjuster_headers"]


# ---------------------------------------------------------------------------
# Queue A: priority_pair_validation_conflict — state beats fiscal/temporal
# ---------------------------------------------------------------------------
def test_claim_file_state_beats_loss_outside_term(api):
    """PRD §2.9: "Only after all of those does the system evaluate state and
    business rules: whether the target is in a state from which the transition
    is defined (`ERR_INVALID_STATE`), then the operation-specific business
    constraints described throughout §3."
    PRD §3.7: "Filing requires the owning policy to be `ACTIVE`; against a
    policy in any other status the filing is rejected with
    `ERR_POLICY_NOT_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/claim_file_state_beats_fiscal_on_lapsed_policy
    """
    s = setup_lapsed_policy(email="pp1@x.com")
    # Policy is LAPSED AND the loss_date (2025-12-01) is before effective_date,
    # which would also be ERR_LOSS_OUTSIDE_TERM. The state check wins.
    resp = api.file_claim(
        s["policy"]["id"],
        {"loss_type": "PERSONAL_PROPERTY", "loss_date": "2025-12-01T00:00:00Z"},
        make_policyholder_headers(s["policyholder"]["id"]),
    )
    validate_error(resp, "ERR_POLICY_NOT_ACTIVE", 409)


def test_loss_outside_term_surfaces_when_policy_active(api):
    """PRD §2.9: "Only after all of those does the system evaluate state and
    business rules: whether the target is in a state from which the transition
    is defined (`ERR_INVALID_STATE`), then the operation-specific business
    constraints described throughout §3."
    PRD §3.7: "a loss dated outside the term is rejected with
    `ERR_LOSS_OUTSIDE_TERM`."

    With the state precondition satisfied (policy ACTIVE), the lower-priority
    business-temporal error is the one that surfaces — confirming the LAPSED
    case is suppressed by the higher-priority state check.

    Design: Difficulty/priority_pair_validation_conflict/claim_file_state_beats_fiscal_on_lapsed_policy
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="pp1b@x.com",
                                                    clock="2026-06-01T00:00:00Z")
    resp = api.file_claim(
        policy["id"],
        {"loss_type": "PERSONAL_PROPERTY", "loss_date": "2025-12-01T00:00:00Z"},
        make_policyholder_headers(_ph["id"]),
    )
    validate_error(resp, "ERR_LOSS_OUTSIDE_TERM", 422)


def test_approve_existence_beats_fiscal_on_missing_claim(api):
    """PRD §2.9: "Existence checks follow: path identifiers resolved left to
    right (`ERR_NOT_FOUND`)".
    PRD §2.9: "a state error is never reported for a resource that does not
    exist."

    Design: Difficulty/priority_pair_validation_conflict/approve_existence_beats_fiscal_limit_on_missing_claim
    """
    # No claim with this id exists; approve must fail with the path-existence
    # error before any fiscal limit math could run.
    resp = api.approve_claim("00000000-0000-4000-8000-000000000000", ADJ)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_start_review_missing_claim_returns_not_found(api):
    """PRD §2.5: "The same `ERR_NOT_FOUND` covers any single-resource fetch
    whose path identifier is unknown."
    PRD §2.9: "a state error is never reported for a resource that does not
    exist."

    A claim-path action on a non-existent claim id resolves the path-existence
    error before any state or business check, just as approve does.

    Design: Difficulty/priority_pair_validation_conflict/approve_existence_beats_fiscal_limit_on_missing_claim
    """
    resp = api.start_review("00000000-0000-4000-8000-000000000000", ADJ)
    validate_error(resp, "ERR_NOT_FOUND", 404)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap — LOU displacement closed-interval overlap
# ---------------------------------------------------------------------------
def test_lou_displacement_shared_boundary_rejected(api):
    """PRD §3.7: "this interval must neither overlap nor share a boundary
    instant with the displacement interval of any existing non-terminal
    `LOSS_OF_USE` claim on the same policy, and any such collision — including
    one that merely touches at a shared endpoint — is rejected with
    `ERR_DISPLACEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/loss_of_use_displacement_closed_interval_shared_boundary_rejected
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="to2@x.com")
    ph_id = _ph["id"]
    file_lou_claim(policy["id"], ph_id, "2026-04-01T00:00:00Z",
                   "2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z")
    # Second LOU claim sharing the endpoint 2026-04-10 is rejected.
    resp = api.file_claim(
        policy["id"],
        {"loss_type": "LOSS_OF_USE", "loss_date": "2026-04-15T00:00:00Z",
         "displacement_start": "2026-04-10T00:00:00Z",
         "displacement_end": "2026-04-20T00:00:00Z"},
        make_policyholder_headers(ph_id),
    )
    validate_error(resp, "ERR_DISPLACEMENT_OVERLAP", 409)


def test_lou_displacement_non_overlapping_accepted(api):
    """PRD §3.7: "this interval must neither overlap nor share a boundary
    instant with the displacement interval of any existing non-terminal
    `LOSS_OF_USE` claim on the same policy, and any such collision — including
    one that merely touches at a shared endpoint — is rejected with
    `ERR_DISPLACEMENT_OVERLAP`."

    A strictly later, non-touching interval is accepted.

    Design: Difficulty/resource_temporal_overlap/loss_of_use_displacement_closed_interval_shared_boundary_rejected
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="to2b@x.com")
    ph_id = _ph["id"]
    file_lou_claim(policy["id"], ph_id, "2026-04-01T00:00:00Z",
                   "2026-04-01T00:00:00Z", "2026-04-10T00:00:00Z")
    # A disjoint interval starting strictly after the prior end is accepted.
    resp = api.file_claim(
        policy["id"],
        {"loss_type": "LOSS_OF_USE", "loss_date": "2026-04-15T00:00:00Z",
         "displacement_start": "2026-04-11T00:00:00Z",
         "displacement_end": "2026-04-20T00:00:00Z"},
        make_policyholder_headers(ph_id),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "FILED", data["status"]
