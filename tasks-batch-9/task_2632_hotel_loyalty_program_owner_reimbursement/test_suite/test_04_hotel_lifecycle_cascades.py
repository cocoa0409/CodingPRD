"""Property lifecycle: delinquency and its only exit, the two independent
dimensions of an award booking, and the two multi-hop unwinds - a stay void and a
property termination."""

from test_helpers import (
    assert_all_deliveries_status,
    assert_batch,
    assert_batch_money_fields_zeroed,
    assert_fund,
    assert_hotel,
    assert_ledger_entry,
    assert_member,
    assert_redemption,
    assert_scoped_ledger_sum_is_zero,
    assert_stay,
    entries_of_type,
    fixtures as fx,
    make_member_headers,
)


# ----------------------------------------------------------------------
# Scenario builders
# ----------------------------------------------------------------------
def _stonegate_delinquent_with_an_approved_batch(api):
    """A delinquent convention property whose September batch has been released and
    approved by two distinct operators and is waiting to be paid."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="GRP-CYC",
        rate_category="GROUP",
        name="Stonegate Grand Hall",
        brand_code="SGH",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=610,
        trailing_12m_occupancy_pct=0.96,
        trailing_12m_adr_cents=241_000,
    )
    hotel_id = bundle["hotel"]["id"]
    group_guest = fx.enroll_member(api)
    group_stay = fx.posted_stay(
        api,
        hotel_id,
        group_guest["id"],
        bundle["rate_plan"]["id"],
        "2026-06-01",
        "2026-06-15",
        14_000_000,
    )
    bundle["hotel_after_posting"] = fx.read_hotel(api, hotel_id)

    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    partner = fx.create_partner(
        api,
        name="Meridian SkyAlliance",
        partner_type="AIRLINE",
        points_cost_per_1000_cents=5_000,
        monthly_cap_points=500_000,
    )
    booker = fx.enroll_member(api)
    fx.settled_purchase(
        api, booker["id"], 200_000, channel="PARTNER_SALE", partner_id=partner["id"]
    )
    booker_headers = make_member_headers(booker["id"])

    booking = fx.book_award(
        api, booker["id"], hotel_id, "2026-09-10", "2026-09-15", headers=booker_headers
    )
    fx.confirm_award(api, booking["id"], headers=booker_headers)
    fx.set_clock_to_day(api, "2026-09-20")
    booking = fx.complete_award_stay(api, booking["id"])

    batch = fx.released_batch(api, hotel_id, "2026-09", releaser_id="op-release-03")
    batch = fx.approve_batch(api, batch["id"], approver_id="op-approve-03")

    bundle["group_guest"] = group_guest
    bundle["group_stay"] = group_stay
    bundle["partner"] = partner
    bundle["booker"] = booker
    bundle["booking"] = booking
    bundle["batch"] = batch
    return bundle


def _ashcroft_with_a_released_batch_awaiting_judgement(api):
    """One completed two-night award, batched and released, sitting in front of an
    administrator who is about to reject the batch."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-ACR",
        rate_category="TRANSIENT",
        name="Ashcroft Row Hotel",
        brand_code="ACR",
        market_tier="URBAN",
        program_fee_pct=0.04,
        rooms_count=150,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    member = fx.member_with_goodwill_points(api, 100_000)
    member_headers = make_member_headers(member["id"])

    booking = fx.book_award(
        api, member["id"], hotel_id, "2026-09-05", "2026-09-07", headers=member_headers
    )
    fx.confirm_award(api, booking["id"], headers=member_headers)
    fx.set_clock_to_day(api, "2026-09-08")
    booking = fx.complete_award_stay(api, booking["id"])
    batch = fx.released_batch(api, hotel_id, "2026-09", releaser_id="op-release-04")

    bundle["member"] = member
    bundle["member_headers"] = member_headers
    bundle["booking"] = booking
    bundle["batch"] = batch
    return bundle


def _vanport_platinum_resting_on_one_long_stay(api):
    """Fifty qualifying nights on one stay carry the guest to PLATINUM; a second,
    short stay was captured at that tier and owes all three benefits."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-VPL",
        rate_category="TRANSIENT",
        name="Vanport Landing",
        brand_code="VPL",
        market_tier="URBAN",
        program_fee_pct=0.05,
        rooms_count=210,
        trailing_12m_occupancy_pct=0.78,
        trailing_12m_adr_cents=26_000,
    )
    hotel_id = bundle["hotel"]["id"]
    rate_plan_id = bundle["rate_plan"]["id"]
    member = fx.enroll_member(api)

    long_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-05-01", "2026-06-20", 95_000
    )
    platinum_stay = fx.posted_stay(
        api, hotel_id, member["id"], rate_plan_id, "2026-07-10", "2026-07-12", 100_000
    )

    bundle["member"] = member
    bundle["long_stay"] = long_stay
    bundle["platinum_stay"] = platinum_stay
    return bundle


def _chandler_with_one_batched_and_one_accrued_award(api):
    """Two completed awards at one property: September's is attached to a released
    batch, October's is still accrued and attached to nothing."""
    bundle = fx.create_active_hotel(
        api,
        rate_code="BAR-CHO",
        rate_category="TRANSIENT",
        name="Chandler House",
        brand_code="CHO",
        market_tier="URBAN",
        program_fee_pct=0.04,
        rooms_count=160,
        trailing_12m_occupancy_pct=0.82,
        trailing_12m_adr_cents=30_000,
    )
    hotel_id = bundle["hotel"]["id"]
    fx.publish_standard_pricing(
        api,
        hotel_id,
        points_per_night=40_000,
        cash_copay_cents=0,
        min_tier_required="BASE",
        award_allotment_per_night=5,
    )
    funded = fx.member_funded_by_purchase(api, 200_000, channel="DIRECT_PURCHASE")
    member_id = funded["member"]["id"]
    member_headers = funded["member_headers"]

    september = fx.book_award(
        api, member_id, hotel_id, "2026-09-01", "2026-09-03", headers=member_headers
    )
    fx.confirm_award(api, september["id"], headers=member_headers)
    fx.set_clock_to_day(api, "2026-09-05")
    september = fx.complete_award_stay(api, september["id"])

    october = fx.book_award(
        api, member_id, hotel_id, "2026-10-05", "2026-10-07", headers=member_headers
    )
    fx.confirm_award(api, october["id"], headers=member_headers)

    batch = fx.released_batch(api, hotel_id, "2026-09", releaser_id="op-release-05")

    fx.set_clock_to_day(api, "2026-10-08")
    october = fx.complete_award_stay(api, october["id"])

    bundle["member"] = funded["member"]
    bundle["september_award"] = september
    bundle["october_award"] = october
    bundle["batch"] = batch
    return bundle


# ----------------------------------------------------------------------
# Delinquency and its only exit.
# ----------------------------------------------------------------------
class TestPropertyCyclesThroughDelinquency:
    def test_posting_the_group_stay_carries_the_ledger_past_the_delinquency_line(
        self, api
    ):
        """A 700,000-cent fee ledger is strictly above the line, so the property
        leaves ACTIVE on the posting request itself.

        PRD: "At the end of any request that posts a paid stay or adjusts a disputed
        one, if the property's recomputed `fee_ledger_balance_cents` is strictly
        greater than 250,000 cents — that is, above two thousand five hundred dollars
        of outstanding fee — the property moves `ACTIVE → FEE_DELINQUENT` and its
        `version` increments."

        Design: Difficulty/non_linear_state_machine/hotel_cycles_active_to_fee_delinquent_and_back_on_batch_payment
        """
        bundle = _stonegate_delinquent_with_an_approved_batch(api)

        assert_hotel(
            bundle["hotel_after_posting"],
            status="FEE_DELINQUENT",
            fee_ledger_cents=700_000,
        )
        assert_stay(
            fx.read_stay(api, bundle["group_stay"]["id"]),
            status="POSTED_QUALIFYING",
            base_points=840_000,
            fee_cents=700_000,
        )

    def test_paying_the_batch_returns_the_property_to_active_transitively(self, api):
        """No request was aimed at the property; the restoration is reached through
        the payment of its batch.

        PRD: "The reverse move happens only through settlement: at the end of a batch
        payment, if the property's `fee_ledger_balance_cents` after that settlement
        stands at or below zero, a property that was `FEE_DELINQUENT` returns to
        `ACTIVE` and its `version` increments again."

        Design: Difficulty/non_linear_state_machine/hotel_cycles_active_to_fee_delinquent_and_back_on_batch_payment
        """
        bundle = _stonegate_delinquent_with_an_approved_batch(api)

        paid = fx.pay_batch(api, bundle["batch"]["id"], payer_id="op-pay-03")

        assert_batch(paid, status="PAID", net_payable_cents=498_000)
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            reimbursement_owed_cents=0,
        )
        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="STAYED",
            reimbursement_status="PAID",
        )

    def test_the_surcharge_is_money_the_fund_keeps_not_credit_the_property_receives(
        self, api
    ):
        """The re-derivation subtracts the offset base, so a 700,000-cent ledger
        settled by a batch carrying a 7,000-cent surcharge lands on zero.

        PRD: "Because the ledger derivation subtracts the offset **base** and not the
        offset total, the surcharge is money the fund keeps rather than credit the
        property receives — a 700,000-cent ledger settled by a batch carrying a
        7,000-cent surcharge lands at exactly 0, not at minus 7,000."

        Design: Difficulty/non_linear_state_machine/hotel_cycles_active_to_fee_delinquent_and_back_on_batch_payment
        """
        bundle = _stonegate_delinquent_with_an_approved_batch(api)
        assert_batch(
            bundle["batch"],
            status="APPROVED",
            fee_offset_base_cents=700_000,
            surcharge_cents=7_000,
        )

        fx.pay_batch(api, bundle["batch"]["id"], payer_id="op-pay-03")

        hotel = fx.read_hotel(api, bundle["hotel"]["id"])
        assert hotel["fee_ledger_balance_cents"] == 0, (
            "expected the ledger to land on 0 rather than minus the surcharge, got "
            f"{hotel['fee_ledger_balance_cents']}"
        )

    def test_programme_cash_falls_by_the_net_payable_and_the_posture_is_re_derived(
        self, api
    ):
        """Cash moves by the net, not the gross, and the fund's posture is recomputed
        from the ratio that results.

        PRD: "The posture then follows: `HEALTHY` at a ratio of 1.0000 or above,
        `WATCH` from 0.7500 up to but not including 1.0000, and `IMPAIRED` below
        0.7500."

        Design: Difficulty/non_linear_state_machine/hotel_cycles_active_to_fee_delinquent_and_back_on_batch_payment
        """
        bundle = _stonegate_delinquent_with_an_approved_batch(api)
        assert_fund(fx.read_fund(api), cash_cents=880_000)

        fx.pay_batch(api, bundle["batch"]["id"], payer_id="op-pay-03")

        assert_fund(
            fx.read_fund(api),
            cash_cents=382_000,
            outstanding_points=880_000,
            liability_cents=422_400,
            solvency_ratio=0.9044,
            status="WATCH",
        )


# ----------------------------------------------------------------------
# The two dimensions of a booking move independently.
# ----------------------------------------------------------------------
class TestBookingDimensionsMoveIndependentlyUnderRejection:
    def test_rejection_leaves_the_fulfilment_dimension_exactly_where_it_stood(self, api):
        """The guest slept in the room; a bookkeeping rejection cannot undo that, so
        only the reimbursement dimension moves.

        PRD: "The reimbursement dimension of every affected booking is now in exactly
        the state it held before release, so a later batch for the same period can
        pick those items up again."

        Design: Difficulty/non_linear_state_machine/redemption_parallel_dimensions_move_independently_under_batch_rejection
        """
        bundle = _ashcroft_with_a_released_batch_awaiting_judgement(api)

        fx.reject_batch(
            api,
            bundle["batch"]["id"],
            reason="Attestation missing from the owner statement",
            rejecter_id="op-approve-04",
        )

        assert_redemption(
            fx.read_redemption(api, bundle["booking"]["id"]),
            fulfillment_status="STAYED",
            reimbursement_status="ACCRUED",
        )

    def test_rejection_discards_the_settlement_figure_from_the_booking(self, api):
        """The settled figure is cleared and the batch link is broken, while the
        accrued estimate - which the property was told - stands.

        PRD: "Rejection unwinds the release completely: every booking whose
        `batch_id` names this batch reverts `reimbursement_status` `BATCHED →
        ACCRUED`, has its `batch_id` cleared to null and its
        `settled_reimbursement_cents` reset to 0 — the settlement figure is discarded
        from the booking and survives only on the batch, for audit."

        Design: Difficulty/non_linear_state_machine/redemption_parallel_dimensions_move_independently_under_batch_rejection
        """
        bundle = _ashcroft_with_a_released_batch_awaiting_judgement(api)
        assert_redemption(
            bundle["booking"], estimated_cents=45_000, reimbursement_status="ACCRUED"
        )

        fx.reject_batch(
            api,
            bundle["batch"]["id"],
            reason="Attestation missing from the owner statement",
            rejecter_id="op-approve-04",
        )

        booking = fx.read_redemption(api, bundle["booking"]["id"])
        assert_redemption(booking, settled_cents=0, estimated_cents=45_000)
        assert booking["batch_id"] is None, "rejection breaks the link to the batch"

    def test_rejection_zeroes_every_money_field_on_the_batch(self, api):
        """All six money fields are reset, and the reason is recorded.

        PRD: "The batch's own `item_count`, `gross_reimbursement_cents`,
        `fee_offset_base_cents`, `delinquency_surcharge_cents`,
        `total_fee_offset_cents` and `net_payable_cents` are all reset to 0 and its
        `version` increments."

        Design: Difficulty/non_linear_state_machine/redemption_parallel_dimensions_move_independently_under_batch_rejection
        """
        bundle = _ashcroft_with_a_released_batch_awaiting_judgement(api)
        assert_batch(
            bundle["batch"], status="RELEASED", gross_cents=45_000, net_payable_cents=45_000
        )

        rejected = fx.reject_batch(
            api,
            bundle["batch"]["id"],
            reason="Attestation missing from the owner statement",
            rejecter_id="op-approve-04",
        )

        assert_batch(
            rejected,
            status="REJECTED",
            rejection_reason="Attestation missing from the owner statement",
        )
        assert_batch_money_fields_zeroed(rejected)

    def test_the_owed_figure_sums_settled_amounts_so_it_reads_zero_throughout(self, api):
        """The property's owed figure is a sum of settlement amounts, and the
        member's balance is untouched by any of this.

        PRD: "the reimbursement owed is the sum of `settled_reimbursement_cents`
        across that property's award bookings whose `reimbursement_status` is either
        `ACCRUED` or `BATCHED`"

        Design: Difficulty/non_linear_state_machine/redemption_parallel_dimensions_move_independently_under_batch_rejection
        """
        bundle = _ashcroft_with_a_released_batch_awaiting_judgement(api)

        fx.reject_batch(
            api,
            bundle["batch"]["id"],
            reason="Attestation missing from the owner statement",
            rejecter_id="op-approve-04",
        )

        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]), reimbursement_owed_cents=0
        )
        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=20_000)


# ----------------------------------------------------------------------
# The stay void: reverse, drop the tier, waive the obligations.
# ----------------------------------------------------------------------
class TestStayVoidCascadesThroughTierToObligations:
    def test_the_void_reverses_every_entry_the_stay_produced(self, api):
        """One reversal per original entry, each negating its own original and naming
        it, leaves the stay's ledger scope at zero.

        PRD: "**Hop two:** because the stay went void, one `REVERSAL` ledger entry is
        written for every existing entry whose `source_stay_id` names this stay, each
        carrying `points` equal to the negation of the original entry's `points` and
        `reversal_of_entry_id` naming that original entry; and the stay's
        `program_fee_assessed_cents` is credited back, so the property's
        `fee_ledger_balance_cents` falls by that amount as the stay leaves the
        fee-ledger's status filter set."

        Design: Difficulty/transitive_cascade/stay_void_reverses_ledger_then_drops_tier_then_waives_benefit_obligations
        """
        bundle = _vanport_platinum_resting_on_one_long_stay(api)
        long_stay_id = bundle["long_stay"]["id"]
        original = entries_of_type(fx.ledger_for_stay(api, long_stay_id), "EARN_BASE")[0]

        voided = fx.void_stay(
            api, long_stay_id, reason="Folio duplicated by the property"
        )

        assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"
        assert voided["void_reason"] == "Folio duplicated by the property"
        reversals = entries_of_type(fx.ledger_for_stay(api, long_stay_id), "REVERSAL")
        assert len(reversals) == 1, (
            f"the stay wrote one entry, so it takes one reversal, saw {len(reversals)}"
        )
        assert_ledger_entry(
            reversals[0],
            entry_type="REVERSAL",
            points=-9_500,
            reversal_of_entry_id=original["id"],
            source_stay_id=long_stay_id,
        )
        assert_scoped_ledger_sum_is_zero(fx.ledger_for_stay(api, long_stay_id))

    def test_the_void_takes_the_nights_and_the_tier_with_them(self, api):
        """Losing fifty nights leaves only the short stay's two, which reads BASE.

        PRD: "**Hop three:** because those reversal entries were written, the member's
        `point_balance`, `lifetime_points_earned`, `qualifying_revenue_cents_ytd` and
        `qualifying_nights_ytd` are all recomputed, and the recomputed night count
        re-derives the member's `elite_tier`, which may drop."

        Design: Difficulty/transitive_cascade/stay_void_reverses_ledger_then_drops_tier_then_waives_benefit_obligations
        """
        bundle = _vanport_platinum_resting_on_one_long_stay(api)
        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="PLATINUM",
            qualifying_nights=52,
        )

        fx.void_stay(api, bundle["long_stay"]["id"], reason="Folio duplicated")

        assert_member(
            fx.read_member(api, bundle["member"]["id"]),
            elite_tier="BASE",
            qualifying_nights=2,
            qualifying_revenue_cents=100_000,
            point_balance=17_500,
        )

    def test_the_tier_drop_waives_obligations_on_a_stay_nobody_voided(self, api):
        """The fourth hop reaches across to another stay of the same member: at BASE
        nothing is entitled, so all three outstanding obligations are waived.

        PRD: "**Hop four:** because the member's `elite_tier` dropped, every elite
        benefit obligation in status `OBLIGATED` belonging to **any** stay of that
        member whose `benefit_type` is no longer entitled at the new tier moves to
        `WAIVED` — a downgrade all the way to `BASE` therefore waives all three
        benefit types across the member's outstanding obligations."

        Design: Difficulty/transitive_cascade/stay_void_reverses_ledger_then_drops_tier_then_waives_benefit_obligations
        """
        bundle = _vanport_platinum_resting_on_one_long_stay(api)
        platinum_stay_id = bundle["platinum_stay"]["id"]
        assert_all_deliveries_status(
            fx.obligations_for_stay(api, platinum_stay_id), "OBLIGATED"
        )

        fx.void_stay(api, bundle["long_stay"]["id"], reason="Folio duplicated")

        obligations = fx.obligations_for_stay(api, platinum_stay_id)
        assert len(obligations) == 3, (
            f"a platinum arrival owes three benefits, saw {len(obligations)}"
        )
        assert_all_deliveries_status(obligations, "WAIVED")
        assert all(o["cost_recovery_cents"] == 0 for o in obligations), (
            "a waived obligation recovers nothing"
        )

    def test_the_untouched_stay_keeps_its_earnings_and_its_own_snapshot(self, api):
        """The short stay was not the request's subject: its status, its snapshot and
        its bonus stand, and the fee ledger keeps only its fee.

        PRD: "Its `outstanding_points` is the signed sum of `points` across **every**
        ledger entry of every member, with no status filter and no exclusion list —
        reversals already carry negative amounts, so nothing needs to be excluded and
        the sum is insensitive to order."

        Design: Difficulty/transitive_cascade/stay_void_reverses_ledger_then_drops_tier_then_waives_benefit_obligations
        """
        bundle = _vanport_platinum_resting_on_one_long_stay(api)

        fx.void_stay(api, bundle["long_stay"]["id"], reason="Folio duplicated")

        assert_stay(
            fx.read_stay(api, bundle["platinum_stay"]["id"]),
            status="POSTED_QUALIFYING",
            tier_at_checkin="PLATINUM",
            base_points=10_000,
            bonus_points=7_500,
            fee_cents=5_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            status="ACTIVE",
            fee_ledger_cents=5_000,
            benefit_recovery_owed_cents=0,
        )
        assert_fund(
            fx.read_fund(api), outstanding_points=17_500, liability_cents=8_400
        )


# ----------------------------------------------------------------------
# Termination rejects the batch, then voids what the batch held.
# ----------------------------------------------------------------------
class TestTerminationRejectsTheBatchThenVoidsItsRows:
    def test_termination_rejects_the_open_batch_with_a_pinned_reason(self, api):
        """The reason on a batch rejected by termination is not the operator's prose;
        it is fixed by the cascade.

        PRD: "Every reimbursement batch of that property whose `status` is `OPEN` or
        `RELEASED` moves to `REJECTED` with `rejection_reason` set to
        `HOTEL_TERMINATED`, and each award booking attached to such a batch reverts
        `BATCHED → VOIDED` with its `batch_id` cleared to null."

        Design: Difficulty/transitive_cascade/hotel_termination_rejects_batch_then_voids_the_rows_that_batch_held
        """
        bundle = _chandler_with_one_batched_and_one_accrued_award(api)

        terminated = fx.terminate_hotel(
            api, bundle["hotel"]["id"], reason="Franchise agreement not renewed"
        )

        assert_hotel(
            terminated,
            status="TERMINATED",
            termination_reason="Franchise agreement not renewed",
        )
        assert_batch(
            fx.read_batch(api, bundle["batch"]["id"]),
            status="REJECTED",
            rejection_reason="HOTEL_TERMINATED",
        )

    def test_the_row_the_batch_held_is_voided_and_unlinked_on_the_way(self, api):
        """The September booking travelled from batched to voided in one request, and
        left its batch reference behind.

        PRD: "In both cases the property's `reimbursement_owed_cents` is recomputed,
        and a booking in `VOIDED` is excluded from every future batch selection
        exactly as `PAID` is."

        Design: Difficulty/transitive_cascade/hotel_termination_rejects_batch_then_voids_the_rows_that_batch_held
        """
        bundle = _chandler_with_one_batched_and_one_accrued_award(api)
        assert_redemption(
            fx.read_redemption(api, bundle["september_award"]["id"]),
            reimbursement_status="BATCHED",
            settled_cents=45_000,
        )

        fx.terminate_hotel(api, bundle["hotel"]["id"], reason="Franchise exit")

        # The termination cascade is specified as "each award booking attached to
        # such a batch reverts `BATCHED → VOIDED` with its `batch_id` cleared to
        # null" and names no other field, so only the status and the link are
        # asserted here.
        september = fx.read_redemption(api, bundle["september_award"]["id"])
        assert_redemption(
            september,
            fulfillment_status="STAYED",
            reimbursement_status="VOIDED",
            estimated_cents=45_000,
        )
        assert september["batch_id"] is None, (
            "termination clears the batch reference on the way to VOIDED"
        )

    def test_the_accrued_row_is_voided_directly_and_the_owed_figure_lands_on_zero(
        self, api
    ):
        """The October booking never reached a batch, so it takes the direct route.

        PRD: "Every award booking of that property whose `reimbursement_status` is
        `ACCRUED` moves `ACCRUED → VOIDED`; because those rows have left the owed set,
        the property's `reimbursement_owed_cents` is recomputed and lands at 0."

        Design: Difficulty/transitive_cascade/hotel_termination_rejects_batch_then_voids_the_rows_that_batch_held
        """
        bundle = _chandler_with_one_batched_and_one_accrued_award(api)

        fx.terminate_hotel(api, bundle["hotel"]["id"], reason="Franchise exit")

        assert_redemption(
            fx.read_redemption(api, bundle["october_award"]["id"]),
            fulfillment_status="STAYED",
            reimbursement_status="VOIDED",
            estimated_cents=45_000,
        )
        assert_hotel(
            fx.read_hotel(api, bundle["hotel"]["id"]),
            reimbursement_owed_cents=0,
            fee_ledger_cents=0,
        )

    def test_two_stayed_bookings_forfeit_no_points_and_move_no_cash(self, api):
        """Nothing was in flight on the fulfilment dimension, so the cascade writes no
        reversal and programme cash is exactly what the purchase put there.

        PRD: "Every award booking of that property whose `fulfillment_status` is
        `HELD` or `CONFIRMED` moves to `CANCELLED`, and the points it charged are
        returned to the member by a `REVERSAL` ledger entry exactly as if the member
        had cancelled it."

        Design: Difficulty/transitive_cascade/hotel_termination_rejects_batch_then_voids_the_rows_that_batch_held
        """
        bundle = _chandler_with_one_batched_and_one_accrued_award(api)

        fx.terminate_hotel(api, bundle["hotel"]["id"], reason="Franchise exit")

        assert_member(fx.read_member(api, bundle["member"]["id"]), point_balance=40_000)
        assert_fund(
            fx.read_fund(api),
            cash_cents=220_000,
            outstanding_points=40_000,
            liability_cents=19_200,
            solvency_ratio=11.4583,
            status="HEALTHY",
        )
