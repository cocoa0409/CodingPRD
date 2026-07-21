"""Settlement proposal, approval, rejection, and acceptance: the PROPOSED fork,
segregation-of-duties, the authority ceiling boundary, state-vs-fiscal precedence,
OCC on the claim version, supersession, and the accept-cascade to SETTLED."""
from test_helpers import (
    validate_success, validate_error,
    build_user_headers, propose_settlement_payload,
    setup_demand_issued_claim, setup_proposed_settlement, setup_settled_claim,
    propose_settlement,
)
from test_helpers import TEST_USERS, make_carrier_user_headers

SPECIALIST = TEST_USERS["specialist_headers"]
MANAGER = TEST_USERS["manager_headers"]
MANAGER2 = TEST_USERS["manager2_headers"]
READER = TEST_USERS["reader_headers"]


def test_reject_moves_settlement_to_rejected(api):
    """PRD §3.5: "Rejection simply moves the settlement from `PROPOSED` to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/settlement_branching_fork_to_rejected
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=1_000_000)
    resp = api.reject_settlement(ctx["settlement"]["id"], MANAGER)
    settlement = validate_success(resp)
    assert settlement["status"] == "REJECTED"


def test_reject_does_not_change_claim_state(api):
    """PRD §3.5: "Rejection simply moves the settlement from `PROPOSED` to `REJECTED`."

    Design: Difficulty/non_linear_state_machine/settlement_branching_fork_to_rejected
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=1_000_000)
    api.reject_settlement(ctx["settlement"]["id"], MANAGER)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], READER))
    assert claim["status"] == "DEMAND_ISSUED", "rejecting a settlement must not settle the claim"


def test_approve_at_exact_authority_ceiling_succeeds(api):
    """PRD §2.10: "a manager may approve only when the proposed `settled_amount_cents`
    does not exceed the managerial authority ceiling of 5,000,000 cents (that is,
    $50,000); a larger amount is rejected with `ERR_EXCEEDS_SETTLEMENT_AUTHORITY`."

    Design: Difficulty/boundary_precision_check/settlement_authority_at_exact_ceiling
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=5_000_000)
    resp = api.approve_settlement(ctx["settlement"]["id"], MANAGER2)
    settlement = validate_success(resp)
    assert settlement["status"] == "APPROVED"


def test_approve_one_cent_over_ceiling_rejected(api):
    """PRD §2.10: "a manager may approve only when the proposed `settled_amount_cents`
    does not exceed the managerial authority ceiling of 5,000,000 cents (that is,
    $50,000); a larger amount is rejected with `ERR_EXCEEDS_SETTLEMENT_AUTHORITY`."

    Design: Difficulty/boundary_precision_check/settlement_authority_at_exact_ceiling
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=5_000_001)
    resp = api.approve_settlement(ctx["settlement"]["id"], MANAGER2)
    validate_error(resp, "ERR_EXCEEDS_SETTLEMENT_AUTHORITY", 409)


def test_state_check_precedes_authority_on_approve(api):
    """PRD §2.11: "(7) that the target resource is in a state permitting the requested
    transition (`ERR_INVALID_STATE`); ... (10) settlement approval authority
    (`ERR_EXCEEDS_SETTLEMENT_AUTHORITY`)".
    PRD §2.11: "Lower-numbered checks take precedence".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settlement_approve
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=6_000_000)
    api.reject_settlement(ctx["settlement"]["id"], MANAGER)  # now REJECTED (terminal)
    resp = api.approve_settlement(ctx["settlement"]["id"], MANAGER2)
    validate_error(resp, "ERR_INVALID_STATE", 409)


def test_rejected_settlement_stays_rejected_after_failed_approve(api):
    """PRD §3.9: "a settlement's [terminal statuses] are `ACCEPTED`, `REJECTED`, and
    `SUPERSEDED`".

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_settlement_approve
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=6_000_000)
    api.reject_settlement(ctx["settlement"]["id"], MANAGER)
    api.approve_settlement(ctx["settlement"]["id"], MANAGER2)
    settlement = validate_success(api.get_settlement(ctx["settlement"]["id"], READER))
    assert settlement["status"] == "REJECTED", "a rejected settlement is terminal and unchanged"


def test_approver_equal_to_proposer_rejected(api):
    """PRD §2.10: "An attempt by the proposer to approve their own settlement is
    rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/sod_approver_equals_proposer_returns_error
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=1_000_000)  # proposer = spec-1
    same_user_manager = build_user_headers("spec-1", "RecoveryManager")
    resp = api.approve_settlement(ctx["settlement"]["id"], same_user_manager)
    validate_error(resp, "ERR_SEGREGATION_OF_DUTIES", 403)


def test_approve_over_authority_rejected(api):
    """PRD §2.10: "a manager may approve only when the proposed `settled_amount_cents`
    does not exceed the managerial authority ceiling of 5,000,000 cents (that is,
    $50,000); a larger amount is rejected with `ERR_EXCEEDS_SETTLEMENT_AUTHORITY`."

    Design: Corner/errors/approve_over_authority_returns_error
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=6_000_000)
    resp = api.approve_settlement(ctx["settlement"]["id"], MANAGER2)
    validate_error(resp, "ERR_EXCEEDS_SETTLEMENT_AUTHORITY", 409)


def test_specialist_cannot_approve_settlement(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted
    to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/specialist_cannot_approve_settlement_returns_forbidden
    """
    ctx = setup_proposed_settlement(api, settled_amount_cents=1_000_000)
    resp = api.approve_settlement(ctx["settlement"]["id"], build_user_headers("spec-9", "RecoverySpecialist"))
    validate_error(resp, "ERR_FORBIDDEN_FOR_ROLE", 403)


def test_stale_claim_version_on_second_proposal_rejected(api):
    """PRD §2.9: "If `expected_claim_version` does not equal the claim's current
    `version`, the proposal is rejected with `ERR_STALE_CLAIM_VERSION` at HTTP 412."

    Design: Corner/cross_cutting/occ_stale_claim_version_on_settlement_returns_412
    """
    ctx = setup_demand_issued_claim(api)
    claim = validate_success(api.get_claim(ctx["claim"]["id"], READER))
    stale_version = claim["version"]
    # First proposal succeeds and bumps the claim version.
    validate_success(
        api.propose_settlement(ctx["claim"]["id"], propose_settlement_payload(1_000_000, stale_version), SPECIALIST),
        201,
    )
    # Second proposal reuses the now-stale version.
    resp = api.propose_settlement(
        ctx["claim"]["id"], propose_settlement_payload(1_200_000, stale_version), SPECIALIST)
    validate_error(resp, "ERR_STALE_CLAIM_VERSION", 412)


def test_new_proposal_supersedes_prior_proposed(api):
    """PRD §3.5: "On success the settlement is created in `status` `PROPOSED`, the
    proposer's `X-User-ID` is recorded as `proposed_by_user_id`, any prior `PROPOSED`
    settlement on the same claim is moved to `SUPERSEDED`, and the claim's `version` is
    incremented by one."

    Design: Corner/cross_cutting/settlement_supersede_prior_proposed_positive
    """
    ctx = setup_demand_issued_claim(api)
    s1 = propose_settlement(api, ctx["claim"]["id"], 1_000_000)
    s2 = propose_settlement(api, ctx["claim"]["id"], 1_200_000)
    s1_now = validate_success(api.get_settlement(s1["id"], READER))
    s2_now = validate_success(api.get_settlement(s2["id"], READER))
    assert s1_now["status"] == "SUPERSEDED"
    assert s2_now["status"] == "PROPOSED"


def test_accept_settles_claim_and_sets_amount(api):
    """PRD §3.5: "Acceptance drives the claim to `SETTLED` and sets the claim's
    `settled_amount_cents` to the settlement's `settled_amount_cents` — this accepted
    amount is the claim's final recoverable figure."

    Design: Difficulty/transitive_cascade/settlement_accept_settles_claim_and_withdraws_arbitration
    """
    ctx = setup_settled_claim(api, settled_amount_cents=2_000_000, from_arbitration=True)
    assert ctx["settlement"]["status"] == "ACCEPTED"
    assert ctx["claim"]["status"] == "SETTLED"
    assert ctx["claim"]["settled_amount_cents"] == 2_000_000


def test_accept_from_arbitration_withdraws_live_arbitration(api):
    """PRD §3.5: "When the accepted claim was in `ARBITRATION`, acceptance additionally
    renders any live arbitration moot: every `Arbitration` for that claim in `FILED`,
    `AWAITING_RESPONSE`, or `RESPONSE_FILED` is cascaded to `WITHDRAWN`."

    Design: Difficulty/transitive_cascade/settlement_accept_settles_claim_and_withdraws_arbitration
    """
    ctx = setup_settled_claim(api, settled_amount_cents=2_000_000, from_arbitration=True)
    arb = validate_success(api.get_arbitration(ctx["arbitration"]["id"], READER))
    assert arb["status"] == "WITHDRAWN", "acceptance from ARBITRATION must moot the live arbitration"
