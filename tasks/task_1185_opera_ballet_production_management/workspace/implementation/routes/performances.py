"""Performance routes (PRD 3.8) — parallel state dimensions, readiness gates,
cancel cascade."""

from flask import Blueprint, request

from db import store
from errors import (ERR_INVALID_STATE, ERR_PERF_NOT_ENDED,
                    ERR_PROD_NOT_REPERTORY, ERR_READINESS_BLOCKED,
                    ERR_TIME_RANGE, ERR_VALIDATION, ApiError, conflict)
from middleware import require_roles
from response import ok_list, ok_object
from routes.common import get_or_404, list_response
from services import compute_current_price, recompute_season_revenue
from util import (json_body, new_record, pagination_params, parse_dt, req_str,
                  to_public, touch)

bp = Blueprint("performances", __name__)

SECTIONS = ("STALLS", "BALCONY", "BOX", "GALLERY")
REPERTORY_PHASES = ("REHEARSAL", "IN_REPERTORY")


def _validate_sections(raw):
    if not isinstance(raw, list) or not raw:
        raise ApiError(ERR_VALIDATION, 400,
                       "Field 'sections' must be a non-empty array")
    seen = set()
    parsed = []
    for i, el in enumerate(raw):
        if not isinstance(el, dict):
            raise ApiError(ERR_VALIDATION, 400, f"sections[{i}] must be an object")
        section = el.get("section")
        if not isinstance(section, str) or section not in SECTIONS:
            raise ApiError(ERR_VALIDATION, 400,
                           f"sections[{i}].section must be one of {list(SECTIONS)}")
        if section in seen:
            raise ApiError(ERR_VALIDATION, 400,
                           f"Duplicate section '{section}' in one request")
        seen.add(section)
        total_seats = el.get("total_seats")
        if not isinstance(total_seats, int) or isinstance(total_seats, bool) \
                or total_seats <= 0:
            raise ApiError(ERR_VALIDATION, 400,
                           f"sections[{i}].total_seats must be a positive integer")
        base_price = el.get("base_price_cents")
        if not isinstance(base_price, int) or isinstance(base_price, bool) \
                or base_price < 0:
            raise ApiError(ERR_VALIDATION, 400,
                           f"sections[{i}].base_price_cents must be a "
                           "non-negative integer")
        parsed.append((section, total_seats, base_price))
    return parsed


@bp.post("/opera/performances")
def create_performance():
    require_roles("BoxOfficeManager")
    body = json_body()
    production_id = req_str(body, "production_id")
    starts_at = parse_dt(body.get("starts_at"), "starts_at")
    ends_at = parse_dt(body.get("ends_at"), "ends_at")
    sections = _validate_sections(body.get("sections"))
    if ends_at <= starts_at:
        raise ApiError(ERR_TIME_RANGE, 400, "ends_at must be strictly after starts_at")
    prod = get_or_404(store.productions, production_id, "Production")
    if prod["status"] not in REPERTORY_PHASES:
        raise conflict(ERR_PROD_NOT_REPERTORY,
                       "Performances require the production in REHEARSAL or "
                       "IN_REPERTORY")
    perf = new_record(
        production_id=prod["id"],
        starts_at=starts_at,
        ends_at=ends_at,
        lifecycle_status="SCHEDULED",
        sales_status="NOT_ON_SALE",
        readiness_status="AWAITING_TECH",
        realized_revenue_cents=0,
    )
    store.performances[perf["id"]] = perf
    for section, total_seats, base_price in sections:
        inv = new_record(
            performance_id=perf["id"],
            section=section,
            total_seats=total_seats,
            seats_held=0,
            seats_sold=0,
            base_price_cents=base_price,
            current_price_cents=0,
        )
        inv["current_price_cents"] = compute_current_price(inv)  # sold_ratio 0
        store.seat_inventories[inv["id"]] = inv
    return ok_object(to_public(perf), 201)


@bp.get("/opera/performances")
def list_performances():
    require_roles("Any")
    return list_response(
        store.performances.values(),
        [("production_id", "production_id"),
         ("lifecycle_status", "lifecycle_status")],
    )


@bp.get("/opera/performances/<pid>")
def get_performance(pid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.performances, pid, "Performance")))


@bp.get("/opera/performances/<pid>/seat-inventories")
def list_performance_inventories(pid):
    require_roles("Any")
    perf = get_or_404(store.performances, pid, "Performance")
    items = [i for i in store.seat_inventories.values()
             if i["performance_id"] == perf["id"]]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([to_public(i) for i in page], limit, offset, total)


# --- sales dimension ---------------------------------------------------------

@bp.post("/opera/performances/<pid>/open-sales")
def open_sales(pid):
    require_roles("BoxOfficeManager")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["lifecycle_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE,
                       "Opening sales requires a SCHEDULED performance")
    if perf["sales_status"] != "NOT_ON_SALE":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot open sales from {perf['sales_status']}")
    perf["sales_status"] = "ON_SALE"
    touch(perf)
    return ok_object(to_public(perf))


@bp.post("/opera/performances/<pid>/suspend-sales")
def suspend_sales(pid):
    require_roles("BoxOfficeManager")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["sales_status"] != "ON_SALE":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot suspend sales from {perf['sales_status']}")
    perf["sales_status"] = "NOT_ON_SALE"
    touch(perf)
    return ok_object(to_public(perf))


@bp.post("/opera/performances/<pid>/close-sales")
def close_sales(pid):
    require_roles("BoxOfficeManager")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["sales_status"] != "ON_SALE":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot close sales from {perf['sales_status']}")
    perf["sales_status"] = "SALES_CLOSED"
    touch(perf)
    return ok_object(to_public(perf))


# --- readiness dimension -----------------------------------------------------

@bp.post("/opera/performances/<pid>/tech-ready")
def tech_ready(pid):
    require_roles("TechnicalDirector")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["lifecycle_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE,
                       "Tech readiness requires a SCHEDULED performance")
    if perf["readiness_status"] != "AWAITING_TECH":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot mark tech-ready from {perf['readiness_status']}")
    prod = store.productions[perf["production_id"]]
    tech_done = any(
        s["production_id"] == prod["id"] and s["slot_type"] == "TECH"
        and s["status"] == "DONE" and s["ends_at"] <= perf["starts_at"]
        for s in store.stage_slots.values())
    surtitle_live = any(
        t["production_id"] == prod["id"]
        and t["language"] == prod["default_surtitle_language"]
        and t["status"] == "LIVE"
        for t in store.surtitle_tracks.values())
    if not tech_done or not surtitle_live or prod["status"] not in REPERTORY_PHASES:
        raise conflict(ERR_READINESS_BLOCKED,
                       "Readiness gate: DONE tech slot before curtain, LIVE "
                       "default-language surtitle track, and production in "
                       "REHEARSAL or IN_REPERTORY are all required")
    perf["readiness_status"] = "TECH_READY"
    touch(perf)
    return ok_object(to_public(perf))


@bp.post("/opera/performances/<pid>/clear")
def clear_for_audience(pid):
    require_roles("TechnicalDirector")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["readiness_status"] != "TECH_READY":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot clear from {perf['readiness_status']}")
    perf["readiness_status"] = "CLEARED_FOR_AUDIENCE"
    touch(perf)
    return ok_object(to_public(perf))


# --- lifecycle dimension -----------------------------------------------------

@bp.post("/opera/performances/<pid>/complete")
def complete_performance(pid):
    require_roles("BoxOfficeManager")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["lifecycle_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot complete a {perf['lifecycle_status']} performance")
    if not (store.clock > perf["ends_at"]):
        raise conflict(ERR_PERF_NOT_ENDED,
                       "The logical clock must be strictly past ends_at")
    if perf["readiness_status"] != "CLEARED_FOR_AUDIENCE":
        raise conflict(ERR_READINESS_BLOCKED,
                       "Completion requires CLEARED_FOR_AUDIENCE readiness")
    perf["lifecycle_status"] = "COMPLETED"
    touch(perf)
    return ok_object(to_public(perf))


@bp.post("/opera/performances/<pid>/cancel")
def cancel_performance(pid):
    require_roles("ProductionManager")
    perf = get_or_404(store.performances, pid, "Performance")
    if perf["lifecycle_status"] != "SCHEDULED":
        raise conflict(ERR_INVALID_STATE,
                       f"Cannot cancel a {perf['lifecycle_status']} performance")
    perf["lifecycle_status"] = "CANCELLED"
    perf["realized_revenue_cents"] = 0
    touch(perf)
    # Cascade link 1: zero every seat inventory; price recomputed at ratio 0.
    for inv in store.seat_inventories.values():
        if inv["performance_id"] != perf["id"]:
            continue
        inv["seats_held"] = 0
        inv["seats_sold"] = 0
        inv["current_price_cents"] = compute_current_price(inv)
        touch(inv)
    # Cascade links 2+3: season revenue recompute propagates to RATIFIED
    # NET_REVENUE_SHARE accruals.
    prod = store.productions[perf["production_id"]]
    recompute_season_revenue(prod)
    return ok_object(to_public(perf))
