"""Derived numbers: the PD cycle, the roster snapshot, adequacy and alignment."""

from test_helpers import (
    assert_assignment_verdict,
    assert_fields,
    assert_hours,
    assert_ordered_codes,
    assert_program_adequacy,
    assert_roster_snapshot,
    assert_score,
    assignment_payload,
    make_assignment,
    make_credentialed_faculty,
    make_discipline,
    make_faculty,
    make_generated_roster,
    make_pd_record,
    make_program,
    make_program_dean_headers,
    make_section,
    read_assignment,
    read_faculty,
    read_program,
    read_roster,
    read_section,
    set_pd_status,
    validate_success,
    withdraw_assignment,
    TEST_USERS,
)


class TestProfessionalDevelopmentCycle:
    def test_only_verified_relevant_in_window_hours_reach_the_cycle_total(
        self, api, env
    ):
        """PRD §3.8: "A record is relevant when its `status` is `VERIFIED`, its
        `activity_date` falls inside that window, and its `discipline_id` aligns with
        the home program's discipline at 0.70 or above."

        Design: Corner/calculations/pd_compliance_counts_only_verified_relevant_in_cycle_hours
        """
        dana = make_faculty(
            "Dana Reyes", "dana.reyes@example.edu", "ADJUNCT", env.prog_df_id
        )
        exact = make_pd_record(
            dana["id"], env.journ_id, "CONFERENCE", 12.0, "2026-07-01"
        )
        parent = make_pd_record(
            dana["id"], env.comm_id, "COURSEWORK", 8.0, "2026-06-01"
        )
        sibling = make_pd_record(
            dana["id"], env.pr_id, "CERTIFICATION", 30.0, "2026-05-01"
        )
        unverified = make_pd_record(
            dana["id"], env.journ_id, "PUBLICATION", 5.0, "2026-04-01"
        )
        too_old = make_pd_record(
            dana["id"], env.journ_id, "INDUSTRY_PLACEMENT", 6.0, "2023-12-20"
        )
        set_pd_status(exact["id"], "VERIFIED")
        set_pd_status(sibling["id"], "VERIFIED")
        set_pd_status(too_old["id"], "VERIFIED")

        set_pd_status(parent["id"], "VERIFIED")

        faculty = read_faculty(dana["id"])
        assert_hours(faculty["pd_hours_current_cycle"], 20.0, "pd_hours_current_cycle")
        assert_fields(faculty, pd_compliant=True)
        assert_fields(exact, discipline_relevant=True)
        assert_fields(parent, discipline_relevant=True)
        assert_fields(sibling, discipline_relevant=False)
        assert_fields(
            validate_success(
                api.get_pd_record(unverified["id"], TEST_USERS["registrar"])
            ),
            status="SUBMITTED",
        )
        assert_fields(too_old, discipline_relevant=True, activity_date="2023-12-20")


def _two_instructors(env):
    """Morgan (aligned Journalism master's) and Alex (Public Relations only)."""
    morgan = make_credentialed_faculty(
        "Morgan Ellis",
        "morgan.ellis@example.edu",
        "FULL_TIME",
        env.prog_cw_id,
        "MASTERS",
        env.journ_id,
        "Lakeside University",
        graduate_credit_hours_in_discipline=36,
    )["faculty"]
    alex = make_credentialed_faculty(
        "Alex Stone",
        "alex.stone@example.edu",
        "ADJUNCT",
        env.prog_cw_id,
        "MASTERS",
        env.pr_id,
        "Harbor College",
        graduate_credit_hours_in_discipline=30,
    )["faculty"]
    return morgan, alex


class TestRosterIncludedSet:
    def test_superseded_and_withdrawn_rows_leave_the_snapshot(self, api, env):
        """PRD §3.6: "The **included set** for a roster is every course assignment
        whose section's `program_id` and `term_id` match the roster's and whose
        `status` is neither `SUPERSEDED` nor `WITHDRAWN`."

        Design: Corner/calculations/roster_snapshot_excludes_superseded_and_withdrawn_assignments
        """
        morgan, alex = _two_instructors(env)
        monday = make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR101",
            "News Writing",
            credit_hours=3,
            meeting_days=["MON"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )
        tuesday = make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR104",
            "Data Journalism",
            credit_hours=3,
            meeting_days=["TUE"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )
        superseded = make_assignment(monday["id"], morgan["id"], env.prog_df_id)
        withdrawn = make_assignment(tuesday["id"], alex["id"], env.prog_df_id)
        survivor = make_assignment(
            monday["id"],
            alex["id"],
            env.prog_df_id,
            expected_section_version=read_section(monday["id"])["version"],
        )
        withdraw_assignment(
            withdrawn["id"], env.prog_df_id, reason="Tuesday section reassigned"
        )

        roster = make_generated_roster(env.prog_df_id, env.term_id)

        assert_fields(
            read_assignment(superseded["id"]),
            status="SUPERSEDED",
            superseded_by_assignment_id=survivor["id"],
        )
        assert_fields(read_assignment(withdrawn["id"]), status="WITHDRAWN")
        assert_roster_snapshot(
            roster,
            total_assignment_count=1,
            distinct_faculty_count=1,
            flagged_exception_count=1,
            terminal_qualified_headcount=0,
            credit_hours_total=3,
            credit_hours_terminal_qualified=0,
            adequacy_ratio_snapshot=0.0000,
            blocking_reason_codes=["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
            certification_readiness="BLOCKED",
        )
        assert read_faculty(morgan["id"])["assigned_credit_hours"] == 0
        assert read_faculty(alex["id"])["assigned_credit_hours"] == 3
        assert_fields(read_program(env.prog_df_id), unqualified_assignment_count=1)


def _credit_hour_roster(env):
    """One terminal credit hour out of three on the CREDIT_HOUR_COVERAGE program."""
    morgan, alex = _two_instructors(env)
    one_credit = make_section(
        env.prog_cw_id,
        env.term_id,
        env.journ_id,
        "JOUR190",
        "Newsroom Lab",
        credit_hours=1,
        meeting_days=["WED"],
        meeting_start_minute=540,
        meeting_end_minute=600,
    )
    two_credit = make_section(
        env.prog_cw_id,
        env.term_id,
        env.journ_id,
        "JOUR191",
        "Media Ethics",
        credit_hours=2,
        meeting_days=["THU"],
        meeting_start_minute=540,
        meeting_end_minute=660,
    )
    qualified = make_assignment(one_credit["id"], morgan["id"], env.prog_cw_id)
    flagged = make_assignment(two_credit["id"], alex["id"], env.prog_cw_id)
    roster = make_generated_roster(env.prog_cw_id, env.term_id)
    return {
        "morgan_id": morgan["id"],
        "alex_id": alex["id"],
        "qualified": qualified,
        "flagged": flagged,
        "roster": roster,
    }


class TestAdequacyPrecision:
    def test_a_non_terminating_quotient_is_stored_at_four_decimals(self, api, env):
        """PRD §3.6: "Under `CREDIT_HOUR_COVERAGE`, the denominator is the sum of
        `CourseSection.credit_hours` over the included set and the numerator is that
        same sum over the terminal subset."

        Design: Corner/calculations/adequacy_ratio_rounds_to_four_decimals_on_the_credit_hour_basis
        """
        state = _credit_hour_roster(env)
        assert_assignment_verdict(
            state["qualified"],
            status="VERIFIED_QUALIFIED",
            qualification_basis="TERMINAL_DEGREE",
            exception_code=None,
            alignment_score=1.0000,
        )

        read = validate_success(
            api.get_program_adequacy(
                env.prog_cw_id, TEST_USERS["liaison"], {"term_id": env.term_id}
            )
        )

        assert_fields(
            read,
            numerator=1,
            denominator=3,
            basis_applied="CREDIT_HOUR_COVERAGE",
            adequacy_status="INSUFFICIENT",
            unqualified_assignment_count=1,
            roster_id=state["roster"]["id"],
        )
        assert_score(read["adequacy_ratio"], 0.3333, "adequacy_ratio")
        assert_roster_snapshot(
            read_roster(state["roster"]["id"]),
            adequacy_ratio_snapshot=0.3333,
            credit_hours_total=3,
            credit_hours_terminal_qualified=1,
        )
        assert_program_adequacy(
            read_program(env.prog_cw_id),
            adequacy_ratio=0.3333,
            adequacy_status="INSUFFICIENT",
        )


class TestAdequacyBasisOverride:
    def test_the_override_recomputes_for_one_read_and_persists_nothing(self, api, env):
        """PRD §3.1: "Supplying `basis_override` recomputes under the other variant
        and writes nothing — this is how an operator observes the `HEADCOUNT` and
        `CREDIT_HOUR_COVERAGE` divergence side by side."

        Design: Corner/calculations/basis_override_recomputes_adequacy_without_persisting_it
        """
        state = _credit_hour_roster(env)
        roster_version = read_roster(state["roster"]["id"])["version"]

        overridden = validate_success(
            api.get_program_adequacy(
                env.prog_cw_id,
                TEST_USERS["liaison"],
                {"term_id": env.term_id, "basis_override": "HEADCOUNT"},
            )
        )

        assert_fields(
            overridden,
            numerator=1,
            denominator=2,
            basis_applied="HEADCOUNT",
            adequacy_status="AT_RISK",
        )
        assert_score(overridden["adequacy_ratio"], 0.5000, "adequacy_ratio")
        program = read_program(env.prog_cw_id)
        assert_fields(program, adequacy_basis="CREDIT_HOUR_COVERAGE")
        assert_program_adequacy(
            program, adequacy_ratio=0.3333, adequacy_status="INSUFFICIENT"
        )
        assert_roster_snapshot(
            read_roster(state["roster"]["id"]),
            adequacy_ratio_snapshot=0.3333,
            version=roster_version,
        )


def _headcount_pair(env, program_id, qualified_id, flagged_id, first, second, building):
    """One qualified and one flagged instructor on two 3-credit sections."""
    sections = []
    for course_code, title, day in (first, second):
        sections.append(
            make_section(
                program_id,
                env.term_id,
                env.journ_id,
                course_code,
                title,
                credit_hours=3,
                building_code=building,
                meeting_days=[day],
                meeting_start_minute=540,
                meeting_end_minute=620,
            )
        )
    make_assignment(sections[0]["id"], qualified_id, program_id)
    make_assignment(sections[1]["id"], flagged_id, program_id)
    return make_generated_roster(program_id, env.term_id)


class TestAdequacyBands:
    def test_the_same_ratio_reads_adequate_or_at_risk_by_the_programs_minimum(
        self, api, env
    ):
        """PRD §3.6: "`adequacy_status` is then `ADEQUATE` when the ratio is at or
        above `min_terminal_ratio`; otherwise `AT_RISK` when the ratio is at or above
        `min_terminal_ratio` less a band of 0.15; otherwise `INSUFFICIENT`."

        Design: Corner/calculations/adequacy_bands_are_inclusive_at_the_minimum_and_at_the_at_risk_floor
        """
        morgan, alex = _two_instructors(env)
        strict_roster = _headcount_pair(
            env,
            env.prog_df_id,
            morgan["id"],
            alex["id"],
            ("JOUR101", "News Writing", "MON"),
            ("JOUR104", "Data Journalism", "TUE"),
            "HALL-A",
        )
        lenient = make_program(
            "BA Media Studies",
            env.journ_id,
            degree_level="BACHELORS",
            qualification_policy="DEGREE_FIELD",
            adequacy_basis="HEADCOUNT",
            min_terminal_ratio=0.50,
            credential_budget_cents=300000,
        )
        lenient_roster = _headcount_pair(
            env,
            lenient["id"],
            morgan["id"],
            alex["id"],
            ("JOUR150", "Media History", "WED"),
            ("JOUR151", "Media Criticism", "THU"),
            "HALL-C",
        )

        strict = validate_success(
            api.get_program_adequacy(
                env.prog_df_id, TEST_USERS["liaison"], {"term_id": env.term_id}
            )
        )
        generous = validate_success(
            api.get_program_adequacy(
                lenient["id"], TEST_USERS["liaison"], {"term_id": env.term_id}
            )
        )

        assert_score(strict["adequacy_ratio"], 0.5000, "adequacy_ratio at min 0.60")
        assert_fields(strict, adequacy_status="AT_RISK")
        assert_score(generous["adequacy_ratio"], 0.5000, "adequacy_ratio at min 0.50")
        assert_fields(generous, adequacy_status="ADEQUATE")
        assert_roster_snapshot(
            read_roster(strict_roster["id"]),
            blocking_reason_codes=["EXCEPTIONS_OUTSTANDING", "ADEQUACY_BELOW_MINIMUM"],
            certification_readiness="BLOCKED",
        )
        assert_roster_snapshot(
            read_roster(lenient_roster["id"]),
            blocking_reason_codes=["EXCEPTIONS_OUTSTANDING"],
            certification_readiness="BLOCKED",
        )
        assert_fields(read_program(env.prog_df_id), unqualified_assignment_count=1)
        assert_fields(read_program(lenient["id"]), unqualified_assignment_count=1)


class TestGrandparentAlignment:
    def test_a_grandparent_discipline_only_matches_on_the_code_prefix(self, api, env):
        """PRD §2.9: "**Only one level of parenthood is ever honored.** A grandparent
        discipline is treated as unrelated to its grandchild by the alignment rule; it
        never earns the parent score."

        Design: Corner/calculations/grandparent_discipline_falls_through_to_the_code_prefix_rule
        """
        broadcast = make_discipline(
            "09.05",
            "Broadcast Journalism",
            required_terminal_degree_level="MASTERS",
            parent_discipline_id=env.journ_id,
            min_graduate_credit_hours=18,
        )
        rin = make_credentialed_faculty(
            "Rin Alvarez",
            "rin.alvarez@example.edu",
            "ADJUNCT",
            env.prog_df_id,
            "MASTERS",
            broadcast["id"],
            "Coastal University",
            graduate_credit_hours_in_discipline=30,
        )["faculty"]
        parent_section = make_section(
            env.prog_df_id,
            env.term_id,
            env.journ_id,
            "JOUR101",
            "News Writing",
            credit_hours=3,
            meeting_days=["MON"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )
        grandparent_section = make_section(
            env.prog_df_id,
            env.term_id,
            env.comm_id,
            "COMM101",
            "Introduction to Communication",
            credit_hours=3,
            meeting_days=["TUE"],
            meeting_start_minute=540,
            meeting_end_minute=620,
        )

        to_parent = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    parent_section["id"], rin["id"], parent_section["version"]
                ),
                make_program_dean_headers(env.prog_df_id),
            ),
            201,
        )
        to_grandparent = validate_success(
            api.create_course_assignment(
                assignment_payload(
                    grandparent_section["id"], rin["id"], grandparent_section["version"]
                ),
                make_program_dean_headers(env.prog_df_id),
            ),
            201,
        )

        assert_assignment_verdict(
            to_parent,
            status="VERIFIED_QUALIFIED",
            qualification_basis="TERMINAL_DEGREE",
            exception_code=None,
            alignment_score=0.7100,
        )
        assert_assignment_verdict(
            to_grandparent,
            status="EXCEPTION_FLAGGED",
            qualification_basis="NONE",
            exception_code="DISCIPLINE_MISALIGNED",
            alignment_score=0.4000,
        )
        assert read_faculty(rin["id"])["assigned_credit_hours"] == 6, (
            "six credit hours sits under the ADJUNCT cap of nine, so both "
            "assignments are live"
        )
        assert_ordered_codes(
            read_faculty(rin["id"])["deficiency_codes"], [], "deficiency_codes"
        )
