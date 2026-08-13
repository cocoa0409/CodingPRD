"""Ride cycles, queue boarding, and the credit ledger: the cycle-threshold
suspension cascade, boundary precision at the manufacturer interval, credit
conservation across board/void/abort, and the rider-count invariant
(PRD sections 3.5-3.6).

Covers design instances:
  Difficulty/transitive_cascade/cycle_completion_threshold_suspends_license_and_voids_queue
  Difficulty/boundary_precision_check/cycle_threshold_exact_boundary
  Difficulty/compensating_invariant/credit_conservation_across_board_void_and_abort
  Difficulty/compensating_invariant/rider_count_matches_redeemed_boardings_under_capacity
  Corner/calculations/load_time_insufficient_credit_skip_and_void
  Corner/errors/redemption_with_zero_credits_rejected
  Corner/errors/redemption_void_and_load_state_errors_on_running_cycle
  Corner/errors/cycle_empty_inprogress_and_sale_void_blocked_errors
"""
from test_helpers import (
    ApiErrorId,
    assert_credit_conservation,
    make_clerk_headers,
    make_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _setup_open_with_credits(api, name, quantity=5, ride_overrides=None):
    ctx = fx.setup_open_day(name, ride_overrides=ride_overrides)
    sup, clerk = ctx["sup"], ctx["clerk"]
    prod = fx.create_product(sup)
    sale = fx.sell(clerk, prod["id"], ctx["day"]["id"], quantity=quantity)
    ctx.update({"prod": prod, "sale": sale})
    return ctx


class TestCycleThresholdCascade:
    def test_completion_at_interval_suspends_and_voids_queue(self, api):
        """PRD section 3.6: "the ride's `cycles_since_inspection` rises by one,
        and the moment that counter reaches the manufacturer
        `cycle_inspection_interval`, the ride's `license_status` moves from
        `LICENSED` to `SUSPENDED`; suspension in turn moves the ride's
        `daily_status` from `OPEN` or `WEATHER_HOLD` to `CLOSED`, and every
        `QUEUED` redemption of that ride for the day is moved to `VOIDED` with
        no credit movement, since a queued entry has never been debited."

        Capacity-1 ride, interval 2: the second completed cycle fires the
        depth-3 cascade while r3 is still QUEUED behind the full cycle.

        Design: Difficulty/transitive_cascade/cycle_completion_threshold_suspends_license_and_voids_queue
        """
        ctx = _setup_open_with_credits(
            api, "H", quantity=5,
            ride_overrides={"capacity_per_cycle": 1, "cycle_inspection_interval": 2})
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        fx.queue_redemption(op, sale["id"], ride_id)
        fx.run_cycle(op, ride_id, day_id)
        fx.queue_redemption(op, sale["id"], ride_id)
        r3 = fx.queue_redemption(op, sale["id"], ride_id)
        cyc2 = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc2["id"], "load")
        fx.cycle_action(op, cyc2["id"], "dispatch")
        fx.cycle_action(op, cyc2["id"], "complete")
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 2
        assert ride["license_status"] == "SUSPENDED", (
            "counter reaching the interval must suspend the license")
        assert ride["daily_status"] == "CLOSED"
        r3_after = fx.get_redemption(sup, r3["id"])
        assert r3_after["status"] == "VOIDED"
        assert r3_after["ride_cycle_id"] is None
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_redeemed"] == 2
        assert sale_after["credits_remaining"] == 3, (
            "the voided QUEUED redemption was never debited")

    def test_ride_audit_pass_resets_counter_and_relicenses(self, api):
        """PRD section 3.2: "A passed `RIDE_AUDIT` resets the audited ride's
        `cycles_since_inspection` to zero and moves its `license_status` from
        `PENDING` or `SUSPENDED` to `LICENSED`."

        Design: Difficulty/transitive_cascade/cycle_completion_threshold_suspends_license_and_voids_queue
        """
        ctx = _setup_open_with_credits(
            api, "Hb", quantity=5,
            ride_overrides={"capacity_per_cycle": 1, "cycle_inspection_interval": 2})
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        for _ in range(2):
            fx.queue_redemption(op, sale["id"], ride_id)
            fx.run_cycle(op, ride_id, day_id)
        ride = fx.get_ride(sup, ride_id)
        assert ride["license_status"] == "SUSPENDED"
        assert ride["cycles_since_inspection"] == 2
        audit = fx.schedule_ride_audit(sup, ride_id)
        fx.complete_appointment(audit, outcome="PASS")
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 0, (
            "a passed RIDE_AUDIT must reset the cycle counter")
        assert ride["license_status"] == "LICENSED"


class TestCycleThresholdBoundary:
    def test_first_cycle_below_interval_keeps_license(self, api):
        """PRD section 3.6: "the ride's `cycles_since_inspection` rises by one,
        and the moment that counter reaches the manufacturer
        `cycle_inspection_interval`, the ride's `license_status` moves from
        `LICENSED` to `SUSPENDED`". With interval 2 the first completed cycle
        leaves the counter at 1 — below the threshold — and the license and
        the day's operation are untouched.

        Design: Difficulty/boundary_precision_check/cycle_threshold_exact_boundary
        """
        ctx = _setup_open_with_credits(
            api, "N", quantity=5, ride_overrides={"cycle_inspection_interval": 2})
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        fx.queue_redemption(op, ctx["sale"]["id"], ride_id)
        fx.run_cycle(op, ride_id, day_id)
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 1
        assert ride["license_status"] == "LICENSED", "1 < 2 must not trigger"
        assert ride["daily_status"] == "OPEN"

    def test_second_cycle_at_exactly_interval_suspends(self, api):
        """PRD section 3.6: "the moment that counter reaches the manufacturer
        `cycle_inspection_interval`, the ride's `license_status` moves from
        `LICENSED` to `SUSPENDED`". With interval 2 the second completed cycle
        lands exactly on the threshold and the >= comparison fires at equality.

        Design: Difficulty/boundary_precision_check/cycle_threshold_exact_boundary
        """
        ctx = _setup_open_with_credits(
            api, "Nb", quantity=5, ride_overrides={"cycle_inspection_interval": 2})
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        for _ in range(2):
            fx.queue_redemption(op, ctx["sale"]["id"], ride_id)
            fx.run_cycle(op, ride_id, day_id)
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 2
        assert ride["license_status"] == "SUSPENDED", "2 >= 2 triggers at equality"
        assert ride["daily_status"] == "CLOSED"


class TestCreditConservation:
    def test_board_then_void_loading_phase_refunds(self, api):
        """PRD section 3.6: "a credit-bearing wristband with at least one
        remaining credit boards and is debited — `credits_remaining` down one,
        `credits_redeemed` up one" and "A `REDEEMED` redemption may be voided
        only while its cycle is still `LOADING`, and that void carries the same
        per-guest refund — `credits_redeemed` down one, `credits_remaining` up
        one, and the cycle's `rider_count` down one."

        Design: Difficulty/compensating_invariant/credit_conservation_across_board_void_and_abort
        """
        ctx = _setup_open_with_credits(api, "S", quantity=5)
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        r1 = fx.queue_redemption(op, sale["id"], ride_id)
        r2 = fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_remaining"] == 3
        assert sale_after["credits_redeemed"] == 2
        assert_credit_conservation(sale_after)
        cyc_after = fx.get_cycle(sup, cyc["id"])
        assert cyc_after["rider_count"] == 2
        validate_success(api.void_redemption(r2["id"], {}, make_operator_headers(op["id"])))
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_remaining"] == 4
        assert sale_after["credits_redeemed"] == 1
        assert_credit_conservation(sale_after)
        cyc_after = fx.get_cycle(sup, cyc["id"])
        assert cyc_after["rider_count"] == 1
        r2_after = fx.get_redemption(sup, r2["id"])
        assert r2_after["status"] == "VOIDED"

    def test_abort_running_cycle_refunds_everyone(self, api):
        """PRD section 3.6: "Aborting a cycle — from `LOADING` or `RUNNING`
        alike, operator-only, otherwise `ERR_CYCLE_INVALID_STATE` — lands it in
        `ABORTED` and refunds everyone aboard: each `REDEEMED` redemption on
        the cycle moves to `VOIDED`, each credit-bearing wristband's
        `credits_redeemed` drops by one and `credits_remaining` rises by one,
        and the cycle's `rider_count` returns to zero."

        Design: Difficulty/compensating_invariant/credit_conservation_across_board_void_and_abort
        """
        ctx = _setup_open_with_credits(api, "Sb", quantity=5)
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        r1 = fx.queue_redemption(op, sale["id"], ride_id)
        r2 = fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        validate_success(api.void_redemption(r2["id"], {}, make_operator_headers(op["id"])))
        fx.cycle_action(op, cyc["id"], "dispatch")
        fx.cycle_action(op, cyc["id"], "abort")
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_remaining"] == 5
        assert sale_after["credits_redeemed"] == 0
        assert sale_after["credits_forfeited"] == 0
        assert_credit_conservation(sale_after)
        cyc_after = fx.get_cycle(sup, cyc["id"])
        assert cyc_after["status"] == "ABORTED"
        assert cyc_after["rider_count"] == 0
        r1_after = fx.get_redemption(sup, r1["id"])
        assert r1_after["status"] == "VOIDED"


class TestRiderCountInvariant:
    def _setup_three_guests(self, api, name):
        ctx = fx.setup_open_day(name, ride_overrides={"capacity_per_cycle": 2})
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        prod = fx.create_product(sup)
        guests = [fx.sell(clerk, prod["id"], day_id, quantity=1) for _ in range(3)]
        queued = [fx.queue_redemption(op, g["id"], ride_id) for g in guests]
        ctx.update({"prod": prod, "guests": guests, "queued": queued})
        return ctx

    def test_capacity_two_boards_exactly_two_of_three(self, api):
        """PRD section 3.6: "Boarding stops as soon as the cycle's
        `rider_count` reaches the ride's `capacity_per_cycle`; candidates
        beyond that point stay `QUEUED` for the next cycle" and "the cycle's
        `rider_count` is an invariant — the count of its currently `REDEEMED`
        redemptions — maintained by boarding, voiding, and aborting alike."

        Design: Difficulty/compensating_invariant/rider_count_matches_redeemed_boardings_under_capacity
        """
        ctx = self._setup_three_guests(api, "T")
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        q1, q2, q3 = ctx["queued"]
        cyc = fx.open_cycle(op, ride_id, day_id)
        cyc = fx.cycle_action(op, cyc["id"], "load")
        assert cyc["rider_count"] == 2, (
            f"capacity-2 cycle must board exactly two of three; got {cyc['rider_count']}")
        q1 = fx.get_redemption(sup, q1["id"])
        q2 = fx.get_redemption(sup, q2["id"])
        q3 = fx.get_redemption(sup, q3["id"])
        assert q1["status"] == "REDEEMED" and q1["ride_cycle_id"] == cyc["id"]
        assert q2["status"] == "REDEEMED" and q2["ride_cycle_id"] == cyc["id"]
        assert q3["status"] == "QUEUED" and q3["ride_cycle_id"] is None
        assert q1["queue_position"] == 1 and q3["queue_position"] == 3

    def test_void_boarded_decrements_rider_count_then_dispatch(self, api):
        """PRD section 3.6: "A `REDEEMED` redemption may be voided only while
        its cycle is still `LOADING`, and that void carries the same per-guest
        refund — `credits_redeemed` down one, `credits_remaining` up one, and
        the cycle's `rider_count` down one."

        Design: Difficulty/compensating_invariant/rider_count_matches_redeemed_boardings_under_capacity
        """
        ctx = self._setup_three_guests(api, "Tb")
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        q1 = ctx["queued"][0]
        g1 = ctx["guests"][0]
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        validate_success(api.void_redemption(q1["id"], {}, make_operator_headers(op["id"])))
        cyc_after = fx.get_cycle(sup, cyc["id"])
        assert cyc_after["rider_count"] == 1
        q1_after = fx.get_redemption(sup, q1["id"])
        assert q1_after["status"] == "VOIDED"
        g1_after = fx.get_sale(sup, g1["id"])
        assert g1_after["credits_redeemed"] == 0
        assert g1_after["credits_remaining"] == 1
        fx.cycle_action(op, cyc["id"], "dispatch")
        fx.cycle_action(op, cyc["id"], "complete")
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 1, "1 < 5, no suspension"


class TestBoardingSkipPath:
    def test_load_voids_insufficient_credit_entry_without_seat(self, api):
        """PRD section 3.6: "a credit-bearing wristband with nothing left is
        moved to `VOIDED` on the spot, skipped without consuming a seat, and
        selection continues."

        Two QUEUED redemptions share a one-credit wristband: credits are
        checked but not debited at queue time, so the first boards and the
        second voids at load.

        Design: Corner/calculations/load_time_insufficient_credit_skip_and_void
        """
        ctx = _setup_open_with_credits(api, "CC6", quantity=1)
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        r1 = fx.queue_redemption(op, sale["id"], ride_id)
        r2 = fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        cyc = fx.cycle_action(op, cyc["id"], "load")
        r1_after = fx.get_redemption(sup, r1["id"])
        assert r1_after["status"] == "REDEEMED"
        assert r1_after["ride_cycle_id"] == cyc["id"]
        r2_after = fx.get_redemption(sup, r2["id"])
        assert r2_after["status"] == "VOIDED"
        assert r2_after["ride_cycle_id"] is None
        assert cyc["rider_count"] == 1, "the voided skip consumes no seat"
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_redeemed"] == 1
        assert sale_after["credits_remaining"] == 0


class TestRedemptionCreditGate:
    def test_redemption_with_zero_credits_rejected(self, api):
        """PRD section 3.6: "a credit-bearing wristband must hold at least one
        remaining credit, else `ERR_INSUFFICIENT_CREDITS`".

        The single credit was drained by an earlier boarding; the next
        redemption attempt against the same wristband fails and persists
        nothing.

        Design: Corner/errors/redemption_with_zero_credits_rejected
        """
        ctx = _setup_open_with_credits(api, "ER4", quantity=1)
        sup, op = ctx["sup"], ctx["op"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        resp = api.create_redemption(
            {"wristband_id": sale["id"], "ride_id": ride_id},
            make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDITS, 422)
        data, meta = validate_paginated(api.list_redemptions(
            make_operator_headers(op["id"]), params={"wristband_id": sale["id"]}))
        assert meta["total_count"] == 1 and len(data) == 1, (
            "the rejected attempt must not persist a redemption row")


class TestCycleAndSaleStateGuards:
    def test_void_boarded_on_running_cycle_rejected(self, api):
        """PRD section 3.6: "Any other combination — a redemption already
        `VOIDED` or `EXPIRED`, or a `REDEEMED` one whose cycle has left
        `LOADING` — is rejected with `ERR_REDEMPTION_NOT_VOIDABLE`."

        Once the cycle is RUNNING the compensation window for individual
        voids is closed; completing the cycle keeps the boarded credit
        consumed.

        Design: Corner/errors/redemption_void_and_load_state_errors_on_running_cycle
        """
        ctx = _setup_open_with_credits(api, "ER11", quantity=2)
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        r1 = fx.queue_redemption(op, sale["id"], ride_id)
        cyc = fx.open_cycle(op, ride_id, day_id)
        fx.cycle_action(op, cyc["id"], "load")
        fx.cycle_action(op, cyc["id"], "dispatch")
        resp = api.void_redemption(r1["id"], {}, make_clerk_headers(clerk["id"]))
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_NOT_VOIDABLE, 409)
        fx.cycle_action(op, cyc["id"], "complete")
        ride = fx.get_ride(sup, ride_id)
        assert ride["cycles_since_inspection"] == 1
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["credits_redeemed"] == 1
        assert sale_after["credits_remaining"] == 1

    def test_cycle_in_progress_empty_dispatch_and_void_blocked(self, api):
        """PRD section 3.6: "no other cycle for the same ride may be in
        `LOADING` or `RUNNING` — a second in-progress cycle is
        `ERR_CYCLE_IN_PROGRESS`" and "dispatching an empty cycle is
        `ERR_CYCLE_EMPTY`"; PRD section 3.5: "if any of its redemptions is
        `REDEEMED`, the void is rejected with `ERR_SALE_HAS_REDEMPTIONS`."

        Design: Corner/errors/cycle_empty_inprogress_and_sale_void_blocked_errors
        """
        ctx = _setup_open_with_credits(api, "ER13", quantity=1)
        sup, op, clerk = ctx["sup"], ctx["op"], ctx["clerk"]
        ride_id, day_id = ctx["ride"]["id"], ctx["day"]["id"]
        sale = ctx["sale"]
        fx.queue_redemption(op, sale["id"], ride_id)
        cyc1 = fx.open_cycle(op, ride_id, day_id)
        resp = api.create_cycle({"ride_id": ride_id, "operating_day_id": day_id},
                                make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_CYCLE_IN_PROGRESS, 409)
        resp = api.dispatch_cycle(cyc1["id"], {}, make_operator_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_CYCLE_EMPTY, 422)
        fx.cycle_action(op, cyc1["id"], "load")
        resp = api.void_sale(sale["id"], {}, make_clerk_headers(clerk["id"]))
        validate_error(resp, ApiErrorId.ERR_SALE_HAS_REDEMPTIONS, 422)
        sale_after = fx.get_sale(sup, sale["id"])
        assert sale_after["status"] == "ACTIVE"
        cyc_after = fx.get_cycle(sup, cyc1["id"])
        assert cyc_after["status"] == "LOADING", (
            "all three rejections must be side-effect free")
