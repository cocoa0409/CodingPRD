"""Program endpoints (8) plus the report and the escheat sweep."""
from flask import Blueprint, g, request

import db
import middleware as mw
import response as resp
import serializers as ser
from errors import err
from services import budget, escheat

bp = Blueprint("programs", __name__)

READ_ROLES = ("ProgramAdmin", "ClaimsProcessor", "FinanceOfficer", "FraudAnalyst")


@bp.post("/api/programs")
@mw.require("ProgramAdmin")
def create_program():
    data = mw.body()
    name = mw.as_string(data, "name")
    budget_total = mw.as_int(data, "budget_total_cents", positive=True)
    fiscal_year = mw.as_int(data, "fiscal_year")
    jurisdiction = mw.as_string(data, "escheat_jurisdiction")

    rec = db.base_record()
    rec.update({
        "name": name,
        "fiscal_year": fiscal_year,
        "escheat_jurisdiction": jurisdiction,
        "budget_total_cents": budget_total,
        "status": "DRAFT",
    })
    db.programs[rec["id"]] = rec
    return resp.created(ser.program(rec))


@bp.get("/api/programs/<pid>")
@mw.require(*READ_ROLES)
def read_program(pid):
    program = db.get_program(pid)
    return resp.ok(ser.program(program))


@bp.get("/api/programs")
@mw.require(*READ_ROLES)
def list_programs():
    items = db.by_created(list(db.programs.values()))
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    fiscal_year = request.args.get("fiscal_year")
    if fiscal_year:
        try:
            fy = int(fiscal_year)
        except ValueError:
            raise err("ERR_VALIDATION", "fiscal_year must be an integer.")
        items = [p for p in items if p["fiscal_year"] == fy]
    return resp.paginated(items, ser.program)


@bp.post("/api/programs/<pid>/activate")
@mw.require("ProgramAdmin")
def activate_program(pid):
    program = db.get_program(pid)
    if program["status"] != "DRAFT" or program["budget_total_cents"] <= 0:
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program cannot be activated from its current state.")
    program["status"] = "ACTIVE"
    db.touch(program)
    budget.recompute(program)
    return resp.ok(ser.program(program))


@bp.post("/api/programs/<pid>/close")
@mw.require("ProgramAdmin")
def close_program(pid):
    program = db.get_program(pid)
    if program["status"] not in ("ACTIVE", "BUDGET_LOCKED"):
        raise err("ERR_PROGRAM_NOT_ACTIVE", "Program cannot be closed from its current state.")
    for claim in db.claims_of_program(pid):
        if claim["adjudication_status"] in db.CLAIM_OPEN_ADJ:
            raise err(
                "ERR_PROGRAM_NOT_ACTIVE",
                "In-flight adjudication must be finished before closing the program.",
            )
    program["status"] = "CLOSED"
    db.touch(program)
    for offer in db.offers_of_program(pid):
        if offer["status"] in ("DRAFT", "PUBLISHED", "SUSPENDED"):
            offer["status"] = "CLOSED"
            offer["closed_at"] = db.now()
            db.touch(offer)
    return resp.ok(ser.program(program))


@bp.post("/api/programs/<pid>/budget-adjustments")
@mw.require("ProgramAdmin")
def adjust_budget(pid):
    program = db.get_program(pid)
    data = mw.body()
    delta = mw.as_int(data, "delta_cents")
    memo = mw.as_string(data, "memo", required=False, allow_empty=True)
    expected = mw.as_int(data, "expected_program_version")

    if expected != program["version"]:
        raise err("ERR_STALE_PROGRAM_VERSION")

    new_total = program["budget_total_cents"] + delta
    if new_total <= 0:
        raise err("ERR_BUDGET_ADJUSTMENT_INVALID")

    program["budget_total_cents"] = new_total
    db.touch(program)
    budget.append_entry(program, "BUDGET_ADJUSTMENT", abs(delta), claim_id=None, memo=memo)
    budget.recompute(program, trigger="BUDGET_ADJUSTMENT")
    return resp.ok(ser.program(program))


@bp.get("/api/programs/<pid>/report")
@mw.require("ProgramAdmin", "ClaimsProcessor")
def program_report(pid):
    program = db.get_program(pid)
    pos = budget.position(program)

    counted = [
        c for c in db.claims_of_program(pid)
        if c["adjudication_status"] not in ("DRAFT", "WITHDRAWN", "VOIDED")
    ]
    submitted = [c for c in counted if c["submitted_at"] is not None]

    dealer = 0
    consumer = 0
    for c in submitted:
        cl = db.claimants.get(c["claimant_id"])
        if cl is None:
            continue
        if cl["type"] == "DEALER":
            dealer += 1
        elif cl["type"] == "CONSUMER":
            consumer += 1

    approved = [c for c in counted if c["adjudication_status"] == "APPROVED"]
    escheated_cents = sum(
        r["amount_cents"] for r in db.escheat_records.values() if r["program_id"] == pid
    )

    offer_rows = sorted(
        db.offers_of_program(pid),
        key=lambda o: (o["effective_start_date"], o["created_at"], o["_seq"]),
    )
    breakdown = []
    for offer in offer_rows:
        approved_cents = sum(
            (c["final_rebate_cents"] or 0)
            for c in db.claims_of_offer(offer["id"])
            if c["adjudication_status"] == "APPROVED"
        )
        breakdown.append({
            "offer_id": offer["id"],
            "active_claim_count": offer["active_claim_count"],
            "approved_rebate_cents": approved_cents,
        })

    return resp.ok({
        "program_id": pid,
        "claims_submitted": len(submitted),
        "claims_approved": len(approved),
        "claims_denied": len([c for c in counted if c["adjudication_status"] == "DENIED"]),
        "claims_revoked": len([c for c in counted if c["adjudication_status"] == "REVOKED"]),
        "dealer_claim_count": dealer,
        "consumer_claim_count": consumer,
        "approved_rebate_cents": sum((c["final_rebate_cents"] or 0) for c in approved),
        "escheated_cents": escheated_cents,
        "committed_cents": pos["committed_cents"],
        "available_cents": pos["available_cents"],
        "utilization_pct": float(pos["utilization_pct"]),
        "offer_breakdown": breakdown,
    })


@bp.post("/api/programs/<pid>/escheat-sweep")
@mw.require("ProgramAdmin")
def escheat_sweep(pid):
    program = db.get_program(pid)
    records = escheat.sweep(program)
    return resp.array_response(records, ser.escheat_record)
