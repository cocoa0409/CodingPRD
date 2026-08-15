"""Shift scheduling, signup gates, attendance, and minted shift credit."""
import pytest

from test_helpers import (ApiErrorId, approve_entry, create_active_volunteer,
                          create_and_open_cycle, create_credit_entry_payload,
                          create_shift, get_record_for, get_success_data,
                          make_volunteer_headers, set_clock,
                          setup_cycle_with_active_volunteer,
                          setup_cycle_with_two_active_volunteers, sign_up,
                          validate_error, validate_paginated, validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]


class TestShiftCreationAndLocationOverlap:
    def test_shift_create_invalid_kind_returns_invalid_request(self, api):
        """PRD §2.9: "(3) schema validation of required fields, types, enum
        membership, and static ranges — `ERR_INVALID_REQUEST` (HTTP 400) for
        missing fields, wrong types, invalid enum members, or malformed
        values"
        PRD §3.4: "a `kind` of `HELP_DESK` or `OUTREACH`"

        Design: Corner/entities/shift_create_invalid_kind_returns_invalid_request
        """
        cycle = create_and_open_cycle()
        resp = api.create_shift(
            {"cycle_id": cycle["id"], "kind": "GALA", "location": "Desk A",
             "start_time": "2026-08-10T09:00:00Z",
             "end_time": "2026-08-10T12:00:00Z", "capacity": 2}, COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_shift_location_back_to_back_allowed(self, api):
        """PRD §3.4: "Back-to-back scheduling, where the new shift starts
        exactly when the existing one ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/shift_location_half_open_overlap
        """
        cycle = create_and_open_cycle()
        create_shift(cycle["id"], start_time="2026-08-10T09:00:00Z",
                     end_time="2026-08-10T12:00:00Z")
        resp = api.create_shift(
            {"cycle_id": cycle["id"], "kind": "HELP_DESK",
             "location": "Desk A", "start_time": "2026-08-10T12:00:00Z",
             "end_time": "2026-08-10T15:00:00Z", "capacity": 2}, COORD)
        created = validate_success(resp, expected_status=201)
        assert created["status"] == "OPEN"

    def test_shift_location_interior_overlap_rejected(self, api):
        """PRD §3.4: "for shifts at the same `location` that are not
        `CANCELLED`, the half-open intervals from `start_time` up to but not
        including `end_time` must not intersect — a new shift starting before
        an existing shift ends while the existing shift starts before the new
        shift ends is a conflict rejected with `ERR_SHIFT_LOCATION_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/shift_location_half_open_overlap
        """
        cycle = create_and_open_cycle()
        create_shift(cycle["id"], start_time="2026-08-10T09:00:00Z",
                     end_time="2026-08-10T12:00:00Z")
        resp = api.create_shift(
            {"cycle_id": cycle["id"], "kind": "OUTREACH",
             "location": "Desk A", "start_time": "2026-08-10T11:59:00Z",
             "end_time": "2026-08-10T13:00:00Z", "capacity": 2}, COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_LOCATION_CONFLICT)

    def test_shift_location_other_location_and_cancelled_not_blocking(
            self, api):
        """PRD §3.4: "One venue cannot host two overlapping shifts: for
        shifts at the same `location` that are not `CANCELLED`, the half-open
        intervals from `start_time` up to but not including `end_time` must
        not intersect"

        Design: Difficulty/resource_temporal_overlap/shift_location_half_open_overlap
        """
        cycle = create_and_open_cycle()
        existing = create_shift(cycle["id"],
                                start_time="2026-08-10T09:00:00Z",
                                end_time="2026-08-10T12:00:00Z")
        # Different location, overlapping window: no conflict.
        resp = api.create_shift(
            {"cycle_id": cycle["id"], "kind": "OUTREACH", "location": "Annex",
             "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T13:00:00Z", "capacity": 2}, COORD)
        assert validate_success(resp, expected_status=201)["status"] == "OPEN"
        # Once the occupant is CANCELLED, the same location frees up.
        get_success_data(api.cancel_shift(existing["id"], COORD))
        resp = api.create_shift(
            {"cycle_id": cycle["id"], "kind": "HELP_DESK",
             "location": "Desk A", "start_time": "2026-08-10T10:00:00Z",
             "end_time": "2026-08-10T11:00:00Z", "capacity": 2}, COORD)
        assert validate_success(resp, expected_status=201)["status"] == "OPEN"


class TestSignupGates:
    def test_shift_capacity_exact_full_boundary(self, api):
        """PRD §3.4: "it increments the shift's `filled_count` by one and
        flips the shift `OPEN → FULL` automatically the moment `filled_count`
        reaches `capacity`."
        PRD §3.4: "the shift must be `OPEN` — attempts against `FULL`,
        `COMPLETED`, or `CANCELLED` shifts all fail with
        `ERR_SHIFT_NOT_OPEN`."

        Design: Difficulty/boundary_precision_check/shift_capacity_exact_full_boundary
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        shift = create_shift(cycle["id"], capacity=1)
        su1 = sign_up(shift["id"], vol1["id"])
        assert su1["status"] == "SIGNED_UP"
        mid = get_success_data(api.get_shift(shift["id"], COORD))
        assert mid["filled_count"] == 1
        assert mid["status"] == "FULL"

        resp = api.create_signup(shift["id"], {"volunteer_id": vol2["id"]},
                                 make_volunteer_headers(vol2["id"]))
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN)

    def test_shift_capacity_boundary_first_signup_keeps_filled_count(
            self, api):
        """PRD §3.4: "it increments the shift's `filled_count` by one and
        flips the shift `OPEN → FULL` automatically the moment `filled_count`
        reaches `capacity`."

        Design: Difficulty/boundary_precision_check/shift_capacity_exact_full_boundary
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        shift = create_shift(cycle["id"], capacity=1)
        su1 = sign_up(shift["id"], vol1["id"])
        assert su1["status"] == "SIGNED_UP"
        mid = get_success_data(api.get_shift(shift["id"], COORD))
        assert mid["filled_count"] == 1
        assert mid["filled_count"] == mid["capacity"]
        api.create_signup(shift["id"], {"volunteer_id": vol2["id"]},
                          make_volunteer_headers(vol2["id"]))
        su1_after = get_success_data(api.get_signup(su1["id"], COORD))
        assert su1_after["status"] == "SIGNED_UP"

    def test_signup_requires_volunteer_active_error(self, api):
        """PRD §3.4: "the volunteer must be `ACTIVE` (otherwise
        `ERR_VOLUNTEER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/signup_requires_volunteer_active
        """
        cycle = create_and_open_cycle()
        from test_helpers import create_accepted_volunteer
        trainee = create_accepted_volunteer(cycle["id"])
        assert trainee["status"] == "TRAINEE"
        shift = create_shift(cycle["id"])
        resp = api.create_signup(shift["id"], {"volunteer_id": trainee["id"]},
                                 make_volunteer_headers(trainee["id"]))
        validate_error(resp, ApiErrorId.ERR_VOLUNTEER_NOT_ACTIVE)

    def test_signup_requires_volunteer_active_no_seat_consumed(self, api):
        """PRD §3.4: "the volunteer must be `ACTIVE` (otherwise
        `ERR_VOLUNTEER_NOT_ACTIVE`)"
        PRD §3.4: "it increments the shift's `filled_count` by one and flips
        the shift `OPEN → FULL` automatically the moment `filled_count`
        reaches `capacity`."

        Design: Difficulty/cross_entity_state_dependency/signup_requires_volunteer_active
        """
        cycle = create_and_open_cycle()
        from test_helpers import create_accepted_volunteer
        trainee = create_accepted_volunteer(cycle["id"])
        shift = create_shift(cycle["id"])
        api.create_signup(shift["id"], {"volunteer_id": trainee["id"]},
                          make_volunteer_headers(trainee["id"]))
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["filled_count"] == 0

    def test_signup_travel_buffer_intervals(self, api):
        """PRD §3.4: "a new shift conflicts with any shift the volunteer is
        `SIGNED_UP` for unless one of the two starts at or after the other
        ends plus a buffer — thirty minutes when the two shifts are at
        different locations, zero when they share a location. A
        cross-location gap of exactly thirty minutes passes; twenty-nine
        minutes fails; same-location back-to-back passes. Violations are
        rejected with `ERR_SIGNUP_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/signup_travel_buffer_intervals
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        sh_a = create_shift(cycle["id"], location="Desk A",
                            start_time="2026-08-10T09:00:00Z",
                            end_time="2026-08-10T12:00:00Z")
        sh_d = create_shift(cycle["id"], location="Desk A",
                            start_time="2026-08-10T12:00:00Z",
                            end_time="2026-08-10T13:00:00Z")
        sh_b = create_shift(cycle["id"], kind="OUTREACH", location="Annex",
                            start_time="2026-08-10T12:20:00Z",
                            end_time="2026-08-10T14:00:00Z")
        sh_c = create_shift(cycle["id"], kind="OUTREACH", location="Hall",
                            start_time="2026-08-10T13:30:00Z",
                            end_time="2026-08-10T15:00:00Z")
        hdrs = make_volunteer_headers(vol["id"])

        su_a = validate_success(api.create_signup(
            sh_a["id"], {"volunteer_id": vol["id"]}, hdrs),
            expected_status=201)
        assert su_a["status"] == "SIGNED_UP"
        # Same location, zero gap: allowed.
        su_d = validate_success(api.create_signup(
            sh_d["id"], {"volunteer_id": vol["id"]}, hdrs),
            expected_status=201)
        assert su_d["status"] == "SIGNED_UP"
        # 20-minute cross-location gap from D (12:20 - 13:00 < 30 min): fails.
        resp = api.create_signup(sh_b["id"], {"volunteer_id": vol["id"]},
                                 hdrs)
        validate_error(resp, ApiErrorId.ERR_SIGNUP_SCHEDULE_CONFLICT)
        sh_b_after = get_success_data(api.get_shift(sh_b["id"], COORD))
        assert sh_b_after["filled_count"] == 0
        # Exactly 30 minutes from D's 13:00 end: allowed.
        su_c = validate_success(api.create_signup(
            sh_c["id"], {"volunteer_id": vol["id"]}, hdrs),
            expected_status=201)
        assert su_c["status"] == "SIGNED_UP"

    def test_signup_travel_buffer_29_min_gap_would_fail(self, api):
        """PRD §3.4: "a new shift conflicts with any shift the volunteer is
        `SIGNED_UP` for unless one of the two starts at or after the other
        ends plus a buffer — thirty minutes when the two shifts are at
        different locations, zero when they share a location. A
        cross-location gap of exactly thirty minutes passes; twenty-nine
        minutes fails; same-location back-to-back passes. Violations are
        rejected with `ERR_SIGNUP_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/signup_travel_buffer_intervals
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        sh_a = create_shift(cycle["id"], location="Desk A",
                            start_time="2026-08-10T09:00:00Z",
                            end_time="2026-08-10T12:00:00Z")
        # Cross-location shift starting 29 minutes after A ends: fails.
        sh_b = create_shift(cycle["id"], kind="OUTREACH", location="Annex",
                            start_time="2026-08-10T12:29:00Z",
                            end_time="2026-08-10T14:00:00Z")
        hdrs = make_volunteer_headers(vol["id"])
        sign_up(sh_a["id"], vol["id"])
        resp = api.create_signup(sh_b["id"], {"volunteer_id": vol["id"]},
                                 hdrs)
        validate_error(resp, ApiErrorId.ERR_SIGNUP_SCHEDULE_CONFLICT)
        sh_b_after = get_success_data(api.get_shift(sh_b["id"], COORD))
        assert sh_b_after["filled_count"] == 0

    def test_signup_state_and_duplicate_errors(self, api):
        """PRD §3.4: "A volunteer may hold at most one `SIGNED_UP` signup per
        shift (a duplicate fails with `ERR_DUPLICATE_SIGNUP`)"
        PRD §3.4: "Both post-shift actions require the signup to be
        `SIGNED_UP` (otherwise `ERR_SIGNUP_NOT_SIGNED_UP`)"

        Design: Corner/state_machines/signup_state_and_duplicate_errors
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"])
        hdrs = make_volunteer_headers(vol["id"])
        su = sign_up(shift["id"], vol["id"])

        resp = api.create_signup(shift["id"], {"volunteer_id": vol["id"]},
                                 hdrs)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNUP)

        get_success_data(api.cancel_signup(su["id"], hdrs))
        resp = api.complete_signup(su["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_SIGNED_UP)
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["filled_count"] == 0
        assert after["status"] == "OPEN"

    def test_signup_after_shift_start_returns_409(self, api):
        """PRD §3.4: "The logical clock must be strictly earlier than the
        shift's `start_time`; a signup at or after start fails with
        `ERR_SIGNUP_WINDOW_CLOSED`."

        Design: Corner/errors/signup_after_shift_start_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"],
                             start_time="2026-08-05T09:00:00Z",
                             end_time="2026-08-05T12:00:00Z")
        set_clock("2026-08-05T10:00:00Z")
        resp = api.create_signup(shift["id"], {"volunteer_id": vol["id"]},
                                 make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_SIGNUP_WINDOW_CLOSED)
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["filled_count"] == 0

    def test_cancel_signup_after_shift_start_returns_409(self, api):
        """PRD §3.4: "the explicit cancellation action additionally requires
        the logical clock to be strictly before the shift's `start_time`,
        failing with `ERR_CANCELLATION_WINDOW_CLOSED` at or after start."

        Design: Corner/errors/cancel_signup_after_shift_start_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"],
                             start_time="2026-08-10T09:00:00Z",
                             end_time="2026-08-10T12:00:00Z")
        hdrs = make_volunteer_headers(vol["id"])
        su = sign_up(shift["id"], vol["id"])
        set_clock("2026-08-10T09:30:00Z")
        resp = api.cancel_signup(su["id"], hdrs)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_WINDOW_CLOSED)
        su_after = get_success_data(api.get_signup(su["id"], COORD))
        assert su_after["status"] == "SIGNED_UP"
        shift_after = get_success_data(api.get_shift(shift["id"], COORD))
        assert shift_after["filled_count"] == 1

    def test_no_show_limit_blocks_fourth_signup(self, api):
        """PRD §3.4: "a volunteer whose `no_show_strikes` has reached three
        is blocked with `ERR_NO_SHOW_LIMIT_REACHED` — two strikes still
        passes, exactly three blocks, and strikes never reset across the
        volunteer's lifetime."
        PRD §3.4: "Marking a no-show instead moves the signup to terminal
        `NO_SHOW` and increments the volunteer's `no_show_strikes` by one,
        moving the volunteer closer to the three-strike signup block."

        Design: Corner/errors/no_show_limit_blocks_fourth_signup
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        signup_ids = []
        for day in ("10", "11", "12"):
            sh = create_shift(cycle["id"],
                              start_time=f"2026-08-{day}T09:00:00Z",
                              end_time=f"2026-08-{day}T10:00:00Z")
            signup_ids.append(sign_up(sh["id"], vol["id"]))
            set_clock(f"2026-08-{day}T10:00:00Z")
            get_success_data(api.complete_shift(sh["id"], COORD))
            get_success_data(api.mark_no_show(signup_ids[-1]["id"], COORD))

        vol_mid = get_success_data(api.get_volunteer(vol["id"], COORD))
        assert vol_mid["no_show_strikes"] == 3

        sh4 = create_shift(cycle["id"], start_time="2026-08-13T09:00:00Z",
                           end_time="2026-08-13T10:00:00Z")
        resp = api.create_signup(sh4["id"], {"volunteer_id": vol["id"]},
                                 make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_LIMIT_REACHED)
        for su in signup_ids:
            assert get_success_data(
                api.get_signup(su["id"], COORD))["status"] == "NO_SHOW"


class TestShiftLifecycleAndCascades:
    def test_completed_shift_cannot_be_cancelled_returns_409(self, api):
        """PRD §3.4: "Cancelling a shift requires `OPEN` or `FULL` (otherwise
        `ERR_SHIFT_NOT_CANCELLABLE`) and moves it to terminal `CANCELLED`"

        Design: Corner/state_machines/completed_shift_cannot_be_cancelled_returns_409
        """
        cycle = create_and_open_cycle()
        shift = create_shift(cycle["id"],
                             start_time="2026-08-10T09:00:00Z",
                             end_time="2026-08-10T12:00:00Z")
        set_clock("2026-08-10T12:00:00Z")
        get_success_data(api.complete_shift(shift["id"], COORD))
        resp = api.cancel_shift(shift["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_CANCELLABLE)
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["status"] == "COMPLETED"

    def test_shift_lifecycle_wrong_state_errors(self, api):
        """PRD §3.4: "Marking a shift completed requires it to be `OPEN` or
        `FULL` (otherwise `ERR_INVALID_SHIFT_STATE`) and the logical clock to
        be at or past `end_time` (otherwise `ERR_SHIFT_NOT_ENDED`), moving it
        to terminal `COMPLETED`."

        Design: Corner/state_machines/shift_lifecycle_wrong_state_errors
        """
        cycle = create_and_open_cycle()
        shift = create_shift(cycle["id"],
                             start_time="2026-08-10T09:00:00Z",
                             end_time="2026-08-10T12:00:00Z")
        # Clock is at the 2026-08-01 default, before end_time.
        resp = api.complete_shift(shift["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_ENDED)

        get_success_data(api.cancel_shift(shift["id"], COORD))
        set_clock("2026-08-10T13:00:00Z")
        resp = api.complete_shift(shift["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_SHIFT_STATE)
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["status"] == "CANCELLED"

    def test_shift_cancel_cascades_to_signups(self, api):
        """PRD §3.4: "Cancelling a shift requires `OPEN` or `FULL` (otherwise
        `ERR_SHIFT_NOT_CANCELLABLE`) and moves it to terminal `CANCELLED`:
        every `SIGNED_UP` signup cascades to `CANCELLED` and `filled_count`
        is set to zero, with no `FULL → OPEN` revert firing because the shift
        is terminal."

        Design: Corner/state_machines/shift_cancel_cascades_to_signups
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"])
        su = sign_up(shift["id"], vol["id"])
        resp = api.cancel_shift(shift["id"], COORD)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["filled_count"] == 0
        su_after = get_success_data(api.get_signup(su["id"], COORD))
        assert su_after["status"] == "CANCELLED"

    def test_signup_complete_before_shift_completed_returns_409(self, api):
        """PRD §3.4: "Both post-shift actions require the signup to be
        `SIGNED_UP` (otherwise `ERR_SIGNUP_NOT_SIGNED_UP`) and the parent
        shift to be `COMPLETED` (otherwise `ERR_SHIFT_NOT_COMPLETED`)."

        Design: Corner/state_machines/signup_complete_before_shift_completed_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        shift = create_shift(cycle["id"])
        su = sign_up(shift["id"], vol["id"])
        resp = api.complete_signup(su["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_COMPLETED)
        su_after = get_success_data(api.get_signup(su["id"], COORD))
        assert su_after["status"] == "SIGNED_UP"
        assert su_after["completed_entry_id"] is None


class TestSeatConservation:
    def test_shift_seat_conservation_signup_fill(self, api):
        """PRD §3.4: "it increments the shift's `filled_count` by one and
        flips the shift `OPEN → FULL` automatically the moment `filled_count`
        reaches `capacity`."

        Design: Difficulty/compensating_invariant/shift_seat_conservation_signup_cancel
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        shift = create_shift(cycle["id"], capacity=2)
        sign_up(shift["id"], vol1["id"])
        su2 = sign_up(shift["id"], vol2["id"])
        mid = get_success_data(api.get_shift(shift["id"], COORD))
        assert mid["filled_count"] == 2
        assert mid["status"] == "FULL"
        assert su2["status"] == "SIGNED_UP"

    def test_shift_seat_conservation_cancel_restores_open(self, api):
        """PRD §3.4: "Cancellation decrements the shift's `filled_count` by
        one, and a `FULL` shift reverts to `OPEN`."

        Design: Difficulty/compensating_invariant/shift_seat_conservation_signup_cancel
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        shift = create_shift(cycle["id"], capacity=2)
        su1 = sign_up(shift["id"], vol1["id"])
        su2 = sign_up(shift["id"], vol2["id"])
        get_success_data(api.cancel_signup(
            su1["id"], make_volunteer_headers(vol1["id"])))
        after = get_success_data(api.get_shift(shift["id"], COORD))
        assert after["filled_count"] == 1
        assert after["status"] == "OPEN"
        assert get_success_data(
            api.get_signup(su1["id"], COORD))["status"] == "CANCELLED"
        assert get_success_data(
            api.get_signup(su2["id"], COORD))["status"] == "SIGNED_UP"


class TestShiftCreditMinting:
    def test_shift_credit_per_entry_rounding_entry_hours(self, api):
        """PRD §3.4: "Credited hours for a completed shift are computed per
        shift entry at mint time: the shift's duration in whole minutes is
        divided by fifteen and rounded half-up to a whole count of
        quarter-hour units, and that count is multiplied by one quarter
        hour."

        Design: Difficulty/combinatorial_formula/shift_credit_per_entry_rounding
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        sh1 = create_shift(cycle["id"], start_time="2026-08-10T09:00:00Z",
                           end_time="2026-08-10T10:40:00Z")   # 100 min
        sh2 = create_shift(cycle["id"], start_time="2026-08-10T11:00:00Z",
                           end_time="2026-08-10T12:10:00Z")   # 70 min
        su1 = sign_up(sh1["id"], vol["id"])
        su2 = sign_up(sh2["id"], vol["id"])
        set_clock("2026-08-10T12:10:00Z")
        get_success_data(api.complete_shift(sh1["id"], COORD))
        get_success_data(api.complete_shift(sh2["id"], COORD))
        done1 = get_success_data(api.complete_signup(su1["id"], COORD))
        done2 = get_success_data(api.complete_signup(su2["id"], COORD))
        e1 = get_success_data(
            api.get_credit_entry(done1["completed_entry_id"], COORD))
        e2 = get_success_data(
            api.get_credit_entry(done2["completed_entry_id"], COORD))
        # 100 min -> round(100/15)=7 quarters -> 1.75; 70 min -> 5 -> 1.25
        assert e1["hours"] == pytest.approx(1.75, abs=0.001)
        assert e2["hours"] == pytest.approx(1.25, abs=0.001)

    def test_shift_credit_per_entry_rounding_record_total(self, api):
        """PRD §3.4: "Volunteer totals then sum the already-rounded per-entry
        values; summing raw minutes across shifts and rounding once is
        explicitly not the rule, and the two orders diverge — a 100-minute
        shift and a 70-minute shift yield 3.00 credited hours under per-entry
        rounding but 2.75 under sum-then-round."

        Design: Difficulty/combinatorial_formula/shift_credit_per_entry_rounding
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        sh1 = create_shift(cycle["id"], start_time="2026-08-10T09:00:00Z",
                           end_time="2026-08-10T10:40:00Z")
        sh2 = create_shift(cycle["id"], start_time="2026-08-10T11:00:00Z",
                           end_time="2026-08-10T12:10:00Z")
        su1 = sign_up(sh1["id"], vol["id"])
        su2 = sign_up(sh2["id"], vol["id"])
        set_clock("2026-08-10T12:10:00Z")
        get_success_data(api.complete_shift(sh1["id"], COORD))
        get_success_data(api.complete_shift(sh2["id"], COORD))
        done1 = get_success_data(api.complete_signup(su1["id"], COORD))
        done2 = get_success_data(api.complete_signup(su2["id"], COORD))
        approve_entry(done1["completed_entry_id"])
        approve_entry(done2["completed_entry_id"])
        evaluated = validate_success(api.evaluate_record(rec["id"], COORD))
        # Per-entry rounding: 1.75 + 1.25 = 3.00 (sum-then-round would be 2.75)
        assert evaluated["official_service_hours"] == pytest.approx(
            3.0, abs=0.001)
        assert evaluated["official_service_hours"] != pytest.approx(
            2.75, abs=0.001)


class TestShiftListing:
    def test_shifts_filter_by_kind_returns_only_matching(self, api):
        """PRD §3.4: "The shift list may be filtered by `cycle_id`, `kind`,
        `location`, and `status`."

        Design: Corner/endpoints/shifts_filter_by_kind_returns_only_matching
        """
        cycle = create_and_open_cycle()
        create_shift(cycle["id"], kind="HELP_DESK", location="Desk A",
                     start_time="2026-08-10T09:00:00Z",
                     end_time="2026-08-10T12:00:00Z")
        outreach = create_shift(cycle["id"], kind="OUTREACH", location="Fair",
                                start_time="2026-08-15T10:00:00Z",
                                end_time="2026-08-15T14:00:00Z", capacity=4)
        resp = api.list_shifts(COORD, params={"kind": "OUTREACH"})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == outreach["id"]
        assert data[0]["kind"] == "OUTREACH"
