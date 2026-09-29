"""Who may call what, what the server says when nobody is identified, what it
says when a named row does not exist, and the duties it refuses to combine."""
from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    VENUE_DEFAULTS,
    confirm_booking,
    create_equipment_pool,
    create_labor_call,
    draft_booking,
    drive_order_to_ready_for_signoff,
    issue_equipment,
    make_anchor_tenant_rep_headers,
    make_changeover_supervisor_headers,
    make_director_headers,
    open_changeover_order,
    place_hold,
    read_asset,
    read_booking,
    read_issue,
    read_labor_call,
    read_order,
    read_reservation,
    read_venue,
    register_tenant,
    return_equipment,
    reserve_dock,
    set_clock,
    setup_arena,
    setup_ice_to_concert_turnaround,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]
COORDINATOR = TEST_USERS["labor_coordinator_headers"]

NO_HEADERS = {}
UNKNOWN = "00000000-0000-4000-8000-0000000000{:02d}"


class TestUnauthenticatedRequests:
    def test_a_headerless_create_is_refused_before_its_body_is_ever_inspected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
        principal, and `X-User-Role`, naming the role that principal is acting in."
        PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the five declared
        role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.10: "**Authentication.** `X-User-Role` and `X-User-ID` both present and the role one
        of the five declared names, otherwise `ERR_UNAUTHENTICATED`."
        PRD §2.10: "When a single request could fail several checks at once, the response must name
        the first failure in the ladder below, never a later one."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/a_request_missing_required_auth_headers_returns_unauthenticated
        """
        set_clock(CLOCK_STARTUP_UTC)

        well_formed_body = dict(VENUE_DEFAULTS, name="Headerless Arena")
        refused = api.create_venue(well_formed_body, NO_HEADERS)
        validate_error(refused, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        envelope = refused.json()["data"]
        assert envelope["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value
        assert isinstance(envelope["message"], str) and envelope["message"]

        malformed_body = api.create_venue({"rigging_capacity_kg": 20_000}, NO_HEADERS)
        validate_error(malformed_body, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
        assert malformed_body.json()["data"]["error_id"] != (
            ApiErrorId.ERR_INVALID_REQUEST.value
        ), "authentication is the first rung, so a missing name never surfaces"


class TestTheNotFoundVocabulary:
    def test_all_ten_not_found_codes_are_reachable_with_an_unknown_identifier(self, api):
        """PRD §2.9: "The unresolved-identifier vocabulary is specific: `ERR_VENUE_NOT_FOUND` for an
        arena, `ERR_PROFILE_NOT_FOUND` for a `config_profile_id`, `ERR_TENANT_NOT_FOUND` for a
        `tenant_id` or a `challenger_tenant_id`, `ERR_BOOKING_NOT_FOUND` for any booking reference
        in a path or body, `ERR_CHALLENGE_NOT_FOUND` for a challenge in a path,
        `ERR_CHANGEOVER_ORDER_NOT_FOUND` for a turnaround in a path or body,
        `ERR_ICE_SHEET_NOT_FOUND` for an ice sheet in a path, `ERR_DOCK_RESERVATION_NOT_FOUND` for a
        dock reservation in a path, `ERR_LABOR_CALL_NOT_FOUND` for a labor call in a path, and
        `ERR_EQUIPMENT_NOT_FOUND` for either an equipment pool or an equipment issue in a path or
        body."
        PRD §2.9: "All ten carry HTTP 404."
        PRD §2.9: "Only once every path segment resolves does the server begin resolving identifiers
        carried in the request body, and body identifiers are resolved in the order the body declares
        them."
        PRD §2.10: "**Existence.** The ten 404 codes of §2.9, path segments left to right, then body
        identifiers in declaration order."

        Design: Corner/errors/every_not_found_code_in_the_catalog_is_triggerable_with_an_unknown_id
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]
        version_before = venue_version(venue_id)
        event = {
            "event_start_utc": "2026-09-10T00:00:00Z",
            "event_end_utc": "2026-09-10T03:00:00Z",
            "expected_attendance": 1_000,
        }

        probes = [
            (
                api.get_venue(UNKNOWN.format(10), MANAGER),
                ApiErrorId.ERR_VENUE_NOT_FOUND,
            ),
            (
                api.create_event_booking(
                    dict(
                        event,
                        venue_id=venue_id,
                        config_profile_id=UNKNOWN.format(11),
                        title="Profile probe",
                        promoter_name="Probe Promotions",
                    ),
                    MANAGER,
                ),
                ApiErrorId.ERR_PROFILE_NOT_FOUND,
            ),
            (
                api.create_event_booking(
                    dict(
                        event,
                        venue_id=venue_id,
                        config_profile_id=profile_id,
                        title="Tenant probe",
                        tenant_id=UNKNOWN.format(12),
                    ),
                    MANAGER,
                ),
                ApiErrorId.ERR_TENANT_NOT_FOUND,
            ),
            (
                api.get_event_booking(UNKNOWN.format(13), MANAGER),
                ApiErrorId.ERR_BOOKING_NOT_FOUND,
            ),
            (
                api.get_hold_challenge(UNKNOWN.format(14), MANAGER),
                ApiErrorId.ERR_CHALLENGE_NOT_FOUND,
            ),
            (
                api.get_changeover_order(UNKNOWN.format(15), SUPERVISOR),
                ApiErrorId.ERR_CHANGEOVER_ORDER_NOT_FOUND,
            ),
            (
                api.transition_ice_sheet(
                    UNKNOWN.format(16), {"to_status": "IN_SERVICE"}, SUPERVISOR
                ),
                ApiErrorId.ERR_ICE_SHEET_NOT_FOUND,
            ),
            (
                api.cancel_dock_slot_reservation(UNKNOWN.format(17), COORDINATOR),
                ApiErrorId.ERR_DOCK_RESERVATION_NOT_FOUND,
            ),
            (
                api.get_labor_call(UNKNOWN.format(18), COORDINATOR),
                ApiErrorId.ERR_LABOR_CALL_NOT_FOUND,
            ),
            (
                api.get_equipment_asset(UNKNOWN.format(19), DIRECTOR),
                ApiErrorId.ERR_EQUIPMENT_NOT_FOUND,
            ),
        ]
        for response, expected in probes:
            validate_error(response, expected.value, 404)

        _rows, meta = validate_paginated(
            api.list_event_bookings(MANAGER, {"venue_id": venue_id})
        )
        assert meta["total_count"] == 0, "the two refused creates wrote nothing"
        assert venue_version(venue_id) == version_before, (
            "ten failures leave the arena row alone"
        )


class TestTerminalStatesRefuseTheirOwnTransitionTwice:
    def test_a_worked_call_and_a_returned_issue_cannot_be_closed_or_returned_again(
        self, api
    ):
        """PRD §3.9: "The call must be `CALLED`, otherwise `ERR_INVALID_LABOR_CALL_STATE`."
        PRD §3.9: "When the call is scoped to a turnaround, that order's `status` must be either
        `READY_FOR_SIGNOFF` or `SIGNED_OFF` — hours cannot be settled against work that is still in
        progress — otherwise `ERR_INVALID_ORDER_STATE`."
        PRD §3.9: "On acceptance the call moves `CALLED → WORKED`, `actual_hours` is stored, and
        `settled_cost_cents` is written from the settled variant."
        PRD §3.9: "The issue must be `ISSUED`, otherwise `ERR_INVALID_ISSUE_STATE`."
        PRD §3.9: "The per-worker amount is the base rate multiplied by the sum of straight hours and
        weighted overtime hours, multiplied by the overnight multiplier, and **then** rounded half up
        to whole cents."
        PRD §3.9: "The pool's `cycles_since_service` rises by one and `service_due` is re-evaluated
        against `service_interval_cycles`."

        Design: Corner/errors/closing_a_worked_call_again_and_returning_a_returned_issue_again_are_rejected
        """
        arena = setup_ice_to_concert_turnaround(
            crew_headcount=40, confirm_incoming=True, floor_panel_units_total=10
        )
        order_id = arena["order"]["id"]
        issue_equipment(arena["floor_pool"]["id"], order_id, 3)
        drive_order_to_ready_for_signoff(
            order_id,
            start_clock="2026-09-10T04:00:00Z",
            complete_clock="2026-09-10T16:30:00Z",
        )
        assert read_order(order_id)["status"] == "READY_FOR_SIGNOFF"

        pool = create_equipment_pool(arena["venue_id"], "STAGE_DECK", 6)
        deck_issue = issue_equipment(pool["id"], order_id, 2)
        returned = return_equipment(deck_issue["id"], damaged_units=0)
        assert returned["status"] == "RETURNED"

        call = create_labor_call(
            "STAGEHAND", 10, "2026-09-10T04:00:00Z", "2026-09-10T12:00:00Z",
            changeover_order_id=order_id,
        )
        assert call["overnight"] is True, "four in the morning UTC is local midnight"
        assert call["estimated_cost_cents"] == 518_400
        worked = validate_success(
            api.close_labor_call(call["id"], {"actual_hours": 8}, COORDINATOR), 200
        )
        assert worked["status"] == "WORKED"
        assert worked["settled_cost_cents"] == 518_400

        refused_call = api.close_labor_call(
            call["id"], {"actual_hours": 8}, COORDINATOR
        )
        validate_error(
            refused_call, ApiErrorId.ERR_INVALID_LABOR_CALL_STATE.value, 409
        )
        stored_call = read_labor_call(call["id"])
        assert stored_call["status"] == "WORKED"
        assert stored_call["settled_cost_cents"] == 518_400

        refused_return = api.return_equipment_issue(
            deck_issue["id"], SUPERVISOR, {"damaged_units": 1}
        )
        validate_error(
            refused_return, ApiErrorId.ERR_INVALID_ISSUE_STATE.value, 409
        )
        stored_issue = read_issue(deck_issue["id"])
        assert stored_issue["status"] == "RETURNED"
        assert stored_issue["damaged_units"] == 0

        stored_pool = read_asset(pool["id"])
        assert stored_pool["units_available"] == 6
        assert stored_pool["units_out_of_service"] == 0
        assert stored_pool["cycles_since_service"] == 1, (
            "the refused second return is not a second cycle"
        )


class TestExclusiveOperationsRefuseForeignRoles:
    def test_six_operations_each_refuse_the_role_that_does_not_own_them(self, api):
        """PRD §2.1: "If both headers are well formed but the named role is not among the roles the
        target endpoint authorises, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
        403)."
        PRD §2.10: "**Role authorisation.** The acting role appears in the endpoint's authorised
        list, otherwise `ERR_ROLE_NOT_PERMITTED`. Applies to every endpoint."
        PRD §2.1: "The role is deliberately excluded from opening turnarounds so that sign-off is
        always a second pair of eyes."
        PRD §2.1: "The role never touches floor execution and never signs a turnaround off."
        PRD §2.5: "A `VenueOperationsDirector` moves the clock by supplying a `to_iso8601` instant
        to the clock-setting capability; the response echoes the new position as `current_utc`."
        PRD §2.10: "When a single request could fail several checks at once, the response must name
        the first failure in the ladder below, never a later one."

        Design: Corner/rbac/roles_cannot_perform_each_others_exclusive_operations
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        draft = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        booking = place_hold(draft["id"])
        version_before = venue_version(venue_id)

        refusals = [
            api.confirm_event_booking(
                booking["id"], {"expected_venue_version": version_before}, SUPERVISOR
            ),
            api.create_changeover_order(
                {
                    "venue_id": venue_id,
                    "from_booking_id": booking["id"],
                    "to_booking_id": booking["id"],
                    "crew_headcount": 40,
                    "expected_venue_version": version_before,
                },
                MANAGER,
            ),
            api.signoff_changeover_order(UNKNOWN.format(20), COORDINATOR),
            api.rule_hold_challenge(
                UNKNOWN.format(21),
                {"decision": "UPHELD"},
                TEST_USERS["anchor_tenant_rep_headers"],
            ),
            api.create_venue(dict(VENUE_DEFAULTS, name="Trespass Arena"), SUPERVISOR),
            api.set_clock("2026-09-01T00:00:00Z", MANAGER),
        ]
        for response in refusals:
            validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

        assert read_booking(booking["id"])["status"] == "HELD"
        assert venue_version(venue_id) == version_before
        _orders, order_meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": venue_id})
        )
        assert order_meta["total_count"] == 0

        probe = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], "Clock probe Sep 20",
            "2026-09-20T00:00:00Z", "2026-09-20T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=0,
            promoter_name="Lakeside Hockey Club",
        )
        held_probe = place_hold(probe["id"])
        assert held_probe["hold_placed_at"] == "2026-08-01T00:00:00.000Z", (
            "the refused clock move left the logical clock at its startup value"
        )


class TestSharedOperationsAcceptEveryAuthorisedRole:
    def test_two_booking_roles_and_two_dock_roles_are_all_served(self, api):
        """PRD §2.1: "A `BookingManager` owns the event calendar and conflict resolution: creating,
        holding, confirming and releasing bookings, sweeping expired holds, and ruling on hold
        challenges."
        PRD §2.1: "An `AnchorTenantRep` acts for exactly one anchor tenant: drafting and holding
        that tenant's own bookings, spending its challenge credits against incumbent holds, and
        withdrawing those challenges."
        PRD §3.3: "Supplying `tenant_id` makes the booking an anchor booking; omitting it makes it a
        promoter booking, in which case `promoter_name` becomes mandatory and the booking will hold
        at the pseudo-tier `OPEN`."
        PRD §3.9: "Either a `ChangeoverSupervisor` or a `LaborCoordinator` reserves a window,
        supplying the `dock_number` to occupy, a `purpose` of either `LOAD_IN` or `LOAD_OUT`, the
        occupation's `window_start_utc` and `window_end_utc` with the end strictly after the start,
        and a `truck_count` between 1 and 60 for the trucks expected through in that window."
        PRD §3.9: "Giving a dock window back is available to either of the same two roles."
        PRD §3.9: "The reservation must be `RESERVED`, otherwise
        `ERR_INVALID_DOCK_RESERVATION_STATE`, and on acceptance it moves `RESERVED → RELEASED` with
        `release_reason` set to `OPERATOR_CANCEL`."

        Design: Corner/rbac/shared_operations_are_accepted_from_every_role_that_declares_them
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]
        tenant = register_tenant(venue_id, "Lakeside Hockey Club", "TIER_2", 5)
        rep = make_anchor_tenant_rep_headers(tenant["id"])

        promoter_draft = validate_success(
            api.create_event_booking(
                {
                    "venue_id": venue_id,
                    "config_profile_id": profile_id,
                    "title": "Promoter game Sep 12",
                    "event_start_utc": "2026-09-12T00:00:00Z",
                    "event_end_utc": "2026-09-12T03:00:00Z",
                    "expected_attendance": 15_000,
                    "promoter_name": "Northline Presents",
                },
                MANAGER,
            ),
            201,
        )
        promoter_held = validate_success(
            api.hold_event_booking(promoter_draft["id"], MANAGER), 200
        )
        assert promoter_held["hold_tier"] == "OPEN"
        assert promoter_held["hold_expires_at"] == "2026-08-02T00:00:00.000Z"

        anchor_draft = validate_success(
            api.create_event_booking(
                {
                    "venue_id": venue_id,
                    "config_profile_id": profile_id,
                    "title": "Anchor game Sep 10",
                    "event_start_utc": "2026-09-10T00:00:00Z",
                    "event_end_utc": "2026-09-10T03:00:00Z",
                    "expected_attendance": 15_000,
                    "tenant_id": tenant["id"],
                },
                rep,
            ),
            201,
        )
        anchor_held = validate_success(
            api.hold_event_booking(anchor_draft["id"], rep), 200
        )
        assert anchor_held["hold_tier"] == "TIER_2"
        assert anchor_held["hold_expires_at"] == "2026-08-08T00:00:00.000Z"

        read_by_rep = validate_success(api.get_venue(venue_id, rep), 200)
        assert read_by_rep["id"] == venue_id
        assert read_by_rep["open_hold_count"] == 2

        supervisor_window = reserve_dock(
            promoter_held["id"], 1, "LOAD_IN",
            "2026-09-11T12:00:00Z", "2026-09-11T18:00:00Z",
            truck_count=6, headers=SUPERVISOR,
        )
        coordinator_window = reserve_dock(
            promoter_held["id"], 2, "LOAD_OUT",
            "2026-09-12T04:00:00Z", "2026-09-12T08:00:00Z",
            truck_count=4, headers=COORDINATOR,
        )
        assert supervisor_window["status"] == "RESERVED"
        assert coordinator_window["status"] == "RESERVED"

        cancelled = validate_success(
            api.cancel_dock_slot_reservation(supervisor_window["id"], COORDINATOR), 200
        )
        assert cancelled["status"] == "RELEASED"
        assert cancelled["release_reason"] == "OPERATOR_CANCEL", (
            "an operator gave the window back, so no booking vanished"
        )
        assert (
            read_reservation(promoter_held["id"], coordinator_window["id"])["status"]
            == "RESERVED"
        )
        live_rows, live_meta = validate_paginated(
            api.list_dock_slot_reservations(
                promoter_held["id"], MANAGER, {"status": "RESERVED"}
            )
        )
        assert live_meta["total_count"] == 1
        assert [r["id"] for r in live_rows] == [coordinator_window["id"]]


class TestSegregationOfDutiesAtSignOff:
    def test_the_opening_principal_is_refused_and_a_different_director_is_accepted(
        self, api
    ):
        """PRD §2.1: "The `X-User-ID` presented at turnaround sign-off must differ from the
        `opened_by_user_id` recorded on that turnaround; a director who is the same principal that
        opened the order is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD §3.8: "The presented `X-User-ID` must differ from `opened_by_user_id`, otherwise
        `ERR_SEGREGATION_OF_DUTIES` — the supervisor who opened the turnaround may never be the
        principal who signs it."
        PRD §3.8: "On acceptance the order moves `READY_FOR_SIGNOFF → SIGNED_OFF` and
        `signed_off_by_user_id` records the director's `X-User-ID`."
        PRD §3.8: "The chronological measurement is then written: `actual_turnaround_minutes` is the
        span from `started_at_utc` to `completed_at_utc`, expressed in whole minutes with any
        fractional minute discarded — rounded down."
        PRD §3.8: "`overrun_minutes` is then the amount by which the actual measurement exceeds
        `window_minutes`, floored at zero: an order that finished inside its window records an
        overrun of 0."
        PRD §3.8: "The arena's `changeover_debt_minutes` rises by exactly this order's
        `overrun_minutes`."

        Design: Corner/rbac/the_user_who_opened_the_turnaround_cannot_sign_it_off
        """
        arena = setup_arena(profiles=("CONCERT", "COURT"), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]

        concert = draft_booking(
            venue_id, arena["profiles"]["CONCERT"]["id"], "Concert Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=8_000, rigging_load_kg=5_000,
            promoter_name="Northline Presents",
        )
        place_hold(concert["id"])
        court = draft_booking(
            venue_id, arena["profiles"]["COURT"]["id"], "Basketball Sep 11",
            "2026-09-11T00:00:00Z", "2026-09-11T04:00:00Z",
            expected_attendance=12_000, rigging_load_kg=0,
            promoter_name="Lakeside Basketball",
        )
        place_hold(court["id"])
        confirm_booking(court["id"], venue_id)

        opener = make_changeover_supervisor_headers("sup-omega")
        order = open_changeover_order(
            venue_id, concert["id"], court["id"], crew_headcount=24, headers=opener
        )
        assert order["opened_by_user_id"] == "sup-omega"
        assert order["window_minutes"] == 1_215
        assert order["planned_turnaround_minutes"] == 380

        pool = create_equipment_pool(venue_id, "FLOOR_PANEL_SET", 10)
        issue_equipment(pool["id"], order["id"], 2)
        drive_order_to_ready_for_signoff(
            order["id"],
            start_clock="2026-09-10T04:00:00Z",
            complete_clock="2026-09-10T09:00:00Z",
            headers=opener,
        )
        assert read_order(order["id"])["status"] == "READY_FOR_SIGNOFF"

        self_signoff = api.signoff_changeover_order(
            order["id"], make_director_headers("sup-omega")
        )
        validate_error(
            self_signoff, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403
        )
        held_open = read_order(order["id"])
        assert held_open["status"] == "READY_FOR_SIGNOFF"
        assert held_open["signed_off_by_user_id"] is None

        signed = validate_success(
            api.signoff_changeover_order(order["id"], DIRECTOR), 200
        )
        assert signed["status"] == "SIGNED_OFF"
        assert signed["signed_off_by_user_id"] == "dir-lakeside"
        assert signed["actual_turnaround_minutes"] == 300
        assert signed["overrun_minutes"] == 0, "five hours inside a twenty-hour window"
        assert signed["window_minutes"] == 1_215
        assert signed["planned_turnaround_minutes"] == 380
        assert read_venue(venue_id)["changeover_debt_minutes"] == 0
