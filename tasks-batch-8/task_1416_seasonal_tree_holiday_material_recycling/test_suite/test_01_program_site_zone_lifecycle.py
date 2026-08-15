"""Program, site, and zone lifecycle: defaults, gates, closure, reschedule."""
import pytest

from test_helpers import (
    ADMIN,
    TEST_USERS,
    ApiErrorId,
    add_site,
    add_zone,
    api_client,
    assert_booking,
    assert_household,
    assert_program,
    assert_same_instant,
    assert_site,
    complete_run,
    create_active_program,
    create_confirmed_booking,
    create_program,
    create_program_payload,
    get_booking,
    get_program,
    get_site,
    get_zone,
    list_notifications,
    open_site,
    patch_site,
    patch_zone,
    publish_program,
    record_intake,
    register_household,
    schedule_run,
    set_clock,
    site_stockpile,
    validate_error,
    validate_success,
)

SUPERVISOR = TEST_USERS["site_supervisor_headers"]


class TestCreateDefaults:

    def test_create_applies_declared_defaults(self):
        """PRD section 3.1: "The program may also carry a
        `target_diversion_rate` between 0 and 1, which defaults to 0.9 when
        omitted. A new program begins with `status` of `DRAFT`, a `posture` of
        `NORMAL`, and all of its counters at zero".
        PRD section 3.1: "an optional `volunteer_slots_per_role` that defaults
        to 3. A new site begins in `PLANNED` status with an empty
        `stockpile_cy` of zero."
        PRD section 3.2: "A household starts life with a `strike_count` of 0
        and `curbside_eligible` set to true".

        Design: Corner/entities/create_applies_declared_defaults
        """
        program = create_program()
        assert_program(program)
        assert program["target_diversion_rate"] == pytest.approx(0.9)
        assert program["status"] == "DRAFT"
        assert program["posture"] == "NORMAL"
        assert program["open_ticket_count"] == 0
        assert program["mulch_produced_cy"] == pytest.approx(0.0)

        site = add_site(program["id"])
        assert_site(site)
        assert site["volunteer_slots_per_role"] == 3
        assert site["status"] == "PLANNED"
        assert site["stockpile_cy"] == pytest.approx(0.0)

        zone = add_zone(program["id"])
        household = register_household(program["id"], zone["id"])
        assert_household(household)
        assert household["strike_count"] == 0
        assert household["curbside_eligible"] is True

    def test_create_with_system_fields_input_ignored(self):
        """PRD section 2.5: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD section 3.1: "A new program begins with `status` of `DRAFT`, a
        `posture` of `NORMAL`, and all of its counters at zero".

        Design: Corner/entities/create_with_system_fields_input_ignored
        """
        supplied_id = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
        resp = api_client.create_program(
            create_program_payload(id=supplied_id, version=99,
                                   status="ACTIVE"),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_program(data)
        assert data["id"] != supplied_id, "server must mint its own UUID"
        assert data["status"] == "DRAFT", \
            f"client-supplied status must be ignored, got {data['status']}"
        assert isinstance(data["version"], int)


class TestProgramLifecycle:

    def test_program_window_shorter_than_seven_days_invalid(self):
        """PRD section 3.1: "The window end must fall at least seven days
        after the window start; a shorter window is rejected with
        `ERR_VALIDATION`."
        PRD section 2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD section 2.2: "The `error_id` is a unique, machine-readable string
        that identifies the specific error."

        Design: Corner/validations/program_window_shorter_than_seven_days_invalid
        """
        resp = api_client.create_program(
            create_program_payload(window_start="2027-01-02T00:00:00Z",
                                   window_end="2027-01-05T00:00:00Z"),
            ADMIN,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_VALIDATION)
        assert error_data.get("message"), "error data must carry a message"
        body = resp.json()
        assert body["response_type"] == "error"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_program_double_publish_returns_invalid_state(self):
        """PRD section 3.1: "Publishing moves the program `DRAFT → PUBLISHED`
        and is the season's point of no return for structure".
        PRD section 2.7: "Fifth, state legality: the target resource must be
        in a state from which the requested transition is declared, including
        terminal-state lockdown; violations surface as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/program_double_publish_returns_invalid_state
        """
        program = create_program()
        add_site(program["id"])
        add_zone(program["id"])
        publish_program(program)

        resp = api_client.patch_program(
            program["id"],
            {"status": "PUBLISHED",
             "expected_program_version": get_program(program["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_program(program["id"])["status"] == "PUBLISHED"

    def test_program_close_blocked_by_open_items(self):
        """PRD section 3.8: "Closure is guarded on five fronts, all reported
        as `ERR_PROGRAM_HAS_OPEN_ITEMS`: every drop-off site must be `CLOSED`;
        at least one diversion report must be `PUBLISHED`; no booking may
        remain in `CONFIRMED` or `MISSED`; no contamination ticket may remain
        in `OPEN` or `APPEALED`; and every mulch event must be `CLOSED`."

        Design: Corner/validations/program_close_blocked_by_open_items
        """
        ctx = create_active_program()
        program = ctx["program"]

        resp = api_client.patch_program(
            program["id"],
            {"status": "CLOSED",
             "expected_program_version": get_program(program["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_ITEMS)
        assert get_program(program["id"])["status"] == "ACTIVE"


class TestSiteLifecycle:

    def test_closed_site_terminal_lockdown(self):
        """PRD section 3.1: "The final step, `CLOSING → CLOSED`, is guarded
        twice over: the site's `stockpile_cy` must be exactly zero, and no
        contamination ticket referencing the site may remain in `OPEN` or
        `APPEALED` status; either violation is rejected with
        `ERR_SITE_NOT_CLOSABLE`."
        PRD section 2.7: "Fifth, state legality: the target resource must be
        in a state from which the requested transition is declared, including
        terminal-state lockdown; violations surface as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/closed_site_terminal_lockdown
        """
        ctx = create_active_program()
        site = ctx["site"]
        open_site(site)
        patch_site(site["id"], status="CLOSING")
        closed = patch_site(site["id"], status="CLOSED")
        assert closed["status"] == "CLOSED"

        resp = api_client.patch_site(
            site["id"],
            {"status": "OPEN",
             "expected_site_version": get_site(site["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_site(site["id"])["status"] == "CLOSED"

    def test_site_suspend_blocks_intake(self):
        """PRD section 3.1: "Either a `ProgramAdmin` or a `SiteSupervisor` may
        then suspend an `OPEN` site (`OPEN → SUSPENDED`), which blocks further
        gate intake with `ERR_SITE_NOT_OPEN` while leaving existing bookings
        and shifts untouched".
        PRD section 3.3: "the site must be `OPEN` (`ERR_SITE_NOT_OPEN`
        otherwise, which is also how intake fails while a site is
        `SUSPENDED`)".

        Design: Corner/state_machines/site_suspend_blocks_intake
        """
        ctx = create_active_program(clock="2027-01-05T00:00:00Z")
        site = ctx["site"]
        open_site(site)
        patch_site(site["id"], status="SUSPENDED")

        resp = api_client.create_intake_event(
            {"site_id": site["id"], "source_type": "CITY_CREW",
             "tree_count": 5, "size_class": "MEDIUM"},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_OPEN)
        assert site_stockpile(site["id"]) == pytest.approx(0.0)

    def test_site_close_blocked_by_nonzero_stockpile(self):
        """PRD section 3.1: "The final step, `CLOSING → CLOSED`, is guarded
        twice over: the site's `stockpile_cy` must be exactly zero, and no
        contamination ticket referencing the site may remain in `OPEN` or
        `APPEALED` status; either violation is rejected with
        `ERR_SITE_NOT_CLOSABLE`."
        PRD section 3.5: "The `input_cy` may not exceed the site's current
        `stockpile_cy` — exact equality draws the pile to zero and is
        allowed".

        Design: Corner/validations/site_close_blocked_by_nonzero_stockpile
        """
        ctx = create_active_program(clock="2027-01-05T00:00:00Z")
        program, site = ctx["program"], ctx["site"]
        open_site(site)
        record_intake(site["id"], tree_count=1, size_class="MEDIUM")
        assert site_stockpile(site["id"]) > 0

        patch_site(site["id"], status="CLOSING")
        resp = api_client.patch_site(
            site["id"],
            {"status": "CLOSED",
             "expected_site_version": get_site(site["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SITE_NOT_CLOSABLE)
        assert get_site(site["id"])["status"] == "CLOSING"

        run = schedule_run(program["id"], site["id"])
        complete_run(run, measured_input_tons=0.1, measured_output_cy=0.2)
        assert site_stockpile(site["id"]) == pytest.approx(0.0)

        closed = patch_site(site["id"], status="CLOSED")
        assert closed["status"] == "CLOSED"


class TestZoneReschedule:

    def test_zone_reschedule_cascades_bookings_and_notifies(self):
        """PRD section 3.2: "When a reschedule lands, every `CONFIRMED`
        booking on the zone has its `service_date` rewritten to the new date
        and one `ZONE_RESCHEDULED` notification is created per affected
        household."

        Design: Corner/state_machines/zone_reschedule_cascades_bookings_and_notifies
        """
        ctx = create_active_program()
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=1, size_class="SMALL")
        assert_same_instant(booking["service_date"], "2027-01-09T00:00:00Z")

        set_clock("2027-01-05T00:00:00Z")
        updated = patch_zone(zone["id"],
                             collection_date="2027-01-12T00:00:00Z")
        assert_same_instant(updated["collection_date"], "2027-01-12T00:00:00Z")

        booking_after = get_booking(booking["id"])
        assert_booking(booking_after)
        assert_same_instant(booking_after["service_date"],
                            "2027-01-12T00:00:00Z",
                            "reschedule must cascade to CONFIRMED bookings")
        assert booking_after["status"] == "CONFIRMED"

        entries = list_notifications(
            program["id"], params={"kind": "ZONE_RESCHEDULED"})
        if isinstance(entries, dict) and "data" in entries:
            entries = entries["data"]
        matching = [e for e in entries
                    if e["kind"] == "ZONE_RESCHEDULED"
                    and e.get("zone_id") == zone["id"]
                    and e.get("household_id") == household["id"]]
        assert len(matching) == 1, \
            f"expected exactly one ZONE_RESCHEDULED notice, got {matching}"

    def test_zone_reschedule_lead_time_boundary(self):
        """PRD section 3.2: "Moving a zone's `collection_date` is permitted in
        exactly two situations: as a makeup-day move when the current
        collection date has already passed, or with at least forty-eight hours
        of lead time, meaning the clock reads no later than forty-eight hours
        before the current collection date — the boundary is inclusive, so
        exactly forty-eight hours ahead is still permitted. A move attempted
        inside that lead is rejected with `ERR_NOTIFICATION_LEAD_TIME`, and in
        either case the new date must lie within the program window and in the
        future."

        Design: Corner/validations/zone_reschedule_lead_time_boundary
        """
        ctx = create_active_program()
        zone1 = ctx["zone"]
        zone2 = add_zone(ctx["program"]["id"], zone_code="NW-2",
                         collection_date="2027-01-09T00:00:00Z")

        # At exactly collection_date - 48h the move is allowed (inclusive).
        set_clock("2027-01-07T00:00:00Z")
        moved = patch_zone(zone1["id"],
                           collection_date="2027-01-12T00:00:00Z")
        assert_same_instant(moved["collection_date"], "2027-01-12T00:00:00Z")

        # One second later the same move is inside the lead time.
        set_clock("2027-01-07T00:00:01Z")
        resp = api_client.patch_zone(
            zone2["id"],
            {"collection_date": "2027-01-12T00:00:00Z",
             "expected_zone_version": get_zone(zone2["id"])["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_NOTIFICATION_LEAD_TIME)
        assert_same_instant(get_zone(zone2["id"])["collection_date"],
                            "2027-01-09T00:00:00Z")
