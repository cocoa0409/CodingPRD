"""Trust account: ledger append, co-pay posting and the grievance reversal (PRD 3.7)."""

import calc
import store
from constants import (
    COPAY_SCHEDULE_CENTS, EXEMPT_ENCOUNTER_TYPES, INDIGENT_LIEN_RATE_PCT,
)


def append_entry(inmate, entry_type, amount_cents, source_copay_charge_id=None, memo=""):
    row = store.base_row(with_version=False)
    row.update({
        "inmate_id": inmate["id"],
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "balance_after_cents": 0,
        "source_copay_charge_id": source_copay_charge_id,
        "memo": memo,
    })
    store.ledger_entries[row["id"]] = row
    calc.recompute_balance(inmate)
    return row


def post_copay_charge(inmate, encounter_type, source_sick_call_id=None):
    """The pinned six-step co-pay order.  Returns (charge, ledger_entry_or_None)."""
    charge = store.base_row()
    charge.update({
        "inmate_id": inmate["id"],
        "encounter_type": encounter_type,
        "source_sick_call_id": source_sick_call_id,
        "reversal_grievance_id": None,
    })

    # Step 1 -- exemption test, before any balance is read.
    if encounter_type in EXEMPT_ENCOUNTER_TYPES:
        charge.update({
            "scheduled_amount_cents": 0,
            "amount_cents": 0,
            "charge_variant": "EXEMPT",
            "status": "WAIVED",
            "indigency_snapshot": False,
        })
        store.copay_charges[charge["id"]] = charge
        return charge, None

    # Step 2 -- schedule lookup.
    scheduled = COPAY_SCHEDULE_CENTS.get(encounter_type, 0)
    # Step 3 -- indigency on the PRE-CHARGE ledger.
    indigent = calc.indigency_determination(inmate)
    charge["scheduled_amount_cents"] = scheduled
    charge["indigency_snapshot"] = indigent

    if not indigent:
        # Step 4 -- FUNDED variant.
        charge["amount_cents"] = scheduled
        charge["charge_variant"] = "FUNDED"
        charge["status"] = "POSTED"
        entry_type = "CHARGE"
    else:
        # Step 5 -- INDIGENT variant.
        charge["amount_cents"] = calc.round_cents(scheduled * INDIGENT_LIEN_RATE_PCT / 100.0)
        charge["charge_variant"] = "INDIGENT"
        charge["status"] = "DEBT_LIEN"
        entry_type = "LIEN"

    store.copay_charges[charge["id"]] = charge
    # Step 6 -- append the entry, then recompute the balance (indigent_flag is
    # derived at read time from that balance).
    entry = append_entry(inmate, entry_type, 0 - charge["amount_cents"],
                         source_copay_charge_id=charge["id"])
    return charge, entry


def reverse_charge(inmate, charge, grievance):
    """Cascade E levels 2..5."""
    charge["status"] = "REVERSED"
    charge["reversal_grievance_id"] = grievance["id"]
    store.touch(charge)
    origin = None
    for entry in calc.inmate_ledger_entries(inmate["id"]):
        if entry.get("source_copay_charge_id") == charge["id"] and entry["entry_type"] in ("CHARGE", "LIEN"):
            origin = entry
    amount = 0 - origin["amount_cents"] if origin is not None else charge["amount_cents"]
    return append_entry(inmate, "REVERSAL", amount, source_copay_charge_id=charge["id"])
