"""Shared ProductionRun mutations used by more than one endpoint:
the CONFIRMED-run unwind (cancel endpoint + reformulate cascade) and the
customer billing ledger adjustment."""
from db import STORE
from services.calc import supplies_of
from services.core import touch


def adjust_outstanding(customer, delta_cents):
    """outstanding_billed_cents is the account's live billing exposure (§3.1);
    every adjustment mutates the customer record (own version bump, §2.4)."""
    customer["outstanding_billed_cents"] += delta_cents
    touch(customer)


def release_run_reservations(run):
    """Drop packaging reservations made at confirm (reserved -= qpu*planned)."""
    for line in run["packaging_requirements"]:
        comp = STORE.components[line["component_id"]]
        comp["reserved_units"] -= line["quantity_per_unit"] * run["planned_units"]
        touch(comp)


def restore_run_consignment(run):
    """Restore CUSTOMER_SUPPLIED consignment drawn at confirm."""
    for s in supplies_of(run["formula_id"]):
        if s["sourcing_mode"] == "CUSTOMER_SUPPLIED":
            s["consigned_units_on_hand"] += s["quantity_per_unit"] * run["planned_units"]
            touch(s)


def unwind_confirmed_run(run, customer):
    """The full cancel-of-CONFIRMED unwind (§3.5): release reservations,
    restore consignments, refund the estimate."""
    release_run_reservations(run)
    restore_run_consignment(run)
    adjust_outstanding(customer, -run["estimated_charge_cents"])


def cancel_run(run, customer):
    """PLANNED -> CANCELLED is a bare status move; CONFIRMED -> CANCELLED
    unwinds everything confirmation posted. Shared by the cancel endpoint and
    the reformulate cascade (§3.3)."""
    if run["status"] == "CONFIRMED":
        unwind_confirmed_run(run, customer)
    run["status"] = "CANCELLED"
    touch(run)
