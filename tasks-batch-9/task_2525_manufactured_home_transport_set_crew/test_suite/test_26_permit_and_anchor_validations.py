"""Ordered permit-issuance gates, the anchoring revision ceiling and the
section mate pointer (PRD §3.4, §3.8 and §3.2)."""

from test_helpers import (
    ANCHOR_INSPECTOR_USER_ID,
    ApiErrorId,
    add_route_leg,
    api_client,
    assert_transport_permit,
    book_set_job,
    create_section_payload,
    make_network_admin_headers,
    make_permit_desk_headers,
    make_plant_dispatcher_headers,
    make_set_crew_lead_headers,
    open_order,
    pay_permit_fee,
    read_anchor_certification,
    read_permit,
    read_section,
    record_section,
    register_plant,
    register_set_crew,
    reserve_escort,
    resubmit_anchor_certification,
    resubmit_anchor_certification_payload,
    review_anchor_certification,
    set_logical_clock,
    setup_leg_awaiting_escorts,
    submit_anchor_certification,
    validate_error,
    validate_paginated,
    validate_success,
)

BRAZOS_ESCORT = {
    "vendor_name": "Brazos Escort",
    "endorsed_states": ["TX"],
    "certified_roles": ["ESCORT", "PILOT_CAR"],
    "endorsement_class": "OVERSIZE",
    "buffer_minutes": 30,
    "max_reserved_minutes": 900,
}

GILA_PILOT_CARS = {
    "vendor_name": "Gila Pilot Cars",
    "endorsed_states": ["AZ"],
    "certified_roles": ["ESCORT", "PILOT_CAR"],
    "endorsement_class": "STANDARD",
    "buffer_minutes": 15,
    "max_reserved_minutes": 1200,
}


def _texas_permit_paid_for_one_leg_then_given_a_second():
    """A Texas permit paid to its provisional fee and then handed a second leg.

    Texas contributes one base escort, so the provisional fee over one planned
    leg is 12,000 + 4,500 + 7,500 = 24,000 cents.  Once a second corridor leg
    exists the final fee rises to 12,000 + 9,000 + 7,500 = 28,500 cents, which
    leaves the permit both under-escorted and under-paid.
    """
    scenario = setup_leg_awaiting_escorts(
        state_code="TX",
        destination_state="TX",
        declared_width_in=168,
        declared_height_in=150,
        planned_leg_count=1,
        corridor_id="TX-I35",
        escort_crews=[BRAZOS_ESCORT],
    )
    permit = scenario["permit"]
    assert_transport_permit(permit)
    assert permit["escort_count_required"] == 1, (
        f"Texas contributes one base escort, got {permit['escort_count_required']}"
    )
    assert permit["provisional_fee_cents"] == 24000, (
        f"expected provisional_fee_cents 24000, got {permit['provisional_fee_cents']}"
    )
    paid = pay_permit_fee(permit["id"], scenario["hauler"]["id"], 24000)
    assert paid["status"] == "FEE_PAID", (
        f"remitting the whole provisional fee moves the permit to FEE_PAID, "
        f"got {paid['status']}"
    )
    scenario["second_leg"] = add_route_leg(
        permit["id"],
        scenario["hauler"]["id"],
        sequence_no=2,
        corridor_id="TX-I10",
        state_code="TX",
        window_start="2026-08-04T06:00:00.000Z",
        window_end="2026-08-04T18:00:00.000Z",
    )
    return scenario


class TestEscortShortfallOutranksUnpaidFee:
    """Issuance runs escort sufficiency strictly before fee coverage."""

    def test_under_escorted_and_under_paid_permit_reports_the_shortfall(self):
        """PRD §3.4: "First, escort sufficiency: counting reserved escort
        assignments across the permit's legs whose `status` is `SCHEDULED` or
        `IN_TRANSIT`, the number carrying `role` `ESCORT` must be at least the
        freshly computed `escort_count_required`, and when the freshly computed
        `pilot_car_required` is true, at least one reserved assignment carrying
        `role` `PILOT_CAR` must exist across those same legs." "A shortfall on
        either arm is refused with `ERR_PERMIT_ESCORT_SHORTFALL`." "Second, and
        only afterwards, fee coverage: `paid_amount_cents` must be at least the
        freshly computed `final_fee_cents`, failing which the request is refused
        with `ERR_PERMIT_FEE_UNPAID` and HTTP 402." "Because escort sufficiency
        outranks fee coverage, a permit that is both under-escorted and
        under-paid reports the shortfall."

        Design: Corner/validations/escort_shortfall_outranks_unpaid_fee_on_issue
        """
        scenario = _texas_permit_paid_for_one_leg_then_given_a_second()
        permit_id = scenario["permit"]["id"]

        response = api_client.issue_permit(permit_id, {}, make_permit_desk_headers())
        validate_error(response, ApiErrorId.ERR_PERMIT_ESCORT_SHORTFALL, 422)

        permit = read_permit(permit_id)
        assert permit["status"] == "FEE_PAID", (
            f"a refused issuance leaves the permit in FEE_PAID, "
            f"got {permit['status']}"
        )
        assert permit["valid_until_date"] is None, (
            f"valid_until_date is written only on a successful issuance, "
            f"got {permit['valid_until_date']}"
        )
        assert permit["paid_amount_cents"] == 24000, (
            f"the remittance stands untouched at 24000, "
            f"got {permit['paid_amount_cents']}"
        )
        section = read_section(scenario["section"]["id"])
        assert section["transit_status"] == "PERMIT_PENDING", (
            f"the floor stays PERMIT_PENDING until the permit issues, "
            f"got {section['transit_status']}"
        )

    def test_fee_gate_reports_unpaid_only_once_the_escorts_are_covered(self):
        """PRD §3.4: "Second, and only afterwards, fee coverage:
        `paid_amount_cents` must be at least the freshly computed
        `final_fee_cents`, failing which the request is refused with
        `ERR_PERMIT_FEE_UNPAID` and HTTP 402." "The **final** variant runs at
        issuance; it uses the floor's `measured_width_in` and
        `measured_height_in`, falling back to the declared figures only where a
        measured figure is still null, and it uses the permit's *actual* leg
        count — the number of that permit's route legs whose `status` is
        `SCHEDULED`, `IN_TRANSIT` or `ARRIVED`."

        The second corridor leg lifts the final fee to 28,500 cents, so the
        24,000 cents already remitted no longer cover it.

        Design: Corner/validations/escort_shortfall_outranks_unpaid_fee_on_issue
        """
        scenario = _texas_permit_paid_for_one_leg_then_given_a_second()
        permit_id = scenario["permit"]["id"]
        hauler_id = scenario["hauler"]["id"]

        reserve_escort(
            scenario["leg"]["id"],
            scenario["escort_crews"][0]["id"],
            hauler_id,
            role="ESCORT",
        )
        response = api_client.issue_permit(permit_id, {}, make_permit_desk_headers())
        validate_error(response, ApiErrorId.ERR_PERMIT_FEE_UNPAID, 402)

        permit = read_permit(permit_id)
        assert permit["status"] == "FEE_PAID", (
            f"the refused issuance leaves the permit in FEE_PAID, "
            f"got {permit['status']}"
        )
        assert permit["paid_amount_cents"] == 24000, (
            f"the remittance stands untouched at 24000, "
            f"got {permit['paid_amount_cents']}"
        )
        assert permit["valid_until_date"] is None, (
            f"valid_until_date is written only on a successful issuance, "
            f"got {permit['valid_until_date']}"
        )


def _arizona_permit_over_three_legs_awaiting_coverage():
    """An Arizona permit whose three corridor legs demand a pilot car.

    Arizona contributes no base escort and the box is neither wide nor tall, so
    the escort requirement is zero; the three-leg count alone raises
    `pilot_car_required`.  The fee is 12,000 + 3 x 4,500 = 25,500 cents both
    provisionally and finally, so the fee gate is satisfied from the start and
    only the pilot-car arm can fail.
    """
    scenario = setup_leg_awaiting_escorts(
        state_code="AZ",
        destination_state="AZ",
        declared_width_in=168,
        declared_height_in=150,
        planned_leg_count=3,
        escort_crews=[GILA_PILOT_CARS],
    )
    permit = scenario["permit"]
    hauler_id = scenario["hauler"]["id"]
    scenario["legs"] = [scenario["leg"]]
    scenario["legs"].append(
        add_route_leg(
            permit["id"],
            hauler_id,
            sequence_no=2,
            corridor_id="AZ-I17",
            state_code="AZ",
            window_start="2026-08-04T06:00:00.000Z",
            window_end="2026-08-04T18:00:00.000Z",
        )
    )
    scenario["legs"].append(
        add_route_leg(
            permit["id"],
            hauler_id,
            sequence_no=3,
            corridor_id="AZ-US60",
            state_code="AZ",
            window_start="2026-08-05T06:00:00.000Z",
            window_end="2026-08-05T18:00:00.000Z",
        )
    )
    paid = pay_permit_fee(permit["id"], hauler_id, 25500)
    assert paid["status"] == "FEE_PAID", (
        f"remitting the whole provisional fee moves the permit to FEE_PAID, "
        f"got {paid['status']}"
    )
    return scenario


class TestPilotCarArmOfEscortSufficiency:
    """The pilot-car arm fires only when the freshly computed flag is true."""

    def test_reserved_escort_does_not_satisfy_the_pilot_car_arm(self):
        """PRD §3.4: "First, escort sufficiency: counting reserved escort
        assignments across the permit's legs whose `status` is `SCHEDULED` or
        `IN_TRANSIT`, the number carrying `role` `ESCORT` must be at least the
        freshly computed `escort_count_required`, and when the freshly computed
        `pilot_car_required` is true, at least one reserved assignment carrying
        `role` `PILOT_CAR` must exist across those same legs." "A shortfall on
        either arm is refused with `ERR_PERMIT_ESCORT_SHORTFALL`."

        Arizona demands no escorts at all, so a reservation in the `ESCORT` role
        covers an arm that was never in question and leaves the pilot-car arm
        unmet.

        Design: Corner/validations/pilot_car_arm_of_escort_sufficiency_is_conditional_on_the_flag
        """
        scenario = _arizona_permit_over_three_legs_awaiting_coverage()
        permit_id = scenario["permit"]["id"]
        permit = read_permit(permit_id)
        assert permit["escort_count_required"] == 0, (
            f"expected escort_count_required 0 in Arizona, "
            f"got {permit['escort_count_required']}"
        )
        assert permit["pilot_car_required"] is True, (
            f"three corridor legs demand a pilot car, "
            f"got {permit['pilot_car_required']}"
        )

        reserve_escort(
            scenario["legs"][0]["id"],
            scenario["escort_crews"][0]["id"],
            scenario["hauler"]["id"],
            role="ESCORT",
        )
        response = api_client.issue_permit(permit_id, {}, make_permit_desk_headers())
        validate_error(response, ApiErrorId.ERR_PERMIT_ESCORT_SHORTFALL, 422)

        unchanged = read_permit(permit_id)
        assert unchanged["status"] == "FEE_PAID", (
            f"the refused issuance leaves the permit in FEE_PAID, "
            f"got {unchanged['status']}"
        )
        assert unchanged["valid_until_date"] is None, (
            f"valid_until_date is written only on a successful issuance, "
            f"got {unchanged['valid_until_date']}"
        )

    def test_pilot_car_reservation_on_any_leg_satisfies_the_arm_and_issues(self):
        """PRD §3.4: "Sufficiency is aggregate across the permit rather than per
        leg." "On success the permit's `valid_until_date` is set to the logical
        clock's current UTC date plus five days, the permit's floor moves
        `PERMIT_PENDING → DISPATCH_READY` — or `PERMIT_REVOKED_HOLD →
        DISPATCH_READY` when a held floor is being re-permitted, which is how a
        revocation hold is cleared — both rows' `version` values rise, and the
        order's posture is re-derived."

        The pilot car is reserved on the second corridor leg while the escort
        sits on the first, and aggregate sufficiency accepts that.

        Design: Corner/validations/pilot_car_arm_of_escort_sufficiency_is_conditional_on_the_flag
        """
        scenario = _arizona_permit_over_three_legs_awaiting_coverage()
        permit_id = scenario["permit"]["id"]
        crew_id = scenario["escort_crews"][0]["id"]
        hauler_id = scenario["hauler"]["id"]

        reserve_escort(scenario["legs"][0]["id"], crew_id, hauler_id, role="ESCORT")
        reserve_escort(
            scenario["legs"][1]["id"],
            crew_id,
            hauler_id,
            role="PILOT_CAR",
            window_start="2026-08-04T06:00:00.000Z",
            window_end="2026-08-04T14:00:00.000Z",
        )

        issued = validate_success(
            api_client.issue_permit(permit_id, {}, make_permit_desk_headers()), 200
        )
        assert issued["status"] == "ISSUED", (
            f"a covered permit issues, got {issued['status']}"
        )
        assert issued["final_fee_cents"] == 25500, (
            f"three corridor legs and no escorts price the final fee at 25500, "
            f"got {issued['final_fee_cents']}"
        )
        assert issued["valid_until_date"] == "2026-08-06", (
            f"the logical clock reads 2026-08-01, so the permit is valid until "
            f"2026-08-06, got {issued['valid_until_date']}"
        )
        section = read_section(scenario["section"]["id"])
        assert section["transit_status"] == "DISPATCH_READY", (
            f"issuance moves the floor to DISPATCH_READY, "
            f"got {section['transit_status']}"
        )


def _package_pushed_to_the_third_revision():
    """An anchoring package walked to `revision_round` 3 and left awaiting fixes.

    The order sits in wind zone `I` with a single section, so HUD demands eight
    anchors; the package opens six anchors short and is corrected twice.
    """
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(license_state="AZ")
    order = open_order(
        plant["id"], section_count=1, destination_state="AZ", wind_zone="I"
    )
    set_job = book_set_job(order["id"], set_crew["id"])
    certification = submit_anchor_certification(
        set_job["id"],
        set_crew["id"],
        anchor_count=6,
        avg_torque_ft_lb=180,
        strap_count=6,
        pier_count=6,
    )
    review_anchor_certification(
        certification["id"],
        decision="REQUEST_CHANGES",
        inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
    )
    second = resubmit_anchor_certification(
        certification["id"],
        set_crew["id"],
        anchor_count=7,
        avg_torque_ft_lb=180,
        strap_count=7,
        pier_count=6,
    )
    review_anchor_certification(
        certification["id"],
        decision="REQUEST_CHANGES",
        inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
    )
    third = resubmit_anchor_certification(
        certification["id"],
        set_crew["id"],
        anchor_count=8,
        avg_torque_ft_lb=120,
        strap_count=8,
        pier_count=6,
    )
    return set_crew, certification, second, third


class TestAnchorRevisionCeiling:
    """The revision cycle is bounded at three rounds."""

    def test_second_and_third_rounds_are_accepted_on_the_same_row(self):
        """PRD §3.8: "When changes have been requested, the job's `SetCrewLead`
        resubmits corrected figures on the **same** row, moving it
        `CHANGES_REQUIRED → SUBMITTED`; the resubmission overwrites
        `anchor_count`, `avg_torque_ft_lb`, `strap_count` and `pier_count` from
        the payload, increments `revision_round` by 1, and re-runs the HUD and
        state evaluation." "That closes the revision cycle `SUBMITTED →
        CHANGES_REQUIRED → SUBMITTED`, and the cycle is bounded: a resubmission
        is only accepted while `revision_round` is still below three, so the
        third round is the last and a fourth attempt is refused with
        `ERR_ANCHOR_REVISION_LIMIT`."

        Design: Corner/validations/anchor_revision_limit_rejects_the_fourth_submission
        """
        _, certification, second, third = _package_pushed_to_the_third_revision()

        assert second["id"] == certification["id"], (
            "a resubmission corrects the same row rather than opening a new one"
        )
        assert second["revision_round"] == 2, (
            f"the first resubmission lifts revision_round to 2, "
            f"got {second['revision_round']}"
        )
        assert second["anchor_count"] == 7, (
            f"the resubmission overwrites anchor_count with 7, "
            f"got {second['anchor_count']}"
        )
        assert second["status"] == "SUBMITTED", (
            f"a resubmission returns the package to SUBMITTED, "
            f"got {second['status']}"
        )
        assert third["revision_round"] == 3, (
            f"the second resubmission lifts revision_round to 3, "
            f"got {third['revision_round']}"
        )
        assert third["avg_torque_ft_lb"] == 120, (
            f"the resubmission overwrites avg_torque_ft_lb with 120, "
            f"got {third['avg_torque_ft_lb']}"
        )
        assert third["hud_pass"] is False, (
            f"120 foot-pounds is below the 175 foot-pound floor, so hud_pass "
            f"must be False, got {third['hud_pass']}"
        )
        assert third["state_pass"] is True, (
            f"eight anchors satisfy the Arizona count, "
            f"got state_pass {third['state_pass']}"
        )

    def test_fourth_resubmission_is_refused_and_leaves_the_row_untouched(self):
        """PRD §3.8: "That closes the revision cycle `SUBMITTED →
        CHANGES_REQUIRED → SUBMITTED`, and the cycle is bounded: a resubmission
        is only accepted while `revision_round` is still below three, so the
        third round is the last and a fourth attempt is refused with
        `ERR_ANCHOR_REVISION_LIMIT`." PRD §2.10 ranks that ceiling at priority
        27: "the anchoring certification's `revision_round` is below the revision
        ceiling. Applies to `POST /installations/anchor-certifications/{id}/resubmit`."

        Design: Corner/validations/anchor_revision_limit_rejects_the_fourth_submission
        """
        set_crew, certification, _, _ = _package_pushed_to_the_third_revision()
        changed = review_anchor_certification(
            certification["id"],
            decision="REQUEST_CHANGES",
            inspector_user_id=ANCHOR_INSPECTOR_USER_ID,
        )
        assert changed["status"] == "CHANGES_REQUIRED", (
            f"expected CHANGES_REQUIRED before the fourth attempt, "
            f"got {changed['status']}"
        )
        assert changed["revision_round"] == 3, (
            f"a review never advances revision_round, got {changed['revision_round']}"
        )

        response = api_client.resubmit_anchor_certification(
            certification["id"],
            resubmit_anchor_certification_payload(
                anchor_count=8, avg_torque_ft_lb=200, strap_count=8, pier_count=6
            ),
            make_set_crew_lead_headers(set_crew["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ANCHOR_REVISION_LIMIT, 422)

        stored = read_anchor_certification(certification["id"])
        assert stored["revision_round"] == 3, (
            f"the refused attempt must not advance revision_round past 3, "
            f"got {stored['revision_round']}"
        )
        assert stored["status"] == "CHANGES_REQUIRED", (
            f"the refused attempt leaves the package in CHANGES_REQUIRED, "
            f"got {stored['status']}"
        )
        assert stored["avg_torque_ft_lb"] == 120, (
            f"the refused payload must not overwrite avg_torque_ft_lb, "
            f"got {stored['avg_torque_ft_lb']}"
        )
        assert stored["hud_pass"] is False, (
            f"the refused attempt must not re-run the evaluation, "
            f"got hud_pass {stored['hud_pass']}"
        )


class TestSectionMatePointerStaysInsideTheOrder:
    """The marriage pointer may not reach across orders."""

    def test_mate_pointer_into_another_order_is_refused(self):
        """PRD §3.2: "The pointer is checked for self-referential integrity: it
        may not name the section itself, it may not reach into a different order,
        and it may not name a floor that is already mated to a third floor — any
        of those three yields `ERR_SECTION_MATE_INVALID`." PRD §2.10 ranks that
        at priority 16: "and a home section's `mates_to_section_id` must point at
        a different section of the **same** order and must not point at a section
        that is already mated to a third section."

        Design: Corner/validations/section_mate_pointer_must_stay_inside_the_order_and_be_unclaimed
        """
        set_logical_clock()
        plant = register_plant(state_code="AZ")
        order_a = open_order(
            plant["id"], section_count=3, home_model="Titan 3266", destination_state="AZ"
        )
        order_b = open_order(
            plant["id"],
            section_count=1,
            dealer_name="Desert Living",
            destination_state="AZ",
        )
        first_floor = record_section(order_a["id"], plant["id"], section_index=1)
        second_floor = record_section(
            order_a["id"],
            plant["id"],
            section_index=2,
            mates_to_section_id=first_floor["id"],
        )
        assert second_floor["mates_to_section_id"] == first_floor["id"], (
            f"a pointer at a sibling floor of the same order is accepted, "
            f"got {second_floor['mates_to_section_id']}"
        )

        response = api_client.create_section(
            create_section_payload(
                order_b["id"], section_index=1, mates_to_section_id=first_floor["id"]
            ),
            make_plant_dispatcher_headers(plant["id"]),
        )
        validate_error(response, ApiErrorId.ERR_SECTION_MATE_INVALID, 422)

        data, meta = validate_paginated(
            api_client.list_sections(
                make_network_admin_headers(), params={"order_id": order_b["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the refused floor must not have been created, "
            f"got total_count {meta['total_count']}"
        )
        assert data == [], f"expected no floors on the second order, got {data}"

        data_a, meta_a = validate_paginated(
            api_client.list_sections(
                make_network_admin_headers(), params={"order_id": order_a["id"]}
            )
        )
        assert meta_a["total_count"] == 2, (
            f"the first order still carries exactly its two floors, "
            f"got total_count {meta_a['total_count']}"
        )
