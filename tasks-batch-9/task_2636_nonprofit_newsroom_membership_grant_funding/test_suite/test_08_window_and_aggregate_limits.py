"""Limits that no single row can violate on its own.

A half-open window and an aggregate award cap are both properties of a set, so
each scenario builds rows that are individually impeccable and only collide.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    add_partner,
    close_proposal,
    collaboration_action,
    open_collaboration,
    read_collaboration,
    read_coverage_area,
    read_partner,
    read_proposal,
    read_sustainability,
    setup_awarded_restricted_proposal,
    setup_disclosed_and_cleared_funder,
    setup_period_and_area,
    setup_submitted_proposal,
    validate_error,
)
from test_helpers.fixtures import DO_HEADERS, ED_HEADERS

_SHARED_SHAPE = {
    "total_cost_cents": 100000,
    "lead_credit_bps": 6000,
    "lead_cost_share_bps": 6000,
}


def _setup_adjacent_and_overlapping_windows():
    """Three collaborations on one beat: A over September, B starting exactly
    where A ends, and C overlapping A by a day while merely touching B."""
    period, area = setup_period_and_area(
        area_code="CLIMATE", area_name="Climate and energy"
    )
    first = open_collaboration(
        area["id"],
        period["id"],
        title="September heat mapping",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        **_SHARED_SHAPE,
    )
    first_partner = add_partner(first["id"], "Delta River Report", 4000, 4000)
    first = collaboration_action(first["id"], "ACTIVATE")

    second = open_collaboration(
        area["id"],
        period["id"],
        title="October grid audit",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-11-01T00:00:00Z",
        **_SHARED_SHAPE,
    )
    second_partner = add_partner(second["id"], "Harbor Light News", 4000, 4000)
    second = collaboration_action(second["id"], "ACTIVATE")

    third = open_collaboration(
        area["id"],
        period["id"],
        title="Late September wildfire smoke",
        window_start="2026-09-30T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        **_SHARED_SHAPE,
    )
    third_partner = add_partner(third["id"], "Summit Public Radio", 4000, 4000)

    return {
        "period": period,
        "area": area,
        "first": first,
        "first_partner": first_partner,
        "second": second,
        "second_partner": second_partner,
        "third": read_collaboration(third["id"]),
        "third_partner": third_partner,
    }


def _activate(collaboration_id):
    return api_client.collaboration_status_action(
        collaboration_id, {"action": "ACTIVATE"}, ED_HEADERS
    )


class TestHalfOpenWindowsPermitAdjacencyAndBarOverlap:
    """Touching at an instant is legal; sharing a day is not."""

    def test_a_window_starting_where_another_ends_activates_cleanly(self):
        """B begins at the exact instant A ends and still reaches ACTIVE, while
        the pending C is untouched in DRAFT.

        PRD: "no other `ACTIVE` collaboration on the same beat may have a
        half-open window overlapping this one - adjacency is expressly permitted,
        so a window starting at the exact instant a previous one ended is legal"

        Design: Difficulty/resource_temporal_overlap/rt_collaboration_half_open_windows_permit_adjacency_and_bar_overlap
        """
        ctx = _setup_adjacent_and_overlapping_windows()

        assert ctx["first"]["status"] == "ACTIVE"
        assert ctx["first"]["lead_cost_cents"] == 60000
        assert read_partner(ctx["first_partner"]["id"])["cost_owed_cents"] == 40000
        assert ctx["second"]["status"] == "ACTIVE"
        assert ctx["third"]["status"] == "DRAFT"

    def test_one_shared_day_with_an_active_window_is_refused(self):
        """C overlaps A on 2026-09-30 even though it only touches B at the
        boundary instant, and the refusal leaves every allocation at zero.

        PRD: "otherwise `ERR_COLLABORATION_WINDOW_OVERLAP` (HTTP 409)"

        Design: Difficulty/resource_temporal_overlap/rt_collaboration_half_open_windows_permit_adjacency_and_bar_overlap
        """
        ctx = _setup_adjacent_and_overlapping_windows()

        validate_error(
            _activate(ctx["third"]["id"]), ApiErrorId.ERR_COLLABORATION_WINDOW_OVERLAP
        )

        blocked = read_collaboration(ctx["third"]["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["lead_cost_cents"] == 0
        assert blocked["allocated_cost_cents"] == 0
        assert read_partner(ctx["third_partner"]["id"])["cost_owed_cents"] == 0

    def test_dissolving_the_blocking_collaboration_folds_its_partner_into_the_lead(self):
        """A's dissolution both frees the window and leaves the newsroom carrying
        the whole cost.

        PRD: "Every `CONFIRMED` partner moves to `WITHDRAWN` with
        `cost_owed_cents` reset to 0, and their shares fold into the lead - each
        partner's `credit_share_bps` is added to `lead_credit_bps` and each
        partner's `cost_share_bps` is added to `lead_cost_share_bps` - after which
        `lead_cost_cents` and `allocated_cost_cents` are recomputed so that
        `allocated_cost_cents` still equals `total_cost_cents`."

        Design: Difficulty/resource_temporal_overlap/rt_collaboration_half_open_windows_permit_adjacency_and_bar_overlap
        """
        ctx = _setup_adjacent_and_overlapping_windows()

        dissolved = collaboration_action(ctx["first"]["id"], "DISSOLVE")
        assert dissolved["status"] == "DISSOLVED"
        assert dissolved["lead_credit_bps"] == 10000
        assert dissolved["lead_cost_share_bps"] == 10000
        assert dissolved["lead_cost_cents"] == 100000
        assert dissolved["allocated_cost_cents"] == 100000

        former = read_partner(ctx["first_partner"]["id"])
        assert former["status"] == "WITHDRAWN"
        assert former["cost_owed_cents"] == 0

    def test_the_identical_activation_succeeds_once_nothing_active_overlaps(self):
        """A is no longer ACTIVE, so the same request on the same window now runs
        the cost split.

        PRD: "Activation then runs the cost split."

        Design: Difficulty/resource_temporal_overlap/rt_collaboration_half_open_windows_permit_adjacency_and_bar_overlap
        """
        ctx = _setup_adjacent_and_overlapping_windows()
        _activate(ctx["third"]["id"])
        collaboration_action(ctx["first"]["id"], "DISSOLVE")

        response = _activate(ctx["third"]["id"])
        assert response.status_code == 200

        activated = read_collaboration(ctx["third"]["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["lead_cost_cents"] == 60000
        assert activated["allocated_cost_cents"] == 100000
        assert read_partner(ctx["third_partner"]["id"])["cost_owed_cents"] == 40000

    def test_the_merely_adjacent_collaboration_is_never_a_party_to_the_conflict(self):
        """B keeps its status and its single partner through the refusal, the
        dissolution and the retry.

        PRD: "A new partner is `CONFIRMED` with `cost_owed_cents` and
        `remainder_rank` at 0 and `withdrawn_at` null, and the collaboration's
        `partner_count` - the count of `CONFIRMED` partners only - rises by 1 along
        with its `version`."

        Design: Difficulty/resource_temporal_overlap/rt_collaboration_half_open_windows_permit_adjacency_and_bar_overlap
        """
        ctx = _setup_adjacent_and_overlapping_windows()
        _activate(ctx["third"]["id"])
        collaboration_action(ctx["first"]["id"], "DISSOLVE")
        _activate(ctx["third"]["id"])

        untouched = read_collaboration(ctx["second"]["id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["partner_count"] == 1


_RESTRICTED_SHAPE = {
    "requested_amount_cents": 250000,
    "restriction_type": "PROGRAM_RESTRICTED",
    "restriction_start_date": "2026-09-01",
    "restriction_end_date": "2027-02-28",
    "reporting_cadence": "NONE",
    "award_probability_bps": 6000,
}


def _setup_two_awards_and_a_third_submitted():
    """One beat carrying two AWARDED restricted grants of 250000 and a third
    identical proposal from a third funder sitting in SUBMITTED."""
    period, area = setup_period_and_area(
        area_code="HOUSING", area_name="Housing and homelessness"
    )
    funders = []
    for legal_name in (
        "First Ward Foundation",
        "Second Street Trust",
        "Third Avenue Fund",
    ):
        pair = setup_disclosed_and_cleared_funder(
            area["id"],
            legal_name=legal_name,
            disclosure_text=(
                f"{legal_name} funds housing coverage; the desk retains "
                "editorial control."
            ),
        )
        funders.append(pair["funder"])

    first = setup_awarded_restricted_proposal(
        title="Housing court watch",
        period=period,
        area=area,
        funder=funders[0],
        **_RESTRICTED_SHAPE,
    )["proposal"]
    second = setup_awarded_restricted_proposal(
        title="Tenant hotline data",
        period=period,
        area=area,
        funder=funders[1],
        **_RESTRICTED_SHAPE,
    )["proposal"]
    third = setup_submitted_proposal(
        funders[2]["id"],
        period["id"],
        area["id"],
        title="Public housing repairs backlog",
        **_RESTRICTED_SHAPE,
    )
    return {
        "period": period,
        "area": area,
        "funders": funders,
        "first": first,
        "second": second,
        "third": third,
    }


def _award(proposal_id):
    return api_client.grant_proposal_record_outcome(
        proposal_id,
        {
            "outcome": "AWARDED",
            "awarded_amount_cents": 250000,
            "award_date": "2026-08-15",
        },
        DO_HEADERS,
    )


class TestTheThirdRestrictedAwardOnOneBeatBreaksTheAggregateCap:
    """Each proposal is individually valid; only their collective count offends."""

    def test_two_overlapping_restricted_awards_fill_the_beat(self):
        """The beat counts both AWARDED restricted grants and the third proposal
        is still merely SUBMITTED.

        PRD: "The cap of two also governs `restricted_grant_count`, which counts
        restricted proposals on the beat in status `AWARDED` or `SUSPENDED`."

        Design: Difficulty/resource_temporal_overlap/rt_third_restricted_award_on_one_area_exceeds_aggregate_cap
        """
        ctx = _setup_two_awards_and_a_third_submitted()

        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 2
        assert ctx["third"]["status"] == "SUBMITTED"

    def test_the_third_award_is_refused_on_the_collective_count_alone(self):
        """The refused proposal keeps an empty ledger and the beat's count does
        not budge.

        PRD: "One further gate is an **aggregate** one: for a restricted proposal,
        the beat may not already carry two proposals in status `AWARDED` whose
        restriction windows overlap this one's - each of those proposals is
        individually valid and only the collective count offends, and the refusal
        is `ERR_RESTRICTED_GRANT_CAP_EXCEEDED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/rt_third_restricted_award_on_one_area_exceeds_aggregate_cap
        """
        ctx = _setup_two_awards_and_a_third_submitted()

        validate_error(
            _award(ctx["third"]["id"]), ApiErrorId.ERR_RESTRICTED_GRANT_CAP_EXCEEDED
        )

        blocked = read_proposal(ctx["third"]["id"])
        assert blocked["status"] == "SUBMITTED"
        assert blocked["awarded_amount_cents"] == 0
        assert blocked["unreleased_cents"] == 0
        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 2

    def test_closing_one_award_returns_its_principal_and_frees_the_slot(self):
        """CLOSED is outside the counted population, so the beat drops to one.

        PRD: "Closure waives every still-`SCHEDULED` report, adds any remaining
        `unreleased_cents` to `returned_cents` and zeroes it, recomputes the fiscal
        period's sustainability fields and the beat's `restricted_grant_count`, and
        leaves the proposal in the terminal status `CLOSED`."

        Design: Difficulty/resource_temporal_overlap/rt_third_restricted_award_on_one_area_exceeds_aggregate_cap
        """
        ctx = _setup_two_awards_and_a_third_submitted()

        closed = close_proposal(
            ctx["first"]["id"],
            closure_justification=(
                "Grantor agreed to terminate the award; unreleased principal "
                "returned."
            ),
        )
        assert closed["status"] == "CLOSED"
        assert closed["unreleased_cents"] == 0
        assert closed["returned_cents"] == 250000
        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 1

    def test_the_identical_award_succeeds_once_a_slot_is_free(self):
        """Nothing about the third request changes; only the population it is
        measured against does.

        PRD: "When `reporting_cadence` is not `NONE`, the award generates a
        contiguous series of reporting periods."

        Design: Difficulty/resource_temporal_overlap/rt_third_restricted_award_on_one_area_exceeds_aggregate_cap
        """
        ctx = _setup_two_awards_and_a_third_submitted()
        _award(ctx["third"]["id"])
        close_proposal(
            ctx["first"]["id"], closure_justification="Grantor terminated the award."
        )

        response = _award(ctx["third"]["id"])
        assert response.status_code == 200

        awarded = read_proposal(ctx["third"]["id"])
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_amount_cents"] == 250000
        assert awarded["unreleased_cents"] == 250000
        assert awarded["report_count"] == 0
        assert read_coverage_area(ctx["area"]["id"])["restricted_grant_count"] == 2

    def test_a_closed_award_still_counts_as_recognized_grant_revenue(self):
        """All three awards sit in the recognized total even though one is closed,
        which is what puts the reserve target at four months.

        PRD: "`GRANTS` is the sum of `awarded_amount_cents` over the period's
        grant proposals in status `AWARDED` or `CLOSED`, plus the basis's pipeline
        term."

        Design: Difficulty/resource_temporal_overlap/rt_third_restricted_award_on_one_area_exceeds_aggregate_cap
        """
        ctx = _setup_two_awards_and_a_third_submitted()
        _award(ctx["third"]["id"])
        close_proposal(
            ctx["first"]["id"], closure_justification="Grantor terminated the award."
        )
        _award(ctx["third"]["id"])

        picture = read_sustainability(ctx["period"]["id"])
        assert picture["recognized_revenue_cents"] == 750000
        assert picture["grants_share_bps"] == 10000
        assert picture["concentration_hhi"] == 10000
        assert picture["top_source_share_bps"] == 3333
        assert picture["reserve_months_target"] == 4
