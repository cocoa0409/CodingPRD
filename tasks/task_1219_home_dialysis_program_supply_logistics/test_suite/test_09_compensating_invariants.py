"""Compensating invariants: deliver-then-return conserves on-hand units;
reserve-then-cancel restores chair availability."""
from test_helpers import (
    validate_success, get_success_data,
    create_active_home_patient, create_chair, create_slot, get_patient,
    create_approved_order, schedule_appointment, complete_appointment,
    report_waste_return, verify_waste_return,
    api_client, make_admin_headers, make_patient_headers,
)


class TestDeliverThenReturnRestoresOnHand:
    """Conserved quantity: patient on-hand supply units."""

    def test_deliver_then_full_return_nets_to_zero(self, api):
        """PRD §3.6: "On-hand inventory is a strict accounting identity,
        recomputed from the ledger of physical events: the units delivered
        across the patient's `DELIVERED` appointments, minus the
        `consumption_units` of all the patient's logs regardless of status,
        minus the `total_units` of the patient's `CREDITED` or `VERIFIED`
        waste-return records."
        PRD §3.8: "Approval of a `RETURN` record lands it in `CREDITED`: the
        `total_units` leave on-hand and `credit_cents` is computed."

        Design: Difficulty/compensating_invariant/deliver_then_return_restores_on_hand
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        assert get_patient(pat)["on_hand_units"] == 0
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 30}])
        appt = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                    "2026-05-04T12:00:00Z")
        complete_appointment(appt["id"], 30)
        assert get_patient(pat)["on_hand_units"] == 30
        ret = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 30, "expired": False}])
        verify_waste_return(ret["id"], approved=True)
        assert get_patient(pat)["on_hand_units"] == 0, (
            "deliver 30 then credit-return 30 nets to the pre-delivery value")

    def test_return_credit_computed_independently_of_conservation(self, api):
        """PRD §3.8: "A full-credit allowance of ten units per sku per month
        applies: units previously credited for that sku and month consume the
        allowance (counted only up to ten), and the full-credit portion of this
        line is the smaller of its eligible units and the allowance remaining.
        Whatever eligible units exceed the full-credit portion form the
        overage."
        PRD §3.5: "Fulfillment transitions never change `order_status`, and
        lifecycle transitions never change `fulfillment_status`; both are
        readable on the same entity."

        Design: Difficulty/compensating_invariant/deliver_then_return_restores_on_hand
        """
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        order = create_approved_order(pat, "2026-05",
                                      [{"sku": "DIALYSATE_2L", "quantity": 30}])
        appt = schedule_appointment(order["id"], "2026-05-04T08:00:00Z",
                                    "2026-05-04T12:00:00Z")
        complete_appointment(appt["id"], 30)
        ret = report_waste_return(
            pat, "RETURN", "2026-05",
            [{"sku": "DIALYSATE_2L", "units": 30, "expired": False}])
        credited = verify_waste_return(ret["id"], approved=True)
        # Full tier 10*300 = 3000; overage 20 -> round_half_up(20*300*0.5)=3000.
        assert credited["credit_cents"] == 6000
        order_after = get_success_data(api.get_supply_order(
            order["id"], make_admin_headers("admin-1")))
        assert order_after["fulfillment_status"] == "DELIVERED"
        assert get_patient(pat)["on_hand_units"] == 0


class TestReserveThenCancelRestoresChairAvailability:
    """Conserved quantity: a chair's RESERVED-reservation count for a day."""

    def _setup(self, api):
        ctx = create_active_home_patient()
        pat = ctx["patient"]["id"]
        chair = create_chair(ctx["program"]["id"], chair_code="CH-1")
        return pat, chair

    def test_cancelled_slot_frees_the_interval(self, api):
        """PRD §3.7: "The patient cancels a reservation only while the clock is
        still before `slot_start` (`ERR_SLOT_TOO_LATE_TO_CANCEL`), and only
        from `RESERVED` (`ERR_SLOT_INVALID_STATE`); a `HomeNurse` marks
        attendance by moving `RESERVED` to `COMPLETED`."

        Design: Difficulty/compensating_invariant/reserve_then_cancel_restores_chair_availability
        """
        pat, chair = self._setup(api)
        slot1 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                            "2026-05-10T12:00:00Z")
        cancelled = validate_success(api.cancel_slot_reservation(
            slot1["id"], make_patient_headers(pat)))
        assert cancelled["status"] == "CANCELLED"
        slot2 = validate_success(api.create_slot_reservation(
            {"patient_id": pat, "chair_id": chair["id"],
             "slot_start": "2026-05-10T10:00:00Z",
             "slot_end": "2026-05-10T12:00:00Z"},
            make_patient_headers(pat)), 201)
        assert slot2["status"] == "RESERVED", (
            "cancelled reservations occupy no capacity")

    def test_cancel_does_not_count_as_no_show(self, api):
        """PRD §2.5: "A BackupSlotReservation still `RESERVED` once the clock
        has passed its `slot_end` reads as `NO_SHOW` and increments the
        patient's `no_show_count`."
        PRD §2.3: "Unless otherwise specified, every list endpoint returns its
        rows sorted by `created_at` in ascending order, and pagination slices
        that deterministic order."

        Design: Difficulty/compensating_invariant/reserve_then_cancel_restores_chair_availability
        """
        pat, chair = self._setup(api)
        slot1 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                            "2026-05-10T12:00:00Z")
        validate_success(api.cancel_slot_reservation(slot1["id"],
                                                     make_patient_headers(pat)))
        slot2 = create_slot(pat, chair["id"], "2026-05-10T10:00:00Z",
                            "2026-05-10T12:00:00Z")
        rows = get_success_data(api.list_chair_slot_reservations(
            chair["id"], make_admin_headers("admin-1")))
        assert len(rows) == 2, "exactly 2 rows, no phantom occupancy"
        assert rows[0]["status"] == "CANCELLED"
        assert rows[1]["status"] == "RESERVED"
        assert get_patient(pat)["no_show_count"] == 0, (
            "cancel does not count as a no-show")
