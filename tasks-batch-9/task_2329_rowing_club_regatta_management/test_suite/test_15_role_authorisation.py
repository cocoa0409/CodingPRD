"""Who may act, and who may not act on their own work: the dock officer's exclusive
reading, two role-exclusivity refusals, and the four segregation-of-duties checks the
club's insurers require — each paired with the neutral colleague who may proceed.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    CLUB_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    api_client,
    assert_damage_report,
    assert_lineup_seat,
    assert_protest,
    assert_water_condition_reading,
    assert_water_session,
    make_coach_headers,
    make_equipment_manager_headers,
    make_jury_chair_headers,
    make_member_headers,
    make_race_official_headers,
    make_safety_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.constants import FAR_FUTURE_CERT
from test_helpers.factories import create_reading_payload
from test_helpers.fixtures import (
    add_coxed_four,
    add_single,
    book_session,
    clear_session,
    coxswain_seat_of_entry,
    declare_coxed_four_lineup,
    enrol_athlete,
    enrol_boatman,
    enrol_coach,
    enrol_coxswain,
    enrol_officer,
    file_damage,
    open_entry,
    open_regatta,
    open_review,
    post_open_reading,
    read_protest,
    read_report,
    read_session,
    set_clock_to,
    triage_report,
)

INSIDE_WEIGH_IN_WINDOW = "2026-08-12T06:30:00Z"
MIN_COXSWAIN_WEIGHT_KG = 55.0


@pytest.fixture
def report_filed_by_a_boatman():
    """A MINOR report filed by one equipment manager, with a colleague on hand."""
    filer = enrol_boatman("Enid Boatman")
    colleague = enrol_boatman("Owen Boatman", body_weight_kg=79.0)
    shell = add_single(hull_name="Kingfisher")
    report = file_damage(
        shell["id"],
        filer["id"],
        make_equipment_manager_headers(filer["id"]),
        severity="MINOR",
        narrative="scuffed bow ball",
    )
    return {
        "filer": filer,
        "filer_headers": make_equipment_manager_headers(filer["id"]),
        "colleague": colleague,
        "colleague_headers": make_equipment_manager_headers(colleague["id"]),
        "shell": shell,
        "report": report,
    }


@pytest.fixture
def session_coached_by_a_dual_role_member():
    """An outing whose coach also holds the dock officer's capacity."""
    dual = enrol_coach(
        "Dana Dual",
        club_roles=["COACH", "LAUNCH_DRIVER"],
        safety_launch_cert_expires_at=FAR_FUTURE_CERT,
    )
    officer = enrol_officer("Sam Officer")
    rita = enrol_athlete("Rita Rower", "COMPETITIVE", 70.0)
    shell = add_single(hull_name="Kingfisher")
    reading = post_open_reading(make_safety_officer_headers(officer["id"]))
    session = book_session(
        shell["id"],
        make_coach_headers(dual["id"]),
        coach_member_id=dual["id"],
        athlete_member_ids=[rita["id"]],
    )
    return {
        "dual": dual,
        "dual_officer_headers": make_safety_officer_headers(dual["id"]),
        "officer": officer,
        "officer_headers": make_safety_officer_headers(officer["id"]),
        "shell": shell,
        "reading": reading,
        "session": session,
    }


@pytest.fixture
def coxswain_seat_inside_the_weigh_in_window(cast):
    """A declared 4+ whose coxswain also acts on the race committee."""
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
    seat = coxswain_seat_of_entry(entry["id"], cast["official_headers"])
    set_clock_to(INSIDE_WEIGH_IN_WINDOW)
    return {
        "regatta": regatta,
        "entry": entry,
        "cox": cox,
        "cox_official_headers": make_race_official_headers(cox["id"]),
        "seat": seat,
    }


class TestDockOfficerReading:
    def test_the_safety_officer_may_post_a_river_reading(self):
        """The positive half of the role model: the dock officer's own endpoint.

        PRD: "A `SafetyOfficer` posts a river-condition reading as an immutable
        observation: `observed_at`, `air_temp_c`, `water_temp_c` and `wind_speed_kt`
        each at one decimal place, `visibility_m` as whole metres of horizontal
        visibility, and the `traffic_pattern` in force"

        Design: Corner/rbac/corner_safety_officer_allowed_to_post_condition_reading
        """
        officer = enrol_officer("Sam Officer")
        reading = assert_water_condition_reading(
            validate_success(
                api_client.create_water_condition_reading(
                    create_reading_payload(),
                    make_safety_officer_headers(officer["id"]),
                ),
                201,
            )
        )
        assert reading["posture"] == "OPEN", (
            "warm water, light air and three kilometres of visibility leave the "
            f"river open, got {reading['posture']}"
        )
        assert reading["cold_water_flag"] is False, (
            f"18.0 degrees of water raises no cold flag, got {reading['cold_water_flag']}"
        )
        assert "version" not in reading, (
            "an immutable observation carries no version, got the keys "
            f"{sorted(reading)}"
        )


class TestRoleExclusivity:
    def test_an_ordinary_member_may_not_open_a_race_entry(self, home_regatta, single_shell):
        """Opening an entry is the coach's act, and the refusal is an authorisation one.

        PRD: "A `Coach` books water sessions, opens entries, declares lineups,
        submits entries and scratches them."

        Design: Corner/rbac/corner_member_cannot_create_regatta_entry_returns_403
        """
        rita = enrol_athlete("Rita Rower", "RECREATIONAL", 70.0)

        response = api_client.create_regatta_entry(
            {
                "regatta_id": home_regatta["id"],
                "shell_id": single_shell["id"],
                "event_code": "M1X_OPEN",
                "boat_class": "1X",
                "seed_time_seconds": 380.0,
            },
            make_member_headers(rita["id"]),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)

        _rows, meta = validate_paginated(
            api_client.list_regatta_entries(
                CLUB_ADMIN_HEADERS, {"regatta_id": home_regatta["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"no entry was opened, got {meta['total_count']}"
        )

    def test_the_role_check_answers_before_the_identifier_is_resolved(self, cast):
        """A coach calling the host's endpoint on a fictional entry still gets a 403.

        PRD: "2. Role authorisation for the called operation, and resolution of an
        entity-backed role's `X-User-ID` to a `Member` — `ERR_UNAUTHORIZED`. Applies
        to every endpoint."

        Design: Corner/rbac/corner_coach_cannot_confirm_entry_returns_403_before_path_resolution
        """
        response = api_client.confirm_regatta_entry(
            NON_EXISTENT_UUID, {}, cast["coach_headers"]
        )
        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
        assert error["error_id"] != ApiErrorId.ERR_ENTRY_NOT_FOUND.value, (
            "the unknown identifier is never reached, so the answer is not a 404, "
            f"got {error['error_id']}"
        )


class TestSelfTriageIsForbidden:
    def test_the_boatman_who_filed_the_damage_may_not_triage_it(
        self, report_filed_by_a_boatman
    ):
        """Holding the endpoint is not enough when the report is your own.

        PRD: "The member who filed a damage report may neither triage it nor verify
        its repair; either attempt is rejected with `ERR_SELF_TRIAGE_FORBIDDEN`."

        Design: Corner/rbac/corner_equipment_manager_cannot_triage_own_report_returns_403
        """
        scenario = report_filed_by_a_boatman

        response = api_client.triage_damage_report(
            scenario["report"]["id"], {"disposition": "REPAIR"}, scenario["filer_headers"]
        )
        validate_error(response, ApiErrorId.ERR_SELF_TRIAGE_FORBIDDEN.value)

        stored = assert_damage_report(read_report(scenario["report"]["id"]))
        assert stored["status"] == "REPORTED", (
            f"the report has not moved, got {stored['status']}"
        )
        assert stored["triaged_by_user_id"] is None, (
            f"and nobody is stamped as having triaged it, got {stored['triaged_by_user_id']}"
        )

    def test_a_second_boatman_may_triage_the_same_report(self, report_filed_by_a_boatman):
        """The refusal is about identity, not about the endpoint.

        PRD: "An `EquipmentManager` triages a `REPORTED` report by supplying a
        `disposition`. A `disposition` of `REPAIR` moves it `REPORTED → TRIAGED` and
        stamps `triaged_by_user_id`."

        Design: Corner/rbac/corner_equipment_manager_cannot_triage_own_report_returns_403
        """
        scenario = report_filed_by_a_boatman
        triaged = assert_damage_report(
            triage_report(scenario["report"]["id"], scenario["colleague_headers"])
        )
        assert triaged["status"] == "TRIAGED", (
            f"the colleague's triage lands, got {triaged['status']}"
        )
        assert triaged["triaged_by_user_id"] == scenario["colleague"]["id"], (
            "and stamps the acting colleague, expected "
            f"{scenario['colleague']['id']}, got {triaged['triaged_by_user_id']}"
        )


class TestSelfClearanceIsForbidden:
    def test_a_coach_may_not_sign_off_their_own_outing(
        self, session_coached_by_a_dual_role_member
    ):
        """One person in two capacities is still one person.

        PRD: "The coach named on a water session may not sign that session's own
        safety clearance — `ERR_SELF_CLEARANCE_FORBIDDEN`."

        Design: Corner/rbac/corner_coach_cannot_clear_own_session_returns_403
        """
        scenario = session_coached_by_a_dual_role_member

        response = api_client.clear_water_session(
            scenario["session"]["id"],
            {"reading_id": scenario["reading"]["id"]},
            scenario["dual_officer_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SELF_CLEARANCE_FORBIDDEN.value)

        stored = assert_water_session(read_session(scenario["session"]["id"]))
        assert stored["status"] == "PLANNED", (
            f"the outing is not cleared to go afloat, got {stored['status']}"
        )
        assert stored["reading_id"] is None, (
            f"and no reading was recorded against it, got {stored['reading_id']}"
        )

    def test_an_independent_officer_may_clear_the_same_outing(
        self, session_coached_by_a_dual_role_member
    ):
        """The clearance itself is sound; only the signatory was wrong.

        PRD: "A successful clearance moves the session `PLANNED → CLEARED` and drives
        the hull `AVAILABLE → ASSIGNED`."

        Design: Corner/rbac/corner_coach_cannot_clear_own_session_returns_403
        """
        scenario = session_coached_by_a_dual_role_member
        cleared = assert_water_session(
            clear_session(
                scenario["session"]["id"],
                scenario["reading"]["id"],
                scenario["officer_headers"],
            )
        )
        assert cleared["status"] == "CLEARED", (
            f"the independent officer's clearance lands, got {cleared['status']}"
        )
        assert cleared["reading_id"] == scenario["reading"]["id"], (
            "and the decision is recorded against the named reading, got "
            f"{cleared['reading_id']}"
        )


class TestJuryConflictOfInterest:
    def test_the_filer_may_not_open_review_on_their_own_protest(self, filed_protest):
        """A jury seat does not cure a personal interest in the outcome.

        PRD: "Conflict-of-interest screening applies: the acting chair may not be the
        protest's `filed_by_member_id`, and — when opening from `FILED` — may not hold
        a `LineupSeat` on any entry that holds a race lane on the protested heat;
        either bars the request with `ERR_JURY_CONFLICT_OF_INTEREST`."

        Design: Corner/rbac/corner_jury_chair_cannot_open_review_on_own_protest_returns_403
        """
        protest = filed_protest["protest"]
        filer = filed_protest["filer"]

        response = api_client.open_protest_review(
            protest["id"], {}, make_jury_chair_headers(filer["id"])
        )
        validate_error(response, ApiErrorId.ERR_JURY_CONFLICT_OF_INTEREST.value)

        stored = assert_protest(read_protest(protest["id"]))
        assert stored["status"] == "FILED", (
            f"the protest is still merely filed, got {stored['status']}"
        )
        assert stored["review_round"] == 0, (
            f"no round has been opened, got {stored['review_round']}"
        )
        assert stored["jury_user_id"] is None, (
            f"and no chair is stamped on it, got {stored['jury_user_id']}"
        )

    def test_a_neutral_chair_may_open_the_same_review(self, cast, filed_protest):
        """The protest is reviewable; only that chair was not.

        PRD: "Opening increments `review_round` by one, stamps `jury_user_id` with
        the acting chair, and moves the protest to `UNDER_JURY_REVIEW` — `FILED →
        UNDER_JURY_REVIEW` or `REMANDED → UNDER_JURY_REVIEW`."

        Design: Corner/rbac/corner_jury_chair_cannot_open_review_on_own_protest_returns_403
        """
        protest = filed_protest["protest"]
        opened = assert_protest(
            open_review(protest["id"], cast["chair_headers"])
        )
        assert opened["status"] == "UNDER_JURY_REVIEW", (
            f"the neutral chair's review opens, got {opened['status']}"
        )
        assert opened["review_round"] == 1, (
            f"and counts as the first round, got {opened['review_round']}"
        )
        assert opened["jury_user_id"] == cast["chair"]["id"], (
            "stamping the acting chair, expected "
            f"{cast['chair']['id']}, got {opened['jury_user_id']}"
        )


class TestSelfWeighInIsForbidden:
    def test_a_coxswain_may_not_record_their_own_weight(
        self, coxswain_seat_inside_the_weigh_in_window
    ):
        """Inside an open window, so the refusal is about identity, not timing.

        PRD: "A coxswain may not record their own weigh-in, so a weigh-in whose
        acting `X-User-ID` equals the seat's `member_id` is rejected with
        `ERR_SELF_WEIGH_IN_FORBIDDEN`."

        Design: Corner/rbac/corner_race_official_cannot_weigh_in_own_seat_returns_403
        """
        scenario = coxswain_seat_inside_the_weigh_in_window

        response = api_client.weigh_in_lineup_seat(
            scenario["seat"]["id"],
            {"weighed_kg": 52.0},
            scenario["cox_official_headers"],
        )
        validate_error(response, ApiErrorId.ERR_SELF_WEIGH_IN_FORBIDDEN.value)

        stored = assert_lineup_seat(
            coxswain_seat_of_entry(scenario["entry"]["id"], CLUB_ADMIN_HEADERS)
        )
        assert stored["weigh_in_status"] == "NOT_REQUIRED", (
            f"the seat has not been through the scales, got {stored['weigh_in_status']}"
        )
        assert stored["weighed_kg"] is None, (
            f"no weight was recorded, got {stored['weighed_kg']}"
        )
        assert stored["weighed_by_user_id"] is None, (
            f"and nobody is stamped as having weighed it, got {stored['weighed_by_user_id']}"
        )

    def test_a_neutral_official_may_weigh_the_same_seat(
        self, cast, coxswain_seat_inside_the_weigh_in_window
    ):
        """The scales work; only the hand on them was wrong.

        PRD: "The recorded weight and the acting `weighed_by_user_id` are stamped on
        the seat. For a `COXSWAIN` seat, `deadweight_kg` is the club's minimum
        coxswain weight of 55.0 kilograms less the recorded weight, floored at zero
        and rounded half up to one decimal place — the sandbag the crew must carry."

        Design: Corner/rbac/corner_race_official_cannot_weigh_in_own_seat_returns_403
        """
        scenario = coxswain_seat_inside_the_weigh_in_window
        weighed = assert_lineup_seat(
            validate_success(
                api_client.weigh_in_lineup_seat(
                    scenario["seat"]["id"],
                    {"weighed_kg": 52.0},
                    cast["official_headers"],
                )
            )
        )
        assert weighed["weighed_kg"] == pytest.approx(52.0, abs=0.01), (
            f"the recorded weight is persisted, got {weighed['weighed_kg']}"
        )
        assert weighed["weighed_by_user_id"] == cast["official"]["id"], (
            "and the acting official is stamped, expected "
            f"{cast['official']['id']}, got {weighed['weighed_by_user_id']}"
        )
        assert weighed["deadweight_kg"] == pytest.approx(
            MIN_COXSWAIN_WEIGHT_KG - 52.0, abs=0.01
        ), (
            "55.0 less 52.0 is a 3.0 kilogram sandbag, got "
            f"{weighed['deadweight_kg']}"
        )
