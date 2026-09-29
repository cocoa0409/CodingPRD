"""Discount offer endpoints (PRD 3.6)."""

from flask import Blueprint

from db import (base_row, clock, clock_date, db, public, put_dt, sorted_rows,
                touch)
from errors import ApiError
from middleware import (BUYER_ADMIN, BUYER_TREASURY, PLATFORM_OPS, SUPPLIER,
                        authenticate, get_invoice, get_offer, get_session,
                        scope_offer, scope_supplier)
from response import ok, ok_list
from services import calc, flows
from services import guards as g
from services import recompute as rc
from validation import (bad, body, filter_arg, opt_dt, paginate, pagination,
                        req_dt, req_int, req_str)

bp = Blueprint("offers", __name__)

READ_ROLES = (BUYER_ADMIN, BUYER_TREASURY, SUPPLIER, PLATFORM_OPS)


def _context(offer):
    invoice = db.invoices.get(offer["invoice_id"])
    program = rc.program_of_invoice(invoice) if invoice else None
    session = db.sessions.get(offer["session_id"])
    supplier = db.suppliers.get(offer["supplier_id"])
    return invoice, program, session, supplier


def _refresh_session(session):
    if session is not None and flows.refresh_named_offer_count(session):
        touch(session)


@bp.post("/discount-offers")
def create_offer():
    ctx = authenticate((SUPPLIER,))
    b = body()
    invoice_id = req_str(b, "invoice_id", 1)
    session_id = req_str(b, "session_id", 1)
    offered_apr_bps = req_int(b, "offered_apr_bps", 1)
    pay_raw, pay_dt = req_dt(b, "requested_pay_date")
    deadline_raw, deadline_dt = req_dt(b, "acceptance_deadline")
    expected_invoice_version = req_int(b, "expected_invoice_version", 0)
    if pay_dt.date() < clock_date():
        bad(detail="requested_pay_date may not precede the current logical date.")
    if deadline_dt <= clock():
        bad(detail="acceptance_deadline must be strictly after the logical clock.")

    invoice = get_invoice(invoice_id)
    session = get_session(session_id)
    scope_supplier(ctx, invoice["supplier_id"])
    if deadline_dt > session["_closes_at"]:
        bad(detail="acceptance_deadline may not fall after the session closes.")

    program = rc.program_of_invoice(invoice)
    supplier = db.suppliers.get(invoice["supplier_id"])
    g.require_invoice_not_suppressed(invoice)
    g.require_program_open(program)
    g.require_session_live(session)

    if invoice["status"] not in ("ELIGIBLE", "OFFERED"):
        g.invalid_state("The invoice is not open to offers.")
    existing = rc.invoice_offers(invoice["id"])
    if invoice["status"] == "OFFERED":
        for other in existing:
            if other["status"] == "ACCEPTED":
                g.invalid_state("The invoice already carries an accepted offer.")

    g.require_invoice_version(invoice, expected_invoice_version)
    g.require_no_sanctions_hold(supplier)
    g.require_payment_ready(supplier)
    g.require_apr_in_program_bounds(program, offered_apr_bps)
    g.require_days_early(program, invoice, pay_dt)

    superseded_sessions = []
    for other in existing:
        if other["status"] in ("NAMED", "COUNTERED"):
            other["status"] = "SUPERSEDED"
            touch(other)
            superseded_sessions.append(db.sessions.get(other["session_id"]))

    offer = base_row()
    offer.update(
        {
            "invoice_id": invoice["id"],
            "session_id": session["id"],
            "supplier_id": invoice["supplier_id"],
            "offered_apr_bps": offered_apr_bps,
            "counter_apr_bps": None,
            "counter_round": 0,
            "status": "NAMED",
            "accepted_apr_bps": 0,
        }
    )
    put_dt(offer, "requested_pay_date", pay_dt, pay_raw)
    put_dt(offer, "acceptance_deadline", deadline_dt, deadline_raw)
    put_dt(offer, "accepted_at", None)
    db.offers[offer["id"]] = offer

    invoice["status"] = "OFFERED"
    touch(invoice)
    seen = []
    for candidate in superseded_sessions + [session]:
        if candidate is not None and candidate["id"] not in seen:
            seen.append(candidate["id"])
            _refresh_session(candidate)
    if program is not None:
        rc.recompute_program_adoption(program)
    return ok(public(offer), 201)


def _visible_offers(ctx):
    rows = []
    for offer in db.offers.values():
        if ctx.role == SUPPLIER and offer["supplier_id"] != ctx.uid:
            continue
        if ctx.is_buyer:
            invoice = db.invoices.get(offer["invoice_id"])
            program = rc.program_of_invoice(invoice) if invoice else None
            if program is None or program["buyer_id"] != ctx.uid:
                continue
        rows.append(offer)
    return sorted_rows(rows)


@bp.get("/discount-offers")
def list_offers():
    ctx = authenticate(READ_ROLES)
    limit, offset = pagination()
    rows = _visible_offers(ctx)
    for name in ("invoice_id", "session_id", "supplier_id", "status"):
        value = filter_arg(name)
        if value is not None:
            rows = [r for r in rows if r[name] == value]
    total = len(rows)
    return ok_list([public(r) for r in paginate(rows, limit, offset)], limit, offset, total)


@bp.get("/discount-offers/<offer_id>")
def read_offer(offer_id):
    ctx = authenticate(READ_ROLES)
    offer = get_offer(offer_id)
    scope_offer(ctx, offer)
    return ok(public(offer))


@bp.post("/discount-offers/<offer_id>/counter")
def counter_offer(offer_id):
    ctx = authenticate((BUYER_ADMIN,))
    b = body()
    counter_apr_bps = req_int(b, "counter_apr_bps", 1)
    offer = get_offer(offer_id)
    scope_offer(ctx, offer)
    invoice, program, session, supplier = _context(offer)
    g.require_invoice_not_suppressed(invoice)
    g.require_program_open(program)
    g.require_session_live(session)
    g.require_offer_not_terminal(offer)
    if offer["status"] != "NAMED":
        g.invalid_state("Only a NAMED offer can be countered.")
    if program["program_type"] != "SUPPLIER_NAMED":
        g.invalid_state("Countering is confined to SUPPLIER_NAMED programmes.")
    if counter_apr_bps <= offer["offered_apr_bps"]:
        g.invalid_state("counter_apr_bps must be strictly greater than offered_apr_bps.")
    g.require_no_sanctions_hold(supplier)
    g.require_apr_in_program_bounds(program, counter_apr_bps)
    if offer["counter_round"] >= calc.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_COUNTER_ROUNDS_EXHAUSTED")

    offer["counter_apr_bps"] = counter_apr_bps
    offer["status"] = "COUNTERED"
    touch(offer)
    _refresh_session(session)
    return ok(public(offer))


@bp.post("/discount-offers/<offer_id>/rename")
def rename_offer(offer_id):
    ctx = authenticate((SUPPLIER,))
    b = body()
    offered_apr_bps = req_int(b, "offered_apr_bps", 1)
    pay_raw, pay_dt = opt_dt(b, "requested_pay_date")
    offer = get_offer(offer_id)
    scope_offer(ctx, offer)
    invoice, program, session, supplier = _context(offer)
    g.require_invoice_not_suppressed(invoice)
    g.require_program_open(program)
    g.require_session_live(session)
    g.require_offer_not_terminal(offer)
    if offer["status"] != "COUNTERED":
        g.invalid_state("Only a COUNTERED offer can be renamed.")
    if offered_apr_bps <= offer["offered_apr_bps"]:
        g.invalid_state("The renamed rate must be strictly greater than the previous rate.")
    if offer["counter_round"] + 1 > calc.MAX_COUNTER_ROUNDS:
        g.invalid_state("The counter round budget is exhausted.")
    g.require_no_sanctions_hold(supplier)
    g.require_apr_in_program_bounds(program, offered_apr_bps)

    offer["offered_apr_bps"] = offered_apr_bps
    offer["counter_round"] += 1
    offer["counter_apr_bps"] = None
    offer["status"] = "NAMED"
    if pay_dt is not None:
        put_dt(offer, "requested_pay_date", pay_dt, pay_raw)
    touch(offer)
    _refresh_session(session)
    return ok(public(offer))


@bp.post("/discount-offers/<offer_id>/accept")
def accept_offer(offer_id):
    ctx = authenticate((BUYER_ADMIN, SUPPLIER))
    offer = get_offer(offer_id)
    if offer["status"] == "NAMED" and ctx.role != BUYER_ADMIN:
        raise ApiError("ERR_UNAUTHORIZED")
    if offer["status"] == "COUNTERED" and ctx.role != SUPPLIER:
        raise ApiError("ERR_UNAUTHORIZED")
    scope_offer(ctx, offer)
    invoice, program, session, supplier = _context(offer)
    g.require_invoice_not_suppressed(invoice)
    g.require_program_open(program)
    g.require_offer_not_terminal(offer)
    if not g.session_is_live_now(session):
        g.invalid_state("The governing auction session is not live.")
    if invoice["status"] != "OFFERED":
        g.invalid_state("The invoice is not in OFFERED.")
    g.require_no_sanctions_hold(supplier)
    g.require_payment_ready(supplier)
    g.require_acceptance_window_open(offer)

    locked = offer["offered_apr_bps"] if offer["status"] == "NAMED" else offer["counter_apr_bps"]
    g.require_apr_in_program_bounds(program, locked)
    g.require_concentration_within_cap(program, invoice)

    offer["accepted_apr_bps"] = locked
    offer["status"] = "ACCEPTED"
    put_dt(offer, "accepted_at", clock())
    touch(offer)

    invoice["status"] = "AWARDED"
    invoice["accepted_apr_bps"] = locked
    touch(invoice)
    _refresh_session(session)
    if program is not None:
        rc.recompute_program_adoption(program)
    return ok(public(offer))
