"""Booking creation economics, slot pools, turnaround, and acceptance windows."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_booking,
    assert_booking,
    assert_slot_invariant,
    create_actor,
    create_booking,
    create_casting_call,
    create_production,
    create_ratio_waiver,
    data_active_booking_count,
    lock_call,
    make_actor_headers,
    make_union_rep_headers,
    publish_call,
    set_clock,
    setup_published_call,
    start_shooting,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBookingCreation:
    def test_booking_rate_snapshot_on_create(self, api, associate_headers):
        """PRD §3.3: "A created booking enters `OFFERED` with its economics
        snapshotted: `slot_type` records `UNION` for a `SAG_AFTRA` actor and
        `NONUNION` otherwise, and `daily_rate_cents` copies the call's
        `union_rate_cents` or `nonunion_rate_cents` to match."
        PRD §3.3: "The booking's `expected_wrap_time` is its `call_time` plus the
        call's `scheduled_duration_minutes`, and for an ordinary booking its
        `offer_expires_at` equals its `call_time` — an offer the actor never
        answers dies at call time."

        Design: Corner/entities/booking_rate_snapshot_on_create
        """
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"],
            publish=True,
            union_slots=1,
            nonunion_slots=1,
            union_rate_cents=12345,
            nonunion_rate_cents=6789,
            location="Lot 32",
        )
        union_actor = create_actor("SAG_AFTRA")
        nonunion_actor = create_actor("NONUNION")

        union_booking = create_booking(call["id"], union_actor["id"])
        assert_booking(union_booking)
        assert union_booking["daily_rate_cents"] == 12345
        assert union_booking["slot_type"] == "UNION"
        assert union_booking["call_time"] == "2026-08-10T07:00:00Z"
        assert union_booking["expected_wrap_time"] == "2026-08-10T17:00:00Z"
        assert union_booking["offer_expires_at"] == "2026-08-10T07:00:00Z"
        assert union_booking["is_replacement"] is False
        assert union_booking["replacement_case_id"] is None
        assert union_booking["replaces_booking_id"] is None

        nonunion_booking = create_booking(call["id"], nonunion_actor["id"])
        assert nonunion_booking["daily_rate_cents"] == 6789
        assert nonunion_booking["slot_type"] == "NONUNION"

    def test_booking_create_missing_required_returns_400(self, api, associate_headers):
        """PRD §2.10: "Body schema: required fields present, enum members valid,
        integer ranges respected — slot counts at least zero, rates, capacities,
        bump amounts, and planned durations strictly positive, waiver reductions at
        least zero (`ERR_VALIDATION`)."
        PRD §3.3: "A `CastingAssociate` books a day player by submitting the
        `casting_call_id`, the `actor_id`, and optionally a per-booking
        `call_time` that overrides the call's `general_call_time` when supplied."

        Design: Corner/validations/booking_create_missing_required_returns_400
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        res = api.create_booking({"casting_call_id": call["id"]}, associate_headers)
        validate_error(res, ApiErrorId.ERR_VALIDATION)

    def test_actor_not_eligible_for_booking(self, api, associate_headers):
        """PRD §3.3: "the actor must be `ELIGIBLE` (`ERR_ACTOR_NOT_ELIGIBLE`)"

        Design: Corner/validations/actor_not_eligible_for_booking
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        actor = create_actor("NONUNION", verify=False)
        assert actor["status"] == "REGISTERED"
        res = api.create_booking(
            {"casting_call_id": call["id"], "actor_id": actor["id"]}, associate_headers
        )
        validate_error(res, ApiErrorId.ERR_ACTOR_NOT_ELIGIBLE)


class TestSlotPools:
    def test_union_actor_no_slot_available(self, api, associate_headers):
        """PRD §3.3: "A union actor may be booked whenever that consumed total is
        still below the call's combined headcount — union performers may spill
        into nominally non-union seats — and is otherwise rejected with
        `ERR_NO_SLOT_AVAILABLE`."

        Design: Corner/validations/union_actor_no_slot_available
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=1)
        u1 = create_actor("SAG_AFTRA")
        u2 = create_actor("SAG_AFTRA")
        n1 = create_actor("NONUNION")
        create_booking(call["id"], u1["id"])
        create_booking(call["id"], n1["id"])
        res = api.create_booking(
            {"casting_call_id": call["id"], "actor_id": u2["id"]}, associate_headers
        )
        validate_error(res, ApiErrorId.ERR_NO_SLOT_AVAILABLE)

    def test_nonunion_cap_extended_by_waiver(self, api, associate_headers):
        """PRD §3.3: "A non-union actor faces a double gate:
        `nonunion_bookings_active` must remain below `nonunion_slots` plus the
        call's `approved_waiver_reduction`, and the consumed total must remain
        below the combined headcount; failure yields `ERR_NO_NONUNION_SLOT`."

        Design: Corner/validations/nonunion_cap_extended_by_waiver
        """
        prod = create_production(active=True)
        call = create_casting_call(
            prod["id"], union_slots=1, nonunion_slots=0, location="Lot 58"
        )
        waiver = create_ratio_waiver(call["id"], union_slot_reduction=1)
        validate_success(
            api.approve_waiver(waiver["id"], make_union_rep_headers("union-1")), 200
        )
        publish_call(call["id"])

        n1 = create_actor("NONUNION")
        n2 = create_actor("NONUNION")
        first = create_booking(call["id"], n1["id"])
        assert first["status"] == "OFFERED"
        res = api.create_booking(
            {"casting_call_id": call["id"], "actor_id": n2["id"]}, associate_headers
        )
        validate_error(res, ApiErrorId.ERR_NO_NONUNION_SLOT)

    def test_union_spillover_consumes_nonunion_pool(self, api, associate_headers):
        """PRD §3.3: "A union actor may be booked whenever that consumed total is
        still below the call's combined headcount — union performers may spill
        into nominally non-union seats — and is otherwise rejected with
        `ERR_NO_SLOT_AVAILABLE`."
        PRD §3.3: "A non-union actor faces a double gate: `nonunion_bookings_active`
        must remain below `nonunion_slots` plus the call's
        `approved_waiver_reduction`, and the consumed total must remain below the
        combined headcount; failure yields `ERR_NO_NONUNION_SLOT`."

        Design: Corner/validations/union_spillover_consumes_nonunion_pool
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        union_actor = create_actor("SAG_AFTRA")
        nonunion_actor = create_actor("NONUNION")
        spill = create_booking(call["id"], union_actor["id"])
        assert spill["slot_type"] == "UNION"
        res = api.create_booking(
            {"casting_call_id": call["id"], "actor_id": nonunion_actor["id"]},
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_NO_NONUNION_SLOT)

    def test_duplicate_booking_same_call_rejected(self, api, associate_headers):
        """PRD §3.3: "the actor must not already hold another booking of this call
        in `OFFERED`, `CONFIRMED`, or `CHECKED_IN` (`ERR_DUPLICATE_BOOKING`)"

        Design: Corner/validations/duplicate_booking_same_call_rejected
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=2)
        actor = create_actor("NONUNION")
        create_booking(call["id"], actor["id"])
        # call_time exactly 600 minutes after the first booking's expected wrap
        # (2026-08-10T17:00:00Z + 10h) so only the duplicate rule can fire.
        res = api.create_booking(
            {
                "casting_call_id": call["id"],
                "actor_id": actor["id"],
                "call_time": "2026-08-11T03:00:00Z",
            },
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_BOOKING)

    def test_bookings_filtered_by_actor(self, api, associate_headers):
        """PRD §4: "List endpoints accept `limit` and `offset` plus the
        resource-specific filters noted in §3 — `production_id`, `shoot_date`,
        `status`, `union_status`, `category`, `casting_call_id`, `actor_id`,
        `booking_id`, `event_type`, `corrects_event_id`, `holding_area_id`,
        `replacement_case_id`, `replaces_booking_id`, `original_booking_id`,
        `voucher_id`, and `payroll_batch_id` — each narrowing the result set to
        matching rows."

        Design: Corner/endpoints/bookings_filtered_by_actor
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=2)
        a1 = create_actor("NONUNION", legal_name="N F1")
        a2 = create_actor("NONUNION", legal_name="N F2")
        create_booking(call["id"], a1["id"])
        create_booking(call["id"], a2["id"])

        res = api.list_bookings(associate_headers, params={"actor_id": a1["id"]})
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert data[0]["actor_id"] == a1["id"]
        assert data[0]["casting_call_id"] == call["id"]


class TestTurnaround:
    def test_turnaround_exactly_600_minutes_allowed(self, api, associate_headers):
        """PRD §3.3: "For each, at least 600 minutes — ten hours — of rest must
        separate the two windows in one direction or the other: either the new
        booking starts no earlier than ten hours after the other booking's window
        ends, or the other booking starts no earlier than ten hours after the new
        booking's window ends."
        PRD §3.3: "A gap of exactly ten hours is permitted; overlap, or a shorter
        gap, rejects the create with `ERR_TURNAROUND_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/turnaround_buffer_on_actor
        """
        prod, call1 = setup_published_call(
            union_slots=0, nonunion_slots=1, location="Lot 20"
        )
        actor = create_actor("NONUNION")
        create_booking(call1["id"], actor["id"])  # window [08-10 07:00, 17:00)
        call2 = create_casting_call(
            prod["id"],
            publish=True,
            shoot_date="2026-08-11",
            general_call_time="2026-08-11T08:00:00Z",
            location="Lot 21",
            union_slots=0,
            nonunion_slots=2,
        )
        # Gap exactly 600 minutes (17:00 -> 03:00 next day): allowed.
        res = api.create_booking(
            {
                "casting_call_id": call2["id"],
                "actor_id": actor["id"],
                "call_time": "2026-08-11T03:00:00Z",
            },
            associate_headers,
        )
        booking2 = validate_success(res, 201)
        assert booking2["status"] == "OFFERED"

    def test_turnaround_599_minutes_rejected(self, api, associate_headers):
        """PRD §3.3: "A gap of exactly ten hours is permitted; overlap, or a
        shorter gap, rejects the create with `ERR_TURNAROUND_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/turnaround_buffer_on_actor
        """
        prod, call1 = setup_published_call(
            union_slots=0, nonunion_slots=1, location="Lot 20"
        )
        actor = create_actor("NONUNION")
        create_booking(call1["id"], actor["id"])  # window [08-10 07:00, 17:00)
        call2 = create_casting_call(
            prod["id"],
            publish=True,
            shoot_date="2026-08-11",
            general_call_time="2026-08-11T08:00:00Z",
            location="Lot 21",
            union_slots=0,
            nonunion_slots=2,
        )
        # Gap 599 minutes (17:00 -> 02:59 next day): rejected.
        res = api.create_booking(
            {
                "casting_call_id": call2["id"],
                "actor_id": actor["id"],
                "call_time": "2026-08-11T02:59:00Z",
            },
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_TURNAROUND_VIOLATION)

    def test_temporal_beats_constraint_at_booking(self, api, associate_headers):
        """PRD §2.10: "Every write request is screened in a fixed order, and the
        first failing check produces the error response" with the business rules
        in this relative order: "the turnaround rest rule
        (`ERR_TURNAROUND_VIOLATION`); duplicate bookings and standby entries
        (`ERR_DUPLICATE_BOOKING`); slot availability (`ERR_NO_SLOT_AVAILABLE`,
        `ERR_NO_NONUNION_SLOT`)".

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_at_booking
        """
        prod, call1 = setup_published_call(
            union_slots=0, nonunion_slots=1, location="Lot 13"
        )
        actor = create_actor("NONUNION", legal_name="N Main")
        filler = create_actor("NONUNION", legal_name="N Filler")
        create_booking(call1["id"], actor["id"])  # window [08-10 07:00, 17:00)
        call2 = create_casting_call(
            prod["id"],
            publish=True,
            shoot_date="2026-08-11",
            general_call_time="2026-08-11T08:00:00Z",
            location="Lot 14",
            union_slots=0,
            nonunion_slots=1,
        )
        create_booking(call2["id"], filler["id"])  # exhausts the nonunion pool

        res = api.create_booking(
            {
                "casting_call_id": call2["id"],
                "actor_id": actor["id"],
                "call_time": "2026-08-11T01:00:00Z",
            },
            associate_headers,
        )
        # Both the turnaround rule (480 < 600 gap) and the nonunion cap fail;
        # the fixed screening order reports the turnaround violation first.
        validate_error(res, ApiErrorId.ERR_TURNAROUND_VIOLATION)

    def test_temporal_priority_leaves_slots_untouched(self, api, associate_headers):
        """PRD §2.10: "Every write request is screened in a fixed order, and the
        first failing check produces the error response" with turnaround
        (`ERR_TURNAROUND_VIOLATION`) listed before slot availability
        (`ERR_NO_SLOT_AVAILABLE`, `ERR_NO_NONUNION_SLOT`) among the business
        rules.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_constraint_at_booking
        """
        prod, call1 = setup_published_call(
            union_slots=0, nonunion_slots=1, location="Lot 13"
        )
        actor = create_actor("NONUNION", legal_name="N Main")
        filler = create_actor("NONUNION", legal_name="N Filler")
        create_booking(call1["id"], actor["id"])
        call2 = create_casting_call(
            prod["id"],
            publish=True,
            shoot_date="2026-08-11",
            general_call_time="2026-08-11T08:00:00Z",
            location="Lot 14",
            union_slots=0,
            nonunion_slots=1,
        )
        create_booking(call2["id"], filler["id"])

        res = api.create_booking(
            {
                "casting_call_id": call2["id"],
                "actor_id": actor["id"],
                "call_time": "2026-08-11T01:00:00Z",
            },
            associate_headers,
        )
        validate_error(res, ApiErrorId.ERR_TURNAROUND_VIOLATION)
        assert res.status_code == 409
        # The rejected create consumed nothing: call2 still has zero slots free.
        call2_after = validate_success(
            api.get_casting_call(call2["id"], associate_headers), 200
        )
        assert call2_after["slots_available"] == 0
        assert data_active_booking_count(call2_after) == 1


class TestSlotConservation:
    def test_slot_pool_conservation_sequence(self, api, associate_headers):
        """PRD §2.6: "For every casting call, the invariant `union_slots` plus
        `nonunion_slots` equals `slots_available` plus the count of that call's
        bookings in `OFFERED`, `CONFIRMED`, `CHECKED_IN`, or `WRAPPED` holds after
        every request. Creating a booking — directly or through a replacement
        offer — consumes one slot; declining, cancelling, expiring, or marking a
        booking as a no-show releases one."

        Design: Difficulty/compensating_invariant/slot_pool_conservation
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=1)
        actor_u = create_actor("SAG_AFTRA")
        actor_n = create_actor("NONUNION")
        assert call["slots_available"] == 2

        booking_u = create_booking(call["id"], actor_u["id"])
        assert self._avail(api, call) == 1
        create_booking(call["id"], actor_n["id"])
        assert self._avail(api, call) == 0
        validate_success(
            api.cancel_booking(booking_u["id"], {"reason": "release"}, associate_headers),
            200,
        )
        assert self._avail(api, call) == 1
        booking_u2 = create_booking(call["id"], actor_u["id"])
        assert self._avail(api, call) == 0
        validate_success(
            api.decline_booking(booking_u2["id"], make_actor_headers(actor_u["id"])),
            200,
        )
        assert self._avail(api, call) == 1

    def test_slot_pool_invariant_holds_at_each_step(self, api, associate_headers):
        """PRD §2.6: "The system recomputes `slots_available`,
        `union_bookings_active`, and `nonunion_bookings_active` after each such
        mutation; the two active counts tally bookings in those same four states,
        broken out by `slot_type`."

        Design: Difficulty/compensating_invariant/slot_pool_conservation
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=1)
        actor_u = create_actor("SAG_AFTRA")
        actor_n = create_actor("NONUNION")

        def check(expected_avail, expected_union, expected_nonunion):
            data = validate_success(
                api.get_casting_call(call["id"], associate_headers), 200
            )
            assert data["slots_available"] == expected_avail
            assert data["union_bookings_active"] == expected_union
            assert data["nonunion_bookings_active"] == expected_nonunion
            assert_slot_invariant(data)

        check(2, 0, 0)
        booking_u = create_booking(call["id"], actor_u["id"])
        check(1, 1, 0)
        create_booking(call["id"], actor_n["id"])
        check(0, 1, 1)
        validate_success(
            api.cancel_booking(booking_u["id"], {"reason": "release"}, associate_headers),
            200,
        )
        check(1, 0, 1)
        booking_u2 = create_booking(call["id"], actor_u["id"])
        check(0, 1, 1)
        validate_success(
            api.decline_booking(booking_u2["id"], make_actor_headers(actor_u["id"])),
            200,
        )
        check(1, 0, 1)

    def _avail(self, api, call):
        return validate_success(
            api.get_casting_call(call["id"], TEST_USERS["associate_headers"]), 200
        )["slots_available"]


class TestAcceptanceWindow:
    def test_booking_double_accept_rejected(self, api, associate_headers):
        """PRD §3.3: "Accepting requires the caller to own the booking
        (`ERR_FORBIDDEN_OWNERSHIP`), the booking to be `OFFERED`
        (`ERR_BOOKING_INVALID_STATE`), and the acceptance window to be open: an
        ordinary booking may be accepted only while its call is `PUBLISHED`, and a
        replacement booking only while its call is `SHOOTING`; any other
        combination fails with `ERR_CALL_NOT_ACCEPTING`."

        Design: Corner/state_machines/booking_double_accept_rejected
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=1)
        actor = create_actor("NONUNION")
        booking = create_booking(call["id"], actor["id"])
        accept_booking(booking["id"], actor["id"])

        res = api.accept_booking(booking["id"], make_actor_headers(actor["id"]))
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)
        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 0

    def test_accept_other_actor_booking_forbidden(self, api, associate_headers):
        """PRD §2.1: "ownership checks on any resource that references a
        BackgroundActor — a booking's `actor_id`, the booking underlying a
        voucher, or a standby entry's `actor_id` — compare that foreign-key field
        to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP`
        (HTTP 403)."

        Design: Corner/rbac/accept_other_actor_booking_forbidden
        """
        prod, call = setup_published_call(union_slots=0, nonunion_slots=2)
        actor_a = create_actor("NONUNION", legal_name="N OwnA")
        actor_b = create_actor("NONUNION", legal_name="N OwnB")
        booking = create_booking(call["id"], actor_a["id"])

        res = api.accept_booking(booking["id"], make_actor_headers(actor_b["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)
        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "OFFERED"

    def test_normal_accept_during_shooting_rejected(self, api, associate_headers):
        """PRD §3.3: "an ordinary booking may be accepted only while its call is
        `PUBLISHED`, and a replacement booking only while its call is `SHOOTING`;
        any other combination fails with `ERR_CALL_NOT_ACCEPTING`."

        Design: Corner/state_machines/normal_accept_during_shooting_rejected
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        booking = create_booking(call["id"], actor["id"])
        lock_call(call["id"])
        start_shooting(call["id"])  # clock 06:55 < offer_expires_at 07:00

        res = api.accept_booking(booking["id"], make_actor_headers(actor["id"]))
        validate_error(res, ApiErrorId.ERR_CALL_NOT_ACCEPTING)
        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "OFFERED"

    def test_accept_requires_call_published(self, api, associate_headers):
        """PRD §3.3: "an ordinary booking may be accepted only while its call is
        `PUBLISHED`, and a replacement booking only while its call is `SHOOTING`;
        any other combination fails with `ERR_CALL_NOT_ACCEPTING`."

        Design: Difficulty/cross_entity_state_dependency/accept_requires_call_published
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        booking = create_booking(call["id"], actor["id"])
        lock_call(call["id"])  # projection satisfied by the OFFERED union booking

        res = api.accept_booking(booking["id"], make_actor_headers(actor["id"]))
        validate_error(res, ApiErrorId.ERR_CALL_NOT_ACCEPTING)
        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "OFFERED"

    def test_accept_after_lock_keeps_slot_consumed(self, api, associate_headers):
        """PRD §3.3: "an ordinary booking may be accepted only while its call is
        `PUBLISHED`, and a replacement booking only while its call is `SHOOTING`;
        any other combination fails with `ERR_CALL_NOT_ACCEPTING`."
        PRD §2.6: the slot invariant "holds after every request" — the rejected
        accept neither consumes nor releases a slot.

        Design: Difficulty/cross_entity_state_dependency/accept_requires_call_published
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        booking = create_booking(call["id"], actor["id"])
        lock_call(call["id"])

        res = api.accept_booking(booking["id"], make_actor_headers(actor["id"]))
        validate_error(res, ApiErrorId.ERR_CALL_NOT_ACCEPTING)
        assert res.status_code == 409
        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 0
        assert call_after["union_bookings_active"] == 1


class TestOfferExpirySweep:
    def test_clock_sweep_expires_offer_and_releases_slot(self, api, associate_headers):
        """PRD §3.3: "Should the logical clock pass a booking's `offer_expires_at`
        while it is still `OFFERED`, the sweep moves it to `EXPIRED` with the same
        slot release"
        PRD §3.3: "the booking to be `OFFERED` (`ERR_BOOKING_INVALID_STATE`)"

        Design: Corner/cross_cutting_complexity_layers/clock_sweep_expires_offer_and_releases_slot
        """
        prod, call = setup_published_call(union_slots=1, nonunion_slots=0)
        actor = create_actor("SAG_AFTRA")
        booking = create_booking(call["id"], actor["id"])
        assert booking["offer_expires_at"] == "2026-08-10T07:00:00Z"

        set_clock("2026-08-10T07:01:00Z")
        booking_after = validate_success(
            api.get_booking(booking["id"], associate_headers), 200
        )
        assert booking_after["status"] == "EXPIRED"
        call_after = validate_success(
            api.get_casting_call(call["id"], associate_headers), 200
        )
        assert call_after["slots_available"] == 1

        res = api.accept_booking(booking["id"], make_actor_headers(actor["id"]))
        validate_error(res, ApiErrorId.ERR_BOOKING_INVALID_STATE)
