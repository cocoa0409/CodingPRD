"""Multi-stage arithmetic where the order of the stages changes the answer.

Three of this service's formulas are compositions rather than single
expressions: the repurchase allocation (capacity, then the hardship tier, then a
floored pro rata with a one-cent leftover pass), the subscription load (two
independently rounded lines, then a sum), and the monthly trail fee (a capped
instalment booked first, then a class conversion). Each scenario below is dialled
so that performing the stages in a different order, or collapsing two of them
into one, lands on a visibly different figure.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    SPONSOR,
    TRANSFER_AGENT,
    ApiClient,
    ApiErrorId,
    ClassCode,
    DeclarationStatus,
    HardshipType,
    RepurchasePeriodStatus,
    RepurchaseRequestStatus,
    SubscriptionStatus,
    assert_created,
    assert_error,
    assert_fields,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld

_HARBORLINE_HOLDERS = (
    ("Avery Nolan", "avery.nolan@example.com", "SUIT-A-2026-08"),
    ("Blake Ortiz", "blake.ortiz@example.com", "SUIT-B-2026-08"),
    ("Casey Rivera", "casey.rivera@example.com", "SUIT-C-2026-08"),
)


def _harborline_with_three_equal_holders(world: ReitWorld) -> dict:
    """Aggregate valuation of 30,000,000 cents split across three 100,000,000 e4 lots.

    The three lots are all minted by the escrow break at the boot instant of the
    logical clock, so each is 60 days old at the September settlement date and
    every one of them is inside the early-repurchase window of PRD §3.8.
    """
    offering = world.offering(
        name="Harborline Diversified REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    share_class = world.share_class(
        offering["id"],
        class_code=ClassCode.I,
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(
        firm_name="Keystone Advisory Group", crd_number="CRD-200001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    holders = []
    for legal_name, email, reference in _HARBORLINE_HOLDERS:
        holder = world.investor(
            legal_name=legal_name,
            email=email,
            state_code="TX",
            net_worth_cents=2000000000,
            annual_income_cents=400000000,
        )
        world.document_suitability(holder["id"], reference)
        holders.append(holder)

    for holder in holders:
        subscription = world.subscription(
            offering["id"],
            share_class["id"],
            holder["id"],
            agreement["id"],
            10000000,
        )
        world.escrow_subscription(subscription["id"])

    world.break_escrow(offering["id"])
    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    world.published_nav(
        share_class["id"], "2026-08-01", "2026-08-31", 30900000, 900000, "IVA-2026-08-I"
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investors": holders,
    }


def _september_period_with_three_tenders(world: ReitWorld, tenders: list) -> dict:
    """Open the September window, file the given tenders in order, then close it.

    ``tenders`` is a list of ``(holder index, shares_requested_e4, hardship_type)``
    filed in the order given, which is the ``created_at`` order the waterfall of
    PRD §3.8 walks.
    """
    scene = _harborline_with_three_equal_holders(world)
    period = world.repurchase_period(
        scene["offering_id"],
        period_month="2026-09",
        opens_at="2026-09-03T00:00:00Z",
        request_cutoff_at="2026-09-25T00:00:00Z",
        settlement_date="2026-09-30",
    )
    world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)

    filed = []
    for holder_index, shares_requested_e4, hardship_type in tenders:
        filed.append(
            world.tender(
                period["id"],
                scene["share_class_id"],
                shares_requested_e4,
                scene["investors"][holder_index]["id"],
                hardship_type=hardship_type,
            )
        )

    world.set_clock("2026-09-25T12:00:00Z", TRANSFER_AGENT)
    scene["period_id"] = period["id"]
    scene["requests"] = filed
    return scene


def _oversubscribed_september(world: ReitWorld) -> dict:
    """Requested value of 900,001 cents against a capacity of 600,000."""
    return _september_period_with_three_tenders(
        world,
        [
            (0, 4000000, HardshipType.NONE),
            (1, 3000000, HardshipType.DEATH),
            (2, 2000010, HardshipType.NONE),
        ],
    )


def _ridgeline_offering(world: ReitWorld, max_commission_bps: int = 300) -> dict:
    """A 275 + 25 bps class D sold under an agreement with the given load ceiling."""
    offering = world.offering(
        name="Ridgeline Value REIT",
        minimum_offering_amount_cents=20000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    share_class = world.share_class(
        offering["id"],
        class_code=ClassCode.D,
        upfront_selling_commission_bps=275,
        dealer_manager_fee_bps=25,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(
        firm_name="Ridge Capital Partners", crd_number="CRD-300001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=max_commission_bps,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    holder = world.investor(
        legal_name="Dana Pike",
        email="dana.pike@example.com",
        state_code="TX",
        net_worth_cents=100000000,
        annual_income_cents=40000000,
    )
    world.document_suitability(holder["id"], "SUIT-D-2026-08")
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "selling_agreement_id": agreement["id"],
        "investor_id": holder["id"],
    }


def _subscribe_250200(api: ApiClient, scene: dict):
    """Tender a gross of 250,200 cents, the amount on which the two rounded lines diverge."""
    return api.create_subscription(
        subscription_payload(
            scene["offering_id"],
            scene["share_class_id"],
            scene["investor_id"],
            scene["selling_agreement_id"],
            gross_investment_cents=250200,
        ),
        SPONSOR,
    )


def _summit_lot_one_month_short_of_its_cap(world: ReitWorld) -> dict:
    """A class T lot carrying 10,000 of 15,000 cents of trail fee, and a second month due.

    Class T charges 1200 bps a year on a 1,000,000-cent lot, so each month books
    10,000 cents against a 150 bps cap of 15,000: the August payment fills two
    thirds of the cap and the September payment is the one that must be truncated
    and then converted (PRD §3.7).
    """
    offering = world.offering(
        name="Summit Net Lease REIT",
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    class_t = world.share_class(
        offering["id"],
        class_code=ClassCode.T,
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=1200,
        distribution_fee_cap_bps=150,
        converts_to_class_code=ClassCode.I,
    )
    class_i = world.share_class(
        offering["id"],
        class_code=ClassCode.I,
        upfront_selling_commission_bps=0,
        dealer_manager_fee_bps=0,
        annual_distribution_fee_bps=0,
        distribution_fee_cap_bps=0,
    )
    firm = world.broker_dealer(
        firm_name="Summit Distribution LLC", crd_number="CRD-400001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    anchor = world.investor(
        legal_name="Grove Institutional Trust",
        email="grove.trust@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(anchor["id"], "SUIT-GROVE-2026-08")
    elena = world.investor(
        legal_name="Elena Marsh",
        email="elena.marsh@example.com",
        state_code="TX",
        net_worth_cents=500000000,
        annual_income_cents=100000000,
    )
    world.document_suitability(elena["id"], "SUIT-E-2026-08")

    anchor_subscription = world.subscription(
        offering["id"], class_i["id"], anchor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(anchor_subscription["id"])
    elena_subscription = world.subscription(
        offering["id"], class_t["id"], elena["id"], agreement["id"], 1000000
    )
    world.escrow_subscription(elena_subscription["id"])
    world.break_escrow(offering["id"])
    lot = world.lot_of_subscription(elena_subscription["id"])

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    world.published_nav(class_t["id"], "2026-08-01", "2026-08-31", 1000000, 0, "IVA-2026-08-T")
    world.published_nav(class_i["id"], "2026-08-01", "2026-08-31", 37500000, 0, "IVA-2026-08-I")

    august = world.declaration(
        offering["id"],
        record_date="2026-08-31",
        payment_date="2026-09-15",
        declared_per_share_cents=1,
        gaap_net_income_cents=15500,
        adjusted_cash_flow_cents=31000,
        board_uncovered_acknowledgement=False,
    )
    world.set_clock("2026-09-15T00:00:00Z", TRANSFER_AGENT)
    world.pay_declaration(august["id"])

    world.set_clock("2026-10-02T00:00:00Z", SPONSOR)
    september = world.declaration(
        offering["id"],
        record_date="2026-09-30",
        payment_date="2026-10-15",
        declared_per_share_cents=1,
        gaap_net_income_cents=15500,
        adjusted_cash_flow_cents=31000,
        board_uncovered_acknowledgement=False,
    )
    world.set_clock("2026-10-15T00:00:00Z", TRANSFER_AGENT)
    return {
        "offering_id": offering["id"],
        "class_t_id": class_t["id"],
        "class_i_id": class_i["id"],
        "lot_id": lot["id"],
        "elena_id": elena["id"],
        "august_id": august["id"],
        "september_id": september["id"],
    }


class TestRepurchaseHardshipTierThenProrataLeftover:
    """Capacity, then hardship in full, then a floored pro rata with the leftover cent."""

    def test_capacity_is_the_lesser_cap_and_every_tender_is_valued_at_the_published_price(
        self, world: ReitWorld
    ):
        """Both caps come off the fresh aggregate valuation and the monthly leg binds.

        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate multiplied by 200 basis points, divided by 10,000, floored."

        PRD §3.8: "`capacity_cents` is the lesser of the monthly cap and the quarterly remainder."

        PRD §3.8: "Each `QUEUED` tender is then valued: `requested_value_cents` is the `shares_requested_e4` multiplied by the transaction price of the tender's class, divided by 10,000 and rounded half up."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        period = world.read_period(scene["period_id"])
        assert_fields(
            period,
            monthly_cap_cents=600000,
            quarterly_remaining_cents=1500000,
            capacity_cents=600000,
        )

        first, hardship, third = scene["requests"]
        assert_fields(world.read_request(first["id"]), requested_value_cents=400000)
        assert_fields(world.read_request(hardship["id"]), requested_value_cents=300000)
        assert_fields(world.read_request(third["id"]), requested_value_cents=200001)

    def test_hardship_tender_is_paid_in_full_before_the_ordinary_tenders_share_the_residue(
        self, world: ReitWorld
    ):
        """The death tender takes 300,000 of the 600,000 capacity and the rest is split pro rata.

        PRD §3.8: "Tier one is every queued tender whose `hardship_type` is `DEATH` or `DISABILITY`; visited in ascending `created_at` order, each such tender is granted the lesser of its own requested value and whatever capacity remains, so hardship tenders are satisfied in full until the capacity is dry and any hardship tender reached after that point is granted nothing."

        PRD §3.8: "Tier two is every queued tender whose `hardship_type` is `NONE`, and it shares only what tier one left."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        first, hardship, third = scene["requests"]
        assert_fields(world.read_request(hardship["id"]), approved_value_cents=300000)
        ordinary_total = (
            world.read_request(first["id"])["approved_value_cents"]
            + world.read_request(third["id"])["approved_value_cents"]
        )
        assert ordinary_total == 300000, (
            "the two ordinary tenders may share only the 300,000 cents the hardship "
            f"tender left of the 600,000-cent capacity, got {ordinary_total}"
        )

    def test_floored_prorata_shares_are_topped_up_a_cent_at_a_time_from_the_earliest_tender(
        self, world: ReitWorld
    ):
        """The floored shares of 199,999 and 100,000 leave one cent, which goes to the earlier tender.

        PRD §3.8: "Otherwise each tier-two tender is granted the remainder multiplied by its own requested value, divided by the tier-two total, and floored; the flooring leaves a shortfall of a few cents against the remainder, and that leftover is distributed one cent at a time to tier-two tenders in ascending `created_at` order until it is exhausted."

        PRD §3.8: "`approved_shares_e4` is the `approved_value_cents` multiplied by 10,000, divided by the class's transaction price and floored."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        first, hardship, third = scene["requests"]
        assert_fields(
            world.read_request(first["id"]),
            approved_value_cents=200000,
            approved_shares_e4=2000000,
        )
        assert_fields(
            world.read_request(third["id"]),
            approved_value_cents=100000,
            approved_shares_e4=1000000,
        )
        assert_fields(world.read_request(hardship["id"]), approved_shares_e4=3000000)

    def test_each_consumed_lot_bears_its_own_early_repurchase_deduction(
        self, world: ReitWorld
    ):
        """Lots 60 days old are all inside the window, so every grant is cut by two percent.

        PRD §3.8: "The lot's holding period is the whole number of days from the calendar date of its `issued_date` to the period's `settlement_date`; where that count is fewer than 365 days the lot bears a deduction of two percent of its own gross proceeds — the lot gross multiplied by 200 basis points, divided by 10,000 and rounded half up — and where it is 365 days or more the lot bears no deduction at all."

        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the sum of its per-lot deductions and `net_proceeds_cents` as the sum of its per-lot gross amounts each less that lot's deduction, and the deduction total is added to the stockholder's `cumulative_early_repurchase_deduction_cents`."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        first, hardship, third = scene["requests"]
        assert_fields(
            world.read_request(first["id"]),
            early_repurchase_deduction_cents=4000,
            net_proceeds_cents=196000,
        )
        assert_fields(
            world.read_request(hardship["id"]),
            early_repurchase_deduction_cents=6000,
            net_proceeds_cents=294000,
        )
        assert_fields(
            world.read_request(third["id"]),
            early_repurchase_deduction_cents=2000,
            net_proceeds_cents=98000,
        )

    def test_outcomes_and_period_totals_follow_from_the_grants(
        self, world: ReitWorld
    ):
        """A cut-back tender is partial, the period settles the gross grants and marks itself prorated.

        PRD §3.8: "A tender whose approved value equals its requested value becomes `FULFILLED`; one whose approved value is zero becomes `REJECTED`, consuming no lot and paying nothing; anything in between becomes `PARTIALLY_FULFILLED`."

        PRD §3.8: "The period's `settled_amount_cents` is the sum of every `approved_value_cents` in the run, and that gross figure is what is charged against both caps; `prorated` is set true when at least one non-hardship tender was cut back below its requested value."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        first, hardship, third = scene["requests"]
        assert_fields(
            world.read_request(first["id"]),
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
        )
        assert_fields(
            world.read_request(hardship["id"]),
            status=RepurchaseRequestStatus.FULFILLED,
        )
        assert_fields(
            world.read_request(third["id"]),
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
        )
        assert_fields(
            world.read_period(scene["period_id"]),
            settled_amount_cents=600000,
            prorated=True,
            status=RepurchasePeriodStatus.PROCESSED,
        )

    def test_consumed_shares_leave_the_class_and_the_aggregate_valuation(
        self, world: ReitWorld
    ):
        """The 6,000,000 e4 repurchased drop out of the class count and out of the aggregate.

        PRD §3.8: "Once the whole run is complete the period reports `settled_amount_cents` and `prorated` and reaches `PROCESSED`; every touched class's `shares_outstanding_e4`, every touched stockholder's `total_shares_e4` and the offering's `aggregate_nav_cents` are recomputed; and any stockholder left holding no `OPEN` lot has `account_status` moved to `CLOSED_NO_POSITION`."

        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class of the offering, of each class's transaction price multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up — each class's contribution rounded to a whole cent on its own before the contributions are added."

        Design: Difficulty/combinatorial_formula/repurchase_hardship_tier_then_prorata_leftover_allocation
        """
        scene = _oversubscribed_september(world)

        world.process_period(scene["period_id"])

        assert_fields(
            world.read_share_class(scene["share_class_id"]),
            shares_outstanding_e4=294000000,
        )
        assert_fields(
            world.read_offering(scene["offering_id"]), aggregate_nav_cents=29400000
        )


class TestSubscriptionLoadPerLineRoundingThenSum:
    """Two load lines rounded on their own, then added — not one blended rate rounded once."""

    def test_each_load_line_is_rounded_before_the_two_are_added(
        self, api: ApiClient, world: ReitWorld
    ):
        """275 bps and 25 bps of 250,200 round to 6881 and 626, netting 242,693 rather than 242,694.

        PRD §3.4: "`upfront_selling_commission_cents` is the gross investment multiplied by the class's `upfront_selling_commission_bps`, divided by 10,000, rounded half up to a whole cent."

        PRD §3.4: "Each line is rounded on its own and only then are the two added together to form the total load; combining the two basis-point rates into one rate and rounding a single time is a different computation that disagrees with this one for some gross amounts, and it is not what this service does."

        PRD §3.4: "`net_invested_cents` is the gross investment less the sum of those two rounded lines."

        Design: Difficulty/combinatorial_formula/subscription_load_per_line_rounding_then_sum
        """
        scene = _ridgeline_offering(world)

        subscription = assert_created(_subscribe_250200(api, scene))

        assert_fields(
            subscription,
            upfront_selling_commission_cents=6881,
            dealer_manager_fee_cents=626,
            net_invested_cents=242693,
        )
        assert subscription["net_invested_cents"] != 242694, (
            "242694 is the net a single blended 300 bps line rounded once would give, "
            "which is not the two-line computation this service performs"
        )

    def test_share_issuance_floors_the_net_against_the_initial_offering_price(
        self, api: ApiClient, world: ReitWorld
    ):
        """With no published valuation the price is the initial 1000 cents and 242,693 buys 2,426,930 e4.

        PRD §3.4: "If there are none, the price is the offering's `initial_offering_price_cents`."

        PRD §3.4: "`shares_issued_e4` is the net invested amount multiplied by 10,000 and divided by the pinned transaction price, floored to a whole share unit — a stockholder is never issued a fraction of a ten-thousandth of a share."

        PRD §3.4: "Because of that floor a sliver of money is usually left over: `unapplied_cash_cents` is the net invested amount less the value of the issued shares, that value being the issued share units multiplied by the transaction price, divided by 10,000, and floored."

        PRD §3.4: "A freshly authored subscription sits in `PENDING` with a null `rejection_reason` and a null `accepted_at`."

        Design: Difficulty/combinatorial_formula/subscription_load_per_line_rounding_then_sum
        """
        scene = _ridgeline_offering(world)

        subscription = assert_created(_subscribe_250200(api, scene))

        assert_fields(
            subscription,
            transaction_price_cents=1000,
            shares_issued_e4=2426930,
            unapplied_cash_cents=0,
            status=SubscriptionStatus.PENDING,
            rejection_reason=None,
            accepted_at=None,
        )

    @pytest.mark.parametrize(
        "max_commission_bps, expect_created",
        [(300, True), (299, False)],
    )
    def test_the_two_load_rates_are_summed_against_the_agreement_ceiling(
        self,
        api: ApiClient,
        world: ReitWorld,
        max_commission_bps: int,
        expect_created: bool,
    ):
        """275 + 25 bps sits exactly on a 300 bps ceiling and one basis point over a 299 bps one.

        PRD §3.4: "The class's `upfront_selling_commission_bps` and `dealer_manager_fee_bps` added together must not exceed the agreement's `max_commission_bps`, or the subscription is refused with `ERR_COMMISSION_CAP_EXCEEDED` — a firm that negotiated a lower load ceiling cannot be routed into an expensive class."

        PRD §3.2: "`concentration_limit_cents` is then ten percent of that basis — the basis multiplied by 1000 basis points, divided by 10,000, and floored to a whole cent."

        Design: Difficulty/combinatorial_formula/subscription_load_per_line_rounding_then_sum
        """
        scene = _ridgeline_offering(world, max_commission_bps=max_commission_bps)
        assert_fields(
            world.read_investor(scene["investor_id"]),
            concentration_limit_cents=10000000,
        )

        response = _subscribe_250200(api, scene)

        if expect_created:
            assert_created(response)
        else:
            assert_error(response, ApiErrorId.COMMISSION_CAP_EXCEEDED, 422)


class TestDistributionFeeCappedAccrualThenClassConversion:
    """The capped instalment is booked first; only then does the lot change classes."""

    def test_the_month_that_reaches_the_cap_still_books_its_truncated_instalment(
        self, world: ReitWorld
    ):
        """A full 10,000-cent monthly fee is cut to the 5,000 of headroom left, landing on the cap.

        PRD §3.7: "The full monthly fee is that lot value multiplied by the class's `annual_distribution_fee_bps`, divided by 10,000 and then divided again by the twelve months of the year, the whole rounded half up to a whole cent."

        PRD §3.7: "The fee actually applied is the lesser of the full monthly fee and that headroom, and it is added to the lot's `cumulative_distribution_fee_cents`."

        PRD §3.7: "A lot that reaches its cap during a month still bears that month's partial fee — the cap truncates the instalment, it does not waive it."

        Design: Difficulty/combinatorial_formula/distribution_fee_capped_accrual_then_class_conversion_order
        """
        scene = _summit_lot_one_month_short_of_its_cap(world)

        world.pay_declaration(scene["september_id"])

        assert_fields(
            world.read_declaration(scene["august_id"]),
            total_declared_cents=31000,
            total_distribution_fee_accrued_cents=10000,
        )
        assert_fields(
            world.read_declaration(scene["september_id"]),
            total_distribution_fee_accrued_cents=5000,
            status=DeclarationStatus.PAID,
        )
        assert_fields(
            world.read_lot(scene["lot_id"]),
            distribution_fee_cap_cents=15000,
            cumulative_distribution_fee_cents=15000,
        )

    def test_conversion_reprices_the_share_count_but_never_the_minting_figures(
        self, world: ReitWorld
    ):
        """Value is carried from a 1000-cent class into a 1250-cent one, and cap and cost stay put.

        PRD §3.7: "Conversion happens only after the capped accrual has been booked."

        PRD §3.7: "The lot's new share count is its `remaining_shares_e4` multiplied by the price of the class it is leaving, divided by the destination class's price, and floored to a whole share unit — value is preserved, share count is not."

        PRD §3.7: "Two figures are deliberately *never* re-based by a conversion: `gross_offering_price_cents` and `distribution_fee_cap_cents` stay exactly as they were set at minting, so a converted lot cannot be charged a second cap's worth of trail fees."

        Design: Difficulty/combinatorial_formula/distribution_fee_capped_accrual_then_class_conversion_order
        """
        scene = _summit_lot_one_month_short_of_its_cap(world)

        world.pay_declaration(scene["september_id"])

        assert_fields(
            world.read_lot(scene["lot_id"]),
            share_class_id=scene["class_i_id"],
            converted_from_share_class_id=scene["class_t_id"],
            original_shares_e4=8000000,
            remaining_shares_e4=8000000,
            gross_offering_price_cents=1000000,
            distribution_fee_cap_cents=15000,
        )

    def test_conversion_moves_the_shares_between_classes_and_rebuilds_the_aggregate(
        self, world: ReitWorld
    ):
        """The emptied class reads zero, the destination absorbs 8,000,000 e4, and both payments credit the holder.

        PRD §3.7: "First, every lot that was `OPEN` as of the `record_date` produces a credit to its holder's `cumulative_distributions_received_cents`, that credit being the `declared_per_share_cents` multiplied by the lot's `remaining_shares_e4`, divided by 10,000 and rounded half up to a whole cent."

        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class of the offering, of each class's transaction price multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up — each class's contribution rounded to a whole cent on its own before the contributions are added."

        Design: Difficulty/combinatorial_formula/distribution_fee_capped_accrual_then_class_conversion_order
        """
        scene = _summit_lot_one_month_short_of_its_cap(world)

        world.pay_declaration(scene["september_id"])

        assert_fields(
            world.read_share_class(scene["class_t_id"]), shares_outstanding_e4=0
        )
        assert_fields(
            world.read_share_class(scene["class_i_id"]),
            shares_outstanding_e4=308000000,
        )
        assert_fields(
            world.read_investor(scene["elena_id"]),
            cumulative_distributions_received_cents=2000,
        )
        assert_fields(
            world.read_offering(scene["offering_id"]), aggregate_nav_cents=38500000
        )
