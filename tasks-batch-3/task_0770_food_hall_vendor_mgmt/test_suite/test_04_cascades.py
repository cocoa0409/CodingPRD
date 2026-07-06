"""Transitive cascades: a failed inspection and a vendor suspension each ripple
through permit/posture -> live orders -> reserved seating within one request.
"""
import pytest
from test_helpers import (
    validate_success,
    open_stall, place_order, reserve_seats, conduct_inspection,
    TEST_USERS,
)

HM = TEST_USERS["hall_manager_headers"]
HI = TEST_USERS["health_inspector_headers"]


class TestInspectionFailCascade:
    """transitive_cascade / inspection_fail_cascade. A FAIL (score 50) cascades:
    permit ISSUED->SUSPENDED -> posture SUSPENDED -> order ROUTED->REJECTED ->
    seating RESERVED->RELEASED."""

    def _setup(self):
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        order = place_order(ctx["food_hall_id"], ctx["stall_id"], gross_amount_cents=1500)
        seat = reserve_seats(ctx["food_hall_id"], 4,
                             "2026-06-15T18:00:00Z", "2026-06-15T20:00:00Z",
                             order_id=order["id"])
        return ctx, order, seat

    def test_fail_suspends_permit_and_posture(self, api):
        """PRD §3.3: "A `FAIL` triggers a cascade: the stall's latest `ISSUED`
        health permit is driven to `SUSPENDED`; that permit suspension recomputes
        the stall's `operational_posture` to `SUSPENDED`; that posture flip then
        auto-rejects the stall's live orders (those in `ROUTED` or `ACCEPTED`
        status), moving each to `REJECTED`; and each such rejected order releases
        its `RESERVED` seating allocation, moving it to `RELEASED` and freeing those
        seats."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade
        """
        ctx, order, seat = self._setup()
        insp = conduct_inspection(ctx["stall_id"], 50, scheduled_for="2026-06-15T19:00:00Z")
        assert insp["result"] == "FAIL"

        permit = validate_success(api.get_permit(ctx["permit_id"], HI), 200)
        assert permit["status"] == "SUSPENDED"
        stall = validate_success(api.get_stall(ctx["stall_id"], HM), 200)
        assert stall["operational_posture"] == "SUSPENDED"

    def test_fail_rejects_order_and_releases_seating(self, api):
        """PRD §3.3: "A `FAIL` triggers a cascade: the stall's latest `ISSUED`
        health permit is driven to `SUSPENDED`; that permit suspension recomputes
        the stall's `operational_posture` to `SUSPENDED`; that posture flip then
        auto-rejects the stall's live orders (those in `ROUTED` or `ACCEPTED`
        status), moving each to `REJECTED`; and each such rejected order releases
        its `RESERVED` seating allocation, moving it to `RELEASED` and freeing those
        seats."

        Design: Difficulty/transitive_cascade/inspection_fail_cascade
        """
        ctx, order, seat = self._setup()
        conduct_inspection(ctx["stall_id"], 50, scheduled_for="2026-06-15T19:00:00Z")

        order_after = validate_success(api.get_order(order["id"], HM), 200)
        assert order_after["status"] == "REJECTED"
        seat_after = validate_success(api.get_seating_allocation(seat["id"], HM), 200)
        assert seat_after["status"] == "RELEASED"


class TestVendorSuspensionCascade:
    """transitive_cascade / vendor_suspension_cascade. Suspending the vendor flips
    its stall's posture to SUSPENDED -> order REJECTED -> seating RELEASED."""

    def _setup(self):
        ctx = open_stall(clock="2026-06-15T18:00:00Z")
        order = place_order(ctx["food_hall_id"], ctx["stall_id"], gross_amount_cents=1500)
        seat = reserve_seats(ctx["food_hall_id"], 4,
                             "2026-06-15T18:00:00Z", "2026-06-15T20:00:00Z",
                             order_id=order["id"])
        return ctx, order, seat

    def test_suspend_flips_posture_and_rejects_order(self, api):
        """PRD §3.5: "When a `HallManager` suspends an `ACTIVE` vendor, then for
        every stall whose `current_vendor_id` is that vendor, the stall's
        `operational_posture` is recomputed and falls to `SUSPENDED` because the
        vendor is no longer `ACTIVE`; each such flip to `SUSPENDED` auto-rejects that
        stall's `ROUTED` and `ACCEPTED` orders, moving them to `REJECTED`; and each
        rejected order releases its `RESERVED` seating allocation to `RELEASED`,
        freeing those seats."

        Design: Difficulty/transitive_cascade/vendor_suspension_cascade
        """
        ctx, order, seat = self._setup()
        validate_success(api.suspend_vendor(ctx["vendor_id"], HM), 200)

        stall = validate_success(api.get_stall(ctx["stall_id"], HM), 200)
        assert stall["operational_posture"] == "SUSPENDED"
        order_after = validate_success(api.get_order(order["id"], HM), 200)
        assert order_after["status"] == "REJECTED"

    def test_suspend_releases_linked_seating(self, api):
        """PRD §3.5: "When a `HallManager` suspends an `ACTIVE` vendor, then for
        every stall whose `current_vendor_id` is that vendor, the stall's
        `operational_posture` is recomputed and falls to `SUSPENDED` because the
        vendor is no longer `ACTIVE`; each such flip to `SUSPENDED` auto-rejects that
        stall's `ROUTED` and `ACCEPTED` orders, moving them to `REJECTED`; and each
        rejected order releases its `RESERVED` seating allocation to `RELEASED`,
        freeing those seats."

        Design: Difficulty/transitive_cascade/vendor_suspension_cascade
        """
        ctx, order, seat = self._setup()
        validate_success(api.suspend_vendor(ctx["vendor_id"], HM), 200)

        seat_after = validate_success(api.get_seating_allocation(seat["id"], HM), 200)
        assert seat_after["status"] == "RELEASED"
