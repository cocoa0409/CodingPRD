"""Buyer programme endpoints (PRD 3.1, 3.10)."""

from decimal import Decimal

from flask import Blueprint

from db import base_row, db, public, sorted_rows, touch
from middleware import (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS, SUPPLIER,
                        authenticate, get_buyer, get_program, scope_program)
from response import ok, ok_list
from services import calc, flows
from services import guards as g
from services import recompute as rc
from validation import (bad, body, filter_arg, opt_decimal, opt_enum, opt_int,
                        paginate, pagination, req_enum, req_int, req_str)

bp = Blueprint("programs", __name__)

READ_ROLES = (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS)
PROGRAM_TYPES = ("SUPPLIER_NAMED", "FIXED_RATE")
FUNDING_POLICIES = ("SELF_ONLY", "FUNDER_ONLY", "SELF_THEN_FUNDER")


@bp.post("/buyer-programs")
def create_program():
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    buyer_id = req_str(b, "buyer_id", 1)
    name = req_str(b, "name", 1, 120)
    program_type = req_enum(b, "program_type", PROGRAM_TYPES)
    max_apr = req_int(b, "max_acceptable_apr_bps", 200, 5000)
    fixed_apr = opt_int(b, "fixed_apr_bps", 1, 5000)
    min_days_early = opt_int(b, "min_days_early", 1, None, 5)
    cap_pct = opt_decimal(b, "concentration_cap_pct", Decimal("0.01"),
                          Decimal("100.00"), Decimal("60.00"))
    funding_policy = opt_enum(b, "funding_policy", FUNDING_POLICIES, "SELF_THEN_FUNDER")
    if program_type == "FIXED_RATE" and fixed_apr is None:
        bad("fixed_apr_bps")
    if program_type == "SUPPLIER_NAMED" and fixed_apr is not None:
        bad("fixed_apr_bps")

    buyer = get_buyer(buyer_id)
    scope_program(ctx, {"buyer_id": buyer["id"]})

    row = base_row()
    row.update(
        {
            "buyer_id": buyer["id"],
            "name": name,
            "program_type": program_type,
            "fixed_apr_bps": fixed_apr,
            "max_acceptable_apr_bps": max_apr,
            "min_days_early": min_days_early,
            "concentration_cap_pct": float(cap_pct),
            "_concentration_cap_pct": cap_pct,
            "funding_policy": funding_policy,
            "status": "DRAFT",
            "eligible_invoice_count": 0,
            "adopted_invoice_count": 0,
            "adoption_rate_pct": 0.00,
            "_adoption_rate_pct": Decimal("0.00"),
            "weighted_avg_accepted_apr_bps": 0,
            "rate_posture": "DISCOVERY",
        }
    )
    db.programs[row["id"]] = row
    return ok(public(row), 201)


@bp.get("/buyer-programs/<program_id>")
def read_program(program_id):
    ctx = authenticate(READ_ROLES)
    program = get_program(program_id)
    scope_program(ctx, program)
    return ok(public(program))


@bp.post("/buyer-programs/<program_id>/open")
def open_program(program_id):
    ctx = authenticate((BUYER_ADMIN,))
    program = get_program(program_id)
    scope_program(ctx, program)
    g.require_program_not_terminal(program)
    if program["status"] != "DRAFT":
        g.invalid_state("Only a DRAFT programme can be opened.")
    buyer = db.buyers.get(program["buyer_id"])
    if buyer is None or buyer["status"] != "ACTIVE":
        g.invalid_state("The owning buyer is not ACTIVE.")
    if program["program_type"] == "FIXED_RATE":
        if program["fixed_apr_bps"] is None:
            g.invalid_state("fixed_apr_bps must be set on a FIXED_RATE programme.")
        if program["fixed_apr_bps"] > program["max_acceptable_apr_bps"]:
            g.invalid_state("fixed_apr_bps exceeds max_acceptable_apr_bps.")
    program["status"] = "OPEN"
    rc.recompute_program_adoption(program, force=True)
    return ok(public(program))


@bp.post("/buyer-programs/<program_id>/status")
def program_status(program_id):
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    action = req_enum(b, "action", ("PAUSE", "RESUME", "CLOSE"))
    program = get_program(program_id)
    scope_program(ctx, program)
    g.require_program_not_terminal(program)

    if action == "PAUSE":
        if program["status"] != "OPEN":
            g.invalid_state("Only an OPEN programme can be paused.")
        program["status"] = "PAUSED"
        touch(program)
    elif action == "RESUME":
        if program["status"] != "PAUSED":
            g.invalid_state("Only a PAUSED programme can be resumed.")
        program["status"] = "OPEN"
        touch(program)
    else:
        if program["status"] not in ("DRAFT", "OPEN", "PAUSED"):
            g.invalid_state("The programme cannot be closed from its current state.")
        program["status"] = "CLOSED"
        touch(program)
        _close_cascade(program)
    return ok(public(program))


def _close_cascade(program):
    # hop 1: SCHEDULED / LIVE sessions become CANCELLED in created_at order
    cancelled = []
    sessions = sorted_rows(
        [s for s in db.sessions.values() if s["program_id"] == program["id"]]
    )
    for session in sessions:
        if session["status"] in ("SCHEDULED", "LIVE"):
            session["status"] = "CANCELLED"
            touch(session)
            cancelled.append(session)
    # hop 2: their outstanding offers expire in created_at order
    pending = []
    for session in cancelled:
        for offer in rc.session_offers(session["id"]):
            if offer["status"] in flows.OUTSTANDING_OFFER_STATUSES:
                pending.append(offer)
    flows.expire_offers(pending)
    for session in cancelled:
        if flows.refresh_named_offer_count(session):
            touch(session)
    # hop 3: the buyer is suspended once no programme remains live
    buyer = db.buyers.get(program["buyer_id"])
    if buyer is None:
        return
    for other in rc.buyer_programs(buyer["id"]):
        if other["status"] in ("DRAFT", "OPEN", "PAUSED"):
            return
    if buyer["status"] == "ACTIVE":
        buyer["status"] = "SUSPENDED"
        touch(buyer)


@bp.get("/buyer-programs/<program_id>/analytics")
def program_analytics(program_id):
    ctx = authenticate(READ_ROLES)
    program = get_program(program_id)
    scope_program(ctx, program)
    eligible, adopted, rate, posture, weighted = rc.adoption_figures(program["id"])
    data = {
        "eligible_invoice_count": eligible,
        "adopted_invoice_count": adopted,
        "adoption_rate_pct": float(rate),
        "rate_posture": posture,
        "weighted_avg_accepted_apr_bps": weighted,
        "max_acceptable_apr_bps": program["max_acceptable_apr_bps"],
        "concentration_top_supplier_face_pct": float(rc.top_supplier_face_pct(program["id"])),
        "concentration_top_supplier_funded_pct": float(rc.top_supplier_funded_pct(program["id"])),
        "concentration_cap_pct": float(program["_concentration_cap_pct"]),
    }
    return ok(data)


@bp.get("/buyer-programs/<program_id>/auction-sessions")
def list_program_sessions(program_id):
    ctx = authenticate((BUYER_ADMIN, BUYER_TREASURY, SUPPLIER, PLATFORM_OPS))
    limit, offset = pagination()
    program = get_program(program_id)
    scope_program(ctx, program)
    status = filter_arg("status")
    rows = sorted_rows(
        [s for s in db.sessions.values() if s["program_id"] == program["id"]]
    )
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.get("/buyer-programs/<program_id>/payable-files")
def list_program_files(program_id):
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    program = get_program(program_id)
    scope_program(ctx, program)
    ingest_status = filter_arg("ingest_status")
    rows = sorted_rows(
        [f for f in db.files.values() if f["program_id"] == program["id"]]
    )
    if ingest_status is not None:
        rows = [r for r in rows if r["ingest_status"] == ingest_status]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)
