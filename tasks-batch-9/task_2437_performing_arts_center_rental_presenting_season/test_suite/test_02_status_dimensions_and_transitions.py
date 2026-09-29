"""The three independent engagement dimensions and the child state machines:
initial states, supersede cascades, terminal lock-down and cross-dimension
preconditions."""

from test_helpers import (
    api_client,
    add_price_tier,
    assess_risk,
    book_presented_engagement,
    book_rental_engagement,
    call_crew,
    clear_rider,
    counter_round,
    engagement_version,
    make_artist_representative_headers,
    make_rental_client_contact_headers,
    make_technical_director_headers,
    open_negotiation_round,
    read_engagement,
    register_artist,
    register_hall,
    register_rental_client,
    register_union_department,
    review_rider,
    set_clock,
    submit_rider,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["center_admin_headers"]
DIRECTOR = TEST_USERS["programming_director_headers"]
RENTAL_MANAGER = TEST_USERS["rental_manager_headers"]
TECH_DIRECTOR = TEST_USERS["technical_director_headers"]
BOX_OFFICE = TEST_USERS["box_office_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestInitialStates:

    def test_engagement_and_child_rows_start_in_their_declared_states(self):
        """A booking, its first negotiation round, its rider, its labor call and
        its first price tier are each born in the state the specification
        declares, before any transition endpoint is called.

        PRD: "A new rider is created in `SUBMITTED` with an empty
        `capability_gaps` array, `additional_equipment_cost_cents` at zero and
        `reviewed_by_user_id` null."

        Design: Corner/state_machines/engagement_and_child_entities_start_in_declared_initial_states
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        department = register_union_department(department="ELECTRICS",
                                              roster_size=20,
                                              straight_hourly_rate_cents=5_000)
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")

        assert engagement["lifecycle_status"] == "DRAFT"
        assert engagement["financial_clearance"] == "UNASSESSED"
        assert engagement["ticketing_status"] == "TICKETING_UNSET"

        negotiation = open_negotiation_round(engagement["id"], 300_000, 0.1,
                                             engagement["version"])
        assert negotiation["status"] == "OFFERED"
        assert negotiation["round_index"] == 1
        assert negotiation["revision_count"] == 0
        assert negotiation.get("counter_fee_cents") is None
        assert negotiation.get("counter_artist_share_pct") is None
        assert negotiation.get("accepted_fee_cents") is None
        assert negotiation.get("accepted_by_user_id") is None

        rider = submit_rider(engagement["id"],
                             make_artist_representative_headers(artist["id"]))
        assert rider["review_status"] == "SUBMITTED"
        assert rider["capability_gaps"] == []
        assert rider["additional_equipment_cost_cents"] == 0
        assert rider.get("reviewed_by_user_id") is None

        call = call_crew(engagement["id"], department["id"], crew_size=4,
                         call_start_utc="2026-10-10T08:00:00Z",
                         call_end_utc="2026-10-10T12:00:00Z")
        assert call["status"] == "ESTIMATED"
        assert call.get("actual_hours") is None
        assert call.get("meal_break_taken") is None
        assert call["actual_cost_cents"] == 0

        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=400, base_price_cents=8_000,
                              price_ceiling_cents=10_000,
                              dynamic_pricing_enabled=False,
                              subscription_eligible=True)
        assert tier["status"] == "ACTIVE"
        assert tier["sold_qty"] == 0
        assert tier["subscription_held_qty"] == 0
        assert tier["available_qty"] == 400
        assert tier["gross_cents"] == 0
        assert tier["subscription_revenue_cents"] == 0


class TestNegotiationRoundCascades:

    def test_a_new_round_supersedes_the_standing_round(self):
        """Opening a second round writes to the first round's row — moving it to
        the terminal superseded state and bumping that row's own version — while
        the engagement counts rounds ever opened.

        PRD: "every earlier round of the same engagement whose `status` is
        `OFFERED` or `COUNTERED` is moved to the terminal `SUPERSEDED` state,
        and each superseded round has its own `version` incremented by 1."

        Design: Corner/state_machines/new_negotiation_round_supersedes_the_open_round
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        first = open_negotiation_round(engagement["id"], 300_000, 0.1,
                                       engagement["version"])
        version_after_first = engagement_version(engagement["id"])

        second = open_negotiation_round(engagement["id"], 350_000, 0.12,
                                        version_after_first)
        assert second["status"] == "OFFERED"
        assert second["round_index"] == 2
        assert second["offered_fee_cents"] == 350_000
        assert second["offered_artist_share_pct"] == 0.12
        assert second["revision_count"] == 0

        rounds, meta = validate_paginated(
            api_client.list_fee_negotiations(engagement["id"], FINANCE))
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rounds}
        superseded = by_id[first["id"]]
        assert superseded["status"] == "SUPERSEDED"
        assert superseded["version"] == 2
        assert superseded["offered_fee_cents"] == 300_000
        assert superseded.get("accepted_fee_cents") is None
        assert superseded.get("accepted_share_pct") is None

        after = read_engagement(engagement["id"])
        assert after["negotiation_round_count"] == 2
        assert after["version"] == version_after_first + 1
        assert after["negotiated_fee_cents"] == 0

    def test_accepting_from_countered_locks_the_counter_terms(self):
        """Acceptance from the countered state freezes the agency's counter, not
        the center's standing offer, and the resulting negative projection does
        not escalate a clearance that was never granted.

        PRD: "Accepting from `COUNTERED` sets `accepted_fee_cents` to the
        round's `counter_fee_cents` and `accepted_share_pct` to its
        `counter_artist_share_pct`."

        Design: Corner/state_machines/accept_from_countered_locks_the_counter_terms
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        negotiation = open_negotiation_round(engagement["id"], 300_000, 0.1,
                                            engagement["version"])
        counter_round(negotiation["id"], artist["id"], 400_000, 0.15)

        accepted = validate_success(
            api_client.accept_fee_negotiation(negotiation["id"], DIRECTOR))

        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_fee_cents"] == 400_000
        assert accepted["accepted_share_pct"] == 0.15
        assert accepted["accepted_by_user_id"] == DIRECTOR["X-User-ID"]
        assert accepted["offered_fee_cents"] == 300_000

        after = read_engagement(engagement["id"])
        assert after["negotiated_fee_cents"] == 400_000
        assert after["artist_share_pct"] == 0.15
        assert after["fee_accepted_by_user_id"] == DIRECTOR["X-User-ID"]
        # No price tier exists, so the projection has no gross to work with:
        # 0 - (400,000 guarantee + 250,000 marketing allowance).
        assert after["projected_margin_cents"] == -650_000
        assert after["financial_clearance"] == "UNASSESSED"
        assert after["risk_tier"] == "LOW"
        assert after["version"] == 3

    def test_countering_or_accepting_a_superseded_round_is_refused(self):
        """The round the supersede cascade closed is locked against both of the
        transitions its live siblings still admit.

        PRD: "Countering is permitted only while the round is `OFFERED` —
        otherwise `ERR_NEGOTIATION_NOT_OPEN`"

        Design: Corner/state_machines/counter_on_superseded_round_is_rejected
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        first = open_negotiation_round(engagement["id"], 300_000, 0.1,
                                       engagement["version"])
        version_after_first = engagement_version(engagement["id"])
        second = open_negotiation_round(engagement["id"], 350_000, 0.12,
                                        version_after_first)

        agency = make_artist_representative_headers(artist["id"])
        validate_error(api_client.counter_fee_negotiation(
            first["id"],
            {"counter_fee_cents": 320_000, "counter_artist_share_pct": 0.11},
            agency), "ERR_NEGOTIATION_NOT_OPEN", 409)
        validate_error(api_client.accept_fee_negotiation(first["id"], agency),
                       "ERR_NEGOTIATION_NOT_OPEN", 409)

        rounds, _ = validate_paginated(
            api_client.list_fee_negotiations(engagement["id"], DIRECTOR))
        by_id = {row["id"]: row for row in rounds}
        assert by_id[first["id"]]["status"] == "SUPERSEDED"
        assert by_id[first["id"]].get("counter_fee_cents") is None
        assert by_id[first["id"]].get("accepted_fee_cents") is None
        assert by_id[first["id"]]["version"] == 2
        assert by_id[second["id"]]["status"] == "OFFERED"

        after = read_engagement(engagement["id"])
        assert after["negotiated_fee_cents"] == 0
        assert after["version"] == version_after_first + 1

    def test_accepting_a_fee_that_turns_the_margin_negative_escalates(self):
        """Accepting a guarantee that drives the projection negative revokes an
        already-granted clearance and thereby blocks a confirmation whose every
        other precondition holds.

        PRD: "If that recomputed margin is negative while the clearance
        dimension currently reads `CLEARED`, the clearance flips `CLEARED →
        ESCALATED` and `risk_tier` is set to `HIGH`."

        Design: Corner/state_machines/accepting_fee_that_turns_margin_negative_escalates_a_cleared_engagement
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        add_price_tier(engagement["id"], tier_name="ORCH", seats_allocated=100,
                       base_price_cents=10_000, price_ceiling_cents=13_000,
                       dynamic_pricing_enabled=False,
                       subscription_eligible=False)
        assessed = assess_risk(engagement["id"], engagement["version"])
        assert assessed["risk_score"] == 10
        assert assessed["financial_clearance"] == "CLEARED"
        assert assessed["projected_gross_cents"] == 800_000
        assert assessed["projected_margin_cents"] == 550_000

        negotiation = open_negotiation_round(engagement["id"], 700_000, 0.1,
                                            assessed["version"])
        agency = make_artist_representative_headers(artist["id"])
        rider = submit_rider(engagement["id"], agency)
        review_rider(rider["id"])
        clear_rider(rider["id"])

        accepted = validate_success(
            api_client.accept_fee_negotiation(negotiation["id"], agency))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["accepted_fee_cents"] == 700_000

        after = read_engagement(engagement["id"])
        # 800,000 gross less the 700,000 guarantee and the 250,000 allowance.
        assert after["projected_margin_cents"] == -150_000
        assert after["financial_clearance"] == "ESCALATED"
        assert after["risk_tier"] == "HIGH"
        assert after["risk_score"] == 10
        assert after["lifecycle_status"] == "DRAFT"
        assert validate_success(api_client.get_tech_rider(
            rider["id"], TECH_DIRECTOR))["review_status"] == "CLEARED"

        validate_error(api_client.confirm_engagement(engagement["id"], DIRECTOR),
                       "ERR_CLEARANCE_REQUIRED", 422)
        final = read_engagement(engagement["id"])
        assert final["lifecycle_status"] == "DRAFT"
        # The refused confirmation advances no dimension; the ticketing dimension
        # is still where the first tier left it (PRD 3.6: "Adding the first tier
        # to an engagement whose ticketing dimension still reads
        # `TICKETING_UNSET` moves that dimension `TICKETING_UNSET →
        # TIERS_DRAFT`").
        assert final["ticketing_status"] == "TIERS_DRAFT"


class TestClearanceReassessment:

    def test_blocked_clearance_returns_to_cleared_once_tiers_exist(self):
        """A prohibitive first assessment blocks the booking; drafting a tier
        collapses the fee-exposure term and a re-assessment moves the clearance
        dimension out of the blocked state.

        PRD: "A `BLOCKED` engagement is not condemned forever: a later
        re-assessment whose tier comes back `LOW` or `MODERATE` moves the
        clearance `BLOCKED → CLEARED`"

        Design: Corner/state_machines/blocked_clearance_flips_to_cleared_after_tiers_raise_projected_gross
        """
        space = register_hall()
        artist = register_artist(
            legal_name="Tidewater Ensemble", agency_name="Harborlight Artists",
            guarantee_floor_cents=1_000_000, historical_sell_through_pct=0.8,
            routing_window_start_utc="2026-08-05T00:00:00Z",
            routing_window_end_utc="2026-08-20T00:00:00Z",
            min_days_between_engagements=0)
        engagement = book_presented_engagement(
            space["id"], artist["id"], title="Tidewater Ensemble Gala",
            load_in_start_utc="2026-08-09T08:00:00Z",
            performance_start_utc="2026-08-10T19:00:00Z",
            performance_end_utc="2026-08-10T22:00:00Z",
            load_out_end_utc="2026-08-11T02:00:00Z")
        open_negotiation_round(engagement["id"], 2_000_000, 0.1,
                               engagement["version"])

        blocked = assess_risk(engagement["id"],
                              engagement_version(engagement["id"]))
        assert blocked["risk_score"] == 82
        assert blocked["risk_tier"] == "PROHIBITIVE"
        assert blocked["financial_clearance"] == "BLOCKED"
        assert blocked["projected_gross_cents"] == 0
        assert blocked["projected_margin_cents"] == -2_250_000

        add_price_tier(engagement["id"], tier_name="ORCH",
                       seats_allocated=1_000, base_price_cents=20_000,
                       price_ceiling_cents=25_000,
                       dynamic_pricing_enabled=False,
                       subscription_eligible=False)

        rescored = assess_risk(engagement["id"], blocked["version"])
        assert rescored["risk_score"] == 42
        assert rescored["risk_tier"] == "MODERATE"
        assert rescored["financial_clearance"] == "CLEARED"
        assert rescored["projected_gross_cents"] == 16_000_000
        assert rescored["projected_margin_cents"] == 13_750_000
        assert rescored["version"] == blocked["version"] + 1


class TestCrossDimensionPreconditions:

    def test_settlement_before_curtain_down_or_before_confirmation(self):
        """Opening a settlement needs both a confirmed booking and a clock at or
        past curtain-down; falsifying either conjunct is refused and no draft
        settlement is left behind.

        PRD: "if either fails — the clock is still before curtain-down, or the
        booking is not `CONFIRMED` — the request is refused with
        `ERR_PERFORMANCE_NOT_COMPLETE`."

        Design: Corner/state_machines/settlement_opened_before_curtain_down_is_rejected
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        engagement = book_rental_engagement(space["id"], client["id"],
                                            title="Early Settlement Probe")

        validate_error(api_client.open_settlement(engagement["id"], FINANCE),
                       "ERR_PERFORMANCE_NOT_COMPLETE", 409)

        clock = set_clock("2026-10-03T00:00:00Z")
        assert clock["current_utc"] == "2026-10-03T00:00:00Z"

        validate_error(api_client.open_settlement(engagement["id"], FINANCE),
                       "ERR_PERFORMANCE_NOT_COMPLETE", 409)

        _, meta = validate_paginated(api_client.list_engagement_settlements(
            engagement["id"], FINANCE))
        assert meta["total_count"] == 0

        after = read_engagement(engagement["id"])
        assert after["lifecycle_status"] == "DRAFT"
        assert after["ticketing_status"] == "TICKETING_UNSET"

    def test_going_on_sale_before_confirmation_is_refused(self):
        """The ticketing dimension is in a legal source state, so only the
        cross-dimension booking precondition can reject the on-sale call.

        PRD: "It is admitted only from `TIERS_DRAFT` — any other ticketing state
        is refused with `ERR_TICKETING_NOT_ON_SALE` — and only while the booking
        dimension reads `CONFIRMED`, otherwise `ERR_ENGAGEMENT_NOT_CONFIRMED`."

        Design: Corner/state_machines/on_sale_before_confirmation_is_rejected
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=400, base_price_cents=8_000,
                              price_ceiling_cents=10_000,
                              dynamic_pricing_enabled=False,
                              subscription_eligible=True)

        validate_error(
            api_client.put_engagement_on_sale(engagement["id"], BOX_OFFICE),
            "ERR_ENGAGEMENT_NOT_CONFIRMED", 409)

        after = read_engagement(engagement["id"])
        assert after["ticketing_status"] == "TIERS_DRAFT"
        assert after["lifecycle_status"] == "DRAFT"
        assert after["version"] == 1
        assert after["projected_gross_cents"] == 0

        reread = validate_success(api_client.get_price_tier(tier["id"],
                                                            BOX_OFFICE))
        assert reread["status"] == "ACTIVE"
        assert reread["sold_qty"] == 0
        assert reread["available_qty"] == 400

    def test_ticketing_advances_without_touching_clearance_or_version(self):
        """Drafting the first tier advances only the ticketing dimension: the
        booking and clearance dimensions, the risk figures and the engagement's
        version counter are all left where they stood.

        PRD: "adding tiers does not increment `Engagement.version`, and neither
        does the dimension change it triggers."

        Design: Corner/state_machines/ticketing_dimension_advances_while_clearance_stays_unassessed
        """
        space = register_hall()
        artist = register_artist(legal_name="Cadence Quartet")
        engagement = book_presented_engagement(space["id"], artist["id"],
                                               title="Cadence Quartet Recital")
        version_before = engagement["version"]

        tier = add_price_tier(engagement["id"], tier_name="ORCH",
                              seats_allocated=400, base_price_cents=8_000,
                              price_ceiling_cents=10_000,
                              dynamic_pricing_enabled=True,
                              subscription_eligible=True)
        assert tier["version"] == 1

        after = read_engagement(engagement["id"], BOX_OFFICE)
        assert after["lifecycle_status"] == "DRAFT"
        assert after["financial_clearance"] == "UNASSESSED"
        assert after["ticketing_status"] == "TIERS_DRAFT"
        assert after["risk_score"] == 0
        assert after["risk_tier"] == "LOW"
        assert after["projected_gross_cents"] == 0
        assert after["version"] == version_before

    def test_reporting_hours_on_a_draft_engagement_is_refused(self):
        """Estimating a call while the booking is still draft is legal, but the
        cross-entity guard on the call's own transition refuses the hours
        report.

        PRD: "Reporting is permitted only while the call reads `ESTIMATED` —
        otherwise `ERR_LABOR_CALL_INVALID_STATE` — and only while the
        engagement's booking dimension reads `CONFIRMED` or `PERFORMED`,
        otherwise `ERR_ENGAGEMENT_NOT_CONFIRMED`."

        Design: Corner/state_machines/labor_hours_reported_on_draft_engagement_is_rejected
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        department = register_union_department(department="STAGEHANDS",
                                              roster_size=20,
                                              straight_hourly_rate_cents=5_000)
        engagement = book_rental_engagement(space["id"], client["id"],
                                            title="Guarded Hours Probe")
        call = call_crew(engagement["id"], department["id"], crew_size=4,
                         call_start_utc="2026-10-01T08:00:00Z",
                         call_end_utc="2026-10-01T12:00:00Z")
        # Four scheduled hours at the four-hour call minimum: 4 x 5,000 cents
        # per crew member, times a crew of four.
        assert call["estimated_cost_cents"] == 80_000

        validate_error(api_client.report_labor_hours(
            call["id"], {"actual_hours": 4, "meal_break_taken": True},
            TECH_DIRECTOR), "ERR_ENGAGEMENT_NOT_CONFIRMED", 409)

        calls, _ = validate_paginated(api_client.list_engagement_labor_calls(
            engagement["id"], TECH_DIRECTOR))
        reread = next(row for row in calls if row["id"] == call["id"])
        assert reread["status"] == "ESTIMATED"
        assert reread.get("actual_hours") is None
        assert reread.get("meal_break_taken") is None
        assert reread["actual_cost_cents"] == 0
        assert reread["estimated_cost_cents"] == 80_000
        assert reread["version"] == 1
        assert read_engagement(engagement["id"])[
            "labor_estimate_total_cents"] == 80_000


class TestRiderReviewIdempotency:

    def test_reviewing_an_already_reviewed_rider_is_refused(self):
        """Replaying the review call is a hard conflict with zero drift: the
        reviewer of record and the rider's version both stand.

        PRD: "Review is the `TechnicalDirector`'s act, and it is available only
        while the rider reads `SUBMITTED`; reviewing an already-reviewed rider
        is refused with `ERR_RIDER_INVALID_STATE`."

        Design: Corner/state_machines/second_review_on_a_reviewed_rider_is_rejected
        """
        space = register_hall()
        client = register_rental_client(org_name="Meridian Dance Company")
        engagement = book_rental_engagement(space["id"], client["id"],
                                            title="Rider Replay Probe")
        rider = submit_rider(engagement["id"],
                             make_rental_client_contact_headers(client["id"]),
                             submitted_rigging_kg=1_000,
                             requested_power_amps=200,
                             requested_dmx_universes=2,
                             requires_orchestra_pit=False)
        first_reviewer = make_technical_director_headers("user-td-1")
        reviewed = review_rider(rider["id"], first_reviewer)
        assert reviewed["review_status"] == "CAPABLE"
        assert reviewed["version"] == 2

        validate_error(api_client.review_tech_rider(
            rider["id"], make_technical_director_headers("user-td-2")),
            "ERR_RIDER_INVALID_STATE", 409)

        reread = validate_success(
            api_client.get_tech_rider(rider["id"], TECH_DIRECTOR))
        assert reread["review_status"] == "CAPABLE"
        assert reread["capability_gaps"] == []
        assert reread["additional_equipment_cost_cents"] == 0
        assert reread["reviewed_by_user_id"] == "user-td-1"
        assert reread["version"] == 2
