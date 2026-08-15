"""Fee/scope negotiation: provisional vs final totals, counter-party rules."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_fee_change,
    create_engagement,
    create_fee_change,
    create_fee_change_request_payload,
    create_fieldwork_engagement,
    get_engagement,
    get_fee_change,
    resolve_fee_change,
    withdraw_fee_change,
    validate_error,
    validate_success,
)

CONTROLLER = TEST_USERS["controller_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestProvisionalVsFinalTotal:

    def test_total_fee_provisional_while_fee_change_proposed(self):
        """PRD §2.7: "One read-time nuance applies: while any fee change
        request remains `PROPOSED`, the `total_fee_cents` reported when
        reading an engagement is a **provisional** figure equal to the base
        fee plus the sum of deltas in either `PROPOSED` or `APPROVED` status —
        a forward-looking estimate of where the fee will land."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_on_engagement
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="Acme Corp", base_fee_cents=1_000_000,
            materiality_cents=500_000)
        f_proposed = create_fee_change(eng["id"], 200_000, proposer="auditor",
                                       scope_description="Extra subsidiary scope")
        f_approved = create_fee_change(eng["id"], 50_000, proposer="auditor",
                                       scope_description="Interim review add-on")
        approve_fee_change(f_approved["id"], resolver="controller")
        data = get_engagement(eng["id"])
        assert data["total_fee_cents"] == 1_250_000, (
            f"provisional read includes PROPOSED + APPROVED deltas "
            f"(1000000 + 200000 + 50000), got {data['total_fee_cents']}"
        )
        assert get_fee_change(f_proposed["id"])["status"] == "PROPOSED"
        assert get_fee_change(f_approved["id"])["status"] == "APPROVED"

    def test_total_fee_final_once_no_proposed_remains(self):
        """PRD §2.7: "Once no `PROPOSED` requests remain, the reported figure
        is the **final** one, equal to the base fee plus approved deltas
        only."

        Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_on_engagement
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="Acme Corp", base_fee_cents=1_000_000,
            materiality_cents=500_000)
        f_proposed = create_fee_change(eng["id"], 200_000, proposer="auditor",
                                       scope_description="Extra subsidiary scope")
        f_approved = create_fee_change(eng["id"], 50_000, proposer="auditor",
                                       scope_description="Interim review add-on")
        approve_fee_change(f_approved["id"], resolver="controller")
        resolve_fee_change(f_proposed["id"], "REJECT", resolver="controller")
        data = get_engagement(eng["id"])
        assert data["total_fee_cents"] == 1_050_000, (
            f"final read counts APPROVED deltas only (1000000 + 50000), got "
            f"{data['total_fee_cents']}"
        )
        assert get_fee_change(f_proposed["id"])["status"] == "REJECTED"


class TestProposeWithdrawIdentity:

    def test_propose_then_withdraw_conserves_total(self):
        """PRD §3.7: "Withdrawal is the proposer's escape hatch: from
        `PROPOSED` (else `ERR_FEE_CHANGE_NOT_PROPOSED`), the acting role must
        match the original proposer role — a mismatch is rejected with
        `ERR_FEE_CHANGE_NOT_PROPOSER` — and the request lands on `WITHDRAWN`."
        PRD §2.7: "An engagement's `total_fee_cents` is defined as its
        `base_fee_cents` plus the sum of `delta_cents` over the engagement's
        fee change requests whose status is `APPROVED`; proposals still in
        `PROPOSED`, and requests in `REJECTED` or `WITHDRAWN`, contribute
        nothing."

        Design: Difficulty/compensating_invariant/fee_approve_then_withdraw_proposed_conserves_total
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="RhoCo", base_fee_cents=1_000_000,
            materiality_cents=100_000)
        assert eng["total_fee_cents"] == 1_000_000
        f = create_fee_change(eng["id"], 150_000, proposer="auditor",
                              scope_description="Extra scope")
        withdrawn = withdraw_fee_change(f["id"], role="auditor")
        assert withdrawn["status"] == "WITHDRAWN"
        data = get_engagement(eng["id"])
        assert data["total_fee_cents"] == 1_000_000, (
            f"propose+withdraw is the identity pair, got "
            f"{data['total_fee_cents']}"
        )

    def test_provisional_read_includes_proposed_delta_until_withdrawn(self):
        """PRD §2.7: "while any fee change request remains `PROPOSED`, the
        `total_fee_cents` reported when reading an engagement is a
        **provisional** figure equal to the base fee plus the sum of deltas in
        either `PROPOSED` or `APPROVED` status — a forward-looking estimate of
        where the fee will land. Once no `PROPOSED` requests remain, the
        reported figure is the **final** one, equal to the base fee plus
        approved deltas only."

        Design: Difficulty/compensating_invariant/fee_approve_then_withdraw_proposed_conserves_total
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="RhoCo", base_fee_cents=1_000_000,
            materiality_cents=100_000)
        f = create_fee_change(eng["id"], 150_000, proposer="auditor",
                              scope_description="Extra scope")
        mid = get_engagement(eng["id"])
        assert mid["total_fee_cents"] == 1_150_000, (
            f"provisional figure includes the PROPOSED delta, got "
            f"{mid['total_fee_cents']}"
        )
        withdraw_fee_change(f["id"], role="auditor")
        final = get_engagement(eng["id"])
        assert final["total_fee_cents"] == 1_000_000


class TestTotalFeeInputSet:

    def test_total_fee_ignores_rejected_and_withdrawn(self):
        """PRD §2.7: "An engagement's `total_fee_cents` is defined as its
        `base_fee_cents` plus the sum of `delta_cents` over the engagement's
        fee change requests whose status is `APPROVED`; proposals still in
        `PROPOSED`, and requests in `REJECTED` or `WITHDRAWN`, contribute
        nothing."

        Design: Corner/calculations/engagement_total_fee_ignores_rejected_and_withdrawn
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="C", base_fee_cents=1_000_000,
            materiality_cents=100_000)
        f1 = create_fee_change(eng["id"], 50_000, proposer="auditor",
                               scope_description="F1")
        f2 = create_fee_change(eng["id"], 70_000, proposer="auditor",
                               scope_description="F2")
        f3 = create_fee_change(eng["id"], 30_000, proposer="auditor",
                               scope_description="F3")
        approve_fee_change(f1["id"], resolver="controller")
        resolve_fee_change(f2["id"], "REJECT", resolver="controller")
        withdraw_fee_change(f3["id"], role="auditor")
        data = get_engagement(eng["id"])
        assert data["total_fee_cents"] == 1_050_000, (
            f"final total counts APPROVED only (1000000 + 50000), got "
            f"{data['total_fee_cents']}"
        )

    def test_total_fee_reconciles_on_approve_and_not_on_reject(self):
        """PRD §3.7: "An approved request becomes `APPROVED` and the
        engagement's `total_fee_cents` increments by `delta_cents` (with the
        read-time provisional/final behavior of §2.7); a rejected one becomes
        `REJECTED` with no fee impact."
        PRD §2.7: "while any fee change request remains `PROPOSED`, the
        `total_fee_cents` reported when reading an engagement is a
        **provisional** figure equal to the base fee plus the sum of deltas in
        either `PROPOSED` or `APPROVED` status".

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_total_fee_updates_on_approve
        """
        eng, _loc = create_fieldwork_engagement(
            client_name="C", base_fee_cents=1_000_000,
            materiality_cents=100_000)
        f1 = create_fee_change(eng["id"], 100_000, proposer="auditor",
                               scope_description="F1")
        f2 = create_fee_change(eng["id"], 50_000, proposer="auditor",
                               scope_description="F2")
        approve_fee_change(f1["id"], resolver="controller")
        after_f1 = get_engagement(eng["id"])
        assert after_f1["total_fee_cents"] == 1_150_000, (
            f"provisional read after approving F1 (F2 still PROPOSED): "
            f"1000000 + 100000 + 50000, got {after_f1['total_fee_cents']}"
        )
        resolve_fee_change(f2["id"], "REJECT", resolver="controller")
        after_f2 = get_engagement(eng["id"])
        assert after_f2["total_fee_cents"] == 1_100_000, (
            f"final read after rejecting F2 counts the APPROVED delta only, "
            f"got {after_f2['total_fee_cents']}"
        )
        assert get_fee_change(f1["id"])["status"] == "APPROVED"
        assert get_fee_change(f2["id"])["status"] == "REJECTED"


class TestFeeChangeRules:

    def test_resolve_after_approved_rejected(self):
        """PRD §3.7: "Resolving takes a payload `decision` of `APPROVE` or
        `REJECT` and requires the request to be in `PROPOSED`
        (`ERR_FEE_CHANGE_NOT_PROPOSED`)."
        PRD §3.7: "Either way the outcome is terminal."

        Design: Corner/state_machines/fee_change_resolution_terminal_lockdown
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        f = create_fee_change(eng["id"], 50_000, proposer="auditor",
                              scope_description="S")
        approve_fee_change(f["id"], resolver="controller")
        resp = api_client.resolve_fee_change_request(
            f["id"], {"decision": "REJECT"}, CONTROLLER)
        validate_error(resp, ApiErrorId.ERR_FEE_CHANGE_NOT_PROPOSED)
        assert get_fee_change(f["id"])["status"] == "APPROVED", \
            "rejected second resolution leaves the request APPROVED"

    def test_same_party_resolution_rejected(self):
        """PRD §3.7: "Resolution is deliberately counter-partisan: the party
        that proposed a change cannot approve it."
        PRD §3.7: "When `proposed_by_role` is `CONTROLLER_OFFICE`, the
        resolver's `X-User-Role` must be `ExternalAuditor`; when it is
        `AUDITOR`, the resolver must be a `Controller`. A same-party
        resolution is rejected with `ERR_FEE_CHANGE_SELF_APPROVAL`."

        Design: Corner/validations/fee_change_self_approval_rejected
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        f = create_fee_change(eng["id"], 50_000, proposer="auditor",
                              scope_description="S")
        assert get_fee_change(f["id"])["proposed_by_role"] == "AUDITOR"
        resp = api_client.resolve_fee_change_request(
            f["id"], {"decision": "APPROVE"}, AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FEE_CHANGE_SELF_APPROVAL)
        assert get_fee_change(f["id"])["status"] == "PROPOSED", \
            "rejected self-approval leaves the request PROPOSED"

    def test_zero_delta_rejected(self):
        """PRD §3.7: "Creating one takes an `engagement_id`, a
        `scope_description` of the change driving the fee impact, and a signed
        `delta_cents` that must be non-zero (else `ERR_INVALID_FEE_DELTA`)".

        Design: Corner/errors/error_invalid_fee_delta
        """
        eng, _loc = create_fieldwork_engagement(client_name="C")
        resp = api_client.create_fee_change_request(
            create_fee_change_request_payload(
                eng["id"], scope_description="no change", delta_cents=0),
            AUDITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FEE_DELTA)
