"""Reconciliation periods, statement import, matching, and the ledger reads."""

from datetime import timedelta

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import adopt_entries_into_period, period_for_month
from core.audit import set_client, set_subject
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.gates import gate_period_frozen_row
from core.pipeline import audited, authorize, resolve, resolve_body_ref
from core.store import all_of, bump, db, new_row

bp = Blueprint("reconciliation", __name__)

READ_ROLES = ("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer", "PlatformAdmin")


def _client_of_account_id(account_id):
    account = db.accounts.get(account_id)
    return account["client_id"] if account else None


@bp.post("/dmm/reconciliation-periods")
@audited("ReconciliationPeriod")
def open_period():
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    account = resolve_body_ref(ctx, "account_id", "accounts")  # rung 3
    if account is not None:
        set_client(account["client_id"])
    ctx.check_shape([                                          # rung 4
        ("account_id", str, True),
        ("period_month", str, True),
    ])

    period_month = ctx.body["period_month"]
    if period_for_month(account["id"], period_month) is not None:   # rung 18
        fail("ERR_PERIOD_OVERLAP", "That account-month is already open.")

    row = new_row("reconciliation_periods", {
        "account_id": account["id"],
        "period_month": period_month,
        "status": "OPEN",
        "imported_line_count": 0,
        "open_exception_count": 0,
        "unreconciled_entry_count": 0,
        "closed_at": None,
        "reopen_count": 0,
        "has_retro_adjustment": False,
    })
    adopt_entries_into_period(row)
    set_subject(row["id"])
    return object_response(serialize.reconciliation_period(row), 201)


@bp.post("/dmm/reconciliation-periods/<rid>/statement-lines")
@audited("StatementLine")
def import_statement_line(rid):
    ctx = authorize("BillPaySpecialist")                       # rungs 1-2
    period = resolve("reconciliation_periods", rid)            # rung 3
    set_client(_client_of_account_id(period["account_id"]))
    ctx.check_shape([                                          # rung 4
        ("external_ref", str, True),
        ("amount_cents", int, True),
        ("line_date", str, True),
        ("line_description", str, False),
    ])

    gate_period_frozen_row(period)                             # rung 10

    external_ref = ctx.body["external_ref"]
    for line in all_of("statement_lines"):                     # rung 16
        if line["period_id"] == period["id"] and line["external_ref"] == external_ref:
            fail("ERR_VALIDATION", "That external_ref is already imported.")

    row = new_row("statement_lines", {
        "period_id": period["id"],
        "external_ref": external_ref,
        "amount_cents": ctx.body["amount_cents"],
        "line_date": ctx.body["line_date"],
        "line_description": ctx.body.get("line_description"),
        "match_status": "UNMATCHED",
        "matched_ledger_entry_id": None,
        "exception_note": None,
    })
    period["imported_line_count"] += 1
    bump(period)
    set_subject(row["id"])
    return object_response(serialize.statement_line(row), 201)


@bp.post("/dmm/reconciliation-periods/<rid>/status")
@audited("ReconciliationPeriod", path_param="rid")
def drive_period_status(rid):
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    period = resolve("reconciliation_periods", rid)            # rung 3
    set_client(_client_of_account_id(period["account_id"]))
    ctx.check_shape([("to_status", str, True)])                # rung 4
    ctx.check_enum("to_status", K.PERIOD_STATUS)               # rung 5

    to_status = ctx.body["to_status"]
    current = period["status"]

    # rung 12 - the state gate.  This endpoint is deliberately exempt from the
    # reconciliation freeze, because the reopen path must survive it.
    if to_status == "IN_REVIEW":
        if current not in ("OPEN", "REOPENED"):
            fail("ERR_INVALID_STATE", "The period cannot enter review from here.")
    elif to_status == "CLOSED":
        if current != "IN_REVIEW":
            fail("ERR_INVALID_STATE", "Only a period IN_REVIEW may be closed.")
    elif to_status == "REOPENED":
        if current != "CLOSED":
            fail("ERR_INVALID_STATE", "Only a CLOSED period may be reopened.")
    else:
        fail("ERR_INVALID_STATE", "No transition leads to that status.")

    if to_status == "REOPENED":                                # rung 23
        deadline = period["closed_at"] + timedelta(days=K.PERIOD_REOPEN_WINDOW_DAYS)
        if db.now > deadline:
            fail("ERR_REOPEN_NOT_PERMITTED", "The reopen window has closed.")

    if to_status == "CLOSED" and period["open_exception_count"] != 0:   # rung 27
        fail("ERR_OPEN_EXCEPTIONS", "An outstanding exception blocks the close.")

    if to_status == "IN_REVIEW":
        period["status"] = "IN_REVIEW"
    elif to_status == "CLOSED":
        period["status"] = (
            "LOCKED" if period["reopen_count"] >= K.PERIOD_REOPEN_MAX_COUNT else "CLOSED"
        )
        period["closed_at"] = db.now
    else:
        period["status"] = "REOPENED"
        period["reopen_count"] += 1
    bump(period)
    return object_response(serialize.reconciliation_period(period), 200)


@bp.post("/dmm/statement-lines/<sid>/disposition")
@audited("StatementLine", path_param="sid")
def dispose_statement_line(sid):
    ctx = authorize("BillPaySpecialist", "FiduciaryManager")   # rungs 1-2
    line = resolve("statement_lines", sid)                     # rung 3 - path
    entry = resolve_body_ref(ctx, "ledger_entry_id", "ledger_entries")   # rung 3 - body
    period = db.reconciliation_periods.get(line["period_id"])
    if period is not None:
        set_client(_client_of_account_id(period["account_id"]))
    ctx.check_shape([                                          # rung 4
        ("action", str, True),
        ("expected_period_version", int, True),
        ("ledger_entry_id", str, False),
        ("exception_note", str, False),
    ])
    action = ctx.body.get("action")
    if action in ("MATCH", "RESOLVE_MATCHED"):
        ctx.require_conditional("ledger_entry_id")
    ctx.check_enum("action", K.STATEMENT_LINE_ACTION)          # rung 5

    gate_period_frozen_row(period)                             # rung 10

    current = line["match_status"]                             # rung 12
    if action in ("MATCH", "FLAG_EXCEPTION"):
        if current != "UNMATCHED":
            fail("ERR_INVALID_STATE", "The line is no longer UNMATCHED.")
    else:
        if current != "EXCEPTION":
            fail("ERR_INVALID_STATE", "The line is not in EXCEPTION.")

    if action in ("MATCH", "RESOLVE_MATCHED"):                 # rung 14
        if entry["period_id"] != line["period_id"] or entry["amount_cents"] != line["amount_cents"]:
            fail("ERR_REFERENCE_MISMATCH", "The ledger entry does not match the line.")

    if ctx.body["expected_period_version"] != period["version"]:   # rung 34
        fail("ERR_STALE_VERSION", "The period version has moved on.")

    if action == "MATCH":
        line["match_status"] = "MATCHED"
        line["matched_ledger_entry_id"] = entry["id"]
        period["unreconciled_entry_count"] -= 1
    elif action == "FLAG_EXCEPTION":
        line["match_status"] = "EXCEPTION"
        line["exception_note"] = ctx.body.get("exception_note")
        period["open_exception_count"] += 1
    elif action == "RESOLVE_MATCHED":
        line["match_status"] = "RESOLVED_MATCHED"
        line["matched_ledger_entry_id"] = entry["id"]
        period["open_exception_count"] -= 1
        period["unreconciled_entry_count"] -= 1
    else:
        line["match_status"] = "RESOLVED_WRITTEN_OFF"
        line["exception_note"] = ctx.body.get("exception_note")
        period["open_exception_count"] -= 1

    bump(line)
    bump(period)
    return object_response(serialize.statement_line(line), 200)


# ---------------------------------------------------------------- reads

@bp.get("/dmm/reconciliation-periods/<rid>")
def read_period(rid):
    authorize(*READ_ROLES)
    return object_response(
        serialize.reconciliation_period(resolve("reconciliation_periods", rid)), 200
    )


@bp.get("/dmm/statement-lines")
def list_statement_lines():
    authorize(*READ_ROLES)
    rows = db.ordered("statement_lines")
    for field in ("period_id", "matched_ledger_entry_id", "match_status"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.statement_line)


@bp.get("/dmm/statement-lines/<sid>")
def read_statement_line(sid):
    authorize(*READ_ROLES)
    return object_response(serialize.statement_line(resolve("statement_lines", sid)), 200)


@bp.get("/dmm/ledger-entries")
def list_ledger_entries():
    authorize(*READ_ROLES)
    rows = db.ordered("ledger_entries")
    for field in ("account_id", "period_id", "source_payment_id", "entry_type"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.ledger_entry)


@bp.get("/dmm/ledger-entries/<lid>")
def read_ledger_entry(lid):
    authorize(*READ_ROLES)
    return object_response(serialize.ledger_entry(resolve("ledger_entries", lid)), 200)
