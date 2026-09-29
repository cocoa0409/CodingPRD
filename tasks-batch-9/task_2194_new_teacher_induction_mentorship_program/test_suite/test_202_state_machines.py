"""State machines: initial states, valid transitions and their declared side
effects, terminal lockdown, and the cascades one transition sets off elsewhere.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_COHORT_STATE_INVALID,
    ERR_CONTACT_LOG_STATE_INVALID,
    ERR_OBSERVATION_PHASE_INVALID,
    ERR_TRAINING_REQUIREMENTS_NOT_MET,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_two_decimals,
)
from test_helpers.constants import CLOCK_INITIAL_UTC
from test_helpers.fixtures import (
    attainment_for,
    attest_attainment,
    build_program,
    create_certified_mentor,
    create_cohort,
    create_mentor,
    create_novice,
    create_site,
    define_milestone,
    document_observation_cycle,
    hold_session,
    open_observation_cycle,
    post_certify_training,
    read_attainment,
    read_cohort,
    read_contact_log,
    read_cycle,
    read_match,
    read_mentor,
    read_novice,
    read_readiness,
    read_session,
    read_site,
    record_attendance,
    schedule_seminar_session,
    set_clock,
    submit_contact_log,
)
from test_helpers.test_users import ADMIN, PROGRAM_OFFICE_1, make_mentor_headers, make_site_lead_headers


class TestMentorCertificationTransitions:
    """The CERTIFY action and the module half of its precondition."""

    def test_mentor_certify_transitions_uncertified_to_certified(
        self, api: InductionApiClient
    ):
        """18.00 hours across the three modules certifies for a year and empties the ledger.

        The PRD spells out the precondition and every effect: "Success sets
        `certification_expires_on` to the current logical time plus 365 days,
        resets the hour ledger and module list, clears `suspension_reason` to null,
        and bumps the mentor's `version`."

        Design: Corner/state_machines/mentor_certify_transitions_uncertified_to_certified
        """
        site = create_site(api)
        mentor = create_mentor(api, site["id"])
        post_certify_training(api, mentor["id"])

        certified = validate_success(
            api.certification_action(mentor["id"], f.certification_payload("CERTIFY"), ADMIN)
        )
        assert certified["certification_status"] == "CERTIFIED", (
            f"the mentor leaves UNCERTIFIED, got {certified['certification_status']}"
        )
        assert_instant_equals(
            certified["certification_expires_on"],
            "2027-08-01T00:00:00Z",
            "certification_expires_on",
        )
        assert_two_decimals(
            certified["training_hours_current_cycle"], 0.00, "training_hours_current_cycle"
        )
        assert certified["training_modules_current_cycle"] == [], (
            "the reset empties the module list too, got "
            f"{certified['training_modules_current_cycle']}"
        )
        assert certified["suspension_reason"] is None, (
            f"certification clears any suspension note, got {certified['suspension_reason']}"
        )

    def test_certify_without_equity_module_rejected(self, api: InductionApiClient):
        """Eighteen hours across only two of the three modules is still a shortfall.

        The PRD makes the module set an independent condition: "It requires that
        the mentor currently be `UNCERTIFIED`, that `training_hours_current_cycle`
        be at least 18.00 hours, and that the current cycle's module list contain
        all three of `FOUNDATIONS`, `OBSERVATION_PROTOCOL` and `EQUITY` — that is,
        all three initial modules must be present, though additional modules do no
        harm."

        Design: Corner/state_machines/certify_without_equity_module_rejected
        """
        site = create_site(
            api, name="Southbank Middle", site_code="SB002", region_code="SOUTH"
        )
        mentor = create_mentor(
            api, site["id"], full_name="Ken Osei", subject_endorsements=["ELA"]
        )
        get_success_data(
            api.post_training_credit(
                mentor["id"], f.training_credit_payload("FOUNDATIONS", 8.00), ADMIN
            )
        )
        get_success_data(
            api.post_training_credit(
                mentor["id"],
                f.training_credit_payload(
                    "OBSERVATION_PROTOCOL", 10.00, completed_on="2026-07-11"
                ),
                ADMIN,
            )
        )

        response = api.certification_action(
            mentor["id"], f.certification_payload("CERTIFY"), ADMIN
        )
        validate_error(response, ERR_TRAINING_REQUIREMENTS_NOT_MET, 422)

        stored = read_mentor(api, mentor["id"])
        assert stored["certification_status"] == "UNCERTIFIED", (
            f"the refused action leaves the mentor alone, got {stored['certification_status']}"
        )
        assert_two_decimals(
            stored["training_hours_current_cycle"], 18.00, "training_hours_current_cycle"
        )
        assert stored["certification_expires_on"] is None, (
            f"no expiry is stamped by a refused certification, got "
            f"{stored['certification_expires_on']}"
        )


class TestSeminarSessionResolution:
    """Holding and cancelling a session, and how far each reaches.

    Attendance is taken while the session is still open, which is the order the
    contract requires.
    """

    def test_seminar_hold_stamps_held_at_and_bubbles_cohort_to_running(
        self, api: InductionApiClient
    ):
        """One HELD call stamps the clock, drags the cohort along and re-scores the novice.

        The PRD lists the whole effect set in one sentence: "It stamps `held_at`;
        it drags the cohort from `FORMING` to `RUNNING` if the cohort is still
        forming; and it then recomputes `credited_seminar_sessions` and
        `readiness_index_live` for every novice holding an attendance row against
        that session, processing those novices in the `created_at` ascending order
        of their attendance rows, which may lift any of them from `NOT_ELIGIBLE` to
        `ELIGIBLE`."

        Design: Corner/state_machines/seminar_hold_stamps_held_at_and_bubbles_cohort_to_running
        """
        site = create_site(api)
        cohort = create_cohort(api)
        novice = create_novice(api, site["id"], cohort["id"])
        session = schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-05T15:00:00Z",
            "2026-08-05T16:30:00Z",
            topic="Classroom routines",
        )
        record_attendance(
            api,
            session["id"],
            novice["id"],
            "PRESENT",
            90,
            make_site_lead_headers(site["id"]),
        )
        set_clock(api, "2026-08-05T16:45:00Z")

        held = validate_success(
            api.set_session_status(session["id"], f.session_status_payload("HELD"), ADMIN)
        )
        assert held["status"] == "HELD", f"the session resolves as held, got {held['status']}"
        assert_instant_equals(held["held_at"], "2026-08-05T16:45:00Z", "held_at")
        assert held["credited_attendance_count"] == 1, (
            f"the one credited row is counted, got {held['credited_attendance_count']}"
        )

        assert read_cohort(api, cohort["id"])["status"] == "RUNNING", (
            "the first held session drags a forming cohort to RUNNING"
        )

        stored_novice = read_novice(api, novice["id"])
        assert stored_novice["credited_seminar_sessions"] == 1, (
            "the credit only counts for the novice once the session is held, got "
            f"{stored_novice['credited_seminar_sessions']}"
        )
        assert_two_decimals(
            stored_novice["readiness_index_live"], 25.00, "readiness_index_live"
        )

        readiness = read_readiness(api, novice["id"])
        assert readiness["held_sessions"] == 1, (
            f"one session has reached HELD, got {readiness['held_sessions']}"
        )
        assert readiness["excused_sessions"] == 0, (
            f"nobody was excused, got {readiness['excused_sessions']}"
        )
        assert readiness["seminar_denominator"] == 1, (
            f"one held session less no excusals is one, got {readiness['seminar_denominator']}"
        )
        assert_two_decimals(readiness["seminar_component"], 1.00, "seminar_component")

    def test_session_cancel_zeroes_credit_only_for_its_own_session(
        self, api: InductionApiClient
    ):
        """Cancelling Thursday's seminar leaves Wednesday's credit exactly where it was.

        The PRD scopes the recomputation to the cancelled session: "Because credited
        attendance only ever counts against a session that was actually held,
        cancellation recomputes that session's `credited_attendance_count` to zero
        and recomputes `credited_seminar_sessions` and `readiness_index_live` for
        every novice with an attendance row on it."

        Design: Corner/state_machines/session_cancel_zeroes_credit_only_for_its_own_session
        """
        site = create_site(api)
        cohort = create_cohort(api, seminar_sessions_required=2)
        lead = make_site_lead_headers(site["id"])
        novice = create_novice(api, site["id"], cohort["id"])
        first = schedule_seminar_session(
            api,
            cohort["id"],
            1,
            "2026-08-05T09:00:00Z",
            "2026-08-05T10:30:00Z",
            topic="Classroom routines",
        )
        second = schedule_seminar_session(
            api,
            cohort["id"],
            2,
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:30:00Z",
            topic="Formative assessment",
        )
        record_attendance(api, first["id"], novice["id"], "PRESENT", 90, lead)
        record_attendance(api, second["id"], novice["id"], "PRESENT", 90, lead)
        set_clock(api, "2026-08-05T11:00:00Z")
        hold_session(api, first["id"])

        cancelled = validate_success(
            api.set_session_status(
                second["id"],
                f.session_status_payload("CANCELLED", cancel_reason="Facilitator unavailable"),
                ADMIN,
            )
        )
        assert cancelled["status"] == "CANCELLED", (
            f"the second session is cancelled, got {cancelled['status']}"
        )
        assert_instant_equals(cancelled["cancelled_at"], "2026-08-05T11:00:00Z", "cancelled_at")
        assert cancelled["cancel_reason"] == "Facilitator unavailable", (
            f"the reason is stored, got {cancelled['cancel_reason']}"
        )
        assert cancelled["credited_attendance_count"] == 0, (
            f"a cancelled session credits nobody, got {cancelled['credited_attendance_count']}"
        )

        survivor = read_session(api, first["id"])
        assert survivor["status"] == "HELD", (
            f"the sibling session is untouched, got {survivor['status']}"
        )
        assert survivor["credited_attendance_count"] == 1, (
            f"and keeps its credited row, got {survivor['credited_attendance_count']}"
        )

        _, meta = validate_paginated(
            api.list_attendances(ADMIN, {"session_id": first["id"], "credited": "true"})
        )
        assert meta["total_count"] == 1, (
            f"exactly one credited row survives on the held session, got {meta['total_count']}"
        )

        assert read_novice(api, novice["id"])["credited_seminar_sessions"] == 1, (
            "only the held session's credit counts for the novice"
        )
        readiness = read_readiness(api, novice["id"])
        assert readiness["held_sessions"] == 1
        assert readiness["seminar_denominator"] == 1, (
            "the cancelled session never entered the denominator, got "
            f"{readiness['seminar_denominator']}"
        )
        assert_two_decimals(readiness["seminar_component"], 1.00, "seminar_component")
        assert_two_decimals(
            readiness["readiness_index_live"], 25.00, "readiness_index_live"
        )


class TestContactLogTerminalGuards:
    """Voiding reaches only a VERIFIED log."""

    def test_void_from_submitted_contact_log_rejected(self, api: InductionApiClient):
        """A void aimed at a SUBMITTED log is refused before any ledger arithmetic runs.

        The PRD fixes which status each contact-log operation needs: "The
        `ContactLog` is in the `verification_status` the operation needs —
        `SUBMITTED` for review, `DISPUTED` for resubmission, `VERIFIED` for voiding
        — otherwise `ERR_CONTACT_LOG_STATE_INVALID` (HTTP 409)."

        Design: Corner/state_machines/void_from_submitted_contact_log_rejected
        """
        program = build_program(api)
        set_clock(api, "2026-08-04T12:00:00Z")
        log = submit_contact_log(
            api,
            program["match_id"],
            "2026-08-02T09:00:00Z",
            minutes=60,
            contact_type="ONE_ON_ONE",
            mentor_id=program["mentor_id"],
            description="Planning conference on proportional reasoning",
        )

        response = api.void_contact_log(
            log["id"],
            f.void_payload(void_reason="Duplicate entry reported by the site lead"),
            ADMIN,
        )
        validate_error(response, ERR_CONTACT_LOG_STATE_INVALID, 409)

        stored = read_contact_log(api, log["id"])
        assert stored["verification_status"] == "SUBMITTED", (
            f"the refused void changes nothing, got {stored['verification_status']}"
        )
        assert stored["void_reason"] is None, (
            f"no void reason is recorded, got {stored['void_reason']}"
        )
        assert stored["credited_minutes"] == 0, "an unverified log credits nothing"
        assert stored["stipend_cents"] == 0, "an unverified log accrues nothing"

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["verified_minutes_lifetime"] == 0, (
            "nothing was credited, so nothing could be reversed"
        )
        # The provisional accrual counts logs whose verification_status is
        # SUBMITTED or VERIFIED, pricing a merely-SUBMITTED log from its
        # projected minutes, so the refused void leaves the 60-minute EXACT
        # log's provisional 4200 cents exactly where submission put it.
        assert mentor["stipend_accrued_cents"] == 4200, (
            "the refused void leaves the provisional accrual of the still-SUBMITTED "
            f"log untouched, got {mentor['stipend_accrued_cents']}"
        )


class TestMentorMatchInitialState:
    """What a proposal writes and what it deliberately leaves empty."""

    def test_mentor_match_created_starts_in_proposed(self, api: InductionApiClient):
        """Creation lands on PROPOSED with the rate unpinned and the novice MATCHED.

        The PRD warns about exactly this: "A newly created match sits in
        `match_status` `PROPOSED` with `verified_minutes_total` and
        `accrued_stipend_cents` at zero, `activated_at`, `suspended_at`, `ended_at`
        and `end_reason` all null, and — this catches people out —
        `pinned_stipend_rate_cents_per_hour` still null. The rate is not pinned at
        proposal; it is pinned only when the match is activated. Creation increments
        `Mentor.version` and, through the bubble-up described in §3.1, moves the
        novice from `ENROLLED` to `MATCHED`."

        Design: Corner/state_machines/mentor_match_created_starts_in_proposed
        """
        site = create_site(api)
        cohort = create_cohort(api)
        mentor = create_certified_mentor(api, site["id"])
        novice = create_novice(api, site["id"], cohort["id"])

        match = validate_success(
            api.create_match(
                f.match_payload(novice["id"], mentor["version"], mentor["id"]), ADMIN
            ),
            201,
        )
        assert match["match_status"] == "PROPOSED", (
            f"a new match opens PROPOSED, got {match['match_status']}"
        )
        assert match["selection_mode"] == "EXPLICIT", (
            f"naming the mentor makes the choice explicit, got {match['selection_mode']}"
        )
        assert match["subject_match_tier"] == "EXACT", (
            f"a MATH mentor on a MATH novice is an exact tier, got "
            f"{match['subject_match_tier']}"
        )
        assert match["site_match"] is True, (
            f"both parties sit at the same site, got {match['site_match']}"
        )
        assert match["pinned_stipend_rate_cents_per_hour"] is None, (
            "the rate is pinned only at activation, got "
            f"{match['pinned_stipend_rate_cents_per_hour']}"
        )
        assert match["activated_at"] is None, (
            f"no activation instant yet, got {match['activated_at']}"
        )
        assert match["verified_minutes_total"] == 0
        assert match["accrued_stipend_cents"] == 0
        assert match["version"] == 1, f"a fresh row starts at version 1, got {match['version']}"

        stored_novice = read_novice(api, novice["id"])
        assert stored_novice["program_status"] == "MATCHED", (
            f"the bubble-up moves the novice to MATCHED, got {stored_novice['program_status']}"
        )
        assert stored_novice["license_advancement_status"] == "NOT_ELIGIBLE", (
            "matching is not evidence, so the licence dimension is unmoved"
        )
        assert read_mentor(api, mentor["id"])["active_caseload_count"] == 0, (
            "a proposal occupies no caseload slot"
        )


class TestObservationCycleTerminalLockdown:
    """DOCUMENTED accepts no further advance, not even to ABANDONED."""

    def test_documented_cycle_refuses_further_advance(self, api: InductionApiClient):
        """The universal abandon escape hatch is closed once a cycle is documented.

        The PRD enumerates the legal advances exhaustively: "The observation
        cycle's `phase` permits the requested advance — `PRE_CONFERENCE` to
        `OBSERVED`, `OBSERVED` to `POST_CONFERENCE`, `POST_CONFERENCE` to
        `DOCUMENTED`, or any non-terminal phase to `ABANDONED` — otherwise
        `ERR_OBSERVATION_PHASE_INVALID` (HTTP 409)."

        Design: Corner/state_machines/documented_cycle_refuses_further_advance
        """
        program = build_program(api)
        set_clock(api, "2026-08-04T12:00:00Z")
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-03T14:00:00Z",
            "2026-08-03T15:00:00Z",
        )
        document_observation_cycle(
            api, cycle["id"], program["mentor_id"], program["site_id"]
        )

        response = api.advance_cycle(
            cycle["id"],
            f.advance_payload("ABANDONED", reason="Mentor asked to reopen the cycle"),
            make_mentor_headers(program["mentor_id"]),
        )
        validate_error(response, ERR_OBSERVATION_PHASE_INVALID, 409)

        stored = read_cycle(api, cycle["id"])
        assert stored["phase"] == "DOCUMENTED", (
            f"the terminal phase stands, got {stored['phase']}"
        )
        assert stored["abandoned_at"] is None, (
            f"no abandonment instant is stamped, got {stored['abandoned_at']}"
        )
        assert_instant_equals(stored["documented_at"], "2026-08-04T12:00:00Z", "documented_at")
        assert stored["feedback_review_status"] == "ACCEPTED", (
            f"the accepted review stands, got {stored['feedback_review_status']}"
        )
        assert_two_decimals(stored["composite_rubric_score"], 3.00, "composite_rubric_score")

        novice = read_novice(api, program["novice_id"])
        assert novice["documented_observation_cycles"] == 1, (
            "the refused advance neither double-counts nor rolls back, got "
            f"{novice['documented_observation_cycles']}"
        )
        assert_two_decimals(novice["readiness_index_live"], 15.00, "readiness_index_live")


class TestCohortClosureIdempotency:
    """A second close is a refusal, not a silent success."""

    def test_second_cohort_close_rejected(self, api: InductionApiClient):
        """The first closure's instant and version both survive the second attempt.

        The PRD makes CLOSED terminal and re-entry an error: "A `CLOSED` cohort is
        terminal, and it is also the gate for the very last step of the whole
        program: a completion packet cannot be sent to the state until the novice's
        cohort has closed."

        Design: Corner/state_machines/second_cohort_close_rejected
        """
        cohort = create_cohort(api)
        closed = validate_success(
            api.close_cohort(cohort["id"], f.close_cohort_payload("CLOSED"), ADMIN)
        )
        assert closed["status"] == "CLOSED"
        first_version = closed["version"]

        response = api.close_cohort(cohort["id"], f.close_cohort_payload("CLOSED"), ADMIN)
        validate_error(response, ERR_COHORT_STATE_INVALID, 422)

        stored = read_cohort(api, cohort["id"])
        assert stored["status"] == "CLOSED", (
            f"the cohort stays closed, got {stored['status']}"
        )
        assert_instant_equals(stored["closed_at"], CLOCK_INITIAL_UTC, "closed_at")
        assert stored["version"] == first_version, (
            f"a refused call mutates nothing, so the version holds at {first_version}, "
            f"got {stored['version']}"
        )


class TestClockDrivenLapseSweep:
    """Moving the clock is the one transition no business endpoint drives."""

    def test_clock_lapse_sweep_lapses_certification_and_suspends_match(
        self, api: InductionApiClient
    ):
        """A year and a day on, the mentor lapses and the live match is suspended.

        The PRD gives the sweep its own cascade shape: "A mentor leaving
        `CERTIFIED` carries a cascade: every match of that mentor in `match_status`
        `ACTIVE` transitions `ACTIVE → SUSPENDED`, processed in `created_at`
        ascending order, and the mentor's `version` increments."

        Design: Corner/state_machines/clock_lapse_sweep_lapses_certification_and_suspends_match
        """
        program = build_program(api)

        echoed = validate_success(api.set_clock("2027-08-02T00:00:00Z", ADMIN))
        assert_instant_equals(echoed["current_utc"], "2027-08-02T00:00:00Z", "current_utc")

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["certification_status"] == "LAPSED", (
            f"the sweep lapses an expired certification, got {mentor['certification_status']}"
        )
        assert mentor["suspension_reason"] is None, (
            f"a lapse is not a suspension, got {mentor['suspension_reason']}"
        )
        assert_instant_equals(
            mentor["certification_expires_on"],
            "2027-08-01T00:00:00Z",
            "certification_expires_on",
        )
        assert mentor["active_caseload_count"] == 0, (
            f"a suspended match releases the caseload slot, got "
            f"{mentor['active_caseload_count']}"
        )

        match = read_match(api, program["match_id"])
        assert match["match_status"] == "SUSPENDED", (
            f"the cascade suspends the live match, got {match['match_status']}"
        )
        assert_instant_equals(match["suspended_at"], "2027-08-02T00:00:00Z", "suspended_at")

        assert read_site(api, program["site_id"])["active_match_count"] == 0, (
            "the site slot is released with the match"
        )
        assert read_novice(api, program["novice_id"])["program_status"] == "ACTIVE", (
            "the cascade stops at the match and does not touch the novice"
        )


class TestAttainmentUnlockCascade:
    """Attaining a prerequisite unlocks exactly the rows that name it."""

    def test_prerequisite_attainment_unlocks_locked_dependent_row(
        self, api: InductionApiClient
    ):
        """The dependent LOCKED row becomes IN_PROGRESS in the very same request.

        The PRD makes the unlock part of the attestation itself: "And it unlocks
        every `LOCKED` attainment row of the same novice whose milestone names this
        one as prerequisite, processed in `sequence_index` ascending order."

        Design: Corner/state_machines/prerequisite_attainment_unlocks_locked_dependent_row
        """
        site = create_site(api)
        cohort = create_cohort(api)
        first = define_milestone(api, "IND_M1", 1, title="Orientation complete")
        second = define_milestone(
            api,
            "IND_M2",
            2,
            title="Mid-year review complete",
            prerequisite_milestone_id=first["id"],
        )
        novice = create_novice(api, site["id"], cohort["id"])
        root_row = attainment_for(api, novice["id"], first["id"])
        dependent_row = attainment_for(api, novice["id"], second["id"])
        assert root_row["status"] == "IN_PROGRESS", (
            f"a milestone with no prerequisite seeds open, got {root_row['status']}"
        )
        assert dependent_row["status"] == "LOCKED", (
            f"a milestone with a prerequisite seeds locked, got {dependent_row['status']}"
        )

        attained = attest_attainment(
            api,
            root_row["id"],
            evidence_note="Orientation roster and signed acknowledgement on file",
        )
        assert attained["status"] == "ATTAINED", (
            f"the root row is attested, got {attained['status']}"
        )
        assert_instant_equals(attained["attained_on"], CLOCK_INITIAL_UTC, "attained_on")
        assert attained["attested_by_user_id"] == PROGRAM_OFFICE_1, (
            f"the caller is recorded as attester, got {attained['attested_by_user_id']}"
        )
        assert attained["snapshot_contact_minutes"] == 0, (
            "the frozen evidence copies today's zero counters, got "
            f"{attained['snapshot_contact_minutes']}"
        )
        assert attained["snapshot_observation_cycles"] == 0
        assert attained["snapshot_credited_seminars"] == 0
        assert attained["snapshot_held_sessions"] == 0
        assert attained["snapshot_excused_sessions"] == 0

        assert read_attainment(api, dependent_row["id"])["status"] == "IN_PROGRESS", (
            "the dependent row unlocks off the back of its prerequisite"
        )

        stored_novice = read_novice(api, novice["id"])
        assert stored_novice["attained_milestone_count"] == 1, (
            f"one milestone stands attained, got {stored_novice['attained_milestone_count']}"
        )
        assert_two_decimals(
            stored_novice["readiness_index_snapshot"], 0.00, "readiness_index_snapshot"
        )
        assert stored_novice["license_advancement_status"] == "NOT_ELIGIBLE", (
            "this milestone gates nothing, got "
            f"{stored_novice['license_advancement_status']}"
        )
        assert stored_novice["license_stage"] == "PRELIMINARY", (
            f"and grants no stage, got {stored_novice['license_stage']}"
        )


class TestNoviceWithdrawalCascade:
    """One withdrawal reaches the match, the open cycle and both slot counters."""

    def test_novice_withdraw_ends_match_and_abandons_open_cycle(
        self, api: InductionApiClient
    ):
        """The match ends as NOVICE_WITHDRAWN and the pre-conference cycle is abandoned.

        The PRD walks the whole footprint: "Every match of that novice sitting in
        `PROPOSED` becomes `REJECTED` with an `end_reason` of `NOVICE_WITHDRAWN`;
        every match in `ACTIVE` or `SUSPENDED` becomes `ENDED` with the same
        `end_reason`; matches are processed in `created_at` ascending order, and
        each match that was `ACTIVE` releases its slot by decrementing both the
        mentor's `active_caseload_count` and the site's `active_match_count`. Every
        observation cycle on those matches whose `phase` is `PRE_CONFERENCE`,
        `OBSERVED` or `POST_CONFERENCE` becomes `ABANDONED`."

        Design: Corner/state_machines/novice_withdraw_ends_match_and_abandons_open_cycle
        """
        program = build_program(api)
        set_clock(api, "2026-08-04T12:00:00Z")
        cycle = open_observation_cycle(
            api,
            program["match_id"],
            program["mentor_id"],
            1,
            "2026-08-06T14:00:00Z",
            "2026-08-06T15:00:00Z",
        )

        withdrawn = validate_success(
            api.withdraw_novice(
                program["novice_id"],
                f.withdraw_novice_payload(reason="Family relocation out of district"),
                ADMIN,
            )
        )
        assert withdrawn["program_status"] == "WITHDRAWN", (
            f"the novice leaves the program, got {withdrawn['program_status']}"
        )
        assert withdrawn["withdrawn_reason"] == "Family relocation out of district", (
            f"the supplied reason is stored, got {withdrawn['withdrawn_reason']}"
        )

        match = read_match(api, program["match_id"])
        assert match["match_status"] == "ENDED", (
            f"an active match is ended by the withdrawal, got {match['match_status']}"
        )
        assert match["end_reason"] == "NOVICE_WITHDRAWN", (
            f"with the system-supplied reason, got {match['end_reason']}"
        )
        assert_instant_equals(match["ended_at"], "2026-08-04T12:00:00Z", "ended_at")

        stored_cycle = read_cycle(api, cycle["id"])
        assert stored_cycle["phase"] == "ABANDONED", (
            f"the open cycle is abandoned, got {stored_cycle['phase']}"
        )
        assert_instant_equals(
            stored_cycle["abandoned_at"], "2026-08-04T12:00:00Z", "abandoned_at"
        )

        mentor = read_mentor(api, program["mentor_id"])
        assert mentor["active_caseload_count"] == 0, (
            f"the mentor's slot is released, got {mentor['active_caseload_count']}"
        )
        assert mentor["certification_status"] == "CERTIFIED", (
            f"and nothing else about the mentor moves, got {mentor['certification_status']}"
        )
        assert read_site(api, program["site_id"])["active_match_count"] == 0, (
            "the site's slot is released too"
        )
