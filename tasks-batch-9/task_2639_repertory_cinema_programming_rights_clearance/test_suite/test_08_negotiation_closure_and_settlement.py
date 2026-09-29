"""The negotiation self-loop, minimum-run pricing at close, and settlement variants.

Negotiation alternates between the cinema and the distributor within a
four-round budget; closing prices the minimum-run shortfall through a strictly
ordered sequence; and a settlement's variant selects the inclusion set that
every downstream figure is computed from.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_booking,
    assert_booking_offer,
    assert_screening_allowance_conserved,
    assert_settlement,
    booking_version,
    cancel_showtime,
    catalogue_title,
    close_engagement,
    close_showtime_sales,
    confirm_engagement,
    draft_settlement,
    finalize_settlement,
    issue_kdm,
    lodge_cinema_round,
    lodge_counter_round,
    mark_showtime_played,
    open_engagement,
    open_showtime_sales,
    pay_for_order,
    place_showtime,
    read_booking,
    read_clearance,
    read_settlement,
    read_showtime,
    register_distributor,
    register_venue,
    sell_seats,
    set_logical_clock,
    settlement_payload,
    setup_ingested_package_world,
    setup_member_at_tier,
    setup_scheduled_screening,
    submit_settlement,
    validate_error,
    validate_paginated,
    verify_booth_playback,
)

COUNTER_TWO = {
    "proposed_house_nut_cents": 14000,
    "proposed_distributor_share_pct": 0.40,
    "proposed_min_run_days": 5,
    "proposed_guarantee_cents": 4000,
}
CINEMA_THREE = {
    "proposed_house_nut_cents": 13000,
    "proposed_distributor_share_pct": 0.36,
    "proposed_min_run_days": 4,
    "proposed_guarantee_cents": 3500,
}
COUNTER_FOUR = {
    "proposed_house_nut_cents": 13500,
    "proposed_distributor_share_pct": 0.38,
    "proposed_min_run_days": 4,
    "proposed_guarantee_cents": 3800,
}


def _opened_engagement():
    """An engagement sitting in OFFERED on its own opening round."""
    venue = register_venue()
    distributor = register_distributor()
    title = catalogue_title(distributor["id"])
    booking = open_engagement(title["id"], distributor["id"], venue["id"])
    return {"venue": venue, "distributor": distributor, "title": title,
            "booking": booking}


class TestNegotiationAlternatesAndSelfLoops:
    """Four rounds alternate CINEMA, DISTRIBUTOR, CINEMA, DISTRIBUTOR."""

    def test_distributor_counter_supersedes_the_opening_round(self):
        """Round two answers round one and moves the engagement to COUNTERED.

        PRD: "Each such round supersedes whatever round it answers: the engagement's currently `PENDING` round has its `outcome` flipped to `COUNTERED`, a new round is created with `round_index` one greater than the engagement's `round_count`, `proposed_by` set to `DISTRIBUTOR`, `outcome` `PENDING` and the four posted `proposed_*` figures, the engagement's `round_count` increases by one, and the engagement's `version` increments."

        Design: Difficulty/non_linear_state_machine/booking_counter_self_loop_negotiation_cycle
        """
        world = _opened_engagement()
        assert world["booking"]["status"] == "OFFERED"
        assert world["booking"]["round_count"] == 1

        second = lodge_counter_round(world["booking"]["id"], **COUNTER_TWO)

        assert_booking_offer(second)
        assert second["round_index"] == 2
        assert second["proposed_by"] == "DISTRIBUTOR"
        assert second["outcome"] == "PENDING"
        assert second["proposed_house_nut_cents"] == 14000

        booking = read_booking(world["booking"]["id"])
        assert booking["status"] == "COUNTERED"
        assert booking["round_count"] == 2

    def test_cinema_reply_swings_the_engagement_back_to_offered(self):
        """Round three is the mirror image and returns the engagement to OFFERED.

        PRD: "Answering a distributor counter with a fresh cinema proposal runs the mirror image, moving the engagement `COUNTERED → OFFERED` with `proposed_by` set to `CINEMA`; that operation carries no version guard, because a second sequential attempt is already refused by the from-state."

        Design: Difficulty/non_linear_state_machine/booking_counter_self_loop_negotiation_cycle
        """
        world = _opened_engagement()
        lodge_counter_round(world["booking"]["id"], **COUNTER_TWO)

        third = lodge_cinema_round(world["booking"]["id"], **CINEMA_THREE)

        assert third["round_index"] == 3
        assert third["proposed_by"] == "CINEMA"
        assert third["outcome"] == "PENDING"
        assert third["proposed_distributor_share_pct"] == 0.36

        booking = read_booking(world["booking"]["id"])
        assert booking["status"] == "OFFERED"
        assert booking["round_count"] == 3

    def test_fourth_round_is_a_self_loop_and_the_log_reads_oldest_first(
        self, programmer_headers
    ):
        """The log holds exactly four alternating, immutable rounds.

        PRD: "A round that has been superseded is immutable — its `outcome` never changes again."

        Design: Difficulty/non_linear_state_machine/booking_counter_self_loop_negotiation_cycle
        """
        world = _opened_engagement()
        lodge_counter_round(world["booking"]["id"], **COUNTER_TWO)
        lodge_cinema_round(world["booking"]["id"], **CINEMA_THREE)

        fourth = lodge_counter_round(world["booking"]["id"], **COUNTER_FOUR)
        assert fourth["round_index"] == 4
        assert fourth["proposed_by"] == "DISTRIBUTOR"

        booking = read_booking(world["booking"]["id"])
        assert booking["status"] == "COUNTERED", "COUNTERED is reached a second time"
        assert booking["round_count"] == 4

        rounds, meta = validate_paginated(
            api_client.list_booking_offers(world["booking"]["id"], programmer_headers)
        )
        assert meta["total_count"] == 4
        assert [row["round_index"] for row in rounds] == [1, 2, 3, 4]
        assert [row["proposed_by"] for row in rounds] == [
            "CINEMA", "DISTRIBUTOR", "CINEMA", "DISTRIBUTOR",
        ]
        assert [row["outcome"] for row in rounds] == [
            "COUNTERED", "COUNTERED", "COUNTERED", "PENDING",
        ]

    def test_confirmation_accepts_the_last_round_and_overwrites_the_terms(
        self, programmer_headers
    ):
        """The negotiated fourth round, not the opening ask, becomes the terms.

        PRD: "When all three hold, the round's `outcome` becomes `ACCEPTED`, its four proposed figures overwrite the engagement's `house_nut_cents`, `distributor_share_pct`, `min_run_days` and `guarantee_cents` — so the negotiated result, not the opening ask, is what settlement will later be priced from — `confirmed_by_user_id` is recorded from the acting `X-User-ID`, and the engagement moves `OFFERED → CONFIRMED` or `COUNTERED → CONFIRMED` depending on which side lodged the accepted round."

        Design: Difficulty/non_linear_state_machine/booking_counter_self_loop_negotiation_cycle
        """
        world = _opened_engagement()
        lodge_counter_round(world["booking"]["id"], **COUNTER_TWO)
        lodge_cinema_round(world["booking"]["id"], **CINEMA_THREE)
        fourth = lodge_counter_round(world["booking"]["id"], **COUNTER_FOUR)

        confirmed = confirm_engagement(world["booking"]["id"])

        assert_booking(confirmed)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["house_nut_cents"] == 13500
        assert confirmed["distributor_share_pct"] == 0.38
        assert confirmed["min_run_days"] == 4
        assert confirmed["guarantee_cents"] == 3800
        assert confirmed["round_count"] == 4

        rounds, _ = validate_paginated(
            api_client.list_booking_offers(world["booking"]["id"], programmer_headers)
        )
        accepted = [row for row in rounds if row["id"] == fourth["id"]]
        assert accepted and accepted[0]["outcome"] == "ACCEPTED"


def _three_date_engagement_world(with_orders=True, cancel_third=False):
    """Three screenings on three dates: two played, the third left unplayed.

    Nine paid seats land on the two played dates — one member order of three at
    1233 plus a walk-up four and a walk-up two at 1450 — and a two-seat walk-up
    hold is left unpaid on the third, unplayed date.
    """
    world = setup_ingested_package_world()
    world["sa"] = place_showtime(world, "2026-08-14T12:00:00Z")
    world["sb"] = place_showtime(world, "2026-08-15T12:00:00Z")
    world["sc"] = place_showtime(world, "2026-08-16T12:00:00Z")
    issue_kdm(
        world["asset"]["id"], world["venue"]["id"],
        "2026-08-14T11:00:00Z", "2026-08-14T14:30:00Z",
    )
    issue_kdm(
        world["asset"]["id"], world["venue"]["id"],
        "2026-08-15T11:00:00Z", "2026-08-15T14:30:00Z",
    )
    verify_booth_playback(world["sa"]["id"], "PASS")
    verify_booth_playback(world["sb"]["id"], "PASS")
    open_showtime_sales(world["sa"]["id"])
    open_showtime_sales(world["sb"]["id"])
    if with_orders:
        open_showtime_sales(world["sc"]["id"])
        world["member"] = setup_member_at_tier("SUPPORTER")
        first = sell_seats(
            world["sa"]["id"], 3,
            purchaser_email="ada@example.com", member_id=world["member"]["id"],
        )
        pay_for_order(first["id"])
        second = sell_seats(world["sa"]["id"], 4, purchaser_email="w1@example.com")
        pay_for_order(second["id"])
        third = sell_seats(world["sb"]["id"], 2, purchaser_email="w2@example.com")
        pay_for_order(third["id"])
        held = sell_seats(world["sc"]["id"], 2, purchaser_email="w3@example.com")
        world["orders"] = {
            "member_paid": first, "walkup_paid": second,
            "second_date_paid": third, "unpaid_hold": held,
        }
    close_showtime_sales(world["sa"]["id"])
    close_showtime_sales(world["sb"]["id"])
    set_logical_clock("2026-08-15T15:00:00Z")
    mark_showtime_played(world["sa"]["id"])
    mark_showtime_played(world["sb"]["id"])
    if cancel_third:
        cancel_showtime(world["sc"]["id"], "projector service window")
    return world


class TestMinimumRunPricingAtClose:
    """Two dates played against a four-day promise, priced in the stated order."""

    def test_close_counts_only_completed_dates_as_playing_days(self):
        """The cancelled third date contributes nothing to the day count.

        PRD: "**Step one** collects the engagement's screenings whose status is `COMPLETED`; scheduled and cancelled screenings are excluded even when they fall inside the engagement window."

        Design: Difficulty/combinatorial_formula/min_run_penalty_daily_nut_circular_resolution_order
        """
        world = _three_date_engagement_world(with_orders=False, cancel_third=True)

        booking = close_engagement(world["booking"]["id"])

        assert_booking(booking)
        assert booking["status"] == "CLOSED"
        assert booking["actual_playing_days"] == 2
        assert booking["min_run_compliant"] is False

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 2, "the cancelled date released its slot"
        assert clearance["screenings_remaining"] == 4
        assert_screening_allowance_conserved(clearance)

    def test_penalty_uses_the_prorated_daily_nut_not_the_unprorated_one(self):
        """The 0.60 floor binds, so the daily nut is 3750 and the penalty 3750.

        PRD: "Dividing the *unprorated* nut by `min_run_days` is explicitly wrong here — it agrees with the correct figure whenever the 0.60 floor is not binding and disagrees precisely when it is, so for a nut of 12500 cents against a promise of 4 days with 1 day actually played the correct daily nut is 11250 cents, not 4688."

        Design: Difficulty/combinatorial_formula/min_run_penalty_daily_nut_circular_resolution_order
        """
        world = _three_date_engagement_world(with_orders=False, cancel_third=True)

        booking = close_engagement(world["booking"]["id"])

        assert booking["min_run_penalty_cents"] == 3750
        assert booking["min_run_penalty_cents"] != 3125, (
            "3125 is the figure the unprorated daily nut would give"
        )

    def test_penalty_is_half_a_day_s_nut_for_each_day_short(self):
        """Two days short at half of a 3750-cent daily nut is 3750 cents.

        PRD: "**Step seven** sets `min_run_penalty_cents` to the shortfall in days multiplied by that daily nut multiplied by a penalty rate of 0.50 — the house forfeits half a day's nut for each day short — rounded half up to a whole cent."

        Design: Difficulty/combinatorial_formula/min_run_penalty_daily_nut_circular_resolution_order
        """
        world = _three_date_engagement_world(with_orders=False, cancel_third=True)

        booking = close_engagement(world["booking"]["id"])

        shortfall_days = booking["min_run_days"] - booking["actual_playing_days"]
        assert shortfall_days == 2
        assert booking["min_run_penalty_cents"] == int(shortfall_days * 3750 * 0.50)
        assert read_showtime(world["sc"]["id"])["status"] == "CANCELLED"


class TestSettlementVariantInclusionSets:
    """PROVISIONAL and FINAL diverge on identical stored data."""

    def test_provisional_draft_counts_scheduled_screenings_and_unpaid_holds(self):
        """Three dates and eleven seats, including the unpaid hold on the third.

        PRD: "Under `PROVISIONAL` — the box office's forward-looking estimate at close — the included screenings are the engagement's screenings whose status is `SCHEDULED` or `COMPLETED`, and the included orders are those screenings' orders whose status is `RESERVED` or `PAID`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_inclusion_set_divergence
        """
        world = _three_date_engagement_world()
        close_engagement(world["booking"]["id"])

        settlement = draft_settlement(world["booking"]["id"], "PROVISIONAL")

        assert_settlement(settlement)
        assert settlement["status"] == "DRAFT"
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["box_office_cents"] == 16949
        assert settlement["facility_fee_total_cents"] == 1650
        assert settlement["adjusted_gross_cents"] == 15299
        assert settlement["playing_days"] == 3
        assert settlement["proration_factor"] == 0.75
        assert settlement["house_nut_applied_cents"] == 9375

    def test_provisional_film_rent_sits_below_the_final_figure(self):
        """The larger provisional nut leaves less above it for the distributor.

        PRD: "The two variants genuinely diverge on identical stored data: the provisional set counts scheduled screenings and unpaid holds, so both the gross **and** the playing-day count are larger, which raises the prorated house nut and therefore *lowers* the ninety-ten film rent relative to the final figure."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_inclusion_set_divergence
        """
        world = _three_date_engagement_world()
        close_engagement(world["booking"]["id"])

        settlement = draft_settlement(world["booking"]["id"], "PROVISIONAL")

        assert settlement["film_rent_cents"] == 5332
        assert settlement["cinema_retained_cents"] == 11617
        assert settlement["min_run_penalty_cents"] == 3750

    def test_finalising_recomputes_every_figure_under_the_final_set(self):
        """Two dates and nine paid seats, with the day count falling to 0.60 proration.

        PRD: "Finalising is the `ExecutiveDirector`'s act from `SUBMITTED`: it recomputes **every** figure under the final inclusion set regardless of the variant the draft was created under, overwrites `variant` to `FINAL`, records `finalized_by_user_id` from the acting `X-User-ID`, and moves the settlement to `RECONCILED`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_inclusion_set_divergence
        """
        world = _three_date_engagement_world()
        close_engagement(world["booking"]["id"])
        settlement = draft_settlement(world["booking"]["id"], "PROVISIONAL")
        submit_settlement(settlement["id"])

        finalized = finalize_settlement(settlement["id"])

        assert_settlement(finalized)
        assert finalized["variant"] == "FINAL"
        assert finalized["status"] == "RECONCILED"
        assert finalized["box_office_cents"] == 13749
        assert finalized["facility_fee_total_cents"] == 1350
        assert finalized["adjusted_gross_cents"] == 12399
        assert finalized["playing_days"] == 2
        assert finalized["proration_factor"] == 0.60
        assert finalized["house_nut_applied_cents"] == 7500
        assert finalized["film_rent_cents"] == 4409
        assert finalized["cinema_retained_cents"] == 9340

        assert read_showtime(world["sc"]["id"])["status"] == "SCHEDULED", (
            "finalising reprices nothing on the calendar"
        )


class TestSettlementCreationReadsClosure:
    """Drafting reads the engagement's closure but not its playing-day count."""

    def test_settlement_refused_while_the_engagement_is_still_confirmed(
        self, box_office_headers
    ):
        """A CONFIRMED engagement cannot be settled, and nothing is created.

        PRD: "The engagement must be `CLOSED`, and no other settlement on the same engagement may already be in `SUBMITTED`, `RECONCILED` or `PAID`; either failure is refused with `ERR_SETTLEMENT_NOT_PERMITTED`."

        Design: Difficulty/cross_entity_state_dependency/settlement_creation_reads_booking_closure_and_diverges_from_its_day_count
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        assert read_booking(world["booking"]["id"])["status"] == "CONFIRMED"

        response = api_client.create_settlement(
            settlement_payload(
                world["booking"]["id"],
                booking_version(world["booking"]["id"]),
                "PROVISIONAL",
            ),
            box_office_headers,
        )

        validate_error(response, ApiErrorId.ERR_SETTLEMENT_NOT_PERMITTED)

        rows, meta = validate_paginated(
            api_client.list_settlements(
                box_office_headers, {"booking_id": world["booking"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_closing_with_nothing_played_prices_the_zero_day_branch(self):
        """No completed screening leaves zero playing days and a 6250-cent penalty.

        PRD: "Closing an engagement on which nothing at all played is legal and exercises the zero-day branch throughout, yielding `actual_playing_days` of 0, `min_run_compliant` false, and a penalty priced off the unprorated daily nut."

        Design: Difficulty/cross_entity_state_dependency/settlement_creation_reads_booking_closure_and_diverges_from_its_day_count
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")

        booking = close_engagement(world["booking"]["id"])

        assert booking["status"] == "CLOSED"
        assert booking["actual_playing_days"] == 0
        assert booking["min_run_compliant"] is False
        assert booking["min_run_penalty_cents"] == 6250

    def test_draft_counts_the_scheduled_date_the_engagement_would_not(self):
        """The settlement sees one playing day where the engagement recorded none.

        PRD: "`playing_days` is the number of *distinct* venue-local calendar dates among the included screenings' `start_at` instants."

        Design: Difficulty/cross_entity_state_dependency/settlement_creation_reads_booking_closure_and_diverges_from_its_day_count
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        booking = close_engagement(world["booking"]["id"])

        settlement = draft_settlement(world["booking"]["id"], "PROVISIONAL")

        assert settlement["status"] == "DRAFT"
        assert settlement["variant"] == "PROVISIONAL"
        assert settlement["playing_days"] == 1
        assert booking["actual_playing_days"] == 0, (
            "the two day counts are computed from different inclusion sets"
        )
        assert settlement["proration_factor"] == 0.60
        assert settlement["house_nut_applied_cents"] == 7500
        assert settlement["min_run_penalty_cents"] == 6250

    def test_guarantee_floors_the_film_rent_on_a_settlement_with_no_gross(self):
        """With no orders at all the distributor still takes the 3000-cent guarantee.

        PRD: "In all three cases `film_rent_cents` is the greater of that raw rent and the engagement's `guarantee_cents`: the guarantee is a **floor**, never a cap."

        Design: Difficulty/cross_entity_state_dependency/settlement_creation_reads_booking_closure_and_diverges_from_its_day_count
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        close_engagement(world["booking"]["id"])

        settlement = draft_settlement(world["booking"]["id"], "PROVISIONAL")

        assert_settlement(settlement)
        assert settlement["box_office_cents"] == 0
        assert settlement["facility_fee_total_cents"] == 0
        assert settlement["adjusted_gross_cents"] == 0
        assert settlement["film_rent_cents"] == 3000
        assert settlement["cinema_retained_cents"] == -3000
        assert read_settlement(settlement["id"])["film_rent_cents"] == 3000
