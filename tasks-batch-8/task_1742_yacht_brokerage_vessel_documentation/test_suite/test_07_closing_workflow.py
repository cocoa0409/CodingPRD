"""Closing workflow: contingency gating, OCC on build, the approve/reopen
revision loop, commission identity conservation, segregation of duties."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_commission_side_split_invariant,
    assert_version_incremented,
    approve_statement,
    build_statement,
    get_success_data,
    list_offer_contingencies,
    listing_headers,
    record_cleared_deposit,
    selling_headers,
    setup_accepted_offer,
    setup_active_listing,
    setup_balanced_statement,
    setup_draft_statement,
    submit_offer,
    waive_all_contingencies,
    create_closing_statement_payload,
    validate_error,
    validate_success,
)

CLOSING = TEST_USERS["closing_officer_headers"]


class TestBuildGatedByContingencyStates:
    def test_open_contingency_blocks_build(self, api):
        """PRD §3.5: "a deal can only march toward closing when every contingency
        on it stands SATISFIED or WAIVED; attempting to build the closing
        statement, or to disburse it, with contingencies anywhere outside those
        two states is rejected with `ERR_CONTINGENCY_UNRESOLVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/closing_build_gated_by_contingency_states
        """
        deal = setup_accepted_offer(offer_price_cents=480000000)
        contingencies = list_offer_contingencies(deal)
        for c in contingencies[1:]:
            validate_success(api.waive_contingency(c["id"], selling_headers(deal)))
        statement = setup_draft_statement(deal)

        fresh = get_success_data(api.get_offer(deal["offer"]["id"], CLOSING))
        res = api.build_closing_statement(
            statement["id"], {"expected_offer_version": fresh["version"]}, CLOSING
        )
        validate_error(res, ApiErrorId.ERR_CONTINGENCY_UNRESOLVED)
        after = get_success_data(api.get_closing_statement(statement["id"], CLOSING))
        assert after["status"] == "DRAFT"
        assert contingencies[0]["status"] == "OPEN", (
            "fixture invariant: one contingency was deliberately left OPEN"
        )

    def test_all_contingencies_resolved_allows_build(self, api):
        """PRD §3.7: "Building the statement — the ClosingOfficer's action
        carrying `expected_offer_version` against the pinned offer — requires the
        parent offer to stand ACCEPTED, every contingency on it SATISFIED or
        WAIVED, and every lien on the vessel to have its `payoff_amount_cents`
        computed; it then runs the full calculation pipeline, writes every
        computed field, creates the tax assessment rows the outcome implies,
        moves the statement from DRAFT to BALANCED, and bumps its `version`."

        Design: Difficulty/cross_entity_state_dependency/closing_build_gated_by_contingency_states
        """
        deal = setup_accepted_offer(offer_price_cents=480000000)
        waive_all_contingencies(deal)
        statement = setup_draft_statement(deal)
        draft_version = statement["version"]
        built = build_statement(deal, statement)
        assert built["status"] == "BALANCED"
        assert_version_incremented(built["version"], draft_version)


def test_build_with_stale_offer_version_rejected(api):
    """PRD §2.6: "Building a closing statement requires `expected_offer_version`
    against the accepted offer whose figures the statement pins." and "When the
    supplied value does not match the parent entity's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_statement_build_stale_offer_version
    """
    deal = setup_accepted_offer()
    waive_all_contingencies(deal)
    statement = setup_draft_statement(deal)
    fresh = get_success_data(api.get_offer(deal["offer"]["id"], CLOSING))
    res = api.build_closing_statement(
        statement["id"], {"expected_offer_version": fresh["version"] - 1}, CLOSING
    )
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)
    after = get_success_data(api.get_closing_statement(statement["id"], CLOSING))
    assert after["status"] == "DRAFT"


class TestApproveReopenRebalanceLoop:
    def test_approve_reopen_approve_cycle(self, api):
        """PRD §3.8: "Approval moves the statement from BALANCED to APPROVED and
        bumps its `version`. When figures need to change, the ClosingOfficer
        reopens an APPROVED statement back to BALANCED — allowed only while no
        escrow entry on the offer has yet been DISBURSED — which re-runs all five
        calculations afresh"

        Design: Difficulty/non_linear_state_machine/closing_statement_approve_reopen_rebalance_loop
        """
        deal = setup_balanced_statement()
        st = deal["statement"]
        v0 = st["version"]

        approved1 = approve_statement(deal, st)
        assert approved1["status"] == "APPROVED"
        assert_version_incremented(approved1["version"], v0)

        reopened = validate_success(
            api.reopen_closing_statement(st["id"], CLOSING), 200
        )
        assert reopened["status"] == "BALANCED"
        assert_version_incremented(reopened["version"], approved1["version"])

        approved2 = validate_success(
            api.approve_closing_statement(
                st["id"],
                {"expected_statement_version": reopened["version"]},
                listing_headers(deal),
            ),
            200,
        )
        assert approved2["status"] == "APPROVED"
        assert_version_incremented(approved2["version"], reopened["version"])

    def test_reopen_rejected_once_escrow_entry_disbursed(self, api):
        """PRD §3.8: "the ClosingOfficer reopens an APPROVED statement back to
        BALANCED — allowed only while no escrow entry on the offer has yet been
        DISBURSED"

        Design: Difficulty/non_linear_state_machine/closing_statement_approve_reopen_rebalance_loop
        """
        deal = setup_accepted_offer(offer_price_cents=200000000)
        entry = record_cleared_deposit(deal)
        waive_all_contingencies(deal)
        statement = setup_draft_statement(deal)
        build_statement(deal, statement)
        approve_statement(deal, deal["statement"])
        released = validate_success(api.release_escrow_entry(entry["id"], CLOSING))
        assert released["status"] == "DISBURSED"

        res = api.reopen_closing_statement(statement["id"], CLOSING)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_closing_statement(statement["id"], CLOSING))
        assert after["status"] == "APPROVED"


class TestCommissionIdentityAcrossReopen:
    def test_side_split_identity_holds_on_initial_build(self, api):
        """PRD §3.7: "`listing_side_cents` is the remainder, computed by
        subtraction and never re-rounded, so the invariant that the two sides sum
        exactly to `commission_cents` always holds."

        Co-broke gross 700000000 -> MID tier 8% -> commission 56000000.

        Design: Difficulty/compensating_invariant/commission_side_split_invariant_across_reopen
        """
        deal = setup_balanced_statement(
            offer_price_cents=700000000, list_price_cents=720000000, co_broke=True
        )
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["commission_cents"] == 56000000
        assert_commission_side_split_invariant(st)

    def test_side_split_identity_holds_after_reopen_rebuild(self, api):
        """PRD §3.8: "the ClosingOfficer reopens an APPROVED statement back to
        BALANCED — allowed only while no escrow entry on the offer has yet been
        DISBURSED — which re-runs all five calculations afresh"
        PRD §3.7: "the invariant that the two sides sum exactly to
        `commission_cents` always holds."

        Design: Difficulty/compensating_invariant/commission_side_split_invariant_across_reopen
        """
        deal = setup_balanced_statement(
            offer_price_cents=700000000, list_price_cents=720000000, co_broke=True
        )
        approve_statement(deal, deal["statement"])
        reopened = validate_success(
            api.reopen_closing_statement(deal["statement"]["id"], CLOSING), 200
        )
        assert reopened["status"] == "BALANCED"
        st = get_success_data(
            api.get_closing_statement(deal["statement"]["id"], CLOSING)
        )
        assert st["commission_cents"] == 56000000, (
            "reopen re-runs the calculations with unchanged inputs"
        )
        assert_commission_side_split_invariant(st)


def test_closing_officer_cannot_approve_statement(api):
    """PRD §2.1: "A well-identified caller whose role is not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.9: "building is ClosingOfficer work, approval is ListingAgent work,
    and an approval attempted by the same role that built the statement is
    rejected with `ERR_SEGREGATION_VIOLATION` (HTTP 403)." — the ClosingOfficer
    role is outside the approve role list entirely, so the RBAC wall fires.

    Design: Corner/validations/segregation_of_duties_builder_cannot_approve
    """
    deal = setup_balanced_statement()
    st = deal["statement"]
    res = api.approve_closing_statement(
        st["id"], {"expected_statement_version": st["version"]}, CLOSING
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_selling_agent_cannot_approve_statement(api):
    """PRD §2.1: "A well-identified caller whose role is not permitted on the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)." — statement
    approval is ListingAgent work; the buyer-side SellingAgent is denied.

    Design: Corner/validations/rbac_denial_selling_agent_cannot_approve_statement
    """
    deal = setup_balanced_statement()
    st = deal["statement"]
    res = api.approve_closing_statement(
        st["id"],
        {"expected_statement_version": st["version"]},
        selling_headers(deal),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)


def test_statement_rejected_for_pending_offer(api):
    """PRD §3.7: "A statement may only be drafted for an offer standing
    ACCEPTED — any other offer state is rejected with `ERR_OFFER_NOT_ACCEPTED`
    (HTTP 409)"

    Design: Corner/endpoints/closing_statement_created_only_for_accepted_offer
    """
    deal = setup_active_listing()
    offer = submit_offer(deal)
    assert offer["status"] == "PENDING"
    res = api.create_closing_statement(
        create_closing_statement_payload(offer["id"]), CLOSING
    )
    validate_error(res, ApiErrorId.ERR_OFFER_NOT_ACCEPTED)
