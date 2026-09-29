"""Two deep cascades: one logged contact, and one overdue report.

Each starts at a row that owns neither money nor a gate and settles several hops
away, in the reserve balance of a fiscal period.
"""

import pytest

from test_helpers import (
    open_fiscal_period,
    read_coverage_area,
    read_fiscal_period,
    read_funder,
    read_proposal,
    read_report,
    read_transparency_report,
    register_coverage_area,
    release_funds,
    run_daily_sweep,
    setup_awarded_restricted_proposal,
    setup_delinquent_award,
    setup_disclosed_and_cleared_funder,
    log_influence_contact,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.fixtures import ED_HEADERS


def _setup_released_award_on_an_affiliated_funder():
    """A climate beat funded by a foundation affiliated to it, with 210000 of the
    350000 award already released into operations."""
    period = open_fiscal_period(
        monthly_expense_base_cents=200000, reserve_balance_cents=500000
    )
    area = register_coverage_area(
        area_code="CLIMATE",
        name="Climate and energy",
        editorial_lead_user_id="user-ed-7",
    )
    pair = setup_disclosed_and_cleared_funder(
        area["id"],
        legal_name="Northgate Foundation",
        affiliated=True,
        disclosure_text=(
            "Northgate funds climate coverage; assignment and publication "
            "decisions rest with the climate desk."
        ),
    )
    ctx = setup_awarded_restricted_proposal(
        period=period,
        area=area,
        funder=pair["funder"],
        disclosure=pair["disclosure"],
        reporting_cadence="SEMIANNUAL",
        title="Grid resilience investigation",
        award_probability_bps=7000,
    )
    ctx["proposal"] = release_funds(ctx["proposal"]["id"], 210000)
    ctx["period"] = read_fiscal_period(period["id"])
    return ctx


def _log_editorial_direction_request(ctx):
    return log_influence_contact(
        ctx["funder"]["id"],
        contact_type="EDITORIAL_DIRECTION_REQUEST",
        occurred_at="2026-08-01T00:00:00Z",
        summary="Program officer asked the newsroom to drop the utility-rate story.",
        coverage_area_id=ctx["area"]["id"],
    )


class TestInfluenceContactCascadesFiveHopsDeep:
    """One POST of an influence contact, five hops of consequence."""

    def test_the_award_and_release_leave_the_reserve_at_710000(self):
        """Releasing 210000 credits the reserve, which is the balance the
        clawback later has to reverse.

        PRD: "The fiscal period's `reserve_balance_cents` is **credited** by the
        released amount and its `reserve_months_ratio_bps` and
        `sustainability_posture` are recomputed, which means a large release can
        improve the posture that governs the next release."

        Design: Difficulty/transitive_cascade/tc_influence_contact_five_hop_cascade_suspends_awarded_grant
        """
        ctx = _setup_released_award_on_an_affiliated_funder()

        assert ctx["period"]["reserve_balance_cents"] == 710000
        assert ctx["period"]["reserve_months_target"] == 5
        assert ctx["period"]["sustainability_posture"] == "WATCH"
        assert ctx["funder"]["independence_risk_score"] == 20

    def test_the_contact_restricts_the_funder_and_stales_its_disclosure(self):
        """Hops one to three: the funder is re-scored 20 to 28 and restricted,
        its disclosure demands re-attestation, and the beat it covers blocks.

        PRD: "In either case `triggered_restriction` on the new contact is set to
        true and the same five-hop cascade of §3.4 runs in full - disclosures to
        `REATTESTATION_REQUIRED` with `reattestation_reason` `INFLUENCE_CONTACT`,
        beats to `STALE` and `BLOCKED`, awarded grants to `SUSPENDED` with
        `FIREWALL_BREACH` and a principal clawback, and the fiscal period's whole
        sustainability picture re-derived."

        Design: Difficulty/transitive_cascade/tc_influence_contact_five_hop_cascade_suspends_awarded_grant
        """
        ctx = _setup_released_award_on_an_affiliated_funder()

        contact = _log_editorial_direction_request(ctx)
        assert contact["triggered_restriction"] is True
        assert contact["severity_weight"] == 3

        funder = read_funder(ctx["funder"]["id"])
        assert funder["status"] == "RESTRICTED"
        assert funder["prior_editorial_requests_count"] == 1
        assert funder["independence_risk_score"] == 28
        assert funder["restricted_at"].startswith("2026-08-01T00:00:00")

        disclosure = validate_success(
            api_client.get_firewall_disclosure(ctx["disclosure"]["id"], ED_HEADERS)
        )
        assert disclosure["status"] == "REATTESTATION_REQUIRED"
        assert disclosure["reattestation_reason"] == "INFLUENCE_CONTACT"

        area = read_coverage_area(ctx["area"]["id"])
        assert area["disclosure_status"] == "STALE"
        assert area["publication_gate"] == "BLOCKED"

    def test_the_blocked_beat_suspends_the_award_and_claws_the_principal_back(self):
        """Hop four: the awarded grant is suspended for firewall breach and the
        210000 already released is debited straight back out of the reserve.

        PRD: "Each such suspension claws back the principal already released: the
        whole of `released_cents` is added to `returned_cents`, `released_cents`
        returns to 0, and the proposal's fiscal period has its
        `reserve_balance_cents` debited by exactly the clawed amount."

        Design: Difficulty/transitive_cascade/tc_influence_contact_five_hop_cascade_suspends_awarded_grant
        """
        ctx = _setup_released_award_on_an_affiliated_funder()

        _log_editorial_direction_request(ctx)

        proposal = read_proposal(ctx["proposal"]["id"])
        assert proposal["status"] == "SUSPENDED"
        assert proposal["suspended_reason"] == "FIREWALL_BREACH"
        assert proposal["released_cents"] == 0
        assert proposal["returned_cents"] == 210000
        assert proposal["unreleased_cents"] == 140000
        assert proposal["awarded_amount_cents"] == 350000

        period = read_fiscal_period(ctx["period"]["id"])
        assert period["reserve_balance_cents"] == 500000

    def test_the_period_re_derives_its_whole_sustainability_picture(self):
        """Hop five: the suspended award leaves recognized revenue entirely, so
        concentration collapses to 0 and the reserve target relaxes to 3 months.

        PRD: "Every other proposal status - `SUSPENDED`, `DECLINED`,
        `WITHDRAWN`, `SUBMITTED`, `CLEARED`, `DRAFT`, `REVISION_REQUESTED` and
        `INDEPENDENCE_REVIEW` - contributes 0 on the recognized basis, which is
        why a suspension moves money *out* of recognized revenue."

        Design: Difficulty/transitive_cascade/tc_influence_contact_five_hop_cascade_suspends_awarded_grant
        """
        ctx = _setup_released_award_on_an_affiliated_funder()

        _log_editorial_direction_request(ctx)

        period = read_fiscal_period(ctx["period"]["id"])
        assert period["recognized_revenue_cents"] == 0
        assert period["concentration_hhi"] == 0
        assert period["top_source_share_bps"] == 0
        assert period["reserve_months_target"] == 3
        assert period["operating_reserve_target_cents"] == 600000
        assert period["reserve_months_ratio_bps"] == 25000
        assert period["sustainability_posture"] == "WATCH"
        assert period["restricted_release_cap_pct_bps"] == 6000

        area = read_coverage_area(ctx["area"]["id"])
        assert area["restricted_grant_count"] == 1

    def test_the_transparency_report_shows_the_beat_undisclosed_and_blocked(self):
        """The public read of the beat loses the funder from its disclosed set
        while still counting the suspended restricted award.

        PRD: "`disclosed_funder_count` counts the distinct funders that currently
        hold an `ACTIVE` firewall disclosure for this beat."

        Design: Difficulty/transitive_cascade/tc_influence_contact_five_hop_cascade_suspends_awarded_grant
        """
        ctx = _setup_released_award_on_an_affiliated_funder()

        _log_editorial_direction_request(ctx)

        report = read_transparency_report(ctx["area"]["id"])
        assert report["disclosed_funder_count"] == 0
        assert report["disclosed_funder_ids"] == []
        assert report["restricted_grant_count"] == 1
        assert report["publication_gate"] == "BLOCKED"


class TestOverdueSweepPenalisesReliabilityExactlyOnce:
    """The delinquency cascade, and the sweep's idempotence within one clock."""

    def test_the_sweep_reports_one_overdue_report_and_one_suspension(self):
        """One report past its due date moves to OVERDUE and takes its proposal
        with it, with the clawback debiting the reserve back to 500000.

        PRD: "Second, its proposal's `compliance_flag` becomes `DELINQUENT` and,
        if the proposal is in `AWARDED`, the proposal itself moves to `SUSPENDED`
        with `suspended_reason` set to `REPORT_DELINQUENCY`; the clawback then
        adds `released_cents` to `returned_cents`, sets `released_cents` to 0,
        and **debits** the fiscal period's `reserve_balance_cents` by the same
        amount, all while preserving the ledger invariant."

        Design: Difficulty/transitive_cascade/tc_report_overdue_sweep_penalises_funder_reliability_once
        """
        ctx = setup_delinquent_award(
            210000, legal_name="Quarry Hill Trust", title="Rent registry reporting"
        )

        sweep = ctx["sweep"]
        assert sweep["reports_moved_to_overdue"] == 1
        assert sweep["proposals_suspended"] == 1
        assert sweep["funders_restricted"] == 0
        assert sweep["members_moved_to_grace"] == 0
        assert sweep["members_moved_to_lapsed"] == 0
        assert sweep["swept_at"].startswith("2027-04-15T00:00:00")

        assert read_report(ctx["reports"][0]["id"])["status"] == "OVERDUE"

        proposal = ctx["proposal"]
        assert proposal["compliance_flag"] == "DELINQUENT"
        assert proposal["status"] == "SUSPENDED"
        assert proposal["suspended_reason"] == "REPORT_DELINQUENCY"
        assert proposal["released_cents"] == 0
        assert proposal["returned_cents"] == 210000
        assert proposal["unreleased_cents"] == 140000
        assert ctx["period"]["reserve_balance_cents"] == 500000

    def test_the_funder_loses_2000_bps_of_reliability_and_gains_five_risk_points(self):
        """The overdue report costs the funder 2000 basis points of reliability,
        which is worth exactly five risk points and leaves it below the hard bar.

        PRD: "`reporting_reliability_bps` itself starts at 10000 and falls by
        2000 for every grant report under this funder's proposals that has ever
        entered `OVERDUE`, with a floor of 0; that history is read across the
        funder's proposals in every status except `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/tc_report_overdue_sweep_penalises_funder_reliability_once
        """
        ctx = setup_delinquent_award(
            210000, legal_name="Quarry Hill Trust", title="Rent registry reporting"
        )

        funder = ctx["funder"]
        assert funder["reporting_reliability_bps"] == 8000
        assert funder["independence_risk_score"] == 15
        assert funder["status"] == "CLEARED"

        period = ctx["period"]
        assert period["recognized_revenue_cents"] == 0
        assert period["concentration_hhi"] == 0
        assert period["reserve_months_target"] == 3
        assert period["operating_reserve_target_cents"] == 600000
        assert period["reserve_months_ratio_bps"] == 25000
        assert period["sustainability_posture"] == "WATCH"
        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 1

    def test_a_second_sweep_on_the_same_clock_changes_nothing(self):
        """The sweep is idempotent within one clock value, so the reliability
        penalty is charged once and not twice.

        PRD: "The sweep is idempotent within a single clock value: running it
        twice without advancing the clock moves nothing the second time."

        Design: Difficulty/transitive_cascade/tc_report_overdue_sweep_penalises_funder_reliability_once
        """
        ctx = setup_delinquent_award(
            210000, legal_name="Quarry Hill Trust", title="Rent registry reporting"
        )

        second = run_daily_sweep()
        assert second["reports_moved_to_overdue"] == 0
        assert second["proposals_suspended"] == 0
        assert second["funders_restricted"] == 0

        funder = read_funder(ctx["funder"]["id"])
        assert funder["reporting_reliability_bps"] == 8000
        assert funder["independence_risk_score"] == 15
        assert read_fiscal_period(ctx["period"]["id"])["reserve_balance_cents"] == 500000

    def test_the_delinquency_cascade_never_touches_the_publication_gate(self):
        """A report delinquency is a fiscal event, not a firewall one, so the
        beat's disclosure state is left exactly as it was.

        PRD: "While every disclosure touching a beat is active, that beat's
        `disclosure_status` reads `CURRENT` and its `publication_gate` reads
        `OPEN`."

        Design: Difficulty/transitive_cascade/tc_report_overdue_sweep_penalises_funder_reliability_once
        """
        ctx = setup_delinquent_award(
            210000, legal_name="Quarry Hill Trust", title="Rent registry reporting"
        )

        area = read_coverage_area(ctx["area"]["id"])
        assert area["publication_gate"] == "OPEN"
        assert area["disclosure_status"] == "CURRENT"
