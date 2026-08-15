"""Program creation validation and the program window lifecycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_donor,
    create_draft_application,
    create_fund,
    create_open_program,
    create_program,
    create_student,
    get_success_data,
    set_clock,
    submit_application,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _donor_and_fund():
    donor = create_donor()
    fund = create_fund()
    return donor["id"], fund["id"]


class TestProgramCreationValidation:
    def test_invalid_program_type_enum_rejected(self, api):
        """PRD §2.8: "**Request shape** — required fields are present, enum
        values are valid, and date ranges are ordered (the application close
        must be later than the application open; a cycle's `ends_on` must be
        later than its `starts_on`; a disbursement's `term_end_date` must be
        on or after its `term_start_date`); otherwise `ERR_VALIDATION` or
        `ERR_INVALID_DATE_RANGE`."
        PRD §3.2: "Three policy selectors shape everything downstream:
        `program_type` (`MERIT`, `NEED`, or `HYBRID`) chooses the weight sets
        used by both the eligibility score of §3.4 and the committee ranking
        score of §3.5; `match_policy` (`STRICT` or `HOLISTIC`) decides
        whether a hard-criterion miss zeroes the eligibility score or merely
        diminishes it; and `stacking_scope` (`ANNUAL` or `PER_TERM`) chooses
        which stacking cap variant of §3.6 applies when a recipient accepts."

        Design: Corner/entities/program_create_invalid_enum_rejected
        """
        donor_id, fund_id = _donor_and_fund()
        resp = api.create_program(
            {
                "name": "Bad Enum",
                "donor_id": donor_id,
                "fund_id": fund_id,
                "program_type": "SPORTS",
                "match_policy": "HOLISTIC",
                "stacking_scope": "ANNUAL",
                "award_amount_cents": 500000,
                "max_recipients": 1,
                "min_gpa_hundredths": 300,
                "required_residency_state": "CA",
                "max_household_income_cents": 10000000,
                "application_open_at": "2026-08-01T00:00:00Z",
                "application_close_at": "2026-09-15T00:00:00Z",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_inverted_application_window_rejected(self, api):
        """PRD §3.2: "The application window is bounded by
        `application_open_at` and `application_close_at`; the close must be
        strictly later than the open, or creation fails with
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/entities/program_create_inverted_window_rejected
        """
        donor_id, fund_id = _donor_and_fund()
        resp = api.create_program(
            {
                "name": "Inverted",
                "donor_id": donor_id,
                "fund_id": fund_id,
                "program_type": "MERIT",
                "match_policy": "HOLISTIC",
                "stacking_scope": "ANNUAL",
                "award_amount_cents": 500000,
                "max_recipients": 1,
                "min_gpa_hundredths": 300,
                "required_residency_state": "CA",
                "max_household_income_cents": 10000000,
                "application_open_at": "2026-09-15T00:00:00Z",
                "application_close_at": "2026-08-01T00:00:00Z",
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestProgramWindowLifecycle:
    def test_publish_before_window_rejected_then_inclusive_gate(self, api):
        """PRD §3.2: "Publishing is allowed once now has reached
        `application_open_at` — the gate is inclusive, so publishing at
        exactly the open instant succeeds, while an earlier attempt fails with
        `ERR_WINDOW_NOT_OPEN`."
        PRD §3.2: "The coordinator creates one — it starts in `DRAFT` —
        naming the sponsoring `donor_id` and the `fund_id` its awards will
        draw on, plus a `name`."

        Design: Corner/state_machines/program_publish_before_window_rejected
        """
        donor_id, fund_id = _donor_and_fund()
        program = create_program(
            donor_id,
            fund_id,
            application_open_at="2026-08-15T00:00:00Z",
            application_close_at="2026-09-15T00:00:00Z",
        )
        assert program["status"] == "DRAFT"

        resp = api.publish_program(program["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)

        set_clock("2026-08-15T00:00:00Z")
        published = validate_success(api.publish_program(program["id"], COORD))
        assert published["status"] == "OPEN", "publish at exactly open_at succeeds"

    def test_extend_reopens_closed_program(self, api):
        """PRD §3.2: "Extending a deadline moves `CLOSED` back to `OPEN`: the
        request carries a `new_close_at` that must be later than the current
        `application_close_at` (otherwise `ERR_INVALID_DATE_RANGE`), and the
        program's `application_close_at` is updated to it — a
        deadline-extension cycle that reopens the window."
        PRD §3.2: "a coordinator's manual close simply flips the status".

        Design: Corner/state_machines/program_extend_reopens_closed_cycle
        """
        student = create_student()
        donor_id, fund_id = _donor_and_fund()
        program = create_open_program(
            donor_id, fund_id, application_close_at="2026-09-01T00:00:00Z"
        )
        get_success_data(api.close_program(program["id"], COORD))

        extended = validate_success(
            api.extend_program(
                program["id"], {"new_close_at": "2026-10-01T00:00:00Z"}, COORD
            )
        )
        assert extended["status"] == "OPEN"
        assert extended["application_close_at"] == "2026-10-01T00:00:00Z"

        # The reopened program accepts submissions under the new close.
        app = create_draft_application(student["id"], program["id"])
        submitted = submit_application(app["id"])
        assert submitted["status"] == "SUBMITTED"

    def test_extend_with_earlier_close_rejected(self, api):
        """PRD §3.2: "the request carries a `new_close_at` that must be later
        than the current `application_close_at` (otherwise
        `ERR_INVALID_DATE_RANGE`)".

        Design: Corner/state_machines/program_extend_reopens_closed_cycle
        """
        donor_id, fund_id = _donor_and_fund()
        program = create_open_program(
            donor_id, fund_id, application_close_at="2026-09-01T00:00:00Z"
        )
        get_success_data(api.close_program(program["id"], COORD))
        resp = api.extend_program(
            program["id"], {"new_close_at": "2026-08-15T00:00:00Z"}, COORD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)

    def test_archive_blocked_then_terminal_lockdown(self, api):
        """PRD §3.2: "Archiving is allowed only from `CLOSED` and only when no
        application of the program remains in `DRAFT`, `SUBMITTED`,
        `UNDER_REVIEW`, `SELECTED`, or `WAITLISTED`; otherwise the archive is
        refused with `ERR_INVALID_STATE`."
        PRD §2.8: "**Own-state** — the target resource's own state permits
        the requested transition; otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/program_archive_blocked_then_terminal_lockdown
        """
        student = create_student()
        donor_id, fund_id = _donor_and_fund()
        program = create_open_program(donor_id, fund_id)
        app = create_draft_application(student["id"], program["id"])
        submit_application(app["id"])
        get_success_data(api.close_program(program["id"], COORD))

        # A SUBMITTED application blocks archival.
        resp = api.archive_program(program["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        # Withdrawing the application unblocks archival.
        get_success_data(api.withdraw_application(app["id"], COORD))
        archived = validate_success(api.archive_program(program["id"], COORD))
        assert archived["status"] == "ARCHIVED"

        # ARCHIVED is terminal: publish is refused.
        resp = api.publish_program(program["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
