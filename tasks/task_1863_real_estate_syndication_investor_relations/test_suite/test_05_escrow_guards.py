"""Escrow guard rails: state-vs-fiscal ordering, overpayment, past-due,
incomplete release, and investor ownership of contributions."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    contribution_for,
    get_contribution,
    issue_capital_call,
    make_investor,
    make_investor_headers,
    receive_escrow_payload,
    set_clock,
    setup_offering_with_approved_subscriptions,
    validate_error,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_operator_headers"]


class TestStateBeatsFiscalOnRelease:
    def test_release_pending_contribution_state_beats_fiscal(self, api):
        """PRD §2.9: "Only then does the generic state-transition guard apply,
        and after it the domain-specific guards in their documented sequence
        for each workflow". PRD §2.8: "State-transition attempts made against a
        resource that is not in a state from which the requested transition is
        allowed are rejected with `ERR_INVALID_STATE` (HTTP 409)." A release
        against a contribution still in PENDING (nothing received, so the
        completeness gate would also fail) is answered by the state guard, not
        by ERR_ESCROW_INCOMPLETE.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_release_escrow
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub = ctx["subs"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        assert contrib["status"] == "PENDING"
        assert contrib["amount_received_cents"] == 0

        resp = api.release_escrow(syn_id, off_id, call["id"], contrib["id"],
                                  SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_release_defaulted_contribution_state_beats_fiscal(self, api):
        """PRD §3.4: "If a contribution's `due_date` passes with
        `amount_received_cents` still short of `amount_due_cents`, the
        contribution moves to `DEFAULTED` — observed lazily on the next read or
        write against it, or eagerly once the logical clock is advanced past
        the due date." PRD §2.9 places "the generic state-transition guard"
        before "the domain-specific guards", so releasing a DEFAULTED
        (under-funded) contribution answers ERR_INVALID_STATE rather than
        ERR_ESCROW_INCOMPLETE.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_release_escrow
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        set_clock("2026-05-01T00:00:00Z")
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000,
                                            due_date="2026-06-01T00:00:00Z")
        contrib = contribution_for(contribs, sub["id"])
        # Partial wire before the due date: 2,000,000 of 5,000,000 due.
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(2_000_000), make_investor_headers(inv["id"])))
        # Advance the logical clock past the due date; the short contribution
        # defaults.
        set_clock("2026-06-02T00:00:00Z")
        contrib_now = get_contribution(syn_id, off_id, call["id"], contrib["id"])
        assert contrib_now["status"] == "DEFAULTED", (
            f"past-due short contribution must be DEFAULTED, "
            f"got {contrib_now['status']}")

        resp = api.release_escrow(syn_id, off_id, call["id"], contrib["id"],
                                  SPONSOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestEscrowGuards:
    def test_escrow_overpayment_rejected(self, api):
        """PRD §3.4: "Two business guards then apply in order: first the
        overpayment guard — the cumulative `amount_received_cents` after this
        receipt must not exceed `amount_due_cents`, or the wire is rejected
        with `ERR_ESCROW_OVERPAYMENT`".

        Design: Corner/validations/escrow_overpayment_rejected
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        assert contrib["amount_due_cents"] == 5_000_000

        resp = api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(5_000_001), make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_ESCROW_OVERPAYMENT, 422)

    def test_escrow_past_due_rejected(self, api):
        """PRD §3.4: "and then the timeliness guard, under which a receipt
        arriving after the call's `due_date` is rejected with
        `ERR_ESCROW_PAST_DUE`."

        Design: Corner/validations/escrow_past_due_rejected
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        set_clock("2026-05-01T00:00:00Z")
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000,
                                            due_date="2026-06-01T00:00:00Z")
        contrib = contribution_for(contribs, sub["id"])
        set_clock("2026-06-02T00:00:00Z")

        resp = api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(5_000_000), make_investor_headers(inv["id"]))
        validate_error(resp, ApiErrorId.ERR_ESCROW_PAST_DUE, 422)

    def test_escrow_incomplete_on_release(self, api):
        """PRD §3.4: "Escrow release is the sponsor's act, and it is gated on
        completeness: a contribution can be released only when the call is
        `ISSUED` or `PARTIALLY_FUNDED` and its `amount_received_cents` exactly
        equals `amount_due_cents` — a partial position cannot be released and
        is rejected with `ERR_ESCROW_INCOMPLETE`."

        Design: Corner/errors/error_escrow_incomplete_on_release
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub, inv = ctx["subs"][0], ctx["investors"][0]
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])
        validate_success(api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(2_000_000), make_investor_headers(inv["id"])))
        contrib_now = get_contribution(syn_id, off_id, call["id"], contrib["id"])
        assert contrib_now["status"] == "ESCROW_RECEIVED"
        assert contrib_now["amount_received_cents"] == 2_000_000

        resp = api.release_escrow(syn_id, off_id, call["id"], contrib["id"],
                                  SPONSOR)
        validate_error(resp, ApiErrorId.ERR_ESCROW_INCOMPLETE, 422)


class TestContributionOwnership:
    def test_receive_escrow_other_investor_rejected(self, api):
        """PRD §3.4: "the investor's `X-User-ID` must equal the `investor_id`
        of the subscription behind the contribution, otherwise
        `ERR_NOT_YOUR_CONTRIBUTION`."

        Design: Corner/errors/error_not_your_contribution
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub = ctx["subs"][0]
        other = make_investor(full_legal_name="Other Investor")
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])

        resp = api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(5_000_000),
            make_investor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_YOUR_CONTRIBUTION, 403)

    def test_investor_identity_must_match_contribution_owner(self, api):
        """PRD §2.1: "When `X-User-Role` is `Investor`, `X-User-ID` is the `id`
        of the acting `Investor`; ownership checks on any resource that
        references an `Investor` compare the resource's foreign-key field to
        `X-User-ID`." PRD §3.4: "the investor's `X-User-ID` must equal the
        `investor_id` of the subscription behind the contribution, otherwise
        `ERR_NOT_YOUR_CONTRIBUTION`."

        Design: Corner/roles/investor_entity_backed_identity_must_match
        """
        ctx = setup_offering_with_approved_subscriptions([5_000_000])
        syn_id, off_id = ctx["syn"]["id"], ctx["off"]["id"]
        sub = ctx["subs"][0]
        other = make_investor(full_legal_name="Second Investor")
        call, contribs = issue_capital_call(syn_id, off_id, 5_000_000)
        contrib = contribution_for(contribs, sub["id"])

        # A partial wire from the wrong investor id is still rejected.
        resp = api.receive_escrow(
            syn_id, off_id, call["id"], contrib["id"],
            receive_escrow_payload(1_000_000),
            make_investor_headers(other["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_YOUR_CONTRIBUTION, 403)
