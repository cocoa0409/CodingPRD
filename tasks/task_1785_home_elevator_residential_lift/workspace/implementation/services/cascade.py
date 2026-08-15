"""Cascading side effects and logical-clock sweeps (PRD sections 2.4, 3.6, 3.8).

Every cascaded child resource gets its own version increment and updated_at
refresh (via db.touch).
"""

from datetime import timedelta

import db
from util import dec


def restore_visit_if_charged(call):
    """When a MAINTENANCE_VISIT consumed a contract visit at dispatch, cancel
    restores it (conservation invariant: consumed + remaining == included)."""
    contract_id = call.get("_visit_charged_contract_id")
    if contract_id:
        contract = db.contracts.get(contract_id)
        if contract is not None and contract["visits_consumed"] > 0:
            contract["visits_consumed"] -= 1
            db.touch(contract)
        call["_visit_charged_contract_id"] = None


def cancel_service_call(call):
    call["status"] = "CANCELLED"
    restore_visit_if_charged(call)
    db.touch(call)


def unit_out_of_service(unit):
    """IN_SERVICE -> OUT_OF_SERVICE; OPEN/DISPATCHED service calls for the unit
    are cancelled with consumed visits restored."""
    if unit["equipment_status"] == "IN_SERVICE":
        unit["equipment_status"] = "OUT_OF_SERVICE"
        db.touch(unit)
    for call in db.service_calls.values():
        if call["unit_id"] == unit["id"] and call["status"] in ("OPEN", "DISPATCHED"):
            cancel_service_call(call)


def supersede_unit_certificates(unit):
    for cert in db.certificates.values():
        if cert["unit_id"] == unit["id"] and cert["status"] != "SUPERSEDED":
            cert["status"] = "SUPERSEDED"
            db.touch(cert)


def decommission_unit(unit):
    if unit["equipment_status"] != "DECOMMISSIONED":
        unit["equipment_status"] = "DECOMMISSIONED"
        db.touch(unit)
    supersede_unit_certificates(unit)


def credit_program_pool(program, amount):
    """Pool credit; an EXHAUSTED program credited back above zero reopens to OPEN."""
    program["remaining_pool"] = dec(program["remaining_pool"]) + dec(amount)
    if program["status"] == "EXHAUSTED" and program["remaining_pool"] > 0:
        program["status"] = "OPEN"
    db.touch(program)


def debit_program_pool(program, amount):
    """Pool debit; reaching exactly zero flips OPEN -> EXHAUSTED."""
    program["remaining_pool"] = dec(program["remaining_pool"]) - dec(amount)
    if program["remaining_pool"] == 0 and program["status"] == "OPEN":
        program["status"] = "EXHAUSTED"
    db.touch(program)


def cancel_project_cascade(project):
    """Full cancel cascade (PRD 3.8): permits, work orders, grant applications
    (with pool credits / program reopen), inspections, created unit, and the
    modernization-target restoration."""
    pid = project["id"]
    # hop 1: non-terminal permit applications -> CANCELLED
    for permit in db.permits.values():
        if permit["project_id"] == pid and permit["status"] in ("UNDER_REVIEW", "CORRECTIONS_REQUIRED", "APPROVED"):
            permit["status"] = "CANCELLED"
            db.touch(permit)
    # hop 1: work orders in DRAFT or RELEASED -> CANCELLED
    for wo in db.work_orders.values():
        if wo["project_id"] == pid and wo["status"] in ("DRAFT", "RELEASED"):
            wo["status"] = "CANCELLED"
            db.touch(wo)
    # hop 1: SCHEDULED inspections referencing this project -> CANCELLED
    for insp in db.inspections.values():
        if insp.get("project_id") == pid and insp["status"] == "SCHEDULED":
            insp["status"] = "CANCELLED"
            db.touch(insp)
    # grants: SUBMITTED -> WITHDRAWN; APPROVED -> WITHDRAWN with pool credit
    for app in db.grant_applications.values():
        if app["project_id"] != pid:
            continue
        if app["status"] == "SUBMITTED":
            app["status"] = "WITHDRAWN"
            db.touch(app)
        elif app["status"] == "APPROVED":
            app["status"] = "WITHDRAWN"
            db.touch(app)
            program = db.grant_programs.get(app["program_id"])
            if program is not None and app.get("final_award") is not None:
                # hop 2 (pool credit) / hop 3 (EXHAUSTED -> OPEN)
                credit_program_pool(program, app["final_award"])
    # unit created by this project: INSTALLED -> DECOMMISSIONED (+ certificates SUPERSEDED)
    for unit in db.units.values():
        if unit["project_id"] == pid and unit["equipment_status"] == "INSTALLED":
            decommission_unit(unit)
    # modernization cancelled before acceptance: target unit UNDER_MODERNIZATION -> IN_SERVICE
    if project.get("modernize_unit_id"):
        target = db.units.get(project["modernize_unit_id"])
        if target is not None and target["equipment_status"] == "UNDER_MODERNIZATION":
            target["equipment_status"] = "IN_SERVICE"
            db.touch(target)


def run_clock_sweeps():
    """PRD 2.4: on every clock set — permit expiry, certificate
    RENEWAL_DUE/EXPIRED with unit lapse cascade, program exhaustion recompute.
    Applied atomically with the clock set."""
    clock = db.now()
    # Sweep 1: approved permits past valid_through while install incomplete -> EXPIRED
    for permit in db.permits.values():
        if permit["status"] != "APPROVED" or permit["valid_through"] is None:
            continue
        if clock > permit["valid_through"]:
            project = db.projects.get(permit["project_id"])
            if project is not None and project["status"] not in (
                "INSTALL_COMPLETE", "AWAITING_REGISTRATION", "REGISTERED", "CLOSED", "CANCELLED",
            ):
                permit["status"] = "EXPIRED"
                db.touch(permit)
    # Sweep 2: certificates
    for cert in db.certificates.values():
        if cert["status"] not in ("ACTIVE", "RENEWAL_DUE") or cert["expiration_date"] is None:
            continue
        if clock > cert["expiration_date"]:
            cert["status"] = "EXPIRED"
            db.touch(cert)
            unit = db.units.get(cert["unit_id"])
            if unit is not None:
                if unit["registration_status"] == "REGISTERED":
                    unit["registration_status"] = "LAPSED"
                if unit["equipment_status"] == "IN_SERVICE":
                    unit["equipment_status"] = "OUT_OF_SERVICE"
                db.touch(unit)
                unit_out_of_service(unit)
        elif cert["status"] == "ACTIVE" and clock >= cert["expiration_date"] - timedelta(days=30):
            cert["status"] = "RENEWAL_DUE"
            db.touch(cert)
    # Sweep 3: program exhaustion recompute
    for program in db.grant_programs.values():
        pool = dec(program["remaining_pool"])
        if program["status"] == "OPEN" and pool == 0:
            program["status"] = "EXHAUSTED"
            db.touch(program)
        elif program["status"] == "EXHAUSTED" and pool > 0:
            program["status"] = "OPEN"
            db.touch(program)
