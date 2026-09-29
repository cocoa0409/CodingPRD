"""Funder and capital commitment endpoints (PRD 3.7)."""

from flask import Blueprint

from db import base_row, db, public, put_dt, touch
from errors import ApiError
from middleware import (BUYER_TREASURY, FUNDER, PLATFORM_OPS, authenticate,
                        get_funder, scope_funder)
from response import ok, ok_list
from services import guards as g
from services import recompute as rc
from validation import (bad, body, filter_arg, paginate, pagination, req_dt,
                        req_enum, req_int, req_str)

bp = Blueprint("funders", __name__)


@bp.post("/funders")
def create_funder():
    authenticate((PLATFORM_OPS,))
    b = body()
    legal_name = req_str(b, "legal_name", 1, 200)
    capital_limit_cents = req_int(b, "capital_limit_cents", 1)
    min_apr_bps = req_int(b, "min_apr_bps", 1, 5000)
    fee_spread_bps = req_int(b, "fee_spread_bps", 0, 500)
    max_single_invoice_cents = req_int(b, "max_single_invoice_cents", 1)
    row = base_row()
    row.update(
        {
            "legal_name": legal_name,
            "capital_limit_cents": capital_limit_cents,
            "min_apr_bps": min_apr_bps,
            "fee_spread_bps": fee_spread_bps,
            "max_single_invoice_cents": max_single_invoice_cents,
            "status": "ACTIVE",
            "encumbered_capital_cents": 0,
            "available_capital_cents": 0,
        }
    )
    db.funders[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/funders/<funder_id>")
def read_funder(funder_id):
    ctx = authenticate((PLATFORM_OPS, FUNDER, BUYER_TREASURY))
    funder = get_funder(funder_id)
    scope_funder(ctx, funder["id"])
    return ok(public(funder))


@bp.post("/funders/<funder_id>/pause")
def pause_funder(funder_id):
    ctx = authenticate((PLATFORM_OPS, FUNDER))
    b = body()
    action = req_enum(b, "action", ("PAUSE", "RESUME", "WITHDRAW"))
    funder = get_funder(funder_id)
    scope_funder(ctx, funder["id"])

    if action == "PAUSE":
        if funder["status"] != "ACTIVE":
            g.invalid_state("Only an ACTIVE funder can be paused.")
        funder["status"] = "PAUSED"
        touch(funder)
    elif action == "RESUME":
        if funder["status"] != "PAUSED":
            g.invalid_state("Only a PAUSED funder can be resumed.")
        funder["status"] = "ACTIVE"
        touch(funder)
    else:
        if funder["status"] not in ("ACTIVE", "PAUSED"):
            g.invalid_state("The funder cannot be withdrawn from its current state.")
        if rc.funder_encumbered(funder["id"]) != 0:
            g.invalid_state("Encumbered capital must be zero before withdrawal.")
        funder["status"] = "WITHDRAWN"
        touch(funder)
        for commitment in rc.funder_commitments(funder["id"]):
            if commitment["status"] == "ACTIVE":
                commitment["status"] = "EXPIRED"
                touch(commitment)
        rc.recompute_funder_capital(funder)
    return ok(public(funder))


@bp.post("/funders/<funder_id>/commitments")
def create_commitment(funder_id):
    ctx = authenticate((FUNDER, PLATFORM_OPS))
    b = body()
    committed_amount_cents = req_int(b, "committed_amount_cents", 1)
    from_raw, from_dt = req_dt(b, "effective_from")
    to_raw, to_dt = req_dt(b, "effective_to")
    if to_dt.date() < from_dt.date():
        bad(detail="effective_to may not precede effective_from.")
    funder = get_funder(funder_id)
    scope_funder(ctx, funder["id"])

    # Ceiling test at the new tranche's start plus every existing boundary
    # point that falls inside the new closed interval.
    existing = rc.funder_commitments(funder["id"])
    candidates = [from_dt.date()]
    for row in existing:
        if row["status"] != "ACTIVE":
            continue
        for boundary in (row["_effective_from"].date(), row["_effective_to"].date()):
            if from_dt.date() <= boundary <= to_dt.date() and boundary not in candidates:
                candidates.append(boundary)
    for instant in sorted(candidates):
        committed = rc.funder_committed_at(funder["id"], instant)
        if committed + committed_amount_cents > funder["capital_limit_cents"]:
            raise ApiError("ERR_FUNDER_CAPITAL_OVERCOMMITTED")

    row = base_row()
    row.update(
        {
            "funder_id": funder["id"],
            "committed_amount_cents": committed_amount_cents,
            "status": "ACTIVE",
        }
    )
    put_dt(row, "effective_from", from_dt, from_raw)
    put_dt(row, "effective_to", to_dt, to_raw)
    db.commitments[row["id"]] = row
    rc.recompute_funder_capital(funder)
    return ok(public(row), 201)


@bp.get("/funders/<funder_id>/commitments")
def list_commitments(funder_id):
    ctx = authenticate((FUNDER, PLATFORM_OPS, BUYER_TREASURY))
    limit, offset = pagination()
    funder = get_funder(funder_id)
    scope_funder(ctx, funder["id"])
    rows = rc.funder_commitments(funder["id"])
    status = filter_arg("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)
