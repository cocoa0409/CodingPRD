"""Who may drive which write, and what the role gate answers before anything else.

Every test builds the whole of its own world against an empty database, with the
logical clock at its boot instant of 2026-08-01T00:00:00Z (PRD §2.6).
"""

from __future__ import annotations

import pytest

from test_helpers import (
    ADVISOR,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    AccountStatus,
    ApiErrorId,
    EscrowAction,
    EscrowStatus,
    LiquidityEventAction,
    LiquidityEventStatus,
    NavRecordStatus,
    ShareClassStatus,
    SuitabilityStatus,
    assert_created,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    investor_payload,
    make_broker_dealer_rep_headers,
    make_investor_user_headers,
    nav_record_payload,
    offering_payload,
    repurchase_period_payload,
    repurchase_request_payload,
)
from test_helpers.fixtures import ReitWorld


def _quarrenden_world(world: ReitWorld) -> dict:
    """An EFFECTIVE offering, a PROPOSED listing, one stockholder and one period."""
    offering = world.offering(name="Quarrenden Income REIT")
    share_class = world.share_class(offering["id"])
    world.declare_effective(offering["id"])
    event = world.liquidity_event(
        offering["id"], event_type="LISTING", proposed_effective_date="2026-12-01"
    )
    investor = world.investor(
        legal_name="Ulla Sorensen",
        email="ulla.sorensen@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    period = world.repurchase_period(
        offering["id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-10T00:00:00Z",
        settlement_date="2026-08-12",
    )
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "event_id": event["id"],
        "investor_id": investor["id"],
        "period_id": period["id"],
    }


def _wrong_role_calls(api, setup: dict) -> dict:
    """One call per operation, each driven by a role that does not own it."""
    return {
        "escrow_break_as_sponsor": lambda: api.drive_escrow(
            setup["offering_id"], {"action": EscrowAction.BREAK}, SPONSOR
        ),
        "register_offering_as_compliance": lambda: api.create_offering(
            offering_payload(name="Compliance Cannot Register This"), COMPLIANCE
        ),
        "register_firm_as_sponsor": lambda: api.create_broker_dealer(
            {"firm_name": "Sponsor Cannot Register This", "crd_number": "CRD-350001"},
            SPONSOR,
        ),
        "board_approve_as_sponsor": lambda: api.drive_liquidity_event(
            setup["event_id"], {"action": LiquidityEventAction.BOARD_APPROVE}, SPONSOR
        ),
        "tender_as_sponsor": lambda: api.create_repurchase_request(
            repurchase_request_payload(
                setup["period_id"], setup["share_class_id"], 10000
            ),
            SPONSOR,
        ),
        "close_class_as_compliance": lambda: api.set_share_class_status(
            setup["share_class_id"],
            {"to_status": ShareClassStatus.CLOSED_TO_NEW},
            COMPLIANCE,
        ),
        "open_period_as_investor": lambda: api.create_repurchase_period(
            repurchase_period_payload(
                setup["offering_id"],
                period_month="2026-09",
                opens_at="2026-09-01T00:00:00Z",
                request_cutoff_at="2026-09-10T00:00:00Z",
                settlement_date="2026-09-12",
            ),
            make_investor_user_headers(setup["investor_id"]),
        ),
    }


class TestExclusiveOperations:
    """PRD §2.1: the role gate answers before any state precondition is consulted."""

    @pytest.mark.parametrize(
        "operation",
        [
            "escrow_break_as_sponsor",
            "register_offering_as_compliance",
            "register_firm_as_sponsor",
            "board_approve_as_sponsor",
            "tender_as_sponsor",
            "close_class_as_compliance",
            "open_period_as_investor",
        ],
    )
    def test_an_exclusively_owned_operation_refuses_a_foreign_role(
        self, world: ReitWorld, api, operation
    ):
        """Each write owned by one role answers ERR_ROLE_NOT_PERMITTED for another role.

        PRD §2.1: "When the headers are well formed but the acting role is not authorised for the endpoint — or is authorised for the endpoint yet not permitted to drive the specific `action` or `to_status` being requested — the service answers `ERR_ROLE_NOT_PERMITTED` with HTTP 403."
        PRD §2.1: "`SponsorOperator` runs the offering's commercial machinery — creating offerings and share classes, closing a class to new money, taking subscriptions, preparing and publishing valuations, proposing liquidity events, and opening and closing stockholder votes — but may never confirm a valuation it prepared, never pay a distribution, and never approve or execute a liquidity event."
        PRD §2.1: "`ComplianceOfficer` owns registration, escrow, the repurchase plan's suspension and termination authority, broker-dealer registration and supervision, selling agreements and supervision findings, and is the only role that may clear a stockholder whose suitability has been flagged."
        PRD §2.1: "`InvestorUser` tenders shares for repurchase, withdraws its own queued tender, and casts ballots."

        Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
        """
        setup = _quarrenden_world(world)
        response = _wrong_role_calls(api, setup)[operation]()
        assert_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    def test_the_owning_role_passes_the_gate_and_meets_the_business_rule_instead(
        self, world: ReitWorld, api
    ):
        """The same escrow break driven by its owner reaches the fiscal rule, and the other two owners succeed.

        PRD §3.5: "`BREAK` takes `escrow_status` from `COLLECTING` to the terminal `BROKEN` and has three preconditions: the offering's `registration_status` must be `EFFECTIVE`, the accumulated `escrow_balance_cents` must be at least the `minimum_offering_amount_cents` — a shortfall reports `ERR_MINIMUM_OFFERING_NOT_MET` — and the current logical date must be on or before the `escrow_deadline_date`, a late break reporting `ERR_ESCROW_DEADLINE_PASSED`."
        PRD §3.1: "A `SponsorOperator` closes one class to new money by requesting `to_status` of `CLOSED_TO_NEW`, which is permitted only while the parent offering's `registration_status` is `EFFECTIVE` — otherwise `ERR_OFFERING_NOT_EFFECTIVE`."

        Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
        """
        setup = _quarrenden_world(world)

        owner_break = api.drive_escrow(
            setup["offering_id"], {"action": EscrowAction.BREAK}, COMPLIANCE
        )
        assert_error(owner_break, ApiErrorId.MINIMUM_OFFERING_NOT_MET, 422)

        firm = assert_created(
            api.create_broker_dealer(
                {"firm_name": "Quarrenden Placement", "crd_number": "CRD-350002"},
                COMPLIANCE,
            )
        )
        assert firm["crd_number"] == "CRD-350002"

        closed = assert_ok(
            api.set_share_class_status(
                setup["share_class_id"],
                {"to_status": ShareClassStatus.CLOSED_TO_NEW},
                SPONSOR,
            )
        )
        assert_fields(closed, status=ShareClassStatus.CLOSED_TO_NEW)

    def test_a_refusal_at_the_role_gate_writes_and_moves_nothing(
        self, world: ReitWorld, api
    ):
        """After four wrong-role attempts the escrow axis, the event and every collection are untouched.

        PRD §2.1: "When the headers are well formed but the acting role is not authorised for the endpoint — or is authorised for the endpoint yet not permitted to drive the specific `action` or `to_status` being requested — the service answers `ERR_ROLE_NOT_PERMITTED` with HTTP 403."

        Design: Corner/rbac/each_exclusive_operation_refuses_every_other_role
        """
        setup = _quarrenden_world(world)
        calls = _wrong_role_calls(api, setup)
        for operation in (
            "escrow_break_as_sponsor",
            "register_offering_as_compliance",
            "board_approve_as_sponsor",
            "tender_as_sponsor",
            "open_period_as_investor",
        ):
            assert_error(calls[operation](), ApiErrorId.ROLE_NOT_PERMITTED, 403)

        assert_fields(
            world.read_offering(setup["offering_id"]),
            escrow_status=EscrowStatus.COLLECTING,
        )
        assert_fields(
            world.read_liquidity_event(setup["event_id"]),
            status=LiquidityEventStatus.PROPOSED,
        )
        assert_total_count(api.list_offerings(None, SPONSOR), 1)
        assert_total_count(
            api.list_repurchase_periods({"offering_id": setup["offering_id"]}, TRANSFER_AGENT),
            1,
        )
        assert_total_count(
            api.list_repurchase_requests(
                {"repurchase_period_id": setup["period_id"]}, TRANSFER_AGENT
            ),
            0,
        )


class TestSharedOperationsAndTheStatement:
    """PRD §3.2: account opening is shared by three roles; the statement by three others."""

    def test_an_account_may_be_opened_by_three_roles_and_not_by_compliance(
        self, world: ReitWorld, api
    ):
        """A sponsor, a transfer agent and a firm's rep each open an account; compliance is refused.

        PRD §3.2: "An **Investor** account may be opened by a `SponsorOperator`, a `TransferAgent` or a `BrokerDealerRep`."
        PRD §3.2: "New accounts start with `suitability_status` at `INCOMPLETE`, `account_status` at `ACTIVE`, a null `suitability_documentation_reference`, and the running totals `cumulative_invested_cents`, `total_shares_e4`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents` all at zero."

        Design: Corner/rbac/shared_operations_span_their_roles_while_the_statement_stays_narrow
        """
        firm = world.broker_dealer(
            firm_name="Ravensworth Securities", crd_number="CRD-350003"
        )

        by_sponsor = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name="Vera Okonkwo",
                    email="vera.okonkwo@example.com",
                    state_code="TX",
                    net_worth_cents=5000000000,
                    annual_income_cents=1000000000,
                ),
                SPONSOR,
            )
        )
        assert_fields(
            by_sponsor,
            suitability_status=SuitabilityStatus.INCOMPLETE,
            account_status=AccountStatus.ACTIVE,
        )

        by_transfer_agent = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name="Wim Delacroix",
                    email="wim.delacroix@example.com",
                    state_code="TX",
                    net_worth_cents=4000000000,
                    annual_income_cents=900000000,
                ),
                TRANSFER_AGENT,
            )
        )
        assert by_transfer_agent["legal_name"] == "Wim Delacroix"

        by_rep = assert_created(
            api.create_investor(
                investor_payload(
                    legal_name="Xiulan Petrov",
                    email="xiulan.petrov@example.com",
                    state_code="TX",
                    net_worth_cents=3000000000,
                    annual_income_cents=800000000,
                ),
                make_broker_dealer_rep_headers(firm["id"]),
            )
        )
        assert by_rep["legal_name"] == "Xiulan Petrov"

        refused = api.create_investor(
            investor_payload(
                legal_name="Compliance Cannot Open This",
                email="nope.compliance@example.com",
                state_code="TX",
                net_worth_cents=1000000000,
                annual_income_cents=500000000,
            ),
            COMPLIANCE,
        )
        assert_error(refused, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        assert_total_count(api.list_investors(None, COMPLIANCE), 3)

    def test_the_statement_is_narrower_than_the_account_read_it_summarises(
        self, world: ReitWorld, api
    ):
        """Three roles pull an all-zero statement, compliance is refused by role, a stranger by ownership.

        PRD §3.2: "A `TransferAgent`, a `SponsorOperator`, or a stockholder reading its own account may pull a reconciling statement, which is computed rather than stored."
        PRD §3.2: "A stockholder reaching for someone else's statement receives `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/rbac/shared_operations_span_their_roles_while_the_statement_stays_narrow
        """
        owner = world.investor(
            legal_name="Vera Okonkwo",
            email="vera.okonkwo@example.com",
            state_code="TX",
            net_worth_cents=5000000000,
            annual_income_cents=1000000000,
        )
        stranger = world.investor(
            legal_name="Wim Delacroix",
            email="wim.delacroix@example.com",
            state_code="TX",
            net_worth_cents=4000000000,
            annual_income_cents=900000000,
        )

        by_transfer_agent = assert_ok(
            api.get_investor_statement(owner["id"], TRANSFER_AGENT)
        )
        assert_fields(
            by_transfer_agent,
            investor_id=owner["id"],
            total_shares_e4=0,
            open_lot_count=0,
            cumulative_invested_cents=0,
            estimated_value_cents=0,
        )

        by_sponsor = assert_ok(api.get_investor_statement(owner["id"], SPONSOR))
        assert_fields(by_sponsor, total_shares_e4=0)

        by_owner = assert_ok(
            api.get_investor_statement(
                owner["id"], make_investor_user_headers(owner["id"])
            )
        )
        assert_fields(
            by_owner,
            total_shares_e4=0,
            cumulative_early_repurchase_deduction_cents=0,
        )

        assert_error(
            api.get_investor_statement(owner["id"], COMPLIANCE),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        assert_error(
            api.get_investor_statement(
                owner["id"], make_investor_user_headers(stranger["id"])
            ),
            ApiErrorId.NOT_RESOURCE_OWNER,
            403,
        )

        # Only the statement is carved out of the compliance read surface.
        account_read = assert_ok(api.get_investor(owner["id"], COMPLIANCE))
        assert account_read["id"] == owner["id"]


class TestNavSegregationOfDuties:
    """PRD §3.6: no single role can walk a valuation from DRAFT to PUBLISHED."""

    def test_preparing_a_valuation_belongs_to_the_sponsor_alone(
        self, world: ReitWorld, api
    ):
        """Compliance cannot prepare a valuation at all, and the preparer cannot confirm its own.

        PRD §3.6: "A **NavRecord** is prepared by a `SponsorOperator` for one class, identified by `share_class_id`, over a valuation period bounded by `period_start_date` and `period_end_date` — both `YYYY-MM-DD` calendar dates in UTC, both inclusive, with the end date never earlier than the start date."
        PRD §3.6: "When the snapshotted share count is zero, both per-share figures are set to the offering's `initial_offering_price_cents`."
        PRD §3.6: "When no prior published record exists, `variance_bps` is zero."

        Design: Corner/rbac/the_nav_lifecycle_cannot_be_completed_by_any_single_role
        """
        offering = world.offering(name="Silverdale Income REIT")
        share_class = world.share_class(offering["id"])
        body = nav_record_payload(
            share_class["id"],
            share_class["version"],
            period_start_date="2026-07-01",
            period_end_date="2026-07-31",
            gross_asset_value_cents=5000000,
            other_liabilities_cents=0,
        )

        assert_error(
            api.create_nav_record(body, COMPLIANCE), ApiErrorId.ROLE_NOT_PERMITTED, 403
        )
        assert_total_count(
            api.list_nav_records({"share_class_id": share_class["id"]}, SPONSOR), 0
        )

        prepared = assert_created(api.create_nav_record(body, SPONSOR))
        assert_fields(
            prepared,
            status=NavRecordStatus.DRAFT,
            nav_per_share_cents=1000,
            variance_bps=0,
        )

        assert_error(
            api.set_nav_record_status(
                prepared["id"],
                {"to_status": NavRecordStatus.ADVISOR_CONFIRMED},
                SPONSOR,
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )

    def test_publication_needs_the_advisor_and_the_sponsor_in_that_order(
        self, world: ReitWorld, api
    ):
        """The advisor may neither submit nor publish, yet nothing publishes without its confirmation.

        PRD §3.6: "A `SponsorOperator` attempting either of those two movements is refused with `ERR_ROLE_NOT_PERMITTED`, and so is an `IndependentValuationAdvisor` attempting to submit or publish."
        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and records the supplied `advisor_opinion_reference`; where `variance_bps` exceeds 500 basis points that reference is mandatory and a confirmation without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."

        Design: Corner/rbac/the_nav_lifecycle_cannot_be_completed_by_any_single_role
        """
        offering = world.offering(name="Silverdale Income REIT")
        share_class = world.share_class(offering["id"])
        prepared = assert_created(
            api.create_nav_record(
                nav_record_payload(
                    share_class["id"],
                    share_class["version"],
                    period_start_date="2026-07-01",
                    period_end_date="2026-07-31",
                    gross_asset_value_cents=5000000,
                    other_liabilities_cents=0,
                ),
                SPONSOR,
            )
        )

        assert_error(
            api.set_nav_record_status(
                prepared["id"], {"to_status": NavRecordStatus.ADVISOR_REVIEW}, ADVISOR
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        submitted = assert_ok(
            api.set_nav_record_status(
                prepared["id"], {"to_status": NavRecordStatus.ADVISOR_REVIEW}, SPONSOR
            )
        )
        assert_fields(submitted, status=NavRecordStatus.ADVISOR_REVIEW)

        assert_error(
            api.set_nav_record_status(
                prepared["id"], {"to_status": NavRecordStatus.PUBLISHED}, ADVISOR
            ),
            ApiErrorId.ROLE_NOT_PERMITTED,
            403,
        )
        confirmed = assert_ok(
            api.set_nav_record_status(
                prepared["id"],
                {"to_status": NavRecordStatus.ADVISOR_CONFIRMED},
                ADVISOR,
            )
        )
        assert_fields(confirmed, status=NavRecordStatus.ADVISOR_CONFIRMED)

        published = assert_ok(
            api.set_nav_record_status(
                prepared["id"], {"to_status": NavRecordStatus.PUBLISHED}, SPONSOR
            )
        )
        assert_fields(published, status=NavRecordStatus.PUBLISHED)
        assert_fields(world.read_offering(offering["id"]), aggregate_nav_cents=0)
