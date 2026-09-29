"""Chargeback ledger arithmetic, the escort requirement matrix and the anchor
torque floor (PRD §3.9, §3.4 and §3.8)."""

from test_helpers import (
    ANCHOR_INSPECTOR_USER_ID,
    ApiErrorId,
    api_client,
    assert_allocation_sums_exactly,
    assert_anchor_certification,
    assert_damage_claim,
    assert_network_chargeback_conserved,
    assert_transport_permit,
    adjudicate_damage_claim,
    book_set_job,
    make_inspector_headers,
    open_damage_claim,
    open_order,
    read_anchor_certification,
    read_damage_claim,
    read_hauler,
    read_order_summary,
    read_plant,
    read_set_crew,
    register_plant,
    register_set_crew,
    resubmit_anchor_certification,
    reverse_damage_claim,
    review_anchor_certification_payload,
    set_logical_clock,
    setup_claim_under_review,
    setup_leg_awaiting_escorts,
    submit_anchor_certification,
    validate_error,
    validate_success,
)


class TestChargebackLedgerCountsOnlyAdjudicatedClaims:
    """Only `ADJUDICATED` claims move a trading partner's balance."""

    def test_claim_under_review_leaves_every_balance_at_zero(self):
        """PRD §3.9: "Those balances are always recomputed in full, never
        adjusted: a plant's balance is the sum of `plant_charge_cents` over every
        claim in `ADJUDICATED` status whose order resolves to that plant; a
        hauler's balance is the sum of `hauler_charge_cents` over every claim in
        `ADJUDICATED` status naming that hauler; a set crew's balance is the sum
        of `installer_charge_cents` over every claim in `ADJUDICATED` status
        naming that crew." "Claims in `SUBMITTED`, `UNDER_REVIEW`, `DISPUTED` or
        `REVERSED` status contribute nothing to any sum."

        Design: Corner/calculations/chargeback_ledger_counts_only_adjudicated_claims
        """
        scenario = setup_claim_under_review(
            claimed_amount_cents=100000, discovered_stage="IN_TRANSIT"
        )
        claim = scenario["claim"]
        assert_damage_claim(claim)
        assert claim["status"] == "UNDER_REVIEW", (
            f"expected claim status UNDER_REVIEW, got {claim['status']}"
        )
        assert claim["approved_amount_cents"] is None, (
            f"an unadjudicated claim carries no approved_amount_cents, "
            f"got {claim['approved_amount_cents']}"
        )
        for field in (
            "plant_charge_cents",
            "hauler_charge_cents",
            "installer_charge_cents",
        ):
            assert claim[field] == 0, f"expected {field} 0, got {claim[field]}"

        assert read_plant(scenario["plant"]["id"])["chargeback_balance_cents"] == 0, (
            "a claim under review contributes nothing to the plant's balance"
        )
        assert read_hauler(scenario["hauler"]["id"])["chargeback_balance_cents"] == 0, (
            "a claim under review contributes nothing to the hauler's balance"
        )
        assert (
            read_set_crew(scenario["set_crew"]["id"])["chargeback_balance_cents"] == 0
        ), "a claim under review contributes nothing to the set crew's balance"
        assert_network_chargeback_conserved(
            read_order_summary(scenario["order"]["id"]), 0
        )

    def test_adjudicated_claim_charges_the_hauler_and_a_second_open_claim_adds_nothing(
        self,
    ):
        """PRD §3.9: "Whichever basis is chosen, the approved amount is computed
        the same way: the claimed amount less a ten percent approval haircut —
        that is, ninety percent of `claimed_amount_cents`, rounded half up to
        whole cents — and stored as `approved_amount_cents`." "Under the `STAGE`
        basis, the entire approved amount is charged to the single party that
        owns the stage at which the damage was discovered, and the other two
        charges stay at 0; evidence points are ignored completely." "Damage found
        at `PLANT_QC` belongs to the plant, damage found `IN_TRANSIT` belongs to
        the hauler, and damage found either `AT_SET` or at `FINAL_INSPECTION`
        belongs to the installer." "Claims in `SUBMITTED`, `UNDER_REVIEW`,
        `DISPUTED` or `REVERSED` status contribute nothing to any sum." And
        §3.9: "Third, threshold refresh on inclusive bounds: a hauler whose
        balance has reached five thousand dollars moves `ACTIVE → SUSPENDED`,
        and a plant whose balance has reached seven thousand five hundred
        dollars moves to `PROBATION`."

        Design: Corner/calculations/chargeback_ledger_counts_only_adjudicated_claims
        """
        scenario = setup_claim_under_review(
            claimed_amount_cents=100000, discovered_stage="IN_TRANSIT"
        )
        adjudicated = adjudicate_damage_claim(
            scenario["claim"]["id"], allocation_basis="STAGE"
        )
        assert adjudicated["status"] == "ADJUDICATED", (
            f"expected claim status ADJUDICATED, got {adjudicated['status']}"
        )
        assert adjudicated["approved_amount_cents"] == 90000, (
            f"ninety percent of 100000 must be 90000, "
            f"got {adjudicated['approved_amount_cents']}"
        )
        assert adjudicated["hauler_charge_cents"] == 90000, (
            f"damage found IN_TRANSIT charges the hauler 90000, "
            f"got {adjudicated['hauler_charge_cents']}"
        )
        assert adjudicated["plant_charge_cents"] == 0, (
            f"expected plant_charge_cents 0, got {adjudicated['plant_charge_cents']}"
        )
        assert adjudicated["installer_charge_cents"] == 0, (
            f"expected installer_charge_cents 0, "
            f"got {adjudicated['installer_charge_cents']}"
        )
        assert_allocation_sums_exactly(adjudicated)

        hauler = read_hauler(scenario["hauler"]["id"])
        assert hauler["chargeback_balance_cents"] == 90000, (
            f"expected the hauler's chargeback_balance_cents to be 90000, "
            f"got {hauler['chargeback_balance_cents']}"
        )
        assert hauler["status"] == "ACTIVE", (
            f"90000 cents is far below the five thousand dollar suspension "
            f"threshold, so the carrier stays ACTIVE, got {hauler['status']}"
        )

        second = open_damage_claim(
            scenario["order"]["id"],
            scenario["section"]["id"],
            scenario["hauler"]["id"],
            scenario["set_crew"]["id"],
            discovered_stage="IN_TRANSIT",
            claimed_amount_cents=200000,
        )
        assert second["status"] == "SUBMITTED", (
            f"a new claim opens at SUBMITTED, got {second['status']}"
        )
        assert read_hauler(scenario["hauler"]["id"])["chargeback_balance_cents"] == 90000, (
            "a claim still sitting in SUBMITTED contributes nothing to the sum"
        )

        summary = read_order_summary(scenario["order"]["id"])
        assert summary["open_claim_count"] == 1, (
            f"only the unsettled SUBMITTED claim is open, "
            f"got {summary['open_claim_count']}"
        )
        assert_network_chargeback_conserved(summary, 90000)

    def test_reversal_recomputes_every_balance_back_to_zero(self):
        """PRD §3.9: "The three charge fields are zeroed, `allocation_basis` and
        `approved_amount_cents` are cleared back to null, and every party's
        `chargeback_balance_cents` is recomputed in full — dropping the reversed
        claim from every sum, which decreases each balance by exactly what the
        adjudication had added and restores the conserved network chargeback
        total of §2.9."

        Design: Corner/calculations/chargeback_ledger_counts_only_adjudicated_claims
        """
        scenario = setup_claim_under_review(
            claimed_amount_cents=100000, discovered_stage="IN_TRANSIT"
        )
        claim_id = scenario["claim"]["id"]
        adjudicate_damage_claim(claim_id, allocation_basis="STAGE")
        reversed_claim = reverse_damage_claim(claim_id, reason_code="NEW_EVIDENCE")

        assert reversed_claim["status"] == "REVERSED", (
            f"expected claim status REVERSED, got {reversed_claim['status']}"
        )
        assert reversed_claim["approved_amount_cents"] is None, (
            f"a reversal clears approved_amount_cents back to null, "
            f"got {reversed_claim['approved_amount_cents']}"
        )
        assert reversed_claim["allocation_basis"] is None, (
            f"a reversal clears allocation_basis back to null, "
            f"got {reversed_claim['allocation_basis']}"
        )
        for field in (
            "plant_charge_cents",
            "hauler_charge_cents",
            "installer_charge_cents",
        ):
            assert reversed_claim[field] == 0, (
                f"a reversal zeroes {field}, got {reversed_claim[field]}"
            )

        hauler = read_hauler(scenario["hauler"]["id"])
        assert hauler["chargeback_balance_cents"] == 0, (
            f"the reversed claim drops out of the hauler's sum, "
            f"got {hauler['chargeback_balance_cents']}"
        )
        assert_network_chargeback_conserved(
            read_order_summary(scenario["order"]["id"]), 0
        )
        assert read_damage_claim(claim_id)["status"] == "REVERSED", (
            "the stored row must read REVERSED"
        )


class TestEscortMatrixConstants:
    """The escort matrix and the fee constants, read off a requested permit."""

    def test_three_planned_legs_demand_a_pilot_car_but_no_escorts_in_arizona(self):
        """PRD §3.4: "`escort_count_required` starts from the issuing state's base
        requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1,
        and `KS` and `CO` each contribute 2 — and then adds one escort for a
        width of at least 192 inches, one more for a width of at least 216 inches
        (so a superload-width box collects both increments), one for a travel
        height of at least thirteen and a half feet (162 inches, again
        inclusive), and one for a night move." "`pilot_car_required` is true when
        any one of three conditions holds: the `permit_class` is anything other
        than `STANDARD`, or the leg count is at least 3, or the issuing
        `state_code` is `KS` and the travel height is at least 162 inches."
        "Then forty-five dollars (4,500 cents) is added for each leg in the leg
        count in use, and seventy-five dollars (7,500 cents) for each escort the
        requirement matrix demanded in the same evaluation."

        A 168-inch by 150-inch daylight move through Arizona over three planned
        legs needs no escorts, does need a pilot car on the leg-count arm, and
        prices provisionally at 12,000 + 3 x 4,500 = 25,500 cents.

        Design: Corner/calculations/escort_matrix_constants_night_bonus_overheight_and_leg_threshold
        """
        scenario = setup_leg_awaiting_escorts(
            state_code="AZ",
            destination_state="AZ",
            declared_width_in=168,
            declared_height_in=150,
            planned_leg_count=3,
            night_move=False,
        )
        permit = scenario["permit"]
        assert_transport_permit(permit)
        assert permit["permit_class"] == "STANDARD", (
            f"168 inches of width is under the 192-inch oversize floor, "
            f"got {permit['permit_class']}"
        )
        assert permit["escort_count_required"] == 0, (
            f"Arizona contributes no base escort and no increment applies, "
            f"got {permit['escort_count_required']}"
        )
        assert permit["pilot_car_required"] is True, (
            f"three planned legs reach the leg-count arm, "
            f"got {permit['pilot_car_required']}"
        )
        assert permit["provisional_fee_cents"] == 25500, (
            f"expected provisional_fee_cents 25500, "
            f"got {permit['provisional_fee_cents']}"
        )

    def test_night_move_adds_one_escort_without_demanding_a_pilot_car(self):
        """PRD §3.4: "`escort_count_required` starts from the issuing state's base
        requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1,
        and `KS` and `CO` each contribute 2 — and then adds one escort for a
        width of at least 192 inches, one more for a width of at least 216 inches
        (so a superload-width box collects both increments), one for a travel
        height of at least thirteen and a half feet (162 inches, again
        inclusive), and one for a night move." "Those three are alternatives, not
        a conjunction — one is enough." "The subtotal begins at a base of one
        hundred and twenty dollars (12,000 cents)."

        The night bonus alone lifts the Arizona escort requirement to one, which
        prices at 12,000 + 2 x 4,500 + 7,500 = 28,500 cents, and two legs leave
        the pilot-car flag false.

        Design: Corner/calculations/escort_matrix_constants_night_bonus_overheight_and_leg_threshold
        """
        scenario = setup_leg_awaiting_escorts(
            state_code="AZ",
            destination_state="AZ",
            declared_width_in=168,
            declared_height_in=150,
            planned_leg_count=2,
            night_move=True,
        )
        permit = scenario["permit"]
        assert permit["escort_count_required"] == 1, (
            f"a night move adds exactly one escort, "
            f"got {permit['escort_count_required']}"
        )
        assert permit["pilot_car_required"] is False, (
            f"a standard-class two-leg Arizona move needs no pilot car, "
            f"got {permit['pilot_car_required']}"
        )
        assert permit["provisional_fee_cents"] == 28500, (
            f"expected provisional_fee_cents 28500, "
            f"got {permit['provisional_fee_cents']}"
        )

    def test_travel_height_of_exactly_162_inches_adds_an_escort_and_the_surcharge(self):
        """PRD §3.4: "`escort_count_required` starts from the issuing state's base
        requirement — `AZ` contributes 0, `NM`, `TX` and `OK` each contribute 1,
        and `KS` and `CO` each contribute 2 — and then adds one escort for a
        width of at least 192 inches, one more for a width of at least 216 inches
        (so a superload-width box collects both increments), one for a travel
        height of at least thirteen and a half feet (162 inches, again
        inclusive), and one for a night move." "Finally, if the height in use is
        at least 162 inches, a flat over-height surcharge of ninety dollars
        (9,000 cents) is added; otherwise nothing is added on that account."
        "The **provisional** variant runs when the permit is requested, before
        the plant has released measured dimensions and before any corridor leg
        exists; it uses the floor's `declared_width_in` and `declared_height_in`
        and the permit's `planned_leg_count`, and its result is stored as
        `provisional_fee_cents`."

        At exactly 162 inches the inclusive over-height comparison fires twice —
        once on the escort matrix and once on the surcharge — for a fee of
        12,000 + 2 x 4,500 + 7,500 + 9,000 = 37,500 cents.

        Design: Corner/calculations/escort_matrix_constants_night_bonus_overheight_and_leg_threshold
        """
        scenario = setup_leg_awaiting_escorts(
            state_code="AZ",
            destination_state="AZ",
            declared_width_in=168,
            declared_height_in=162,
            planned_leg_count=2,
            night_move=False,
        )
        permit = scenario["permit"]
        assert permit["escort_count_required"] == 1, (
            f"a travel height of exactly 162 inches adds one escort, "
            f"got {permit['escort_count_required']}"
        )
        assert permit["pilot_car_required"] is False, (
            f"an over-height standard-class two-leg Arizona move needs no pilot "
            f"car, got {permit['pilot_car_required']}"
        )
        assert permit["provisional_fee_cents"] == 37500, (
            f"expected provisional_fee_cents 37500, "
            f"got {permit['provisional_fee_cents']}"
        )
        assert permit["status"] == "REQUESTED", (
            f"the provisional variant is priced while the permit is REQUESTED, "
            f"got {permit['status']}"
        )


def _job_awaiting_anchor_package():
    """One zone I single-section order with a booked set job and its crew."""
    set_logical_clock()
    plant = register_plant(state_code="AZ")
    set_crew = register_set_crew(license_state="AZ")
    order = open_order(
        plant["id"], section_count=1, destination_state="AZ", wind_zone="I"
    )
    set_job = book_set_job(order["id"], set_crew["id"])
    return set_crew, set_job


class TestAnchorTorqueAtExactMinimum:
    """The 175 foot-pound torque floor is inclusive."""

    def test_average_torque_below_175_fails_hud_and_refuses_certification(self):
        """PRD §3.8: "`hud_pass` is true only when all three of the following
        hold: the `anchor_count` is at least that required figure, the
        `avg_torque_ft_lb` is at least one hundred and seventy-five foot-pounds,
        and the `strap_count` is at least one strap per installed anchor."
        "`state_pass` is a separate and stricter count test on the anchors alone:
        the `anchor_count` must be at least the HUD-required figure, plus four
        additional anchors when the order's `destination_state` is `KS` or `CO`,
        and plus nothing in any other destination state." "A decision of
        `CERTIFY` moves the package `SUBMITTED → CERTIFIED`, but only when both
        `hud_pass` and `state_pass` are true; if either is false the request is
        refused with `ERR_ANCHOR_COMPLIANCE_FAILED`."

        Design: Corner/calculations/anchor_torque_at_exact_minimum_passes_and_below_fails
        """
        set_crew, set_job = _job_awaiting_anchor_package()
        certification = submit_anchor_certification(
            set_job["id"],
            set_crew["id"],
            anchor_count=8,
            avg_torque_ft_lb=174.99,
            strap_count=8,
            pier_count=6,
        )
        assert_anchor_certification(certification)
        assert certification["hud_pass"] is False, (
            f"174.99 foot-pounds is below the 175 foot-pound floor, so hud_pass "
            f"must be False, got {certification['hud_pass']}"
        )
        assert certification["state_pass"] is True, (
            f"eight anchors meet the Arizona count with no extra anchors, so "
            f"state_pass must be True, got {certification['state_pass']}"
        )
        assert certification["revision_round"] == 1, (
            f"a new package opens at revision_round 1, "
            f"got {certification['revision_round']}"
        )
        assert certification["status"] == "SUBMITTED", (
            f"a new package opens at SUBMITTED, got {certification['status']}"
        )

        response = api_client.review_anchor_certification(
            certification["id"],
            review_anchor_certification_payload(decision="CERTIFY"),
            make_inspector_headers(ANCHOR_INSPECTOR_USER_ID),
        )
        validate_error(response, ApiErrorId.ERR_ANCHOR_COMPLIANCE_FAILED, 422)

        stored = read_anchor_certification(certification["id"])
        assert stored["status"] == "SUBMITTED", (
            f"a refused certification leaves the package in SUBMITTED, "
            f"got {stored['status']}"
        )

    def test_average_torque_of_exactly_175_passes_hud_and_certifies(self):
        """PRD §3.8: "Both the torque comparison and every anchor-count
        comparison are inclusive — an average torque of exactly 175 foot-pounds
        passes." "When changes have been requested, the job's `SetCrewLead`
        resubmits corrected figures on the **same** row, moving it
        `CHANGES_REQUIRED → SUBMITTED`; the resubmission overwrites
        `anchor_count`, `avg_torque_ft_lb`, `strap_count` and `pier_count` from
        the payload, increments `revision_round` by 1, and re-runs the HUD and
        state evaluation." "Three decisions exist and each writes the acting
        `X-User-ID` into `certifier_user_id`."

        Design: Corner/calculations/anchor_torque_at_exact_minimum_passes_and_below_fails
        """
        set_crew, set_job = _job_awaiting_anchor_package()
        certification = submit_anchor_certification(
            set_job["id"],
            set_crew["id"],
            anchor_count=8,
            avg_torque_ft_lb=174.99,
            strap_count=8,
            pier_count=6,
        )
        changes = validate_success(
            api_client.review_anchor_certification(
                certification["id"],
                review_anchor_certification_payload(decision="REQUEST_CHANGES"),
                make_inspector_headers(ANCHOR_INSPECTOR_USER_ID),
            ),
            200,
        )
        assert changes["status"] == "CHANGES_REQUIRED", (
            f"REQUEST_CHANGES moves the package to CHANGES_REQUIRED, "
            f"got {changes['status']}"
        )

        resubmitted = resubmit_anchor_certification(
            certification["id"],
            set_crew["id"],
            anchor_count=8,
            avg_torque_ft_lb=175,
            strap_count=8,
            pier_count=6,
        )
        assert resubmitted["avg_torque_ft_lb"] == 175, (
            f"the resubmission overwrites avg_torque_ft_lb with 175, "
            f"got {resubmitted['avg_torque_ft_lb']}"
        )
        assert resubmitted["hud_pass"] is True, (
            f"exactly 175 foot-pounds passes the inclusive torque comparison, "
            f"got hud_pass {resubmitted['hud_pass']}"
        )
        assert resubmitted["state_pass"] is True, (
            f"expected state_pass True, got {resubmitted['state_pass']}"
        )
        assert resubmitted["revision_round"] == 2, (
            f"the resubmission increments revision_round to 2, "
            f"got {resubmitted['revision_round']}"
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"the resubmission returns the package to SUBMITTED, "
            f"got {resubmitted['status']}"
        )

        certified = validate_success(
            api_client.review_anchor_certification(
                certification["id"],
                review_anchor_certification_payload(decision="CERTIFY"),
                make_inspector_headers(ANCHOR_INSPECTOR_USER_ID),
            ),
            200,
        )
        assert certified["status"] == "CERTIFIED", (
            f"both verdicts now pass, so CERTIFY must certify the package, "
            f"got {certified['status']}"
        )
        assert certified["certifier_user_id"] == ANCHOR_INSPECTOR_USER_ID, (
            f"expected certifier_user_id {ANCHOR_INSPECTOR_USER_ID}, "
            f"got {certified['certifier_user_id']}"
        )
