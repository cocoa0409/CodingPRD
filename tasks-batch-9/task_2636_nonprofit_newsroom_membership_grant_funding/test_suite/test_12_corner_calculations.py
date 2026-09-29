"""Calculation surface: constants at their tier boundaries, basis-dependent input
sets, waterfall allocation and fill order, cap precision, schedule generation,
calendar clamping, variance tolerance and exact-division cost splitting.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    add_partner,
    collaboration_action,
    enrol_member,
    list_proposal_reports,
    member_lifecycle,
    open_collaboration,
    open_fiscal_period,
    publish_tier,
    read_collaboration,
    read_fiscal_period,
    read_member,
    read_partner,
    read_proposal,
    read_report,
    read_sustainability,
    record_contribution,
    record_gift_offer,
    define_tier,
    draft_proposal,
    register_funder,
    release_funds,
    review_report,
    set_clock,
    settle_contribution,
    setup_awarded_restricted_proposal,
    setup_awarded_unrestricted_proposal,
    setup_period_and_area,
    submit_offer_for_review,
    submit_report,
    validate_error,
)
from test_helpers.fixtures import FC_HEADERS


def _published_sustainer():
    tier = define_tier(
        benefits=[],
        tier_code="SUSTAINER",
        name="Sustainer",
        renewal_cadence="MONTHLY",
        contribution_amount_cents=2500,
    )
    return publish_tier(tier["id"])


class TestGiftStewardshipFeeTierBoundaries:
    def test_the_fee_rate_is_selected_from_the_gross_at_every_floor(self):
        """999999 pays nothing, 1000000 pays 150 bps, 4999999 still pays 150 bps and
        5000000 jumps to 250 bps - a rate keyed on the net would have kept the last
        gift in the lower tier.

        PRD: "The tier floors are inclusive, so a gift of exactly 5000000 cents is
        charged at 250 basis points, not 150, and a gift of exactly 1000000 cents is
        charged at 150 basis points, not 0."

        Design: Corner/Calculations/calc_gift_stewardship_fee_tier_boundaries_are_keyed_on_the_gross
        """
        period = open_fiscal_period()
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")

        offers = {}
        for gross in (999999, 1000000, 4999999, 5000000):
            offer = record_gift_offer(
                funder["id"],
                period["id"],
                offered_amount_cents=gross,
                designation="UNRESTRICTED",
            )
            offers[gross] = submit_offer_for_review(offer["id"])

        assert offers[999999]["stewardship_fee_cents"] == 0
        assert offers[999999]["net_acceptable_amount_cents"] == 999999

        assert offers[1000000]["stewardship_fee_cents"] == 15000
        assert offers[1000000]["net_acceptable_amount_cents"] == 985000

        assert offers[4999999]["stewardship_fee_cents"] == 75000
        assert offers[4999999]["net_acceptable_amount_cents"] == 4924999

        assert offers[5000000]["stewardship_fee_cents"] == 125000
        assert offers[5000000]["net_acceptable_amount_cents"] == 4875000

    def test_the_ratification_threshold_sits_between_the_two_fee_floors(self):
        """The funder scores 10, so ratification is decided by the gross alone, and
        the 2500000-cent ratification threshold is independent of the 1000000 and
        5000000 fee floors: the two gifts under it are exempt and the two at or
        above it are not, so 4999999 needs the board while paying only 150 bps.

        PRD: "Third, and also keyed on the gross, `board_ratification_required`
        becomes true when either `offered_amount_cents` has reached **2500000 cents**
        (25,000 dollars) or the funder's current `independence_risk_score` has reached
        40; otherwise it is false."

        Design: Corner/Calculations/calc_gift_stewardship_fee_tier_boundaries_are_keyed_on_the_gross
        """
        period = open_fiscal_period()
        funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
        assert funder["independence_risk_score"] == 10

        required = {}
        for gross in (999999, 1000000, 4999999, 5000000):
            offer = record_gift_offer(
                funder["id"],
                period["id"],
                offered_amount_cents=gross,
                designation="UNRESTRICTED",
            )
            required[gross] = submit_offer_for_review(offer["id"])[
                "board_ratification_required"
            ]

        assert required[999999] is False
        assert required[1000000] is False
        assert required[4999999] is True
        assert required[5000000] is True


def _setup_settled_membership_initiated_events_and_a_draft_proposal():
    """One period holding a SETTLED 100000-cent membership gift, an INITIATED
    400000-cent events receipt and a DRAFT 500000-cent proposal."""
    period = open_fiscal_period()
    tier = _published_sustainer()
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    membership = record_contribution(
        period["id"],
        "MEMBERSHIP",
        100000,
        member_id=member["id"],
        received_date="2026-08-01",
    )
    settle_contribution(membership["id"])
    events = record_contribution(
        period["id"],
        "EVENTS",
        400000,
        received_date="2026-08-01",
        source_label="Annual benefit dinner",
    )
    funder = register_funder(legal_name="Ironwood Trust", funder_type="FOUNDATION")
    proposal = draft_proposal(
        funder["id"],
        period["id"],
        title="General operating support",
        requested_amount_cents=500000,
        restriction_type="UNRESTRICTED",
    )
    return {
        "period": period,
        "member": member,
        "membership": membership,
        "events": events,
        "funder": funder,
        "proposal": proposal,
    }


class TestRecognizedBasisExcludesInitiatedCashAndDraftPipeline:
    def test_the_recognized_basis_sees_only_the_settled_membership_money(self):
        """The events receipt is still INITIATED and the proposal is still DRAFT, so
        membership is the only stream with revenue and the index is fully
        concentrated.

        PRD: "The **recognized** basis is the persisted one: its settled set is
        exactly `SETTLED`, both pipeline terms are 0, and it counts cash and signed
        awards only."

        Design: Corner/Calculations/calc_diversification_recognized_basis_excludes_initiated_cash_and_draft_pipeline
        """
        ctx = _setup_settled_membership_initiated_events_and_a_draft_proposal()

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 100000
        assert picture["membership_share_bps"] == 10000
        assert picture["events_share_bps"] == 0
        assert picture["grants_share_bps"] == 0
        assert picture["concentration_hhi"] == 10000
        assert picture["top_source_share_bps"] == 0
        assert picture["reserve_months_target"] == 4
        assert picture["operating_reserve_target_cents"] == 800000
        assert picture["reserve_months_ratio_bps"] == 25000
        assert picture["sustainability_posture"] == "WATCH"
        assert picture["restricted_release_cap_pct_bps"] == 6000

    def test_the_pipeline_basis_admits_the_initiated_cash_but_not_the_draft(self):
        """INITIATED money joins the projection and drops the index to 6800, while
        the DRAFT proposal contributes nothing because only SUBMITTED proposals carry
        a probability weight.

        PRD: "The **pipeline** basis is a read-only projection that is never
        persisted: its settled set is `SETTLED` **and** `INITIATED`, and its grant
        pipeline term is the sum, over the period's proposals in status `SUBMITTED`,
        of `requested_amount_cents` multiplied by `award_probability_bps` divided by
        10000 and rounded half up - the same term also entering each funder's source
        total."

        Design: Corner/Calculations/calc_diversification_recognized_basis_excludes_initiated_cash_and_draft_pipeline
        """
        ctx = _setup_settled_membership_initiated_events_and_a_draft_proposal()

        projection = read_sustainability(ctx["period"]["id"], basis="PIPELINE")
        assert projection["basis"] == "PIPELINE"
        assert projection["recognized_revenue_cents"] == 500000
        assert projection["membership_share_bps"] == 2000
        assert projection["events_share_bps"] == 8000
        assert projection["grants_share_bps"] == 0
        assert projection["concentration_hhi"] == 6800
        assert projection["top_source_share_bps"] == 0

        assert read_fiscal_period(ctx["period"]["id"])["concentration_hhi"] == 10000


def _setup_project_restricted_award_of_350001():
    """A PROJECT_RESTRICTED 350001-cent award over a 2026-09-01..2027-07-31 window
    on SEMIANNUAL reporting, so the principal splits into two buckets."""
    return setup_awarded_restricted_proposal(
        requested_amount_cents=350001,
        award_date="2026-08-01",
        reporting_cadence="SEMIANNUAL",
        restriction_type="PROJECT_RESTRICTED",
        restriction_start_date="2026-09-01",
        restriction_end_date="2027-07-31",
        legal_name="Ironwood Trust",
        title="Housing accountability project",
    )


class TestReleaseWaterfallFillsTheEarliestBucketFirst:
    def test_the_odd_cent_is_parked_in_the_last_bucket_alone(self):
        """350001 over two semiannual buckets floors the base at 175000 and hands
        the whole leftover to the bucket with the highest due date.

        PRD: "A base share is the awarded amount divided by `report_count` and
        **floored**; every bucket except the last receives exactly that base as its
        `allocated_release_cents`, and the last bucket - the one with the highest
        `due_date` - receives the base plus the entire leftover, that is the awarded
        amount minus the base times the report count."

        Design: Corner/Calculations/calc_release_waterfall_fills_earliest_bucket_and_parks_remainder_last
        """
        ctx = _setup_project_restricted_award_of_350001()

        awarded = ctx["proposal"]
        assert awarded["report_count"] == 2
        assert awarded["awarded_amount_cents"] == 350001
        assert awarded["unreleased_cents"] == 350001
        assert awarded["released_cents"] == 0
        assert awarded["returned_cents"] == 0

        first, second = ctx["reports"]
        assert first["sequence_no"] == 1
        assert first["period_start"] == "2026-09-01"
        assert first["period_end"] == "2027-02-28"
        assert first["due_date"] == "2027-04-14"
        assert first["allocated_release_cents"] == 175000
        assert first["consumed_release_cents"] == 0

        assert second["sequence_no"] == 2
        assert second["period_start"] == "2027-03-01"
        assert second["period_end"] == "2027-07-31"
        assert second["due_date"] == "2027-09-14"
        assert second["allocated_release_cents"] == 175001
        assert second["consumed_release_cents"] == 0

    def test_a_180000_release_fills_bucket_one_before_spilling_5000(self):
        """The earliest bucket is taken to its own cap of 175000 and only the
        residue reaches the second bucket.

        PRD: "When the request survives, the buckets are filled strictly in
        `due_date` ascending order: each bucket absorbs the lesser of the amount
        still to place and its own remaining headroom, its `consumed_release_cents`
        rises by that fill, and the walk stops as soon as nothing is left to place."

        Design: Corner/Calculations/calc_release_waterfall_fills_earliest_bucket_and_parks_remainder_last
        """
        ctx = _setup_project_restricted_award_of_350001()

        released = release_funds(ctx["proposal"]["id"], 180000)
        assert released["status"] == "AWARDED"
        assert released["released_cents"] == 180000
        assert released["unreleased_cents"] == 170001
        assert released["returned_cents"] == 0
        assert (
            released["released_cents"]
            + released["unreleased_cents"]
            + released["returned_cents"]
            == 350001
        )

        first, second = list_proposal_reports(ctx["proposal"]["id"])
        assert first["consumed_release_cents"] == 175000
        assert first["allocated_release_cents"] == 175000
        assert second["consumed_release_cents"] == 5000
        assert second["allocated_release_cents"] == 175001

    def test_the_release_credits_the_reserve_without_shifting_the_posture(self):
        """500000 plus the released 180000 is 680000, still short of the 1000000
        five-month target, so the period stays on WATCH.

        PRD: "The fiscal period's `reserve_balance_cents` is **credited** by the
        released amount and its `reserve_months_ratio_bps` and
        `sustainability_posture` are recomputed, which means a large release can
        improve the posture that governs the next release."

        Design: Corner/Calculations/calc_release_waterfall_fills_earliest_bucket_and_parks_remainder_last
        """
        ctx = _setup_project_restricted_award_of_350001()
        release_funds(ctx["proposal"]["id"], 180000)

        period = read_fiscal_period(ctx["period"]["id"])
        assert period["reserve_balance_cents"] == 680000

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["reserve_months_target"] == 5
        assert picture["operating_reserve_target_cents"] == 1000000
        assert picture["reserve_months_ratio_bps"] == 34000
        assert picture["sustainability_posture"] == "WATCH"


class TestReleaseCapBoundaryIsRoundedNotTruncated:
    def test_one_cent_over_the_rounded_cap_is_refused(self):
        """6000 bps of 350001 is 210000.6, which rounds half up to 210001, so a
        210002-cent request breaks the cap and nothing is written.

        PRD: "The request must not exceed `unreleased_cents` multiplied by
        `restricted_release_cap_pct_bps` divided by 10000, rounded half up, using
        the posture computed from the reserve balance **as it stands before** this
        release is credited."

        Design: Corner/Calculations/calc_release_cap_boundary_rejects_one_cent_over_and_admits_the_cap_exactly
        """
        ctx = _setup_project_restricted_award_of_350001()
        assert read_sustainability(ctx["period"]["id"])[
            "restricted_release_cap_pct_bps"
        ] == 6000

        validate_error(
            api_client.release_restricted_funds(
                ctx["proposal"]["id"], {"request_amount_cents": 210002}, FC_HEADERS
            ),
            ApiErrorId.ERR_RELEASE_CAP_EXCEEDED,
        )

        blocked = read_proposal(ctx["proposal"]["id"])
        assert blocked["released_cents"] == 0
        assert blocked["unreleased_cents"] == 350001
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 500000

    def test_the_cap_itself_is_admitted_and_drawn_down_in_bucket_order(self):
        """210001 is exactly the rounded cap, so it is released and the waterfall
        fills 175000 then 35001 - a truncated cap of 210000 would have refused this
        request.

        PRD: "`request_amount_cents` moves from `unreleased_cents` to
        `released_cents`, so that `unreleased_cents` becomes the awarded amount less
        `released_cents` less `returned_cents`."

        Design: Corner/Calculations/calc_release_cap_boundary_rejects_one_cent_over_and_admits_the_cap_exactly
        """
        ctx = _setup_project_restricted_award_of_350001()

        released = release_funds(ctx["proposal"]["id"], 210001)
        assert released["released_cents"] == 210001
        assert released["unreleased_cents"] == 140000
        assert released["returned_cents"] == 0

        first, second = list_proposal_reports(ctx["proposal"]["id"])
        assert first["consumed_release_cents"] == 175000
        assert second["consumed_release_cents"] == 35001

        period = read_fiscal_period(ctx["period"]["id"])
        assert period["reserve_balance_cents"] == 710001
        picture = read_sustainability(ctx["period"]["id"])
        assert picture["reserve_months_ratio_bps"] == 35500
        assert picture["sustainability_posture"] == "WATCH"


class TestUnrestrictedReportScheduleRunsFromAwardDateToPeriodEnd:
    def test_the_window_is_the_award_date_to_the_periods_end_date(self):
        """With no restriction window to follow, a 2026-08-01 award inside a period
        ending 2027-07-31 spans twelve months and yields two semiannual reports.

        PRD: "The series spans the restricted funding window for a restricted
        proposal - from `restriction_start_date` to `restriction_end_date` - and, for
        an `UNRESTRICTED` proposal, from the `award_date` to the fiscal period's
        `end_date`."

        Design: Corner/Calculations/calc_report_schedule_for_an_unrestricted_award_runs_from_award_date_to_period_end
        """
        ctx = setup_awarded_unrestricted_proposal(
            requested_amount_cents=350000,
            award_date="2026-08-01",
            reporting_cadence="SEMIANNUAL",
            legal_name="Ironwood Trust",
            title="General operating support",
        )

        awarded = ctx["proposal"]
        assert awarded["status"] == "AWARDED"
        assert awarded["report_count"] == 2
        assert awarded["awarded_amount_cents"] == 350000
        assert awarded["unreleased_cents"] == 350000

        first, second = ctx["reports"]
        assert first["sequence_no"] == 1
        assert first["period_start"] == "2026-08-01"
        assert first["period_end"] == "2027-01-31"
        assert second["sequence_no"] == 2
        assert second["period_start"] == "2027-02-01"
        assert second["period_end"] == "2027-07-31"

    def test_each_period_end_carries_forty_five_days_of_grace(self):
        """2027-01-31 plus 45 days is 2027-03-17 and 2027-07-31 plus 45 days is
        2027-09-14, and both obligations start out SCHEDULED.

        PRD: "Its `due_date` is `period_end` plus **45 days** of grace."

        Design: Corner/Calculations/calc_report_schedule_for_an_unrestricted_award_runs_from_award_date_to_period_end
        """
        ctx = setup_awarded_unrestricted_proposal(
            requested_amount_cents=350000,
            award_date="2026-08-01",
            reporting_cadence="SEMIANNUAL",
            legal_name="Ironwood Trust",
            title="General operating support",
        )

        first, second = ctx["reports"]
        assert first["due_date"] == "2027-03-17"
        assert first["status"] == "SCHEDULED"
        assert first["consumed_release_cents"] == 0
        assert first["spend_reported_cents"] is None
        assert first["variance_bps"] is None
        assert first["submitted_at"] is None
        assert second["due_date"] == "2027-09-14"
        assert second["status"] == "SCHEDULED"

    def test_an_evenly_divisible_award_parks_no_remainder(self):
        """350000 divides exactly across two buckets, so both hold 175000 and the
        last bucket receives no leftover at all.

        PRD: "The remainder always lands in the last bucket and is never spread
        across buckets."

        Design: Corner/Calculations/calc_report_schedule_for_an_unrestricted_award_runs_from_award_date_to_period_end
        """
        ctx = setup_awarded_unrestricted_proposal(
            requested_amount_cents=350000,
            award_date="2026-08-01",
            reporting_cadence="SEMIANNUAL",
            legal_name="Ironwood Trust",
            title="General operating support",
        )

        first, second = ctx["reports"]
        assert first["allocated_release_cents"] == 175000
        assert second["allocated_release_cents"] == 175000
        assert (
            first["allocated_release_cents"] + second["allocated_release_cents"] == 350000
        )


def _setup_member_activated_on_the_last_day_of_august():
    """An ACTIVE member on a MONTHLY 2500 tier whose activating contribution was
    received 2026-08-31."""
    period = open_fiscal_period()
    tier = _published_sustainer()
    member = enrol_member(tier["id"], email="ana@example.org", full_name="Ana Ruiz")
    contribution = record_contribution(
        period["id"],
        "MEMBERSHIP",
        2500,
        member_id=member["id"],
        received_date="2026-08-31",
    )
    settle_contribution(contribution["id"])
    return {"period": period, "tier": tier, "member": member}


class TestRenewalMonthClampIsStickyAcrossTheNextRenewal:
    def test_the_thirty_first_clamps_to_the_last_day_of_september(self):
        """One calendar month from 2026-08-31 has no 31st, so the renewal date
        clamps to 2026-09-30 rather than spilling into October.

        PRD: "Where the anchor day-of-month does not exist in the target month, the
        date clamps to the **last day of the target month** and never spills into the
        month after."

        Design: Corner/Calculations/calc_renewal_month_clamp_is_sticky_across_the_next_renewal
        """
        ctx = _setup_member_activated_on_the_last_day_of_august()

        activated = read_member(ctx["member"]["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["cycle_start_date"] == "2026-08-31"
        assert activated["next_renewal_date"] == "2026-09-30"
        assert activated["grace_expires_at"] is None

    def test_the_clamped_anchor_is_never_recovered_by_the_next_renewal(self):
        """RENEW advances the anchor to the clamped 2026-09-30, so the following
        renewal falls on 2026-10-30 and the original 31st is gone for good.

        PRD: "The anchor is always the day-of-month of the *current*
        `cycle_start_date`, and because every renewal advances `cycle_start_date` to
        the `next_renewal_date` it just consumed, a clamp is sticky and the original
        day never recovers: a member activated on 2026-08-31 on a monthly cadence
        renews next on 2026-09-30, and after that renewal - with `cycle_start_date`
        now 2026-09-30 - the following renewal falls on 2026-10-30, not 2026-10-31."

        Design: Corner/Calculations/calc_renewal_month_clamp_is_sticky_across_the_next_renewal
        """
        ctx = _setup_member_activated_on_the_last_day_of_august()

        renewed = member_lifecycle(ctx["member"]["id"], "RENEW")
        assert renewed["status"] == "ACTIVE"
        assert renewed["cycle_start_date"] == "2026-09-30"
        assert renewed["next_renewal_date"] == "2026-10-30"
        assert renewed["consecutive_renewals"] == 1
        assert renewed["grace_expires_at"] is None


def _setup_two_reports_ready_for_review():
    """The 350001-cent award with 180000 released - bucket 1 consumed 175000 and
    bucket 2 consumed 5000 - observed with the clock past both period ends."""
    ctx = _setup_project_restricted_award_of_350001()
    release_funds(ctx["proposal"]["id"], 180000)
    set_clock("2027-08-01T00:00:00Z")
    ctx["reports"] = list_proposal_reports(ctx["proposal"]["id"])
    return ctx


def _clear_the_first_report(ctx):
    """Reports must be submitted in order - every report with a lower
    `sequence_no` must already be ACCEPTED or WAIVED - so bucket 1 is reported at
    exactly its 175000-cent consumption (variance 0) and accepted before bucket 2
    can be touched at all."""
    first = ctx["reports"][0]
    submit_report(first["id"], 175000)
    review_report(first["id"], "ACCEPT")


class TestVarianceToleranceIsInclusiveAtTwoThousandBasisPoints:
    def test_a_variance_of_exactly_minus_two_thousand_is_accepted(self):
        """140000 against a 175000 bucket is -2000 bps, which is no more than the
        tolerance, so the report reaches ACCEPTED and the proposal is compliant.

        PRD: "`ACCEPT` requires the absolute value of `variance_bps` to be no more
        than 2000; a wider swing must be returned for rework instead, and accepting
        it is refused with `ERR_VARIANCE_UNACCEPTABLE` (HTTP 409)."

        Design: Corner/Calculations/calc_variance_bps_accepts_exactly_minus_two_thousand_and_refuses_minus_two_thousand_two
        """
        ctx = _setup_two_reports_ready_for_review()
        first = ctx["reports"][0]

        submitted = submit_report(first["id"], 140000)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["spend_reported_cents"] == 140000
        assert submitted["variance_bps"] == -2000
        assert submitted["submitted_at"].startswith("2027-08-01T00:00:00")

        accepted = review_report(first["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"
        assert read_proposal(ctx["proposal"]["id"])["compliance_flag"] == "COMPLIANT"

    def test_a_variance_of_minus_two_thousand_and_two_cannot_be_accepted(self):
        """3999 against a 5000 bucket is -2002 bps, two basis points outside the
        tolerance, and the refusal leaves the report in SUBMITTED.

        PRD: "Submission stamps `submitted_at` with the logical clock and computes
        `variance_bps` as 10000 times the difference between `spend_reported_cents`
        and `consumed_release_cents`, divided by `consumed_release_cents`, rounded
        half up - a signed figure, negative when the newsroom underspent - and
        defined as 0 when `consumed_release_cents` is 0."

        Design: Corner/Calculations/calc_variance_bps_accepts_exactly_minus_two_thousand_and_refuses_minus_two_thousand_two
        """
        ctx = _setup_two_reports_ready_for_review()
        _clear_the_first_report(ctx)
        second = ctx["reports"][1]

        submitted = submit_report(second["id"], 3999)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["variance_bps"] == -2002

        validate_error(
            api_client.review_grant_report(
                second["id"], {"decision": "ACCEPT"}, FC_HEADERS
            ),
            ApiErrorId.ERR_VARIANCE_UNACCEPTABLE,
        )

        unchanged = read_report(second["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["spend_reported_cents"] == 3999
        assert unchanged["variance_bps"] == -2002

    def test_returning_the_wider_swing_clears_both_reported_figures(self):
        """The only route out of the refusal is RETURN, which sends the report back
        for rework with its spend and variance nulled.

        PRD: "`RETURN` moves the report to `RETURNED` and clears
        `spend_reported_cents` and `variance_bps` back to null, closing the
        `SUBMITTED -> RETURNED -> SUBMITTED` revision cycle, which is unbounded."

        Design: Corner/Calculations/calc_variance_bps_accepts_exactly_minus_two_thousand_and_refuses_minus_two_thousand_two
        """
        ctx = _setup_two_reports_ready_for_review()
        _clear_the_first_report(ctx)
        second = ctx["reports"][1]
        submit_report(second["id"], 3999)

        returned = review_report(
            second["id"],
            "RETURN",
            review_note="Spend variance exceeds the 2000 bps tolerance.",
        )
        assert returned["status"] == "RETURNED"
        assert returned["spend_reported_cents"] is None
        assert returned["variance_bps"] is None
        assert returned["consumed_release_cents"] == 5000


class TestTwoWayCostSplitAllocatesTheWholeTotal:
    def test_an_exactly_divisible_split_needs_no_remainder_adjustment(self):
        """6700 bps and 3300 bps of 100000 are 67000 and 33000 with nothing left
        over, so no participant receives an extra cent.

        PRD: "The leftover to distribute is `total_cost_cents` minus the sum of all
        the floors, a quantity that is always at least 0 and strictly less than the
        number of participants."

        Design: Corner/Calculations/calc_collaboration_two_way_cost_split_allocates_the_whole_total
        """
        period, area = setup_period_and_area(area_code="CLIMATE", area_name="Climate")
        collaboration = open_collaboration(
            area["id"],
            period["id"],
            title="Heat island investigation",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
            total_cost_cents=100000,
            lead_credit_bps=6700,
            lead_cost_share_bps=6700,
        )
        partner = add_partner(collaboration["id"], "Riverbend Public Media", 3300, 3300)

        activated = collaboration_action(collaboration["id"], "ACTIVATE")
        assert activated["status"] == "ACTIVE"
        assert activated["partner_count"] == 1
        assert activated["lead_cost_cents"] == 67000
        assert activated["syndication_revenue_cents"] == 0

        allocated = read_partner(partner["id"])
        assert allocated["status"] == "CONFIRMED"
        assert allocated["cost_owed_cents"] == 33000

    def test_the_two_buckets_close_on_the_total_exactly(self):
        """67000 plus 33000 is the whole 100000, which is the invariant the split
        must satisfy at every instant.

        PRD: "`allocated_cost_cents` is `lead_cost_cents` plus the sum of the
        `cost_owed_cents` of every `CONFIRMED` partner, and the invariant is that
        this equals `total_cost_cents` exactly, always."

        Design: Corner/Calculations/calc_collaboration_two_way_cost_split_allocates_the_whole_total
        """
        period, area = setup_period_and_area(area_code="CLIMATE", area_name="Climate")
        collaboration = open_collaboration(
            area["id"],
            period["id"],
            title="Heat island investigation",
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
            total_cost_cents=100000,
            lead_credit_bps=6700,
            lead_cost_share_bps=6700,
        )
        partner = add_partner(collaboration["id"], "Riverbend Public Media", 3300, 3300)
        collaboration_action(collaboration["id"], "ACTIVATE")

        settled = read_collaboration(collaboration["id"])
        owed = read_partner(partner["id"])["cost_owed_cents"]
        assert settled["allocated_cost_cents"] == 100000
        assert settled["total_cost_cents"] == 100000
        assert settled["lead_cost_cents"] + owed == 100000
