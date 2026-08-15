"""Launch posting, tow fees (provisional vs final variants), tow-slot capacity
and OCC, landing accrual, void cascades, and ledger conservation."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_flight,
    assert_member_balance,
    assert_tow_slot,
    book_reservation,
    checkout_reservation,
    complete_flight,
    create_aircraft,
    create_member,
    create_tier,
    create_tow_slot,
    get_flight,
    get_member,
    get_reservation,
    get_tow_slot,
    land_flight,
    make_member_headers,
    post_flight,
    post_flight_raw,
    reconcile_flight,
    set_clock,
    setup_in_flight,
    setup_ops,
    tow_slot_version,
    validate_error,
    validate_success,
    void_flight,
)


class TestProvisionalVsFinalTowFee:
    """2500 ft (base 3800) on a 10%-discount tier with no included tows; the
    95-minute flight owes a 2-block soaring surcharge (800) on the final
    variant only: 3420 provisional vs 4220 final."""

    def _setup_and_fly(self):
        ctx = setup_in_flight(
            tier_overrides={
                "tier_code": "STANDARD",
                "monthly_dues_cents": 6000,
                "tow_fee_discount_pct": 0.10,
                "included_tows_per_month": 0,
            },
            slot_start="2026-08-10T13:00:00Z", slot_end="2026-08-10T18:00:00Z",
            capacity=4,
            res_start="2026-08-10T13:30:00Z", res_end="2026-08-10T16:00:00Z",
            clock="2026-08-10T13:40:00Z",
            release_altitude_ft=2500,
            takeoff_at="2026-08-10T14:05:00Z",
        )
        landed = land_flight(ctx["flight"]["id"], "2026-08-10T15:40:00Z", ctx["pilot"]["id"])
        ctx["flight"] = landed
        return ctx

    def test_provisional_ignores_quota_and_surcharge(self, api):
        """PRD §3.5: "A successful posting creates the flight in `IN_FLIGHT`
        status and immediately computes `provisional_fee_cents` under the
        provisional variant of the tow fee: take the base price for the
        release altitude — below 2,000 feet is 3,000 cents; 2,000 up to but
        not including 3,000 feet is 3,800 cents; 3,000 up to but not including
        5,000 feet is 4,600 cents; 5,000 feet and above is 5,500 cents —
        multiply that base by one minus the member's tier
        `tow_fee_discount_pct`, and round half up to whole cents. The
        provisional variant deliberately ignores both the tier's monthly
        included-tow quota and any soaring surcharge."
        PRD §3.6: "when `flight_minutes` exceeds 60, add 400 cents for each
        commenced 30-minute block beyond the first 60 minutes, so minutes 61
        through 90 add one block, 91 through 120 add two, and so on".

        Design: Difficulty/dual_variant_calc/tow_fee_provisional_vs_final_divergence
        """
        ctx = self._setup_and_fly()
        flight = ctx["flight"]
        assert_flight(flight)
        assert flight["provisional_fee_cents"] == 3420, (
            "round_half_up(3800 * 0.9) at 2500 ft on a 10%-discount tier"
        )
        assert flight["flight_minutes"] == 95
        assert flight["final_fee_cents"] == 4220, (
            "3420 discounted base plus 2 commenced 30-minute blocks beyond 60 "
            "minutes (95 min) at 400 cents each"
        )

    def test_final_fee_replaces_provisional_delta_on_balance(self, api):
        """PRD §2.6: "A launch posts a **provisional** tow debit; when the
        flight lands, the provisional debit is replaced by the final tow fee
        with only the delta applied; a voided launch reverses the provisional
        debit entirely."

        Design: Difficulty/dual_variant_calc/tow_fee_provisional_vs_final_divergence
        """
        ctx = self._setup_and_fly()
        assert_member_balance(get_member(ctx["pilot"]["id"]), 4220), (
            "provisional 3420 replaced by final 4220: net +800 delta after landing"
        )


class TestFinalFeeComposition:
    """Member's 3rd tow of the month on a tier with included_tows_per_month=2
    and a 25% discount: tows 1-2 are free, tow 3 pays the altitude base with
    the discount applied first and the non-discounted surcharge added after."""

    def _setup_three_tows(self):
        ctx = setup_ops(
            tier_overrides={
                "tier_code": "CLUB",
                "monthly_dues_cents": 6000,
                "tow_fee_discount_pct": 0.25,
                "included_tows_per_month": 2,
            },
            slot_start="2026-08-20T12:00:00Z", slot_end="2026-08-20T19:00:00Z",
            capacity=6,
            pilot_name="Quota Pilot",
        )
        pilot = ctx["pilot"]
        glider = ctx["glider"]
        slot = ctx["slot"]
        # Burn the two included tows (fully reconciled).
        set_clock("2026-08-20T12:05:00Z")
        f1 = complete_flight(
            pilot["id"], glider["id"], slot["id"],
            "2026-08-20T12:00:00Z", "2026-08-20T13:00:00Z",
            "2026-08-20T12:10:00Z", "2026-08-20T12:40:00Z",
            release_altitude_ft=3000,
            reconcile_officer_id=ctx["tow_pilot"]["id"],
        )
        set_clock("2026-08-20T13:05:00Z")
        f2 = complete_flight(
            pilot["id"], glider["id"], slot["id"],
            "2026-08-20T13:00:00Z", "2026-08-20T14:00:00Z",
            "2026-08-20T13:10:00Z", "2026-08-20T13:40:00Z",
            release_altitude_ft=3000,
            reconcile_officer_id=ctx["tow_pilot"]["id"],
        )
        # Third tow: the measured flight (4200 ft, 121 minutes).
        set_clock("2026-08-20T15:00:00Z")
        reservation = book_reservation(
            glider["id"], pilot["id"], "2026-08-20T15:00:00Z", "2026-08-20T18:00:00Z"
        )
        checkout_reservation(reservation["id"], pilot["id"])
        f3 = post_flight(reservation["id"], slot["id"], 4200, "2026-08-20T15:10:00Z", pilot["id"])
        f3_landed = land_flight(f3["id"], "2026-08-20T17:11:00Z", pilot["id"])
        return {"ctx": ctx, "f1": f1, "f2": f2, "f3": f3_landed}

    def test_included_tow_quota_zeroes_first_flights_final_fee(self, api):
        """PRD §3.6: "First, count the member's prior `RECONCILED` flights in
        the same UTC calendar month as this flight's `takeoff_at`, taking the
        current flight's position in `created_at` order — the current flight
        is that count plus one, its chronological tow-of-the-month number. If
        that position is within the tier's `included_tows_per_month`, the
        gross fee is zero; otherwise the gross is the same altitude-tier base
        used by the provisional variant."

        Design: Difficulty/combinatorial_formula/tow_fee_final_tiered_quota_surcharge_composition
        """
        state = self._setup_three_tows()
        assert get_flight(state["f1"]["id"])["final_fee_cents"] == 0, (
            "tow 1 of 2 included tows bills at zero cents"
        )
        assert get_flight(state["f2"]["id"])["final_fee_cents"] == 0, (
            "tow 2 of 2 included tows bills at zero cents"
        )
        assert state["f3"]["provisional_fee_cents"] == 3450, (
            "provisional ignores the quota: round_half_up(4600 * 0.75)"
        )

    def test_third_tow_composes_tier_discount_and_surcharge(self, api):
        """PRD §3.6: "Third, assemble `final_fee_cents`: apply the tier
        discount to the gross — one minus `tow_fee_discount_pct`, multiplied
        and rounded half up to whole cents — and only then add the integer
        surcharge, which is never discounted."

        Design: Difficulty/combinatorial_formula/tow_fee_final_tiered_quota_surcharge_composition
        """
        state = self._setup_three_tows()
        f3 = state["f3"]
        assert f3["flight_minutes"] == 121
        # Position 3 > included 2 -> gross 4600 at 4200 ft; discounted 3450;
        # surcharge ceil((121-60)/30) = 3 blocks * 400 = 1200 added after.
        assert f3["final_fee_cents"] == 4650


class TestTowSlotCapacityBoundary:
    """Capacity 2: the second posting (count 1 -> 2) fills the last seat and
    succeeds; the third posting arrives with count == capacity and fails."""

    def _setup_full_slot(self):
        tier = create_tier(tier_code="CAP", monthly_dues_cents=0, included_tows_per_month=99)
        pilots = [create_member(tier["id"], full_name=f"Cap Pilot {c}") for c in "ABC"]
        tow_pilot = create_member(tier["id"], full_name="Cap Tow", is_tow_pilot=True)
        gliders = [
            create_aircraft(reg, "GLIDER") for reg in ("N910G", "N911G", "N912G")
        ]
        tow_plane = create_aircraft("N913T", "TOW_PLANE")
        slot = create_tow_slot(
            tow_plane["id"], tow_pilot["id"],
            "2026-08-20T09:00:00Z", "2026-08-20T18:00:00Z", 2,
        )
        set_clock("2026-08-20T09:40:00Z")
        flights = []
        for i in (0, 1):
            reservation = book_reservation(
                gliders[i]["id"], pilots[i]["id"],
                "2026-08-20T09:30:00Z", "2026-08-20T12:00:00Z",
            )
            checkout_reservation(reservation["id"], pilots[i]["id"])
            flights.append(
                post_flight(reservation["id"], slot["id"], 1500,
                            f"2026-08-20T10:{5 + i * 5:02d}:00Z", pilots[i]["id"])
            )
        # Third pilot checked out and ready to post.
        reservation3 = book_reservation(
            gliders[2]["id"], pilots[2]["id"],
            "2026-08-20T09:30:00Z", "2026-08-20T12:00:00Z",
        )
        checkout_reservation(reservation3["id"], pilots[2]["id"])
        return {"slot": slot, "flights": flights, "reservation3": reservation3,
                "pilot3": pilots[2]}

    def test_filling_last_slot_seat_succeeds(self, api):
        """PRD §3.5: "posting succeeds while `confirmed_count` is strictly
        below `capacity` — filling the last seat succeeds — but a slot whose
        count already equals its capacity refuses with `ERR_TOW_SLOT_FULL`."

        Design: Difficulty/boundary_precision_check/tow_slot_capacity_exact_full
        """
        state = self._setup_full_slot()
        slot = get_tow_slot(state["slot"]["id"])
        assert_tow_slot(slot)
        assert slot["confirmed_count"] == 2, (
            "the second posting (count 1 -> 2 at capacity 2) is allowed"
        )
        for flight in state["flights"]:
            assert get_flight(flight["id"])["status"] == "IN_FLIGHT"

    def test_posting_at_full_capacity_rejected(self, api):
        """PRD §3.5: "posting succeeds while `confirmed_count` is strictly
        below `capacity` — filling the last seat succeeds — but a slot whose
        count already equals its capacity refuses with `ERR_TOW_SLOT_FULL`."

        Design: Difficulty/boundary_precision_check/tow_slot_capacity_exact_full
        """
        state = self._setup_full_slot()
        resp = post_flight_raw(
            state["reservation3"]["id"], state["slot"]["id"], 1500,
            "2026-08-20T10:15:00Z", tow_slot_version(state["slot"]["id"]),
            state["pilot3"]["id"],
        )
        validate_error(resp, ApiErrorId.ERR_TOW_SLOT_FULL)
        assert get_tow_slot(state["slot"]["id"])["confirmed_count"] == 2, (
            "a rejected posting must not partially mutate the count"
        )


class TestFlightVoidCascade:
    def _setup_in_flight_flight(self):
        return setup_in_flight(
            tier_overrides={
                "tier_code": "VOIDT",
                "monthly_dues_cents": 0,
                "tow_fee_discount_pct": 0.10,
                "included_tows_per_month": 0,
            },
            slot_start="2026-08-16T12:00:00Z", slot_end="2026-08-16T18:00:00Z",
            capacity=2,
            res_start="2026-08-16T10:00:00Z", res_end="2026-08-16T15:00:00Z",
            clock="2026-08-16T10:10:00Z",
            release_altitude_ft=1500,
            takeoff_at="2026-08-16T12:05:00Z",
        )

    def test_void_reverses_provisional_and_keeps_reservation(self, api):
        """PRD §3.6: "A false launch can be undone by a `DutyOfficer` or
        `ClubAdmin` while the flight is still `IN_FLIGHT`
        (`ERR_FLIGHT_NOT_IN_FLIGHT` otherwise): the flight moves to the
        terminal `VOIDED`, the provisional debit on the member's account is
        reversed in full, and the slot's `confirmed_count` decrements by one."
        PRD §3.6: "The linked reservation stays `CHECKED_OUT` — the pilot may
        launch again."

        Design: Difficulty/transitive_cascade/flight_void_cascade_balance_restore_and_slot_cancel
        """
        ctx = self._setup_in_flight_flight()
        voided = void_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
        assert voided["status"] == "VOIDED"
        assert_member_balance(get_member(ctx["pilot"]["id"]), 0), (
            "the provisional 2700-cent debit is reversed in full"
        )
        assert get_reservation(ctx["reservation"]["id"])["status"] == "CHECKED_OUT"

    def test_void_to_zero_auto_cancels_future_slot(self, api):
        """PRD §3.6: "Should that decrement bring the count to zero while the
        slot's `start_at` still lies in the future, the slot cancels itself
        automatically."

        Design: Difficulty/transitive_cascade/flight_void_cascade_balance_restore_and_slot_cancel
        """
        ctx = self._setup_in_flight_flight()
        void_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
        slot = get_tow_slot(ctx["slot"]["id"])
        assert slot["confirmed_count"] == 0
        # Slot starts 12:00 and the logical clock reads 10:10: still future.
        assert slot["status"] == "CANCELLED"


class TestPostThenVoidBalanceInvariant:
    def _ctx(self):
        return setup_in_flight(
            tier_overrides={
                "tier_code": "INV",
                "monthly_dues_cents": 0,
                "tow_fee_discount_pct": 0.10,
                "included_tows_per_month": 0,
            },
            slot_start="2026-08-24T09:00:00Z", slot_end="2026-08-24T18:00:00Z",
            capacity=3,
            res_start="2026-08-24T09:30:00Z", res_end="2026-08-24T14:00:00Z",
            clock="2026-08-24T09:40:00Z",
            release_altitude_ft=1500,
            takeoff_at="2026-08-24T10:05:00Z",
        )

    def test_post_debits_provisional_fee(self, api):
        """PRD §3.5: "The provisional amount is debited to the member's
        `account_balance_cents` at once, the slot's `confirmed_count`
        increments by one, and the slot's `version` increments by one with
        it."

        Design: Difficulty/compensating_invariant/flight_post_then_void_balance_invariant
        """
        ctx = self._ctx()
        flight = get_flight(ctx["flight"]["id"])
        assert flight["provisional_fee_cents"] == 2700, (
            "1500 ft base 3000 at a 10% discount: round_half_up(3000 * 0.9)"
        )
        assert_member_balance(get_member(ctx["pilot"]["id"]), 2700)
        assert get_tow_slot(ctx["slot"]["id"])["confirmed_count"] == 1

    def test_void_restores_balance_to_pre_flight(self, api):
        """PRD §2.6: "a voided launch reverses the provisional debit
        entirely."
        PRD §3.6: "the flight moves to the terminal `VOIDED`, the provisional
        debit on the member's account is reversed in full, and the slot's
        `confirmed_count` decrements by one."

        Design: Difficulty/compensating_invariant/flight_post_then_void_balance_invariant
        """
        ctx = self._ctx()
        assert_member_balance(get_member(ctx["pilot"]["id"]), 2700)
        void_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
        assert_member_balance(get_member(ctx["pilot"]["id"]), 0), (
            "post-then-void must conserve the ledger at its pre-flight value"
        )
        assert get_flight(ctx["flight"]["id"])["status"] == "VOIDED"


class TestFlightLifecycleErrors:
    def test_land_twice_rejected(self, api):
        """PRD §3.6: "The flight must be `IN_FLIGHT` — anything else fails
        with `ERR_FLIGHT_NOT_IN_FLIGHT`".

        Design: Corner/state_machines/flight_land_twice_rejected
        """
        ctx = setup_in_flight(
            tier_overrides={"tier_code": "L2", "monthly_dues_cents": 0},
            slot_start="2026-08-26T09:00:00Z", slot_end="2026-08-26T18:00:00Z",
            capacity=3,
            res_start="2026-08-26T09:30:00Z", res_end="2026-08-26T14:00:00Z",
            clock="2026-08-26T09:40:00Z",
            release_altitude_ft=1500,
            takeoff_at="2026-08-26T10:05:00Z",
        )
        land_flight(ctx["flight"]["id"], "2026-08-26T10:35:00Z", ctx["pilot"]["id"])
        resp = api.land_flight(
            ctx["flight"]["id"], {"landed_at": "2026-08-26T10:40:00Z"},
            make_member_headers(ctx["pilot"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_IN_FLIGHT)
        # No double-apply: 30 minutes at 1500 ft, no discount, no surcharge.
        assert_member_balance(get_member(ctx["pilot"]["id"]), 3000)
        assert get_flight(ctx["flight"]["id"])["flight_minutes"] == 30

    def test_tow_slot_cancel_blocked_while_in_flight(self, api):
        """PRD §3.5: "A `TowPilot` or `ClubAdmin` may cancel a slot, but only
        while no `IN_FLIGHT` flight is linked to it; an airborne launch blocks
        cancellation with `ERR_TOW_SLOT_IN_USE` (HTTP 409). Cancellation
        leaves `LANDED` flights as history and blocks any future launches
        against the slot."

        Design: Corner/state_machines/tow_slot_cancel_blocked_while_in_flight
        """
        ctx = setup_in_flight(
            tier_overrides={"tier_code": "TS", "monthly_dues_cents": 0},
            slot_start="2026-08-27T09:00:00Z", slot_end="2026-08-27T18:00:00Z",
            capacity=2,
            res_start="2026-08-27T09:30:00Z", res_end="2026-08-27T14:00:00Z",
            clock="2026-08-27T09:40:00Z",
            release_altitude_ft=1500,
            takeoff_at="2026-08-27T10:05:00Z",
        )
        resp = api.cancel_tow_slot(ctx["slot"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_TOW_SLOT_IN_USE)

        land_flight(ctx["flight"]["id"], "2026-08-27T11:00:00Z", ctx["pilot"]["id"])
        reconcile_flight(ctx["flight"]["id"], ctx["tow_pilot"]["id"])
        cancelled = validate_success(api.cancel_tow_slot(ctx["slot"]["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"


class TestFlightPostingOCC:
    def test_flight_post_stale_tow_slot_version(self, api):
        """PRD §2.10: "A `POST /soaring/flights` request must carry
        `expected_tow_slot_version`, holding the client's last observed
        `version` of the target tow slot. Posting a flight legitimately
        advances the slot's `version` (its `confirmed_count` increments), so
        a second create carrying the previously observed version is stale even
        if the slot still has capacity. If the supplied value does not match
        the tow slot's current `version`, the request is rejected with
        `ERR_STALE_TOW_SLOT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/flight_post_stale_tow_slot_version
        """
        tier = create_tier(tier_code="OC", monthly_dues_cents=0)
        pilot_a = create_member(tier["id"], full_name="OCC P1")
        pilot_b = create_member(tier["id"], full_name="OCC P2")
        tow_pilot = create_member(tier["id"], full_name="OCC Tow", is_tow_pilot=True)
        glider_a = create_aircraft("N022G", "GLIDER", "2027-01-01T00:00:00Z")
        glider_b = create_aircraft("N023G", "GLIDER", "2027-01-01T00:00:00Z")
        tow_plane = create_aircraft("N024T", "TOW_PLANE", "2027-01-01T00:00:00Z")
        slot = create_tow_slot(
            tow_plane["id"], tow_pilot["id"],
            "2026-08-25T09:00:00Z", "2026-08-25T18:00:00Z", 5,
        )
        set_clock("2026-08-25T09:40:00Z")
        stale_version = slot["version"]
        res_a = book_reservation(
            glider_a["id"], pilot_a["id"], "2026-08-25T09:30:00Z", "2026-08-25T14:00:00Z"
        )
        checkout_reservation(res_a["id"], pilot_a["id"])
        res_b = book_reservation(
            glider_b["id"], pilot_b["id"], "2026-08-25T09:30:00Z", "2026-08-25T14:00:00Z"
        )
        checkout_reservation(res_b["id"], pilot_b["id"])

        first = post_flight_raw(
            res_a["id"], slot["id"], 1500, "2026-08-25T10:05:00Z", stale_version,
            pilot_a["id"],
        )
        validate_success(first, 201)
        slot_after = get_tow_slot(slot["id"])
        assert slot_after["confirmed_count"] == 1
        assert slot_after["version"] > stale_version

        second = post_flight_raw(
            res_b["id"], slot["id"], 1500, "2026-08-25T10:10:00Z", stale_version,
            pilot_b["id"],
        )
        validate_error(second, ApiErrorId.ERR_STALE_TOW_SLOT_VERSION)
        assert get_tow_slot(slot["id"])["confirmed_count"] == 1, (
            "the stale posting must not partially mutate the slot"
        )


class TestImmediateConsistency:
    def test_land_response_and_read_after_write(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.6: "Second, a soaring surcharge rewards — and bills — long
        flights: when `flight_minutes` exceeds 60, add 400 cents for each
        commenced 30-minute block beyond the first 60 minutes, so minutes 61
        through 90 add one block, 91 through 120 add two, and so on; flights
        of 60 minutes or less add nothing."

        Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
        """
        ctx = setup_in_flight(
            tier_overrides={
                "tier_code": "IM",
                "monthly_dues_cents": 0,
                "tow_fee_discount_pct": 0.10,
                "included_tows_per_month": 0,
            },
            slot_start="2026-08-31T09:00:00Z", slot_end="2026-08-31T18:00:00Z",
            capacity=2,
            res_start="2026-08-31T09:30:00Z", res_end="2026-08-31T14:00:00Z",
            clock="2026-08-31T09:40:00Z",
            release_altitude_ft=1500,
            takeoff_at="2026-08-31T10:05:00Z",
        )
        resp = api.land_flight(
            ctx["flight"]["id"], {"landed_at": "2026-08-31T10:35:00Z"},
            make_member_headers(ctx["pilot"]["id"]),
        )
        landed = validate_success(resp, 200)
        assert_flight(landed)
        assert landed["status"] == "LANDED"
        assert landed["flight_minutes"] == 30
        assert landed["final_fee_cents"] == 2700, (
            "30 minutes or less adds no surcharge: round_half_up(3000 * 0.9)"
        )
        # Read-after-write in the same instant: provisional 2700 replaced by
        # final 2700, net zero delta.
        assert_member_balance(get_member(ctx["pilot"]["id"]), 2700)
