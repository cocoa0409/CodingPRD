"""Listing-withdrawal and dispute cascades, dispute forks, and conservation invariants."""
from test_helpers import (
    validate_success, TEST_USERS, make_leaseholder_headers,
    setup_scenario, setup_dispute_under_review,
)


def _get_agreement(api, aid):
    return validate_success(api.get_agreement(aid, TEST_USERS["admin_headers"]))


def _get_settlement(api, sid):
    return validate_success(api.get_settlement(sid, TEST_USERS["admin_headers"]))


def _get_lease(api, lid):
    return validate_success(api.get_lease(lid, TEST_USERS["admin_headers"]))


def _get_application(api, aid):
    return validate_success(api.get_application(aid, TEST_USERS["admin_headers"]))


def _get_listing(api, lid):
    return validate_success(api.get_listing(lid, TEST_USERS["admin_headers"]))


class TestListingWithdrawDepth4Cascade:
    """Difficulty: transitive_cascade — withdrawing a MATCHED listing cascades through
    Application -> Agreement -> Settlement, each hop caused by the previous."""

    def _withdraw(self, api):
        # stage "funded": EXECUTED agreement, FUNDED settlement, listing MATCHED, occupancy 1.
        ctx = setup_scenario(api, stage="funded")
        validate_success(api.withdraw_listing(ctx["listing"]["id"],
                                              make_leaseholder_headers(ctx["leaseholder"]["id"])))
        return ctx

    def test_withdraw_declines_application_and_voids_agreement(self, api):
        """PRD §3.2: "First, every application on the listing whose status is `SUBMITTED`,
        `SCREENING`, `INFO_REQUESTED`, `SCREENED`, or `MATCHED` is moved to `DECLINED`.
        Second, each such application's non-terminal agreement — one in `DRAFT`,
        `PENDING_SIGNATURES`, or `EXECUTED` — is moved to `VOID`."

        Design: Difficulty/transitive_cascade/listing_withdraw_depth4_cascade
        """
        ctx = self._withdraw(api)
        assert _get_listing(api, ctx["listing"]["id"])["status"] == "WITHDRAWN"
        assert _get_application(api, ctx["application"]["id"])["status"] == "DECLINED"
        assert _get_agreement(api, ctx["agreement"]["id"])["status"] == "VOID"

    def test_withdraw_refunds_settlement_and_releases_occupancy(self, api):
        """PRD §3.2: "for each voided agreement, if its settlement was `FUNDED` the
        settlement is moved to `REFUNDED` and its held deposit is released from escrow,
        and if the voided agreement had been `EXECUTED` (and thus occupying) the lease's
        `active_occupancy_count` is decremented by 1".

        Design: Difficulty/transitive_cascade/listing_withdraw_depth4_cascade
        """
        ctx = self._withdraw(api)
        settlement = _get_settlement(api, ctx["settlement"]["id"])
        assert settlement["status"] == "REFUNDED", f"funded settlement must be REFUNDED, got {settlement['status']}"
        assert settlement["deposit_held_cents"] == 0, "refund must remove the deposit from escrow"
        assert _get_lease(api, ctx["lease"]["id"])["active_occupancy_count"] == 0


class TestDisputeApplicantDepth3Cascade:
    """Difficulty: transitive_cascade — resolving a dispute for the applicant cascades
    Dispute -> Agreement -> Settlement."""

    def test_agreement_terminated_and_settlement_refunded(self, api):
        """PRD §3.8: "The parent agreement cascades to terminal `TERMINATED`; that
        termination in turn moves the settlement to `REFUNDED` (the deposit is returned to
        the applicant and leaves escrow)".

        Design: Difficulty/transitive_cascade/dispute_applicant_depth3_cascade
        """
        ctx, dispute = setup_dispute_under_review(api, raised_by="APPLICANT")
        validate_success(api.resolve_dispute(dispute["id"], {"outcome": "RESOLVED_APPLICANT"},
                                             TEST_USERS["compliance_headers"]))
        assert _get_agreement(api, ctx["agreement"]["id"])["status"] == "TERMINATED"
        assert _get_settlement(api, ctx["settlement"]["id"])["status"] == "REFUNDED"

    def test_deposit_leaves_escrow_and_occupancy_released(self, api):
        """PRD §3.8: "moves the settlement to `REFUNDED` (the deposit is returned to the
        applicant and leaves escrow), decrements the lease's `active_occupancy_count` by 1".

        Design: Difficulty/transitive_cascade/dispute_applicant_depth3_cascade
        """
        ctx, dispute = setup_dispute_under_review(api, raised_by="APPLICANT")
        validate_success(api.resolve_dispute(dispute["id"], {"outcome": "RESOLVED_APPLICANT"},
                                             TEST_USERS["compliance_headers"]))
        assert _get_settlement(api, ctx["settlement"]["id"])["deposit_held_cents"] == 0
        assert _get_lease(api, ctx["lease"]["id"])["active_occupancy_count"] == 0


class TestDisputeBranchingFork:
    """Difficulty: non_linear_state_machine — UNDER_REVIEW forks to divergent terminal
    outcomes with different side-effects."""

    def test_resolved_applicant_terminates_agreement(self, api):
        """PRD §3.8: "**`RESOLVED_APPLICANT`** favours the incoming occupant and unwinds
        the tenancy. The parent agreement cascades to terminal `TERMINATED`".

        Design: Difficulty/non_linear_state_machine/dispute_branching_fork_resolution
        """
        ctx, dispute = setup_dispute_under_review(api, raised_by="APPLICANT")
        data = validate_success(api.resolve_dispute(dispute["id"], {"outcome": "RESOLVED_APPLICANT"},
                                                    TEST_USERS["compliance_headers"]))
        assert data["status"] == "RESOLVED_APPLICANT", f"dispute status, got {data['status']}"
        assert data["outcome"] == "RESOLVED_APPLICANT", f"dispute outcome, got {data['outcome']}"
        assert _get_agreement(api, ctx["agreement"]["id"])["status"] == "TERMINATED"

    def test_dismissed_leaves_agreement_active(self, api):
        """PRD §3.8: "**`DISMISSED`** closes the dispute with no financial effect; the
        agreement remains `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/dispute_branching_fork_resolution
        """
        ctx, dispute = setup_dispute_under_review(api, raised_by="APPLICANT")
        data = validate_success(api.resolve_dispute(dispute["id"], {"outcome": "DISMISSED"},
                                                    TEST_USERS["compliance_headers"]))
        assert data["status"] == "DISMISSED", f"dispute status, got {data['status']}"
        assert _get_agreement(api, ctx["agreement"]["id"])["status"] == "ACTIVE", "agreement must remain ACTIVE"


class TestEscrowConservedFundThenVoidRefund:
    """Difficulty: compensating_invariant — a fund (+deposit) paired with a void's refund
    (-deposit) leaves escrow at its pre-fund value."""

    def test_fund_adds_deposit_to_escrow(self, api):
        """PRD §2.8: "A settlement's `deposit_held_cents` equals its `deposit_amount_cents`
        while the settlement is FUNDED or HANDED_OFF, and is exactly 0 in every terminal
        state (RELEASED, REFUNDED, FORFEITED) and while PENDING."

        Design: Difficulty/compensating_invariant/escrow_conserved_fund_then_void_refund
        """
        ctx = setup_scenario(api, stage="funded")  # deposit 500000 funded into escrow
        s = _get_settlement(api, ctx["settlement"]["id"])
        assert s["status"] == "FUNDED"
        assert s["deposit_held_cents"] == 500000, f"funded escrow must hold 500000, got {s['deposit_held_cents']}"

    def test_void_refund_removes_deposit_from_escrow(self, api):
        """PRD §3.5: "if the settlement is `FUNDED` it moves to `REFUNDED` and its deposit
        leaves escrow back to the applicant".

        Design: Difficulty/compensating_invariant/escrow_conserved_fund_then_void_refund
        """
        ctx = setup_scenario(api, stage="funded")
        validate_success(api.void_agreement(ctx["agreement"]["id"],
                                            make_leaseholder_headers(ctx["leaseholder"]["id"])))
        s = _get_settlement(api, ctx["settlement"]["id"])
        assert s["status"] == "REFUNDED", f"voided funded settlement must be REFUNDED, got {s['status']}"
        assert s["deposit_held_cents"] == 0, "refund must return escrow to its pre-fund value (0)"


class TestOccupancyCountConservedExecuteThenTerminate:
    """Difficulty: compensating_invariant — execution reserves a slot (+1) and termination
    releases it (-1), leaving the occupancy count unchanged."""

    def test_execution_reserves_occupancy_slot(self, api):
        """PRD §2.8: "Reserving occupancy (an agreement reaching EXECUTED) increments the
        count by 1".

        Design: Difficulty/compensating_invariant/occupancy_count_conserved_execute_then_terminate
        """
        ctx = setup_scenario(api, stage="executed")
        assert _get_lease(api, ctx["lease"]["id"])["active_occupancy_count"] == 1, (
            "an EXECUTED agreement must reserve exactly one occupancy slot")

    def test_termination_releases_occupancy_slot(self, api):
        """PRD §2.8: "each compensating release (that agreement reaching COMPLETED, VOID,
        or TERMINATED) decrements it by 1, so the count never drifts."

        Design: Difficulty/compensating_invariant/occupancy_count_conserved_execute_then_terminate
        """
        ctx, dispute = setup_dispute_under_review(api, raised_by="APPLICANT")
        assert _get_lease(api, ctx["lease"]["id"])["active_occupancy_count"] == 1
        validate_success(api.resolve_dispute(dispute["id"], {"outcome": "RESOLVED_APPLICANT"},
                                             TEST_USERS["compliance_headers"]))
        assert _get_lease(api, ctx["lease"]["id"])["active_occupancy_count"] == 0, (
            "termination via dispute must release the occupancy slot back to 0")
