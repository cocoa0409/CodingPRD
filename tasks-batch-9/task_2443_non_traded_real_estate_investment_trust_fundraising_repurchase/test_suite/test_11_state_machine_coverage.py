"""State-machine coverage for the Non-Traded REIT Fundraising & Repurchase API.

Every test in this file pins one declared transition, initial state, terminal
lockdown or cascade from PRD §2.4, §2.9, §2.10, §3.1, §3.2, §3.3, §3.5, §3.6
and §3.8. The service is restarted before each test, so the database is empty
and the logical clock reads its boot instant of 2026-08-01T00:00:00Z until a
test moves it.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from test_helpers import (
    ADVISOR,
    BOARD,
    COMPLIANCE,
    SPONSOR,
    TRANSFER_AGENT,
    ApiClient,
    ApiErrorId,
    ClassCode,
    FindingAction,
    FindingSeverity,
    LiquidityEventAction,
    LiquidityEventStatus,
    LiquidityEventType,
    NavRecordStatus,
    RegistrationAction,
    RegistrationStatus,
    RepurchasePeriodStatus,
    RepurchasePlanAction,
    RepurchasePlanStatus,
    RepurchaseRequestStatus,
    SellingAgreementStatus,
    ShareClassStatus,
    SubscriptionStatus,
    SupervisionStatus,
    assert_error,
    assert_fields,
    assert_offering_axes,
    assert_ok,
    make_investor_user_headers,
)
from test_helpers.fixtures import ReitWorld

# ─── Payload shapes reused by the scenarios below ─────────────────────

_ZERO_LOAD_CLASS_I: Dict[str, Any] = {
    "class_code": ClassCode.I,
    "upfront_selling_commission_bps": 0,
    "dealer_manager_fee_bps": 0,
    "annual_distribution_fee_bps": 0,
    "distribution_fee_cap_bps": 0,
}


def _offering(name: str, minimum_cents: int, maximum_cents: int) -> Dict[str, Any]:
    return {
        "name": name,
        "minimum_offering_amount_cents": minimum_cents,
        "maximum_offering_amount_cents": maximum_cents,
        "escrow_deadline_date": "2026-12-31",
        "initial_offering_price_cents": 1000,
    }


def _class_with_no_shares(world: ReitWorld, offering_name: str) -> Dict[str, Any]:
    """An offering left in DRAFT carrying one zero-load class I and no money."""
    offering = world.offering(**_offering(offering_name, 25000000, 90000000000))
    share_class = world.share_class(offering["id"], **_ZERO_LOAD_CLASS_I)
    return {"offering_id": offering["id"], "share_class_id": share_class["id"]}


def _funded_offering(world: ReitWorld, offering_name: str) -> Dict[str, Any]:
    """One 30,000,000-cent class I ticket accepted by an escrow break."""
    world_rows = world.effective_offering(
        offering=_offering(offering_name, 30000000, 50000000000),
        share_class=dict(_ZERO_LOAD_CLASS_I),
        agreement={"max_commission_bps": 100},
    )
    investor = world.documented_investor(
        legal_name="Gil Sandoval",
        email="gil.sandoval@example.com",
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    subscription = world.subscription(
        world_rows["offering_id"],
        world_rows["share_class_id"],
        investor["id"],
        world_rows["selling_agreement_id"],
        30000000,
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(world_rows["offering_id"])
    world_rows["investor_id"] = investor["id"]
    world_rows["subscription_id"] = subscription["id"]
    return world_rows


def _held_tender_world(world: ReitWorld) -> Dict[str, Any]:
    """A funded offering, an OPEN August period, one WITHDRAWN and one QUEUED tender."""
    rows = _funded_offering(world, "Selectrix REIT")
    period = world.repurchase_period(
        rows["offering_id"],
        period_month="2026-08",
        opens_at="2026-08-01T00:00:00Z",
        request_cutoff_at="2026-08-26T00:00:00Z",
        settlement_date="2026-08-30",
    )
    first = world.tender(period["id"], rows["share_class_id"], 1000000, rows["investor_id"])
    second = world.tender(period["id"], rows["share_class_id"], 1000000, rows["investor_id"])
    rows["period_id"] = period["id"]
    rows["withdrawn_request_id"] = first["id"]
    rows["queued_request_id"] = second["id"]
    return rows


class TestNavRecordLifecycle:
    """PRD §3.6 — the four-hop valuation review cycle."""

    def test_valuation_walks_draft_to_published_incrementing_version_at_every_hop(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """Each declared hop of the valuation cycle succeeds for its own role and bumps version by one.

        PRD §3.6: "A `SponsorOperator` submits `DRAFT` to `ADVISOR_REVIEW`, which is permitted only once the valuation period has fully elapsed — the current logical date must be strictly after the `period_end_date`, and an early submission is refused with `ERR_NAV_PERIOD_NOT_ELAPSED`."
        PRD §3.6: "A confirmation moves the record to `ADVISOR_CONFIRMED` and records the supplied `advisor_opinion_reference`; where `variance_bps` exceeds 500 basis points that reference is mandatory and a confirmation without one is refused with `ERR_ADVISOR_OPINION_REQUIRED`."
        PRD §3.6: "A `SponsorOperator` moves `ADVISOR_CONFIRMED` to `PUBLISHED`, which is permitted only when no other `PUBLISHED` record for the same class covers an overlapping period."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most recent mutation of the row, and `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/state_machines/nav_record_lifecycle_draft_to_published_valid_transitions
        """
        rows = _class_with_no_shares(world, "Ladderway REIT")
        world.set_clock("2026-09-02T00:00:00Z", SPONSOR)

        draft = world.nav_record(rows["share_class_id"], "2026-08-01", "2026-08-31", 0, 0)
        assert_fields(draft, status=NavRecordStatus.DRAFT, version=1)

        in_review = assert_ok(
            api.set_nav_record_status(
                draft["id"], {"to_status": NavRecordStatus.ADVISOR_REVIEW}, SPONSOR
            )
        )
        assert_fields(in_review, status=NavRecordStatus.ADVISOR_REVIEW, version=2)

        confirmed = assert_ok(
            api.set_nav_record_status(
                draft["id"], {"to_status": NavRecordStatus.ADVISOR_CONFIRMED}, ADVISOR
            )
        )
        assert_fields(confirmed, status=NavRecordStatus.ADVISOR_CONFIRMED, version=3)

        published = assert_ok(
            api.set_nav_record_status(
                draft["id"], {"to_status": NavRecordStatus.PUBLISHED}, SPONSOR
            )
        )
        assert_fields(published, status=NavRecordStatus.PUBLISHED, version=4)

    def test_first_valuation_of_a_class_reports_zero_variance_at_the_initial_price(
        self, world: ReitWorld
    ) -> None:
        """A first valuation over a class with no shares carries zero variance and the initial offering price.

        PRD §3.6: "New records open in `DRAFT` with a null `advisor_opinion_reference` and a null `rejection_reason`."
        PRD §3.6: "When no prior published record exists, `variance_bps` is zero."
        PRD §3.6: "When the snapshotted share count is zero, both per-share figures are set to the offering's `initial_offering_price_cents`."
        PRD §3.6: "The record snapshots `shares_outstanding_e4_snapshot` from the class's `shares_outstanding_e4` at the instant of creation, and computes `accrued_distribution_payable_cents` as the sum of `total_declared_cents` across every declaration of the class's offering that is currently `DECLARED` and whose `record_date` falls on or before this record's `period_end_date`."

        Design: Corner/state_machines/nav_record_lifecycle_draft_to_published_valid_transitions
        """
        rows = _class_with_no_shares(world, "Ladderway REIT")
        world.set_clock("2026-09-02T00:00:00Z", SPONSOR)

        draft = world.nav_record(rows["share_class_id"], "2026-08-01", "2026-08-31", 0, 0)
        assert_fields(
            draft,
            status=NavRecordStatus.DRAFT,
            advisor_opinion_reference=None,
            rejection_reason=None,
            shares_outstanding_e4_snapshot=0,
            variance_bps=0,
            nav_per_share_pre_accrual_cents=1000,
            nav_per_share_cents=1000,
        )

        world.submit_nav_for_review(draft["id"])
        world.confirm_nav(draft["id"])
        published = world.publish_nav_record(draft["id"])
        assert_fields(
            published,
            status=NavRecordStatus.PUBLISHED,
            variance_bps=0,
            advisor_opinion_reference=None,
            rejection_reason=None,
            nav_per_share_cents=1000,
        )
        assert world.read_offering(rows["offering_id"])["aggregate_nav_cents"] == 0


class TestSellingAgreementActivation:
    """PRD §3.3 — PENDING to ACTIVE carries two preconditions from two parents."""

    def test_activation_is_refused_while_the_covered_offering_is_still_draft(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """A spotless firm's agreement cannot go ACTIVE until its offering is EFFECTIVE, and then it can.

        PRD §3.3: "`PENDING` becomes `ACTIVE` only when the firm behind it is not `BARRED` — otherwise `ERR_BROKER_DEALER_BARRED` — and the covered offering's `registration_status` is `EFFECTIVE`, otherwise `ERR_OFFERING_NOT_EFFECTIVE`."

        Design: Corner/state_machines/selling_agreement_activation_preconditions_enforced
        """
        rows = _class_with_no_shares(world, "Gatecheck REIT")
        firm = world.broker_dealer(
            firm_name="Gatecheck Placement A", crd_number="CRD-210001"
        )
        agreement = world.selling_agreement(
            rows["offering_id"], firm["id"], max_commission_bps=700
        )

        refused = api.set_selling_agreement_status(
            agreement["id"], {"to_status": SellingAgreementStatus.ACTIVE}, COMPLIANCE
        )
        assert_error(refused, ApiErrorId.OFFERING_NOT_EFFECTIVE, 409)
        assert_fields(
            world.read_agreement(agreement["id"]),
            status=SellingAgreementStatus.PENDING,
            version=1,
        )

        world.declare_effective(rows["offering_id"])
        activated = assert_ok(
            api.set_selling_agreement_status(
                agreement["id"], {"to_status": SellingAgreementStatus.ACTIVE}, COMPLIANCE
            )
        )
        assert_fields(activated, status=SellingAgreementStatus.ACTIVE, version=2)

    def test_activation_is_refused_while_the_firm_behind_the_agreement_is_barred(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """An agreement written after its firm was barred cannot be activated even under an EFFECTIVE offering.

        PRD §3.3: "`PENDING` becomes `ACTIVE` only when the firm behind it is not `BARRED` — otherwise `ERR_BROKER_DEALER_BARRED` — and the covered offering's `registration_status` is `EFFECTIVE`, otherwise `ERR_OFFERING_NOT_EFFECTIVE`."
        PRD §3.3: "`HEIGHTENED_SUPERVISION` may also be escalated to the terminal `BARRED`, which is the most destructive single act in the system: every selling agreement of that firm still in `PENDING`, `ACTIVE` or `SUSPENDED` is driven to the terminal `TERMINATED`, and every subscription still in `PENDING` under any of those agreements is driven to `REJECTED` carrying the `rejection_reason` string `BROKER_DEALER_BARRED`."

        Design: Corner/state_machines/selling_agreement_activation_preconditions_enforced
        """
        rows = _class_with_no_shares(world, "Gatecheck REIT")
        world.declare_effective(rows["offering_id"])

        firm = world.broker_dealer(
            firm_name="Gatecheck Placement B", crd_number="CRD-210002"
        )
        world.set_supervision_status(firm["id"], SupervisionStatus.HEIGHTENED_SUPERVISION)
        world.set_supervision_status(
            firm["id"], SupervisionStatus.BARRED, reason="FINRA expulsion"
        )

        agreement = world.selling_agreement(
            rows["offering_id"], firm["id"], max_commission_bps=700
        )
        refused = api.set_selling_agreement_status(
            agreement["id"], {"to_status": SellingAgreementStatus.ACTIVE}, COMPLIANCE
        )
        assert_error(refused, ApiErrorId.BROKER_DEALER_BARRED, 409)

        assert_fields(
            world.read_agreement(agreement["id"]), status=SellingAgreementStatus.PENDING
        )
        assert_fields(
            world.read_broker_dealer(firm["id"]),
            supervision_status=SupervisionStatus.BARRED,
        )


class TestSupervisionFindingCascade:
    """PRD §3.3 — agreement status is derived from the open finding counters."""

    @staticmethod
    def _two_active_agreements(world: ReitWorld) -> Dict[str, Any]:
        offering = world.offering(**_offering("Findingsworth REIT", 25000000, 90000000000))
        share_class = world.share_class(offering["id"], **_ZERO_LOAD_CLASS_I)
        firm = world.broker_dealer(
            firm_name="Findingsworth Placement", crd_number="CRD-220001"
        )
        world.declare_effective(offering["id"])
        first = world.selling_agreement(offering["id"], firm["id"], max_commission_bps=700)
        second = world.selling_agreement(offering["id"], firm["id"], max_commission_bps=700)
        world.activate_agreement(first["id"])
        world.activate_agreement(second["id"])
        return {
            "offering_id": offering["id"],
            "share_class_id": share_class["id"],
            "broker_dealer_id": firm["id"],
            "first_agreement_id": first["id"],
            "second_agreement_id": second["id"],
        }

    def test_third_open_minor_finding_auto_suspends_and_escalates_the_firm(
        self, world: ReitWorld
    ) -> None:
        """Two minor findings leave the agreement ACTIVE; the third derives SUSPENDED and bubbles up to the firm.

        PRD §3.3: "`RECORD` increments `open_minor_finding_count` or `open_major_finding_count` according to the severity given; `RESOLVE` decrements the matching counter."
        PRD §3.3: "The agreement's status is then re-derived from the resulting counters rather than being set by hand: an `ACTIVE` agreement is automatically suspended as soon as it carries three or more open minor findings or one or more open major findings, and a `SUSPENDED` agreement automatically returns to `ACTIVE` once, after the resolution, its open minor count is below three **and** its open major count is zero — provided the firm behind it is not `BARRED`."
        PRD §3.3: "Auto-suspension carries the same secondary effects as an explicit suspension, incrementing the firm's `suspended_agreement_count` and escalating an `IN_GOOD_STANDING` firm to `HEIGHTENED_SUPERVISION`; auto-reactivation decrements that counter."

        Design: Corner/state_machines/supervision_findings_auto_suspend_and_reactivate_agreement
        """
        rows = self._two_active_agreements(world)
        agreement_id = rows["first_agreement_id"]

        after_one = world.record_finding(
            agreement_id, FindingAction.RECORD, FindingSeverity.MINOR, finding_reference="FIND-1"
        )
        assert_fields(after_one, status=SellingAgreementStatus.ACTIVE, open_minor_finding_count=1)

        after_two = world.record_finding(
            agreement_id, FindingAction.RECORD, FindingSeverity.MINOR, finding_reference="FIND-2"
        )
        assert_fields(after_two, status=SellingAgreementStatus.ACTIVE, open_minor_finding_count=2)

        after_three = world.record_finding(
            agreement_id, FindingAction.RECORD, FindingSeverity.MINOR, finding_reference="FIND-3"
        )
        assert_fields(
            after_three,
            status=SellingAgreementStatus.SUSPENDED,
            open_minor_finding_count=3,
            open_major_finding_count=0,
        )

        assert_fields(
            world.read_broker_dealer(rows["broker_dealer_id"]),
            supervision_status=SupervisionStatus.HEIGHTENED_SUPERVISION,
            suspended_agreement_count=1,
        )

    def test_major_finding_suspends_a_sibling_and_resolution_reactivates_only_its_own_agreement(
        self, world: ReitWorld
    ) -> None:
        """A single major finding suspends its own agreement, and resolving one minor finding reactivates only that agreement.

        PRD §3.3: "The agreement's status is then re-derived from the resulting counters rather than being set by hand: an `ACTIVE` agreement is automatically suspended as soon as it carries three or more open minor findings or one or more open major findings, and a `SUSPENDED` agreement automatically returns to `ACTIVE` once, after the resolution, its open minor count is below three **and** its open major count is zero — provided the firm behind it is not `BARRED`."
        PRD §3.3: "Auto-suspension carries the same secondary effects as an explicit suspension, incrementing the firm's `suspended_agreement_count` and escalating an `IN_GOOD_STANDING` firm to `HEIGHTENED_SUPERVISION`; auto-reactivation decrements that counter."

        Design: Corner/state_machines/supervision_findings_auto_suspend_and_reactivate_agreement
        """
        rows = self._two_active_agreements(world)
        first_id = rows["first_agreement_id"]
        second_id = rows["second_agreement_id"]

        for reference in ("FIND-1", "FIND-2", "FIND-3"):
            world.record_finding(
                first_id, FindingAction.RECORD, FindingSeverity.MINOR, finding_reference=reference
            )

        after_major = world.record_finding(
            second_id, FindingAction.RECORD, FindingSeverity.MAJOR, finding_reference="FIND-4"
        )
        assert_fields(
            after_major, status=SellingAgreementStatus.SUSPENDED, open_major_finding_count=1
        )
        assert_fields(
            world.read_broker_dealer(rows["broker_dealer_id"]), suspended_agreement_count=2
        )

        after_resolve = world.record_finding(
            first_id, FindingAction.RESOLVE, FindingSeverity.MINOR, finding_reference="FIND-3"
        )
        assert_fields(
            after_resolve,
            status=SellingAgreementStatus.ACTIVE,
            open_minor_finding_count=2,
            open_major_finding_count=0,
        )
        assert_fields(
            world.read_broker_dealer(rows["broker_dealer_id"]), suspended_agreement_count=1
        )
        assert_fields(
            world.read_agreement(second_id), status=SellingAgreementStatus.SUSPENDED
        )


class TestSubscriptionUndefinedTransitions:
    """PRD §2.9, §3.5 — exits the subscription machine does not define are 409s."""

    @staticmethod
    def _pending_subscription(world: ReitWorld) -> Dict[str, Any]:
        rows = world.effective_offering(
            offering=_offering("Deadend REIT", 25000000, 90000000000),
            share_class=dict(_ZERO_LOAD_CLASS_I),
            agreement={"max_commission_bps": 700},
        )
        investor = world.documented_investor(
            legal_name="Nils Aberdene",
            email="nils.aberdene@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )
        subscription = world.subscription(
            rows["offering_id"],
            rows["share_class_id"],
            investor["id"],
            rows["selling_agreement_id"],
            250000,
        )
        rows["investor_id"] = investor["id"]
        rows["subscription_id"] = subscription["id"]
        return rows

    @pytest.mark.parametrize(
        "to_status",
        [SubscriptionStatus.RESCINDED, SubscriptionStatus.REFUNDED],
    )
    def test_pending_subscription_refuses_exits_reserved_for_later_states(
        self, api: ApiClient, world: ReitWorld, to_status: str
    ) -> None:
        """A PENDING subscription cannot be rescinded or refunded, even by the role that owns those exits elsewhere.

        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.5: "A `TransferAgent` may drive `ESCROWED` to `REFUNDED` while `escrow_status` is `COLLECTING` or `FAILED`, which subtracts the `gross_investment_cents` from `escrow_balance_cents`; this is also the path the escrow-failure cascade takes."
        PRD §3.5: "And a `TransferAgent` may drive `ACCEPTED` to `RESCINDED`, again with a `rejection_reason`, but only inside the rescission window and only against an untouched lot."

        Design: Corner/state_machines/subscription_undefined_transitions_from_pending_and_escrowed_rejected
        """
        rows = self._pending_subscription(world)
        payload: Dict[str, Any] = {"to_status": to_status}
        if to_status == SubscriptionStatus.RESCINDED:
            payload["rejection_reason"] = "changed mind"

        refused = api.set_subscription_status(
            rows["subscription_id"], payload, TRANSFER_AGENT
        )
        assert_error(refused, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_subscription(rows["subscription_id"]),
            status=SubscriptionStatus.PENDING,
            version=1,
        )
        assert world.read_offering(rows["offering_id"])["escrow_balance_cents"] == 0

    def test_escrowed_subscription_refuses_rejection_and_rescission(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """An ESCROWED subscription keeps its state, version and escrow contribution after two undefined exits.

        PRD §3.5: "A `TransferAgent` moves a subscription from `PENDING` to `ESCROWED`, which is permitted only while the offering's `escrow_status` is `COLLECTING` and its `registration_status` is `EFFECTIVE` — an offering that is not `EFFECTIVE` refuses the move with `ERR_OFFERING_NOT_EFFECTIVE`; the subscription's `version` increments and its `gross_investment_cents` is added to the offering's `escrow_balance_cents`."
        PRD §3.5: "A `SponsorOperator` may drive `PENDING` to `REJECTED` at any time, supplying a `rejection_reason`."
        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/subscription_undefined_transitions_from_pending_and_escrowed_rejected
        """
        rows = self._pending_subscription(world)
        escrowed = world.escrow_subscription(rows["subscription_id"])
        assert_fields(escrowed, status=SubscriptionStatus.ESCROWED, version=2)

        late_rejection = api.set_subscription_status(
            rows["subscription_id"],
            {"to_status": SubscriptionStatus.REJECTED, "rejection_reason": "too late"},
            SPONSOR,
        )
        assert_error(late_rejection, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        early_rescission = api.set_subscription_status(
            rows["subscription_id"],
            {"to_status": SubscriptionStatus.RESCINDED, "rejection_reason": "changed mind"},
            TRANSFER_AGENT,
        )
        assert_error(early_rescission, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_subscription(rows["subscription_id"]),
            status=SubscriptionStatus.ESCROWED,
            version=2,
        )
        assert world.read_offering(rows["offering_id"])["escrow_balance_cents"] == 250000


class TestDeclaredInitialStates:
    """PRD §3.1, §3.2, §3.3, §3.6, §3.9 — every create lands on its declared initial state."""

    def test_offering_opens_on_three_axes_with_a_fresh_class_and_firm(
        self, world: ReitWorld
    ) -> None:
        """A new offering opens DRAFT/COLLECTING/ACTIVE with zeroed money, beside an ACTIVE class and a good-standing firm.

        PRD §3.1: "A newly created offering opens with `registration_status` at `DRAFT`, `escrow_status` at `COLLECTING`, `repurchase_plan_status` at `ACTIVE`, a null `repurchase_plan_suspension_reason`, and `escrow_balance_cents`, `gross_proceeds_cents` and `aggregate_nav_cents` all at zero."
        PRD §3.1: "A new class opens `ACTIVE` with `shares_outstanding_e4` at zero."
        PRD §3.3: "Firms open at `IN_GOOD_STANDING` with `suspended_agreement_count` at zero."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        offering = world.offering(**_offering("Genesis REIT", 25000000, 90000000000))
        assert_offering_axes(
            offering,
            registration_status=RegistrationStatus.DRAFT,
            escrow_status="COLLECTING",
            repurchase_plan_status=RepurchasePlanStatus.ACTIVE,
        )
        assert_fields(
            offering,
            repurchase_plan_suspension_reason=None,
            escrow_balance_cents=0,
            gross_proceeds_cents=0,
            aggregate_nav_cents=0,
            version=1,
        )

        share_class = world.share_class(offering["id"], **_ZERO_LOAD_CLASS_I)
        assert_fields(share_class, status=ShareClassStatus.ACTIVE, shares_outstanding_e4=0)

        firm = world.broker_dealer(firm_name="Genesis Placement", crd_number="CRD-240001")
        assert_fields(
            firm,
            supervision_status=SupervisionStatus.IN_GOOD_STANDING,
            suspended_agreement_count=0,
        )

    def test_agreement_account_valuation_and_event_open_in_their_declared_states(
        self, world: ReitWorld
    ) -> None:
        """An agreement, an account, a valuation prepared before its period elapses and a proposed event all open where the PRD says.

        PRD §3.3: "An agreement opens `PENDING` with `open_minor_finding_count` and `open_major_finding_count` both at zero."
        PRD §3.2: "New accounts start with `suitability_status` at `INCOMPLETE`, `account_status` at `ACTIVE`, a null `suitability_documentation_reference`, and the running totals `cumulative_invested_cents`, `total_shares_e4`, `cumulative_distributions_received_cents` and `cumulative_early_repurchase_deduction_cents` all at zero."
        PRD §3.6: "New records open in `DRAFT` with a null `advisor_opinion_reference` and a null `rejection_reason`."
        PRD §3.9: "It opens in `PROPOSED` with `record_date_shares_e4`, `votes_for_e4`, `votes_against_e4` and `votes_abstain_e4` all at zero and `quorum_met` false."

        Design: Corner/state_machines/newly_created_rows_start_in_declared_initial_states
        """
        rows = _class_with_no_shares(world, "Genesis REIT")
        firm = world.broker_dealer(firm_name="Genesis Placement", crd_number="CRD-240001")

        agreement = world.selling_agreement(
            rows["offering_id"], firm["id"], max_commission_bps=700
        )
        assert_fields(
            agreement,
            status=SellingAgreementStatus.PENDING,
            open_minor_finding_count=0,
            open_major_finding_count=0,
        )

        investor = world.investor(
            legal_name="Pell Vanterpool",
            email="pell.vanterpool@example.com",
            state_code="TX",
            net_worth_cents=400000000,
            annual_income_cents=80000000,
        )
        assert_fields(
            investor,
            suitability_status="INCOMPLETE",
            account_status="ACTIVE",
            suitability_documentation_reference=None,
            cumulative_invested_cents=0,
            total_shares_e4=0,
            cumulative_distributions_received_cents=0,
            cumulative_early_repurchase_deduction_cents=0,
        )

        valuation = world.nav_record(
            rows["share_class_id"], "2026-08-01", "2026-08-31", 0, 0
        )
        assert_fields(
            valuation,
            status=NavRecordStatus.DRAFT,
            advisor_opinion_reference=None,
            rejection_reason=None,
        )

        event = world.liquidity_event(
            rows["offering_id"],
            event_type=LiquidityEventType.LISTING,
            proposed_effective_date="2027-03-01",
        )
        assert_fields(
            event,
            status=LiquidityEventStatus.PROPOSED,
            record_date_shares_e4=0,
            votes_for_e4=0,
            votes_against_e4=0,
            votes_abstain_e4=0,
            quorum_met=False,
        )


class TestTerminalStateLockdown:
    """PRD §2.9, §3.1, §3.9 — a terminal state refuses every further trigger."""

    def test_closed_registration_locks_the_axis_and_its_cascaded_class(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """After CLOSE, both further registration actions and a re-close of the cascaded class report the own-state error.

        PRD §3.1: "`CLOSE` moves either `EFFECTIVE` or `SUSPENDED` to the terminal `CLOSED`, and requires that no subscription of the offering still sits in `PENDING` or `ESCROWED`; an attempt to close over unfinished subscriptions is refused with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.1: "Every one of these four actions increments the offering's `version` by 1, and closing additionally cascades: every share class of the offering still in `ACTIVE` is moved to the terminal `CLOSED_TO_NEW`, each such class having its own `version` incremented."
        PRD §2.9: "The **first** rule that is violated determines the response; later violations are never reported, never merged into the message, and never change the status code."
        PRD §2.9: "This covers terminal-state lockdown and repeated triggers — paying an already paid declaration, processing an already processed period, breaking an already broken escrow."

        Design: Corner/state_machines/closed_registration_and_abandoned_event_reject_every_further_trigger
        """
        rows = _class_with_no_shares(world, "Lockdown REIT")
        world.declare_effective(rows["offering_id"])
        world.drive_registration(rows["offering_id"], RegistrationAction.CLOSE)

        reclose = api.drive_registration(
            rows["offering_id"], {"action": RegistrationAction.CLOSE}, COMPLIANCE
        )
        assert_error(reclose, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        reinstate = api.drive_registration(
            rows["offering_id"], {"action": RegistrationAction.REINSTATE}, COMPLIANCE
        )
        assert_error(reinstate, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        reclose_class = api.set_share_class_status(
            rows["share_class_id"], {"to_status": ShareClassStatus.CLOSED_TO_NEW}, SPONSOR
        )
        assert_error(reclose_class, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_offering(rows["offering_id"]),
            registration_status=RegistrationStatus.CLOSED,
        )
        assert_fields(
            world.read_share_class(rows["share_class_id"]),
            status=ShareClassStatus.CLOSED_TO_NEW,
        )

    def test_abandoned_liquidity_event_refuses_a_second_abandonment(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """An event abandoned straight out of PROPOSED will not be abandoned twice.

        PRD §3.9: "Finally, the board may abandon a liquidity event, moving it to the terminal `ABANDONED` from `PROPOSED`, from `BOARD_APPROVED`, from `VOTE_OPEN` or from `REJECTED`, in each case incrementing the event's `version`."
        PRD §2.9: "This covers terminal-state lockdown and repeated triggers — paying an already paid declaration, processing an already processed period, breaking an already broken escrow."

        Design: Corner/state_machines/closed_registration_and_abandoned_event_reject_every_further_trigger
        """
        rows = _class_with_no_shares(world, "Lockdown REIT")
        event = world.liquidity_event(
            rows["offering_id"],
            event_type=LiquidityEventType.MERGER,
            proposed_effective_date="2027-03-01",
        )
        abandoned = world.drive_liquidity_event(
            event["id"], LiquidityEventAction.ABANDON, BOARD
        )
        assert_fields(abandoned, status=LiquidityEventStatus.ABANDONED, version=2)

        replay = api.drive_liquidity_event(
            event["id"], {"action": LiquidityEventAction.ABANDON}, BOARD
        )
        assert_error(replay, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_liquidity_event(event["id"]),
            status=LiquidityEventStatus.ABANDONED,
            version=2,
        )


class TestRepeatedTriggerRejected:
    """PRD §2.9 — replaying an applied transition errors instead of no-op succeeding."""

    def test_replaying_agreement_activation_leaves_the_version_it_first_reached(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """A second activation of an already ACTIVE agreement is a 409 that cannot inflate the row's version.

        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."
        PRD §2.9: "This covers terminal-state lockdown and repeated triggers — paying an already paid declaration, processing an already processed period, breaking an already broken escrow."
        PRD §2.4: "`updated_at` is an ISO 8601 UTC timestamp recording the most recent mutation of the row, and `version` is an integer that starts at 1 on creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/state_machines/repeated_trigger_on_same_row_rejected_and_leaves_version_untouched
        """
        rows = _class_with_no_shares(world, "Replay REIT")
        firm = world.broker_dealer(firm_name="Replay Placement", crd_number="CRD-250001")
        world.declare_effective(rows["offering_id"])
        agreement = world.selling_agreement(
            rows["offering_id"], firm["id"], max_commission_bps=700
        )
        first = world.activate_agreement(agreement["id"])
        assert_fields(first, status=SellingAgreementStatus.ACTIVE, version=2)

        replay = api.set_selling_agreement_status(
            agreement["id"], {"to_status": SellingAgreementStatus.ACTIVE}, COMPLIANCE
        )
        assert_error(replay, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_agreement(agreement["id"]),
            status=SellingAgreementStatus.ACTIVE,
            version=2,
        )
        assert_fields(
            world.read_broker_dealer(firm["id"]), suspended_agreement_count=0
        )

    def test_replaying_valuation_submission_leaves_the_version_it_first_reached(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """A second submission of a record already in ADVISOR_REVIEW is a 409 that cannot inflate the row's version.

        PRD §2.9: "The requested transition is defined in the target row's own state machine for the state that row is currently in, otherwise `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.6: "Submission increments the record's `version` and clears any `rejection_reason` left over from an earlier push-back."

        Design: Corner/state_machines/repeated_trigger_on_same_row_rejected_and_leaves_version_untouched
        """
        rows = _class_with_no_shares(world, "Replay REIT")
        world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
        record = world.nav_record(rows["share_class_id"], "2026-08-01", "2026-08-31", 0, 0)
        first = world.submit_nav_for_review(record["id"])
        assert_fields(first, status=NavRecordStatus.ADVISOR_REVIEW, version=2)

        replay = api.set_nav_record_status(
            record["id"], {"to_status": NavRecordStatus.ADVISOR_REVIEW}, SPONSOR
        )
        assert_error(replay, ApiErrorId.INVALID_STATE_TRANSITION, 409)

        assert_fields(
            world.read_nav_record(record["id"]),
            status=NavRecordStatus.ADVISOR_REVIEW,
            version=2,
        )


class TestPublicationResyncsAggregateNav:
    """PRD §3.6 — the offering's aggregate valuation moves at publication and nowhere else."""

    def test_aggregate_nav_is_re_derived_only_when_the_valuation_is_published(
        self, world: ReitWorld
    ) -> None:
        """A lower valuation leaves aggregate_nav_cents alone in DRAFT and ADVISOR_CONFIRMED and resets it on publication.

        PRD §3.6: "Publication increments the record's `version`, drives the class's previously `PUBLISHED` record to the terminal `SUPERSEDED` with its own `version` incremented, and recomputes the offering's `aggregate_nav_cents` from the new transaction price."
        PRD §3.6: "`aggregate_nav_cents` is the sum, taken over every share class of the offering, of each class's transaction price multiplied by that class's `shares_outstanding_e4`, divided by 10,000 and rounded half up — each class's contribution rounded to a whole cent on its own before the contributions are added."
        PRD §3.6: "It is recomputed after any change to a class's `shares_outstanding_e4` and after any publication."
        PRD §3.6: "Otherwise `nav_per_share_pre_accrual_cents` is the pre-accrual net assets multiplied by 10,000, divided by the snapshotted share count and rounded half up to a whole cent, while `nav_per_share_cents` is the post-accrual net assets multiplied by 10,000, divided by the same snapshotted share count and rounded half up."

        Design: Corner/state_machines/publishing_nav_resyncs_offering_aggregate_nav_ledger
        """
        rows = world.effective_offering(
            offering=_offering("Ledgerlink REIT", 30000000, 50000000000),
            share_class=dict(_ZERO_LOAD_CLASS_I),
            agreement={"max_commission_bps": 100},
        )
        investor = world.documented_investor(
            legal_name="Marta Kilbride",
            email="marta.kilbride@example.com",
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
        after_break = world.break_escrow(rows["offering_id"])
        assert after_break["aggregate_nav_cents"] == 30000000

        world.set_clock("2026-09-02T00:00:00Z", SPONSOR)
        record = world.nav_record(
            rows["share_class_id"],
            "2026-08-01",
            "2026-08-31",
            27000000,
            0,
            world.share_class_version(rows["share_class_id"]),
        )
        assert_fields(
            record, nav_per_share_cents=900, shares_outstanding_e4_snapshot=300000000
        )
        assert world.read_offering(rows["offering_id"])["aggregate_nav_cents"] == 30000000

        world.submit_nav_for_review(record["id"])
        world.confirm_nav(record["id"], "IVA-2026-08-LL")
        assert world.read_offering(rows["offering_id"])["aggregate_nav_cents"] == 30000000

        published = world.publish_nav_record(record["id"])
        assert_fields(published, status=NavRecordStatus.PUBLISHED)
        assert world.read_offering(rows["offering_id"])["aggregate_nav_cents"] == 27000000
        assert_fields(
            world.read_share_class(rows["share_class_id"]),
            shares_outstanding_e4=300000000,
        )


class TestPlanSuspensionSkipsWithdrawnTender:
    """PRD §3.8 — the suspend and resume cascades touch only QUEUED and HELD tenders."""

    def test_suspending_the_plan_holds_the_queued_tender_but_not_the_withdrawn_one(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """SUSPEND cancels nothing the stockholder already withdrew while holding the tender still queued.

        PRD §3.8: "`SUSPEND` moves `repurchase_plan_status` from `ACTIVE` to `SUSPENDED`, increments the offering's `version`, records the supplied text in `repurchase_plan_suspension_reason`, drives every `OPEN` repurchase period of the offering to `SUSPENDED`, and drives every `QUEUED` tender inside those periods to `HELD`, where it is excluded from any allocation."
        PRD §3.8: "Withdrawal is terminal and increments the request's `version`."

        Design: Corner/state_machines/plan_suspension_cascade_skips_withdrawn_request
        """
        rows = _held_tender_world(world)
        withdrawn = assert_ok(
            api.set_repurchase_request_status(
                rows["withdrawn_request_id"],
                {"to_status": RepurchaseRequestStatus.WITHDRAWN},
                make_investor_user_headers(rows["investor_id"]),
            )
        )
        assert_fields(withdrawn, status=RepurchaseRequestStatus.WITHDRAWN)

        suspended = world.drive_repurchase_plan(
            rows["offering_id"],
            RepurchasePlanAction.SUSPEND,
            reason="board review of liquidity",
        )
        assert_fields(
            suspended,
            repurchase_plan_status=RepurchasePlanStatus.SUSPENDED,
            repurchase_plan_suspension_reason="board review of liquidity",
        )

        assert_fields(
            world.read_period(rows["period_id"]), status=RepurchasePeriodStatus.SUSPENDED
        )
        assert_fields(
            world.read_request(rows["withdrawn_request_id"]),
            status=RepurchaseRequestStatus.WITHDRAWN,
        )
        assert_fields(
            world.read_request(rows["queued_request_id"]),
            status=RepurchaseRequestStatus.HELD,
        )

    def test_resuming_the_plan_requeues_the_held_tender_but_never_the_withdrawn_one(
        self, api: ApiClient, world: ReitWorld
    ) -> None:
        """RESUME returns the period to OPEN and the HELD tender to QUEUED while the withdrawn tender stays terminal.

        PRD §3.8: "`RESUME` reverses all of that — it returns `SUSPENDED` to `ACTIVE`, increments `version`, clears `repurchase_plan_suspension_reason`, returns every `SUSPENDED` period of the offering to `OPEN` and every `HELD` tender in those periods to `QUEUED` — but it is permitted only while the offering's `escrow_status` is `BROKEN`."
        PRD §3.8: "Withdrawal is terminal and increments the request's `version`."

        Design: Corner/state_machines/plan_suspension_cascade_skips_withdrawn_request
        """
        rows = _held_tender_world(world)
        assert_ok(
            api.set_repurchase_request_status(
                rows["withdrawn_request_id"],
                {"to_status": RepurchaseRequestStatus.WITHDRAWN},
                make_investor_user_headers(rows["investor_id"]),
            )
        )
        world.drive_repurchase_plan(
            rows["offering_id"],
            RepurchasePlanAction.SUSPEND,
            reason="board review of liquidity",
        )

        resumed = world.drive_repurchase_plan(
            rows["offering_id"], RepurchasePlanAction.RESUME
        )
        assert_fields(
            resumed,
            repurchase_plan_status=RepurchasePlanStatus.ACTIVE,
            repurchase_plan_suspension_reason=None,
        )

        assert_fields(
            world.read_period(rows["period_id"]), status=RepurchasePeriodStatus.OPEN
        )
        assert_fields(
            world.read_request(rows["withdrawn_request_id"]),
            status=RepurchaseRequestStatus.WITHDRAWN,
        )
        assert_fields(
            world.read_request(rows["queued_request_id"]),
            status=RepurchaseRequestStatus.QUEUED,
        )
