"""The daily sweep (PRD §2.5), run whenever the logical clock is set.

Five jobs, in order: license expiry, permit expiry, plan lapse, deficiency
late-fee accrual, impairment OUT_OF_SERVICE promotion — plus monthly compounding
of unpaid backflow balances. After mutations, every contractor's provisional
score and posture are recomputed (overdue sets shift with the clock).
"""

from datetime import date, timedelta

from db import store
from services.core import touch
from services import calc


def _expire_licenses(today):
    for lic in list(store.license_records.values()):
        if lic["status"] == "ACTIVE" and today > lic["expires_on"]:
            lic["status"] = "EXPIRED"
            touch(lic)
            tech = store.technicians.get(lic["technician_id"])
            if tech is not None:
                touch(tech)


def _expire_permits(today):
    for perm in list(store.permits.values()):
        if perm["status"] == "ISSUED" and perm.get("_issued_date") is not None:
            if today > perm["_issued_date"] + timedelta(days=calc.PERMIT_VALIDITY_DAYS):
                perm["status"] = "EXPIRED"
                touch(perm)


def _lapse_plans(today):
    for plan in list(store.plans.values()):
        if plan["plan_posture"] in ("SCHEDULED", "IN_PROGRESS") \
                and today > date(plan["plan_year"], 12, 31):
            calc.derive_plan_posture(plan)


def _accrue_deficiency_late_fees(today):
    for d in list(store.deficiencies.values()):
        if d["status"] == "OPEN" and d["correction_deadline"] is not None and today > d["correction_deadline"]:
            fee = calc.deficiency_late_fee_cents(d, today)
            if d["late_fee_cents"] != fee:
                d["late_fee_cents"] = fee
                touch(d)


def _promote_impairments():
    for sys in list(store.systems.values()):
        calc.derive_impairment_status(sys)


def _compound_backflow_balances(today):
    for bt in list(store.backflow_tests.values()):
        if bt["status"] != "INVOICED" or bt.get("_invoiced_date") is None:
            continue
        due = bt["_invoiced_date"] + timedelta(days=calc.BACKFLOW_PAYMENT_DUE_DAYS)
        months_late = calc.whole_months_between(due, today)
        balance = calc.backflow_penalty_balance_cents(months_late)
        if bt["unpaid_balance_cents"] != balance:
            bt["unpaid_balance_cents"] = balance
            touch(bt)


def run_daily_sweep():
    today = store.today()
    _expire_licenses(today)
    _expire_permits(today)
    _lapse_plans(today)
    _accrue_deficiency_late_fees(today)
    _promote_impairments()
    _compound_backflow_balances(today)
    for con in list(store.contractors.values()):
        calc.recompute_contractor(con)
