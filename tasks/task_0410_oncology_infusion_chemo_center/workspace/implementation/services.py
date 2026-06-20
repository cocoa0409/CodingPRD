"""Shared business-logic services: cascades used by hold/abandon/toxicity-hold."""
from db import db
from store_helpers import touch

DRUG_ORDER_NON_TERMINAL = {"ORDERED", "PREPARED", "VERIFIED"}
APPOINTMENT_NON_TERMINAL = {"SCHEDULED", "CHECKED_IN"}


def cascade_cancel_children(cycle):
    """Two-step cascade: cancel open drug orders, then open appointments.

    Chain step 1: every DrugOrder of this cycle in {ORDERED,PREPARED,VERIFIED} -> CANCELLED.
      A cancelled order that was VERIFIED reverses no reservation (administered_dose_mg
      stays 0; no PriorAuthorization consumption).
    Chain step 2: every InfusionAppointment of this cycle in {SCHEDULED,CHECKED_IN}
      -> CANCELLED, freeing chair+nurse intervals.

    Each mutated child gets its own updated_at refresh and version bump.
    """
    cycle_id = cycle["id"]

    # Step 1 — drug orders
    for order in db.drug_orders.values():
        if order["treatment_cycle_id"] == cycle_id and order["status"] in DRUG_ORDER_NON_TERMINAL:
            order["status"] = "CANCELLED"
            # administered_dose_mg stays 0; no PA consumption reversal needed.
            touch(order, bump_version=True)

    # Step 2 — appointments
    for appt in db.infusion_appointments.values():
        if appt["treatment_cycle_id"] == cycle_id and appt["status"] in APPOINTMENT_NON_TERMINAL:
            appt["status"] = "CANCELLED"
            touch(appt, bump_version=True)


def place_on_hold(cycle):
    """ACTIVE -> ON_HOLD with cascade and version bump on the cycle."""
    cascade_cancel_children(cycle)
    cycle["status"] = "ON_HOLD"
    touch(cycle, bump_version=True)
