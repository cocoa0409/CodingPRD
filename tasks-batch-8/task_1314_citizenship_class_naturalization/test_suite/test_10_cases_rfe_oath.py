"""Case tracking, RFEs, and oath ceremonies (PRD §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_case,
    assert_oath_ceremony,
    assert_same_instant,
    assign_case_to_ceremony,
    complete_workshop,
    create_ceremony,
    create_general_volunteer,
    create_legal_volunteer,
    create_packet_in_review,
    create_program,
    create_screened_applicant,
    create_workshop,
    advance_case,
    advance_case_to,
    get_case,
    get_ceremony,
    get_packet,
    make_volunteer_headers,
    reserve_seat,
    set_clock,
    setup_certified_pipeline,
    setup_filed_case,
    setup_oath_ready_case,
    setup_two_oath_ready_cases,
    certify_packet,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["intake_coordinator_headers"]


class TestCaseStageMachine:
    def test_case_invalid_stage_jump_rejected(self, api):
        """PRD §3.9: "A `ProgramAdmin` advances the stage by naming a `to_stage`,
        which must be exactly the next stage in the linear order — anything else
        rejects with `ERR_INVALID_STAGE_JUMP`."

        Design: Corner/endpoints/case_invalid_stage_jump_rejected
        """
        pipeline = setup_filed_case()
        case = pipeline["case"]
        assert case["stage"] == "FILED"

        # FILED may only advance to RECEIPTED; skipping to BIOMETRICS_COMPLETE fails.
        response = api.advance_case(case["id"], {"to_stage": "BIOMETRICS_COMPLETE"},
                                    ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STAGE_JUMP)
        assert get_case(case["id"])["stage"] == "FILED"

    def test_case_second_active_rejected(self, api):
        """PRD §3.8: "Filing is blocked when another case already exists for this
        applicant in any stage other than `APPLICATION_DENIED`
        (`ERR_CASE_ALREADY_ACTIVE`)."

        Design: Corner/endpoints/case_second_active_rejected
        """
        pipeline = setup_filed_case()
        assert pipeline["case"]["stage"] == "FILED"

        # A second workshop, seat, and certified packet for the same applicant.
        workshop_2 = create_workshop(pipeline["supervisor"]["id"],
                                     scheduled_start="2026-08-06T10:00:00Z",
                                     duration_hours=2, title="WS2")
        seat_2 = reserve_seat(workshop_2["id"], pipeline["applicant"]["id"])
        complete_workshop(workshop_2["id"], pipeline["supervisor"]["id"],
                          at="2026-08-06T10:00:00Z")
        packet_2 = create_packet_in_review(
            {"applicant": pipeline["applicant"], "seat": seat_2,
             "preparer": pipeline["preparer"]},
        )
        certified_2 = certify_packet(packet_2["id"], pipeline["certifier"]["id"])
        assert certified_2["status"] == "CERTIFIED"

        response = api.file_packet(packet_2["id"], COORD)
        validate_error(response, ApiErrorId.ERR_CASE_ALREADY_ACTIVE)
        assert get_packet(packet_2["id"])["status"] == "CERTIFIED", (
            "a failed filing is not a transition"
        )


class TestParallelRfeDimension:
    def test_case_parallel_stage_and_rfe_dimensions(self, api):
        """PRD §3.9: "Every advancement additionally requires the RFE dimension to be
        clear — a `rfe_status` of anything other than `NONE` rejects with
        `ERR_RFE_OPEN`."
        PRD §3.9: "Responding — an `IntakeCoordinator` or `ProgramAdmin` action —
        moves `ISSUED` → `RESPONDED`, and a late response is explicitly permitted:
        `OVERDUE` → `RESPONDED` follows the same path (`ERR_INVALID_STATE` from any
        other status). Only a `ProgramAdmin` may then clear a `RESPONDED` request back
        to `NONE`, nulling both `rfe_issued_at` and `rfe_deadline`."

        Design: Difficulty/non_linear_state_machine/case_parallel_stage_and_rfe_dimensions
        """
        pipeline = setup_filed_case()
        case = advance_case_to(pipeline["case"]["id"], "BIOMETRICS_COMPLETE")

        issued = validate_success(api.issue_rfe(case["id"], ADMIN), 200)
        assert_case(issued)
        assert issued["rfe_status"] == "ISSUED"
        assert issued["rfe_issued_at"] is not None
        assert issued["rfe_deadline"] is not None

        # The sibling dimension gates advancement without itself changing.
        blocked = api.advance_case(case["id"], {"to_stage": "INTERVIEW_SCHEDULED"},
                                   ADMIN)
        validate_error(blocked, ApiErrorId.ERR_RFE_OPEN)
        after_block = get_case(case["id"])
        assert after_block["stage"] == "BIOMETRICS_COMPLETE"
        assert after_block["rfe_status"] == "ISSUED"

        responded = validate_success(api.respond_rfe(case["id"], COORD), 200)
        assert responded["rfe_status"] == "RESPONDED"
        assert responded["stage"] == "BIOMETRICS_COMPLETE", (
            "the RFE transition must not move the stage dimension"
        )

        # RESPONDED is still not NONE: advancement remains blocked.
        still_blocked = api.advance_case(case["id"],
                                         {"to_stage": "INTERVIEW_SCHEDULED"}, ADMIN)
        validate_error(still_blocked, ApiErrorId.ERR_RFE_OPEN)

        cleared = validate_success(api.clear_rfe(case["id"], ADMIN), 200)
        assert cleared["rfe_status"] == "NONE"
        assert cleared["rfe_issued_at"] is None
        assert cleared["rfe_deadline"] is None

        advanced = validate_success(
            api.advance_case(case["id"], {"to_stage": "INTERVIEW_SCHEDULED"}, ADMIN),
            200,
        )
        assert advanced["stage"] == "INTERVIEW_SCHEDULED"
        assert advanced["rfe_status"] == "NONE", (
            "stage advancement must not move the RFE dimension"
        )

    def test_case_issue_rfe_state_guards(self, api):
        """PRD §3.9: "A `ProgramAdmin` issues a Request for Evidence only while the
        case sits in `RECEIPTED`, `BIOMETRICS_COMPLETE`, or `INTERVIEW_SCHEDULED` and
        only from `rfe_status` `NONE` (`ERR_INVALID_STATE` otherwise); issuance stamps
        `rfe_issued_at` at the clock and sets `rfe_deadline` to the clock plus
        `rfe_deadline_days`."

        Design: Difficulty/non_linear_state_machine/case_parallel_stage_and_rfe_dimensions
        """
        pipeline = setup_filed_case()
        case = pipeline["case"]
        assert case["stage"] == "FILED"

        # FILED is not an issueable stage.
        response = api.issue_rfe(case["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)

        case = advance_case(case["id"], "RECEIPTED")
        issued = validate_success(api.issue_rfe(case["id"], ADMIN), 200)
        assert issued["rfe_status"] == "ISSUED"
        assert_same_instant(issued["rfe_issued_at"], "2026-08-05T10:00:00Z")
        assert_same_instant(issued["rfe_deadline"], "2026-10-28T10:00:00Z",
                            "rfe_deadline is the issue clock plus 84 days")

        # A second issuance while ISSUED is not from NONE.
        response = api.issue_rfe(case["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE)


class TestRfeDeadlineSweep:
    def test_rfe_deadline_exact_boundary(self, api):
        """PRD §3.9: "issuance stamps `rfe_issued_at` at the clock and sets
        `rfe_deadline` to the clock plus `rfe_deadline_days`. The clock sweep flips an
        `ISSUED` request to `OVERDUE` once the deadline is strictly past, while a
        clock reading exactly at `rfe_deadline` leaves it `ISSUED`."
        PRD §3.9: "While the dimension shows `ISSUED`, `RESPONDED`, or `OVERDUE`,
        stage advancement and oath assignment remain blocked with `ERR_RFE_OPEN`."

        Design: Corner/calculations/rfe_deadline_exact_boundary
        """
        pipeline = setup_filed_case()
        case = advance_case(pipeline["case"]["id"], "RECEIPTED")
        set_clock("2026-08-06T00:00:00Z")
        issued = validate_success(api.issue_rfe(case["id"], ADMIN), 200)
        assert_same_instant(issued["rfe_deadline"], "2026-10-29T00:00:00Z",
                            "issued 2026-08-06 plus the default 84 days")

        # At exactly the deadline the request remains ISSUED.
        set_clock("2026-10-29T00:00:00Z")
        assert get_case(case["id"])["rfe_status"] == "ISSUED"

        # Strictly past the deadline the sweep flips it to OVERDUE.
        set_clock("2026-10-30T00:00:00Z")
        overdue = get_case(case["id"])
        assert overdue["rfe_status"] == "OVERDUE"
        response = api.advance_case(case["id"], {"to_stage": "BIOMETRICS_COMPLETE"},
                                    ADMIN)
        validate_error(response, ApiErrorId.ERR_RFE_OPEN)


class TestOathCeremonies:
    def test_oath_assign_requires_oath_ready_case(self, api):
        """PRD §3.9: "Assignment — an `IntakeCoordinator` or `ProgramAdmin` action
        naming a `case_id` and carrying the ceremony-version concurrency field of
        §2.7 — requires the ceremony still `SCHEDULED` (`ERR_INVALID_STATE`), the case
        sitting exactly at `APPROVED_PENDING_OATH` (`ERR_CASE_NOT_OATH_READY`), the
        case's RFE dimension clear (`ERR_RFE_OPEN`), and `assigned_count` still below
        `capacity` (`ERR_CEREMONY_FULL`)."

        Design: Corner/endpoints/oath_assign_requires_oath_ready_case
        """
        pipeline = setup_filed_case()
        case = advance_case(pipeline["case"]["id"], "RECEIPTED")
        ceremony = create_ceremony(capacity=2)

        response = api.assign_oath_ceremony(
            ceremony["id"],
            {"case_id": case["id"],
             "expected_ceremony_version": ceremony["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CASE_NOT_OATH_READY)
        assert get_ceremony(ceremony["id"])["assigned_count"] == 0
        assert get_case(case["id"])["stage"] == "RECEIPTED"

    def test_ceremony_conclude_before_date_rejected(self, api):
        """PRD §3.9: "Concluding a ceremony is a `ProgramAdmin` action guarded twice:
        the ceremony must be `SCHEDULED` (`ERR_INVALID_STATE`) and the clock must be
        at or after `ceremony_date` (`ERR_CEREMONY_NOT_YET_HELD`)."

        Design: Corner/endpoints/ceremony_conclude_before_date_rejected
        """
        create_program()
        ceremony = create_ceremony(ceremony_date="2026-09-01T17:00:00Z", capacity=2)
        # The default clock 2026-08-01 is strictly before the ceremony date.
        response = api.conclude_oath_ceremony(ceremony["id"], ADMIN)
        validate_error(response, ApiErrorId.ERR_CEREMONY_NOT_YET_HELD)
        assert get_ceremony(ceremony["id"])["status"] == "SCHEDULED"

    def test_oath_ceremony_full_and_double_assign_rejected(self, api):
        """PRD §3.9: "Assignment — an `IntakeCoordinator` or `ProgramAdmin` action
        naming a `case_id` and carrying the ceremony-version concurrency field of
        §2.7 — requires the ceremony still `SCHEDULED` (`ERR_INVALID_STATE`), the case
        sitting exactly at `APPROVED_PENDING_OATH` (`ERR_CASE_NOT_OATH_READY`), the
        case's RFE dimension clear (`ERR_RFE_OPEN`), and `assigned_count` still below
        `capacity` (`ERR_CEREMONY_FULL`)."

        Design: Corner/endpoints/oath_ceremony_full_and_double_assign_rejected
        """
        bundle = setup_two_oath_ready_cases()
        case_a, case_b = bundle["cases"]
        ceremony_1 = create_ceremony(capacity=1)
        ceremony_2 = create_ceremony(ceremony_date="2026-09-15T17:00:00Z",
                                     venue="Library", capacity=2)

        assigned = assign_case_to_ceremony(ceremony_1["id"], case_a["id"])
        assert assigned["stage"] == "OATH_SCHEDULED"
        assert assigned["oath_ceremony_id"] == ceremony_1["id"]

        # Ceremony 1 is now at capacity: the second ready case is refused.
        current = get_ceremony(ceremony_1["id"])
        response = api.assign_oath_ceremony(
            ceremony_1["id"],
            {"case_id": case_b["id"],
             "expected_ceremony_version": current["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CEREMONY_FULL)
        assert get_ceremony(ceremony_1["id"])["assigned_count"] == 1

        # Case A already left APPROVED_PENDING_OATH, so a second assignment of the
        # same case to another ceremony fails the stage guard.
        ceremony_2_now = get_ceremony(ceremony_2["id"])
        response = api.assign_oath_ceremony(
            ceremony_2["id"],
            {"case_id": case_a["id"],
             "expected_ceremony_version": ceremony_2_now["version"]},
            ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CASE_NOT_OATH_READY)
        assert get_ceremony(ceremony_2["id"])["assigned_count"] == 0

    def test_oath_conclude_case_applicant_referral_cascade(self, api):
        """PRD §3.9: "The conclusion cascades three levels deep: every assigned case
        in `OATH_SCHEDULED` moves to `NATURALIZED`; each such case's applicant
        advances from `FILED` to `NATURALIZED`; and each of those applicants has
        `voter_registration_referred` set to true — the program's referral handshake
        to voter registration. The ceremony itself lands in the terminal
        `CONCLUDED`."

        Design: Difficulty/transitive_cascade/oath_conclude_case_applicant_referral_cascade
        """
        pipeline = setup_oath_ready_case()
        case = pipeline["case"]
        ceremony = create_ceremony(ceremony_date="2026-09-01T17:00:00Z", capacity=2)
        assigned = assign_case_to_ceremony(ceremony["id"], case["id"])
        assert assigned["stage"] == "OATH_SCHEDULED"

        set_clock("2026-09-01T17:00:00Z")
        concluded = validate_success(api.conclude_oath_ceremony(ceremony["id"], ADMIN),
                                     200)
        assert_oath_ceremony(concluded)
        assert concluded["status"] == "CONCLUDED"

        # Hop 1: the assigned case naturalizes.
        case_after = get_case(case["id"])
        assert case_after["stage"] == "NATURALIZED"
        # Hops 2 and 3: the applicant naturalizes and the referral flag is set by the
        # case transition, not by the conclude call directly.
        applicant_after = api.get_applicant(pipeline["applicant"]["id"], COORD).json()["data"]
        assert applicant_after["stage"] == "NATURALIZED"
        assert applicant_after["voter_registration_referred"] is True

    def test_oath_ceremony_cancel_reverts_assignments(self, api):
        """PRD §3.9: "Cancelling, also `ProgramAdmin`-only and only from `SCHEDULED`
        (`ERR_INVALID_STATE`), unwinds instead of completing: every assigned case
        reverts from `OATH_SCHEDULED` to `APPROVED_PENDING_OATH`, each
        `oath_ceremony_id` is nulled, `assigned_count` decrements by the number of
        reverted cases, and the ceremony becomes `CANCELLED`."

        Design: Difficulty/transitive_cascade/oath_conclude_case_applicant_referral_cascade
        """
        pipeline = setup_oath_ready_case()
        case = pipeline["case"]
        ceremony = create_ceremony(capacity=2)
        assign_case_to_ceremony(ceremony["id"], case["id"])
        assert get_ceremony(ceremony["id"])["assigned_count"] == 1

        cancelled = validate_success(api.cancel_oath_ceremony(ceremony["id"], ADMIN),
                                     200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["assigned_count"] == 0

        case_after = get_case(case["id"])
        assert case_after["stage"] == "APPROVED_PENDING_OATH"
        assert case_after["oath_ceremony_id"] is None
