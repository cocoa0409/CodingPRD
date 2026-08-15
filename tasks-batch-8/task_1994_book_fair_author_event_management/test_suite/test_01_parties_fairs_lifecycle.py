"""Parties, fair creation, listing/pagination, and lifecycle state transitions."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_party_payload,
    create_fair_payload,
    create_venue_slot_payload,
    make_school,
    make_fair,
    make_confirmed_venue_slot,
    make_fair_scheduled,
    make_school_coordinator_headers,
    TEST_USERS,
)

ORG = TEST_USERS["organizer_headers"]


class TestPartyCreateRead:
    def test_party_create_read_system_fields(self, api):
        """PRD §3.1: "each `Party` is created with a `kind` — exactly one of
        `SCHOOL`, `PUBLISHER`, or `AUTHOR`, immutable after creation — plus a
        display `name` and a `contact_email`."
        PRD §2.4: "Every persisted resource carries an `id` that is a
        server-minted UUID with no type prefix, a `created_at` timestamp, and —
        with one exception — an `updated_at` timestamp and a `version` integer."

        Design: Corner/entities/party_create_read_system_fields
        """
        resp = api.create_party(
            create_party_payload(kind="SCHOOL", name="Ridgeview Elementary",
                                 contact_email="pta@ridgeview.example"),
            ORG,
        )
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1
        assert data["id"]
        assert data["created_at"]

        got = validate_success(api.get_party(data["id"], ORG))
        assert got["name"] == "Ridgeview Elementary"
        assert got["kind"] == "SCHOOL"

    def test_party_invalid_kind_rejected(self, api):
        """PRD §3.1: "each `Party` is created with a `kind` — exactly one of
        `SCHOOL`, `PUBLISHER`, or `AUTHOR`, immutable after creation"
        PRD §2.9: "Request-shape validation (priority 7, `ERR_VALIDATION`, HTTP
        400) rejects missing required fields, wrong types, invalid enum values,
        out-of-range numbers ... and any unknown field."

        Design: Corner/entities/party_invalid_kind_rejected
        """
        resp = api.create_party(
            {"kind": "DISTRIBUTOR", "name": "Bad Kind", "contact_email": "x@example.com"},
            ORG,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_party_create_requires_organizer_role(self, api):
        """PRD §4 (routing summary row for POST /parties): "Register a school,
        publisher, or author party | Organizer".
        PRD §2.1: "If the named role is not in the endpoint's authorized role
        list, the request is rejected with `ERR_ROLE_FORBIDDEN` (HTTP 403)."

        Design: Corner/entities/party_create_read_system_fields
        """
        resp = api.create_party(create_party_payload(), TEST_USERS["cashier_headers"])
        validate_error(resp, ApiErrorId.ERR_ROLE_FORBIDDEN)


class TestFairLifecycle:
    def test_fair_missing_venue_key_rejected(self, api):
        """PRD §3.1: "the organizer creates the `Fair` itself, supplying
        `school_party_id` ... a `title`, the `venue_key` identifying the shared
        venue calendar, `planned_start_date` and `planned_end_date` as ISO dates
        ... and the `promo_budget_cents` ceiling on approved media spend"
        PRD §2.9: "Request-shape validation (priority 7, `ERR_VALIDATION`, HTTP
        400) rejects missing required fields ..."

        Design: Corner/entities/fair_missing_venue_key_rejected
        """
        school = make_school()
        payload = {
            "school_party_id": school["id"],
            "title": "Fall Fair",
            "planned_start_date": "2026-08-10",
            "planned_end_date": "2026-08-14",
            "signing_floor_capacity_units": 20,
            "promo_budget_cents": 0,
        }
        resp = api.create_fair(payload, ORG)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_fair_read_nonexistent_returns_not_found(self, api):
        """PRD §2.9: "then resource existence, with path resources resolved left
        to right and the first missing path or body reference yielding
        `ERR_NOT_FOUND` (HTTP 404, priority 5)"

        Design: Corner/entities/fair_read_nonexistent_returns_not_found
        """
        resp = api.get_fair(NON_EXISTENT_UUID, ORG)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`,
        `total_count`, and `has_more` in its `meta` object."
        PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not
        exceed 100. The `offset` defaults to 0."

        Design: Corner/entities/list_pagination_envelope
        """
        school = make_school()
        for title, start, end in (
            ("Fair A", "2026-08-10", "2026-08-14"),
            ("Fair B", "2026-08-17", "2026-08-21"),
            ("Fair C", "2026-08-24", "2026-08-28"),
        ):
            make_fair(school["id"], title=title,
                      planned_start_date=start, planned_end_date=end)
        resp = api.list_fairs(ORG, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_fair_schedule_twice_invalid(self, api):
        """PRD §3.1: "Scheduling the fair moves it `DRAFT` → `SCHEDULED` and
        requires at least one of the fair's venue slots to be `CONFIRMED`.
        Attempting any lifecycle action from a state that does not offer it is
        rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/fair_schedule_twice_invalid
        """
        school = make_school()
        fair = make_fair_scheduled(school["id"])
        resp = api.schedule_fair(fair["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        still = validate_success(api.get_fair(fair["id"], ORG))
        assert still["status"] == "SCHEDULED"

    def test_fair_schedule_requires_confirmed_slot(self, api):
        """PRD §3.1: "Scheduling the fair moves it `DRAFT` → `SCHEDULED` and
        requires at least one of the fair's venue slots to be `CONFIRMED`."

        Design: Corner/state_machines/fair_schedule_twice_invalid
        """
        school = make_school()
        fair = make_fair(school["id"])
        # Slot exists but never confirmed
        slot_resp = api.create_venue_slot(
            create_venue_slot_payload(fair_id=fair["id"]), ORG
        )
        validate_success(slot_resp, expected_status=201)
        resp = api.schedule_fair(fair["id"], ORG)
        # With no CONFIRMED slot, the transition is not offered from DRAFT.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_fair_cancelled_terminal_lockdown(self, api):
        """PRD §3.1: "An organizer may cancel a fair from `DRAFT`, `SCHEDULED`,
        `STOCKING`, or `OPEN` ... The fair ends `CANCELLED`, a terminal state."
        PRD §3.1: "Attempting any lifecycle action from a state that does not
        offer it is rejected with `ERR_INVALID_STATE` (HTTP 409) — the same
        response an actor gets when poking at an entity in a terminal state."

        Design: Corner/state_machines/fair_cancelled_terminal_lockdown
        """
        school = make_school()
        fair = make_fair(school["id"])
        validate_success(api.cancel_fair(fair["id"], ORG, {"reason": "district freeze"}))
        resp = api.schedule_fair(fair["id"], ORG)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_slot_release_then_confirm_invalid(self, api):
        """PRD §3.1: "An organizer may release a slot from either `HELD` or
        `CONFIRMED`, moving it to `RELEASED`; a released slot stops constraining
        the venue calendar."
        PRD §3.1: "Attempting any lifecycle action from a state that does not
        offer it is rejected with `ERR_INVALID_STATE` (HTTP 409)"

        Design: Corner/state_machines/slot_release_then_confirm_invalid
        """
        school = make_school()
        fair = make_fair(school["id"])
        slot = validate_success(api.create_venue_slot(
            create_venue_slot_payload(fair_id=fair["id"]), ORG
        ), expected_status=201)
        validate_success(api.release_venue_slot(slot["id"], ORG))
        resp = api.confirm_venue_slot(
            slot["id"], make_school_coordinator_headers(school["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestVenueSlotOverlap:
    def test_venue_slot_buffered_half_open_overlap(self, api):
        """PRD §2.8: "A `VenueSlot` occupies the venue calendar over the
        half-open interval that begins `setup_buffer_minutes` before its
        `start_at` and ends `teardown_buffer_minutes` after its `end_at`,
        exclusive of the final instant. Creating a slot is rejected with
        `ERR_VENUE_CONFLICT` (HTTP 409) when that effective buffered interval
        intersects the effective interval of any non-`RELEASED` slot sharing the
        same `venue_key`. Because the intervals are half-open, one block ending
        at exactly the instant another begins — buffers included — is not a
        conflict."

        Design: Difficulty/resource_temporal_overlap/venue_slot_buffered_half_open_overlap
        """
        school = make_school()
        fair = make_fair(school["id"])
        # slot1 effective [09:30, 12:30)
        slot1 = validate_success(api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"], purpose="FAIR_DAY",
                start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T12:00:00Z",
                setup_buffer_minutes=30, teardown_buffer_minutes=30,
            ), ORG,
        ), expected_status=201)

        # slot2 effective [12:30, 14:00): adjacency at 12:30 — allowed
        resp2 = api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"], purpose="AUTHOR_EVENT",
                start_at="2026-08-10T12:30:00Z", end_at="2026-08-10T14:00:00Z",
                setup_buffer_minutes=0, teardown_buffer_minutes=0,
            ), ORG,
        )
        slot2 = validate_success(resp2, expected_status=201)
        assert slot2["status"] == "HELD"

        # slot3 effective [12:15, 13:00): strict interior intersection — conflict
        resp3 = api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"], purpose="AUTHOR_EVENT",
                start_at="2026-08-10T12:15:00Z", end_at="2026-08-10T13:00:00Z",
                setup_buffer_minutes=0, teardown_buffer_minutes=0,
            ), ORG,
        )
        validate_error(resp3, ApiErrorId.ERR_VENUE_CONFLICT)

        # slot4 effective [12:15, 13:30) — own 15-min setup buffer extends occupancy
        resp4 = api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"], purpose="SETUP",
                start_at="2026-08-10T12:30:00Z", end_at="2026-08-10T13:30:00Z",
                setup_buffer_minutes=15, teardown_buffer_minutes=0,
            ), ORG,
        )
        validate_error(resp4, ApiErrorId.ERR_VENUE_CONFLICT)

        # slot1 undisturbed
        slot1_after = validate_success(api.get_venue_slot(slot1["id"], ORG))
        assert slot1_after["status"] == "HELD"

    def test_venue_slot_released_slot_no_longer_conflicts(self, api):
        """PRD §2.8: "Creating a slot is rejected with `ERR_VENUE_CONFLICT`
        (HTTP 409) when that effective buffered interval intersects the
        effective interval of any non-`RELEASED` slot sharing the same
        `venue_key`."
        PRD §3.1: "An organizer may release a slot from either `HELD` or
        `CONFIRMED`, moving it to `RELEASED`; a released slot stops constraining
        the venue calendar."

        Design: Difficulty/resource_temporal_overlap/venue_slot_buffered_half_open_overlap
        """
        school = make_school()
        fair = make_fair(school["id"])
        slot1 = validate_success(api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"],
                start_at="2026-08-10T10:00:00Z", end_at="2026-08-10T12:00:00Z",
                setup_buffer_minutes=30, teardown_buffer_minutes=30,
            ), ORG,
        ), expected_status=201)
        validate_success(api.release_venue_slot(slot1["id"], ORG))
        # Now an overlapping slot is accepted because slot1 is RELEASED
        resp = api.create_venue_slot(
            create_venue_slot_payload(
                fair_id=fair["id"],
                start_at="2026-08-10T11:00:00Z", end_at="2026-08-10T13:00:00Z",
                setup_buffer_minutes=0, teardown_buffer_minutes=0,
            ), ORG,
        )
        validate_success(resp, expected_status=201)
