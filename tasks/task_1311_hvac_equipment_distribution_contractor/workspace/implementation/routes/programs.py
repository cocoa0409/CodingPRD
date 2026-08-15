"""Pre-buy programs and allocation pools."""
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import ApiError, ERR_WINDOW_OVERLAP, ERR_POOL_CAPACITY_EXCEEDED, \
    invalid_state
from middleware import authenticate, authorize
from response import success
from serializers import prebuy_program as ser_program, allocation_pool as ser_pool
from services import core
from utils import StructErrors, check_unknown_fields, get_str, get_int, \
    get_decimal, get_datetime, touch
from routes.common import body, get_path, new_common, list_response

bp = Blueprint("programs", __name__)
READ_ROLES = {"DistributorAdmin", "ContractorUser"}


@bp.post("/prebuy-programs")
def create_program():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"name", "family_code", "window_start",
                                "window_end", "ship_by_date", "deposit_pct",
                                "discount_pct"}, struct)
    name = get_str(data, "name", struct)
    family_code = get_str(data, "family_code", struct)
    window_start = get_datetime(data, "window_start", struct)
    window_end = get_datetime(data, "window_end", struct)
    ship_by = get_datetime(data, "ship_by_date", struct)
    deposit_pct = get_decimal(data, "deposit_pct", struct)
    discount_pct = get_decimal(data, "discount_pct", struct)

    if deposit_pct is not None and not (Decimal("0") < deposit_pct <= Decimal("0.5")):
        struct.add("deposit_pct must be > 0 and <= 0.5")
    if discount_pct is not None and not (Decimal("0") < discount_pct <= Decimal("0.20")):
        struct.add("discount_pct must be > 0 and <= 0.20")

    # Window overlap (priority 10): half-open [start, end); touching allowed.
    if window_start is not None and window_end is not None and family_code:
        for p in db.prebuy_programs.values():
            if p["family_code"] != family_code:
                continue
            if window_start < p["window_end"] and p["window_start"] < window_end:
                raise ApiError(ERR_WINDOW_OVERLAP, 422,
                               "Window overlaps an existing program for family %s"
                               % family_code)
    struct.raise_if_bad()

    p = new_common()
    p.update({
        "name": name,
        "family_code": family_code,
        "window_start": window_start,
        "window_end": window_end,
        "ship_by_date": ship_by,
        "deposit_pct": deposit_pct,
        "discount_pct": discount_pct,
        "status": "SCHEDULED",
        "_manually_closed": False,
    })
    p["status"] = core.program_effective_status(p)
    db.prebuy_programs[p["id"]] = p
    return success(ser_program(p), 201)


@bp.get("/prebuy-programs/<pid>")
def get_program(pid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    p = get_path(db.prebuy_programs, pid)
    core.recompute_program_status(p)
    return success(ser_program(p))


@bp.get("/prebuy-programs")
def list_programs():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    for p in db.prebuy_programs.values():
        core.recompute_program_status(p)
    filters = {"family_code": request.args.get("family_code"),
               "status": request.args.get("status")}
    return list_response(db.prebuy_programs.values(), ser_program, filters)


@bp.post("/prebuy-programs/<pid>/close")
def close_program(pid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    p = get_path(db.prebuy_programs, pid)
    core.recompute_program_status(p)
    if p.get("_manually_closed") or p["status"] not in ("SCHEDULED", "OPEN"):
        raise invalid_state("Program cannot be closed from state %s" % p["status"])
    p["_manually_closed"] = True
    p["status"] = core.program_effective_status(p)
    touch(p)
    return success(ser_program(p))


@bp.post("/allocation-pools")
def create_pool():
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    data = body()
    struct = StructErrors()
    check_unknown_fields(data, {"family_code", "season_start", "season_end",
                                "total_qty"}, struct)
    family_code = get_str(data, "family_code", struct)
    season_start = get_datetime(data, "season_start", struct)
    season_end = get_datetime(data, "season_end", struct)
    total_qty = get_int(data, "total_qty", struct, minimum=0)

    # Aggregate capacity (priority 12): at every instant, the sum of total_qty
    # over pools covering it must not exceed 2x the largest single pool.
    if family_code and season_start is not None and season_end is not None \
            and total_qty is not None:
        pools = [p for p in db.allocation_pools.values()
                 if p["family_code"] == family_code]
        all_seasons = [(p["season_start"], p["season_end"], p["total_qty"])
                       for p in pools] + [(season_start, season_end, total_qty)]
        largest = max(q for _, _, q in all_seasons)
        instants = sorted({s for s, _, _ in all_seasons})
        for t in instants:
            covering = sum(q for s, e, q in all_seasons if s <= t < e)
            if covering > 2 * largest:
                raise ApiError(ERR_POOL_CAPACITY_EXCEEDED, 422,
                               "Aggregate pool capacity for family %s exceeds "
                               "2x the largest single pool" % family_code)
    struct.raise_if_bad()

    p = new_common()
    p.update({
        "family_code": family_code,
        "season_start": season_start,
        "season_end": season_end,
        "total_qty": total_qty,
        "reserved_qty": 0,
        "committed_qty": 0,
        "status": "OPEN",
        "_manually_closed": False,
    })
    p["status"] = core.pool_effective_status(p)
    db.allocation_pools[p["id"]] = p

    # Re-reservation sweep: newly available capacity re-evaluates open orders.
    core.rereservation_sweep()
    return success(ser_pool(p), 201)


@bp.get("/allocation-pools/<pid>")
def get_pool(pid):
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    p = get_path(db.allocation_pools, pid)
    core.recompute_pool_status(p)
    return success(ser_pool(p))


@bp.get("/allocation-pools")
def list_pools():
    user_id, role = authenticate()
    authorize(READ_ROLES, role)
    for p in list(db.allocation_pools.values()):
        core.recompute_pool_status(p)
    filters = {"family_code": request.args.get("family_code"),
               "status": request.args.get("status")}
    return list_response(db.allocation_pools.values(), ser_pool, filters)


@bp.post("/allocation-pools/<pid>/close")
def close_pool(pid):
    user_id, role = authenticate()
    authorize({"DistributorAdmin"}, role)
    p = get_path(db.allocation_pools, pid)
    core.recompute_pool_status(p)
    if p["status"] == "CLOSED":
        raise invalid_state("Pool is already CLOSED")
    p["_manually_closed"] = True
    p["status"] = "CLOSED"
    touch(p)
    # Backordered orders shorted by this pool revert to SUBMITTED with their
    # partial reservations released.
    core.revert_orders_shorted_by_pool(p["id"])
    return success(ser_pool(p))
