"""Assignment lifecycle (sign-on, relieve, close, cancel) and the parallel
travel / repatriation dimensions with their fare arithmetic."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    book_and_ticket,
    confirm_assignment,
    create_activated_mariner,
    create_join_booking,
    create_join_booking_payload,
    create_ticketed_join_booking,
    get_assignment,
    list_bookings,
    propose_assignment,
    set_clock,
    setup_confirmed_assignment,
    setup_relief_pair,
    travel_leg_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
CREWING = TEST_USERS["crewing_headers"]
CAPTAIN = TEST_USERS["port_captain_headers"]


class TestParallelTravelDimensions:

    def test_travel_dimension_advances_independently_of_lifecycle(self):
        """PRD section 3.7: "A confirmed assignment's `travel_status` is set
        to `WAIVED` when `local_join` is true, and remains `PENDING`
        otherwise."
        PRD section 3.8: "`travel_status` runs `PENDING` → `READY` when a join
        booking is ticketed"
        PRD section 3.8: "Ticketing requires `BOOKED` (else
        `ERR_INVALID_STATE`) and computes `total_fare_cents`: each leg's fare
        is its `base_fare_cents` marked up by its `markup_bps` ten-thousandths,
        rounded half-up to whole cents per leg first"

        Design: Difficulty/non_linear_state_machine/assignment_parallel_travel_dimensions
        """
        ctx = setup_confirmed_assignment(local_join=False)
        assignment = ctx["assignment"]
        assert assignment["assignment_status"] == "CONFIRMED"
        assert assignment["travel_status"] == "PENDING", \
            "confirm does not auto-ready travel"
        assert assignment["repatriation_status"] == "NOT_DUE"

        # One leg: 10000 x (1 + 500/10000) = 10500.
        booking = create_ticketed_join_booking(assignment["id"])
        assert booking["total_fare_cents"] == 10500

        after_ticket = get_assignment(assignment["id"])
        assert after_ticket["assignment_status"] == "CONFIRMED", \
            "travel reaching READY does not advance the lifecycle"
        assert after_ticket["travel_status"] == "READY"
        assert after_ticket["repatriation_status"] == "NOT_DUE"

        set_clock("2026-08-10T00:00:00Z")
        signed = validate_success(
            api_client.sign_on_assignment(assignment["id"], CREWING))
        assert signed["assignment_status"] == "ONBOARD"
        assert signed["travel_status"] == "READY", \
            "sign-on leaves the travel dimension untouched"

    def test_relieve_flips_only_repatriation_and_autocreates_booking(self):
        """PRD section 3.7: "it stamps `actual_relieved_at` with the current
        clock, moves `repatriation_status` to `DUE`, auto-creates a
        repatriation travel booking under the relieved assignment (direction
        `REPATRIATION`, status `QUOTED`, empty `legs`, payer `VESSEL_OWNER`)"
        PRD section 3.8: "`travel_status` runs `PENDING` → `READY` when a join
        booking is ticketed, `READY` → `PENDING` when the last
        ticketed-or-completed join booking is cancelled, and `PENDING` →
        `WAIVED` at confirmation for a local-join mariner."

        Design: Difficulty/non_linear_state_machine/assignment_parallel_travel_dimensions
        """
        ctx = setup_relief_pair()
        assert ctx["incoming"]["travel_status"] == "WAIVED", \
            "local-join confirm waives travel"

        set_clock("2026-11-08T00:00:00Z")
        validate_success(
            api_client.sign_on_assignment(ctx["incoming"]["id"], CAPTAIN))
        relieved = validate_success(
            api_client.relieve_assignment(ctx["outgoing"]["id"], CREWING))
        assert relieved["assignment_status"] == "RELIEVED"
        assert relieved["repatriation_status"] == "DUE"
        assert relieved["travel_status"] == "WAIVED", \
            "the relieve touches only the repatriation dimension"

        repats = list_bookings(ctx["outgoing"]["id"], direction="REPATRIATION")
        assert len(repats) == 1, "exactly one system-created repatriation booking"
        assert repats[0]["status"] == "QUOTED"
        assert repats[0]["direction"] == "REPATRIATION"


class TestSignOnGateLadder:

    def test_sign_on_temporal_then_travel_gate_ladder(self):
        """PRD section 3.7: "It requires the current clock to be at or past
        the `sign_on_date` (else `ERR_SIGN_ON_TOO_EARLY`), the `travel_status`
        to be `READY` or `WAIVED` (else `ERR_TRAVEL_NOT_READY`), and the
        mariner's posture to be anything but `BLOCKED` (else
        `ERR_MARINER_NOT_CLEAR`). Sign-on stamps `actual_sign_on_at` with the
        current clock"

        Design: Corner/state_machines/sign_on_temporal_then_travel_gate_ladder
        """
        ctx = setup_confirmed_assignment(local_join=False)
        assignment_id = ctx["assignment"]["id"]

        set_clock("2026-08-05T00:00:00Z")  # before sign_on 2026-08-10
        resp = api_client.sign_on_assignment(assignment_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_SIGN_ON_TOO_EARLY)

        set_clock("2026-08-10T00:00:00Z")  # clock reached; travel still PENDING
        resp = api_client.sign_on_assignment(assignment_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_NOT_READY)

        booking = create_join_booking(
            assignment_id,
            legs=[travel_leg_payload(base_fare_cents=10000, markup_bps=0)])
        book_and_ticket(assignment_id, booking["id"])

        signed = validate_success(
            api_client.sign_on_assignment(assignment_id, CREWING))
        assert signed["assignment_status"] == "ONBOARD"
        assert signed["actual_sign_on_at"] == "2026-08-10T00:00:00Z"


class TestRelieveAndClose:

    def test_relieve_rejected_until_incoming_is_onboard(self):
        """PRD section 3.7: "Relieving — a `CrewingManager` action — moves
        `ONBOARD` to `RELIEVED` and requires that another, different
        assignment on the same billet already be `ONBOARD` (else
        `ERR_RELIEF_NOT_ONBOARD`)"

        Design: Difficulty/cross_entity_state_dependency/relieve_gated_by_incoming_onboard
        """
        ctx = setup_relief_pair()  # incoming merely CONFIRMED
        resp = api_client.relieve_assignment(ctx["outgoing"]["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_RELIEF_NOT_ONBOARD)

    def test_relieve_succeeds_after_incoming_signs_on(self):
        """PRD section 3.7: "Relieving — a `CrewingManager` action — moves
        `ONBOARD` to `RELIEVED` and requires that another, different
        assignment on the same billet already be `ONBOARD` (else
        `ERR_RELIEF_NOT_ONBOARD`); it stamps `actual_relieved_at` with the
        current clock, moves `repatriation_status` to `DUE`"

        Design: Difficulty/cross_entity_state_dependency/relieve_gated_by_incoming_onboard
        """
        ctx = setup_relief_pair()
        set_clock("2026-11-08T00:00:00Z")
        validate_success(
            api_client.sign_on_assignment(ctx["incoming"]["id"], CAPTAIN))
        relieved = validate_success(
            api_client.relieve_assignment(ctx["outgoing"]["id"], CREWING))
        assert relieved["assignment_status"] == "RELIEVED"
        assert relieved["repatriation_status"] == "DUE"

    def test_assignment_close_gated_until_repatriation_completes(self):
        """PRD section 3.7: "Closing moves `RELIEVED` to the terminal `CLOSED`
        and requires `repatriation_status` to have reached `COMPLETED` (else
        `ERR_REPATRIATION_INCOMPLETE`)."
        PRD section 3.8: "a `REPATRIATION` booking reaching `TICKETED` moves
        `repatriation_status` from `DUE` to `ARRANGED`. Completion requires
        `TICKETED` (else `ERR_INVALID_STATE`); a completed `REPATRIATION`
        booking moves `repatriation_status` from `ARRANGED` to `COMPLETED`."

        Design: Corner/state_machines/assignment_close_gated_until_repatriation_completes
        """
        ctx = setup_relief_pair()
        set_clock("2026-11-08T00:00:00Z")
        validate_success(
            api_client.sign_on_assignment(ctx["incoming"]["id"], CAPTAIN))
        relieved = validate_success(
            api_client.relieve_assignment(ctx["outgoing"]["id"], CREWING))
        assert relieved["repatriation_status"] == "DUE"

        repats = list_bookings(ctx["outgoing"]["id"], direction="REPATRIATION")
        booking = repats[0]
        assert booking["status"] == "QUOTED" and booking["legs"] == []

        outgoing_id = ctx["outgoing"]["id"]
        # Close blocked at DUE.
        resp = api_client.close_assignment(outgoing_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_REPATRIATION_INCOMPLETE)

        # Fill the system-created booking's legs and ticket it.
        validate_success(
            api_client.update_travel_booking_legs(
                outgoing_id, booking["id"],
                {"legs": [travel_leg_payload(
                    carrier="SQ", from_port="SIN", to_port="SFO",
                    depart_at="2026-11-09T10:00:00Z",
                    arrive_at="2026-11-09T20:00:00Z",
                    base_fare_cents=20000, markup_bps=0)]},
                CREWING))
        ticketed = book_and_ticket(outgoing_id, booking["id"])
        assert ticketed["status"] == "TICKETED"
        assert get_assignment(outgoing_id)["repatriation_status"] == "ARRANGED"

        # Close still blocked at ARRANGED.
        resp = api_client.close_assignment(outgoing_id, CREWING)
        validate_error(resp, ApiErrorId.ERR_REPATRIATION_INCOMPLETE)

        validate_success(
            api_client.complete_travel_booking(outgoing_id, booking["id"],
                                               CREWING))
        closed = validate_success(api_client.close_assignment(outgoing_id,
                                                              CREWING))
        assert closed["assignment_status"] == "CLOSED"
        assert closed["repatriation_status"] == "COMPLETED"

    def test_assignment_cancel_from_cancelled_lockdown(self):
        """PRD section 3.7: "Cancellation moves an assignment from `PROPOSED`,
        `CONFIRMED`, or `SUSPENDED` to the terminal `CANCELLED` — any other
        source state is `ERR_INVALID_STATE`"

        Design: Corner/state_machines/assignment_cancel_from_cancelled_lockdown
        """
        ctx = setup_confirmed_assignment()
        cancelled = validate_success(
            api_client.cancel_assignment(ctx["assignment"]["id"], CREWING))
        assert cancelled["assignment_status"] == "CANCELLED"

        resp = api_client.cancel_assignment(ctx["assignment"]["id"], CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTravelFareAndFees:

    def test_travel_fare_per_leg_rounding_order(self):
        """PRD section 3.8: "Ticketing requires `BOOKED` (else
        `ERR_INVALID_STATE`) and computes `total_fare_cents`: each leg's fare
        is its `base_fare_cents` marked up by its `markup_bps` ten-thousandths,
        rounded half-up to whole cents per leg first, and the per-leg amounts
        are then summed — the evaluation order is pinned, because rounding per
        leg before summing yields different cents than summing before
        rounding."

        Design: Difficulty/combinatorial_formula/travel_fare_per_leg_rounding_order
        """
        ctx = setup_confirmed_assignment(local_join=False)
        legs = [
            travel_leg_payload(carrier="UA", base_fare_cents=9990,
                               markup_bps=1550),
            travel_leg_payload(carrier="SQ", from_port="SIN", to_port="JKT",
                               depart_at="2026-08-10T06:00:00Z",
                               arrive_at="2026-08-10T08:00:00Z",
                               base_fare_cents=9990, markup_bps=1550),
        ]
        booking = create_join_booking(ctx["assignment"]["id"], legs=legs)
        ticketed = book_and_ticket(ctx["assignment"]["id"], booking["id"])
        # round_half_up(11538.45) = 11538 per leg, then 11538 + 11538.
        assert ticketed["total_fare_cents"] == 23076, (
            f"per-leg rounding then sum, got {ticketed['total_fare_cents']} "
            f"(sum-then-round would yield 23077)")

        after = get_assignment(ctx["assignment"]["id"])
        assert after["travel_status"] == "READY", \
            "a JOIN booking reaching TICKETED bubbles the travel dimension"

    def test_travel_fare_single_leg_markup_computation(self):
        """PRD section 3.8: "each leg's fare is its `base_fare_cents` marked
        up by its `markup_bps` ten-thousandths, rounded half-up to whole cents
        per leg first, and the per-leg amounts are then summed"

        Design: Difficulty/combinatorial_formula/travel_fare_per_leg_rounding_order
        """
        ctx = setup_confirmed_assignment(local_join=False)
        # 9990 x (1 + 1550/10000) = 11538.45 -> 11538 (round half-up per leg).
        booking = create_ticketed_join_booking(
            ctx["assignment"]["id"],
            legs=[travel_leg_payload(base_fare_cents=9990, markup_bps=1550)])
        assert booking["total_fare_cents"] == 11538, \
            f"single-leg total, got {booking['total_fare_cents']}"

    def test_travel_ticketed_cancel_fee_and_travel_demotion(self):
        """PRD section 3.8: "Cancelling from `QUOTED` or `BOOKED` sets
        `cancellation_fee_cents` to zero; cancelling from `TICKETED` sets
        `cancellation_fee_cents` to 15 percent of `total_fare_cents`, rounded
        half-up to whole cents."
        PRD section 3.8: "Cancelling a ticketed `JOIN` booking demotes the
        assignment's `travel_status` back to `PENDING` when no other `JOIN`
        booking in `TICKETED` or `COMPLETED` status remains."

        Design: Corner/state_machines/travel_ticketed_cancel_fee_and_travel_demotion
        """
        ctx = setup_confirmed_assignment(local_join=False)
        booking = create_ticketed_join_booking(ctx["assignment"]["id"])
        assert booking["total_fare_cents"] == 10500
        assert get_assignment(ctx["assignment"]["id"])["travel_status"] == "READY"

        cancelled = validate_success(
            api_client.cancel_travel_booking(
                ctx["assignment"]["id"], booking["id"], CREWING))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_fee_cents"] == 1575, \
            f"round_half_up(10500 x 0.15), got {cancelled['cancellation_fee_cents']}"
        assert get_assignment(ctx["assignment"]["id"])["travel_status"] == "PENDING", \
            "last JOIN ticket cancelled demotes the travel dimension"


class TestTravelBookingConstraints:

    def test_manual_repatriation_booking_rejected(self):
        """PRD section 3.8: "Only `JOIN` bookings are created manually — a
        `CrewingManager` capability on an assignment in `CONFIRMED`,
        `ONBOARD`, or `RELIEVED` status (else `ERR_INVALID_STATE`), and a
        manual creation naming `REPATRIATION` is rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/errors/manual_repatriation_booking_rejected
        """
        ctx = setup_confirmed_assignment()
        resp = api_client.create_travel_booking(
            ctx["assignment"]["id"],
            create_join_booking_payload(
                direction="REPATRIATION",
                legs=[travel_leg_payload(
                    carrier="SQ", from_port="SIN", to_port="SFO",
                    depart_at="2026-11-10T10:00:00Z",
                    arrive_at="2026-11-11T00:00:00Z",
                    base_fare_cents=20000, markup_bps=0)]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_travel_join_without_legs_rejected(self):
        """PRD section 3.8: "A `JOIN` creation requires at least one leg, else
        `ERR_NO_TRAVEL_LEGS`"

        Design: Corner/errors/travel_join_without_legs_rejected
        """
        ctx = setup_confirmed_assignment(local_join=False)
        resp = api_client.create_travel_booking(
            ctx["assignment"]["id"],
            create_join_booking_payload(legs=[]),
            CREWING)
        validate_error(resp, ApiErrorId.ERR_NO_TRAVEL_LEGS)

    def test_travel_legs_replaceable_only_while_quoted(self):
        """PRD section 3.8: "While a booking is `QUOTED`, a `CrewingManager`
        may replace its `legs` wholesale — this is how the empty
        system-created repatriation booking gets its itinerary — and replacing
        legs in any other status is `ERR_INVALID_STATE`."

        Design: Corner/endpoints/travel_legs_replaceable_only_while_quoted
        """
        ctx = setup_confirmed_assignment(local_join=False)
        booking = create_join_booking(ctx["assignment"]["id"])

        replaced = validate_success(
            api_client.update_travel_booking_legs(
                ctx["assignment"]["id"], booking["id"],
                {"legs": [travel_leg_payload(
                    to_port="TYO", depart_at="2026-08-09T11:00:00Z",
                    arrive_at="2026-08-10T03:00:00Z", base_fare_cents=12000,
                    markup_bps=0)]},
                CREWING))
        assert replaced["legs"][0]["to_port"] == "TYO", \
            "legs replaced while QUOTED"

        validate_success(
            api_client.book_travel_booking(
                ctx["assignment"]["id"], booking["id"], CREWING))
        resp = api_client.update_travel_booking_legs(
            ctx["assignment"]["id"], booking["id"],
            {"legs": [travel_leg_payload(to_port="HNL")]},
            CREWING)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
