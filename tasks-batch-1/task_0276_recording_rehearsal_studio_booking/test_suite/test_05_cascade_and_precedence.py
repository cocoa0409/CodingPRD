"""Transitive lockout cascades and validation-precedence conflicts (Difficulty rules 4, 5).

Covers the depth-3 lockout-terminate cascade and the two ordered-priority error pairs
(state vs room-overlap, ownership vs state).
"""
from test_helpers import (
    setup_studio_room_client,
    setup_engineer,
    create_booking,
    pay_deposit,
    confirm,
    create_lockout_contract,
    activate_lockout_contract,
    list_series_occurrences,
    assign_engineer,
    get_room,
    get_booking,
    get_engineer_assignment,
    setup_client,
    api_client,
    TEST_USERS,
    make_client_headers,
    get_success_data,
    validate_error,
)

SM = TEST_USERS["studio_manager_headers"]


# =====================================================================
# Difficulty rule 4 — transitive_cascade:
#   lockout_terminate_cascades_to_occurrence_to_assignment_release
# =====================================================================
class TestLockoutTerminateCascade:
    """terminate -> each future occurrence CONFIRMED->CANCELLED -> that booking's
    EngineerAssignment ASSIGNED->RELEASED."""

    def _setup_active_with_assignment(self):
        studio, room, client = setup_studio_room_client(room_overrides={
            "hourly_rate_cents": 6000, "block_rate_cents": 40000, "block_hours": 8})
        engineer = setup_engineer(studio["id"], full_name="Sam", tier="STAFF",
                                  hourly_rate_cents=8000)
        room_v = room["version"]
        contract = create_lockout_contract(
            studio, room, client,
            weekday_mask=[1, 3], daily_start_local="18:00", daily_end_local="22:00",
            window_start_date="2026-07-06T00:00:00Z", window_end_date="2026-07-08T00:00:00Z")
        activated = activate_lockout_contract(contract, room_v)
        occurrences = list_series_occurrences(contract["id"])
        occ1 = occurrences[0]
        assignment = assign_engineer(occ1, engineer)
        return studio, room, client, engineer, contract, occ1, assignment

    def test_terminate_unlocks_room_and_cancels_occurrence(self):
        """PRD §3.8: "A StudioManager terminates it, the room's status returns to OPEN, and every
        future occurrence booking — each occurrence whose start_at is still after the current
        clock instant — is cancelled, moving its schedule_status from CONFIRMED to CANCELLED."

        Design: Difficulty/transitive_cascade/lockout_terminate_cascades_to_occurrence_to_assignment_release
        """
        studio, room, client, engineer, contract, occ1, assignment = self._setup_active_with_assignment()
        terminated = get_success_data(api_client.terminate_lockout_contract(contract["id"], SM))
        assert terminated["status"] == "TERMINATED", terminated["status"]
        assert get_room(room["id"])["status"] == "OPEN"
        assert get_booking(occ1["id"])["schedule_status"] == "CANCELLED"

    def test_cancelled_occurrence_releases_its_assignment(self):
        """PRD §3.8: "Each such cancellation transitively releases that occurrence's own gear
        rentals and engineer assignments."
        PRD §2.8: "each `EngineerAssignment` moves from `ASSIGNED` to `RELEASED`".

        Design: Difficulty/transitive_cascade/lockout_terminate_cascades_to_occurrence_to_assignment_release
        """
        studio, room, client, engineer, contract, occ1, assignment = self._setup_active_with_assignment()
        get_success_data(api_client.terminate_lockout_contract(contract["id"], SM))
        released = get_engineer_assignment(assignment["id"])
        assert released["status"] == "RELEASED", released["status"]


# =====================================================================
# Difficulty rule 5 — priority_pair_validation_conflict:
#   confirm_state_beats_room_overlap_constraint
# =====================================================================
class TestStateBeatsRoomOverlap:
    """A confirm on an already-CANCELLED booking that ALSO overlaps a confirmed booking returns
    ERR_INVALID_STATE (p5), not ERR_ROOM_UNAVAILABLE (p9)."""

    def _setup(self):
        studio, room, client = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        # other booking confirmed, occupies the overlapping window
        other = create_booking(studio, room, client,
                               start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        pay_deposit(other, client, 14400)
        confirm(other)
        # booking_x overlaps other, then is cancelled while HELD
        booking_x = create_booking(studio, room, client,
                                   start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T11:00:00Z")
        get_success_data(api_client.cancel_booking(booking_x["id"], make_client_headers(client["id"])))
        return studio, room, client, booking_x

    def test_state_check_precedes_room_overlap_check(self):
        """PRD §2.12: "then whether the target is in a state from which the requested transition
        is defined (ERR_INVALID_STATE); then the optimistic-concurrency token where one applies
        (ERR_STALE_VERSION); and only then the domain-specific temporal, safety, capacity, and
        fiscal checks described throughout §3."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_room_overlap_constraint
        """
        studio, room, client, booking_x = self._setup()
        res = api_client.confirm_booking(booking_x["id"], SM)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_cancelled_booking_confirm_is_invalid_state_not_room(self):
        """PRD §3.2: "If the booking is not in HELD when confirmation is attempted, the transition
        is undefined and the request fails with ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/confirm_state_beats_room_overlap_constraint
        """
        studio, room, client, booking_x = self._setup()
        # confirm against the cancelled (terminal) booking -> still ERR_INVALID_STATE
        res = api_client.confirm_booking(booking_x["id"], SM)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# =====================================================================
# Difficulty rule 5 — priority_pair_validation_conflict:
#   ownership_referential_beats_state_on_cancel
# =====================================================================
class TestOwnershipBeatsState:
    """A non-owning Client cancelling an already-CANCELLED booking gets ERR_FORBIDDEN (p4),
    not ERR_INVALID_STATE (p5)."""

    def _setup(self):
        studio, room, _ = setup_studio_room_client(
            studio_overrides={"deposit_pct": 0.60},
            room_overrides={"hourly_rate_cents": 6000, "block_rate_cents": 40000},
        )
        owner = setup_client(studio["id"], display_name="Owner", email="owner@x.com")
        intruder = setup_client(studio["id"], display_name="Intruder", email="intruder@x.com")
        booking = create_booking(studio, room, owner,
                                 start_at="2026-07-10T09:00:00Z", end_at="2026-07-10T12:30:00Z")
        get_success_data(api_client.cancel_booking(booking["id"], make_client_headers(owner["id"])))
        return studio, room, owner, intruder, booking

    def test_ownership_check_precedes_state_check(self):
        """PRD §2.12: "then existence of every path and body resource, left-to-right
        (ERR_NOT_FOUND); then resource ownership for client- and engineer-scoped operations
        (ERR_FORBIDDEN); then whether the target is in a state from which the requested
        transition is defined (ERR_INVALID_STATE)".

        Design: Difficulty/priority_pair_validation_conflict/ownership_referential_beats_state_on_cancel
        """
        studio, room, owner, intruder, booking = self._setup()
        res = api_client.cancel_booking(booking["id"], make_client_headers(intruder["id"]))
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    def test_non_owning_client_forbidden_over_invalid_state(self):
        """PRD §2.1: "A client may only act on bookings whose `client_id` equals their own
        `X-User-ID`."
        PRD §2.1: "Ownership violations — a client reaching for someone else's booking, or an
        engineer reaching for a delivery on a booking they are not assigned to — are rejected with
        `ERR_FORBIDDEN`".

        Design: Difficulty/priority_pair_validation_conflict/ownership_referential_beats_state_on_cancel
        """
        studio, room, owner, intruder, booking = self._setup()
        # intruder does not own the booking; ownership (p4) wins over state (p5)
        res = api_client.cancel_booking(booking["id"], make_client_headers(intruder["id"]))
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
