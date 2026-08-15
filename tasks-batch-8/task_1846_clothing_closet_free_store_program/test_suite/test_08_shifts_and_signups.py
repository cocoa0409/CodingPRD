"""Volunteer shifts and signups: capacity lock cycle, overlap windows, window
gates, and the completion cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    actor_headers_for,
    assert_shift_signup,
    assert_volunteer_shift,
    checkin_signup,
    create_shift,
    register_volunteer,
    set_clock,
    signup_volunteer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]


class TestShiftLockCycle:
    def test_shift_locks_at_capacity_and_reopens_on_cancel(self, api):
        """PRD: "Each new signup increments `active_signup_count`, and the moment
        the count reaches `capacity_volunteers` the shift locks automatically
        from `OPEN` to `LOCKED`."
        PRD: "Cancelling a `SIGNED_UP` signup moves it to `CANCELLED`, decrements
        the shift's `active_signup_count`, and when a `LOCKED` shift drops back
        below capacity it reopens automatically from `LOCKED` to `OPEN`."

        Design: Difficulty/non_linear_state_machine/shift_open_locked_open_cycle
        """
        vol = register_volunteer("Vol One")
        shift = create_shift("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z",
                             role_type="FLOOR", capacity_volunteers=1)

        signup = signup_volunteer(shift["id"], vol)
        assert signup["status"] == "SIGNED_UP"
        locked = validate_success(api.get_shift(shift["id"], ADMIN), 200)
        assert locked["status"] == "LOCKED", "count reached capacity"

        cancelled = validate_success(
            api.cancel_signup(shift["id"], signup["id"],
                              TEST_USERS["program_admin_headers"]),
            200)
        assert cancelled["status"] == "CANCELLED"
        reopened = validate_success(api.get_shift(shift["id"], ADMIN), 200)
        assert reopened["status"] == "OPEN", "dropping below capacity reopens"

    def test_shift_relocks_when_refilled(self, api):
        """PRD: "Each new signup increments `active_signup_count`, and the moment
        the count reaches `capacity_volunteers` the shift locks automatically
        from `OPEN` to `LOCKED`."
        PRD: "Cancelling a `SIGNED_UP` signup moves it to `CANCELLED`, decrements
        the shift's `active_signup_count`, and when a `LOCKED` shift drops back
        below capacity it reopens automatically from `LOCKED` to `OPEN`."

        Design: Difficulty/non_linear_state_machine/shift_open_locked_open_cycle
        """
        vol_one = register_volunteer("Vol One")
        vol_two = register_volunteer("Vol Two")
        shift = create_shift("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z",
                             role_type="FLOOR", capacity_volunteers=1)

        signup = signup_volunteer(shift["id"], vol_one)
        assert validate_success(api.get_shift(shift["id"], ADMIN), 200)["status"] == "LOCKED"
        validate_success(api.cancel_signup(shift["id"], signup["id"], ADMIN), 200)
        assert validate_success(api.get_shift(shift["id"], ADMIN), 200)["status"] == "OPEN"

        signup_two = signup_volunteer(shift["id"], vol_two)
        assert signup_two["status"] == "SIGNED_UP"
        final = validate_success(api.get_shift(shift["id"], ADMIN), 200)
        assert final["status"] == "LOCKED", "the cycle re-enters LOCKED"


class TestShiftOverlap:
    def test_overlapping_shift_signup_rejected(self, api):
        """PRD: "the volunteer must not already hold an active signup — one in
        `SIGNED_UP` or `CHECKED_IN` — on a shift whose window overlaps this one,
        where overlap is judged on half-open intervals so back-to-back shifts,
        one ending exactly when the other begins, do not conflict
        (`ERR_SHIFT_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_half_open_overlap
        """
        vol = register_volunteer("Vol One")
        shift1 = create_shift("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z",
                              role_type="FLOOR", capacity_volunteers=3)
        shift2 = create_shift("2026-08-05T10:00:00Z", "2026-08-05T14:00:00Z",
                              role_type="SORTING", capacity_volunteers=3)
        signup_volunteer(shift1["id"], vol)

        resp = api.create_signup(shift2["id"], {"volunteer_id": vol["id"]},
                                 actor_headers_for(vol))
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)

    def test_back_to_back_shift_signup_allowed(self, api):
        """PRD: "the volunteer must not already hold an active signup — one in
        `SIGNED_UP` or `CHECKED_IN` — on a shift whose window overlaps this one,
        where overlap is judged on half-open intervals so back-to-back shifts,
        one ending exactly when the other begins, do not conflict
        (`ERR_SHIFT_OVERLAP`)"

        Design: Difficulty/resource_temporal_overlap/volunteer_shift_half_open_overlap
        """
        vol = register_volunteer("Vol One")
        shift1 = create_shift("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z",
                              role_type="FLOOR", capacity_volunteers=3)
        shift3 = create_shift("2026-08-05T12:00:00Z", "2026-08-05T16:00:00Z",
                              role_type="SORTING", capacity_volunteers=3)
        signup_volunteer(shift1["id"], vol)

        adjacent = signup_volunteer(shift3["id"], vol)
        assert_shift_signup(adjacent)
        assert adjacent["status"] == "SIGNED_UP", "12:00-16:00 is back-to-back"


class TestSignupGuards:
    def test_shift_signup_duplicate_and_full_rejected(self, api):
        """PRD: "Signup enforces its rules in order: a shift that is `LOCKED` (at
        capacity) rejects with `ERR_SHIFT_FULL`, and a shift that is `COMPLETED`
        or `CANCELLED` rejects with `ERR_INVALID_STATE`; the volunteer must not
        already hold an active signup — one in `SIGNED_UP` or `CHECKED_IN` — on a
        shift whose window overlaps this one, where overlap is judged on
        half-open intervals so back-to-back shifts, one ending exactly when the
        other begins, do not conflict (`ERR_SHIFT_OVERLAP`); and the volunteer
        must not already be actively signed up on this same shift
        (`ERR_ALREADY_SIGNED_UP`)."

        Design: Corner/validations/shift_signup_duplicate_and_full_rejected
        """
        vol1 = register_volunteer("V1")
        vol2 = register_volunteer("V2")
        vol3 = register_volunteer("V3")
        shift = create_shift("2026-08-05T08:00:00Z", "2026-08-05T12:00:00Z",
                             role_type="FLOOR", capacity_volunteers=2)

        first = signup_volunteer(shift["id"], vol1)
        assert first["status"] == "SIGNED_UP"
        resp = api.create_signup(shift["id"], {"volunteer_id": vol1["id"]},
                                 actor_headers_for(vol1))
        validate_error(resp, ApiErrorId.ERR_ALREADY_SIGNED_UP)

        second = signup_volunteer(shift["id"], vol2)
        assert second["status"] == "SIGNED_UP"
        locked = validate_success(api.get_shift(shift["id"], ADMIN), 200)
        assert locked["status"] == "LOCKED", "auto-LOCKED at 2"
        resp = api.create_signup(shift["id"], {"volunteer_id": vol3["id"]},
                                 actor_headers_for(vol3))
        validate_error(resp, ApiErrorId.ERR_SHIFT_FULL)


class TestShiftWindowGates:
    def test_shift_window_checks(self, api):
        """PRD: "Checking in requires the signup to be `SIGNED_UP` (otherwise
        `ERR_INVALID_STATE`), the shift to be `OPEN` or `LOCKED`, and the current
        instant to fall on or after the shift's `start_at` and on or before its
        `end_at` — outside that window the check-in is `ERR_SHIFT_NOT_IN_WINDOW`."
        PRD: "Completing a shift — allowed once the clock has reached the shift's
        `end_at`, otherwise `ERR_SHIFT_NOT_IN_WINDOW` — moves an `OPEN` or
        `LOCKED` shift to `COMPLETED` and settles its signups"

        Design: Corner/validations/shift_window_checks
        """
        vol = register_volunteer("V1")
        future_shift = create_shift("2026-08-02T08:00:00Z", "2026-08-02T12:00:00Z",
                                    role_type="FLOOR", capacity_volunteers=2)
        current_shift = create_shift("2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z",
                                     role_type="FLOOR", capacity_volunteers=2)
        signup = signup_volunteer(future_shift["id"], vol)

        resp = api.checkin_signup(future_shift["id"], signup["id"],
                                  actor_headers_for(vol))
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_IN_WINDOW)

        resp = api.complete_shift(current_shift["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_IN_WINDOW)

    def test_shift_create_invalid_window_rejected(self, api):
        """PRD: "A shift is created with a `start_at`, an `end_at` that must be
        strictly later than the start, a `role_type` of `SORTING`, `INTAKE`, or
        `FLOOR`, and a `capacity_volunteers` of at least 1."

        Design: Corner/endpoints/shift_create_invalid_window_rejected
        """
        resp = api.create_shift(
            {"start_at": "2026-08-05T08:00:00Z", "end_at": "2026-08-05T08:00:00Z",
             "role_type": "FLOOR", "capacity_volunteers": 1},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestShiftCompletionCascade:
    def test_shift_complete_no_show_cascade(self, api):
        """PRD: "Completing a shift — allowed once the clock has reached the
        shift's `end_at`, otherwise `ERR_SHIFT_NOT_IN_WINDOW` — moves an `OPEN`
        or `LOCKED` shift to `COMPLETED` and settles its signups: those still
        `SIGNED_UP` become `NO_SHOW`, and those `CHECKED_IN` become `COMPLETED`."

        Design: Corner/state_machines/shift_complete_no_show_cascade
        """
        vol1 = register_volunteer("Vol One")
        vol2 = register_volunteer("Vol Two")
        shift = create_shift("2026-08-01T00:00:00Z", "2026-08-01T02:00:00Z",
                             role_type="FLOOR", capacity_volunteers=2)
        signup1 = signup_volunteer(shift["id"], vol1)
        signup2 = signup_volunteer(shift["id"], vol2)
        checkin_signup(shift["id"], signup2["id"], vol2)

        set_clock("2026-08-01T03:00:00Z")
        completed = validate_success(api.complete_shift(shift["id"], ADMIN), 200)
        assert_volunteer_shift(completed)
        assert completed["status"] == "COMPLETED"

        page1, meta1 = validate_paginated(api.list_volunteer_signups(vol1["id"], ADMIN))
        assert meta1["total_count"] == 1
        assert page1[0]["id"] == signup1["id"]
        assert page1[0]["status"] == "NO_SHOW", "signed up, never checked in"

        page2, meta2 = validate_paginated(api.list_volunteer_signups(vol2["id"], ADMIN))
        assert meta2["total_count"] == 1
        assert page2[0]["id"] == signup2["id"]
        assert page2[0]["status"] == "COMPLETED", "was checked in"

