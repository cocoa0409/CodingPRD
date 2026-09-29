"""Exclusive-use clauses and radius restrictions."""
from flask import Blueprint

import engine
import validate as v
from crud import apply_filters, base, paginate, resolve, strip
from db import store
from errors import ApiError
from middleware import LIST_READ_ROLES, SINGLE_READ_ROLES, authorize
from response import created, listing, ok
from util import D, as_date, q2

bp = Blueprint("clauses", __name__)

SCOPES = ("CENTER_WIDE", "PAD_EXCLUDED", "RADIUS_INCLUSIVE")
MEASURED_FROM = ("CENTER_BOUNDARY", "PREMISES_CENTROID")
RECAPTURE_BASES = ("GROSS_SALES", "INCREMENTAL_SALES")


@bp.post("/leases/<lease_id>/exclusive-use-clauses")
def create_clause(lease_id):
    authorize(["LeaseAdministrator"])
    body = v.body()
    protected_use_codes = v.req_str_list(body, "protected_use_codes", min_len=1)
    scope = v.req_enum(body, "exclusivity_scope", SCOPES)
    carve_out = v.opt_int(body, "gla_carve_out_sqft", default=0, minimum=0)
    cap = v.opt_pct(body, "incidental_sales_pct_cap", default=D(0))
    from_date = v.req_date(body, "effective_from_date")
    through_date = v.req_date(body, "effective_through_date")
    if as_date(through_date) <= as_date(from_date):
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_through_date must be strictly after "
                       "effective_from_date")

    lease = resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    center = engine.center_of_lease(lease)
    if center["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_CENTER_EXECUTION_FROZEN")

    clause = base(engine.stamp())
    clause.update({
        "lease_id": lease["id"],
        "protected_use_codes": protected_use_codes,
        "exclusivity_scope": scope,
        "gla_carve_out_sqft": carve_out,
        "incidental_sales_pct_cap": q2(cap),
        "effective_from_date": from_date,
        "effective_through_date": through_date,
        "status": "ACTIVE",
        "suspended_by_plan_id": None,
    })
    store.clauses[clause["id"]] = clause
    engine.bump_center(center)
    return created(strip(clause))


@bp.get("/exclusive-use-clauses/<clause_id>")
def read_clause(clause_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(resolve(store.clauses, clause_id, "ERR_CLAUSE_NOT_FOUND")))


@bp.get("/exclusive-use-clauses")
def list_clauses():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.clauses.values()))
    records = apply_filters(records, [
        ("lease_id", v.filter_value("lease_id")),
        ("suspended_by_plan_id", v.filter_value("suspended_by_plan_id")),
        ("status", v.filter_value("status")),
        ("exclusivity_scope", v.filter_value("exclusivity_scope")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)


@bp.post("/leases/<lease_id>/radius-restrictions")
def create_restriction(lease_id):
    authorize(["LeaseAdministrator"])
    body = v.body()
    radius_miles = v.req_number(body, "radius_miles", exclusive_min=0)
    measured_from = v.req_enum(body, "measured_from", MEASURED_FROM)
    recapture_basis = v.req_enum(body, "recapture_basis", RECAPTURE_BASES)
    recapture_pct = v.req_pct(body, "recapture_pct", exclusive_min=0)
    baseline = v.opt_int(body, "protected_baseline_cents", default=0, minimum=0)
    from_date = v.req_date(body, "window_from_date")
    through_date = v.req_date(body, "window_through_date")
    if as_date(through_date) < as_date(from_date):
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_through_date must not precede window_from_date")

    lease = resolve(store.leases, lease_id, "ERR_LEASE_NOT_FOUND")
    center = engine.center_of_lease(lease)
    if center["compliance_posture"] == "FROZEN":
        raise ApiError("ERR_CENTER_EXECUTION_FROZEN")

    # rung 18 - closed-closed windows may not share even a single day
    new_from, new_through = as_date(from_date), as_date(through_date)
    for other in engine.restrictions_of_lease(lease["id"]):
        if other["status"] != "ACTIVE":
            continue
        other_from = as_date(other["window_from_date"])
        other_through = as_date(other["window_through_date"])
        if new_from <= other_through and other_from <= new_through:
            raise ApiError("ERR_RADIUS_WINDOW_OVERLAP")

    restriction = base(engine.stamp())
    restriction.update({
        "lease_id": lease["id"],
        "radius_miles": radius_miles,
        "measured_from": measured_from,
        "recapture_basis": recapture_basis,
        "recapture_pct": q2(recapture_pct),
        "protected_baseline_cents": baseline,
        "window_from_date": from_date,
        "window_through_date": through_date,
        "status": "ACTIVE",
    })
    store.restrictions[restriction["id"]] = restriction
    return created(strip(restriction))


@bp.get("/radius-restrictions/<restriction_id>")
def read_restriction(restriction_id):
    authorize(SINGLE_READ_ROLES)
    return ok(strip(resolve(store.restrictions, restriction_id,
                            "ERR_RESTRICTION_NOT_FOUND")))


@bp.get("/radius-restrictions")
def list_restrictions():
    authorize(LIST_READ_ROLES)
    limit, offset = v.pagination()
    records = engine._ordered(list(store.restrictions.values()))
    records = apply_filters(records, [
        ("lease_id", v.filter_value("lease_id")),
        ("status", v.filter_value("status")),
        ("recapture_basis", v.filter_value("recapture_basis")),
    ])
    page, total = paginate(records, limit, offset)
    return listing([strip(r) for r in page], limit, offset, total)
