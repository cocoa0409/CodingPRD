"""New-lot connections: the four-component fee, the two entity states approval
depends on, and the charge states that keep a parcel intact."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_delinquency_action_payload,
    decide_connection_payload,
    file_connection_request,
    list_parcel_charges,
    make_clerk_headers,
    make_member_owner_headers,
    make_secretary_headers,
    make_treasurer_headers,
    payment_payload,
    read_action,
    read_association,
    read_connection_request,
    read_member,
    read_parcel,
    record_access_inspection,
    set_clock,
    setup_annual_assessment,
    setup_assessment_roll,
    setup_association,
    setup_member,
    setup_parcel,
    setup_road_segment,
    subdivide,
    validate_error,
    validate_paginated,
    validate_success,
    verify_deed_payload,
)

PINE_HOLLOW = {
    "name": "Pine Hollow Road Association",
    "reserve_target_cents": 1_000_000,
    "default_voting_basis": "PER_PARCEL",
    "delinquency_interest_basis": "STATUTORY",
    "quorum_bps": 5000,
}
SEGMENT_2400 = {
    "name": "Pine Hollow Road",
    "length_feet": 2400,
    "width_feet": 22,
    "max_grade_pct": 9,
    "surface_type": "GRAVEL",
    "turnout_count": 2,
    "culvert_count": 3,
    "turnaround_present": True,
    "bridge_present": False,
}
THREE_PARCELS = [
    {
        "deed_book_page": "DB120-P41",
        "frontage_feet": 290,
        "usage_class": "RESIDENTIAL_YEAR_ROUND",
        "trips_per_day": 6,
    },
    {
        "deed_book_page": "DB120-P42",
        "frontage_feet": 400,
        "usage_class": "SEASONAL",
        "trips_per_day": 3,
    },
    {
        "deed_book_page": "DB120-P43",
        "frontage_feet": 250,
        "usage_class": "AGRICULTURAL",
        "trips_per_day": 6,
    },
]
SINGLE_PARCEL = [THREE_PARCELS[0]]
COMPLIANT_MEASUREMENTS = {
    "measured_width_feet": 22,
    "measured_max_grade_pct": 9,
    "measured_turnout_count": 2,
    "turnaround_present": True,
}
SECRETARY = make_secretary_headers()
CLERK = make_clerk_headers()
TREASURER = make_treasurer_headers()
FIRST_TREASURER = make_treasurer_headers("bt-user-1")
SECOND_TREASURER = make_treasurer_headers("bt-user-2")


def _approve(api, request_id):
    return api.decide_connection_request(
        request_id, decide_connection_payload("APPROVED"), SECRETARY
    )


class TestConnectionFeeComponentRounding:
    """Round each of the four components, then add — never the other order."""

    def _request_on_a_half_foot_lot(self, api):
        set_clock("2026-10-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=THREE_PARCELS,
            fiscal_year=2027,
            fy_start_date="2026-10-01",
            fy_end_date="2027-09-30",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
            association_overrides=PINE_HOLLOW,
            segment_overrides=SEGMENT_2400,
        )
        record_access_inspection(
            scenario["segment"]["id"], "2026-10-01T00:00:00Z", **COMPLIANT_MEASUREMENTS
        )
        parent = scenario["parcels"][1]
        member = scenario["members"][1]
        charge = [c for c in scenario["charges"] if c["parcel_id"] == parent["id"]][0]
        assert charge["amount_cents"] == 1_315_068
        validate_success(
            api.create_payment(
                charge["id"],
                payment_payload(1_315_068),
                make_member_owner_headers(member["id"]),
            )
        )

        split = subdivide(
            parent["id"],
            [
                {"deed_book_page": "DB120-P42A", "frontage_feet": 137.5},
                {"deed_book_page": "DB120-P42B", "frontage_feet": 262.5},
            ],
        )
        scenario["lot"] = split["children"][0]
        scenario["parent_member"] = member
        scenario["request"] = file_connection_request(
            scenario["lot"]["id"],
            requested_usage_class="RESIDENTIAL_YEAR_ROUND",
            requested_trips_per_day=3.5,
            easement_grant_recorded=True,
        )
        return scenario

    def test_each_component_is_rounded_before_the_four_are_added(self, api):
        """PRD §3.8: "The fee itself has four components, and each is rounded half up
        to whole cents on its own before the four integers are added; summing the
        exact components and rounding once at the end is a different and wrong
        answer, because the halves of the frontage and trip components can add to a
        whole cent."
        PRD §3.8: "The base component is a flat two hundred and fifty thousand cents.
        The frontage component is the lot's `frontage_feet` multiplied by one thousand
        eight hundred and seventy-five cents per foot. The trip component is the
        request's `requested_trips_per_day` multiplied by forty-one thousand seven
        hundred and thirty-three cents."

        Design: Difficulty/combinatorial_formula/connection_fee_round_per_component_versus_sum_then_round
        """
        scenario = self._request_on_a_half_foot_lot(api)
        assert scenario["request"]["status"] == "SUBMITTED"
        assert scenario["request"]["connection_fee_cents"] == 0

        approved = validate_success(_approve(api, scenario["request"]["id"]))

        assert approved["status"] == "APPROVED"
        assert approved["connection_fee_cents"] == 693_165, (
            "250000 + 257813 + 146066 + 39286, each component rounded on its own"
        )
        assert approved["connection_fee_cents"] != 693_164, (
            "693164 is the sum-then-round answer and is wrong"
        )
        # PRD §3.8 stamps `decided_at` with the current logical-clock instant but
        # never pins the fractional-digit rendering of that field, so the instant
        # is asserted rather than one particular serialisation of it.
        assert approved["decided_at"].startswith("2026-10-01T00:00:00")
        assert approved["decided_by_user_id"] == "sec-1"

    def test_the_reserve_component_uses_the_post_subdivision_frontage_total(self, api):
        """PRD §3.8: "take the current total frontage share units of the association,
        being the sum of `frontage_share_units` over every parcel that is `ACTIVE`
        with `covenant_recorded` true on a segment of this association — a set which
        excludes both the `SUBDIVIDED` parent and the connecting lot itself; and
        multiply thirty-five hundredths by the deficit and by the new lot's units,
        then divide by that association total."
        PRD §3.8: "Fourth, because `reserve_buyin_cents` was credited, the
        association's `reserve_balance_cents` rises by that amount,
        `reserve_funding_ratio` and `reserve_posture` are recomputed, and every
        `DRAFT` proposal's `required_threshold_bps` follows."

        Design: Difficulty/combinatorial_formula/connection_fee_round_per_component_versus_sum_then_round
        """
        scenario = self._request_on_a_half_foot_lot(api)
        before = read_association(scenario["association"]["id"])
        assert before["reserve_balance_cents"] == 600_000, "fifteen percent of 4000000"

        approved = validate_success(_approve(api, scenario["request"]["id"]))

        assert approved["reserve_buyin_cents"] == 39_286, (
            "0.35 * 400000 * 137.5 / 490, so the denominator is 490 and not 730"
        )
        after = read_association(scenario["association"]["id"])
        assert after["reserve_balance_cents"] == 639_286
        assert after["reserve_posture"] == "ADEQUATE"

    def test_approval_activates_the_lot_and_bills_the_parent_member(self, api):
        """PRD §3.8: "Second, because the request was approved, the lot's parcel moves
        `PENDING_CONNECTION → ACTIVE`, its `covenant_recorded` becomes true, its
        `usage_class` and `trips_per_day` are taken from the request's
        `requested_usage_class` and `requested_trips_per_day`, and both of its share
        units are recomputed."
        PRD §3.8: "Third, because a fee was assessed, a charge is created with
        `charge_type` `CONNECTION_FEE`, `roll_id` set to the association's latest
        levied roll under the same ranking used for special assessments, `parcel_id`
        set to the new lot, `member_id` set to the parent parcel's member — the new
        owner has no membership yet, so the parent is billed — `status` `OPEN`, and a
        `due_date` of the current clock date plus forty-five days."

        Design: Difficulty/combinatorial_formula/connection_fee_round_per_component_versus_sum_then_round
        """
        scenario = self._request_on_a_half_foot_lot(api)
        validate_success(_approve(api, scenario["request"]["id"]))

        lot = read_parcel(scenario["lot"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["covenant_recorded"] is True
        assert lot["usage_class"] == "RESIDENTIAL_YEAR_ROUND"
        assert lot["trips_per_day"] == pytest.approx(3.5, abs=0.0001)
        assert lot["frontage_share_units"] == pytest.approx(137.5, abs=0.0001)
        assert lot["trip_share_units"] == pytest.approx(115, abs=0.0001), (
            "3.5 * 25 + 137.5 * 0.20"
        )

        charges = list_parcel_charges(lot["id"])
        assert len(charges) == 1
        charge = charges[0]
        assert charge["charge_type"] == "CONNECTION_FEE"
        assert charge["amount_cents"] == 693_165
        assert charge["status"] == "OPEN"
        assert charge["due_date"] == "2026-11-15"
        assert charge["roll_id"] == scenario["roll"]["id"]
        assert charge["member_id"] == scenario["parent_member"]["id"]


class TestApprovalDependsOnTwoOtherEntities:
    """A deed verification on one row and a levy on another decide the approval."""

    def _birch_landing(self, api):
        set_clock("2026-10-01T00:00:00Z")
        association = setup_association(
            **dict(PINE_HOLLOW, name="Birch Landing Road Association")
        )
        segment = setup_road_segment(
            association["id"], **dict(SEGMENT_2400, name="Birch Landing Road")
        )
        record_access_inspection(segment["id"], "2026-10-01T00:00:00Z", **COMPLIANT_MEASUREMENTS)
        p1 = setup_parcel(
            segment["id"],
            deed_book_page="DB150-P01",
            frontage_feet=290,
            usage_class="RESIDENTIAL_YEAR_ROUND",
            trips_per_day=6,
        )
        p2 = setup_parcel(
            segment["id"],
            deed_book_page="DB150-P02",
            frontage_feet=400,
            usage_class="SEASONAL",
            trips_per_day=3,
        )
        m1 = setup_member(
            p1["id"],
            verified=False,
            owner_name="Ada Reyes",
            deed_book_page="DB150-P01",
            deed_recorded_date="2019-04-12",
        )
        m2 = setup_member(
            p2["id"],
            owner_name="Bo Nakamura",
            deed_book_page="DB150-P02",
            deed_recorded_date="2020-06-03",
        )
        split = subdivide(
            p1["id"],
            [
                {"deed_book_page": "DB150-P01A", "frontage_feet": 145},
                {"deed_book_page": "DB150-P01B", "frontage_feet": 145},
            ],
        )
        return {
            "association": association,
            "segment": segment,
            "p1": p1,
            "p2": p2,
            "m1": m1,
            "m2": m2,
            "lot": split["children"][0],
        }

    def _levy_fy2027(self, api, association_id):
        roll = setup_assessment_roll(
            association_id,
            fiscal_year=2027,
            fy_start_date="2026-10-01",
            fy_end_date="2027-09-30",
            budget_requirement_cents=1_000_000,
            method_variant="FRONTAGE_WEIGHTED",
        )
        validate_success(api.certify_roll(roll["id"], CLERK))
        return validate_success(api.levy_roll(roll["id"], TREASURER))

    def test_a_parent_member_still_awaiting_deed_verification_blocks_the_lot(self, api):
        """PRD §3.8: "a member must exist on that parent parcel whose
        `standing_status` is past `PENDING_DEED_VERIFICATION`, since that member is
        who the connection fee will be billed to. A request naming a parcel with no
        subdivision parent, or a parent with no verified member, is rejected with
        `ERR_PARENT_MEMBER_NOT_FOUND`."
        PRD §2.10 item 32: "The parcel named by a connection request has
        `covenant_recorded` false and a non-null `parent_parcel_id`, and a member
        exists on the parent parcel whose `standing_status` is something other than
        `PENDING_DEED_VERIFICATION` — otherwise `ERR_PARENT_MEMBER_NOT_FOUND` (409),
        on connection filing and connection decision."

        Design: Difficulty/cross_entity_state_dependency/connection_approval_depends_on_parent_member_and_roll_states
        """
        world = self._birch_landing(api)
        assert read_member(world["m1"]["id"])["standing_status"] == "PENDING_DEED_VERIFICATION"

        validate_error(
            api.create_connection_request(
                {
                    "parcel_id": world["lot"]["id"],
                    "requested_usage_class": "RESIDENTIAL_YEAR_ROUND",
                    "requested_trips_per_day": 4,
                    "easement_grant_recorded": True,
                },
                SECRETARY,
            ),
            ApiErrorId.ERR_PARENT_MEMBER_NOT_FOUND.value,
        )

        requests, _meta = validate_paginated(
            api.list_connection_requests(SECRETARY, params={"parcel_id": world["lot"]["id"]})
        )
        assert requests == [], "no request row survives the rejected filing"
        assert read_parcel(world["lot"]["id"])["status"] == "PENDING_CONNECTION"

    def test_approval_needs_a_levied_roll_to_hang_the_fee_charge_on(self, api):
        """PRD §3.8: "requires the association to have at least one roll whose
        `status` is `LEVIED` to hang the fee charge on — no levied roll means
        `ERR_ROLL_NOT_FOUND`."
        PRD §3.8: "The new request starts `SUBMITTED` with `connection_fee_cents` and
        `reserve_buyin_cents` at zero, and null `dispute_reason`, `resolution_note`,
        `decided_at`, and `decided_by_user_id`. No fee is computed until approval."

        Design: Difficulty/cross_entity_state_dependency/connection_approval_depends_on_parent_member_and_roll_states
        """
        world = self._birch_landing(api)
        verified = validate_success(
            api.verify_deed(world["m1"]["id"], verify_deed_payload("DB150-P01"), SECRETARY)
        )
        assert verified["standing_status"] == "GOOD_STANDING"

        request = file_connection_request(
            world["lot"]["id"],
            requested_usage_class="RESIDENTIAL_YEAR_ROUND",
            requested_trips_per_day=4,
            easement_grant_recorded=True,
        )
        assert request["status"] == "SUBMITTED"
        assert request["connection_fee_cents"] == 0
        assert request["reserve_buyin_cents"] == 0
        assert request["decided_at"] is None

        validate_error(_approve(api, request["id"]), ApiErrorId.ERR_ROLL_NOT_FOUND.value)

        unchanged = read_connection_request(request["id"])
        assert unchanged["status"] == "SUBMITTED"
        assert unchanged["connection_fee_cents"] == 0
        assert read_parcel(world["lot"]["id"])["status"] == "PENDING_CONNECTION"

    def test_the_levied_reserve_balance_and_the_parent_member_shape_the_fee(self, api):
        """PRD §3.8: "The reserve buy-in component makes the new lot pay its share of
        the reserve shortfall: take the association's `reserve_target_cents` less its
        `reserve_balance_cents`, floored at zero, to get the deficit; take the new
        lot's frontage share units, being its `frontage_feet` multiplied by the
        usage-class multiplier for the `requested_usage_class`"
        PRD §3.4: "The roll's `reserve_contribution_cents` is set to fifteen percent
        of `budget_requirement_cents`, rounded half up to whole cents, and that
        amount is credited to the association's `reserve_balance_cents`"

        Design: Difficulty/cross_entity_state_dependency/connection_approval_depends_on_parent_member_and_roll_states
        """
        world = self._birch_landing(api)
        validate_success(
            api.verify_deed(world["m1"]["id"], verify_deed_payload("DB150-P01"), SECRETARY)
        )
        request = file_connection_request(
            world["lot"]["id"],
            requested_usage_class="RESIDENTIAL_YEAR_ROUND",
            requested_trips_per_day=4,
            easement_grant_recorded=True,
        )
        roll = self._levy_fy2027(api, world["association"]["id"])

        assert roll["total_share_units"] == pytest.approx(240, abs=0.01), "only P2 is assessable"
        assert roll["total_levied_cents"] == 400_000
        assert roll["unallocated_residual_cents"] == 600_000
        assert roll["reserve_contribution_cents"] == 150_000

        approved = validate_success(_approve(api, request["id"]))

        assert approved["status"] == "APPROVED"
        assert approved["reserve_buyin_cents"] == 179_740, (
            "0.35 * 850000 * 145 / 240, the deficit taken after the levy"
        )
        assert approved["connection_fee_cents"] == 868_547, (
            "250000 + 271875 + 166932 + 179740"
        )

        lot = read_parcel(world["lot"]["id"])
        assert lot["status"] == "ACTIVE"
        assert lot["covenant_recorded"] is True
        assert lot["trips_per_day"] == pytest.approx(4, abs=0.0001)
        assert lot["frontage_share_units"] == pytest.approx(145, abs=0.0001)

        charges = list_parcel_charges(lot["id"])
        assert len(charges) == 1
        assert charges[0]["charge_type"] == "CONNECTION_FEE"
        assert charges[0]["amount_cents"] == 868_547
        assert charges[0]["member_id"] == world["m1"]["id"], "the parent's member is billed"
        assert charges[0]["roll_id"] == roll["id"]
        assert charges[0]["status"] == "OPEN"
        assert charges[0]["due_date"] == "2026-11-15"

        association = read_association(world["association"]["id"])
        assert association["reserve_balance_cents"] == 329_740
        assert association["reserve_posture"] == "UNDERFUNDED"


CHILDREN_145 = [
    {"deed_book_page": "DB120-P41A", "frontage_feet": 145},
    {"deed_book_page": "DB120-P41B", "frontage_feet": 145},
]


class TestSubdivisionChargeGate:
    """Three charge states block a split, and only payment opens the gate."""

    def _levied_single_parcel(self, api):
        set_clock("2026-10-01T00:00:00Z")
        scenario = setup_annual_assessment(
            parcel_specs=SINGLE_PARCEL,
            fiscal_year=2027,
            fy_start_date="2026-10-01",
            fy_end_date="2027-09-30",
            budget_requirement_cents=4_000_000,
            method_variant="FRONTAGE_WEIGHTED",
            association_overrides=PINE_HOLLOW,
            segment_overrides=SEGMENT_2400,
        )
        scenario["parcel"] = scenario["parcels"][0]
        scenario["charge"] = scenario["charges"][0]
        assert scenario["charge"]["amount_cents"] == 1_600_000
        assert scenario["charge"]["due_date"] == "2026-11-15"
        return scenario

    def _split(self, api, parcel_id):
        return api.subdivide_parcel(parcel_id, {"children": CHILDREN_145}, SECRETARY)

    def test_an_open_charge_blocks_the_split(self, api):
        """PRD §3.2: "the parent must carry no charge whose `status` is `OPEN`,
        `DELINQUENT`, or `LIEN_ENCUMBERED` — an association does not let an owner
        subdivide out from under an unpaid assessment, and the attempt fails with
        `ERR_PARCEL_HAS_OPEN_CHARGES`."

        Design: Difficulty/cross_entity_state_dependency/subdivision_gate_tracks_every_blocking_charge_state
        """
        scenario = self._levied_single_parcel(api)
        assert scenario["charge"]["status"] == "OPEN"
        assert scenario["roll"]["status"] == "LEVIED", "no certified-roll lock is in play"

        validate_error(
            self._split(api, scenario["parcel"]["id"]),
            ApiErrorId.ERR_PARCEL_HAS_OPEN_CHARGES.value,
        )

        assert read_parcel(scenario["parcel"]["id"])["status"] == "ACTIVE"
        children, _meta = validate_paginated(
            api.list_parcels(
                SECRETARY, params={"parent_parcel_id": scenario["parcel"]["id"]}
            )
        )
        assert children == []

    def test_a_delinquent_charge_still_blocks_the_split(self, api):
        """PRD §2.10 item 52: "The parcel has no charge whose `status` is `OPEN`,
        `DELINQUENT`, or `LIEN_ENCUMBERED`, at subdivision — otherwise
        `ERR_PARCEL_HAS_OPEN_CHARGES` (409)."
        PRD §3.6: "As a side effect of the first action against a charge, the charge
        moves `OPEN → DELINQUENT` and `delinquent_since` is stamped with the current
        clock date, and the member's `standing_status` is reconciled to `DELINQUENT`."

        Design: Difficulty/cross_entity_state_dependency/subdivision_gate_tracks_every_blocking_charge_state
        """
        scenario = self._levied_single_parcel(api)
        set_clock("2026-12-15T00:00:00Z")
        validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("NOTICE"),
                FIRST_TREASURER,
            ),
            201,
        )
        assert (
            validate_success(
                api.get_assessment_charge(scenario["charge"]["id"], CLERK)
            )["status"]
            == "DELINQUENT"
        )

        validate_error(
            self._split(api, scenario["parcel"]["id"]),
            ApiErrorId.ERR_PARCEL_HAS_OPEN_CHARGES.value,
        )
        assert read_parcel(scenario["parcel"]["id"])["status"] == "ACTIVE"

    def test_a_lien_encumbered_charge_still_blocks_the_split(self, api):
        """PRD §3.6: "Second, because a `LIEN_FILING` or `ACCESS_RESTRICTION` became
        effective, the charge moves `DELINQUENT → LIEN_ENCUMBERED`; a `NOTICE` leaves
        the charge `DELINQUENT`."
        PRD §3.2: "The parent must be `ACTIVE`, no roll of its association may be
        `CERTIFIED`, and the parent must carry no charge whose `status` is `OPEN`,
        `DELINQUENT`, or `LIEN_ENCUMBERED`"

        Design: Difficulty/cross_entity_state_dependency/subdivision_gate_tracks_every_blocking_charge_state
        """
        scenario = self._levied_single_parcel(api)
        set_clock("2026-12-15T00:00:00Z")
        validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("NOTICE"),
                FIRST_TREASURER,
            ),
            201,
        )
        lien = validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("LIEN_FILING"),
                FIRST_TREASURER,
            ),
            201,
        )
        validate_success(api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER))
        assert (
            validate_success(
                api.get_assessment_charge(scenario["charge"]["id"], CLERK)
            )["status"]
            == "LIEN_ENCUMBERED"
        )

        validate_error(
            self._split(api, scenario["parcel"]["id"]),
            ApiErrorId.ERR_PARCEL_HAS_OPEN_CHARGES.value,
        )

        parent = read_parcel(scenario["parcel"]["id"])
        assert parent["status"] == "ACTIVE"
        assert parent["version"] == scenario["parcel"]["version"], (
            "three rejections leave the parcel untouched"
        )

    def test_paying_the_charge_in_full_opens_the_gate(self, api):
        """PRD §3.6: "Clearing a balance unwinds the remedies attached to it. Because
        the charge reached `PAID`, every delinquency action on that charge whose
        `status` is `EFFECTIVE` moves `EFFECTIVE → RELEASED` with `released_at`
        stamped and its `lien_amount_cents` reset to zero"
        PRD §3.2: "On success, one parcel is created per entry in `children`, each
        with `parent_parcel_id` pointing at the parent, `status` `PENDING_CONNECTION`,
        `covenant_recorded` false, `usage_class` `UNDEVELOPED`, `trips_per_day` zero,
        and `road_segment_id` copied from the parent; the parent moves
        `ACTIVE → SUBDIVIDED`, leaving the assessable set, and its `version`
        increments by one."

        Design: Difficulty/cross_entity_state_dependency/subdivision_gate_tracks_every_blocking_charge_state
        """
        scenario = self._levied_single_parcel(api)
        member = scenario["members"][0]
        set_clock("2026-12-15T00:00:00Z")
        notice = validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("NOTICE"),
                FIRST_TREASURER,
            ),
            201,
        )
        lien = validate_success(
            api.create_delinquency_action(
                scenario["charge"]["id"],
                create_delinquency_action_payload("LIEN_FILING"),
                FIRST_TREASURER,
            ),
            201,
        )
        validate_success(api.effectuate_delinquency_action(lien["id"], SECOND_TREASURER))
        validate_error(
            self._split(api, scenario["parcel"]["id"]),
            ApiErrorId.ERR_PARCEL_HAS_OPEN_CHARGES.value,
        )

        paid = validate_success(
            api.create_payment(scenario["charge"]["id"], payment_payload(1_600_000), CLERK)
        )
        assert paid["status"] == "PAID"
        assert paid["balance_cents"] == 0
        assert read_action(lien["id"])["status"] == "RELEASED"
        assert read_action(lien["id"])["lien_amount_cents"] == 0
        assert read_action(notice["id"])["status"] == "INITIATED", (
            "only EFFECTIVE remedies are released by a payment"
        )

        cleared = read_member(member["id"])
        assert cleared["standing_status"] == "GOOD_STANDING"
        assert cleared["encumbered_principal_cents"] == 0
        assert cleared["access_status"] == "UNRESTRICTED"

        before = read_parcel(scenario["parcel"]["id"])
        split = validate_success(self._split(api, scenario["parcel"]["id"]))

        assert split["parent_parcel"]["status"] == "SUBDIVIDED"
        assert split["parent_parcel"]["version"] == before["version"] + 1
        children = split["children"]
        assert len(children) == 2
        assert [child["deed_book_page"] for child in children] == [
            "DB120-P41A",
            "DB120-P41B",
        ]
        for child in children:
            assert child["frontage_feet"] == pytest.approx(145, abs=0.0001)
            assert child["status"] == "PENDING_CONNECTION"
            assert child["covenant_recorded"] is False
            assert child["usage_class"] == "UNDEVELOPED"
            assert child["trips_per_day"] == pytest.approx(0, abs=0.0001)
            assert child["parent_parcel_id"] == scenario["parcel"]["id"]
            assert child["road_segment_id"] == scenario["segment"]["id"]
