"""Declared transitions, refused transitions, initial states, terminal lockdown,
the reversible roll cycle, the dispute loop, and a cascade keyed on category."""
import pytest

from test_helpers import (
    ApiErrorId,
    award_project,
    create_connection_request_payload,
    create_contractor_bid_payload,
    create_delinquency_action_payload,
    create_maintenance_project_payload,
    create_proposal_payload,
    decide_connection_payload,
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_member_owner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    payment_payload,
    read_association,
    read_charge,
    read_member,
    read_parcel,
    read_project,
    read_roll,
    read_segment,
    recall_payload,
    record_access_inspection,
    resolve_dispute_payload,
    set_clock,
    setup_annual_assessment,
    setup_assessment_roll,
    setup_association,
    setup_member,
    setup_parcel,
    setup_project,
    setup_road_segment,
    submit_bid,
    subdivide,
    validate_error,
    validate_paginated,
    validate_success,
    verify_deed_payload,
)

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
COMMISSIONER = make_commissioner_headers("rc-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")

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
ONE_PARCEL = [
    {
        "deed_book_page": "DB130-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    }
]


class TestTheRollCycleIsReversibleButNotSkippable:
    """DRAFT to CERTIFIED to DRAFT to CERTIFIED to LEVIED, and nothing out of turn."""

    def test_certification_freezes_one_charge_per_assessable_parcel(self, api):
        """PRD §3.4: "The certification writes one charge per assessable parcel with
        `charge_type` `ANNUAL` and `status` `PENDING`, freezing that parcel's
        `share_units_snapshot` and computed `amount_cents` onto the charge, with
        `paid_cents` at zero, `balance_cents` equal to `amount_cents`, a null
        `due_date`, and a null `delinquent_since`."
        PRD §3.4: "The roll moves `DRAFT → CERTIFIED`, `certified_at` is stamped with
        the current logical-clock instant, and the roll's `version` increments by one."

        Design: Corner/state_machines/roll_certification_moves_draft_to_certified_and_freezes_one_charge_per_parcel
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=ONE_PARCEL,
            certify=False,
            levy=False,
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )

        certified = validate_success(api.certify_roll(scenario["roll"]["id"], CLERK))
        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(290, abs=0.0001)
        assert certified["total_levied_cents"] == 1_600_000
        assert certified["unallocated_residual_cents"] == 2_400_000
        assert certified["certified_at"].startswith("2026-08-01T00:00:00")
        assert certified["levied_at"] is None
        assert certified["due_date"] is None
        assert certified["reserve_contribution_cents"] == 0
        assert certified["version"] == 2

        charges, meta = validate_paginated(
            api.list_assessment_charges(CLERK, params={"roll_id": scenario["roll"]["id"]})
        )
        assert meta["total_count"] == 1
        charge = charges[0]
        assert charge["charge_type"] == "ANNUAL"
        assert charge["status"] == "PENDING"
        assert charge["share_units_snapshot"] == pytest.approx(290.0, abs=0.0001)
        assert charge["amount_cents"] == 1_600_000
        assert charge["paid_cents"] == 0
        assert charge["balance_cents"] == 1_600_000
        assert charge["due_date"] is None
        assert charge["parcel_id"] == scenario["parcels"][0]["id"]
        assert charge["member_id"] == scenario["members"][0]["id"]

        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 0
        assert association["reserve_posture"] == "UNDERFUNDED"

    def test_levy_and_recall_are_refused_outside_the_certified_state(self, api):
        """PRD §3.4: "Levy requires the roll to be `CERTIFIED`, failing which the
        request is rejected with `ERR_ROLL_NOT_CERTIFIED` — the same error a recall
        attempt receives on a `DRAFT` or `LEVIED` roll."
        PRD §3.4: "The roll's `reserve_contribution_cents` is set to fifteen percent
        of `budget_requirement_cents`, rounded half up to whole cents, and that amount
        is credited to the association's `reserve_balance_cents`"

        Design: Corner/state_machines/levy_and_recall_of_a_draft_roll_return_roll_not_certified
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[dict(ONE_PARCEL[0], deed_book_page="DB131-P01")],
            certify=False,
            levy=False,
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )
        roll_id = scenario["roll"]["id"]

        validate_error(
            api.levy_roll(roll_id, TREASURER), ApiErrorId.ERR_ROLL_NOT_CERTIFIED.value, 409
        )
        assert read_roll(roll_id)["status"] == "DRAFT"
        assert read_roll(roll_id)["recall_count"] == 0

        validate_error(
            api.recall_roll(roll_id, recall_payload("premature"), CLERK),
            ApiErrorId.ERR_ROLL_NOT_CERTIFIED.value,
            409,
        )
        assert read_roll(roll_id)["recall_count"] == 0

        validate_success(api.certify_roll(roll_id, CLERK))
        levied = validate_success(api.levy_roll(roll_id, TREASURER))
        assert levied["status"] == "LEVIED"
        assert levied["reserve_contribution_cents"] == 600_000
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 600_000

        validate_error(
            api.levy_roll(roll_id, TREASURER), ApiErrorId.ERR_ROLL_NOT_CERTIFIED.value, 409
        )
        association = read_association(scenario["association"]["id"])
        assert association["reserve_balance_cents"] == 600_000, "the terminal state held"
        assert association["reserve_funding_ratio"] == pytest.approx(0.6, abs=0.0001)
        assert association["reserve_posture"] == "ADEQUATE"

    def test_recall_voids_the_pending_charge_and_a_re_certification_mints_another(self, api):
        """PRD §3.4: "A recall, available to the `AssessmentClerk` on a `CERTIFIED`
        roll and taking a `recall_reason`, moves the roll `CERTIFIED → DRAFT`: every
        `ANNUAL` charge of that roll whose `status` is `PENDING` moves `PENDING →
        VOIDED` and thereby drops out of `total_levied_cents`; `total_levied_cents`,
        `total_share_units`, and `unallocated_residual_cents` all reset to zero;
        `certified_at` resets to null; and `recall_count` increases by one."
        PRD §3.4: "No reserve money moves on a recall, because the reserve
        contribution is credited only at levy."

        Design: Corner/state_machines/roll_recall_voids_pending_charges_and_zeroes_the_totals
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[dict(ONE_PARCEL[0], deed_book_page="DB136-P01")],
            certify=True,
            levy=False,
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )
        roll_id = scenario["roll"]["id"]

        recalled = validate_success(
            api.recall_roll(roll_id, recall_payload("budget revised by the board"), CLERK)
        )
        assert recalled["status"] == "DRAFT"
        assert recalled["total_levied_cents"] == 0
        assert recalled["total_share_units"] == pytest.approx(0, abs=0.0001)
        assert recalled["unallocated_residual_cents"] == 0
        assert recalled["certified_at"] is None
        assert recalled["recall_count"] == 1

        voided, voided_meta = validate_paginated(
            api.list_assessment_charges(CLERK, params={"roll_id": roll_id, "status": "VOIDED"})
        )
        assert voided_meta["total_count"] == 1, "the charge was voided, not deleted"
        assert voided[0]["id"] == scenario["charges"][0]["id"]
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 0

        recertified = validate_success(api.certify_roll(roll_id, CLERK))
        assert recertified["total_share_units"] == pytest.approx(290, abs=0.0001)
        assert recertified["total_levied_cents"] == 1_600_000
        assert recertified["unallocated_residual_cents"] == 2_400_000
        assert recertified["recall_count"] == 1

        all_charges, all_meta = validate_paginated(
            api.list_assessment_charges(CLERK, params={"roll_id": roll_id})
        )
        assert all_meta["total_count"] == 2
        statuses = sorted(row["status"] for row in all_charges)
        assert statuses == ["PENDING", "VOIDED"]

    def test_one_unverified_member_anywhere_blocks_certification(self, api):
        """PRD §3.4: "Certification also refuses to proceed unless every `ACTIVE`
        covenant-recorded parcel of the association has a member past deed
        verification, which is `ERR_MEMBERSHIP_ROLL_INCOMPLETE`."
        PRD §3.4: "Fourth, each raw share is clamped between a floor of fifty thousand
        cents and a per-parcel cap, where the cap is forty percent of
        `budget_requirement_cents` with any fraction discarded downward."

        Design: Corner/state_machines/certification_with_an_unverified_member_returns_membership_roll_incomplete
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Two Creeks Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Two Creeks Main", **MAIN_SEGMENT)
        first = setup_parcel(
            segment["id"], deed_book_page="DB135-P01", frontage_feet=290, trips_per_day=6
        )
        second = setup_parcel(
            segment["id"], deed_book_page="DB135-P02", frontage_feet=240, trips_per_day=4
        )
        setup_member(
            first["id"],
            verified=True,
            owner_name="A. Whitcomb",
            deed_book_page="DB135-P01",
            deed_recorded_date="2019-04-11",
        )
        unverified = setup_member(
            second["id"],
            verified=False,
            owner_name="B. Okafor",
            deed_book_page="DB135-P02",
            deed_recorded_date="2020-06-02",
        )
        roll = setup_assessment_roll(association["id"], fiscal_year=2026)

        validate_error(
            api.certify_roll(roll["id"], CLERK),
            ApiErrorId.ERR_MEMBERSHIP_ROLL_INCOMPLETE.value,
            409,
        )
        blocked = read_roll(roll["id"])
        assert blocked["status"] == "DRAFT"
        assert blocked["version"] == 1
        assert blocked["total_share_units"] == pytest.approx(0, abs=0.0001)
        assert blocked["certified_at"] is None
        _rows, meta = validate_paginated(
            api.list_assessment_charges(CLERK, params={"roll_id": roll["id"]})
        )
        assert meta["total_count"] == 0, "no partial charge set survives the rejection"

        validate_success(
            api.verify_deed(unverified["id"], verify_deed_payload("DB135-P02"), SECRETARY)
        )
        certified = validate_success(api.certify_roll(roll["id"], CLERK))
        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(530, abs=0.0001)
        assert certified["total_levied_cents"] == 3_200_000
        assert certified["unallocated_residual_cents"] == 800_000

        charges, _meta = validate_paginated(
            api.list_assessment_charges(CLERK, params={"roll_id": roll["id"]})
        )
        by_parcel = {row["parcel_id"]: row for row in charges}
        assert by_parcel[first["id"]]["amount_cents"] == 1_600_000
        assert by_parcel[second["id"]]["amount_cents"] == 1_600_000
        assert by_parcel[first["id"]]["share_units_snapshot"] == pytest.approx(290.0, abs=0.0001)
        assert by_parcel[second["id"]]["share_units_snapshot"] == pytest.approx(240.0, abs=0.0001)


class TestInitialStatesAndTerminalLockdown:
    """Where every entity starts, and what a terminal charge refuses."""

    def test_six_entities_start_in_their_declared_initial_states(self, api):
        """PRD §3.5: "The proposal starts in `DRAFT` with `balloting_opened_at` null,
        all weight totals at zero, `quorum_met` false, `failed_tally_count` zero, and
        `approved_amount_cents` zero."
        PRD §3.5: "A further five hundred are added when the association's
        `reserve_posture` is `UNDERFUNDED`, on the theory that a board with no reserve
        should need broader consent."
        PRD §3.4: "A new roll has `status` `DRAFT`, all its totals at zero, and no
        charges yet in existence."

        Design: Corner/state_machines/newly_created_entities_start_in_their_declared_initial_states
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Larkspur Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Larkspur Main", **MAIN_SEGMENT)

        parcel = setup_parcel(
            segment["id"], deed_book_page="DB132-P01", frontage_feet=290, trips_per_day=6
        )
        assert parcel["status"] == "ACTIVE"
        assert parcel["parent_parcel_id"] is None

        member = setup_member(
            parcel["id"],
            verified=False,
            owner_name="A. Whitcomb",
            deed_book_page="DB132-P01",
            deed_recorded_date="2019-04-11",
        )
        assert member["standing_status"] == "PENDING_DEED_VERIFICATION"
        assert member["access_status"] == "UNRESTRICTED"
        assert member["deed_verified_at"] is None

        roll = setup_assessment_roll(association["id"], fiscal_year=2026)
        assert roll["status"] == "DRAFT"
        assert roll["total_share_units"] == pytest.approx(0, abs=0.0001)
        assert roll["total_levied_cents"] == 0
        assert roll["unallocated_residual_cents"] == 0
        assert roll["reserve_contribution_cents"] == 0
        assert roll["recall_count"] == 0
        assert roll["certified_at"] is None
        assert roll["levied_at"] is None
        assert roll["due_date"] is None

        proposal = validate_success(
            api.create_proposal(
                create_proposal_payload(
                    segment["id"],
                    project_type="GRADING",
                    title="Regrade the main line",
                    estimated_cost_cents=1_500_000,
                    cost_allocation_method="EQUAL_SHARE",
                    voting_basis="PER_PARCEL",
                ),
                TREASURER,
            ),
            201,
        )
        assert proposal["status"] == "DRAFT"
        assert proposal["required_threshold_bps"] == 5500, "GRADING 5000 plus the 500 bump"
        assert proposal["eligible_weight_total"] == pytest.approx(0, abs=0.0001)
        assert proposal["counted_weight_total"] == pytest.approx(0, abs=0.0001)
        assert proposal["yes_weight_total"] == pytest.approx(0, abs=0.0001)
        assert proposal["quorum_met"] is False
        assert proposal["failed_tally_count"] == 0
        assert proposal["approved_amount_cents"] == 0
        assert proposal["balloting_opened_at"] is None

        project = validate_success(
            api.create_maintenance_project(
                create_maintenance_project_payload(
                    segment["id"],
                    category="GRADING",
                    window_start_date="2026-08-05",
                    window_end_date="2026-08-08",
                ),
                COMMISSIONER,
            ),
            201,
        )
        assert project["status"] == "BID_SOLICITATION"
        assert project["awarded_bid_id"] is None
        assert project["awarded_amount_cents"] == 0
        assert project["reserve_draw_cents"] == 0
        assert project["awarded_by_user_id"] is None
        assert project["created_by_user_id"] == "rc-1"

        bid = validate_success(
            api.create_contractor_bid(
                project["id"],
                create_contractor_bid_payload(
                    project["version"],
                    contractor_name="Basin Grading LLC",
                    amount_cents=400_000,
                ),
                make_contractor_headers("c-1"),
            ),
            201,
        )
        assert bid["status"] == "SUBMITTED"
        assert bid["contractor_user_id"] == "c-1"
        assert bid["submitted_at"].startswith("2026-08-01T00:00:00")

        fresh_segment = read_segment(segment["id"])
        assert fresh_segment["emergency_access_grade"] == "UNKNOWN"
        assert fresh_segment["required_turnouts"] == 1
        assert fresh_segment["last_inspection_at"] is None

    def test_a_paid_charge_refuses_both_payment_and_a_new_remedy(self, api):
        """PRD §2.10: "The charge's `status` is `OPEN`, `DELINQUENT`, or
        `LIEN_ENCUMBERED` and its `balance_cents` is greater than zero — otherwise
        `ERR_CHARGE_NOT_COLLECTIBLE` (409). This applies to payment, remedy
        initiation, and remedy effectuation."
        PRD §3.6: "the charge moves to `PAID` only when `balance_cents` has reached
        exactly zero — a partial payment leaves the charge where it was."

        Design: Corner/state_machines/payments_and_remedies_against_a_paid_charge_return_charge_not_collectible
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[dict(ONE_PARCEL[0], deed_book_page="DB133-P01")],
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "Ridge Hollow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Ridge Hollow Main"),
        )
        charge = scenario["charges"][0]
        member = scenario["members"][0]
        owner = make_member_owner_headers(member["id"])

        paid = validate_success(
            api.create_payment(charge["id"], payment_payload(1_600_000), owner), 200
        )
        assert paid["status"] == "PAID"

        set_clock("2026-10-20T00:00:00Z")

        validate_error(
            api.create_payment(charge["id"], payment_payload(1), owner),
            ApiErrorId.ERR_CHARGE_NOT_COLLECTIBLE.value,
            409,
        )
        validate_error(
            api.create_delinquency_action(
                charge["id"], create_delinquency_action_payload("NOTICE"), TREASURER
            ),
            ApiErrorId.ERR_CHARGE_NOT_COLLECTIBLE.value,
            409,
        )

        final = read_charge(charge["id"])
        assert final["status"] == "PAID"
        assert final["paid_cents"] == 1_600_000
        assert final["balance_cents"] == 0
        _actions, meta = validate_paginated(
            api.list_charge_delinquency_actions(charge["id"], TREASURER)
        )
        assert meta["total_count"] == 0
        owner_record = read_member(member["id"])
        assert owner_record["standing_status"] == "GOOD_STANDING"
        assert owner_record["access_status"] == "UNRESTRICTED"

    def test_a_second_deed_verification_does_not_restamp_the_instant(self, api):
        """PRD §3.3: "On success the member advances `PENDING_DEED_VERIFICATION →
        GOOD_STANDING`, `deed_verified_at` is stamped with the current logical-clock
        instant, and the member's parcel becomes eligible to appear on an assessment
        roll."
        PRD §3.3: "A second attempt on an already-verified member fails with
        `ERR_MEMBER_ALREADY_VERIFIED`."

        Design: Corner/state_machines/verify_deed_twice_returns_member_already_verified
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Willow Bend Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Willow Bend Main", **MAIN_SEGMENT)
        parcel = setup_parcel(
            segment["id"], deed_book_page="DB134-P01", frontage_feet=290, trips_per_day=6
        )
        member = setup_member(
            parcel["id"],
            verified=False,
            owner_name="A. Whitcomb",
            deed_book_page="DB134-P01",
            deed_recorded_date="2019-04-11",
        )

        verified = validate_success(
            api.verify_deed(member["id"], verify_deed_payload("DB134-P01"), SECRETARY)
        )
        assert verified["standing_status"] == "GOOD_STANDING"
        assert verified["deed_verified_at"].startswith("2026-08-01T00:00:00")

        set_clock("2026-08-02T00:00:00Z")
        validate_error(
            api.verify_deed(member["id"], verify_deed_payload("DB134-P01"), SECRETARY),
            ApiErrorId.ERR_MEMBER_ALREADY_VERIFIED.value,
            409,
        )

        after = read_member(member["id"])
        assert after["deed_verified_at"] == verified["deed_verified_at"]
        assert after["deed_verified_at"].startswith("2026-08-01T00:00:00")
        assert after["standing_status"] == "GOOD_STANDING"
        assert after["access_status"] == "UNRESTRICTED"


class TestLoopsAndConditionalCascades:
    """A request that revisits SUBMITTED, and a completion keyed on category."""

    def test_a_connection_request_may_travel_through_a_dispute_and_back(self, api):
        """PRD §3.8: "Resolving the dispute is a separate act that moves the request
        `DISPUTED → SUBMITTED`, requires the request to actually be `DISPUTED`, and
        takes a fresh `easement_grant_recorded` value and a `resolution_note`."
        PRD §3.8: "The base component is a flat two hundred and fifty thousand cents.
        The frontage component is the lot's `frontage_feet` multiplied by one thousand
        eight hundred and seventy-five cents per foot. The trip component is the
        request's `requested_trips_per_day` multiplied by forty-one thousand seven
        hundred and thirty-three cents."
        PRD §3.8: "Deferring into a dispute moves the request `SUBMITTED → DISPUTED`
        and requires a `dispute_reason` to be present; a deferral without one is
        rejected as a malformed request. The reason is recorded, the lot stays
        `PENDING_CONNECTION`, and no fee is computed."

        Design: Corner/state_machines/connection_request_cycles_through_dispute_before_approval
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Elk Meadow Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Elk Meadow Main", **MAIN_SEGMENT)
        assessed = setup_parcel(
            segment["id"], deed_book_page="DB137-P01", frontage_feet=290, trips_per_day=6
        )
        setup_member(
            assessed["id"],
            verified=True,
            owner_name="A. Whitcomb",
            deed_book_page="DB137-P01",
            deed_recorded_date="2019-04-11",
        )
        parent = setup_parcel(
            segment["id"], deed_book_page="DB137-P02", frontage_feet=300, trips_per_day=4
        )
        parent_member = setup_member(
            parent["id"],
            verified=True,
            owner_name="B. Okafor",
            deed_book_page="DB137-P02",
            deed_recorded_date="2020-06-02",
        )
        split = subdivide(
            parent["id"],
            [
                {"deed_book_page": "DB137-P02A", "frontage_feet": 180},
                {"deed_book_page": "DB137-P02B", "frontage_feet": 120},
            ],
        )
        lot = split["children"][0]
        roll = setup_assessment_roll(association["id"], fiscal_year=2026)
        validate_success(api.certify_roll(roll["id"], CLERK))
        validate_success(api.levy_roll(roll["id"], TREASURER))

        owner = make_member_owner_headers(parent_member["id"])
        request = validate_success(
            api.create_connection_request(
                create_connection_request_payload(
                    lot["id"],
                    requested_usage_class="COMMERCIAL",
                    requested_trips_per_day=3,
                    easement_grant_recorded=False,
                ),
                owner,
            ),
            201,
        )

        disputed = validate_success(
            api.decide_connection_request(
                request["id"],
                decide_connection_payload(
                    "DISPUTED", dispute_reason="neighbour contests the easement centreline"
                ),
                SECRETARY,
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["dispute_reason"] == "neighbour contests the easement centreline"
        assert disputed["connection_fee_cents"] == 0
        assert disputed["reserve_buyin_cents"] == 0
        assert disputed["decided_at"] is None
        still_pending = read_parcel(lot["id"])
        assert still_pending["status"] == "PENDING_CONNECTION"
        assert still_pending["covenant_recorded"] is False

        resolved = validate_success(
            api.resolve_connection_dispute(
                request["id"],
                resolve_dispute_payload(True, "corrected easement recorded at DB137-P02A"),
                SECRETARY,
            )
        )
        assert resolved["status"] == "SUBMITTED"
        assert resolved["easement_grant_recorded"] is True
        assert resolved["dispute_reason"] is None
        assert resolved["resolution_note"] == "corrected easement recorded at DB137-P02A"

        approved = validate_success(
            api.decide_connection_request(
                request["id"], decide_connection_payload("APPROVED"), SECRETARY
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["connection_fee_cents"] == 864_768
        assert approved["reserve_buyin_cents"] == 152_069

        connected = read_parcel(lot["id"])
        assert connected["status"] == "ACTIVE"
        assert connected["covenant_recorded"] is True
        assert connected["usage_class"] == "COMMERCIAL"
        assert connected["trips_per_day"] == 3
        assert connected["frontage_share_units"] == pytest.approx(315.0, abs=0.0001)
        assert connected["trip_share_units"] == pytest.approx(111.0, abs=0.0001)

        fees, meta = validate_paginated(
            api.list_assessment_charges(
                CLERK, params={"parcel_id": lot["id"], "charge_type": "CONNECTION_FEE"}
            )
        )
        assert meta["total_count"] == 1
        fee = fees[0]
        assert fee["amount_cents"] == 864_768
        assert fee["status"] == "OPEN"
        assert fee["due_date"] == "2026-09-15"
        assert fee["share_units_snapshot"] == pytest.approx(315.0, abs=0.0001)
        assert fee["roll_id"] == roll["id"]
        assert fee["member_id"] == parent_member["id"], "the parent parcel's member is billed"

        after = read_association(association["id"])
        assert after["reserve_balance_cents"] == 752_069
        assert after["reserve_funding_ratio"] == pytest.approx(0.7521, abs=0.0001)
        assert after["reserve_posture"] == "ADEQUATE"

    def test_only_a_paving_completion_repaves_and_regrades_the_segment(self, api):
        """PRD §3.7: "One category carries an extra consequence: on a `PAVING` project
        only, the segment's `surface_type` becomes `PAVED` and its
        `emergency_access_grade` resets to `UNKNOWN`, because a rebuilt travelway must
        be re-inspected before the association may again assert compliance."
        PRD §3.7: "for the operating categories `GRADING`, `SNOW`, and `DUST` the draw
        is zero, because operating work is funded from the annual levy"

        Design: Corner/state_machines/paving_completion_repaves_the_segment_while_grading_completion_leaves_it_untouched
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[dict(ONE_PARCEL[0], deed_book_page="DB138-P01")],
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "Bear Wallow Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(MAIN_SEGMENT, name="Bear Wallow Main"),
        )
        segment_id = scenario["segment"]["id"]
        record_access_inspection(
            segment_id,
            "2026-08-02T00:00:00Z",
            measured_width_feet=22,
            measured_max_grade_pct=8,
            measured_turnout_count=1,
            turnaround_present=True,
        )
        grading = setup_project(
            segment_id,
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
            headers=COMMISSIONER,
        )
        grading_bid = submit_bid(
            grading, 400_000, contractor_user_id="c-1", contractor_name="Basin Grading LLC"
        )
        awarded_grading = award_project(
            grading["id"], grading_bid["id"], headers=SECOND_COMMISSIONER
        )
        assert awarded_grading["reserve_draw_cents"] == 0
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 600_000

        paving = setup_project(
            segment_id,
            category="PAVING",
            window_start_date="2026-08-12",
            window_end_date="2026-08-16",
            headers=COMMISSIONER,
        )
        paving_bid = submit_bid(
            paving, 500_000, contractor_user_id="c-2", contractor_name="Summit Paving Co"
        )

        set_clock("2026-08-08T00:00:00Z")
        completed_grading = validate_success(
            api.complete_project(
                grading["id"],
                {"completed_at": "2026-08-08T00:00:00Z", "actual_cost_cents": 400_000},
                COMMISSIONER,
            )
        )
        assert completed_grading["status"] == "COMPLETE"
        assert completed_grading["actual_cost_cents"] == 400_000
        assert completed_grading["reserve_draw_cents"] == 0
        untouched = read_segment(segment_id)
        assert untouched["surface_type"] == "GRAVEL"
        assert untouched["emergency_access_grade"] == "COMPLIANT"

        awarded_paving = award_project(
            paving["id"], paving_bid["id"], headers=SECOND_COMMISSIONER
        )
        assert awarded_paving["reserve_draw_cents"] == 500_000
        mid = read_association(scenario["association"]["id"])
        assert mid["reserve_balance_cents"] == 100_000
        assert mid["reserve_funding_ratio"] == pytest.approx(0.1, abs=0.0001)
        assert mid["reserve_posture"] == "UNDERFUNDED"

        set_clock("2026-08-16T00:00:00Z")
        completed_paving = validate_success(
            api.complete_project(
                paving["id"],
                {"completed_at": "2026-08-16T00:00:00Z", "actual_cost_cents": 500_000},
                COMMISSIONER,
            )
        )
        assert completed_paving["status"] == "COMPLETE"
        assert completed_paving["reserve_draw_cents"] == 500_000
        repaved = read_segment(segment_id)
        assert repaved["surface_type"] == "PAVED"
        assert repaved["emergency_access_grade"] == "UNKNOWN"
        assert repaved["required_turnouts"] == 1
        assert repaved["last_inspection_at"].startswith("2026-08-02T00:00:00")
        assert read_project(grading["id"])["status"] == "COMPLETE"
        assert read_association(scenario["association"]["id"])["reserve_balance_cents"] == 100_000
