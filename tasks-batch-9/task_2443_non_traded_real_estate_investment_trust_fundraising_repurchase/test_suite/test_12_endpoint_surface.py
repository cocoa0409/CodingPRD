"""Endpoint-surface coverage for the Non-Traded REIT Fundraising & Repurchase API.

These tests exercise the reads and action endpoints that have no other way in:
the computed stockholder statement of PRD §3.8, the filtered collections of
PRD §2.3 and §2.7 that are the only route to a cascade-minted share lot, and the
two repurchase-plan action endpoints of PRD §3.8. The service is restarted before
each test, so the database is empty and the logical clock reads its boot instant
of 2026-08-01T00:00:00Z until a test moves it.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    ApiClient,
    ApiErrorId,
    ClassCode,
    RepurchasePeriodStatus,
    RepurchasePlanAction,
    RepurchasePlanStatus,
    RepurchaseRequestStatus,
    ShareLotStatus,
    SubscriptionStatus,
    assert_created,
    assert_envelope_meta,
    assert_error,
    assert_fields,
    assert_ok,
    assert_total_count,
    investor_payload,
    make_investor_user_headers,
    repurchase_period_payload,
    repurchase_request_payload,
)
from test_helpers.fixtures import ReitWorld

_ZERO_LOAD_CLASS: Dict[str, Any] = {
    "upfront_selling_commission_bps": 0,
    "dealer_manager_fee_bps": 0,
    "annual_distribution_fee_bps": 0,
    "distribution_fee_cap_bps": 0,
}

_AUGUST_PERIOD: Dict[str, Any] = {
    "period_month": "2026-08",
    "opens_at": "2026-08-01T00:00:00Z",
    "request_cutoff_at": "2026-08-26T00:00:00Z",
    "settlement_date": "2026-08-30",
}


def _offering(name: str) -> Dict[str, Any]:
    return {
        "name": name,
        "minimum_offering_amount_cents": 30000000,
        "maximum_offering_amount_cents": 50000000000,
        "escrow_deadline_date": "2026-12-31",
        "initial_offering_price_cents": 1000,
    }


def _settled_statement_world(api: ApiClient, world: ReitWorld) -> Dict[str, Any]:
    """One 30,000,000-cent class I holding, cut back to 600,000 cents by an August run."""
    rows = world.effective_offering(
        offering=_offering("Estuary Income REIT"),
        share_class={"class_code": ClassCode.I, **_ZERO_LOAD_CLASS},
        agreement={"max_commission_bps": 100},
    )
    investor = assert_created(
        api.create_investor(
            investor_payload(
                legal_name="Oona Ferreira",
                email="oona.ferreira@example.com",
                state_code="TX",
                net_worth_cents=5000000000,
                annual_income_cents=1000000000,
            ),
            TRANSFER_AGENT,
        )
    )
    world.document_suitability(investor["id"], "SUIT-OONA-2026-08")
    subscription = world.subscription(
        rows["offering_id"],
        rows["share_class_id"],
        investor["id"],
        rows["selling_agreement_id"],
        30000000,
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(rows["offering_id"])

    published = world.published_nav(
        rows["share_class_id"], "2026-07-01", "2026-07-31", 30000000
    )
    assert_fields(published, nav_per_share_cents=1000)

    period = world.repurchase_period(rows["offering_id"], **_AUGUST_PERIOD)
    tender = world.tender(
        period["id"], rows["share_class_id"], 10000000, investor["id"]
    )
    world.set_clock("2026-08-26T00:00:00Z")
    processed = world.process_period(period["id"])
    assert_fields(processed, capacity_cents=600000, settled_amount_cents=600000)

    rows["investor_id"] = investor["id"]
    rows["subscription_id"] = subscription["id"]
    rows["period_id"] = period["id"]
    rows["request_id"] = tender["id"]
    return rows


def _cascade_minted_lot_world(api: ApiClient, world: ReitWorld) -> Dict[str, Any]:
    """Two zero-load classes, one accepted class I subscription, one minted lot."""
    offering = world.offering(**_offering("Fernbank Core REIT"))
    class_i = world.share_class(offering["id"], class_code=ClassCode.I, **_ZERO_LOAD_CLASS)
    class_t = world.share_class(offering["id"], class_code=ClassCode.T, **_ZERO_LOAD_CLASS)
    firm = world.broker_dealer(firm_name="Fernbank Placement", crd_number="CRD-330002")
    world.declare_effective(offering["id"])
    agreement = world.selling_agreement(
        offering["id"], firm["id"], max_commission_bps=100
    )
    world.activate_agreement(agreement["id"])
    investor = world.documented_investor(
        legal_name="Pia Rosenlund",
        email="pia.rosenlund@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    subscription = world.subscription(
        offering["id"], class_i["id"], investor["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(offering["id"])
    return {
        "offering_id": offering["id"],
        "class_i_id": class_i["id"],
        "class_t_id": class_t["id"],
        "investor_id": investor["id"],
        "subscription_id": subscription["id"],
    }


def _queued_tender_world(world: ReitWorld) -> Dict[str, Any]:
    """An OPEN August period carrying two QUEUED tenders against a 300000000 e4 holding."""
    rows = world.effective_offering(
        offering=_offering("Gladstone Income REIT"),
        share_class={"class_code": ClassCode.I, **_ZERO_LOAD_CLASS},
        agreement={"max_commission_bps": 100},
    )
    investor = world.documented_investor(
        legal_name="Quinn Adeyemi",
        email="quinn.adeyemi@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    subscription = world.subscription(
        rows["offering_id"],
        rows["share_class_id"],
        investor["id"],
        rows["selling_agreement_id"],
        30000000,
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(rows["offering_id"])
    period = world.repurchase_period(rows["offering_id"], **_AUGUST_PERIOD)
    first = world.tender(
        period["id"], rows["share_class_id"], 100000000, investor["id"]
    )
    second = world.tender(
        period["id"], rows["share_class_id"], 50000000, investor["id"]
    )
    rows["investor_id"] = investor["id"]
    rows["period_id"] = period["id"]
    rows["first_request_id"] = first["id"]
    rows["second_request_id"] = second["id"]
    return rows


def _empty_period_world(world: ReitWorld) -> Dict[str, Any]:
    """An EFFECTIVE offering with no money at all and one empty August period."""
    offering = world.offering(**_offering("Halewood Core REIT"))
    share_class = world.share_class(
        offering["id"], class_code=ClassCode.I, **_ZERO_LOAD_CLASS
    )
    world.declare_effective(offering["id"])
    period = world.repurchase_period(offering["id"], **_AUGUST_PERIOD)
    assert_fields(period, status=RepurchasePeriodStatus.OPEN, quarter_key="2026-Q3")
    return {
        "offering_id": offering["id"],
        "share_class_id": share_class["id"],
        "period_id": period["id"],
    }


class TestInvestorStatement:
    """PRD §3.8 — the stockholder statement is computed from open lots at read time."""

    def test_statement_reconciles_the_remaining_lot_after_a_partial_settlement(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """After a 600,000-cent partial fill the statement reports one open lot worth 29,400,000 cents.

        PRD §3.8: "A `TransferAgent`, a `SponsorOperator`, or a stockholder reading its own account may pull a reconciling statement, which is computed rather than stored."
        PRD §3.8: "It reports the `investor_id`, the current `total_shares_e4`, an `open_lot_count` giving the number of lots for that stockholder whose status is `OPEN`, the `cumulative_invested_cents`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents` copied from the account row, and an `estimated_value_cents` computed as the sum over those open lots of each lot's `remaining_shares_e4` multiplied by the transaction price of the class the lot currently sits in, divided by 10,000 and rounded half up — once again each lot's contribution rounded on its own before summation."
        PRD §3.8: "The request records `early_repurchase_deduction_cents` as the sum of its per-lot deductions and `net_proceeds_cents` as the sum of its per-lot gross amounts each less that lot's deduction, and the deduction total is added to the stockholder's `cumulative_early_repurchase_deduction_cents`."

        Design: Corner/endpoints/investor_statement_reconciles_holdings_after_a_partial_settlement
        """
        rows = _settled_statement_world(api, world)
        assert_fields(
            world.read_request(rows["request_id"]),
            status=RepurchaseRequestStatus.PARTIALLY_FULFILLED,
            approved_value_cents=600000,
            approved_shares_e4=6000000,
            early_repurchase_deduction_cents=12000,
            net_proceeds_cents=588000,
        )

        statement = assert_ok(
            api.get_investor_statement(rows["investor_id"], TRANSFER_AGENT)
        )
        assert_fields(
            statement,
            investor_id=rows["investor_id"],
            total_shares_e4=294000000,
            open_lot_count=1,
            cumulative_invested_cents=30000000,
            cumulative_distributions_received_cents=0,
            cumulative_early_repurchase_deduction_cents=12000,
            estimated_value_cents=29400000,
        )

    def test_stockholder_reading_its_own_account_sees_the_same_computed_statement(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """The stockholder's own read of its statement returns the same estimated value as the transfer agent's.

        PRD §3.8: "A `TransferAgent`, a `SponsorOperator`, or a stockholder reading its own account may pull a reconciling statement, which is computed rather than stored."
        PRD §3.8: "It reports the `investor_id`, the current `total_shares_e4`, an `open_lot_count` giving the number of lots for that stockholder whose status is `OPEN`, the `cumulative_invested_cents`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents` copied from the account row, and an `estimated_value_cents` computed as the sum over those open lots of each lot's `remaining_shares_e4` multiplied by the transaction price of the class the lot currently sits in, divided by 10,000 and rounded half up — once again each lot's contribution rounded on its own before summation."

        Design: Corner/endpoints/investor_statement_reconciles_holdings_after_a_partial_settlement
        """
        rows = _settled_statement_world(api, world)

        own_statement = assert_ok(
            api.get_investor_statement(
                rows["investor_id"], make_investor_user_headers(rows["investor_id"])
            )
        )
        assert_fields(
            own_statement,
            investor_id=rows["investor_id"],
            total_shares_e4=294000000,
            open_lot_count=1,
            estimated_value_cents=29400000,
        )


class TestCascadeMintedLotReads:
    """PRD §2.3, §2.7, §3.5 — a lot has no write endpoint, only filtered reads."""

    def test_minted_lot_is_reachable_through_each_declared_lot_filter(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """The lot an escrow break minted is selected by its subscription, holder and status, and by nothing else.

        PRD §3.5: "Lots themselves are never written directly."
        PRD §3.5: "They are read, filterable by the subscription that minted them, the holder, the class they now sit in, the class they converted out of, or their status, and each is individually addressable so that a transfer agent can audit `remaining_shares_e4` and `cumulative_distribution_fee_cents` lot by lot."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, a boolean that is true when rows remain beyond the current page."

        Design: Corner/endpoints/cascade_created_lots_are_reachable_only_through_filtered_collections
        """
        rows = _cascade_minted_lot_world(api, world)

        by_subscription = api.list_share_lots(
            {"subscription_id": rows["subscription_id"]}, TRANSFER_AGENT
        )
        lots = assert_total_count(by_subscription, 1)
        assert assert_envelope_meta(by_subscription)["has_more"] is False
        assert_fields(
            lots[0],
            original_shares_e4=300000000,
            share_class_id=rows["class_i_id"],
        )

        by_holder = api.list_share_lots(
            {"investor_id": rows["investor_id"], "status": ShareLotStatus.OPEN},
            TRANSFER_AGENT,
        )
        assert_total_count(by_holder, 1)

        by_sibling_class = api.list_share_lots(
            {"share_class_id": rows["class_t_id"]}, TRANSFER_AGENT
        )
        assert_total_count(by_sibling_class, 0)

        by_closed_status = api.list_share_lots(
            {"status": ShareLotStatus.CLOSED}, TRANSFER_AGENT
        )
        assert_total_count(by_closed_status, 0)

    def test_sibling_collections_count_only_the_rows_matching_each_filter(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """The accepted subscription, the two classes and the absent valuations are each counted by filter, not by table.

        PRD §2.7: "Share classes may be filtered by `offering_id`, `class_code` and `status`; investors by `suitability_status`, `account_status` and `state_code`; broker-dealers by `supervision_status` and `crd_number`; selling agreements by `offering_id`, `broker_dealer_id` and `status`; subscriptions by `offering_id`, `share_class_id`, `investor_id`, `selling_agreement_id` and `status`; share lots by `subscription_id`, `investor_id`, `share_class_id`, `converted_from_share_class_id` and `status`; valuation records by `share_class_id`, `status` and `period_end_date`; declarations by `offering_id`, `status` and `record_date`; repurchase periods by `offering_id`, `status`, `quarter_key` and `period_month`; repurchase requests by `repurchase_period_id`, `investor_id`, `share_class_id`, `status` and `hardship_type`; liquidity events by `offering_id`, `status` and `event_type`; ballots by `liquidity_event_id`, `investor_id` and `choice`; and offerings by `registration_status`, `escrow_status` and `repurchase_plan_status`."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` — the total number of rows matching the filters, not the number returned on this page — and `has_more`, a boolean that is true when rows remain beyond the current page."
        PRD §3.5: "The offering's `version` increments; every subscription of the offering in `ESCROWED` is moved to `ACCEPTED` in ascending `created_at` order; one share lot is minted per accepted subscription with `issued_date` set to the current logical clock instant; `shares_outstanding_e4` on every touched class and `total_shares_e4` on every touched stockholder are recomputed; each affected stockholder's `cumulative_invested_cents` is recomputed and their `suitability_status` re-evaluated against `concentration_limit_cents`, so a stockholder pushed over the limit by the batch lands in `FLAGGED`; and the whole of `escrow_balance_cents` is moved into `gross_proceeds_cents`."

        Design: Corner/endpoints/cascade_created_lots_are_reachable_only_through_filtered_collections
        """
        rows = _cascade_minted_lot_world(api, world)

        assert_total_count(
            api.list_subscriptions({"status": SubscriptionStatus.ACCEPTED}, TRANSFER_AGENT), 1
        )
        assert_total_count(
            api.list_subscriptions({"status": SubscriptionStatus.PENDING}, TRANSFER_AGENT), 0
        )
        assert_total_count(
            api.list_share_classes({"offering_id": rows["offering_id"]}, SPONSOR), 2
        )
        assert_total_count(
            api.list_nav_records({"share_class_id": rows["class_i_id"]}, SPONSOR), 0
        )


class TestRepurchasePlanTermination:
    """PRD §3.8 — TERMINATE cancels the open period and locks the axis for good."""

    def test_terminating_the_plan_cancels_the_open_period_and_rejects_its_tenders(
        self, world: ReitWorld
    ) -> None:
        """One TERMINATE call cancels the OPEN period and rejects both queued tenders without settling anything.

        PRD §3.8: "`TERMINATE` is reachable from both `ACTIVE` and `SUSPENDED`, moves the axis to the terminal `TERMINATED`, increments `version`, drives every `OPEN` or `SUSPENDED` period of the offering to the terminal `CANCELLED`, and drives every `QUEUED` or `HELD` tender in those periods to the terminal `REJECTED`."
        PRD §3.8: "A filed tender sits in `QUEUED` with `requested_value_cents`, `approved_value_cents`, `approved_shares_e4`, `early_repurchase_deduction_cents` and `net_proceeds_cents` all at zero until the period is processed."

        Design: Corner/endpoints/terminating_the_repurchase_plan_cancels_periods_and_locks_the_axis
        """
        rows = _queued_tender_world(world)

        terminated = world.drive_repurchase_plan(
            rows["offering_id"],
            RepurchasePlanAction.TERMINATE,
            reason="plan wound down ahead of a listing",
        )
        assert_fields(
            terminated, repurchase_plan_status=RepurchasePlanStatus.TERMINATED
        )

        assert_fields(
            world.read_period(rows["period_id"]),
            status=RepurchasePeriodStatus.CANCELLED,
            settled_amount_cents=0,
        )
        for request_id in (rows["first_request_id"], rows["second_request_id"]):
            assert_fields(
                world.read_request(request_id),
                status=RepurchaseRequestStatus.REJECTED,
                approved_value_cents=0,
            )
        assert_fields(world.read_investor(rows["investor_id"]), total_shares_e4=300000000)

    def test_terminated_plan_refuses_resumption_new_periods_and_new_tenders(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """A TERMINATED plan is terminal on its own axis and gates period and tender creation, leaving the other two axes alone.

        PRD §3.8: "`TERMINATE` is reachable from both `ACTIVE` and `SUSPENDED`, moves the axis to the terminal `TERMINATED`, increments `version`, drives every `OPEN` or `SUSPENDED` period of the offering to the terminal `CANCELLED`, and drives every `QUEUED` or `HELD` tender in those periods to the terminal `REJECTED`."
        PRD §3.8: "While the plan is `SUSPENDED` or `TERMINATED`, opening a period, filing a tender and processing a period all fail with `ERR_REPURCHASE_PLAN_SUSPENDED`."
        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.10: "A change on one axis never implies a change on another unless a rule in §3 says so explicitly."

        Design: Corner/endpoints/terminating_the_repurchase_plan_cancels_periods_and_locks_the_axis
        """
        rows = _queued_tender_world(world)
        world.drive_repurchase_plan(
            rows["offering_id"],
            RepurchasePlanAction.TERMINATE,
            reason="plan wound down ahead of a listing",
        )

        resume = api.drive_repurchase_plan(
            rows["offering_id"], {"action": RepurchasePlanAction.RESUME}, COMPLIANCE
        )
        assert_error(resume, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        new_period = api.create_repurchase_period(
            repurchase_period_payload(
                offering_id=rows["offering_id"],
                period_month="2026-09",
                opens_at="2026-09-01T00:00:00Z",
                request_cutoff_at="2026-09-26T00:00:00Z",
                settlement_date="2026-09-30",
            ),
            TRANSFER_AGENT,
        )
        assert_error(new_period, ApiErrorId.REPURCHASE_PLAN_SUSPENDED, 409)

        new_tender = api.create_repurchase_request(
            repurchase_request_payload(
                repurchase_period_id=rows["period_id"],
                share_class_id=rows["share_class_id"],
                shares_requested_e4=1000000,
            ),
            make_investor_user_headers(rows["investor_id"]),
        )
        assert_error(new_tender, ApiErrorId.REPURCHASE_PLAN_SUSPENDED, 409)

        offering = world.read_offering(rows["offering_id"])
        assert_fields(
            offering,
            registration_status="EFFECTIVE",
            escrow_status="BROKEN",
            repurchase_plan_status=RepurchasePlanStatus.TERMINATED,
        )
        assert_total_count(
            api.list_repurchase_periods({"offering_id": rows["offering_id"]}, TRANSFER_AGENT),
            1,
        )


class TestRepurchaseProcessingCutoff:
    """PRD §3.8 — the processing endpoint opens exactly at request_cutoff_at."""

    @pytest.mark.parametrize(
        "instant", ["2026-08-01T00:00:00Z", "2026-08-25T23:59:59Z"]
    )
    def test_processing_is_refused_at_every_instant_before_the_cutoff(
        self, api: ApiClient, world: ReitWorld, instant: str
    ) -> None:
        """A processing run one second before the cutoff, or on the day the window opened, is refused as not ready.

        PRD §3.8: "It requires that the current logical clock has reached `request_cutoff_at`, an early attempt being refused with `ERR_PERIOD_NOT_READY_FOR_PROCESSING`; that the plan is `ACTIVE`; and that a `PUBLISHED` valuation record exists for every class holding a `QUEUED` tender in the period, without which the run is refused with `ERR_NO_PUBLISHED_NAV`."
        PRD §3.8: "The request window is the half-open interval running from `opens_at` inclusive to `request_cutoff_at` exclusive, and windows of the same offering may abut but never overlap."

        Design: Corner/endpoints/processing_is_refused_before_the_cutoff_and_allowed_at_it
        """
        rows = _empty_period_world(world)
        world.set_clock(instant)

        early = api.process_repurchase_period(rows["period_id"], None, TRANSFER_AGENT)
        assert_error(early, ApiErrorId.PERIOD_NOT_READY_FOR_PROCESSING, 409)

        assert_fields(
            world.read_period(rows["period_id"]), status=RepurchasePeriodStatus.OPEN
        )

    def test_processing_at_the_cutoff_settles_an_empty_period_at_zero_capacity(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """At exactly the cutoff an empty period reaches PROCESSED with every cap, the capacity and the settled total at zero.

        PRD §3.8: "Processing a closed period is the exclusive act of a `TransferAgent`, and it takes the period from `OPEN` to the terminal `PROCESSED`."
        PRD §3.8: "A new period opens `OPEN` with `monthly_cap_cents`, `quarterly_remaining_cents`, `capacity_cents` and `settled_amount_cents` all at zero and `prorated` false."
        PRD §3.8: "`monthly_cap_cents` is two percent of it — the aggregate multiplied by 200 basis points, divided by 10,000, floored."
        PRD §3.8: "`capacity_cents` is the lesser of the monthly cap and the quarterly remainder."
        PRD §3.8: "The period's `settled_amount_cents` is the sum of every `approved_value_cents` in the run, and that gross figure is what is charged against both caps; `prorated` is set true when at least one non-hardship tender was cut back below its requested value."
        PRD §3.8: "The service derives `quarter_key` from the month as the four-digit year, a hyphen, the letter `Q`, and the quarter number obtained by taking the month number less one, dividing by three, flooring, and adding one — so January through March fall in the first quarter, April through June in the second, and so on."

        Design: Corner/endpoints/processing_is_refused_before_the_cutoff_and_allowed_at_it
        """
        rows = _empty_period_world(world)
        world.set_clock("2026-08-26T00:00:00Z")

        processed = assert_ok(
            api.process_repurchase_period(rows["period_id"], None, TRANSFER_AGENT)
        )
        assert_fields(
            processed,
            status=RepurchasePeriodStatus.PROCESSED,
            quarter_key="2026-Q3",
            monthly_cap_cents=0,
            quarterly_remaining_cents=0,
            capacity_cents=0,
            settled_amount_cents=0,
            prorated=False,
        )

        assert_total_count(
            api.list_repurchase_requests(
                {"repurchase_period_id": rows["period_id"]}, TRANSFER_AGENT
            ),
            0,
        )
