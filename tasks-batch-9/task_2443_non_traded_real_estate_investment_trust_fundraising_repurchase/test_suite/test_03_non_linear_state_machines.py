"""State machines that are not straight lines: parallel axes, a review loop, a fan-out.

An offering carries three simultaneously live status axes, a valuation record
walks a `DRAFT`/`ADVISOR_REVIEW` cycle rather than a chain, and one processing
call fans a single `QUEUED` source state out into three different terminal states
in the same transaction. Each scenario below drives the machine off its happy
path and pins both what moved and what deliberately did not.
"""

from __future__ import annotations

from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    ApiClient,
    ApiErrorId,
    ClassCode,
    EscrowAction,
    EscrowStatus,
    HardshipType,
    NavRecordStatus,
    RegistrationAction,
    RegistrationStatus,
    RepurchasePeriodStatus,
    RepurchasePlanAction,
    RepurchasePlanStatus,
    RepurchaseRequestStatus,
    SubscriptionStatus,
    assert_error,
    assert_fields,
    assert_offering_axes,
    assert_ok,
)
from test_helpers.fixtures import ReitWorld

_HARBORLINE_HOLDERS = (
    ("Avery Nolan", "avery.nolan@example.com", "SUIT-A-2026-08"),
    ("Blake Ortiz", "blake.ortiz@example.com", "SUIT-B-2026-08"),
    ("Casey Rivera", "casey.rivera@example.com", "SUIT-C-2026-08"),
)


def _single_holder_broken_escrow(
    world: ReitWorld, offering_name: str, firm_name: str, crd_number: str,
    holder_name: str, holder_email: str, documentation_reference: str,
) -> dict:
    """One 30,000,000-cent class I ticket, escrowed and then accepted by the break."""
    offering = world.offering(
        name=offering_name,
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
    firm = world.broker_dealer(firm_name=firm_name, crd_number=crd_number)
    agreement = world.selling_agreement(
        offering["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(offering["id"])
    world.activate_agreement(agreement["id"])

    holder = world.investor(
        legal_name=holder_name,
        email=holder_email,
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(holder["id"], documentation_reference)
    subscription = world.subscription(
        offering["id"], share_class["id"], holder["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investor_id": holder["id"],
        "subscription_id": subscription["id"],
    }


def _northgate_with_both_reversible_axes_suspended(world: ReitWorld) -> dict:
    """Registration already reinstated, the plan axis still suspended, escrow terminal.

    Registration walks EFFECTIVE to SUSPENDED and back while the plan axis walks
    ACTIVE to SUSPENDED on its own, so the row under test is one whose three axes
    all sit in different places (PRD §2.10).
    """
    scene = _single_holder_broken_escrow(
        world,
        offering_name="Northgate Core REIT",
        firm_name="Northgate Distribution LLC",
        crd_number="CRD-500001",
        holder_name="Nora Whitfield",
        holder_email="nora.whitfield@example.com",
        documentation_reference="SUIT-N-2026-08",
    )
    world.drive_registration(
        scene["offering_id"],
        RegistrationAction.SUSPEND,
        reason="PROSPECTUS_SUPPLEMENT_PENDING",
    )
    world.drive_repurchase_plan(
        scene["offering_id"],
        RepurchasePlanAction.SUSPEND,
        reason="MARKET_DISLOCATION",
    )
    world.drive_registration(scene["offering_id"], RegistrationAction.REINSTATE)
    return scene


def _beacon_with_a_pushed_back_valuation(world: ReitWorld, api: ApiClient) -> dict:
    """An August record sent back to DRAFT by the advisor with a stored reason."""
    scene = _single_holder_broken_escrow(
        world,
        offering_name="Beacon Yield REIT",
        firm_name="Beacon Placement Group",
        crd_number="CRD-600001",
        holder_name="Fiona Lang",
        holder_email="fiona.lang@example.com",
        documentation_reference="SUIT-F-2026-08",
    )
    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    record = world.nav_record(
        scene["share_class_id"], "2026-08-01", "2026-08-31", 30900000, 900000
    )
    world.submit_nav_for_review(record["id"])
    pushed_back = assert_ok(
        api.set_nav_record_status(
            record["id"],
            {
                "to_status": NavRecordStatus.DRAFT,
                "rejection_reason": "APPRAISAL_STALE_ON_TWO_ASSETS",
            },
            ADVISOR,
        )
    )
    scene["nav_record_id"] = record["id"]
    scene["pushed_back"] = pushed_back
    return scene


def _harborline_with_three_equal_holders(world: ReitWorld) -> dict:
    """Aggregate valuation of 30,000,000 cents split across three 100,000,000 e4 lots."""
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
            offering["id"], share_class["id"], holder["id"], agreement["id"], 10000000
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


def _september_with_one_hardship_soaking_the_capacity(world: ReitWorld) -> dict:
    """A death tender of 599,995 cents against 600,000 of capacity, leaving five cents."""
    scene = _harborline_with_three_equal_holders(world)
    period = world.repurchase_period(
        scene["offering_id"],
        period_month="2026-09",
        opens_at="2026-09-03T00:00:00Z",
        request_cutoff_at="2026-09-25T00:00:00Z",
        settlement_date="2026-09-30",
    )
    world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)
    tenders = [
        world.tender(
            period["id"],
            scene["share_class_id"],
            4000000,
            scene["investors"][0]["id"],
            hardship_type=HardshipType.NONE,
        ),
        world.tender(
            period["id"],
            scene["share_class_id"],
            5999950,
            scene["investors"][1]["id"],
            hardship_type=HardshipType.DEATH,
        ),
        world.tender(
            period["id"],
            scene["share_class_id"],
            200000,
            scene["investors"][2]["id"],
            hardship_type=HardshipType.NONE,
        ),
    ]
    world.set_clock("2026-09-25T12:00:00Z", TRANSFER_AGENT)
    scene["period_id"] = period["id"]
    scene["requests"] = tenders
    return scene


class TestOfferingParallelAxesWithALockedEscrowAxis:
    """Two axes cycle while the third stays pinned at its terminal state."""

    def test_resuming_the_plan_leaves_the_other_two_axes_exactly_where_they_were(
        self, world: ReitWorld
    ):
        """A plan resume clears only the plan's own reason; registration and escrow are untouched.

        PRD §2.10: "A change on one axis never implies a change on another unless a rule in §3 says so explicitly."

        PRD §3.8: "`RESUME` reverses all of that — it returns `SUSPENDED` to `ACTIVE`, increments `version`, clears `repurchase_plan_suspension_reason`, returns every `SUSPENDED` period of the offering to `OPEN` and every `HELD` tender in those periods to `QUEUED` — but it is permitted only while the offering's `escrow_status` is `BROKEN`."

        Design: Difficulty/non_linear_state_machine/offering_parallel_axes_independent_with_locked_escrow_axis
        """
        scene = _northgate_with_both_reversible_axes_suspended(world)

        world.drive_repurchase_plan(scene["offering_id"], RepurchasePlanAction.RESUME)

        offering = world.read_offering(scene["offering_id"])
        assert_offering_axes(
            offering,
            registration_status=RegistrationStatus.EFFECTIVE,
            escrow_status=EscrowStatus.BROKEN,
            repurchase_plan_status=RepurchasePlanStatus.ACTIVE,
        )
        assert_fields(offering, repurchase_plan_suspension_reason=None)

    def test_the_terminal_escrow_axis_refuses_a_fail_the_other_axes_would_have_allowed(
        self, api: ApiClient, world: ReitWorld
    ):
        """Escrow sits terminal at BROKEN, so FAIL is not a transition of its own machine.

        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."

        PRD §2.10: "It carries three independent axes, each with its own state machine and its own transition vocabulary: `registration_status` (`DRAFT`, `EFFECTIVE`, `SUSPENDED`, `CLOSED`, with `CLOSED` terminal), `escrow_status` (`COLLECTING`, `BROKEN`, `FAILED`, with both `BROKEN` and `FAILED` terminal), and `repurchase_plan_status` (`ACTIVE`, `SUSPENDED`, `TERMINATED`, with `TERMINATED` terminal)."

        Design: Difficulty/non_linear_state_machine/offering_parallel_axes_independent_with_locked_escrow_axis
        """
        scene = _northgate_with_both_reversible_axes_suspended(world)
        world.drive_repurchase_plan(scene["offering_id"], RepurchasePlanAction.RESUME)

        response = api.drive_escrow(
            scene["offering_id"], {"action": EscrowAction.FAIL}, COMPLIANCE
        )

        assert_error(response, ApiErrorId.INVALID_STATE_TRANSITION, 409)
        assert_offering_axes(
            world.read_offering(scene["offering_id"]),
            escrow_status=EscrowStatus.BROKEN,
            repurchase_plan_status=RepurchasePlanStatus.ACTIVE,
        )

    def test_the_figures_the_escrow_break_moved_survive_the_suspension_round_trip(
        self, world: ReitWorld
    ):
        """The break already emptied escrow into gross proceeds and accepted the ticket.

        PRD §3.5: "The offering's `version` increments; every subscription of the offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at` order; one share lot is minted per accepted subscription with `issued_date` set to the current logical clock instant; `shares_outstanding_e4` on every touched class and `total_shares_e4` on every touched stockholder are recomputed; each affected stockholder's `cumulative_invested_cents` is recomputed and their `suitability_status` re-evaluated against `concentration_limit_cents`, so a stockholder pushed over the limit by the batch lands in `FLAGGED`; and the whole of `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Difficulty/non_linear_state_machine/offering_parallel_axes_independent_with_locked_escrow_axis
        """
        scene = _northgate_with_both_reversible_axes_suspended(world)

        world.drive_repurchase_plan(scene["offering_id"], RepurchasePlanAction.RESUME)

        assert_fields(
            world.read_offering(scene["offering_id"]),
            escrow_balance_cents=0,
            gross_proceeds_cents=30000000,
        )
        assert_fields(
            world.read_subscription(scene["subscription_id"]),
            status=SubscriptionStatus.ACCEPTED,
        )


class TestValuationAdvisorPushBackRevisionCycle:
    """DRAFT and ADVISOR_REVIEW form a loop, and PUBLISHED closes it for good."""

    def test_a_push_back_stores_its_reason_and_the_resubmission_clears_it(
        self, api: ApiClient, world: ReitWorld
    ):
        """The advisor's reason is stored on the row and wiped by the next submission.

        PRD §3.6: "A push-back returns the record to `DRAFT` and requires a `rejection_reason`, which is stored on the record; without one the request is rejected with `ERR_INVALID_REQUEST`."

        PRD §3.6: "Submission increments the record's `version` and clears any `rejection_reason` left over from an earlier push-back."

        Design: Difficulty/non_linear_state_machine/nav_record_advisor_pushback_revision_cycle
        """
        scene = _beacon_with_a_pushed_back_valuation(world, api)
        assert_fields(
            scene["pushed_back"],
            status=NavRecordStatus.DRAFT,
            rejection_reason="APPRAISAL_STALE_ON_TWO_ASSETS",
        )

        resubmitted = world.submit_nav_for_review(scene["nav_record_id"])

        assert_fields(
            resubmitted,
            status=NavRecordStatus.ADVISOR_REVIEW,
            rejection_reason=None,
        )

    def test_the_second_pass_publishes_the_record_and_repriced_the_offering(
        self, api: ApiClient, world: ReitWorld
    ):
        """A record that went round the loop publishes normally, opinion reference and all.

        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and records the supplied `advisor_opinion_reference`; where `variance_bps` exceeds 500 basis points that reference is mandatory and a confirmation without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."

        PRD §3.6: "Publication increments the record's `version`, drives the class's previously `PUBLISHED` record to the terminal `SUPERSEDED` with its own `version` incremented, and recomputes the offering's `aggregate_nav_cents` from the new transaction price."

        Design: Difficulty/non_linear_state_machine/nav_record_advisor_pushback_revision_cycle
        """
        scene = _beacon_with_a_pushed_back_valuation(world, api)
        world.submit_nav_for_review(scene["nav_record_id"])
        world.confirm_nav(scene["nav_record_id"], "IVA-2026-08-BEACON")

        published = world.publish_nav_record(scene["nav_record_id"])

        assert_fields(
            published,
            status=NavRecordStatus.PUBLISHED,
            advisor_opinion_reference="IVA-2026-08-BEACON",
            rejection_reason=None,
            shares_outstanding_e4_snapshot=300000000,
            nav_per_share_pre_accrual_cents=1000,
            nav_per_share_cents=1000,
            variance_bps=0,
        )
        assert_fields(
            world.read_offering(scene["offering_id"]), aggregate_nav_cents=30000000
        )

    def test_publishing_an_already_published_record_is_refused_and_changes_nothing(
        self, api: ApiClient, world: ReitWorld
    ):
        """The loop ends at PUBLISHED: a repeated trigger has no transition to take.

        PRD §2.9: "This covers terminal-state lockdown and repeated triggers — paying an already paid declaration, processing an already processed period, breaking an already broken escrow."

        PRD §3.6: "A `SponsorOperator` moves `ADVISOR_CONFIRMED` to `PUBLISHED`, which is permitted only when no other `PUBLISHED` record for the same class covers an overlapping period."

        Design: Difficulty/non_linear_state_machine/nav_record_advisor_pushback_revision_cycle
        """
        scene = _beacon_with_a_pushed_back_valuation(world, api)
        world.submit_nav_for_review(scene["nav_record_id"])
        world.confirm_nav(scene["nav_record_id"], "IVA-2026-08-BEACON")
        world.publish_nav_record(scene["nav_record_id"])

        response = api.set_nav_record_status(
            scene["nav_record_id"], {"to_status": NavRecordStatus.PUBLISHED}, SPONSOR
        )

        assert_error(response, ApiErrorId.INVALID_STATE_TRANSITION, 409)
        assert_fields(
            world.read_nav_record(scene["nav_record_id"]),
            status=NavRecordStatus.PUBLISHED,
            advisor_opinion_reference="IVA-2026-08-BEACON",
        )


class TestRepurchaseRequestThreeWayBranchFromQueued:
    """One processing call sends three QUEUED tenders to three different terminals."""

    def test_the_hardship_tender_is_fulfilled_in_full_out_of_the_whole_capacity(
        self, world: ReitWorld
    ):
        """A death tender of 599,995 cents fits inside 600,000 of capacity and settles complete.

        PRD §3.8: "Tier one is every queued tender whose `hardship_type` is `DEATH` or `DISABILITY`; visited in ascending `created_at` order, each such tender is granted the lesser of its own requested value and whatever capacity remains, so hardship tenders are satisfied in full until the capacity is dry and any hardship tender reached after that point is granted nothing."

        PRD §3.8: "A tender whose approved value equals its requested value becomes `FULFILLED`; one whose approved value is zero becomes `REJECTED`, consuming no lot and paying nothing; anything in between becomes `PARTIALLY_FULFILLED`."

        Design: Difficulty/non_linear_state_machine/repurchase_request_three_way_branch_from_queued
        """
        scene = _september_with_one_hardship_soaking_the_capacity(world)

        world.process_period(scene["period_id"])

        assert_fields(world.read_period(scene["period_id"]), capacity_cents=600000)
        assert_fields(
            world.read_request(scene["requests"][1]["id"]),
            status=RepurchaseRequestStatus.FULFILLED,
            approved_value_cents=599995,
            approved_shares_e4=5999950,
            early_repurchase_deduction_cents=12000,
            net_proceeds_cents=587995,
        )

    def test_the_five_cent_residue_partially_fulfils_one_tender_and_rejects_the_other(
        self, world: ReitWorld
    ):
        """The earliest ordinary tender takes the whole five-cent residue; the later one gets nothing.

        PRD §3.8: "Otherwise each tier-two tender is granted the remainder multiplied by its own requested value, divided by the tier-two total, and floored; the flooring leaves a shortfall of a few cents against the remainder, and that leftover is distributed one cent at a time to tier-two tenders in ascending `created_at` order until it is exhausted."

        PRD §3.8: "A tender whose approved value equals its requested value becomes `FULFILLED`; one whose approved value is zero becomes `REJECTED`, consuming no lot and paying nothing; anything in between becomes `PARTIALLY_FULFILLED`."

        Design: Difficulty/non_linear_state_machine/repurchase_request_three_way_branch_from_queued
        """
        scene = _september_with_one_hardship_soaking_the_capacity(world)

        world.process_period(scene["period_id"])

        assert_fields(
            world.read_request(scene["requests"][0]["id"]),
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
            approved_value_cents=5,
            approved_shares_e4=50,
            early_repurchase_deduction_cents=0,
            net_proceeds_cents=5,
        )
        assert_fields(
            world.read_request(scene["requests"][2]["id"]),
            status=RepurchaseRequestStatus.REJECTED,
            approved_value_cents=0,
            approved_shares_e4=0,
        )
        assert_fields(
            world.read_investor(scene["investors"][2]["id"]),
            total_shares_e4=100000000,
        )

    def test_the_period_settles_the_gross_grants_of_all_three_branches(
        self, world: ReitWorld
    ):
        """599,995 plus 5 plus nothing is the settled amount, and the cut-back tender marks it prorated.

        PRD §3.8: "The period's `settled_amount_cents` is the sum of every `approved_value_cents` in the run, and that gross figure is what is charged against both caps; `prorated` is set true when at least one non-hardship tender was cut back below its requested value."

        PRD §3.8: "Once the whole run is complete the period reports `settled_amount_cents` and `prorated` and reaches `PROCESSED`; every touched class's `shares_outstanding_e4`, every touched stockholder's `total_shares_e4` and the offering's `aggregate_nav_cents` are recomputed; and any stockholder left holding no `OPEN` lot has `account_status` moved to `CLOSED_NO_POSITION`."

        Design: Difficulty/non_linear_state_machine/repurchase_request_three_way_branch_from_queued
        """
        scene = _september_with_one_hardship_soaking_the_capacity(world)

        world.process_period(scene["period_id"])

        assert_fields(
            world.read_period(scene["period_id"]),
            settled_amount_cents=600000,
            prorated=True,
            status=RepurchasePeriodStatus.PROCESSED,
        )
        assert_fields(
            world.read_share_class(scene["share_class_id"]),
            shares_outstanding_e4=294000000,
        )
