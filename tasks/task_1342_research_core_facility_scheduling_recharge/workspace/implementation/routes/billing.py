"""Recharge batches, recharge entries, fiscal years (PRD §3.9, §3.13)."""

from flask import Blueprint, request

from auth import authenticate, require_roles, is_entity_role, auth_id, auth_role
from errors import fail
from helpers import (
    Body, validate_body, is_int, ser_batch, ser_entry, ser_fiscal_year,
    open_batch, batch_live_totals, create_entry, award_status,
    contract_intersects_fy, suggested_internal_rate, OPERATING_OVERHEAD_CENTS,
    RATE_DEVIATION_FLAG_PCT,
)
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts
from decimal import Decimal

bp = Blueprint("billing", __name__)


def get_batch_or_404(bid):
    b = store.batches.get(bid)
    if b is None:
        fail("ERR_NOT_FOUND", "Recharge batch not found")
    return b


def get_entry_or_404(eid):
    e = store.entries.get(eid)
    if e is None:
        fail("ERR_NOT_FOUND", "Recharge entry not found")
    return e


def get_fy_or_404(fid):
    f = store.fiscal_years.get(fid)
    if f is None:
        fail("ERR_NOT_FOUND", "Fiscal year period not found")
    return f


def _fy_period_by_year(year):
    for p in store.fiscal_years.values():
        if p["fiscal_year"] == year:
            return p
    return None


# ---------------------------------------------------------------------------
# Recharge batches
# ---------------------------------------------------------------------------

@bp.route("/recharge-batches", methods=["POST"])
def create_batch():
    authenticate()
    require_roles("FinanceOfficer")
    body = Body(request.get_json(silent=True))
    # Priority 8 — FY of the period must exist and be OPEN
    year = body.get("period_year")
    if is_int(year):
        period = _fy_period_by_year(year)
        if period is None or period["status"] != "OPEN":
            fail("ERR_FY_CLOSED", "The period's fiscal year is missing or CLOSED")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"period_year", "period_month"},
        required={"period_year", "period_month"},
        checkers={
            "period_year": is_int,
            "period_month": lambda v: is_int(v) and 1 <= v <= 12,
        },
    )
    # Priority 22 — (period_year, period_month) unique
    for b in store.batches.values():
        if b["period_year"] == year and b["period_month"] == body.get("period_month"):
            fail("ERR_UNIQUE_CONSTRAINT", "A batch already exists for this period")
    # Priority 23 — at most one OPEN batch
    if open_batch() is not None:
        fail("ERR_DUPLICATE_OPEN_BATCH", "An OPEN recharge batch already exists")
    batch = new_entity({
        "period_year": year,
        "period_month": body.get("period_month"),
        "status": "OPEN",
        "finalized_at": None,
        "_frozen_entry_count": None,
        "_frozen_gross": None,
        "_frozen_offset": None,
        "_frozen_net": None,
    })
    store.batches[batch["id"]] = batch
    return ok_object(ser_batch(batch), status=201)


@bp.route("/recharge-batches", methods=["GET"])
def list_batches():
    authenticate()
    require_roles("FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    items = list(store.batches.values())
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_batch)


@bp.route("/recharge-batches/<bid>", methods=["GET"])
def get_batch(bid):
    authenticate()
    require_roles("FinanceOfficer")
    return ok_object(ser_batch(get_batch_or_404(bid)))


@bp.route("/recharge-batches/<bid>/finalize", methods=["POST"])
def finalize_batch(bid):
    authenticate()
    require_roles("FinanceOfficer")
    batch = get_batch_or_404(bid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if batch["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN batch can be finalized")
    # PENDING entries -> BILLED
    for e in store.entries.values():
        if e["batch_id"] == bid and e["status"] == "PENDING":
            e["status"] = "BILLED"
            touch(e)
    # Freeze totals once — immutable thereafter
    ec, gross, offset, net = batch_live_totals(batch)
    batch["_frozen_entry_count"] = ec
    batch["_frozen_gross"] = gross
    batch["_frozen_offset"] = offset
    batch["_frozen_net"] = net
    batch["status"] = "FINALIZED"
    batch["finalized_at"] = fmt_ts(now())
    touch(batch)
    return ok_object(ser_batch(batch))


# ---------------------------------------------------------------------------
# Recharge entries
# ---------------------------------------------------------------------------

@bp.route("/recharge-entries", methods=["GET"])
def list_entries():
    authenticate()
    require_roles("FinanceOfficer", "Researcher", "ExternalClient")
    limit, offset = parse_pagination(request.args)
    items = list(store.entries.values())
    if is_entity_role():
        items = [e for e in items if e["user_id"] == auth_id()]
    else:
        user_id = request.args.get("user_id")
        if user_id is not None:
            items = [e for e in items if e["user_id"] == user_id]
    for param in ("batch_id", "usage_log_id", "booking_id", "grant_id", "instrument_id", "kind", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e.get(param) == v]
    return paginate(sort_default(items), limit, offset, ser_entry)


@bp.route("/recharge-entries/<eid>", methods=["GET"])
def get_entry(eid):
    authenticate()
    require_roles("FinanceOfficer", "Researcher", "ExternalClient")
    e = get_entry_or_404(eid)
    if is_entity_role() and e["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
    return ok_object(ser_entry(e))


@bp.route("/recharge-entries/<eid>/dispute", methods=["POST"])
def dispute_entry(eid):
    authenticate()
    require_roles("Researcher", "ExternalClient", "FinanceOfficer")
    e = get_entry_or_404(eid)
    if is_entity_role() and e["user_id"] != auth_id():
        fail("ERR_FORBIDDEN", "Entity-backed callers may only dispute their own entries")
    # Priority 6 — state legality
    if e["status"] != "BILLED":
        fail("ERR_INVALID_STATE", "Only a BILLED entry can be disputed")
    body = Body(request.get_json(silent=True))
    # Priority 21 — dispute_reason required non-empty
    validate_body(
        body,
        allowed={"dispute_reason"},
        required={"dispute_reason"},
        checkers={"dispute_reason": lambda v: isinstance(v, str) and len(v.strip()) > 0},
    )
    e["status"] = "DISPUTED"
    e["dispute_reason"] = body.get("dispute_reason")
    touch(e)
    return ok_object(ser_entry(e))


@bp.route("/recharge-entries/<eid>/resolve-dispute", methods=["POST"])
def resolve_dispute(eid):
    authenticate()
    require_roles("FinanceOfficer")
    e = get_entry_or_404(eid)
    body = Body(request.get_json(silent=True))
    # Priority 6 — state legality
    if e["status"] != "DISPUTED":
        fail("ERR_INVALID_STATE", "Only a DISPUTED entry can be resolved")
    resolution = body.get("resolution")
    # Priority 7 — WRITE_OFF posts an ADJUSTMENT into the OPEN batch
    if resolution == "WRITE_OFF" and open_batch() is None:
        fail("ERR_BATCH_NOT_OPEN", "No OPEN recharge batch for the adjustment entry")
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"resolution", "note"},
        required={"resolution"},
        checkers={
            "resolution": lambda v: v in ("UPHOLD", "WRITE_OFF"),
            "note": lambda v: isinstance(v, str),
        },
    )
    if resolution == "UPHOLD":
        e["status"] = "BILLED"
        e["dispute_reason"] = None
        touch(e)
        return ok_object(ser_entry(e))
    # WRITE_OFF — compensating cascade
    batch = open_batch()
    e["status"] = "WRITTEN_OFF"
    touch(e)
    create_entry(
        batch_id=batch["id"],
        kind="ADJUSTMENT",
        amount=-e["amount_cents"],
        offset=0,
        status="PAID",
        user_id=e["user_id"],
        instrument_id=e["instrument_id"],
        grant_id=e.get("grant_id"),
        booking_id=None,
        usage_log_id=None,
        is_external=e.get("is_external", False),
    )
    # Subsidy reversal: restore each award's draw
    for award_id, amount in e.get("_draws", []):
        award = store.awards.get(award_id)
        if award is not None and amount:
            award["remaining_amount_cents"] += amount
            touch(award)
    return ok_object(ser_entry(e))


@bp.route("/recharge-entries/<eid>/mark-paid", methods=["POST"])
def mark_paid(eid):
    authenticate()
    require_roles("FinanceOfficer")
    e = get_entry_or_404(eid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if e["status"] != "BILLED":
        fail("ERR_INVALID_STATE", "Only a BILLED entry can be marked PAID")
    e["status"] = "PAID"
    touch(e)
    return ok_object(ser_entry(e))


# ---------------------------------------------------------------------------
# Fiscal years
# ---------------------------------------------------------------------------

@bp.route("/fiscal-years", methods=["POST"])
def create_fiscal_year():
    authenticate()
    require_roles("FinanceOfficer")
    body = Body(request.get_json(silent=True))
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"fiscal_year", "carryforward_in_cents"},
        required={"fiscal_year"},
        checkers={
            "fiscal_year": is_int,
            "carryforward_in_cents": is_int,
        },
    )
    # Priority 22 — fiscal_year unique
    fy_val = body.get("fiscal_year")
    for p in store.fiscal_years.values():
        if p["fiscal_year"] == fy_val:
            fail("ERR_UNIQUE_CONSTRAINT", "A fiscal year period already exists for this year")
    period = new_entity({
        "fiscal_year": fy_val,
        "status": "OPEN",
        "carryforward_in_cents": body.get("carryforward_in_cents", 0),
        "revenue_cents": None,
        "cash_revenue_cents": None,
        "cost_cents": None,
        "surplus_deficit_cents": None,
        "carryforward_out_cents": None,
        "closed_at": None,
    })
    store.fiscal_years[period["id"]] = period
    return ok_object(ser_fiscal_year(period), status=201)


@bp.route("/fiscal-years", methods=["GET"])
def list_fiscal_years():
    authenticate()
    require_roles("FinanceOfficer", "FacilityAdmin")
    limit, offset = parse_pagination(request.args)
    items = list(store.fiscal_years.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(sort_default(items), limit, offset, ser_fiscal_year)


@bp.route("/fiscal-years/<fid>", methods=["GET"])
def get_fiscal_year(fid):
    authenticate()
    require_roles("FinanceOfficer", "FacilityAdmin")
    return ok_object(ser_fiscal_year(get_fy_or_404(fid)))


@bp.route("/fiscal-years/<fid>/close", methods=["POST"])
def close_fiscal_year(fid):
    authenticate()
    require_roles("FinanceOfficer")
    period = get_fy_or_404(fid)
    body = Body(request.get_json(silent=True))
    if body.raw:
        for k in body.raw:
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6 — state legality
    if period["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN fiscal year can be closed")
    # Priority 40 — no OPEN batch whose period falls inside this FY
    for b in store.batches.values():
        if b["period_year"] == period["fiscal_year"] and b["status"] == "OPEN":
            fail("ERR_UNFINALIZED_BATCHES", "An in-year batch is still OPEN")
    fy = period["fiscal_year"]
    # Counted set: USAGE/PENALTY entries whose batch period falls in this FY
    batch_year = {b["id"]: b["period_year"] for b in store.batches.values()}
    counted = [e for e in store.entries.values()
               if e["kind"] in ("USAGE", "PENALTY") and batch_year.get(e["batch_id"]) == fy]
    revenue = sum(e["net_amount_cents"] for e in counted if e["status"] in ("BILLED", "PAID"))
    cash = sum(e["net_amount_cents"] for e in counted if e["status"] == "PAID")
    instruments_with_entries = {e["instrument_id"] for e in counted}
    cost = sum(c["annual_cost_cents"] for c in store.contracts.values()
               if contract_intersects_fy(c, fy))
    cost += OPERATING_OVERHEAD_CENTS * len(instruments_with_entries)
    surplus = revenue - cost
    period["revenue_cents"] = revenue
    period["cash_revenue_cents"] = cash
    period["cost_cents"] = cost
    period["surplus_deficit_cents"] = surplus
    period["carryforward_out_cents"] = surplus
    period["closed_at"] = fmt_ts(now())
    period["status"] = "CLOSED"
    touch(period)
    # Cascade: auto-create next year's period with the carryforward if absent
    next_period = _fy_period_by_year(fy + 1)
    if next_period is None:
        next_period = new_entity({
            "fiscal_year": fy + 1,
            "status": "OPEN",
            "carryforward_in_cents": surplus,
            "revenue_cents": None,
            "cash_revenue_cents": None,
            "cost_cents": None,
            "surplus_deficit_cents": None,
            "carryforward_out_cents": None,
            "closed_at": None,
        })
        store.fiscal_years[next_period["id"]] = next_period
    # Cascade: re-derive DRAFT/UNDER_REVIEW rate lines for the next FY and
    # flag lines deviating from the suggestion by more than 5%.
    carryforward = next_period["carryforward_in_cents"]
    for rs in list(store.rate_sets.values()):
        if rs["fiscal_year"] != (fy + 1) or rs["status"] not in ("DRAFT", "UNDER_REVIEW"):
            continue
        changed = False
        flags = rs.get("_line_flags") or [False] * len(rs["lines"])
        while len(flags) < len(rs["lines"]):
            flags.append(False)
        for i, line in enumerate(rs["lines"]):
            suggested = suggested_internal_rate(
                line["instrument_id"], fy + 1, carryforward, line["projected_billable_hours"])
            stored_rate = Decimal(int(line["internal_rate_cents_per_hour"]))
            base = Decimal(abs(suggested))
            deviation = abs(stored_rate - Decimal(suggested))
            over = deviation > base * RATE_DEVIATION_FLAG_PCT if base > 0 else stored_rate != 0
            if over and not flags[i]:
                flags[i] = True
                changed = True
        rs["_line_flags"] = flags
        if changed:
            touch(rs)
    return ok_object(ser_fiscal_year(period))
