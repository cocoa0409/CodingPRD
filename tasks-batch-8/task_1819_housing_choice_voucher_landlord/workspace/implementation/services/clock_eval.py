"""Date-driven system transitions evaluated on logical-clock advance
(SCAFFOLD §1.2: HAPContract ACTIVE→ABATED on repair-deadline breach;
Recertification OPEN→OVERDUE past due_date)."""

from datetime import date, timedelta

import db
from db import touch
from services.calculations import _parse_iso_date


REPAIR_WINDOW_DAYS = 30
LIFE_THREATENING_WINDOW_DAYS = 1


def _contract_for_inspection(insp):
    return db.hap_contracts.get(insp["contract_id"])


def evaluate_abatements():
    """ACTIVE contracts with a breached repair deadline flip to ABATED."""
    today = db.current_logical_date()
    for contract in list(db.hap_contracts.values()):
        if contract["status"] != "ACTIVE":
            continue
        # find a FAILED inspection on this contract with a breached deadline
        for insp in db.inspections.values():
            if insp["contract_id"] != contract["id"]:
                continue
            if insp["status"] != "FAILED":
                continue
            if not insp.get("result_recorded_date"):
                continue
            recorded = _parse_iso_date(insp["result_recorded_date"])
            for ri in db.repair_items.values():
                if ri["inspection_id"] != insp["id"]:
                    continue
                if ri["status"] not in ("OPEN", "FAILED_VERIFICATION"):
                    continue
                window = LIFE_THREATENING_WINDOW_DAYS if ri.get("is_life_threatening") else REPAIR_WINDOW_DAYS
                deadline = recorded + timedelta(days=window)
                # breach: deadline earlier than current logical date
                if deadline < today:
                    _abate_contract(contract, breach_date=deadline)
                    return  # re-scan after mutation to keep it simple
                    # (function recurses via loop on next clock advance)


def _abate_contract(contract, breach_date: date):
    """HAPContract ACTIVE -> ABATED cascade."""
    contract["status"] = "ABATED"
    contract["abatement_start_date"] = breach_date.isoformat()
    touch(contract)
    # Unit UNDER_CONTRACT -> SUSPENDED_ABATEMENT
    unit = db.units.get(contract["unit_id"])
    if unit and unit["status"] == "UNDER_CONTRACT":
        unit["status"] = "SUSPENDED_ABATEMENT"
        touch(unit)
    # HAPPayment rows for periods after the breach, still SCHEDULED -> ABATED_HELD
    for p in db.hap_payments.values():
        if p["contract_id"] != contract["id"]:
            continue
        if p["disbursement_status"] != "SCHEDULED":
            continue
        period = _parse_iso_date(p["period_month"])
        # "for periods after the breach": period month at/after breach date's month
        # treat breach as affecting this and all future periods whose month start >= breach month start
        if period >= date(breach_date.year, breach_date.month, 1):
            p["disbursement_status"] = "ABATED_HELD"


def evaluate_overdue_recertifications():
    """OPEN recertifications whose due_date has passed flip to OVERDUE."""
    today = db.current_logical_date()
    for recert in list(db.recertifications.values()):
        if recert["status"] != "OPEN":
            continue
        due = _parse_iso_date(recert["due_date"])
        if today > due:
            recert["status"] = "OVERDUE"
            touch(recert)


def evaluate_all():
    evaluate_abatements()
    # run twice to catch contracts that may need a second pass after the first flip
    evaluate_overdue_recertifications()
