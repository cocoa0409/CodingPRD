"""Logical-clock-driven laminate expiry and its cascade (PRD §2.5, §3.5)."""
from test_helpers import (
    validate_success, get_success_data,
    ApiErrorId,
    assert_same_instant,
    create_laminate_lot, get_laminate_lot, prepare_order, set_clock,
    TEST_USERS,
)

PLANNER = TEST_USERS["production_planner_headers"]


class TestClockExpiryCascade:
    def test_clock_set_past_expiry_cascades(self, api):
        """PRD §3.5: "When the logical clock reaches a lot's `expiry_date` —
        re-evaluated both when the clock is set and on every access to the lot —
        ... a `QUALIFIED` lot fires a two-link cascade: every `RESERVED`
        reservation of the lot flips to `RELEASED`, and each affected order then
        re-evaluates its material coverage, so an order sitting in
        `AWAITING_LAMINATE` whose remaining `RESERVED` coverage has fallen below
        its released array's `panels_required` drops to `ON_HOLD`".

        Design: Difficulty/transitive_cascade/clock_expiry_cascade
        """
        # Ship 2026-08-09 is strictly before expiry 2026-08-10, so the
        # reservation is admitted; the default clock 2026-08-01 precedes expiry.
        ctx = prepare_order(
            company_name="Theta Circuits", contact_email="ops@theta.example",
            requested_ship_date="2026-08-09T00:00:00Z",
            lot_code="LOT-E1", manufacture_date="2025-08-10T00:00:00Z",
            panels_total=100, panels_to_reserve=34,
        )
        assert ctx["order"]["fab_status"] == "AWAITING_LAMINATE"
        assert ctx["reservation"]["status"] == "RESERVED"

        # Advance the clock past the lot's expiry date (2026-08-10). PRD §2.5
        # pins the instant ("responds with the resulting current_utc"), not
        # its string form.
        result = set_clock("2026-08-11T00:00:00Z")
        assert_same_instant(result["current_utc"], "2026-08-11T00:00:00Z")

        lot = get_laminate_lot(ctx["lot"]["id"])
        assert lot["status"] == "EXPIRED", (
            f"clock past expiry_date must expire the lot, got {lot['status']}"
        )
        assert lot["panels_reserved"] == 0

        reservation = get_success_data(
            api.get_reservation(ctx["reservation"]["id"], PLANNER)
        )
        assert reservation["status"] == "RELEASED", (
            "link 1 of the expiry cascade: RESERVED -> RELEASED"
        )

        order = get_success_data(api.get_fab_order(ctx["order"]["id"], PLANNER))
        assert order["fab_status"] == "ON_HOLD", (
            f"link 2 of the expiry cascade: coverage 0 < 34 drops the order to "
            f"ON_HOLD, got {order['fab_status']}"
        )

    def test_received_lot_expires_lazily_on_access(self, api):
        """PRD §3.5: "When the logical clock reaches a lot's `expiry_date` —
        re-evaluated both when the clock is set and on every access to the lot —
        a `RECEIVED` lot simply becomes `EXPIRED`" and "its `expiry_date` is
        exactly 365 days after `manufacture_date`".

        Design: Difficulty/transitive_cascade/clock_expiry_cascade
        """
        # Manufacture 2025-08-01 -> expiry 2026-08-01T00:00:00Z == default clock.
        lot = create_laminate_lot(
            "LOT-LAZY1", manufacture_date="2025-08-01T00:00:00Z", panels_total=10,
        )
        lot = get_laminate_lot(lot["id"])
        assert lot["status"] == "EXPIRED", (
            f"a lot at its expiry instant reads EXPIRED on access, got {lot['status']}"
        )
