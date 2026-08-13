"""All API routes."""
from datetime import date, timedelta
from fractions import Fraction

from flask import Blueprint, request

from auth import (ALL_ROLES, ADMIN_ROLES, TRIO_ROLES, auth_context, require_roles)
from db import db, now, new_entity, touch, fmt_ts
from util import ApiError, envelope, paginate, parse_date, parse_datetime, rhu, sort_created
from validate import body_json, as_str, as_int, as_bool, as_enum, as_date
import services as S

bp = Blueprint("api", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_fund_or_404(fund_id):
    f = db.funds.get(fund_id)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Fund not found")
    return f


def get_tax_year_or_404(tax_year_id):
    ty = db.tax_years.get(tax_year_id)
    if ty is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Tax year not found")
    return ty


def get_partner_or_404(partner_id):
    p = db.partners.get(partner_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Partner not found")
    return p


def tax_year_for_date(fund_id, d):
    for ty in db.tax_years.values():
        if ty["fund_id"] == fund_id and ty["year"] == d.year:
            return ty
    return None


def list_response(items, serializer):
    items = sort_created(items)
    page, page_meta = paginate(items)
    return envelope([serializer(i) for i in page], 200, pagination=page_meta)


def investor_owns_or_403(uid, partner_id):
    if uid != partner_id:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", 403, "Investor may only access own resources")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("FundTaxAdmin")
    body = body_json()
    raw = body.get("to_iso8601")
    try:
        dt = parse_datetime(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO 8601 timestamp")
    db.clock = dt
    return envelope({"current_utc": fmt_ts(db.clock)}, 200)


# ---------------------------------------------------------------------------
# Funds
# ---------------------------------------------------------------------------

@bp.post("/funds")
def create_fund():
    require_roles("FundTaxAdmin")
    body = body_json()
    legal_name = as_str(body, "legal_name")
    ein = as_str(body, "ein")
    hurdle = as_int(body, "waterfall_hurdle_rate_bps", lo=0, hi=10000)
    catchup = as_int(body, "waterfall_catchup_bps", lo=0, hi=10000)
    carry = as_int(body, "waterfall_carry_bps", lo=0, hi=10000)
    cap = as_int(body, "foreign_ownership_cap_pct_bps", lo=0, hi=10000)
    fee_rate = as_int(body, "management_fee_rate_bps", lo=0, hi=10000)
    fee_threshold = as_int(body, "fee_discount_threshold_cents", lo=0)
    fee_discount = as_int(body, "fee_discount_bps", lo=0, hi=10000)
    # uniqueness: ein unique across funds -> ERR_INVALID_REQUEST
    for f in db.funds.values():
        if f["ein"] == ein:
            raise ApiError("ERR_INVALID_REQUEST", 400, "ein already in use")
    f = new_entity()
    f.update({
        "legal_name": legal_name,
        "ein": ein,
        "waterfall_hurdle_rate_bps": hurdle,
        "waterfall_catchup_bps": catchup,
        "waterfall_carry_bps": carry,
        "foreign_ownership_cap_pct_bps": cap,
        "management_fee_rate_bps": fee_rate,
        "fee_discount_threshold_cents": fee_threshold,
        "fee_discount_bps": fee_discount,
    })
    db.funds[f["id"]] = f
    return envelope(S.serialize_fund(f), 201)


@bp.get("/funds/<fundId>")
def get_fund(fundId):
    require_roles(*ALL_ROLES)
    return envelope(S.serialize_fund(get_fund_or_404(fundId)), 200)


# ---------------------------------------------------------------------------
# Tax years
# ---------------------------------------------------------------------------

@bp.post("/funds/tax-years")
def create_tax_year():
    require_roles("FundTaxAdmin")
    body = body_json()
    fund_id = as_str(body, "fund_id")
    year = as_int(body, "year", lo=1800, hi=2500)
    gross = as_int(body, "gross_ordinary_income_cents")
    cg = as_int(body, "capital_gain_cents")
    interest = as_int(body, "interest_income_cents")
    ext = as_bool(body, "federal_extension_filed", default=False)
    fund = get_fund_or_404(fund_id)
    for ty in db.tax_years.values():
        if ty["fund_id"] == fund_id and ty["year"] == year:
            raise ApiError("ERR_DUPLICATE_TAX_YEAR", 409, "Tax year already exists for this fund and year")
    # management_fee_net_income: pinned top-down order, computed once at create
    fee_base = sum(p["capital_commitment_cents"] for p in db.partners.values()
                   if p["fund_id"] == fund_id and p["status"] == "ACTIVE")
    gross_fee = rhu(Fraction(fee_base) * fund["management_fee_rate_bps"] / 10000)
    discount = gross < fund["fee_discount_threshold_cents"]
    fee = rhu(Fraction(gross_fee) * (10000 - fund["fee_discount_bps"]) / 10000) if discount else gross_fee
    ty = new_entity()
    ty.update({
        "fund_id": fund_id,
        "year": year,
        "gross_ordinary_income_cents": gross,
        "capital_gain_cents": cg,
        "interest_income_cents": interest,
        "federal_extension_filed": ext,
        "management_fee_cents": fee,
        "net_ordinary_income_cents": gross - fee,
        "status": "OPEN",
    })
    db.tax_years[ty["id"]] = ty
    return envelope(S.serialize_tax_year(ty), 201)


@bp.get("/funds/tax-years/<taxYearId>")
def get_tax_year(taxYearId):
    require_roles(*ALL_ROLES)
    return envelope(S.serialize_tax_year(get_tax_year_or_404(taxYearId)), 200)


@bp.get("/funds/tax-years")
def list_tax_years():
    require_roles(*ADMIN_ROLES)
    items = list(db.tax_years.values())
    fund_id = request.args.get("fund_id")
    status = request.args.get("status")
    if fund_id is not None:
        items = [t for t in items if t["fund_id"] == fund_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items, S.serialize_tax_year)


@bp.post("/funds/tax-years/<taxYearId>/close-books")
def close_books(taxYearId):
    require_roles("FundTaxAdmin")
    body_json()
    ty = get_tax_year_or_404(taxYearId)
    if ty["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not OPEN")
    active = [p for p in db.partners.values() if p["fund_id"] == ty["fund_id"] and p["status"] == "ACTIVE"]
    if not active:
        raise ApiError("ERR_NO_ALLOCABLE_PARTNERS", 422, "At least one ACTIVE partner is required")
    ty["status"] = "BOOKS_CLOSED"
    touch(ty)
    return envelope(S.serialize_tax_year(ty), 200)


@bp.post("/funds/tax-years/<taxYearId>/submit-review")
def submit_review_tax_year(taxYearId):
    require_roles("TaxPreparer")
    body_json()
    ty = get_tax_year_or_404(taxYearId)
    if ty["status"] != "ALLOCATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not ALLOCATED")
    if S.locked_final_run(ty["id"]) is None:
        raise ApiError("ERR_ALLOCATION_NOT_LOCKED", 409, "No LOCKED FINAL allocation run exists")
    ty["status"] = "UNDER_REVIEW"
    touch(ty)
    return envelope(S.serialize_tax_year(ty), 200)


@bp.post("/funds/tax-years/<taxYearId>/approve")
def approve_tax_year(taxYearId):
    require_roles("TaxReviewer")
    body_json()
    ty = get_tax_year_or_404(taxYearId)
    if ty["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not UNDER_REVIEW")
    if S.locked_final_run(ty["id"]) is None:
        if S.stale_final_run(ty["id"]) is not None:
            raise ApiError("ERR_ALLOCATION_STALE", 409, "The tax year's FINAL run is STALE")
        raise ApiError("ERR_ALLOCATION_NOT_LOCKED", 409, "No LOCKED FINAL allocation run exists")
    ty["status"] = "APPROVED"
    touch(ty)
    return envelope(S.serialize_tax_year(ty), 200)


@bp.post("/funds/tax-years/<taxYearId>/reopen")
def reopen_tax_year(taxYearId):
    require_roles("FundTaxAdmin")
    body_json()
    ty = get_tax_year_or_404(taxYearId)
    if ty["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Tax year is not APPROVED")
    delivered = [k for k in db.k1_packages.values()
                 if k["tax_year_id"] == ty["id"] and k["prep_status"] == "DELIVERED"]
    if delivered:
        raise ApiError("ERR_K1_ALREADY_GENERATED", 409, "K-1 packages have already been delivered")
    S.mark_locked_runs_stale(ty["id"])
    ty["status"] = "BOOKS_CLOSED"
    touch(ty)
    return envelope(S.serialize_tax_year(ty), 200)


# ---------------------------------------------------------------------------
# Partners
# ---------------------------------------------------------------------------

@bp.post("/funds/partners")
def create_partner():
    require_roles("FundTaxAdmin")
    body = body_json()
    fund_id = as_str(body, "fund_id")
    legal_name = as_str(body, "legal_name")
    partner_type = as_enum(body, "partner_type", S.PARTNER_TYPES)
    partner_class = as_enum(body, "partner_class", S.PARTNER_CLASSES)
    residency_state = as_str(body, "residency_state")
    if len(residency_state) != 2 or not residency_state.isalpha() or residency_state.upper() != residency_state:
        raise ApiError("ERR_INVALID_REQUEST", 400, "residency_state must be a 2-letter code")
    ownership = as_int(body, "ownership_pct_bps", lo=1, hi=10000)
    commitment = as_int(body, "capital_commitment_cents", lo=0)
    admission = as_date(body, "admission_date")
    get_fund_or_404(fund_id)
    p = new_entity()
    p.update({
        "fund_id": fund_id,
        "legal_name": legal_name,
        "partner_type": partner_type,
        "partner_class": partner_class,
        "residency_state": residency_state,
        "ownership_pct_bps": ownership,
        "capital_commitment_cents": commitment,
        "admission_date": admission,
        "is_foreign": partner_type in S.FOREIGN_TYPES,
        "current_ownership_pct_bps": ownership,
        "capital_account_balance_cents": 0,
        "tax_basis_cents": 0,
        "excess_distribution_gain_cents": 0,
        "status": "ACTIVE",
    })
    db.partners[p["id"]] = p
    return envelope(S.serialize_partner(p), 201)


@bp.get("/funds/partners/<partnerId>")
def get_partner(partnerId):
    uid, role = require_roles(*ALL_ROLES)
    if role == "Investor":
        investor_owns_or_403(uid, partnerId)
    return envelope(S.serialize_partner(get_partner_or_404(partnerId)), 200)


@bp.get("/funds/partners")
def list_partners():
    require_roles(*ADMIN_ROLES)
    items = list(db.partners.values())
    fund_id = request.args.get("fund_id")
    status = request.args.get("status")
    ptype = request.args.get("partner_type")
    if fund_id is not None:
        items = [p for p in items if p["fund_id"] == fund_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if ptype is not None:
        items = [p for p in items if p["partner_type"] == ptype]
    return list_response(items, S.serialize_partner)


@bp.post("/funds/partners/<partnerId>/withdraw")
def withdraw_partner(partnerId):
    require_roles("FundTaxAdmin")
    body_json()
    p = get_partner_or_404(partnerId)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Partner is not ACTIVE")
    inflight = [k for k in db.k1_packages.values()
                if k["partner_id"] == p["id"] and k["prep_status"] in ("GENERATED", "REVIEWED", "APPROVED")]
    if inflight:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Partner has in-flight K-1 packages")
    S.refresh_partner_balances(p)
    if p["capital_account_balance_cents"] != 0:
        raise ApiError("ERR_PARTNER_CAPITAL_NOT_ZERO", 422, "Partner capital balance is not zero")
    p["status"] = "WITHDRAWN"
    touch(p)
    return envelope(S.serialize_partner(p), 200)


# ---------------------------------------------------------------------------
# Capital account events
# ---------------------------------------------------------------------------

@bp.post("/funds/capital-events")
def create_capital_event():
    require_roles("TaxPreparer")
    body = body_json()
    partner_id = as_str(body, "partner_id")
    tax_year_id = as_str(body, "tax_year_id")
    event_type = as_enum(body, "event_type", S.EVENT_TYPES)
    amount = as_int(body, "amount_cents")
    if amount == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be non-zero")
    effective_date = as_date(body, "effective_date")
    memo = body.get("memo")
    if memo is not None and not isinstance(memo, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "memo must be a string")
    partner = get_partner_or_404(partner_id)
    ty = get_tax_year_or_404(tax_year_id)
    # tax-year window (priority 8): effective_date inside a COMPLETED tax year
    eff = parse_date(effective_date)
    containing = tax_year_for_date(partner["fund_id"], eff)
    if containing is not None and containing["status"] == "COMPLETED":
        raise ApiError("ERR_TAX_YEAR_WINDOW_CLOSED", 409, "Effective date falls in a COMPLETED tax year")
    # cross-fund referential (priority 11)
    if partner["fund_id"] != ty["fund_id"]:
        raise ApiError("ERR_CROSS_FUND_REFERENCE", 409, "Partner and tax year belong to different funds")
    if not (date(ty["year"], 1, 1) <= eff <= date(ty["year"], 12, 31)):
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_date is outside the referenced tax year")
    # ledger guard (priority 12)
    if event_type == "DISTRIBUTION":
        S.refresh_partner_balances(partner)
        if amount > partner["capital_account_balance_cents"]:
            raise ApiError("ERR_DISTRIBUTION_EXCEEDS_CAPITAL", 422,
                           "Distribution exceeds current capital account balance")
    ev = S.make_capital_event(partner_id, tax_year_id, event_type, amount, effective_date, memo=memo)
    S.refresh_partner_balances(partner)
    touch(partner)
    return envelope(S.serialize_event(ev), 201)


@bp.get("/funds/capital-events/<eventId>")
def get_capital_event(eventId):
    require_roles(*TRIO_ROLES)
    ev = db.capital_events.get(eventId)
    if ev is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Capital event not found")
    return envelope(S.serialize_event(ev), 200)


@bp.get("/funds/capital-events")
def list_capital_events():
    require_roles(*TRIO_ROLES)
    items = list(db.capital_events.values())
    partner_id = request.args.get("partner_id")
    tax_year_id = request.args.get("tax_year_id")
    reverses = request.args.get("reverses_event_id")
    if partner_id is not None:
        items = [e for e in items if e["partner_id"] == partner_id]
    if tax_year_id is not None:
        items = [e for e in items if e["tax_year_id"] == tax_year_id]
    if reverses is not None:
        items = [e for e in items if e["reverses_event_id"] == reverses]
    return list_response(items, S.serialize_event)


@bp.post("/funds/capital-events/<eventId>/reverse")
def reverse_capital_event(eventId):
    require_roles("TaxPreparer")
    body = body_json()
    memo = body.get("memo")
    if memo is not None and not isinstance(memo, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "memo must be a string")
    ev = db.capital_events.get(eventId)
    if ev is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Capital event not found")
    if ev["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Event is already REVERSED")
    if ev["reverses_event_id"] is not None:
        raise ApiError("ERR_REVERSAL_OF_REVERSAL", 422, "A mirror event cannot be reversed")
    mirror = S.make_capital_event(ev["partner_id"], ev["tax_year_id"], ev["event_type"],
                                  -ev["amount_cents"], ev["effective_date"], memo=memo,
                                  reverses_event_id=ev["id"])
    ev["status"] = "REVERSED"
    touch(ev)
    partner = db.partners[ev["partner_id"]]
    S.refresh_partner_balances(partner)
    touch(partner)
    return envelope(S.serialize_event(mirror), 201)
