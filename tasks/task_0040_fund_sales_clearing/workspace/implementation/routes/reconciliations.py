"""Reconciliation routes."""
from flask import Blueprint, g

import db
from db import (
    orders, dividend_distributions, recon_runs, recon_exceptions,
    settlement_instructions, stamp_create, stamp_update, public,
)
from clock import now, iso, parse_iso, parse_iso_date, date_to_dt_utc
from errors import err
from middleware import require_auth
from response import success
from services import audit
from services.util import get_body, require_field, check_version


bp = Blueprint("reconciliations", __name__)


VALID_SCOPES = {"TA_VS_CUSTODIAN", "TA_VS_CHANNEL", "TA_VS_BANK"}
VALID_TARGET_SYSTEMS = {"BANK", "CUSTODIAN", "TA", "REGULATOR"}


def _get_internal_records(scope: str, as_of_date):
    """Collect internal SETTLED ledger entries for this scope+date.

    PRD §3.7 says the match runs on "internal SETTLED ledger entries for
    the run's scope and `as_of_date`". The PRD does not pin which date
    field on Order corresponds to the SETTLED ledger date; we use
    `trade_date` (the date the trade took effect on the fund) as the
    settlement key — every CONFIRMED order whose trade_date equals
    `as_of_date` is in scope.
    """
    records = []
    for o in orders.values():
        if o["status"] != "CONFIRMED":
            continue
        if not o.get("trade_date"):
            continue
        if parse_iso_date(o["trade_date"]) != as_of_date:
            continue
        records.append({
            "ref_id": o["id"],
            "amount_cents": o.get("confirmed_amount_cents") or 0,
            "shares": o.get("confirmed_shares") or 0,
        })
    return records


@bp.route("/reconciliations", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def open_run():
    body = get_body()
    require_field(body, "as_of_date")
    require_field(body, "scope")
    require_field(body, "external_records")
    if body["scope"] not in VALID_SCOPES:
        raise err("ERR_VALIDATION", "invalid scope")
    if not isinstance(body["external_records"], list):
        raise err("ERR_VALIDATION", "external_records must be array")
    try:
        as_of = parse_iso_date(body["as_of_date"])
    except Exception:
        raise err("ERR_VALIDATION", "invalid as_of_date")

    run = {
        "as_of_date": iso(date_to_dt_utc(as_of)),
        "scope": body["scope"],
        "external_records": body["external_records"],
        "status": "OPEN",
        "total_internal_amount_cents": 0,
        "total_external_amount_cents": 0,
        "net_break_cents": 0,
        "created_by": g.user_id,
    }
    stamp_create(run, common_fields=True)
    recon_runs[run["id"]] = run
    return success(public(run), 201)


@bp.route("/reconciliations/<id>/run-match", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def run_match(id):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    body = get_body()
    check_version(body, run)
    if run["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", f"Run.status={run['status']}, expected OPEN")
    if not run["external_records"]:
        raise err("ERR_INVALID_STATE", "external_records must be non-empty")

    as_of = parse_iso_date(run["as_of_date"])
    internal = _get_internal_records(run["scope"], as_of)
    external = run["external_records"]

    internal_by_ref = {r["ref_id"]: r for r in internal}
    external_by_ref = {r.get("ref_id"): r for r in external}

    total_internal = sum(r["amount_cents"] for r in internal)
    total_external = sum((r.get("amount_cents") or 0) for r in external)
    net_break = total_internal - total_external

    run["total_internal_amount_cents"] = total_internal
    run["total_external_amount_cents"] = total_external
    run["net_break_cents"] = net_break

    exceptions_created = []
    seen_internal = set()
    seen_external = set()

    # Match by ref_id
    all_refs = set(internal_by_ref.keys()) | set(external_by_ref.keys())
    for ref in all_refs:
        i = internal_by_ref.get(ref)
        e = external_by_ref.get(ref)
        if i is None and e is not None:
            # MISSING_INTERNAL
            exc = {
                "reconciliation_run_id": run["id"],
                "ref_id": ref,
                "kind": "MISSING_INTERNAL",
                "internal_amount_cents": None,
                "external_amount_cents": e.get("amount_cents"),
                "resolution_status": "OPEN",
                "adjustment_amount_cents": None,
            }
            stamp_create(exc, common_fields=False)
            recon_exceptions[exc["id"]] = exc
            exceptions_created.append(exc)
            seen_external.add(ref)
        elif e is None and i is not None:
            exc = {
                "reconciliation_run_id": run["id"],
                "ref_id": ref,
                "kind": "MISSING_EXTERNAL",
                "internal_amount_cents": i["amount_cents"],
                "external_amount_cents": None,
                "resolution_status": "OPEN",
                "adjustment_amount_cents": None,
            }
            stamp_create(exc, common_fields=False)
            recon_exceptions[exc["id"]] = exc
            exceptions_created.append(exc)
            seen_internal.add(ref)
        else:
            # Both exist
            if i["amount_cents"] != e.get("amount_cents"):
                exc = {
                    "reconciliation_run_id": run["id"],
                    "ref_id": ref,
                    "kind": "AMOUNT_MISMATCH",
                    "internal_amount_cents": i["amount_cents"],
                    "external_amount_cents": e.get("amount_cents"),
                    "resolution_status": "OPEN",
                    "adjustment_amount_cents": None,
                }
                stamp_create(exc, common_fields=False)
                recon_exceptions[exc["id"]] = exc
                exceptions_created.append(exc)
            elif i.get("shares") != e.get("shares") and "shares" in e:
                exc = {
                    "reconciliation_run_id": run["id"],
                    "ref_id": ref,
                    "kind": "SHARE_MISMATCH",
                    "internal_amount_cents": i["amount_cents"],
                    "external_amount_cents": e.get("amount_cents"),
                    "resolution_status": "OPEN",
                    "adjustment_amount_cents": None,
                }
                stamp_create(exc, common_fields=False)
                recon_exceptions[exc["id"]] = exc
                exceptions_created.append(exc)
            seen_internal.add(ref)
            seen_external.add(ref)

    if not exceptions_created and net_break == 0:
        run["status"] = "RESOLVED"
    else:
        run["status"] = "EXCEPTIONS_FOUND"
        run["_original_net_break_cents"] = net_break  # internal field for invariant check
    stamp_update(run)
    return success(public(run), 200)


@bp.route("/reconciliations/<id>/exceptions/<eid>/adjust", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def adjust_exception(id, eid):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    exc = recon_exceptions.get(eid)
    if not exc or exc["reconciliation_run_id"] != id:
        raise err("ERR_NOT_FOUND", "Exception not found")
    body = get_body()
    require_field(body, "adjustment_amount_cents")
    if not isinstance(body["adjustment_amount_cents"], int) or isinstance(body["adjustment_amount_cents"], bool):
        raise err("ERR_VALIDATION", "adjustment_amount_cents must be integer")
    if run["status"] != "EXCEPTIONS_FOUND":
        raise err("ERR_INVALID_STATE", f"Run.status={run['status']}, expected EXCEPTIONS_FOUND")
    if exc["resolution_status"] != "OPEN":
        raise err("ERR_INVALID_STATE",
                  f"Exception.resolution_status={exc['resolution_status']}, expected OPEN")

    delta = body["adjustment_amount_cents"]
    exc["adjustment_amount_cents"] = delta
    exc["resolution_status"] = "ADJUSTED"
    # Update parent net_break_cents
    run["net_break_cents"] = run["net_break_cents"] - delta
    stamp_update(run)
    return success(public(exc), 200)


@bp.route("/reconciliations/<id>/exceptions/<eid>/waive", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def waive_exception(id, eid):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    exc = recon_exceptions.get(eid)
    if not exc or exc["reconciliation_run_id"] != id:
        raise err("ERR_NOT_FOUND", "Exception not found")
    body = get_body()
    if run["status"] != "EXCEPTIONS_FOUND":
        raise err("ERR_INVALID_STATE", f"Run.status={run['status']}, expected EXCEPTIONS_FOUND")
    if exc["resolution_status"] != "OPEN":
        raise err("ERR_INVALID_STATE",
                  f"Exception.resolution_status={exc['resolution_status']}, expected OPEN")
    if exc["kind"] == "AMOUNT_MISMATCH":
        raise err("ERR_WAIVE_NOT_ALLOWED", "Cannot waive AMOUNT_MISMATCH exception")
    exc["resolution_status"] = "WAIVED"
    return success(public(exc), 200)


@bp.route("/reconciliations/<id>/finalize", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def finalize_run(id):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    body = get_body()
    check_version(body, run)
    if run["status"] != "EXCEPTIONS_FOUND":
        raise err("ERR_INVALID_STATE", f"Run.status={run['status']}, expected EXCEPTIONS_FOUND")
    excs = [e for e in recon_exceptions.values() if e["reconciliation_run_id"] == id]
    if any(e["resolution_status"] == "OPEN" for e in excs):
        raise err("ERR_INVALID_STATE", "Some exceptions remain OPEN")
    # Invariant: original_net_break - sum(ADJUSTED) == 0
    original_net = run.get("_original_net_break_cents", 0)
    sum_adj = sum(e["adjustment_amount_cents"] or 0 for e in excs
                  if e["resolution_status"] == "ADJUSTED")
    if original_net - sum_adj != 0:
        raise err("ERR_RECONCILIATION_INVARIANT_BROKEN",
                  "Sum of ADJUSTED does not restore net_break_cents")
    run["status"] = "RESOLVED"
    run["net_break_cents"] = 0
    stamp_update(run)
    return success(public(run), 200)


@bp.route("/reconciliations/<id>/close-and-instruct", methods=["POST"])
@require_auth(roles={"ClearingOperator"})
def close_and_instruct(id):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    body = get_body()
    check_version(body, run)
    if run["status"] != "RESOLVED":
        raise err("ERR_INVALID_STATE", f"Run.status={run['status']}, expected RESOLVED")
    if g.user_id == run.get("created_by"):
        raise err("ERR_SOD_VIOLATION_RECON", "Closer must differ from creator")

    # Generate one SettlementInstruction row per target system. Use the run's net positions.
    # For simplicity, emit one REPORT instruction per system with run's totals.
    for sysname in ("BANK", "CUSTODIAN", "TA", "REGULATOR"):
        instr = {
            "reconciliation_run_id": run["id"],
            "target_system": sysname,
            "instruction_type": "REPORT",
            "amount_cents": run["total_internal_amount_cents"],
            "dispatched_at": iso(now()),
        }
        stamp_create(instr, common_fields=False)
        settlement_instructions[instr["id"]] = instr

    run["status"] = "CLOSED"
    stamp_update(run)
    audit.write(g.user_id, g.user_role, "RECONCILIATION_RESOLVED", "ReconciliationRun",
                run["id"], "RESOLVED", "CLOSED", {})
    return success(public(run), 200)


@bp.route("/reconciliations/<id>", methods=["GET"])
@require_auth(roles={"ClearingOperator", "ComplianceReviewer", "PlatformAdmin"})
def get_run(id):
    run = recon_runs.get(id)
    if not run:
        raise err("ERR_NOT_FOUND", "Reconciliation run not found")
    out = public(run).copy()
    out["exceptions"] = [public(e) for e in recon_exceptions.values()
                          if e["reconciliation_run_id"] == id]
    out["settlement_instructions"] = [public(s) for s in settlement_instructions.values()
                                       if s["reconciliation_run_id"] == id]
    return success(out, 200)
