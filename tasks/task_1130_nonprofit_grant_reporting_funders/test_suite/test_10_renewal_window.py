"""Renewal window boundaries: inclusive open, lapsing after close (PRD §3.9,
§2.11)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_renewal_application,
    set_clock,
    setup_active_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
DIRECTOR = TEST_USERS["director_headers"]


class TestRenewalWindowBoundary:
    def test_renewal_submit_one_second_before_open_rejected(self, api):
        """PRD §3.9: "Submitting from `NOT_OPEN` — before the window has opened
        — is rejected with `ERR_RENEWAL_WINDOW_NOT_OPEN` (HTTP 409)."
        PRD §3.9: "`window_open` is the grant's `end_date` minus
        `renewal_window_days`, taken at 00:00:00Z" — end_date 2027-05-31 with
        the default 60-day window gives window_open 2027-04-01T00:00:00Z.

        Design: Difficulty/boundary_precision_check/renewal_window_opens_at_exact_instant
        """
        ctx = setup_active_grant()
        ra = create_renewal_application(ctx["grant"]["id"])
        assert ra["status"] == "NOT_OPEN"

        set_clock("2027-03-31T23:59:59Z")  # one second before window_open
        resp = api.submit_renewal_application(ra["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN)

    def test_renewal_submit_at_exact_window_open_succeeds(self, api):
        """PRD §2.11: "Advancing the clock fires any time-based automatic
        transitions whose moment has arrived: a renewal application in
        `NOT_OPEN` whose `window_open` has been reached moves to `ELIGIBLE`."
        PRD §3.9: "While the application is `ELIGIBLE`, a `ProgramDirector`
        submits it; submission stamps `submitted_at` with the current logical
        time."

        Design: Difficulty/boundary_precision_check/renewal_window_opens_at_exact_instant
        """
        ctx = setup_active_grant()
        ra = create_renewal_application(ctx["grant"]["id"])

        set_clock("2027-04-01T00:00:00Z")  # exactly window_open
        resp = api.submit_renewal_application(ra["id"], DIRECTOR)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED", (
            "window_open is inclusive: submit at exactly 2027-04-01T00:00:00Z "
            "must succeed after the NOT_OPEN -> ELIGIBLE auto-transition"
        )


class TestRenewalLapse:
    def test_renewal_lapsed_after_window_close(self, api):
        """PRD §2.11: "one in `ELIGIBLE` whose `window_close` has passed without
        a submission moves to `LAPSED`."
        PRD §3.9: "submitting from `LAPSED` — after the window has closed — is
        rejected with `ERR_RENEWAL_WINDOW_LAPSED` (HTTP 409)."
        PRD §3.9: "`window_close` is the grant's `end_date` at 23:59:59Z."

        Design: Corner/validations/renewal_lapsed_after_window_close
        """
        ctx = setup_active_grant()
        ra = create_renewal_application(ctx["grant"]["id"])

        set_clock("2027-04-15T00:00:00Z")  # inside the window -> ELIGIBLE
        set_clock("2027-06-01T00:00:00Z")  # past window_close 2027-05-31T23:59:59Z

        resp = api.submit_renewal_application(ra["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_RENEWAL_WINDOW_LAPSED)

        rows, _ = validate_paginated(
            api.list_renewal_applications(ctx["grant"]["id"], OFFICER)
        )
        assert rows[0]["status"] == "LAPSED"
