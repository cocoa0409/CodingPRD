"""Approved-list standing: the suspension cascade and its compensating restoration."""

import pytest

from test_helpers import assert_bid_solicitation, assert_contractor, assert_instant
from test_helpers.fixtures import (
    build_contractor,
    place_bid,
    refresh_application,
    refresh_bid,
    refresh_contractor,
    refresh_solicitation,
    set_contractor_status,
    setup_case,
    tabulate,
)


class TestSuspensionCascade:
    """One administrative write walks four rows: firm, bid, solicitation, case."""

    @pytest.fixture
    def sole_bidder_case(self):
        """A tabulated solicitation whose single responsive bid is the firm's only one."""
        return setup_case(stage="tabulated")

    def test_suspending_the_only_bidder_withdraws_its_live_bid(self, sole_bidder_case):
        """The firm's standing change is the only reason the bid leaves `RESPONSIVE`.

        PRD: "Hop two withdraws its live bids: every bid of that firm whose status
        is `SUBMITTED` or `RESPONSIVE` and whose solicitation is in `OPEN` or
        `TABULATED` moves to `WITHDRAWN_BY_PROGRAM`."

        Design: Difficulty/transitive_cascade/contractor_suspension_cascades_four_hops_to_a_failed_application
        """
        case = sole_bidder_case
        before = refresh_bid(case["bid"]["id"])
        assert before["status"] == "RESPONSIVE"
        assert before["rank"] == 1

        suspended = set_contractor_status(
            case["contractor"]["id"], "SUSPENDED", "Uninsured subcontractor on site"
        )

        assert_contractor(suspended)
        assert suspended["approved_list_status"] == "SUSPENDED"
        withdrawn = refresh_bid(case["bid"]["id"])
        assert withdrawn["status"] == "WITHDRAWN_BY_PROGRAM", (
            "The suspension withdraws the firm's live bid, got "
            f"{withdrawn['status']}"
        )

    def test_the_withdrawal_empties_the_census_and_fails_the_solicitation(
        self, sole_bidder_case
    ):
        """The recomputed census drops below the minimum, so the solicitation fails.

        PRD: "Hop three re-counts the affected solicitations: each recomputes
        `bid_count` and `responsive_bid_count`, and a solicitation in `OPEN` or
        `TABULATED` whose recomputed `responsive_bid_count` has fallen below its
        `min_bids_required` moves to `FAILED`."

        Design: Difficulty/transitive_cascade/contractor_suspension_cascades_four_hops_to_a_failed_application
        """
        case = sole_bidder_case

        set_contractor_status(
            case["contractor"]["id"], "SUSPENDED", "Uninsured subcontractor on site"
        )

        solicitation = refresh_solicitation(case["solicitation"]["id"])
        assert_bid_solicitation(solicitation)
        assert solicitation["status"] == "FAILED"
        assert solicitation["responsive_bid_count"] == 0
        assert solicitation["bid_count"] == 0, (
            "A withdrawn bid leaves the census entirely, got "
            f"{solicitation['bid_count']}"
        )
        assert solicitation.get("award_bid_id") in (None, "")
        assert solicitation["reopen_count"] == 0, (
            "Failing on a withdrawal is not a rebid, so reopen_count stays at 0"
        )

    def test_the_failed_solicitation_drives_the_case_to_bid_failed(
        self, sole_bidder_case
    ):
        """The last hop reaches the household's case file.

        PRD: "Hop four propagates to the cases: each solicitation that just failed
        drives its case `BID_OPEN → BID_FAILED`."

        Design: Difficulty/transitive_cascade/contractor_suspension_cascades_four_hops_to_a_failed_application
        """
        case = sole_bidder_case
        assert refresh_application(case["application"]["id"])["workflow_state"] == (
            "BID_OPEN"
        )

        set_contractor_status(
            case["contractor"]["id"], "SUSPENDED", "Uninsured subcontractor on site"
        )

        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_FAILED"
        )
        assert refresh_contractor(case["contractor"]["id"])["active_award_count"] == 0


class TestReinstatementRestoration:
    """Reinstatement must put the census and the ranking back exactly as they were."""

    @pytest.fixture
    def two_bidder_case(self):
        """A tabulated solicitation needing two bids, held by two approved firms."""
        case = setup_case(
            stage="bid_open", solicitation_overrides={"min_bids_required": 2}
        )
        case["bid"] = place_bid(
            case["solicitation"]["id"], case["contractor"]["id"], amount_cents=2_000_000
        )
        case["second_contractor"] = build_contractor(legal_name="Borough Builders Inc")
        case["second_bid"] = place_bid(
            case["solicitation"]["id"],
            case["second_contractor"]["id"],
            amount_cents=1_900_000,
        )
        case["solicitation"] = tabulate(case["solicitation"]["id"])
        return case

    def test_the_tabulated_census_ranks_the_lower_bid_first(self, two_bidder_case):
        """Both bids are responsive and the cheaper one takes rank 1.

        PRD: "Responsive bids are then ranked, with `rank` starting at 1:
        primarily by `amount_cents` ascending; where two bids carry the same
        amount, by the bidding firm's `performance_score` descending; and where
        those also tie, by the bid's `created_at` ascending."

        Design: Difficulty/compensating_invariant/contractor_reinstatement_restores_the_solicitation_bid_census_without_drift
        """
        case = two_bidder_case
        solicitation = case["solicitation"]

        assert solicitation["status"] == "TABULATED"
        assert solicitation["bid_count"] == 2
        assert solicitation["responsive_bid_count"] == 2
        assert refresh_bid(case["second_bid"]["id"])["rank"] == 1, (
            "The 1,900,000 bid is the low bid and takes rank 1"
        )
        assert refresh_bid(case["bid"]["id"])["rank"] == 2

    def test_suspending_one_of_two_firms_fails_the_solicitation_on_the_minimum(
        self, two_bidder_case
    ):
        """Losing one responsive bid drops the census under the required two.

        PRD: "Hop one moves the firm to `SUSPENDED` and recomputes its
        `performance_score`."

        Design: Difficulty/compensating_invariant/contractor_reinstatement_restores_the_solicitation_bid_census_without_drift
        """
        case = two_bidder_case

        set_contractor_status(
            case["second_contractor"]["id"], "SUSPENDED", "Licence lapsed mid-season"
        )

        assert (
            refresh_bid(case["second_bid"]["id"])["status"] == "WITHDRAWN_BY_PROGRAM"
        )
        assert refresh_bid(case["bid"]["id"])["status"] == "RESPONSIVE", (
            "The untouched firm's bid is never disturbed"
        )
        solicitation = refresh_solicitation(case["solicitation"]["id"])
        assert solicitation["bid_count"] == 1
        assert solicitation["responsive_bid_count"] == 1
        assert solicitation["status"] == "FAILED"
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_FAILED"
        )

    def test_reinstatement_restores_the_census_and_the_ranks_without_drift(
        self, two_bidder_case
    ):
        """The restoration is exact: same statuses, same census, same ranks.

        PRD: "Each affected solicitation recomputes `bid_count` and
        `responsive_bid_count`, and a solicitation sitting in `FAILED` whose
        recomputed `responsive_bid_count` is at or above its `min_bids_required`
        moves `FAILED → TABULATED` and drives its case `BID_FAILED → BID_OPEN`."

        Design: Difficulty/compensating_invariant/contractor_reinstatement_restores_the_solicitation_bid_census_without_drift
        """
        case = two_bidder_case
        set_contractor_status(
            case["second_contractor"]["id"], "SUSPENDED", "Licence lapsed mid-season"
        )

        reinstated = set_contractor_status(
            case["second_contractor"]["id"], "APPROVED", "Licence renewed and verified"
        )

        assert reinstated["approved_list_status"] == "APPROVED"
        assert reinstated["performance_score"] == 100, (
            "No complaint or sanction was involved, so the score is unchanged"
        )
        assert refresh_bid(case["second_bid"]["id"])["status"] == "RESPONSIVE"
        solicitation = refresh_solicitation(case["solicitation"]["id"])
        assert solicitation["bid_count"] == 2
        assert solicitation["responsive_bid_count"] == 2
        assert solicitation["status"] == "TABULATED"
        assert solicitation.get("award_bid_id") in (None, "")
        assert solicitation["reopen_count"] == 0, (
            "Restoration is not a rebid, so reopen_count stays at 0"
        )
        assert_instant(solicitation, "bid_due_at", "2026-09-01T00:00:00Z")
        assert refresh_bid(case["second_bid"]["id"])["rank"] == 1, (
            "The pre-suspension ranking returns unchanged"
        )
        assert refresh_bid(case["bid"]["id"])["rank"] == 2
        assert (
            refresh_application(case["application"]["id"])["workflow_state"]
            == "BID_OPEN"
        )
