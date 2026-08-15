from flask import Blueprint, request

from auth import require, ALL_ROLES
from domain import (cases_unrouted, dump_window, dump_case, get_product, get_run,
                    get_window, get_case, quota_remaining, window_exhaustion_check,
                    window_reactivation_check)
from errors import ApiError
from store import STORE, new_entity, touch, sort_key
from util import body, ok, paginate, req_int, opt_int, parse_date

bp = Blueprint("promos", __name__)


@bp.post("/snack-mfg/promo-windows")
def create_window():
    require(["PlantManager"])
    data = body()
    # tier 3: body FK
    product_id = data.get("product_id")
    product = get_product(STORE, product_id) if isinstance(product_id, str) else None
    if product is None:
        if not isinstance(product_id, str) or product_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: product_id")
        raise ApiError("ERR_PRODUCT_NOT_FOUND", 404, "product not found")
    # tier 5: shape
    quota_total = req_int(data, "quota_total_cases", ge=1)
    try:
        start_d = parse_date(data.get("window_start_date"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "window_start_date must be YYYY-MM-DD")
    try:
        end_d = parse_date(data.get("window_end_date"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "window_end_date must be YYYY-MM-DD")
    if end_d < start_d:
        raise ApiError("ERR_VALIDATION", 400, "window_end_date must be >= window_start_date")
    case_size = opt_int(data, "case_size_bags", ge=1, default=12)
    w = new_entity(STORE)
    w.update({
        "product_id": product["id"], "quota_total_cases": quota_total,
        "window_start_date": start_d.isoformat(), "window_end_date": end_d.isoformat(),
        "case_size_bags": case_size, "status": "DRAFT",
        "quota_consumed_cases": 0, "quota_released_cases": 0,
    })
    STORE.windows[w["id"]] = w
    return ok(STORE, dump_window(w), status=201)


@bp.get("/snack-mfg/promo-windows/<wid>")
def get_window_ep(wid):
    require(ALL_ROLES)
    w = get_window(STORE, wid)
    return ok(STORE, dump_window(w))


@bp.get("/snack-mfg/promo-windows")
def list_windows():
    require(ALL_ROLES)
    items = list(STORE.windows.values())
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    if product_id is not None:
        items = [w for w in items if w["product_id"] == product_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_window(w) for w in items])
    return ok(STORE, page, response_type="array", pagination=meta)


@bp.post("/snack-mfg/promo-windows/<wid>/activate")
def activate_window(wid):
    require(["PlantManager"])
    w = get_window(STORE, wid)
    if w["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "window is CLOSED")
    if w["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "window is not DRAFT")
    for other in STORE.windows.values():
        if (other["id"] != w["id"] and other["product_id"] == w["product_id"]
                and other["status"] == "ACTIVE"):
            # closed-interval overlap: sharing a boundary date IS an overlap
            if (w["window_start_date"] <= other["window_end_date"]
                    and other["window_start_date"] <= w["window_end_date"]):
                raise ApiError("ERR_PROMO_WINDOW_OVERLAP", 409,
                               "overlaps an ACTIVE window for the same product")
    w["status"] = "ACTIVE"
    touch(STORE, w)
    return ok(STORE, dump_window(w))


@bp.post("/snack-mfg/promo-windows/<wid>/close")
def close_window(wid):
    require(["PlantManager"])
    w = get_window(STORE, wid)
    if w["status"] == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "window is CLOSED")
    if w["status"] not in ("ACTIVE", "EXHAUSTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "window is not ACTIVE or EXHAUSTED")
    w["status"] = "CLOSED"
    for dc in STORE.cases.values():
        if dc["promo_window_id"] == w["id"] and dc["status"] == "PLANNED":
            dc["status"] = "CANCELLED"
            dc["cancelled_reason"] = "MANUAL"
            touch(STORE, dc)
    touch(STORE, w)
    return ok(STORE, dump_window(w))


# ---------------------------------------------------------------------------
# Display cases
# ---------------------------------------------------------------------------

@bp.post("/snack-mfg/display-cases")
def create_case():
    require(["PlantManager"])
    data = body()
    # tier 3: body FKs in canonical order (run_id before promo_window_id)
    run_id = data.get("run_id")
    window_id = data.get("promo_window_id")
    run = get_run(STORE, run_id) if isinstance(run_id, str) else None
    window = get_window(STORE, window_id) if isinstance(window_id, str) else None
    if run is None:
        if not isinstance(run_id, str) or run_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: run_id")
        raise ApiError("ERR_RUN_NOT_FOUND", 404, "run not found")
    if window is None:
        if not isinstance(window_id, str) or window_id == "":
            raise ApiError("ERR_VALIDATION", 400, "missing or invalid field: promo_window_id")
        raise ApiError("ERR_PROMO_WINDOW_NOT_FOUND", 404, "promo window not found")
    # tier 5: shape
    cases_planned = req_int(data, "cases_planned", ge=1)
    # tier 6: cross-entity gating states
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "promo window is not ACTIVE")
    if run["execution_status"] not in ("RUNNING", "COMPLETED"):
        raise ApiError("ERR_INVALID_STATE", 409, "run is not RUNNING or COMPLETED")
    # tier 9: reservation availability
    if cases_planned > cases_unrouted(STORE, run):
        raise ApiError("ERR_CASES_UNAVAILABLE", 422, "insufficient cases_unrouted")
    dc = new_entity(STORE)
    dc.update({
        "promo_window_id": window["id"], "run_id": run["id"],
        "cases_planned": cases_planned, "status": "PLANNED", "cancelled_reason": None,
    })
    STORE.cases[dc["id"]] = dc
    return ok(STORE, dump_case(dc), status=201)


@bp.get("/snack-mfg/display-cases/<cid>")
def get_case_ep(cid):
    require(ALL_ROLES)
    dc = get_case(STORE, cid)
    return ok(STORE, dump_case(dc))


@bp.get("/snack-mfg/display-cases")
def list_cases():
    require(ALL_ROLES)
    items = list(STORE.cases.values())
    window_id = request.args.get("promo_window_id")
    run_id = request.args.get("run_id")
    status = request.args.get("status")
    if window_id is not None:
        items = [d for d in items if d["promo_window_id"] == window_id]
    if run_id is not None:
        items = [d for d in items if d["run_id"] == run_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=sort_key)
    page, meta = paginate([dump_case(d) for d in items])
    return ok(STORE, page, response_type="array", pagination=meta)


@bp.post("/snack-mfg/display-cases/<cid>/build")
def build_case(cid):
    require(["LineOperator"])
    dc = get_case(STORE, cid)
    if dc["status"] in ("BUILT", "CANCELLED"):
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "display case is terminal")
    if dc["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", 409, "display case is not PLANNED")
    window = get_window(STORE, dc["promo_window_id"])
    if window["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "promo window is not ACTIVE")
    today = STORE.clock.date()
    if not (window["window_start_date"] <= today.isoformat() <= window["window_end_date"]):
        raise ApiError("ERR_OUTSIDE_PROMO_WINDOW", 422, "logical clock date outside the window")
    if dc["cases_planned"] > quota_remaining(window):
        raise ApiError("ERR_PROMO_QUOTA_EXHAUSTED", 422, "build exceeds quota_remaining_cases")
    dc["status"] = "BUILT"
    touch(STORE, dc)
    window["quota_consumed_cases"] += dc["cases_planned"]
    touch(STORE, window)
    window_exhaustion_check(STORE, window)
    return ok(STORE, dump_case(dc))


@bp.post("/snack-mfg/display-cases/<cid>/cancel")
def cancel_case(cid):
    require(["PlantManager"])
    dc = get_case(STORE, cid)
    if dc["status"] == "CANCELLED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "display case already CANCELLED")
    if dc["status"] not in ("PLANNED", "BUILT"):
        raise ApiError("ERR_INVALID_STATE", 409, "display case cannot be cancelled")
    was_built = dc["status"] == "BUILT"
    dc["status"] = "CANCELLED"
    dc["cancelled_reason"] = "MANUAL"
    touch(STORE, dc)
    if was_built:
        window = get_window(STORE, dc["promo_window_id"])
        window["quota_released_cases"] += dc["cases_planned"]
        touch(STORE, window)
        window_reactivation_check(STORE, window)
    return ok(STORE, dump_case(dc))
