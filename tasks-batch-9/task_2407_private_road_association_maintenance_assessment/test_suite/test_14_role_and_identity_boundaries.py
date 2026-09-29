"""The offices divide the work: role-exclusive writes, per-row identity scope,
the two user-level segregation checks, and the one genuinely shared write."""
import pytest

from test_helpers import (
    api_client,
    create_maintenance_project_payload,
    create_parcel_payload,
    create_road_segment_payload,
    make_blank_user_headers,
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_member_owner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    payment_payload,
    read_action,
    read_charge,
    read_member,
    read_project,
    read_roll,
    set_clock,
    setup_annual_assessment,
    setup_assessment_roll,
    setup_association,
    setup_delinquent_charge,
    setup_membership_roll,
    setup_project,
    setup_road_segment,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import award_project as award
from test_helpers import award_payload
from test_helpers import withdraw_bid_payload

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
SECOND_TREASURER = make_treasurer_headers("bt-2")
FIRST_COMMISSIONER = make_commissioner_headers("rc-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")
FIRST_CONTRACTOR = make_contractor_headers("c-1")
SECOND_CONTRACTOR = make_contractor_headers("c-2")

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
        "deed_book_page": "DB170-P01",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
        "covenant_recorded": True,
    }
]

TWO_PEERS = [
    {
        "deed_book_page": "DB172-P01",
        "frontage_feet": 240,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
        "covenant_recorded": True,
    },
    {
        "deed_book_page": "DB172-P02",
        "frontage_feet": 200,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 4,
        "covenant_recorded": True,
    },
]


class TestTheAssessmentCycleIsSplitAcrossTwoOffices:
    """The clerk certifies and cannot levy; the treasurer levies and cannot
    certify."""

    def _draft_roll(self):
        """A single 290-foot parcel with a verified member and a DRAFT FY2026 roll
        of 4,000,000 cents."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_membership_roll(
            parcel_specs=SINGLE_290,
            association_overrides={
                "name": "Duty Split Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Duty Split Main", **MAIN_SEGMENT),
        )
        scenario["roll"] = setup_assessment_roll(
            scenario["association"]["id"],
            fiscal_year=2026,
            fy_start_date="2026-01-01",
            fy_end_date="2026-12-31",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )
        return scenario

    def test_a_treasurer_cannot_certify_a_draft_roll(self, api):
        """PRD §2.1: "The `BoardTreasurer` levies rolls, runs special-assessment
        balloting, and pursues delinquency remedies, but may never certify a roll."

        Design: Corner/rbac/clerk_cannot_levy_and_treasurer_cannot_certify
        """
        scenario = self._draft_roll()

        validate_error(
            api_client.certify_roll(scenario["roll"]["id"], TREASURER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        after = read_roll(scenario["roll"]["id"])
        assert after["status"] == "DRAFT"
        assert after["certified_at"] is None

    def test_a_clerk_cannot_levy_the_roll_it_certified(self, api):
        """PRD §2.1: "The `AssessmentClerk` opens, certifies, and recalls assessment
        rolls and may post payments, but may never levy."

        Design: Corner/rbac/clerk_cannot_levy_and_treasurer_cannot_certify
        """
        scenario = self._draft_roll()

        certified = validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))
        assert certified["status"] == "CERTIFIED"
        assert certified["total_share_units"] == pytest.approx(290.0, abs=0.0001)

        validate_error(
            api_client.levy_roll(scenario["roll"]["id"], CLERK),
            "ERR_FORBIDDEN_ROLE",
            403,
        )

        after = read_roll(scenario["roll"]["id"])
        assert after["status"] == "CERTIFIED"
        assert after["levied_at"] is None

    def test_the_role_check_precedes_every_state_guard(self, api):
        """The role check is item 3 of the order below while the roll-state guard is
        item 13, so the wrong office masks the wrong state.
        PRD §2.10: "More generally, every request walks the following checks in this exact
        order, and the first failure is the error returned. Where several checks could all
        fire, the earlier one masks the later ones."

        Design: Corner/rbac/clerk_cannot_levy_and_treasurer_cannot_certify
        """
        scenario = self._draft_roll()

        # A DRAFT roll cannot be levied at all, yet the wrong office is what the
        # response reports, because the role check sits earlier in §2.10.
        validate_error(
            api_client.levy_roll(scenario["roll"]["id"], CLERK),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        assert read_roll(scenario["roll"]["id"])["status"] == "DRAFT"

    def test_each_office_completes_its_own_half_of_the_cycle(self, api):
        """PRD §3.4: "The roll's `reserve_contribution_cents` is set to fifteen percent
        of `budget_requirement_cents`, rounded half up to whole cents, and that amount is
        credited to the association's `reserve_balance_cents`"

        Design: Corner/rbac/clerk_cannot_levy_and_treasurer_cannot_certify
        """
        scenario = self._draft_roll()
        validate_success(api_client.certify_roll(scenario["roll"]["id"], CLERK))

        levied = validate_success(api_client.levy_roll(scenario["roll"]["id"], TREASURER))
        assert levied["status"] == "LEVIED"
        assert levied["reserve_contribution_cents"] == 600_000
        assert levied["due_date"] == "2026-09-15"


class TestParcelAndRoadWritesCannotCrossRoleBoundaries:
    """Three writes, three owners, and no forbidden call leaves a row behind."""

    def _association(self):
        return setup_association(
            name="Role Fence Road Association", reserve_target_cents=1_000_000
        )

    def test_only_the_commissioner_records_a_road_segment(self, api):
        """PRD §2.1: "The `RoadCommissioner` owns the physical road — segments,
        emergency-access inspections, and maintenance projects."

        Design: Corner/rbac/parcel_and_road_writes_cannot_cross_role_boundaries
        """
        association = self._association()
        payload = create_road_segment_payload(
            association["id"], name="Role Fence Main", **MAIN_SEGMENT
        )

        validate_error(
            api_client.create_road_segment(payload, SECRETARY), "ERR_FORBIDDEN_ROLE", 403
        )

        segment = validate_success(
            api_client.create_road_segment(payload, FIRST_COMMISSIONER), 201
        )
        assert segment["name"] == "Role Fence Main"

    def test_only_the_secretary_enrolls_a_parcel(self, api):
        """PRD §2.1: "The `AssociationSecretary` keeps the membership roll, the parcel
        record, and the easement and connection file."

        Design: Corner/rbac/parcel_and_road_writes_cannot_cross_role_boundaries
        """
        association = self._association()
        segment = setup_road_segment(association["id"], name="Role Fence Main", **MAIN_SEGMENT)
        payload = create_parcel_payload(
            segment["id"],
            deed_book_page="DB171-P01",
            frontage_feet=240,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=4,
            covenant_recorded=True,
        )

        validate_error(
            api_client.create_parcel(payload, FIRST_COMMISSIONER), "ERR_FORBIDDEN_ROLE", 403
        )

        parcel = validate_success(api_client.create_parcel(payload, SECRETARY), 201)
        assert parcel["frontage_share_units"] == pytest.approx(240.0, abs=0.0001)

    def test_only_the_commissioner_opens_a_maintenance_project(self, api):
        """PRD §2.1: "When the role is recognised but is not among those authorised for
        the endpoint being called, the request is rejected with `ERR_FORBIDDEN_ROLE`
        (HTTP 403)."

        Design: Corner/rbac/parcel_and_road_writes_cannot_cross_role_boundaries
        """
        association = self._association()
        segment = setup_road_segment(association["id"], name="Role Fence Main", **MAIN_SEGMENT)
        payload = create_maintenance_project_payload(
            segment["id"],
            category="SNOW",
            window_start_date="2026-12-01",
            window_end_date="2026-12-05",
        )

        validate_error(
            api_client.create_maintenance_project(payload, TREASURER), "ERR_FORBIDDEN_ROLE", 403
        )

        project = validate_success(
            api_client.create_maintenance_project(payload, FIRST_COMMISSIONER), 201
        )
        assert project["status"] == "BID_SOLICITATION"
        assert project["created_by_user_id"] == "rc-1"

    def test_no_forbidden_write_persisted_a_row(self, api):
        """PRD §2.10: "3. The role is among the endpoint's authorised roles — otherwise
        `ERR_FORBIDDEN_ROLE` (403)."

        Design: Corner/rbac/parcel_and_road_writes_cannot_cross_role_boundaries
        """
        association = self._association()
        segment_payload = create_road_segment_payload(
            association["id"], name="Role Fence Main", **MAIN_SEGMENT
        )
        validate_error(
            api_client.create_road_segment(segment_payload, SECRETARY), "ERR_FORBIDDEN_ROLE", 403
        )
        segment = validate_success(
            api_client.create_road_segment(segment_payload, FIRST_COMMISSIONER), 201
        )

        project_payload = create_maintenance_project_payload(
            segment["id"],
            category="SNOW",
            window_start_date="2026-12-01",
            window_end_date="2026-12-05",
        )
        validate_error(
            api_client.create_maintenance_project(project_payload, TREASURER),
            "ERR_FORBIDDEN_ROLE",
            403,
        )
        validate_success(
            api_client.create_maintenance_project(project_payload, FIRST_COMMISSIONER), 201
        )

        _, segment_meta = validate_paginated(
            api_client.list_road_segments(
                SECRETARY, params={"association_id": association["id"]}
            )
        )
        assert segment_meta["total_count"] == 1

        _, project_meta = validate_paginated(
            api_client.list_maintenance_projects(
                FIRST_COMMISSIONER, params={"road_segment_id": segment["id"]}
            )
        )
        assert project_meta["total_count"] == 1


class TestMemberOwnerScopeIsPerRow:
    """One role, two identities: the charge's `member_id` decides who may pay."""

    def _two_capped_charges(self):
        """A 1,000,000-cent roll over 240 and 200 frontage feet, where both raw
        shares exceed the cap so each charge lands at 400,000 cents."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=TWO_PEERS,
            budget_requirement_cents=1_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "Peer Pay Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Peer Pay Main", **MAIN_SEGMENT),
        )
        by_member = {charge["member_id"]: charge for charge in scenario["charges"]}
        scenario["charge_a"] = by_member[scenario["members"][0]["id"]]
        scenario["charge_b"] = by_member[scenario["members"][1]["id"]]
        return scenario

    def test_the_cap_clamps_both_peer_charges_to_four_hundred_thousand(self, api):
        """PRD §3.4: "Eighth, the roll's `total_levied_cents` is the sum of those rounded
        per-parcel amounts, and its `unallocated_residual_cents` is
        `budget_requirement_cents` minus `total_levied_cents`."

        Design: Corner/rbac/member_owner_cannot_pay_another_members_charge
        """
        scenario = self._two_capped_charges()

        assert scenario["charge_a"]["amount_cents"] == 400_000
        assert scenario["charge_b"]["amount_cents"] == 400_000
        assert scenario["roll"]["total_levied_cents"] == 800_000
        assert scenario["roll"]["unallocated_residual_cents"] == 200_000

    def test_paying_a_peers_charge_is_refused_on_identity(self, api):
        """PRD §2.1: "an assessment charge is the acting member's when its `member_id`
        equals `X-User-ID`; and a connection request may be filed by a `MemberOwner` only
        when the `Member` on the subdividing parent parcel is `X-User-ID`."

        Design: Corner/rbac/member_owner_cannot_pay_another_members_charge
        """
        scenario = self._two_capped_charges()
        first_owner = make_member_owner_headers(scenario["members"][0]["id"])

        validate_error(
            api_client.create_payment(
                scenario["charge_b"]["id"], payment_payload(400_000), first_owner
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        peer_charge = read_charge(scenario["charge_b"]["id"])
        assert peer_charge["paid_cents"] == 0
        assert peer_charge["balance_cents"] == 400_000
        assert peer_charge["status"] == "OPEN"

    def test_the_identical_payload_clears_the_callers_own_charge(self, api):
        """PRD §3.6: "a `MemberOwner` may only pay a charge whose `member_id` equals
        `X-User-ID`; and the payment may not exceed the remaining `balance_cents`, an
        overpayment being rejected with `ERR_OVERPAYMENT`."

        Design: Corner/rbac/member_owner_cannot_pay_another_members_charge
        """
        scenario = self._two_capped_charges()
        first_owner = make_member_owner_headers(scenario["members"][0]["id"])

        paid = validate_success(
            api_client.create_payment(
                scenario["charge_a"]["id"], payment_payload(400_000), first_owner
            )
        )
        assert paid["paid_cents"] == 400_000
        assert paid["balance_cents"] == 0
        assert paid["status"] == "PAID"

        assert read_member(scenario["members"][0]["id"])["standing_status"] == "GOOD_STANDING"
        assert read_member(scenario["members"][1]["id"])["standing_status"] == "GOOD_STANDING"


class TestContractorScopeIsPerBid:
    """Two firms share the `Contractor` role but not each other's bids."""

    def _two_bids(self):
        """One GRADING solicitation carrying a 500,000-cent bid from c-1 and a
        600,000-cent bid from c-2."""
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Two Firm Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Two Firm Main", **MAIN_SEGMENT)
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )
        first = submit_bid(
            project,
            500_000,
            contractor_user_id="c-1",
            contractor_name="Basin Grading LLC",
            bond_on_file=True,
        )
        second = submit_bid(
            project,
            600_000,
            contractor_user_id="c-2",
            contractor_name="Highline Roadworks",
            bond_on_file=True,
        )
        return {"project": project, "first_bid": first, "second_bid": second}

    def test_withdrawing_a_peers_bid_is_refused(self, api):
        """PRD §2.1: "A `Contractor` may withdraw only a bid whose `contractor_user_id`
        equals `X-User-ID`. Any of these mismatches yields `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."

        Design: Corner/rbac/contractor_cannot_withdraw_another_firms_bid
        """
        scenario = self._two_bids()

        validate_error(
            api_client.withdraw_bid(
                scenario["second_bid"]["id"],
                withdraw_bid_payload("competitor tries to pull the rival bid"),
                FIRST_CONTRACTOR,
            ),
            "ERR_NOT_RESOURCE_OWNER",
            403,
        )

        untouched = validate_success(
            api_client.get_contractor_bid(scenario["second_bid"]["id"], FIRST_COMMISSIONER)
        )
        assert untouched["status"] == "SUBMITTED"
        assert untouched["contractor_user_id"] == "c-2"

    def test_the_owning_firm_withdraws_the_very_same_bid(self, api):
        """PRD §3.7: "A `Contractor` may withdraw its own bid, supplying a
        `withdrawal_reason`; the bid must be `SUBMITTED` or `AWARDED` and its
        `contractor_user_id` must equal `X-User-ID`. The bid moves to `WITHDRAWN`."

        Design: Corner/rbac/contractor_cannot_withdraw_another_firms_bid
        """
        scenario = self._two_bids()

        withdrawn = validate_success(
            api_client.withdraw_bid(
                scenario["second_bid"]["id"],
                withdraw_bid_payload("crew unavailable"),
                SECOND_CONTRACTOR,
            )
        )
        assert withdrawn["status"] == "WITHDRAWN"

        remaining = validate_success(
            api_client.get_contractor_bid(scenario["first_bid"]["id"], FIRST_COMMISSIONER)
        )
        assert remaining["status"] == "SUBMITTED"
        assert remaining["contractor_user_id"] == "c-1"

        _, meta = validate_paginated(
            api_client.list_project_bids(
                scenario["project"]["id"], FIRST_COMMISSIONER, params={"status": "SUBMITTED"}
            )
        )
        assert meta["total_count"] == 1


class TestProjectCreatorCannotAwardItsOwnProject:
    """Two commissioners, one role, and only `X-User-ID` tells them apart."""

    def _one_bonded_bid(self):
        """A GRADING project opened by rc-1 with a single bonded 400,000-cent bid."""
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Two Hands Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Two Hands Main", **MAIN_SEGMENT)
        project = setup_project(
            segment["id"],
            category="GRADING",
            window_start_date="2026-08-05",
            window_end_date="2026-08-08",
        )
        bid = submit_bid(
            project,
            400_000,
            contractor_user_id="c-1",
            contractor_name="Basin Grading LLC",
            bond_on_file=True,
        )
        return {"project": project, "bid": bid}

    def test_the_creating_commissioner_is_refused(self, api):
        """PRD §2.1: "awarding a maintenance project requires that `X-User-ID` differ
        from the project's `created_by_user_id`, and effectuating a delinquency remedy
        requires that `X-User-ID` differ from that remedy's `initiated_by_user_id`.
        Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/project_creator_cannot_award_its_own_project
        """
        scenario = self._one_bonded_bid()

        validate_error(
            api_client.award_project(
                scenario["project"]["id"],
                award_payload(scenario["bid"]["id"]),
                FIRST_COMMISSIONER,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        after = read_project(scenario["project"]["id"])
        assert after["status"] == "BID_SOLICITATION"
        assert after["awarded_by_user_id"] is None

    def test_the_second_commissioner_awards_the_identical_payload(self, api):
        """PRD §3.7: "The project's `awarded_bid_id`, `awarded_amount_cents` (taken from
        the awarded bid's `amount_cents`), and `awarded_by_user_id` are set, and
        `reserve_draw_cents` is set to the computed draw."

        Design: Corner/rbac/project_creator_cannot_award_its_own_project
        """
        scenario = self._one_bonded_bid()
        validate_error(
            api_client.award_project(
                scenario["project"]["id"],
                award_payload(scenario["bid"]["id"]),
                FIRST_COMMISSIONER,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        awarded = award(scenario["project"]["id"], scenario["bid"]["id"], SECOND_COMMISSIONER)
        assert awarded["status"] == "AWARDED"
        assert awarded["awarded_bid_id"] == scenario["bid"]["id"]
        assert awarded["awarded_amount_cents"] == 400_000
        assert awarded["awarded_by_user_id"] == "rc-2"
        assert awarded["created_by_user_id"] == "rc-1"


class TestRemedyInitiatorCannotEffectuateItsOwnRemedy:
    """The lien needs four eyes: bt-1 files it and bt-2 makes it bite."""

    def _initiated_lien(self):
        """A 1,600,000-cent charge past grace carrying a LIEN_FILING initiated by
        bt-1 and not yet effectuated."""
        return setup_delinquent_charge(
            parcel_specs=SINGLE_290,
            budget_requirement_cents=4_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            remedy_clock="2026-10-15T00:00:00Z",
            action_type="LIEN_FILING",
        )

    def test_the_initiating_treasurer_is_refused(self, api):
        """PRD §3.6: "It requires the remedy to be `INITIATED` (otherwise
        `ERR_ACTION_NOT_INITIATED`), requires `X-User-ID` to differ from
        `initiated_by_user_id`, and requires the charge's `balance_cents` to still be
        greater than zero."

        Design: Corner/rbac/remedy_initiator_cannot_effectuate_its_own_remedy
        """
        scenario = self._initiated_lien()
        action = scenario["action"]
        assert action["initiated_by_user_id"] == "bt-1"

        validate_error(
            api_client.effectuate_delinquency_action(action["id"], TREASURER),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        after = read_action(action["id"])
        assert after["status"] == "INITIATED"
        assert after["lien_amount_cents"] == 0
        assert read_charge(scenario["charge"]["id"])["status"] == "DELINQUENT"

    def test_the_second_treasurer_makes_the_lien_bite(self, api):
        """PRD §3.6: "First, the remedy moves `INITIATED → EFFECTIVE`, with
        `effective_at` and `effectuated_by_user_id` stamped; for a `LIEN_FILING` or an
        `ACCESS_RESTRICTION`, `lien_amount_cents` is frozen at the charge's
        `balance_cents` and `payoff_amount_cents` is set to the quoted payoff."

        Design: Corner/rbac/remedy_initiator_cannot_effectuate_its_own_remedy
        """
        scenario = self._initiated_lien()
        action = scenario["action"]
        validate_error(
            api_client.effectuate_delinquency_action(action["id"], TREASURER),
            "ERR_SEGREGATION_OF_DUTIES",
            403,
        )

        effective = validate_success(
            api_client.effectuate_delinquency_action(action["id"], SECOND_TREASURER)
        )
        assert effective["status"] == "EFFECTIVE"
        assert effective["effectuated_by_user_id"] == "bt-2"
        assert effective["initiated_by_user_id"] == "bt-1"
        assert effective["effective_at"].startswith("2026-10-15T00:00:00")
        assert effective["lien_amount_cents"] == 1_600_000

        assert read_charge(scenario["charge"]["id"])["status"] == "LIEN_ENCUMBERED"
        member = read_member(action["member_id"])
        assert member["standing_status"] == "LIEN_FILED"
        assert member["encumbered_principal_cents"] == 1_600_000


class TestPaymentsAreSharedButIdentityIsMandatory:
    """Two offices post against the same charge; a blank caller posts nothing."""

    def _open_charge(self):
        """A levied 4,000,000-cent roll leaving one OPEN charge of 1,600,000 cents
        due 2026-09-15."""
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=[
                {
                    "deed_book_page": "DB175-P01",
                    "frontage_feet": 290,
                    "usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "trips_per_day": 6,
                    "covenant_recorded": True,
                }
            ],
            budget_requirement_cents=4_000_000,
            levy_clock="2026-08-01T00:00:00Z",
            association_overrides={
                "name": "Front Desk Road Association",
                "reserve_target_cents": 1_000_000,
            },
            segment_overrides=dict(name="Front Desk Main", **MAIN_SEGMENT),
        )
        scenario["charge"] = scenario["charges"][0]
        return scenario

    def test_a_blank_user_id_is_rejected_before_any_ownership_check(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, naming the office that user is acting in. If
        either header is absent or blank, the request is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/payments_are_shared_but_a_missing_x_user_id_is_unauthenticated
        """
        scenario = self._open_charge()
        assert scenario["charge"]["status"] == "OPEN"
        assert scenario["charge"]["amount_cents"] == 1_600_000

        validate_error(
            api_client.create_payment(
                scenario["charge"]["id"],
                payment_payload(1_000_000),
                make_blank_user_headers("MemberOwner"),
            ),
            "ERR_UNAUTHENTICATED",
            401,
        )

        untouched = read_charge(scenario["charge"]["id"])
        assert untouched["paid_cents"] == 0
        assert untouched["balance_cents"] == 1_600_000

    def test_the_owner_and_the_clerk_each_apply_part_of_the_same_charge(self, api):
        """PRD §3.6: "A payment may be posted by the `AssessmentClerk` or by the owning
        `MemberOwner`, and it carries a single `amount_cents`."

        Design: Corner/rbac/payments_are_shared_but_a_missing_x_user_id_is_unauthenticated
        """
        scenario = self._open_charge()
        owner = make_member_owner_headers(scenario["members"][0]["id"])

        partly_paid = validate_success(
            api_client.create_payment(
                scenario["charge"]["id"], payment_payload(1_000_000), owner
            )
        )
        assert partly_paid["paid_cents"] == 1_000_000
        assert partly_paid["balance_cents"] == 600_000
        assert partly_paid["status"] == "OPEN"

        cleared = validate_success(
            api_client.create_payment(
                scenario["charge"]["id"], payment_payload(600_000), CLERK
            )
        )
        assert cleared["paid_cents"] == 1_600_000
        assert cleared["balance_cents"] == 0
        assert cleared["status"] == "PAID"

        member = read_member(scenario["members"][0]["id"])
        assert member["standing_status"] == "GOOD_STANDING"
        assert member["access_status"] == "UNRESTRICTED"
        assert member["encumbered_principal_cents"] == 0
