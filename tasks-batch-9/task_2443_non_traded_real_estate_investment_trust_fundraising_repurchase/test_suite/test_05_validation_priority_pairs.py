"""Pairs of simultaneously broken rules, pinned to the PRD §2.9 ordering.

Each pair is built so that one request violates two rules at once. The suite
asserts which code comes back, and then removes only the higher-priority
violation and re-sends the identical body so the lower-priority code surfaces.
That flip is what distinguishes a correctly ordered ladder from an
implementation that merely happens to emit the right code first.
"""

from typing import Any, Dict

from test_helpers import (
    SPONSOR,
    TRANSFER_AGENT,
    ApiClient,
    ApiErrorId,
    ClassCode,
    DeclarationStatus,
    HardshipType,
    RegistrationAction,
    RegistrationStatus,
    RepurchasePeriodStatus,
    RepurchaseRequestStatus,
    SubscriptionStatus,
    assert_created,
    assert_error,
    assert_fields,
    declaration_payload,
    make_investor_user_headers,
    repurchase_request_payload,
    subscription_payload,
)
from test_helpers.fixtures import ReitWorld

# ─── Chain builders ───────────────────────────────────────────────────


def _build_suspended_offering_near_its_ceiling(world: ReitWorld) -> Dict[str, Any]:
    """An offering at 20,000,000 cents raised against a 20,500,000-cent ceiling.

    Escrow is BROKEN so the whole balance sits in ``gross_proceeds_cents``, and
    registration is then SUSPENDED. The documented stockholder is wealthy enough
    that no investor-protection gate can fire (PRD §3.1, §3.4, §3.5).
    """
    offering = world.offering(
        name="Ashford Core Plus REIT",
        minimum_offering_amount_cents=20000000,
        maximum_offering_amount_cents=20500000,
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
        firm_name="Ashford Selling Group", crd_number="CRD-110001"
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
        legal_name="Jonas Ferreira",
        email="jonas.ferreira@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    first = world.subscription(
        offering["id"],
        share_class["id"],
        investor["id"],
        agreement["id"],
        20000000,
    )
    world.escrow_subscription(first["id"])
    world.break_escrow(offering["id"])
    world.drive_registration(
        offering["id"], RegistrationAction.SUSPEND, reason="SUPPLEMENT_UNDER_REVIEW"
    )

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "investor_id": investor["id"],
        "agreement_id": agreement["id"],
    }


def _build_open_period_over_a_small_position(world: ReitWorld) -> Dict[str, Any]:
    """A 2026-09 period whose window has already closed, over a 3,000,500 e4 holding.

    An anchor stockholder supplies the bulk of the valuation base; Dana Pike
    holds the small position the oversized tender will be measured against. The
    clock is parked one day past the cutoff (PRD §3.6, §3.8).
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

    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
    world.published_nav(
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
    world.set_clock("2026-09-26T00:00:00Z", TRANSFER_AGENT)

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "holder_id": holder["id"],
        "period_id": period["id"],
    }


def _build_offering_with_a_stale_version_in_hand(world: ReitWorld) -> Dict[str, Any]:
    """A funded offering whose version was read one write too early.

    The offering version is captured before the escrow break, which increments
    it, so the captured echo is stale by exactly one write while the re-read
    value is fresh (PRD §2.8, §3.5).
    """
    offering = world.offering(
        name="Wexley Diversified REIT",
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
        firm_name="Wexley Placement LLC", crd_number="CRD-120001"
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
        legal_name="Wren Halloran",
        email="wren.halloran@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    subscription = world.subscription(
        offering["id"], share_class["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])

    stale_version = world.offering_version(offering["id"])
    world.break_escrow(offering["id"])
    fresh_version = world.offering_version(offering["id"])
    world.set_clock("2026-09-02T00:00:00Z", SPONSOR)

    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "stale_version": stale_version,
        "fresh_version": fresh_version,
    }


def _uncovered_declaration_body(offering_id: str, version: int) -> Dict[str, Any]:
    """The one declaration body used by all three calls, varying only the echo.

    Adjusted cash flow of 90,000 cents against a 150,000-cent declared total is
    6,000 basis points of coverage, so the uncovered gate applies (PRD §3.7).
    """
    return declaration_payload(
        offering_id,
        version,
        record_date="2026-08-31",
        payment_date="2026-09-15",
        declared_per_share_cents=5,
        gaap_net_income_cents=60000,
        adjusted_cash_flow_cents=90000,
        board_uncovered_acknowledgement=False,
    )


# ─── Suspended registration vs the registered ceiling ─────────────────


class TestOfferingNotEffectiveOutranksTheRegisteredMaximum:
    """PRD §2.9: the money ceiling is the last thing checked, below offering state."""

    def test_suspended_registration_is_reported_ahead_of_the_breached_maximum(
        self, api: ApiClient, world: ReitWorld
    ):
        """A ticket that both misses an effective offering and breaches the ceiling reports the offering state.

        PRD §2.9: "Being last means a subscription aimed at a suspended offering
        reports `ERR_OFFERING_NOT_EFFECTIVE` rather than
        `ERR_OFFERING_MAXIMUM_EXCEEDED` even when it would also breach the
        registered maximum."

        Design: Difficulty/priority_pair_validation_conflict/offering_not_effective_outranks_offering_maximum_exceeded
        """
        ids = _build_suspended_offering_near_its_ceiling(world)
        assert_fields(
            world.read_offering(ids["offering_id"]),
            registration_status=RegistrationStatus.SUSPENDED,
            gross_proceeds_cents=20000000,
        )

        response = api.create_subscription(
            subscription_payload(
                ids["offering_id"],
                ids["share_class_id"],
                ids["investor_id"],
                ids["agreement_id"],
                gross_investment_cents=600000,
            ),
            SPONSOR,
        )

        assert_error(response, ApiErrorId.OFFERING_NOT_EFFECTIVE, 409)

    def test_reinstating_registration_lets_the_identical_body_report_the_maximum(
        self, api: ApiClient, world: ReitWorld
    ):
        """With the higher-priority violation removed, the same 600,000-cent ticket reports the ceiling.

        PRD §3.1: "`REINSTATE` returns `SUSPENDED` to `EFFECTIVE`, but only while
        `escrow_status` is not `FAILED`; a reinstatement attempt on an offering
        whose escrow has failed is refused with `ERR_INVALID_STATE_TRANSITION`,
        since a failed escrow is terminal and there is nothing left to sell
        into."
        PRD §3.4: "Last of all, the offering's `gross_proceeds_cents` plus this
        subscription's `gross_investment_cents` must not exceed
        `maximum_offering_amount_cents`, or the subscription reports
        `ERR_OFFERING_MAXIMUM_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/offering_not_effective_outranks_offering_maximum_exceeded
        """
        ids = _build_suspended_offering_near_its_ceiling(world)
        body = subscription_payload(
            ids["offering_id"],
            ids["share_class_id"],
            ids["investor_id"],
            ids["agreement_id"],
            gross_investment_cents=600000,
        )
        assert_error(
            api.create_subscription(body, SPONSOR),
            ApiErrorId.OFFERING_NOT_EFFECTIVE,
            409,
        )

        world.drive_registration(ids["offering_id"], RegistrationAction.REINSTATE)

        assert_error(
            api.create_subscription(body, SPONSOR),
            ApiErrorId.OFFERING_MAXIMUM_EXCEEDED,
            422,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]),
            registration_status=RegistrationStatus.EFFECTIVE,
            gross_proceeds_cents=20000000,
        )

    def test_a_ticket_landing_exactly_on_the_registered_maximum_is_accepted(
        self, api: ApiClient, world: ReitWorld
    ):
        """500,000 cents brings the raise to exactly the ceiling, which is not an excess.

        PRD §3.4: "Last of all, the offering's `gross_proceeds_cents` plus this
        subscription's `gross_investment_cents` must not exceed
        `maximum_offering_amount_cents`, or the subscription reports
        `ERR_OFFERING_MAXIMUM_EXCEEDED`."
        PRD §3.4: "If there are none, the price is the offering's
        `initial_offering_price_cents`."
        PRD §3.4: "A freshly authored subscription sits in `PENDING` with a null
        `rejection_reason` and a null `accepted_at`."

        Design: Difficulty/priority_pair_validation_conflict/offering_not_effective_outranks_offering_maximum_exceeded
        """
        ids = _build_suspended_offering_near_its_ceiling(world)
        world.drive_registration(ids["offering_id"], RegistrationAction.REINSTATE)

        response = api.create_subscription(
            subscription_payload(
                ids["offering_id"],
                ids["share_class_id"],
                ids["investor_id"],
                ids["agreement_id"],
                gross_investment_cents=500000,
            ),
            SPONSOR,
        )

        created = assert_created(response)
        assert_fields(
            created,
            status=SubscriptionStatus.PENDING,
            transaction_price_cents=1000,
            net_invested_cents=500000,
        )
        assert_fields(
            world.read_offering(ids["offering_id"]), gross_proceeds_cents=20000000
        )


# ─── A closed window vs an unavailable position ───────────────────────


class TestRepurchasePeriodClosedOutranksInsufficientShares:
    """PRD §2.9: window membership is settled before any quantity is looked at."""

    def test_a_tender_past_the_cutoff_reports_the_closed_window_not_the_shortfall(
        self, api: ApiClient, world: ReitWorld
    ):
        """An oversized tender filed after the cutoff reports the window, not the missing shares.

        PRD §2.9: "Window membership is decided before any quantity is examined,
        so a tender filed after a period's cutoff reports
        `ERR_REPURCHASE_PERIOD_CLOSED` even if the stockholder also lacks the
        shares."

        Design: Difficulty/priority_pair_validation_conflict/repurchase_period_closed_outranks_insufficient_shares
        """
        ids = _build_open_period_over_a_small_position(world)

        response = api.create_repurchase_request(
            repurchase_request_payload(
                ids["period_id"],
                ids["share_class_id"],
                99999999,
                hardship_type=HardshipType.NONE,
            ),
            make_investor_user_headers(ids["holder_id"]),
        )

        assert_error(response, ApiErrorId.REPURCHASE_PERIOD_CLOSED, 409)

    def test_the_same_oversized_tender_inside_the_window_reports_the_shortfall(
        self, api: ApiClient, world: ReitWorld
    ):
        """Move the clock back inside the window and the quantity check finally runs.

        PRD §3.8: "The plan must be `ACTIVE`; the current logical clock must fall
        inside the half-open window, so a tender filed before `opens_at` or at or
        after `request_cutoff_at` is refused with
        `ERR_REPURCHASE_PERIOD_CLOSED`; and the shares must actually be there —
        `shares_requested_e4` may not exceed what the stockholder holds across
        `OPEN` lots in that class, net of shares already tendered in that
        stockholder's other `QUEUED` or `HELD` requests in the same period, or
        the tender is refused with `ERR_INSUFFICIENT_SHARES`."

        Design: Difficulty/priority_pair_validation_conflict/repurchase_period_closed_outranks_insufficient_shares
        """
        ids = _build_open_period_over_a_small_position(world)
        body = repurchase_request_payload(
            ids["period_id"],
            ids["share_class_id"],
            99999999,
            hardship_type=HardshipType.NONE,
        )
        headers = make_investor_user_headers(ids["holder_id"])
        assert_error(
            api.create_repurchase_request(body, headers),
            ApiErrorId.REPURCHASE_PERIOD_CLOSED,
            409,
        )

        world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)

        assert_error(
            api.create_repurchase_request(body, headers),
            ApiErrorId.INSUFFICIENT_SHARES,
            422,
        )
        assert_fields(
            world.read_period(ids["period_id"]), status=RepurchasePeriodStatus.OPEN
        )

    def test_a_tender_within_the_position_is_queued_with_zero_valuation_fields(
        self, api: ApiClient, world: ReitWorld
    ):
        """A tender that clears both gates is queued, owned by the caller, and valued at zero.

        PRD §3.8: "A filed tender sits in `QUEUED` with `requested_value_cents`,
        `approved_value_cents`, `approved_shares_e4`,
        `early_repurchase_deduction_cents` and `net_proceeds_cents` all at zero
        until the period is processed."
        PRD §3.8: "The `investor_id` is never supplied in the payload; it is
        taken from the acting stockholder's `X-User-ID`."

        Design: Difficulty/priority_pair_validation_conflict/repurchase_period_closed_outranks_insufficient_shares
        """
        ids = _build_open_period_over_a_small_position(world)
        world.set_clock("2026-09-05T00:00:00Z", TRANSFER_AGENT)

        response = api.create_repurchase_request(
            repurchase_request_payload(
                ids["period_id"],
                ids["share_class_id"],
                1000000,
                hardship_type=HardshipType.NONE,
            ),
            make_investor_user_headers(ids["holder_id"]),
        )

        tender = assert_created(response)
        assert_fields(
            tender,
            status=RepurchaseRequestStatus.QUEUED,
            shares_requested_e4=1000000,
            hardship_type=HardshipType.NONE,
            investor_id=ids["holder_id"],
            requested_value_cents=0,
            approved_value_cents=0,
            approved_shares_e4=0,
            early_repurchase_deduction_cents=0,
            net_proceeds_cents=0,
        )
        assert_fields(
            world.read_period(ids["period_id"]), status=RepurchasePeriodStatus.OPEN
        )


# ─── A stale version echo vs the uncovered-distribution gate ──────────


class TestStaleOfferingVersionOutranksTheUncoveredGate:
    """PRD §2.9: the concurrency check sits above every state and business rule."""

    def test_a_stale_version_echo_is_reported_ahead_of_the_uncovered_gate(
        self, api: ApiClient, world: ReitWorld
    ):
        """A declaration that is both stale and unacknowledged reports the stale echo with 412.

        PRD §2.9: "Because this level sits above every state and business rule, a
        stale echo is reported even when the request would also have failed a
        later check."
        PRD §2.8: "If that value does not equal the offering's currently stored
        `version`, the write is rejected with `ERR_STALE_OFFERING_VERSION` and
        HTTP 412, and nothing at all is mutated."

        Design: Difficulty/priority_pair_validation_conflict/stale_offering_version_outranks_uncovered_distribution_gate
        """
        ids = _build_offering_with_a_stale_version_in_hand(world)
        assert ids["stale_version"] < ids["fresh_version"], (
            "breaking escrow must increment the offering version so the captured "
            f"echo {ids['stale_version']} is genuinely stale"
        )

        response = api.create_distribution_declaration(
            _uncovered_declaration_body(ids["offering_id"], ids["stale_version"]),
            SPONSOR,
        )

        assert_error(response, ApiErrorId.STALE_OFFERING_VERSION, 412)
        assert_fields(
            world.read_offering(ids["offering_id"]), version=ids["fresh_version"]
        )

    def test_the_fresh_echo_surfaces_the_unacknowledged_uncovered_distribution(
        self, api: ApiClient, world: ReitWorld
    ):
        """Repair only the echo and the identical body reports the coverage gate with 422.

        PRD §3.7: "When `coverage_ratio_cash_bps` is below 10,000 basis points
        the distribution is not fully covered by adjusted cash flow, and the
        board must have said so: if `board_uncovered_acknowledgement` is false
        the declaration is refused with
        `ERR_UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED`."

        Design: Difficulty/priority_pair_validation_conflict/stale_offering_version_outranks_uncovered_distribution_gate
        """
        ids = _build_offering_with_a_stale_version_in_hand(world)
        assert_error(
            api.create_distribution_declaration(
                _uncovered_declaration_body(ids["offering_id"], ids["stale_version"]),
                SPONSOR,
            ),
            ApiErrorId.STALE_OFFERING_VERSION,
            412,
        )

        response = api.create_distribution_declaration(
            _uncovered_declaration_body(ids["offering_id"], ids["fresh_version"]),
            SPONSOR,
        )

        assert_error(
            response, ApiErrorId.UNCOVERED_DISTRIBUTION_UNACKNOWLEDGED, 422
        )

    def test_an_acknowledged_uncovered_declaration_reports_both_coverage_bases(
        self, api: ApiClient, world: ReitWorld
    ):
        """With the board acknowledgement set, the declaration lands and discloses both bases.

        PRD §3.7: "The declared total is built class by class:
        `total_declared_cents` is the sum, over every share class of the
        offering, of the `declared_per_share_cents` multiplied by that class's
        `shares_outstanding_e4`, divided by 10,000 and rounded half up to a whole
        cent — again each class's contribution rounded independently before
        summation."
        PRD §3.7: "Full coverage is 10,000 basis points, so the disclosed return
        of capital on each basis is what the coverage falls short of full:
        `return_of_capital_bps` is the greater of zero and 10,000 less
        `coverage_ratio_cash_bps`, while `gaap_return_of_capital_bps` is the
        greater of zero and 10,000 less `coverage_ratio_gaap_bps`."
        PRD §3.7: "A new declaration opens `DECLARED` with
        `total_distribution_fee_accrued_cents` at zero."

        Design: Difficulty/priority_pair_validation_conflict/stale_offering_version_outranks_uncovered_distribution_gate
        """
        ids = _build_offering_with_a_stale_version_in_hand(world)
        body = _uncovered_declaration_body(ids["offering_id"], ids["fresh_version"])
        body["board_uncovered_acknowledgement"] = True

        response = api.create_distribution_declaration(body, SPONSOR)

        declaration = assert_created(response)
        assert_fields(
            declaration,
            total_declared_cents=150000,
            coverage_ratio_gaap_bps=4000,
            coverage_ratio_cash_bps=6000,
            return_of_capital_bps=4000,
            gaap_return_of_capital_bps=6000,
            board_uncovered_acknowledgement=True,
            status=DeclarationStatus.DECLARED,
            total_distribution_fee_accrued_cents=0,
        )
        assert_fields(
            world.read_share_class(ids["share_class_id"]),
            shares_outstanding_e4=300000000,
        )
