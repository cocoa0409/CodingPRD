"""Sealed bidding: the closing instant, the one-live-bid rule, and award gates."""

from test_helpers import (
    api_client,
    assert_bid,
    create_bid_payload,
    make_contractor_headers,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PROGRAM_MANAGER,
    refresh_application,
    refresh_bid,
    refresh_contractor,
    refresh_solicitation,
    set_clock,
    set_contractor_status,
)


class TestBidSubmissionPrecedence:
    """The closing instant is tested before the one-live-bid rule."""

    def test_a_late_resubmission_reports_the_closed_window(self, bid_open_case):
        """A firm that already bid and files again after the cutoff hears the cutoff.

        PRD: "The bid is accepted only while the logical clock is strictly before
        the solicitation's `bid_due_at`; a bid arriving exactly at the due
        instant is late and is refused with `ERR_BID_WINDOW_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/bid_window_closure_outranks_the_duplicate_bid_constraint
        """
        solicitation_id = bid_open_case["solicitation"]["id"]
        contractor_id = bid_open_case["contractor"]["id"]
        first = validate_success(
            api_client.create_bid(
                create_bid_payload(solicitation_id, contractor_id, amount_cents=2_000_000),
                make_contractor_headers(contractor_id),
            ),
            201,
        )
        set_clock("2026-09-02T00:00:00Z")

        response = api_client.create_bid(
            create_bid_payload(
                solicitation_id,
                contractor_id,
                amount_cents=1_900_000,
                proposed_start_date="2026-09-10",
                proposed_end_date="2026-11-05",
            ),
            make_contractor_headers(contractor_id),
        )

        validate_error(response, "ERR_BID_WINDOW_CLOSED")
        solicitation = refresh_solicitation(solicitation_id)
        assert solicitation["bid_count"] == 1, (
            "The refused submission writes no bid row, so the census stays at 1, "
            f"got {solicitation['bid_count']}"
        )
        untouched = refresh_bid(first["id"])
        assert untouched["status"] == "SUBMITTED"
        assert untouched["amount_cents"] == 2_000_000

    def test_a_second_bid_inside_the_window_reports_the_duplicate(self, bid_open_case):
        """While the window is open, the same firm's second bid is the duplicate.

        PRD: "One live bid per firm per solicitation is allowed: a firm that
        already holds a bid on that solicitation in `SUBMITTED`, `RESPONSIVE`,
        `NON_RESPONSIVE` or `AWARDED` is refused with `ERR_DUPLICATE_BID`, while
        a bid previously rejected by a reopen, or withdrawn by the program, does
        not block a fresh submission."

        Design: Difficulty/priority_pair_validation_conflict/bid_window_closure_outranks_the_duplicate_bid_constraint
        """
        solicitation_id = bid_open_case["solicitation"]["id"]
        contractor_id = bid_open_case["contractor"]["id"]
        first = validate_success(
            api_client.create_bid(
                create_bid_payload(solicitation_id, contractor_id, amount_cents=2_000_000),
                make_contractor_headers(contractor_id),
            ),
            201,
        )
        assert_bid(first)

        response = api_client.create_bid(
            create_bid_payload(solicitation_id, contractor_id, amount_cents=1_900_000),
            make_contractor_headers(contractor_id),
        )

        validate_error(response, "ERR_DUPLICATE_BID")
        assert refresh_solicitation(solicitation_id)["bid_count"] == 1


class TestAwardStandingGate:
    """A tabulated solicitation still needs an approved firm at award time."""

    def test_a_probation_demotion_leaves_the_bid_and_the_census_alone(
        self, tabulated_case
    ):
        """Only suspension withdraws live bids, so probation disturbs nothing.

        PRD: "The transitions available are `APPROVED → PROBATION`, `PROBATION →
        APPROVED` (which requires a `performance_score` of at least 50),
        `APPROVED → SUSPENDED`, `PROBATION → SUSPENDED`, `SUSPENDED → APPROVED`
        and `SUSPENDED → REMOVED`."

        Design: Difficulty/cross_entity_state_dependency/award_is_gated_by_the_winning_contractors_approved_list_status
        """
        contractor_id = tabulated_case["contractor"]["id"]

        demoted = set_contractor_status(
            contractor_id,
            "PROBATION",
            "Two late completions on prior program years",
        )

        assert demoted["approved_list_status"] == "PROBATION"
        assert refresh_bid(tabulated_case["bid"]["id"])["status"] == "RESPONSIVE", (
            "A probation demotion does not run the bid-withdrawal cascade"
        )
        solicitation = refresh_solicitation(tabulated_case["solicitation"]["id"])
        assert solicitation["status"] == "TABULATED"
        assert solicitation["bid_count"] == 1
        assert solicitation["responsive_bid_count"] == 1

    def test_awarding_to_a_firm_on_probation_is_refused(self, tabulated_case):
        """The winning firm's standing is re-tested at award time.

        PRD: "The winning firm's `approved_list_status` must still be `APPROVED`
        at award time, so a firm demoted to `PROBATION`, `SUSPENDED` or `REMOVED`
        after bidding is refused with `ERR_CONTRACTOR_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/award_is_gated_by_the_winning_contractors_approved_list_status
        """
        solicitation_id = tabulated_case["solicitation"]["id"]
        set_contractor_status(
            tabulated_case["contractor"]["id"],
            "PROBATION",
            "Two late completions on prior program years",
        )

        response = api_client.award_solicitation(
            solicitation_id, {"bid_id": tabulated_case["bid"]["id"]}, PROGRAM_MANAGER
        )

        validate_error(response, "ERR_CONTRACTOR_NOT_APPROVED")
        solicitation = refresh_solicitation(solicitation_id)
        assert solicitation["status"] == "TABULATED"
        assert solicitation.get("award_bid_id") in (None, "")
        assert (
            refresh_application(tabulated_case["application"]["id"])["workflow_state"]
            == "BID_OPEN"
        )

    def test_reinstating_the_firm_lets_the_identical_award_succeed(
        self, tabulated_case
    ):
        """Restoring the firm to the approved list unblocks the same request.

        PRD: "The solicitation moves `TABULATED → AWARDED` with `award_bid_id`
        set to the winning bid and `awarded_by_user_id` set to the acting
        `X-User-ID`."

        Design: Difficulty/cross_entity_state_dependency/award_is_gated_by_the_winning_contractors_approved_list_status
        """
        solicitation_id = tabulated_case["solicitation"]["id"]
        bid_id = tabulated_case["bid"]["id"]
        contractor_id = tabulated_case["contractor"]["id"]
        set_contractor_status(
            contractor_id, "PROBATION", "Two late completions on prior program years"
        )
        validate_error(
            api_client.award_solicitation(
                solicitation_id, {"bid_id": bid_id}, PROGRAM_MANAGER
            ),
            "ERR_CONTRACTOR_NOT_APPROVED",
        )
        reinstated = set_contractor_status(
            contractor_id, "APPROVED", "Corrective action plan accepted"
        )
        assert reinstated["approved_list_status"] == "APPROVED"
        assert reinstated["performance_score"] == 100

        awarded = validate_success(
            api_client.award_solicitation(
                solicitation_id, {"bid_id": bid_id}, PROGRAM_MANAGER
            ),
            200,
        )

        assert awarded["status"] == "AWARDED"
        assert awarded["award_bid_id"] == bid_id
        assert refresh_bid(bid_id)["status"] == "AWARDED"
        case = refresh_application(tabulated_case["application"]["id"])
        assert case["workflow_state"] == "AWARDED"
        assert case["awarded_contractor_id"] == contractor_id
        assert refresh_contractor(contractor_id)["active_award_count"] == 1
