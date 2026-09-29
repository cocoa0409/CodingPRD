"""Request validation corners and guard precedence.

Covers the boundary cases of the combine-week containment window, the
booking-type resource shape, the temporal gate on undrafted offers and the
rookie-pool gate at signing, plus the two places where the fixed guard order
decides which of several simultaneously violated rules is reported: an
unresolvable body foreign key ahead of the coherence check it would feed, and
authentication ahead of body parsing.
"""

from test_helpers import (
    ADMIN,
    COMBINE_WEEK_START_AT,
    CYCLE_SETUP_NOW,
    DRAFT_START_AT,
    ERR_BOOKING_RESOURCE_MISMATCH,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_ROOKIE_POOL_EXCEEDED,
    ERR_UDFA_WINDOW_CLOSED,
    ERR_UNAUTHENTICATED,
    LEAGUE_ADMIN_USER_ID,
    NON_EXISTENT_UUID,
    UDFA_WINDOW_CLOSE_AT,
    advance_clock,
    assert_cents_equal,
    build_combine_week_with_station,
    build_declaration_open,
    build_draft_live_on_clock,
    build_first_selection,
    combine_booking_payload,
    contract_status_payload,
    create_cycle,
    declare_prospect,
    finalize_order,
    list_picks,
    make_club_gm_headers,
    make_prospect_agent_headers,
    make_selection,
    move_phase,
    offer_drafted_contract,
    pick_index,
    player_contract_payload,
    prospect_payload,
    read_club,
    read_contract,
    read_cycle,
    read_prospect,
    register_club,
    register_prospect,
    rule_prospect_eligible,
    run_lottery,
    set_clock,
    validate_error,
    validate_success,
)


def _drive_to_draft_complete(api, cycle_id):
    """Advance the selection clock until the cycle reports DRAFT_COMPLETE."""
    for _ in range(6):
        if read_cycle(api, cycle_id)["status"] == "DRAFT_COMPLETE":
            return
        advance_clock(api, cycle_id)
    raise AssertionError("the draft never reached DRAFT_COMPLETE")


class TestCombineWeekContainment:
    """The compressed week is inclusive at its opening instant."""

    def test_booking_that_opens_exactly_at_the_week_start_is_created(self, api):
        """A booking starting on the week-open instant is accepted, not refused.

        The interval runs from the cycle's own combine_week_start_at to
        forty-five minutes later, entirely inside the week, so the booking is
        scheduled and its duration is published in whole minutes.

        PRD: "The interval must sit wholly inside the cycle's compressed week: `starts_at` at or after `combine_week_start_at` and `ends_at` at or before `combine_week_end_at`, else `ERR_OUTSIDE_COMBINE_WEEK`."
        PRD: "The server computes `duration_minutes` as the whole number of minutes between `starts_at` and `ends_at`."

        Design: Corner/validations/booking_starting_exactly_at_the_combine_week_open_is_accepted
        """
        state = build_combine_week_with_station(api)

        booking = validate_success(
            api.create_combine_booking(
                combine_booking_payload(
                    state["prospect"]["id"],
                    "MEDICAL_EXAM",
                    COMBINE_WEEK_START_AT,
                    "2027-02-22T08:45:00.000Z",
                    medical_station_id=state["station"]["id"],
                ),
                ADMIN,
            ),
            expected_status=201,
        )

        assert booking["status"] == "SCHEDULED"
        assert booking["starts_at"] == "2027-02-22T08:00:00.000Z"
        assert booking["duration_minutes"] == 45
        assert booking["medical_station_id"] == state["station"]["id"]


class TestBookingResourceShape:
    """The resource fields a booking may carry follow from its type."""

    def test_on_field_test_may_not_name_a_medical_station(self, api):
        """A station id that a medical exam would require makes a field test invalid.

        An ON_FIELD_TEST supplies none of the three resource references, so the
        request is refused and the station it named is left untouched.

        PRD: "Which resource fields accompany the booking is dictated entirely by `booking_type`: a `MEDICAL_EXAM` supplies `medical_station_id` and neither of the other two; a `CLUB_INTERVIEW` supplies both `interview_room_id` and `club_id` and no station; an `ON_FIELD_TEST` supplies none of the three."

        Design: Corner/validations/on_field_test_with_a_station_id_is_rejected
        """
        state = build_combine_week_with_station(api)

        response = api.create_combine_booking(
            combine_booking_payload(
                state["prospect"]["id"],
                "ON_FIELD_TEST",
                "2027-02-24T10:00:00.000Z",
                "2027-02-24T11:00:00.000Z",
                medical_station_id=state["station"]["id"],
            ),
            ADMIN,
        )

        validate_error(response, ERR_BOOKING_RESOURCE_MISMATCH, expected_status=422)

        station = validate_success(
            api.get_medical_station(state["station"]["id"], ADMIN),
            expected_status=200,
        )
        assert station["status"] == "AVAILABLE"


class TestBodyReferenceResolutionOrder:
    """An unresolvable body reference is reported before it can be judged."""

    def test_unknown_draft_pick_reports_the_missing_reference(self, api):
        """A contract naming a non-existent pick answers 404, not the coherence 422.

        The coherence rule can only inspect a pick it has loaded, so a
        draft_pick_id that resolves to nothing surfaces the reference failure and
        the prospect keeps the drafted position it already holds.

        PRD: "Foreign keys supplied in a request body are resolved after all path parameters, in the order the endpoint declares its input fields, and an unresolvable one produces `ERR_REFERENCED_ENTITY_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/unknown_draft_pick_fk_is_reported_before_the_contract_pick_mismatch
        """
        state = build_first_selection(api)
        elm = state["clubs"]["ELM"]
        prospect = read_prospect(api, state["prospect"]["id"])

        response = api.create_player_contract(
            player_contract_payload(
                prospect["id"],
                elm["id"],
                "DRAFTED",
                prospect["version"],
                draft_pick_id=NON_EXISTENT_UUID,
            ),
            make_club_gm_headers(elm["id"]),
        )

        validate_error(response, ERR_REFERENCED_ENTITY_NOT_FOUND, expected_status=404)

        after = read_prospect(api, prospect["id"])
        assert after["signing_status"] == "UNSIGNED"
        assert after["drafted_pick_overall_number"] == 1


class TestUndraftedWindowBoundary:
    """The undrafted window is closed at its own closing instant."""

    def test_offer_at_exactly_the_close_instant_is_refused(self, api):
        """An offer submitted on the closing instant is already too late.

        The gate is strictly before udfa_window_close_at, so at exactly
        2027-04-25T18:00:00.000Z the offer is refused even though the cycle still
        sits in UDFA_WINDOW and the club's frozen pool is untouched.

        PRD: "Undrafted-window openness — the current logical instant is strictly before `udfa_window_close_at` for undrafted-free-agent offers and signings, else `ERR_UDFA_WINDOW_CLOSED` (409)."
        PRD: "Sum `slot_first_year_cap_charge_cents` over the picks whose `owning_club_id` is this club and whose `status` is `LAPSED`; picks in `USED`, `PASSED`, `PENDING` or `FORFEITED` contribute nothing."

        Design: Corner/validations/udfa_offer_exactly_at_the_window_close_instant_is_rejected
        """
        state = build_draft_live_on_clock(api)
        cycle_id = state["cycle"]["id"]
        elm = state["clubs"]["ELM"]

        set_clock(api, "2027-04-24T00:00:00.000Z")
        _drive_to_draft_complete(api, cycle_id)
        move_phase(api, cycle_id, "UDFA_WINDOW")

        set_clock(api, UDFA_WINDOW_CLOSE_AT)
        prospect = read_prospect(api, state["prospect"]["id"])

        response = api.create_player_contract(
            player_contract_payload(
                prospect["id"],
                elm["id"],
                "UDFA",
                prospect["version"],
                udfa_signing_bonus_cents=5000000,
            ),
            make_club_gm_headers(elm["id"]),
        )

        validate_error(response, ERR_UDFA_WINDOW_CLOSED, expected_status=409)

        assert read_cycle(api, cycle_id)["status"] == "UDFA_WINDOW"

        club = read_club(api, elm["id"])
        assert_cents_equal(club["udfa_pool_total_cents"], 214508256)
        assert_cents_equal(club["udfa_pool_remaining_cents"], 214508256)

        assert read_prospect(api, prospect["id"])["signing_status"] == "UNSIGNED"


class TestRookiePoolGate:
    """The rookie pool is tested at signing, not at offer."""

    def test_signing_over_the_pool_is_refused_and_leaves_the_pool_whole(self, api):
        """A club with a small pool may offer the overall-one contract but not sign it.

        The slotted first-year charge of 196,721,432 cents exceeds the club's
        whole pool of 150,000,000, so SIGN is refused, the contract stays
        OFFERED with no signing instant, and the pool is undrawn.

        PRD: "The gate applies at signing time: if the club's signed first-year charges *after* this signing would exceed `rookie_pool_total_cents`, the signing is refused with `ERR_ROOKIE_POOL_EXCEEDED`."

        Design: Corner/validations/signing_a_slotted_contract_above_the_rookie_pool_is_rejected
        """
        set_clock(api, CYCLE_SETUP_NOW)
        cycle = create_cycle(api, rounds_count=2)
        cycle_id = cycle["id"]
        elm = register_club(api, cycle_id, "ELM", rookie_pool_total_cents=150000000)
        register_club(api, cycle_id, "HAR")

        move_phase(api, cycle_id, "DECLARATION_OPEN")
        prospect = register_prospect(api, cycle_id)
        declare_prospect(api, prospect)
        rule_prospect_eligible(api, prospect)
        move_phase(api, cycle_id, "COMBINE_WEEK")
        move_phase(api, cycle_id, "ORDER_PENDING")
        run_lottery(api, cycle_id)
        finalize_order(api, cycle_id)
        picks = pick_index(list_picks(api, cycle_id))

        set_clock(api, DRAFT_START_AT)
        move_phase(api, cycle_id, "DRAFT_LIVE")
        advance_clock(api, cycle_id)
        make_selection(api, picks["r1p1"], prospect, elm)
        contract = offer_drafted_contract(api, prospect, elm, picks["r1p1"])

        response = api.set_contract_status(
            contract["id"],
            contract_status_payload("SIGN"),
            make_prospect_agent_headers(prospect["id"]),
        )

        validate_error(response, ERR_ROOKIE_POOL_EXCEEDED, expected_status=422)

        stored = read_contract(api, contract["id"])
        assert stored["status"] == "OFFERED"
        assert_cents_equal(stored["first_year_cap_charge_cents"], 196721432)
        assert stored["signed_at"] is None

        assert_cents_equal(read_club(api, elm["id"])["rookie_pool_remaining_cents"], 150000000)
        assert read_prospect(api, prospect["id"])["signing_status"] == "OFFER_OUT"


class TestAuthenticationPrecedence:
    """Authentication is resolved before the body is parsed."""

    def test_missing_role_header_beats_an_unknown_enum_value(self, api):
        """A request with no role header and a bad enum reports the authentication failure.

        Authentication is the first guard and the enum check the third, so the
        response is 401 rather than 400 and no prospect is created.

        PRD: "Guards are therefore evaluated in a single fixed order, top to bottom; the first guard that fails determines the response, and no later guard runs."
        PRD: "Authentication — both headers present and `X-User-Role` one of the six declared roles, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

        Design: Corner/validations/missing_role_header_unauthenticated_outranks_invalid_request
        """
        state = build_declaration_open(api)
        cycle_id = state["cycle"]["id"]

        response = api.create_prospect(
            prospect_payload(
                cycle_id,
                full_name="Cade Rios",
                position_group="GOALIE",
                school_code="EST",
                seasons_played=3,
                scouting_grade=85.00,
                position_group_scarcity_rank=2,
            ),
            {"X-User-ID": LEAGUE_ADMIN_USER_ID, "Content-Type": "application/json"},
        )

        validate_error(response, ERR_UNAUTHENTICATED, expected_status=401)

        assert read_cycle(api, cycle_id)["status"] == "DECLARATION_OPEN"
