"""Declared lifecycles: initial states, side effects fired on creation, refused
undeclared moves, terminal lockdown, missing preconditions and the automatic
reversion a closed river forces on a cleared crew.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    api_client,
    assert_damage_report,
    assert_heat,
    assert_heat_lane_counts_conserved,
    assert_member,
    assert_race_lane,
    assert_regatta_entry,
    assert_shell,
    assert_water_condition_reading,
    assert_water_session,
    validate_error,
    validate_paginated,
)
from test_helpers.fixtures import (
    add_single,
    book_session,
    build_provisional_heat,
    cancel_session,
    clear_session,
    enrol_athlete,
    file_damage,
    lanes_of_heat,
    make_confirmed_single_entry,
    move_member_to,
    officialize_heat,
    open_entry,
    open_regatta,
    post_closed_reading,
    post_open_reading,
    read_entry,
    read_heat,
    read_lane,
    read_member,
    read_regatta,
    read_report,
    read_session,
    read_shell,
    schedule_heat,
    set_clock_to,
    triage_report,
)

OFFICIALIZATION_CLOCK = "2026-08-12T09:30:00Z"


@pytest.fixture
def cleared_practice_outing(cast, single_shell):
    """One 06:00-07:00 practice outing cleared against an open river."""
    rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    reading = post_open_reading(cast["officer_headers"], observed_at="2026-08-01T05:00:00Z")
    session = book_session(
        single_shell["id"],
        cast["coach_headers"],
        coach_member_id=cast["coach"]["id"],
        athlete_member_ids=[rower["id"]],
    )
    session = clear_session(session["id"], reading["id"], cast["officer_headers"])
    return {"shell": single_shell, "session": session, "rower": rower, "reading": reading}


@pytest.fixture
def later_cleared_outing(cast, single_shell):
    """An 08:00-09:00 outing cleared against a 05:00 open reading."""
    rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
    reading = post_open_reading(cast["officer_headers"], observed_at="2026-08-01T05:00:00Z")
    session = book_session(
        single_shell["id"],
        cast["coach_headers"],
        planned_start_at="2026-08-01T08:00:00Z",
        planned_end_at="2026-08-01T09:00:00Z",
        coach_member_id=cast["coach"]["id"],
        athlete_member_ids=[rower["id"]],
    )
    session = clear_session(session["id"], reading["id"], cast["officer_headers"])
    return {"shell": single_shell, "session": session, "rower": rower}


@pytest.fixture
def triaged_major_report(cast, single_shell):
    """A MAJOR report triaged for repair but with no bay reserved yet."""
    report = file_damage(
        single_shell["id"], cast["reporter"]["id"], cast["reporter_headers"], severity="MAJOR"
    )
    report = triage_report(report["id"], cast["boatman_headers"])
    return {"shell": single_shell, "report": report}


class TestInitialStates:
    def test_a_new_entry_opens_in_draft_carrying_no_fees(self, cast, single_shell, home_regatta):
        """Fees are only computed at submission, so a draft carries zeros.

        PRD: "A new entry is `DRAFT`, with `base_fee_cents`,
        `transport_levy_cents`, `late_fee_cents` and `total_fee_cents` all 0,
        `refund_cents` null, `submitted_at` null, and `trailer_load_id`,
        `rack_tier` and `rack_position` all null."

        Design: Corner/state_machines/corner_regatta_entry_initial_state_is_draft_with_zero_fees
        """
        entry = assert_regatta_entry(
            open_entry(
                home_regatta["id"],
                single_shell["id"],
                cast["coach_headers"],
                seed_time_seconds=380.0,
            )
        )
        assert entry["status"] == "DRAFT", (
            f"a newly opened entry is a draft, got {entry['status']}"
        )
        assert entry["submitted_at"] is None, (
            f"nothing has been submitted yet, got {entry['submitted_at']}"
        )
        assert entry["refund_cents"] is None, (
            f"no refund has been computed, got {entry['refund_cents']}"
        )
        assert entry["rack_tier"] is None, (
            f"a draft holds no rack placement, got {entry['rack_tier']}"
        )
        assert entry["trailer_load_id"] is None, (
            f"a draft names no trailer load, got {entry['trailer_load_id']}"
        )
        for field in (
            "base_fee_cents",
            "transport_levy_cents",
            "late_fee_cents",
            "total_fee_cents",
        ):
            assert entry[field] == 0, (
                f"{field} is zero until the entry is submitted, got {entry[field]}"
            )

        regatta = read_regatta(home_regatta["id"])
        assert regatta["status"] == "OPEN_FOR_ENTRY", (
            f"the regatta is still taking entries, got {regatta['status']}"
        )
        assert regatta["net_fee_cents"] == 0, (
            f"a draft contributes nothing to the ledger, got {regatta['net_fee_cents']}"
        )


class TestCreationSideEffects:
    def test_a_major_report_takes_its_hull_out_of_service(self, cast, single_shell):
        """Filing MAJOR damage is itself an intervention on the hull.

        PRD: "A report of `MAJOR` or `STRUCTURAL` severity also takes the hull out
        of service, moving it `AVAILABLE → DAMAGED` or `ASSIGNED → DAMAGED`; when
        the hull was `ASSIGNED`, every session in status `PLANNED` or `CLEARED` on
        that hull is cancelled as well."

        Design: Corner/state_machines/corner_major_damage_report_side_effects_on_creation
        """
        report = assert_damage_report(
            file_damage(
                single_shell["id"],
                cast["reporter"]["id"],
                cast["reporter_headers"],
                severity="MAJOR",
            )
        )
        assert report["status"] == "REPORTED", (
            f"a fresh report opens at REPORTED, got {report['status']}"
        )
        assert report["reported_at"].startswith("2026-08-01T00:00:00"), (
            "the report is stamped from the untouched logical clock, got "
            f"{report['reported_at']}"
        )
        assert report["triaged_by_user_id"] is None, (
            f"nobody has triaged it yet, got {report['triaged_by_user_id']}"
        )
        hull = assert_shell(read_shell(single_shell["id"]))
        assert hull["status"] == "DAMAGED", (
            f"the hull is pulled out of service, got {hull['status']}"
        )

    def test_an_undecayed_major_deduction_drops_both_indices_to_eighty_two(
        self, cast, single_shell
    ):
        """Both indices read 100 less the report's full severity weight.

        PRD: "The report's raw severity weight is 2 points for `COSMETIC`, 6 for
        `MINOR`, 18 for `MAJOR` and 40 for `STRUCTURAL`; from it the server
        subtracts 0.5 points per completed decay period, and the result is floored
        at zero."

        Design: Corner/state_machines/corner_major_damage_report_side_effects_on_creation
        """
        report = assert_damage_report(
            file_damage(
                single_shell["id"],
                cast["reporter"]["id"],
                cast["reporter_headers"],
                severity="MAJOR",
            )
        )
        assert report["severity_points"] == pytest.approx(18.0, abs=0.01), (
            "a report filed on the same instant it is observed has completed no "
            f"decay period, so it weighs the full 18 points, got {report['severity_points']}"
        )
        hull = assert_shell(read_shell(single_shell["id"]))
        assert hull["condition_index_conservative"] == 82, (
            f"100 less 18 is 82 conservatively, got {hull['condition_index_conservative']}"
        )
        assert hull["condition_index_optimistic"] == 82, (
            "a REPORTED report counts in full on both readings, got "
            f"{hull['condition_index_optimistic']}"
        )


class TestUndeclaredMembersMoves:
    def test_reaffirming_an_active_member_is_not_a_declared_path(self):
        """ACTIVE to ACTIVE is not on the member machine.

        PRD: "Any other `to_status` request — a direct move from `DUES_HOLD` to
        `WITHDRAWN`, say, or a move whose declared precondition does not hold — is
        rejected with `ERR_INVALID_STATUS_TRANSITION`."

        Design: Corner/state_machines/corner_member_status_transition_active_to_active_returns_409
        """
        member = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)

        response = api_client.transition_member(
            member["id"], {"to_status": "ACTIVE"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATUS_TRANSITION.value)

        after = assert_member(read_member(member["id"]))
        assert after["membership_status"] == "ACTIVE", (
            f"the refused request leaves the standing untouched, got {after['membership_status']}"
        )
        assert after["boathouse_access_level"] == "FULL", (
            f"access is unchanged as well, got {after['boathouse_access_level']}"
        )

    def test_a_withdrawn_member_cannot_be_reactivated(self):
        """Withdrawal is the member machine's one terminal state.

        PRD: "Terminal-state guard — `ERR_ALREADY_TERMINAL`. Applies to every
        state-changing write **except** dues payment and dues true-up, which are
        carved out so that the more specific money-domain rule at rung 55 reports
        `ERR_INVOICE_NOT_PAYABLE` instead. Voiding an invoice is *not* carved out
        and remains under this rung."

        Design: Corner/state_machines/corner_member_withdrawn_is_terminal_and_reactivation_returns_409
        """
        member = enrol_athlete("Gone Rower", "RECREATIONAL", 70.0)
        withdrawn = assert_member(move_member_to(member["id"], "WITHDRAWN"))
        assert withdrawn["membership_status"] == "WITHDRAWN", (
            f"the member resigns ACTIVE -> WITHDRAWN, got {withdrawn['membership_status']}"
        )

        response = api_client.transition_member(
            member["id"], {"to_status": "ACTIVE"}, CLUB_ADMIN_HEADERS
        )
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)

        after = assert_member(read_member(member["id"]))
        assert after["membership_status"] == "WITHDRAWN", (
            f"the refusal leaves the member resigned, got {after['membership_status']}"
        )
        assert after["boathouse_access_level"] == "NONE", (
            "withdrawal recomputes access to NONE and the refusal does not undo it, "
            f"got {after['boathouse_access_level']}"
        )


class TestMissingPreconditions:
    def test_launching_an_uncleared_outing_is_refused(self, cast, single_shell):
        """Only a cleared crew goes afloat.

        PRD: "A `SafetyOfficer` logs a `CLEARED` crew onto the water, optionally
        with a `note`, permitted only while the logical clock is at or after
        `planned_start_at` and strictly before `planned_end_at`; a session in any
        other status fails with `ERR_SESSION_NOT_CLEARED`."

        Design: Corner/state_machines/corner_session_launch_before_clearance_returns_409_not_cleared
        """
        rower = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        session = book_session(
            single_shell["id"],
            cast["coach_headers"],
            coach_member_id=cast["coach"]["id"],
            athlete_member_ids=[rower["id"]],
        )
        set_clock_to("2026-08-01T06:00:00Z")

        response = api_client.launch_water_session(session["id"], {}, cast["officer_headers"])
        validate_error(response, ApiErrorId.ERR_SESSION_NOT_CLEARED.value)

        after = assert_water_session(read_session(session["id"]))
        assert after["status"] == "PLANNED", (
            f"the outing stays merely booked, got {after['status']}"
        )
        assert after["reading_id"] is None, (
            f"no clearance decision was ever recorded, got {after['reading_id']}"
        )
        assert read_shell(single_shell["id"])["status"] == "AVAILABLE", (
            "an unlaunched outing never reserves its hull"
        )

    def test_seeding_before_the_regatta_is_racing_is_refused(self, cast):
        """Lane seeding is a race-day act, whatever the candidate pool looks like.

        PRD: "Lane assignment, run by a `RaceOfficial` and optionally annotated
        with a `note`, requires the heat's regatta to be `RACING`
        (`ERR_REGATTA_NOT_RACING`)."

        Design: Corner/state_machines/corner_assign_lanes_before_regatta_racing_returns_409_not_racing
        """
        regatta = open_regatta()
        shell = add_single(hull_name="Kingfisher")
        rower = enrol_athlete("Row One", "COMPETITIVE", 82.0)
        entry = make_confirmed_single_entry(
            regatta,
            shell,
            rower["id"],
            cast["coach_headers"],
            cast["official_headers"],
            seed_time_seconds=380.0,
        )
        heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=4)

        response = api_client.assign_lanes(heat["id"], {}, cast["official_headers"])
        validate_error(response, ApiErrorId.ERR_REGATTA_NOT_RACING.value)

        after = assert_heat_lane_counts_conserved(assert_heat(read_heat(heat["id"])))
        assert after["status"] == "SCHEDULED", (
            f"the heat is still merely scheduled, got {after['status']}"
        )
        assert after["occupied_lane_count"] == 0, (
            f"no lane was drawn, got {after['occupied_lane_count']}"
        )
        assert after["free_lane_count"] == 4, (
            f"all four lanes remain free, got {after['free_lane_count']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_race_lanes(cast["official_headers"], {"heat_id": heat["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the refused draw wrote no lane rows, got {meta['total_count']}"
        )
        assert read_entry(entry["id"])["status"] == "CONFIRMED", (
            "the confirmed crew is untouched, so the refusal is about the regatta's "
            "state and not an empty candidate pool"
        )

    def test_verifying_an_unscheduled_repair_is_refused(self, cast, triaged_major_report):
        """VERIFIED is only reachable from REPAIR_SCHEDULED.

        PRD: "An `EquipmentManager` other than the reporter verifies a
        `REPAIR_SCHEDULED` report, optionally with a `note`, but only once the
        logical clock has reached or passed `repair_window_end_at`; earlier
        attempts fail on that precondition, and a report in any other status fails
        with `ERR_REPORT_NOT_SCHEDULED`."

        Design: Corner/state_machines/corner_verify_repair_from_triaged_returns_409_not_scheduled
        """
        report_id = triaged_major_report["report"]["id"]
        response = api_client.verify_repair(
            report_id, {"note": "looks fine to me"}, cast["boatman_headers"]
        )
        validate_error(response, ApiErrorId.ERR_REPORT_NOT_SCHEDULED.value)

        after = assert_damage_report(read_report(report_id))
        assert after["status"] == "TRIAGED", (
            f"the report is still awaiting a bay, got {after['status']}"
        )
        assert after["assigned_repair_bay"] is None, (
            f"no bay was ever reserved, got {after['assigned_repair_bay']}"
        )
        hull = assert_shell(read_shell(triaged_major_report["shell"]["id"]))
        assert hull["status"] == "DAMAGED", (
            f"the hull is not returned to service, got {hull['status']}"
        )
        assert hull["condition_index_conservative"] == 82, (
            "a TRIAGED report still counts in full, so the index stays at 82, got "
            f"{hull['condition_index_conservative']}"
        )


class TestTerminalLockdown:
    def test_officializing_a_heat_twice_is_not_idempotent(self, cast):
        """RESULTS_OFFICIAL is the heat machine's terminal state.

        PRD: "The heat moves `RESULTS_PROVISIONAL → RESULTS_OFFICIAL`, which is
        terminal. `OFFICIAL` and `VOIDED` are the lane's terminal states;
        `DISQUALIFIED` is deliberately not terminal, because a later denial can
        restore a disqualified lane as described in §3.9."

        Design: Corner/state_machines/corner_heat_officialize_twice_returns_409_already_terminal
        """
        scenario = build_provisional_heat(cast, entry_count=1, lane_count=4)
        heat_id = scenario["heat"]["id"]
        set_clock_to(OFFICIALIZATION_CLOCK)
        first = assert_heat(officialize_heat(heat_id, cast["official_headers"]))
        assert first["status"] == "RESULTS_OFFICIAL", (
            f"the first call makes the results official, got {first['status']}"
        )

        response = api_client.officialize_heat(heat_id, {}, cast["official_headers"])
        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value)

        after = assert_heat(read_heat(heat_id))
        assert after["status"] == "RESULTS_OFFICIAL", (
            f"the refusal leaves the heat official, got {after['status']}"
        )
        assert after["protest_window_closes_at"] == scenario["heat"][
            "protest_window_closes_at"
        ], (
            "the jury window instant is not moved by the refused second call, "
            f"got {after['protest_window_closes_at']}"
        )

    def test_the_second_officialization_runs_no_second_advancement_pass(self, cast):
        """A final advances nobody, and the single crew moves to RACED exactly once.

        PRD: "Every lane still `PROVISIONAL` moves `PROVISIONAL → OFFICIAL`; a
        lane that the jury disqualified stays `DISQUALIFIED`. Advancement selection
        then runs, and every entry holding an `OFFICIAL` or `DISQUALIFIED` lane on
        this heat moves `CONFIRMED → RACED`."

        Design: Corner/state_machines/corner_heat_officialize_twice_returns_409_already_terminal
        """
        scenario = build_provisional_heat(cast, entry_count=1, lane_count=4)
        heat_id = scenario["heat"]["id"]
        set_clock_to(OFFICIALIZATION_CLOCK)
        officialize_heat(heat_id, cast["official_headers"])
        api_client.officialize_heat(heat_id, {}, cast["official_headers"])

        lanes = lanes_of_heat(heat_id)
        assert len(lanes) == 1, f"the heat drew one lane, got {len(lanes)}"
        lane = assert_race_lane(read_lane(lanes[0]["id"]))
        assert lane["lane_status"] == "OFFICIAL", (
            f"the surviving lane is made official, got {lane['lane_status']}"
        )
        assert lane["place"] == 1, (
            f"the only finisher places first, got {lane['place']}"
        )
        assert lane["advanced"] is False, (
            "nothing advances out of a heat whose advances_to_heat_id is null, got "
            f"{lane['advanced']}"
        )
        entry = assert_regatta_entry(read_entry(scenario["entries"][0]["id"]))
        assert entry["status"] == "RACED", (
            f"the crew moves CONFIRMED -> RACED exactly once, got {entry['status']}"
        )


class TestReleasingAndRevertingCrews:
    def test_cancelling_a_cleared_outing_hands_the_hull_back(self, cast, cleared_practice_outing):
        """Cancelling from CLEARED runs the hull-release side effect.

        PRD: "A `Coach` or `SafetyOfficer` may instead cancel a session with a
        stated `reason` while it is `PLANNED` or `CLEARED` — `PLANNED → CANCELLED`
        or `CLEARED → CANCELLED`; cancelling from `CLEARED` releases the hull
        `ASSIGNED → AVAILABLE`."

        Design: Corner/state_machines/corner_cancel_cleared_session_releases_hull
        """
        scenario = cleared_practice_outing
        assert read_shell(scenario["shell"]["id"])["status"] == "ASSIGNED", (
            "the cleared outing holds its hull before the cancellation"
        )

        cancelled = assert_water_session(
            cancel_session(
                scenario["session"]["id"], cast["coach_headers"], reason="thunderstorm forecast"
            )
        )
        assert cancelled["status"] == "CANCELLED", (
            f"the outing is called off, got {cancelled['status']}"
        )
        assert cancelled["actual_return_at"] is None, (
            f"nobody went afloat, so no return is stamped, got {cancelled['actual_return_at']}"
        )
        assert read_shell(scenario["shell"]["id"])["status"] == "AVAILABLE", (
            "the cancellation releases the hull back to the rack"
        )

    def test_a_cancelled_outing_is_never_logged_water_time(self, cast, cleared_practice_outing):
        """Only returned outings count towards a member's usage.

        PRD: "`logged_session_count` is the number of water sessions in status
        `RETURNED` whose `athlete_member_ids` array contains this member's `id`."

        Design: Corner/state_machines/corner_cancel_cleared_session_releases_hull
        """
        scenario = cleared_practice_outing
        cancel_session(
            scenario["session"]["id"], cast["coach_headers"], reason="thunderstorm forecast"
        )

        rower = assert_member(read_member(scenario["rower"]["id"]))
        assert rower["logged_session_count"] == 0, (
            "a cancelled outing is not water time, got "
            f"{rower['logged_session_count']}"
        )

    def test_a_closed_reading_reverts_a_later_cleared_outing(self, cast, later_cleared_outing):
        """Posting a closed reading is itself an intervention on cleared crews.

        PRD: "Every session in status `CLEARED` whose `planned_start_at` falls
        after the new reading's `observed_at` is reverted `CLEARED → PLANNED`, its
        `reading_id` reset to null and its `required_launch_count` reset to 0, and
        its hull released `ASSIGNED → AVAILABLE`."

        Design: Corner/state_machines/corner_closed_reading_reverts_cleared_session_to_planned
        """
        scenario = later_cleared_outing
        closed = assert_water_condition_reading(
            post_closed_reading(cast["officer_headers"], observed_at="2026-08-01T06:00:00Z")
        )
        assert closed["posture"] == "CLOSED", (
            f"a 22-knot wind shuts the river, got {closed['posture']}"
        )

        session = assert_water_session(read_session(scenario["session"]["id"]))
        assert session["status"] == "PLANNED", (
            f"the outing is reverted CLEARED -> PLANNED, got {session['status']}"
        )
        assert session["reading_id"] is None, (
            f"the stale clearance decision is discarded, got {session['reading_id']}"
        )
        assert session["required_launch_count"] == 0, (
            f"the launch requirement is reset, got {session['required_launch_count']}"
        )
        assert read_shell(scenario["shell"]["id"])["status"] == "AVAILABLE", (
            "the reverted outing hands its hull back"
        )

    def test_a_closing_wind_is_not_a_cold_water_finding(self, cast, later_cleared_outing):
        """The closing condition here is wind alone, not temperature.

        PRD: "The `posture` is then decided in order: it is `CLOSED` when the
        sustained wind is 20.0 knots or more, or the visibility is 400 metres or
        less."

        Design: Corner/state_machines/corner_closed_reading_reverts_cleared_session_to_planned
        """
        closed = assert_water_condition_reading(
            post_closed_reading(
                cast["officer_headers"],
                observed_at="2026-08-01T06:00:00Z",
                wind_speed_kt=25.0,
                air_temp_c=20.0,
                water_temp_c=18.0,
                visibility_m=3000,
            )
        )
        assert closed["cold_water_flag"] is False, (
            "18.0-degree water with a combined sum of 38.0 is not cold, got "
            f"{closed['cold_water_flag']}"
        )
        assert closed["posture"] == "CLOSED", (
            f"25.0 knots is at or above the closing threshold, got {closed['posture']}"
        )
        session = assert_water_session(read_session(later_cleared_outing["session"]["id"]))
        assert session["status"] == "PLANNED", (
            "the reversion follows from the posture alone, got "
            f"{session['status']}"
        )
