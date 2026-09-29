"""Compensating actions that must restore an identity rather than approximate it.

Each scenario observes the same conserved quantity at every step of a
mutate-and-compensate sequence, including at the point where the compensation is
itself refused.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    add_partner,
    api_client,
    collaboration_action,
    open_collaboration,
    read_collaboration,
    read_fiscal_period,
    read_funder,
    read_partner,
    read_proposal,
    read_report,
    read_sustainability,
    record_contribution,
    release_funds,
    reinstate_proposal,
    review_report,
    run_daily_sweep,
    set_clock,
    settle_contribution,
    setup_awarded_restricted_proposal,
    setup_period_and_area,
    submit_report,
    validate_error,
    validate_paginated,
    withdraw_partner,
)
from test_helpers.fixtures import ED_HEADERS, FC_HEADERS


def _ledger(proposal):
    return (
        proposal["released_cents"],
        proposal["unreleased_cents"],
        proposal["returned_cents"],
    )


def _assert_ledger_identity(proposal):
    released, unreleased, returned = _ledger(proposal)
    assert released + unreleased + returned == proposal["awarded_amount_cents"]


def _setup_awarded_semiannual_grant():
    """A 350000 restricted award on HOUSING with its semiannual reporting
    obligations generated."""
    return setup_awarded_restricted_proposal(
        requested_amount_cents=350000,
        reporting_cadence="SEMIANNUAL",
        award_probability_bps=7000,
        legal_name="Larkspur Foundation",
        title="Homelessness services audit",
    )


def _setup_clawed_back_grant():
    """The same award after 210000 was released and then swept back out by the
    delinquency cascade."""
    ctx = _setup_awarded_semiannual_grant()
    ctx["report_id"] = ctx["reports"][0]["id"]
    ctx["proposal"] = release_funds(ctx["proposal"]["id"], 210000)
    set_clock("2027-04-15T00:00:00Z")
    run_daily_sweep()
    ctx["proposal"] = read_proposal(ctx["proposal"]["id"])
    return ctx


class TestAwardLedgerIsConservedThroughReleaseClawbackAndReinstatement:
    """Three buckets, one total, at every observation point."""

    def test_the_identity_holds_across_award_release_and_clawback(self):
        """The three buckets move between each other and never change their sum,
        and the reserve is credited and debited by the same 210000.

        PRD: "`awarded_amount_cents` and `award_date` are stored,
        `unreleased_cents` is set equal to `awarded_amount_cents`, and
        `released_cents` and `returned_cents` are set to 0 - establishing the
        ledger invariant that `awarded_amount_cents` always equals
        `released_cents` plus `unreleased_cents` plus `returned_cents`, at every
        instant, for the rest of the proposal's life."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_awarded_semiannual_grant()
        report_id = ctx["reports"][0]["id"]

        awarded = ctx["proposal"]
        assert _ledger(awarded) == (0, 350000, 0)
        _assert_ledger_identity(awarded)

        released = release_funds(awarded["id"], 210000)
        assert _ledger(released) == (210000, 140000, 0)
        _assert_ledger_identity(released)
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 710000
        assert read_report(report_id)["consumed_release_cents"] == 210000

        set_clock("2027-04-15T00:00:00Z")
        run_daily_sweep()

        suspended = read_proposal(awarded["id"])
        assert suspended["status"] == "SUSPENDED"
        assert suspended["suspended_reason"] == "REPORT_DELINQUENCY"
        assert suspended["compliance_flag"] == "DELINQUENT"
        assert _ledger(suspended) == (0, 140000, 210000)
        _assert_ledger_identity(suspended)
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 500000

    def test_the_compensation_is_refused_while_the_report_is_still_overdue(self):
        """The ledger stays exactly where the clawback left it.

        PRD: "A delinquent grant can neither release funds nor be reinstated."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()

        response = api_client.reinstate_grant_proposal(
            ctx["proposal"]["id"], FC_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_PROPOSAL_DELINQUENT)

        unchanged = read_proposal(ctx["proposal"]["id"])
        assert unchanged["status"] == "SUSPENDED"
        assert _ledger(unchanged) == (0, 140000, 210000)
        _assert_ledger_identity(unchanged)

    def test_the_overdue_report_is_measured_against_the_surviving_bucket(self):
        """The clawback emptied `released_cents` but left the report's consumed
        figure at 210000, which is what the variance divides by.

        PRD: "Submission stamps `submitted_at` with the logical clock and computes
        `variance_bps` as 10000 times the difference between `spend_reported_cents`
        and `consumed_release_cents`, divided by `consumed_release_cents`, rounded
        half up - a signed figure, negative when the newsroom underspent - and
        defined as 0 when `consumed_release_cents` is 0."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()

        submitted = submit_report(ctx["report_id"], 205000)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["spend_reported_cents"] == 205000
        assert submitted["variance_bps"] == -238

    def test_acceptance_is_what_lifts_the_delinquent_flag(self):
        """Submitting the overdue report is not enough; the flag clears only on
        acceptance.

        PRD: "Acceptance is terminal for the report and recomputes the proposal's
        `compliance_flag`, which is what finally lifts a `DELINQUENT` flag -
        submitting an overdue report is not enough, the flag stays `DELINQUENT`
        until the report is accepted."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()
        submit_report(ctx["report_id"], 205000)
        assert read_proposal(ctx["proposal"]["id"])["compliance_flag"] == "DELINQUENT"

        accepted = review_report(
            ctx["report_id"], "ACCEPT", review_note="Within tolerance."
        )
        assert accepted["status"] == "ACCEPTED"
        assert read_proposal(ctx["proposal"]["id"])["compliance_flag"] == "COMPLIANT"

    def test_reinstatement_returns_the_principal_to_unreleased_not_released(self):
        """The compensation rebuilds the buckets rather than leaving the report at
        210000, and the grant must be released again from the beginning.

        PRD: "Reinstatement is the exact compensating action for the clawback:
        `returned_cents` is added back to `unreleased_cents` and set to 0,
        **every** report's `consumed_release_cents` is reset to 0 and the waterfall
        is re-run over the buckets, `suspended_reason` is cleared, and the beat's
        `restricted_grant_count` and the period's sustainability fields are
        recomputed."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()
        submit_report(ctx["report_id"], 205000)
        review_report(ctx["report_id"], "ACCEPT")

        reinstated = reinstate_proposal(ctx["proposal"]["id"])
        assert reinstated["status"] == "AWARDED"
        assert _ledger(reinstated) == (0, 350000, 0)
        assert reinstated["awarded_amount_cents"] == 350000
        assert reinstated["suspended_reason"] is None
        _assert_ledger_identity(reinstated)

        report = read_report(ctx["report_id"])
        assert report["consumed_release_cents"] == 0
        assert report["allocated_release_cents"] == 350000

    def test_the_reserve_is_not_credited_a_second_time(self):
        """Reinstatement restores principal to `unreleased_cents`, so the reserve
        stays at its pre-release figure while the award counts as revenue again.

        PRD: "Note the asymmetry with the suspension: suspension moves money from
        `released_cents`, reinstatement returns it to `unreleased_cents`, so a
        reinstated grant must be released again from the beginning."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()
        submit_report(ctx["report_id"], 205000)
        review_report(ctx["report_id"], "ACCEPT")
        reinstate_proposal(ctx["proposal"]["id"])

        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 500000

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 350000
        assert picture["concentration_hhi"] == 10000
        assert picture["reserve_months_target"] == 5
        assert picture["sustainability_posture"] == "WATCH"

    def test_the_reliability_penalty_is_not_compensated_by_reinstatement(self):
        """The funder keeps the 2000-bps hit the delinquency cost it, and the
        recomputed risk score keeps the resulting reliability term.

        PRD: "Third, because the proposal left `AWARDED`, the funder's
        `reporting_reliability_bps` drops by 2000 floored at 0 and its
        `independence_risk_score` is recomputed; if that new score reaches 60 the
        funder moves to `RESTRICTED` and the whole funder-restriction cascade of
        §3.4 runs from its second hop onward, which can suspend the funder's
        *other* awards in turn."

        Design: Difficulty/compensating_invariant/ci_award_ledger_conserved_through_release_clawback_and_reinstatement
        """
        ctx = _setup_clawed_back_grant()
        submit_report(ctx["report_id"], 205000)
        review_report(ctx["report_id"], "ACCEPT")
        reinstate_proposal(ctx["proposal"]["id"])

        funder = read_funder(ctx["funder"]["id"])
        assert funder["reporting_reliability_bps"] == 8000
        assert funder["independence_risk_score"] == 15


def _setup_two_partner_collaboration_with_syndication_revenue():
    """A 99998-cent collaboration split three ways, with one settled syndication
    contribution pointing at it."""
    period, area = setup_period_and_area(
        area_code="CLIMATE", area_name="Climate and energy"
    )
    collaboration = open_collaboration(
        area["id"],
        period["id"],
        title="Cross-border emissions audit",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        total_cost_cents=99998,
        lead_credit_bps=3400,
        lead_cost_share_bps=3400,
    )
    first = add_partner(collaboration["id"], "Delta River Report", 3300, 3300)
    second = add_partner(collaboration["id"], "Harbor Light News", 3300, 3300)
    collaboration = collaboration_action(collaboration["id"], "ACTIVATE")

    contribution = record_contribution(
        period["id"],
        "SYNDICATION",
        40000,
        collaboration_id=collaboration["id"],
        received_date="2026-09-15",
        source_label="Regional wire syndication",
    )
    settle_contribution(contribution["id"])

    return {
        "period": period,
        "area": area,
        "collaboration": collaboration,
        "first": first,
        "second": second,
    }


def _confirmed_total(collaboration_id):
    collaboration = read_collaboration(collaboration_id)
    rows, _ = validate_paginated(
        api_client.list_collaboration_partners(collaboration_id, ED_HEADERS)
    )
    owed = sum(
        partner["cost_owed_cents"]
        for partner in rows
        if partner["status"] == "CONFIRMED"
    )
    return collaboration["lead_cost_cents"] + owed


class TestPartnerWithdrawalRefoldsSharesAndPreservesAllocatedCost:
    """A withdrawal rewrites the whole apportionment, not one bucket."""

    def test_the_three_way_split_places_the_single_leftover_cent(self):
        """Both partners share the larger remainder, so the first-created partner
        takes the extra cent and the lead keeps its floor.

        PRD: "Participants are ranked by remainder descending with `created_at`
        ascending as the tie-break, and the first *leftover* ranked participants
        each receive exactly one extra cent."

        Design: Difficulty/compensating_invariant/ci_partner_withdrawal_refolds_shares_and_preserves_allocated_cost
        """
        ctx = _setup_two_partner_collaboration_with_syndication_revenue()

        assert ctx["collaboration"]["lead_cost_cents"] == 33999
        first = read_partner(ctx["first"]["id"])
        second = read_partner(ctx["second"]["id"])
        assert first["cost_owed_cents"] == 33000
        assert first["remainder_rank"] == 1
        assert second["cost_owed_cents"] == 32999
        assert second["remainder_rank"] == 2
        assert ctx["collaboration"]["allocated_cost_cents"] == 99998
        assert (
            ctx["collaboration"]["allocated_cost_cents"]
            == ctx["collaboration"]["total_cost_cents"]
        )

    def test_the_withdrawn_partner_loses_its_share_to_the_lead(self):
        """Its own bucket is zeroed and its 3300 bps fold into both of the lead's
        share figures.

        PRD: "The partner moves to `WITHDRAWN`, `withdrawn_at` is stamped with the
        logical clock, and its `cost_owed_cents` and `remainder_rank` are reset to
        0; its `credit_share_bps` is added to the collaboration's `lead_credit_bps`
        and its `cost_share_bps` to `lead_cost_share_bps`, so the two sums still
        close at 10000 bps; the split is re-run over the remaining `CONFIRMED`
        participants; `partner_count` decrements; and both the collaboration's and
        the partner's `version` increment by 1."

        Design: Difficulty/compensating_invariant/ci_partner_withdrawal_refolds_shares_and_preserves_allocated_cost
        """
        ctx = _setup_two_partner_collaboration_with_syndication_revenue()

        withdraw_partner(
            ctx["second"]["id"],
            withdrawal_reason="Partner newsroom lost its grant match.",
        )

        gone = read_partner(ctx["second"]["id"])
        assert gone["status"] == "WITHDRAWN"
        assert gone["cost_owed_cents"] == 0
        assert gone["remainder_rank"] == 0
        assert gone["withdrawn_at"].startswith("2026-08-01T00:00:00")

        collaboration = read_collaboration(ctx["collaboration"]["id"])
        assert collaboration["lead_cost_share_bps"] == 6700
        assert collaboration["lead_credit_bps"] == 6700
        assert collaboration["partner_count"] == 1

    def test_the_surviving_partners_own_bucket_falls_by_a_cent(self):
        """The re-run split hands the leftover cent to the lead instead, so the
        remaining partner drops from 33000 to 32999 while the total is unchanged.

        PRD: "`allocated_cost_cents` is `lead_cost_cents` plus the sum of the
        `cost_owed_cents` of every `CONFIRMED` partner, and the invariant is that
        this equals `total_cost_cents` exactly, always."

        Design: Difficulty/compensating_invariant/ci_partner_withdrawal_refolds_shares_and_preserves_allocated_cost
        """
        ctx = _setup_two_partner_collaboration_with_syndication_revenue()

        withdraw_partner(ctx["second"]["id"])

        collaboration = read_collaboration(ctx["collaboration"]["id"])
        survivor = read_partner(ctx["first"]["id"])
        assert collaboration["lead_cost_cents"] == 66999
        assert survivor["cost_owed_cents"] == 32999
        assert survivor["remainder_rank"] == 2
        assert collaboration["allocated_cost_cents"] == 99998
        assert 66999 + 32999 == 99998
        assert _confirmed_total(ctx["collaboration"]["id"]) == 99998

    def test_the_last_partner_cannot_withdraw_and_nothing_moves(self):
        """The refusal leaves the apportionment exactly as the first withdrawal
        left it.

        PRD: "An `ACTIVE` collaboration must retain at least one `CONFIRMED`
        partner, so the last remaining partner cannot withdraw - the collaboration
        must be dissolved instead - and the attempt is refused with
        `ERR_LAST_PARTNER_WITHDRAWAL` (HTTP 409)."

        Design: Difficulty/compensating_invariant/ci_partner_withdrawal_refolds_shares_and_preserves_allocated_cost
        """
        ctx = _setup_two_partner_collaboration_with_syndication_revenue()
        withdraw_partner(ctx["second"]["id"])

        response = api_client.withdraw_collaboration_partner(
            ctx["first"]["id"],
            {"withdrawal_reason": "Second partner also wants out."},
            ED_HEADERS,
        )
        validate_error(response, ApiErrorId.ERR_LAST_PARTNER_WITHDRAWAL)

        survivor = read_partner(ctx["first"]["id"])
        assert survivor["status"] == "CONFIRMED"
        assert survivor["cost_owed_cents"] == 32999
        assert read_collaboration(ctx["collaboration"]["id"])["allocated_cost_cents"] == 99998
        assert _confirmed_total(ctx["collaboration"]["id"]) == 99998

    def test_settlement_keeps_the_allocation_and_gathers_the_syndication_money(self):
        """Once the window has closed the collaboration settles with its total
        still fully allocated.

        PRD: "Settlement stamps `settled_at` with the logical clock and recomputes
        `syndication_revenue_cents` as the sum of `amount_cents` over every
        `SETTLED` contribution on the `SYNDICATION` revenue stream pointing at this
        collaboration."

        Design: Difficulty/compensating_invariant/ci_partner_withdrawal_refolds_shares_and_preserves_allocated_cost
        """
        ctx = _setup_two_partner_collaboration_with_syndication_revenue()
        withdraw_partner(ctx["second"]["id"])

        set_clock("2026-10-01T00:00:00Z")
        settled = collaboration_action(ctx["collaboration"]["id"], "SETTLE")
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"].startswith("2026-10-01T00:00:00")
        assert settled["allocated_cost_cents"] == 99998
        assert settled["syndication_revenue_cents"] == 40000
