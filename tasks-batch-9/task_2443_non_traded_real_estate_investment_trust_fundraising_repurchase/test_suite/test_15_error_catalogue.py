"""Which identifier each refusal reports, and what the refusal leaves behind.

Every test builds the whole of its own world against an empty database. The
logical clock reads its boot instant of 2026-08-01T00:00:00Z (PRD §2.6) unless
the test moves it explicitly.
"""

from __future__ import annotations

import pytest

from test_helpers import (
    BOARD,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    AccountStatus,
    ApiErrorId,
    DeclarationAction,
    DeclarationStatus,
    EscrowAction,
    EscrowStatus,
    LiquidityEventAction,
    LiquidityEventStatus,
    RegistrationAction,
    RegistrationStatus,
    RepurchasePlanStatus,
    RepurchaseRequestStatus,
    SellingAgreementStatus,
    ShareClassStatus,
    ShareLotStatus,
    SubscriptionStatus,
    SupervisionStatus,
    VoteChoice,
    assert_ballot_fields,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    declaration_payload,
    investor_payload,
    make_investor_user_headers,
    repurchase_period_payload,
    share_class_payload,
    stockholder_vote_payload,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld

# ─── Shared world builders (each test calls one against a fresh database) ──


def _jerrow_world(world: ReitWorld) -> dict:
    """An EFFECTIVE offering whose only agreement is still at its default PENDING."""
    offering = world.offering(name="Jerrow Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Jerrow Placement", crd_number="CRD-340002")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    investor = world.investor(
        legal_name="Kaia Lindqvist",
        email="kaia.lindqvist@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], "SUIT-KAIA-2026-08")
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "broker_dealer_id": firm["id"],
        "selling_agreement": agreement,
        "selling_agreement_id": agreement["id"],
        "investor_id": investor["id"],
    }


def _kestrel_world(world: ReitWorld) -> dict:
    """One EFFECTIVE offering and two documented stockholders in different states."""
    offering = world.offering(name="Kestrel Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Kestrel Placement", crd_number="CRD-340003")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    texan = world.investor(
        legal_name="Lena Marchetti",
        email="lena.marchetti@example.com",
        state_code="TX",
        net_worth_cents=2600000,
        annual_income_cents=900000,
    )
    world.document_suitability(texan["id"], "SUIT-LENA-2026-08")
    ohioan = world.investor(
        legal_name="Milo Bergstrom",
        email="milo.bergstrom@example.com",
        state_code="OH",
        net_worth_cents=2600000,
        annual_income_cents=2500000,
    )
    world.document_suitability(ohioan["id"], "SUIT-MILO-2026-08")
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "selling_agreement_id": agreement["id"],
        "texan": texan,
        "ohioan": ohioan,
    }


def _larkmoor_world(world: ReitWorld) -> dict:
    """Three offerings sharing a 2026-08-10 escrow deadline; two are funded.

    Every offering carries a share class, so the only `DECLARE_EFFECTIVE`
    precondition a late attempt on the still-`DRAFT` offering C can violate is
    the escrow deadline (PRD §3.1: "`DECLARE_EFFECTIVE` moves
    `registration_status` from `DRAFT` to `EFFECTIVE`, and it has two
    preconditions: the offering must already have at least one share class, and
    the current logical date must be on or before the `escrow_deadline_date`.").
    """
    offering_a = world.offering(name="Larkmoor A", escrow_deadline_date="2026-08-10")
    offering_b = world.offering(name="Larkmoor B", escrow_deadline_date="2026-08-10")
    offering_c = world.offering(name="Larkmoor C", escrow_deadline_date="2026-08-10")
    class_a = world.share_class(offering_a["id"])
    class_b = world.share_class(offering_b["id"])
    world.share_class(offering_c["id"])
    firm = world.broker_dealer(firm_name="Larkmoor Placement", crd_number="CRD-340004")
    world.declare_effective(offering_a["id"])
    world.declare_effective(offering_b["id"])
    agreement_a = world.selling_agreement(
        offering_a["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement_a["id"])
    agreement_b = world.selling_agreement(
        offering_b["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement_b["id"])
    investor = world.investor(
        legal_name="Noor Habib",
        email="noor.habib@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], "SUIT-NOOR-2026-08")
    subscription_a = world.subscription(
        offering_a["id"], class_a["id"], investor["id"], agreement_a["id"], 30000000
    )
    world.escrow_subscription(subscription_a["id"])
    subscription_b = world.subscription(
        offering_b["id"], class_b["id"], investor["id"], agreement_b["id"], 30000000
    )
    world.escrow_subscription(subscription_b["id"])
    return {
        "offering_a_id": offering_a["id"],
        "offering_b_id": offering_b["id"],
        "offering_c_id": offering_c["id"],
        "subscription_a_id": subscription_a["id"],
        "subscription_b_id": subscription_b["id"],
    }


def _marbrook_world(world: ReitWorld) -> dict:
    """A funded offering carrying one DECLARED distribution for 2026-08-15."""
    offering = world.offering(name="Marbrook Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Marbrook Placement", crd_number="CRD-340005")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    investor = world.investor(
        legal_name="Orla Vance",
        email="orla.vance@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], "SUIT-ORLA-2026-08")
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    declaration = world.declaration(
        offering["id"],
        record_date="2026-08-15",
        payment_date="2026-08-31",
        declared_per_share_cents=5,
        gaap_net_income_cents=90000,
        adjusted_cash_flow_cents=150000,
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investor_id": investor["id"],
        "declaration": declaration,
        "declaration_id": declaration["id"],
    }


def _nethergate_world(world: ReitWorld) -> dict:
    """A funded offering with one PROPOSED listing and one 300000000 e4 holder."""
    offering = world.offering(name="Nethergate Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Nethergate Placement", crd_number="CRD-340006")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    investor = world.investor(
        legal_name="Priya Raval",
        email="priya.raval@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], "SUIT-PRIYA-2026-08")
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    event = world.liquidity_event(
        offering["id"], event_type="LISTING", proposed_effective_date="2026-09-30"
    )
    return {
        "offering_id": offering["id"],
        "investor_id": investor["id"],
        "event": event,
        "event_id": event["id"],
    }


def _oakbourne_world(world: ReitWorld) -> dict:
    """A merger approved by the stockholders, waiting for 2026-09-30."""
    offering = world.offering(name="Oakbourne Income REIT")
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Oakbourne Placement", crd_number="CRD-340007")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    investor = world.investor(
        legal_name="Rhys Calloway",
        email="rhys.calloway@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(investor["id"], "SUIT-RHYS-2026-08")
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    event = world.liquidity_event(
        offering["id"], event_type="MERGER", proposed_effective_date="2026-09-30"
    )
    world.drive_liquidity_event(event["id"], LiquidityEventAction.BOARD_APPROVE, BOARD)
    world.drive_liquidity_event(event["id"], LiquidityEventAction.OPEN_VOTE, SPONSOR)
    world.cast_vote(event["id"], investor["id"], choice=VoteChoice.FOR)
    closed = world.drive_liquidity_event(
        event["id"], LiquidityEventAction.CLOSE_VOTE, SPONSOR
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investor_id": investor["id"],
        "subscription_id": subscription["id"],
        "event_id": event["id"],
        "closed_event": closed,
    }


def _pellworth_world(world: ReitWorld) -> dict:
    """Two funded holders, one of whom has had part of her lot repurchased."""
    offering = world.offering(
        name="Pellworth Income REIT", rescission_window_days=30
    )
    share_class = world.share_class(offering["id"])
    firm = world.broker_dealer(firm_name="Pellworth Placement", crd_number="CRD-340008")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    tendering = world.investor(
        legal_name="Sable Duarte",
        email="sable.duarte@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(tendering["id"], "SUIT-SABLE-2026-08")
    untouched = world.investor(
        legal_name="Tomas Grieve",
        email="tomas.grieve@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(untouched["id"], "SUIT-TOMAS-2026-08")
    subscription_a = world.subscription(
        offering["id"], share_class["id"], tendering["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription_a["id"])
    subscription_b = world.subscription(
        offering["id"], share_class["id"], untouched["id"], agreement["id"], 250000
    )
    world.escrow_subscription(subscription_b["id"])
    broken = world.break_escrow(offering["id"])
    nav = world.published_nav(
        share_class["id"], "2026-07-01", "2026-07-31", 30250000
    )
    period = world.repurchase_period(
        offering["id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-26T00:00:00Z",
        settlement_date="2026-08-30",
    )
    tender = world.tender(period["id"], share_class["id"], 10000000, tendering["id"])
    world.set_clock("2026-08-26T00:00:00Z", TRANSFER_AGENT)
    processed = world.process_period(period["id"])
    return {
        "offering_id": offering["id"],
        "offering": offering,
        "share_class_id": share_class["id"],
        "tendering_id": tendering["id"],
        "untouched_id": untouched["id"],
        "subscription_a_id": subscription_a["id"],
        "subscription_b_id": subscription_b["id"],
        "broken": broken,
        "nav": nav,
        "tender_id": tender["id"],
        "processed": processed,
    }


class TestUniquenessScopes:
    """PRD §3.1–§3.8: four duplicate keys, two global and two per offering."""

    def test_investor_email_and_firm_crd_are_unique_across_the_whole_service(
        self, world: ReitWorld, api
    ):
        """A second account on a taken email and a second firm on a taken CRD are refused.

        PRD §3.2: "The account is described by a `legal_name` of 1 to 120 characters, an `email` that must be unique across all investors — a collision reports `ERR_DUPLICATE_INVESTOR_EMAIL` — a `state_code` of exactly two uppercase letters, and two attested figures that may each be zero or positive but never negative: `net_worth_cents` and `annual_income_cents`."
        PRD §3.3: "A `ComplianceOfficer` registers a **BrokerDealer** with a `firm_name` and a `crd_number`, the latter unique across all firms — a duplicate reports `ERR_DUPLICATE_CRD_NUMBER`."

        Design: Corner/errors/four_uniqueness_scopes_each_reject_their_own_duplicate_key
        """
        world.broker_dealer(firm_name="Ironvale Placement", crd_number="CRD-340001")
        world.investor(
            legal_name="Ida Brekke",
            email="ida.brekke@example.com",
            state_code="TX",
            net_worth_cents=5000000000,
            annual_income_cents=1000000000,
        )

        duplicate_email = api.create_investor(
            investor_payload(
                legal_name="Ida Brekke-Solheim",
                email="ida.brekke@example.com",
                state_code="NY",
                net_worth_cents=900000000,
                annual_income_cents=200000000,
            ),
            TRANSFER_AGENT,
        )
        assert_error(duplicate_email, ApiErrorId.DUPLICATE_INVESTOR_EMAIL, 422)

        duplicate_crd = api.create_broker_dealer(
            {"firm_name": "Quite Different Securities", "crd_number": "CRD-340001"},
            COMPLIANCE,
        )
        assert_error(duplicate_crd, ApiErrorId.DUPLICATE_CRD_NUMBER, 422)

        assert_total_count(api.list_investors(None, SPONSOR), 1)
        assert_total_count(api.list_broker_dealers(None, COMPLIANCE), 1)

    def test_class_code_and_period_month_are_unique_only_within_one_offering(
        self, world: ReitWorld, api
    ):
        """Class code I repeats in a sibling offering but not in its own, and a covered month is refused.

        PRD §3.1: "A `SponsorOperator` adds a **ShareClass** to an offering by naming the parent `offering_id` and a `class_code`, which must be one of `T`, `S`, `D` or `I` and must be unique among that offering's classes — a second attempt at a code the offering already uses is refused with `ERR_DUPLICATE_SHARE_CLASS_CODE`."
        PRD §3.8: "The offering may hold only one non-cancelled period per calendar month: a second attempt at a `period_month` the offering already covers with a period in any status other than `CANCELLED` reports `ERR_DUPLICATE_REPURCHASE_PERIOD`."

        Design: Corner/errors/four_uniqueness_scopes_each_reject_their_own_duplicate_key
        """
        offering_a = world.offering(name="Ironvale Income REIT")
        offering_b = world.offering(name="Ironvale Growth REIT")
        world.share_class(offering_a["id"])
        world.declare_effective(offering_a["id"])
        world.repurchase_period(
            offering_a["id"],
            period_month="2026-08",
            opens_at="2026-08-01T00:00:00Z",
            request_cutoff_at="2026-08-10T00:00:00Z",
            settlement_date="2026-08-12",
        )

        duplicate_code = api.create_share_class(
            share_class_payload(offering_a["id"], class_code="I"), SPONSOR
        )
        assert_error(duplicate_code, ApiErrorId.DUPLICATE_SHARE_CLASS_CODE, 422)

        sibling = assert_created(
            api.create_share_class(
                share_class_payload(offering_b["id"], class_code="I"), SPONSOR
            )
        )
        assert sibling["class_code"] == "I", (
            f"a sibling offering may reuse code I, got {sibling['class_code']!r}"
        )

        # The 2026-08-20 window neither overlaps the 2026-08-01..2026-08-10 sibling
        # nor breaches the five-day buffer after its 2026-08-12 settlement.
        duplicate_month = api.create_repurchase_period(
            repurchase_period_payload(
                offering_a["id"],
                period_month="2026-08",
                opens_at="2026-08-20T00:00:00Z",
                request_cutoff_at="2026-08-25T00:00:00Z",
                settlement_date="2026-08-27",
            ),
            TRANSFER_AGENT,
        )
        assert_error(duplicate_month, ApiErrorId.DUPLICATE_REPURCHASE_PERIOD, 422)

        assert_total_count(
            api.list_share_classes({"offering_id": offering_a["id"]}, SPONSOR), 1
        )
        assert_total_count(
            api.list_repurchase_periods({"offering_id": offering_a["id"]}, TRANSFER_AGENT),
            1,
        )


class TestSellingAgreementDependencyGate:
    """PRD §3.4: only an ACTIVE agreement may carry a subscription."""

    def test_a_pending_agreement_refuses_the_subscription_it_would_carry(
        self, world: ReitWorld, api
    ):
        """The same body is refused while the agreement is PENDING and accepted once it is ACTIVE.

        PRD §3.3: "An agreement opens `PENDING` with `open_minor_finding_count` and `open_major_finding_count` both at zero."
        PRD §3.4: "The offering's `registration_status` must be `EFFECTIVE` (`ERR_OFFERING_NOT_EFFECTIVE`); the target class must not be `CLOSED_TO_NEW` (`ERR_SHARE_CLASS_CLOSED`); the agreement must be `ACTIVE`, so a `PENDING`, `SUSPENDED` or `TERMINATED` agreement reports `ERR_SELLING_AGREEMENT_NOT_ACTIVE`; and the firm behind that agreement must not be `BARRED` (`ERR_BROKER_DEALER_BARRED`)."

        Design: Corner/errors/subscriptions_are_refused_under_pending_suspended_and_terminated_agreements
        """
        setup = _jerrow_world(world)
        assert setup["selling_agreement"]["status"] == SellingAgreementStatus.PENDING, (
            "a fresh agreement must open PENDING"
        )

        body = subscription_payload(
            setup["offering_id"],
            setup["share_class_id"],
            setup["investor_id"],
            setup["selling_agreement_id"],
            gross_investment_cents=250000,
        )
        refused = api.create_subscription(body, SPONSOR)
        assert_error(refused, ApiErrorId.SELLING_AGREEMENT_NOT_ACTIVE, 409)

        world.activate_agreement(setup["selling_agreement_id"])
        accepted = assert_created(api.create_subscription(body, SPONSOR))
        assert accepted["status"] == SubscriptionStatus.PENDING, (
            f"a fresh subscription sits in PENDING, got {accepted['status']!r}"
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": setup["offering_id"]}, SPONSOR), 1
        )

    def test_a_suspended_then_terminated_agreement_refuses_further_subscriptions(
        self, world: ReitWorld, api
    ):
        """Suspension escalates the firm and blocks new money; termination gives the counter back and still blocks.

        PRD §3.3: "`ACTIVE` may be driven to `SUSPENDED`, which increments the firm's `suspended_agreement_count` and, when the firm was `IN_GOOD_STANDING`, escalates it to `HEIGHTENED_SUPERVISION`; while an agreement is suspended, subscriptions under it fail with `ERR_SELLING_AGREEMENT_NOT_ACTIVE`."
        PRD §3.3: "Termination is reachable from all three earlier states and behaves differently in each: from `PENDING` it merely increments the agreement's `version`; from `ACTIVE` it additionally drives every `PENDING` subscription placed under the agreement to `REJECTED` with `rejection_reason` set to `AGREEMENT_TERMINATED`; from `SUSPENDED` it additionally decrements the firm's `suspended_agreement_count`."

        Design: Corner/errors/subscriptions_are_refused_under_pending_suspended_and_terminated_agreements
        """
        setup = _jerrow_world(world)
        world.activate_agreement(setup["selling_agreement_id"])
        world.subscription(
            setup["offering_id"],
            setup["share_class_id"],
            setup["investor_id"],
            setup["selling_agreement_id"],
            250000,
        )

        suspended = assert_ok(
            api.set_selling_agreement_status(
                setup["selling_agreement_id"],
                {"to_status": SellingAgreementStatus.SUSPENDED},
                COMPLIANCE,
            )
        )
        assert_fields(suspended, status=SellingAgreementStatus.SUSPENDED)
        assert_fields(
            world.read_broker_dealer(setup["broker_dealer_id"]),
            suspended_agreement_count=1,
            supervision_status=SupervisionStatus.HEIGHTENED_SUPERVISION,
        )

        follow_on = subscription_payload(
            setup["offering_id"],
            setup["share_class_id"],
            setup["investor_id"],
            setup["selling_agreement_id"],
            gross_investment_cents=50000,
        )
        assert_error(
            api.create_subscription(follow_on, SPONSOR),
            ApiErrorId.SELLING_AGREEMENT_NOT_ACTIVE,
            409,
        )

        terminated = assert_ok(
            api.set_selling_agreement_status(
                setup["selling_agreement_id"],
                {"to_status": SellingAgreementStatus.TERMINATED},
                COMPLIANCE,
            )
        )
        assert_fields(terminated, status=SellingAgreementStatus.TERMINATED)
        assert_fields(
            world.read_broker_dealer(setup["broker_dealer_id"]),
            suspended_agreement_count=0,
        )

        assert_error(
            api.create_subscription(follow_on, SPONSOR),
            ApiErrorId.SELLING_AGREEMENT_NOT_ACTIVE,
            409,
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": setup["offering_id"]}, SPONSOR), 1
        )


class TestConcentrationLimit:
    """PRD §3.2, §3.4: ten percent of a state-dependent basis, inclusive at the limit."""

    def test_the_concentration_limit_takes_the_lesser_basis_in_a_strict_state(
        self, world: ReitWorld, api
    ):
        """Identical net worth yields 260000 in Texas and 250000 in Ohio.

        PRD §3.2: "For a stockholder resident in one of those five, the concentration basis is the **lesser** of the attested net worth and the attested annual income; for a stockholder resident anywhere else, the basis is the attested net worth alone, and annual income does not enter the arithmetic."
        PRD §3.2: "`concentration_limit_cents` is then ten percent of that basis — the basis multiplied by 1000 basis points, divided by 10,000, and floored to a whole cent."

        Design: Corner/errors/concentration_limit_binds_one_cent_past_ten_percent_of_the_state_basis
        """
        setup = _kestrel_world(world)
        assert setup["texan"]["concentration_limit_cents"] == 260000, (
            "a Texas basis is the 2600000-cent net worth alone"
        )
        assert setup["ohioan"]["concentration_limit_cents"] == 250000, (
            "an Ohio basis is the lesser of 2600000 and 2500000"
        )

    @pytest.mark.parametrize(
        "resident, over_limit_cents, at_limit_cents",
        [("texan", 260001, 260000), ("ohioan", 260000, 250000)],
    )
    def test_a_subscription_one_cent_past_the_limit_is_refused(
        self, world: ReitWorld, api, resident, over_limit_cents, at_limit_cents
    ):
        """One cent past the limit is refused; a ticket landing exactly on it is written.

        PRD §3.4: "Then concentration: if this one subscription would by itself carry `cumulative_invested_cents` past `concentration_limit_cents`, it is refused with `ERR_CONCENTRATION_LIMIT_EXCEEDED`."

        Design: Corner/errors/concentration_limit_binds_one_cent_past_ten_percent_of_the_state_basis
        """
        setup = _kestrel_world(world)
        investor_id = setup[resident]["id"]

        over = api.create_subscription(
            subscription_payload(
                setup["offering_id"],
                setup["share_class_id"],
                investor_id,
                setup["selling_agreement_id"],
                gross_investment_cents=over_limit_cents,
            ),
            SPONSOR,
        )
        assert_error(over, ApiErrorId.CONCENTRATION_LIMIT_EXCEEDED, 422)

        at_limit = assert_created(
            api.create_subscription(
                subscription_payload(
                    setup["offering_id"],
                    setup["share_class_id"],
                    investor_id,
                    setup["selling_agreement_id"],
                    gross_investment_cents=at_limit_cents,
                ),
                SPONSOR,
            )
        )
        assert_fields(
            at_limit,
            status=SubscriptionStatus.PENDING,
            gross_investment_cents=at_limit_cents,
        )
        assert_total_count(
            api.list_subscriptions({"offering_id": setup["offering_id"]}, SPONSOR), 1
        )


class TestEscrowDeadline:
    """PRD §3.1, §3.5: the deadline is a calendar date, inclusive on its own day."""

    def test_escrow_breaks_on_the_last_instant_of_the_deadline_date(
        self, world: ReitWorld, api
    ):
        """A break at 2026-08-10T23:59:59Z against a 2026-08-10 deadline is still on time.

        PRD §3.5: "`BREAK` takes `escrow_status` from `COLLECTING` to the terminal `BROKEN` and has three preconditions: the offering's `registration_status` must be `EFFECTIVE`, the accumulated `escrow_balance_cents` must be at least the `minimum_offering_amount_cents` — a shortfall reports `ERR_MINIMUM_OFFERING_NOT_MET` — and the current logical date must be on or before the `escrow_deadline_date`, a late break reporting `ERR_ESCROW_DEADLINE_PASSED`."
        PRD §3.5: "The offering's `version` increments; every subscription of the offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at` order; one share lot is minted per accepted subscription with `issued_date` set to the current logical clock instant; `shares_outstanding_e4` on every touched class and `total_shares_e4` on every touched stockholder are recomputed; each affected stockholder's `cumulative_invested_cents` is recomputed and their `suitability_status` re-evaluated against `concentration_limit_cents`, so a stockholder pushed over the limit by the batch lands in `FLAGGED`; and the whole of `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Corner/errors/escrow_deadline_bars_the_break_and_a_late_effectiveness_on_the_day_after
        """
        setup = _larkmoor_world(world)
        world.set_clock("2026-08-10T23:59:59Z", COMPLIANCE)

        broken = assert_ok(
            api.drive_escrow(
                setup["offering_a_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
            )
        )
        assert_fields(
            broken,
            escrow_status=EscrowStatus.BROKEN,
            gross_proceeds_cents=30000000,
            escrow_balance_cents=0,
        )
        assert_fields(
            world.read_subscription(setup["subscription_a_id"]),
            status=SubscriptionStatus.ACCEPTED,
        )

    def test_the_day_after_the_deadline_bars_the_break_and_a_fresh_effectiveness(
        self, world: ReitWorld, api
    ):
        """At 2026-08-11 both the break and DECLARE_EFFECTIVE report the deadline code and move nothing.

        PRD §3.1: "Declaring an offering effective after the escrow deadline has passed is refused with `ERR_ESCROW_DEADLINE_PASSED`; declaring one effective with no share class attached is refused as an invalid transition with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.5: "`BREAK` takes `escrow_status` from `COLLECTING` to the terminal `BROKEN` and has three preconditions: the offering's `registration_status` must be `EFFECTIVE`, the accumulated `escrow_balance_cents` must be at least the `minimum_offering_amount_cents` — a shortfall reports `ERR_MINIMUM_OFFERING_NOT_MET` — and the current logical date must be on or before the `escrow_deadline_date`, a late break reporting `ERR_ESCROW_DEADLINE_PASSED`."

        Design: Corner/errors/escrow_deadline_bars_the_break_and_a_late_effectiveness_on_the_day_after
        """
        setup = _larkmoor_world(world)
        world.set_clock("2026-08-11T00:00:00Z", COMPLIANCE)

        late_break = api.drive_escrow(
            setup["offering_b_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
        )
        assert_error(late_break, ApiErrorId.ESCROW_DEADLINE_PASSED, 409)

        late_effectiveness = api.drive_registration(
            setup["offering_c_id"],
            {"action": RegistrationAction.DECLARE_EFFECTIVE},
            COMPLIANCE,
        )
        assert_error(late_effectiveness, ApiErrorId.ESCROW_DEADLINE_PASSED, 409)

        assert_fields(
            world.read_offering(setup["offering_b_id"]),
            escrow_status=EscrowStatus.COLLECTING,
            escrow_balance_cents=30000000,
            gross_proceeds_cents=0,
        )
        assert_fields(
            world.read_offering(setup["offering_c_id"]),
            registration_status=RegistrationStatus.DRAFT,
        )
        assert_fields(
            world.read_subscription(setup["subscription_b_id"]),
            status=SubscriptionStatus.ESCROWED,
        )


class TestDeclarationPaymentAndSupersession:
    """PRD §3.7: a declaration pays on its date and is unsupersedable once paid."""

    def test_a_declaration_pays_only_once_its_payment_date_has_been_reached(
        self, world: ReitWorld, api
    ):
        """PAY is refused on 2026-08-01 and credits the holder on the 2026-08-31 payment date.

        PRD §3.7: "`DECLARED` becomes the terminal `PAID` only when the current logical date is on or after the declaration's `payment_date` — an early payment is refused with `ERR_PAYMENT_DATE_NOT_REACHED` — and only when the offering's `escrow_status` is `BROKEN`."
        PRD §3.7: "First, every lot that was `OPEN` as of the `record_date` produces a credit to its holder's `cumulative_distributions_received_cents`, that credit being the `declared_per_share_cents` multiplied by the lot's `remaining_shares_e4`, divided by 10,000 and rounded half up to a whole cent."

        Design: Corner/errors/a_declaration_pays_only_on_its_date_and_then_cannot_be_superseded
        """
        setup = _marbrook_world(world)
        assert_fields(
            setup["declaration"],
            total_declared_cents=150000,
            coverage_ratio_gaap_bps=6000,
            coverage_ratio_cash_bps=10000,
            return_of_capital_bps=0,
            gaap_return_of_capital_bps=4000,
            status=DeclarationStatus.DECLARED,
        )

        early = api.drive_declaration_payment(
            setup["declaration_id"], {"action": DeclarationAction.PAY}, TRANSFER_AGENT
        )
        assert_error(early, ApiErrorId.PAYMENT_DATE_NOT_REACHED, 409)

        world.set_clock("2026-08-31T00:00:00Z", TRANSFER_AGENT)
        paid = assert_ok(
            api.drive_declaration_payment(
                setup["declaration_id"],
                {"action": DeclarationAction.PAY},
                TRANSFER_AGENT,
            )
        )
        assert_fields(paid, status=DeclarationStatus.PAID)
        assert_fields(
            world.read_investor(setup["investor_id"]),
            cumulative_distributions_received_cents=150000,
        )

    def test_a_paid_record_date_cannot_be_superseded_while_another_date_still_can(
        self, world: ReitWorld, api
    ):
        """A second 2026-08-15 declaration is refused after payment; a 2026-09-15 one is written.

        PRD §3.7: "Any declaration of the same offering with the same `record_date` that is still `DECLARED` is driven to the terminal `SUPERSEDED`, with its own `version` incremented and the offering's `version` incremented as well."
        PRD §3.7: "What may not be superseded is a declaration for that record date that has already been paid: that attempt is refused with `ERR_DECLARATION_ALREADY_PAID`."

        Design: Corner/errors/a_declaration_pays_only_on_its_date_and_then_cannot_be_superseded
        """
        setup = _marbrook_world(world)
        world.set_clock("2026-08-31T00:00:00Z", TRANSFER_AGENT)
        world.pay_declaration(setup["declaration_id"])

        # The echoed version is read fresh, so the concurrency gate cannot pre-empt.
        current_version = world.offering_version(setup["offering_id"])
        supersede = api.create_distribution_declaration(
            declaration_payload(
                setup["offering_id"],
                current_version,
                record_date="2026-08-15",
                payment_date="2026-09-30",
                declared_per_share_cents=5,
                gaap_net_income_cents=90000,
                adjusted_cash_flow_cents=150000,
            ),
            SPONSOR,
        )
        assert_error(supersede, ApiErrorId.DECLARATION_ALREADY_PAID, 409)

        later = assert_created(
            api.create_distribution_declaration(
                declaration_payload(
                    setup["offering_id"],
                    world.offering_version(setup["offering_id"]),
                    record_date="2026-09-15",
                    payment_date="2026-09-30",
                    declared_per_share_cents=5,
                    gaap_net_income_cents=90000,
                    adjusted_cash_flow_cents=150000,
                ),
                SPONSOR,
            )
        )
        assert_fields(
            later, status=DeclarationStatus.DECLARED, total_declared_cents=150000
        )
        assert_total_count(
            api.list_distribution_declarations(
                {"offering_id": setup["offering_id"]}, SPONSOR
            ),
            2,
        )
        assert_total_count(
            api.list_distribution_declarations(
                {"status": DeclarationStatus.SUPERSEDED}, SPONSOR
            ),
            0,
        )


class TestBallotWindow:
    """PRD §3.9: ballots are acceptable only inside VOTE_OPEN, once per stockholder."""

    def test_a_ballot_is_refused_before_the_vote_opens_and_accepted_once_it_does(
        self, world: ReitWorld, api
    ):
        """The same ballot fails at PROPOSED and BOARD_APPROVED, then carries the holder's snapshot.

        PRD §3.9: "A ballot cast against an event that is not `VOTE_OPEN` is refused with `ERR_VOTE_NOT_OPEN`, and a stockholder who has already voted on the event is refused a second ballot with `ERR_DUPLICATE_STOCKHOLDER_VOTE`."
        PRD §3.9: "The `SponsorOperator` then opens the solicitation: `OPEN_VOTE` moves `BOARD_APPROVED` to `VOTE_OPEN`, is permitted only while the offering's `registration_status` is anything other than `DRAFT`, snapshots `record_date_shares_e4` as the sum of `shares_outstanding_e4` across every share class of the offering, and is the moment ballots become acceptable."
        PRD §3.9: "As with a tender, the `investor_id` comes from the acting stockholder's `X-User-ID` rather than the payload, and `voting_shares_e4` is snapshotted from that stockholder's `total_shares_e4` at the instant the ballot is written."

        Design: Corner/errors/ballots_are_refused_outside_the_open_vote_and_when_repeated_inside_it
        """
        setup = _nethergate_world(world)
        assert_fields(
            setup["event"],
            status=LiquidityEventStatus.PROPOSED,
            record_date_shares_e4=0,
        )
        holder = make_investor_user_headers(setup["investor_id"])
        ballot = stockholder_vote_payload(setup["event_id"], choice=VoteChoice.FOR)

        assert_error(
            api.cast_stockholder_vote(ballot, holder), ApiErrorId.VOTE_NOT_OPEN, 409
        )

        approved = world.drive_liquidity_event(
            setup["event_id"], LiquidityEventAction.BOARD_APPROVE, BOARD
        )
        assert_fields(approved, status=LiquidityEventStatus.BOARD_APPROVED)
        assert_error(
            api.cast_stockholder_vote(ballot, holder), ApiErrorId.VOTE_NOT_OPEN, 409
        )

        opened = world.drive_liquidity_event(
            setup["event_id"], LiquidityEventAction.OPEN_VOTE, SPONSOR
        )
        assert_fields(
            opened,
            status=LiquidityEventStatus.VOTE_OPEN,
            record_date_shares_e4=300000000,
        )

        response = api.cast_stockholder_vote(ballot, holder)
        assert response.status_code == 201, (
            f"casting a ballot must return 201 Created, got {response.status_code}"
        )
        cast = response.json()["data"]
        # PRD §2.4: a StockholderVote carries only ``id`` and ``created_at`` — it
        # has no ``updated_at`` and no ``version``, so the generic system-field
        # helper does not apply to a ballot.
        assert_ballot_fields(cast)
        assert_fields(
            cast, voting_shares_e4=300000000, investor_id=setup["investor_id"]
        )

    def test_a_second_ballot_inside_the_window_and_any_ballot_after_the_close_are_refused(
        self, world: ReitWorld, api
    ):
        """One stockholder gets one ballot per event, and the closed box refuses the next.

        PRD §3.9: "A ballot cast against an event that is not `VOTE_OPEN` is refused with `ERR_VOTE_NOT_OPEN`, and a stockholder who has already voted on the event is refused a second ballot with `ERR_DUPLICATE_STOCKHOLDER_VOTE`."
        PRD §3.9: "Approval requires both that quorum and a majority of **all** shares outstanding on the record date rather than merely a majority of those voting: the event is approved when quorum is met and twice `votes_for_e4` is strictly greater than `record_date_shares_e4`."

        Design: Corner/errors/ballots_are_refused_outside_the_open_vote_and_when_repeated_inside_it
        """
        setup = _nethergate_world(world)
        holder = make_investor_user_headers(setup["investor_id"])
        world.drive_liquidity_event(
            setup["event_id"], LiquidityEventAction.BOARD_APPROVE, BOARD
        )
        world.drive_liquidity_event(
            setup["event_id"], LiquidityEventAction.OPEN_VOTE, SPONSOR
        )
        world.cast_vote(setup["event_id"], setup["investor_id"], choice=VoteChoice.FOR)

        repeat = api.cast_stockholder_vote(
            stockholder_vote_payload(setup["event_id"], choice=VoteChoice.AGAINST),
            holder,
        )
        assert_error(repeat, ApiErrorId.DUPLICATE_STOCKHOLDER_VOTE, 422)

        closed = world.drive_liquidity_event(
            setup["event_id"], LiquidityEventAction.CLOSE_VOTE, SPONSOR
        )
        assert_fields(
            closed,
            status=LiquidityEventStatus.APPROVED,
            votes_for_e4=300000000,
            quorum_met=True,
        )

        after_close = api.cast_stockholder_vote(
            stockholder_vote_payload(setup["event_id"], choice=VoteChoice.FOR), holder
        )
        assert_error(after_close, ApiErrorId.VOTE_NOT_OPEN, 409)
        assert_total_count(
            api.list_stockholder_votes({"liquidity_event_id": setup["event_id"]}, SPONSOR),
            1,
        )


class TestLiquidityEventExecution:
    """PRD §3.9: execution waits for the proposed effective date, then winds down."""

    def test_execution_before_the_proposed_effective_date_changes_nothing(
        self, world: ReitWorld, api
    ):
        """EXECUTE at 2026-09-29T23:59:59Z is refused and leaves the offering as the vote left it.

        PRD §3.9: "`EXECUTE` moves `APPROVED` to the terminal `EXECUTED` and is permitted only once the current logical date has reached the `proposed_effective_date`; an early attempt is refused with `ERR_EFFECTIVE_DATE_NOT_REACHED`."
        PRD §3.9: "When `CLOSE_VOTE` resolves to `APPROVED`, the offering's `repurchase_plan_status` is moved to `SUSPENDED` with `repurchase_plan_suspension_reason` recorded as `LIQUIDITY_EVENT_APPROVED`, which in turn holds the plan's open periods and queued tenders exactly as an ordinary compliance suspension would."

        Design: Corner/errors/execution_waits_for_the_effective_date_then_closes_the_whole_offering
        """
        setup = _oakbourne_world(world)
        assert_fields(setup["closed_event"], status=LiquidityEventStatus.APPROVED)
        world.set_clock("2026-09-29T23:59:59Z", BOARD)

        early = api.drive_liquidity_event(
            setup["event_id"], {"action": LiquidityEventAction.EXECUTE}, BOARD
        )
        assert_error(early, ApiErrorId.EFFECTIVE_DATE_NOT_REACHED, 409)

        assert_fields(
            world.read_offering(setup["offering_id"]),
            registration_status=RegistrationStatus.EFFECTIVE,
            repurchase_plan_status=RepurchasePlanStatus.SUSPENDED,
            repurchase_plan_suspension_reason="LIQUIDITY_EVENT_APPROVED",
        )

    def test_execution_on_the_effective_date_closes_the_whole_offering(
        self, world: ReitWorld, api
    ):
        """At 2026-09-30 the merger executes, closing registration, the plan and the class.

        PRD §3.9: "Execution winds the offering down in one transaction: the event's `version` increments, the offering's `registration_status` is set to `CLOSED` and its `repurchase_plan_status` to `TERMINATED`, and every share class of the offering still `ACTIVE` is moved to `CLOSED_TO_NEW`."

        Design: Corner/errors/execution_waits_for_the_effective_date_then_closes_the_whole_offering
        """
        setup = _oakbourne_world(world)
        world.set_clock("2026-09-30T00:00:00Z", BOARD)

        executed = assert_ok(
            api.drive_liquidity_event(
                setup["event_id"], {"action": LiquidityEventAction.EXECUTE}, BOARD
            )
        )
        assert_fields(executed, status=LiquidityEventStatus.EXECUTED)
        assert_fields(
            world.read_offering(setup["offering_id"]),
            registration_status=RegistrationStatus.CLOSED,
            repurchase_plan_status=RepurchasePlanStatus.TERMINATED,
        )
        assert_fields(
            world.read_share_class(setup["share_class_id"]),
            status=ShareClassStatus.CLOSED_TO_NEW,
        )
        assert_fields(
            world.read_subscription(setup["subscription_id"]),
            status=SubscriptionStatus.ACCEPTED,
        )
        assert_fields(
            world.read_investor(setup["investor_id"]), total_shares_e4=300000000
        )


class TestRescissionAgainstAConsumedLot:
    """PRD §3.5: a rescission needs an untouched lot, not merely an open window."""

    def test_a_partially_repurchased_lot_cannot_be_rescinded(
        self, world: ReitWorld, api
    ):
        """Settlement left 293950000 of 300000000 e4, so the in-window rescission is refused.

        PRD §3.5: "The untouched test is that the lot's `remaining_shares_e4` still equals its `original_shares_e4`; if a repurchase has already consumed part of it, the rescission is refused with `ERR_LOT_PARTIALLY_REPURCHASED`."
        PRD §3.5: "The window test is that the current logical clock is at or before the lot's `issued_date` advanced by the offering's `rescission_window_days` days; past that instant the request is refused with `ERR_RESCISSION_WINDOW_EXPIRED`."

        Design: Corner/errors/rescission_is_barred_once_the_lot_has_been_partially_repurchased
        """
        setup = _pellworth_world(world)
        assert setup["offering"]["rescission_window_days"] == 30, (
            "the offering was registered with a 30-day rescission window"
        )
        assert setup["nav"]["nav_per_share_cents"] == 1000
        assert_fields(
            setup["processed"], capacity_cents=605000, settled_amount_cents=605000
        )
        assert_fields(
            world.read_request(setup["tender_id"]),
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
            approved_shares_e4=6050000,
            early_repurchase_deduction_cents=12100,
            net_proceeds_cents=592900,
        )
        consumed_lot = world.lot_of_subscription(setup["subscription_a_id"])
        assert_fields(
            consumed_lot,
            original_shares_e4=300000000,
            remaining_shares_e4=293950000,
            status=ShareLotStatus.OPEN,
        )

        # The clock reads 2026-08-26, still inside the 2026-08-31 window bound.
        refused = api.set_subscription_status(
            setup["subscription_a_id"],
            {
                "to_status": SubscriptionStatus.RESCINDED,
                "rejection_reason": "investor changed her mind",
            },
            TRANSFER_AGENT,
        )
        assert_error(refused, ApiErrorId.LOT_PARTIALLY_REPURCHASED, 409)
        assert_fields(
            world.read_subscription(setup["subscription_a_id"]),
            status=SubscriptionStatus.ACCEPTED,
        )

    def test_an_untouched_sibling_lot_still_rescinds_and_reverses_its_money(
        self, world: ReitWorld, api
    ):
        """The holder whose lot was never tendered unwinds, zeroing his position.

        PRD §3.5: "A successful rescission increments the subscription's `version`, sets the minted lot to the terminal `RESCINDED` and zeroes its `remaining_shares_e4`, subtracts the `gross_investment_cents` from both the offering's `gross_proceeds_cents` and the stockholder's `cumulative_invested_cents`, recomputes the class's `shares_outstanding_e4`, the stockholder's `total_shares_e4` and the offering's `aggregate_nav_cents`, re-evaluates `suitability_status` so that a `FLAGGED` stockholder returns to `DOCUMENTED` once the concentration limit is respected again, and moves `account_status` to `CLOSED_NO_POSITION` when the stockholder is left holding no `OPEN` lot at all."

        Design: Corner/errors/rescission_is_barred_once_the_lot_has_been_partially_repurchased
        """
        setup = _pellworth_world(world)

        rescinded = assert_ok(
            api.set_subscription_status(
                setup["subscription_b_id"],
                {
                    "to_status": SubscriptionStatus.RESCINDED,
                    "rejection_reason": "investor changed his mind",
                },
                TRANSFER_AGENT,
            )
        )
        assert_fields(rescinded, status=SubscriptionStatus.RESCINDED)
        assert_fields(
            world.read_investor(setup["untouched_id"]),
            total_shares_e4=0,
            account_status=AccountStatus.CLOSED_NO_POSITION,
        )
        assert_fields(
            world.read_investor(setup["tendering_id"]),
            total_shares_e4=293950000,
            cumulative_early_repurchase_deduction_cents=12100,
        )
        assert_fields(
            world.read_offering(setup["offering_id"]),
            gross_proceeds_cents=30000000,
            aggregate_nav_cents=29395000,
        )
