"""CarrierStatement endpoints: import, reconciliation lifecycle, line waiver."""
from flask import Blueprint

from db import DB
from errors import ApiError
from middleware import auth, ADMIN, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import (
    by_seq,
    new_resource,
    periods_overlap_closed,
    run_statement_matching,
    ser_statement,
    touch,
)
from util import (
    apply_filters,
    as_date_str,
    as_int,
    as_list,
    as_str,
    get_body,
    is_date_str,
    req,
    respond_list,
)

bp = Blueprint("statements", __name__)


@bp.post("/agency/carrier-statements")
def create_statement():
    auth(ADMIN_ACCT)
    data = get_body()
    # Priority 3: body FK reference.
    carrier_id = data.get("carrier_id")
    if isinstance(carrier_id, str) and carrier_id not in DB["carriers"]:
        raise ApiError("ERR_NOT_FOUND", 404, "carrier_id does not reference an existing carrier")
    # Priority 6: closed-interval period overlap within the same carrier
    # (a shared boundary date counts as an intersection).
    ps = data.get("period_start")
    pe = data.get("period_end")
    if isinstance(carrier_id, str) and is_date_str(ps) and is_date_str(pe):
        new_start, new_end = ps.strip(), pe.strip()
        for s in by_seq(DB["statements"].values()):
            if s["carrier_id"] == carrier_id and periods_overlap_closed(
                new_start, new_end, s["period_start"], s["period_end"]
            ):
                raise ApiError(
                    "ERR_STATEMENT_PERIOD_OVERLAP",
                    409,
                    "Statement period overlaps an existing statement of this carrier",
                )
    # Priority 10: shape.
    carrier_id = as_str(req(data, "carrier_id"), "carrier_id")
    period_start = as_date_str(req(data, "period_start"), "period_start")
    period_end = as_date_str(req(data, "period_end"), "period_end")
    raw_lines = as_list(req(data, "lines"), "lines")
    lines = []
    for i, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, f"lines[{i}] must be an object")
        line_ref = as_str(req(line, "line_ref"), f"lines[{i}].line_ref")
        reported = as_int(
            req(line, "reported_amount_cents"), f"lines[{i}].reported_amount_cents"
        )
        lines.append({
            "line_ref": line_ref,
            "reported_amount_cents": reported,
            "match_status": "UNMATCHED",
            "matched_entry_id": None,
        })
    stmt = new_resource({
        "carrier_id": carrier_id,
        "period_start": period_start,
        "period_end": period_end,
        "lines": lines,
        "total_reported_cents": sum(l["reported_amount_cents"] for l in lines),
        "status": "RECEIVED",
    })
    DB["statements"][stmt["id"]] = stmt
    return ok(ser_statement(stmt), 201)


@bp.get("/agency/carrier-statements")
def list_statements():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["statements"].values(), {"carrier_id": "carrier_id", "status": "status"}
    )
    return respond_list(items, ser_statement)


@bp.get("/agency/carrier-statements/<statementId>")
def get_statement(statementId):
    auth(ALL_ROLES)
    s = DB["statements"].get(statementId)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    return ok(ser_statement(s))


@bp.post("/agency/carrier-statements/<statementId>/start-reconciliation")
def start_reconciliation(statementId):
    auth(ADMIN_ACCT)
    stmt = DB["statements"].get(statementId)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    if stmt["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not RECEIVED")
    run_statement_matching(stmt)
    return ok(ser_statement(stmt))


@bp.post("/agency/carrier-statements/<statementId>/dispute")
def dispute_statement(statementId):
    auth(ADMIN_ACCT)
    stmt = DB["statements"].get(statementId)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    if stmt["status"] != "RECONCILING":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not RECONCILING")
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return ok(ser_statement(stmt))


@bp.post("/agency/carrier-statements/<statementId>/resume")
def resume_statement(statementId):
    auth(ADMIN_ACCT)
    stmt = DB["statements"].get(statementId)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    if stmt["status"] != "DISPUTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not DISPUTED")
    stmt["status"] = "RECONCILING"
    touch(stmt)
    return ok(ser_statement(stmt))


@bp.post("/agency/carrier-statements/<statementId>/close")
def close_statement(statementId):
    auth(ADMIN_ACCT)
    stmt = DB["statements"].get(statementId)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    if stmt["status"] != "RECONCILING":
        raise ApiError("ERR_INVALID_STATE", 409, "Statement is not RECONCILING")
    # Priority 8: every line resolved and no linked entry still in VARIANCE.
    unresolved = any(
        l["match_status"] not in ("MATCHED", "WAIVED") for l in stmt["lines"]
    )
    variance_left = any(
        e["matched_statement_id"] == stmt["id"] and e["status"] == "VARIANCE"
        for e in DB["entries"].values()
    )
    if unresolved or variance_left:
        raise ApiError(
            "ERR_UNMATCHED_STATEMENT_LINES",
            409,
            "Statement has unresolved lines or entries still in VARIANCE",
        )
    stmt["status"] = "RECONCILED"
    touch(stmt)
    return ok(ser_statement(stmt))


@bp.post("/agency/carrier-statements/<statementId>/waive-line")
def waive_line(statementId):
    auth(ADMIN)
    stmt = DB["statements"].get(statementId)
    if stmt is None:
        raise ApiError("ERR_NOT_FOUND", 404, "CarrierStatement not found")
    data = get_body()
    # Priority 3: the body-supplied line reference must resolve to a line.
    line_ref = data.get("line_ref")
    line = None
    if isinstance(line_ref, str):
        line = next(
            (l for l in stmt["lines"] if l["line_ref"] == line_ref), None
        )
        if line is None:
            raise ApiError("ERR_NOT_FOUND", 404, "No statement line with that line_ref")
    # Priority 4: statement must be in an active reconciliation state and the
    # line must be ORPHAN.
    if stmt["status"] not in ("RECONCILING", "DISPUTED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Statement is not in reconciliation"
        )
    if line is not None and line["match_status"] != "ORPHAN":
        raise ApiError("ERR_INVALID_STATE", 409, "Only ORPHAN lines can be waived")
    # Priority 10: shape.
    as_str(req(data, "line_ref"), "line_ref")
    line["match_status"] = "WAIVED"
    touch(stmt)
    return ok(ser_statement(stmt))
