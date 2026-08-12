"""Corner: load-in windows, check-in, cancellation lock, sweep epoch, spot fines."""
from datetime import datetime, timezone

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    book_reservation,
    create_slot,
    get_assignment,
    get_reservation,
    get_slot,
    make_vendor_spec,
    record_inspection,
    setup_confirmed_assignment,
    setup_curated_multi,
    set_clock,
    sweep_festival,
    validate_error,
    validate_paginated,
    validate_success,
)

OPS = TEST_USERS["ops_headers"]
HI = TEST_USERS["health_inspector_headers"]


def _instant(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestCheckInWindow:
    def test_reservation_checkin_window_enforced(self, api):
        """PRD §3.5: "Gate check-in moves a reservation from `BOOKED` to
        `CHECKED_IN` and is allowed only from `window_start` through thirty minutes
        after `window_end`, inclusive at both ends; outside that span the check-in
        is rejected with `ERR_CHECKIN_WINDOW_CLOSED`. A successful check-in stamps
        `checked_in_at` with the logical clock."

        Design: Corner/state_machines/reservation_checkin_window_enforced
        """
        scen = setup_confirmed_assignment(name="Checkin Fest")
        slot = create_slot(scen["festival"]["id"])
        res = book_reservation(scen["assignment"]["id"], slot["id"], vehicle_count=1)

        set_clock("2026-07-10T07:00:00Z")  # before window_start 08:00
        resp = api.check_in_reservation(res["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED)

        set_clock("2026-07-10T09:00:00Z")  # inside the window
        data = validate_success(api.check_in_reservation(res["id"], OPS))
        assert data["status"] == "CHECKED_IN"
        assert _instant(data["checked_in_at"]) == _instant("2026-07-10T09:00:00Z"), (
            f"checked_in_at must be stamped from the logical clock, got {data['checked_in_at']}"
        )


class TestCancelLock:
    def test_reservation_cancel_after_lock_rejected(self, api):
        """PRD §3.5: "Both booking and cancellation lock two hours before the
        window opens: once the logical clock reaches the instant 120 minutes
        before `window_start`, creating a reservation in that slot or cancelling
        an existing one is rejected with `ERR_SLOT_LOCKED`."

        Design: Corner/state_machines/reservation_cancel_after_lock_rejected
        """
        scen = setup_confirmed_assignment(name="LockCancel Fest")
        slot = create_slot(scen["festival"]["id"])
        res = book_reservation(scen["assignment"]["id"], slot["id"], vehicle_count=1)

        set_clock("2026-07-10T06:00:00Z")  # exactly window_start - 120min
        resp = api.cancel_reservation(res["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_SLOT_LOCKED)
        after = get_reservation(res["id"])
        assert after["status"] == "BOOKED", "rejected cancel leaves the reservation BOOKED"
        slot_after = get_slot(slot["id"])
        assert slot_after["reserved_vehicle_count"] == 1, "rejected cancel released nothing"


class TestSweepGraceBoundary:
    def test_sweep_grace_boundary_and_completion(self, api):
        """PRD §3.5: "The sweep marks every `BOOKED` reservation whose `window_end`
        plus the thirty-minute grace lies strictly before the logical clock as
        `NO_SHOW` — a clock exactly equal to the grace boundary does not mark — and
        every such new no-show decrements the slot's reserved count and auto-issues
        a `NO_SHOW_PENALTY` fine of 25,000 cents (two hundred fifty dollars) on the
        reservation's assignment, recorded with `created_by_user_id` `system` in
        status `ISSUED`. Every `CHECKED_IN` reservation past the same strict grace
        boundary moves to `COMPLETED` and likewise releases its vehicles from the
        slot count."

        Design: Corner/state_machines/sweep_grace_boundary_and_completion
        """
        specs = [
            make_vendor_spec("Sweep A", "FOOD_HOT", power_draw_amps=20),
            make_vendor_spec("Sweep B", "FOOD_COLD", power_draw_amps=20),
        ]
        scen = setup_curated_multi(specs, name="Sweep Fest", zone_power=200)
        asg_a, asg_b = scen["assignments"]
        slot = create_slot(scen["festival"]["id"], max_vehicles=10)
        ra = book_reservation(asg_a["id"], slot["id"], vehicle_count=1)
        rb = book_reservation(asg_b["id"], slot["id"], vehicle_count=2)
        set_clock("2026-07-10T09:00:00Z")
        validate_success(api.check_in_reservation(rb["id"], OPS))

        # Exactly window_end + 30min: strict boundary, nothing marked.
        set_clock("2026-07-10T11:30:00Z")
        sweep1 = sweep_festival(scen["festival"]["id"])
        assert sweep1["no_shows_marked"] == 0
        assert get_reservation(ra["id"])["status"] == "BOOKED"

        # One second past: rA -> NO_SHOW (auto-fine), rB -> COMPLETED.
        set_clock("2026-07-10T11:30:01Z")
        sweep2 = sweep_festival(scen["festival"]["id"])
        assert sweep2["no_shows_marked"] == 1
        assert get_reservation(ra["id"])["status"] == "NO_SHOW"
        assert get_reservation(rb["id"])["status"] == "COMPLETED"
        assert get_slot(slot["id"])["reserved_vehicle_count"] == 0, "both reservations released vehicles"

        fines, meta = validate_paginated(
            api.list_fines(OPS, params={"assignment_id": asg_a["id"], "type": "NO_SHOW_PENALTY"})
        )
        assert len(fines) == 1
        assert fines[0]["amount_cents"] == 25000
        assert fines[0]["created_by_user_id"] == "system"

        # Clock (11:30:01) precedes event_start (12:00): no forfeiture.
        assert sweep2["forfeited_assignment_ids"] == []
        assert get_assignment(asg_a["id"])["status"] == "CONFIRMED"
        assert get_assignment(asg_b["id"])["status"] == "CONFIRMED"


class TestSpotCheckFine:
    def test_spot_check_fail_auto_issues_health_fine(self, api):
        """PRD §3.4: "recording a `HEALTH_SPOT` inspection with `result` `FAIL`
        auto-issues a `HEALTH_VIOLATION` compliance fine of 50,000 cents (five
        hundred dollars) against the assignment, with `created_by_user_id` set to
        the literal `system` and status `ISSUED`."

        Design: Corner/state_machines/spot_check_fail_auto_issues_health_fine
        """
        scen = setup_confirmed_assignment(name="Spot Fest")
        asg_id = scen["assignment"]["id"]
        record_inspection(asg_id, "FIRE_SAFETY", "PASS")  # no fine expected
        record_inspection(asg_id, "HEALTH_SPOT", "FAIL", notes="raw chicken over ice cream")

        fines, meta = validate_paginated(api.list_fines(OPS, params={"assignment_id": asg_id}))
        assert meta["total_count"] == 1, "exactly one fine — FIRE_SAFETY PASS created none"
        fine = fines[0]
        assert fine["type"] == "HEALTH_VIOLATION"
        assert fine["amount_cents"] == 50000
        assert fine["created_by_user_id"] == "system"
        assert fine["status"] == "ISSUED"
