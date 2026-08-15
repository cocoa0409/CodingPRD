"""Travel advisory windows, schedule buffer, and the suspension cascade (PRD §3.1, §3.6)."""
from test_helpers import (
    ApiErrorId,
    approve_application,
    clear_application,
    commit_application,
    create_committed_application,
    create_containing_do_not_travel_advisory,
    create_open_program,
    create_partner_agreement,
    create_program_payload,
    create_student,
    create_submitted_application,
    create_travel_advisory,
    enroll_insurance,
    get_statement_for_application,
    make_student_headers,
    record_payment,
    set_logical_clock,
    setup_open_program_with_application,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    BURSAR_HEADERS,
    COORD_A_HEADERS,
    COORD_B_HEADERS,
    SAFETY_HEADERS,
)


class TestAdvisoryWindowOverlap:
    def test_adjacent_window_accepted_intersecting_rejected(self, api):
        """PRD §3.6: "a new advisory is rejected with `ERR_ADVISORY_WINDOW_OVERLAP` if its
        half-open window intersects that of another `ACTIVE` advisory for the same
        `country_code` — though pure adjacency, where one advisory's `effective_to` equals
        the other's `effective_from`, is not an overlap and is permitted."

        Design: Difficulty/resource_temporal_overlap/advisory_half_open_overlap
        """
        adv_a = create_travel_advisory(
            country_code="FR", level="CAUTION",
            effective_from="2027-01-01T00:00:00Z", effective_to="2027-03-01T00:00:00Z",
        )
        # Adjacent window [2027-03-01, 2027-05-01) touches but does not overlap.
        resp_b = api.create_travel_advisory(
            {
                "country_code": "FR", "level": "WARNING",
                "effective_from": "2027-03-01T00:00:00Z", "effective_to": "2027-05-01T00:00:00Z",
            },
            SAFETY_HEADERS,
        )
        adv_b = validate_success(resp_b, expected_status=201)
        assert adv_b["status"] == "ACTIVE"

        # Properly intersecting window is rejected.
        resp_c = api.create_travel_advisory(
            {
                "country_code": "FR", "level": "CAUTION",
                "effective_from": "2027-02-01T00:00:00Z", "effective_to": "2027-04-01T00:00:00Z",
            },
            SAFETY_HEADERS,
        )
        validate_error(resp_c, ApiErrorId.ERR_ADVISORY_WINDOW_OVERLAP)

    def test_different_country_window_allowed(self, api):
        """PRD §3.6: "a new advisory is rejected with `ERR_ADVISORY_WINDOW_OVERLAP` if its
        half-open window intersects that of another `ACTIVE` advisory for the same
        `country_code` ..."

        Design: Difficulty/resource_temporal_overlap/advisory_half_open_overlap
        """
        create_travel_advisory(
            country_code="FR", level="CAUTION",
            effective_from="2027-01-01T00:00:00Z", effective_to="2027-03-01T00:00:00Z",
        )
        # Same window but a different country_code is not an overlap.
        resp = api.create_travel_advisory(
            {
                "country_code": "JP", "level": "WARNING",
                "effective_from": "2027-01-01T00:00:00Z", "effective_to": "2027-03-01T00:00:00Z",
            },
            SAFETY_HEADERS,
        )
        validate_success(resp, expected_status=201)


class TestProgramScheduleBuffer:
    def test_seven_day_gap_allowed(self, api):
        """PRD §3.1: "If another program at the same `host_institution` exists in `DRAFT` or
        `OPEN` status whose dates are separated from the new program's dates by fewer than
        seven days in either direction, the create is rejected with
        `ERR_PROGRAM_SCHEDULE_BUFFER`; a separation of exactly seven days is permitted, and
        `SUSPENDED` programs do not participate in the check."

        Design: Difficulty/resource_temporal_overlap/program_host_schedule_buffer
        """
        agreement = create_partner_agreement()
        prog1 = get_success_payload = validate_success(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS),
            expected_status=201,
        )
        # Exactly 7 days after prog1 ends (2027-05-10 -> 2027-05-17) is permitted.
        resp = api.create_program(
            create_program_payload(
                agreement["id"],
                name="Lyon Summer 2027", term="SUMMER",
                start_date="2027-05-17T00:00:00Z", end_date="2027-08-15T00:00:00Z",
                application_deadline="2027-02-01T00:00:00Z",
                capacity=20, program_fee_cents=900000, min_gpa=2.50,
            ),
            COORD_A_HEADERS,
        )
        prog2 = validate_success(resp, expected_status=201)
        assert prog2["status"] == "DRAFT"

    def test_six_day_gap_rejected(self, api):
        """PRD §3.1: "... separated from the new program's dates by fewer than seven days in
        either direction, the create is rejected with `ERR_PROGRAM_SCHEDULE_BUFFER` ..."

        Design: Difficulty/resource_temporal_overlap/program_host_schedule_buffer
        """
        agreement = create_partner_agreement()
        validate_success(
            api.create_program(create_program_payload(agreement["id"]), COORD_A_HEADERS),
            expected_status=201,
        )
        # 6-day gap (2027-05-10 -> 2027-05-16) violates the buffer.
        resp = api.create_program(
            create_program_payload(
                agreement["id"],
                name="Lyon Tight Summer 2027", term="SUMMER",
                start_date="2027-05-16T00:00:00Z", end_date="2027-08-10T00:00:00Z",
                application_deadline="2027-02-01T00:00:00Z",
                capacity=20, program_fee_cents=900000, min_gpa=2.50,
            ),
            COORD_A_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_SCHEDULE_BUFFER)


class TestAdvisoryLift:
    def test_advisory_lift_then_relift_returns_invalid_state(self, api):
        """PRD §3.6: "Lifting an advisory — `ACTIVE` to `LIFTED`, a `SafetyOfficer` action —
        closes the window going forward but is deliberately not retroactive ..." and
        PRD §2.10: "The target resource must be in a valid from-state for the requested
        transition ... otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/advisory_lift_then_relift_returns_invalid_state
        """
        advisory = create_travel_advisory(
            country_code="FR", level="WARNING",
            effective_from="2027-01-01T00:00:00Z", effective_to="2027-03-01T00:00:00Z",
        )
        lifted = validate_success(api.lift_travel_advisory(advisory["id"], SAFETY_HEADERS))
        assert lifted["status"] == "LIFTED"

        resp = api.lift_travel_advisory(advisory["id"], SAFETY_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestAdvisoryBlockOnApprove:
    def test_advisory_block_on_approve(self, api):
        """PRD §3.6: "Application approval (§3.2) and insurance enrollment creation (§3.5)
        are both blocked with `ERR_TRAVEL_ADVISORY_BLOCK` whenever an `ACTIVE` advisory
        exists with `level` `DO_NOT_TRAVEL` whose `country_code` matches the program's,
        whose window is in effect at the logical clock — `effective_from` at or before the
        clock and `effective_to` strictly after it — and whose window overlaps the program's
        `[start_date, end_date]` span."

        Design: Corner/validations/advisory_block_on_approve
        """
        program, student, application = setup_open_program_with_application(
            student_overrides={"full_name": "Blocked Student", "email": "blocked@uni.edu"},
        )
        application = clear_application(application, "CLEARED")
        # Partial-overlap advisory in effect at the logical clock (2027-05-05).
        set_logical_clock("2027-05-05T00:00:00Z")
        create_travel_advisory(
            country_code="FR", level="DO_NOT_TRAVEL",
            effective_from="2027-05-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        )
        resp = api.approve_application(application["id"], COORD_B_HEADERS)
        validate_error(resp, ApiErrorId.ERR_TRAVEL_ADVISORY_BLOCK)
        reread = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert reread["status"] == "CLEARED", (
            "A partial-overlap advisory blocks approve but does not suspend the program "
            "or withdraw the application"
        )


class TestAdvisorySuspensionCascade:
    def test_advisory_suspension_cascade_committed_application(self, api):
        """PRD §3.6: "When its window **fully contains** an `OPEN` program's dates —
        `effective_from` at or before the program's `start_date` and `effective_to` at or
        after its `end_date` — for a matching `country_code`, the program is suspended: it
        transitions from `OPEN` to `SUSPENDED`, terminally, with its `version` incremented.
        The cascade continues to the program's applications: every application in `APPROVED`
        or `COMMITTED` is withdrawn with `withdraw_reason` set to `SYSTEM_SUSPENSION`, while
        `CLEARED` applications are deliberately left untouched. Each of those withdrawals
        fires the withdrawal side effects of §3.2 — and for withdrawn `COMMITTED`
        applications that means the seat is released (`seats_taken` decremented, program
        `version` bumped again per §2.7), the billing statement is voided with the full
        refund credit memo of §3.4, and any `ACTIVE` insurance enrollment is cancelled."

        Design: Difficulty/transitive_cascade/advisory_suspension_cascade
        """
        program, student, application = create_committed_application(
            student_overrides={"full_name": "Cascade Student", "email": "cascade@uni.edu", "aid_award_cents": 900000},
        )
        enrollment = enroll_insurance(application, student)
        statement = get_statement_for_application(application["id"])
        record_payment(statement["id"], 200000)

        # Fully containing DO_NOT_TRAVEL advisory triggers the cascade.
        create_travel_advisory(
            country_code="FR", level="DO_NOT_TRAVEL",
            effective_from="2027-01-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        )

        program_after = validate_success(api.get_program(program["id"], COORD_A_HEADERS))
        assert program_after["status"] == "SUSPENDED"

        app_after = validate_success(api.get_application(application["id"], COORD_A_HEADERS))
        assert app_after["status"] == "WITHDRAWN"
        assert app_after["withdraw_reason"] == "SYSTEM_SUSPENSION"

        stmt_after = get_statement_for_application(application["id"])
        assert stmt_after["status"] == "VOID"
        assert stmt_after["credit_memo_cents"] == 200000, (
            "Void refunds monies actually paid: credit_memo_cents must equal the "
            "pre-cascade amount_paid_cents (200000)"
        )
        assert stmt_after["outstanding_cents"] == 0

        ins_resp = api.list_insurance_enrollments(
            COORD_A_HEADERS, params={"application_id": application["id"]},
        )
        ins_data, _meta = validate_paginated(ins_resp)
        assert len(ins_data) == 1
        assert ins_data[0]["status"] == "CANCELLED"

    def test_advisory_suspension_spares_cleared_application(self, api):
        """PRD §3.6: "every application in `APPROVED` or `COMMITTED` is withdrawn with
        `withdraw_reason` set to `SYSTEM_SUSPENSION`, while `CLEARED` applications are
        deliberately left untouched."

        Design: Difficulty/transitive_cascade/advisory_suspension_cascade
        """
        # One COMMITTED application (cascade victim) ...
        program, student_c, app_committed = create_committed_application(
            student_overrides={"full_name": "Committed Victim", "email": "cv@uni.edu"},
        )
        # ... and a second application left in CLEARED (must survive).
        student2 = create_student(full_name="Cleared Survivor", email="cs@uni.edu")
        app_cleared = create_submitted_application(student2, program)
        app_cleared = clear_application(app_cleared, "CLEARED")

        create_travel_advisory(
            country_code="FR", level="DO_NOT_TRAVEL",
            effective_from="2027-01-01T00:00:00Z", effective_to="2027-06-01T00:00:00Z",
        )

        committed_after = validate_success(
            api.get_application(app_committed["id"], COORD_A_HEADERS)
        )
        assert committed_after["status"] == "WITHDRAWN"
        assert committed_after["withdraw_reason"] == "SYSTEM_SUSPENSION"

        cleared_after = validate_success(
            api.get_application(app_cleared["id"], COORD_A_HEADERS)
        )
        assert cleared_after["status"] == "CLEARED", (
            "CLEARED applications are deliberately left untouched by the suspension cascade"
        )
