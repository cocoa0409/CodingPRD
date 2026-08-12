"""Claim adjudication: denial/appeal cycle, budget identity, payment settlement,
appeal window, role segregation."""
from test_helpers import (
    ADMIN,
    COORD,
    ApiErrorId,
    adjudicate_claim,
    appeal_claim,
    assert_program_budget_identity,
    make_provider_headers,
    pay_claim,
    setup_approved_claim,
    setup_submitted_claim,
    setup_verified_service,
    set_clock,
    submit_claim,
    validate_error,
    validate_success,
)


class TestClaimDenialAppealApprovalCycle:
    def test_denial_then_appeal_then_approval(self, api):
        """PRD §3.10: "A denial moves a `SUBMITTED` claim to `DENIED` or an `APPEALED`
        claim to `DENIED_FINAL`, sets `denial_reason` to the supplied reason, sets
        `decided_at` to the logical clock time, and appends a `RELEASE` ledger entry
        for the claim's `amount_cents`."
        PRD §3.10: "A claim in `DENIED` may be appealed by its owning provider"
        PRD §3.10: "An approval moves the claim to `APPROVED`"

        Design: Difficulty/non_linear_state_machine/claim_denial_appeal_approval_cycle
        """
        ctx = setup_submitted_claim()
        claim_id = ctx["claim"]["id"]

        denied = adjudicate_claim(claim_id, "DENY", reason="documentation gap")
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "documentation gap"

        appealed = appeal_claim(claim_id, ctx["provider"]["id"], reason="letter provided")
        assert appealed["status"] == "APPEALED"

        approved = adjudicate_claim(claim_id, "APPROVE")
        assert approved["status"] == "APPROVED"

    def test_denial_releases_and_appeal_approval_reencumbers(self, api):
        """PRD §3.10: "when the claim was in `APPEALED` rather than `SUBMITTED`, an
        approval additionally re-encumbers the claim's `amount_cents` (an `ENCUMBER`
        ledger entry, reversing the release that happened at denial) and increments
        `Program.version` by 1."

        Design: Difficulty/non_linear_state_machine/claim_denial_appeal_approval_cycle
        """
        ctx = setup_submitted_claim()  # claim 7500 encumbered
        program_id = ctx["program"]["id"]
        after_verify = validate_success(api.get_program(program_id, ADMIN), 200)
        assert after_verify["encumbered_cents"] == 7500

        adjudicate_claim(ctx["claim"]["id"], "DENY", reason="documentation gap")
        after_deny = validate_success(api.get_program(program_id, ADMIN), 200)
        assert after_deny["encumbered_cents"] == 0

        appeal_claim(ctx["claim"]["id"], ctx["provider"]["id"], reason="letter provided")
        adjudicate_claim(ctx["claim"]["id"], "APPROVE")
        after_reapprove = validate_success(api.get_program(program_id, ADMIN), 200)
        assert after_reapprove["encumbered_cents"] == 7500


class TestBudgetCentsIdentity:
    def test_deny_restores_unencumbered(self, api):
        """PRD §2.6: "The difference, `unencumbered_cents`, is by definition
        `total_budget_cents` minus `encumbered_cents` minus `settled_cents`"
        PRD §3.9: "On the budget side, the voucher's provisional encumbrance is
        released (a `RELEASE` ledger entry) and the claim's `amount_cents` is
        encumbered (an `ENCUMBER` ledger entry)."
        PRD §3.10: "A denial moves a `SUBMITTED` claim to `DENIED` or an `APPEALED`
        claim to `DENIED_FINAL`, sets `denial_reason` to the supplied reason, sets
        `decided_at` to the logical clock time, and appends a `RELEASE` ledger entry
        for the claim's `amount_cents`."

        Design: Difficulty/compensating_invariant/budget_cents_identity_verify_swap_then_deny
        """
        ctx = setup_submitted_claim()
        adjudicate_claim(ctx["claim"]["id"], "DENY", reason="insufficient documentation")
        program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
        assert program["total_budget_cents"] == 50000000
        assert program["unencumbered_cents"] == 50000000
        assert program["encumbered_cents"] == 0
        assert program["settled_cents"] == 0
        assert_program_budget_identity(program)

    def test_identity_holds_through_verify_swap(self, api):
        """PRD §2.6: "The difference, `unencumbered_cents`, is by definition
        `total_budget_cents` minus `encumbered_cents` minus `settled_cents`"
        PRD §3.9: "On the budget side, the voucher's provisional encumbrance is
        released (a `RELEASE` ledger entry) and the claim's `amount_cents` is
        encumbered (an `ENCUMBER` ledger entry)."

        Design: Difficulty/compensating_invariant/budget_cents_identity_verify_swap_then_deny
        """
        ctx = setup_verified_service()
        program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
        # Voucher provisional 60000 released; claim 7500 encumbered in its place.
        assert program["total_budget_cents"] == 50000000
        assert program["encumbered_cents"] == 7500
        assert program["settled_cents"] == 0
        assert program["unencumbered_cents"] == 50000000 - 7500
        assert_program_budget_identity(program)


def test_voucher_settled_after_claim_paid(api):
    """PRD §3.10: "Payment appends a `SETTLE` ledger entry for `amount_cents` — which
    decrements the program's `encumbered_cents` by `amount_cents` and increments its
    `settled_cents` by the same amount — sets `paid_at` to the logical clock time,
    moves the claim to `PAID`"
    PRD §3.10: "If after this payment the voucher has no claim in `DRAFT`, `SUBMITTED`,
    `APPROVED`, or `APPEALED` status and no booking in `PENDING_CONFIRMATION`,
    `CONFIRMED`, or `IN_SERVICE` status, the voucher transitions from `REDEEMED` to
    `SETTLED`."

    Design: Corner/state_machines/voucher_settled_after_claim_paid
    """
    ctx = setup_approved_claim()
    paid = pay_claim(ctx["claim"]["id"])
    assert paid["status"] == "PAID"

    voucher = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
    assert voucher["status"] == "SETTLED"

    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert program["encumbered_cents"] == 0
    assert program["settled_cents"] == 7500


def test_appeal_window_closed_after_30_days(api):
    """PRD §3.10: "A claim in `DENIED` may be appealed by its owning provider, but only
    when the logical clock is at or before `decided_at` plus the program's
    `appeal_window_days` (default 30 days). A later appeal is rejected with
    `ERR_APPEAL_WINDOW_CLOSED`."

    Design: Corner/validations/appeal_window_closed_after_30_days
    """
    ctx = setup_submitted_claim()
    claim_id = ctx["claim"]["id"]
    set_clock("2026-05-04T22:00:00Z")
    denied = adjudicate_claim(claim_id, "DENY", reason="documentation gap")
    assert denied["status"] == "DENIED"
    # decided_at + 30 days = 2026-06-03T22:00Z; appeal at +31 days is too late.
    set_clock("2026-06-04T22:00:00Z")
    res = api.appeal_claim(claim_id, {"reason": "too late"},
                           make_provider_headers(ctx["provider"]["id"]))
    validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED, expected_status=422)
    after = validate_success(api.get_claim(claim_id, COORD), 200)
    assert after["status"] == "DENIED"


def test_provider_cannot_pay_claim(api):
    """PRD §2.1: "A role that is authenticated but not named in the endpoint's role
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /respite/claims/{id}/pay is authorized for FunderAdmin only.

    Design: Corner/rbac/provider_cannot_pay_claim
    """
    ctx = setup_approved_claim()
    res = api.pay_claim(ctx["claim"]["id"], make_provider_headers(ctx["provider"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    after = validate_success(api.get_claim(ctx["claim"]["id"], COORD), 200)
    assert after["status"] == "APPROVED"


def test_coordinator_cannot_adjudicate_claim(api):
    """PRD §2.1: "A role that is authenticated but not named in the endpoint's role
    list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
    PRD §4: POST /respite/claims/{id}/adjudicate is authorized for FunderAdmin only.

    Design: Corner/rbac/coordinator_cannot_adjudicate_claim
    """
    ctx = setup_submitted_claim()
    res = api.adjudicate_claim(ctx["claim"]["id"], {"decision": "APPROVE"}, COORD)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    after = validate_success(api.get_claim(ctx["claim"]["id"], COORD), 200)
    assert after["status"] == "SUBMITTED"
