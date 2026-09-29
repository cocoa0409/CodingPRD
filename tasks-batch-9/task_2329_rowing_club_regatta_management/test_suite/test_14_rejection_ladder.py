"""Refusals along the rejection ladder: the header gate, the entity-specific 404s,
and the status, window, capacity and cross-reference guards that stand in front of
outings, repairs, entries, weigh-ins, lane draws, trailer racks and the jury.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    api_client,
    assert_damage_report,
    assert_heat,
    assert_lineup_seat,
    assert_protest,
    assert_race_lane,
    assert_regatta_entry,
    assert_trailer_load,
    assert_water_session,
    build_user_headers,
    make_member_headers,
    validate_error,
    validate_paginated,
)
from test_helpers.factories import (
    create_heat_payload,
    create_protest_payload,
    create_shell_payload,
)
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    assign_lanes,
    book_session,
    build_racing_regatta_with_lanes,
    clear_session,
    coxswain_seat_of_entry,
    declare_coxed_four_lineup,
    drive_regatta_to_racing,
    enrol_athlete,
    enrol_coxswain,
    file_damage,
    file_protest,
    lane_of_entry,
    make_confirmed_single_entry,
    make_submitted_single_entry,
    move_trailer_to,
    open_away_regatta,
    open_entry,
    open_regatta,
    open_trailer_load,
    post_results,
    post_results_for_all_pending,
    rack_entry,
    read_entry,
    read_heat,
    read_lane,
    read_member,
    read_protest,
    read_regatta,
    read_report,
    read_session,
    read_shell,
    read_trailer,
    schedule_heat,
    set_clock_to,
    submit_entry,
)

UNRECOGNISED_ROLE = "Commodore"
LANE_DRAW_CLOCK = "2026-08-12T08:30:00Z"
RACE_START_CLOCK = "2026-08-12T09:00:00Z"
WEIGH_IN_CLOSE_INSTANT = "2026-08-12T07:00:00Z"
PROTEST_WINDOW_CLOSE_PREFIX = "2026-08-12T09:30:00"
PAST_PROTEST_WINDOW_CLOCK = "2026-08-12T09:31:00Z"
COXED_FOUR_HOME_FEE_CENTS = 13500
DEFAULT_RACK_CAPACITY = 16


def _away_regatta_with_two_submitted_singles(cast, **trailer_overrides):
    """An away regatta with two on-time submitted singles and a fresh OPEN load."""
    regatta = open_away_regatta(name="Lakeside Sprints", host_club="Lakeside RC")
    shell_a = add_single(hull_name="Kingfisher")
    shell_b = add_single(hull_name="Heron", hull_weight_kg=14.5, home_bay="BAY-2")
    rower_a = enrol_athlete("Row One", "COMPETITIVE", 82.0)
    rower_b = enrol_athlete("Row Two", "COMPETITIVE", 83.0)
    entry_a = make_submitted_single_entry(
        regatta, shell_a, rower_a["id"], cast["coach_headers"], seed_time_seconds=370.0
    )
    entry_b = make_submitted_single_entry(
        regatta, shell_b, rower_b["id"], cast["coach_headers"], seed_time_seconds=390.0
    )
    trailer = open_trailer_load(
        regatta["id"],
        cast["driver"]["id"],
        cast["boatman_headers"],
        tow_vehicle_code="TOW-1",
        depart_at="2026-08-11T12:00:00Z",
        **trailer_overrides,
    )
    return {
        "regatta": regatta,
        "entry_a": entry_a,
        "entry_b": entry_b,
        "trailer": trailer,
    }


@pytest.fixture
def single_unit_rack_already_full(cast):
    """A one-tier, one-unit rack holding the first single, with a second waiting."""
    scenario = _away_regatta_with_two_submitted_singles(
        cast, rack_tier_count=1, rack_units_per_tier=1
    )
    scenario["trailer"] = rack_entry(
        scenario["trailer"], scenario["entry_a"]["id"], cast["boatman_headers"]
    )
    return scenario


@pytest.fixture
def sealed_load_with_a_spare_single(cast):
    """A four-by-four rack holding one single, then sealed, with a second waiting."""
    scenario = _away_regatta_with_two_submitted_singles(cast)
    scenario["trailer"] = rack_entry(
        scenario["trailer"], scenario["entry_a"]["id"], cast["boatman_headers"]
    )
    scenario["trailer"] = move_trailer_to(
        scenario["trailer"]["id"], "SEALED", cast["boatman_headers"]
    )
    return scenario


@pytest.fixture
def declared_coxed_four(cast):
    """A 4+ entry at LINEUP_DECLARED with a certified coxswain in seat 0."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    shell = add_coxed_four(hull_name="Cormorant", hull_weight_kg=51.0, home_bay="BAY-4")
    cox = enrol_coxswain("Cara Cox", 52.0)
    rowers = [
        enrol_athlete(f"Row {index}", "COMPETITIVE", 81.0 + index) for index in range(1, 5)
    ]
    entry = open_entry(
        regatta["id"],
        shell["id"],
        cast["coach_headers"],
        event_code="M4PLUS_OPEN",
        boat_class="4+",
        seed_time_seconds=400.0,
    )
    entry = declare_coxed_four_lineup(
        entry, cox["id"], [rower["id"] for rower in rowers], cast["coach_headers"]
    )
    return {"regatta": regatta, "shell": shell, "cox": cox, "entry": entry}


@pytest.fixture
def two_heats_one_with_results(cast):
    """Two sibling heats in different events; only the first has results posted."""
    regatta = open_regatta(name="Club Head Race", host_club="Home RC")
    shell_a = add_single(hull_name="Kingfisher")
    shell_b = add_single(hull_name="Heron", hull_weight_kg=14.5, home_bay="BAY-2")
    rower_a = enrol_athlete("Row One", "COMPETITIVE", 82.0)
    rower_b = enrol_athlete("Row Two", "COMPETITIVE", 83.0)
    entry_a = make_confirmed_single_entry(
        regatta,
        shell_a,
        rower_a["id"],
        cast["coach_headers"],
        cast["official_headers"],
        event_code="M1X_OPEN",
        seed_time_seconds=370.0,
    )
    entry_b = make_confirmed_single_entry(
        regatta,
        shell_b,
        rower_b["id"],
        cast["coach_headers"],
        cast["official_headers"],
        event_code="M1X_MASTERS",
        seed_time_seconds=400.0,
    )
    heat_a = schedule_heat(
        regatta["id"], cast["official_headers"], event_code="M1X_OPEN", lane_count=4
    )
    heat_b = schedule_heat(
        regatta["id"],
        cast["official_headers"],
        event_code="M1X_MASTERS",
        scheduled_start_at="2026-08-12T09:10:00Z",
        lane_count=4,
    )
    drive_regatta_to_racing(regatta, racing_clock=RACE_START_CLOCK)
    assign_lanes(heat_a["id"], cast["official_headers"])
    assign_lanes(heat_b["id"], cast["official_headers"])
    lane_a = lane_of_entry(entry_a["id"])
    lane_b = lane_of_entry(entry_b["id"])
    heat_a = post_results(heat_a["id"], [(lane_a["id"], 371.0)], cast["official_headers"])
    return {
        "regatta": regatta,
        "heat_a": heat_a,
        "heat_b": heat_b,
        "lane_a": lane_a,
        "lane_b": lane_b,
        "filer": rower_a,
        "filer_headers": make_member_headers(rower_a["id"]),
    }


class TestHeaderGate:
    def test_a_request_carrying_no_identity_at_all_is_turned_away(self):
        """The header check precedes everything, including a well-formed body.

        PRD: "Every request must carry two headers: `X-User-ID`, identifying the
        acting user, and `X-User-Role`, declaring the capacity they are acting in.
        If either header is absent, or if `X-User-Role` is not one of the seven
        declared roles, the request is rejected with `ERR_MISSING_AUTH_HEADERS`
        (HTTP 401)."

        Design: Corner/errors/corner_request_without_auth_headers_returns_401
        """
        response = api_client.create_shell(
            create_shell_payload(), {"Content-Type": "application/json"}
        )
        validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)

        _rows, meta = validate_paginated(api_client.list_shells(CLUB_ADMIN_HEADERS))
        assert meta["total_count"] == 0, (
            f"the refused request stored nothing, got {meta['total_count']} hulls"
        )

    def test_a_role_the_club_does_not_recognise_is_turned_away_too(self):
        """An unrecognised capacity is treated as no capacity, not as a 403.

        PRD: "If either header is absent, or if `X-User-Role` is not one of the
        seven declared roles, the request is rejected with
        `ERR_MISSING_AUTH_HEADERS` (HTTP 401). If the headers are well formed but
        the declared role is not authorised for the requested operation, the
        rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/errors/corner_request_without_auth_headers_returns_401
        """
        response = api_client.create_shell(
            create_shell_payload(), build_user_headers("test-member-1", UNRECOGNISED_ROLE)
        )
        error = validate_error(response, ApiErrorId.ERR_MISSING_AUTH_HEADERS.value)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value, (
            "an unknown role fails the header gate, not the authorisation gate, got "
            f"{error['error_id']}"
        )

        _rows, meta = validate_paginated(api_client.list_shells(CLUB_ADMIN_HEADERS))
        assert meta["total_count"] == 0, (
            f"the refused request stored nothing, got {meta['total_count']} hulls"
        )


class TestEntitySpecificNotFound:
    def test_the_club_records_each_answer_with_their_own_not_found_code(self):
        """Members, invoices, hulls, reports, readings and outings each own a code.

        PRD: "Identifiers in a request path are resolved left to right, and the
        first identifier that does not resolve ends the request with that entity's
        own 404 error rather than a generic one."

        Design: Corner/errors/corner_unknown_path_ids_return_entity_specific_not_found
        """
        cases = [
            (api_client.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
            (api_client.get_dues_invoice, ApiErrorId.ERR_DUES_INVOICE_NOT_FOUND),
            (api_client.get_shell, ApiErrorId.ERR_SHELL_NOT_FOUND),
            (api_client.get_damage_report, ApiErrorId.ERR_DAMAGE_REPORT_NOT_FOUND),
            (api_client.get_water_condition_reading, ApiErrorId.ERR_READING_NOT_FOUND),
            (api_client.get_water_session, ApiErrorId.ERR_SESSION_NOT_FOUND),
        ]
        for getter, expected in cases:
            error = validate_error(
                getter(NON_EXISTENT_UUID, CLUB_ADMIN_HEADERS), expected.value
            )
            assert error["message"], (
                f"{expected.value} still carries a human-readable message"
            )

    def test_the_race_day_records_each_answer_with_their_own_not_found_code(self):
        """Regattas, entries, seats, heats, lanes, protests and loads likewise.

        PRD: "The entity-specific codes are `ERR_MEMBER_NOT_FOUND`,
        `ERR_DUES_INVOICE_NOT_FOUND`, `ERR_SHELL_NOT_FOUND`,
        `ERR_DAMAGE_REPORT_NOT_FOUND`, `ERR_READING_NOT_FOUND`,
        `ERR_SESSION_NOT_FOUND`, `ERR_REGATTA_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
        `ERR_SEAT_NOT_FOUND`, `ERR_HEAT_NOT_FOUND`, `ERR_LANE_NOT_FOUND`,
        `ERR_PROTEST_NOT_FOUND` and `ERR_TRAILER_NOT_FOUND`."

        Design: Corner/errors/corner_unknown_path_ids_return_entity_specific_not_found
        """
        cases = [
            (api_client.get_regatta, ApiErrorId.ERR_REGATTA_NOT_FOUND),
            (api_client.get_regatta_entry, ApiErrorId.ERR_ENTRY_NOT_FOUND),
            (api_client.get_lineup_seat, ApiErrorId.ERR_SEAT_NOT_FOUND),
            (api_client.get_heat, ApiErrorId.ERR_HEAT_NOT_FOUND),
            (api_client.get_race_lane, ApiErrorId.ERR_LANE_NOT_FOUND),
            (api_client.get_protest, ApiErrorId.ERR_PROTEST_NOT_FOUND),
            (api_client.get_trailer_load, ApiErrorId.ERR_TRAILER_NOT_FOUND),
        ]
        for getter, expected in cases:
            error = validate_error(
                getter(NON_EXISTENT_UUID, CLUB_ADMIN_HEADERS), expected.value
            )
            assert error["message"], (
                f"{expected.value} still carries a human-readable message"
            )


class TestOutingStatusGuards:
    def test_a_crew_that_never_left_the_dock_cannot_be_logged_back_in(
        self, cast, single_shell, open_reading
    ):
        """The return call insists on a launched outing, and no water time accrues.

        PRD: "Logging the crew back in, again optionally with a `note`, requires
        status `LAUNCHED` (`ERR_SESSION_NOT_LAUNCHED`), moves the session `LAUNCHED
        → RETURNED`, stamps `actual_return_at` from the logical clock, releases the
        hull `ASSIGNED → AVAILABLE`, and recomputes `logged_session_count` for every
        member named in `athlete_member_ids`"

        Design: Corner/errors/corner_session_return_before_launch_returns_409
        """
        rita = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)
        session = book_session(
            single_shell["id"],
            cast["coach_headers"],
            coach_member_id=cast["coach"]["id"],
            athlete_member_ids=[rita["id"]],
        )
        clear_session(session["id"], open_reading["id"], cast["officer_headers"])

        response = api_client.return_water_session(
            session["id"], {"note": "back at the dock"}, cast["officer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_SESSION_NOT_LAUNCHED.value)

        stored = assert_water_session(read_session(session["id"]))
        assert stored["status"] == "CLEARED", (
            f"the outing is still only cleared to go afloat, got {stored['status']}"
        )
        assert stored["actual_return_at"] is None, (
            f"no return instant was stamped, got {stored['actual_return_at']}"
        )
        assert read_member(rita["id"])["logged_session_count"] == 0, (
            "an outing that never happened is no water time"
        )
        assert read_shell(single_shell["id"])["status"] == "ASSIGNED", (
            "the hull stays reserved to the cleared outing"
        )


class TestRepairSchedulingGuard:
    def test_a_bay_cannot_be_booked_before_the_boatman_has_triaged(
        self, cast, single_shell
    ):
        """Scheduling reaches for a TRIAGED report and finds one only REPORTED.

        PRD: "Repair scheduling against a report that is not `TRIAGED` fails with
        `ERR_REPORT_NOT_TRIAGED`."

        Design: Corner/errors/corner_schedule_repair_before_triage_returns_409
        """
        report = file_damage(
            single_shell["id"],
            cast["reporter"]["id"],
            cast["reporter_headers"],
            severity="MAJOR",
        )
        assert report["status"] == "REPORTED", (
            f"a freshly filed report is REPORTED, got {report['status']}"
        )

        response = api_client.schedule_repair(
            report["id"],
            {
                "assigned_repair_bay": "BAY-R1",
                "repair_window_start_at": "2026-08-02T08:00:00Z",
                "repair_window_end_at": "2026-08-02T12:00:00Z",
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_REPORT_NOT_TRIAGED.value)

        stored = assert_damage_report(read_report(report["id"]))
        assert stored["status"] == "REPORTED", (
            f"the report has not moved, got {stored['status']}"
        )
        assert stored["assigned_repair_bay"] is None, (
            f"no bay was reserved, got {stored['assigned_repair_bay']}"
        )
        assert stored["repair_window_start_at"] is None, (
            f"no window was persisted, got {stored['repair_window_start_at']}"
        )
        assert stored["repair_window_end_at"] is None, (
            f"no window was persisted, got {stored['repair_window_end_at']}"
        )
        assert read_shell(single_shell["id"])["status"] == "DAMAGED", (
            "the MAJOR report already took the hull out of service, and the refused "
            "scheduling did not move it on to IN_REPAIR"
        )


class TestEntryProgressionGuards:
    def test_a_seatless_entry_cannot_be_sent_to_the_host(
        self, cast, home_regatta, single_shell
    ):
        """Submission reaches for a declared lineup and finds a bare draft.

        PRD: "The regatta must still be `OPEN_FOR_ENTRY`
        (`ERR_REGATTA_ENTRIES_CLOSED`), the entry must be `LINEUP_DECLARED`
        (`ERR_ENTRY_NOT_DECLARED`), the hull's `condition_index_conservative` must be
        at least 60 (`ERR_SHELL_CONDITION_TOO_LOW`)"

        Design: Corner/errors/corner_submit_before_lineup_declared_returns_409
        """
        entry = open_entry(home_regatta["id"], single_shell["id"], cast["coach_headers"])

        response = api_client.submit_regatta_entry(entry["id"], {}, cast["coach_headers"])
        validate_error(response, ApiErrorId.ERR_ENTRY_NOT_DECLARED.value)

        stored = assert_regatta_entry(read_entry(entry["id"]))
        assert stored["status"] == "DRAFT", (
            f"the entry stays a draft, got {stored['status']}"
        )
        assert stored["total_fee_cents"] == 0, (
            f"no fee was assessed, got {stored['total_fee_cents']}"
        )
        assert stored["submitted_at"] is None, (
            f"no submission instant was stamped, got {stored['submitted_at']}"
        )
        assert read_regatta(home_regatta["id"])["net_fee_cents"] == 0, (
            "and the regatta's ledger is untouched"
        )

    def test_a_declared_crew_cannot_be_confirmed_until_it_is_submitted(
        self, cast, declared_entry
    ):
        """Confirmation is the host's answer to a submission, not to a declaration.

        PRD: "A `RaceOfficial` confirms a `SUBMITTED` entry, optionally with a
        `note`; any other status is `ERR_ENTRY_NOT_SUBMITTED`."

        Design: Corner/errors/corner_confirm_before_submit_returns_409
        """
        entry = declared_entry["entry"]
        assert entry["status"] == "LINEUP_DECLARED", (
            f"the entry has a lineup but no submission, got {entry['status']}"
        )

        response = api_client.confirm_regatta_entry(
            entry["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_ENTRY_NOT_SUBMITTED.value)

        stored = assert_regatta_entry(read_entry(entry["id"]))
        assert stored["status"] == "LINEUP_DECLARED", (
            f"the entry has not moved, got {stored['status']}"
        )


class TestResultsGuard:
    def test_results_cannot_be_posted_to_a_heat_with_no_lane_draw(
        self, cast, home_regatta
    ):
        """An empty results array carries no foreign key, so the status guard answers.

        PRD: "A `RaceOfficial` posts results for a `LANES_ASSIGNED` heat — any other
        status is `ERR_HEAT_NOT_ASSIGNED` — by supplying `lane_results`, which must
        carry an `elapsed_seconds` value at one decimal place for every lane on the
        heat currently in `PENDING`."

        Design: Corner/errors/corner_results_before_lanes_assigned_returns_409
        """
        heat = schedule_heat(home_regatta["id"], cast["official_headers"], lane_count=4)

        response = api_client.post_heat_results(
            heat["id"], {"lane_results": []}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_HEAT_NOT_ASSIGNED.value)

        stored = assert_heat(read_heat(heat["id"]))
        assert stored["status"] == "SCHEDULED", (
            f"the heat still awaits its lane draw, got {stored['status']}"
        )
        assert stored["protest_window_closes_at"] is None, (
            "the jury's window opens only when results are posted, got "
            f"{stored['protest_window_closes_at']}"
        )


class TestRackAssignmentGuards:
    def test_a_load_refuses_a_hull_bound_for_a_different_regatta(self, cast):
        """The manifest is per regatta, and free units do not excuse a mismatch.

        PRD: "The load must be `OPEN` — a sealed or departed load refuses both
        assignments and releases with `ERR_TRAILER_SEALED` — and the entry's
        `regatta_id` must match the load's `regatta_id`, or the request fails with
        `ERR_TRAILER_REGATTA_MISMATCH`."

        Design: Corner/errors/corner_rack_assignment_across_regattas_returns_409
        """
        regatta_a = open_away_regatta(name="Lakeside Sprints", host_club="Lakeside RC")
        regatta_b = open_away_regatta(
            name="Riverside Sprints",
            host_club="Riverside RC",
            race_date_at="2026-08-19T08:00:00Z",
            entry_deadline_at="2026-08-17T00:00:00Z",
            scratch_deadline_at="2026-08-18T00:00:00Z",
            weigh_in_opens_at="2026-08-19T06:00:00Z",
            weigh_in_closes_at="2026-08-19T07:00:00Z",
        )
        shell = add_single(hull_name="Kingfisher")
        entry_b = open_entry(regatta_b["id"], shell["id"], cast["coach_headers"])
        trailer = open_trailer_load(
            regatta_a["id"],
            cast["driver"]["id"],
            cast["boatman_headers"],
            tow_vehicle_code="TOW-1",
            depart_at="2026-08-11T12:00:00Z",
        )

        response = api_client.create_rack_assignment(
            trailer["id"],
            {
                "regatta_entry_id": entry_b["id"],
                "expected_trailer_load_version": trailer["version"],
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_TRAILER_REGATTA_MISMATCH.value)

        stored = assert_trailer_load(read_trailer(trailer["id"]))
        assert stored["rack_units_used"] == 0, (
            f"nothing was racked, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == DEFAULT_RACK_CAPACITY, (
            "the whole four-by-four rack is still free, so capacity was never the "
            f"obstacle, got {stored['rack_units_free']}"
        )
        entry = assert_regatta_entry(read_entry(entry_b["id"]))
        assert entry["trailer_load_id"] is None, (
            f"the other regatta's entry holds no load, got {entry['trailer_load_id']}"
        )
        assert entry["rack_tier"] is None, (
            f"and no tier, got {entry['rack_tier']}"
        )
        assert entry["rack_position"] is None, (
            f"and no position, got {entry['rack_position']}"
        )

    def test_a_rack_with_no_free_run_refuses_the_second_single(
        self, cast, single_unit_rack_already_full
    ):
        """The waterfall walks the whole permitted range and finds nowhere to go.

        PRD: "If no such run exists anywhere in the permitted range, the request is
        rejected with `ERR_TRAILER_TIER_UNAVAILABLE`."

        Design: Corner/errors/corner_rack_assignment_without_free_units_returns_409
        """
        scenario = single_unit_rack_already_full
        trailer = scenario["trailer"]

        response = api_client.create_rack_assignment(
            trailer["id"],
            {
                "regatta_entry_id": scenario["entry_b"]["id"],
                "expected_trailer_load_version": trailer["version"],
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_TRAILER_TIER_UNAVAILABLE.value)

        stored = assert_trailer_load(read_trailer(trailer["id"]))
        assert stored["rack_unit_capacity"] == 1, (
            "one tier of one unit is a capacity of one, got "
            f"{stored['rack_unit_capacity']}"
        )
        assert stored["rack_units_used"] == 1, (
            f"the first single holds that unit, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == 0, (
            f"leaving nothing free, got {stored['rack_units_free']}"
        )
        first = assert_regatta_entry(read_entry(scenario["entry_a"]["id"]))
        assert first["rack_tier"] == 1, (
            f"the first single keeps its tier, got {first['rack_tier']}"
        )
        assert first["rack_position"] == 1, (
            f"and its position, got {first['rack_position']}"
        )
        second = read_entry(scenario["entry_b"]["id"])
        assert second["trailer_load_id"] is None, (
            f"the second single travels with nobody, got {second['trailer_load_id']}"
        )

    def test_a_sealed_load_refuses_a_hull_even_with_units_to_spare(
        self, cast, sealed_load_with_a_spare_single
    ):
        """Sealing freezes the manifest, and the seal answers before capacity does.

        PRD: "The load must be `OPEN` — a sealed or departed load refuses both
        assignments and releases with `ERR_TRAILER_SEALED` — and the entry's
        `regatta_id` must match the load's `regatta_id`, or the request fails with
        `ERR_TRAILER_REGATTA_MISMATCH`."

        Design: Corner/errors/corner_rack_assignment_on_sealed_load_returns_409
        """
        scenario = sealed_load_with_a_spare_single
        trailer = scenario["trailer"]
        assert trailer["status"] == "SEALED", (
            f"the load was sealed while entries were still open, got {trailer['status']}"
        )

        response = api_client.create_rack_assignment(
            trailer["id"],
            {
                "regatta_entry_id": scenario["entry_b"]["id"],
                "expected_trailer_load_version": trailer["version"],
            },
            cast["boatman_headers"],
        )
        validate_error(response, ApiErrorId.ERR_TRAILER_SEALED.value)

        stored = assert_trailer_load(read_trailer(trailer["id"]))
        assert stored["rack_units_used"] == 1, (
            f"only the first single is aboard, got {stored['rack_units_used']}"
        )
        assert stored["rack_units_free"] == DEFAULT_RACK_CAPACITY - 1, (
            "fifteen units stand empty, so capacity was never the obstacle, got "
            f"{stored['rack_units_free']}"
        )
        second = read_entry(scenario["entry_b"]["id"])
        assert second["trailer_load_id"] is None, (
            f"the second single is left behind, got {second['trailer_load_id']}"
        )


class TestLaneDrawCapacityGuard:
    def test_two_crews_will_not_be_seeded_into_one_lane(self, cast):
        """The draw is all-or-nothing: no partial seeding is written.

        PRD: "If there are more candidates than available lanes, the request is
        rejected with `ERR_LANE_CAPACITY_EXCEEDED`."

        Design: Corner/errors/corner_assign_lanes_with_more_candidates_than_lanes_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=1)
        entries = []
        for index, (hull, seed) in enumerate(
            (("Kingfisher", 370.0), ("Heron", 390.0)), start=1
        ):
            shell = add_single(hull_name=hull, hull_weight_kg=14.0 + index * 0.5)
            rower = enrol_athlete(f"Row {index}", "COMPETITIVE", 81.0 + index)
            entries.append(
                make_confirmed_single_entry(
                    regatta,
                    shell,
                    rower["id"],
                    cast["coach_headers"],
                    cast["official_headers"],
                    seed_time_seconds=seed,
                )
            )
        drive_regatta_to_racing(regatta, racing_clock=LANE_DRAW_CLOCK)

        response = api_client.assign_lanes(heat["id"], {}, cast["official_headers"])
        validate_error(response, ApiErrorId.ERR_LANE_CAPACITY_EXCEEDED.value)

        stored = assert_heat(read_heat(heat["id"]))
        assert stored["status"] == "SCHEDULED", (
            f"the heat is not promoted, got {stored['status']}"
        )
        assert stored["occupied_lane_count"] == 0, (
            f"no lane was awarded, got {stored['occupied_lane_count']}"
        )
        assert stored["free_lane_count"] == 1, (
            f"the single lane is still free, got {stored['free_lane_count']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_race_lanes(cast["official_headers"], {"heat_id": heat["id"]})
        )
        assert meta["total_count"] == 0, (
            f"the seeding was all-or-nothing, got {meta['total_count']} lanes"
        )
        for entry in entries:
            assert read_entry(entry["id"])["status"] == "CONFIRMED", (
                "both crews keep their confirmation"
            )


class TestProgressionWiringGuard:
    def test_a_heat_may_not_feed_a_final_in_another_regatta(self, cast):
        """The progression tree stays inside one regatta.

        PRD: "That downstream heat must belong to the same regatta and sit later in
        the progression — a heat may feed a semi or a final, and a semi may feed a
        final, but never the reverse — or the request is rejected with
        `ERR_HEAT_NOT_IN_REGATTA`."

        Design: Corner/errors/corner_heat_advancement_target_in_other_regatta_returns_409
        """
        regatta_a = open_regatta(name="Club Head Race", host_club="Home RC")
        regatta_b = open_regatta(
            name="Fall Classic",
            host_club="Home RC",
            race_date_at="2026-09-12T08:00:00Z",
            entry_deadline_at="2026-09-10T00:00:00Z",
            scratch_deadline_at="2026-09-11T00:00:00Z",
            weigh_in_opens_at="2026-09-12T06:00:00Z",
            weigh_in_closes_at="2026-09-12T07:00:00Z",
        )
        final_b = schedule_heat(
            regatta_b["id"],
            cast["official_headers"],
            round_kind="FINAL",
            scheduled_start_at="2026-09-12T10:00:00Z",
            lane_count=6,
        )

        response = api_client.create_heat(
            create_heat_payload(
                regatta_a["id"],
                round_kind="HEAT",
                lane_count=6,
                advance_count=2,
                advances_to_heat_id=final_b["id"],
            ),
            cast["official_headers"],
        )
        validate_error(response, ApiErrorId.ERR_HEAT_NOT_IN_REGATTA.value)

        _rows, meta = validate_paginated(
            api_client.list_heats(
                cast["official_headers"], {"regatta_id": regatta_a["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the first regatta got no heat at all, got {meta['total_count']}"
        )


class TestCoxswainCredentialGuard:
    def test_a_lapsed_coxswain_certificate_sinks_the_whole_declaration(self, cast):
        """The coxswain seat is checked on its own terms, and the batch is atomic.

        PRD: "Every seated member must have `membership_status` `ACTIVE`, must
        satisfy the swim-test rule of §3.4 (`ERR_SWIM_TEST_MISSING`), and, in the
        coxswain seat, must hold a `coxswain_cert_expires_at` strictly after the
        logical clock (`ERR_COXSWAIN_CERT_EXPIRED`)"

        Design: Corner/errors/corner_coxswain_with_expired_certificate_returns_409
        """
        regatta = open_regatta(name="Club Head Race", host_club="Home RC")
        shell = add_coxed_four(
            hull_name="Cormorant", hull_weight_kg=51.0, home_bay="BAY-4"
        )
        lapsed_cox = enrol_coxswain(
            "Cox Lapsed", 52.0, coxswain_cert_expires_at="2026-07-01T00:00:00Z"
        )
        rowers = [
            enrol_athlete(f"Row {index}", "COMPETITIVE", 81.0 + index)
            for index in range(1, 5)
        ]
        entry = open_entry(
            regatta["id"],
            shell["id"],
            cast["coach_headers"],
            event_code="M4PLUS_OPEN",
            boat_class="4+",
            seed_time_seconds=400.0,
        )

        seats = [{"member_id": lapsed_cox["id"], "seat_number": 0, "seat_role": "COXSWAIN"}]
        for index, rower in enumerate(rowers, start=1):
            seats.append(
                {"member_id": rower["id"], "seat_number": index, "seat_role": "ROWER"}
            )
        response = api_client.declare_lineup(
            entry["id"],
            {"expected_regatta_entry_version": entry["version"], "seats": seats},
            cast["coach_headers"],
        )
        validate_error(response, ApiErrorId.ERR_COXSWAIN_CERT_EXPIRED.value)

        stored = assert_regatta_entry(read_entry(entry["id"]))
        assert stored["status"] == "DRAFT", (
            f"the entry keeps its draft status, got {stored['status']}"
        )
        assert stored["version"] == entry["version"], (
            "the refused declaration consumed no version, expected "
            f"{entry['version']}, got {stored['version']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_lineup_seats(
                cast["coach_headers"], {"regatta_entry_id": entry["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            "not one of the five seats was written, got "
            f"{meta['total_count']}"
        )


class TestWeighInWindowGuard:
    def test_a_weigh_in_at_the_closing_instant_is_already_too_late(
        self, cast, declared_coxed_four
    ):
        """The weigh-in window is half-open, so its closing instant is outside it.

        PRD: "A `RaceOfficial` records a coxswain's weight by supplying `weighed_kg`
        at one decimal place, permitted only while the logical clock lies inside the
        regatta's half-open weigh-in window (`ERR_WEIGH_IN_WINDOW_CLOSED`) and never
        by the coxswain themselves (`ERR_SELF_WEIGH_IN_FORBIDDEN`)."

        Design: Corner/errors/corner_weigh_in_at_window_close_instant_returns_409
        """
        scenario = declared_coxed_four
        assert scenario["regatta"]["weigh_in_closes_at"] == WEIGH_IN_CLOSE_INSTANT, (
            "the scales come off the dock at 07:00, got "
            f"{scenario['regatta']['weigh_in_closes_at']}"
        )
        cox_seat = coxswain_seat_of_entry(scenario["entry"]["id"])
        set_clock_to(WEIGH_IN_CLOSE_INSTANT)

        response = api_client.weigh_in_lineup_seat(
            cox_seat["id"], {"weighed_kg": 52.0}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_WEIGH_IN_WINDOW_CLOSED.value)

        stored = assert_lineup_seat(
            coxswain_seat_of_entry(scenario["entry"]["id"], cast["official_headers"])
        )
        assert stored["weigh_in_status"] == "NOT_REQUIRED", (
            "an unsubmitted entry's coxswain seat is not yet awaiting the scales, "
            f"got {stored['weigh_in_status']}"
        )
        assert stored["weighed_kg"] is None, (
            f"no weight was recorded, got {stored['weighed_kg']}"
        )
        assert stored["deadweight_kg"] is None, (
            f"and no sandbag was computed, got {stored['deadweight_kg']}"
        )


class TestConfirmationWeighInGuard:
    def test_a_coxed_crew_cannot_be_confirmed_unweighed(self, cast, declared_coxed_four):
        """Confirmation insists the coxswain has passed the scales.

        PRD: "Confirmation requires that every `COXSWAIN` seat on the entry have
        `weigh_in_status` `PASSED` (`ERR_WEIGH_IN_NOT_PASSED`), that every seat be
        `ELIGIBLE`, and — when the regatta's `venue_kind` is `AWAY` — that the
        entry's `rack_tier` be non-null and its owning trailer load be in status
        `SEALED`, `DEPARTED` or `ARRIVED` (`ERR_ENTRY_NOT_RACKED`)."

        Design: Corner/errors/corner_confirm_without_coxswain_weigh_in_returns_409
        """
        scenario = declared_coxed_four
        submitted = assert_regatta_entry(
            submit_entry(scenario["entry"]["id"], cast["coach_headers"])
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the entry reached the host, got {submitted['status']}"
        )
        assert submitted["total_fee_cents"] == COXED_FOUR_HOME_FEE_CENTS, (
            "a coxed four entered on time at a home regatta pays only its class fee "
            f"of 13500, got {submitted['total_fee_cents']}"
        )

        response = api_client.confirm_regatta_entry(
            scenario["entry"]["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_WEIGH_IN_NOT_PASSED.value)

        cox_seat = assert_lineup_seat(coxswain_seat_of_entry(scenario["entry"]["id"]))
        assert cox_seat["weigh_in_status"] == "PENDING", (
            "submission moved the coxswain seat from NOT_REQUIRED to PENDING and "
            f"nothing since has weighed it, got {cox_seat['weigh_in_status']}"
        )
        assert read_entry(scenario["entry"]["id"])["status"] == "SUBMITTED", (
            "the entry is still awaiting the host's confirmation"
        )


class TestOfficializationGuards:
    def test_a_heat_with_no_results_cannot_be_made_official(self, cast):
        """Officialization reaches for provisional results and finds only a draw.

        PRD: "Making a heat official requires the heat to be `RESULTS_PROVISIONAL`
        (`ERR_HEAT_NOT_PROVISIONAL`), the logical clock to have reached
        `protest_window_closes_at` (`ERR_PROTEST_WINDOW_OPEN` if it has not), and no
        protest on the heat to remain in status `FILED`, `UNDER_JURY_REVIEW` or
        `REMANDED`."

        Design: Corner/errors/corner_officialize_before_results_then_before_window_close_returns_409
        """
        scenario = build_racing_regatta_with_lanes(cast, entry_count=1, lane_count=4)
        assert scenario["heat"]["status"] == "LANES_ASSIGNED", (
            f"the heat has its lane draw and nothing more, got {scenario['heat']['status']}"
        )

        response = api_client.officialize_heat(
            scenario["heat"]["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_HEAT_NOT_PROVISIONAL.value)

        stored = assert_heat(read_heat(scenario["heat"]["id"]))
        assert stored["status"] == "LANES_ASSIGNED", (
            f"the heat has not moved, got {stored['status']}"
        )
        assert stored["protest_window_closes_at"] is None, (
            "no window has opened yet, got "
            f"{stored['protest_window_closes_at']}"
        )

    def test_a_heat_inside_its_protest_window_cannot_be_made_official_either(self, cast):
        """The same call now fails for the other reason, thirty minutes early.

        PRD: "Posting results also opens the jury's window:
        `protest_window_closes_at` is set to the logical clock at posting plus 30
        minutes."

        Design: Corner/errors/corner_officialize_before_results_then_before_window_close_returns_409
        """
        scenario = build_racing_regatta_with_lanes(cast, entry_count=1, lane_count=4)
        provisional = assert_heat(
            post_results_for_all_pending(scenario["heat"]["id"], cast["official_headers"])
        )
        assert provisional["status"] == "RESULTS_PROVISIONAL", (
            f"the results are in but not official, got {provisional['status']}"
        )
        assert provisional["protest_window_closes_at"].startswith(
            PROTEST_WINDOW_CLOSE_PREFIX
        ), (
            "results posted at 09:00 close the jury's window at 09:30, got "
            f"{provisional['protest_window_closes_at']}"
        )

        response = api_client.officialize_heat(
            scenario["heat"]["id"], {}, cast["official_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PROTEST_WINDOW_OPEN.value)

        stored = read_heat(scenario["heat"]["id"])
        assert stored["status"] == "RESULTS_PROVISIONAL", (
            f"the heat stays provisional, got {stored['status']}"
        )
        assert read_entry(scenario["entries"][0]["id"])["status"] == "CONFIRMED", (
            "and the crew has not yet been marked as having raced"
        )


class TestProtestCrossReferenceGuards:
    def test_a_protest_must_cite_a_lane_of_the_heat_it_names(
        self, two_heats_one_with_results
    ):
        """A sibling heat's lane is not this heat's business.

        PRD: "the challenged lane must belong to that same heat, or the filing is
        rejected with `ERR_LANE_NOT_IN_HEAT`."

        Design: Corner/errors/corner_protest_window_and_lane_cross_reference_errors
        """
        scenario = two_heats_one_with_results
        outsider = assert_race_lane(read_lane(scenario["lane_b"]["id"]))
        assert outsider["heat_id"] == scenario["heat_b"]["id"], (
            f"the cited lane belongs to the masters heat, got {outsider['heat_id']}"
        )

        response = api_client.create_protest(
            create_protest_payload(
                scenario["heat_a"]["id"],
                scenario["filer"]["id"],
                scenario["lane_b"]["id"],
                narrative="the masters lane crossed my line",
            ),
            scenario["filer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_LANE_NOT_IN_HEAT.value)

        _rows, meta = validate_paginated(
            api_client.list_protests(
                scenario["filer_headers"], {"heat_id": scenario["heat_a"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no protest was opened, got {meta['total_count']}"
        )
        assert read_regatta(scenario["regatta"]["id"])["deposit_held_cents"] == 0, (
            "and no deposit was taken"
        )

    def test_the_jury_cannot_rule_on_a_protest_it_never_opened(
        self, cast, two_heats_one_with_results
    ):
        """A ruling belongs to a review, and a FILED protest has had none.

        PRD: "A `JuryChair` rules on an `UNDER_JURY_REVIEW` protest — any other
        status is `ERR_PROTEST_NOT_UNDER_REVIEW` — by supplying a `decision` with a
        written `rationale`, and, when upholding, a `remedy`."

        Design: Corner/errors/corner_protest_window_and_lane_cross_reference_errors
        """
        scenario = two_heats_one_with_results
        opened = assert_protest(
            file_protest(
                scenario["heat_a"]["id"],
                scenario["filer"]["id"],
                scenario["lane_a"]["id"],
                scenario["filer_headers"],
                narrative="buoy line encroachment",
            )
        )
        assert opened["status"] == "FILED", (
            f"a new protest opens at FILED, got {opened['status']}"
        )
        assert opened["deposit_cents"] == 5000, (
            f"the club holds a 5000-cent deposit, got {opened['deposit_cents']}"
        )
        assert opened["deposit_refunded"] is False, (
            f"which is not yet returned, got {opened['deposit_refunded']}"
        )
        assert opened["review_round"] == 0, (
            f"and no jury round has run, got {opened['review_round']}"
        )

        # PRD §3.9 requires a `remedy` alongside the decision when upholding, and
        # PRD §2.9 places payload shape at rung 5, ahead of rung 19. The payload is
        # therefore complete so that ERR_PROTEST_NOT_UNDER_REVIEW is the first
        # failing rung rather than ERR_INVALID_REQUEST.
        response = api_client.rule_on_protest(
            opened["id"],
            {
                "decision": "UPHELD",
                "rationale": "ruling without opening a review",
                "remedy": "DISQUALIFY",
            },
            cast["chair_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PROTEST_NOT_UNDER_REVIEW.value)

        stored = assert_protest(read_protest(opened["id"]))
        assert stored["status"] == "FILED", (
            f"the protest is still merely filed, got {stored['status']}"
        )
        _rows, meta = validate_paginated(
            api_client.list_protests(
                scenario["filer_headers"], {"heat_id": scenario["heat_a"]["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"one protest stands on the heat, got {meta['total_count']}"
        )
        assert read_regatta(scenario["regatta"]["id"])["deposit_held_cents"] == 5000, (
            "and its deposit is held against the regatta"
        )

    def test_a_protest_filed_after_the_window_shuts_is_refused(
        self, two_heats_one_with_results
    ):
        """One minute past 09:30 the jury is closed for business.

        PRD: "the filer must have `membership_status` `ACTIVE`, the logical clock
        must be strictly before the heat's `protest_window_closes_at`
        (`ERR_PROTEST_WINDOW_CLOSED`)"

        Design: Corner/errors/corner_protest_window_and_lane_cross_reference_errors
        """
        scenario = two_heats_one_with_results
        heat = assert_heat(read_heat(scenario["heat_a"]["id"]))
        assert heat["protest_window_closes_at"].startswith(PROTEST_WINDOW_CLOSE_PREFIX), (
            "results posted at 09:00 close the window at 09:30, got "
            f"{heat['protest_window_closes_at']}"
        )
        set_clock_to(PAST_PROTEST_WINDOW_CLOCK)

        response = api_client.create_protest(
            create_protest_payload(
                scenario["heat_a"]["id"],
                scenario["filer"]["id"],
                scenario["lane_a"]["id"],
                narrative="filed too late",
            ),
            scenario["filer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_PROTEST_WINDOW_CLOSED.value)

        _rows, meta = validate_paginated(
            api_client.list_protests(
                scenario["filer_headers"], {"heat_id": scenario["heat_a"]["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the late filing was not recorded, got {meta['total_count']}"
        )
        assert read_regatta(scenario["regatta"]["id"])["deposit_held_cents"] == 0, (
            "and no deposit was taken"
        )
