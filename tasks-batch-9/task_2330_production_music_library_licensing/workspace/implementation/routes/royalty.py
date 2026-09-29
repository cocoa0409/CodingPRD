"""RoyaltyStatement and RoyaltyLedgerEntry endpoints (PRD §3.9)."""

from flask import Blueprint, request

from db import DB
from errors import fail
from middleware import (
    body,
    is_role,
    req_datetime,
    req_enum,
    req_int,
    req_string,
    require_role,
    user_id,
)
from response import object_response, page_response, pagination
from routes.common import PREFIX, SOURCE_TYPES, guard_composer, require_state
from services import calc
from services.cascade import append_ledger, bump_once, sweep_set
from services.derive import (
    lookup,
    outstanding_advance_cents,
    rows,
    serialize_entry,
    serialize_statement,
)

bp = Blueprint("royalty", __name__)

BASES = ("ACCRUAL", "CASH")


@bp.post(PREFIX + "/royalty-statements")
def create_statement():
    data = body()
    composer_id = req_string(data, "composer_id")
    raw_start, start = req_datetime(data, "period_start")
    raw_end, end = req_datetime(data, "period_end")
    basis = req_enum(data, "basis", BASES)
    expected_version = req_int(data, "expected_composer_version", 0, None)

    composer = lookup("composers", composer_id)                       # 3
    require_role("RoyaltyAccountant")                                 # 4
    if composer["version"] != expected_version:                       # 9
        fail(
            "ERR_COMPOSER_VERSION_CONFLICT",
            "expected composer version %s but the row is at %s."
            % (expected_version, composer["version"]),
        )
    for other in rows("statements"):                                  # 45
        if other["composer_id"] != composer["id"]:
            continue
        if start <= other["_period_end_dt"] and other["_period_start_dt"] <= end:
            fail("ERR_STATEMENT_PERIOD_OVERLAP", "another statement covers this period.")

    swept = sweep_set(composer["id"], start, end, basis)
    gross = sum(entry["amount_cents"] for entry in swept)
    advance = outstanding_advance_cents(composer["id"])
    recouped, withholding, net, payout_status = calc.statement_figures(
        gross, advance, composer["_tax_withholding_pct"]
    )

    row = DB.new_row()
    row.update(
        {
            "composer_id": composer["id"],
            "period_start": raw_start,
            "_period_start_dt": start,
            "period_end": raw_end,
            "_period_end_dt": end,
            "basis": basis,
            "status": "DRAFT",
            "gross_cents": gross,
            "recouped_cents": recouped,
            "withholding_cents": withholding,
            "net_payable_cents": net,
            "line_count": len(swept),
            "payout_status": payout_status,
            "finalized_by_user_id": None,
            "paid_by_user_id": None,
            "payment_reference": None,
            "finalized_at": None,
            "paid_at": None,
        }
    )
    DB.statements[row["id"]] = row

    for entry in swept:
        entry["statement_id"] = row["id"]
    if recouped > 0:
        recoup_entry = append_ledger(
            composer["id"],
            "ADVANCE_RECOUP",
            row["id"],
            recouped,
            "ADVANCE_RECOUPMENT",
            cash=True,
            bump_composer=False,
        )
        recoup_entry["statement_id"] = row["id"]
    bump_once(composer)
    return object_response(serialize_statement(row), 201)


@bp.get(PREFIX + "/royalty-statements/<statement_id>")
def get_statement(statement_id):
    row = lookup("statements", statement_id)
    require_role("RoyaltyAccountant", "Composer")
    guard_composer(row["composer_id"])
    return object_response(serialize_statement(row))


@bp.get(PREFIX + "/royalty-statements")
def list_statements():
    limit, offset = pagination(request.args)
    require_role("RoyaltyAccountant", "Composer")
    args = request.args
    if is_role("Composer"):
        wanted = args.get("composer_id")
        if wanted not in (None, "") and wanted != user_id():
            fail("ERR_COMPOSER_IDENTITY_MISMATCH", "Composers may list only their own rows.")
    result = rows("statements")
    if is_role("Composer"):
        result = [r for r in result if r["composer_id"] == user_id()]
    for name in ("composer_id", "status", "basis"):
        wanted = args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_statement)


@bp.post(PREFIX + "/royalty-statements/<statement_id>/finalize")
def finalize(statement_id):
    row = lookup("statements", statement_id)
    require_role("RoyaltyAccountant")
    require_state(row, "status", ("DRAFT",), "statement")
    if row["payout_status"] == "NO_ACTIVITY":                          # 46
        fail("ERR_STATEMENT_NO_ACTIVITY", "an empty statement may not be finalized.")
    row["status"] = "FINALIZED"
    row["finalized_by_user_id"] = user_id()
    row["finalized_at"] = DB.now_iso
    bump_once(row)
    return object_response(serialize_statement(row))


@bp.post(PREFIX + "/royalty-statements/<statement_id>/pay")
def pay(statement_id):
    data = body()
    reference = req_string(data, "payment_reference", allow_empty=False)
    row = lookup("statements", statement_id)
    require_role("RoyaltyAccountant")
    if row["finalized_by_user_id"] is not None and user_id() == row["finalized_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the finalizing user may not pay the statement.")  # 7
    require_state(row, "status", ("FINALIZED",), "statement")          # 10
    if row["payout_status"] != "PAYABLE":                              # 47
        fail("ERR_STATEMENT_NOT_PAYABLE", "the statement is not payable.")

    row["status"] = "PAID"
    row["paid_by_user_id"] = user_id()
    row["payment_reference"] = reference
    row["paid_at"] = DB.now_iso
    bump_once(row)
    bump_once(DB.composers.get(row["composer_id"]))
    return object_response(serialize_statement(row))


@bp.post(PREFIX + "/royalty-ledger-entries")
def create_entry():
    data = body()
    composer_id = req_string(data, "composer_id")
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    amount = req_int(data, "amount_cents")
    memo = req_string(data, "memo")
    if source_type != "ADJUSTMENT":                        # shape check, schema pass
        fail("ERR_LEDGER_SOURCE_NOT_MANUAL", "only ADJUSTMENT entries may be appended by hand.")
    composer = lookup("composers", composer_id)                       # 3
    require_role("RoyaltyAccountant")                                 # 4
    row = append_ledger(composer["id"], "ADJUSTMENT", None, amount, memo, cash=True)
    return object_response(serialize_entry(row), 201)


@bp.get(PREFIX + "/royalty-ledger-entries/<entry_id>")
def get_entry(entry_id):
    row = lookup("ledger", entry_id)
    require_role("RoyaltyAccountant", "Composer")
    guard_composer(row["composer_id"])
    return object_response(serialize_entry(row))


@bp.get(PREFIX + "/royalty-ledger-entries")
def list_entries():
    limit, offset = pagination(request.args)
    require_role("RoyaltyAccountant", "Composer")
    args = request.args
    if is_role("Composer"):
        wanted = args.get("composer_id")
        if wanted not in (None, "") and wanted != user_id():
            fail("ERR_COMPOSER_IDENTITY_MISMATCH", "Composers may list only their own rows.")
    result = rows("ledger")
    if is_role("Composer"):
        result = [r for r in result if r["composer_id"] == user_id()]
    for name in ("composer_id", "statement_id", "source_type"):
        wanted = args.get(name)
        if wanted not in (None, ""):
            result = [r for r in result if r[name] == wanted]
    return page_response(result, limit, offset, serialize_entry)
