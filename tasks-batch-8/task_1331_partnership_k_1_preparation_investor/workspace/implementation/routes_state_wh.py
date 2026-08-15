"""Special allocations, composite filings, withholding records."""
from fractions import Fraction

from flask import Blueprint, request

from auth import TRIO_ROLES, require_roles
from db import db, now, new_entity, touch, fmt_ts
from util import ApiError, envelope, parse_date, rhu
from validate import body_json, as_str, as_int, as_enum, as_date
import services as S
from routes import get_tax_year_or_404, get_partner_or_404, list_response

bp = Blueprint("state_wh", __name__)


# ---------------------------------------------------------------------------
# Special allocations
# ---------------------------------------------------------------------------

@bp.post("/funds/special-allocations")
def create_special_allocation():
    uid, _role = require_roles("TaxPreparer")
    body = body_json()
    tax_year_id = as_str(body, "tax_year_id")
    partner_id = as_str(body, "partner_id")
    category = as_enum(body, "category", S.SA_CATEGORIES)
    target = as_int(body, "target_pct_bps", lo=1, hi=10000)
    effective_from = as_date(body, "effective_from")
    effective_to = as_date(body, "effective_to")
    if parse_date(effective_to) <= parse_date(effective_from):
        raise ApiError("ERR_INVALID_REQUEST", 400, "effective_to must be strictly after effective_from")
    ty = get_tax_year_or_404(tax_year_id)
    partner = get_partner_or_404(partner_id)
    if partner["fund_id"] != ty["fund_id"]:
        raise ApiError("ERR_CROSS_FUND_REFERENCE", 409, "Partner and tax year belong to different funds")
    sa = new_entity()
    sa.update({
        "tax_year_id": tax_year_id,
        "partner_id": partner_id,
        "category": category,
        "target_pct_bps": target,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "proposed_by_user_id": uid,
        "reviewed_by_user_id": None,
        "status": "PROPOSED",
    })
    db.special_allocations[sa["id"]] = sa
    return envelope(S.serialize_sa(sa), 201)


def get_sa_or_404(sid):
    sa = db.special_allocations.get(sid)
    if sa is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Special allocation not found")
    return sa


@bp.get("/funds/special-allocations/<saId>")
def get_special_allocation(saId):
    require_roles(*TRIO_ROLES)
    return envelope(S.serialize_sa(get_sa_or_404(saId)), 200)


@bp.get("/funds/special-allocations")
def list_special_allocations():
    require_roles(*TRIO_ROLES)
    items = list(db.special_allocations.values())
    for param in ("tax_year_id", "partner_id", "category", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    return list_response(items, S.serialize_sa)


@bp.post("/funds/special-allocations/<saId>/approve")
def approve_special_allocation(saId):
    uid, _role = require_roles("TaxReviewer")
    body_json()
    sa = get_sa_or_404(saId)
    if sa["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Special allocation is not PROPOSED")
    if uid == sa["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Approver must differ from proposer")
    ty = db.tax_years[sa["tax_year_id"]]
    if ty["status"] not in ("OPEN", "BOOKS_CLOSED"):
        raise ApiError("ERR_TAX_YEAR_WINDOW_CLOSED", 409,
                       "Special allocations cannot be approved after the year is ALLOCATED")
    sa_from = parse_date(sa["effective_from"])
    sa_to = parse_date(sa["effective_to"])
    for other in db.special_allocations.values():
        if other["id"] == sa["id"]:
            continue
        if other["status"] not in ("PROPOSED", "APPROVED"):
            continue
        if (other["tax_year_id"], other["partner_id"], other["category"]) != \
                (sa["tax_year_id"], sa["partner_id"], sa["category"]):
            continue
        # half-open overlap: touching endpoints do NOT overlap
        if sa_from < parse_date(other["effective_to"]) and parse_date(other["effective_from"]) < sa_to:
            raise ApiError("ERR_SPECIAL_ALLOCATION_OVERLAP", 409,
                           "Window overlaps an existing special allocation")
    sa["status"] = "APPROVED"
    sa["reviewed_by_user_id"] = uid
    touch(sa)
    return envelope(S.serialize_sa(sa), 200)


@bp.post("/funds/special-allocations/<saId>/reject")
def reject_special_allocation(saId):
    uid, _role = require_roles("TaxReviewer")
    body_json()
    sa = get_sa_or_404(saId)
    if sa["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Special allocation is not PROPOSED")
    if uid == sa["proposed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "Rejecter must differ from proposer")
    sa["status"] = "REJECTED"
    sa["reviewed_by_user_id"] = uid
    touch(sa)
    return envelope(S.serialize_sa(sa), 200)


# ---------------------------------------------------------------------------
# Composite filings
# ---------------------------------------------------------------------------

@bp.post("/funds/composite-filings")
def create_composite_filing():
    require_roles("TaxPreparer")
    body = body_json()
    tax_year_id = as_str(body, "tax_year_id")
    state_code = as_str(body, "state_code")
    if len(state_code) != 2 or not state_code.isalpha() or state_code.upper() != state_code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "state_code must be a 2-letter code")
    apportionment = as_int(body, "apportionment_pct_bps", lo=1, hi=10000)
    rate = as_int(body, "composite_rate_bps", lo=0, hi=10000)
    min_income = as_int(body, "min_income_cents", lo=0)
    ty = get_tax_year_or_404(tax_year_id)
    for cf in db.composite_filings.values():
        if cf["tax_year_id"] == tax_year_id and cf["state_code"] == state_code:
            raise ApiError("ERR_DUPLICATE_COMPOSITE_FILING", 409,
                           "A composite filing already exists for this state and tax year")
    total_apport = sum(cf["apportionment_pct_bps"] for cf in db.composite_filings.values()
                       if cf["tax_year_id"] == tax_year_id)
    if total_apport + apportionment > 10000:
        raise ApiError("ERR_APPORTIONMENT_OVERFLOW", 422,
                       "Sum of apportionment shares would exceed 10000 bps")
    cf = new_entity()
    cf.update({
        "tax_year_id": tax_year_id,
        "state_code": state_code,
        "apportionment_pct_bps": apportionment,
        "composite_rate_bps": rate,
        "min_income_cents": min_income,
        "included_partner_ids": [],
        "total_state_source_income_cents": 0,
        "total_composite_tax_cents": 0,
        "filed_at": None,
        "status": "DRAFT",
    })
    db.composite_filings[cf["id"]] = cf
    # compute immediately when a LOCKED FINAL run already exists
    if S.locked_final_run(tax_year_id) is not None:
        S.recompute_composite_filing(cf)
    return envelope(S.serialize_cf(cf), 201)


def get_cf_or_404(cid):
    cf = db.composite_filings.get(cid)
    if cf is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Composite filing not found")
    return cf


@bp.get("/funds/composite-filings/<cfId>")
def get_composite_filing(cfId):
    require_roles(*TRIO_ROLES)
    return envelope(S.serialize_cf(get_cf_or_404(cfId)), 200)


@bp.get("/funds/composite-filings")
def list_composite_filings():
    require_roles(*TRIO_ROLES)
    items = list(db.composite_filings.values())
    for param in ("tax_year_id", "state_code", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return list_response(items, S.serialize_cf)


def require_locked_final_run(ty):
    run = S.locked_final_run(ty["id"])
    if run is not None:
        return run
    if S.stale_final_run(ty["id"]) is not None:
        raise ApiError("ERR_ALLOCATION_STALE", 409, "The tax year's FINAL run is STALE")
    raise ApiError("ERR_ALLOCATION_NOT_LOCKED", 409, "No LOCKED FINAL allocation run exists")


@bp.post("/funds/composite-filings/<cfId>/file")
def file_composite_filing(cfId):
    require_roles("TaxPreparer")
    body_json()
    cf = get_cf_or_404(cfId)
    if cf["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Composite filing is not DRAFT")
    ty = db.tax_years[cf["tax_year_id"]]
    if ty["status"] not in ("ALLOCATED", "UNDER_REVIEW", "APPROVED", "COMPLETED"):
        raise ApiError("ERR_TAX_YEAR_NOT_BOOKS_CLOSED", 409,
                       "Tax year must be ALLOCATED or later to file")
    require_locked_final_run(ty)
    S.recompute_composite_filing(cf)
    if not cf["included_partner_ids"]:
        raise ApiError("ERR_COMPOSITE_PARTNER_INELIGIBLE", 422,
                       "No partners are eligible for this composite filing")
    cf["status"] = "FILED"
    cf["filed_at"] = fmt_ts(now())
    touch(cf)
    return envelope(S.serialize_cf(cf), 200)


@bp.post("/funds/composite-filings/<cfId>/record-outcome")
def record_outcome_composite_filing(cfId):
    require_roles("FundTaxAdmin")
    body = body_json()
    outcome = as_enum(body, "outcome", {"ACCEPTED", "REJECTED"})
    cf = get_cf_or_404(cfId)
    if cf["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Composite filing is not FILED")
    if outcome == "ACCEPTED":
        cf["status"] = "ACCEPTED"
    else:
        cf["status"] = "DRAFT"
        cf["filed_at"] = None
    touch(cf)
    return envelope(S.serialize_cf(cf), 200)


# ---------------------------------------------------------------------------
# Withholding
# ---------------------------------------------------------------------------

@bp.post("/funds/withholding-accruals")
def create_withholding_accruals():
    require_roles("TaxPreparer")
    body = body_json()
    tax_year_id = as_str(body, "tax_year_id")
    quarter = as_int(body, "quarter", lo=1, hi=4)
    method = as_enum(body, "method", S.WH_METHODS)
    ty = get_tax_year_or_404(tax_year_id)
    foreign_partners = [p for p in db.partners.values()
                        if p["fund_id"] == ty["fund_id"] and p["is_foreign"] and p["status"] == "ACTIVE"]
    if not foreign_partners:
        raise ApiError("ERR_NO_FOREIGN_PARTNERS", 422,
                       "The tax year has no foreign ACTIVE partners")
    if method == "CURRENT_ACTUAL":
        # duplicate check (priority 10) precedes allocation prerequisite (priority 13)
        for p in foreign_partners:
            for wr in db.withholding_records.values():
                if (wr["partner_id"], wr["tax_year_id"], wr["quarter"]) == (p["id"], ty["id"], quarter):
                    raise ApiError("ERR_DUPLICATE_WITHHOLDING_ACCRUAL", 409,
                                   "A withholding record already exists for this partner, tax year, quarter")
        require_locked_final_run(ty)
    else:
        for p in foreign_partners:
            for wr in db.withholding_records.values():
                if (wr["partner_id"], wr["tax_year_id"], wr["quarter"]) == (p["id"], ty["id"], quarter):
                    raise ApiError("ERR_DUPLICATE_WITHHOLDING_ACCRUAL", 409,
                                   "A withholding record already exists for this partner, tax year, quarter")
    created = []
    for p in sorted(foreign_partners, key=lambda x: (x["created_at"], x["_seq"])):
        created.append(S.accrue_withholding_record(p, ty, quarter, method))
    return envelope([S.serialize_wr(w) for w in created], 201)


def get_wr_or_404(wid):
    wr = db.withholding_records.get(wid)
    if wr is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Withholding record not found")
    return wr


@bp.get("/funds/withholding-records/<wrId>")
def get_withholding_record(wrId):
    require_roles(*TRIO_ROLES)
    return envelope(S.serialize_wr(get_wr_or_404(wrId)), 200)


@bp.get("/funds/withholding-records")
def list_withholding_records():
    require_roles(*TRIO_ROLES)
    items = list(db.withholding_records.values())
    for param in ("partner_id", "tax_year_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [w for w in items if w[param] == v]
    q = request.args.get("quarter")
    if q is not None:
        try:
            qv = int(q)
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", 400, "quarter must be an integer")
        items = [w for w in items if w["quarter"] == qv]
    return list_response(items, S.serialize_wr)


@bp.post("/funds/withholding-records/<wrId>/remit")
def remit_withholding(wrId):
    require_roles("TaxPreparer")
    body = body_json()
    amount = as_int(body, "amount_cents")
    if amount <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be positive")
    wr = get_wr_or_404(wrId)
    if wr["status"] not in ("ACCRUED", "PARTIALLY_REMITTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Withholding record cannot accept remittances in its state")
    if wr["remitted_cents"] + amount > wr["accrued_cents"]:
        raise ApiError("ERR_REMIT_EXCEEDS_ACCRUED", 422,
                       "Remittance would exceed the remaining accrued amount")
    wr["remitted_cents"] += amount
    wr["status"] = "REMITTED" if wr["remitted_cents"] == wr["accrued_cents"] else "PARTIALLY_REMITTED"
    touch(wr)
    return envelope(S.serialize_wr(wr), 200)


@bp.post("/funds/withholding-records/<wrId>/reconcile")
def reconcile_withholding(wrId):
    require_roles("TaxReviewer")
    body_json()
    wr = get_wr_or_404(wrId)
    if wr["status"] not in ("ACCRUED", "PARTIALLY_REMITTED", "REMITTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409, "Withholding record is already RECONCILED")
    underpayment = max(0, wr["accrued_cents"] - wr["remitted_cents"])
    due = parse_date(wr["due_date"])
    clock_date = now().date()
    months = (clock_date.year - due.year) * 12 + (clock_date.month - due.month)
    if clock_date.day < due.day:
        months -= 1
    months = max(months, 0)
    effective_months = min(months, S.PENALTY_CAP_MONTHS)
    wr["penalty_cents"] = rhu(Fraction(underpayment) * S.PENALTY_MONTHLY_BPS * effective_months / 10000)
    wr["status"] = "RECONCILED"
    touch(wr)
    return envelope(S.serialize_wr(wr), 200)
