"""Transitive cascades and compensating invariants (PRD §2.7, §2.10, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_money_equal,
    assert_weight_equal,
    clear_hwb,
    consolidate_hwb,
    create_hwb,
    deconsolidate_hwb,
    get_booking,
    get_hwb,
    get_mawb,
    setup_consolidated,
    setup_lane,
    validate_success,
)


def _setup_consolidated_plus_cleared():
    """HWB-A consolidated (100.0 kg / 475.00) and HWB-B cleared but unattached."""
    ctx = setup_consolidated(hwb_number="HWB-A")
    hwb_b = create_hwb(
        ctx["shipper"]["id"], "HWB-B", pieces=1, gross_weight_kg=10.0,
        declared_volume_m3=0.05,
    )
    clear_hwb(hwb_b["id"])
    ctx["hwb_b"] = hwb_b
    return ctx


class TestBookingCancelCascade:
    def test_cancel_voids_mawb_detaches_hwb_and_recomputes_booking(
        self, api, capacity_planner_headers
    ):
        """PRD §2.10: "Link one: every master waybill of the booking in `DRAFT`,
        `OPEN_FOR_CONSOLIDATION`, or `TENDERED` becomes `VOID`. Link two, caused by
        each voiding: every house waybill attached to a voided master waybill in
        `CONSOLIDATED` or `TENDERED` returns to `CLEARED`, detached — its `mawb_id`
        cleared, every charge line zeroed, the spot flag cleared, its rating basis
        reset, and the voided master waybill's totals zeroed. Link three, caused by
        the detachments: the booking's consumption and utilization are recomputed over
        the waybills that remain attached."

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3
        """
        ctx = _setup_consolidated_plus_cleared()
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 100.0,
            "consumed_weight_kg",
        )

        cancelled = validate_success(
            api.cancel_flight_booking(ctx["booking"]["id"], capacity_planner_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        assert_weight_equal(cancelled["consumed_weight_kg"], 0.0, "consumed_weight_kg")
        assert cancelled["utilization_pct"] == pytest.approx(0.0, abs=1e-6)

        assert get_mawb(ctx["mawb"]["id"])["status"] == "VOID", (
            "link 1: the booking's open master waybill is voided"
        )
        detached = get_hwb(ctx["hwb"]["id"])
        assert detached["status"] == "CLEARED", "link 2: attached waybill detaches"
        assert detached["mawb_id"] is None
        assert_money_equal(detached["total_charge_amount"], 0.00, "total_charge_amount")
        assert detached["weight_basis"] == "UNRATED"

    def test_cancel_leaves_unconsolidated_waybill_untouched(
        self, api, capacity_planner_headers
    ):
        """PRD §2.10: "Link two, caused by each voiding: every house waybill attached
        to a voided master waybill in `CONSOLIDATED` or `TENDERED` returns to
        `CLEARED`, detached"

        Design: Difficulty/transitive_cascade/booking_cancel_cascade_depth3
        """
        ctx = _setup_consolidated_plus_cleared()
        validate_success(api.cancel_flight_booking(ctx["booking"]["id"], capacity_planner_headers))

        untouched = get_hwb(ctx["hwb_b"]["id"])
        assert untouched["status"] == "CLEARED", (
            "the detach cascade touches only waybills attached to a voided MAWB"
        )
        assert untouched["mawb_id"] is None


class TestConsumedWeightConservation:
    def _setup_two_cleared(self):
        ctx = setup_lane()
        hwb_a = create_hwb(ctx["shipper"]["id"], "HWB-A")  # 100.0 kg chargeable
        clear_hwb(hwb_a["id"])
        hwb_b = create_hwb(
            ctx["shipper"]["id"], "HWB-B", pieces=20, gross_weight_kg=400.0,
            declared_volume_m3=1.0,
        )  # 400.0 kg chargeable
        clear_hwb(hwb_b["id"])
        return ctx, hwb_a, hwb_b

    def test_consumed_weight_after_each_consolidation(self, api):
        """PRD §2.7: "The weight contribution of each counted waybill is its
        `chargeable_weight_kg`; the volume contribution is its `effective_volume_m3`."
        PRD §2.7: "all three are recomputed every time the attached set or any
        member's rated weight or volume changes: at consolidation, at deconsolidation,
        at tender, at waybill detach during a void, and at booking cancellation."

        Design: Difficulty/compensating_invariant/booking_consumed_weight_conservation
        """
        ctx, hwb_a, hwb_b = self._setup_two_cleared()
        consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 100.0,
            "consumed after A",
        )
        consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 500.0,
            "consumed after A+B",
        )

    def test_consumed_weight_after_each_deconsolidation(self, api):
        """PRD §3.4: "Deconsolidation is the compensating action, also `ForwarderOps`:
        removing a waybill that is `CONSOLIDATED` under the named master waybill — the
        master waybill `id` and the `houseWaybillId` are both identified in the
        request path — returns it to `CLEARED`"
        PRD §3.4: "The master waybill's totals are recomputed and its `version`
        increments by one, and booking consumption is recomputed."

        Design: Difficulty/compensating_invariant/booking_consumed_weight_conservation
        """
        ctx, hwb_a, hwb_b = self._setup_two_cleared()
        consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])

        deconsolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 400.0,
            "consumed after removing A is exactly B's chargeable weight",
        )

        deconsolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert_weight_equal(
            get_booking(ctx["booking"]["id"])["consumed_weight_kg"], 0.0,
            "the compensate pair leaves zero drift",
        )


class TestMawbChargesConservation:
    def _setup_two_cleared(self):
        ctx = setup_lane()
        hwb_a = create_hwb(ctx["shipper"]["id"], "HWB-A")  # total 475.00
        clear_hwb(hwb_a["id"])
        hwb_b = create_hwb(
            ctx["shipper"]["id"], "HWB-B", pieces=20, gross_weight_kg=400.0,
            declared_volume_m3=1.0,
        )  # total 1825.00: 1600.00 freight + 200.00 fuel + 25.00 security
        clear_hwb(hwb_b["id"])
        return ctx, hwb_a, hwb_b

    def test_mawb_freight_total_after_each_consolidation(self, api):
        """PRD §3.4: "A successful consolidation mutates three resources atomically."
        PRD §3.4: "The master waybill: totals recomputed and `version` incremented by
        exactly one."

        Design: Difficulty/compensating_invariant/mawb_charges_conservation
        """
        ctx, hwb_a, hwb_b = self._setup_two_cleared()
        rated_a = consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        assert_money_equal(rated_a["total_charge_amount"], 475.00, "A total_charge_amount")
        assert_money_equal(
            get_mawb(ctx["mawb"]["id"])["total_freight_amount"], 475.00,
            "mawb total after A",
        )

        rated_b = consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert_money_equal(rated_b["total_charge_amount"], 1825.00, "B total_charge_amount")
        assert_money_equal(
            get_mawb(ctx["mawb"]["id"])["total_freight_amount"], 2300.00,
            "mawb total after A+B == 475.00 + 1825.00",
        )

    def test_mawb_freight_total_after_deconsolidation_zeroes_the_removed(self, api):
        """PRD §3.4: "removing a waybill that is `CONSOLIDATED` under the named master
        waybill — the master waybill `id` and the `houseWaybillId` are both identified
        in the request path — returns it to `CLEARED`, clears `mawb_id` to null,
        zeroes every charge line and `chargeable_weight_kg`, clears both spot fields,
        resets `weight_basis` to `UNRATED`, and nulls `rate_agreement_id`."

        Design: Difficulty/compensating_invariant/mawb_charges_conservation
        """
        ctx, hwb_a, hwb_b = self._setup_two_cleared()
        consolidate_hwb(ctx["mawb"]["id"], hwb_a["id"])
        consolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])

        removed = deconsolidate_hwb(ctx["mawb"]["id"], hwb_b["id"])
        assert removed["status"] == "CLEARED"
        assert_money_equal(removed["total_charge_amount"], 0.00, "removed total_charge_amount")
        assert removed["weight_basis"] == "UNRATED"
        assert removed["mawb_id"] is None

        assert_money_equal(
            get_mawb(ctx["mawb"]["id"])["total_freight_amount"], 475.00,
            "the surviving waybill's total remains — no drift in the money invariant",
        )
