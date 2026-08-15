"""Registration gates: classification, age grid, crossover caps, roster
bounds, eligibility loop, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_roster_entry,
    create_athlete,
    create_division_payload,
    create_roster_entry_payload,
    create_team,
    create_team_payload,
    get_success_data,
    make_team_coach_headers,
    setup_event_with_division,
    setup_registered_team,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["event_director_headers"]
ELIGIBILITY = TEST_USERS["eligibility_officer_headers"]


class TestTeamClassification:
    def test_team_classification_mismatch_rejected(self, api):
        """PRD §3.2: "Classification is strict: the team's `level` must equal
        the division's `level`, its `category` must equal the division's
        `category`, and the division must belong to the same event the team
        names; any mismatch is rejected with `ERR_DIVISION_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/team_classification_mismatch_rejected
        """
        event, division, panel, head, safety = setup_event_with_division()

        level_bad = create_team_payload(event["id"], division["id"], "coach-1",
                                        name="TX", level=4)
        resp = api.create_team(level_bad, make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_DIVISION_MISMATCH)

        cat_bad = create_team_payload(event["id"], division["id"], "coach-1",
                                      name="TY", category="DANCE")
        resp = api.create_team(cat_bad, make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_DIVISION_MISMATCH)


class TestRosterAgeGrid:
    def test_athlete_age_min_boundary_inclusive(self, api):
        """PRD §3.2: "the athlete's age at the event's `age_reference_date`
        must fall within the division's inclusive `min_age`–`max_age` band,
        else `ERR_ATHLETE_AGE_INELIGIBLE`."
        PRD §3.2: "An athlete's competitive age is the number of full years
        elapsed between `date_of_birth` and the event's `age_reference_date`."

        Design: Corner/validations/athlete_age_min_boundary_inclusive
        """
        event, division, panel, head, safety = setup_event_with_division(
            division_overrides={"min_age": 14, "max_age": 18})
        team = create_team(event["id"], division["id"], "coach-1")

        # Exactly 14 at the 2026-08-31 reference date: accepted.
        edge = create_athlete("Edge", "2012-08-31", "coach-1")
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], edge["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_success(resp, 201)

        # One day younger (13): rejected.
        young = create_athlete("Young", "2012-09-01", "coach-1")
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], young["id"], bib_number=2),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ATHLETE_AGE_INELIGIBLE)


class TestCrossoverCaps:
    def test_crossover_third_team_rejected_but_second_allowed(self, api):
        """PRD §3.2: "Second, crossover caps: an athlete may appear on at most
        2 teams within the same event — a third is rejected with
        `ERR_CROSSOVER_LIMIT_EXCEEDED`"

        Design: Corner/validations/crossover_third_team_rejected_but_second_allowed
        """
        event, division, panel, head, safety = setup_event_with_division()
        # Second division in the same event (DANCE) so the second entry is a
        # legal cross-division crossover.
        division2 = get_success_data(api.create_division(
            create_division_payload(
                event["id"], [j["id"] for j in panel],
                name="D2", category="DANCE",
                schedule_start_at="2026-09-05T14:00:00Z"),
            DIRECTOR))

        athlete = create_athlete("Ann", "2010-05-01", "coach-1")
        t1 = create_team(event["id"], division["id"], "coach-1", name="T1")
        t2 = create_team(event["id"], division2["id"], "coach-1", name="T2",
                         category="DANCE")
        t3 = create_team(event["id"], division2["id"], "coach-1", name="T3",
                         category="DANCE")

        resp = api.create_roster_entry(
            create_roster_entry_payload(t1["id"], athlete["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_success(resp, 201)
        resp = api.create_roster_entry(
            create_roster_entry_payload(t2["id"], athlete["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_success(resp, 201)

        resp = api.create_roster_entry(
            create_roster_entry_payload(t3["id"], athlete["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_CROSSOVER_LIMIT_EXCEEDED)

    def test_same_division_crossover_rejected(self, api):
        """PRD §3.2: "an athlete already rostered on another team in the
        *same division* is rejected outright with `ERR_SAME_DIVISION_CROSSOVER`."

        Design: Corner/validations/same_division_crossover_rejected
        """
        event, division, panel, head, safety = setup_event_with_division()
        athlete = create_athlete("Ann", "2010-05-01", "coach-1")
        t1 = create_team(event["id"], division["id"], "coach-1", name="T1")
        t2 = create_team(event["id"], division["id"], "coach-1", name="T2")

        resp = api.create_roster_entry(
            create_roster_entry_payload(t1["id"], athlete["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_success(resp, 201)

        resp = api.create_roster_entry(
            create_roster_entry_payload(t2["id"], athlete["id"], bib_number=1),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_SAME_DIVISION_CROSSOVER)


class TestRosterBounds:
    def test_roster_size_bounds_at_lock_and_create(self, api):
        """PRD §3.3: "the count of non-removed roster entries whose
        `eligibility_status` is `ACTIVE` must fall within the division's
        inclusive bounds — below `min_athletes` yields `ERR_ROSTER_TOO_SMALL`,
        above `max_athletes` yields `ERR_ROSTER_TOO_LARGE`."
        PRD §3.2: "Third, the addition must not push the team's non-removed
        roster count above the division's `max_athletes`
        (`ERR_ROSTER_TOO_LARGE`)."

        Design: Corner/validations/roster_size_bounds_at_lock_and_create
        """
        event, division, panel, head, safety = setup_event_with_division(
            division_overrides={"min_athletes": 2, "max_athletes": 3})
        team = create_team(event["id"], division["id"], "coach-1")
        athletes = [create_athlete(f"A{i}", f"2010-0{i}-01", "coach-1")
                    for i in range(5, 9)]

        add_roster_entry(team["id"], athletes[0]["id"], "coach-1", bib_number=1)

        # Lock with 1 active athlete (min 2): too small, team stays REGISTERED.
        resp = api.lock_roster(team["id"], make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ROSTER_TOO_SMALL)
        team_after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert team_after["reg_status"] == "REGISTERED"

        # Entries 2 and 3 succeed (count 3 == max, inclusive).
        add_roster_entry(team["id"], athletes[1]["id"], "coach-1", bib_number=2)
        add_roster_entry(team["id"], athletes[2]["id"], "coach-1", bib_number=3)

        # The 4th entry would exceed max_athletes 3.
        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], athletes[3]["id"],
                                        bib_number=4),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_ROSTER_TOO_LARGE)

    def test_roster_entry_with_bogus_fk_returns_not_found(self, api):
        """PRD §2.6: "**Existence** — path identifiers resolve left-to-right,
        then request-body foreign keys (`event_id`, `division_id`, `team_id`,
        `athlete_id`, `session_id`, and so on) resolve (`ERR_NOT_FOUND`)."

        Design: Corner/errors/roster_entry_with_bogus_fk_returns_not_found
        """
        event, division, panel, head, safety = setup_event_with_division()
        team = create_team(event["id"], division["id"], "coach-1")

        resp = api.create_roster_entry(
            create_roster_entry_payload(team["id"], NON_EXISTENT_UUID,
                                        bib_number=7),
            make_team_coach_headers("coach-1"))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEligibilityLoop:
    def test_roster_eligibility_loop_active_ineligible_active(self, api):
        """PRD §3.2: "Eligibility review is a separate loop owned by the
        `EligibilityOfficer`, who flips an entry's `eligibility_status` between
        `ACTIVE` and `INELIGIBLE` via a payload carrying the desired
        `eligibility_status`."
        PRD §3.2: "Eligibility changes are permitted only while the team is
        `REGISTERED` or `ROSTER_LOCKED`"

        Design: Corner/state_machines/roster_eligibility_loop_active_ineligible_active
        """
        event, division, panel, head, safety = setup_event_with_division()
        team, athlete, entry = setup_registered_team(division, coach_id="coach-1")

        resp = api.set_eligibility(entry["id"], "INELIGIBLE", ELIGIBILITY)
        data = validate_success(resp, 200)
        assert data["eligibility_status"] == "INELIGIBLE"

        resp = api.set_eligibility(entry["id"], "ACTIVE", ELIGIBILITY)
        data = validate_success(resp, 200)
        assert data["eligibility_status"] == "ACTIVE"


class TestWithdrawalLockdown:
    def test_withdrawn_team_cannot_withdraw_again(self, api):
        """PRD §3.3: "A coach may **withdraw** their own team
        (ownership-checked against `coach_user_id`, else `ERR_FORBIDDEN`)
        from `REGISTERED`, `ROSTER_LOCKED`, or `CHECKED_IN`; from any other
        state the attempt is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/withdrawn_team_cannot_withdraw_again
        """
        event, division, panel, head, safety = setup_event_with_division()
        team = create_team(event["id"], division["id"], "coach-1")
        coach = make_team_coach_headers("coach-1")

        resp = api.withdraw_team(team["id"], coach)
        validate_success(resp, 200)

        resp = api.withdraw_team(team["id"], coach)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_team(team["id"], DIRECTOR))
        assert after["reg_status"] == "WITHDRAWN"
