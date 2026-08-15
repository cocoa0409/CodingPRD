"""Daily operations sweep (PRD 2.5, 3.5, 3.7, 3.8).

Performs system-side scheduled work against the logical clock:
  1. reminder outreach for ACTIVE supply plans approaching eligibility,
  2. rental-contract activation (SCHEDULED -> BILLING) at the first monthly
     anniversary,
  3. patient discontinuation finalization (DISCONTINUING -> DISCONTINUED) as a
     backstop when a linked retrieval case has closed.
"""
from db import db
from services.core import (
    cadence_days_for,
    cascade_patient_discontinued,
    payer_for_patient,
    touch,
)
from util import add_days, add_months, parse_date, today

REMINDER_LOOKAHEAD_DAYS = 7


def run_daily_sweep():
    current = today()
    reminders_sent = 0
    rental_activations = 0
    patient_discontinuations = 0

    # --- 1. Reminder outreach (PRD 3.5) ---
    for plan in db["component_supply_plans"].values():
        if plan["plan_status"] != "ACTIVE":
            continue
        last = plan.get("last_dispensed_on")
        if last is None:
            continue  # first fill not yet dispensed: nothing to remind about
        patient = db["patients"].get(plan["patient_id"])
        payer = payer_for_patient(patient)
        if payer is None:
            continue
        next_eligible = add_days(parse_date(last), cadence_days_for(payer, plan["component_type"]))
        lookahead = add_days(next_eligible, -REMINDER_LOOKAHEAD_DAYS)
        if current >= lookahead:
            sent = plan.get("reminder_sent_on")
            if sent is None or parse_date(sent) < lookahead:
                plan["reminder_sent_on"] = current.isoformat()
                touch(plan)
                reminders_sent += 1

    # --- 2. Rental activation (PRD 3.7) ---
    for contract in db["rental_contracts"].values():
        if contract["billing_status"] != "SCHEDULED":
            continue
        activation = add_months(parse_date(contract["rental_start_on"]), 1)
        if current >= activation:
            contract["billing_status"] = "BILLING"
            touch(contract)
            rental_activations += 1

    # --- 3. Discontinuation finalization backstop (PRD 3.8) ---
    for case in db["retrieval_cases"].values():
        if case["retrieval_status"] not in ("RECONCILED", "CLOSED_UNRECOVERABLE"):
            continue
        patient = db["patients"].get(case["patient_id"])
        if patient is None or patient["patient_status"] != "DISCONTINUING":
            continue
        recovered = case["retrieval_status"] == "RECONCILED"
        if cascade_patient_discontinued(patient, case.get("device_enrollment_id"), recovered):
            patient_discontinuations += 1

    return {
        "reminders_sent": reminders_sent,
        "rental_activations": rental_activations,
        "patient_discontinuations": patient_discontinuations,
    }
