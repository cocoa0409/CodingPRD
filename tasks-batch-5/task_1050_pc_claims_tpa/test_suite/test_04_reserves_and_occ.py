"""Case reserves: adjuster authority ceiling, optimistic concurrency, conservation of the
account reserve pool, and validation-priority (state beats fiscal).

Translates the compensating_invariant (reserve pool) and priority_pair_validation_conflict
(state vs fiscal) difficulty instances plus reserve corner instances.
"""
from test_helpers import (
    validate_success, validate_error,
    create_reserve_change_payload, TEST_USERS,
    setup_assigned_claim, setup_closed_claim, claim_version, post_reserve_change,
    get_claim,
)

CM = TEST_USERS["claims_manager_headers"]


def test_adjuster_reserve_change_over_authority_rejected(api):
    """PRD §3.4: "After applying the delta, if the acting principal is an `Adjuster`, the
    claim's total case reserve — the sum of `indemnity_reserve_cents` and
    `expense_reserve_cents` after the change — must not exceed that adjuster's
    `authority_limit_cents`; if it would, the change is rejected with
    `ERR_RESERVE_AUTHORITY_EXCEEDED`."

    Design: Corner/validations/reserve_authority_exceeded_by_adjuster
    """
    env = setup_assigned_claim(
        api, account_overrides={"account_code": "C-RA"},
        adjuster_overrides={"authority_limit_cents": 100000})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    v1 = claim_version(api, claim_id, adj)
    payload = create_reserve_change_payload(claim_id, "INDEMNITY", 200000, v1, reason="big")
    validate_error(api.create_reserve_change(payload, adj), "ERR_RESERVE_AUTHORITY_EXCEEDED")


def test_reserve_change_with_stale_version_rejected(api):
    """PRD §2.6: "If `expected_claim_version` does not equal the claim's current `version`,
    the write is rejected with `ERR_STALE_VERSION` (HTTP 412), because another writer has
    advanced the claim since the client read it and proceeding would overwrite work the client
    never saw."

    Design: Corner/cross_cutting/reserve_change_stale_version_rejected
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "C-SV"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    v1 = claim_version(api, claim_id, adj)
    # First change succeeds and advances the claim past v1.
    post_reserve_change(api, claim_id, adj, 100000, reason="first", version=v1)
    # Second change still carries the now-stale v1.
    stale = create_reserve_change_payload(claim_id, "INDEMNITY", 100000, v1, reason="stale")
    validate_error(api.create_reserve_change(stale, adj), "ERR_STALE_VERSION")


def test_reserve_roundtrip_returns_claim_reserve_to_zero(api):
    """PRD §3.4: "Applying a change adds `delta_cents` to the named bucket, with the resulting
    bucket floored at zero (a negative delta can never drive a reserve below zero)."

    Design: Difficulty/compensating_invariant/account_reserve_pool_conserved_across_reserve_roundtrip
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CI2"})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    post_reserve_change(api, claim_id, adj, 500000, reason="up")
    post_reserve_change(api, claim_id, adj, -500000, reason="down")
    assert get_claim(api, claim_id, adj)["indemnity_reserve_cents"] == 0


def test_reserve_roundtrip_returns_account_pool_to_zero(api):
    """PRD §3.9: "`open_case_reserve_total_cents` is the sum of each open claim's
    `indemnity_reserve_cents` plus `expense_reserve_cents`, counting only claims whose status
    is `INTAKE`, `ASSIGNED`, `INVESTIGATING`, `EVALUATED`, or `REOPENED`."

    Design: Difficulty/compensating_invariant/account_reserve_pool_conserved_across_reserve_roundtrip
    """
    env = setup_assigned_claim(api, account_overrides={"account_code": "CI2b"})
    claim_id, adj, account_id = env["claim"]["id"], env["adj_headers"], env["account"]["id"]
    post_reserve_change(api, claim_id, adj, 500000, reason="up")
    post_reserve_change(api, claim_id, adj, -500000, reason="down")
    account = validate_success(api.get_client_account(account_id, CM), 200)
    assert account["open_case_reserve_total_cents"] == 0


def test_reserve_change_on_closed_claim_reports_state_error(api):
    """PRD §3.4: "The claim must be in an open status — `ASSIGNED`, `INVESTIGATING`,
    `EVALUATED`, or `REOPENED` — or the post is rejected with `ERR_CLAIM_NOT_OPEN`."
    PRD §2.8: "When a request could fail more than one check, the checks are evaluated in a
    fixed priority order and the first failure determines the error returned."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_change_to_closed_claim
    """
    env = setup_closed_claim(
        api, account_overrides={"account_code": "PP1"},
        adjuster_overrides={"authority_limit_cents": 5000000})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    v1 = claim_version(api, claim_id, adj)
    # Over-authority delta AND claim not open: state check (priority 5) wins over fiscal (11).
    payload = create_reserve_change_payload(claim_id, "INDEMNITY", 9000000000, v1, reason="big")
    validate_error(api.create_reserve_change(payload, adj), "ERR_CLAIM_NOT_OPEN")


def test_reserve_change_on_closed_claim_makes_no_mutation(api):
    """PRD §2.8: "the target resource is in a legal from-state for the requested transition,
    and the claim is open where required, else one of `ERR_INVALID_STATE`, `ERR_CLAIM_NOT_OPEN`,
    `ERR_PAYMENT_PENDING`, `ERR_LITIGATION_OPEN`, or `ERR_SUBROGATION_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_reserve_change_to_closed_claim
    """
    env = setup_closed_claim(
        api, account_overrides={"account_code": "PP1b"},
        adjuster_overrides={"authority_limit_cents": 5000000})
    claim_id, adj = env["claim"]["id"], env["adj_headers"]
    v1 = claim_version(api, claim_id, adj)
    payload = create_reserve_change_payload(claim_id, "INDEMNITY", 9000000000, v1, reason="big")
    validate_error(api.create_reserve_change(payload, adj), "ERR_CLAIM_NOT_OPEN")
    after = get_claim(api, claim_id, adj)
    assert after["status"] == "CLOSED"
    assert after["indemnity_reserve_cents"] == 0
