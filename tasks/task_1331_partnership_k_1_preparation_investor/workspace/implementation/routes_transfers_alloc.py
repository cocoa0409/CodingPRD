"""Ownership transfers and allocation runs."""
from datetime import date, timedelta
from fractions import Fraction

from flask import Blueprint, request

from auth import TRIO_ROLES, require_roles
from db import db, now, new_entity, touch, fmt_ts
from util import ApiError, envelope, paginate, parse_date, rhu, sort_created
from validate import body_json, as_str, as_int, as_enum, as_date
import services as S
from routes import get_fund_or_404, get_partner_or_404, get_tax_year_or_404, list_response

bp = Blueprint("transfers_alloc", __name__)


def get_transfer_or_404(tid):
    t = db.transfers.get(tid)
    if t is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Transfer not found")
    return t


def get_run_or_404(rid):
    r = db.allocation_runs.get(rid)
    if r is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Allocation run not found")
    return r


# ---------------------------------------------------------------------------
# Ownership transfers
# ---------------------------------------------------------------------------

@bp.post("/funds/transfers")
def create_transfer():
    require_roles("FundTaxAdmin")
    body = body_json()
    fund_id = as_str(body, "fund_id")
    transferor_id = as_str(body, "transferor_partner_id")
    transferee_id = as_str(body, "transferee_partner_id")
    pct = as_int(body, "pct_bps", lo=1, hi=10000)
    effective_date = as_date(body, "effective_date")
    settlement_date = as_date(body, "settlement_date")
    if parse_date(settlement_date) < parse_date(effective_date):
        raise ApiError("ERR_INVALID_REQUEST", 400, "settlement_date must be on or after effective_date")
    get_fund_or_404(fund_id)
    transferor = get_partner_or_404(transferor_id)
    transferee = get_partner_or_404(transferee_id)
    if transferor["fund_id"] != fund_id or transferee["fund_id"] != fund_id:
        raise ApiError("ERR_CROSS_FUND_REFERENCE", 409, "Partners must belong to the stated fund")
    if transferor_id == transferee_id:
        raise ApiError("ERR_SAME_PARTNER_TRANSFER", 422, "Transferor and transferee must differ")
    t = new_entity()
    t.update({
        "fund_id": fund_id,
        "transferor_partner_id": transferor_id,
        "transferee_partner_id": transferee_id,
        "pct_bps": pct,
        "effective_date": effective_date,
        "settlement_date": settlement_date,
        "transferred_capital_cents": None,
        "status": "PROPOSED",
    })
    db.transfers[t["id"]] = t
    return envelope(S.serialize_transfer(t), 201)


@bp.get("/funds/transfers/<transferId>")
def get_transfer(transferId):
    require_roles(*TRIO_ROLES)
    return envelope(S.serialize_transfer(get_transfer_or_404(transferId)), 200)


@bp.get("/funds/transfers")
def list_transfers():
    require_roles(*TRIO_ROLES)
    items = list(db.transfers.values())
    for param, field in (("fund_id", "fund_id"),
                         ("transferor_partner_id", "transferor_partner_id"),
                         ("transferee_partner_id", "transferee_partner_id"),
                         ("status", "status")):
            v = request.args.get(param)
            if v is not None:
                items = [t for t in items if t[field] == v]
    return list_response(items, S.serialize_transfer)


@bp.post("/funds/transfers/<transferId>/confirm")
def confirm_transfer(transferId):
    require_roles("FundTaxAdmin")
    body_json()
    t = get_transfer_or_404(transferId)
    if t["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Transfer is not PROPOSED")
    transferor = db.partners.get(t["transferor_partner_id"])
    transferee = db.partners.get(t["transferee_partner_id"])
    if transferor is None or transferee is None:
        raise ApiError("ERR_CROSS_FUND_REFERENCE", 409, "Partners must exist in the same fund")
    if transferor["fund_id"] != transferee["fund_id"]:
        raise ApiError("ERR_CROSS_FUND_REFERENCE", 409, "Partners must belong to the same fund")
    if transferor["id"] == transferee["id"]:
        raise ApiError("ERR_SAME_PARTNER_TRANSFER", 422, "Transferor and transferee must differ")
    if transferor["status"] != "ACTIVE" or transferee["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Both partners must be ACTIVE")
    fund = db.funds[t["fund_id"]]
    # foreign ownership projection (inclusive cap)
    projected = {}
    for p in db.partners.values():
        if p["fund_id"] != t["fund_id"] or p["status"] != "ACTIVE":
            continue
        own = S.current_ownership(p)
        if p["id"] == transferor["id"]:
            own -= t["pct_bps"]
        elif p["id"] == transferee["id"]:
            own += t["pct_bps"]
        projected[p["id"]] = own
    total_own = sum(projected.values())
    foreign_own = sum(v for pid, v in projected.items() if db.partners[pid]["is_foreign"])
    if total_own > 0 and foreign_own * 10000 > fund["foreign_ownership_cap_pct_bps"] * total_own:
        raise ApiError("ERR_FOREIGN_OWNERSHIP_CAP_EXCEEDED", 409,
                       "Projected foreign ownership exceeds the fund cap")
    # tax-year window: effective_date inside a COMPLETED tax year
    eff = parse_date(t["effective_date"])
    containing = None
    for ty in db.tax_years.values():
        if ty["fund_id"] == t["fund_id"] and ty["year"] == eff.year:
            containing = ty
            break
    if containing is not None and containing["status"] == "COMPLETED":
        raise ApiError("ERR_TAX_YEAR_WINDOW_CLOSED", 409, "Effective date falls in a COMPLETED tax year")
    # closed-interval overlap per transferor (shared endpoint counts as overlap)
    eff_d = parse_date(t["effective_date"])
    set_d = parse_date(t["settlement_date"])
    for other in db.transfers.values():
        if other["id"] == t["id"]:
            continue
        if other["transferor_partner_id"] != t["transferor_partner_id"]:
            continue
        if other["status"] not in ("PROPOSED", "CONFIRMED", "SETTLED"):
            continue
        o_eff = parse_date(other["effective_date"])
        o_set = parse_date(other["settlement_date"])
        if eff_d <= o_set and o_eff <= set_d:
            raise ApiError("ERR_TRANSFER_WINDOW_OVERLAP", 409,
                           "Transfer window overlaps another transfer of the same transferor")
    # ledger guard
    if t["pct_bps"] > S.current_ownership(transferor):
        raise ApiError("ERR_INSUFFICIENT_OWNERSHIP", 422,
                       "pct_bps exceeds the transferor's current ownership")
    t["status"] = "CONFIRMED"
    touch(t)
    return envelope(S.serialize_transfer(t), 200)


@bp.post("/funds/transfers/<transferId>/settle")
def settle_transfer(transferId):
    require_roles("FundTaxAdmin")
    body_json()
    t = get_transfer_or_404(transferId)
    if t["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Transfer is not CONFIRMED")
    if now().date() < parse_date(t["settlement_date"]):
        raise ApiError("ERR_TAX_YEAR_WINDOW_CLOSED", 409, "Settlement date has not been reached")
    transferor = db.partners[t["transferor_partner_id"]]
    transferee = db.partners[t["transferee_partner_id"]]
    eff = parse_date(t["effective_date"])
    book = S.book_balance_at(transferor["id"], eff)
    denom = S.ownership_at_date(transferor, eff - timedelta(days=1))
    if denom > 0:
        t["transferred_capital_cents"] = rhu(Fraction(book) * t["pct_bps"] / denom)
    else:
        t["transferred_capital_cents"] = 0
    # cascade hop 1: transfer events
    tax_year = None
    for ty in db.tax_years.values():
        if ty["fund_id"] == t["fund_id"] and ty["year"] == eff.year:
            tax_year = ty
            break
    ty_id = tax_year["id"] if tax_year is not None else None
    S.make_capital_event(transferor["id"], ty_id, "TRANSFER_OUT",
                         t["transferred_capital_cents"], t["effective_date"])
    S.make_capital_event(transferee["id"], ty_id, "TRANSFER_IN",
                         t["transferred_capital_cents"], t["effective_date"])
    # cascade hop 2: balances + ownership recompute
    S.refresh_partner_balances(transferor)
    S.refresh_partner_balances(transferee)
    touch(transferor)
    touch(transferee)
    # cascade hop 3: LOCKED runs of the containing tax year -> STALE (hop 4 inside)
    if tax_year is not None:
        S.mark_locked_runs_stale(tax_year["id"])
    t["status"] = "SETTLED"
    touch(t)
    return envelope(S.serialize_transfer(t), 200)


@bp.post("/funds/transfers/<transferId>/cancel")
def cancel_transfer(transferId):
    require_roles("FundTaxAdmin")
    body_json()
    t = get_transfer_or_404(transferId)
    if t["status"] not in ("PROPOSED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Transfer cannot be cancelled from its state")
    t["status"] = "CANCELLED"
    touch(t)
    return envelope(S.serialize_transfer(t), 200)


# ---------------------------------------------------------------------------
# Allocation runs
# ---------------------------------------------------------------------------

@bp.post("/funds/allocation-runs")
def create_allocation_run():
    require_roles("TaxPreparer")
    body = body_json()
    tax_year_id = as_str(body, "tax_year_id")
    run_kind = as_enum(body, "run_kind", S.RUN_KINDS)
    expected_version = as_int(body, "expected_tax_year_version")
    ty = get_tax_year_or_404(tax_year_id)
    # optimistic concurrency control
    if expected_version != ty["version"]:
        raise ApiError("ERR_STALE_TAX_YEAR_VERSION", 412,
                       "expected_tax_year_version does not match the tax year's current version")
    # tax-year window per run kind
    if run_kind == "PROVISIONAL":
        if ty["status"] not in ("OPEN", "BOOKS_CLOSED"):
            raise ApiError("ERR_TAX_YEAR_NOT_BOOKS_CLOSED", 409,
                           "PROVISIONAL runs require an OPEN or BOOKS_CLOSED tax year")
    else:
        if ty["status"] not in ("BOOKS_CLOSED", "ALLOCATED", "UNDER_REVIEW", "APPROVED"):
            raise ApiError("ERR_TAX_YEAR_NOT_BOOKS_CLOSED", 409,
                           "FINAL runs require BOOKS_CLOSED or later (non-COMPLETED) tax year")
    participants = [p for p in db.partners.values()
                    if p["fund_id"] == ty["fund_id"] and p["status"] == "ACTIVE"]
    if not participants:
        raise ApiError("ERR_NO_ALLOCABLE_PARTNERS", 422, "Allocation requires at least one ACTIVE partner")
    totals, amounts, mechs, participants = S.compute_allocation(ty, run_kind)
    # supersede prior COMPUTED/STALE runs of this tax year
    for r in db.allocation_runs.values():
        if r["tax_year_id"] == ty["id"] and r["status"] in ("COMPUTED", "STALE"):
            r["status"] = "SUPERSEDED"
            touch(r)
    run = new_entity()
    run_seq = 1 + max([r["run_seq"] for r in db.allocation_runs.values()
                       if r["tax_year_id"] == ty["id"]] or [0])
    run.update({
        "tax_year_id": ty["id"],
        "run_kind": run_kind,
        "run_seq": run_seq,
        "ordinary_total_cents": totals["ORDINARY"],
        "capital_gain_total_cents": totals["CAPITAL_GAIN"],
        "interest_total_cents": totals["INTEREST"],
        "computed_at": fmt_ts(now()),
        "status": "COMPUTED",
    })
    db.allocation_runs[run["id"]] = run
    for p in participants:
        for cat in ("ORDINARY", "CAPITAL_GAIN", "INTEREST"):
            line = new_entity()
            line.update({
                "run_id": run["id"],
                "partner_id": p["id"],
                "category": cat,
                "amount_cents": amounts[p["id"]][cat],
                "applied_mechanism": mechs[p["id"]][cat],
            })
            db.allocation_lines[line["id"]] = line
    touch(ty)
    return envelope(S.serialize_run(run), 201)


@bp.get("/funds/allocation-runs/<runId>")
def get_run(runId):
    require_roles(*TRIO_ROLES)
    return envelope(S.serialize_run(get_run_or_404(runId)), 200)


@bp.get("/funds/allocation-runs")
def list_runs():
    require_roles(*TRIO_ROLES)
    items = list(db.allocation_runs.values())
    tax_year_id = request.args.get("tax_year_id")
    status = request.args.get("status")
    if tax_year_id is not None:
        items = [r for r in items if r["tax_year_id"] == tax_year_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items, S.serialize_run)


@bp.post("/funds/allocation-runs/<runId>/lock")
def lock_run(runId):
    require_roles("TaxReviewer")
    body_json()
    run = get_run_or_404(runId)
    if run["status"] != "COMPUTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Run is not COMPUTED")
    if run["run_kind"] != "FINAL":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Only a FINAL run can be locked")
    ty = db.tax_years[run["tax_year_id"]]
    if ty["status"] not in ("BOOKS_CLOSED", "ALLOCATED", "UNDER_REVIEW", "APPROVED"):
        raise ApiError("ERR_TAX_YEAR_NOT_BOOKS_CLOSED", 409,
                       "Tax year is not in a lockable state")
    for cat in ("ORDINARY", "CAPITAL_GAIN", "INTEREST"):
        total_pct = sum(sa["target_pct_bps"] for sa in db.special_allocations.values()
                        if sa["tax_year_id"] == ty["id"] and sa["status"] == "APPROVED"
                        and sa["category"] == cat)
        if total_pct > 10000:
            raise ApiError("ERR_SPECIAL_ALLOCATION_OVERFLOW", 422,
                           "Approved special allocations exceed 100%% of category %s" % cat)
    S.post_allocation_share_events(run)
    run["status"] = "LOCKED"
    touch(run)
    if ty["status"] == "BOOKS_CLOSED":
        ty["status"] = "ALLOCATED"
    touch(ty)
    return envelope(S.serialize_run(run), 200)


@bp.get("/funds/allocation-runs/<runId>/lines")
def list_run_lines(runId):
    require_roles(*TRIO_ROLES)
    run = get_run_or_404(runId)
    return list_response(S.run_lines(run["id"]), S.serialize_line)


@bp.get("/funds/partners/<partnerId>/allocation-lines")
def list_partner_lines(partnerId):
    require_roles(*TRIO_ROLES)
    p = get_partner_or_404(partnerId)
    items = [l for l in db.allocation_lines.values() if l["partner_id"] == p["id"]]
    return list_response(items, S.serialize_line)
