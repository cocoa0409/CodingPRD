"""The allocation ladder, the two temporal boundaries, and the remittance guards."""

import pytest

from test_helpers import (
    BENEFICIARY_HEADERS,
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_ALT_HEADERS,
    SPONSORSHIP_ALT_USER_ID,
    SPONSORSHIP_HEADERS,
    SPONSORSHIP_USER_ID,
    TREASURER_HEADERS,
    ApiErrorId,
    assert_direct_costs,
    assert_inventory_conservation,
    assert_rollup_chain,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

NO_GUARANTEE = {"guaranteed_player_count": 0}

GATES_OUTING = {
    "name": "Entitlement Gates Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
SIGN_TIER = {
    "code": "SPON_SIGN",
    "price_cents": 250000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 10,
    "entitled_asset_type": "HOLE_SIGN",
    "entitled_asset_count": 1,
}
SIGN_THREE = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 3 tee sign",
    "hole_number": 3,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 60000,
}
SIGN_FIVE = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 5 tee sign",
    "hole_number": 5,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 60000,
}
FREE_CART = {
    "asset_type": "CART",
    "label": "Cart wrap fleet A",
    "hole_number": None,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 0,
}
EXCLUSIVE_STATION = {
    "asset_type": "BEVERAGE_STATION",
    "label": "Turn beverage station",
    "hole_number": None,
    "capacity": 2,
    "exclusive": True,
    "list_price_cents": 80000,
}
EARLY_WINDOW = {
    "service_window_start": "2026-09-19T12:00:00Z",
    "service_window_end": "2026-09-19T13:00:00Z",
}
LATE_WINDOW = {
    "service_window_start": "2026-09-19T15:00:00Z",
    "service_window_end": "2026-09-19T16:00:00Z",
}


class TestAllocationGates:
    def _one_sponsor_and_four_units(self, api):
        ctx = fx.open_outing(
            api, contract=NO_GUARANTEE, tier=SIGN_TIER, outing=GATES_OUTING, sponsor_tier=True
        )
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Ridgeline Insurance",
            player_count=0,
        )
        fx.pay_registration(api, registration["id"], 250000)
        ctx["registration_id"] = registration["id"]
        ctx["sign3_id"] = fx.new_asset(api, ctx["outing_id"], **SIGN_THREE)["id"]
        ctx["sign5_id"] = fx.new_asset(api, ctx["outing_id"], **SIGN_FIVE)["id"]
        ctx["cart_id"] = fx.new_asset(api, ctx["outing_id"], **FREE_CART)["id"]
        ctx["station_id"] = fx.new_asset(api, ctx["outing_id"], **EXCLUSIVE_STATION)["id"]
        return ctx

    def test_the_entitled_type_and_then_the_exhausted_balance_refuse_the_draw(self, api):
        """The first two rungs of the allocation ladder fire in order. "an allocation created
        with `source` `PACKAGE_ENTITLEMENT` must target a unit whose `asset_type` equals
        the held tier's `entitled_asset_type`, otherwise `ERR_ASSET_TYPE_MISMATCH`", so a
        beverage station cannot be drawn against a hole-sign entitlement even with a
        balance of one.  Then "an entitlement allocation requires the registration's
        `entitled_asset_balance` to be at least 1", and the accepted draw leaves that
        balance at 0, so the second entitlement draw reports
        `ERR_ALLOCATION_NOT_ENTITLED` with the type matching this time.

        Design: Corner/validations/entitlement_type_balance_price_and_exclusivity_gates_each_refuse_an_allocation
        """
        ctx = self._one_sponsor_and_four_units(api)

        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"], ctx["station_id"], "PACKAGE_ENTITLEMENT",
                    **EARLY_WINDOW,
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.ASSET_TYPE_MISMATCH,
            409,
        )
        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 1

        drawn = fx.new_allocation(api, ctx["registration_id"], ctx["sign3_id"])
        assert drawn["source"] == "PACKAGE_ENTITLEMENT"
        assert drawn["upsell_price_cents"] == 0
        assert drawn["status"] == "RESERVED"
        assert fx.read_registration(api, ctx["registration_id"])["entitled_asset_balance"] == 0

        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"], ctx["sign5_id"], "PACKAGE_ENTITLEMENT"
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.ALLOCATION_NOT_ENTITLED,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 1

    def test_a_free_unit_an_exclusive_unit_and_an_occupied_unit_are_each_refused(self, api):
        """An upsell has its own price gate: "an upsell allocation requires the unit to carry
        a positive `list_price_cents` and consumes no balance at all; either failure is
        `ERR_ALLOCATION_NOT_ENTITLED`", so the cart listed at zero is refused.
        Exclusivity is later and narrower: "a unit flagged `exclusive` accepts at most one
        non-released allocation regardless of the `capacity` it declares, so a second
        attempt is refused with `ERR_EXCLUSIVE_ASSET_CONFLICT`" - the station still has a
        free slot and the two padded windows do not touch, so nothing else can have fired.
        Withdrawal is stricter still: it "requires that `reserved_count`,
        `committed_count`, and `fulfilled_count` all read zero; a unit with any occupancy
        at all is refused with `ERR_ASSET_OCCUPIED`".

        Design: Corner/validations/entitlement_type_balance_price_and_exclusivity_gates_each_refuse_an_allocation
        """
        ctx = self._one_sponsor_and_four_units(api)
        fx.new_allocation(api, ctx["registration_id"], ctx["sign3_id"])

        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"], ctx["cart_id"], "UPSELL", **EARLY_WINDOW
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.ALLOCATION_NOT_ENTITLED,
            409,
        )

        upsell = fx.new_allocation(
            api, ctx["registration_id"], ctx["station_id"], "UPSELL", **EARLY_WINDOW
        )
        assert upsell["upsell_price_cents"] == 80000
        station = fx.read_asset(api, ctx["station_id"])
        assert station["reserved_count"] == 1
        assert station["remaining_capacity"] == 1
        assert_inventory_conservation(station)

        validate_error(
            api.create_sponsor_allocation(
                f.sponsor_allocation_payload(
                    ctx["registration_id"], ctx["station_id"], "UPSELL", **LATE_WINDOW
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.EXCLUSIVE_ASSET_CONFLICT,
            409,
        )

        validate_error(
            api.asset_inventory(
                ctx["sign3_id"], f.inventory_payload("WITHDRAW"), SPONSORSHIP_HEADERS
            ),
            ApiErrorId.ASSET_OCCUPIED,
            409,
        )
        sign = fx.read_asset(api, ctx["sign3_id"])
        assert sign["status"] == "RESERVED"
        assert sign["remaining_capacity"] == 0
        assert fx.read_outing(api, ctx["outing_id"])["reserved_asset_slot_count"] == 2


DEADLINE_OUTING = {
    "name": "Fulfillment Deadline Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
PLAIN_SPONSOR_TIER = {
    "code": "SPON_PLAIN",
    "price_cents": 250000,
    "player_slots": 0,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
DEADLINE_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 7 tee sign",
    "hole_number": 7,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 60000,
    "fulfillment_due_at": "2026-09-10T00:00:00Z",
}
ON_THE_DEADLINE = "2026-09-10T00:00:00Z"
ONE_SECOND_LATE = "2026-09-10T00:00:01Z"
ONE_SECOND_EARLY = "2026-09-09T23:59:59Z"


class TestFulfillmentDeadlineAndSegregationOfDuties:
    def _one_committed_upsell(self, api):
        ctx = fx.open_outing(
            api, contract=NO_GUARANTEE, tier=PLAIN_SPONSOR_TIER, outing=DEADLINE_OUTING,
            sponsor_tier=True,
        )
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Ridgeline Insurance",
            player_count=0,
        )
        fx.pay_registration(api, registration["id"], 250000)
        ctx["asset_id"] = fx.new_asset(api, ctx["outing_id"], **DEADLINE_SIGN)["id"]
        allocation = fx.new_allocation(
            api, registration["id"], ctx["asset_id"], "UPSELL"
        )
        ctx["allocation_id"] = allocation["id"]
        fx.drive_fulfillment(api, allocation["id"], "COMMIT", headers=SPONSORSHIP_HEADERS)
        return ctx

    def test_approval_exactly_on_the_deadline_is_accepted(self, api):
        """The deadline comparison is inclusive on the deadline instant: approval and
        verification "are subject to the unit's `fulfillment_due_at`: they must be
        performed at or before that instant as read from the logical clock, and a later
        attempt is refused with `ERR_FULFILLMENT_WINDOW_ELAPSED`".  The approval also
        records the approver, because "Approving the artwork records the approving user's
        `X-User-ID` as `artwork_approved_by_user_id`", and installation is simply "a bare
        acknowledgement that the sign went up".

        Design: Corner/validations/the_fulfillment_deadline_is_inclusive_and_yields_to_the_segregation_of_duties_check
        """
        ctx = self._one_committed_upsell(api)
        fx.set_clock(api, ON_THE_DEADLINE)

        approved = fx.drive_fulfillment(
            api, ctx["allocation_id"], "APPROVE_ARTWORK", headers=SPONSORSHIP_HEADERS
        )
        assert approved["status"] == "ARTWORK_APPROVED"
        assert approved["artwork_approved_by_user_id"] == SPONSORSHIP_USER_ID

        installed = fx.drive_fulfillment(
            api, ctx["allocation_id"], "INSTALL", headers=SPONSORSHIP_HEADERS
        )
        assert installed["status"] == "INSTALLED"

    def test_the_duties_check_is_reported_before_the_elapsed_window(self, api):
        """One request breaks two rules and the safety sub-tier answers first. The PRD puts
        "segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)" in the safety sub-tier while
        "the fulfillment deadline (`ERR_FULFILLMENT_WINDOW_ELAPSED`)" sits in the temporal
        sub-tier, and the ladder runs "**safety** first, then **referential**, then
        **temporal**".  So past the deadline the approver's own attempt reports the duties
        error, a different user finally surfaces the window error, and back inside the
        window that user's verification lands - "the acting `X-User-ID` must differ from
        `artwork_approved_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`, and on
        success the acting user is recorded as `verified_by_user_id`".

        Design: Corner/validations/the_fulfillment_deadline_is_inclusive_and_yields_to_the_segregation_of_duties_check
        """
        ctx = self._one_committed_upsell(api)
        fx.set_clock(api, ON_THE_DEADLINE)
        fx.drive_fulfillment(
            api, ctx["allocation_id"], "APPROVE_ARTWORK", headers=SPONSORSHIP_HEADERS
        )
        fx.drive_fulfillment(api, ctx["allocation_id"], "INSTALL", headers=SPONSORSHIP_HEADERS)

        fx.set_clock(api, ONE_SECOND_LATE)
        validate_error(
            api.allocation_fulfillment(
                ctx["allocation_id"], f.fulfillment_payload("VERIFY"), SPONSORSHIP_HEADERS
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api.allocation_fulfillment(
                ctx["allocation_id"], f.fulfillment_payload("VERIFY"), SPONSORSHIP_ALT_HEADERS
            ),
            ApiErrorId.FULFILLMENT_WINDOW_ELAPSED,
            409,
        )

        fx.set_clock(api, ONE_SECOND_EARLY)
        verified = fx.drive_fulfillment(
            api, ctx["allocation_id"], "VERIFY", headers=SPONSORSHIP_ALT_HEADERS
        )
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by_user_id"] == SPONSORSHIP_ALT_USER_ID

        asset = fx.read_asset(api, ctx["asset_id"])
        assert asset["fulfilled_count"] == 1
        assert asset["committed_count"] == 0
        assert asset["remaining_capacity"] == 0
        assert asset["status"] == "FULFILLED"
        assert_inventory_conservation(asset)


NOTICE_ONE = {"name": "Notice Boundary One", "field_capacity_teams": 4, "prize_pool_cents": 0}
NOTICE_TWO = {
    "name": "Notice Boundary Two",
    "beneficiary_name": "Southside Literacy Trust",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
NOTICE_CONTRACT = {"guaranteed_player_count": 0, "cancellation_notice_days": 30}
SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
NOTICE_BOUNDARY = "2026-08-20T12:00:00Z"
JUST_INSIDE_THE_NOTICE = "2026-08-20T11:59:59Z"
WELL_INSIDE_THE_WINDOW = "2026-09-01T00:00:00Z"
VOID_REASON = {"void_reason": "Course lost its liquor licence"}


class TestContractVoidNoticeBoundary:
    def _unsold_open_outing(self, api):
        return fx.open_outing(api, contract=NOTICE_CONTRACT, tier=SOLO_TIER, outing=NOTICE_ONE)

    def test_the_boundary_instant_is_already_too_late_and_one_second_earlier_voids(self, api):
        """The notice test is strict on the boundary. Voiding a signed contract requires that
        "the logical clock must be strictly earlier than the outing's `scheduled_date`
        minus `cancellation_notice_days` whole days, and a void attempted at or inside that
        notice window is refused with `ERR_CANCELLATION_NOTICE_VIOLATION`".  One second
        earlier the void lands, and it takes the outing with it: "When a signed contract is
        voided the outing loses its venue, so an outing whose play dimension is `DRAFT` or
        `OPEN` is moved to `CANCELLED` by the same request."

        Design: Corner/validations/a_contract_void_exactly_on_the_notice_boundary_is_refused_and_a_sold_field_outranks_it
        """
        ctx = self._unsold_open_outing(api)
        fx.set_clock(api, NOTICE_BOUNDARY)

        validate_error(
            api.contract_lifecycle(
                ctx["contract_id"],
                f.contract_lifecycle_payload("VOID", **VOID_REASON),
                COURSE_HEADERS,
            ),
            ApiErrorId.CANCELLATION_NOTICE_VIOLATION,
            409,
        )
        assert fx.read_contract(api, ctx["contract_id"])["status"] == "SIGNED"
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"

        fx.set_clock(api, JUST_INSIDE_THE_NOTICE)
        voided = validate_success(
            api.contract_lifecycle(
                ctx["contract_id"],
                f.contract_lifecycle_payload("VOID", **VOID_REASON),
                COURSE_HEADERS,
            )
        )
        assert voided["status"] == "VOIDED"
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "CANCELLED"

    def test_a_sold_package_reports_the_state_error_instead_of_the_notice_error(self, api):
        """The state precondition sits above every business rule, and a sold field trips it:
        the void requires that "no registration of the outing may be sitting at
        `CONFIRMED`, `AMENDED`, or `CHECKED_IN`; if one is, the void is refused with
        `ERR_INVALID_STATE_TRANSITION`".  Because the ladder places "**State
        precondition**" above the business rules that hold the cancellation notice, a
        clock deep inside the notice window never gets to speak.

        Design: Corner/validations/a_contract_void_exactly_on_the_notice_boundary_is_refused_and_a_sold_field_outranks_it
        """
        ctx = fx.open_outing(api, contract=NOTICE_CONTRACT, tier=SOLO_TIER, outing=NOTICE_TWO)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Sold Package Buyer",
            player_count=1,
        )
        fx.pay_registration(api, registration["id"], 30000)
        fx.set_clock(api, WELL_INSIDE_THE_WINDOW)

        validate_error(
            api.contract_lifecycle(
                ctx["contract_id"],
                f.contract_lifecycle_payload("VOID", **VOID_REASON),
                COURSE_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        assert fx.read_contract(api, ctx["contract_id"])["status"] == "SIGNED"
        assert fx.read_registration(api, registration["id"])["status"] == "CONFIRMED"
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"


REFUND_OUTING = {"name": "Refund Ceiling Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
REFUND_CONTRACT = {"guaranteed_player_count": 0, "cancellation_notice_days": 30}


class TestRefundCeilingMovesWithTheClock:
    def _two_paid_foursomes(self, api):
        ctx = fx.open_outing(api, contract=REFUND_CONTRACT, outing=REFUND_OUTING)
        early = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Early Canceller", player_count=4
        )
        fx.pay_registration(api, early["id"], 120000)
        late = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Late Canceller", player_count=4
        )
        fx.pay_registration(api, late["id"], 120000)
        ctx["early_id"] = early["id"]
        ctx["late_id"] = late["id"]
        return ctx

    def test_one_cent_above_the_payment_is_refused_and_the_full_amount_is_available(self, api):
        """Outside the notice window the whole payment is refundable. "No refund may push
        `amount_refunded_cents` above `amount_paid_cents` minus the retained
        late-cancellation fee; an attempt is refused with `ERR_REFUND_EXCEEDS_PAYMENT`",
        and "Outside the notice window `late_cancel_fee_cents` stays 0 and the refund is
        the whole of `amount_paid_cents`."  A positive refund also advances the row, since
        "when the refund is greater than zero the row auto-advances one further step,
        `CANCELLED → REFUNDED`, in the same request".

        Design: Corner/validations/a_refund_may_not_exceed_the_payment_net_of_the_retained_late_cancellation_fee
        """
        ctx = self._two_paid_foursomes(api)

        validate_error(
            api.registration_lifecycle(
                ctx["early_id"],
                f.registration_lifecycle_payload("CANCEL", refund_cents=120001),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.REFUND_EXCEEDS_PAYMENT,
            409,
        )
        untouched = fx.read_registration(api, ctx["early_id"])
        assert untouched["status"] == "CONFIRMED"
        assert untouched["amount_refunded_cents"] == 0

        refunded = validate_success(
            api.registration_lifecycle(
                ctx["early_id"],
                f.registration_lifecycle_payload("CANCEL", refund_cents=100000),
                DIRECTOR_HEADERS,
            )
        )
        assert refunded["late_cancel_fee_cents"] == 0
        assert refunded["amount_refunded_cents"] == 100000
        assert refunded["status"] == "REFUNDED"

    def test_inside_the_window_the_retained_fee_lowers_the_very_same_ceiling(self, api):
        """The ceiling moves with the clock. "When the logical clock is at or after the
        outing's `scheduled_date` minus the contract's `cancellation_notice_days` whole
        days, the organizer retains a quarter of what was paid: `late_cancel_fee_cents` is
        set to `amount_paid_cents` multiplied by 0.25 and rounded half up to whole cents,
        and the refund is `amount_paid_cents` minus that retained fee."  So the identical
        100000 figure that was legal a moment earlier now breaks the ceiling, the refused
        call retains nothing, and the plain cancellation pays the reduced balance.

        Design: Corner/validations/a_refund_may_not_exceed_the_payment_net_of_the_retained_late_cancellation_fee
        """
        ctx = self._two_paid_foursomes(api)
        validate_success(
            api.registration_lifecycle(
                ctx["early_id"],
                f.registration_lifecycle_payload("CANCEL", refund_cents=100000),
                DIRECTOR_HEADERS,
            )
        )
        fx.set_clock(api, WELL_INSIDE_THE_WINDOW)

        validate_error(
            api.registration_lifecycle(
                ctx["late_id"],
                f.registration_lifecycle_payload("CANCEL", refund_cents=100000),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.REFUND_EXCEEDS_PAYMENT,
            409,
        )
        held = fx.read_registration(api, ctx["late_id"])
        assert held["status"] == "CONFIRMED"
        assert held["amount_refunded_cents"] == 0
        assert held["late_cancel_fee_cents"] == 0

        cancelled = validate_success(
            api.registration_lifecycle(
                ctx["late_id"], f.registration_lifecycle_payload("CANCEL"), DIRECTOR_HEADERS
            )
        )
        assert cancelled["late_cancel_fee_cents"] == 30000
        assert cancelled["amount_refunded_cents"] == 90000
        assert cancelled["status"] == "REFUNDED"

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["refunded_cents"] == 190000
        assert outing["gross_revenue_cents"] == 0
        assert outing["confirmed_player_slots"] == 0
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -190000
        assert_rollup_chain(outing)


FUNDING_OUTING = {
    "name": "Prize Funding Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 160000,
}
FLAT_CONTRACT = {
    "guaranteed_player_count": 0,
    "slope_rating": 113,
    "course_rating": 72.0,
    "par": 72,
}
FUNDING_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Hole 9 tee sign",
    "hole_number": 9,
    "capacity": 1,
    "exclusive": False,
    "list_price_cents": 60000,
}
FUNDING_CARD = {
    "gross_score": 74,
    "gross_back_9": 37,
    "gross_back_6": 25,
    "gross_back_3": 12,
    "gross_hole_18": 4,
}
FUNDING_NAMES = ("Funding One", "Funding Two", "Funding Three", "Funding Four")


class TestPrizePoolFundingIsAnAggregateCheck:
    def _a_scored_card_on_an_underfunded_pool(self, api):
        ctx = fx.open_outing(api, contract=FLAT_CONTRACT, outing=FUNDING_OUTING)
        reg = fx.confirmed_registration(
            api, ctx, players=(12.0, 12.0, 12.0, 12.0),
            buyer_name="Prize Funding Buyer", names=list(FUNDING_NAMES),
        )
        asset = fx.new_asset(api, ctx["outing_id"], **FUNDING_SIGN)
        ctx["allocation_id"] = fx.new_allocation(
            api, reg["registration_id"], asset["id"], "UPSELL"
        )["id"]
        team = fx.new_team(
            api, ctx["outing_id"], reg["player_ids"], team_name="Funding Foursome"
        )
        ctx["team_id"] = team["id"]
        fx.assign_tee(api, team["id"], wave="A", starting_hole=1, cart_number=1)
        fx.lock_field(api, ctx["outing_id"])
        fx.start_play(api, ctx["outing_id"])
        fx.post_score(api, team["id"], **FUNDING_CARD)
        return ctx

    def test_the_finalization_is_refused_while_the_pool_outruns_live_revenue(self, api):
        """The funding rule is an aggregate test made at finalization, not at budgeting time:
        "the outing's `prize_pool_cents` plus the sum of the settled `contest_payout_cents`
        across its contests may not exceed `gross_revenue_cents` minus `refunded_cents`.
        If it does, the finalization is refused with `ERR_PRIZE_POOL_UNFUNDED` even though
        every single prize was within its own limit."  Nothing is written by the refusal,
        so no ranking appears.

        Design: Corner/validations/an_underfunded_prize_pool_blocks_scoring_until_an_upsell_commit_raises_gross_revenue
        """
        ctx = self._a_scored_card_on_an_underfunded_pool(api)

        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("FINALIZE_SCORING"), DIRECTOR_HEADERS
            ),
            ApiErrorId.PRIZE_POOL_UNFUNDED,
            409,
        )

        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "IN_PLAY"
        team = fx.read_team(api, ctx["team_id"])
        assert team["rank_position"] is None
        assert team["prize_award_cents"] == 0

    def test_a_mid_round_commitment_recognizes_the_revenue_the_rule_needs(self, api):
        """A commitment is the one revenue event still available mid-round: an allocation's
        `upsell_price_cents` "is not yet revenue" and "it becomes recognized revenue only
        from the commitment step onward".  With gross revenue lifted the same transition is
        accepted, "The first eligible team's `prize_award_cents` is 0.50 of
        `prize_pool_cents` rounded half up to whole cents", and the rest of the pool lands
        in "`unclaimed_prize_cents`, computed as `prize_pool_cents` minus the sum of
        `prize_award_cents` across all teams".  Under the provisional treatment
        "`prize_cost_cents` is the full `prize_pool_cents` plus the sum of
        `contest_payout_cents` across the outing's contests".

        Design: Corner/validations/an_underfunded_prize_pool_blocks_scoring_until_an_upsell_commit_raises_gross_revenue
        """
        ctx = self._a_scored_card_on_an_underfunded_pool(api)
        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("FINALIZE_SCORING"), DIRECTOR_HEADERS
            ),
            ApiErrorId.PRIZE_POOL_UNFUNDED,
            409,
        )

        committed = fx.drive_fulfillment(api, ctx["allocation_id"], "COMMIT")
        assert committed["status"] == "COMMITTED"
        assert committed["upsell_price_cents"] == 60000
        assert fx.read_outing(api, ctx["outing_id"])["gross_revenue_cents"] == 180000

        scored = fx.finalize_scoring(api, ctx["outing_id"])
        assert scored["play_status"] == "SCORED"

        team = fx.read_team(api, ctx["team_id"])
        assert team["rank_position"] == 1
        assert team["prize_eligible"] is True
        assert team["prize_award_cents"] == 80000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["unclaimed_prize_cents"] == 80000
        assert outing["course_charge_cents"] == 38000
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["prize_cost_cents"] == 160000
        assert outing["direct_costs_cents"] == 198000
        assert outing["net_proceeds_before_fee_cents"] == -18000
        assert outing["admin_fee_pct"] == pytest.approx(0.0, abs=0.0001)
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -18000
        assert_direct_costs(outing)
        assert_rollup_chain(outing)


SETTLEMENT_OUTING = {"name": "Remittance Settlement", "field_capacity_teams": 4}
SETTLEMENT_CARD = {
    "gross_score": 74,
    "gross_back_9": 37,
    "gross_back_6": 25,
    "gross_back_3": 12,
    "gross_hole_18": 4,
}
FIRST_REFERENCE = "ACH-2026-0919-01"
SECOND_REFERENCE = "ACH-2026-0919-02"


class TestRemittanceMustMatchTheFinalNet:
    def _a_reconciled_receipted_outing(self, api):
        return fx.remit_ready_outing(
            api,
            handicap_indexes=(12.0, 12.0, 12.0, 12.0),
            outing=SETTLEMENT_OUTING,
            contract=FLAT_CONTRACT,
            score=SETTLEMENT_CARD,
        )

    def test_a_remittance_one_cent_high_is_refused_and_freezes_nothing(self, api):
        """The comparison is exact: "The supplied `remittance_cents` must equal the
        final-treatment `net_proceeds_cents` to the cent, otherwise
        `ERR_REMITTANCE_AMOUNT_MISMATCH` (HTTP 402)."  The setup receipt shows the token
        rule was never reached, because "only a benefit strictly above the ceiling is
        carried through at its declared value", and the refusal leaves the frozen fields
        untouched - freezing happens only "On acceptance".

        Design: Corner/validations/remittance_must_equal_the_final_net_proceeds_to_the_cent_before_the_outing_disburses
        """
        ctx = self._a_reconciled_receipted_outing(api)
        assert ctx["receipt"]["payment_cents"] == 120000
        assert ctx["receipt"]["gsv_cents"] == 24000
        assert ctx["receipt"]["deductible_amount_cents"] == 96000

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["proceeds_variant"] == "FINAL"
        assert outing["net_proceeds_cents"] == 76000

        validate_error(
            api.finance_transition(
                ctx["outing_id"],
                f.remit_payload(outing["version"], 76001, FIRST_REFERENCE),
                TREASURER_HEADERS,
            ),
            ApiErrorId.REMITTANCE_AMOUNT_MISMATCH,
            402,
        )

        after = fx.read_outing(api, ctx["outing_id"])
        assert after["finance_status"] == "RECONCILED"
        assert after["beneficiary_remittance_cents"] == 0
        assert after["remittance_reference"] is None

    def test_the_exact_figure_disburses_settles_the_course_and_is_terminal(self, api):
        """Acceptance freezes three things at once. "`beneficiary_remittance_cents` is set to
        the outing's `net_proceeds_cents` at that instant and `remittance_reference`
        records the supplied payment reference", and "the outing's contract moves to
        `SETTLED` from either `SIGNED` or `AMENDED` with identical effect, and its
        `settled_charge_cents` is frozen as the outing's `course_charge_cents` plus its
        `fnb_shortfall_cents` less the contract's `rain_credit_cents`".  Because the
        transition is "`RECONCILED → DISBURSED`, which is terminal", the replay is refused
        on the state machine rather than on the amount.

        Design: Corner/validations/remittance_must_equal_the_final_net_proceeds_to_the_cent_before_the_outing_disburses
        """
        ctx = self._a_reconciled_receipted_outing(api)

        disbursed = fx.remit(api, ctx["outing_id"], 76000, reference=FIRST_REFERENCE)
        assert disbursed["finance_status"] == "DISBURSED"
        assert disbursed["beneficiary_remittance_cents"] == 76000
        assert disbursed["remittance_reference"] == FIRST_REFERENCE

        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["status"] == "SETTLED"
        assert contract["settled_charge_cents"] == 38000

        validate_error(
            api.finance_transition(
                ctx["outing_id"],
                f.remit_payload(disbursed["version"], 76000, SECOND_REFERENCE),
                TREASURER_HEADERS,
            ),
            ApiErrorId.INVALID_STATE_TRANSITION,
            409,
        )
        assert fx.read_outing(api, ctx["outing_id"])["remittance_reference"] == FIRST_REFERENCE

        report = validate_success(api.get_proceeds_report(ctx["outing_id"], BENEFICIARY_HEADERS))
        assert report["proceeds_variant"] == "FINAL"
        assert report["gross_revenue_cents"] == 120000
        assert report["refunded_cents"] == 0
        assert report["course_charge_cents"] == 38000
        assert report["fnb_shortfall_cents"] == 0
        assert report["prize_cost_cents"] == 0
        assert report["direct_costs_cents"] == 38000
        assert report["net_proceeds_before_fee_cents"] == 82000
        assert report["admin_fee_pct"] == pytest.approx(0.05, abs=0.0001)
        assert report["admin_fee_cents"] == 6000
        assert report["net_proceeds_cents"] == 76000


LOSS_OUTING = {"name": "Loss Making Outing", "field_capacity_teams": 4, "prize_pool_cents": 0}
GUARANTEE_72 = {
    "rate_per_player_cents": 9500,
    "guaranteed_player_count": 72,
    "fnb_minimum_cents": 0,
    "slope_rating": 113,
    "course_rating": 72.0,
    "par": 72,
}
LOSS_NAMES = ("Thin One", "Thin Two", "Thin Three", "Thin Four")
LOSS_REFERENCE = "ACH-LOSS-01"


class TestTheFourRemitConditionsPeelOffInOrder:
    def _a_reconciled_loss_holding_a_stale_version(self, api):
        ctx = fx.locked_field_outing(
            api,
            handicap_indexes=(12.0, 12.0, 12.0, 12.0),
            outing=LOSS_OUTING,
            contract=GUARANTEE_72,
        )
        fx.assign_tee(api, ctx["team_id"])
        validate_success(
            api.registration_lifecycle(
                ctx["registration_id"], f.registration_lifecycle_payload("CHECK_IN"),
                COURSE_HEADERS,
            )
        )
        fx.start_play(api, ctx["outing_id"])
        fx.post_score(api, ctx["team_id"], **SETTLEMENT_CARD)
        finalized = fx.finalize_scoring(api, ctx["outing_id"])
        ctx["stale_version"] = finalized["version"]
        ctx["outing"] = fx.reconcile(api, ctx["outing_id"])
        return ctx

    def test_the_guarantee_floor_produces_a_final_loss_with_no_admin_fee(self, api):
        """A thin turnout still pays the promise: "`course_charge_cents` is the larger of the
        billable player count and the contract's `guaranteed_player_count`, multiplied by
        the contract's `rate_per_player_cents`. The guarantee is a floor, so a poorly
        attended outing still pays for the players it promised."  The fee tier then
        collapses, because "`admin_fee_pct` is 0 when `net_proceeds_before_fee_cents` is
        zero or negative".

        Design: Corner/validations/unreceipted_items_outrank_the_stale_version_and_the_negative_net_at_remit
        """
        ctx = self._a_reconciled_loss_holding_a_stale_version(api)
        outing = ctx["outing"]

        assert outing["proceeds_variant"] == "FINAL"
        assert outing["gross_revenue_cents"] == 120000
        assert outing["course_charge_cents"] == 684000
        assert outing["fnb_shortfall_cents"] == 0
        assert outing["direct_costs_cents"] == 684000
        assert outing["net_proceeds_before_fee_cents"] == -564000
        assert outing["admin_fee_pct"] == pytest.approx(0.0, abs=0.0001)
        assert outing["admin_fee_cents"] == 0
        assert outing["net_proceeds_cents"] == -564000
        assert_rollup_chain(outing)

    def test_receipts_then_the_version_guard_then_the_loss_are_reported_in_turn(self, api):
        """One unchanged request is refused three different ways as each rung is cleared.
        "Every registration of the outing whose status is `CONFIRMED`, `AMENDED`, or
        `CHECKED_IN` must have `receipt_issued` true, and every fundraising item of the
        outing sitting at `PAID` must have been receipted; an outstanding receipt anywhere
        refuses the remittance with `ERR_UNRECEIPTED_ITEMS_REMAIN`" - reported first even
        though the held version is already stale and the net is already negative.  With
        the receipt filed, "A mismatch with the outing's current `version` is rejected with
        `ERR_STALE_OUTING_VERSION` (HTTP 412)".  On a fresh version the fiscal sub-tier
        speaks in its declared order, "non-negative net proceeds
        (`ERR_NEGATIVE_NET_PROCEEDS`), and remittance matching
        (`ERR_REMITTANCE_AMOUNT_MISMATCH`), in that order", so the mismatched figure 0 is
        never reported: "The outing's `net_proceeds_cents` must be strictly greater than
        zero, otherwise `ERR_NEGATIVE_NET_PROCEEDS`".

        Design: Corner/validations/unreceipted_items_outrank_the_stale_version_and_the_negative_net_at_remit
        """
        ctx = self._a_reconciled_loss_holding_a_stale_version(api)
        stale = ctx["stale_version"]

        # The PRD names both outcomes for this request without pinning their
        # relative order: §3.9 lists the unreceipted-items condition first
        # among the four remit conditions, while §2.6 places optimistic
        # concurrency at tier 11 above every tier-12 business rule.  Either
        # reading is faithful, so both identifiers are accepted here.
        validate_error_is_one_of(
            api.finance_transition(
                ctx["outing_id"], f.remit_payload(stale, 0, LOSS_REFERENCE), TREASURER_HEADERS
            ),
            [
                ApiErrorId.UNRECEIPTED_ITEMS_REMAIN.value,
                ApiErrorId.STALE_OUTING_VERSION.value,
            ],
        )

        receipt = fx.issue_registration_receipt(
            api, ctx["outing_id"], ctx["registration_id"]
        )
        assert receipt["deductible_amount_cents"] == 96000
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is True

        validate_error(
            api.finance_transition(
                ctx["outing_id"], f.remit_payload(stale, 0, LOSS_REFERENCE), TREASURER_HEADERS
            ),
            ApiErrorId.STALE_OUTING_VERSION,
            412,
        )

        fresh = fx.outing_version(api, ctx["outing_id"])
        assert fresh != stale
        validate_error(
            api.finance_transition(
                ctx["outing_id"], f.remit_payload(fresh, 0, LOSS_REFERENCE), TREASURER_HEADERS
            ),
            ApiErrorId.NEGATIVE_NET_PROCEEDS,
            409,
        )

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["finance_status"] == "RECONCILED"
        assert outing["beneficiary_remittance_cents"] == 0
        assert outing["remittance_reference"] is None
        contract = fx.read_contract(api, ctx["contract_id"])
        assert contract["status"] == "SIGNED"
        assert contract["settled_charge_cents"] == 0
