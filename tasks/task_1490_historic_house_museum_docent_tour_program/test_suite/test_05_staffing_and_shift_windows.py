"""Shift staffing gates, the thirty-minute double-booking buffer, and the
validation precedence between qualification and overlap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_route,
    api_client,
    assign_and_confirm_lead,
    assign_shift,
    confirm_shift,
    create_certified_docent,
    create_route,
    create_rooms,
    create_script,
    create_slot,
    decline_shift,
    get_slot,
    make_docent_headers,
    open_slot,
    setup_active_route_no_script,
    setup_staffed_scheduled_slot,
    submit_script,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["museum_admin_headers"]
COORDINATOR = TEST_USERS["docent_coordinator_headers"]
CURATOR = TEST_USERS["curator_headers"]


def _two_routes():
    """Two ACTIVE single-room routes (Parlor downstairs, Library upstairs)."""
    rooms = create_rooms([
        {"name": "Parlor", "floor": 1, "capacity_max": 20,
         "safety_max_party": 12, "collection_tier": "STANDARD"},
        {"name": "Library", "floor": 2, "capacity_max": 15,
         "safety_max_party": 10, "collection_tier": "STANDARD"},
    ])
    route1 = create_route([rooms[0]["id"]], name="Main Floor")
    route2 = create_route([rooms[1]["id"]], name="Library Tour")
    route1 = activate_route(route1["id"])
    route2 = activate_route(route2["id"])
    return rooms, route1, route2


class TestShiftBufferOverlap:
    """A docent's existing slot window is padded by thirty minutes; a
    candidate touching the padded edge passes, one minute inside fails."""

    def test_exactly_thirty_minute_gap_is_allowed(self):
        """PRD section 3.4: "The double-booking guard rejects any assignment
        where the docent already holds a non-terminal shift whose slot
        window, padded by a thirty-minute buffer, conflicts with the
        candidate slot's window; the rejection is `ERR_SHIFT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/docent_shift_buffer_overlap
        """
        _rooms, route1, route2 = _two_routes()
        docent = create_certified_docent([route1["id"], route2["id"]])
        slot1 = create_slot(route1["id"], start_at="2026-09-01T10:00:00Z")
        slot2 = create_slot(route1["id"], start_at="2026-09-01T11:30:00Z")
        assign_and_confirm_lead(docent["id"], slot1["id"])
        # slot1 runs 10:00-11:00; padded edge is 11:30. slot2 starts exactly
        # at 11:30 — a 30-minute gap satisfies the buffer.
        resp = api_client.create_shift_assignment(
            {"docent_id": docent["id"], "slot_id": slot2["id"],
             "shift_role": "LEAD"},
            COORDINATOR)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "ASSIGNED", (
            f"an exactly 30-minute gap must satisfy the buffer, "
            f"got {data['status']}"
        )

    def test_twenty_minute_gap_rejected_shift_overlap(self):
        """PRD section 3.4: "The double-booking guard rejects any assignment
        where the docent already holds a non-terminal shift whose slot
        window, padded by a thirty-minute buffer, conflicts with the
        candidate slot's window; the rejection is `ERR_SHIFT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/docent_shift_buffer_overlap
        """
        _rooms, route1, route2 = _two_routes()
        docent = create_certified_docent([route1["id"], route2["id"]])
        slot1 = create_slot(route1["id"], start_at="2026-09-01T10:00:00Z")
        slot3 = create_slot(route2["id"], start_at="2026-09-01T11:20:00Z")
        assign_and_confirm_lead(docent["id"], slot1["id"])
        # 11:20 is inside the padded window [10:00, 11:30).
        resp = api_client.create_shift_assignment(
            {"docent_id": docent["id"], "slot_id": slot3["id"],
             "shift_role": "LEAD"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestQualificationBeforeOverlap:
    """When an assignment violates both qualification (tier 9) and the
    overlap buffer (tier 10), the earlier tier wins."""

    def test_unqualified_overlapping_shift_returns_not_qualified(self):
        """PRD section 2.9: "Every request passes through an ordered gauntlet
        of checks, and a failure at any tier short-circuits all later tiers —
        the error surfaced is always the earliest applicable one, never a
        later mask."
        PRD section 2.9, tier 9: "shift assignment checks docent
        qualification (`ERR_DOCENT_NOT_QUALIFIED`)"; tier 10: "docent shift
        windows must not collide under the buffer rule (`ERR_SHIFT_OVERLAP`)".
        PRD section 3.4: "a `LEAD` must be `CERTIFIED` with that route
        present in `certified_route_ids`, while a `SHADOW` need only be
        `TRAINEE` or `CERTIFIED`; an unqualified assignment is rejected with
        `ERR_DOCENT_NOT_QUALIFIED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/unqualified_overlapping_shift_returns_not_qualified
        """
        _rooms, route1, route2 = _two_routes()
        d1 = create_certified_docent([route1["id"]], email="dee@x.org")
        d2 = create_certified_docent([route1["id"]], full_name="Pat Guide",
                                     email="pat@x.org")
        slot1 = create_slot(route1["id"], start_at="2026-09-01T10:00:00Z")
        slot2 = create_slot(route2["id"], start_at="2026-09-01T10:30:00Z")
        assign_and_confirm_lead(d1["id"], slot1["id"])
        shadow = assign_shift(d2["id"], slot1["id"], "SHADOW")
        confirm_shift(shadow["id"], d2["id"])
        # d2 is not certified on route2 AND 10:30 falls inside the buffered
        # window of slot1 (ends 11:00 + 30 min). Tier 9 fires first.
        resp = api_client.create_shift_assignment(
            {"docent_id": d2["id"], "slot_id": slot2["id"],
             "shift_role": "LEAD"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_DOCENT_NOT_QUALIFIED)

    def test_qualified_overlapping_shift_returns_shift_overlap(self):
        """PRD section 2.9, tier 10: "docent shift windows must not collide
        under the buffer rule (`ERR_SHIFT_OVERLAP`)".
        PRD section 3.4: "The double-booking guard rejects any assignment
        where the docent already holds a non-terminal shift whose slot
        window, padded by a thirty-minute buffer, conflicts with the
        candidate slot's window; the rejection is `ERR_SHIFT_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/unqualified_overlapping_shift_returns_not_qualified
        """
        _rooms, route1, route2 = _two_routes()
        docent = create_certified_docent([route1["id"], route2["id"]])
        slot1 = create_slot(route1["id"], start_at="2026-09-01T10:00:00Z")
        slot2 = create_slot(route2["id"], start_at="2026-09-01T10:30:00Z")
        assign_and_confirm_lead(docent["id"], slot1["id"])
        # Fully qualified for route2 — only the buffer overlap can fire.
        resp = api_client.create_shift_assignment(
            {"docent_id": docent["id"], "slot_id": slot2["id"],
             "shift_role": "LEAD"},
            COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestSlotOpenScriptGate:

    def test_open_rejected_while_script_in_review(self):
        """PRD section 3.4: "Opening a slot is a `MuseumAdmin` action guarded
        by four gates, each with its own error: the route must be `ACTIVE`
        (`ERR_ROUTE_NOT_ACTIVE`), the route must have a published script —
        `published_script_id` non-null (`ERR_SCRIPT_NOT_PUBLISHED`,
        HTTP 409), every room on the route must be `OPEN` (`ERR_ROOM_CLOSED`,
        HTTP 409), and the slot must be `STAFFED` with a confirmed lead
        (`ERR_SLOT_NOT_STAFFED`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/slot_open_requires_published_script
        """
        room = create_rooms([{"name": "Parlor", "floor": 1, "capacity_max": 20,
                              "safety_max_party": 12,
                              "collection_tier": "STANDARD"}])[0]
        route = create_route([room["id"]])
        # Script is drafted and submitted but never approved/published.
        script = create_script(route["id"],
                               content_text="Script under review")
        submit_script(script["id"])
        activate_route(route["id"])
        docent = create_certified_docent([route["id"]])
        slot = create_slot(route["id"])
        assign_and_confirm_lead(docent["id"], slot["id"])

        resp = api_client.open_tour_slot(slot["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SCRIPT_NOT_PUBLISHED)
        slot_after = get_slot(slot["id"])
        assert slot_after["status"] == "SCHEDULED", (
            f"a rejected open must leave the slot SCHEDULED, "
            f"got {slot_after['status']}"
        )

    def test_open_succeeds_once_script_published(self):
        """PRD section 3.4: "Passing all four moves the slot from `SCHEDULED`
        to `OPEN` and increments the slot's `version`."

        Design: Difficulty/cross_entity_state_dependency/slot_open_requires_published_script
        """
        ctx = setup_staffed_scheduled_slot()
        assert ctx["slot"]["status"] == "SCHEDULED"
        slot = open_slot(ctx["slot_id"])
        assert slot["status"] == "OPEN"
        assert slot["version"] == ctx["slot"]["version"] + 1, (
            f"opening must increment the slot's version, got "
            f"{slot['version']} after {ctx['slot']['version']}"
        )


class TestShiftTerminalStates:

    def test_shift_confirm_from_declined_rejected(self):
        """PRD section 3.4: "Confirming moves a shift from `ASSIGNED` to
        `CONFIRMED`, and declining moves it from `ASSIGNED` to `DECLINED`;
        both require the caller's `X-User-ID` to equal the shift's
        `docent_id`, else `ERR_FORBIDDEN`."
        PRD section 2.9, tier 5: "the target resource must be in a state that
        offers the requested transition; generic violations yield
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/shift_confirm_from_declined_rejected
        """
        ctx = setup_active_route_no_script()
        docent = create_certified_docent([ctx["route_id"]])
        slot = create_slot(ctx["route_id"])
        shift = assign_shift(docent["id"], slot["id"], "LEAD")
        decline_shift(shift["id"], docent["id"])
        resp = api_client.confirm_shift_assignment(
            shift["id"], make_docent_headers(docent["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
