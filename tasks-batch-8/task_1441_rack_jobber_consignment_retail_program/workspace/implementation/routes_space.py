"""SpaceAllocation, PriceDirective, Promotion, and InventoryBalance endpoints."""
from flask import Blueprint, request

import response
from db import store
from errors import err
from middleware import extract_identity, require_role, ALL_ROLES
from common import (
    new_entity, touch, public, get_json, get_or_404, fk_exists,
    require_str, require_enum, require_int, require_num,
    parse_date, parse_datetime, require_from_state,
    parse_pagination, list_page,
)
from services import CATEGORIES, _effective_directive

bp = Blueprint("space", __name__)

ALLOC_TERMINAL = {"CLOSED"}
PROMO_TERMINAL = {"ENDED", "CANCELLED"}


def _windows_intersect(s1, e1, s2, e2):
    """Half-open interval intersection: touching endpoints do NOT intersect."""
    return s1 < e2 and s2 < e1


# =============================================================================
# Space allocations (PRD Section 3.4)
# =============================================================================

@bp.route("/space-allocations", methods=["POST"])
def create_allocation():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "store_agreement_id", store.agreements)
    # Stage 5: shape.
    agreement_id = require_str(body, "store_agreement_id")
    facings = require_int(body, "facings")
    start = parse_date(body.get("window_start_date"), "window_start_date")
    end = parse_date(body.get("window_end_date"), "window_end_date")
    # Stage 6: enums.
    category = require_enum(body, "category", CATEGORIES)
    # Stage 7: ranges.
    if facings < 1:
        raise err("ERR_RANGE_INVALID", "facings must be >= 1")
    agreement = store.agreements[agreement_id]
    # Stage 13: half-open window order — start must precede end.
    if not start < end:
        raise err("ERR_WINDOW_INVALID", "window_start_date must precede window_end_date")
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    store_id = agreement["store_id"]
    candidates = [
        a for a in store.space_allocations.values()
        if a["store_id"] == store_id
        and a["category"] == category
        and a["status"] in ("PLANNED", "ACTIVE")
        and _windows_intersect(start_s, end_s, a["window_start_date"], a["window_end_date"])
    ]
    # Stage 17: same store + category + same program overlap.
    for a in candidates:
        other = store.agreements[a["store_agreement_id"]]
        if other["program_id"] == agreement["program_id"]:
            raise err("ERR_SPACE_WINDOW_OVERLAP",
                      "overlapping allocation for the same store, category and program")
    # Stage 20: category exclusivity across programs.
    for a in candidates:
        other = store.agreements[a["store_agreement_id"]]
        if other["program_id"] != agreement["program_id"]:
            raise err("ERR_CATEGORY_EXCLUSIVE_CONFLICT",
                      "category is exclusively allocated to another program")
    # Stage 21: facing capacity across the whole store; equality is allowed.
    store_row = store.stores[store_id]
    committed = sum(
        a["facings"]
        for a in store.space_allocations.values()
        if a["store_id"] == store_id
        and a["status"] in ("PLANNED", "ACTIVE")
        and _windows_intersect(start_s, end_s, a["window_start_date"], a["window_end_date"])
    ) + facings
    if committed > store_row["total_facings"]:
        raise err("ERR_SPACE_CAPACITY_EXCEEDED", "store facing capacity exceeded")
    today = store.today_str()
    status = "ACTIVE" if start_s <= today < end_s else "PLANNED"
    allocation = new_entity({
        "store_agreement_id": agreement_id,
        "store_id": store_id,  # denormalized at creation
        "category": category,
        "facings": facings,
        "window_start_date": start_s,
        "window_end_date": end_s,
        "status": status,
    })
    store.space_allocations[allocation["id"]] = allocation
    return response.success(public(allocation), http_status=201)


@bp.route("/space-allocations", methods=["GET"])
def list_allocations():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.space_allocations.values()
    for param in ("store_agreement_id", "category", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [a for a in rows if a[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/space-allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    allocation = get_or_404(store.space_allocations, aid, "space allocation")
    return response.success(public(allocation))


@bp.route("/space-allocations/<aid>/close", methods=["POST"])
def close_allocation(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    allocation = get_or_404(store.space_allocations, aid, "space allocation")
    get_json(request)
    require_from_state(allocation, ["PLANNED", "ACTIVE"], ALLOC_TERMINAL, "space allocation", target="CLOSED")
    allocation["status"] = "CLOSED"
    touch(allocation)
    return response.success(public(allocation))


# =============================================================================
# Price directives (PRD Section 3.2) — OCC-guarded create-with-supersede
# =============================================================================

@bp.route("/price-directives", methods=["POST"])
def create_directive():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    # Stage 4: body FK references.
    fk_exists(body, "store_agreement_id", store.agreements)
    fk_exists(body, "product_id", store.products)
    # Stage 5: shape (the OCC field is non-optional on this endpoint).
    agreement_id = require_str(body, "store_agreement_id")
    product_id = require_str(body, "product_id")
    price_cents = require_int(body, "price_cents")
    effective_from = fmt_dt_checked(body, "effective_from")
    expected = require_int(body, "expected_store_agreement_version")
    agreement = store.agreements[agreement_id]
    product = store.products[product_id]
    # Stage 7: prices must be at least 1 cent.
    if price_cents < 1:
        raise err("ERR_RANGE_INVALID", "price_cents must be >= 1")
    # Stage 11: optimistic concurrency on the agreement version.
    if expected != agreement["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_store_agreement_version does not match current version")
    # Domain ladder (PRD Section 2.8): floor (22) -> membership (23) ->
    # discontinued (24) -> agreement active (27).
    if price_cents < product["min_retail_cents"]:
        raise err("ERR_PRICE_BELOW_FLOOR", "price_cents is below the retail floor")
    if product["program_id"] != agreement["program_id"]:
        raise err("ERR_PRODUCT_NOT_IN_PROGRAM", "product is not in the agreement's program")
    if product["status"] != "ACTIVE":
        raise err("ERR_PRODUCT_DISCONTINUED", "product is discontinued")
    if agreement["status"] != "ACTIVE":
        raise err("ERR_AGREEMENT_NOT_ACTIVE", "agreement is not ACTIVE")
    now = store.now_iso()
    born_effective = effective_from <= now
    # Create-with-supersede: only an EFFECTIVE birth displaces the incumbent.
    if born_effective:
        incumbent = _effective_directive(agreement_id, product_id)
        if incumbent is not None:
            incumbent["status"] = "SUPERSEDED"
            incumbent["superseded_at"] = now
            touch(incumbent)
    directive = new_entity({
        "store_agreement_id": agreement_id,
        "product_id": product_id,
        "price_cents": price_cents,
        "effective_from": effective_from,
        "status": "EFFECTIVE" if born_effective else "SCHEDULED",
        "superseded_at": None,
    })
    store.price_directives[directive["id"]] = directive
    # Either form of creation advances the agreement's version by one.
    touch(agreement)
    return response.success(public(directive), http_status=201)


def fmt_dt_checked(body, field):
    from db import fmt_dt
    return fmt_dt(parse_datetime(body.get(field), field))


@bp.route("/price-directives", methods=["GET"])
def list_directives():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.price_directives.values()
    for param in ("store_agreement_id", "product_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [d for d in rows if d[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/price-directives/<did>", methods=["GET"])
def get_directive(did):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    directive = get_or_404(store.price_directives, did, "price directive")
    return response.success(public(directive))


# =============================================================================
# Promotions (PRD Section 3.3)
# =============================================================================

@bp.route("/promotions", methods=["POST"])
def create_promotion():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "program_id", store.programs)
    fk_exists(body, "product_id", store.products)
    # Stage 5: shape.
    program_id = require_str(body, "program_id")
    product_id = require_str(body, "product_id")
    name = require_str(body, "name")
    depth = require_num(body, "depth_pct")
    funding = require_num(body, "jobber_funding_pct")
    start = parse_date(body.get("start_date"), "start_date")
    end = parse_date(body.get("end_date"), "end_date")
    # Stage 7: promotion depth in (0, 0.50]; funding share within [0, 1].
    if not (0 < depth <= 0.50):
        raise err("ERR_RANGE_INVALID", "depth_pct must be in (0, 0.50]")
    if not (0 <= funding <= 1):
        raise err("ERR_RANGE_INVALID", "jobber_funding_pct must be within [0, 1]")
    # Stage 13: promotion windows are closed intervals — start <= end.
    if start > end:
        raise err("ERR_WINDOW_INVALID", "start_date must not follow end_date")
    start_s, end_s = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    # Stage 18: minimum full-day gap against every non-CANCELLED promotion of
    # the same (program, product); the separation must be strictly greater
    # than promo_min_gap_days.
    program = store.programs[program_id]
    gap = program["promo_min_gap_days"]
    for p in store.promotions.values():
        if (p["program_id"] == program_id and p["product_id"] == product_id
                and p["status"] != "CANCELLED"):
            existing_start = parse_date(p["start_date"], "start_date")
            existing_end = parse_date(p["end_date"], "end_date")
            after = (start - existing_end).days > gap
            before = (existing_start - end).days > gap
            if not (after or before):
                raise err("ERR_PROMO_GAP_VIOLATION",
                          "promotion window violates the minimum gap")
    promo = new_entity({
        "program_id": program_id,
        "product_id": product_id,
        "name": name,
        "depth_pct": depth,
        "jobber_funding_pct": funding,
        "start_date": start_s,
        "end_date": end_s,
        "status": "DRAFT",
    })
    store.promotions[promo["id"]] = promo
    return response.success(public(promo), http_status=201)


@bp.route("/promotions", methods=["GET"])
def list_promotions():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.promotions.values()
    for param in ("program_id", "product_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [p for p in rows if p[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/promotions/<pid>", methods=["GET"])
def get_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    promo = get_or_404(store.promotions, pid, "promotion")
    return response.success(public(promo))


@bp.route("/promotions/<pid>/schedule", methods=["POST"])
def schedule_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    promo = get_or_404(store.promotions, pid, "promotion")
    get_json(request)
    require_from_state(promo, ["DRAFT"], PROMO_TERMINAL, "promotion", target="SCHEDULED")
    # Window order guard (closed interval).
    if promo["start_date"] > promo["end_date"]:
        raise err("ERR_WINDOW_INVALID", "promotion window is inverted")
    # A window already covering the clock date lands directly in ACTIVE.
    today = store.today_str()
    if promo["start_date"] <= today <= promo["end_date"]:
        promo["status"] = "ACTIVE"
    else:
        promo["status"] = "SCHEDULED"
    touch(promo)
    return response.success(public(promo))


@bp.route("/promotions/<pid>/suspend", methods=["POST"])
def suspend_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    promo = get_or_404(store.promotions, pid, "promotion")
    get_json(request)
    require_from_state(promo, ["ACTIVE"], PROMO_TERMINAL, "promotion", target="SUSPENDED")
    promo["status"] = "SUSPENDED"
    touch(promo)
    return response.success(public(promo))


@bp.route("/promotions/<pid>/resume", methods=["POST"])
def resume_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    promo = get_or_404(store.promotions, pid, "promotion")
    get_json(request)
    require_from_state(promo, ["SUSPENDED"], PROMO_TERMINAL, "promotion", target="ACTIVE")
    # Resumption requires the clock date to still lie within the window.
    today = store.today_str()
    if not (promo["start_date"] <= today <= promo["end_date"]):
        raise err("ERR_WINDOW_INVALID", "promotion window does not cover the clock date")
    promo["status"] = "ACTIVE"
    touch(promo)
    return response.success(public(promo))


@bp.route("/promotions/<pid>/cancel", methods=["POST"])
def cancel_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    promo = get_or_404(store.promotions, pid, "promotion")
    get_json(request)
    require_from_state(promo, ["DRAFT", "SCHEDULED", "ACTIVE", "SUSPENDED"], PROMO_TERMINAL, "promotion", target="CANCELLED")
    promo["status"] = "CANCELLED"
    touch(promo)
    return response.success(public(promo))


@bp.route("/promotions/<pid>/end", methods=["POST"])
def end_promotion(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    promo = get_or_404(store.promotions, pid, "promotion")
    get_json(request)
    require_from_state(promo, ["ACTIVE", "SUSPENDED"], PROMO_TERMINAL, "promotion", target="ENDED")
    promo["status"] = "ENDED"
    touch(promo)
    return response.success(public(promo))


# =============================================================================
# Inventory balances (PRD Section 3.6) — read-only, auto-created
# =============================================================================

@bp.route("/inventory-balances", methods=["GET"])
def list_balances():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.inventory_balances.values()
    for param in ("store_agreement_id", "product_id", "stock_posture"):
        val = request.args.get(param)
        if val is not None:
            rows = [b for b in rows if b[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/inventory-balances/<bid>", methods=["GET"])
def get_balance(bid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    balance = get_or_404(store.inventory_balances, bid, "inventory balance")
    return response.success(public(balance))
