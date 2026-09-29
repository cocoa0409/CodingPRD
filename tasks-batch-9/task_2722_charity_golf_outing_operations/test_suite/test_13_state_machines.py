"""Lifecycles beyond the play dimension: contract, sale, lot, contest and unit."""

import pytest

from test_helpers import (
    CLOCK_START_UTC,
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_ALT_HEADERS,
    SPONSORSHIP_ALT_USER_ID,
    SPONSORSHIP_HEADERS,
    SPONSORSHIP_USER_ID,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_direct_costs,
    assert_instant_equals,
    assert_inventory_conservation,
    assert_rollup_chain,
    assert_version_unchanged,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

DOUBLE_SIGN_OUTING = {"name": "Double Sign Open", "field_capacity_teams": 4}
LATER_CLOCK = "2026-08-02T00:00:00Z"

CAPACITY_EDGE_OUTING = {"name": "Capacity Edge Open", "field_capacity_teams": 1}


class TestSigningASignedContractTwice:
    def test_the_repeat_signature_is_refused_and_signed_at_is_not_restamped(self, api):
        """`SIGN` is an edge out of two states, and `SIGNED` is neither of them.

        "Signing moves the contract from `DRAFT` to `SIGNED` and stamps `signed_at`
        from the logical clock", and the only other edge into that state is the
        countersignature, since "Countersigning an amendment returns it
        `AMENDED → SIGNED`, which closes the amendment cycle and leaves the contract
        able to be amended again."  A duplicate therefore fails the ladder's state
        tier, where "the requested action is a declared edge out of the target row's
        current state in the relevant lifecycle, including the parallel dimensions
        carried by outings and contests, otherwise `ERR_INVALID_STATE_TRANSITION`
        (HTTP 409)."

        Design: Corner/state_machines/signing_an_already_signed_contract_twice_is_rejected
        """
        ctx = fx.signed_contract_outing(api, outing=DOUBLE_SIGN_OUTING)
        signed = ctx["contract"]
        assert signed["status"] == "SIGNED"
        assert_instant_equals(signed["signed_at"], CLOCK_START_UTC)
        version_before = signed["version"]

        fx.set_clock(api, LATER_CLOCK, COURSE_HEADERS)

        validate_error(
            api.contract_lifecycle(
                signed["id"], f.contract_lifecycle_payload("SIGN"), COURSE_HEADERS
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )

        contract = fx.read_contract(api, signed["id"])
        assert contract["status"] == "SIGNED"
        assert_instant_equals(contract["signed_at"], CLOCK_START_UTC)
        assert contract["amendment_count"] == 0
        assert_version_unchanged(contract, version_before)


class TestPaymentOnTheCapacityBoundary:
    def test_landing_exactly_on_the_field_confirms_and_the_next_slot_waitlists(self, api):
        """The fork is a strict inequality, so the boundary payment is a confirmation.

        "the server compares the outing's current `confirmed_player_slots` plus this
        registration's `player_count` against the field's capacity in player slots,
        which is `field_capacity_teams` multiplied by four. When the sum is less than
        or equal to that capacity the registration moves
        `PENDING_PAYMENT → CONFIRMED`; when the sum strictly exceeds it, the
        registration moves `PENDING_PAYMENT → WAITLISTED` instead. The boundary
        matters: a payment that lands exactly on the capacity figure confirms, and
        only the first slot past it waitlists."  The money is taken either way, since
        "Both outcomes add `amount_cents` to `amount_paid_cents`", while
        "Waitlisting deliberately does none of that handicap work".  Tier inventory
        is untouched by a waitlisting, because `sold_count` counts "the number of
        registrations currently holding it whose status is `CONFIRMED`, `AMENDED`, or
        `CHECKED_IN`".

        Design: Corner/state_machines/payment_landing_exactly_on_field_capacity_confirms_and_the_next_one_waitlists
        """
        ctx = fx.open_outing(api, outing=CAPACITY_EDGE_OUTING)
        first = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Exactly Four", player_count=4
        )
        second = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="One Too Many", player_count=1
        )

        confirmed = fx.pay_registration(api, first["id"], 120000)
        assert confirmed["status"] == "CONFIRMED"
        assert_instant_equals(confirmed["confirmed_at"], CLOCK_START_UTC)

        waitlisted = fx.pay_registration(api, second["id"], 120000)
        assert waitlisted["status"] == "WAITLISTED"
        assert waitlisted["confirmed_at"] is None
        assert waitlisted["amount_paid_cents"] == 120000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 4
        assert outing["waitlisted_registration_count"] == 1
        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 1

        rows, meta = validate_paginated(
            api.list_registrations(
                DIRECTOR_HEADERS, outing_id=ctx["outing_id"], status="WAITLISTED"
            )
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [second["id"]]


RETRACTED_OUTING = {"name": "Retracted Bid Open", "field_capacity_teams": 4}
AUCTION_LOT = {
    "item_type": "AUCTION",
    "description": "Signed pin flag",
    "fmv_cents": 5000,
    "ask_cents": 40000,
}
VOID_REASON = "Winning bidder withdrew before paying"

ACE_OUTING = {"name": "Ace Prize Open", "field_capacity_teams": 4}
ACE_CONTEST = {
    "contest_type": "HOLE_IN_ONE",
    "hole_number": 12,
    "prize_value_cents": 500000,
    "yardage": 165,
    "prize_form": "CASH",
}
ACE_POLICY = {
    "insurance_carrier": "Fairway Mutual",
    "insurance_premium_cents": 45000,
    "insurance_coverage_cap_cents": 500000,
    "insurance_min_yardage": 150,
    "insurance_required_witness_count": 2,
}


class TestVoidingAndRelistingAFundraisingLot:
    def test_the_void_strips_the_sale_and_the_relist_reopens_the_same_lot(self, api):
        """One lot, two buyers, and a void counter that only ever climbs.

        "Voiding moves the item `SOLD → VOID`. Voiding clears
        `buyer_registration_id`, `bid_cents`, and `recorded_by_user_id`, reverses any
        collected revenue out of the rollup, and increments `void_count` by one; the
        request may carry a `void_reason`. Relisting then returns the lot
        `VOID → LISTED`, closing the sold-void-relist cycle so the same lot can be
        offered again to a different buyer."  The reserve survives the round trip, so
        the second offer still has to clear it, since "`bid_cents` must be greater
        than or equal to `ask_cents`".  An unpaid sale never reached the ledger in the
        first place, which counts only "the `collected_cents` of every fundraising
        item whose status is `PAID` or `RECEIPTED`".

        Design: Corner/state_machines/fundraising_item_voided_then_relisted_returns_to_listed_with_its_bid_cleared
        """
        ctx = fx.open_outing(api, outing=RETRACTED_OUTING)
        buyer = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Bidder Holdings", player_count=4
        )
        fx.pay_registration(api, buyer["id"], 120000)
        item = fx.new_item(api, ctx["outing_id"], **AUCTION_LOT)
        assert item["status"] == "LISTED"
        assert item["void_count"] == 0

        sold = fx.sell_item(api, item["id"], buyer["id"], 60000)
        assert sold["status"] == "SOLD"
        assert sold["bid_cents"] == 60000
        assert sold["buyer_registration_id"] == buyer["id"]
        assert sold["collected_cents"] == 0
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 120000

        voided = validate_success(
            api.item_lifecycle(
                item["id"],
                f.item_lifecycle_payload("VOID", void_reason=VOID_REASON),
                TREASURER_HEADERS,
            )
        )
        assert voided["status"] == "VOID"
        assert voided["buyer_registration_id"] is None
        assert voided["bid_cents"] == 0
        assert voided["recorded_by_user_id"] is None
        assert voided["void_count"] == 1

        relisted = validate_success(
            api.item_lifecycle(item["id"], f.item_lifecycle_payload("RELIST"), TREASURER_HEADERS)
        )
        assert relisted["status"] == "LISTED"
        assert relisted["void_count"] == 1
        assert relisted["ask_cents"] == 40000
        assert relisted["bid_cents"] == 0
        assert relisted["buyer_registration_id"] is None

        validate_error(
            api.record_item_sale(
                item["id"], f.item_sale_payload(buyer["id"], 39999), TREASURER_HEADERS
            ),
            ApiErrorId.INSUFFICIENT_BID,
            402,
        )

        resold = fx.sell_item(api, item["id"], buyer["id"], 45000)
        assert resold["status"] == "SOLD"
        assert resold["bid_cents"] == 45000
        assert resold["void_count"] == 1
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 120000


class TestOpeningAContestThatRequiresInsurance:
    def test_the_ace_prize_stays_planned_until_the_policy_is_bound(self, api):
        """Two independent dimensions, and the lifecycle one is gated on the other.

        The prize sits exactly on the trigger, since "`requires_insurance` is true
        exactly when the `contest_type` is `HOLE_IN_ONE`" and "the
        `prize_value_cents` is at least 500000 cents".  Opening therefore
        "additionally requires that either `requires_insurance` is false or the
        insurance dimension already reads `BOUND`, otherwise
        `ERR_INSURANCE_NOT_BOUND`. That single rule is what stops a
        five-thousand-dollar ace prize from being advertised uninsured."  Binding
        touches money and nothing else: "Binding stamps `insurance_bound_at` from the
        logical clock, adds the premium to the outing's `insurance_cost_cents`, and
        recomputes the finance figures. It advances the contest's `version` without
        touching the lifecycle dimension at all".  With no revenue yet the fee stays
        away, because `admin_fee_pct` is "0 when `net_proceeds_before_fee_cents` is
        zero or negative".

        Design: Corner/state_machines/contest_requiring_insurance_cannot_open_until_the_policy_is_bound
        """
        ctx = fx.open_outing(api, outing=ACE_OUTING)
        contest = fx.new_contest(api, ctx["outing_id"], **ACE_CONTEST)
        assert contest["requires_insurance"] is True
        assert contest["status"] == "PLANNED"
        assert contest["insurance_status"] == "NONE"
        assert contest["insurance_bound_at"] is None

        validate_error(
            api.contest_status(
                contest["id"], f.contest_status_payload("OPEN"), DIRECTOR_HEADERS
            ),
            ApiErrorId.INSURANCE_NOT_BOUND,
            409,
        )
        assert fx.read_contest(api, contest["id"])["status"] == "PLANNED"

        bound = fx.bind_contest_insurance(api, contest["id"], **ACE_POLICY)
        assert bound["insurance_status"] == "BOUND"
        assert bound["status"] == "PLANNED"
        assert bound["insurance_premium_cents"] == 45000
        assert_instant_equals(bound["insurance_bound_at"], CLOCK_START_UTC)

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["insurance_cost_cents"] == 45000
        assert outing["direct_costs_cents"] == 45000
        assert outing["net_proceeds_before_fee_cents"] == -45000
        assert outing["admin_fee_pct"] == pytest.approx(0.0, abs=0.0001)
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -45000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)

        opened = fx.drive_contest(api, contest["id"], "OPEN")
        assert opened["status"] == "OPEN"
        assert opened["insurance_status"] == "BOUND"


BUBBLE_OUTING = {"name": "Bubble Up Open", "field_capacity_teams": 4}
BUBBLE_TIER = {
    "code": "SPONSOR1",
    "price_cents": 300000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
SHARED_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 5 tee sign",
    "hole_number": 5,
    "capacity": 2,
    "exclusive": False,
    "list_price_cents": 50000,
    "fulfillment_due_at": "2026-09-18T00:00:00Z",
}
WAIVER_REASON = "The second sign was never printed by the vendor"

DONATION_OUTING = {"name": "Donation Ledger Open", "field_capacity_teams": 4}
DONATION_APPEAL = {
    "item_type": "DONATION",
    "description": "Fund-a-need appeal",
    "fmv_cents": 0,
    "ask_cents": 0,
}
DONATION_INDEXES = (10.0, 14.0, 18.0, 22.0)


def _unit_shape(asset):
    """One unit's posture beside the three occupancy counters and the remainder."""
    return (
        asset["status"],
        asset["reserved_count"],
        asset["committed_count"],
        asset["fulfilled_count"],
        asset["remaining_capacity"],
    )


class TestAssetPostureWaitsForTheLastAllocation:
    def test_a_shared_sign_reaches_fulfilled_only_once_both_holders_are_terminal(self, api):
        """Two holders on one two-capacity unit, finishing down different branches.

        The posture is a derivation over counters: it reads "`COMMITTED` whenever
        `committed_count` is greater than zero; and `FULFILLED` when
        `committed_count` and `reserved_count` are both zero while `fulfilled_count`
        is greater than zero".  Verification is one of the two ways occupancy crosses
        over, since it "moves this allocation's occupancy from `committed_count` into
        `fulfilled_count` and re-derives the unit's posture, which reaches
        `FULFILLED` once no reserved or committed allocation remains on the unit and
        at least one fulfilled one does", and it is also the control point, because
        "Verifying is the segregation-of-duties point: the acting `X-User-ID` must
        differ from `artwork_approved_by_user_id`".  The waiver is the other way over
        and it is the only one that costs money: "the allocation's
        `fulfillment_credit_cents` is set to 0.60 of the unit's `list_price_cents`",
        while "Like verification, waiving moves the occupancy from `committed_count`
        into `fulfilled_count` and re-derives the unit's posture."

        Design: Corner/state_machines/asset_reaches_fulfilled_only_when_every_occupying_allocation_is_terminal
        """
        ctx = fx.open_outing(api, outing=BUBBLE_OUTING, tier=BUBBLE_TIER, sponsor_tier=True)
        asset = fx.new_asset(api, ctx["outing_id"], **SHARED_SIGN)
        assert _unit_shape(asset) == ("AVAILABLE", 0, 0, 0, 2)

        holders = []
        for buyer_name in ("Sponsor One Bank", "Sponsor Two Trust"):
            registration = fx.new_registration(
                api, ctx["outing_id"], ctx["tier_id"], buyer_name=buyer_name, player_count=1
            )
            fx.pay_registration(api, registration["id"], 300000)
            holders.append(fx.new_allocation(api, registration["id"], asset["id"], "UPSELL"))

        first, second = holders[0]["id"], holders[1]["id"]
        assert _unit_shape(fx.read_asset(api, asset["id"])) == ("RESERVED", 2, 0, 0, 0)

        fx.drive_fulfillment(api, first, "COMMIT")
        fx.drive_fulfillment(api, second, "COMMIT")
        committed = fx.read_asset(api, asset["id"])
        assert _unit_shape(committed) == ("COMMITTED", 0, 2, 0, 0)
        assert_inventory_conservation(committed)

        fx.drive_fulfillment(api, first, "APPROVE_ARTWORK", headers=SPONSORSHIP_HEADERS)
        fx.drive_fulfillment(api, first, "INSTALL")
        verified = fx.drive_fulfillment(api, first, "VERIFY", headers=SPONSORSHIP_ALT_HEADERS)
        assert verified["status"] == "VERIFIED"
        assert verified["artwork_approved_by_user_id"] == SPONSORSHIP_USER_ID
        assert verified["verified_by_user_id"] == SPONSORSHIP_ALT_USER_ID
        assert verified["verified_by_user_id"] != verified["artwork_approved_by_user_id"]

        midway = fx.read_asset(api, asset["id"])
        assert _unit_shape(midway) == ("COMMITTED", 0, 1, 1, 0)
        assert_inventory_conservation(midway)

        waived = fx.drive_fulfillment(api, second, "WAIVE", waived_reason=WAIVER_REASON)
        assert waived["status"] == "WAIVED"
        assert waived["fulfillment_credit_cents"] == 30000
        assert fx.read_allocation(api, first)["fulfillment_credit_cents"] == 0

        fulfilled = fx.read_asset(api, asset["id"])
        assert _unit_shape(fulfilled) == ("FULFILLED", 0, 0, 2, 0)
        assert_inventory_conservation(fulfilled)

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["gross_revenue_cents"] == 700000
        assert outing["fulfillment_credit_cents"] == 30000
        assert outing["proceeds_variant"] == "PROVISIONAL"
        assert_direct_costs(outing)
        assert_rollup_chain(outing)


class TestPayingAFundraisingItem:
    def test_the_collected_cash_enters_gross_revenue_and_reprices_the_fee(self, api):
        """The lot's cash is a third revenue stream, and it moves the whole rollup.

        Gross revenue is "the sum of three streams: the `amount_paid_cents` of every
        registration whose status is `CONFIRMED`, `AMENDED`, or `CHECKED_IN`", the
        recognized allocation prices, "plus the `collected_cents` of every
        fundraising item whose status is `PAID` or `RECEIPTED`", so an appeal
        contributes only once it is paid: "On acceptance `collected_cents` is set to
        that amount and added to the outing's `gross_revenue_cents`, and the rest of
        the rollup is recomputed."  An outright appeal has nothing to clear, since
        `ask_cents` is "the reserve an offer must reach, likewise defaulting to 0",
        and the recomputation reprices the fee on the new base, because
        "`admin_fee_cents` is then `admin_fee_pct` multiplied by
        `gross_revenue_cents`, rounded half up to whole cents".

        Design: Corner/state_machines/paying_a_fundraising_item_pushes_its_cash_into_the_outing_ledger
        """
        ctx = fx.open_outing(api, outing=DONATION_OUTING)
        reg = fx.confirmed_registration(
            api, ctx, players=DONATION_INDEXES, buyer_name="Donor Foursome"
        )

        before = fx.read_outing(api, ctx["outing_id"])
        assert before["gross_revenue_cents"] == 120000
        assert before["course_charge_cents"] == 38000
        assert before["direct_costs_cents"] == 38000
        assert before["net_proceeds_before_fee_cents"] == 82000
        assert before["admin_fee_cents"] == 6000
        assert before["net_proceeds_cents"] == 76000

        item = fx.new_item(api, ctx["outing_id"], **DONATION_APPEAL)
        sold = fx.sell_item(api, item["id"], reg["registration_id"], 50000)
        assert sold["status"] == "SOLD"
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 120000

        paid = fx.pay_item(api, item["id"], 50000)
        assert paid["status"] == "PAID"
        assert paid["collected_cents"] == 50000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["gross_revenue_cents"] == 170000
        assert outing["course_charge_cents"] == 38000
        assert outing["direct_costs_cents"] == 38000
        assert outing["net_proceeds_before_fee_cents"] == 132000
        assert outing["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert outing["admin_fee_cents"] == 8500
        assert outing["net_proceeds_cents"] == 123500
        assert_direct_costs(outing)
        assert_rollup_chain(outing)
