"""Cascade logic: application withdrawal side effects and advisory suspension cascade."""

import db
from db import now_iso
from services.billing import void_statement


def withdraw_application(app, reason):
    """Withdraw an application, firing side effects (seat release, billing void, insurance cancel)."""
    from services.program import recompute_seats

    previous_status = app["status"]
    app["status"] = "WITHDRAWN"
    app["withdraw_reason"] = reason
    app["version"] += 1
    app["updated_at"] = now_iso()

    program = db.programs.get(app["program_id"])

    if previous_status == "COMMITTED":
        # seat release
        if program:
            recompute_seats(program)
            program["version"] += 1
            program["updated_at"] = now_iso()
        # void billing statement(s) in ISSUED/PARTIALLY_PAID/PAID
        for stmt in db.billing_statements.values():
            if stmt["application_id"] == app["id"] and stmt["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID"):
                void_statement(stmt)
        # cancel ACTIVE insurance enrollments
        for enr in db.insurance_enrollments.values():
            if enr["application_id"] == app["id"] and enr["status"] == "ACTIVE":
                enr["status"] = "CANCELLED"
                enr["version"] += 1
                enr["updated_at"] = now_iso()


def suspend_program_cascade(program):
    """Program OPEN -> SUSPENDED cascade: withdraw APPROVED/COMMITTED applications with SYSTEM_SUSPENSION."""
    from services.program import recompute_seats

    program["status"] = "SUSPENDED"
    program["version"] += 1
    program["updated_at"] = now_iso()

    for app in list(db.applications.values()):
        if app["program_id"] == program["id"] and app["status"] in ("APPROVED", "COMMITTED"):
            withdraw_application(app, "SYSTEM_SUSPENSION")

    # after all withdrawals, recompute seats once more (each COMMITTED withdrawal already did)
    recompute_seats(program)
