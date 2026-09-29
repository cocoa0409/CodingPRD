"""Conflict scoring arithmetic and the honoraria waterfall."""
from test_helpers import (
    ApiErrorId,
    CASE_MANAGER,
    admit_panelist,
    api_client,
    assert_appointment,
    assert_conflict_factors_sorted,
    assert_honoraria_waterfall,
    fund_case_to_assessment,
    nominate_seat,
    read_appointment,
    read_case,
    read_panelist,
    replace_seat,
    screen_seat,
    setup_responded_case,
    setup_three_member_panel,
    validate_error,
    validate_paginated,
    waiver_payload,
)


def _single_member_case_ready_for_a_seat(**kwargs):
    bundle = setup_responded_case(**kwargs)
    fund_case_to_assessment(bundle["case"]["id"])
    return bundle


class TestConflictScoreCarveOut:
    def test_financial_interest_never_ages_away_and_disqualifies_at_sixty(self):
        """PRD §3.6: "The financial interest is deliberately carved out before
        decay: its 60 points are added back at full value after the decayable
        subtotal has been decayed and rounded half up to two decimals, so a
        financial interest never ages away."
        PRD §3.6: "A score at or above the disqualification threshold of 60 sends
        the seat straight to `CONFLICTED`, taking no load and requiring no further
        step — exactly 60.00 disqualifies."

        Design: Difficulty/combinatorial_formula/conflict_score_financial_carveout_beats_a_larger_but_decayable_disclosure
        """
        bundle = _single_member_case_ready_for_a_seat(
            iana_id="IANA-4004", domain_name="carveout.example", legal_name="Carve SA",
        )
        panelist = admit_panelist(full_name="Anna Bauer", nationality_code="DE")
        seat = nominate_seat(bundle["case"]["id"], "SOLE", panelist["id"])
        screened = screen_seat(
            seat["id"], panelist["id"],
            disclosed_financial_interest=True,
            months_since_last_contact=36,
        )
        assert_appointment(screened)
        assert float(screened["conflict_score"]) == 60.00
        assert screened["status"] == "CONFLICTED"
        assert screened["conflict_factors"] == ["FINANCIAL_INTEREST"]
        assert screened["accepted_at"] is None
        assert read_panelist(panelist["id"])["active_case_load"] == 0
        refused = api_client.record_waiver(seat["id"], waiver_payload(), CASE_MANAGER)
        validate_error(refused, ApiErrorId.ERR_CONFLICT_NOT_WAIVABLE.value, 409)
        assert read_case(bundle["case"]["id"])["status"] == "PANEL_APPOINTMENT"

    def test_two_larger_disclosures_decay_below_the_waiver_threshold_and_seat_the_neutral(self):
        """PRD §3.6: "A prior representation contributes 45 points, a same-firm
        relationship 35 points, and prior appointments 8 points each, capped at 24
        points no matter how many are disclosed."
        PRD §3.6: "The decay factor is 1.00 when `months_since_last_contact` is
        null or omitted; otherwise it is one minus the disclosed months divided by
        the 24-month horizon, with a floor of 0.25 — so 12 months yields 0.50, 24
        months or more yields the floor 0.25, and the factor never falls below it."

        Design: Difficulty/combinatorial_formula/conflict_score_financial_carveout_beats_a_larger_but_decayable_disclosure
        """
        bundle = _single_member_case_ready_for_a_seat(
            iana_id="IANA-4004", domain_name="carveout.example", legal_name="Carve SA",
        )
        case_id = bundle["case"]["id"]
        first = admit_panelist(full_name="Anna Bauer", nationality_code="DE")
        second = admit_panelist(
            full_name="Marco Rossi", nationality_code="IT", firm_name="Rossi & Partners",
        )
        seat = nominate_seat(case_id, "SOLE", first["id"])
        screen_seat(
            seat["id"], first["id"],
            disclosed_financial_interest=True, months_since_last_contact=36,
        )
        predecessor = replace_seat(seat["id"], replacement_panelist_id=second["id"])
        assert predecessor["status"] == "REPLACED"
        successor_id = predecessor["replaced_by_appointment_id"]
        screened = screen_seat(
            successor_id, second["id"],
            disclosed_prior_representation=True,
            disclosed_same_firm=True,
            months_since_last_contact=36,
        )
        # (45 + 35) decayed by the 0.25 floor is 20.00, below the waiver threshold.
        assert float(screened["conflict_score"]) == 20.00
        assert screened["status"] == "ACCEPTED"
        assert screened["conflict_factors"] == ["PRIOR_REPRESENTATION", "SAME_FIRM"]
        assert_conflict_factors_sorted(screened)
        assert read_panelist(second["id"])["active_case_load"] == 1
        assert read_panelist(first["id"])["active_case_load"] == 0
        case = read_case(case_id)
        assert case["status"] == "PANEL_CONSTITUTED"
        assert read_appointment(successor_id)["honoraria_cents"] == 105000


class TestPriorAppointmentCapAndDecay:
    def test_prior_appointment_points_saturate_at_the_cap(self):
        """PRD §3.6: "A neutral disclosing a prior representation and three prior
        appointments with the last contact 12 months ago scores 45 plus 24,
        decayed by 0.50, for 34.50; the same disclosures with a financial interest
        added score 34.50 plus 60, or 94.50; a financial interest alone always
        scores exactly 60.00 whatever the elapsed months."
        PRD §3.6: "A score at or above the waiver threshold of 30 but below 60
        sends the seat to `WAIVER_PENDING`, again taking no load, and the seat
        waits on the parties' consent — exactly 30.00 requires a waiver."

        Design: Difficulty/combinatorial_formula/conflict_score_prior_appointment_cap_saturates_then_decay_halves_it
        """
        bundle = _single_member_case_ready_for_a_seat(
            iana_id="IANA-6006", domain_name="capdecay.example", legal_name="Cap Decay AG",
        )
        case_id = bundle["case"]["id"]
        first = admit_panelist(full_name="Anna Bauer", nationality_code="DE")
        second = admit_panelist(full_name="Marco Rossi", nationality_code="IT")
        seat = nominate_seat(case_id, "SOLE", first["id"])
        five = screen_seat(
            seat["id"], first["id"],
            disclosed_prior_representation=True,
            prior_appointments_with_complainant=5,
            months_since_last_contact=12,
        )
        assert float(five["conflict_score"]) == 34.50
        assert five["status"] == "WAIVER_PENDING"
        assert five["conflict_factors"] == ["PRIOR_APPOINTMENTS", "PRIOR_REPRESENTATION"]
        assert read_panelist(first["id"])["active_case_load"] == 0

        predecessor = replace_seat(seat["id"], replacement_panelist_id=second["id"])
        three = screen_seat(
            predecessor["replaced_by_appointment_id"], second["id"],
            disclosed_prior_representation=True,
            prior_appointments_with_complainant=3,
            months_since_last_contact=12,
        )
        assert float(three["conflict_score"]) == 34.50, (
            "five prior appointments and three both saturate the 24-point cap"
        )
        assert three["status"] == "WAIVER_PENDING"

    def test_a_seat_abandoned_before_acceptance_is_declined_and_the_undecayed_pair_seats(self):
        """PRD §3.6: "The predecessor's fate depends on where it stood: a seat in
        `NOMINATED` or `WAIVER_PENDING` becomes `DECLINED`, while a seat in
        `CONFLICTED` or `ACCEPTED` becomes `REPLACED`."
        PRD §3.6: "Anything below 30 seats the neutral directly: the
        engagement-window and capacity checks are re-run at this moment against
        the same half-open window and the same closed blackout interval, and if
        they pass, the seat moves to `ACCEPTED` with `accepted_at` stamped from
        the clock, `decision_due_at` set 14 days later, and the neutral's
        `active_case_load` incremented by one."

        Design: Difficulty/combinatorial_formula/conflict_score_prior_appointment_cap_saturates_then_decay_halves_it
        """
        bundle = _single_member_case_ready_for_a_seat(
            iana_id="IANA-6006", domain_name="capdecay.example", legal_name="Cap Decay AG",
        )
        case_id = bundle["case"]["id"]
        first = admit_panelist(full_name="Anna Bauer", nationality_code="DE")
        second = admit_panelist(full_name="Marco Rossi", nationality_code="IT")
        third = admit_panelist(full_name="Piet de Vries", nationality_code="NL")
        seat = nominate_seat(case_id, "SOLE", first["id"])
        screen_seat(
            seat["id"], first["id"], disclosed_prior_representation=True,
            prior_appointments_with_complainant=5, months_since_last_contact=12,
        )
        first_predecessor = replace_seat(seat["id"], replacement_panelist_id=second["id"])
        assert first_predecessor["status"] == "DECLINED", (
            "a seat replaced out of WAIVER_PENDING has never been accepted"
        )
        second_seat_id = first_predecessor["replaced_by_appointment_id"]
        screen_seat(
            second_seat_id, second["id"], disclosed_prior_representation=True,
            prior_appointments_with_complainant=3, months_since_last_contact=12,
        )
        second_predecessor = replace_seat(second_seat_id, replacement_panelist_id=third["id"])
        assert second_predecessor["status"] == "DECLINED"
        final_seat_id = second_predecessor["replaced_by_appointment_id"]
        seated = screen_seat(
            final_seat_id, third["id"], disclosed_prior_representation=True,
            prior_appointments_with_complainant=0, months_since_last_contact=12,
        )
        assert float(seated["conflict_score"]) == 22.50
        assert seated["status"] == "ACCEPTED"
        assert seated["conflict_factors"] == ["PRIOR_REPRESENTATION"]
        assert seated["accepted_at"] == "2026-08-01T00:00:00.000Z"
        assert seated["decision_due_at"] == "2026-08-15T00:00:00.000Z"
        assert read_panelist(third["id"])["active_case_load"] == 1
        assert read_panelist(first["id"])["active_case_load"] == 0
        assert read_panelist(second["id"])["active_case_load"] == 0
        assert read_case(case_id)["status"] == "PANEL_CONSTITUTED"


class TestHonorariaWaterfall:
    def test_expedited_three_member_case_prices_an_odd_honoraria_pool(self):
        """PRD §3.5: "`honoraria_pool_cents` is recomputed as 70 percent of the
        new assessment, rounded half up."
        PRD §3.2: "The expedited surcharge, applied only when
        `expedited_requested` is true, is 12.5 percent of the base administrative
        fee alone, rounded half up to a whole cent — it is never charged on the
        three-member supplement, which is why the surcharge is a constant 18750
        cents whenever expedited handling was bought, at either seat count."

        Design: Difficulty/combinatorial_formula/honoraria_floor_each_seat_then_remainder_to_presiding_on_odd_pool
        """
        bundle = setup_three_member_panel(
            expedited_requested=True, iana_id="IANA-5005",
            domain_name="honoraria.example", legal_name="Odd Pool Ltd",
        )
        case = read_case(bundle["case"]["id"])
        assert case["expedited_requested"] is True
        assert case["assessed_fee_cents"] == 418750
        assert case["complainant_share_cents"] == 293750
        assert case["respondent_share_cents"] == 125000
        assert case["honoraria_pool_cents"] == 293125
        assert case["paid_cents"] == 418750
        assert case["status"] == "PANEL_CONSTITUTED"

    def test_rounding_remainder_on_an_odd_pool_is_handed_to_the_presiding_seat(self):
        """PRD §3.6: "On a three-member panel the `PRESIDING` seat is entitled to
        40 percent and each co-panelist to 30 percent; each seat's raw entitlement
        is floored to a whole cent independently, and then the entire rounding
        remainder is handed to the `PRESIDING` seat so that the three
        `honoraria_cents` values sum to the pool exactly."

        Design: Difficulty/combinatorial_formula/honoraria_floor_each_seat_then_remainder_to_presiding_on_odd_pool
        """
        bundle = setup_three_member_panel(
            expedited_requested=True, iana_id="IANA-5005",
            domain_name="honoraria.example", legal_name="Odd Pool Ltd",
        )
        appointments = [read_appointment(a["id"]) for a in bundle["appointments"]]
        by_seat = {a["seat"]: a for a in appointments}
        assert by_seat["PRESIDING"]["honoraria_cents"] == 117251, (
            "the presiding seat takes the floored 40 percent plus the whole remainder"
        )
        assert by_seat["CO_PANELIST_1"]["honoraria_cents"] == 87937
        assert by_seat["CO_PANELIST_2"]["honoraria_cents"] == 87937
        assert_honoraria_waterfall(appointments, 293125)
        rows, meta = validate_paginated(
            api_client.list_appointments(
                CASE_MANAGER,
                params={"case_id": bundle["case"]["id"], "status": "ACCEPTED",
                        "limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 3
        assert len(rows) == 3
