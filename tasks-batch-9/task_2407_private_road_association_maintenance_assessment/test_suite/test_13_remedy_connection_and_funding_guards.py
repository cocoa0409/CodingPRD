"""Closed remedies, the easement dispute loop, membership enrolment, and the
two axes on which a funded project must match its proposal."""
import pytest

from test_helpers import (
    api_client,
    cast_ballot,
    create_maintenance_project_payload,
    create_member_payload,
    decide_connection_payload,
    file_connection_request,
    make_clerk_headers,
    make_commissioner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    open_balloting,
    read_association,
    read_charge,
    read_connection_request,
    read_member,
    read_parcel,
    read_proposal,
    release_payload,
    resolve_dispute_payload,
    set_clock,
    setup_annual_assessment,
    setup_association,
    setup_delinquent_charge,
    setup_member,
    setup_parcel,
    setup_proposal,
    setup_road_segment,
    subdivide,
    validate_error,
    validate_paginated,
    validate_success,
)

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
SECOND_TREASURER = make_treasurer_headers("bt-2")
THIRD_TREASURER = make_treasurer_headers("bt-3")
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

SINGLE_290 = [
    {
        "deed_book_page": "DB162-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
        "covenant_recorded": True,
    }
]

CONNECTION_PARCEL = [
    {
        "deed_book_page": "DB163-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
        "covenant_recorded": True,
    }
]

TWO_VOTERS = [
    {
        "deed_book_page": "DB165-P01",
        "frontage_feet": 240,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
        "covenant_recorded": True,
    },
    {
        "deed_book_page": "DB165-P02",
        "frontage_feet": 200,
        "usage_class": "SEASONAL",
        "trips_per_day": 2,
        "covenant_recorded": True,
    },
]


class TestTheEffectuationGuardCoversBothClosedStates:
    """A remedy that is EFFECTIVE and then RELEASED refuses effectuation for the
    same reason, and never for want of a second treasurer."""

    def _effective_notice(self):
        """A 1,600,000-cent charge thirty grace days past due, carrying a NOTICE
        initiated by bt-1 and effectuated by bt-2."""
        scenario = setup_delinquent_charge(
            parcel_specs=SINGLE_290,
            budget_requirement_cents=4_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            remedy_clock="2026-10-15T00:00:00Z",
            action_type="NOTICE",
        )
        scenario["action"] = validate_success(
            api_client.effectuate_delinquency_action(scenario["action"]["id"], SECOND_TREASURER)
        )
        return scenario

    def test_effectuating_an_effective_remedy_reports_the_state_guard(self, api):
        """PRD §2.10: "The remedy's `status` is `INITIATED` for effectuation —
        otherwise `ERR_ACTION_NOT_INITIATED` (409)."

        Design: Corner/errors/effectuation_guard_code_is_reachable_from_effective_and_released
        """
        scenario = self._effective_notice()
        action = scenario["action"]
        assert action["status"] == "EFFECTIVE"
        assert action["effectuated_by_user_id"] == "bt-2"
        assert action["lien_amount_cents"] == 0
        assert read_member(action["member_id"])["access_status"] == "WARNED"

        validate_error(
            api_client.effectuate_delinquency_action(action["id"], THIRD_TREASURER),
            "ERR_ACTION_NOT_INITIATED",
            409,
        )

        after = validate_success(
            api_client.get_delinquency_action(action["id"], TREASURER)
        )
        assert after["status"] == "EFFECTIVE"
        assert after["effectuated_by_user_id"] == "bt-2"

    def test_the_third_treasurer_proves_segregation_is_not_what_fired(self, api):
        """PRD §2.10: "Segregation of duties on `X-User-ID` — otherwise
        `ERR_SEGREGATION_OF_DUTIES` (403). This applies to project award and remedy
        effectuation."

        Design: Corner/errors/effectuation_guard_code_is_reachable_from_effective_and_released
        """
        scenario = self._effective_notice()
        action = scenario["action"]

        body = validate_error(
            api_client.effectuate_delinquency_action(action["id"], THIRD_TREASURER),
            "ERR_ACTION_NOT_INITIATED",
            409,
        )
        assert body["error_id"] != "ERR_SEGREGATION_OF_DUTIES"

    def test_releasing_the_effective_notice_leaves_the_charge_delinquent(self, api):
        """PRD §3.6: "From `EFFECTIVE`, the remedy moves `EFFECTIVE → RELEASED`:
        `released_at` is stamped, `lien_amount_cents` resets to zero, and
        `payoff_amount_cents` is retained as the historical quote"

        Design: Corner/errors/effectuation_guard_code_is_reachable_from_effective_and_released
        """
        scenario = self._effective_notice()
        action = scenario["action"]

        released = validate_success(
            api_client.release_delinquency_action(
                action["id"],
                release_payload("board accepted a payment plan"),
                TREASURER,
            )
        )
        assert released["status"] == "RELEASED"
        assert released["released_at"].startswith("2026-10-15T00:00:00")
        assert released["lien_amount_cents"] == 0

        charge = read_charge(scenario["charge"]["id"])
        assert charge["status"] == "DELINQUENT"
        assert charge["balance_cents"] == 1_600_000

    def test_effectuating_a_released_remedy_reports_the_same_guard(self, api):
        """PRD §3.6: "Second, because a `LIEN_FILING` or `ACCESS_RESTRICTION` became
        effective, the charge moves `DELINQUENT → LIEN_ENCUMBERED`; a `NOTICE` leaves
        the charge `DELINQUENT`."

        Design: Corner/errors/effectuation_guard_code_is_reachable_from_effective_and_released
        """
        scenario = self._effective_notice()
        action = scenario["action"]
        validate_success(
            api_client.release_delinquency_action(
                action["id"],
                release_payload("board accepted a payment plan"),
                TREASURER,
            )
        )

        validate_error(
            api_client.effectuate_delinquency_action(action["id"], THIRD_TREASURER),
            "ERR_ACTION_NOT_INITIATED",
            409,
        )
        assert read_charge(scenario["charge"]["id"])["status"] == "DELINQUENT"


class TestTheDisputeLoopGuardsBothDirections:
    """Approval needs a recorded easement, and the pending guard fires from both
    sides of the dispute loop before the same approval finally succeeds."""

    def _disputable_request(self):
        """A levied roll against a 290-foot parcel, plus a 300-foot parcel split
        into 180 and 120 feet with a request filed on the larger lot and its
        easement unrecorded."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=CONNECTION_PARCEL,
            budget_requirement_cents=4_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "New Lot Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="New Lot Main", **MAIN_SEGMENT),
        )
        parent = setup_parcel(
            scenario["segment"]["id"],
            deed_book_page="DB163-P02",
            frontage_feet=300,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=5,
            covenant_recorded=True,
        )
        scenario["parent_member"] = setup_member(
            parent["id"],
            verified=True,
            owner_name="B. Okafor",
            deed_book_page="DB163-P02",
            deed_recorded_date="2020-06-02",
        )
        split = subdivide(
            parent["id"],
            [
                {"deed_book_page": "DB163-P02A", "frontage_feet": 180},
                {"deed_book_page": "DB163-P02B", "frontage_feet": 120},
            ],
        )
        scenario["parent_parcel"] = split["parent_parcel"]
        scenario["lot"] = split["children"][0]
        scenario["request"] = file_connection_request(
            scenario["lot"]["id"],
            requested_usage_class="RESIDENTIAL_YEAR_ROUND",
            requested_trips_per_day=4,
            easement_grant_recorded=False,
        )
        return scenario

    def test_approval_without_a_recorded_easement_is_rejected(self, api):
        """PRD §3.8: "it requires the request's `easement_grant_recorded` to be true
        (otherwise `ERR_EASEMENT_NOT_RECORDED`), requires the lot's road segment not to
        be graded `DEFICIENT`"

        Design: Corner/errors/connection_review_guard_codes_are_each_reachable
        """
        scenario = self._disputable_request()
        request = scenario["request"]
        assert request["status"] == "SUBMITTED"
        assert request["connection_fee_cents"] == 0

        validate_error(
            api_client.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            ),
            "ERR_EASEMENT_NOT_RECORDED",
            409,
        )

        after = read_connection_request(request["id"])
        assert after["status"] == "SUBMITTED"
        assert after["connection_fee_cents"] == 0

    def test_the_pending_guard_fires_from_both_sides_of_the_dispute_loop(self, api):
        """PRD §2.10: "The connection request's `status` is `SUBMITTED` for a decision,
        with a denial additionally accepted from `DISPUTED`, and `DISPUTED` for dispute
        resolution — otherwise `ERR_REQUEST_NOT_PENDING` (409)."

        Design: Corner/errors/connection_review_guard_codes_are_each_reachable
        """
        scenario = self._disputable_request()
        request = scenario["request"]

        disputed = validate_success(
            api_client.decide_connection_request(
                request["id"],
                decide_connection_payload(
                    "DISPUTED",
                    dispute_reason="adjoining owner contests the easement grant",
                ),
                SECRETARY,
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "adjoining owner contests the easement grant"
        assert read_parcel(scenario["lot"]["id"])["status"] == "PENDING_CONNECTION"

        validate_error(
            api_client.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            ),
            "ERR_REQUEST_NOT_PENDING",
            409,
        )

        resolved = validate_success(
            api_client.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "easement re-recorded at DB163-E11"),
                SECRETARY,
            )
        )
        assert resolved["status"] == "SUBMITTED"
        assert resolved["easement_grant_recorded"] is True
        assert resolved["resolution_note"] == "easement re-recorded at DB163-E11"
        assert resolved["dispute_reason"] is None

        validate_error(
            api_client.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "duplicate resolution"),
                SECRETARY,
            ),
            "ERR_REQUEST_NOT_PENDING",
            409,
        )

    def test_the_cured_request_approves_for_eight_hundred_forty_one_thousand_cents(self, api):
        """PRD §3.8: "The base component is a flat two hundred and fifty thousand cents.
        The frontage component is the lot's `frontage_feet` multiplied by one thousand
        eight hundred and seventy-five cents per foot. The trip component is the
        request's `requested_trips_per_day` multiplied by forty-one thousand seven
        hundred and thirty-three cents."

        Design: Corner/errors/connection_review_guard_codes_are_each_reachable
        """
        scenario = self._disputable_request()
        request = scenario["request"]
        validate_success(
            api_client.decide_connection_request(
                request["id"],
                decide_connection_payload(
                    "DISPUTED",
                    dispute_reason="adjoining owner contests the easement grant",
                ),
                SECRETARY,
            )
        )
        validate_success(
            api_client.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "easement re-recorded at DB163-E11"),
                SECRETARY,
            )
        )

        approved = validate_success(
            api_client.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["reserve_buyin_cents"] == 86_897
        assert approved["connection_fee_cents"] == 841_329
        assert approved["connection_fee_cents"] == 250_000 + 337_500 + 166_932 + 86_897

    def test_the_approval_activates_the_lot_and_bills_the_parent_member(self, api):
        """PRD §3.8: "Third, because a fee was assessed, a charge is created with
        `charge_type` `CONNECTION_FEE`, `roll_id` set to the association's latest levied
        roll under the same ranking used for special assessments, `parcel_id` set to the
        new lot, `member_id` set to the parent parcel's member — the new owner has no
        membership yet, so the parent is billed — `status` `OPEN`, and a `due_date` of
        the current clock date plus forty-five days."

        Design: Corner/errors/connection_review_guard_codes_are_each_reachable
        """
        scenario = self._disputable_request()
        request = scenario["request"]
        validate_success(
            api_client.decide_connection_request(
                request["id"],
                decide_connection_payload(
                    "DISPUTED",
                    dispute_reason="adjoining owner contests the easement grant",
                ),
                SECRETARY,
            )
        )
        validate_success(
            api_client.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "easement re-recorded at DB163-E11"),
                SECRETARY,
            )
        )
        validate_success(
            api_client.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            )
        )

        lot = read_parcel(scenario["lot"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["covenant_recorded"] is True
        assert lot["usage_class"] == "RESIDENTIAL_YEAR_ROUND"
        assert lot["trips_per_day"] == 4
        assert lot["frontage_share_units"] == pytest.approx(180.0, abs=0.0001)
        assert lot["trip_share_units"] == pytest.approx(136.0, abs=0.0001)

        charges, meta = validate_paginated(
            api_client.list_assessment_charges(
                CLERK, params={"parcel_id": lot["id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 1
        fee = charges[0]
        assert fee["charge_type"] == "CONNECTION_FEE"
        assert fee["amount_cents"] == 841_329
        assert fee["roll_id"] == scenario["roll"]["id"]
        assert fee["member_id"] == scenario["parent_member"]["id"]
        assert fee["status"] == "OPEN"
        assert fee["due_date"] == "2026-09-15"

    def test_the_reserve_buyin_lifts_the_balance_and_the_ratio(self, api):
        """PRD §3.8: "Fourth, because `reserve_buyin_cents` was credited, the
        association's `reserve_balance_cents` rises by that amount,
        `reserve_funding_ratio` and `reserve_posture` are recomputed, and every `DRAFT`
        proposal's `required_threshold_bps` follows."

        Design: Corner/errors/connection_review_guard_codes_are_each_reachable
        """
        scenario = self._disputable_request()
        request = scenario["request"]
        assert scenario["association"]["reserve_balance_cents"] == 600_000

        validate_success(
            api_client.decide_connection_request(
                request["id"],
                decide_connection_payload(
                    "DISPUTED",
                    dispute_reason="adjoining owner contests the easement grant",
                ),
                SECRETARY,
            )
        )
        validate_success(
            api_client.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "easement re-recorded at DB163-E11"),
                SECRETARY,
            )
        )
        validate_success(
            api_client.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            )
        )

        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 686_897
        assert association["reserve_funding_ratio"] == pytest.approx(0.6869, abs=0.0001)
        assert association["reserve_posture"] == "ADEQUATE"


class TestMembershipEnrolmentGuardCodes:
    """Which parcel is named decides which of the two enrolment guards fires."""

    def _two_parcels(self):
        """One covenanted parcel and one uncovenanted parcel on the same segment."""
        association = setup_association(
            name="Enrollment Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Enrollment Main", **MAIN_SEGMENT)
        covenanted = setup_parcel(
            segment["id"],
            deed_book_page="DB164-P01",
            frontage_feet=240,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=4,
            covenant_recorded=True,
        )
        uncovenanted = setup_parcel(
            segment["id"],
            deed_book_page="DB164-P02",
            frontage_feet=150,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=1,
            covenant_recorded=False,
        )
        return {
            "association": association,
            "segment": segment,
            "covenanted": covenanted,
            "uncovenanted": uncovenanted,
        }

    def test_a_second_member_on_the_same_parcel_is_a_duplicate(self, api):
        """PRD §2.10: "A parcel carries at most one member row — otherwise
        `ERR_DUPLICATE_MEMBER_FOR_PARCEL` (409)."

        Design: Corner/errors/membership_enrollment_guard_codes_are_each_reachable
        """
        scenario = self._two_parcels()
        first = validate_success(
            api_client.create_member(
                create_member_payload(
                    scenario["covenanted"]["id"],
                    owner_name="A. Whitcomb",
                    deed_book_page="DB164-P01",
                    deed_recorded_date="2019-04-11",
                ),
                SECRETARY,
            ),
            201,
        )
        assert first["standing_status"] == "PENDING_DEED_VERIFICATION"
        assert first["deed_verified_at"] is None

        validate_error(
            api_client.create_member(
                create_member_payload(
                    scenario["covenanted"]["id"],
                    owner_name="A. Whitcomb Jr.",
                    deed_book_page="DB164-P01",
                    deed_recorded_date="2024-02-02",
                ),
                SECRETARY,
            ),
            "ERR_DUPLICATE_MEMBER_FOR_PARCEL",
            409,
        )

    def test_a_first_member_on_an_uncovenanted_parcel_is_refused(self, api):
        """PRD §2.10: "The parcel's `covenant_recorded` is true when a membership is
        enrolled against it or a ballot is voted with it — otherwise
        `ERR_COVENANT_NOT_RECORDED` (409)."

        Design: Corner/errors/membership_enrollment_guard_codes_are_each_reachable
        """
        scenario = self._two_parcels()

        validate_error(
            api_client.create_member(
                create_member_payload(
                    scenario["uncovenanted"]["id"],
                    owner_name="C. Iversen",
                    deed_book_page="DB164-P02",
                    deed_recorded_date="2021-03-19",
                ),
                SECRETARY,
            ),
            "ERR_COVENANT_NOT_RECORDED",
            409,
        )

    def test_only_the_covenanted_parcel_carries_a_member_row(self, api):
        """PRD §3.3: "The two standing dimensions described in §2.8 are both exposed on
        the member record and both usable as list filters, alongside a `parcel_id`
        filter."

        Design: Corner/errors/membership_enrollment_guard_codes_are_each_reachable
        """
        scenario = self._two_parcels()
        setup_member(
            scenario["covenanted"]["id"],
            verified=False,
            owner_name="A. Whitcomb",
            deed_book_page="DB164-P01",
            deed_recorded_date="2019-04-11",
        )
        validate_error(
            api_client.create_member(
                create_member_payload(
                    scenario["uncovenanted"]["id"],
                    owner_name="C. Iversen",
                    deed_book_page="DB164-P02",
                    deed_recorded_date="2021-03-19",
                ),
                SECRETARY,
            ),
            "ERR_COVENANT_NOT_RECORDED",
            409,
        )

        _, covenanted_meta = validate_paginated(
            api_client.list_members(SECRETARY, params={"parcel_id": scenario["covenanted"]["id"]})
        )
        assert covenanted_meta["total_count"] == 1

        _, uncovenanted_meta = validate_paginated(
            api_client.list_members(
                SECRETARY, params={"parcel_id": scenario["uncovenanted"]["id"]}
            )
        )
        assert uncovenanted_meta["total_count"] == 0


class TestAFundedProjectMustMatchItsProposalOnBothAxes:
    """A DRAFT proposal, the wrong segment, and the wrong category each block the
    project, and only the matching triple opens."""

    def _adopted_and_draft(self):
        """A levied FY2026 roll, an ADOPTED 1,500,000-cent GRADING proposal on the
        main segment, a DRAFT 900,000-cent one beside it, and a spur segment that
        no proposal covers."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=TWO_VOTERS,
            budget_requirement_cents=4_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "Funded Work Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Funded Work Main", **MAIN_SEGMENT),
        )
        scenario["spur"] = setup_road_segment(
            scenario["association"]["id"],
            name="Funded Work Spur",
            length_feet=900,
            width_feet=21,
            max_grade_pct=9,
            surface_type="GRAVEL",
            turnout_count=1,
            turnaround_present=True,
            bridge_present=False,
            culvert_count=1,
        )

        proposal = setup_proposal(
            scenario,
            project_type="GRADING",
            estimated_cost_cents=1_500_000,
            cost_allocation_method="EQUAL_SHARE",
            title="Adopted regrade",
        )
        proposal = open_balloting(proposal["id"], "2026-08-15T00:00:00Z")
        cast_ballot(proposal, scenario["members"][0], "YES", proposal["version"])
        cast_ballot(
            proposal,
            scenario["members"][1],
            "YES",
            read_proposal(proposal["id"])["version"],
        )
        set_clock("2026-08-15T00:00:00Z")
        scenario["adopted"] = validate_success(
            api_client.tally_proposal(proposal["id"], TREASURER)
        )
        scenario["draft"] = setup_proposal(
            scenario,
            project_type="GRADING",
            estimated_cost_cents=900_000,
            cost_allocation_method="EQUAL_SHARE",
            title="Unadopted regrade",
        )
        return scenario

    def test_the_unanimous_tally_adopts_at_the_grading_base_threshold(self, api):
        """PRD §3.5: "The base threshold follows the work type: five thousand basis
        points for `GRADING`, six thousand for `CULVERT`, six thousand six hundred and
        sixty-seven for `PAVING`, and seven thousand five hundred for `BRIDGE`. Five
        hundred basis points are added when the proposal's `estimated_cost_cents` is
        strictly greater than two million cents."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()
        adopted = scenario["adopted"]
        assert adopted["status"] == "ADOPTED"
        assert adopted["required_threshold_bps"] == 5000
        assert adopted["eligible_weight_total"] == 2
        assert adopted["counted_weight_total"] == 2
        assert adopted["yes_weight_total"] == 2
        assert adopted["quorum_met"] is True
        assert adopted["approved_amount_cents"] == 1_500_000

    def test_the_adoption_spreads_the_capped_special_charges(self, api):
        """PRD §3.4: "Fourth, each raw share is clamped between a floor of fifty
        thousand cents and a per-parcel cap, where the cap is forty percent of
        `budget_requirement_cents` with any fraction discarded downward."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()

        charges, meta = validate_paginated(
            api_client.list_assessment_charges(
                CLERK,
                params={"proposal_id": scenario["adopted"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 2
        assert [c["charge_type"] for c in charges] == ["SPECIAL", "SPECIAL"]
        assert [c["amount_cents"] for c in charges] == [600_000, 600_000]
        assert sum(c["amount_cents"] for c in charges) == 1_200_000

    def test_a_draft_proposal_cannot_fund_a_project(self, api):
        """PRD §2.10: "A `proposal_id` cited when a project is opened refers to a
        proposal whose `status` is `ADOPTED` — otherwise `ERR_PROPOSAL_NOT_ADOPTED`
        (409)."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()
        assert read_proposal(scenario["draft"]["id"])["status"] == "DRAFT"

        validate_error(
            api_client.create_maintenance_project(
                create_maintenance_project_payload(
                    scenario["segment"]["id"],
                    category="GRADING",
                    window_start_date="2026-08-20",
                    window_end_date="2026-08-23",
                    proposal_id=scenario["draft"]["id"],
                ),
                FIRST_COMMISSIONER,
            ),
            "ERR_PROPOSAL_NOT_ADOPTED",
            409,
        )

    def test_the_mismatch_guard_fires_on_the_segment_axis(self, api):
        """PRD §2.10: "When a `proposal_id` is supplied at project creation, that
        proposal's `road_segment_id` equals the project's `road_segment_id` and its
        `project_type` equals the project's `category` — otherwise
        `ERR_PROPOSAL_SEGMENT_MISMATCH` (409)."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()

        validate_error(
            api_client.create_maintenance_project(
                create_maintenance_project_payload(
                    scenario["spur"]["id"],
                    category="GRADING",
                    window_start_date="2026-08-20",
                    window_end_date="2026-08-23",
                    proposal_id=scenario["adopted"]["id"],
                ),
                FIRST_COMMISSIONER,
            ),
            "ERR_PROPOSAL_SEGMENT_MISMATCH",
            409,
        )

    def test_the_mismatch_guard_fires_on_the_category_axis(self, api):
        """PRD §3.7: "When a `proposal_id` is supplied, that proposal must be `ADOPTED`
        (otherwise `ERR_PROPOSAL_NOT_ADOPTED`) and must match the project on two axes —
        its `road_segment_id` must equal the project's `road_segment_id` and its
        `project_type` must equal the project's `category` — with any mismatch rejected
        as `ERR_PROPOSAL_SEGMENT_MISMATCH`."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()

        validate_error(
            api_client.create_maintenance_project(
                create_maintenance_project_payload(
                    scenario["segment"]["id"],
                    category="CULVERT",
                    window_start_date="2026-08-20",
                    window_end_date="2026-08-23",
                    proposal_id=scenario["adopted"]["id"],
                ),
                FIRST_COMMISSIONER,
            ),
            "ERR_PROPOSAL_SEGMENT_MISMATCH",
            409,
        )

    def test_the_matching_triple_opens_the_solicitation(self, api):
        """PRD §3.7: "The new project starts in `BID_SOLICITATION` with
        `created_by_user_id` set from `X-User-ID`, a null `awarded_bid_id`,
        `awarded_amount_cents` and `reserve_draw_cents` at zero, and null
        `awarded_by_user_id`, `completed_at`, `actual_cost_cents`, and
        `cancellation_reason`."

        Design: Corner/errors/project_funding_proposal_guard_codes_are_each_reachable
        """
        scenario = self._adopted_and_draft()

        project = validate_success(
            api_client.create_maintenance_project(
                create_maintenance_project_payload(
                    scenario["segment"]["id"],
                    category="GRADING",
                    window_start_date="2026-08-20",
                    window_end_date="2026-08-23",
                    proposal_id=scenario["adopted"]["id"],
                ),
                FIRST_COMMISSIONER,
            ),
            201,
        )
        assert project["status"] == "BID_SOLICITATION"
        assert project["proposal_id"] == scenario["adopted"]["id"]
        assert project["awarded_amount_cents"] == 0
        assert project["reserve_draw_cents"] == 0
        assert project["awarded_bid_id"] is None
