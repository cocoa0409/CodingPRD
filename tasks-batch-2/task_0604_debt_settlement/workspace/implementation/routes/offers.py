from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g, request

from db import store, stamp_new, touch, round_half_up
from errors import (
    fail,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_OFFER_EXPIRED,
    ERR_OFFER_WINDOW_OVERLAP,
    ERR_ACCOUNT_DEFAULTED,
    ERR_ACCOUNT_DELINQUENT,
    ERR_OFFER_ALREADY_ACCEPTED,
    ERR_PROJECTED_RESERVE_SHORTFALL,
    ERR_STALE_VERSION,
    ERR_NOT_PROGRAM_OWNER,
)
from middleware import require_roles
from response import success
from clock import clock, parse_iso8601
from routes.helpers import (
    get_body,
    require_fields,
    fraction,
    lookup,
    paginate,
    sort_by_created,
)
from services import core
from services.serialize import offer_out

bp = Blueprint("offers", __name__)


def _quote(debt, offer_pct):
    """settlement_offer_quote (§1.3). Returns (settlement_amount, projected_fee, effective_rate)."""
    current_balance = Decimal(str(debt["original_balance"])) if debt["status"] != "SETTLED" else Decimal("0")
    settlement_amount = round_half_up(current_balance * offer_pct, 2)
    eff_rate = core.effective_rate(Decimal(str(debt["fee_rate_pct"])), debt["status"])
    projected_fee = round_half_up(settlement_amount * eff_rate, 2)
    return settlement_amount, projected_fee, eff_rate


@bp.post("/offers")
@require_roles("NegotiationAgent")
def create_offer():
    body = get_body()
    require_fields(body, ["program_id", "debt_id", "offer_pct", "due_date"])
    program_id = body["program_id"]
    program = lookup(store.programs, program_id)
    debt = lookup(store.debts, body["debt_id"])

    # debt must belong to the same program
    if debt["program_id"] != program_id:
        fail(ERR_NOT_FOUND, "debt does not belong to the named program")

    offer_pct = fraction(body["offer_pct"], "offer_pct")
    due_raw = body["due_date"]
    due_dt = parse_iso8601(due_raw)
    if due_dt is None:
        fail(ERR_INVALID_REQUEST, "due_date must be a valid ISO8601 instant")

    # State precondition: if debt is ENROLLED it advances to IN_NEGOTIATION,
    # which requires program ACTIVE. Recording an offer requires the debt to be
    # in a state that admits offers (ENROLLED / IN_NEGOTIATION / LAWSUIT).
    if debt["status"] in ("SETTLED", "WITHDRAWN"):
        fail(ERR_INVALID_STATE, "Debt is terminal")
    if debt["status"] == "ENROLLED" and program["program_phase"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Program must be ACTIVE to begin negotiation")
    if debt["status"] in ("IN_NEGOTIATION", "LAWSUIT") and program["program_phase"] != "ACTIVE":
        fail(ERR_INVALID_STATE, "Program must be ACTIVE")

    # Offer due_date must be strictly after current clock
    if due_dt <= clock.get():
        fail(ERR_OFFER_EXPIRED, "Offer due_date is at or before the current time")

    # Window-overlap check vs existing PENDING offers on same debt (closed 30d buffer)
    core.expire_program_offers(program_id)
    gap = timedelta(days=core.MIN_OFFER_GAP_DAYS)
    for o in core.debt_offers(debt["id"]):
        if o["status"] == "PENDING":
            other_due = parse_iso8601(o["due_date"])
            if other_due is not None and abs(due_dt - other_due) <= gap:
                fail(ERR_OFFER_WINDOW_OVERLAP, "Offer due_date collides with an existing PENDING offer")

    settlement_amount, projected_fee, _ = _quote(debt, offer_pct)

    o = stamp_new({
        "program_id": program_id,
        "debt_id": debt["id"],
        "offer_pct": offer_pct,
        "settlement_amount": settlement_amount,
        "projected_fee": projected_fee,
        "due_date": due_raw,
        "status": "PENDING",
    })
    store.offers[o["id"]] = o

    # If debt was ENROLLED, advance to IN_NEGOTIATION
    if debt["status"] == "ENROLLED":
        debt["status"] = "IN_NEGOTIATION"
        touch(debt)

    return success(offer_out(o), status=201)


@bp.get("/offers/<oid>")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def get_offer(oid):
    o = lookup(store.offers, oid)
    _scope(o["program_id"])
    core.expire_offer_if_due(o)
    return success(offer_out(o))


@bp.get("/offers")
@require_roles("ProgramAdmin", "NegotiationAgent", "Client")
def list_offers():
    items = list(store.offers.values())
    program_id = request.args.get("program_id")
    debt_id = request.args.get("debt_id")
    status = request.args.get("status")
    # Lazily expire before filtering by status
    for o in items:
        core.expire_offer_if_due(o)
    if program_id is not None:
        items = [o for o in items if o["program_id"] == program_id]
    if debt_id is not None:
        items = [o for o in items if o["debt_id"] == debt_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if g.role == "Client":
        items = [o for o in items
                 if store.programs.get(o["program_id"], {}).get("client_id") == g.user_id]
    items = sort_by_created(items)
    page, pagination = paginate(items)
    return success([offer_out(o) for o in page], pagination=pagination)


@bp.post("/offers/<oid>/accept")
@require_roles("NegotiationAgent")
def accept_offer(oid):
    o = lookup(store.offers, oid)
    body = get_body()
    require_fields(body, ["expected_program_version"])
    expected_version = body["expected_program_version"]

    program = store.programs[o["program_id"]]
    debt = store.debts[o["debt_id"]]

    # Lazy expiry observed at acceptance
    core.expire_offer_if_due(o)

    # 1. State: offer must be PENDING (EXPIRED -> ERR_OFFER_EXPIRED, else INVALID_STATE)
    if o["status"] == "EXPIRED":
        fail(ERR_OFFER_EXPIRED, "Offer has expired")
    if o["status"] != "PENDING":
        fail(ERR_INVALID_STATE, "Offer is not PENDING")

    # 2. Account standing
    core.recompute_account_standing(program)
    if program["account_standing"] == "DEFAULTED":
        fail(ERR_ACCOUNT_DEFAULTED, "Program is DEFAULTED")
    if program["account_standing"] == "DELINQUENT":
        fail(ERR_ACCOUNT_DELINQUENT, "Program is DELINQUENT")

    # 3. Debt must have no other ACCEPTED offer
    for other in core.debt_offers(debt["id"]):
        if other["id"] != o["id"] and other["status"] == "ACCEPTED":
            fail(ERR_OFFER_ALREADY_ACCEPTED, "Debt already has an ACCEPTED offer")

    # 4. Forward-looking reserve check
    if not _projected_reserve_ok(program, o):
        fail(ERR_PROJECTED_RESERVE_SHORTFALL, "Projected balance is below required reserve")

    # 5. OCC: expected_program_version must equal Program.version
    if expected_version != program["version"]:
        fail(ERR_STALE_VERSION, "expected_program_version does not match")

    # Commit
    o["status"] = "ACCEPTED"
    touch(o)
    # sibling PENDING offers on the same debt -> REJECTED
    for other in core.debt_offers(debt["id"]):
        if other["id"] != o["id"] and other["status"] == "PENDING":
            other["status"] = "REJECTED"
            touch(other)
    program["version"] = program["version"] + 1
    program["updated_at"] = o["updated_at"]

    return success(offer_out(o))


@bp.post("/offers/<oid>/reject")
@require_roles("NegotiationAgent")
def reject_offer(oid):
    o = lookup(store.offers, oid)
    core.expire_offer_if_due(o)
    if o["status"] != "PENDING":
        fail(ERR_INVALID_STATE, "Offer is not PENDING")
    o["status"] = "REJECTED"
    touch(o)
    return success(offer_out(o))


def _projected_reserve_ok(program, offer):
    """projected_balance(due_date) >= settlement_amount + projected_fee + reserve_floor."""
    acct = core.account_for_program(program["id"])
    balance = core.account_balance(program["id"])
    reserve_floor = Decimal(str(acct["reserve_floor"])) if acct else Decimal("0")
    monthly = Decimal(str(program["monthly_deposit_amount"]))
    day = program["deposit_day_of_month"]
    due_dt = parse_iso8601(offer["due_date"])
    now = clock.get()

    projected = balance
    projected += _scheduled_deposit_sum(now, due_dt, day, monthly)

    required = (Decimal(str(offer["settlement_amount"]))
                + Decimal(str(offer["projected_fee"]))
                + reserve_floor)
    return projected >= required


def _scheduled_deposit_sum(now, due_dt, day, monthly):
    """Sum monthly deposits for each scheduled deposit day strictly after now
    and on or before due_dt (lower-open at now, upper-closed at due_dt)."""
    from datetime import datetime, timezone
    total = Decimal("0")
    if due_dt <= now:
        return total
    year, month = now.year, now.month
    # Walk from now's month through due_dt's month inclusive (day <= 28 always valid).
    while (year, month) <= (due_dt.year, due_dt.month):
        candidate = datetime(year, month, day, 0, 0, 0, tzinfo=timezone.utc)
        if now < candidate <= due_dt:
            total += monthly
        month += 1
        if month > 12:
            month = 1
            year += 1
    return total


def _scope(program_id):
    if g.role == "Client":
        p = store.programs.get(program_id)
        if p is None or p["client_id"] != g.user_id:
            fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own resources")
