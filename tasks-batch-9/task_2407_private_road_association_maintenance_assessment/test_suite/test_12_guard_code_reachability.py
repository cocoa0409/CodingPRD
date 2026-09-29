"""Every not-found code, every roll and subdivision guard, every balloting
guard, and every bid and project guard, each reached on its own path."""
import pytest

from test_helpers import (
    api_client,
    cast_ballot,
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_secretary_headers,
    make_treasurer_headers,
    open_balloting,
    read_bid,
    read_parcel,
    read_project,
    read_proposal,
    read_roll,
    complete_project_payload,
    set_clock,
    setup_assessment_roll,
    setup_association,
    setup_member,
    setup_membership_roll,
    setup_parcel,
    setup_project_with_bids,
    setup_proposal,
    setup_road_segment,
    subdivide_payload,
    open_balloting_payload,
    revoke_ballot_payload,
    withdraw_bid_payload,
    award_payload,
    create_ballot_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import award_project as award

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
FIRST_COMMISSIONER = make_commissioner_headers("rc-1")

MAIN_SEGMENT = {
    "length_feet": 1600,
    "width_feet": 22,
    "max_grade_pct": 8,
    "surface_type": "GRAVEL",
    "turnout_count": 1,
    "turnaround_present": True,
    "bridge_present": False,
    "culvert_count": 2,
}

# Twelve identifiers that were never issued, one per entity family.
UNISSUED = {
    "association": "00000000-0000-4000-8000-000000000001",
    "segment": "00000000-0000-4000-8000-000000000002",
    "parcel": "00000000-0000-4000-8000-000000000003",
    "member": "00000000-0000-4000-8000-000000000004",
    "roll": "00000000-0000-4000-8000-000000000005",
    "charge": "00000000-0000-4000-8000-000000000006",
    "proposal": "00000000-0000-4000-8000-000000000007",
    "ballot": "00000000-0000-4000-8000-000000000008",
    "project": "00000000-0000-4000-8000-000000000009",
    "bid": "00000000-0000-4000-8000-000000000010",
    "action": "00000000-0000-4000-8000-000000000011",
    "request": "00000000-0000-4000-8000-000000000012",
}

REGISTRY_READS = [
    (lambda: api_client.get_association(UNISSUED["association"], SECRETARY),
     "ERR_ASSOCIATION_NOT_FOUND"),
    (lambda: api_client.get_road_segment(UNISSUED["segment"], SECRETARY),
     "ERR_ROAD_SEGMENT_NOT_FOUND"),
    (lambda: api_client.get_parcel(UNISSUED["parcel"], SECRETARY),
     "ERR_PARCEL_NOT_FOUND"),
    (lambda: api_client.get_member(UNISSUED["member"], SECRETARY),
     "ERR_MEMBER_NOT_FOUND"),
    (lambda: api_client.get_assessment_roll(UNISSUED["roll"], SECRETARY),
     "ERR_ROLL_NOT_FOUND"),
    (lambda: api_client.get_assessment_charge(UNISSUED["charge"], SECRETARY),
     "ERR_CHARGE_NOT_FOUND"),
]

WORKFLOW_READS = [
    (lambda: api_client.get_proposal(UNISSUED["proposal"], SECRETARY),
     "ERR_PROPOSAL_NOT_FOUND"),
    (lambda: api_client.get_ballot(UNISSUED["ballot"], SECRETARY),
     "ERR_BALLOT_NOT_FOUND"),
    (lambda: api_client.get_maintenance_project(UNISSUED["project"], SECRETARY),
     "ERR_PROJECT_NOT_FOUND"),
    (lambda: api_client.get_contractor_bid(UNISSUED["bid"], SECRETARY),
     "ERR_BID_NOT_FOUND"),
    (lambda: api_client.get_delinquency_action(UNISSUED["action"], SECRETARY),
     "ERR_DELINQUENCY_ACTION_NOT_FOUND"),
    (lambda: api_client.get_connection_request(UNISSUED["request"], SECRETARY),
     "ERR_CONNECTION_REQUEST_NOT_FOUND"),
]


class TestEveryNotFoundCodeIsEntitySpecific:
    """Twelve single-resource reads on an empty database, twelve different codes."""

    def test_the_six_registry_families_each_answer_with_their_own_code(self, api):
        """PRD §2.10: "Path-templated identifiers resolve, left to right — otherwise
        the matching 404: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`,
        `ERR_CHARGE_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DELINQUENCY_ACTION_NOT_FOUND`,
        or `ERR_CONNECTION_REQUEST_NOT_FOUND`."

        Design: Corner/errors/every_entity_not_found_code_is_reachable_on_an_empty_database
        """
        observed = []
        for read, expected_error_id in REGISTRY_READS:
            body = validate_error(read(), expected_error_id, 404)
            observed.append(body["error_id"])

        assert observed == [expected for _, expected in REGISTRY_READS]
        assert len(set(observed)) == 6

    def test_the_six_workflow_families_each_answer_with_their_own_code(self, api):
        """PRD §2.10: "Path-templated identifiers resolve, left to right — otherwise
        the matching 404: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`,
        `ERR_CHARGE_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DELINQUENCY_ACTION_NOT_FOUND`,
        or `ERR_CONNECTION_REQUEST_NOT_FOUND`."

        Design: Corner/errors/every_entity_not_found_code_is_reachable_on_an_empty_database
        """
        observed = []
        for read, expected_error_id in WORKFLOW_READS:
            body = validate_error(read(), expected_error_id, 404)
            observed.append(body["error_id"])

        assert observed == [expected for _, expected in WORKFLOW_READS]
        assert len(set(observed)) == 6

    def test_no_two_of_the_twelve_reads_share_an_error_id(self, api):
        """PRD §2.10: "Path-templated identifiers resolve, left to right — otherwise
        the matching 404: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`,
        `ERR_CHARGE_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, `ERR_BALLOT_NOT_FOUND`,
        `ERR_PROJECT_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DELINQUENCY_ACTION_NOT_FOUND`,
        or `ERR_CONNECTION_REQUEST_NOT_FOUND`."

        Design: Corner/errors/every_entity_not_found_code_is_reachable_on_an_empty_database
        """
        observed = []
        for read, expected_error_id in REGISTRY_READS + WORKFLOW_READS:
            response = read()
            assert response.status_code == 404
            observed.append(validate_error(response, expected_error_id, 404)["error_id"])

        assert len(observed) == 12
        assert len(set(observed)) == 12


class TestRollAndSubdivisionGuardCodes:
    """A wrong frontage sum, a roll already certified, and a roll with nothing
    to spread."""

    def _one_parcel_and_a_draft_roll(self):
        """Association A1: one 290-foot parcel, its verified member, and a DRAFT
        FY2026 roll of 4,000,000 cents."""
        association = setup_association(
            name="Guard Codes Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Guard Codes Main", **MAIN_SEGMENT)
        parcel = setup_parcel(
            segment["id"],
            deed_book_page="DB160-P01",
            frontage_feet=290,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=6,
            covenant_recorded=True,
        )
        setup_member(
            parcel["id"],
            verified=True,
            owner_name="A. Whitcomb",
            deed_book_page="DB160-P01",
            deed_recorded_date="2019-04-11",
        )
        roll = setup_assessment_roll(
            association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )
        return {"association": association, "segment": segment, "parcel": parcel, "roll": roll}

    def test_children_that_miss_the_parent_frontage_by_ten_feet_are_rejected(self, api):
        """PRD §3.2: "an array whose frontages do not sum exactly to the parent's
        `frontage_feet` is rejected with `ERR_FRONTAGE_MISMATCH`."

        Design: Corner/errors/roll_and_subdivision_guard_codes_are_each_reachable
        """
        scenario = self._one_parcel_and_a_draft_roll()
        parcel = scenario["parcel"]

        validate_error(
            api_client.subdivide_parcel(
                parcel["id"],
                subdivide_payload([
                    {"deed_book_page": "DB160-P01A", "frontage_feet": 200},
                    {"deed_book_page": "DB160-P01B", "frontage_feet": 80},
                ]),
                SECRETARY,
            ),
            "ERR_FRONTAGE_MISMATCH",
            422,
        )

        untouched = read_parcel(parcel["id"])
        assert untouched["status"] == "ACTIVE"
        assert untouched["version"] == 1
        assert untouched["frontage_feet"] == 290

    def test_the_rejected_split_created_no_children(self, api):
        """PRD §2.10: "The children's `frontage_feet` sum exactly to the parent
        parcel's `frontage_feet` — otherwise `ERR_FRONTAGE_MISMATCH` (422)."

        Design: Corner/errors/roll_and_subdivision_guard_codes_are_each_reachable
        """
        scenario = self._one_parcel_and_a_draft_roll()
        parcel = scenario["parcel"]

        validate_error(
            api_client.subdivide_parcel(
                parcel["id"],
                subdivide_payload([
                    {"deed_book_page": "DB160-P01A", "frontage_feet": 200},
                    {"deed_book_page": "DB160-P01B", "frontage_feet": 80},
                ]),
                SECRETARY,
            ),
            "ERR_FRONTAGE_MISMATCH",
            422,
        )

        _, meta = validate_paginated(
            api_client.list_parcels(SECRETARY, params={"parent_parcel_id": parcel["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_roll_already_certified_cannot_be_certified_again(self, api):
        """PRD §3.4: "The roll moves `DRAFT → CERTIFIED`, `certified_at` is stamped
        with the current logical-clock instant, and the roll's `version` increments
        by one. A roll that is not `DRAFT` cannot be certified, which is
        `ERR_ROLL_NOT_DRAFT`."

        Design: Corner/errors/roll_and_subdivision_guard_codes_are_each_reachable
        """
        scenario = self._one_parcel_and_a_draft_roll()

        certified = validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))
        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(290.0, abs=0.0001)

        validate_error(
            api_client.certify_roll(scenario["roll"]["id"], CLERK),
            "ERR_ROLL_NOT_DRAFT",
            409,
        )

        after = read_roll(scenario["roll"]["id"])
        assert after["status"] == "CERTIFIED"
        assert after["certified_at"] == certified["certified_at"]

    def test_a_roll_with_no_assessable_parcels_cannot_certify(self, api):
        """PRD §3.4: "The sum of those units across the set becomes the roll's
        `total_share_units`. If that sum is zero the certification is rejected with
        `ERR_NO_ASSESSABLE_PARCELS`."

        Design: Corner/errors/roll_and_subdivision_guard_codes_are_each_reachable
        """
        empty_association = setup_association(
            name="Empty Roll Road Association", reserve_target_cents=1_000_000
        )
        empty_roll = setup_assessment_roll(
            empty_association["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=1_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )

        validate_error(
            api_client.certify_roll(empty_roll["id"], CLERK),
            "ERR_NO_ASSESSABLE_PARCELS",
            409,
        )

        after = read_roll(empty_roll["id"])
        assert after["status"] == "DRAFT"
        assert after["total_share_units"] == pytest.approx(0.0, abs=0.0001)
        assert after["certified_at"] is None


class TestBallotingLifecycleGuardCodes:
    """Re-opening a round, tallying early, revoking twice, and casting on the
    closing instant."""

    TWO_VOTERS = [
        {
            "deed_book_page": "DB161-P01",
            "frontage_feet": 240,
            "usage_class": "RESIDENTIAL_YEAR_ROUND",
            "trips_per_day": 4,
            "covenant_recorded": True,
        },
        {
            "deed_book_page": "DB161-P02",
            "frontage_feet": 200,
            "usage_class": "SEASONAL",
            "trips_per_day": 2,
            "covenant_recorded": True,
        },
    ]

    def _open_round(self):
        """Two verified members and a GRADING proposal balloting until
        2026-08-15T00:00:00Z."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_membership_roll(
            parcel_specs=self.TWO_VOTERS,
            association_overrides={
                "name": "Ballot Guard Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Ballot Guard Main", **MAIN_SEGMENT),
        )
        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
            title="Guard chain regrade",
        )
        scenario["proposal"] = open_balloting(proposal["id"], "2026-08-15T00:00:00Z")
        return scenario

    def test_reopening_a_round_reports_the_draft_guard(self, api):
        """PRD §3.5: "A proposal that is not `DRAFT` cannot open a round, which is
        `ERR_PROPOSAL_NOT_DRAFT`."

        Design: Corner/errors/balloting_lifecycle_guard_codes_are_each_reachable
        """
        scenario = self._open_round()
        proposal = scenario["proposal"]
        assert proposal["status"] == "BALLOTING"

        validate_error(
            api_client.open_balloting(
                proposal["id"], open_balloting_payload("2026-08-20T00:00:00Z"), TREASURER
            ),
            "ERR_PROPOSAL_NOT_DRAFT",
            409,
        )

        after = read_proposal(proposal["id"])
        assert after["status"] == "BALLOTING"
        assert after["balloting_closes_at"].startswith("2026-08-15T00:00:00")

    def test_a_tally_before_the_closing_instant_is_still_open(self, api):
        """PRD §3.5: "It requires the proposal to be `BALLOTING` and requires the
        logical clock to have reached `balloting_closes_at`; a tally taken early is
        rejected with `ERR_BALLOTING_STILL_OPEN`."

        Design: Corner/errors/balloting_lifecycle_guard_codes_are_each_reachable
        """
        scenario = self._open_round()
        proposal = scenario["proposal"]
        cast_ballot(proposal, scenario["members"][0], "YES", proposal["version"])

        validate_error(
            api_client.tally_proposal(proposal["id"], TREASURER),
            "ERR_BALLOTING_STILL_OPEN",
            409,
        )

        after = read_proposal(proposal["id"])
        assert after["status"] == "BALLOTING"
        assert after["failed_tally_count"] == 0
        assert after["approved_amount_cents"] == 0

    def test_revoking_twice_reports_the_ballot_guard_not_the_version_guard(self, api):
        """PRD §3.5: "Revoking is the member's other lever. It moves the ballot
        `CAST → REVOKED`, requires that same `expected_proposal_version`, and requires
        that the ballot be `CAST` (otherwise `ERR_BALLOT_NOT_CAST`)"

        Design: Corner/errors/balloting_lifecycle_guard_codes_are_each_reachable
        """
        scenario = self._open_round()
        proposal = scenario["proposal"]
        member = scenario["members"][0]
        ballot = cast_ballot(proposal, member, "YES", proposal["version"])

        revoked = validate_success(
            api_client.revoke_ballot(
                ballot["id"],
                revoke_ballot_payload(read_proposal(proposal["id"])["version"]),
                scenario["member_headers"][0],
            )
        )
        assert revoked["status"] == "REVOKED"

        after_revoke = read_proposal(proposal["id"])
        assert after_revoke["counted_weight_total"] == 0
        assert after_revoke["yes_weight_total"] == 0
        assert after_revoke["quorum_met"] is False

        validate_error(
            api_client.revoke_ballot(
                ballot["id"],
                revoke_ballot_payload(after_revoke["version"]),
                scenario["member_headers"][0],
            ),
            "ERR_BALLOT_NOT_CAST",
            409,
        )

    def test_a_cast_at_the_closing_instant_is_already_closed(self, api):
        """PRD §3.5: "the logical clock must still be strictly before
        `balloting_closes_at` — a cast at or after the closing instant is rejected
        with `ERR_BALLOTING_CLOSED`"

        Design: Corner/errors/balloting_lifecycle_guard_codes_are_each_reachable
        """
        scenario = self._open_round()
        proposal = scenario["proposal"]
        cast_ballot(proposal, scenario["members"][0], "YES", proposal["version"])

        set_clock("2026-08-15T00:00:00Z")
        second_member = scenario["members"][1]
        validate_error(
            api_client.create_ballot(
                create_ballot_payload(
                    proposal["id"],
                    second_member["id"],
                    "NO",
                    read_proposal(proposal["id"])["version"],
                ),
                scenario["member_headers"][1],
            ),
            "ERR_BALLOTING_CLOSED",
            409,
        )

        _, meta = validate_paginated(api_client.list_proposal_ballots(proposal["id"], TREASURER))
        assert meta["total_count"] == 1


class TestBidAndProjectGuardCodes:
    """The unbonded low bid, the responsive ranking, the withdrawn bid, and the
    two terminal state guards."""

    BID_SPECS = [
        {
            "amount_cents": 400_000,
            "contractor_user_id": "c-1",
            "contractor_name": "Thrift Grading",
            "bond_on_file": False,
        },
        {
            "amount_cents": 500_000,
            "contractor_user_id": "c-2",
            "contractor_name": "Basin Grading LLC",
            "bond_on_file": True,
        },
        {
            "amount_cents": 600_000,
            "contractor_user_id": "c-3",
            "contractor_name": "Highline Roadworks",
            "bond_on_file": True,
        },
    ]

    def _three_bids(self):
        """A GRADING project for 2026-08-05..2026-08-08 carrying an unbonded
        400,000-cent bid and bonded bids of 500,000 and 600,000 cents."""
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Bid Guard Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Bid Guard Main", **MAIN_SEGMENT)
        solicited = setup_project_with_bids(
            segment["id"],
            bid_specs=self.BID_SPECS,
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )
        solicited["association"] = association
        solicited["segment"] = segment
        return solicited

    def test_the_cheapest_bid_without_a_bond_reports_the_bond_guard(self, api):
        """PRD §3.7: "the bid's `status` must be `SUBMITTED` (otherwise
        `ERR_BID_NOT_ACTIVE`); the bid's `bond_on_file` must be true (otherwise
        `ERR_BOND_NOT_ON_FILE`)"

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        unbonded, mid, high = solicited["bids"]
        assert unbonded["amount_cents"] == 400_000
        assert unbonded["bond_on_file"] is False

        validate_error(
            api_client.award_project(
                solicited["project"]["id"], award_payload(unbonded["id"]),
                make_commissioner_headers("rc-2"),
            ),
            "ERR_BOND_NOT_ON_FILE",
            409,
        )

        project = read_project(solicited["project"]["id"])
        assert project["status"] == "BID_SOLICITATION"
        assert project["awarded_bid_id"] is None
        assert read_bid(mid["id"])["status"] == "SUBMITTED"
        assert read_bid(high["id"])["status"] == "SUBMITTED"

    def test_awarding_above_the_lowest_responsive_bid_is_rejected(self, api):
        """PRD §3.7: "Candidates are ranked by `amount_cents` ascending, with ties
        broken by `created_at` ascending and never by identifier, and the first is the
        winner. If the supplied `bid_id` is not that winner — or if the candidate set
        is empty altogether — the award is rejected with
        `ERR_NOT_LOWEST_RESPONSIVE_BID`."

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        _, mid, high = solicited["bids"]

        validate_error(
            api_client.award_project(
                solicited["project"]["id"], award_payload(high["id"]),
                make_commissioner_headers("rc-2"),
            ),
            "ERR_NOT_LOWEST_RESPONSIVE_BID",
            409,
        )

        assert read_bid(mid["id"])["status"] == "SUBMITTED"
        assert read_bid(high["id"])["status"] == "SUBMITTED"
        assert read_project(solicited["project"]["id"])["status"] == "BID_SOLICITATION"

    def test_withdrawing_the_same_bid_twice_reports_the_activity_guard(self, api):
        """PRD §3.7: "the bid must be `SUBMITTED` or `AWARDED` and its
        `contractor_user_id` must equal `X-User-ID`. The bid moves to `WITHDRAWN`."

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        high = solicited["bids"][2]
        bidder = make_contractor_headers("c-3")

        withdrawn = validate_success(
            api_client.withdraw_bid(
                high["id"], withdraw_bid_payload("crew reassigned"), bidder
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        validate_error(
            api_client.withdraw_bid(
                high["id"], withdraw_bid_payload("duplicate withdrawal"), bidder
            ),
            "ERR_BID_NOT_ACTIVE",
            409,
        )
        assert read_bid(high["id"])["status"] == "WITHDRAWN"

    def test_the_award_becomes_legal_once_the_dearest_bid_withdraws(self, api):
        """PRD §3.7: "A successful award moves the project `BID_SOLICITATION →
        AWARDED` and the nominated bid `SUBMITTED → AWARDED`; every other bid on the
        project whose `status` is `SUBMITTED` moves `SUBMITTED → REJECTED`."

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        unbonded, mid, high = solicited["bids"]
        validate_success(
            api_client.withdraw_bid(
                high["id"], withdraw_bid_payload("crew reassigned"),
                make_contractor_headers("c-3"),
            )
        )

        awarded = award(solicited["project"]["id"], mid["id"])
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_bid_id"] == mid["id"]
        assert awarded["awarded_amount_cents"] == 500_000
        assert awarded["reserve_draw_cents"] == 0
        assert awarded["awarded_by_user_id"] == "rc-2"

        assert read_bid(mid["id"])["status"] == "AWARDED"
        assert read_bid(unbonded["id"])["status"] == "REJECTED"
        assert read_bid(high["id"])["status"] == "WITHDRAWN"

    def test_an_awarded_project_reports_the_solicitation_guard(self, api):
        """PRD §2.10: "The project's `status` is `BID_SOLICITATION` for bid submission
        and for award — otherwise `ERR_PROJECT_NOT_IN_SOLICITATION` (409)."

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        mid, high = solicited["bids"][1], solicited["bids"][2]
        validate_success(
            api_client.withdraw_bid(
                high["id"], withdraw_bid_payload("crew reassigned"),
                make_contractor_headers("c-3"),
            )
        )
        award(solicited["project"]["id"], mid["id"])

        validate_error(
            api_client.award_project(
                solicited["project"]["id"], award_payload(mid["id"]),
                make_commissioner_headers("rc-2"),
            ),
            "ERR_PROJECT_NOT_IN_SOLICITATION",
            409,
        )
        assert read_project(solicited["project"]["id"])["status"] == "AWARDED"

    def test_a_completed_project_reports_the_awarded_guard(self, api):
        """PRD §3.7: "The project must be `AWARDED`, failing which the request is
        rejected with `ERR_PROJECT_NOT_AWARDED`."

        Design: Corner/errors/bid_and_project_guard_codes_are_each_reachable
        """
        solicited = self._three_bids()
        mid, high = solicited["bids"][1], solicited["bids"][2]
        validate_success(
            api_client.withdraw_bid(
                high["id"], withdraw_bid_payload("crew reassigned"),
                make_contractor_headers("c-3"),
            )
        )
        award(solicited["project"]["id"], mid["id"])

        set_clock("2026-08-09T00:00:00Z")
        completed = validate_success(
            api_client.complete_project(
                solicited["project"]["id"],
                complete_project_payload("2026-08-09T00:00:00Z", 500_000),
                FIRST_COMMISSIONER,
            )
        )
        assert completed["status"] == "COMPLETE"
        assert completed["completed_at"].startswith("2026-08-09T00:00:00")
        assert completed["actual_cost_cents"] == 500_000

        validate_error(
            api_client.complete_project(
                solicited["project"]["id"],
                complete_project_payload("2026-08-09T00:00:00Z", 500_000),
                FIRST_COMMISSIONER,
            ),
            "ERR_PROJECT_NOT_AWARDED",
            409,
        )
