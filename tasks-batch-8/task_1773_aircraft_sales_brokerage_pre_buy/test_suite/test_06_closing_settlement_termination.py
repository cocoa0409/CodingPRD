"""Closing settlement (commission tiers, dual-agency variant), close cascades,
termination escrow disposition, and delivery-condition OCC."""
import pytest

from test_helpers import (
    EXPECTED_BUYER_DUE,
    EXPECTED_COMMISSION_DUAL,
    EXPECTED_COMMISSION_FLAT4,
    EXPECTED_COMMISSION_FLAT6,
    EXPECTED_COMMISSION_SOLE,
    EXPECTED_SELLER_NET_DUAL,
    EXPECTED_SELLER_NET_SOLE,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    assert_escrow_disposition_invariant,
    assert_money,
    complete_delivery_conditions,
    create_buyer_payload,
    delivery_conditions_payload,
    fund_escrow,
    get_success_data,
    setup_accepted_deal,
    setup_closable_canonical_deal,
    setup_closable_deal,
    setup_delivery_pending_deal,
    setup_funded_deal,
    terminate_deal,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_principal_headers"]
LISTING_AGENT = TEST_USERS["listing_agent_headers"]
BUYER_AGENT = TEST_USERS["buyer_agent_headers"]
ESCROW = TEST_USERS["escrow_officer_headers"]
SCHEDULER = TEST_USERS["facility_scheduler_headers"]


class TestCommissionTierStraddle:
    def test_commission_straddles_tier_boundary(self, api):
        """PRD §3.9: "The commission base is the transaction's
        `agreed_price_usd` minus its `credits_total_usd`. The tiered sole-agency
        amount applies a rate of six percent to the portion of the base up to
        five million US dollars and a rate of four percent to any portion of the
        base above five million; both tier components are computed at full
        precision, summed, and the tiered total is rounded half up to two
        decimal places."

        Design: Difficulty/combinatorial_formula/commission_tier_straddle_with_dual_branch
        """
        deal = setup_closable_canonical_deal()
        closed = validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        # base = 6200000.50 - 100000.25 = 6100000.25
        # 5000000 * 0.06 + 1100000.25 * 0.04 = 300000.00 + 44000.01 = 344000.01
        assert_money(closed["commission_amount_usd"], EXPECTED_COMMISSION_SOLE,
                     "commission_amount_usd")

    def test_commission_is_neither_flat_rate(self, api):
        """PRD §3.9: "The tiered sole-agency amount applies a rate of six
        percent to the portion of the base up to five million US dollars and a
        rate of four percent to any portion of the base above five million;
        both tier components are computed at full precision, summed, and the
        tiered total is rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/commission_tier_straddle_with_dual_branch
        """
        deal = setup_closable_canonical_deal()
        closed = validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        commission = float(closed["commission_amount_usd"])
        assert commission != pytest.approx(EXPECTED_COMMISSION_FLAT6, abs=0.005), (
            "Flat 6% of base (366000.02) ignores the tier boundary")
        assert commission != pytest.approx(EXPECTED_COMMISSION_FLAT4, abs=0.005), (
            "Flat 4% of base (244000.01) ignores the tier boundary")
        assert_money(commission, EXPECTED_COMMISSION_SOLE, "commission_amount_usd")


class TestSoleVersusDualAgency:
    def test_close_sole_agency_commission_and_settlement(self, api):
        """PRD §3.9: "When the transaction's `dual_agency` is false,
        `commission_amount_usd` is that tiered total."
        PRD §3.9: "Settlement then follows: `settlement_buyer_due_usd` is the
        `agreed_price_usd` minus the `credits_total_usd` minus the escrow's
        `deposit_amount_usd`, and `settlement_seller_net_usd` is the
        `agreed_price_usd` minus the just-computed `commission_amount_usd`."

        Design: Difficulty/dual_variant_calc/commission_sole_vs_dual_diverge
        """
        deal = setup_closable_canonical_deal(dual_agency=False)
        closed = validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        assert_money(closed["commission_amount_usd"], EXPECTED_COMMISSION_SOLE,
                     "SOLE commission")
        # 6200000.50 - 100000.25 - 500000.00 = 5600000.25
        assert_money(closed["settlement_buyer_due_usd"], EXPECTED_BUYER_DUE,
                     "settlement_buyer_due_usd")
        # 6200000.50 - 344000.01 = 5856000.49
        assert_money(closed["settlement_seller_net_usd"], EXPECTED_SELLER_NET_SOLE,
                     "settlement_seller_net_usd")

    def test_close_dual_agency_diverges_from_sole(self, api):
        """PRD §3.9: "When `dual_agency` is true — both sides represented by
        this brokerage — a buyer-side fee of two percent of the entire base is
        added on top of the tiered amount, and the combined figure is rounded
        half up to two decimal places; the dual-agency variant therefore
        diverges from sole agency on an identical price and credits."

        Design: Difficulty/dual_variant_calc/commission_sole_vs_dual_diverge
        """
        deal = setup_closable_canonical_deal(dual_agency=True)
        closed = validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        # 344000.01 + round_half_up(6100000.25 * 0.02) -> 466000.02 combined
        assert_money(closed["commission_amount_usd"], EXPECTED_COMMISSION_DUAL,
                     "DUAL commission")
        assert float(closed["commission_amount_usd"]) != pytest.approx(
            EXPECTED_COMMISSION_SOLE, abs=0.005), (
            "Dual agency must diverge from sole agency on identical economics")
        # buyer_due is unaffected by the commission variant
        assert_money(closed["settlement_buyer_due_usd"], EXPECTED_BUYER_DUE,
                     "settlement_buyer_due_usd")
        # 6200000.50 - 466000.02 = 5734000.48
        assert_money(closed["settlement_seller_net_usd"], EXPECTED_SELLER_NET_DUAL,
                     "settlement_seller_net_usd")


class TestCloseCascade:
    def test_close_cascades_escrow_release_and_listing_sold(self, api):
        """PRD §3.9: "A successful closing cascades outward. The escrow deposit
        moves from `FUNDED` to `RELEASED` with `released_usd` set to the full
        `deposit_amount_usd` disbursed to the seller. The listing moves from
        `UNDER_CONTRACT` to `SOLD`, its terminal state"
        PRD §3.9: "The transaction itself moves to `CLOSED`, terminal, with its
        `version` incremented by the closing."

        Design: Difficulty/transitive_cascade/close_cascade_transaction_listing_comparable
        """
        deal = setup_closable_canonical_deal()
        closed = validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        assert closed["status"] == "CLOSED"
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "SOLD"
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "RELEASED"
        assert_money(escrow["released_usd"], 500000.00, "released_usd")
        assert_escrow_disposition_invariant(escrow)

    def test_close_mints_verified_comparable_from_listing(self, api):
        """PRD §3.9: "The listing moves from `UNDER_CONTRACT` to `SOLD`, its
        terminal state, and the same cascade mints a market comparable from the
        closing: a new `VERIFIED` comparable sale whose `make`, `model`, `year`,
        and `total_time_hours` are copied from the listing, whose
        `sale_price_usd` is the transaction's `agreed_price_usd`, whose
        `sale_date` is the closing request's date, and whose `source_listing_id`
        is the sold listing's id"

        Design: Difficulty/transitive_cascade/close_cascade_transaction_listing_comparable
        """
        deal = setup_closable_canonical_deal()
        validate_success(api.close_transaction(deal["transaction"]["id"], BROKER))
        rows, meta = validate_paginated(
            api.list_comparable_sales(LISTING_AGENT,
                                      {"source_listing_id": deal["listing"]["id"]}))
        assert meta["total_count"] == 1, "Exactly one comparable is minted at closing"
        comp = rows[0]
        assert comp["comp_status"] == "VERIFIED"
        assert_money(comp["sale_price_usd"], 6200000.50, "sale_price_usd")
        assert comp["make"] == "Gulfstream"
        assert comp["model"] == "G550"
        assert comp["year"] == 2015
        assert comp["total_time_hours"] == 2900
        assert comp["source_listing_id"] == deal["listing"]["id"]


class TestClosingGates:
    def test_close_without_registration_docs_returns_incomplete(self, api):
        """PRD §3.9: "It requires both `logbook_complete` and
        `registration_docs_complete` to be true; closing with either condition
        unmet is rejected with `ERR_DELIVERY_CONDITIONS_INCOMPLETE` (HTTP 409)."

        Design: Corner/errors/close_without_registration_docs_returns_incomplete
        """
        deal = setup_delivery_pending_deal()  # accept-as-is path, escrow FUNDED
        tx_id = deal["transaction"]["id"]
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        get_success_data(
            api.patch_delivery_conditions(
                tx_id,
                delivery_conditions_payload(tx["version"], logbook_complete=True),
                BROKER))
        resp = api.close_transaction(tx_id, BROKER)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_CONDITIONS_INCOMPLETE)
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert tx["status"] == "DELIVERY_PENDING"
        assert tx["commission_amount_usd"] is None, "No commission computed on rejection"
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "FUNDED"

    def test_facility_scheduler_cannot_close_transaction(self, api):
        """PRD §2.1: "Each endpoint declares the roles authorized to invoke it,
        and a caller whose role is not in that list is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "POST `/api/transactions/{id}/close` | Close the deal: computes
        commission + settlement, releases escrow, sells listing, records
        comparable | BrokerPrincipal"

        Design: Corner/rbac/facility_scheduler_cannot_close_transaction
        """
        deal = setup_closable_deal()
        resp = api.close_transaction(deal["transaction"]["id"], SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        tx = validate_success(api.get_transaction(deal["transaction"]["id"], BROKER))
        assert tx["status"] == "DELIVERY_PENDING"

    def test_get_transaction_not_found_returns_404(self, api):
        """PRD §2.9: "Wherever a path carries identifiers, the system validates
        their existence sequentially from left to right and rejects the request
        with the not-found error corresponding to the first identifier that does
        not resolve: `ERR_LISTING_NOT_FOUND`, `ERR_BUYER_NOT_FOUND`,
        `ERR_COMPARABLE_SALE_NOT_FOUND`, `ERR_LOI_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_ESCROW_DEPOSIT_NOT_FOUND`,
        `ERR_INSPECTION_FACILITY_NOT_FOUND`, `ERR_INSPECTION_BOOKING_NOT_FOUND`,
        or `ERR_DISCREPANCY_ITEM_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/get_transaction_not_found_returns_404
        """
        get_success_data(api.create_buyer(create_buyer_payload(), BUYER_AGENT))
        resp = api.get_transaction(NON_EXISTENT_UUID, BROKER)
        validate_error(resp, ApiErrorId.ERR_TRANSACTION_NOT_FOUND)


class TestTerminationEscrowDisposition:
    def test_fund_then_terminate_refunds_full_deposit(self, api):
        """PRD §3.9: "Termination from `OPENED`, `ESCROW_FUNDED`,
        `INSPECTION_SCHEDULED`, `INSPECTION_COMPLETE`, or
        `DISCREPANCY_NEGOTIATION` refunds the buyer: a `FUNDED` escrow moves to
        `REFUNDED` with `refunded_usd` set to the full `deposit_amount_usd`"
        PRD §3.9: "In every termination the listing cascades from
        `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the
        transaction's `version` increments."

        Design: Difficulty/compensating_invariant/escrow_fund_then_refund_conserves_deposit
        """
        deal = setup_funded_deal()  # ESCROW_FUNDED, deposit 100000.00
        terminated = terminate_deal(deal["transaction"]["id"], as_role=LISTING_AGENT)
        assert terminated["status"] == "TERMINATED"
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "REFUNDED"
        assert_money(escrow["refunded_usd"], 100000.00, "refunded_usd")
        assert float(escrow["released_usd"]) == 0
        assert float(escrow["forfeited_usd"]) == 0
        assert_escrow_disposition_invariant(escrow)
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "ACTIVE"

    def test_non_terminal_escrow_disposes_nothing(self, api):
        """PRD §3.9: "the sum of `released_usd`, `refunded_usd`, and
        `forfeited_usd` equals exactly the `deposit_amount_usd` when the escrow
        is terminal (`RELEASED`, `REFUNDED`, or `FORFEITED`) and exactly zero
        while it is non-terminal."
        PRD §3.6: "it begins in `AWAITING_FUNDS` status with `funding_reference`
        null and `released_usd`, `refunded_usd`, and `forfeited_usd` all at 0."

        Design: Difficulty/compensating_invariant/escrow_fund_then_refund_conserves_deposit
        """
        deal = setup_accepted_deal()
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "AWAITING_FUNDS"
        assert float(escrow["released_usd"]) == 0
        assert float(escrow["refunded_usd"]) == 0
        assert float(escrow["forfeited_usd"]) == 0
        assert_escrow_disposition_invariant(escrow)

        fund_escrow(deal["escrow"]["id"])
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "FUNDED"
        assert_escrow_disposition_invariant(escrow)

    def test_terminate_at_delivery_pending_forfeits_deposit(self, api):
        """PRD §3.9: "Termination from `DELIVERY_PENDING` forfeits the deposit
        to the seller: the escrow moves from `FUNDED` to `FORFEITED` with
        `forfeited_usd` set to the full `deposit_amount_usd`."
        PRD §3.9: "In every termination the listing cascades from
        `UNDER_CONTRACT` back to `ACTIVE` and becomes marketable again, and the
        transaction's `version` increments."

        Design: Corner/errors/terminate_at_delivery_pending_forfeits_deposit
        """
        deal = setup_delivery_pending_deal()  # accept-as-is path, escrow FUNDED
        terminated = terminate_deal(deal["transaction"]["id"],
                                    reason="buyer default after technical acceptance",
                                    as_role=BROKER)
        assert terminated["status"] == "TERMINATED"
        escrow = validate_success(api.get_escrow_deposit(deal["escrow"]["id"], ESCROW))
        assert escrow["status"] == "FORFEITED"
        assert_money(escrow["forfeited_usd"], 100000.00, "forfeited_usd")
        assert float(escrow["refunded_usd"]) == 0
        assert float(escrow["released_usd"]) == 0
        assert_escrow_disposition_invariant(escrow)
        listing = validate_success(api.get_listing(deal["listing"]["id"], LISTING_AGENT))
        assert listing["status"] == "ACTIVE"


class TestDeliveryConditionOcc:
    def test_occ_delivery_conditions_stale_version_rejected(self, api):
        """PRD §2.6: "Updating a transaction's delivery-condition checklist
        requires `expected_transaction_version`, a non-optional field holding
        the transaction's `version` as the client last observed it. Condition
        updates are legitimate in every non-terminal transaction state, so the
        version is the only deterministic signal that the client's view (of
        `credits_total_usd`, `status`, or the conditions themselves) is out of
        date; a mismatch with the transaction's current `version` is rejected
        with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_delivery_conditions_stale_version_rejected
        """
        deal = setup_accepted_deal()
        tx_id = deal["transaction"]["id"]
        v0 = deal["transaction"]["version"]
        get_success_data(
            api.patch_delivery_conditions(
                tx_id, delivery_conditions_payload(v0, logbook_complete=True), BROKER))
        # The second PATCH carries the version observed before the first landed.
        resp = api.patch_delivery_conditions(
            tx_id, delivery_conditions_payload(v0, registration_docs_complete=True),
            BROKER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        tx = validate_success(api.get_transaction(tx_id, BROKER))
        assert tx["logbook_complete"] is True, "First patch persists"
        assert tx["registration_docs_complete"] is False, "Stale patch is not applied"
        assert tx["version"] == v0 + 1
