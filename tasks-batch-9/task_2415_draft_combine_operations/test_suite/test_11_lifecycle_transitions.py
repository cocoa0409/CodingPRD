"""Lifecycle transitions across the cycle, prospect, waiver, booking and pick.

Covers the phase ladder's preconditions and its undeclared jumps, the opening
posture of an eligibility waiver, the terminal eligibility ruling, declaration
idempotence, the draft-order mint and its stamped windows, the withdrawal
cascade onto scheduled bookings, the check-in lead window, and the selection
that hands the clock on while re-deriving the drafting club's capital.
"""

from test_helpers import (
    ADMIN,
    COMMITTEE,
    CYCLE_SETUP_NOW,
    DRAFT_START_AT,
    ERR_ALREADY_DECLARED,
    ERR_INVALID_STATE_TRANSITION,
    UDFA_WINDOW_CLOSE_AT,
    assert_chart_points,
    assert_common_fields,
    assert_prospect_dimensions,
    booking_status_payload,
    build_combine_week,
    build_cycle_with_clubs,
    build_order_pending,
    create_station,
    declaration_payload,
    eligibility_determination_payload,
    eligibility_waiver_payload,
    book,
    declare_prospect,
    make_club_gm_headers,
    make_prospect_agent_headers,
    phase_payload,
    read_club,
    read_cycle,
    read_prospect,
    register_prospect,
    rule_prospect_eligible,
    rule_prospect_ineligible,
    run_lottery,
    selection_payload,
    set_clock,
    validate_error,
    validate_success,
)


class TestPhaseLadder:
    """Walking, and failing to walk, the cycle's ten-value status ladder."""

    def test_two_registered_clubs_unlock_the_declaration_phase(
        self, api, cycle_with_two_clubs
    ):
        """The SETUP to DECLARATION_OPEN move succeeds and bumps the cycle version.

        "`SETUP` advances to `DECLARATION_OPEN` only once `club_count` is at least 2, at which point prospects may begin declaring."
        "Each phase change increments the cycle's `version` by one."

        Design: Corner/state_machines/cycle_opens_declarations_once_two_clubs_are_registered
        """
        before = read_cycle(api, cycle_with_two_clubs["cycle"]["id"])

        cycle = validate_success(
            api.set_cycle_phase(
                before["id"], phase_payload("DECLARATION_OPEN"), ADMIN
            )
        )

        assert cycle["status"] == "DECLARATION_OPEN"
        assert cycle["posture"] == "OPEN"
        assert cycle["club_count"] == 2
        assert cycle["lottery_completed"] is False
        assert cycle["version"] == before["version"] + 1

    def test_single_club_cycle_cannot_open_declarations(self, api):
        """One registered club leaves the declaration phase unreachable.

        "`SETUP` advances to `DECLARATION_OPEN` only once `club_count` is at least 2, at which point prospects may begin declaring."
        "Only a `LeagueDraftAdmin` moves it, by naming the desired next phase in `target_status`; a requested phase that is not a declared transition out of the current one is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/single_club_cycle_cannot_open_declarations
        """
        state = build_cycle_with_clubs(api, club_codes=["ELM"])
        before = read_cycle(api, state["cycle"]["id"])

        validate_error(
            api.set_cycle_phase(
                before["id"], phase_payload("DECLARATION_OPEN"), ADMIN
            ),
            ERR_INVALID_STATE_TRANSITION,
        )

        after = read_cycle(api, before["id"])
        assert after["status"] == "SETUP"
        assert after["club_count"] == 1
        assert after["version"] == before["version"]

    def test_cycle_cannot_jump_from_setup_straight_to_a_live_draft(
        self, api, cycle_with_two_clubs
    ):
        """DRAFT_LIVE is a legal enum value but not a legal move out of SETUP.

        "Only a `LeagueDraftAdmin` moves it, by naming the desired next phase in `target_status`; a requested phase that is not a declared transition out of the current one is refused with `ERR_INVALID_STATE_TRANSITION`."
        "`ORDER_FINAL` advances to `DRAFT_LIVE` only once the current logical instant has reached or passed `draft_start_at`; the posture becomes `RESTRICTED`, and no pick is on the clock until the clock is first advanced."

        Design: Corner/state_machines/cycle_cannot_jump_from_setup_to_draft_live
        """
        cycle_id = cycle_with_two_clubs["cycle"]["id"]

        validate_error(
            api.set_cycle_phase(cycle_id, phase_payload("DRAFT_LIVE"), ADMIN),
            ERR_INVALID_STATE_TRANSITION,
        )

        after = read_cycle(api, cycle_id)
        assert after["status"] == "SETUP"
        assert after["order_finalized_at"] is None


class TestProspectDimensionGuards:
    """The declaration and eligibility dimensions and their locked doors."""

    def test_repeat_declaration_is_refused_and_leaves_declared_at_alone(
        self, api, declaration_open
    ):
        """A second DECLARE on the same prospect never restamps the first one.

        "`DECLARE` advances `declaration_status` from `UNDECLARED` to `DECLARED` and stamps `declared_at` with the current logical instant."
        "A late attempt without that relief is refused with `ERR_DECLARATION_DEADLINE_PASSED`; an attempt against a prospect whose `declaration_status` is anything other than `UNDECLARED` is refused with `ERR_ALREADY_DECLARED`."

        Design: Corner/state_machines/second_declaration_for_the_same_prospect_is_rejected
        """
        prospect = register_prospect(api, declaration_open["cycle"]["id"])
        declared = declare_prospect(api, prospect)
        assert declared["declared_at"] == CYCLE_SETUP_NOW

        validate_error(
            api.declare_prospect(
                prospect["id"],
                declaration_payload("DECLARE"),
                make_prospect_agent_headers(prospect["id"]),
            ),
            ERR_ALREADY_DECLARED,
        )

        after = read_prospect(api, prospect["id"])
        assert after["declaration_status"] == "DECLARED"
        assert after["declared_at"] == CYCLE_SETUP_NOW

    def test_ineligible_prospect_cannot_be_ruled_eligible_again(
        self, api, declaration_open
    ):
        """An INELIGIBLE ruling cannot be undone by a later eligible ruling.

        "`DECLARE_ELIGIBLE` advances `eligibility_status` from `UNREVIEWED` to `ELIGIBLE`, and requires two things: the prospect's `declaration_status` is `DECLARED`, and the prospect has completed at least three amateur `seasons_played` — or, failing the seasons test, carries an `early_entry_waived` flag that is already true."
        "Transition legality — the supplied action corresponds to a declared transition out of the target resource's current state, else `ERR_INVALID_STATE_TRANSITION` (409). Applies to every action and status endpoint."

        Design: Corner/state_machines/ineligible_prospect_cannot_be_declared_eligible_again
        """
        prospect = register_prospect(api, declaration_open["cycle"]["id"])
        prospect = declare_prospect(api, prospect)
        rule_prospect_ineligible(api, prospect)

        validate_error(
            api.determine_prospect_eligibility(
                prospect["id"],
                eligibility_determination_payload("DECLARE_ELIGIBLE"),
                COMMITTEE,
            ),
            ERR_INVALID_STATE_TRANSITION,
        )

        after = read_prospect(api, prospect["id"])
        assert_prospect_dimensions(
            after, eligibility_status="INELIGIBLE", declaration_status="DECLARED"
        )

    def test_withdrawing_the_declaration_cancels_the_scheduled_exam(self, api):
        """Withdrawal rules the prospect out and releases the station interval.

        "Withdrawal is intentionally destructive: it forces `eligibility_status` to `INELIGIBLE`, and it cancels every one of the prospect's bookings still in `SCHEDULED`."

        Design: Corner/state_machines/prospect_withdrawal_cancels_its_scheduled_bookings
        """
        state = build_combine_week(api)
        prospect = rule_prospect_eligible(api, state["prospect"])
        station = create_station(api)
        booking = book(
            api,
            prospect,
            "MEDICAL_EXAM",
            "2027-02-23T09:00:00.000Z",
            "2027-02-23T09:45:00.000Z",
            medical_station_id=station["id"],
        )

        withdrawn = validate_success(
            api.declare_prospect(
                prospect["id"],
                declaration_payload("WITHDRAW"),
                make_prospect_agent_headers(prospect["id"]),
            )
        )

        assert_prospect_dimensions(
            withdrawn,
            declaration_status="WITHDRAWN",
            eligibility_status="INELIGIBLE",
            signing_status="UNSIGNED",
        )

        after = validate_success(api.get_combine_booking(booking["id"], ADMIN))
        assert after["status"] == "CANCELLED"
        assert after["duration_minutes"] == 45


class TestWaiverAndBookingOpeningStates:
    """The opening posture of a waiver and the guarded booking check-in."""

    def test_filed_waiver_opens_in_submitted_with_no_reviewer_recorded(
        self, api, declaration_open
    ):
        """The filer is stamped on the waiver while both reviewer slots stay null.

        "The new waiver starts at `status` `SUBMITTED` with `info_request_count` 0, `opened_by_user_id` null, `decided_by_user_id` null and `decided_at` null, and the filer's identifier is recorded as `submitted_by_user_id`."

        Design: Corner/state_machines/eligibility_waiver_opens_in_submitted_state
        """
        prospect = register_prospect(api, declaration_open["cycle"]["id"])

        waiver = validate_success(
            api.create_eligibility_waiver(
                prospect["id"],
                eligibility_waiver_payload(
                    "LATE_DECLARATION",
                    rationale="Bowl-game injury delayed the paperwork",
                ),
                make_prospect_agent_headers(prospect["id"]),
            ),
            expected_status=201,
        )

        assert_common_fields(waiver, expected_version=1)
        assert waiver["status"] == "SUBMITTED"
        assert waiver["waiver_type"] == "LATE_DECLARATION"
        assert waiver["info_request_count"] == 0
        assert waiver["submitted_by_user_id"] == prospect["id"]
        assert waiver["opened_by_user_id"] is None
        assert waiver["decided_by_user_id"] is None
        assert waiver["decided_at"] is None

        assert read_prospect(api, prospect["id"])["late_declaration_waived"] is False

    def test_check_in_at_the_thirty_minute_lead_boundary_is_accepted(self, api):
        """Presenting exactly half an hour early checks the prospect in.

        "`CHECK_IN` advances `SCHEDULED` to `CHECKED_IN`, and requires both that the cycle is `COMBINE_WEEK` and that the current logical instant has reached the point half an hour before `starts_at` — a prospect may present up to thirty minutes early, no earlier."

        Design: Corner/state_machines/booking_check_in_allowed_inside_the_lead_time_window
        """
        state = build_combine_week(api)
        prospect = rule_prospect_eligible(api, state["prospect"])
        station = create_station(api)
        booking = book(
            api,
            prospect,
            "MEDICAL_EXAM",
            "2027-02-23T09:00:00.000Z",
            "2027-02-23T09:45:00.000Z",
            medical_station_id=station["id"],
        )
        set_clock(api, "2027-02-23T08:45:00.000Z")

        checked_in = validate_success(
            api.set_booking_status(
                booking["id"], booking_status_payload("CHECK_IN"), ADMIN
            )
        )

        assert checked_in["status"] == "CHECKED_IN"
        assert read_cycle(api, state["cycle"]["id"])["status"] == "COMBINE_WEEK"
        assert (
            read_prospect(api, prospect["id"])["medical_clearance_status"]
            == "PENDING"
        )


class TestOrderMintAndSelection:
    """Minting the pick ledger and spending the first pick on the clock."""

    def test_finalize_mints_the_ledger_and_stamps_both_windows(self, api):
        """One finalize call mints four picks and reconciles every aggregate.

        "It mints one pick per club per round, `rounds_count` multiplied by `club_count` rows in total, each created in `PENDING`."
        "Finalizing also stamps `order_finalized_at` with the current logical instant and computes `udfa_window_close_at` as seventy-two hours after `draft_start_at`."

        Design: Corner/state_machines/finalize_mints_the_whole_pick_ledger_and_stamps_the_windows
        """
        state = build_order_pending(api)
        cycle_id = state["cycle"]["id"]
        run_lottery(api, cycle_id)

        result = validate_success(api.finalize_draft_order(cycle_id, None, ADMIN))

        assert result["created_pick_count"] == 4
        assert result["compensatory_pick_count"] == 0

        cycle = read_cycle(api, cycle_id)
        assert cycle["status"] == "ORDER_FINAL"
        assert cycle["order_finalized_at"] == CYCLE_SETUP_NOW
        assert cycle["udfa_window_close_at"] == UDFA_WINDOW_CLOSE_AT
        assert cycle["pick_inventory_count"] == 4
        assert_chart_points(cycle["pick_inventory_chart_points"], 2754.8)

        elm = state["clubs"]["ELM"]
        har = state["clubs"]["HAR"]

        first_pick = validate_success(
            api.get_draft_pick(result["first_overall_pick_id"], ADMIN)
        )
        assert first_pick["overall_number"] == 1
        assert first_pick["owning_club_id"] == elm["id"]
        assert first_pick["status"] == "PENDING"
        assert_chart_points(first_pick["chart_value_points"], 1000.0)

        elm_after = read_club(api, elm["id"])
        har_after = read_club(api, har["id"])
        assert_chart_points(elm_after["draft_capital_points"], 1420.0)
        assert elm_after["trade_authorization_tier"] == "FULL"
        assert_chart_points(har_after["draft_capital_points"], 1334.8)
        assert har_after["trade_authorization_tier"] == "FULL"

    def test_selection_hands_the_clock_on_and_re_derives_club_capital(
        self, api, draft_live_on_clock
    ):
        """Using overall pick one drops ELM to 420.0 points and starts pick two.

        "It sets `selected_prospect_id`, sets the prospect's `drafted_pick_overall_number` to this pick's `overall_number`, recomputes the club's `draft_capital_points` and `trade_authorization_tier`, and puts the next `PENDING` pick on the clock with `on_clock_started_at` set to the current instant."
        "it is `FULL` when `draft_capital_points` is at least 1200.0, `LIMITED` when it is at least 900.0 but below 1200.0, and `SUSPENDED` when it is below 900.0."

        Design: Corner/state_machines/selection_moves_the_clock_and_reconciles_club_capital
        """
        state = draft_live_on_clock
        elm = state["clubs"]["ELM"]
        prospect = state["prospect"]
        first_pick = state["pick"]["r1p1"]
        second_pick = state["pick"]["r1p2"]

        used = validate_success(
            api.create_selection(
                first_pick["id"],
                selection_payload(prospect["id"]),
                make_club_gm_headers(elm["id"]),
            )
        )

        assert used["status"] == "USED"
        assert used["selection_source"] == "ON_TIME"
        assert used["selected_prospect_id"] == prospect["id"]

        assert (
            read_prospect(api, prospect["id"])["drafted_pick_overall_number"] == 1
        )

        elm_after = read_club(api, elm["id"])
        assert_chart_points(elm_after["draft_capital_points"], 420.0)
        assert elm_after["trade_authorization_tier"] == "SUSPENDED"

        next_pick = validate_success(api.get_draft_pick(second_pick["id"], ADMIN))
        assert next_pick["status"] == "ON_CLOCK"
        assert next_pick["on_clock_started_at"] == DRAFT_START_AT
        assert next_pick["deadline_at"] == "2027-04-22T18:10:00.000Z"

        assert read_cycle(api, state["cycle"]["id"])["current_overall_number"] == 2
