"""Incident lifecycle (including the reopen cycle), segregation of duties,
and site posture consequences (ESCALATED block, DEGRADED surge cap)."""
from test_helpers import (
    ADMIN,
    OP_ALICE,
    OP_BOB,
    ApiErrorId,
    api_client,
    assert_incident,
    create_incident,
    create_reserved_booking,
    create_site,
    create_site_with_stalls,
    investigate_incident,
    acknowledge_incident,
    resolve_incident,
    make_driver_headers,
    register_driver,
    register_drivers,
    set_clock,
    validate_error,
    validate_success,
)


class TestResolveReopenCycle:

    def test_reopen_loop_completes_inside_window(self):
        """PRD section 3.8: "A resolved report is not necessarily final —
        within 72 hours of `resolved_at`, inclusive, a `SiteOperator` may move
        it to `REOPENED`, incrementing `reopened_count`, after which it flows
        back through `INVESTIGATING` to a fresh `RESOLVED`; the cycle may
        repeat while the reopen window holds".

        Design: Difficulty/non_linear_state_machine/incident_resolve_reopen_cycle
        """
        site = create_site(name="S")
        driver = register_driver("CDL-C-1", "C One")
        set_clock("2026-08-10T00:00:00Z")
        inc = create_incident(site["id"], "SECURITY", "HIGH", "loitering",
                              reporter_driver_id=driver["id"])
        acknowledge_incident(inc["id"], OP_ALICE)
        investigate_incident(inc["id"], OP_ALICE)
        resolve_incident(inc["id"], OP_BOB)

        resp = api_client.transition_incident(inc["id"], {"to": "REOPENED"},
                                              OP_BOB)
        reopened = validate_success(resp, expected_status=200)
        assert reopened["status"] == "REOPENED"
        assert reopened["reopened_count"] == 1

        resp = api_client.transition_incident(inc["id"],
                                              {"to": "INVESTIGATING"},
                                              OP_ALICE)
        assert validate_success(resp)["status"] == "INVESTIGATING"
        resp = api_client.transition_incident(inc["id"], {"to": "RESOLVED"},
                                              OP_BOB)
        resolved = validate_success(resp, expected_status=200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == "op-bob"
        assert_incident(resolved)

    def test_reopen_cycle_repeats_while_window_holds(self):
        """PRD section 3.8: "A resolved report is not necessarily final —
        within 72 hours of `resolved_at`, inclusive, a `SiteOperator` may move
        it to `REOPENED`, incrementing `reopened_count`, after which it flows
        back through `INVESTIGATING` to a fresh `RESOLVED`; the cycle may
        repeat while the reopen window holds, and a reopen attempted strictly
        after the window is `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Difficulty/non_linear_state_machine/incident_resolve_reopen_cycle
        """
        site = create_site(name="S")
        set_clock("2026-08-10T00:00:00Z")
        inc = create_incident(site["id"], "FACILITY", "LOW", "pothole")
        acknowledge_incident(inc["id"], OP_ALICE)
        investigate_incident(inc["id"], OP_ALICE)
        resolve_incident(inc["id"], OP_BOB)

        # First loop: reopen one hour after the first resolution.
        set_clock("2026-08-10T01:00:00Z")
        resp = api_client.transition_incident(inc["id"], {"to": "REOPENED"},
                                              OP_BOB)
        assert validate_success(resp)["reopened_count"] == 1
        investigate_incident(inc["id"], OP_ALICE)
        set_clock("2026-08-10T02:00:00Z")
        resolve_incident(inc["id"], OP_BOB)

        # Second loop: still inside 72 hours of the fresh resolved_at.
        set_clock("2026-08-10T03:00:00Z")
        resp = api_client.transition_incident(inc["id"], {"to": "REOPENED"},
                                              OP_BOB)
        reopened_again = validate_success(resp, expected_status=200)
        assert reopened_again["status"] == "REOPENED"
        assert reopened_again["reopened_count"] == 2, \
            "each RESOLVED -> REOPENED loop increments reopened_count"


class TestSegregationOfDuties:

    def test_incident_resolve_same_operator_segregation_rejected(self):
        """PRD section 3.8: "Resolution is segregated: the resolver's
        `X-User-ID` must differ from `acknowledged_by_user_id`, otherwise the
        transition is rejected with `ERR_SEGREGATION_OF_DUTIES`; a valid
        resolution stamps `resolved_by_user_id` and `resolved_at`."

        Design: Corner/validations/incident_resolve_same_operator_segregation_rejected
        """
        site = create_site(name="S")
        driver = register_driver("CDL-SD-1", "S Dee")
        set_clock("2026-08-10T00:00:00Z")
        inc = create_incident(site["id"], "SECURITY", "HIGH", "tailgating",
                              reporter_driver_id=driver["id"])
        acknowledge_incident(inc["id"], OP_ALICE)
        investigate_incident(inc["id"], OP_ALICE)

        resp = api_client.transition_incident(inc["id"], {"to": "RESOLVED"},
                                              OP_ALICE)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        resp = api_client.transition_incident(inc["id"], {"to": "RESOLVED"},
                                              OP_BOB)
        resolved = validate_success(resp, expected_status=200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolved_by_user_id"] == "op-bob"


class TestReopenWindow:

    def test_reopen_window_inclusive_72h_then_expired(self):
        """PRD section 3.8: "A resolved report is not necessarily final —
        within 72 hours of `resolved_at`, inclusive, a `SiteOperator` may move
        it to `REOPENED`, incrementing `reopened_count`, after which it flows
        back through `INVESTIGATING` to a fresh `RESOLVED`; the cycle may
        repeat while the reopen window holds, and a reopen attempted strictly
        after the window is `ERR_REOPEN_WINDOW_EXPIRED`."

        Design: Corner/validations/reopen_window_inclusive_72h_then_expired
        """
        site = create_site(name="S")
        set_clock("2026-08-09T00:00:00Z")
        inc = create_incident(site["id"], "FACILITY", "LOW", "pothole")
        acknowledge_incident(inc["id"], OP_ALICE)
        investigate_incident(inc["id"], OP_ALICE)
        set_clock("2026-08-10T00:00:00Z")
        resolve_incident(inc["id"], OP_BOB)

        set_clock("2026-08-13T00:00:00Z")
        resp = api_client.transition_incident(inc["id"], {"to": "REOPENED"},
                                              OP_BOB)
        reopened = validate_success(resp, expected_status=200)
        assert reopened["reopened_count"] == 1, \
            "reopen at exactly resolved_at + 72h is the inclusive boundary"

        investigate_incident(inc["id"], OP_ALICE)
        resolve_incident(inc["id"], OP_BOB)  # resolved again at 2026-08-13
        set_clock("2026-08-16T00:00:01Z")
        resp = api_client.transition_incident(inc["id"], {"to": "REOPENED"},
                                              OP_BOB)
        validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)


class TestPostureConsequences:

    def test_escalated_posture_blocks_then_recovers(self):
        """PRD section 3.8: "Any `CRITICAL` among them puts the site in
        `ESCALATED`".
        PRD section 3.8: "`ESCALATED` blocks new booking creation and waitlist
        acceptance with `ERR_SITE_ESCALATED` while leaving existing bookings
        and check-ins untouched".
        PRD section 3.8: "a site returns to `NORMAL` once neither condition
        holds."

        Design: Corner/state_machines/escalated_posture_blocks_then_recovers
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        reporter = register_driver("CDL-E1-1", "E One")
        booker = register_driver("CDL-E2-1", "E Two")
        set_clock("2026-08-01T00:00:00Z")
        inc = create_incident(site["id"], "SECURITY", "CRITICAL", "break-in",
                              reporter_driver_id=reporter["id"])

        resp = api_client.create_booking(
            {"driver_id": booker["id"], "site_id": site["id"],
             "booking_kind": "RESERVED", "arrival_date": "2026-08-10",
             "night_count": 1, "payment_mode": "DRIVER_DIRECT"},
            make_driver_headers(booker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SITE_ESCALATED)

        acknowledge_incident(inc["id"], OP_ALICE)
        investigate_incident(inc["id"], OP_ALICE)
        resolve_incident(inc["id"], OP_BOB)

        resp = api_client.get_site(site["id"], ADMIN)
        assert validate_success(resp)["posture"] == "NORMAL", \
            "resolving the only CRITICAL recomputes posture to NORMAL"

        booking = create_reserved_booking(booker["id"], site["id"],
                                          "2026-08-10", 1)
        assert booking["status"] == "BOOKED", \
            "creation succeeds again once the site recovers"

    def test_degraded_posture_caps_occupancy_surge(self):
        """PRD section 3.8: "otherwise, at least three `LIGHTING` incidents in
        that set put it in `DEGRADED`".
        PRD section 3.2: "Surge suppression applies to degraded sites: when
        the site `posture` is `DEGRADED` (§3.8), the occupancy multiplier for
        new quotes is capped at 1.00 even where the tier table would yield
        more."

        Design: Corner/state_machines/degraded_posture_caps_occupancy_surge
        """
        ctx = create_site_with_stalls(num_reservable=5)
        site = ctx["site"]
        drivers = register_drivers(5, "CDL-D")
        set_clock("2026-08-01T00:00:00Z")
        for d in drivers[:4]:
            create_reserved_booking(d["id"], site["id"], "2026-08-10", 1)
        for i in range(1, 4):
            create_incident(site["id"], "LIGHTING", "MEDIUM",
                            f"pole {i} out")

        resp = api_client.get_site(site["id"], ADMIN)
        assert validate_success(resp)["posture"] == "DEGRADED", \
            "3 open LIGHTING incidents with no CRITICAL degrade the site"

        fifth = create_reserved_booking(drivers[4]["id"], site["id"],
                                        "2026-08-10", 1)
        assert fifth["quoted_total_cents"] == 5000, (
            f"the occupancy multiplier is capped at 1.00 despite 80% "
            f"occupancy: got {fifth['quoted_total_cents']}"
        )


class TestValidationPriority:

    def test_escalated_site_beats_past_window(self):
        """PRD section 2.7: "Every mutating request passes through an ordered
        validation pipeline. The first failing check determines the response;
        once a check fails, no later check is consulted."
        PRD section 2.7: "7. Safety gate: the site must not be `ESCALATED`
        when new inventory is committed — booking creation and waitlist
        acceptance — otherwise `ERR_SITE_ESCALATED` (409)."
        PRD section 2.7: "8. Window values on booking creation and waitlist
        joins (all 422): a `RESERVED` arrival before the clock date is
        `ERR_WINDOW_IN_PAST`".

        Design: Difficulty/priority_pair_validation_conflict/escalated_site_beats_past_window
        """
        ctx = create_site_with_stalls(num_reservable=1)
        site = ctx["site"]
        driver = register_driver("CDL-V-1", "V One")
        set_clock("2026-08-10T00:00:00Z")
        create_incident(site["id"], "SECURITY", "CRITICAL", "break-in",
                        reporter_driver_id=driver["id"])

        resp = api_client.create_booking(
            {"driver_id": driver["id"], "site_id": site["id"],
             "booking_kind": "RESERVED", "arrival_date": "2026-08-01",
             "night_count": 1, "payment_mode": "DRIVER_DIRECT"},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SITE_ESCALATED)
        assert resp.json()["data"]["error_id"] != "ERR_WINDOW_IN_PAST", \
            "the safety gate (step 7) fires before window values (step 8)"

    def test_past_window_alone_yields_window_in_past(self):
        """PRD section 2.7: "8. Window values on booking creation and waitlist
        joins (all 422): a `RESERVED` arrival before the clock date is
        `ERR_WINDOW_IN_PAST`".
        PRD section 2.7: "The first failing check determines the response;
        once a check fails, no later check is consulted."

        Design: Difficulty/priority_pair_validation_conflict/escalated_site_beats_past_window
        """
        ctx = create_site_with_stalls(num_reservable=1)
        driver = register_driver("CDL-V-2", "V Two")
        set_clock("2026-08-10T00:00:00Z")

        resp = api_client.create_booking(
            {"driver_id": driver["id"], "site_id": ctx["site"]["id"],
             "booking_kind": "RESERVED", "arrival_date": "2026-08-01",
             "night_count": 1, "payment_mode": "DRIVER_DIRECT"},
            make_driver_headers(driver["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)
        # On a NORMAL site the losing check of the pair fires in isolation,
        # confirming the dual-failure outcome above is a priority decision.
