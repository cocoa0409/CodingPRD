"""Lease endpoints (§3.2): create/get/list, activate (ladder guard), vacate."""
from flask import Blueprint, request

from errors import raise_error, ERR_INVALID_STATE, ERR_TEMPORAL_ORDER, ERR_LADDER_BREACH
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, public, serialize_lease, compute_ladder,
)
from routes.helpers import resolve_portfolio, resolve_lease, sorted_items, paged
from util import CLOCK, fmt_date_midnight
from validate import get_body, req_str, req_int, opt_int, req_dateish, opt_bool

bp = Blueprint("leases", __name__)


@bp.post("/portfolios/<pid>/leases")
def create_lease(pid):
    authorized(["PlatformAdmin", "AssetManager"])
    resolve_portfolio(pid)
    body = get_body()
    premises_label = req_str(body, "premises_label")
    rsf = req_int(body, "rentable_square_feet", positive=True)
    base_rent = req_int(body, "base_rent_cents_per_rsf_year", positive=True)
    commencement = req_dateish(body, "commencement_date")
    expiration = req_dateish(body, "expiration_date")
    t1_pct = req_int(body, "holdover_tier1_pct", positive=True)
    t2_pct = req_int(body, "holdover_tier2_pct", positive=True)
    t1_days = opt_int(body, "holdover_tier1_days", 90, positive=True)
    # priority 10: expiration strictly after commencement
    if expiration <= commencement:
        raise_error(ERR_TEMPORAL_ORDER, "expiration_date must be strictly after commencement_date")
    lease = new_record("leases", {
        "portfolio_id": pid,
        "premises_label": premises_label,
        "rentable_square_feet": rsf,
        "base_rent_cents_per_rsf_year": base_rent,
        "commencement_date": fmt_date_midnight(commencement),
        "expiration_date": fmt_date_midnight(expiration),
        "holdover_tier1_pct": t1_pct,
        "holdover_tier2_pct": t2_pct,
        "holdover_tier1_days": t1_days,
        "status": "DRAFT",
        "holdover_entered_at": None,
        "accrued_holdover_rent_cents": 0,
        "active_amendment_id": None,
        "_vacate_requested": False,
    })
    return success_object(serialize_lease(lease), 201)


@bp.get("/portfolios/<pid>/leases")
def list_leases(pid):
    authorized(READ_ROLES)
    resolve_portfolio(pid)
    items = sorted_items("leases", {
        "portfolio_id": pid,
        "status": request.args.get("status"),
    })
    return paged(items, serialize_lease)


@bp.get("/portfolios/<pid>/leases/<lid>")
def get_lease(pid, lid):
    authorized(READ_ROLES)
    _p, lease = resolve_lease(pid, lid)
    return success_object(serialize_lease(lease))


@bp.post("/portfolios/<pid>/leases/<lid>/activate")
def activate_lease(pid, lid):
    authorized(["AssetManager"])
    _p, lease = resolve_lease(pid, lid)
    body = get_body()
    enforce_ladder = opt_bool(body, "enforce_ladder", False)
    # priority 5: state + term preconditions
    if lease["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT lease can be activated")
    clock_date = CLOCK.today()
    from util import parse_date_value as pdv
    if pdv(lease["commencement_date"]) > clock_date:
        raise_error(ERR_INVALID_STATE, "commencement_date is after the current clock date")
    if pdv(lease["expiration_date"]) <= clock_date:
        raise_error(ERR_INVALID_STATE, "expiration_date is not after the current clock date")
    # priority 15: advisory ladder guard, evaluated after state/term checks
    if enforce_ladder:
        lad = compute_ladder(pid, overrides={lid: {"status": "ACTIVE"}})
        if lad["posture"] == "LADDER_STRESSED":
            raise_error(ERR_LADDER_BREACH, "activation would push the portfolio into LADDER_STRESSED")
    lease["status"] = "ACTIVE"
    touch(lease)
    return success_object(serialize_lease(lease))


@bp.post("/portfolios/<pid>/leases/<lid>/vacate")
def vacate_lease(pid, lid):
    authorized(["AssetManager"])
    _p, lease = resolve_lease(pid, lid)
    if lease["status"] not in ("ACTIVE", "EXPIRING"):
        raise_error(ERR_INVALID_STATE, "only an ACTIVE or EXPIRING lease can record a vacatur")
    from util import parse_date_value as pdv
    if CLOCK.today() > pdv(lease["expiration_date"]):
        raise_error(ERR_INVALID_STATE, "vacatur must be recorded at or before expiration_date")
    lease["_vacate_requested"] = True
    return success_object(serialize_lease(lease))
