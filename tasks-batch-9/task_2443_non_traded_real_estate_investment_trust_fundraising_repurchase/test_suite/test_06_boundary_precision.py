"""Comparisons that must land on the exact side the PRD names.

Three thresholds carry an explicit inclusivity in the specification: the escrow
minimum (``>=``, measured on gross rather than net money), the 365-day
early-repurchase holding boundary (inclusive at the top), and the 500-basis-point
NAV variance escalation (strictly greater). Each test pairs the value that sits
on the boundary with the neighbouring value one unit away, because only the pair
distinguishes a correct comparison from an off-by-one.
"""

from typing import Any, Dict

from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    AccountStatus,
    ApiClient,
    ApiErrorId,
    ClassCode,
    EscrowAction,
    EscrowStatus,
    HardshipType,
    NavRecordStatus,
    RepurchaseRequestStatus,
    ShareLotStatus,
    SubscriptionStatus,
    assert_error,
    assert_fields,
    assert_ok,
)
from test_helpers.fixtures import ReitWorld

# ─── Chain builders ───────────────────────────────────────────────────


def _build_escrow_one_cent_short(world: ReitWorld) -> Dict[str, Any]:
    """A 20,000,000-cent minimum with 19,750,000 cents of gross money escrowed.

    Class T charges 300 basis points of selling commission and 50 of dealer
    manager fee under an agreement capped at 500, so the two rounded load lines
    are visible in every share count (PRD §3.4, §3.5).
    """
    offering = world.offering(
        name="Cornerstone Income REIT",
        minimum_offering_amount_cents=20000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    share_class = world.share_class(
        offering["id"],
        class_code=ClassCode.T,
        upfront_selling_commission_bps=300,
        dealer_manager_fee_bps=50,
        annual_distribution_fee_bps=850,
        distribution_fee_cap_bps=875,
        converts_to_class_code=ClassCode.I,
    )
    firm = world.broker_dealer(
        firm_name="Meridian Securities LLC", crd_number="CRD-100001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=500,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    investors = [
        world.documented_investor(
            legal_name=name,
            email=email,
            state_code="TX",
            net_worth_cents=500000000,
            annual_income_cents=100000000,
        )
        for name, email in (
            ("Avery Nolan", "avery.nolan@example.com"),
            ("Blake Ortiz", "blake.ortiz@example.com"),
            ("Casey Rivera", "casey.rivera@example.com"),
        )
    ]
    sub_a = world.subscription(
        offering["id"],
        share_class["id"],
        investors[0]["id"],
        agreement["id"],
        10000000,
    )
    world.escrow_subscription(sub_a["id"])
    sub_b = world.subscription(
        offering["id"],
        share_class["id"],
        investors[1]["id"],
        agreement["id"],
        9750000,
    )
    world.escrow_subscription(sub_b["id"])

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "agreement_id": agreement["id"],
        "investor_c_id": investors[2]["id"],
        "sub_a_id": sub_a["id"],
        "sub_b_id": sub_b["id"],
    }


def _top_up_escrow_to_the_minimum(
    world: ReitWorld, ids: Dict[str, Any]
) -> str:
    """Escrow the last 250,000 cents, taking the balance to exactly the minimum."""
    sub_c = world.subscription(
        ids["offering_id"],
        ids["share_class_id"],
        ids["investor_c_id"],
        ids["agreement_id"],
        250000,
    )
    world.escrow_subscription(sub_c["id"])
    return sub_c["id"]


def _build_two_lots_straddling_the_holding_boundary(
    world: ReitWorld,
) -> Dict[str, Any]:
    """Two lots one day apart, tendered against a 2027-08-01 settlement date.

    The first lot is minted by the escrow break at the boundary clock instant of
    2026-08-01 and the second by an acceptance a day later, so at settlement they
    are 365 and 364 days old respectively (PRD §3.5, §3.6, §3.8).
    """
    offering = world.offering(
        name="Trailhead Income REIT",
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
        firm_name="Trailhead Securities LLC", crd_number="CRD-900001"
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
        legal_name="Avery Nolan",
        email="avery.nolan@example.com",
        state_code="TX",
        net_worth_cents=100000000,
        annual_income_cents=40000000,
    )
    sub_anchor = world.subscription(
        offering["id"], share_class["id"], anchor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(sub_anchor["id"])
    sub_first = world.subscription(
        offering["id"], share_class["id"], holder["id"], agreement["id"], 250000
    )
    world.escrow_subscription(sub_first["id"])
    world.break_escrow(offering["id"])
    lot_first = world.lot_of_subscription(sub_first["id"])

    world.set_clock("2026-08-02T00:00:00Z", SPONSOR)
    world.published_nav(
        share_class["id"],
        "2026-07-01",
        "2026-07-31",
        31150000,
        900000,
        "IVA-2026-07-TH",
    )
    sub_second = world.subscription(
        offering["id"], share_class["id"], holder["id"], agreement["id"], 250000
    )
    world.accept_subscription(sub_second["id"])
    lot_second = world.lot_of_subscription(sub_second["id"])

    period = world.repurchase_period(
        offering["id"],
        period_month="2027-07",
        opens_at="2027-07-20T00:00:00Z",
        request_cutoff_at="2027-08-01T00:00:00Z",
        settlement_date="2027-08-01",
    )
    world.set_clock("2027-07-25T00:00:00Z", TRANSFER_AGENT)
    tender = world.tender(
        period["id"],
        share_class["id"],
        4000000,
        holder["id"],
        hardship_type=HardshipType.NONE,
    )
    world.set_clock("2027-08-01T00:00:00Z", TRANSFER_AGENT)

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "holder_id": holder["id"],
        "lot_first_id": lot_first["id"],
        "lot_second_id": lot_second["id"],
        "period_id": period["id"],
        "tender_id": tender["id"],
    }


def _build_september_valuation_at_the_variance_boundary(
    world: ReitWorld,
) -> Dict[str, Any]:
    """August published at 1000 cents, September in review at 1050 — exactly 500 bps.

    The class holds exactly 300,000,000 e4 and there are no distribution
    accruals, so each record's per-share figure is the gross asset value divided
    by the share count (PRD §3.5, §3.6).
    """
    offering = world.offering(
        name="Sentinel Realty Income REIT",
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
        firm_name="Sentinel Placement LLC", crd_number="CRD-130001"
    )
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    investor = world.documented_investor(
        legal_name="Sable Ridgeway",
        email="sable.ridgeway@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    august = world.published_nav(
        share_class["id"], "2026-08-01", "2026-08-31", 30000000, 0, "IVA-2026-08-SEN"
    )

    world.set_clock("2026-10-02T00:00:00Z", SPONSOR)
    september = world.nav_record(
        share_class["id"], "2026-09-01", "2026-09-30", 31500000, 0
    )
    world.submit_nav_for_review(september["id"])

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "august_id": august["id"],
        "september_id": september["id"],
    }


def _open_october_for_review(world: ReitWorld, ids: Dict[str, Any]) -> str:
    """Publish September at 1050 and put an October record at 1103 into review."""
    world.confirm_nav(ids["september_id"])
    world.publish_nav_record(ids["september_id"])
    world.set_clock("2026-11-02T00:00:00Z", SPONSOR)
    october = world.nav_record(
        ids["share_class_id"], "2026-10-01", "2026-10-31", 33090000, 0
    )
    world.submit_nav_for_review(october["id"])
    return october["id"]


# ─── The escrow minimum ───────────────────────────────────────────────


class TestEscrowBreakAtTheExactMinimum:
    """PRD §3.5: the break needs the balance at least at the minimum, on gross money."""

    def test_a_balance_one_subscription_short_of_the_minimum_cannot_break(
        self, api: ApiClient, world: ReitWorld
    ):
        """19,750,000 cents of gross money against a 20,000,000-cent minimum is refused.

        PRD §3.5: "`BREAK` takes `escrow_status` from `COLLECTING` to the terminal
        `BROKEN` and has three preconditions: the offering's
        `registration_status` must be `EFFECTIVE`, the accumulated
        `escrow_balance_cents` must be at least the
        `minimum_offering_amount_cents` — a shortfall reports
        `ERR_MINIMUM_OFFERING_NOT_MET` — and the current logical date must be on
        or before the `escrow_deadline_date`, a late break reporting
        `ERR_ESCROW_DEADLINE_PASSED`."
        PRD §3.5: "the subscription's `version` increments and its
        `gross_investment_cents` is added to the offering's
        `escrow_balance_cents`."

        Design: Difficulty/boundary_precision_check/escrow_break_at_exact_minimum_offering_threshold
        """
        ids = _build_escrow_one_cent_short(world)
        assert_fields(
            world.read_offering(ids["offering_id"]),
            escrow_balance_cents=19750000,
            escrow_status=EscrowStatus.COLLECTING,
        )

        response = api.drive_escrow(
            ids["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
        )

        assert_error(response, ApiErrorId.MINIMUM_OFFERING_NOT_MET, 422)
        assert_fields(
            world.read_offering(ids["offering_id"]),
            escrow_status=EscrowStatus.COLLECTING,
            gross_proceeds_cents=0,
        )

    def test_each_ticket_issues_shares_off_two_independently_rounded_load_lines(
        self, world: ReitWorld
    ):
        """The 300 bps and 50 bps lines are rounded separately before the net drives the share count.

        PRD §3.4: "`upfront_selling_commission_cents` is the gross investment
        multiplied by the class's `upfront_selling_commission_bps`, divided by
        10,000, rounded half up to a whole cent."
        PRD §3.4: "`net_invested_cents` is the gross investment less the sum of
        those two rounded lines."
        PRD §3.4: "`shares_issued_e4` is the net invested amount multiplied by
        10,000 and divided by the pinned transaction price, floored to a whole
        share unit — a stockholder is never issued a fraction of a ten-thousandth
        of a share."

        Design: Difficulty/boundary_precision_check/escrow_break_at_exact_minimum_offering_threshold
        """
        ids = _build_escrow_one_cent_short(world)
        sub_c_id = _top_up_escrow_to_the_minimum(world, ids)

        assert_fields(
            world.read_subscription(ids["sub_a_id"]),
            upfront_selling_commission_cents=300000,
            dealer_manager_fee_cents=50000,
            net_invested_cents=9650000,
            shares_issued_e4=96500000,
        )
        assert_fields(
            world.read_subscription(ids["sub_b_id"]),
            upfront_selling_commission_cents=292500,
            dealer_manager_fee_cents=48750,
            net_invested_cents=9408750,
            shares_issued_e4=94087500,
        )
        assert_fields(
            world.read_subscription(sub_c_id),
            upfront_selling_commission_cents=7500,
            dealer_manager_fee_cents=1250,
            net_invested_cents=241250,
            shares_issued_e4=2412500,
        )

    def test_a_balance_landing_exactly_on_the_minimum_breaks_escrow(
        self, api: ApiClient, world: ReitWorld
    ):
        """At exactly 20,000,000 cents — not one cent more — the break is allowed and moves the money.

        PRD §3.5: "`BREAK` takes `escrow_status` from `COLLECTING` to the terminal
        `BROKEN` and has three preconditions: the offering's
        `registration_status` must be `EFFECTIVE`, the accumulated
        `escrow_balance_cents` must be at least the
        `minimum_offering_amount_cents` — a shortfall reports
        `ERR_MINIMUM_OFFERING_NOT_MET` — and the current logical date must be on
        or before the `escrow_deadline_date`, a late break reporting
        `ERR_ESCROW_DEADLINE_PASSED`."
        PRD §3.5: "The offering's `version` increments; every subscription of the
        offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at`
        order; one share lot is minted per accepted subscription with
        `issued_date` set to the current logical clock instant;
        `shares_outstanding_e4` on every touched class and `total_shares_e4` on
        every touched stockholder are recomputed; each affected stockholder's
        `cumulative_invested_cents` is recomputed and their `suitability_status`
        re-evaluated against `concentration_limit_cents`, so a stockholder pushed
        over the limit by the batch lands in `FLAGGED`; and the whole of
        `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Difficulty/boundary_precision_check/escrow_break_at_exact_minimum_offering_threshold
        """
        ids = _build_escrow_one_cent_short(world)
        sub_c_id = _top_up_escrow_to_the_minimum(world, ids)
        assert_fields(
            world.read_offering(ids["offering_id"]), escrow_balance_cents=20000000
        )

        response = api.drive_escrow(
            ids["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
        )

        assert_ok(response)
        assert_fields(
            world.read_offering(ids["offering_id"]),
            escrow_status=EscrowStatus.BROKEN,
            escrow_balance_cents=0,
            gross_proceeds_cents=20000000,
        )
        for subscription_id in (ids["sub_a_id"], ids["sub_b_id"], sub_c_id):
            assert_fields(
                world.read_subscription(subscription_id),
                status=SubscriptionStatus.ACCEPTED,
            )

    def test_the_break_recomputes_outstanding_shares_and_the_aggregate_valuation(
        self, api: ApiClient, world: ReitWorld
    ):
        """The batch sums the three independently floored share counts and revalues the offering.

        PRD §3.5: "The offering's `version` increments; every subscription of the
        offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at`
        order; one share lot is minted per accepted subscription with
        `issued_date` set to the current logical clock instant;
        `shares_outstanding_e4` on every touched class and `total_shares_e4` on
        every touched stockholder are recomputed; each affected stockholder's
        `cumulative_invested_cents` is recomputed and their `suitability_status`
        re-evaluated against `concentration_limit_cents`, so a stockholder pushed
        over the limit by the batch lands in `FLAGGED`; and the whole of
        `escrow_balance_cents` is moved into `gross_proceeds_cents`."
        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class
        of the offering, of each class's transaction price multiplied by that
        class's `shares_outstanding_e4`, divided by 10,000 and rounded half up —
        each class's contribution rounded to a whole cent on its own before the
        contributions are added."

        Design: Difficulty/boundary_precision_check/escrow_break_at_exact_minimum_offering_threshold
        """
        ids = _build_escrow_one_cent_short(world)
        _top_up_escrow_to_the_minimum(world, ids)

        assert_ok(
            api.drive_escrow(
                ids["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
            )
        )

        assert_fields(
            world.read_share_class(ids["share_class_id"]),
            shares_outstanding_e4=193000000,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=19300000
        )


# ─── The 365-day holding boundary ─────────────────────────────────────


class TestEarlyRepurchaseDeductionAtTheHoldingBoundary:
    """PRD §3.8: exactly 365 days is free, 364 days is charged two percent."""

    def test_processing_captures_both_caps_and_grants_the_tender_in_full(
        self, api: ApiClient, world: ReitWorld
    ):
        """A 400,000-cent request sits well inside a 610,000-cent capacity, so it is fulfilled.

        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate
        multiplied by 200 basis points, divided by 10,000, floored."
        PRD §3.8: "The quarterly leg is measured against a five percent ceiling:
        the quarter's usage is the sum of `settled_amount_cents` across the
        offering's *other* periods that share this period's `quarter_key` and
        have already reached `PROCESSED`, and `quarterly_remaining_cents` is the
        greater of zero and the aggregate multiplied by 500 basis points, divided
        by 10,000, floored, less that usage."
        PRD §3.8: "`approved_shares_e4` is the `approved_value_cents` multiplied
        by 10,000, divided by the class's transaction price and floored."

        Design: Difficulty/boundary_precision_check/early_repurchase_deduction_at_exactly_365_day_holding_boundary
        """
        ids = _build_two_lots_straddling_the_holding_boundary(world)
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=30500000
        )

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_period(ids["period_id"]),
            monthly_cap_cents=610000,
            quarterly_remaining_cents=1525000,
            capacity_cents=610000,
        )
        assert_fields(
            world.read_request(ids["tender_id"]),
            requested_value_cents=400000,
            approved_value_cents=400000,
            approved_shares_e4=4000000,
            status=RepurchaseRequestStatus.FULFILLED,
        )

    def test_the_lot_held_exactly_365_days_is_free_and_the_364_day_lot_pays_two_percent(
        self, api: ApiClient, world: ReitWorld
    ):
        """Only the younger lot's 150,000 cents of gross bears a deduction, giving 3,000 cents in total.

        PRD §3.8: "The boundary is inclusive at the top: a lot held for exactly
        365 days is not charged, a lot held for 364 days is."
        PRD §3.8: "The lot's holding period is the whole number of days from the
        calendar date of its `issued_date` to the period's `settlement_date`;
        where that count is fewer than 365 days the lot bears a deduction of two
        percent of its own gross proceeds — the lot gross multiplied by 200 basis
        points, divided by 10,000 and rounded half up — and where it is 365 days
        or more the lot bears no deduction at all."
        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the
        sum of its per-lot deductions and `net_proceeds_cents` as the sum of its
        per-lot gross amounts each less that lot's deduction, and the deduction
        total is added to the stockholder's
        `cumulative_early_repurchase_deduction_cents`."

        Design: Difficulty/boundary_precision_check/early_repurchase_deduction_at_exactly_365_day_holding_boundary
        """
        ids = _build_two_lots_straddling_the_holding_boundary(world)
        assert str(world.read_lot(ids["lot_first_id"])["issued_date"]).startswith(
            "2026-08-01"
        ), "the escrow break must mint its lot at the 2026-08-01 clock instant"
        assert str(world.read_lot(ids["lot_second_id"])["issued_date"]).startswith(
            "2026-08-02"
        ), "the later acceptance must mint its lot at the 2026-08-02 clock instant"

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_request(ids["tender_id"]),
            early_repurchase_deduction_cents=3000,
            net_proceeds_cents=397000,
        )
        assert_fields(
            world.read_investor(ids["holder_id"]),
            cumulative_early_repurchase_deduction_cents=3000,
        )

    def test_settlement_exhausts_the_older_lot_first_and_leaves_the_newer_one_open(
        self, api: ApiClient, world: ReitWorld
    ):
        """FIFO takes all 2,500,000 e4 of the older lot and only 1,500,000 e4 of the newer.

        PRD §3.8: "For each tender, the price is the transaction price of the
        tender's class, and the stockholder's `OPEN` lots in that class are
        visited in ascending `issued_date` order with ascending `created_at`
        breaking a tie — oldest first."
        PRD §3.8: "The lot's `remaining_shares_e4` is reduced by the units taken
        and, if it falls to zero, the lot moves to the terminal `CLOSED` with its
        `version` incremented and drops out of both `shares_outstanding_e4` and
        `total_shares_e4`."

        Design: Difficulty/boundary_precision_check/early_repurchase_deduction_at_exactly_365_day_holding_boundary
        """
        ids = _build_two_lots_straddling_the_holding_boundary(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_lot(ids["lot_first_id"]),
            remaining_shares_e4=0,
            status=ShareLotStatus.CLOSED,
        )
        assert_fields(
            world.read_lot(ids["lot_second_id"]),
            remaining_shares_e4=1000000,
            status=ShareLotStatus.OPEN,
        )
        assert_fields(
            world.read_investor(ids["holder_id"]),
            total_shares_e4=1000000,
            account_status=AccountStatus.ACTIVE,
        )

    def test_settlement_rebases_the_class_and_the_offering_by_the_consumed_units(
        self, api: ApiClient, world: ReitWorld
    ):
        """4,000,000 e4 leaves the class, dropping outstanding shares and the aggregate valuation.

        PRD §3.8: "Once the whole run is complete the period reports
        `settled_amount_cents` and `prorated` and reaches `PROCESSED`; every
        touched class's `shares_outstanding_e4`, every touched stockholder's
        `total_shares_e4` and the offering's `aggregate_nav_cents` are
        recomputed; and any stockholder left holding no `OPEN` lot has
        `account_status` moved to `CLOSED_NO_POSITION`."

        Design: Difficulty/boundary_precision_check/early_repurchase_deduction_at_exactly_365_day_holding_boundary
        """
        ids = _build_two_lots_straddling_the_holding_boundary(world)

        assert_ok(api.process_repurchase_period(ids["period_id"], None, TRANSFER_AGENT))

        assert_fields(
            world.read_share_class(ids["share_class_id"]),
            shares_outstanding_e4=301000000,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=30100000
        )


# ─── The 500-basis-point variance boundary ────────────────────────────


class TestNavVarianceAtTheEscalationThreshold:
    """PRD §3.6: the escalation test is strictly greater than 500 basis points."""

    def test_a_move_of_exactly_500_bps_confirms_without_an_advisor_opinion(
        self, api: ApiClient, world: ReitWorld
    ):
        """1000 to 1050 cents is exactly 500 bps, so confirmation needs no reference at all.

        PRD §3.6: "Otherwise `variance_bps` is the absolute difference between
        this record's `nav_per_share_cents` and the prior record's
        `nav_per_share_cents`, multiplied by 10,000, divided by the prior figure,
        and floored to whole basis points. An independent advisor opinion becomes
        mandatory only when `variance_bps` is **strictly greater** than 500 basis
        points, that is, strictly more than a five percent month-over-month move;
        a move landing on exactly 500 basis points does not require one."
        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and
        records the supplied `advisor_opinion_reference`; where `variance_bps`
        exceeds 500 basis points that reference is mandatory and a confirmation
        without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."

        Design: Difficulty/boundary_precision_check/nav_variance_exactly_at_escalation_threshold
        """
        ids = _build_september_valuation_at_the_variance_boundary(world)
        assert_fields(
            world.read_nav_record(ids["september_id"]),
            nav_per_share_cents=1050,
            variance_bps=500,
        )

        response = api.set_nav_record_status(
            ids["september_id"],
            {"to_status": NavRecordStatus.ADVISOR_CONFIRMED},
            ADVISOR,
        )

        confirmed = assert_ok(response)
        assert "advisor_opinion_reference" in confirmed, (
            f"a valuation record always carries the reference field: {confirmed}"
        )
        assert_fields(
            confirmed,
            status=NavRecordStatus.ADVISOR_CONFIRMED,
            advisor_opinion_reference=None,
        )

    def test_publishing_the_boundary_record_supersedes_august_and_rebases_the_aggregate(
        self, api: ApiClient, world: ReitWorld
    ):
        """The confirmed 1050-cent record publishes with a null reference and retires August.

        PRD §3.6: "Publication increments the record's `version`, drives the
        class's previously `PUBLISHED` record to the terminal `SUPERSEDED` with
        its own `version` incremented, and recomputes the offering's
        `aggregate_nav_cents` from the new transaction price."
        PRD §3.6: "New records open in `DRAFT` with a null
        `advisor_opinion_reference` and a null `rejection_reason`."

        Design: Difficulty/boundary_precision_check/nav_variance_exactly_at_escalation_threshold
        """
        ids = _build_september_valuation_at_the_variance_boundary(world)
        world.confirm_nav(ids["september_id"])

        response = api.set_nav_record_status(
            ids["september_id"], {"to_status": NavRecordStatus.PUBLISHED}, SPONSOR
        )

        published = assert_ok(response)
        assert "advisor_opinion_reference" in published, (
            f"a valuation record always carries the reference field: {published}"
        )
        assert_fields(
            published,
            status=NavRecordStatus.PUBLISHED,
            variance_bps=500,
            advisor_opinion_reference=None,
        )
        assert_fields(
            world.read_nav_record(ids["august_id"]),
            status=NavRecordStatus.SUPERSEDED,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=31500000
        )

    def test_a_move_of_504_bps_refuses_confirmation_until_an_opinion_is_supplied(
        self, api: ApiClient, world: ReitWorld
    ):
        """1050 to 1103 cents floors to 504 bps, which is over the line and demands a reference.

        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and
        records the supplied `advisor_opinion_reference`; where `variance_bps`
        exceeds 500 basis points that reference is mandatory and a confirmation
        without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."
        PRD §3.6: "Otherwise `variance_bps` is the absolute difference between
        this record's `nav_per_share_cents` and the prior record's
        `nav_per_share_cents`, multiplied by 10,000, divided by the prior figure,
        and floored to whole basis points."

        Design: Difficulty/boundary_precision_check/nav_variance_exactly_at_escalation_threshold
        """
        ids = _build_september_valuation_at_the_variance_boundary(world)
        october_id = _open_october_for_review(world, ids)
        assert_fields(
            world.read_nav_record(october_id),
            nav_per_share_cents=1103,
            variance_bps=504,
        )

        refused = api.set_nav_record_status(
            october_id, {"to_status": NavRecordStatus.ADVISOR_CONFIRMED}, ADVISOR
        )

        assert_error(refused, ApiErrorId.ADVISOR_OPINION_REQUIRED, 422)
        assert_fields(
            world.read_nav_record(october_id), status=NavRecordStatus.ADVISOR_REVIEW
        )

    def test_the_504_bps_record_confirms_once_the_opinion_reference_is_supplied(
        self, api: ApiClient, world: ReitWorld
    ):
        """Supplying the reference clears the escalation; the unpublished record leaves the aggregate alone.

        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and
        records the supplied `advisor_opinion_reference`; where `variance_bps`
        exceeds 500 basis points that reference is mandatory and a confirmation
        without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."
        PRD §3.6: "Publication increments the record's `version`, drives the
        class's previously `PUBLISHED` record to the terminal `SUPERSEDED` with
        its own `version` incremented, and recomputes the offering's
        `aggregate_nav_cents` from the new transaction price."

        Design: Difficulty/boundary_precision_check/nav_variance_exactly_at_escalation_threshold
        """
        ids = _build_september_valuation_at_the_variance_boundary(world)
        october_id = _open_october_for_review(world, ids)
        assert_error(
            api.set_nav_record_status(
                october_id, {"to_status": NavRecordStatus.ADVISOR_CONFIRMED}, ADVISOR
            ),
            ApiErrorId.ADVISOR_OPINION_REQUIRED,
            422,
        )

        response = api.set_nav_record_status(
            october_id,
            {
                "to_status": NavRecordStatus.ADVISOR_CONFIRMED,
                "advisor_opinion_reference": "IVA-2026-10-SEN",
            },
            ADVISOR,
        )

        confirmed = assert_ok(response)
        assert_fields(
            confirmed,
            status=NavRecordStatus.ADVISOR_CONFIRMED,
            advisor_opinion_reference="IVA-2026-10-SEN",
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), aggregate_nav_cents=31500000
        )
