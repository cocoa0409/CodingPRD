"""Two interval conventions that deliberately disagree with each other.

A valuation period is a closed interval on both ends, so two records sharing a
single calendar date already conflict while back-to-back months do not (PRD §3.6).
A repurchase request window is half-open, so abutting windows are legal — yet an
abutting window can still die on the five-day post-settlement blackout that runs
past the sibling's settlement date (PRD §3.8).
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    SPONSOR,
    TRANSFER_AGENT,
    ApiErrorId,
    assert_created,
    assert_error,
    assert_fields,
    nav_record_payload,
    repurchase_period_payload,
)
from test_helpers.fixtures import ReitWorld

ZERO_LOAD = {
    "upfront_selling_commission_bps": 0,
    "dealer_manager_fee_bps": 0,
    "annual_distribution_fee_bps": 0,
    "distribution_fee_cap_bps": 0,
}


def _funded_class_i_offering(
    world: ReitWorld, name: str, firm_name: str, crd_number: str,
    legal_name: str, email: str,
) -> Dict[str, Any]:
    """An EFFECTIVE offering whose escrow has broken on one 30,000,000-cent ticket.

    The single class I lot leaves 300,000,000 e4 outstanding at the offering's
    initial price of 1000 cents.
    """
    off = world.offering(
        name=name,
        minimum_offering_amount_cents=30000000,
        maximum_offering_amount_cents=50000000000,
        escrow_deadline_date="2026-12-31",
        initial_offering_price_cents=1000,
        rescission_window_days=5,
    )
    sc_i = world.share_class(off["id"], class_code="I", **ZERO_LOAD)
    firm = world.broker_dealer(firm_name=firm_name, crd_number=crd_number)
    agreement = world.selling_agreement(
        off["id"],
        firm["id"],
        max_commission_bps=100,
        suitability_documentation_required=True,
    )
    world.declare_effective(off["id"])
    world.activate_agreement(agreement["id"])

    holder = world.investor(
        legal_name=legal_name,
        email=email,
        state_code="TX",
        net_worth_cents=5000000000,
        annual_income_cents=1000000000,
    )
    world.document_suitability(holder["id"], "SUIT-2026-08")
    subscription = world.subscription(
        off["id"], sc_i["id"], holder["id"], agreement["id"], 30000000
    )
    world.escrow_subscription(subscription["id"])
    world.break_escrow(off["id"])
    return {
        "offering_id": off["id"],
        "share_class_i_id": sc_i["id"],
        "investor_id": holder["id"],
        "subscription_id": subscription["id"],
    }


# ─── Larkspur: closed valuation intervals ─────────────────────────────


def _larkspur_with_published_august(world: ReitWorld) -> Dict[str, Any]:
    """Class I priced for 2026-08-01..2026-08-31 with the clock at 2026-10-02.

    The share class's ``version`` is re-read afterwards, because only preparing a
    valuation record advances it.
    """
    scene = _funded_class_i_offering(
        world,
        "Larkspur Core REIT",
        "Larkspur Placement LLC",
        "CRD-150001",
        "Lena Kowalczyk",
        "lena.kowalczyk@example.com",
    )
    world.set_clock("2026-10-02T00:00:00Z", SPONSOR)
    scene["august_nav"] = world.published_nav(
        scene["share_class_i_id"], "2026-08-01", "2026-08-31", 30000000, 0, "IVA-2026-08-LK"
    )
    scene["share_class_version"] = world.share_class_version(scene["share_class_i_id"])
    return scene


def _propose_period(
    scene: Dict[str, Any], period_start_date: str, period_end_date: str
) -> Dict[str, Any]:
    """The class I valuation payload for a candidate period."""
    return nav_record_payload(
        scene["share_class_i_id"],
        scene["share_class_version"],
        period_start_date=period_start_date,
        period_end_date=period_end_date,
        gross_asset_value_cents=30000000,
        other_liabilities_cents=0,
    )


class TestValuationPeriodsAreClosedIntervals:
    """PRD §3.6: a shared endpoint conflicts, an adjacent month does not."""

    def test_period_straddling_the_published_month_is_an_overlap(self, api, world):
        """2026-08-15..2026-09-15 crosses a PUBLISHED 2026-08-01..2026-08-31 record.

        PRD §3.6: "Against sibling records of the same class whose status is
        `ADVISOR_REVIEW`, `ADVISOR_CONFIRMED` or `PUBLISHED`, the proposed period
        conflicts whenever its `period_start_date` is on or before the sibling's
        `period_end_date` **and** the sibling's `period_start_date` is on or
        before the proposed `period_end_date`; such a conflict is rejected with
        `ERR_NAV_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/nav_period_closed_interval_overlap_versus_adjacent_month
        """
        scene = _larkspur_with_published_august(world)

        response = api.create_nav_record(
            _propose_period(scene, "2026-08-15", "2026-09-15"), SPONSOR
        )

        assert_error(response, ApiErrorId.NAV_PERIOD_OVERLAP, 409)

    def test_single_shared_calendar_date_is_already_an_overlap(self, api, world):
        """2026-08-31..2026-09-30 collides on exactly one day and is still refused.

        PRD §3.6: "Valuation periods are closed intervals on both ends, which
        makes a single shared calendar date an overlap."

        Design: Difficulty/resource_temporal_overlap/nav_period_closed_interval_overlap_versus_adjacent_month
        """
        scene = _larkspur_with_published_august(world)

        response = api.create_nav_record(
            _propose_period(scene, "2026-08-31", "2026-09-30"), SPONSOR
        )

        assert_error(response, ApiErrorId.NAV_PERIOD_OVERLAP, 409)

    def test_adjacent_month_is_accepted_as_a_draft_with_zero_variance(self, api, world):
        """2026-09-01..2026-09-30 shares no date with August and prices flat at 1000.

        PRD §3.6: "Back-to-back months are therefore legal — one period ending on
        the last day of a month and the next beginning on the first day of the
        following month share no date."
        PRD §3.6: "New records open in `DRAFT` with a null
        `advisor_opinion_reference` and a null `rejection_reason`."
        PRD §3.6: "Otherwise `variance_bps` is the absolute difference between
        this record's `nav_per_share_cents` and the prior record's
        `nav_per_share_cents`, multiplied by 10,000, divided by the prior figure,
        and floored to whole basis points."

        Design: Difficulty/resource_temporal_overlap/nav_period_closed_interval_overlap_versus_adjacent_month
        """
        scene = _larkspur_with_published_august(world)

        september = assert_created(
            api.create_nav_record(_propose_period(scene, "2026-09-01", "2026-09-30"), SPONSOR)
        )

        assert_fields(
            september,
            period_start_date="2026-09-01",
            period_end_date="2026-09-30",
            status="DRAFT",
            shares_outstanding_e4_snapshot=300000000,
            nav_per_share_cents=1000,
            variance_bps=0,
            advisor_opinion_reference=None,
            rejection_reason=None,
        )

    def test_a_draft_sibling_over_the_same_period_is_superseded_rather_than_blocking(
        self, api, world
    ):
        """The overlap gate consults only reviewed and published siblings, never a draft.

        PRD §3.6: "A sibling still sitting in `DRAFT` does not block the write at
        all: it is instead driven to the terminal `SUPERSEDED`, with its `version`
        incremented, and the new record takes its place."

        Design: Difficulty/resource_temporal_overlap/nav_period_closed_interval_overlap_versus_adjacent_month
        """
        scene = _larkspur_with_published_august(world)
        first_september = assert_created(
            api.create_nav_record(_propose_period(scene, "2026-09-01", "2026-09-30"), SPONSOR)
        )
        scene["share_class_version"] = world.share_class_version(scene["share_class_i_id"])

        second_september = assert_created(
            api.create_nav_record(_propose_period(scene, "2026-09-01", "2026-09-30"), SPONSOR)
        )

        assert_fields(world.read_nav_record(first_september["id"]), status="SUPERSEDED")
        assert_fields(
            second_september,
            status="DRAFT",
            period_start_date="2026-09-01",
            period_end_date="2026-09-30",
        )
        assert_fields(world.read_nav_record(scene["august_nav"]["id"]), status="PUBLISHED")


# ─── Pinecrest: half-open windows and the settlement blackout ─────────


def _pinecrest_with_september_period(world: ReitWorld) -> Dict[str, Any]:
    """A funded offering holding one OPEN 2026-09 period settling on 2026-09-30.

    Its request window is ``[2026-09-03T00:00:00Z, 2026-09-25T00:00:00Z)``, so the
    five-day post-settlement blackout runs up to 2026-10-05.
    """
    scene = _funded_class_i_offering(
        world,
        "Pinecrest Income REIT",
        "Pinecrest Selling Group",
        "CRD-160001",
        "Priya Raghunathan",
        "priya.raghunathan@example.com",
    )
    scene["september_period"] = world.repurchase_period(
        scene["offering_id"],
        period_month="2026-09",
        opens_at="2026-09-03T00:00:00Z",
        request_cutoff_at="2026-09-25T00:00:00Z",
        settlement_date="2026-09-30",
    )
    return scene


class TestRepurchaseWindowAdjacencyAndSettlementBlackout:
    """PRD §3.8: abutting windows are legal, the blackout is a separate test."""

    def test_window_overlapping_the_sibling_is_refused(self, api, world):
        """An October period opening on 2026-09-20 straddles the live September window.

        PRD §3.8: "A true overlap exists when this period's `opens_at` falls
        before the sibling's `request_cutoff_at` and the sibling's `opens_at`
        falls before this period's `request_cutoff_at`; that is rejected with
        `ERR_REPURCHASE_PERIOD_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/repurchase_window_adjacency_legal_but_settlement_blackout_conflicts
        """
        scene = _pinecrest_with_september_period(world)

        response = api.create_repurchase_period(
            repurchase_period_payload(
                scene["offering_id"],
                period_month="2026-10",
                opens_at="2026-09-20T00:00:00Z",
                request_cutoff_at="2026-10-15T00:00:00Z",
                settlement_date="2026-10-20",
            ),
            TRANSFER_AGENT,
        )

        assert_error(response, ApiErrorId.REPURCHASE_PERIOD_WINDOW_CONFLICT, 409)

    def test_abutting_window_inside_the_settlement_blackout_is_refused(self, api, world):
        """Opening exactly at the sibling's cutoff is no overlap yet still blacked out.

        PRD §3.8: "Separately, where this period's `opens_at` is at or after a
        sibling's `request_cutoff_at`, the calendar date of this period's
        `opens_at` must fall on or after that sibling's `settlement_date`
        advanced by five days; opening inside that five-day settlement blackout
        is rejected with the same code."

        Design: Difficulty/resource_temporal_overlap/repurchase_window_adjacency_legal_but_settlement_blackout_conflicts
        """
        scene = _pinecrest_with_september_period(world)

        response = api.create_repurchase_period(
            repurchase_period_payload(
                scene["offering_id"],
                period_month="2026-10",
                opens_at="2026-09-25T00:00:00Z",
                request_cutoff_at="2026-10-15T00:00:00Z",
                settlement_date="2026-10-20",
            ),
            TRANSFER_AGENT,
        )

        assert_error(response, ApiErrorId.REPURCHASE_PERIOD_WINDOW_CONFLICT, 409)

    def test_earlier_window_ending_at_the_siblings_opening_instant_is_accepted(
        self, api, world
    ):
        """An August period whose cutoff equals the sibling's opens_at abuts legally.

        PRD §3.8: "The request window is the half-open interval running from
        `opens_at` inclusive to `request_cutoff_at` exclusive, and windows of the
        same offering may abut but never overlap."
        PRD §3.8: "The service derives `quarter_key` from the month as the
        four-digit year, a hyphen, the letter `Q`, and the quarter number
        obtained by taking the month number less one, dividing by three,
        flooring, and adding one — so January through March fall in the first
        quarter, April through June in the second, and so on."

        Design: Difficulty/resource_temporal_overlap/repurchase_window_adjacency_legal_but_settlement_blackout_conflicts
        """
        scene = _pinecrest_with_september_period(world)

        august = assert_created(
            api.create_repurchase_period(
                repurchase_period_payload(
                    scene["offering_id"],
                    period_month="2026-08",
                    opens_at="2026-08-10T00:00:00Z",
                    request_cutoff_at="2026-09-03T00:00:00Z",
                    settlement_date="2026-09-04",
                ),
                TRANSFER_AGENT,
            )
        )

        assert_fields(
            august,
            period_month="2026-08",
            quarter_key="2026-Q3",
            status="OPEN",
            opens_at="2026-08-10T00:00:00Z",
            request_cutoff_at="2026-09-03T00:00:00Z",
        )
        assert_fields(world.read_period(scene["september_period"]["id"]), status="OPEN")

    def test_window_opening_exactly_when_the_blackout_expires_is_accepted(self, api, world):
        """2026-10-05 is the sibling's settlement date plus five days, and is admitted.

        PRD §3.8: "Adjacency is legal: an `opens_at` exactly equal to a sibling's
        `request_cutoff_at` is not an overlap, provided the settlement blackout
        is also satisfied."
        PRD §3.8: "A new period opens `OPEN` with `monthly_cap_cents`,
        `quarterly_remaining_cents`, `capacity_cents` and `settled_amount_cents`
        all at zero and `prorated` false."

        Design: Difficulty/resource_temporal_overlap/repurchase_window_adjacency_legal_but_settlement_blackout_conflicts
        """
        scene = _pinecrest_with_september_period(world)
        assert_created(
            api.create_repurchase_period(
                repurchase_period_payload(
                    scene["offering_id"],
                    period_month="2026-08",
                    opens_at="2026-08-10T00:00:00Z",
                    request_cutoff_at="2026-09-03T00:00:00Z",
                    settlement_date="2026-09-04",
                ),
                TRANSFER_AGENT,
            )
        )

        october = assert_created(
            api.create_repurchase_period(
                repurchase_period_payload(
                    scene["offering_id"],
                    period_month="2026-10",
                    opens_at="2026-10-05T00:00:00Z",
                    request_cutoff_at="2026-10-26T00:00:00Z",
                    settlement_date="2026-10-30",
                ),
                TRANSFER_AGENT,
            )
        )

        assert_fields(
            october,
            opens_at="2026-10-05T00:00:00Z",
            quarter_key="2026-Q4",
            status="OPEN",
            monthly_cap_cents=0,
            quarterly_remaining_cents=0,
            capacity_cents=0,
            settled_amount_cents=0,
            prorated=False,
        )
        assert_fields(world.read_period(scene["september_period"]["id"]), status="OPEN")
