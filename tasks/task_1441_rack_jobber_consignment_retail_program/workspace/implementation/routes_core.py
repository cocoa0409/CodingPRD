"""Clock, Program, Store, StoreAgreement, and Product endpoints."""
from flask import Blueprint, request

import response
from db import store, fmt_dt
from errors import err
from middleware import extract_identity, require_role, ALL_ROLES
from common import (
    new_entity, touch, public, get_json, get_or_404, fk_exists,
    require_str, optional_str, require_enum, optional_enum,
    require_int, optional_int, require_num, optional_num,
    require_pct, optional_pct, _check_pct, require_from_state,
    require_store_manager, parse_datetime, parse_pagination, list_page,
)
from services import (
    run_sweep, CADENCES, LIVE_AGREEMENT_STATES,
)

bp = Blueprint("core", __name__)

SETTLEMENT_BLOCKING = {"PROVISIONAL", "FINALIZED", "DISPUTED", "APPROVED"}
SET_BLOCKING = {"PLANNED", "SET_IN_PROGRESS", "SET_COMPLETE", "ACTIVE_SEASON", "TEARDOWN_DUE"}


# =============================================================================
# Logical clock (PRD Section 2.6)
# =============================================================================

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    target = parse_datetime(require_str(body, "to_iso8601"), "to_iso8601")
    store.clock = target
    swept = run_sweep()
    return response.success({
        "current_utc": store.now_iso(),
        "swept_transitions": swept,
    })


# =============================================================================
# Programs (PRD Section 3.1)
# =============================================================================

@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    program = new_entity({
        "name": require_str(body, "name"),
        "promo_min_gap_days": optional_int(body, "promo_min_gap_days", 1),
        "min_payout_cents": optional_int(body, "min_payout_cents", 5000),
        "default_settlement_cadence": optional_enum(
            body, "default_settlement_cadence", CADENCES, "WEEKLY"),
        "status": "ACTIVE",
    })
    store.programs[program["id"]] = program
    return response.success(public(program), http_status=201)


@bp.route("/programs", methods=["GET"])
def list_programs():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.programs.values()
    status = request.args.get("status")
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/programs/<pid>", methods=["GET"])
def get_program(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    program = get_or_404(store.programs, pid, "program")
    return response.success(public(program))


@bp.route("/programs/<pid>/archive", methods=["POST"])
def archive_program(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    program = get_or_404(store.programs, pid, "program")
    require_from_state(program, ["ACTIVE"], ["ARCHIVED"], "program", target="ARCHIVED")
    # Archiving is permitted only when no live agreements remain.
    for a in store.agreements.values():
        if a["program_id"] == pid and a["status"] in LIVE_AGREEMENT_STATES:
            raise err("ERR_INVALID_STATE", "program has live agreements")
    program["status"] = "ARCHIVED"
    touch(program)
    return response.success(public(program))


# =============================================================================
# Stores (PRD Section 3.1)
# =============================================================================

@bp.route("/stores", methods=["POST"])
def create_store():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    name = require_str(body, "name")
    store_code = require_str(body, "store_code")
    total_facings = require_int(body, "total_facings", minimum=1, range_err=True)
    # store_code must be unique across all stores.
    for s in store.stores.values():
        if s["store_code"] == store_code:
            raise err("ERR_INVALID_REQUEST", "store_code already exists")
    row = new_entity({
        "name": name,
        "store_code": store_code,
        "total_facings": total_facings,
        "status": "ACTIVE",
    })
    store.stores[row["id"]] = row
    return response.success(public(row), http_status=201)


@bp.route("/stores", methods=["GET"])
def list_stores():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.stores.values()
    status = request.args.get("status")
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/stores/<sid>", methods=["GET"])
def get_store(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    row = get_or_404(store.stores, sid, "store")
    return response.success(public(row))


@bp.route("/stores/<sid>/close", methods=["POST"])
def close_store(sid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    row = get_or_404(store.stores, sid, "store")
    require_from_state(row, ["ACTIVE"], ["CLOSED"], "store", target="CLOSED")
    # Closing is permitted only when no live agreements remain at the store.
    for a in store.agreements.values():
        if a["store_id"] == sid and a["status"] in LIVE_AGREEMENT_STATES:
            raise err("ERR_INVALID_STATE", "store has live agreements")
    row["status"] = "CLOSED"
    touch(row)
    return response.success(public(row))


# =============================================================================
# Store agreements (PRD Section 3.1)
# =============================================================================

_AGREEMENT_PCT_DEFAULTS = {
    "tier1_uplift_pct": 0.01,
    "tier2_uplift_pct": 0.02,
    "min_margin_pct": 0.15,
    "max_margin_pct": 0.40,
    "free_allowance_pct": 0.01,
    "shrink_suspend_ratio": 0.02,
    "estimated_shrink_rate": 0.0,
    "markdown_jobber_share_pct": 0.5,
    "markdown_cap_pct_of_gross": 0.08,
}
_AGREEMENT_INT_DEFAULTS = {
    "tier1_threshold_cents": 100000,
    "tier2_threshold_cents": 200000,
    "service_frequency_days": 7,
}


@bp.route("/agreements", methods=["POST"])
def create_agreement():
    user_id, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    # Stage 4: body FK references must resolve.
    fk_exists(body, "program_id", store.programs)
    fk_exists(body, "store_id", store.stores)
    # Stage 5: shape — every field present and well-typed.
    program_id = require_str(body, "program_id")
    store_id = require_str(body, "store_id")
    terms = {
        "base_margin_pct": require_num(body, "base_margin_pct"),
        "shrink_retailer_share_pct": require_num(body, "shrink_retailer_share_pct"),
        "restock_value_cap_cents": require_int(body, "restock_value_cap_cents"),
    }
    for field, default in _AGREEMENT_PCT_DEFAULTS.items():
        terms[field] = optional_num(body, field, default)
    for field, default in _AGREEMENT_INT_DEFAULTS.items():
        terms[field] = optional_int(body, field, default)
    # Stage 6: enums.
    shrink_mode = optional_enum(body, "shrink_valuation_mode",
                                ["JOBBER_COST", "BLENDED_RETAIL"], "JOBBER_COST")
    markdown_liability = optional_enum(body, "markdown_liability",
                                       ["JOBBER", "RETAILER", "SHARED"], "SHARED")
    cadence = optional_enum(body, "settlement_cadence", CADENCES, "WEEKLY")
    # Stage 7: numeric ranges — base margin strictly between 0 and 1, the
    # remaining percentage fields within [0, 1] inclusive.
    _check_pct(terms["base_margin_pct"], "base_margin_pct", 0.0, 1.0, True, True)
    for field in ("shrink_retailer_share_pct",) + tuple(_AGREEMENT_PCT_DEFAULTS):
        _check_pct(terms[field], field, 0.0, 1.0, False, False)
    # markdown_jobber_share_pct is forced by the liability mode.
    if markdown_liability == "JOBBER":
        terms["markdown_jobber_share_pct"] = 1.0
    elif markdown_liability == "RETAILER":
        terms["markdown_jobber_share_pct"] = 0.0
    # Stage 19: at most one live agreement per (program, store).
    for a in store.agreements.values():
        if (a["program_id"] == program_id and a["store_id"] == store_id
                and a["status"] in LIVE_AGREEMENT_STATES):
            raise err("ERR_AGREEMENT_EXISTS",
                      "a live agreement already exists for this program and store")
    agreement = new_entity({
        "program_id": program_id,
        "store_id": store_id,
        "shrink_valuation_mode": shrink_mode,
        "markdown_liability": markdown_liability,
        "settlement_cadence": cadence,
        "status": "DRAFT",
        "activated_at": None,
        "created_by_user_id": user_id,
        "cumulative_delivered_units": 0,
        "cumulative_shrink_units": 0,
        "cumulative_shrink_ratio": 0.0,
    })
    agreement.update(terms)
    store.agreements[agreement["id"]] = agreement
    return response.success(public(agreement), http_status=201)


@bp.route("/agreements", methods=["GET"])
def list_agreements():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.agreements.values()
    for param in ("program_id", "store_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [a for a in rows if a[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    agreement = get_or_404(store.agreements, aid, "agreement")
    return response.success(public(agreement))


@bp.route("/agreements/<aid>", methods=["PATCH"])
def amend_agreement(aid):
    """Amend commercial terms; OCC-guarded (PRD Section 2.7)."""
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    body = get_json(request)
    # Stage 5: the OCC field is non-optional on this endpoint.
    expected = require_int(body, "expected_store_agreement_version")
    # Stages 6/7: validate any provided amendment values.
    amendments = {}
    for field in ("base_margin_pct", "shrink_retailer_share_pct", "free_allowance_pct",
                  "estimated_shrink_rate", "markdown_jobber_share_pct", "shrink_suspend_ratio"):
        if field in body and body[field] is not None:
            lo_open = field == "base_margin_pct"
            hi_open = field == "base_margin_pct"
            amendments[field] = optional_pct(body, field, None,
                                             lo_open=lo_open, hi_open=hi_open)
    if "restock_value_cap_cents" in body and body["restock_value_cap_cents"] is not None:
        amendments["restock_value_cap_cents"] = require_int(body, "restock_value_cap_cents")
    # Stage 11: optimistic concurrency.
    if expected != agreement["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_store_agreement_version does not match current version")
    for field, value in amendments.items():
        agreement[field] = value
    # The liability mode forces the jobber share.
    if agreement["markdown_liability"] == "JOBBER":
        agreement["markdown_jobber_share_pct"] = 1.0
    elif agreement["markdown_liability"] == "RETAILER":
        agreement["markdown_jobber_share_pct"] = 0.0
    touch(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/submit", methods=["POST"])
def submit_agreement(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)
    require_from_state(agreement, ["DRAFT"], ["REJECTED", "TERMINATED"], "agreement", target="PENDING_ACCEPTANCE")
    agreement["status"] = "PENDING_ACCEPTANCE"
    touch(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/accept", methods=["POST"])
def accept_agreement(aid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)
    # Stage 8 ownership precedes stage 9 from-state validity.
    require_store_manager(user_id, agreement)
    require_from_state(agreement, ["PENDING_ACCEPTANCE"], ["REJECTED", "TERMINATED"], "agreement", target="ACTIVE")
    agreement["status"] = "ACTIVE"
    agreement["activated_at"] = store.now_iso()  # anchors settlement period 0
    touch(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/reject", methods=["POST"])
def reject_agreement(aid):
    user_id, role = extract_identity(request.headers)
    require_role(role, ["RetailerManager"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)  # optional reason accepted and ignored
    require_store_manager(user_id, agreement)
    require_from_state(agreement, ["PENDING_ACCEPTANCE"], ["REJECTED", "TERMINATED"], "agreement", target="REJECTED")
    agreement["status"] = "REJECTED"
    touch(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/suspend", methods=["POST"])
def suspend_agreement_endpoint(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)  # optional reason accepted and ignored
    require_from_state(agreement, ["ACTIVE"], ["REJECTED", "TERMINATED"], "agreement", target="SUSPENDED")
    # Side effect: every SCHEDULED service visit of the agreement -> CANCELLED.
    from services import suspend_agreement
    suspend_agreement(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/resume", methods=["POST"])
def resume_agreement(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)
    require_from_state(agreement, ["SUSPENDED"], ["REJECTED", "TERMINATED"], "agreement", target="ACTIVE")
    agreement["status"] = "ACTIVE"
    touch(agreement)
    return response.success(public(agreement))


@bp.route("/agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    agreement = get_or_404(store.agreements, aid, "agreement")
    get_json(request)
    require_from_state(agreement, ["ACTIVE", "SUSPENDED"], ["REJECTED", "TERMINATED"], "agreement", target="TERMINATED")
    # Preconditions: no unsettled statement and no unfinished seasonal set.
    for s in store.settlement_statements.values():
        if s["store_agreement_id"] == aid and s["status"] in SETTLEMENT_BLOCKING:
            raise err("ERR_INVALID_STATE", "agreement has an unsettled statement")
    for s in store.seasonal_sets.values():
        if s["store_agreement_id"] == aid and s["status"] in SET_BLOCKING:
            raise err("ERR_INVALID_STATE", "agreement has an unfinished seasonal set")
    # Side effects: close ACTIVE allocations; cancel SCHEDULED visits.
    for a in store.space_allocations.values():
        if a["store_agreement_id"] == aid and a["status"] == "ACTIVE":
            a["status"] = "CLOSED"
            touch(a)
    for v in store.service_visits.values():
        if v["store_agreement_id"] == aid and v["status"] == "SCHEDULED":
            v["status"] = "CANCELLED"
            touch(v)
    agreement["status"] = "TERMINATED"
    touch(agreement)
    return response.success(public(agreement))


# =============================================================================
# Products (PRD Section 3.2)
# =============================================================================

@bp.route("/products", methods=["POST"])
def create_product():
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    body = get_json(request)
    fk_exists(body, "program_id", store.programs)
    # Stage 5: shape.
    program_id = require_str(body, "program_id")
    sku = require_str(body, "sku")
    name = require_str(body, "name")
    jobber_cost = require_int(body, "jobber_cost_cents")
    min_retail = require_int(body, "min_retail_cents")
    upf = require_int(body, "units_per_facing")
    # Stage 7: all three numeric fields must be at least 1.
    for value, field in ((jobber_cost, "jobber_cost_cents"),
                         (min_retail, "min_retail_cents"),
                         (upf, "units_per_facing")):
        if value < 1:
            raise err("ERR_RANGE_INVALID", "%s must be >= 1" % field)
    # sku must be unique within the program.
    for p in store.products.values():
        if p["program_id"] == program_id and p["sku"] == sku:
            raise err("ERR_SKU_EXISTS", "sku already exists within program")
    product = new_entity({
        "program_id": program_id,
        "sku": sku,
        "name": name,
        "jobber_cost_cents": jobber_cost,
        "min_retail_cents": min_retail,
        "units_per_facing": upf,
        "status": "ACTIVE",
    })
    store.products[product["id"]] = product
    return response.success(public(product), http_status=201)


@bp.route("/products", methods=["GET"])
def list_products():
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = store.products.values()
    for param in ("program_id", "status"):
        val = request.args.get(param)
        if val is not None:
            rows = [p for p in rows if p[param] == val]
    page, meta = list_page(rows, limit, offset)
    return response.success(page, is_list=True, pagination=meta)


@bp.route("/products/<pid>", methods=["GET"])
def get_product(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ALL_ROLES)
    product = get_or_404(store.products, pid, "product")
    return response.success(public(product))


@bp.route("/products/<pid>", methods=["PATCH"])
def update_product(pid):
    _, role = extract_identity(request.headers)
    require_role(role, ["JobberAdmin"])
    product = get_or_404(store.products, pid, "product")
    body = get_json(request)
    # Stage 5 shape -> stage 6 enum -> stage 7 range.
    updates = {}
    for field in ("jobber_cost_cents", "min_retail_cents"):
        if field in body and body[field] is not None:
            updates[field] = require_int(body, field)
    status = optional_enum(body, "status", ["ACTIVE", "DISCONTINUED"])
    for field, value in updates.items():
        if value < 1:
            raise err("ERR_RANGE_INVALID", "%s must be >= 1" % field)
    if status is not None:
        product["status"] = status
    for field, value in updates.items():
        product[field] = value
    touch(product)
    return response.success(public(product))
