"""Benefit routing and the allocation waterfall (calculations.benefit_route / benefit_allocation)."""
from decimal import Decimal

from services.domain import (DENTAL_RATE, MEDICAL_LEANING_CATEGORIES,
                             MEDICAL_RATE, get_case, get_patient)
from timeutil import rcents


def service_line_total(service_lines):
    return sum(int(line["charge_cents"]) for line in service_lines)


def route_for(patient):
    medical = bool(patient.get("medical_plan_active"))
    dental = bool(patient.get("dental_plan_active"))
    if medical and dental:
        return "SPLIT"
    if medical:
        return "MEDICAL_PRIMARY"
    if dental:
        return "DENTAL_PRIMARY"
    return "SELF_PAY"


def primary_payer_for(route, case):
    if route == "SPLIT":
        return "MEDICAL" if case["procedure_category"] in MEDICAL_LEANING_CATEGORIES else "DENTAL"
    if route == "MEDICAL_PRIMARY":
        return "MEDICAL"
    if route == "DENTAL_PRIMARY":
        return "DENTAL"
    return None


def allocate(service_lines, route, primary_payer, snapshot_cents, total_charge_cents):
    remaining_dental = int(snapshot_cents)
    medical_allowed = 0
    dental_allowed = 0

    if route == "SELF_PAY":
        medical_allowed = 0
        dental_allowed = 0
    elif primary_payer == "MEDICAL":
        for line in service_lines:
            medical_allowed += rcents(Decimal(int(line["charge_cents"])) * MEDICAL_RATE)
        if route == "SPLIT":
            for line in service_lines:
                charge = int(line["charge_cents"])
                residual = charge - rcents(Decimal(charge) * MEDICAL_RATE)
                want = rcents(Decimal(residual) * DENTAL_RATE)
                paid = min(want, remaining_dental)
                remaining_dental -= paid
                dental_allowed += paid
    else:
        dental_paid_per_line = []
        for line in service_lines:
            charge = int(line["charge_cents"])
            want = rcents(Decimal(charge) * DENTAL_RATE)
            paid = min(want, remaining_dental)
            remaining_dental -= paid
            dental_allowed += paid
            dental_paid_per_line.append(paid)
        if route == "SPLIT":
            for line, paid in zip(service_lines, dental_paid_per_line):
                residual = int(line["charge_cents"]) - paid
                medical_allowed += rcents(Decimal(residual) * MEDICAL_RATE)

    responsibility = int(total_charge_cents) - medical_allowed - dental_allowed
    return medical_allowed, dental_allowed, responsibility


def recompute_determination(determination, snapshot_cents):
    """Refresh route, payer and the three money fields from the stored service lines."""
    case = get_case(determination["case_id"])
    patient = get_patient(case["patient_id"])
    route = route_for(patient)
    payer = primary_payer_for(route, case)
    determination["route"] = route
    determination["primary_payer"] = payer
    determination["dental_annual_remaining_snapshot_cents"] = int(snapshot_cents)
    medical, dental, responsibility = allocate(
        determination["service_lines"], route, payer, snapshot_cents,
        int(case["total_charge_cents"]),
    )
    determination["medical_allowed_cents"] = medical
    determination["dental_allowed_cents"] = dental
    determination["patient_responsibility_cents"] = responsibility
    return determination
