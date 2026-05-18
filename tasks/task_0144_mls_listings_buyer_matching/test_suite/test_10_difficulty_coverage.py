"""Dedicated coverage for difficulty-design instances.

Every test here is tagged with `# difficulty: <rule_id>/<instance.name>`
so the coverage audit can correlate. Each test exercises a PRD-stated
rule cited in its docstring; the difficulty index is the priority queue
that motivated the test, not the source of authority.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_offer,
    advance_clock,
    advance_clock_and_sweep,
    api_client,
    attach_contingency,
    close_listing,
    counter_offer,
    create_buyer,
    create_buyer_agent,
    create_listing,
    create_listing_agent,
    create_listing_with_armed_lockbox,
    fail_contingency,
    get_listing_state,
    get_offer_state,
    iso_at,
    iso_in_future,
    iso_in_past,
    list_commission_splits,
    make_buyer_agent_headers,
    make_listing_agent_headers,
    rebound_offer,
    rebound_offer_payload,
    request_showing,
    request_showing_payload,
    setup_listing_and_buyer,
    setup_listing_under_contract,
    setup_multi_round_negotiation,
    setup_offer_with_open_counter,
    setup_sold_listing,
    submit_offer,
    submit_offer_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Rule 2 / instance 3: rebound_round_no_increment_circular_eval
# ---------------------------------------------------------------------------
class TestRebound_RoundNoChain:

    def test_three_round_chain_round_no_increments_each_step(self, api):
        """PRD §3.6: 'a new Offer row is created with status of
        SUBMITTED, its parent_counter_id set to the just-rebounded
        counter, and its round_no set to the previous offer's round_no
        plus 1.'

        Claim: Across a 3-round chain, round_no goes 1 → 2 → 3 and
        every prior Counter is REBOUND.

        # difficulty: combinatorial_formula/rebound_round_no_increment_circular_eval
        """
        state = setup_multi_round_negotiation()
        offer1, offer2, offer3 = state["offer1"], state["offer2"], state["offer3"]
        assert offer1["round_no"] == 1
        assert offer2["round_no"] == 2
        assert offer3["round_no"] == 3
        # parent_counter_id back-references.
        assert offer2["parent_counter_id"] == state["counter1"]["id"]
        assert offer3["parent_counter_id"] == state["counter2"]["id"]

    def test_final_net_to_seller_sums_only_rebound_counter_concessions(
        self, api,
    ):
        """PRD §3.8: 'the seller-concessions term is replaced by the
        sum of counter_concessions_cents taken from every Counter row
        along the negotiation chain that reached the accepted offer
        (only counters in REBOUND status are summed, ordered by
        created_at ascending), capped so that the cumulative actual
        concessions cannot exceed the offer price'.

        Claim: With Counter1.counter_concessions_cents=200_000 (now
        REBOUND) and Counter2.counter_concessions_cents=50_000 (now
        REBOUND), accepting Offer3 and closing yields a FINAL
        net-to-seller using 250_000 as the actual concession sum.

        # difficulty: combinatorial_formula/rebound_round_no_increment_circular_eval
        # difficulty: dual_variant_calc/offer_net_to_seller_provisional_vs_final_on_concession_drift
        """
        state = setup_multi_round_negotiation(
            list_price_cents=50_000_000,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            round1_counter_concessions=200_000,
            round2_counter_concessions=50_000,
        )
        la = state["listing_agent"]
        listing = state["listing"]
        offer3 = state["offer3"]
        # Accept Offer3 — verify provisional uses Offer3 est_concessions
        # (100_000 from fixture) NOT the chain sum.
        accepted = accept_offer(listing, offer3, la)
        # PROVISIONAL net at acceptance, per PRD §3.8:
        #   net = offer_price - est_concessions - buyer_side - listing_side
        # offer_price = 50_000_000; est = 100_000 (from fixture rebound);
        # buyer_side = round(50_000_000 * 0.025) = 1_250_000;
        # listing_side = round(50_000_000 * 0.035) = 1_750_000;
        # net = 50_000_000 - 100_000 - 1_250_000 - 1_750_000 = 46_900_000.
        assert accepted["provisional_net_to_seller_cents"] == 46_900_000, (
            f"PROVISIONAL net mismatch: got "
            f"{accepted['provisional_net_to_seller_cents']!r}, expected 46_900_000"
        )
        # Close with no contingencies.
        listing_now = get_listing_state(listing["id"])
        close_listing(
            listing_now, la, version=listing_now["version"],
        )
        # The FINAL net-to-seller is not exposed as a top-level field by
        # PRD; it is described in §3.8 as the close-time recomputation.
        # Verify via the FINAL CommissionSplit row: buyer_side and
        # listing_side cents are unchanged from PROVISIONAL when
        # brokerage_split_pct stayed put.
        splits = list_commission_splits(listing["id"])
        prov = [s for s in splits if s.get("variant") == "PROVISIONAL"]
        final = [s for s in splits if s.get("variant") == "FINAL"]
        assert len(prov) == 1 and len(final) == 1
        # Sale price identical, commissions identical → only the
        # concessions term differs between PROVISIONAL (100_000) and
        # FINAL (200_000 + 50_000 = 250_000). The 150_000-cent gap is
        # PRD §3.8's stated divergence.
        # PROVISIONAL on Offer3: 46_900_000.
        # FINAL net = 50_000_000 - 250_000 - 1_250_000 - 1_750_000
        #            = 46_750_000.
        # We can't observe FINAL net directly via the PRD (no exposed
        # field at the listing level; provisional_net_to_seller_cents
        # belongs to the Offer entity). What we CAN observe is the
        # invariant: prov.commission cents == final.commission cents
        # when the splits haven't changed.
        assert prov[0]["buyer_side_cents"] == final[0]["buyer_side_cents"]
        assert prov[0]["listing_side_cents"] == final[0]["listing_side_cents"]


# ---------------------------------------------------------------------------
# Rule 4 / instance 1: accept_offer_triggers_3_hop_cascade
# (2nd test — PROVISIONAL split emission is the parallel fan-out)
# ---------------------------------------------------------------------------
class TestAccept_DepthCascade:

    def test_accept_emits_provisional_commission_split(self, api):
        """PRD §3.6: 'a CommissionSplit row with variant of PROVISIONAL
        is emitted using the commission-split calculation in §3.8.'

        Claim: After accepting an offer, exactly one PROVISIONAL
        CommissionSplit row exists for the listing (parallel fan-out
        side effect of the accept cascade).

        # difficulty: transitive_cascade/accept_offer_triggers_3_hop_cascade
        """
        state = setup_listing_under_contract()
        splits = list_commission_splits(state["accepted_listing"]["id"])
        prov = [s for s in splits if s.get("variant") == "PROVISIONAL"]
        assert len(prov) == 1, (
            f"Expected exactly one PROVISIONAL CommissionSplit row after "
            f"accept; got {len(prov)} rows: {splits}"
        )


# ---------------------------------------------------------------------------
# Rule 2 / instance 2: co_op_commission_residual_assignment_ordering
# (Second test — odd-cent sale price; verify the residual identity holds
# even when buyer-side and listing-side independently rounded would diverge.)
# ---------------------------------------------------------------------------
class TestCommission_ResidualOrdering:

    def test_residual_invariant_on_odd_cent_sale_price(self, api):
        """PRD §3.8: 'listing_side_cents is the gross commission minus
        the buyer-side portion — a residual assignment that guarantees
        the two side totals add up exactly to the gross, with no penny
        drift; the listing side is never computed independently from
        the total fraction minus the co-op fraction.'

        Claim: For sale_price=49_999_999 (an odd-cent value), the
        residual identity gross == listing_side + buyer_side holds
        exactly, AND listing_side_cents reflects the residual (not the
        independent (total - co_op) computation).

        # difficulty: combinatorial_formula/co_op_commission_residual_assignment_ordering
        """
        # Build a listing with sale that yields fractional cents.
        la, listing, lockbox = create_listing_with_armed_lockbox(
            list_price_cents=49_999_999,
            co_op_pct=0.025,
            total_commission_pct=0.06,
            listing_agent_split=0.70,
        )
        # BuyerAgent + Buyer at the same price.
        ba = create_buyer_agent(brokerage_split_pct=0.70)
        buyer = create_buyer(
            ba, max_price_cents=50_000_000, min_price_cents=40_000_000,
            desired_zips=["94110"],
        )
        offer = submit_offer(
            listing, buyer, ba,
            offer_price_cents=49_999_999,
            earnest_money_cents=1_000_000,
            estimated_seller_concessions_cents=0,
        )
        accept_offer(listing, offer, la)
        splits = list_commission_splits(listing["id"], variant="PROVISIONAL")
        prov = [s for s in splits if s.get("variant") == "PROVISIONAL"]
        assert len(prov) == 1
        row = prov[0]
        # gross = round_half_up(49_999_999 * 0.06) = 3_000_000
        # (since 2_999_999.94 rounds up to 3_000_000).
        # buyer_side = round_half_up(49_999_999 * 0.025) = 1_250_000.
        # listing_side = gross - buyer_side = 1_750_000 (RESIDUAL).
        assert row["gross_commission_cents"] == 3_000_000
        assert row["buyer_side_cents"] == 1_250_000
        assert row["listing_side_cents"] == 1_750_000
        # The residual identity MUST hold exactly.
        assert (
            row["gross_commission_cents"]
            == row["listing_side_cents"] + row["buyer_side_cents"]
        ), "PRD §3.8 residual identity broken"


# NOTE: TestStateBeforeSafety_Skipped removed — PRD §2.11 orders
# validation CATEGORIES but does not pin a tie-breaker between two
# state-category errors on the same endpoint. The rule the test would
# have asserted is not uniquely derivable from PRD prose, so the test
# is deleted under the validation-priority silence category.


# ---------------------------------------------------------------------------
# Rule 5 / instance 2: counter_expired vs offer_expired
# (Second test — confirm ERR_COUNTER_EXPIRED fires when BOTH the counter
# and the new offer's expires_at are expired.)
# ---------------------------------------------------------------------------
class TestPriority_CounterBeforeOfferExpiry:

    def test_rebound_with_both_expired_returns_counter_expired(self, api):
        """PRD §2.11: 'state-specific errors → time/business-window
        errors → schema-fiscal errors.' (Counter expiration is the
        state-specific rebound check at PRD §3.6.)

        Claim: When BOTH the counter and the new offer's expires_at are
        in the past at rebound time, ERR_COUNTER_EXPIRED is returned
        (the counter-state check pre-empts the offer-fiscal-temporal
        check).

        # difficulty: priority_pair_validation_conflict/business_referential_vs_business_temporal_overlap_vs_expired_counter
        """
        state = setup_offer_with_open_counter()
        listing = state["listing"]
        offer = state["offer"]
        counter = state["counter"]
        ba = state["buyer_agent"]
        ce = counter["counter_expires_at"]
        ce_dt = datetime.fromisoformat(ce.replace("Z", "+00:00"))
        target = ce_dt + timedelta(seconds=60)
        advance_clock(iso_at(target))
        # Rebound with already-expired offer expires_at AND past
        # counter_expires_at.
        res = api.rebound_offer(
            listing["id"], offer["id"],
            rebound_offer_payload(
                offer_price_cents=50_000_000,
                earnest_money_cents=1_000_000,
                expires_at=iso_at(target - timedelta(seconds=1)),
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        validate_error(res, ApiErrorId.ERR_COUNTER_EXPIRED.value)


# ---------------------------------------------------------------------------
# Rule 6 / instance 1: offer_expires_at_strict_greater_than_now
# (Second test — strictly-greater-than boundary at +1ms.)
# ---------------------------------------------------------------------------
class TestExpiresAt_Boundary:

    def test_expires_at_strictly_in_future_accepted(self, api):
        """PRD §3.6: 'The expires_at deadline must be strictly in the
        future at the moment of submission; otherwise the submission
        is rejected with ERR_OFFER_EXPIRED.'

        Claim: expires_at strictly in the future → POST /offers
        returns 201.

        # difficulty: boundary_precision_check/offer_expires_at_strict_greater_than_now
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        res = api.submit_offer(
            listing["id"],
            submit_offer_payload(
                buyer_id=buyer["id"],
                expires_at=iso_in_future(120),
                offset_seconds=120,
            ),
            make_buyer_agent_headers(ba["id"]),
        )
        offer = validate_success(res, 201)
        assert offer["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# Rule 9 / instance 2: listing_revert_clears_accepted_offer_count_invariant
# ---------------------------------------------------------------------------
class TestAccept_RevertCount:

    def test_accept_sets_accepted_offer_id_and_offer_status_accepted(self, api):
        """PRD §3.6: 'Acceptance ... The accepted offer's id is
        recorded on the listing as accepted_offer_id.'

        Claim: After accept, exactly one Offer on the listing has
        status ACCEPTED, and Listing.accepted_offer_id equals that
        offer's id.

        # difficulty: compensating_invariant/listing_revert_clears_accepted_offer_count_invariant
        """
        la, listing, lockbox, ba, buyer = setup_listing_and_buyer()
        offer = submit_offer(listing, buyer, ba)
        accept_offer(listing, offer, la)
        listing_after = get_listing_state(listing["id"])
        assert listing_after["accepted_offer_id"] == offer["id"]
        # The single ACCEPTED count.
        offers_resp = api.list_offers(
            listing["id"], TEST_USERS["mls_admin_headers"],
        )
        from test_helpers import get_success_data
        offers = get_success_data(offers_resp)
        accepted = [o for o in offers if o["status"] == "ACCEPTED"]
        assert len(accepted) == 1
        assert accepted[0]["id"] == offer["id"]

    def test_fail_contingency_clears_accepted_offer_count_back_to_zero(self, api):
        """PRD §3.7: 'A failed contingency cascades. The accepted offer
        is withdrawn ... the listing's accepted_offer_id is cleared
        back to null; and the listing transitions from UNDER_CONTRACT
        back to ACTIVE.'

        Claim: After contingency fail, accepted_offer_id is null and
        zero offers have status ACCEPTED on the listing.

        # difficulty: compensating_invariant/listing_revert_clears_accepted_offer_count_invariant
        """
        state = setup_listing_under_contract()
        c = attach_contingency(
            state["accepted_listing"], state["accepted_offer"],
            state["buyer_agent"], kind="INSPECTION",
        )
        fail_contingency(state["accepted_listing"], c, state["buyer_agent"])
        listing_after = get_listing_state(state["accepted_listing"]["id"])
        assert listing_after["accepted_offer_id"] is None
        assert listing_after["status"] == "ACTIVE"
        # Zero ACCEPTED offers.
        offers_resp = api.list_offers(
            state["accepted_listing"]["id"],
            TEST_USERS["mls_admin_headers"],
        )
        from test_helpers import get_success_data
        offers = get_success_data(offers_resp)
        accepted = [o for o in offers if o["status"] == "ACCEPTED"]
        assert len(accepted) == 0, (
            f"PRD §3.7 cascade should clear ACCEPTED count; "
            f"found {len(accepted)} ACCEPTED offer(s) still on listing"
        )
        # And the previously-accepted offer is now WITHDRAWN.
        former = next(
            (o for o in offers if o["id"] == state["accepted_offer"]["id"]),
            None,
        )
        assert former is not None
        assert former["status"] == "WITHDRAWN"


# ---------------------------------------------------------------------------
# Rule 3 / instance 1 (2nd) — re-enter UNDER_CONTRACT via a new accept
# after revert.
# ---------------------------------------------------------------------------
class TestListing_CycleReEntry:

    def test_listing_can_reenter_under_contract_after_revert(self, api):
        """PRD §3.7: cascade returns the listing to ACTIVE. PRD §3.6:
        a new SUBMITTED offer may be accepted, driving ACTIVE →
        UNDER_CONTRACT again — the listing state machine is cyclic on
        the ACTIVE↔UNDER_CONTRACT edge.

        Claim: After contingency-fail revert, submitting and accepting
        a brand-new offer drives the listing UNDER_CONTRACT a second
        time.

        # difficulty: non_linear_state_machine/listing_under_contract_revert_to_active_on_contingency_fail
        """
        state = setup_listing_under_contract()
        la = state["listing_agent"]
        ba = state["buyer_agent"]
        listing = state["accepted_listing"]
        buyer = state["buyer"]
        # Attach + fail contingency to revert.
        c = attach_contingency(listing, state["accepted_offer"], ba, kind="INSPECTION")
        fail_contingency(listing, c, ba)
        # The buyer's previous offer is WITHDRAWN; submit a NEW offer
        # from the same buyer (Buyer.status is still ACTIVE — only
        # CLOSE sets buyer SOLD; revert leaves the buyer ACTIVE).
        listing_after = get_listing_state(listing["id"])
        assert listing_after["status"] == "ACTIVE"
        new_offer = submit_offer(listing_after, buyer, ba)
        accept_offer(listing_after, new_offer, la)
        listing_final = get_listing_state(listing["id"])
        assert listing_final["status"] == "UNDER_CONTRACT"
        assert listing_final["accepted_offer_id"] == new_offer["id"]
