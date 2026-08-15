"""Visit execution: check-in/check-out lifecycle, photo-evidence window
semantics, on_site_minutes computation, and terminal-state lockdown on
verification."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    check_in_assignment,
    execute_visit,
    make_field_rep_headers,
    make_scenario,
    schedule_assignment,
    set_clock,
    upload_photo,
    validate_error,
    validate_success,
    verify_visit,
    visit_store,
)

PM = TEST_USERS["pm_headers"]


class TestCheckoutPhotoPrecondition:
    def test_checkout_without_before_photo_blocked(self, api):
        """PRD 3.3: "Checking out requires the visit to already carry at least
        one `BEFORE` photo and at least one `AFTER` photo; attempting checkout
        without both is rejected with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/checkout_without_photos_blocked
        """
        scn = make_scenario()
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        visit = check_in_assignment(asg["id"], rep["id"])
        upload_photo(visit["id"], rep["id"], "AFTER", "2026-08-05T09:30:00Z")
        set_clock("2026-08-05T10:30:00Z")
        resp = api.check_out_assignment(asg["id"], make_field_rep_headers(rep["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPhotoWindow:
    def test_photo_window_inclusive_bounds(self, api):
        """PRD 3.4: "While on site, a photo's `captured_at` must be at or after
        the visit's `check_in_at` and at or before the current logical clock
        time — a capture timestamp before check-in, or in the future, is
        rejected with `ERR_TEMPORAL_INVALID`. The comparison is at second-level
        precision, inclusive on both ends."

        Design: Corner/calculations/photo_window_inclusive_bounds
        """
        scn = make_scenario()
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        visit = check_in_assignment(asg["id"], rep["id"])
        # captured_at exactly equal to check_in_at: inclusive lower bound
        lower = api.upload_photo(
            visit["id"],
            {
                "photo_type": "BEFORE",
                "image_url": "https://img/b.jpg",
                "captured_at": visit["check_in_at"],
            },
            make_field_rep_headers(rep["id"]),
        )
        validate_success(lower, 201)
        # captured_at exactly equal to the current clock: inclusive upper bound
        set_clock("2026-08-05T10:00:00Z")
        upper = api.upload_photo(
            visit["id"],
            {
                "photo_type": "AFTER",
                "image_url": "https://img/a.jpg",
                "captured_at": "2026-08-05T10:00:00Z",
            },
            make_field_rep_headers(rep["id"]),
        )
        validate_success(upper, 201)

    def test_photo_before_checkin_rejected(self, api):
        """PRD 3.4: "While on site, a photo's `captured_at` must be at or after
        the visit's `check_in_at` and at or before the current logical clock
        time — a capture timestamp before check-in, or in the future, is
        rejected with `ERR_TEMPORAL_INVALID`."

        Design: Corner/calculations/photo_before_window_rejected
        """
        scn = make_scenario()
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        set_clock("2026-08-05T09:30:00Z")
        visit = check_in_assignment(asg["id"], rep["id"])
        # check_in_at is server-stamped with three fractional digits (PRD 2.2);
        # compare parsed instants, not raw strings ("...00.000Z" < "...00Z"
        # lexicographically).
        from datetime import datetime
        _ci = datetime.fromisoformat(
            visit["check_in_at"].replace("Z", "+00:00"))
        assert _ci >= datetime.fromisoformat("2026-08-05T09:30:00+00:00")
        resp = api.upload_photo(
            visit["id"],
            {
                "photo_type": "BEFORE",
                "image_url": "https://img/early.jpg",
                "captured_at": "2026-08-05T09:29:59Z",
            },
            make_field_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_INVALID)

    def test_photo_upload_after_checkout_rejected(self, api):
        """PRD 3.4: "Uploads are accepted only while the owning assignment
        remains `ON_SITE`; after checkout the visit is frozen and further
        uploads are rejected with `ERR_INVALID_STATE`."

        Design: Corner/validations/photo_upload_after_checkout_rejected
        """
        scn = make_scenario()
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        visit = execute_visit(
            asg["id"], rep["id"], "2026-08-05T09:30:00Z", "2026-08-05T10:00:00Z"
        )
        resp = api.upload_photo(
            visit["id"],
            {
                "photo_type": "FIXTURE",
                "image_url": "https://img/x.jpg",
                "captured_at": "2026-08-05T09:45:00Z",
            },
            make_field_rep_headers(rep["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOnSiteMinutes:
    def test_on_site_minutes_computed_at_checkout(self, api):
        """PRD 3.3: "A successful checkout stamps `check_out_at` from the
        logical clock, computes `on_site_minutes` as the number of minutes
        between check-in and check-out, and moves the assignment `ON_SITE` to
        `SUBMITTED`."
        PRD 3.3: "Check-in creates the visit itself: a store-visit record is
        born with `check_in_at` stamped from the logical clock, `check_out_at`
        unset, `on_site_minutes` 0 until checkout."

        Design: Corner/calculations/on_site_minutes_computed_at_checkout
        """
        scn = make_scenario(
            client_overrides={
                "name": "Min Client",
                "billing_model": "HOURLY",
                "hourly_rate_cents": 4200,
            }
        )
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-05T09:00:00Z",
            scheduled_end="2026-08-05T12:00:00Z",
        )
        visit = execute_visit(
            asg["id"], rep["id"], "2026-08-05T10:00:00Z", "2026-08-05T11:35:00Z"
        )
        assert visit["on_site_minutes"] == 95, (
            f"10:00:00 -> 11:35:00 must compute 95 minutes, "
            f"got {visit['on_site_minutes']}"
        )
        assert visit["check_out_at"] is not None
        asg_after = api.get_assignment(asg["id"], PM)
        assert validate_success(asg_after)["status"] == "SUBMITTED"


class TestVerifyTerminalLockdown:
    def test_verify_already_verified_visit_rejected(self, api):
        """PRD 3.5: "Verification requires the visit's `verification_status` to
        be `PENDING_REVIEW` and requires at least one `BEFORE` photo and one
        `AFTER` photo on file."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Corner/state_machines/verify_from_already_verified_rejected
        """
        scn = make_scenario()
        asg, visit = visit_store(scn, outcome="verify")
        assert visit["verification_status"] == "VERIFIED"
        resp = api.verify_store_visit(visit["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
