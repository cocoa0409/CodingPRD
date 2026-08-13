"""PackOrder endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import domain as D
from db import store, mint, touch, now, fmt_dt
from errors import err
from middleware import authorize, ROLES
from response import ok, ok_list
from validate import body, need_str, need_int, need_enum, paginate

bp = Blueprint("packs", __name__)


@bp.post("/plant/pack-orders")
def create_pack_order():
    authorize(["PackagingLead"])
    b = body()
    production_run_id = need_str(b, "production_run_id")
    cases_planned = need_int(b, "cases_planned")
    verification_method = need_enum(b, "verification_method", D.VERIFICATION_METHODS)
    if cases_planned <= 0:
        err("ERR_INVALID_REQUEST", 400, "cases_planned must be greater than zero")
    run = D.get_run(production_run_id)
    pack = mint()
    pack.update({
        "production_run_id": run["id"], "cases_planned": cases_planned,
        "verification_method": verification_method, "cases_packed": None,
        "avg_pack_weight_g": None, "count_accuracy_pct": None,
        "sealed_at": None, "expires_on": None, "pack_status": "OPEN",
    })
    store.pack_orders[pack["id"]] = pack
    return ok(D.pack_json(pack), 201)


@bp.get("/plant/pack-orders/<pid>")
def get_pack(pid):
    authorize(ROLES)
    return ok(D.pack_json(D.get_pack(pid)))


@bp.post("/plant/pack-orders/<pid>/start-packing")
def start_packing(pid):
    authorize(["PackagingLead"])
    pack = D.get_pack(pid)
    if pack["pack_status"] != "OPEN":
        err("ERR_PACK_INVALID_STATE", 409, "Pack order must be OPEN to start packing")
    run = D.get_run(pack["production_run_id"])
    if run["production_status"] != "IN_PROGRESS":
        err("ERR_RUN_INVALID_STATE", 409, "Parent run must be IN_PROGRESS to start packing")
    pack["pack_status"] = "PACKING"
    touch(pack)
    return ok(D.pack_json(pack))


def _num_list(v):
    if not isinstance(v, list) or len(v) < D.SAMPLE_MIN:
        return None
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None
        out.append(Decimal(str(x)))
    return out


def _int_list(v):
    if not isinstance(v, list) or len(v) < D.SAMPLE_MIN:
        return None
    out = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, int):
            return None
        out.append(x)
    return out


@bp.post("/plant/pack-orders/<pid>/weight-check")
def weight_check(pid):
    authorize(["PackagingLead"])
    b = body()
    cases_packed = need_int(b, "cases_packed")
    if cases_packed <= 0:
        err("ERR_INVALID_REQUEST", 400, "cases_packed must be greater than zero")
    pack = D.get_pack(pid)
    if pack["pack_status"] not in ("PACKING", "HOLD"):
        err("ERR_PACK_INVALID_STATE", 409,
            "Pack order must be PACKING or HOLD for a weight check")
    run = D.get_run(pack["production_run_id"])
    product = D.get_product(run["product_id"])

    weights = _num_list(b.get("sample_weights_g"))
    counts = _int_list(b.get("sample_counts"))
    if pack["verification_method"] == "AVERAGE_WEIGHT":
        if weights is None:
            err("ERR_WEIGHT_SAMPLE_INVALID", 422,
                "AVERAGE_WEIGHT requires sample_weights_g with at least 3 numeric entries")
    else:  # COUNT_VERIFY evaluates counts and the average weight floor
        if counts is None or weights is None:
            err("ERR_WEIGHT_SAMPLE_INVALID", 422,
                "COUNT_VERIFY requires sample_counts and sample_weights_g, each with at least 3 entries")

    avg = D.r1(sum(weights) / Decimal(len(weights)))
    declared = product["declared_pack_net_g"]
    tol = product["weight_tolerance_pct"] / Decimal("100")
    lower = declared * (Decimal("1") - tol)
    upper = declared * (Decimal("1") + tol)

    pack["cases_packed"] = cases_packed
    pack["avg_pack_weight_g"] = avg
    if pack["verification_method"] == "AVERAGE_WEIGHT":
        passed = (avg >= lower) and (avg <= upper)
    else:
        exact = sum(1 for c in counts if c == product["count_per_pack"])
        pack["count_accuracy_pct"] = D.r2(
            Decimal(exact) / Decimal(len(counts)) * Decimal("100"))
        passed = (exact == len(counts)) and (avg >= lower)
    pack["pack_status"] = "PASSED" if passed else "HOLD"
    touch(pack)
    return ok(D.pack_json(pack))


@bp.post("/plant/pack-orders/<pid>/seal")
def seal_pack(pid):
    authorize(["PackagingLead"])
    pack = D.get_pack(pid)
    if pack["pack_status"] != "PASSED":
        err("ERR_PACK_INVALID_STATE", 409, "Pack order must be PASSED to seal")
    run = D.get_run(pack["production_run_id"])
    if run["qc_status"] == "ON_HOLD":
        err("ERR_QC_HOLD_ACTIVE", 409, "Parent run is on QC hold")
    product = D.get_product(run["product_id"])
    sealed = now()
    pack["sealed_at"] = fmt_dt(sealed)
    pack["expires_on"] = (sealed.date()
                          + timedelta(days=product["shelf_life_days"])).isoformat()
    pack["pack_status"] = "SEALED"
    touch(pack)
    return ok(D.pack_json(pack))


@bp.post("/plant/pack-orders/<pid>/reject")
def reject_pack(pid):
    authorize(["PackagingLead"])
    pack = D.get_pack(pid)
    if pack["pack_status"] not in ("OPEN", "PACKING", "HOLD"):
        err("ERR_PACK_INVALID_STATE", 409,
            "Only OPEN, PACKING or HOLD pack orders may be rejected")
    pack["pack_status"] = "REJECTED"
    touch(pack)
    return ok(D.pack_json(pack))


@bp.get("/plant/pack-orders/<pid>/stops")
def pack_stops(pid):
    authorize(ROLES)
    D.get_pack(pid)
    items = [s for s in store.stops.values() if s["pack_order_id"] == pid]
    page, limit, offset, total = paginate(items, D.stop_json)
    return ok_list(page, limit, offset, total)
