"""Caregiver suspension: the four-hop cascade across allocation, vouchers, booking,
window."""
from test_helpers import (
    COORD,
    assert_hours,
    setup_suspension_scenario,
    validate_success,
)


class TestCaregiverSuspensionFourHopCascade:
    def _suspend(self, api):
        ctx = setup_suspension_scenario()
        caregiver = validate_success(
            api.transition_caregiver(
                ctx["caregiver"]["id"],
                {"target_status": "SUSPENDED", "reason": "safeguarding review"}, COORD),
            200)
        return ctx, caregiver

    def test_suspension_cascade_entity_states(self, api):
        """PRD §3.8: "Every `OPEN` allocation of the caregiver transitions to `FROZEN`
        and increments its `version`."
        PRD §3.8: "Each frozen allocation's `ISSUED` vouchers transition to `REVOKED`"
        PRD §3.8: "Each voucher in `COMMITTED` first has its bookings in
        `PENDING_CONFIRMATION` or `CONFIRMED` cancelled with `cancel_reason`
        `SYSTEM_SUSPENSION`; each cancelled booking frees its availability-window
        overlap count, and a `FULLY_BOOKED` window whose count drops below capacity
        returns to `OPEN`."
        PRD §3.8: "Only after those bookings are cancelled does the `COMMITTED` voucher
        itself transition to `REVOKED` with the same bucket and ledger effects as
        above."

        Design: Difficulty/transitive_cascade/caregiver_suspension_four_hop_cascade
        """
        ctx, caregiver = self._suspend(api)
        assert caregiver["status"] == "SUSPENDED"

        alloc = validate_success(api.get_allocation(ctx["allocation"]["id"], COORD), 200)
        assert alloc["status"] == "FROZEN"

        voucher1 = validate_success(api.get_voucher(ctx["voucher1"]["id"], COORD), 200)
        assert voucher1["status"] == "REVOKED"
        voucher2 = validate_success(api.get_voucher(ctx["voucher2"]["id"], COORD), 200)
        assert voucher2["status"] == "REVOKED"

        booking = validate_success(api.get_booking(ctx["booking"]["id"], COORD), 200)
        assert booking["status"] == "CANCELLED"
        assert booking["cancel_reason"] == "SYSTEM_SUSPENSION"

        windows = validate_success(
            api.list_provider_windows(ctx["provider"]["id"], COORD), 200)
        assert windows[0]["status"] == "OPEN"

    def test_suspension_cascade_allocation_buckets(self, api):
        """PRD §3.8: "on each such voucher `forfeited_hours` is set to
        `authorized_hours` minus `consumed_hours`, the allocation's `reserved_hours` is
        decremented by `forfeited_hours`, its `revoked_hours` is incremented by the
        same, and a `RELEASE` ledger entry is appended for the remaining provisional
        encumbrance."

        Design: Difficulty/transitive_cascade/caregiver_suspension_four_hop_cascade
        """
        ctx, _caregiver = self._suspend(api)
        alloc = validate_success(api.get_allocation(ctx["allocation"]["id"], COORD), 200)
        # Two 10.00h vouchers revoked: reserved 20.00 -> 0.00, revoked 0.00 -> 20.00,
        # available stays 60.00.
        assert_hours(alloc["revoked_hours"], 20.00, "revoked_hours")
        assert_hours(alloc["reserved_hours"], 0.00, "reserved_hours")
        assert_hours(alloc["available_hours"], 60.00, "available_hours")
