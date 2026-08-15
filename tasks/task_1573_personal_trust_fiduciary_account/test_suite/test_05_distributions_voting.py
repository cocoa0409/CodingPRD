"""Distribution request workflow: invalid transitions, quorum boundary,
duplicate/inactive votes, suspended-trust gating, fund boundary, and the
information cycle / approval fork (PRD §3.3)."""
from test_helpers import (
    ApiErrorId,
    make_committee_member_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    EXEC,
    OFFICER,
    OPS,
    create_request,
    create_request_in_review,
    create_request_in_voting,
    setup_funded_trust,
)


def _voting_scenario(api, amount_cents=1000000, income_cents=5000000,
                     members=5, standard="HEMS", purpose="HEALTH",
                     allocation="INCOME_ONLY"):
    """ACTIVE trust + beneficiary + committee + a request in VOTING."""
    ctx = setup_funded_trust(
        income_cents=income_cents,
        committee_size=members,
        all_beneficiaries=[{"full_name": "Ivy Inc", "beneficiary_class": "INCOME",
                            "share_bps": 10000, "date_of_birth": "1955-01-01"}],
        distribution_standard=standard,
    )
    ben = ctx["beneficiaries"][0]
    req = create_request_in_voting(
        ctx["trust"]["id"], ben["id"], amount_cents=amount_cents,
        allocation_source=allocation, purpose_category=purpose,
    )
    return ctx, ben, req


class TestInvalidTransitions:
    def test_disburse_submitted_request_rejected(self, api):
        """PRD §3.3: "Only an APPROVED request can be paid out. Disbursement
        by a `TrustOperationsOfficer` requires the request to be APPROVED
        (`ERR_REQUEST_NOT_APPROVED`) and the trust ACTIVE
        (`ERR_TRUST_NOT_ACTIVE`)."

        Design: Corner/state_machines/disburse_submitted_request_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request(ctx["trust"]["id"], ben["id"], amount_cents=1000000,
                             purpose_category="HEALTH")
        resp = api.disburse_request(req["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_APPROVED)

    def test_disburse_from_submitted_posts_no_ledger_rows(self, api):
        """PRD §3.3: "Only an APPROVED request can be paid out. Disbursement
        by a `TrustOperationsOfficer` requires the request to be APPROVED
        (`ERR_REQUEST_NOT_APPROVED`) and the trust ACTIVE
        (`ERR_TRUST_NOT_ACTIVE`)."

        Design: Corner/state_machines/disburse_submitted_request_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request(ctx["trust"]["id"], ben["id"], amount_cents=1000000,
                             purpose_category="HEALTH")
        api.disburse_request(req["id"], OPS)
        _, meta = validate_paginated(
            api.list_ledger_entries(
                OPS, params={"trust_id": ctx["trust"]["id"], "entry_kind": "DISTRIBUTION"}
            )
        )
        assert meta["total_count"] == 0, "no DISTRIBUTION row may be appended"

    def test_vote_after_decision_rejected(self, api):
        """PRD §3.3: "CommitteeMembers cast ballots by supplying the `vote`
        field — one of `APPROVE`, `DECLINE`, or `ABSTAIN`. Each ballot appends
        a CommitteeVote naming the `distribution_request_id`, with
        `committee_member_id` taken from the caster's `X-User-ID`; the request
        must be VOTING (`ERR_REQUEST_NOT_VOTING`), the member ACTIVE
        (`ERR_MEMBER_NOT_ACTIVE`), and one member gets one vote per request —
        a repeat is rejected with `ERR_DUPLICATE_VOTE`."

        Design: Corner/state_machines/vote_after_decision_rejected
        """
        ctx, ben, req = _voting_scenario(api, members=4)
        ids = [m["id"] for m in ctx["members"]]
        for mid in ids[:3]:
            assert api.cast_vote(
                req["id"], {"vote": "APPROVE"}, make_committee_member_headers(mid)
            ).status_code == 201

        resp = api.cast_vote(req["id"], {"vote": "ABSTAIN"},
                             make_committee_member_headers(ids[3]))
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_VOTING)

    def test_vote_after_decision_leaves_tallies_unchanged(self, api):
        """PRD §3.3: "if `approve_count` has reached at least three, the
        request becomes APPROVED — exactly three approvals approves — and the
        reservation remains in place."

        Design: Corner/state_machines/vote_after_decision_rejected
        """
        ctx, ben, req = _voting_scenario(api, members=4)
        ids = [m["id"] for m in ctx["members"]]
        for mid in ids[:3]:
            assert api.cast_vote(
                req["id"], {"vote": "APPROVE"}, make_committee_member_headers(mid)
            ).status_code == 201
        api.cast_vote(req["id"], {"vote": "ABSTAIN"},
                      make_committee_member_headers(ids[3]))
        current = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert current["status"] == "APPROVED"
        assert current["abstain_count"] == 0


class TestQuorumBoundary:
    def test_first_two_approvals_keep_request_voting(self, api):
        """PRD §3.3: "The quorum threshold is three. After the just-cast vote
        is appended and the tallies recomputed: if `approve_count` has reached
        at least three, the request becomes APPROVED — exactly three approvals
        approves — and the reservation remains in place."

        Design: Difficulty/boundary_precision_check/quorum_exactly_three_approves
        """
        ctx, ben, req = _voting_scenario(api)
        ids = [m["id"] for m in ctx["members"]]
        assert api.cast_vote(req["id"], {"vote": "APPROVE"},
                             make_committee_member_headers(ids[0])).status_code == 201
        after1 = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert after1["status"] == "VOTING" and after1["approve_count"] == 1

        assert api.cast_vote(req["id"], {"vote": "APPROVE"},
                             make_committee_member_headers(ids[1])).status_code == 201
        after2 = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert after2["status"] == "VOTING" and after2["approve_count"] == 2

    def test_third_approval_decides_approved(self, api):
        """PRD §3.3: "The quorum threshold is three. After the just-cast vote
        is appended and the tallies recomputed: if `approve_count` has reached
        at least three, the request becomes APPROVED — exactly three approvals
        approves — and the reservation remains in place; otherwise, if
        `decline_count` has reached at least three, the request becomes
        DECLINED; otherwise, if the total votes cast now equal
        `committee_size_snapshot` and `approve_count` is still below three,
        the request is DECLINED as a full ballot without quorum. Either
        decision stamps `decision_at` and advances the trust's `version` by
        one."

        Design: Difficulty/boundary_precision_check/quorum_exactly_three_approves
        """
        ctx, ben, req = _voting_scenario(api)
        ids = [m["id"] for m in ctx["members"]]
        for mid in ids[:3]:
            assert api.cast_vote(req["id"], {"vote": "APPROVE"},
                                 make_committee_member_headers(mid)).status_code == 201
        after3 = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert after3["status"] == "APPROVED"
        assert after3["approve_count"] == 3
        assert after3["decision_at"], "decision_at must be stamped on the decision"


class TestVoteIntegrity:
    def test_duplicate_vote_rejected(self, api):
        """PRD §3.3: "one member gets one vote per request — a repeat is
        rejected with `ERR_DUPLICATE_VOTE`."

        Design: Corner/validations/duplicate_vote_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=3,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_voting(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        cm1 = ctx["members"][0]["id"]
        assert api.cast_vote(req["id"], {"vote": "APPROVE"},
                             make_committee_member_headers(cm1)).status_code == 201
        resp = api.cast_vote(req["id"], {"vote": "DECLINE"},
                             make_committee_member_headers(cm1))
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VOTE)

    def test_duplicate_vote_leaves_tallies_and_status(self, api):
        """PRD §3.3: "one member gets one vote per request — a repeat is
        rejected with `ERR_DUPLICATE_VOTE`."

        Design: Corner/validations/duplicate_vote_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=3,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_voting(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        cm1 = ctx["members"][0]["id"]
        assert api.cast_vote(req["id"], {"vote": "APPROVE"},
                             make_committee_member_headers(cm1)).status_code == 201
        api.cast_vote(req["id"], {"vote": "DECLINE"}, make_committee_member_headers(cm1))
        current = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert current["approve_count"] == 1
        assert current["decline_count"] == 0
        assert current["status"] == "VOTING"

    def test_inactive_member_vote_rejected(self, api):
        """PRD §3.2: "Deactivation moves ACTIVE → INACTIVE and is deliberately
        non-retroactive: votes the member has already cast remain counted, and
        the size snapshot taken when voting opened is not recomputed, but the
        member can no longer cast new votes — an attempt by an INACTIVE member
        is rejected with `ERR_MEMBER_NOT_ACTIVE`."

        Design: Corner/validations/inactive_member_vote_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=4,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_voting(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        cm4 = ctx["members"][3]["id"]
        assert api.deactivate_committee_member(cm4, EXEC).status_code == 200
        resp = api.cast_vote(req["id"], {"vote": "APPROVE"},
                             make_committee_member_headers(cm4))
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_ACTIVE)

    def test_deactivation_does_not_recompute_size_snapshot(self, api):
        """PRD §3.2: "Deactivation moves ACTIVE → INACTIVE and is deliberately
        non-retroactive: votes the member has already cast remain counted, and
        the size snapshot taken when voting opened is not recomputed, but the
        member can no longer cast new votes — an attempt by an INACTIVE member
        is rejected with `ERR_MEMBER_NOT_ACTIVE`."

        Design: Corner/validations/inactive_member_vote_rejected
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=4,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_voting(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        cm4 = ctx["members"][3]["id"]
        assert api.deactivate_committee_member(cm4, EXEC).status_code == 200
        api.cast_vote(req["id"], {"vote": "APPROVE"}, make_committee_member_headers(cm4))
        current = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert current["committee_size_snapshot"] == 4


class TestSuspendedTrustGate:
    def test_open_voting_blocked_when_trust_suspended(self, api):
        """PRD §3.3: "Opening the vote is the fiduciary hinge, and its
        preconditions are evaluated in the order given here. The trust must be
        ACTIVE, otherwise `ERR_TRUST_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/open_voting_blocked_when_trust_suspended
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=5,
            all_beneficiaries=[{"full_name": "Ivy Inc", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(trust["id"], ben["id"], amount_cents=1000000,
                                       purpose_category="HEALTH")
        assert api.suspend_trust(trust["id"], {"reason": "executive hold"}, EXEC).status_code == 200

        resp = api.open_voting(req["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_TRUST_NOT_ACTIVE)

    def test_reinstate_reenables_open_voting(self, api):
        """PRD §3.1: "Reinstatement from SUSPENDED → ACTIVE is permitted only
        when the trust has zero ComplianceReviews in OPEN,
        REMEDIATION_PLANNED, or ESCALATED; otherwise the attempt is rejected
        with `ERR_UNRESOLVED_COMPLIANCE_REVIEWS`."
        PRD §3.3: "A successful opening sets `income_portion_cents` and
        `principal_portion_cents` per the waterfall, adds them to the trust's
        `reserved_income_cents` and `reserved_principal_cents`, recomputes the
        available balances, increments the trust's `version`, snapshots
        `committee_size_snapshot` as the count of ACTIVE members at that
        instant, zeroes all three tallies, and records the officer as
        `opened_by_user_id`. The request is then VOTING."

        Design: Difficulty/cross_entity_state_dependency/open_voting_blocked_when_trust_suspended
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=5,
            all_beneficiaries=[{"full_name": "Ivy Inc", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        trust = ctx["trust"]
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(trust["id"], ben["id"], amount_cents=1000000,
                                       purpose_category="HEALTH")
        assert api.suspend_trust(trust["id"], {"reason": "executive hold"}, EXEC).status_code == 200
        api.open_voting(req["id"], OFFICER)  # blocked

        reinstated = api.reinstate_trust(trust["id"], EXEC)
        assert reinstated.status_code == 200, (
            "reinstate must succeed when no non-RESOLVED ComplianceReview exists"
        )
        opened = validate_success(api.open_voting(req["id"], OFFICER))
        assert opened["status"] == "VOTING"
        trust_after = validate_success(api.get_trust(trust["id"], OFFICER))
        assert trust_after["reserved_income_cents"] == 1000000


class TestAvailableBalanceBoundary:
    def test_over_by_one_cent_rejected(self, api):
        """PRD §3.3: "Finally the reservation waterfall for the chosen
        `allocation_source` must succeed against the trust's available
        balances, otherwise `ERR_INSUFFICIENT_AVAILABLE_BALANCE`: INCOME_ONLY
        reserves the entire amount from income and requires the amount to be
        no more than `available_income_cents`."

        Design: Corner/validations/available_balance_exact_edge_and_over
        """
        ctx = setup_funded_trust(
            income_cents=2000000, committee_size=3,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        over = create_request_in_review(ctx["trust"]["id"], ben["id"],
                                        amount_cents=2000001, purpose_category="HEALTH")
        resp = api.open_voting(over["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_BALANCE)
        current = validate_success(api.get_distribution_request(over["id"], OFFICER))
        assert current["status"] == "UNDER_REVIEW"

    def test_exact_available_edge_reserved(self, api):
        """PRD §3.3: "INCOME_ONLY reserves the entire amount from income and
        requires the amount to be no more than `available_income_cents`."
        PRD §3.3: "A successful opening sets `income_portion_cents` and
        `principal_portion_cents` per the waterfall, adds them to the trust's
        `reserved_income_cents` and `reserved_principal_cents`, recomputes the
        available balances."

        Design: Corner/validations/available_balance_exact_edge_and_over
        """
        ctx = setup_funded_trust(
            income_cents=2000000, committee_size=3,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        edge = create_request_in_review(ctx["trust"]["id"], ben["id"],
                                        amount_cents=2000000, purpose_category="HEALTH")
        opened = validate_success(api.open_voting(edge["id"], OFFICER))
        assert opened["status"] == "VOTING"
        assert opened["income_portion_cents"] == 2000000
        trust = validate_success(api.get_trust(ctx["trust"]["id"], OFFICER))
        assert trust["reserved_income_cents"] == 2000000
        assert trust["available_income_cents"] == 0


class TestQuorumUnavailable:
    def test_two_active_members_block_open_voting(self, api):
        """PRD §3.3: "At least three CommitteeMembers must be ACTIVE,
        otherwise `ERR_COMMITTEE_QUORUM_UNAVAILABLE`."

        Design: Corner/validations/quorum_unavailable_blocks_open_voting
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=2,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        resp = api.open_voting(req["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_COMMITTEE_QUORUM_UNAVAILABLE)

    def test_quorum_failure_leaves_no_reservation(self, api):
        """PRD §3.3: "At least three CommitteeMembers must be ACTIVE,
        otherwise `ERR_COMMITTEE_QUORUM_UNAVAILABLE`."
        PRD §2.6: "`reserved_income_cents` and `reserved_principal_cents`
        accumulate the portions earmarked by distribution requests that are in
        VOTING or APPROVED."

        Design: Corner/validations/quorum_unavailable_blocks_open_voting
        """
        ctx = setup_funded_trust(
            income_cents=5000000, committee_size=2,
            all_beneficiaries=[{"full_name": "Ivy", "beneficiary_class": "INCOME"}],
            distribution_standard="HEMS",
        )
        ben = ctx["beneficiaries"][0]
        req = create_request_in_review(ctx["trust"]["id"], ben["id"],
                                       amount_cents=1000000, purpose_category="HEALTH")
        api.open_voting(req["id"], OFFICER)
        current = validate_success(api.get_distribution_request(req["id"], OFFICER))
        assert current["status"] == "UNDER_REVIEW"
        trust = validate_success(api.get_trust(ctx["trust"]["id"], OFFICER))
        assert trust["reserved_income_cents"] == 0
