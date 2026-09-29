"""Cascades that walk several entity levels inside a single request.

Two of the PRD's operations reach far past the row they are aimed at. Barring a
firm (PRD §3.3) travels BrokerDealer to SellingAgreement to Subscription, and
processing a repurchase period (PRD §3.8) travels RepurchasePeriod to
RepurchaseRequest to ShareLot to the stockholder's ``account_status``. Each test
below builds the whole chain from an empty database and then makes exactly one
call, so the assertions describe what that one call did.
"""

from typing import Any, Dict

from test_helpers import (
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    AccountStatus,
    ApiClient,
    ClassCode,
    RepurchasePeriodStatus,
    RepurchaseRequestStatus,
    SellingAgreementStatus,
    ShareLotStatus,
    SubscriptionStatus,
    SupervisionStatus,
    assert_fields,
    assert_ok,
)
from test_helpers.fixtures import ReitWorld

# ─── Chain builders ───────────────────────────────────────────────────


def _build_two_firm_channel(world: ReitWorld) -> Dict[str, Any]:
    """One EFFECTIVE offering, two firms, three agreements, two tickets.

    Firm BD1 holds an ACTIVE agreement carrying a PENDING subscription and a
    PENDING agreement that never sold anything; firm BD2 holds an ACTIVE
    agreement carrying a PENDING subscription of its own. BD1 is then escalated
    to HEIGHTENED_SUPERVISION so that the bar is reachable (PRD §3.3).
    """
    offering = world.offering(
        name="Crestline Income REIT",
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
    world.declare_effective(offering["id"])

    bd1 = world.broker_dealer(
        firm_name="Crestline Securities LLC", crd_number="CRD-700001"
    )
    bd2 = world.broker_dealer(
        firm_name="Lakeshore Placement Inc", crd_number="CRD-700002"
    )
    sa1 = world.selling_agreement(
        offering["id"],
        bd1["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    sa2 = world.selling_agreement(
        offering["id"],
        bd1["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    sa3 = world.selling_agreement(
        offering["id"],
        bd2["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.activate_agreement(sa1["id"])
    world.activate_agreement(sa3["id"])

    investor_g = world.documented_investor(
        legal_name="Gabriel Ness",
        email="gabriel.ness@example.com",
        state_code="TX",
        net_worth_cents=2000000000,
        annual_income_cents=400000000,
    )
    world.documented_investor(
        legal_name="Hana Ibarra",
        email="hana.ibarra@example.com",
        state_code="TX",
        net_worth_cents=2000000000,
        annual_income_cents=400000000,
    )
    investor_i = world.documented_investor(
        legal_name="Ivan Petrossian",
        email="ivan.petrossian@example.com",
        state_code="TX",
        net_worth_cents=2000000000,
        annual_income_cents=400000000,
    )

    sub_g = world.subscription(
        offering["id"], share_class["id"], investor_g["id"], sa1["id"], 500000
    )
    sub_i = world.subscription(
        offering["id"], share_class["id"], investor_i["id"], sa3["id"], 500000
    )

    world.set_supervision_status(
        bd1["id"],
        SupervisionStatus.HEIGHTENED_SUPERVISION,
        reason="BRANCH_AUDIT_FINDINGS",
    )

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "bd1_id": bd1["id"],
        "bd2_id": bd2["id"],
        "sa1_id": sa1["id"],
        "sa2_id": sa2["id"],
        "sa3_id": sa3["id"],
        "sub_g_id": sub_g["id"],
        "sub_i_id": sub_i["id"],
    }


def _build_settled_period(world: ReitWorld) -> Dict[str, Any]:
    """A funded offering with a closed 2026-09 period holding one full tender.

    An anchor stockholder holds 300,000,000 e4 and a small holder holds the
    3,000,500 e4 it is about to tender in full. The class carries a PUBLISHED
    August valuation of 1000 cents per share and the clock is parked past the
    period's cutoff so the run may proceed (PRD §3.6, §3.8).
    """
    offering = world.offering(
        name="Fairhaven Growth REIT",
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
        firm_name="Fairhaven Distributors LLC", crd_number="CRD-800001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    anchor = world.documented_investor(
        legal_name="Grove Institutional Trust",
        email="grove.trust@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    holder = world.documented_investor(
        legal_name="Dana Pike",
        email="dana.pike@example.com",
        state_code="TX",
        net_worth_cents=100000000,
        annual_income_cents=40000000,
    )

    sub_anchor = world.subscription(
        offering["id"], share_class["id"], anchor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(sub_anchor["id"])
    sub_holder = world.subscription(
        offering["id"], share_class["id"], holder["id"], agreement["id"], 300050
    )
    world.escrow_subscription(sub_holder["id"])
    world.break_escrow(offering["id"])
    lot = world.lot_of_subscription(sub_holder["id"])

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    nav_record = world.published_nav(
        share_class["id"],
        "2026-08-01",
        "2026-08-31",
        31200050,
        900000,
        "IVA-2026-08-FH",
    )

    period = world.repurchase_period(
        offering["id"],
        period_month="2026-09",
        opens_at="2026-09-03T00:00:00Z",
        request_cutoff_at="2026-09-25T00:00:00Z",
        settlement_date="2026-09-30",
    )
    world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)
    tender = world.tender(period["id"], share_class["id"], 3000500, holder["id"])
    world.set_clock("2026-09-25T12:00:00Z", TRANSFER_AGENT)

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "anchor_id": anchor["id"],
        "holder_id": holder["id"],
        "lot_id": lot["id"],
        "nav_record_id": nav_record["id"],
        "period_id": period["id"],
        "tender_id": tender["id"],
    }


# ─── Barring a firm ───────────────────────────────────────────────────


class TestBarringAFirmCascades:
    """PRD §3.3: barring reaches agreements and then pending subscriptions."""

    def test_barring_terminates_every_agreement_and_rejects_pending_business(
        self, api: ApiClient, world: ReitWorld
    ):
        """One bar drives both of the firm's agreements terminal and rejects its pending ticket.

        PRD §3.3: "`HEIGHTENED_SUPERVISION` may also be escalated to the
        terminal `BARRED`, which is the most destructive single act in the
        system: every selling agreement of that firm still in `PENDING`,
        `ACTIVE` or `SUSPENDED` is driven to the terminal `TERMINATED`, and
        every subscription still in `PENDING` under any of those agreements is
        driven to `REJECTED` carrying the `rejection_reason` string
        `BROKER_DEALER_BARRED`."

        Design: Difficulty/transitive_cascade/broker_dealer_barred_cascades_agreements_then_pending_subscriptions
        """
        ids = _build_two_firm_channel(world)

        response = api.set_supervision_status(
            ids["bd1_id"],
            {"to_status": SupervisionStatus.BARRED, "reason": "REGULATORY_BAR_ORDER"},
            COMPLIANCE,
        )
        barred = assert_ok(response)
        assert_fields(barred, supervision_status=SupervisionStatus.BARRED)

        assert_fields(
            world.read_agreement(ids["sa1_id"]),
            status=SellingAgreementStatus.TERMINATED,
        )
        assert_fields(
            world.read_agreement(ids["sa2_id"]),
            status=SellingAgreementStatus.TERMINATED,
        )
        assert_fields(
            world.read_subscription(ids["sub_g_id"]),
            status=SubscriptionStatus.REJECTED,
            rejection_reason="BROKER_DEALER_BARRED",
        )

    def test_barring_one_firm_leaves_a_rival_firms_channel_untouched(
        self, api: ApiClient, world: ReitWorld
    ):
        """The cascade is scoped to the barred firm, so the sibling channel keeps selling.

        PRD §3.3: "`HEIGHTENED_SUPERVISION` may also be escalated to the
        terminal `BARRED`, which is the most destructive single act in the
        system: every selling agreement of that firm still in `PENDING`,
        `ACTIVE` or `SUSPENDED` is driven to the terminal `TERMINATED`, and
        every subscription still in `PENDING` under any of those agreements is
        driven to `REJECTED` carrying the `rejection_reason` string
        `BROKER_DEALER_BARRED`."
        PRD §3.1: "A newly created offering opens with `registration_status` at
        `DRAFT`, `escrow_status` at `COLLECTING`, `repurchase_plan_status` at
        `ACTIVE`, a null `repurchase_plan_suspension_reason`, and
        `escrow_balance_cents`, `gross_proceeds_cents` and `aggregate_nav_cents`
        all at zero."

        Design: Difficulty/transitive_cascade/broker_dealer_barred_cascades_agreements_then_pending_subscriptions
        """
        ids = _build_two_firm_channel(world)

        assert_ok(
            api.set_supervision_status(
                ids["bd1_id"],
                {
                    "to_status": SupervisionStatus.BARRED,
                    "reason": "REGULATORY_BAR_ORDER",
                },
                COMPLIANCE,
            )
        )

        assert_fields(
            world.read_broker_dealer(ids["bd2_id"]),
            supervision_status=SupervisionStatus.IN_GOOD_STANDING,
        )
        assert_fields(
            world.read_agreement(ids["sa3_id"]), status=SellingAgreementStatus.ACTIVE
        )
        assert_fields(
            world.read_subscription(ids["sub_i_id"]), status=SubscriptionStatus.PENDING
        )
        assert_fields(
            world.read_offering(ids["offering_id"]),
            escrow_balance_cents=0,
            gross_proceeds_cents=0,
        )

    def test_barring_increments_the_version_of_every_row_the_cascade_touches(
        self, api: ApiClient, world: ReitWorld
    ):
        """Each cascaded row advances exactly one revision; untouched rows do not move.

        PRD §3.3: "The firm's `version` increments, as does the `version` of
        every agreement and subscription the cascade touches."
        PRD §3.3: "Firms open at `IN_GOOD_STANDING` with
        `suspended_agreement_count` at zero."

        Design: Difficulty/transitive_cascade/broker_dealer_barred_cascades_agreements_then_pending_subscriptions
        """
        ids = _build_two_firm_channel(world)
        before = {
            "bd1": world.read_broker_dealer(ids["bd1_id"])["version"],
            "sa1": world.read_agreement(ids["sa1_id"])["version"],
            "sa2": world.read_agreement(ids["sa2_id"])["version"],
            "sub_g": world.read_subscription(ids["sub_g_id"])["version"],
            "sa3": world.read_agreement(ids["sa3_id"])["version"],
            "sub_i": world.read_subscription(ids["sub_i_id"])["version"],
        }

        assert_ok(
            api.set_supervision_status(
                ids["bd1_id"],
                {
                    "to_status": SupervisionStatus.BARRED,
                    "reason": "REGULATORY_BAR_ORDER",
                },
                COMPLIANCE,
            )
        )

        barred_firm = world.read_broker_dealer(ids["bd1_id"])
        assert barred_firm["version"] == before["bd1"] + 1, (
            f"barred firm version should advance by one, "
            f"got {barred_firm['version']} from {before['bd1']}"
        )
        assert world.read_agreement(ids["sa1_id"])["version"] == before["sa1"] + 1
        assert world.read_agreement(ids["sa2_id"])["version"] == before["sa2"] + 1
        assert world.read_subscription(ids["sub_g_id"])["version"] == before["sub_g"] + 1
        assert world.read_agreement(ids["sa3_id"])["version"] == before["sa3"], (
            "a rival firm's agreement is outside the cascade and must not be revised"
        )
        assert world.read_subscription(ids["sub_i_id"])["version"] == before["sub_i"], (
            "a rival firm's pending subscription must not be revised"
        )
        assert_fields(barred_firm, suspended_agreement_count=0)


# ─── Processing a period ──────────────────────────────────────────────


class TestPeriodProcessingCascadesToTheAccount:
    """PRD §3.8: one processing run values, settles, closes lots and accounts."""

    def test_processing_captures_the_caps_and_fulfils_the_whole_tender(
        self, api: ApiClient, world: ReitWorld
    ):
        """Caps come off the fresh aggregate valuation and the lone tender is granted in full.

        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate
        multiplied by 200 basis points, divided by 10,000, floored."
        PRD §3.8: "`capacity_cents` is the lesser of the monthly cap and the
        quarterly remainder."
        PRD §3.8: "If the tier-two tenders' requested values sum to no more than
        the remainder, each of them is granted its full requested value."
        PRD §3.8: "A tender whose approved value equals its requested value
        becomes `FULFILLED`; one whose approved value is zero becomes
        `REJECTED`, consuming no lot and paying nothing; anything in between
        becomes `PARTIALLY_FULFILLED`."

        Design: Difficulty/transitive_cascade/period_processing_closes_lot_then_closes_investor_account
        """
        ids = _build_settled_period(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(world.read_nav_record(ids["nav_record_id"]), nav_per_share_cents=1000)
        assert_fields(
            world.read_period(ids["period_id"]),
            monthly_cap_cents=606001,
            capacity_cents=606001,
        )
        assert_fields(
            world.read_request(ids["tender_id"]),
            requested_value_cents=300050,
            approved_value_cents=300050,
            status=RepurchaseRequestStatus.FULFILLED,
        )

    def test_processing_charges_the_early_repurchase_deduction_on_the_young_lot(
        self, api: ApiClient, world: ReitWorld
    ):
        """A lot held well under a year bears two percent, and the deduction reaches the account.

        PRD §3.8: "The lot's holding period is the whole number of days from the
        calendar date of its `issued_date` to the period's `settlement_date`;
        where that count is fewer than 365 days the lot bears a deduction of two
        percent of its own gross proceeds — the lot gross multiplied by 200
        basis points, divided by 10,000 and rounded half up — and where it is
        365 days or more the lot bears no deduction at all."
        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the
        sum of its per-lot deductions and `net_proceeds_cents` as the sum of its
        per-lot gross amounts each less that lot's deduction, and the deduction
        total is added to the stockholder's
        `cumulative_early_repurchase_deduction_cents`."

        Design: Difficulty/transitive_cascade/period_processing_closes_lot_then_closes_investor_account
        """
        ids = _build_settled_period(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_request(ids["tender_id"]),
            early_repurchase_deduction_cents=6001,
            net_proceeds_cents=294049,
        )
        assert_fields(
            world.read_investor(ids["holder_id"]),
            cumulative_early_repurchase_deduction_cents=6001,
        )

    def test_processing_closes_the_exhausted_lot_and_then_closes_the_account(
        self, api: ApiClient, world: ReitWorld
    ):
        """Consuming the last lot down to zero closes it and drops the stockholder to no position.

        PRD §3.8: "The lot's `remaining_shares_e4` is reduced by the units taken
        and, if it falls to zero, the lot moves to the terminal `CLOSED` with
        its `version` incremented and drops out of both `shares_outstanding_e4`
        and `total_shares_e4`."
        PRD §3.8: "Once the whole run is complete the period reports
        `settled_amount_cents` and `prorated` and reaches `PROCESSED`; every
        touched class's `shares_outstanding_e4`, every touched stockholder's
        `total_shares_e4` and the offering's `aggregate_nav_cents` are
        recomputed; and any stockholder left holding no `OPEN` lot has
        `account_status` moved to `CLOSED_NO_POSITION`."

        Design: Difficulty/transitive_cascade/period_processing_closes_lot_then_closes_investor_account
        """
        ids = _build_settled_period(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_lot(ids["lot_id"]),
            remaining_shares_e4=0,
            status=ShareLotStatus.CLOSED,
        )
        assert_fields(
            world.read_investor(ids["holder_id"]),
            total_shares_e4=0,
            account_status=AccountStatus.CLOSED_NO_POSITION,
        )

    def test_processing_leaves_the_anchor_holder_and_rebases_the_class_and_offering(
        self, api: ApiClient, world: ReitWorld
    ):
        """The untouched co-investor keeps its position while the derived totals fall by the settled shares.

        PRD §3.8: "Once the whole run is complete the period reports
        `settled_amount_cents` and `prorated` and reaches `PROCESSED`; every
        touched class's `shares_outstanding_e4`, every touched stockholder's
        `total_shares_e4` and the offering's `aggregate_nav_cents` are
        recomputed; and any stockholder left holding no `OPEN` lot has
        `account_status` moved to `CLOSED_NO_POSITION`."
        PRD §3.8: "The period's `settled_amount_cents` is the sum of every
        `approved_value_cents` in the run, and that gross figure is what is
        charged against both caps; `prorated` is set true when at least one
        non-hardship tender was cut back below its requested value."
        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share
        class of the offering, of each class's transaction price multiplied by
        that class's `shares_outstanding_e4`, divided by 10,000 and rounded half
        up — each class's contribution rounded to a whole cent on its own before
        the contributions are added."

        Design: Difficulty/transitive_cascade/period_processing_closes_lot_then_closes_investor_account
        """
        ids = _build_settled_period(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_investor(ids["anchor_id"]),
            account_status=AccountStatus.ACTIVE,
            total_shares_e4=300000000,
        )
        assert_fields(
            world.read_period(ids["period_id"]),
            status=RepurchasePeriodStatus.PROCESSED,
            settled_amount_cents=300050,
            prorated=False,
        )
        assert_fields(
            world.read_share_class(ids["share_class_id"]),
            shares_outstanding_e4=300000000,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=30000000
        )
