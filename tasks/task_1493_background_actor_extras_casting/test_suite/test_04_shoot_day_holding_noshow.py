"""Shoot day: check-in, holding areas, time-event ledger, and no-show cascades."""
from test_helpers import (
    ApiErrorId,
    assert_holding_area,
    assert_voucher,
    check_in_booking,
    confirm_booking,
    create_actor,
    create_casting_call,
    create_holding_area,
    create_production,
    create_standby_entry,
    get_case_for_call,
    lock_call,
    publish_call,
    set_clock,
    setup_shooting_booking,
    setup_wrapped_day,
    start_shooting,
    wrap_out_booking,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCheckIn:
    def test_voucher_auto_created_draft_at_checkin(self, api, associate_headers):
        """PRD §3.4: "A successful check-in moves the booking `CONFIRMED` →
        `CHECKED_IN`, appends a `CHECK_IN` TimeEvent stamped at the logical clock,
        automatically creates the booking's **Voucher** in `DRAFT` — exactly one
        voucher per booking, for its whole life"

        Design: Corner/entities/voucher_auto_created_draft_at_checkin
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="NONUNION",
            union_slots=0,
            nonunion_slots=1,
            check_in=True,
            check_in_at="2026-08-10T07:00:00Z",
        )
        assert booking["status"] == "CHECKED_IN"

        res = api.list_vouchers(associate_headers, params={"booking_id": booking["id"]})
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["status"] == "DRAFT"
        assert data[0]["booking_id"] == booking["id"]
        assert_voucher(data[0])

    def test_state_beats_safety_at_checkin(self, api, associate_headers):
        """PRD §2.10: "Every write request is screened in a fixed order, and the
        first failing check produces the error response" — entity state
        preconditions (step 8) are screened before the business rules (step 10),
        which include "actor eligibility (`ERR_ACTOR_NOT_ELIGIBLE`)".
        PRD §3.4: "It requires the booking `CONFIRMED` (`ERR_BOOKING_INVALID_STATE`),
        the call `SHOOTING` (`ERR_CALL_INVALID_STATE`), and the actor still
        `ELIGIBLE` (`ERR_ACTOR_NOT_ELIGIBLE`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_at_checkin
        """
        booking, actor = self._cancelled_booking_suspended_actor(api)
        res = api.check_in_booking(booking["id"], {}, associate_headers)
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)

    def test_state_priority_checkin_has_no_side_effects(self, api, associate_headers):
        """PRD §2.10: "Every write request is screened in a fixed order, and the
        first failing check produces the error response" — the state check (step
        8) reports `ERR_BOOKING_INVALID_STATE` before the eligibility rule (step
        10) is reached.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_at_checkin
        """
        booking, actor = self._cancelled_booking_suspended_actor(api)
        res = api.check_in_booking(booking["id"], {}, associate_headers)
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)
        assert res.status_code == 409
        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "CANCELLED"
        actor_after = validate_success(api.get_actor(actor["id"], associate_headers), 200)
        assert actor_after["status"] == "SUSPENDED"

    def _cancelled_booking_suspended_actor(self, api):
        """Build: booking CONFIRMED -> cancelled while PUBLISHED -> actor
        suspended -> call LOCKED -> SHOOTING. Returns (booking, actor)."""
        prod, call, actor, booking = self._build_cancelled(api)
        return booking, actor

    def _build_cancelled(self, api):
        from test_helpers import (
            TEST_USERS,
            create_actor as _mk_actor,
            setup_published_call,
        )

        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        actor = _mk_actor("NONUNION")
        booking = confirm_booking(call["id"], actor["id"])
        validate_success(
            api.cancel_booking(booking["id"], {"reason": "release"},
                               TEST_USERS["associate_headers"]),
            200,
        )
        validate_success(
            api.suspend_actor(actor["id"], TEST_USERS["admin_headers"]), 200
        )
        lock_call(call["id"])
        start_shooting(call["id"])
        return prod, call, actor, booking


class TestHoldingAreas:
    def test_holding_area_aggregate_capacity(self, api, associate_headers):
        """PRD §3.4: "The associate may supply a `holding_area_id`; when supplied,
        the area must belong to this call — a foreign or missing area fails with
        `ERR_HOLDING_AREA_NOT_FOUND` — and its `current_occupancy` must be
        strictly below its `capacity`, since occupancy equal to capacity rejects
        the check-in with `ERR_HOLDING_AREA_FULL`."

        Design: Difficulty/resource_temporal_overlap/holding_area_aggregate_capacity
        """
        prod, call, actors, bookings, area = self._two_confirmed_with_area(api)
        check_in_booking(bookings[0]["id"], at="2026-08-10T07:00:00Z",
                         holding_area_id=area["id"])
        res = api.check_in_booking(
            bookings[1]["id"], {"holding_area_id": area["id"]}, associate_headers
        )
        validate_error(res, ApiErrorId.ERR_HOLDING_AREA_FULL)

    def test_holding_area_occupancy_unchanged_after_rejection(
        self, api, associate_headers
    ):
        """PRD §3.4: "its `current_occupancy` must be strictly below its
        `capacity`, since occupancy equal to capacity rejects the check-in with
        `ERR_HOLDING_AREA_FULL`" — the rejected check-in leaves occupancy and the
        booking's state untouched.

        Design: Difficulty/resource_temporal_overlap/holding_area_aggregate_capacity
        """
        prod, call, actors, bookings, area = self._two_confirmed_with_area(api)
        check_in_booking(bookings[0]["id"], at="2026-08-10T07:00:00Z",
                         holding_area_id=area["id"])
        res = api.check_in_booking(
            bookings[1]["id"], {"holding_area_id": area["id"]}, associate_headers
        )
        validate_error(res, ApiErrorId.ERR_HOLDING_AREA_FULL)
        assert res.status_code == 409

        area_after = validate_success(
            api.get_holding_area(area["id"], associate_headers), 200
        )
        assert area_after["current_occupancy"] == 1
        booking_after = validate_success(
            api.get_booking(bookings[1]["id"], associate_headers), 200
        )
        assert booking_after["status"] == "CONFIRMED"
        assert booking_after["holding_area_id"] is None

    def test_holding_occupancy_reconcile_on_wrapout(self, api, associate_headers):
        """PRD §3.4: "Wrap-out moves the booking `CHECKED_IN` → `WRAPPED`, appends
        a `WRAP_OUT` TimeEvent at the logical clock, and releases the holding seat
        — the area's `current_occupancy` drops by one and its `version` increments
        — when the booking had one."

        Design: Corner/cross_cutting_complexity_layers/holding_occupancy_reconcile_on_wrapout
        """
        prod, call, actors, bookings, area = self._two_confirmed_with_area(api)
        check_in_booking(bookings[0]["id"], at="2026-08-10T07:00:00Z",
                         holding_area_id=area["id"])
        wrap_out_booking(bookings[0]["id"], at="2026-08-10T12:00:00Z")

        area_mid = validate_success(
            api.get_holding_area(area["id"], associate_headers), 200
        )
        assert area_mid["current_occupancy"] == 0

        res = api.check_in_booking(
            bookings[1]["id"], {"holding_area_id": area["id"]}, associate_headers
        )
        checked = validate_success(res, 200)
        assert checked["status"] == "CHECKED_IN"
        area_after = validate_success(
            api.get_holding_area(area["id"], associate_headers), 200
        )
        assert area_after["current_occupancy"] == 1
        assert_holding_area(area_after)

    def _two_confirmed_with_area(self, api):
        """Production ACTIVE; call u0/n2 PUBLISHED; capacity-1 holding area; two
        CONFIRMED bookings; call LOCKED -> SHOOTING. Returns tuple."""
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"], publish=True, union_slots=0, nonunion_slots=2
        )
        area = create_holding_area(call["id"], capacity=1, name="Basecamp A")
        a1 = create_actor("NONUNION", legal_name="N One")
        a2 = create_actor("NONUNION", legal_name="N Two")
        b1 = confirm_booking(call["id"], a1["id"])
        b2 = confirm_booking(call["id"], a2["id"])
        lock_call(call["id"])
        start_shooting(call["id"])
        return prod, call, (a1, a2), (b1, b2), area


class TestTimeEvents:
    def test_time_event_sequence_violations_rejected(self, api, associate_headers):
        """PRD §3.4: "The ledger polices its own sequence, rejecting violations
        with `ERR_TIME_EVENT_INVALID`: no event may precede the check-in; there
        must be exactly one effective `CHECK_IN`; at most one effective `WRAP_OUT`
        may exist and it must follow the check-in; a `MEAL_IN` requires a
        preceding `MEAL_OUT` that no other `MEAL_IN` has yet matched; and a
        manually submitted `WRAP_OUT` is always rejected, because wrap-out flows
        only through the wrap-out action."

        Design: Corner/validations/time_event_sequence_violations_rejected
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="NONUNION",
            union_slots=0,
            nonunion_slots=1,
            check_in=True,
            check_in_at="2026-08-10T07:00:00Z",
        )
        violations = [
            # MEAL_IN with no open MEAL_OUT
            {"booking_id": booking["id"], "event_type": "MEAL_IN",
             "occurred_at": "2026-08-10T12:30:00Z"},
            # manual WRAP_OUT
            {"booking_id": booking["id"], "event_type": "WRAP_OUT",
             "occurred_at": "2026-08-10T15:00:00Z"},
            # event timestamped before the effective CHECK_IN
            {"booking_id": booking["id"], "event_type": "MEAL_OUT",
             "occurred_at": "2026-08-10T06:30:00Z"},
        ]
        for payload in violations:
            res = api.create_time_event(payload, associate_headers)
            validate_error(res, ApiErrorId.ERR_TIME_EVENT_INVALID)


class TestNoShow:
    def test_no_show_before_grace_rejected(self, api, associate_headers):
        """PRD §3.4: "An associate may mark it only while the booking is
        `CONFIRMED` (`ERR_BOOKING_INVALID_STATE`), the call is `SHOOTING`
        (`ERR_CALL_INVALID_STATE`), and the logical clock has reached at least
        sixty minutes past the booking's `call_time`; earlier attempts fail with
        `ERR_NO_SHOW_TOO_EARLY`."

        Design: Corner/validations/no_show_before_grace_rejected
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="SAG_AFTRA", union_slots=1, nonunion_slots=0
        )
        set_clock("2026-08-10T07:30:00Z")  # only 30 minutes past call_time 07:00
        res = api.mark_no_show(booking["id"], associate_headers)
        validate_error(res, ApiErrorId.ERR_NO_SHOW_TOO_EARLY)

        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "CONFIRMED"
        cases = validate_success(
            api.list_replacement_cases(
                associate_headers, params={"casting_call_id": call["id"]}
            ),
            200,
        )
        assert cases == []

    def test_no_show_releases_slot_and_restores_ratio(self, api, associate_headers):
        """PRD §3.4: "First, the call releases the slot — `slots_available` rises
        by one, the projected and active union counts recompute, and the call's
        `version` increments"
        PRD §3.4: "The booking itself lands in `NO_SHOW`, terminal."

        Design: Difficulty/transitive_cascade/no_show_releases_slot_and_restores_ratio
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="SAG_AFTRA", union_slots=1, nonunion_slots=0
        )
        call_locked = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_locked["slots_available"] == 0
        assert call_locked["union_bookings_active"] == 1

        set_clock("2026-08-10T08:05:00Z")
        marked = validate_success(api.mark_no_show(booking["id"], associate_headers), 200)
        assert marked["status"] == "NO_SHOW"

        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 1
        assert call_after["union_bookings_active"] == 0

    def test_no_show_creates_case_and_strikes_actor(self, api, associate_headers):
        """PRD §3.4: "a **ReplacementCase** springs into existence in `OPEN` with
        `reason` `NO_SHOW`, its `required_slot_type` copied from the vacated
        booking's `slot_type`, and its `deadline_at` set to the booking's
        `call_time` plus 120 minutes. Simultaneously, the actor's `no_show_count`
        increments by one, `reliability_score` recomputes, and the actor's
        `version` increments."
        PRD §3.1: "The reliability score itself is the arithmetic of trust: one
        hundred minus twenty points per lifetime no-show, never dropping below
        zero."

        Design: Difficulty/transitive_cascade/no_show_releases_slot_and_restores_ratio
        """
        prod, call, actor, booking = setup_shooting_booking(
            union_status="SAG_AFTRA", union_slots=1, nonunion_slots=0
        )
        set_clock("2026-08-10T08:05:00Z")
        validate_success(api.mark_no_show(booking["id"], associate_headers), 200)

        case = get_case_for_call(call["id"])
        assert case["status"] == "OPEN"
        assert case["reason"] == "NO_SHOW"
        assert case["required_slot_type"] == "UNION"
        assert case["deadline_at"] == "2026-08-10T09:00:00Z"
        assert case["original_booking_id"] == booking["id"]

        actor_after = validate_success(api.get_actor(actor["id"], associate_headers), 200)
        assert actor_after["no_show_count"] == 1
        assert actor_after["reliability_score"] == 80

    def test_third_no_show_auto_suspends(self, api, associate_headers, admin_headers):
        """PRD §3.4: "Second, if that increment brings the count to exactly 3, the
        actor auto-transitions `ELIGIBLE` → `SUSPENDED` with the full suspension
        cascade of §3.1 — outstanding offers expire, confirmed bookings cancel,
        standby entries withdraw."
        PRD §3.1: "The reliability score itself is the arithmetic of trust: one
        hundred minus twenty points per lifetime no-show, never dropping below
        zero."

        Design: Corner/state_machines/third_no_show_auto_suspends
        """
        prod = create_production(active=True)
        actor = create_actor("NONUNION", legal_name="N Ns3")
        calls = []
        bookings = []
        for i, day in enumerate(["2026-08-10", "2026-08-11", "2026-08-12"]):
            call = create_casting_call(
                prod["id"],
                shoot_date=day,
                general_call_time=f"{day}T07:00:00Z",
                location=f"Lot {40 + i}",
                union_slots=0,
                nonunion_slots=1,
            )
            publish_call(call["id"])
            bookings.append(confirm_booking(call["id"], actor["id"]))
            calls.append(call)
        entry = create_standby_entry(calls[2]["id"], actor["id"])
        for call in calls:
            lock_call(call["id"])

        def shoot_and_no_show(call, booking, day):
            set_clock(f"{day}T06:55:00Z")
            validate_success(api.start_shooting(call["id"], associate_headers), 200)
            set_clock(f"{day}T08:05:00Z")
            validate_success(api.mark_no_show(booking["id"], associate_headers), 200)

        shoot_and_no_show(calls[0], bookings[0], "2026-08-10")
        shoot_and_no_show(calls[1], bookings[1], "2026-08-11")

        mid = validate_success(api.get_actor(actor["id"], associate_headers), 200)
        assert mid["no_show_count"] == 2
        assert mid["reliability_score"] == 60
        assert mid["status"] == "ELIGIBLE"

        shoot_and_no_show(calls[2], bookings[2], "2026-08-12")

        final = validate_success(api.get_actor(actor["id"], associate_headers), 200)
        assert final["no_show_count"] == 3
        assert final["reliability_score"] == 40
        assert final["status"] == "SUSPENDED"

        entry_after = validate_success(
            api.get_standby_entry(entry["id"], associate_headers), 200
        )
        assert entry_after["status"] == "WITHDRAWN"
        booking3_after = validate_success(
            api.get_booking(bookings[2]["id"], associate_headers), 200
        )
        assert booking3_after["status"] == "NO_SHOW"


class TestTerminalLockdown:
    def test_wrapped_booking_terminal_lockdown(self, api, associate_headers):
        """PRD §3.3: "An associate may also cancel a booking outright — cancelling
        carries an optional `reason` — from `OFFERED` or `CONFIRMED`
        (`ERR_BOOKING_INVALID_STATE` from any other state)"
        PRD §3.4: "An associate may mark it only while the booking is `CONFIRMED`
        (`ERR_BOOKING_INVALID_STATE`)"

        Design: Corner/state_machines/wrapped_booking_terminal_lockdown
        """
        prod, call, actor, booking, voucher = setup_wrapped_day(
            wrap_at="2026-08-10T12:00:00Z"
        )
        assert booking["status"] == "WRAPPED"
        res1 = api.cancel_booking(booking["id"], {}, associate_headers)
        validate_error(res1, ApiErrorId.ERR_BOOKING_INVALID_STATE)
        res2 = api.mark_no_show(booking["id"], associate_headers)
        validate_error(res2, ApiErrorId.ERR_BOOKING_INVALID_STATE)
