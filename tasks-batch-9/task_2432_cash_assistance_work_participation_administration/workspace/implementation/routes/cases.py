"""Assistance case reads, monthly issuance, the two clocks and hardship
extensions (PRD 3.4)."""

from flask import Blueprint

import guards
from calc import (MAX_HARDSHIP_EXTENSION_MONTHS, STATE_TIME_LIMIT_MONTHS, month_add)
from domain import (close_case, extension_covers, granted_extensions, lookup,
                    recompute_household_clocks, recompute_tlm, refresh_case_ledger,
                    rows_where)
from errors import fail
from guards import Fields, raw_body, require
from respond import created, filter_value, listing, ok, pagination
from store import clock_fiscal_year, db, new_record, touch

bp = Blueprint("cases", __name__)

EXTENSION_TYPES = ("HARDSHIP_DOMESTIC_VIOLENCE", "HARDSHIP_DISABILITY",
                   "HARDSHIP_LOCAL_LABOR_MARKET", "HARDSHIP_CARETAKER")


def _case(case_id):
    return lookup("cases", case_id, "ERR_CASE_NOT_FOUND")


def _extension(extension_id):
    return lookup("extensions", extension_id, "ERR_EXTENSION_NOT_FOUND")


@bp.get("/cases/<case_id>")
def read_case(case_id):
    require()
    return ok(_case(case_id))


@bp.get("/cases")
def search_cases():
    require(*guards.STAFF_ROLES)
    limit, offset = pagination()
    rows = rows_where("cases")
    for name in ("household_id", "application_id", "benefit_status",
                 "compliance_status"):
        value = filter_value(name)
        if value is not None:
            rows = [row for row in rows if row[name] == value]
    return listing(rows, limit, offset)


@bp.post("/cases/<case_id>/issuances")
def issue_month(case_id):
    require(guards.CASEWORKER)
    case = _case(case_id)
    fields = Fields(raw_body())
    fields.month("benefit_month")
    month = fields["benefit_month"]
    if case["benefit_status"] not in ("PENDING_ISSUANCE", "ACTIVE"):
        fail("ERR_INVALID_CASE_STATE",
             "Assistance may only be issued while the case is PENDING_ISSUANCE or ACTIVE.")
    for row in rows_where("time_limit_months", case_id=case_id):
        if row["benefit_month"] == month:
            fail("ERR_DUPLICATE_ISSUANCE_MONTH",
                 "This month has already been issued for the case.")

    ledger_row = new_record({
        "case_id": case_id,
        "benefit_month": month,
        "assistance_issued": True,
        "state_clock_countable": False,
        "federal_clock_countable": False,
        "non_countable_reason": "NONE",
    }, audited=False)
    recompute_tlm(ledger_row, case)
    db.time_limit_months[ledger_row["id"]] = ledger_row

    if case["benefit_status"] == "PENDING_ISSUANCE":
        case["benefit_status"] = "ACTIVE"
        touch(case)
    household = db.households[case["household_id"]]
    recompute_household_clocks(household)

    shielded = any(extension_covers(extension, month)
                   for extension in granted_extensions(case_id))
    if household["state_clock_months_used"] >= STATE_TIME_LIMIT_MONTHS \
            and not shielded and case["benefit_status"] == "ACTIVE":
        close_case(case, "TIME_LIMIT", clock_fiscal_year())
    return created(ledger_row)


@bp.get("/cases/<case_id>/time-limit-months")
def list_time_limit_months(case_id):
    require()
    _case(case_id)
    limit, offset = pagination()
    rows = rows_where("time_limit_months", case_id=case_id)
    month = filter_value("benefit_month")
    if month is not None:
        rows = [row for row in rows if row["benefit_month"] == month]
    return listing(rows, limit, offset)


@bp.post("/cases/<case_id>/extensions")
def request_extension(case_id):
    require(guards.CASEWORKER, guards.SPECIALIST)
    case = _case(case_id)
    fields = Fields(raw_body())
    fields.enum("extension_type", EXTENSION_TYPES)
    fields.integer("months_requested", minimum=1, maximum=12)
    fields.month("first_effective_month")
    if case["benefit_status"] == "CLOSED":
        fail("ERR_INVALID_CASE_STATE",
             "An extension may not be requested on a CLOSED case.")

    extension = new_record({
        "case_id": case_id,
        "extension_type": fields["extension_type"],
        "months_requested": fields["months_requested"],
        "first_effective_month": fields["first_effective_month"],
        "months_granted": 0,
        "last_effective_month": None,
        "status": "REQUESTED",
        "denial_reason": None,
        "revocation_reason": None,
        "decided_by_user_id": None,
    })
    db.extensions[extension["id"]] = extension
    return created(extension)


@bp.get("/cases/<case_id>/extensions")
def list_extensions(case_id):
    require()
    _case(case_id)
    limit, offset = pagination()
    rows = rows_where("extensions", case_id=case_id)
    status = filter_value("status")
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return listing(rows, limit, offset)


@bp.post("/extensions/<extension_id>/grant")
def grant_extension(extension_id):
    actor = require(guards.SUPERVISOR)
    extension = _extension(extension_id)
    fields = Fields(raw_body())
    fields.integer("months_granted")
    granted = fields["months_granted"]
    if extension["status"] != "REQUESTED":
        fail("ERR_INVALID_EXTENSION_STATE",
             "Only a REQUESTED extension may be granted.")
    case = db.cases[extension["case_id"]]
    if case["benefit_status"] not in ("ACTIVE", "SUSPENDED"):
        fail("ERR_INVALID_CASE_STATE",
             "The case must be ACTIVE or SUSPENDED to grant an extension.")
    household = db.households[case["household_id"]]
    if granted < 1 or granted > extension["months_requested"]:
        fail("ERR_EXTENSION_LIMIT_EXCEEDED",
             "months_granted must be between 1 and months_requested.")
    if household["extension_months_used"] + granted > MAX_HARDSHIP_EXTENSION_MONTHS:
        fail("ERR_EXTENSION_LIMIT_EXCEEDED",
             "The lifetime hardship allowance of 12 months would be exceeded.")

    extension["status"] = "GRANTED"
    extension["months_granted"] = granted
    extension["last_effective_month"] = month_add(extension["first_effective_month"],
                                                  granted - 1)
    extension["decided_by_user_id"] = actor.user_id
    touch(extension)
    refresh_case_ledger(case)
    recompute_household_clocks(household)
    return ok(extension)


@bp.post("/extensions/<extension_id>/deny")
def deny_extension(extension_id):
    actor = require(guards.SUPERVISOR)
    extension = _extension(extension_id)
    fields = Fields(raw_body())
    fields.text("denial_reason")
    if extension["status"] != "REQUESTED":
        fail("ERR_INVALID_EXTENSION_STATE",
             "Only a REQUESTED extension may be denied.")
    extension["status"] = "DENIED"
    extension["denial_reason"] = fields["denial_reason"]
    extension["decided_by_user_id"] = actor.user_id
    touch(extension)
    return ok(extension)


@bp.post("/extensions/<extension_id>/revoke")
def revoke_extension(extension_id):
    actor = require(guards.SUPERVISOR)
    extension = _extension(extension_id)
    fields = Fields(raw_body())
    fields.text("revocation_reason")
    if extension["status"] != "GRANTED":
        fail("ERR_INVALID_EXTENSION_STATE",
             "Only a GRANTED extension may be revoked.")
    case = db.cases[extension["case_id"]]
    extension["status"] = "REVOKED"
    extension["months_granted"] = 0
    extension["last_effective_month"] = None
    extension["revocation_reason"] = fields["revocation_reason"]
    extension["decided_by_user_id"] = actor.user_id
    touch(extension)
    refresh_case_ledger(case)
    household = db.households[case["household_id"]]
    recompute_household_clocks(household)
    if household["state_clock_months_used"] >= STATE_TIME_LIMIT_MONTHS \
            and case["benefit_status"] == "ACTIVE":
        case["benefit_status"] = "CLOSED"
        case["closure_reason"] = "TIME_LIMIT"
        touch(case)
    return ok(extension)
