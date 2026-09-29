"""Program income ledger: signed federal share, running balance, reversal mirrors."""
from flask import Blueprint

import calc
import lookups
import store
import web
from core import fail, fmt_date
from web import endpoint

bp = Blueprint("ledger", __name__)


def _ledger_sort(rec):
    return (rec["posted_on"], rec["created_at"], rec["_seq"])


@bp.post("/mitigation-projects/<project_id>/program-income-entries")
@endpoint("SubrecipientCoordinator")
def create_entry(project_id):
    project = lookups.get_project(project_id)
    web.scope_project(project_id)
    body = web.get_body()
    entry_type = web.req_enum(body, "entry_type", store.ENTRY_TYPES)
    amount = web.int_field(body, "amount_cents", minimum=1)
    posted_on = web.req_date(body, "posted_on")
    parcel_id = web.opt_id(body, "applied_to_parcel_id")
    reverses_id = web.opt_id(body, "reverses_entry_id")
    expected = web.int_field(body, "expected_project_version", minimum=1)

    if parcel_id is not None:
        parcel = lookups.get_parcel(parcel_id)
        if parcel["project_id"] != project_id:
            fail("ERR_PARCEL_PROJECT_MISMATCH")
    if reverses_id is not None:
        target = lookups.get_entry(reverses_id)
        if target["project_id"] != project_id:
            fail("ERR_PARCEL_PROJECT_MISMATCH")
    if expected != int(project["version"]):
        fail("ERR_STALE_PROJECT_VERSION")
    if project["status"] not in ("APPROVED", "CLOSEOUT_PENDING", "CLOSED_OUT"):
        fail("ERR_INVALID_PROJECT_STATE")

    share = calc.program_income_federal_share(entry_type, amount, project["cost_share_federal_pct"])
    if int(project["program_income_balance_cents"]) + share < 0:
        fail("ERR_PROGRAM_INCOME_OVERDRAWN")

    record = store.new_record("ProgramIncomeLedgerEntry", {
        "project_id": project_id,
        "applied_to_parcel_id": parcel_id,
        "entry_type": entry_type,
        "amount_cents": amount,
        "federal_share_cents": share,
        "posted_on": fmt_date(posted_on),
        "reverses_entry_id": reverses_id,
        "status": "ACTIVE",
        "expected_project_version": expected,
    }, versioned=False)
    store.ledger[record["id"]] = record
    calc.recompute_program_income_balance(project)
    store.touch(project)
    return web.respond_object(record, 201)


@bp.get("/program-income-entries")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_entries():
    project_id = web.query_str("project_id")
    parcel_id = web.query_str("applied_to_parcel_id")
    reverses_id = web.query_str("reverses_entry_id")
    status = web.query_enum("status", store.LEDGER_STATUSES)
    rows = list(store.ledger.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if parcel_id is not None:
        rows = [r for r in rows if r["applied_to_parcel_id"] == parcel_id]
    if reverses_id is not None:
        rows = [r for r in rows if r["reverses_entry_id"] == reverses_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows, sort=_ledger_sort)


@bp.get("/program-income-entries/<entry_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_entry(entry_id):
    return web.respond_object(lookups.get_entry(entry_id))


@bp.post("/program-income-entries/<entry_id>/reverse")
@endpoint("ProgramAdministrator")
def reverse_entry(entry_id):
    target = lookups.get_entry(entry_id)
    body = web.get_body()
    web.opt_string(body, "reversal_note")
    if target["status"] != "ACTIVE":
        fail("ERR_ALREADY_REVERSED")

    target["status"] = "REVERSED"
    mirror = store.new_record("ProgramIncomeLedgerEntry", {
        "project_id": target["project_id"],
        "applied_to_parcel_id": target["applied_to_parcel_id"],
        "entry_type": target["entry_type"],
        "amount_cents": target["amount_cents"],
        "federal_share_cents": -int(target["federal_share_cents"]),
        "posted_on": target["posted_on"],
        "reverses_entry_id": target["id"],
        "status": "REVERSED",
        "expected_project_version": None,
    }, versioned=False)
    store.ledger[mirror["id"]] = mirror

    project = store.projects.get(target["project_id"])
    if project is not None:
        calc.recompute_program_income_balance(project)
        store.touch(project)
    return web.respond_object(mirror, 201)
