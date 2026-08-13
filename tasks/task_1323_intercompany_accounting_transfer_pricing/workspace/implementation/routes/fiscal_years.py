"""FiscalYear resource (PRD 3.1)."""
from flask import Blueprint

import errors
from db import store, new_resource, touch, public, clock_iso
from errors import ApiError
from middleware import require_auth, get_body, get_path, is_int, ALL_ROLES
from response import ok_object
from services import calc

bp = Blueprint("fiscal_years", __name__)

_ADMIN = ["GroupTaxAdmin"]


@bp.post("/tp/fiscal_years")
def create_fiscal_year():
    require_auth(_ADMIN)
    body = get_body()
    year_index = body.get("year_index")
    revenue = body.get("group_revenue_eur")
    if not is_int(year_index):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "year_index is required and must be an integer")
    if not is_int(revenue):
        raise ApiError(errors.INVALID_REQUEST, 400,
                       "group_revenue_eur is required and must be an integer")
    for fy in store.fiscal_years.values():
        if fy["year_index"] == year_index:
            raise ApiError(errors.INVALID_REQUEST, 400,
                           "year_index must be unique across all fiscal years")
    fy = new_resource()
    fy.update({
        "year_index": year_index,
        "group_revenue_eur": revenue,
        "cbc_required": calc.cbc_required(revenue),
        "status": "OPEN",
        "consolidated_intercompany_net_cents": 0,
        "closed_at": None,
    })
    store.fiscal_years[fy["id"]] = fy
    return ok_object(public(fy), 201)


@bp.get("/tp/fiscal_years/<fiscalYearId>")
def get_fiscal_year(fiscalYearId):
    require_auth(ALL_ROLES)
    fy = get_path(store.fiscal_years, fiscalYearId)
    return ok_object(public(fy), 200)


@bp.post("/tp/fiscal_years/<fiscalYearId>/begin_closing")
def begin_closing(fiscalYearId):
    require_auth(_ADMIN)
    fy = get_path(store.fiscal_years, fiscalYearId)
    if fy["status"] != "OPEN":
        raise ApiError(errors.INVALID_STATE, 409,
                       "begin_closing requires the fiscal year to be OPEN")
    # Automatic elimination: every MATCHED transaction of the year -> ELIMINATED,
    # in chronological (created_at ASC) order, each booking its plug so the
    # consolidated net stays 0 by construction.
    matched = [t for t in store.transactions.values()
               if t["fiscal_year_id"] == fy["id"]
               and t["elimination_status"] == "MATCHED"]
    matched.sort(key=lambda t: t["_seq"])
    net = fy["consolidated_intercompany_net_cents"]
    for t in matched:
        plug = t["provider_revenue_cents"] - t["recipient_cost_cents"]
        t["_plug_cents"] = plug
        t["elimination_status"] = "ELIMINATED"
        touch(t)
        net += t["provider_revenue_cents"] - t["recipient_cost_cents"] - plug
    fy["consolidated_intercompany_net_cents"] = net
    fy["status"] = "CLOSING"
    touch(fy)
    return ok_object(public(fy), 200)


@bp.post("/tp/fiscal_years/<fiscalYearId>/close")
def close_fiscal_year(fiscalYearId):
    require_auth(_ADMIN)
    fy = get_path(store.fiscal_years, fiscalYearId)
    if fy["status"] != "CLOSING":
        raise ApiError(errors.INVALID_STATE, 409,
                       "close requires the fiscal year to be CLOSING")
    # Preconditions in scaffold order (transactions, true-ups, then CbC filing).
    for t in store.transactions.values():
        if t["fiscal_year_id"] == fy["id"] and t["elimination_status"] != "ELIMINATED":
            raise ApiError(errors.YEAR_HAS_OPEN_TRANSACTIONS, 409,
                           "Year close blocked by transactions not yet ELIMINATED")
    for r in store.true_up_runs.values():
        if r["fiscal_year_id"] == fy["id"] and r["status"] != "POSTED":
            raise ApiError(errors.YEAR_HAS_OPEN_TRUE_UPS, 409,
                           "Year close blocked by true-up runs not yet POSTED")
    if fy["cbc_required"]:
        filed = any(d["fiscal_year_id"] == fy["id"]
                    and d["doc_type"] == "CBC_REPORT" and d["status"] == "FILED"
                    for d in store.doc_packages.values())
        if not filed:
            raise ApiError(errors.CBC_FILING_MISSING, 409,
                           "A FILED CBC_REPORT package is required before close")
    fy["status"] = "CLOSED"
    fy["closed_at"] = clock_iso()
    touch(fy)
    # Cascade link 1: CURRENT studies aged out (vintage <= year_index - 2) -> STALE.
    newly_stale = []
    for s in store.studies.values():
        if s["status"] == "CURRENT" and s["vintage_year"] <= fy["year_index"] - 2:
            s["status"] = "STALE"
            touch(s)
            newly_stale.append(s["id"])
    # Cascade link 2: agreements pinned to newly-STALE studies need pricing review.
    for a in store.agreements.values():
        if a["pinned_study_id"] in newly_stale and not a["pricing_review_required"]:
            a["pricing_review_required"] = True
            touch(a)
    return ok_object(public(fy), 200)
