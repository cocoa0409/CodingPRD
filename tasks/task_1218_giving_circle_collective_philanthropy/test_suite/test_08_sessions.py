"""Learning sessions: the strict capacity boundary, the fifteen-minute
calendar buffer, RSVP uniqueness, and the error envelope shape
(PRD §2.2, §2.10, §3.5).
"""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_active_member,
    create_circle_and_cycle,
    create_session,
    get_success_data,
    make_member_headers,
    rsvp,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _setup_session_ctx(api, name, capacity):
    """Circle + DRAFT cycle + three ACTIVE members + one session (PRD §3.5)."""
    ctx = create_circle_and_cycle(name)
    for _ in range(3):
        add_active_member(ctx)
    session = create_session(
        ctx["cycle"]["id"],
        "Grantmaking 101",
        "2026-06-10T10:00:00Z",
        "2026-06-10T11:00:00Z",
        capacity,
    )
    return ctx, session


class TestSessionCapacity:
    def test_session_full_at_capacity_rejects(self, api):
        """PRD §3.5: "Two failures guard the seat count: a membership already
        present in `rsvp_membership_ids` fails with `ERR_ALREADY_RSVPED`, and a
        session whose `seats_taken` has reached its `capacity` is full — the
        boundary is a strict less-than, so the reservation that would equalize
        the two fails with `ERR_SESSION_FULL`."

        Design: Difficulty/boundary_precision_check/session_full_at_capacity_rejects
        """
        ctx, session = _setup_session_ctx(api, "Circle BP2", capacity=2)
        rsvp(session["id"], ctx["memberships"][0]["id"], ctx["members"][0]["id"])
        rsvp(session["id"], ctx["memberships"][1]["id"], ctx["members"][1]["id"])
        resp = api.rsvp_session(
            session["id"],
            {"membership_id": ctx["memberships"][2]["id"]},
            make_member_headers(ctx["members"][2]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        after = get_success_data(api.get_learning_session(session["id"], ADMIN))
        assert after["seats_taken"] == 2, "the rejected RSVP must not move the counter"

    def test_rsvp_below_capacity_increments_seats(self, api):
        """PRD §3.5: "An active member reserves a seat by presenting their
        `membership_id`; the membership must belong to the acting member and
        be `ACTIVE` (`ERR_MEMBERSHIP_NOT_ACTIVE`)."
        PRD §3.5: "A successful reservation increments `seats_taken` by one and
        appends the membership to `rsvp_membership_ids`."

        The passing side of the strict-less-than boundary: seats 0 -> 1 -> 2
        with capacity 2.

        Design: Difficulty/boundary_precision_check/session_full_at_capacity_rejects
        """
        ctx, session = _setup_session_ctx(api, "Circle BP2B", capacity=2)
        first = rsvp(session["id"], ctx["memberships"][0]["id"], ctx["members"][0]["id"])
        assert first["seats_taken"] == 1
        assert ctx["memberships"][0]["id"] in first["rsvp_membership_ids"]
        second = rsvp(session["id"], ctx["memberships"][1]["id"], ctx["members"][1]["id"])
        assert second["seats_taken"] == 2
        assert len(second["rsvp_membership_ids"]) == 2


class TestSessionCalendarBuffer:
    def test_session_buffer_gap_below_15_rejected(self, api):
        """PRD §2.10: "Learning sessions within one cycle's calendar require a
        fifteen-minute buffer: a new session must leave at least fifteen
        minutes between its window and the window of every other `SCHEDULED`
        session in the same cycle, in either direction. A violation is rejected
        with `ERR_SESSION_OVERLAP_BUFFER` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/learning_session_buffer_gap
        """
        ctx = create_circle_and_cycle("Circle TO2")
        create_session(
            ctx["cycle"]["id"], "S1",
            "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z", 10,
        )
        resp = api.create_learning_session(
            {
                "cycle_id": ctx["cycle"]["id"],
                "title": "S2 too close",
                "starts_at": "2026-06-10T11:10:00Z",
                "ends_at": "2026-06-10T12:00:00Z",
                "capacity": 10,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP_BUFFER)

    def test_session_buffer_exactly_15_accepted(self, api):
        """PRD §2.10: "Learning sessions within one cycle's calendar require a
        fifteen-minute buffer: a new session must leave at least fifteen
        minutes between its window and the window of every other `SCHEDULED`
        session in the same cycle, in either direction. A violation is rejected
        with `ERR_SESSION_OVERLAP_BUFFER` (HTTP 409)."

        A gap of exactly fifteen minutes satisfies "at least fifteen minutes".

        Design: Difficulty/resource_temporal_overlap/learning_session_buffer_gap
        """
        ctx = create_circle_and_cycle("Circle TO2B")
        create_session(
            ctx["cycle"]["id"], "S1",
            "2026-06-10T10:00:00Z", "2026-06-10T11:00:00Z", 10,
        )
        accepted = validate_success(
            api.create_learning_session(
                {
                    "cycle_id": ctx["cycle"]["id"],
                    "title": "S3 exact buffer",
                    "starts_at": "2026-06-10T11:15:00Z",
                    "ends_at": "2026-06-10T12:00:00Z",
                    "capacity": 10,
                },
                ADMIN,
            ),
            expected_status=201,
        )
        assert accepted["status"] == "SCHEDULED"
        _data, meta = validate_paginated(
            api.list_learning_sessions(
                ADMIN, params={"cycle_id": ctx["cycle"]["id"], "status": "SCHEDULED"}
            )
        )
        assert meta["total_count"] == 2


class TestErrorEnvelope:
    def test_error_envelope_shape_on_validation_failure(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §3.5: "Two failures guard the seat count: a membership already
        present in `rsvp_membership_ids` fails with `ERR_ALREADY_RSVPED`, and a
        session whose `seats_taken` has reached its `capacity` is full — the
        boundary is a strict less-than, so the reservation that would equalize
        the two fails with `ERR_SESSION_FULL`."

        Design: Corner/endpoints/error_envelope_shape_on_validation_failure
        """
        ctx, session = _setup_session_ctx(api, "Circle EP3", capacity=5)
        rsvp(session["id"], ctx["memberships"][0]["id"], ctx["members"][0]["id"])
        resp = api.rsvp_session(
            session["id"],
            {"membership_id": ctx["memberships"][0]["id"]},
            make_member_headers(ctx["members"][0]["id"]),
        )
        assert resp.status_code == 409
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_ per PRD §2.2"
        )
        assert body["data"]["error_id"] == "ERR_ALREADY_RSVPED"

        after = get_success_data(api.get_learning_session(session["id"], ADMIN))
        assert after["seats_taken"] == 1
