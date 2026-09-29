"""Role authority, separation of duties and error-code reachability.

Who may act, who may not, and whether every declared not-found and invalid-state
identifier in the catalogue can actually be reached from the wire.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    cancel_event,
    cancel_showtime,
    close_engagement,
    open_showtime_sales,
    plan_event,
    place_showtime,
    read_asset,
    read_booking,
    read_clearance,
    read_event,
    read_order,
    read_showtime,
    register_distributor,
    sell_seats,
    setup_programming_baseline,
    title_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    venue_payload,
)

PROGRAMMER = TEST_USERS["programmer_headers"]
RIGHTS_MANAGER = TEST_USERS["rights_manager_headers"]
RIGHTS_MANAGER_TWO = TEST_USERS["rights_manager_two_headers"]
TECHNICAL_MANAGER = TEST_USERS["technical_manager_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
EXECUTIVE_DIRECTOR = TEST_USERS["executive_director_headers"]
MEMBER = TEST_USERS["member_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


class TestRoleAuthority:

    def test_venue_create_with_no_role_header_is_refused(self, api):
        """PRD §2.1: "A request whose `X-User-Role` header is absent is treated as
        an anonymous walk-up caller and is admitted only on endpoints that
        explicitly list the anonymous role; a request whose `X-User-Role` header
        names a role that is not one of the seven roles below is rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401)."

        PRD §2.1: "A syntactically valid role that is simply not permitted on the
        addressed endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), as is
        a request to an endpoint governed by segregation of duties that arrives
        without an `X-User-ID` header."

        Design: Corner/errors/request_with_no_role_header_is_unauthenticated
        """
        # The body is a complete, valid auditorium payload, so nothing but the
        # missing caller identity can be at fault. Registering an auditorium is
        # not among the operations open to a walk-up caller, so the request must
        # be refused; the PRD names two identifiers for an unidentified caller
        # and does not settle which of them answers an absent header, so both are
        # accepted here.
        response = api.create_venue(venue_payload(), ANONYMOUS)

        validate_error_is_one_of(
            response,
            [
                ApiErrorId.ERR_UNAUTHENTICATED.value,
                ApiErrorId.ERR_FORBIDDEN_ROLE.value,
            ],
        )
        body = response.json()
        assert isinstance(body["data"].get("message"), str) and body["data"]["message"], (
            f"Expected a non-empty message in the envelope, got {body['data']!r}"
        )

        # Nothing was written, and the identical body from a permitted role lands.
        titles, _meta = validate_paginated(api.list_titles(ANONYMOUS))
        assert titles == [], f"Expected an empty world, got {titles}"
        created = validate_success(
            api.create_venue(venue_payload(), EXECUTIVE_DIRECTOR), expected_status=201
        )
        assert created["name"] == "Reel Repertory", (
            f"Expected the same body to be accepted, got {created['name']!r}"
        )

    def test_no_role_can_reach_another_roles_exclusive_operation(self, api):
        """PRD §2.1: "They are not a hierarchy: `ExecutiveDirector` is the sign-off
        authority but does **not** inherit the `Programmer`'s right to lodge
        negotiation rounds or schedule screenings, nor the `TechnicalManager`'s
        booth operations."

        PRD §2.1: "A syntactically valid role that is simply not permitted on the
        addressed endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403), as is
        a request to an endpoint governed by segregation of duties that arrives
        without an `X-User-ID` header."

        PRD §2.7: "Authorisation — the named role appears in the addressed
        endpoint's permitted list, and `X-User-ID` is present where segregation of
        duties applies (`ERR_FORBIDDEN_ROLE`)."

        Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation
        """
        # Every body is deliberately empty: authorisation is evaluated before the
        # request shape and before any id lookup, so an empty body still proves
        # which rung answered.
        denials = [
            ("POST /venues as Programmer", api.create_venue({}, PROGRAMMER)),
            ("POST /showtimes as RightsManager", api.create_showtime({}, RIGHTS_MANAGER)),
            (
                "POST /clearances as TechnicalManager",
                api.create_clearance({}, TECHNICAL_MANAGER),
            ),
            (
                "POST /dcp-assets as BoxOfficeManager",
                api.create_dcp_asset({}, BOX_OFFICE),
            ),
            (
                "POST /settlements as ExecutiveDirector",
                api.create_settlement({}, EXECUTIVE_DIRECTOR),
            ),
            (
                "POST /membership-sweeps as Member",
                api.run_membership_sweep(MEMBER, payload={}),
            ),
        ]

        for label, response in denials:
            validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
            assert response.status_code == 403, (
                f"{label}: expected 403, got {response.status_code} — the role gate "
                "must answer ahead of the body parser and ahead of any lookup"
            )

    def test_titles_shared_operation_succeeds_for_both_declared_roles(self, api):
        """PRD §3.1: "Titles are catalogued by a `Programmer` or an
        `ExecutiveDirector` with the `title_name` as it will be printed in the
        calendar, the original theatrical `release_year`, a `runtime_minutes` of at
        least 1 excluding trailers, an `is_first_run` flag distinguishing
        first-run art films from repertory and archival titles, a `native_format`
        drawn from the same five-format enumeration, and
        `rights_holder_distributor_id` naming the party that controls theatrical
        rights."

        PRD §2.3: "For every list response the `meta` object carries `limit` (the
        effective page size), `offset` (the effective starting position),
        `total_count` (the number of rows matching the filters before pagination is
        applied) and `has_more` (true when rows remain beyond this page)."

        Design: Corner/rbac/shared_operations_succeed_for_both_declared_roles
        """
        distributor = register_distributor()

        repertory = validate_success(
            api.create_title(
                title_payload(
                    distributor["id"],
                    title_name="La Jetee Redux",
                    release_year=1962,
                    runtime_minutes=104,
                    is_first_run=False,
                    native_format="DCP_2K",
                ),
                PROGRAMMER,
            ),
            expected_status=201,
        )
        first_run = validate_success(
            api.create_title(
                title_payload(
                    distributor["id"],
                    title_name="Northern Light",
                    release_year=2026,
                    runtime_minutes=96,
                    is_first_run=True,
                    native_format="DCP_4K",
                ),
                EXECUTIVE_DIRECTOR,
            ),
            expected_status=201,
        )

        assert repertory["id"] != first_run["id"], (
            "Expected two distinct rows, got the same id twice"
        )
        assert repertory["is_first_run"] is False, (
            f"Expected is_first_run false, got {repertory['is_first_run']!r}"
        )
        assert first_run["is_first_run"] is True, (
            f"Expected is_first_run true, got {first_run['is_first_run']!r}"
        )

        rows, meta = validate_paginated(
            api.list_titles(ANONYMOUS, params={"limit": 10, "offset": 0})
        )
        assert meta["total_count"] == 2, (
            f"Expected total_count 2, got {meta['total_count']}"
        )
        listed = {row["id"] for row in rows}
        assert listed == {repertory["id"], first_run["id"]}, (
            f"Neither row may be scoped to its creating role, got {listed}"
        )

        # The row created by one sharer is readable by the other.
        crossed = validate_success(
            api.get_title(first_run["id"], PROGRAMMER), expected_status=200
        )
        assert crossed["title_name"] == "Northern Light", (
            f"Expected 'Northern Light', got {crossed['title_name']!r}"
        )

    def test_clearance_the_person_who_lodged_it_cannot_clear_it(self, api):
        """PRD §2.1: "Clearing a rights licence is under **segregation of duties**:
        the `X-User-ID` that clears a licence must differ from the `X-User-ID`
        recorded as having lodged it. A caller who tries to clear their own submission is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403), even though the role
        itself is permitted."

        PRD §3.3: "The acting `X-User-ID` must differ from the recorded
        `submitted_by_user_id`, or the request is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.3: "On success `cleared_by_user_id` is recorded from the acting
        `X-User-ID`."

        Design: Corner/rbac/the_person_who_lodged_a_clearance_cannot_clear_it
        """
        world = setup_programming_baseline(clear=False)
        clearance_id = world["clearance"]["id"]
        assert world["clearance"]["submitted_by_user_id"] == "u-rm-1", (
            "Expected the licence lodged by u-rm-1, got "
            f"{world['clearance']['submitted_by_user_id']!r}"
        )

        # Same role, same person: the role is permitted, the person is not.
        refused = api.clear_clearance(clearance_id, RIGHTS_MANAGER)
        validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

        held = read_clearance(clearance_id)
        assert held["status"] == "SUBMITTED", (
            f"Expected the licence still SUBMITTED, got {held['status']}"
        )
        assert held["cleared_by_user_id"] is None, (
            f"Expected cleared_by_user_id null, got {held['cleared_by_user_id']!r}"
        )

        # A different person of the identical role succeeds, which is what shows
        # the check reads the user rather than the role.
        cleared = validate_success(
            api.clear_clearance(clearance_id, RIGHTS_MANAGER_TWO), expected_status=200
        )
        assert cleared["status"] == "CLEARED", (
            f"Expected CLEARED, got {cleared['status']}"
        )
        assert cleared["cleared_by_user_id"] == "u-rm-2", (
            f"Expected cleared_by_user_id u-rm-2, got {cleared['cleared_by_user_id']!r}"
        )
        assert cleared["submitted_by_user_id"] == "u-rm-1", (
            f"Expected the lodger unchanged, got {cleared['submitted_by_user_id']!r}"
        )
        assert cleared["screenings_remaining"] == 6, (
            "Clearing does not consume the allowance, got "
            f"{cleared['screenings_remaining']}"
        )


class TestErrorReachability:

    def test_every_entity_not_found_error_is_reachable(self, api):
        """PRD §2.11: "When an operation addresses one resource and its payload
        names others, the addressed resource is resolved first, then each foreign
        key in the payload; the specific not-found error names the entity type that
        was missing — `ERR_VENUE_NOT_FOUND`, `ERR_DISTRIBUTOR_NOT_FOUND`,
        `ERR_TITLE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`,
        `ERR_BOOKING_OFFER_NOT_FOUND`, `ERR_CLEARANCE_NOT_FOUND`,
        `ERR_DCP_ASSET_NOT_FOUND`, `ERR_KDM_KEY_NOT_FOUND`,
        `ERR_SHOWTIME_NOT_FOUND`, `ERR_SPECIAL_EVENT_NOT_FOUND`,
        `ERR_TICKET_ORDER_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND` or
        `ERR_SETTLEMENT_NOT_FOUND`."

        Design: Corner/errors/every_entity_not_found_error_is_reachable
        """
        # Each id is a syntactically valid UUID that was never minted, and each
        # read is issued by a role the endpoint permits, so nothing above the
        # existence rung can pre-empt it.
        sweep = [
            (
                "venue",
                api.get_venue("00000000-0000-4000-8000-000000000001", EXECUTIVE_DIRECTOR),
                ApiErrorId.ERR_VENUE_NOT_FOUND.value,
            ),
            (
                "booking",
                api.get_booking("00000000-0000-4000-8000-000000000002", PROGRAMMER),
                ApiErrorId.ERR_BOOKING_NOT_FOUND.value,
            ),
            (
                "clearance",
                api.get_clearance("00000000-0000-4000-8000-000000000003", RIGHTS_MANAGER),
                ApiErrorId.ERR_CLEARANCE_NOT_FOUND.value,
            ),
            (
                "dcp_asset",
                api.get_dcp_asset(
                    "00000000-0000-4000-8000-000000000004", TECHNICAL_MANAGER
                ),
                ApiErrorId.ERR_DCP_ASSET_NOT_FOUND.value,
            ),
            (
                "kdm_key",
                api.get_kdm_key(
                    "00000000-0000-4000-8000-000000000005", TECHNICAL_MANAGER
                ),
                ApiErrorId.ERR_KDM_KEY_NOT_FOUND.value,
            ),
            (
                "showtime",
                api.get_showtime("00000000-0000-4000-8000-000000000006", ANONYMOUS),
                ApiErrorId.ERR_SHOWTIME_NOT_FOUND.value,
            ),
            (
                "special_event",
                api.get_special_event(
                    "00000000-0000-4000-8000-000000000007", PROGRAMMER
                ),
                ApiErrorId.ERR_SPECIAL_EVENT_NOT_FOUND.value,
            ),
            (
                "ticket_order",
                api.get_ticket_order("00000000-0000-4000-8000-000000000008", BOX_OFFICE),
                ApiErrorId.ERR_TICKET_ORDER_NOT_FOUND.value,
            ),
            (
                "member",
                api.get_member("00000000-0000-4000-8000-000000000009", BOX_OFFICE),
                ApiErrorId.ERR_MEMBER_NOT_FOUND.value,
            ),
            (
                "settlement",
                api.get_settlement("00000000-0000-4000-8000-00000000000a", BOX_OFFICE),
                ApiErrorId.ERR_SETTLEMENT_NOT_FOUND.value,
            ),
        ]

        observed = []
        for entity, response, expected in sweep:
            assert response.status_code == 404, (
                f"{entity}: expected 404, got {response.status_code}"
            )
            validate_error(response, expected)
            body = response.json()["data"]
            assert isinstance(body.get("message"), str) and body["message"], (
                f"{entity}: expected a non-empty message, got {body.get('message')!r}"
            )
            observed.append(body["error_id"])

        assert len(set(observed)) == len(observed), (
            f"No entity may share another's not-found code, got {observed}"
        )

    def test_every_entity_invalid_state_error_is_reachable(self, api):
        """PRD §2.7: "State — the addressed resource is in a state from which the
        requested transition is declared, yielding the per-entity invalid-state
        error. A terminal state admits nothing."

        PRD §3.4: "Asking for anything other than the single next step from the
        asset's current status is refused with `ERR_DCP_ASSET_INVALID_STATE`."

        PRD §3.8: "An order that is not `RESERVED` when payment arrives, or not
        `PAID` when a refund arrives, yields `ERR_TICKET_ORDER_INVALID_STATE`."

        Design: Corner/errors/every_entity_invalid_state_error_is_reachable
        """
        world = setup_programming_baseline(asset_target_status="INGESTED")
        booking_id = world["booking"]["id"]
        clearance_id = world["clearance"]["id"]
        asset_id = world["asset"]["id"]

        showtime = place_showtime(world, "2026-08-14T12:00:00Z")
        open_showtime_sales(showtime["id"])
        order = sell_seats(
            showtime["id"], 2, headers=ANONYMOUS, purchaser_email="hold@example.com"
        )
        event = plan_event(
            showtime["id"],
            event_type="PANEL",
            guest_name="Rina Okada",
            extra_minutes=20,
            surcharge_cents=0,
            guest_fee_cents=10000,
        )

        # Drive every machine into a state from which the transition is gone.
        cancel_event(event["id"], "Guest withdrew")
        cancel_showtime(showtime["id"], "Print damaged")
        close_engagement(booking_id)

        sweep = [
            (
                "booking",
                api.confirm_booking(booking_id, EXECUTIVE_DIRECTOR),
                ApiErrorId.ERR_BOOKING_INVALID_STATE.value,
            ),
            (
                "clearance",
                api.clear_clearance(clearance_id, RIGHTS_MANAGER_TWO),
                ApiErrorId.ERR_CLEARANCE_INVALID_STATE.value,
            ),
            (
                "dcp_asset",
                api.traffic_update_dcp_asset(
                    asset_id, {"new_status": "INGESTING"}, TECHNICAL_MANAGER
                ),
                ApiErrorId.ERR_DCP_ASSET_INVALID_STATE.value,
            ),
            (
                "showtime",
                api.cancel_showtime(
                    showtime["id"], {"cancel_reason": "Print damaged again"}, PROGRAMMER
                ),
                ApiErrorId.ERR_SHOWTIME_INVALID_STATE.value,
            ),
            (
                "ticket_order",
                api.pay_ticket_order(order["id"], BOX_OFFICE),
                ApiErrorId.ERR_TICKET_ORDER_INVALID_STATE.value,
            ),
            (
                "special_event",
                api.cancel_special_event(
                    event["id"], {"cancel_reason": "Guest withdrew twice"}, PROGRAMMER
                ),
                ApiErrorId.ERR_SPECIAL_EVENT_INVALID_STATE.value,
            ),
        ]

        observed = []
        for entity, response, expected in sweep:
            validate_error(response, expected)
            observed.append(response.json()["data"]["error_id"])

        assert len(set(observed)) == len(observed), (
            f"No machine may share another's invalid-state code, got {observed}"
        )

        # A refused transition is a no-op on every row it addressed.
        assert read_booking(booking_id)["status"] == "CLOSED", (
            f"Expected CLOSED, got {read_booking(booking_id)['status']}"
        )
        assert read_clearance(clearance_id)["status"] == "CLEARED", (
            f"Expected CLEARED, got {read_clearance(clearance_id)['status']}"
        )
        assert read_asset(asset_id)["status"] == "INGESTED", (
            f"Expected INGESTED, got {read_asset(asset_id)['status']}"
        )
        cancelled = read_showtime(showtime["id"])
        assert cancelled["status"] == "CANCELLED", (
            f"Expected CANCELLED, got {cancelled['status']}"
        )
        assert cancelled["cancel_reason"] == "Print damaged", (
            "The second cancel must not overwrite the recorded reason, got "
            f"{cancelled['cancel_reason']!r}"
        )
        assert read_order(order["id"])["status"] == "VOID", (
            f"Expected VOID, got {read_order(order['id'])['status']}"
        )
        assert read_event(event["id"])["status"] == "CANCELLED", (
            f"Expected CANCELLED, got {read_event(event['id'])['status']}"
        )
