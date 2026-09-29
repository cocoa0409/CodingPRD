"""Validation breadth: each rule driven to violation and to satisfaction.

Eight standalone rules covering station coordination, the shape of a slot
negotiation, grandfather-rights protection, the weekly traffic-rights ceiling,
the season window, notice channels, notice deadlines and ownership. Each one is
exercised in both directions against the same fixture, so only the rule under
test can explain the difference between the refusal and the acceptance.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_notification_obligation,
    assert_route_authority,
    assert_score_matches_counters,
    assert_slot_holding,
    assert_slot_transaction,
    assert_timestamp_equals,
    create_flight_leg_payload,
    create_route_authority,
    create_schedule_version,
    create_slot_holding_payload,
    create_slot_transaction_payload,
    dispatch_obligation,
    make_network_planner_headers,
    raise_obligation,
    read_carrier,
    read_holding,
    read_leg,
    read_obligation,
    read_route_authority,
    read_version,
    set_clock,
    setup_booked_leg,
    setup_reference_data,
    setup_transaction_precondition,
    validate_error,
    validate_paginated,
    validate_success,
    SEASON_MONDAYS,
    TEST_USERS,
)

COORDINATOR = TEST_USERS["slot_coordinator_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# ─── Rule 1: slots exist only where the airport is fully coordinated ──────

def _series_payload(ref, station_code):
    """The identical series request, aimed at whichever airport is named."""
    return create_slot_holding_payload(
        ref["stations"][station_code]["id"],
        ref["season"]["id"],
        ref["carrier"]["id"],
        movement_type="DEPARTURE",
        slot_time_utc=f"{SEASON_MONDAYS[0]}T08:00:00.000Z",
        days_of_week="1",
        series_weeks=5,
        historic_precedence=False,
    )


class TestSlotSeriesExistOnlyAtFullyCoordinatedAirports:
    """One payload, two stations: refused at the facilitated field, created at
    the coordinated hub."""

    def test_a_facilitated_airport_refuses_the_series(self):
        """Only the station's coordination level differs, so only it can
        explain the refusal.

        PRD §3.5: "if the named station's `coordination_level` is anything other
        than `LEVEL_3_COORDINATED` the request is refused with
        `ERR_STATION_NOT_COORDINATED`, because slots simply do not exist at
        schedules-facilitated or non-coordinated fields."

        Design: Corner/validations/slot_holdings_exist_only_at_fully_coordinated_stations
        """
        ref = setup_reference_data(("FRA", "MUC"))
        assert ref["stations"]["MUC"]["coordination_level"] == "LEVEL_2_FACILITATED"

        validate_error(
            api_client.create_slot_holding(_series_payload(ref, "MUC"), COORDINATOR),
            ApiErrorId.ERR_STATION_NOT_COORDINATED,
            expected_status=422,
        )

        assert read_carrier(ref["carrier"]["id"])["held_series_count"] == 0
        rows, meta = validate_paginated(
            api_client.list_slot_holdings(
                COORDINATOR, params={"station_id": ref["stations"]["MUC"]["id"]}
            )
        )
        assert meta["total_count"] == 0
        assert rows == []

    def test_the_coordinated_hub_accepts_the_same_request(self):
        """The series lands HELD with five planned Monday operations.

        PRD §3.5: "A new series is created in `holding_status` `HELD` with
        `planned_operations` equal to `series_weeks` multiplied by the number of
        digits in `days_of_week`"

        Design: Corner/validations/slot_holdings_exist_only_at_fully_coordinated_stations
        """
        ref = setup_reference_data(("FRA", "MUC"))
        assert ref["stations"]["FRA"]["coordination_level"] == "LEVEL_3_COORDINATED"

        holding = validate_success(
            api_client.create_slot_holding(_series_payload(ref, "FRA"), COORDINATOR),
            expected_status=201,
        )
        assert_slot_holding(holding)
        assert holding["holding_status"] == "HELD"
        assert holding["planned_operations"] == 5
        assert holding["station_id"] == ref["stations"]["FRA"]["id"]
        assert holding["attached_operations"] == 0

        assert read_carrier(ref["carrier"]["id"])["held_series_count"] == 1


# ─── Rule 2: the counter-slot field is keyed strictly to the kind ─────────

def _negotiation_with_two_series(*, offered_historic: bool = False):
    """HX offering its 08:00Z series while XP holds an unrelated 10:00Z one."""
    setup = setup_transaction_precondition(
        kind="EXCHANGE", offered_historic=offered_historic, series_weeks=5
    )
    setup["planner_headers"] = make_network_planner_headers(setup["carrier"]["id"])
    return setup


def _proposal_payload(setup, *, kind, with_counter):
    payload = create_slot_transaction_payload(
        setup["partner"]["id"],
        setup["offered"]["id"],
        setup["offered"]["version"],
        kind=kind,
    )
    if with_counter:
        payload["counter_slot_holding_id"] = setup["counter"]["id"]
    return payload


class TestCounterSlotIsRequiredForExchangeAndForbiddenForTransfer:
    """The same rule fires from both directions before it lets an exchange
    through."""

    def test_both_shapes_that_breach_the_kind_keying_are_refused(self):
        """An exchange missing its counter and a transfer carrying one share one
        error id.

        PRD §3.6: "The counter-slot field is strictly keyed to the kind: it must
        be present for an `EXCHANGE`, must be absent for a `TRANSFER`, and when
        present must be a series belonging to `counterparty_carrier_id`; a breach
        of any of those three is `ERR_COUNTER_SLOT_REQUIRED`."

        Design: Corner/validations/exchange_needs_a_counter_slot_and_transfer_must_not_carry_one
        """
        setup = _negotiation_with_two_series()

        validate_error(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="EXCHANGE", with_counter=False),
                setup["planner_headers"],
            ),
            ApiErrorId.ERR_COUNTER_SLOT_REQUIRED,
            expected_status=422,
        )
        validate_error(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="TRANSFER", with_counter=True),
                setup["planner_headers"],
            ),
            ApiErrorId.ERR_COUNTER_SLOT_REQUIRED,
            expected_status=422,
        )

        for holding_id in (setup["offered"]["id"], setup["counter"]["id"]):
            assert read_holding(holding_id, COORDINATOR)["pending_transaction_id"] is None

    def test_the_exchange_carrying_its_counter_slot_encumbers_both_series(self):
        """The initiating carrier is copied off the offered series, not
        supplied.

        PRD §3.6: "`initiating_carrier_id` is not supplied by the client at all
        - it is copied from the offered holding's own `carrier_id`".

        PRD §3.6: "A successful proposal is created in `status` `PROPOSED` with
        `proposed_by_user_id` stamped from the acting `X-User-ID`"

        Design: Corner/validations/exchange_needs_a_counter_slot_and_transfer_must_not_carry_one
        """
        setup = _negotiation_with_two_series()
        validate_error(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="EXCHANGE", with_counter=False),
                setup["planner_headers"],
            ),
            ApiErrorId.ERR_COUNTER_SLOT_REQUIRED,
        )

        transaction = validate_success(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="EXCHANGE", with_counter=True),
                setup["planner_headers"],
            ),
            expected_status=201,
        )
        assert_slot_transaction(transaction)
        assert transaction["status"] == "PROPOSED"
        assert transaction["kind"] == "EXCHANGE"
        assert transaction["initiating_carrier_id"] == setup["carrier"]["id"]
        assert transaction["proposed_by_user_id"] == setup["carrier"]["id"]
        assert transaction["counter_slot_holding_id"] == setup["counter"]["id"]
        assert transaction["successor_slot_holding_id"] is None
        assert transaction["responded_by_user_id"] is None
        assert transaction["approved_by_user_id"] is None

        for holding_id in (setup["offered"]["id"], setup["counter"]["id"]):
            holding = read_holding(holding_id, COORDINATOR)
            assert holding["pending_transaction_id"] == transaction["id"]

        rows, meta = validate_paginated(
            api_client.list_slot_transactions(COORDINATOR)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == transaction["id"]


# ─── Rule 3: grandfather rights survive a swap but not a disposal ─────────

class TestHistoricSeriesMayBeExchangedButNeverTransferred:
    """Precedence is protected against disposal only, so the two kinds diverge
    on one identical series."""

    def test_transferring_a_historic_series_outright_is_refused(self):
        """The transfer omits its counter slot correctly, so the precedence rule
        is the one that fires.

        PRD §3.6: "when the offered holding's `historic_precedence` is true and
        the `kind` is `TRANSFER`, the proposal is refused with
        `ERR_HISTORIC_PRECEDENCE_PROTECTED`."

        Design: Corner/validations/a_historic_series_may_be_exchanged_but_never_transferred_outright
        """
        setup = _negotiation_with_two_series(offered_historic=True)
        assert setup["offered"]["historic_precedence"] is True

        validate_error(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="TRANSFER", with_counter=False),
                setup["planner_headers"],
            ),
            ApiErrorId.ERR_HISTORIC_PRECEDENCE_PROTECTED,
            expected_status=409,
        )

        offered = read_holding(setup["offered"]["id"], COORDINATOR)
        assert offered["pending_transaction_id"] is None
        assert offered["holding_status"] == "HELD"

    def test_exchanging_that_very_same_series_is_accepted(self):
        """The rights follow the swap instead of blocking it.

        PRD §3.6: "A historic series may be exchanged - the rights follow the
        swap - but never disposed of outright."

        Design: Corner/validations/a_historic_series_may_be_exchanged_but_never_transferred_outright
        """
        setup = _negotiation_with_two_series(offered_historic=True)
        validate_error(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="TRANSFER", with_counter=False),
                setup["planner_headers"],
            ),
            ApiErrorId.ERR_HISTORIC_PRECEDENCE_PROTECTED,
        )

        transaction = validate_success(
            api_client.create_slot_transaction(
                _proposal_payload(setup, kind="EXCHANGE", with_counter=True),
                setup["planner_headers"],
            ),
            expected_status=201,
        )
        assert transaction["kind"] == "EXCHANGE"
        assert transaction["status"] == "PROPOSED"

        offered = read_holding(setup["offered"]["id"], COORDINATOR)
        assert offered["historic_precedence"] is True
        assert offered["holding_status"] == "HELD"
        assert offered["retains_historic_precedence"] is None


# ─── Rule 4: the weekly ceiling counts one ISO week, not seven rolling days ─

def _capped_route_to_lisbon():
    """A DE/PT authority capped at two frequencies a week, and an empty plan."""
    ref = setup_reference_data(("FRA", "LIS"))
    ref["authority"] = create_route_authority(
        ref["carrier"]["id"], "DE", "PT", weekly_frequency_cap=2
    )
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-R1"
    )
    ref["payload"] = lambda flight_number, date: create_flight_leg_payload(
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["LIS"]["id"],
        f"{date}T08:00:00.000Z",
        f"{date}T11:00:00.000Z",
        flight_number=flight_number,
    )
    return ref


class TestWeeklyFrequencyCapIsScopedToTheIsoWeek:
    """Monday and Tuesday fill the cap, Wednesday overflows it, and the next
    Monday starts over."""

    def test_the_third_departure_in_the_same_week_is_refused(self):
        """Each leg is individually authorised; only the weekly total breaches.

        PRD §3.4: "the total including the new leg may not exceed the authority's
        `weekly_frequency_cap`, or the leg is refused with
        `ERR_FREQUENCY_CAP_EXCEEDED`."

        PRD §3.4: "That last check is an aggregate one: each individual leg is
        fully authorised and only the weekly total breaches."

        Design: Corner/validations/weekly_frequency_cap_admits_two_legs_then_rejects_the_third_in_the_same_iso_week
        """
        ref = _capped_route_to_lisbon()

        for flight_number, date in (("HX600", "2026-11-02"), ("HX602", "2026-11-03")):
            leg = validate_success(
                api_client.create_flight_leg(
                    ref["payload"](flight_number, date), ref["planner"]
                ),
                expected_status=201,
            )
            assert leg["is_international"] is True
            assert leg["block_minutes"] == 180

        validate_error(
            api_client.create_flight_leg(
                ref["payload"]("HX604", "2026-11-04"), ref["planner"]
            ),
            ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED,
            expected_status=409,
        )
        assert read_version(ref["version"]["id"], ref["planner"])["leg_count"] == 2

    def test_the_first_instant_of_the_next_week_is_admitted_again(self):
        """The window runs Monday to Monday, so 2026-11-09 is a fresh budget.

        PRD §3.4: "counting the acting carrier's non-cancelled legs on that
        unordered country pair whose departure falls inside the new leg's ISO week
        - from Monday at 00:00:00Z through the following Monday at 00:00:00Z, the
        later boundary excluded"

        Design: Corner/validations/weekly_frequency_cap_admits_two_legs_then_rejects_the_third_in_the_same_iso_week
        """
        ref = _capped_route_to_lisbon()
        for flight_number, date in (("HX600", "2026-11-02"), ("HX602", "2026-11-03")):
            validate_success(
                api_client.create_flight_leg(
                    ref["payload"](flight_number, date), ref["planner"]
                ),
                expected_status=201,
            )
        validate_error(
            api_client.create_flight_leg(
                ref["payload"]("HX604", "2026-11-04"), ref["planner"]
            ),
            ApiErrorId.ERR_FREQUENCY_CAP_EXCEEDED,
        )

        next_week = validate_success(
            api_client.create_flight_leg(
                ref["payload"]("HX606", "2026-11-09"), ref["planner"]
            ),
            expected_status=201,
        )
        assert next_week["status"] == "DRAFT"

        version = read_version(ref["version"]["id"], ref["planner"])
        assert version["leg_count"] == 3
        assert version["unslotted_leg_count"] == 3
        assert version["schedule_compliance_score"] == pytest.approx(76.00, abs=0.01)
        assert version["compliance_state"] == "WARNED"
        assert_score_matches_counters(version)

        authority = read_route_authority(ref["authority"]["id"])
        assert_route_authority(authority)
        assert authority["status"] == "ACTIVE"
        assert authority["weekly_frequency_cap"] == 2


# ─── Rule 5: one rule guards three separate geometries ────────────────────

def _empty_plan_inside_the_season():
    """A W26 plan with nothing in it and a payload builder for any geometry."""
    ref = setup_reference_data(("FRA", "MUC"))
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-W1"
    )
    ref["payload"] = lambda flight_number, dep_utc, arr_utc: create_flight_leg_payload(
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["MUC"]["id"],
        dep_utc,
        arr_utc,
        flight_number=flight_number,
    )
    return ref


class TestLegsMustLieInsideTheSeasonAndRunForwards:
    """An early departure, a late arrival and a reversed pair all share one
    error id."""

    def test_all_three_broken_geometries_are_refused(self):
        """Checking only the departure side would accept the overrunning leg.

        PRD §3.4: "Both `dep_utc` and `arr_utc` must fall inside the season's
        window - the departure no earlier than `start_date` and the arrival no
        later than `end_date`, with the departure strictly before the arrival -
        and a breach in any of those three respects is
        `ERR_LEG_OUTSIDE_SEASON_WINDOW`."

        Design: Corner/validations/legs_must_lie_inside_the_season_window_and_run_forwards_in_time
        """
        ref = _empty_plan_inside_the_season()

        for flight_number, dep_utc, arr_utc in (
            ("HX101", "2026-10-20T08:00:00.000Z", "2026-10-20T09:00:00.000Z"),
            ("HX103", "2027-03-27T08:00:00.000Z", "2027-03-27T09:00:00.000Z"),
            ("HX105", "2026-11-02T09:00:00.000Z", "2026-11-02T08:00:00.000Z"),
        ):
            validate_error(
                api_client.create_flight_leg(
                    ref["payload"](flight_number, dep_utc, arr_utc), ref["planner"]
                ),
                ApiErrorId.ERR_LEG_OUTSIDE_SEASON_WINDOW,
                expected_status=422,
            )

        assert read_version(ref["version"]["id"], ref["planner"])["leg_count"] == 0

    def test_a_leg_wholly_inside_the_window_is_created(self):
        """The three rejected calls left no rows behind.

        PRD §3.4: "`block_minutes` is the whole number of minutes from `dep_utc`
        to `arr_utc`."

        Design: Corner/validations/legs_must_lie_inside_the_season_window_and_run_forwards_in_time
        """
        ref = _empty_plan_inside_the_season()
        for flight_number, dep_utc, arr_utc in (
            ("HX101", "2026-10-20T08:00:00.000Z", "2026-10-20T09:00:00.000Z"),
            ("HX103", "2027-03-27T08:00:00.000Z", "2027-03-27T09:00:00.000Z"),
            ("HX105", "2026-11-02T09:00:00.000Z", "2026-11-02T08:00:00.000Z"),
        ):
            validate_error(
                api_client.create_flight_leg(
                    ref["payload"](flight_number, dep_utc, arr_utc), ref["planner"]
                ),
                ApiErrorId.ERR_LEG_OUTSIDE_SEASON_WINDOW,
            )

        leg = validate_success(
            api_client.create_flight_leg(
                ref["payload"](
                    "HX107", "2026-11-02T08:00:00.000Z", "2026-11-02T09:00:00.000Z"
                ),
                ref["planner"],
            ),
            expected_status=201,
        )
        assert leg["block_minutes"] == 60
        assert leg["status"] == "DRAFT"

        version = read_version(ref["version"]["id"], ref["planner"])
        assert version["leg_count"] == 1

        rows, meta = validate_paginated(
            api_client.list_flight_legs(
                ref["planner"], params={"schedule_version_id": ref["version"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == leg["id"]


# ─── Rule 6: the channel rule is tier-conditional and dispatch is single-shot ─

def _mandatory_notice_pending():
    """Ten economy passengers and a three-hour retime, so the tier is
    mandatory."""
    world = setup_booked_leg(
        booked_first=0,
        booked_business=0,
        booked_economy=10,
        version_label="W26-D1",
    )
    world["obligation"] = raise_obligation(
        world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=180
    )
    return world


class TestAReaccommodationNoticeRefusesSmsAndDispatchesOnce:
    """SMS is insufficient for the mandatory tier, and the exit fires exactly
    once."""

    def test_sms_is_refused_and_leaves_the_obligation_untouched(self):
        """The rejected attempt must not consume the pending obligation.

        PRD §3.9: "a `MANDATORY_REACCOMMODATION` obligation may not be dispatched
        by `SMS` at all - only `EMAIL` or `AGENCY_QUEUE` are sufficient for a
        notice that has to carry re-accommodation options - with a violation
        reported as `ERR_NOTIFICATION_CHANNEL_INSUFFICIENT`."

        Design: Corner/validations/a_reaccommodation_notice_cannot_go_out_by_sms_and_cannot_be_dispatched_twice
        """
        world = _mandatory_notice_pending()
        obligation = world["obligation"]
        assert_notification_obligation(obligation)
        assert obligation["obligation_tier"] == "MANDATORY_REACCOMMODATION"
        assert obligation["compensation_cents"] == 251240

        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "SMS"}, OFFICER
            ),
            ApiErrorId.ERR_NOTIFICATION_CHANNEL_INSUFFICIENT,
            expected_status=422,
        )

        stored = read_obligation(obligation["id"], OFFICER)
        assert stored["status"] == "PENDING"
        assert stored["dispatched_channel"] is None
        assert read_leg(world["leg"]["id"], world["planner"])["open_obligation_count"] == 1

    def test_email_carries_the_same_notice_through(self):
        """Only the channel changed between the refusal and the acceptance.

        PRD §3.9: "On success `status` moves `PENDING → DISPATCHED`,
        `dispatched_channel` and `regulator_reference` are recorded"

        Design: Corner/validations/a_reaccommodation_notice_cannot_go_out_by_sms_and_cannot_be_dispatched_twice
        """
        world = _mandatory_notice_pending()
        obligation = world["obligation"]
        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "SMS"}, OFFICER
            ),
            ApiErrorId.ERR_NOTIFICATION_CHANNEL_INSUFFICIENT,
        )

        dispatched = validate_success(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "EMAIL"}, OFFICER
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_channel"] == "EMAIL"
        assert dispatched["late_dispatch"] is False
        assert dispatched["regulator_reference"] is None
        assert read_leg(world["leg"]["id"], world["planner"])["open_obligation_count"] == 0

    def test_a_second_dispatch_on_any_channel_is_refused(self):
        """The notice went out once; the counter stays where the exit left it.

        PRD §3.9: "**Dispatching the notice** is a `ComplianceOfficer` action,
        permitted only from `PENDING` - any other status gives
        `ERR_NOTIFICATION_STATE_INVALID`."

        Design: Corner/validations/a_reaccommodation_notice_cannot_go_out_by_sms_and_cannot_be_dispatched_twice
        """
        world = _mandatory_notice_pending()
        obligation = world["obligation"]
        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "SMS"}, OFFICER
            ),
            ApiErrorId.ERR_NOTIFICATION_CHANNEL_INSUFFICIENT,
        )
        dispatch_obligation(obligation["id"], channel="EMAIL")

        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "AGENCY_QUEUE"}, OFFICER
            ),
            ApiErrorId.ERR_NOTIFICATION_STATE_INVALID,
            expected_status=409,
        )

        stored = read_obligation(obligation["id"], OFFICER)
        assert stored["status"] == "DISPATCHED"
        assert stored["dispatched_channel"] == "EMAIL"
        assert stored["compensation_cents"] == 251240
        assert read_leg(world["leg"]["id"], world["planner"])["open_obligation_count"] == 0


# ─── Rule 7: a late notice must justify itself ────────────────────────────

def _advisory_notice_past_its_deadline():
    """An advisory notice raised on 08-01, then the clock walked past 08-04."""
    world = setup_booked_leg(
        booked_first=0,
        booked_business=0,
        booked_economy=10,
        version_label="W26-D2",
    )
    world["obligation"] = raise_obligation(
        world["leg"]["id"], trigger_kind="RETIME", change_magnitude_minutes=45
    )
    set_clock("2026-08-05T00:00:00.000Z")
    return world


class TestALateDispatchNeedsARegulatorReference:
    """SMS is legal for an advisory notice, so only the missing reference can
    explain the refusal."""

    def test_the_unreferenced_late_dispatch_is_refused(self):
        """The deadline was frozen at creation and the clock has since passed
        it.

        PRD §3.9: "If the logical clock has passed `notify_deadline_utc`, the
        request **must** carry a `regulator_reference` justifying the late notice,
        or it is refused with `ERR_LATE_NOTIFICATION_UNREFERENCED`; a dispatch at
        or before the deadline needs no reference."

        Design: Corner/validations/a_dispatch_after_the_notify_deadline_needs_a_regulator_reference
        """
        world = _advisory_notice_past_its_deadline()
        obligation = world["obligation"]
        assert obligation["obligation_tier"] == "ADVISORY"

        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "SMS"}, OFFICER
            ),
            ApiErrorId.ERR_LATE_NOTIFICATION_UNREFERENCED,
            expected_status=422,
        )

        stored = read_obligation(obligation["id"], OFFICER)
        assert stored["status"] == "PENDING"
        assert stored["regulator_reference"] is None
        assert stored["late_dispatch"] is False
        assert read_leg(world["leg"]["id"], world["planner"])["open_obligation_count"] == 1

    def test_the_referenced_dispatch_goes_out_and_is_marked_late(self):
        """Advancing the clock never re-derived the frozen deadline or the money.

        PRD §3.9: "`notify_deadline_utc` is the logical clock's `current_utc` at
        creation plus 72 hours. It is **frozen** on the row and never recomputed"

        Design: Corner/validations/a_dispatch_after_the_notify_deadline_needs_a_regulator_reference
        """
        world = _advisory_notice_past_its_deadline()
        obligation = world["obligation"]
        validate_error(
            api_client.dispatch_notification_obligation(
                obligation["id"], {"channel": "SMS"}, OFFICER
            ),
            ApiErrorId.ERR_LATE_NOTIFICATION_UNREFERENCED,
        )

        dispatched = validate_success(
            api_client.dispatch_notification_obligation(
                obligation["id"],
                {"channel": "SMS", "regulator_reference": "REG-2026-771"},
                OFFICER,
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        assert dispatched["dispatched_channel"] == "SMS"
        assert dispatched["regulator_reference"] == "REG-2026-771"
        assert dispatched["late_dispatch"] is True
        assert dispatched["compensation_cents"] == 94215
        assert_timestamp_equals(
            dispatched["notify_deadline_utc"],
            "2026-08-04T00:00:00Z",
            "notify_deadline_utc",
        )
        assert read_leg(world["leg"]["id"], world["planner"])["open_obligation_count"] == 0


# ─── Rule 8: an entity-backed planner may only write its own plan ─────────

def _plan_owned_by_the_home_carrier():
    """HX's empty W26-O1 plan, plus XP's planner standing outside it."""
    ref = setup_reference_data(("FRA", "MUC"), with_partner=True)
    ref["version"] = create_schedule_version(
        ref["carrier"]["id"], ref["season"]["id"], version_label="W26-O1"
    )
    ref["intruder"] = make_network_planner_headers(ref["partner"]["id"])
    ref["payload"] = lambda flight_number: create_flight_leg_payload(
        ref["version"]["id"],
        ref["stations"]["FRA"]["id"],
        ref["stations"]["MUC"]["id"],
        "2026-11-02T08:00:00.000Z",
        "2026-11-02T09:00:00.000Z",
        flight_number=flight_number,
    )
    return ref


class TestWritingIntoAnotherCarriersPlanIsForbidden:
    """The role is permitted on the endpoint; only the principal is wrong."""

    def test_the_other_carriers_planner_cannot_create_a_leg(self):
        """The ownership check compares the version's carrier to the acting id.

        PRD §2.1: "Ownership checks on any resource that references a `Carrier`
        compare that resource's carrier foreign key to `X-User-ID`: the
        `carrier_id` of the schedule version for schedule and leg writes"

        Design: Corner/validations/writing_into_another_carriers_schedule_version_is_forbidden
        """
        ref = _plan_owned_by_the_home_carrier()

        validate_error(
            api_client.create_flight_leg(ref["payload"]("XP900"), ref["intruder"]),
            ApiErrorId.ERR_OWNERSHIP_MISMATCH,
            expected_status=403,
        )

        assert read_version(ref["version"]["id"], ref["planner"])["leg_count"] == 0

    def test_the_owning_planner_creates_the_identical_geometry(self):
        """Same payload, same endpoint, different principal.

        PRD §2.1: "Any mismatch in either case is `ERR_OWNERSHIP_MISMATCH` (HTTP
        403), and it applies to every write against a schedule version, a flight
        leg, a slot holding, or a slot transaction."

        Design: Corner/validations/writing_into_another_carriers_schedule_version_is_forbidden
        """
        ref = _plan_owned_by_the_home_carrier()
        validate_error(
            api_client.create_flight_leg(ref["payload"]("XP900"), ref["intruder"]),
            ApiErrorId.ERR_OWNERSHIP_MISMATCH,
        )

        leg = validate_success(
            api_client.create_flight_leg(ref["payload"]("HX101"), ref["planner"]),
            expected_status=201,
        )
        assert leg["status"] == "DRAFT"
        assert read_version(ref["version"]["id"], ref["planner"])["leg_count"] == 1

    def test_the_intruder_cannot_retime_the_leg_either(self):
        """The same guard covers the retime endpoint on an existing row.

        PRD §2.1: "Any mismatch in either case is `ERR_OWNERSHIP_MISMATCH` (HTTP
        403), and it applies to every write against a schedule version, a flight
        leg, a slot holding, or a slot transaction."

        Design: Corner/validations/writing_into_another_carriers_schedule_version_is_forbidden
        """
        ref = _plan_owned_by_the_home_carrier()
        leg = validate_success(
            api_client.create_flight_leg(ref["payload"]("HX101"), ref["planner"]),
            expected_status=201,
        )

        validate_error(
            api_client.patch_flight_leg(
                leg["id"],
                {
                    "dep_utc": "2026-11-02T10:00:00.000Z",
                    "arr_utc": "2026-11-02T11:00:00.000Z",
                },
                ref["intruder"],
            ),
            ApiErrorId.ERR_OWNERSHIP_MISMATCH,
            expected_status=403,
        )

        stored = read_leg(leg["id"], ref["planner"])
        assert_timestamp_equals(stored["dep_utc"], "2026-11-02T08:00:00Z", "dep_utc")
        assert_timestamp_equals(stored["arr_utc"], "2026-11-02T09:00:00Z", "arr_utc")

        rows, meta = validate_paginated(
            api_client.list_flight_legs(
                ref["planner"], params={"schedule_version_id": ref["version"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == leg["id"]
