"""Refusal codes on the later rungs: interval well-formedness, the acyclicity rule,
the attainment and feedback bounds, and the packet, fiscal and seminar state gates.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_client import InductionApiClient
from test_helpers.api_errors import (
    ERR_ACTIVE_PACKET_EXISTS,
    ERR_ADJUSTMENT_EXCEEDS_GROSS,
    ERR_ATTAINMENT_STATE_INVALID,
    ERR_DISBURSEMENT_STATE_INVALID,
    ERR_DUPLICATE_DISBURSEMENT_PERIOD,
    ERR_FEEDBACK_INCOMPLETE,
    ERR_FEEDBACK_RETURN_LIMIT_REACHED,
    ERR_FEEDBACK_STATE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_MILESTONE_CYCLE,
    ERR_MILESTONE_REQUIREMENTS_NOT_MET,
    ERR_NON_POSITIVE_NET_STIPEND,
    ERR_NOVICE_PROGRAM_STATE_INVALID,
    ERR_NO_ELIGIBLE_ACTIVITY,
    ERR_PACKET_STATE_INVALID,
    ERR_REVOCATION_LIMIT_REACHED,
    ERR_SESSION_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_ascending_by,
    assert_four_decimals,
    assert_instant_equals,
    assert_money_cents,
    assert_two_decimals,
    ids_of,
)
from test_helpers.fixtures import (
    attainment_decision_request,
    attainment_for,
    attest_attainment,
    build_program,
    create_novice,
    define_milestone,
    read_attainment,
    read_cycle,
    read_mentor,
    read_novice,
    read_packet,
    read_session,
    revoke_attainment,
    set_clock,
    submit_and_verify_contact_log,
)
from test_helpers.test_users import (
    ADMIN,
    ADMIN_2,
    STATE_OFFICER,
    make_mentor_headers,
    make_site_lead_headers,
)


class TestIntervalWellFormedness:
    """One code covers the duration floor, the duration ceiling and inversion."""

    def test_invalid_window_bounds_rejected(self, api: InductionApiClient):
        """Short, inverted observation and seminar intervals and an inverted period.

        The PRD states all four shapes in one rule: "An observation window's
        `window_end` must be strictly after its `window_start`, and a seminar
        session's `scheduled_end` must be strictly after its `scheduled_start`. For
        both of those, the duration must be at least 30 minutes and at most 240
        minutes, inclusive at both ends. A stipend period is looser: `period_end`
        need only be strictly after `period_start`, with no duration bound at all.
        Violations of any of these produce `ERR_INVALID_WINDOW` (HTTP 422)."

        Design: Corner/errors/invalid_window_bounds_rejected
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        mentor_version = read_mentor(api, program["mentor_id"])["version"]

        too_short = api.create_observation_cycle(
            f.observation_cycle_payload(
                program["match_id"], 1, "2026-08-10T09:00:00Z", "2026-08-10T09:20:00Z"
            ),
            mentor_headers,
        )
        validate_error(too_short, ERR_INVALID_WINDOW, 422)

        short_seminar = api.create_seminar_session(
            f.seminar_session_payload(
                program["cohort_id"],
                1,
                "2026-08-12T15:00:00Z",
                "2026-08-12T15:25:00Z",
                topic="Truncated institute block",
            ),
            ADMIN,
        )
        validate_error(short_seminar, ERR_INVALID_WINDOW, 422)

        inverted_window = api.create_observation_cycle(
            f.observation_cycle_payload(
                program["match_id"], 2, "2026-08-11T10:00:00Z", "2026-08-11T09:00:00Z"
            ),
            mentor_headers,
        )
        validate_error(inverted_window, ERR_INVALID_WINDOW, 422)

        inverted_period = api.create_disbursement(
            f.disbursement_payload(
                program["mentor_id"],
                mentor_version,
                period_code="2026-Q3",
                period_start="2026-08-10T00:00:00Z",
                period_end="2026-08-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(inverted_period, ERR_INVALID_WINDOW, 422)

        exactly_thirty = validate_success(
            api.create_observation_cycle(
                f.observation_cycle_payload(
                    program["match_id"], 3, "2026-08-13T09:00:00Z", "2026-08-13T09:30:00Z"
                ),
                mentor_headers,
            ),
            201,
        )
        assert exactly_thirty["phase"] == "PRE_CONFERENCE", (
            "thirty minutes is inside the inclusive floor, got phase "
            f"{exactly_thirty['phase']}"
        )
        assert exactly_thirty["cycle_index"] == 3

        rows, meta = validate_paginated(
            api.list_observation_cycles(ADMIN, {"match_id": program["match_id"]})
        )
        assert meta["total_count"] == 1, (
            f"only the well-formed cycle exists, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [exactly_thirty["id"]]
        _, session_meta = validate_paginated(
            api.list_seminar_sessions(ADMIN, {"cohort_id": program["cohort_id"]})
        )
        assert session_meta["total_count"] == 0, (
            f"the refused session was never stored, got {session_meta['total_count']}"
        )
        _, fiscal_meta = validate_paginated(
            api.list_disbursements(ADMIN, {"mentor_id": program["mentor_id"]})
        )
        assert fiscal_meta["total_count"] == 0, (
            f"and neither was the refused draft, got {fiscal_meta['total_count']}"
        )


class TestMilestoneAcyclicity:
    """Acyclicity is enforced by the ordering index, not by a graph walk."""

    def test_milestone_prerequisite_cycle_rejected(self, api: InductionApiClient):
        """A later prerequisite is refused; the same request pointing earlier is accepted.

        The PRD leans on the index rather than a traversal: "The prerequisite chain
        is kept acyclic at insertion by a rule that leans on the ordering index
        rather than a graph walk: a new milestone's prerequisite must have a
        `sequence_index` strictly less than the new milestone's own. A prerequisite
        whose index is greater than or equal to the new one's is refused with
        `ERR_MILESTONE_CYCLE`."

        Design: Corner/errors/milestone_prerequisite_cycle_rejected
        """
        second = define_milestone(
            api, "IND_M2", 2, title="Entry conference complete", gates_license_recommendation=False
        )
        fifth = define_milestone(
            api, "IND_M5", 5, title="Portfolio submitted", gates_license_recommendation=False
        )

        forward_edge = api.create_milestone(
            f.milestone_payload(
                "IND_M3",
                3,
                title="Mid-year review complete",
                gates_license_recommendation=False,
                prerequisite_milestone_id=fifth["id"],
            ),
            ADMIN,
        )
        validate_error(forward_edge, ERR_MILESTONE_CYCLE, 422)

        third = validate_success(
            api.create_milestone(
                f.milestone_payload(
                    "IND_M3",
                    3,
                    title="Mid-year review complete",
                    gates_license_recommendation=False,
                    prerequisite_milestone_id=second["id"],
                ),
                ADMIN,
            ),
            201,
        )
        assert third["prerequisite_milestone_id"] == second["id"], (
            "an edge to a strictly smaller index is accepted, got "
            f"{third['prerequisite_milestone_id']}"
        )
        assert third["sequence_index"] == 3

        rows, meta = validate_paginated(api.list_milestones(ADMIN))
        assert meta["total_count"] == 3, (
            f"three definitions exist, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [second["id"], third["id"], fifth["id"]], (
            f"ordered by sequence_index ascending, got {ids_of(rows)}"
        )
        assert_ascending_by(rows, "sequence_index")

        _, orphan_meta = validate_paginated(
            api.list_milestones(ADMIN, {"prerequisite_milestone_id": fifth["id"]})
        )
        assert orphan_meta["total_count"] == 0, (
            f"the refused definition left no row, got {orphan_meta['total_count']}"
        )


class TestAttainmentDecisionBounds:
    """The state gate, the evidence gate and the cycle bound are three codes."""

    def test_attainment_decision_state_requirement_and_revocation_limit_errors(
        self, api: InductionApiClient
    ):
        """A revoke from IN_PROGRESS, an attestation short of evidence, a fourth revoke.

        The PRD bounds the revocation loop explicitly: "A row may be revoked at most
        three times: a fourth attempt, made when `revocation_count` already stands at
        3, is refused with `ERR_REVOCATION_LIMIT_REACHED`."

        Design: Corner/errors/attainment_decision_state_requirement_and_revocation_limit_errors
        """
        program = build_program(api)
        free = define_milestone(
            api, "IND_Z", 1, title="Orientation complete", gates_license_recommendation=False
        )
        gated = define_milestone(
            api,
            "IND_HRS",
            2,
            title="Foundational contact hours",
            required_contact_minutes=300,
            gates_license_recommendation=False,
        )
        free_row = attainment_for(api, program["novice_id"], free["id"])
        gated_row = attainment_for(api, program["novice_id"], gated["id"])

        for _ in range(3):
            attest_attainment(api, free_row["id"], evidence_note="Orientation roster reviewed")
            revoke_attainment(
                api,
                free_row["id"],
                revoke_reason="Roster signature could not be authenticated",
            )
            validate_success(attainment_decision_request(api, free_row["id"], "REOPEN", ADMIN))
        attest_attainment(
            api, free_row["id"], evidence_note="Roster re-signed by the site principal"
        )

        wrong_state = attainment_decision_request(
            api,
            gated_row["id"],
            "REVOKE",
            ADMIN,
            revoke_reason="Filed against the wrong milestone",
        )
        validate_error(wrong_state, ERR_ATTAINMENT_STATE_INVALID, 409)

        short_of_evidence = attainment_decision_request(
            api,
            gated_row["id"],
            "ATTEST",
            ADMIN,
            evidence_note="Contact hour ledger attached",
        )
        validate_error(short_of_evidence, ERR_MILESTONE_REQUIREMENTS_NOT_MET, 422)

        fourth_revocation = attainment_decision_request(
            api,
            free_row["id"],
            "REVOKE",
            ADMIN,
            revoke_reason="Fourth revocation attempt by the program office",
        )
        validate_error(fourth_revocation, ERR_REVOCATION_LIMIT_REACHED, 409)

        gated_after = read_attainment(api, gated_row["id"])
        assert gated_after["status"] == "IN_PROGRESS", (
            f"neither refusal moved the gated row, got {gated_after['status']}"
        )
        assert gated_after["revocation_count"] == 0
        assert gated_after["attained_on"] is None

        free_after = read_attainment(api, free_row["id"])
        assert free_after["status"] == "ATTAINED", (
            f"the free row stays attained, got {free_after['status']}"
        )
        assert free_after["revocation_count"] == 3, (
            f"the counter is at its bound, got {free_after['revocation_count']}"
        )

        novice = read_novice(api, program["novice_id"])
        assert novice["attained_milestone_count"] == 1
        assert novice["verified_contact_minutes"] == 0
        assert novice["license_advancement_status"] == "NOT_ELIGIBLE"


class TestFeedbackBounds:
    """Completeness, the return bound and the state gate are three independent codes."""

    def test_feedback_completeness_state_and_return_limit_errors(
        self, api: InductionApiClient
    ):
        """A short narrative, a fourth return and a submission after acceptance.

        The PRD bounds the revision loop and makes acceptance terminal: "A fourth
        return — attempted when `return_count` already stands at 3 — is refused with
        `ERR_FEEDBACK_RETURN_LIMIT_REACHED`; by then the feedback must either be
        accepted or the cycle abandoned."

        Design: Corner/errors/feedback_completeness_state_and_return_limit_errors
        """
        program = build_program(api)
        mentor_headers = make_mentor_headers(program["mentor_id"])
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-15T12:00:00Z")
        cycle = validate_success(
            api.create_observation_cycle(
                f.observation_cycle_payload(
                    program["match_id"], 1, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z"
                ),
                mentor_headers,
            ),
            201,
        )
        validate_success(
            api.advance_cycle(cycle["id"], f.advance_payload("OBSERVED"), mentor_headers)
        )
        validate_success(
            api.advance_cycle(
                cycle["id"], f.advance_payload("POST_CONFERENCE"), mentor_headers
            )
        )
        for _ in range(3):
            validate_success(
                api.write_feedback(cycle["id"], f.feedback_payload(submit=True), mentor_headers)
            )
            validate_success(
                api.review_feedback(cycle["id"], f.feedback_review_payload("RETURN"), lead)
            )

        incomplete = api.write_feedback(
            cycle["id"],
            f.feedback_payload(
                submit=True,
                narrative="Lesson went well overall today.",
                growth_area_codes=["PLANNING"],
            ),
            mentor_headers,
        )
        validate_error_is_one_of(incomplete, [ERR_INVALID_REQUEST, ERR_FEEDBACK_INCOMPLETE])

        resubmitted = validate_success(
            api.write_feedback(
                cycle["id"],
                f.feedback_payload(
                    submit=True,
                    rubric_scores={
                        "planning": 4,
                        "instruction": 3,
                        "environment": 3,
                        "assessment": 2,
                    },
                ),
                mentor_headers,
            )
        )
        assert resubmitted["feedback_review_status"] == "SUBMITTED"
        assert_two_decimals(
            resubmitted["composite_rubric_score"], 3.00, "composite_rubric_score"
        )

        fourth_return = api.review_feedback(
            cycle["id"],
            f.feedback_review_payload(
                "RETURN", return_reason="Fourth return attempt by the site lead"
            ),
            lead,
        )
        validate_error(fourth_return, ERR_FEEDBACK_RETURN_LIMIT_REACHED, 409)

        accepted = validate_success(
            api.review_feedback(cycle["id"], f.feedback_review_payload("ACCEPT"), lead)
        )
        assert accepted["feedback_review_status"] == "ACCEPTED"
        assert accepted["return_reason"] is None, (
            f"acceptance clears the return reason, got {accepted['return_reason']}"
        )
        assert accepted["return_count"] == 3, (
            f"the return counter stays at its bound, got {accepted['return_count']}"
        )

        after_acceptance = api.write_feedback(
            cycle["id"],
            f.feedback_payload(
                submit=True,
                growth_area_codes=["PLANNING"],
                rubric_scores={
                    "planning": 1,
                    "instruction": 1,
                    "environment": 1,
                    "assessment": 1,
                },
            ),
            mentor_headers,
        )
        validate_error(after_acceptance, ERR_FEEDBACK_STATE_INVALID, 409)

        stored = read_cycle(api, cycle["id"])
        assert_two_decimals(stored["composite_rubric_score"], 3.00, "composite_rubric_score")
        assert stored["phase"] == "POST_CONFERENCE", (
            f"the phase dimension never moved, got {stored['phase']}"
        )


class TestPacketCreationAndStateGates:
    """The program-state refusal and the active-packet refusal stay distinguishable."""

    def test_packet_creation_program_state_active_packet_and_packet_state_errors(
        self, api: InductionApiClient
    ):
        """An ENROLLED novice, a novice mid-packet and a premature state decision.

        The ladder admits the mid-packet state on purpose so the two refusals do not
        collapse: "Packet creation admits `COMPLETION_PENDING` on purpose, so that a
        novice already mid-packet is refused by rule 41 below and the two refusals
        stay distinguishable."

        Design: Corner/errors/packet_creation_program_state_active_packet_and_packet_state_errors
        """
        program = build_program(api)
        never_matched = create_novice(
            api, program["site_id"], program["cohort_id"], full_name="Ira Vance"
        )

        wrong_program_state = api.create_packet(
            f.packet_payload(never_matched["id"], never_matched["version"]), ADMIN
        )
        validate_error(wrong_program_state, ERR_NOVICE_PROGRAM_STATE_INVALID, 409)

        packet = validate_success(
            api.create_packet(
                f.packet_payload(
                    program["novice_id"], read_novice(api, program["novice_id"])["version"]
                ),
                ADMIN,
            ),
            201,
        )
        assert packet["packet_status"] == "ASSEMBLING"
        assert packet["resubmission_count"] == 0

        premature_decision = api.packet_state_decision(
            packet["id"], f.state_decision_payload("ACCEPT"), STATE_OFFICER
        )
        validate_error(premature_decision, ERR_PACKET_STATE_INVALID, 409)

        second_packet = api.create_packet(
            f.packet_payload(
                program["novice_id"], read_novice(api, program["novice_id"])["version"]
            ),
            ADMIN,
        )
        refusal = validate_error(second_packet, ERR_ACTIVE_PACKET_EXISTS, 409)
        assert refusal["error_id"] != ERR_NOVICE_PROGRAM_STATE_INVALID, (
            "the novice is COMPLETION_PENDING at this point, which packet creation "
            "admits, so the live packet is what refuses the call"
        )

        withdrawn = validate_success(
            api.packet_transition(
                packet["id"],
                f.packet_transition_payload(
                    "WITHDRAW", reason="Novice deferred completion to the spring window"
                ),
                ADMIN,
            )
        )
        assert withdrawn["packet_status"] == "WITHDRAWN"
        assert (
            withdrawn["withdrawn_reason"]
            == "Novice deferred completion to the spring window"
        ), f"the supplied reason is stored, got {withdrawn['withdrawn_reason']}"

        fresh = validate_success(
            api.create_packet(
                f.packet_payload(
                    program["novice_id"], read_novice(api, program["novice_id"])["version"]
                ),
                ADMIN,
            ),
            201,
        )
        assert fresh["packet_status"] == "ASSEMBLING"
        assert fresh["id"] != packet["id"], (
            "a withdrawn packet does not block a fresh one, and the fresh one is a new row"
        )
        assert read_packet(api, packet["id"])["packet_status"] == "WITHDRAWN"
        assert read_novice(api, program["novice_id"])["program_status"] == "COMPLETION_PENDING"


class TestFiscalRefusalFamily:
    """No activity, an excessive adjustment, a zero net, a state skip and a duplicate."""

    def test_stipend_draft_activity_adjustment_and_status_errors(
        self, api: InductionApiClient
    ):
        """Five fiscal refusals on one mentor holding exactly sixty verified minutes.

        The PRD orders the two adjustment checks so that the boundary case is
        unambiguous: "The resulting net must itself be strictly positive, or the
        draft is refused with `ERR_NON_POSITIVE_NET_STIPEND`; because that check is
        applied after the excess check, an adjustment exactly equal to the negated
        gross reports the non-positive net rather than the excess."

        Design: Corner/errors/stipend_draft_activity_adjustment_and_status_errors
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        set_clock(api, "2026-08-05T12:00:00Z")
        submit_and_verify_contact_log(
            api,
            program["match_id"],
            program["mentor_id"],
            "2026-08-03T09:00:00Z",
            minutes=60,
            contact_type="CO_PLANNING",
            verifier=lead,
            description="Co-planning the opening unit and the shared classroom norms",
        )
        set_clock(api, "2026-09-01T09:00:00Z")
        version = read_mentor(api, program["mentor_id"])["version"]

        empty_period = api.create_disbursement(
            f.disbursement_payload(
                program["mentor_id"],
                version,
                period_code="2026-Q2",
                period_start="2026-07-01T00:00:00Z",
                period_end="2026-07-31T23:59:59Z",
            ),
            ADMIN,
        )
        validate_error(empty_period, ERR_NO_ELIGIBLE_ACTIVITY, 422)

        def august(**extra):
            return f.disbursement_payload(
                program["mentor_id"],
                version,
                period_code="2026-Q3",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
                **extra,
            )

        excessive = api.create_disbursement(august(adjustment_cents=-5000), ADMIN)
        validate_error(excessive, ERR_ADJUSTMENT_EXCEEDS_GROSS, 422)

        exactly_negated = api.create_disbursement(august(adjustment_cents=-4200), ADMIN)
        zero_net = validate_error(exactly_negated, ERR_NON_POSITIVE_NET_STIPEND, 422)
        assert zero_net["error_id"] != ERR_ADJUSTMENT_EXCEEDS_GROSS, (
            "an adjustment exactly equal to the negated gross clears the excess check"
        )

        draft = validate_success(api.create_disbursement(august(), ADMIN), 201)
        assert draft["status"] == "DRAFT"
        assert draft["eligible_log_count"] == 1, (
            f"one verified log sits inside the window, got {draft['eligible_log_count']}"
        )
        assert_money_cents(draft["gross_cents"], 4200, "gross_cents")
        assert_money_cents(draft["adjustment_cents"], 0, "adjustment_cents")
        assert_money_cents(draft["net_cents"], 4200, "net_cents")

        skip_to_paid = api.set_disbursement_status(
            draft["id"], f.disbursement_status_payload("PAID"), ADMIN_2
        )
        validate_error(skip_to_paid, ERR_DISBURSEMENT_STATE_INVALID, 409)

        approved = validate_success(
            api.set_disbursement_status(
                draft["id"], f.disbursement_status_payload("APPROVED"), ADMIN_2
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["payment_reference"] is None, (
            f"approval does not pay, got {approved['payment_reference']}"
        )

        duplicate_period = api.create_disbursement(
            f.disbursement_payload(
                program["mentor_id"],
                read_mentor(api, program["mentor_id"])["version"],
                period_code="2026-Q3",
                period_start="2026-08-01T00:00:00Z",
                period_end="2026-09-01T00:00:00Z",
            ),
            ADMIN,
        )
        validate_error(duplicate_period, ERR_DUPLICATE_DISBURSEMENT_PERIOD, 409)

        mentor = read_mentor(api, program["mentor_id"])
        assert_money_cents(mentor["stipend_accrued_cents"], 4200, "stipend_accrued_cents")
        assert_money_cents(mentor["stipend_paid_cents"], 0, "stipend_paid_cents")

        rows, meta = validate_paginated(
            api.list_disbursements(ADMIN, {"mentor_id": program["mentor_id"]})
        )
        assert meta["total_count"] == 1, (
            f"none of the four refusals created a row, got {meta['total_count']}"
        )
        assert ids_of(rows) == [draft["id"]]


class TestSeminarSessionTerminalStates:
    """HELD and CANCELLED are both terminal, and one code guards four refusals."""

    def test_seminar_session_terminal_status_blocks_hold_cancel_and_attendance(
        self, api: InductionApiClient
    ):
        """Attendance and resolution are both refused once a session has been resolved.

        The PRD makes both resolutions terminal for all three operations: "Both
        `HELD` and `CANCELLED` are terminal; any further attempt to hold, cancel or
        attend the session is refused with `ERR_SESSION_STATE_INVALID`."

        Design: Corner/errors/seminar_session_terminal_status_blocks_hold_cancel_and_attendance
        """
        program = build_program(api)
        lead = make_site_lead_headers(program["site_id"])
        first = validate_success(
            api.create_seminar_session(
                f.seminar_session_payload(
                    program["cohort_id"],
                    1,
                    "2026-08-05T15:00:00Z",
                    "2026-08-05T16:00:00Z",
                    topic="Classroom routines",
                ),
                ADMIN,
            ),
            201,
        )
        second = validate_success(
            api.create_seminar_session(
                f.seminar_session_payload(
                    program["cohort_id"],
                    2,
                    "2026-08-06T15:00:00Z",
                    "2026-08-06T16:00:00Z",
                    topic="Formative assessment",
                ),
                ADMIN,
            ),
            201,
        )
        set_clock(api, "2026-08-07T12:00:00Z")

        cancelled = validate_success(
            api.set_session_status(
                first["id"],
                f.session_status_payload(
                    "CANCELLED", cancel_reason="Facilitator reassigned to state review"
                ),
                ADMIN,
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancel_reason"] == "Facilitator reassigned to state review"
        assert cancelled["credited_attendance_count"] == 0

        attend_cancelled = api.create_attendance(
            f.attendance_payload(first["id"], program["novice_id"], "PRESENT", 60), lead
        )
        validate_error(attend_cancelled, ERR_SESSION_STATE_INVALID, 409)

        hold_cancelled = api.set_session_status(
            first["id"], f.session_status_payload("HELD"), ADMIN
        )
        validate_error(hold_cancelled, ERR_SESSION_STATE_INVALID, 409)

        attendance = validate_success(
            api.create_attendance(
                f.attendance_payload(second["id"], program["novice_id"], "PRESENT", 60), lead
            ),
            201,
        )
        assert_four_decimals(attendance["credit_ratio"], 1.0000, "credit_ratio")
        assert attendance["credited"] is True

        held = validate_success(
            api.set_session_status(second["id"], f.session_status_payload("HELD"), ADMIN)
        )
        assert held["status"] == "HELD"
        assert_instant_equals(held["held_at"], "2026-08-07T12:00:00Z", "held_at")

        cancel_held = api.set_session_status(
            second["id"],
            f.session_status_payload(
                "CANCELLED", cancel_reason="Retroactive cancellation attempt"
            ),
            ADMIN,
        )
        validate_error(cancel_held, ERR_SESSION_STATE_INVALID, 409)

        attend_held = api.create_attendance(
            f.attendance_payload(second["id"], program["novice_id"], "LATE", 50), lead
        )
        state_refusal = validate_error(attend_held, ERR_SESSION_STATE_INVALID, 409)
        assert state_refusal["error_id"] != "ERR_DUPLICATE_ATTENDANCE", (
            "the session state is checked before the uniqueness of the attendance row"
        )

        assert validate_success(api.get_cohort(program["cohort_id"], ADMIN))[
            "status"
        ] == "RUNNING", "the successful hold dragged the cohort out of FORMING"
        assert read_novice(api, program["novice_id"])["credited_seminar_sessions"] == 1, (
            "only the held session counts"
        )
        assert read_session(api, first["id"])["credited_attendance_count"] == 0

        rows, meta = validate_paginated(
            api.list_attendances(ADMIN, {"session_id": second["id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused calls created no rows, got total_count {meta['total_count']}"
        )
        assert ids_of(rows) == [attendance["id"]]
