"""Composite state builders and pytest fixtures.

The server is restarted and the database emptied before every individual test,
so every fixture here builds the state it needs from scratch through the public
API. Nothing is shared between tests.

The helpers are plain callables so a test can compose an unusual state, and the
pytest fixtures at the bottom wrap the shapes that recur.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_CLOCK_ISO,
    PROTEST_WINDOW_MINUTES,
)
from .factories import (
    athlete_payload,
    coach_payload,
    coxed_four_seats,
    coxswain_payload,
    create_damage_report_payload,
    create_dues_invoice_payload,
    create_heat_payload,
    create_protest_payload,
    create_reading_payload,
    create_regatta_entry_payload,
    create_regatta_payload,
    create_shell_payload,
    create_trailer_load_payload,
    create_water_session_payload,
    equipment_manager_payload,
    jury_chair_payload,
    lane_results_payload,
    launch_driver_payload,
    lineup_payload,
    officer_payload,
    seat,
)
from .test_users import (
    CLUB_ADMIN_HEADERS,
    make_coach_headers,
    make_equipment_manager_headers,
    make_jury_chair_headers,
    make_member_headers,
    make_race_official_headers,
    make_safety_officer_headers,
)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock_to(iso8601, headers=CLUB_ADMIN_HEADERS):
    """Move the logical clock. The clock starts at 2026-08-01T00:00:00Z."""
    return get_success_data(api_client.set_clock(iso8601, headers))


def reset_clock(headers=CLUB_ADMIN_HEADERS):
    return set_clock_to(DEFAULT_CLOCK_ISO, headers)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def enrol_member(payload, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.create_member(payload, headers))


def enrol_athlete(full_name="Ada Athlete", tier="COMPETITIVE", body_weight_kg=82.0, **overrides):
    return enrol_member(athlete_payload(full_name, tier, body_weight_kg, **overrides))


def enrol_coxswain(full_name="Kip Cox", body_weight_kg=52.0, **overrides):
    return enrol_member(coxswain_payload(full_name, body_weight_kg, **overrides))


def enrol_coach(full_name="Cora Coach", **overrides):
    return enrol_member(coach_payload(full_name, **overrides))


def enrol_launch_driver(full_name="Dave Driver", launch_supervision_limit=2, **overrides):
    return enrol_member(launch_driver_payload(full_name, launch_supervision_limit, **overrides))


def enrol_officer(full_name="Ollie Officer", **overrides):
    return enrol_member(officer_payload(full_name, **overrides))


def enrol_boatman(full_name="Enid Boatman", **overrides):
    return enrol_member(equipment_manager_payload(full_name, **overrides))


def enrol_jury_chair(full_name="Jude Jury", **overrides):
    return enrol_member(jury_chair_payload(full_name, **overrides))


def amend_certifications(member_id, payload, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.update_member_certifications(member_id, payload, headers))


def move_member_to(member_id, to_status, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(
        api_client.transition_member(member_id, {"to_status": to_status}, headers)
    )


def read_member(member_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_member(member_id, headers))


def build_cast():
    """Enrol the standing cast of members the club needs to run anything.

    Duty segregation is baked in: the safety officer is not the coach, the
    verifying boatman is not the member who filed the damage, the race official
    is not a seated coxswain, and the jury chair holds no seat at all.
    """
    coach = enrol_coach()
    officer = enrol_officer("Ollie Officer")
    official = enrol_officer("Rex Official")
    boatman = enrol_boatman()
    reporter = enrol_athlete("Rory Reporter", "RECREATIONAL", 79.0)
    chair = enrol_jury_chair()
    athlete = enrol_athlete()
    cox = enrol_coxswain()
    driver = enrol_launch_driver()
    return {
        "admin_headers": CLUB_ADMIN_HEADERS,
        "coach": coach,
        "coach_headers": make_coach_headers(coach["id"]),
        "officer": officer,
        "officer_headers": make_safety_officer_headers(officer["id"]),
        "official": official,
        "official_headers": make_race_official_headers(official["id"]),
        "boatman": boatman,
        "boatman_headers": make_equipment_manager_headers(boatman["id"]),
        "reporter": reporter,
        "reporter_headers": make_member_headers(reporter["id"]),
        "chair": chair,
        "chair_headers": make_jury_chair_headers(chair["id"]),
        "athlete": athlete,
        "athlete_headers": make_member_headers(athlete["id"]),
        "cox": cox,
        "cox_headers": make_member_headers(cox["id"]),
        "driver": driver,
        "driver_headers": make_member_headers(driver["id"]),
    }


# ---------------------------------------------------------------------------
# Dues
# ---------------------------------------------------------------------------


def issue_invoice(member_id, headers=CLUB_ADMIN_HEADERS, **overrides):
    payload = create_dues_invoice_payload(member_id, **overrides)
    return get_success_data(api_client.create_dues_invoice(payload, headers))


def read_invoice(invoice_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_dues_invoice(invoice_id, headers))


def pay_invoice(invoice_id, amount_cents, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(
        api_client.pay_dues_invoice(invoice_id, {"amount_cents": amount_cents}, headers)
    )


def true_up_invoice(invoice_id, headers=CLUB_ADMIN_HEADERS, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.true_up_dues_invoice(invoice_id, payload, headers))


def void_invoice(invoice_id, reason="issued in error", headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.void_dues_invoice(invoice_id, {"reason": reason}, headers))


def run_delinquency(headers=CLUB_ADMIN_HEADERS, season_year=None):
    payload = {} if season_year is None else {"season_year": season_year}
    return api_client.run_dues_delinquency(payload, headers)


def make_partially_paid_invoice(member_id, amount_cents=1000, headers=CLUB_ADMIN_HEADERS, **overrides):
    """An invoice carrying a part payment — the only state a true-up accepts."""
    invoice = issue_invoice(member_id, headers, **overrides)
    pay_invoice(invoice["id"], amount_cents, headers)
    return invoice


def make_delinquent_member(member_id, due_at="2026-07-01T00:00:00Z", **overrides):
    """Issue a past-due invoice and run the checkpoint so the member lands on hold."""
    invoice = issue_invoice(member_id, due_at=due_at, **overrides)
    run_delinquency()
    return invoice


# ---------------------------------------------------------------------------
# Shells
# ---------------------------------------------------------------------------


def add_shell(headers=CLUB_ADMIN_HEADERS, **overrides):
    return get_success_data(api_client.create_shell(create_shell_payload(**overrides), headers))


def add_single(hull_name="Kingfisher", **overrides):
    defaults = {"hull_name": hull_name, "boat_class": "1X"}
    defaults.update(overrides)
    return add_shell(**defaults)


def add_coxed_four(hull_name="Heron", **overrides):
    defaults = {"hull_name": hull_name, "boat_class": "4+", "hull_weight_kg": 50.0}
    defaults.update(overrides)
    return add_shell(**defaults)


def add_eight(hull_name="Osprey", **overrides):
    defaults = {"hull_name": hull_name, "boat_class": "8+", "hull_weight_kg": 96.0}
    defaults.update(overrides)
    return add_shell(**defaults)


def read_shell(shell_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_shell(shell_id, headers))


# ---------------------------------------------------------------------------
# Damage reports
# ---------------------------------------------------------------------------


def file_damage(shell_id, reported_by_member_id, headers, **overrides):
    payload = create_damage_report_payload(shell_id, reported_by_member_id, **overrides)
    return get_success_data(api_client.create_damage_report(payload, headers))


def triage_report(report_id, headers, disposition="REPAIR"):
    return get_success_data(
        api_client.triage_damage_report(report_id, {"disposition": disposition}, headers)
    )


def schedule_report_repair(report_id, headers, bay="BAY-A", start_at=None, end_at=None):
    payload = {
        "assigned_repair_bay": bay,
        "repair_window_start_at": start_at,
        "repair_window_end_at": end_at,
    }
    return get_success_data(api_client.schedule_repair(report_id, payload, headers))


def verify_report_repair(report_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.verify_repair(report_id, payload, headers))


def condemn_report(report_id, headers, reason="hull beyond economic repair"):
    return get_success_data(api_client.condemn_damage_report(report_id, {"reason": reason}, headers))


def read_report(report_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_damage_report(report_id, headers))


def make_scheduled_repair(shell_id, reporter_id, reporter_headers, boatman_headers,
                          severity="MAJOR", bay="BAY-A", start_at=None, end_at=None):
    """File, triage and schedule in one go — the hull ends up IN_REPAIR."""
    report = file_damage(shell_id, reporter_id, reporter_headers, severity=severity)
    triage_report(report["id"], boatman_headers)
    return schedule_report_repair(report["id"], boatman_headers, bay, start_at, end_at)


def make_condemnable_report(shell_id, reporter_id, reporter_headers, boatman_headers):
    """A STRUCTURAL report sitting at TRIAGED, ready to be condemned."""
    report = file_damage(shell_id, reporter_id, reporter_headers, severity="STRUCTURAL")
    return triage_report(report["id"], boatman_headers)


# ---------------------------------------------------------------------------
# River readings
# ---------------------------------------------------------------------------


def post_reading(headers, **overrides):
    payload = create_reading_payload(**overrides)
    return get_success_data(api_client.create_water_condition_reading(payload, headers))


def post_open_reading(headers, **overrides):
    return post_reading(headers, **overrides)


def post_restricted_reading(headers, **overrides):
    """Wind at or above 12.0 knots restricts the river without closing it."""
    defaults = {"wind_speed_kt": 14.0}
    defaults.update(overrides)
    return post_reading(headers, **defaults)


def post_closed_reading(headers, **overrides):
    """Sustained wind of 20.0 knots or more closes the river."""
    defaults = {"wind_speed_kt": 22.0}
    defaults.update(overrides)
    return post_reading(headers, **defaults)


def post_cold_reading(headers, **overrides):
    """Water strictly below 12.8 degrees raises the cold-water flag."""
    defaults = {"water_temp_c": 10.0, "air_temp_c": 18.0}
    defaults.update(overrides)
    return post_reading(headers, **defaults)


# ---------------------------------------------------------------------------
# Water sessions
# ---------------------------------------------------------------------------


def book_session(shell_id, headers, **overrides):
    payload = create_water_session_payload(shell_id, **overrides)
    return get_success_data(api_client.create_water_session(payload, headers))


def clear_session(session_id, reading_id, headers):
    return get_success_data(
        api_client.clear_water_session(session_id, {"reading_id": reading_id}, headers)
    )


def launch_session(session_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.launch_water_session(session_id, payload, headers))


def return_session(session_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.return_water_session(session_id, payload, headers))


def cancel_session(session_id, headers, reason="crew withdrew"):
    return get_success_data(
        api_client.cancel_water_session(session_id, {"reason": reason}, headers)
    )


def read_session(session_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_water_session(session_id, headers))


def run_returned_session(shell_id, athlete_ids, coach_headers, officer_headers,
                         start_at, end_at, reading_id=None, **booking_overrides):
    """Book, clear, launch and log a crew back in — one completed outing.

    The clock is moved to the planned start so the launch falls inside the
    session's half-open window.
    """
    set_clock_to(start_at)
    if reading_id is None:
        reading_id = post_reading(officer_headers, observed_at=start_at)["id"]
    session = book_session(
        shell_id,
        coach_headers,
        planned_start_at=start_at,
        planned_end_at=end_at,
        athlete_member_ids=list(athlete_ids),
        **booking_overrides,
    )
    clear_session(session["id"], reading_id, officer_headers)
    launch_session(session["id"], officer_headers)
    return return_session(session["id"], officer_headers)


def hourly_windows(count, day="2026-08-01", first_hour=6, spacing_hours=2):
    """`count` one-hour windows two hours apart on a single day.

    Two hours apart leaves a clear gap once the 30-minute turnaround buffer is
    appended to the earlier session's end, so consecutive outings on the same
    hull never collide.
    """
    windows = []
    for index in range(count):
        hour = first_hour + index * spacing_hours
        windows.append((f"{day}T{hour:02d}:00:00Z", f"{day}T{hour + 1:02d}:00:00Z"))
    return windows


def log_returned_sessions(shell_id, athlete_ids, coach_headers, officer_headers, count,
                          windows=None):
    """Run `count` completed outings on one hull, back to back.

    The clock is walked to each window's start so every launch falls inside its
    session's half-open window.
    """
    windows = windows or hourly_windows(count)
    assert len(windows) >= count, "not enough windows supplied for the requested outings"
    sessions = []
    for start_at, end_at in windows[:count]:
        sessions.append(
            run_returned_session(
                shell_id, athlete_ids, coach_headers, officer_headers, start_at, end_at
            )
        )
    return sessions


# ---------------------------------------------------------------------------
# Regattas
# ---------------------------------------------------------------------------


def open_regatta(headers=CLUB_ADMIN_HEADERS, **overrides):
    return get_success_data(api_client.create_regatta(create_regatta_payload(**overrides), headers))


def open_away_regatta(headers=CLUB_ADMIN_HEADERS, **overrides):
    defaults = {"venue_kind": "AWAY", "name": "Away Championship"}
    defaults.update(overrides)
    return open_regatta(headers, **defaults)


def move_regatta_to(regatta_id, to_status, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(
        api_client.transition_regatta(regatta_id, {"to_status": to_status}, headers)
    )


def read_regatta(regatta_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_regatta(regatta_id, headers))


def drive_regatta_to_racing(regatta, headers=CLUB_ADMIN_HEADERS, racing_clock=None):
    """Close entries and start racing, moving the clock past each gate."""
    set_clock_to(regatta["entry_deadline_at"])
    move_regatta_to(regatta["id"], "ENTRIES_CLOSED", headers)
    set_clock_to(racing_clock or regatta["race_date_at"])
    return move_regatta_to(regatta["id"], "RACING", headers)


# ---------------------------------------------------------------------------
# Regatta entries and lineup seats
# ---------------------------------------------------------------------------


def open_entry(regatta_id, shell_id, headers, **overrides):
    payload = create_regatta_entry_payload(regatta_id, shell_id, **overrides)
    return get_success_data(api_client.create_regatta_entry(payload, headers))


def declare_lineup(entry, seats, headers):
    payload = lineup_payload(entry["version"], seats)
    return get_success_data(api_client.declare_lineup(entry["id"], payload, headers))


def declare_single_lineup(entry, member_id, headers):
    """A 1X carries exactly one ROWER seat."""
    return declare_lineup(entry, [seat(member_id, 1, "ROWER")], headers)


def declare_coxed_four_lineup(entry, cox_id, rower_ids, headers):
    return declare_lineup(entry, coxed_four_seats(cox_id, rower_ids), headers)


def submit_entry(entry_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.submit_regatta_entry(entry_id, payload, headers))


def confirm_entry(entry_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.confirm_regatta_entry(entry_id, payload, headers))


def scratch_entry(entry_id, headers, reason="crew stood down"):
    return get_success_data(
        api_client.scratch_regatta_entry(entry_id, {"reason": reason}, headers)
    )


def read_entry(entry_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_regatta_entry(entry_id, headers))


def seats_of_entry(entry_id, headers=CLUB_ADMIN_HEADERS, seat_role=None):
    params = {"regatta_entry_id": entry_id}
    if seat_role is not None:
        params["seat_role"] = seat_role
    return get_success_data(api_client.list_lineup_seats(headers, params))


def coxswain_seat_of_entry(entry_id, headers=CLUB_ADMIN_HEADERS):
    rows = seats_of_entry(entry_id, headers)
    coxswain_rows = [row for row in rows if row["seat_role"] == "COXSWAIN"]
    assert coxswain_rows, f"entry {entry_id} has no COXSWAIN seat"
    return coxswain_rows[0]


def weigh_in_seat(seat_id, weighed_kg, headers):
    return get_success_data(
        api_client.weigh_in_lineup_seat(seat_id, {"weighed_kg": weighed_kg}, headers)
    )


def make_submitted_single_entry(regatta, shell, member_id, coach_headers, **entry_overrides):
    """A 1X entry carried through DRAFT to SUBMITTED."""
    entry = open_entry(regatta["id"], shell["id"], coach_headers, **entry_overrides)
    declare_single_lineup(entry, member_id, coach_headers)
    return submit_entry(entry["id"], coach_headers)


def make_confirmed_single_entry(regatta, shell, member_id, coach_headers, official_headers,
                                **entry_overrides):
    """A 1X entry carried all the way to CONFIRMED.

    A `1X` has no coxswain seat, so the weigh-in gate on confirmation is
    vacuously satisfied.
    """
    entry = make_submitted_single_entry(
        regatta, shell, member_id, coach_headers, **entry_overrides
    )
    return confirm_entry(entry["id"], official_headers)


# ---------------------------------------------------------------------------
# Heats, lanes, results
# ---------------------------------------------------------------------------


def schedule_heat(regatta_id, headers, **overrides):
    payload = create_heat_payload(regatta_id, **overrides)
    return get_success_data(api_client.create_heat(payload, headers))


def assign_lanes(heat_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.assign_lanes(heat_id, payload, headers))


def post_results(heat_id, pairs, headers):
    return get_success_data(
        api_client.post_heat_results(heat_id, lane_results_payload(pairs), headers)
    )


def officialize_heat(heat_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.officialize_heat(heat_id, payload, headers))


def read_heat(heat_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_heat(heat_id, headers))


def lanes_of_heat(heat_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.list_race_lanes(headers, {"heat_id": heat_id}))


def lanes_of_entry(entry_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(
        api_client.list_race_lanes(headers, {"regatta_entry_id": entry_id})
    )


def lane_of_entry(entry_id, headers=CLUB_ADMIN_HEADERS):
    rows = lanes_of_entry(entry_id, headers)
    assert rows, f"entry {entry_id} holds no race lane"
    return rows[0]


def read_lane(lane_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_race_lane(lane_id, headers))


def post_results_for_all_pending(heat_id, headers, first_elapsed=360.0, step=2.5):
    """Post an elapsed time for every lane on the heat still PENDING."""
    pending = [row for row in lanes_of_heat(heat_id, headers) if row["lane_status"] == "PENDING"]
    pending.sort(key=lambda row: row["lane_number"])
    pairs = [
        (row["id"], first_elapsed + index * step) for index, row in enumerate(pending)
    ]
    return post_results(heat_id, pairs, headers)


# ---------------------------------------------------------------------------
# Protests
# ---------------------------------------------------------------------------


def file_protest(heat_id, filed_by_member_id, against_race_lane_id, headers, **overrides):
    payload = create_protest_payload(
        heat_id, filed_by_member_id, against_race_lane_id, **overrides
    )
    return get_success_data(api_client.create_protest(payload, headers))


def open_review(protest_id, headers, note=None):
    payload = {} if note is None else {"note": note}
    return get_success_data(api_client.open_protest_review(protest_id, payload, headers))


def rule_on_protest(protest_id, decision, headers, rationale="the jury has considered the facts",
                    remedy=None):
    payload = {"decision": decision, "rationale": rationale}
    if remedy is not None:
        payload["remedy"] = remedy
    return get_success_data(api_client.rule_on_protest(protest_id, payload, headers))


def withdraw_protest(protest_id, headers):
    return get_success_data(api_client.withdraw_protest(protest_id, {}, headers))


def read_protest(protest_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_protest(protest_id, headers))


# ---------------------------------------------------------------------------
# Trailer loads
# ---------------------------------------------------------------------------


def open_trailer_load(regatta_id, driver_member_id, headers, **overrides):
    payload = create_trailer_load_payload(regatta_id, driver_member_id, **overrides)
    return get_success_data(api_client.create_trailer_load(payload, headers))


def rack_entry(trailer, entry_id, headers):
    payload = {
        "regatta_entry_id": entry_id,
        "expected_trailer_load_version": trailer["version"],
    }
    return get_success_data(api_client.create_rack_assignment(trailer["id"], payload, headers))


def release_rack_units(trailer, entry_id, headers):
    payload = {
        "regatta_entry_id": entry_id,
        "expected_trailer_load_version": trailer["version"],
    }
    return get_success_data(api_client.create_rack_release(trailer["id"], payload, headers))


def move_trailer_to(trailer_id, to_status, headers):
    return get_success_data(
        api_client.transition_trailer_load(trailer_id, {"to_status": to_status}, headers)
    )


def read_trailer(trailer_id, headers=CLUB_ADMIN_HEADERS):
    return get_success_data(api_client.get_trailer_load(trailer_id, headers))


# ---------------------------------------------------------------------------
# Full-lifecycle scenario builders
# ---------------------------------------------------------------------------


def build_racing_regatta_with_lanes(cast, entry_count=2, lane_count=4, seed_times=None):
    """A HOME regatta driven to RACING with a lane-assigned heat.

    Each entry is a 1X on its own hull, confirmed before entries close, so the
    lane-assignment candidate pool is exactly `entry_count` crews.
    """
    regatta = open_regatta()
    heat = schedule_heat(regatta["id"], cast["official_headers"], lane_count=lane_count)
    seed_times = seed_times or [370.0 + 5.0 * index for index in range(entry_count)]
    entries = []
    rowers = []
    for index in range(entry_count):
        shell = add_single(hull_name=f"Hull-{index + 1}")
        rower = enrol_athlete(f"Rower {index + 1}", "COMPETITIVE", 80.0 + index)
        rowers.append(rower)
        entry = make_confirmed_single_entry(
            regatta,
            shell,
            rower["id"],
            cast["coach_headers"],
            cast["official_headers"],
            seed_time_seconds=seed_times[index],
        )
        entries.append(entry)
    drive_regatta_to_racing(regatta, racing_clock="2026-08-12T09:00:00Z")
    heat = assign_lanes(heat["id"], cast["official_headers"])
    return {
        "regatta": read_regatta(regatta["id"]),
        "heat": heat,
        "entries": [read_entry(entry["id"]) for entry in entries],
        "rowers": rowers,
        "lanes": lanes_of_heat(heat["id"]),
    }


def build_provisional_heat(cast, entry_count=2, lane_count=4):
    """Carry a heat all the way to RESULTS_PROVISIONAL with a live protest window."""
    scenario = build_racing_regatta_with_lanes(cast, entry_count, lane_count)
    heat = post_results_for_all_pending(scenario["heat"]["id"], cast["official_headers"])
    scenario["heat"] = heat
    scenario["lanes"] = lanes_of_heat(heat["id"])
    scenario["entries"] = [read_entry(entry["id"]) for entry in scenario["entries"]]
    return scenario


def build_filed_protest(cast, entry_count=2, lane_count=4):
    """A protest lodged against the slower crew's lane while results are provisional."""
    scenario = build_provisional_heat(cast, entry_count, lane_count)
    lanes = sorted(scenario["lanes"], key=lambda row: row["elapsed_seconds"])
    challenged = lanes[-1]
    filer = scenario["rowers"][0]
    protest = file_protest(
        scenario["heat"]["id"],
        filer["id"],
        challenged["id"],
        make_member_headers(filer["id"]),
    )
    scenario["protest"] = protest
    scenario["challenged_lane"] = challenged
    scenario["filer"] = filer
    return scenario


def build_sealed_trailer_with_entry(cast, seed_time_seconds=380.0):
    """An away regatta with one submitted entry racked on a SEALED trailer."""
    regatta = open_away_regatta()
    shell = add_single(hull_name="Voyager")
    rower = enrol_athlete("Tessa Trailer", "COMPETITIVE", 78.0)
    entry = make_submitted_single_entry(
        regatta, shell, rower["id"], cast["coach_headers"], seed_time_seconds=seed_time_seconds
    )
    trailer = open_trailer_load(regatta["id"], cast["driver"]["id"], cast["boatman_headers"])
    trailer = rack_entry(trailer, entry["id"], cast["boatman_headers"])
    trailer = move_trailer_to(trailer["id"], "SEALED", cast["boatman_headers"])
    return {
        "regatta": read_regatta(regatta["id"]),
        "shell": shell,
        "rower": rower,
        "entry": read_entry(entry["id"]),
        "trailer": trailer,
    }


def build_hull_with_two_reports(cast, shell=None):
    """A hull carrying a VERIFIED MAJOR report and a REPAIR_SCHEDULED MINOR one.

    The clock is walked forward so the two deductions have decayed by different
    amounts, which is what makes the conservative and optimistic indices differ.
    """
    shell = shell or add_single(hull_name="Wren")
    set_clock_to("2026-05-04T00:00:00Z")
    major = file_damage(
        shell["id"], cast["reporter"]["id"], cast["reporter_headers"], severity="MAJOR"
    )
    triage_report(major["id"], cast["boatman_headers"])
    schedule_report_repair(
        major["id"],
        cast["boatman_headers"],
        "BAY-A",
        "2026-05-05T08:00:00Z",
        "2026-05-05T12:00:00Z",
    )
    set_clock_to("2026-07-02T00:00:00Z")
    minor = file_damage(
        shell["id"], cast["reporter"]["id"], cast["reporter_headers"], severity="MINOR"
    )
    triage_report(minor["id"], cast["boatman_headers"])
    set_clock_to(DEFAULT_CLOCK_ISO)
    verify_report_repair(major["id"], cast["boatman_headers"])
    return {
        "shell": read_shell(shell["id"]),
        "major_report": read_report(major["id"]),
        "minor_report": read_report(minor["id"]),
    }


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cast():
    """The standing cast of club members, with matching role headers."""
    return build_cast()


@pytest.fixture
def single_shell():
    """One AVAILABLE 1X hull."""
    return add_single()


@pytest.fixture
def coxed_four_shell():
    """One AVAILABLE 4+ hull, which occupies two trailer rack units."""
    return add_coxed_four()


@pytest.fixture
def home_regatta():
    """A HOME regatta OPEN_FOR_ENTRY, so no transport levy applies."""
    return open_regatta()


@pytest.fixture
def away_regatta():
    """An AWAY regatta OPEN_FOR_ENTRY, so hulls must be trailered."""
    return open_away_regatta()


@pytest.fixture
def open_reading(cast):
    """A river reading whose posture is OPEN."""
    return post_open_reading(cast["officer_headers"])


@pytest.fixture
def draft_entry(cast, home_regatta, single_shell):
    """A DRAFT 1X entry with no lineup yet."""
    entry = open_entry(home_regatta["id"], single_shell["id"], cast["coach_headers"])
    return {"regatta": home_regatta, "shell": single_shell, "entry": entry}


@pytest.fixture
def declared_entry(cast, home_regatta, single_shell):
    """A 1X entry at LINEUP_DECLARED with a single eligible rower seated."""
    entry = open_entry(home_regatta["id"], single_shell["id"], cast["coach_headers"])
    entry = declare_single_lineup(entry, cast["athlete"]["id"], cast["coach_headers"])
    return {"regatta": home_regatta, "shell": single_shell, "entry": entry}


@pytest.fixture
def submitted_entry(cast, home_regatta, single_shell):
    """A 1X entry at SUBMITTED with the on-time fee assessed."""
    entry = make_submitted_single_entry(
        home_regatta, single_shell, cast["athlete"]["id"], cast["coach_headers"]
    )
    return {"regatta": read_regatta(home_regatta["id"]), "shell": single_shell, "entry": entry}


@pytest.fixture
def confirmed_entry(cast, home_regatta, single_shell):
    """A 1X entry at CONFIRMED — in the lane-assignment candidate pool."""
    entry = make_confirmed_single_entry(
        home_regatta,
        single_shell,
        cast["athlete"]["id"],
        cast["coach_headers"],
        cast["official_headers"],
    )
    return {"regatta": read_regatta(home_regatta["id"]), "shell": single_shell, "entry": entry}


@pytest.fixture
def racing_heat(cast):
    """A RACING regatta whose heat sits at LANES_ASSIGNED with two crews."""
    return build_racing_regatta_with_lanes(cast)


@pytest.fixture
def provisional_heat(cast):
    """A heat at RESULTS_PROVISIONAL with an open 30-minute protest window."""
    return build_provisional_heat(cast)


@pytest.fixture
def filed_protest(cast):
    """A protest at FILED against a lane in a provisional heat."""
    return build_filed_protest(cast)


@pytest.fixture
def sealed_trailer(cast):
    """An away regatta with one racked entry on a SEALED trailer load."""
    return build_sealed_trailer_with_entry(cast)


@pytest.fixture
def open_trailer(cast, away_regatta):
    """An OPEN trailer load with the default four-by-four rack geometry."""
    return {
        "regatta": away_regatta,
        "trailer": open_trailer_load(
            away_regatta["id"], cast["driver"]["id"], cast["boatman_headers"]
        ),
    }


PROTEST_WINDOW_LENGTH_MINUTES = PROTEST_WINDOW_MINUTES
