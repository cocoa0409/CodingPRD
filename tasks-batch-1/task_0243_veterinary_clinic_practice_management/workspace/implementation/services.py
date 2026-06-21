"""Business-logic services: cascades, deposits, surgery booking math,
invoice finalization, wellness realized savings, resource-overlap geometry.
"""
from datetime import timedelta

import db
import calculations as calc
from calculations import parse_dt


# -----------------------------------------------------------------------------
# Wellness plan helpers
# -----------------------------------------------------------------------------
def active_plan_for_patient(patient_id):
    """The patient's ACTIVE WellnessPlan, if any (plans are always ACTIVE here)."""
    for wp in db.wellness_plans.values():
        if wp["patient_id"] == patient_id and wp["status"] == "ACTIVE":
            return wp
    return None


# -----------------------------------------------------------------------------
# Kennel occupancy (PRD §3.9 / validation 12): count non-CANCELLED stays per day
# -----------------------------------------------------------------------------
def _stay_days(stay):
    ci = parse_dt(stay["check_in_date"]).date()
    co = parse_dt(stay["check_out_date"]).date()
    days = []
    d = ci
    while d <= co:
        days.append(d)
        d = d + timedelta(days=1)
    return days


def kennel_capacity_ok(kennel_id, new_check_in, new_check_out, capacity):
    """For each inclusive day spanned by the new stay, the count of existing
    non-CANCELLED stays covering that day (plus the new stay) must stay <= capacity.
    """
    ci = parse_dt(new_check_in).date()
    co = parse_dt(new_check_out).date()
    new_days = []
    d = ci
    while d <= co:
        new_days.append(d)
        d = d + timedelta(days=1)

    # Pre-compute occupancy per day from existing non-cancelled stays in this kennel.
    occupancy = {}
    for stay in db.boarding_stays.values():
        if stay["kennel_id"] != kennel_id:
            continue
        if stay["status"] == "CANCELLED":
            continue
        for day in _stay_days(stay):
            occupancy[day] = occupancy.get(day, 0) + 1

    for day in new_days:
        if occupancy.get(day, 0) + 1 > capacity:
            return False
    return True


# -----------------------------------------------------------------------------
# Operatory overlap geometry (PRD §3.8 / validation 11):
# half-open [start, end+buffer) must not overlap any non-cancelled surgery's
# equivalently-buffered interval in the same operatory.
# -----------------------------------------------------------------------------
def operatory_conflict(operatory_id, buffer_minutes, new_start, new_end):
    ns = parse_dt(new_start)
    ne = parse_dt(new_end) + timedelta(minutes=buffer_minutes)
    for sg in db.surgeries.values():
        if sg["operatory_id"] != operatory_id:
            continue
        if sg["status"] == "CANCELLED":
            continue
        es = parse_dt(sg["window_start"])
        ee = parse_dt(sg["window_end"]) + timedelta(minutes=buffer_minutes)
        # half-open overlap: intervals [ns, ne) and [es, ee) overlap iff ns < ee and es < ne
        if ns < ee and es < ne:
            return True
    return False


# -----------------------------------------------------------------------------
# Surgery deposit commit at booking (PRD §3.8)
# -----------------------------------------------------------------------------
def commit_surgery_deposit(surgery, estimate):
    """deposit_consumed := min(estimate.deposit_posted, surgery_total);
    debit household credit, reduce estimate deposit_posted, bump household version.
    """
    consumed = min(estimate["deposit_posted_cents"], surgery["surgery_total_cents"])
    surgery["deposit_consumed_cents"] = consumed
    if consumed > 0:
        estimate["deposit_posted_cents"] -= consumed
        db.touch(estimate)
        patient = db.patients[estimate["patient_id"]]
        household = db.households[patient["household_id"]]
        household["account_credit_cents"] -= consumed
        db.touch(household)
    return consumed


def refund_surgery_deposit(surgery):
    """Cancel-time refund: deposit_consumed back to household credit AND back to
    the funding estimate's deposit_posted; bump household version; reset to 0.
    """
    consumed = surgery.get("deposit_consumed_cents", 0)
    if consumed > 0:
        estimate = db.estimates.get(surgery["estimate_id"])
        if estimate is not None:
            estimate["deposit_posted_cents"] += consumed
            db.touch(estimate)
            patient = db.patients.get(estimate["patient_id"])
            if patient is not None:
                household = db.households.get(patient["household_id"])
                if household is not None:
                    household["account_credit_cents"] += consumed
                    db.touch(household)
    surgery["deposit_consumed_cents"] = 0


# -----------------------------------------------------------------------------
# Cascade: appointment cancel (PRD §3.3, Rule 4 A)
# -----------------------------------------------------------------------------
def cascade_appointment_cancel(appointment):
    aid = appointment["id"]
    # hop 1: surgeries on this appointment in BOOKED/IN_PROGRESS -> CANCELLED
    for sg in db.surgeries.values():
        if sg["appointment_id"] != aid:
            continue
        if sg["status"] in ("BOOKED", "IN_PROGRESS"):
            minutes = calc.window_minutes(sg["window_start"], sg["window_end"])
            sg["status"] = "CANCELLED"
            # hop 2: release operatory minutes
            op = db.operatories.get(sg["operatory_id"])
            if op is not None:
                op["booked_minutes"] -= minutes
                db.touch(op)
            # hop 3: refund deposit to funding estimate's household
            refund_surgery_deposit(sg)
            db.touch(sg)
    # parallel hop-1 target: lab orders ORDERED/COLLECTED -> CANCELLED
    for lo in db.lab_orders.values():
        if lo["appointment_id"] != aid:
            continue
        if lo["status"] in ("ORDERED", "COLLECTED"):
            lo["status"] = "CANCELLED"
            db.touch(lo)


# -----------------------------------------------------------------------------
# Cascade: patient mark-deceased (PRD §3.1, Rule 4 B)
# -----------------------------------------------------------------------------
def cascade_patient_deceased(patient):
    pid = patient["id"]
    # hop 1: ACTIVE prescriptions -> VOIDED; hop 2: restore refills_used to 0
    for rx in db.prescriptions.values():
        if rx["patient_id"] != pid:
            continue
        if rx["status"] == "ACTIVE":
            rx["status"] = "VOIDED"
            rx["refills_used"] = 0
            db.touch(rx)
    # parallel hop-1 target: RESERVED/CHECKED_IN boarding stays -> CANCELLED
    for stay in db.boarding_stays.values():
        if stay["patient_id"] != pid:
            continue
        if stay["status"] in ("RESERVED", "CHECKED_IN"):
            stay["status"] = "CANCELLED"
            db.touch(stay)


# -----------------------------------------------------------------------------
# Wellness realized savings on appointment complete (PRD §3.2)
# -----------------------------------------------------------------------------
def settle_realized_savings(appointment):
    # PRD §3.2 walks "discount-eligible" rendered work on appointment-complete.
    # AMBIGUITY: LabOrder/Surgery/Vaccination entities carry NO eligible_for_plan_discount
    # field (only Estimate line_items do, per §1.1). With no stored eligibility flag on
    # rendered entities, this discount walk contributes 0; the bundled-vaccine waived-fee
    # increment (the one concretely-triggered realized-savings effect) is applied at
    # vaccination time, not here. The walk is retained defensively and yields 0 unless a
    # discount-eligibility flag is ever set on these records.
    plan = active_plan_for_patient(appointment["patient_id"])
    if plan is None:
        return
    aid = appointment["id"]
    items = []
    # RESULTED lab orders on the appointment
    for lo in db.lab_orders.values():
        if lo["appointment_id"] == aid and lo["status"] == "RESULTED":
            if lo.get("eligible_for_plan_discount"):
                items.append((lo["_seq"], lo["fee_cents"]))
    # DONE surgeries on the appointment
    for sg in db.surgeries.values():
        if sg["appointment_id"] == aid and sg["status"] == "DONE":
            if sg.get("eligible_for_plan_discount"):
                items.append((sg["_seq"], sg["surgery_total_cents"]))
    # administered non-bundled vaccinations marked discount-eligible
    for v in db.vaccinations.values():
        if v["patient_id"] != appointment["patient_id"]:
            continue
        if v.get("bundled"):
            continue
        if v.get("eligible_for_plan_discount"):
            items.append((v["_seq"], v["fee_cents"]))
    items.sort(key=lambda t: t[0])
    accrued = 0
    for _seq, gross in items:
        accrued += calc.round_half_up(gross * plan["service_discount_pct"])
    if accrued:
        plan["realized_savings_cents"] += accrued
        db.touch(plan)
