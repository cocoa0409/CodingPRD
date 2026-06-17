"""Portable Storage Container API — Flask entry point.

In-memory only; the store starts empty on every boot. No seeding.
"""
import os

from flask import Flask, request

from db import db
from errors import ApiError, err
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_VERSION,
    ERR_INVENTORY_ROW_MISSING, ERR_INSUFFICIENT_CLEARANCE,
    ERR_DECLARED_VALUE_OVER_CAP, ERR_CREW_WINDOW_CONFLICT,
    ERR_TRUCK_CAPACITY_EXCEEDED, ERR_OPEN_LOGISTICS, ERR_BILLING_NOT_CURRENT,
    ERR_OUTSTANDING_BALANCE, ERR_NO_INVENTORY,
)
from response import ok, error_response
from middleware import authenticate, require_role, require_owner_or_operator
from lookups import find, maybe, paginate, sorted_by_created
from domain import (
    stamp_create, touch, public, recompute_inventory, post_charge,
    recompute_balance, recompute_customer_mirrors, compute_days_overdue,
    total_late_fees_posted, agreement_charges_sorted,
)
import validation as V
import calculations as C
from clock import parse_iso, fmt_iso, Clock

app = Flask(__name__)

SIZE_CODES = {"C8", "C12", "C16"}
TIER_CODES = {"NONE", "BASIC", "PLUS", "PREMIER"}
ALL_ROLES = ["PlatformAdmin", "DispatchOperator", "BillingClerk", "Customer"]


# ==========================================================================
# Error handling
# ==========================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found."), 404


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed."), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message), e.http_status
    return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % e), 400


# ==========================================================================
# Helpers for agreement ownership / lookups
# ==========================================================================
def auth_ctx():
    return authenticate()


def load_agreement(agreement_id):
    return find("rental_agreement", agreement_id)


def container_model_for_size(size_code):
    for m in db.container_models.values():
        if m["size_code"] == size_code:
            return m
    return None


def protection_plan_for_tier(tier_code):
    for p in db.protection_plans.values():
        if p["tier_code"] == tier_code:
            return p
    return None


def inventory_row_for(depot_id, size_code):
    for inv in db.depot_inventory.values():
        if inv["depot_id"] == depot_id and inv["size_code"] == size_code:
            return inv
    return None


# ==========================================================================
# §3.1 Catalog: container models
# ==========================================================================
@app.route("/container-models", methods=["POST"])
def create_container_model():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["size_code", "cubic_feet", "monthly_rate_cents",
                            "delivery_fee_cents", "footprint_sqft"])
    size_code = V.require_enum(body, "size_code", SIZE_CODES)
    cubic_feet = V.require_int_min(body, "cubic_feet", 1)
    monthly = V.require_nonneg_int(body, "monthly_rate_cents")
    delivery = V.require_nonneg_int(body, "delivery_fee_cents")
    footprint = V.require_int_min(body, "footprint_sqft", 1)
    if container_model_for_size(size_code) is not None:
        raise err(ERR_INVALID_REQUEST, "size_code must be unique across ContainerModel.")
    m = stamp_create(immutable=True)
    m.update({"size_code": size_code, "cubic_feet": cubic_feet,
              "monthly_rate_cents": monthly, "delivery_fee_cents": delivery,
              "footprint_sqft": footprint})
    db.container_models[m["id"]] = m
    return ok(public(m), 201)


@app.route("/container-models", methods=["GET"])
def list_container_models():
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    rows = list(db.container_models.values())
    sc = request.args.get("size_code")
    if sc is not None:
        rows = [r for r in rows if r["size_code"] == sc]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/container-models/<cid>", methods=["GET"])
def get_container_model(cid):
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    return ok(public(find("container_model", cid)), 200)


# ==========================================================================
# Protection plans
# ==========================================================================
@app.route("/protection-plans", methods=["POST"])
def create_protection_plan():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["tier_code", "base_premium_cents", "rate_bps",
                            "min_premium_cents", "coverage_cap_cents"])
    tier_code = V.require_enum(body, "tier_code", TIER_CODES)
    base = V.require_nonneg_int(body, "base_premium_cents")
    rate_bps = V.require_nonneg_int(body, "rate_bps")
    min_prem = V.require_nonneg_int(body, "min_premium_cents")
    cap = V.require_nonneg_int(body, "coverage_cap_cents")
    if tier_code == "NONE" and cap != 0:
        raise err(ERR_INVALID_REQUEST, "NONE tier must have coverage_cap_cents = 0.")
    if protection_plan_for_tier(tier_code) is not None:
        raise err(ERR_INVALID_REQUEST, "tier_code must be unique across ProtectionPlan.")
    p = stamp_create(immutable=True)
    p.update({"tier_code": tier_code, "base_premium_cents": base,
              "rate_bps": rate_bps, "min_premium_cents": min_prem,
              "coverage_cap_cents": cap})
    db.protection_plans[p["id"]] = p
    return ok(public(p), 201)


@app.route("/protection-plans", methods=["GET"])
def list_protection_plans():
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    rows = list(db.protection_plans.values())
    tc = request.args.get("tier_code")
    if tc is not None:
        rows = [r for r in rows if r["tier_code"] == tc]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/protection-plans/<pid>", methods=["GET"])
def get_protection_plan(pid):
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    return ok(public(find("protection_plan", pid)), 200)


# ==========================================================================
# Depots, inventory, crews, trucks
# ==========================================================================
@app.route("/depots", methods=["POST"])
def create_depot():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["name", "state_code", "service_radius_miles"])
    name = V.require_str(body, "name")
    state_code = V.require_state_code(body, "state_code")
    radius = V.require_nonneg_int(body, "service_radius_miles")
    d = stamp_create()
    d.update({"name": name, "state_code": state_code,
              "service_radius_miles": radius})
    db.depots[d["id"]] = d
    return ok(public(d), 201)


@app.route("/depots/<did>", methods=["GET"])
def get_depot(did):
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    return ok(public(find("depot", did)), 200)


@app.route("/depot-inventory", methods=["POST"])
def create_depot_inventory():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["depot_id", "size_code", "total_units"])
    depot_id = V.require_str(body, "depot_id")
    size_code = V.require_enum(body, "size_code", SIZE_CODES)
    total = V.require_nonneg_int(body, "total_units")
    # existence (priority 3) before business uniqueness
    find("depot", depot_id)
    if inventory_row_for(depot_id, size_code) is not None:
        raise err(ERR_INVALID_REQUEST, "(depot_id, size_code) must be unique.")
    inv = stamp_create()
    inv.update({"depot_id": depot_id, "size_code": size_code,
                "total_units": total, "reserved_units": 0,
                "committed_units": 0, "available_units": total})
    db.depot_inventory[inv["id"]] = inv
    return ok(public(inv), 201)


@app.route("/depot-inventory", methods=["GET"])
def list_depot_inventory():
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    rows = list(db.depot_inventory.values())
    dp = request.args.get("depot_id")
    sc = request.args.get("size_code")
    if dp is not None:
        rows = [r for r in rows if r["depot_id"] == dp]
    if sc is not None:
        rows = [r for r in rows if r["size_code"] == sc]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/depot-inventory/<iid>", methods=["GET"])
def get_depot_inventory(iid):
    role, _ = auth_ctx()
    require_role(role, set(ALL_ROLES))
    return ok(public(find("depot_inventory", iid)), 200)


@app.route("/crews", methods=["POST"])
def create_crew():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["depot_id", "name"])
    depot_id = V.require_str(body, "depot_id")
    name = V.require_str(body, "name")
    buffer_minutes = V.opt_nonneg_int(body, "setup_buffer_minutes", 30)
    find("depot", depot_id)
    c = stamp_create()
    c.update({"depot_id": depot_id, "name": name,
              "setup_buffer_minutes": buffer_minutes})
    db.crews[c["id"]] = c
    return ok(public(c), 201)


@app.route("/crews/<cid>", methods=["GET"])
def get_crew(cid):
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    return ok(public(find("crew", cid)), 200)


@app.route("/crews", methods=["GET"])
def list_crews():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    rows = list(db.crews.values())
    dp = request.args.get("depot_id")
    if dp is not None:
        rows = [r for r in rows if r["depot_id"] == dp]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/trucks", methods=["POST"])
def create_truck():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["depot_id", "plate"])
    depot_id = V.require_str(body, "depot_id")
    plate = V.require_str(body, "plate")
    max_conc = V.opt_int_min(body, "max_concurrent_containers", 1, 1)
    find("depot", depot_id)
    for t in db.trucks.values():
        if t["plate"] == plate:
            raise err(ERR_INVALID_REQUEST, "plate must be unique across Truck.")
    t = stamp_create()
    t.update({"depot_id": depot_id, "plate": plate,
              "max_concurrent_containers": max_conc})
    db.trucks[t["id"]] = t
    return ok(public(t), 201)


@app.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    return ok(public(find("truck", tid)), 200)


@app.route("/trucks", methods=["GET"])
def list_trucks():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    rows = list(db.trucks.values())
    dp = request.args.get("depot_id")
    if dp is not None:
        rows = [r for r in rows if r["depot_id"] == dp]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


# ==========================================================================
# §3.2 Customers
# ==========================================================================
@app.route("/customers", methods=["POST"])
def create_customer():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "Customer"})
    body = V.get_body()
    V.require_fields(body, ["email", "full_name", "state_code"])
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name", allow_empty=True)
    state_code = V.require_state_code(body, "state_code")
    for cust in db.customers.values():
        if cust["email"] == email:
            raise err(ERR_INVALID_REQUEST, "email must be unique across Customer.")
    c = stamp_create()
    c.update({"email": email, "full_name": full_name, "state_code": state_code,
              "lifetime_paid_cents": 0, "open_balance_cents": 0})
    db.customers[c["id"]] = c
    return ok(public(c), 201)


@app.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    role, user_id = auth_ctx()
    require_role(role, {"PlatformAdmin", "BillingClerk", "Customer"})
    cust = find("customer", cid)
    if role == "Customer":
        require_owner_or_operator(role, user_id, cust["id"])
    return ok(public(cust), 200)


@app.route("/customers/<cid>/rental-agreements", methods=["GET"])
def list_customer_agreements(cid):
    role, user_id = auth_ctx()
    require_role(role, {"PlatformAdmin", "BillingClerk", "Customer"})
    cust = find("customer", cid)
    if role == "Customer":
        require_owner_or_operator(role, user_id, cust["id"])
    rows = [a for a in db.rental_agreements.values() if a["customer_id"] == cid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


# ==========================================================================
# §3.2 Rental agreements: create / read / list
# ==========================================================================
@app.route("/rental-agreements", methods=["POST"])
def create_rental_agreement():
    role, user_id = auth_ctx()
    require_role(role, {"Customer", "DispatchOperator"})
    body = V.get_body()
    V.require_fields(body, ["customer_id", "depot_id", "size_code",
                            "site_address", "site_clearance_sqft"])
    customer_id = V.require_str(body, "customer_id")
    depot_id = V.require_str(body, "depot_id")
    size_code = V.require_enum(body, "size_code", SIZE_CODES)
    tier_code = V.opt_enum(body, "protection_tier_code", TIER_CODES, "NONE")
    declared_value = V.opt_nonneg_int(body, "declared_value_cents", 0)
    proration_method = V.opt_enum(body, "proration_method",
                                  {"CALENDAR_DAY", "FIXED_30"}, "CALENDAR_DAY")
    site_address = V.require_str(body, "site_address", allow_empty=True)
    clearance = V.require_nonneg_int(body, "site_clearance_sqft")
    # existence: customer then depot (left-to-right)
    cust = find("customer", customer_id)
    find("depot", depot_id)
    # Customer may only create for self
    if role == "Customer":
        require_owner_or_operator(role, user_id, cust["id"])
    a = stamp_create()
    a.update({
        "customer_id": customer_id, "depot_id": depot_id, "size_code": size_code,
        "protection_tier_code": tier_code, "declared_value_cents": declared_value,
        "proration_method": proration_method, "site_address": site_address,
        "site_clearance_sqft": clearance,
        "lifecycle_status": "QUOTED", "billing_status": "CURRENT",
        "delivery_anchor_date": None, "monthly_premium_cents": 0,
        "balance_due_cents": 0, "last_charged_cycle_date": None,
        "days_overdue": 0,
    })
    db.rental_agreements[a["id"]] = a
    return ok(public(a), 201)


@app.route("/rental-agreements/<aid>", methods=["GET"])
def get_rental_agreement(aid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    a = load_agreement(aid)
    if role == "Customer":
        require_owner_or_operator(role, user_id, a["customer_id"])
    return ok(public(a), 200)


@app.route("/rental-agreements", methods=["GET"])
def list_rental_agreements():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator", "BillingClerk"})
    rows = list(db.rental_agreements.values())
    cust = request.args.get("customer_id")
    dp = request.args.get("depot_id")
    lc = request.args.get("lifecycle_status")
    if cust is not None:
        rows = [r for r in rows if r["customer_id"] == cust]
    if dp is not None:
        rows = [r for r in rows if r["depot_id"] == dp]
    if lc is not None:
        rows = [r for r in rows if r["lifecycle_status"] == lc]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


# ==========================================================================
# Agreement sub-resource list endpoints
# ==========================================================================
def _owner_guard_agreement(aid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    a = load_agreement(aid)
    if role == "Customer":
        require_owner_or_operator(role, user_id, a["customer_id"])
    return a


@app.route("/rental-agreements/<aid>/charges", methods=["GET"])
def list_agreement_charges(aid):
    _owner_guard_agreement(aid)
    rows = [c for c in db.charges.values() if c["agreement_id"] == aid]
    ct = request.args.get("charge_type")
    if ct is not None:
        rows = [r for r in rows if r["charge_type"] == ct]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/rental-agreements/<aid>/container-units", methods=["GET"])
def list_agreement_units(aid):
    _owner_guard_agreement(aid)
    rows = [u for u in db.container_units.values() if u["agreement_id"] == aid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/rental-agreements/<aid>/delivery-jobs", methods=["GET"])
def list_agreement_jobs(aid):
    _owner_guard_agreement(aid)
    rows = [j for j in db.delivery_jobs.values() if j["agreement_id"] == aid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/rental-agreements/<aid>/move-orders", methods=["GET"])
def list_agreement_moves(aid):
    _owner_guard_agreement(aid)
    rows = [m for m in db.move_orders.values() if m["agreement_id"] == aid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/rental-agreements/<aid>/access-visits", methods=["GET"])
def list_agreement_visits(aid):
    _owner_guard_agreement(aid)
    rows = [v for v in db.access_visits.values() if v["agreement_id"] == aid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/rental-agreements/<aid>/packing-supply-orders", methods=["GET"])
def list_agreement_supply_orders(aid):
    _owner_guard_agreement(aid)
    rows = [o for o in db.packing_supply_orders.values() if o["agreement_id"] == aid]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


# ==========================================================================
# §3.2 reserve (QUOTED -> RESERVED) with OCC + inventory gates
# ==========================================================================
@app.route("/rental-agreements/<aid>/reserve", methods=["POST"])
def reserve_agreement(aid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    a = load_agreement(aid)
    body = V.get_body()
    # schema: expected_agreement_version required (priority 4)
    V.require_fields(body, ["expected_agreement_version"])
    expected = V.require_nonneg_int(body, "expected_agreement_version")
    # priority 5: inventory row must exist for (depot_id, size_code)
    inv = inventory_row_for(a["depot_id"], a["size_code"])
    if inv is None:
        raise err(ERR_INVENTORY_ROW_MISSING,
                  "No DepotInventory row for (depot_id, size_code).")
    # priority 6: state precondition
    if a["lifecycle_status"] != "QUOTED":
        raise err(ERR_INVALID_STATE, "Agreement must be QUOTED to reserve.")
    # priority 7: OCC
    if expected != a["version"]:
        raise err(ERR_STALE_VERSION, "expected_agreement_version is stale.")
    # priority 9: declared value within coverage cap
    plan = protection_plan_for_tier(a["protection_tier_code"])
    if plan is None:
        raise err(ERR_INVENTORY_ROW_MISSING,
                  "No ProtectionPlan for selected tier.")
    if a["declared_value_cents"] > plan["coverage_cap_cents"]:
        raise err(ERR_DECLARED_VALUE_OVER_CAP,
                  "declared_value_cents exceeds tier coverage_cap_cents.")
    # priority 15: inventory floor
    if inv["available_units"] < 1:
        raise err(ERR_NO_INVENTORY, "No available units in inventory.")
    # side effects: create ContainerUnit RESERVED, bump inventory, bump version
    u = stamp_create()
    u.update({
        "agreement_id": a["id"], "depot_inventory_id": inv["id"],
        "size_code": inv["size_code"], "status": "RESERVED",
        "current_depot_id": inv["depot_id"],
    })
    db.container_units[u["id"]] = u
    recompute_inventory(inv)
    a["lifecycle_status"] = "RESERVED"
    touch(a)
    recompute_customer_mirrors(a["customer_id"])
    return ok(public(a), 200)


# ==========================================================================
# hold / resume / request-closeout / close / cancel
# ==========================================================================
@app.route("/rental-agreements/<aid>/hold", methods=["POST"])
def hold_agreement(aid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    a = load_agreement(aid)
    require_owner_or_operator(role, user_id, a["customer_id"])
    if a["lifecycle_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement must be ACTIVE to hold.")
    if a["billing_status"] in ("PAST_DUE", "DELINQUENT"):
        raise err(ERR_BILLING_NOT_CURRENT,
                  "Agreement billing_status must be CURRENT to hold.")
    a["lifecycle_status"] = "ON_HOLD"
    touch(a)
    return ok(public(a), 200)


@app.route("/rental-agreements/<aid>/resume", methods=["POST"])
def resume_agreement(aid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    a = load_agreement(aid)
    require_owner_or_operator(role, user_id, a["customer_id"])
    if a["lifecycle_status"] != "ON_HOLD":
        raise err(ERR_INVALID_STATE, "Agreement must be ON_HOLD to resume.")
    a["lifecycle_status"] = "ACTIVE"
    touch(a)
    return ok(public(a), 200)


@app.route("/rental-agreements/<aid>/request-closeout", methods=["POST"])
def request_closeout(aid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    a = load_agreement(aid)
    require_owner_or_operator(role, user_id, a["customer_id"])
    if a["lifecycle_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Agreement must be ACTIVE to request closeout.")
    # priority 12: closeout block on open logistics
    for m in db.move_orders.values():
        if m["agreement_id"] == aid and m["status"] in ("SCHEDULED", "IN_TRANSIT"):
            raise err(ERR_OPEN_LOGISTICS, "Open move order blocks closeout.")
    for j in db.delivery_jobs.values():
        if j["agreement_id"] == aid and j["status"] == "SCHEDULED":
            raise err(ERR_OPEN_LOGISTICS, "Scheduled delivery job blocks closeout.")
    a["lifecycle_status"] = "CLOSING"
    touch(a)
    # phase change can alter balance variant (PROVISIONAL -> FINAL)
    recompute_balance(a)
    return ok(public(a), 200)


@app.route("/rental-agreements/<aid>/close", methods=["POST"])
def close_agreement(aid):
    role, _ = auth_ctx()
    require_role(role, {"BillingClerk"})
    a = load_agreement(aid)
    if a["lifecycle_status"] != "CLOSING":
        raise err(ERR_INVALID_STATE, "Agreement must be CLOSING to close.")
    # find the unit(s) for the agreement
    units = [u for u in db.container_units.values()
             if u["agreement_id"] == aid and u["status"] != "RELEASED"]
    # the active unit must be RETURNED
    unit = units[0] if units else None
    if unit is None or unit["status"] != "RETURNED":
        raise err(ERR_INVALID_STATE, "Container must be RETURNED to close.")
    # fiscal gate: FINAL balance must be 0
    recompute_balance(a)  # a is CLOSING => FINAL variant
    if a["balance_due_cents"] > 0:
        raise err(ERR_OUTSTANDING_BALANCE, "Final balance must be settled to close.")
    # side effects
    a["lifecycle_status"] = "CLOSED"
    unit["status"] = "RELEASED"
    touch(unit)
    inv = db.depot_inventory.get(unit["depot_inventory_id"])
    if inv is not None:
        recompute_inventory(inv)
    touch(a)
    recompute_customer_mirrors(a["customer_id"])
    return ok(public(a), 200)


@app.route("/rental-agreements/<aid>/cancel", methods=["POST"])
def cancel_agreement(aid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    a = load_agreement(aid)
    require_owner_or_operator(role, user_id, a["customer_id"])
    if a["lifecycle_status"] not in ("QUOTED", "RESERVED"):
        raise err(ERR_INVALID_STATE, "Only QUOTED or RESERVED agreements can be cancelled.")
    if a["lifecycle_status"] == "RESERVED":
        # compensating: release the reserved unit, restore inventory pool
        for u in db.container_units.values():
            if u["agreement_id"] == aid and u["status"] == "RESERVED":
                u["status"] = "RELEASED"
                touch(u)
                inv = db.depot_inventory.get(u["depot_inventory_id"])
                if inv is not None:
                    recompute_inventory(inv)
    a["lifecycle_status"] = "CANCELLED"
    touch(a)
    recompute_customer_mirrors(a["customer_id"])
    return ok(public(a), 200)


# ==========================================================================
# §3.9 payments
# ==========================================================================
@app.route("/rental-agreements/<aid>/payments", methods=["POST"])
def post_payment(aid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    a = load_agreement(aid)
    require_owner_or_operator(role, user_id, a["customer_id"])
    body = V.get_body()
    V.require_fields(body, ["amount_cents", "expected_agreement_version"])
    amount = V.require_nonneg_int(body, "amount_cents")
    expected = V.require_nonneg_int(body, "expected_agreement_version")
    # OCC (priority 7)
    if expected != a["version"]:
        raise err(ERR_STALE_VERSION, "expected_agreement_version is stale.")
    # post a PAYMENT charge carrying the negative of the paid amount
    charge = post_charge(aid, "PAYMENT", -amount, due_date=None)
    recompute_balance(a)
    # billing dimension: if PAST_DUE/DELINQUENT and balance now 0 -> CURRENT
    if a["billing_status"] in ("PAST_DUE", "DELINQUENT") and a["balance_due_cents"] == 0:
        a["billing_status"] = "CURRENT"
    a["days_overdue"] = compute_days_overdue(a)
    touch(a)
    recompute_customer_mirrors(a["customer_id"])
    return ok(public(charge), 201)


# ==========================================================================
# Container units
# ==========================================================================
@app.route("/container-units/<uid>", methods=["GET"])
def get_container_unit(uid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    u = find("container_unit", uid)
    if role == "Customer":
        a = db.rental_agreements.get(u["agreement_id"])
        owner = a["customer_id"] if a else None
        require_owner_or_operator(role, user_id, owner)
    return ok(public(u), 200)


@app.route("/container-units", methods=["GET"])
def list_container_units():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator", "BillingClerk"})
    rows = list(db.container_units.values())
    for key in ("depot_inventory_id", "agreement_id", "current_depot_id"):
        v = request.args.get(key)
        if v is not None:
            rows = [r for r in rows if r.get(key) == v]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/container-units/<uid>/return-to-depot", methods=["POST"])
def return_unit_to_depot(uid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    u = find("container_unit", uid)
    a = db.rental_agreements.get(u["agreement_id"])
    if a is None:
        raise err(ERR_NOT_FOUND, "Parent agreement not found.")
    if u["status"] != "ON_SITE":
        raise err(ERR_INVALID_STATE, "Unit must be ON_SITE to return to depot.")
    if a["lifecycle_status"] != "CLOSING":
        raise err(ERR_INVALID_STATE, "Parent agreement must be CLOSING.")
    u["status"] = "RETURNED"
    touch(u)
    inv = db.depot_inventory.get(u["depot_inventory_id"])
    if inv is not None:
        recompute_inventory(inv)  # RETURNED still counts as committed
    return ok(public(u), 200)


# ==========================================================================
# §3.3 Delivery jobs
# ==========================================================================
@app.route("/delivery-jobs", methods=["POST"])
def create_delivery_job():
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    body = V.get_body()
    V.require_fields(body, ["agreement_id", "crew_id", "container_unit_id",
                            "window_start", "window_end"])
    agreement_id = V.require_str(body, "agreement_id")
    crew_id = V.require_str(body, "crew_id")
    unit_id = V.require_str(body, "container_unit_id")
    job_kind = V.opt_enum(body, "job_kind",
                          {"INITIAL_DELIVERY", "REDELIVERY"}, "INITIAL_DELIVERY")
    ws, we = V.require_window(body)
    # existence left-to-right: agreement, crew, unit
    a = find("rental_agreement", agreement_id)
    crew = find("crew", crew_id)
    unit = find("container_unit", unit_id)
    # priority 5 referential: unit belongs to the agreement
    if unit["agreement_id"] != agreement_id:
        raise err(ERR_INVENTORY_ROW_MISSING,
                  "ContainerUnit does not belong to the agreement.")
    # priority 8: clearance (INITIAL_DELIVERY only)
    if job_kind == "INITIAL_DELIVERY":
        model = container_model_for_size(a["size_code"])
        if model is not None and a["site_clearance_sqft"] < model["footprint_sqft"]:
            raise err(ERR_INSUFFICIENT_CLEARANCE,
                      "site_clearance_sqft below ContainerModel.footprint_sqft.")
    # priority 10: crew window conflict (half-open + buffer minutes appended)
    buffer_secs = crew["setup_buffer_minutes"] * 60
    new_start = ws
    new_end = we.timestamp() + buffer_secs
    for j in db.delivery_jobs.values():
        if j["crew_id"] != crew_id or j["status"] != "SCHEDULED":
            continue
        ex_start = parse_iso(j["window_start"]).timestamp()
        ex_end = parse_iso(j["window_end"]).timestamp() + buffer_secs
        # half-open buffered intervals overlap iff start < other_end and other_start < end
        if new_start.timestamp() < ex_end and ex_start < new_end:
            raise err(ERR_CREW_WINDOW_CONFLICT,
                      "Delivery window conflicts with another scheduled job on the crew.")
    j = stamp_create()
    j.update({
        "agreement_id": agreement_id, "crew_id": crew_id,
        "container_unit_id": unit_id, "job_kind": job_kind,
        "window_start": fmt_iso(ws), "window_end": fmt_iso(we),
        "status": "SCHEDULED",
    })
    db.delivery_jobs[j["id"]] = j
    return ok(public(j), 201)


@app.route("/delivery-jobs/<jid>", methods=["GET"])
def get_delivery_job(jid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    j = find("delivery_job", jid)
    if role == "Customer":
        a = db.rental_agreements.get(j["agreement_id"])
        require_owner_or_operator(role, user_id, a["customer_id"] if a else None)
    return ok(public(j), 200)


@app.route("/delivery-jobs", methods=["GET"])
def list_delivery_jobs():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    rows = list(db.delivery_jobs.values())
    for key in ("crew_id", "agreement_id", "container_unit_id"):
        v = request.args.get(key)
        if v is not None:
            rows = [r for r in rows if r.get(key) == v]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/delivery-jobs/<jid>/complete", methods=["POST"])
def complete_delivery_job(jid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    j = find("delivery_job", jid)
    if j["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Delivery job must be SCHEDULED to complete.")
    unit = db.container_units.get(j["container_unit_id"])
    if unit is None:
        raise err(ERR_NOT_FOUND, "Container unit not found.")
    a = db.rental_agreements.get(j["agreement_id"])
    if a is None:
        raise err(ERR_NOT_FOUND, "Agreement not found.")
    if j["job_kind"] == "INITIAL_DELIVERY":
        if unit["status"] != "RESERVED":
            raise err(ERR_INVALID_STATE, "Unit must be RESERVED for INITIAL_DELIVERY.")
        _activation_cascade(j, a, unit)
    else:  # REDELIVERY
        if unit["status"] != "IN_TRANSIT":
            raise err(ERR_INVALID_STATE, "Unit must be IN_TRANSIT for REDELIVERY.")
        unit["status"] = "ON_SITE"
        touch(unit)
    j["status"] = "COMPLETED"
    touch(j)
    return ok(public(j), 200)


def _activation_cascade(job, agreement, unit):
    """RESERVED->ACTIVE delivery activation chain (PRD §3.3, §3.4)."""
    # container RESERVED -> DELIVERED -> ON_SITE within one transition
    unit["status"] = "ON_SITE"
    touch(unit)
    inv = db.depot_inventory.get(unit["depot_inventory_id"])
    if inv is not None:
        recompute_inventory(inv)  # reserved-1, committed+1
    # delivery_anchor_date = date of job window_start
    anchor = parse_iso(job["window_start"])
    agreement["delivery_anchor_date"] = fmt_iso(anchor)
    agreement["lifecycle_status"] = "ACTIVE"
    # opening charges
    model = container_model_for_size(agreement["size_code"])
    plan = protection_plan_for_tier(agreement["protection_tier_code"])
    # DELIVERY_FEE
    post_charge(agreement["id"], "DELIVERY_FEE",
                model["delivery_fee_cents"] if model else 0,
                due_date=db.now())
    # lock monthly premium, post PROTECTION_PREMIUM
    premium = C.protection_premium(plan, agreement["declared_value_cents"]) if plan else 0
    agreement["monthly_premium_cents"] = premium
    post_charge(agreement["id"], "PROTECTION_PREMIUM", premium, due_date=db.now())
    # RENTAL_PRORATION first cycle
    proration = C.rental_proration(
        model["monthly_rate_cents"] if model else 0,
        anchor, agreement["proration_method"])
    post_charge(agreement["id"], "RENTAL_PRORATION", proration, due_date=db.now())
    agreement["last_charged_cycle_date"] = agreement["delivery_anchor_date"]
    touch(agreement)
    recompute_balance(agreement)
    recompute_customer_mirrors(agreement["customer_id"])


@app.route("/delivery-jobs/<jid>/cancel", methods=["POST"])
def cancel_delivery_job(jid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    j = find("delivery_job", jid)
    if j["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Only SCHEDULED jobs can be cancelled.")
    j["status"] = "CANCELLED"
    touch(j)
    return ok(public(j), 200)


# ==========================================================================
# §3.6 Move orders
# ==========================================================================
@app.route("/move-orders", methods=["POST"])
def create_move_order():
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    body = V.get_body()
    V.require_fields(body, ["agreement_id", "truck_id", "container_unit_id",
                            "origin_depot_id", "destination_state_code",
                            "distance_miles", "window_start", "window_end"])
    agreement_id = V.require_str(body, "agreement_id")
    truck_id = V.require_str(body, "truck_id")
    unit_id = V.require_str(body, "container_unit_id")
    origin_depot_id = V.require_str(body, "origin_depot_id")
    dest_state = V.require_state_code(body, "destination_state_code")
    distance = V.require_nonneg_int(body, "distance_miles")
    ws, we = V.require_window(body)
    # existence left-to-right: agreement, truck, unit, origin depot
    a = find("rental_agreement", agreement_id)
    truck = find("truck", truck_id)
    unit = find("container_unit", unit_id)
    depot = find("depot", origin_depot_id)
    # priority 5: unit belongs to agreement
    if unit["agreement_id"] != agreement_id:
        raise err(ERR_INVENTORY_ROW_MISSING,
                  "ContainerUnit does not belong to the agreement.")
    # classify + price (move_pricing) locked at scheduling
    move_class = C.classify_move(distance, depot["service_radius_miles"])
    quoted = C.move_pricing(distance, move_class)
    # priority 11: truck capacity over closed-interval intersection
    ws_ts = ws.timestamp()
    we_ts = we.timestamp()
    used = 0
    for m in db.move_orders.values():
        if m["truck_id"] != truck_id or m["status"] not in ("SCHEDULED", "IN_TRANSIT"):
            continue
        ex_s = parse_iso(m["window_start"]).timestamp()
        ex_e = parse_iso(m["window_end"]).timestamp()
        # closed intervals intersect iff start <= other_end and other_start <= end
        if ws_ts <= ex_e and ex_s <= we_ts:
            used += 1  # one container per move
    if used + 1 > truck["max_concurrent_containers"]:
        raise err(ERR_TRUCK_CAPACITY_EXCEEDED,
                  "Truck capacity exceeded across overlapping moves.")
    m = stamp_create()
    m.update({
        "agreement_id": agreement_id, "truck_id": truck_id,
        "container_unit_id": unit_id, "origin_depot_id": origin_depot_id,
        "destination_state_code": dest_state, "distance_miles": distance,
        "move_class": move_class, "window_start": fmt_iso(ws),
        "window_end": fmt_iso(we), "quoted_cost_cents": quoted,
        "status": "SCHEDULED",
    })
    db.move_orders[m["id"]] = m
    # post MOVE charge = quoted_cost_cents; recompute balance
    post_charge(agreement_id, "MOVE", quoted, due_date=db.now())
    recompute_balance(a)
    return ok(public(m), 201)


@app.route("/move-orders/<mid>", methods=["GET"])
def get_move_order(mid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    m = find("move_order", mid)
    if role == "Customer":
        a = db.rental_agreements.get(m["agreement_id"])
        require_owner_or_operator(role, user_id, a["customer_id"] if a else None)
    return ok(public(m), 200)


@app.route("/move-orders", methods=["GET"])
def list_move_orders():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    rows = list(db.move_orders.values())
    for key in ("truck_id", "agreement_id", "container_unit_id", "origin_depot_id"):
        v = request.args.get(key)
        if v is not None:
            rows = [r for r in rows if r.get(key) == v]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/move-orders/<mid>/dispatch", methods=["POST"])
def dispatch_move(mid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    m = find("move_order", mid)
    if m["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Move must be SCHEDULED to dispatch.")
    unit = db.container_units.get(m["container_unit_id"])
    a = db.rental_agreements.get(m["agreement_id"])
    if unit is None or a is None:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    if unit["status"] != "ON_SITE":
        raise err(ERR_INVALID_STATE, "Container must be ON_SITE to dispatch move.")
    if a["lifecycle_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent agreement must be ACTIVE.")
    m["status"] = "IN_TRANSIT"
    touch(m)
    unit["status"] = "IN_TRANSIT"
    touch(unit)
    inv = db.depot_inventory.get(unit["depot_inventory_id"])
    if inv is not None:
        recompute_inventory(inv)
    return ok(public(m), 200)


@app.route("/move-orders/<mid>/complete", methods=["POST"])
def complete_move(mid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    m = find("move_order", mid)
    if m["status"] != "IN_TRANSIT":
        raise err(ERR_INVALID_STATE, "Move must be IN_TRANSIT to complete.")
    unit = db.container_units.get(m["container_unit_id"])
    if unit is None:
        raise err(ERR_NOT_FOUND, "Container unit not found.")
    m["status"] = "COMPLETED"
    touch(m)
    unit["status"] = "ON_SITE"
    if m["move_class"] == "LONG_DISTANCE":
        # rebalance inventory: origin committed -1, destination committed +1
        origin_inv = db.depot_inventory.get(unit["depot_inventory_id"])
        dest_depot = _depot_for_state(m["destination_state_code"])
        dest_inv = None
        if dest_depot is not None:
            dest_inv = inventory_row_for(dest_depot["id"], unit["size_code"])
        if dest_depot is not None:
            unit["current_depot_id"] = dest_depot["id"]
        if dest_inv is not None:
            unit["depot_inventory_id"] = dest_inv["id"]
        touch(unit)
        if origin_inv is not None:
            recompute_inventory(origin_inv)
        if dest_inv is not None and dest_inv is not origin_inv:
            recompute_inventory(dest_inv)
    else:
        touch(unit)
        inv = db.depot_inventory.get(unit["depot_inventory_id"])
        if inv is not None:
            recompute_inventory(inv)
    return ok(public(m), 200)


def _depot_for_state(state_code):
    for d in db.depots.values():
        if d["state_code"] == state_code:
            return d
    return None


@app.route("/move-orders/<mid>/cancel", methods=["POST"])
def cancel_move(mid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    m = find("move_order", mid)
    if m["status"] != "SCHEDULED":
        raise err(ERR_INVALID_STATE, "Only SCHEDULED moves can be cancelled.")
    m["status"] = "CANCELLED"
    touch(m)
    # compensating ADJUSTMENT = -quoted_cost_cents (a MOVE charge was posted at scheduling)
    a = db.rental_agreements.get(m["agreement_id"])
    post_charge(m["agreement_id"], "ADJUSTMENT", -m["quoted_cost_cents"], due_date=None)
    if a is not None:
        recompute_balance(a)
    return ok(public(m), 200)


# ==========================================================================
# §3.7 Access visits
# ==========================================================================
@app.route("/access-visits", methods=["POST"])
def create_access_visit():
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    body = V.get_body()
    V.require_fields(body, ["agreement_id", "container_unit_id", "requested_for"])
    agreement_id = V.require_str(body, "agreement_id")
    unit_id = V.require_str(body, "container_unit_id")
    access_kind = V.opt_enum(body, "access_kind",
                             {"ON_SITE", "DEPOT_PICKUP"}, "ON_SITE")
    requested_for = V.require_dt(body, "requested_for")
    a = find("rental_agreement", agreement_id)
    require_owner_or_operator(role, user_id, a["customer_id"])
    unit = find("container_unit", unit_id)
    if unit["agreement_id"] != agreement_id:
        raise err(ERR_INVENTORY_ROW_MISSING,
                  "ContainerUnit does not belong to the agreement.")
    v = stamp_create()
    v.update({
        "agreement_id": agreement_id, "container_unit_id": unit_id,
        "access_kind": access_kind, "requested_for": fmt_iso(requested_for),
        "redelivery_required": (access_kind == "DEPOT_PICKUP"),
        "status": "REQUESTED",
    })
    db.access_visits[v["id"]] = v
    return ok(public(v), 201)


@app.route("/access-visits/<vid>", methods=["GET"])
def get_access_visit(vid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    v = find("access_visit", vid)
    if role == "Customer":
        a = db.rental_agreements.get(v["agreement_id"])
        require_owner_or_operator(role, user_id, a["customer_id"] if a else None)
    return ok(public(v), 200)


@app.route("/access-visits", methods=["GET"])
def list_access_visits():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin", "DispatchOperator"})
    rows = list(db.access_visits.values())
    for key in ("agreement_id", "container_unit_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    rows = sorted_by_created(rows)
    page, meta = paginate(rows)
    return ok([public(r) for r in page], 200, pagination=meta)


@app.route("/access-visits/<vid>/fulfill", methods=["POST"])
def fulfill_access_visit(vid):
    role, _ = auth_ctx()
    require_role(role, {"DispatchOperator"})
    v = find("access_visit", vid)
    a = db.rental_agreements.get(v["agreement_id"])
    unit = db.container_units.get(v["container_unit_id"])
    if a is None or unit is None:
        raise err(ERR_NOT_FOUND, "Referenced resource not found.")
    if v["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Visit must be REQUESTED to fulfill.")
    if a["lifecycle_status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Parent agreement must be ACTIVE.")
    if unit["status"] != "ON_SITE":
        raise err(ERR_INVALID_STATE, "Container must be ON_SITE to fulfill access.")
    v["status"] = "FULFILLED"
    touch(v)
    # post ACCESS_FEE charge
    post_charge(v["agreement_id"], "ACCESS_FEE", _access_fee_amount(), due_date=db.now())
    if v["access_kind"] == "DEPOT_PICKUP":
        unit["status"] = "IN_TRANSIT"
        touch(unit)
        v["redelivery_required"] = True
        inv = db.depot_inventory.get(unit["depot_inventory_id"])
        if inv is not None:
            recompute_inventory(inv)
    recompute_balance(a)
    return ok(public(v), 200)


def _access_fee_amount():
    # The PRD does not parametrize an ACCESS_FEE table value; the fee is a posted
    # ACCESS_FEE Charge. With no configured amount, a flat access fee of 0 keeps
    # the ledger consistent without inventing a number not in the spec.
    return 0


@app.route("/access-visits/<vid>/cancel", methods=["POST"])
def cancel_access_visit(vid):
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    v = find("access_visit", vid)
    a = db.rental_agreements.get(v["agreement_id"])
    require_owner_or_operator(role, user_id, a["customer_id"] if a else None)
    if v["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Only REQUESTED visits can be cancelled.")
    v["status"] = "CANCELLED"
    touch(v)
    return ok(public(v), 200)


# ==========================================================================
# §3.7 Packing supply orders
# ==========================================================================
@app.route("/packing-supply-orders", methods=["POST"])
def create_packing_supply_order():
    role, user_id = auth_ctx()
    require_role(role, {"Customer"})
    body = V.get_body()
    V.require_fields(body, ["agreement_id", "lines"])
    agreement_id = V.require_str(body, "agreement_id")
    lines = body.get("lines")
    tax_rate_bps = V.opt_nonneg_int(body, "tax_rate_bps", 825)
    a = find("rental_agreement", agreement_id)
    require_owner_or_operator(role, user_id, a["customer_id"])
    # schema: lines non-empty array of valid line objects
    if not isinstance(lines, list) or len(lines) == 0:
        raise err(ERR_INVALID_REQUEST, "lines must be a non-empty array.")
    norm_lines = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise err(ERR_INVALID_REQUEST, "Each line must be an object.")
        for f in ("sku", "qty", "unit_price_cents", "bulk_threshold", "bulk_pct"):
            if f not in ln or ln[f] is None:
                raise err(ERR_INVALID_REQUEST, "Line missing field: %s" % f)
        qty = ln["qty"]
        unit_price = ln["unit_price_cents"]
        bulk_threshold = ln["bulk_threshold"]
        bulk_pct = ln["bulk_pct"]
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise err(ERR_INVALID_REQUEST, "Line qty must be an integer >= 1.")
        if isinstance(unit_price, bool) or not isinstance(unit_price, int) or unit_price < 0:
            raise err(ERR_INVALID_REQUEST, "Line unit_price_cents must be >= 0.")
        if isinstance(bulk_threshold, bool) or not isinstance(bulk_threshold, int):
            raise err(ERR_INVALID_REQUEST, "Line bulk_threshold must be an integer.")
        if not isinstance(bulk_pct, (int, float)) or isinstance(bulk_pct, bool):
            raise err(ERR_INVALID_REQUEST, "Line bulk_pct must be numeric.")
        norm_lines.append({
            "sku": ln["sku"], "qty": qty, "unit_price_cents": unit_price,
            "bulk_threshold": bulk_threshold, "bulk_pct": bulk_pct,
        })
    subtotal, tax, total = C.packing_supplies_total(norm_lines, tax_rate_bps)
    o = stamp_create()
    o.update({
        "agreement_id": agreement_id, "lines": norm_lines,
        "tax_rate_bps": tax_rate_bps, "subtotal_cents": subtotal,
        "tax_cents": tax, "total_cents": total, "status": "PLACED",
    })
    db.packing_supply_orders[o["id"]] = o
    post_charge(agreement_id, "PACKING_SUPPLIES", total, due_date=db.now())
    recompute_balance(a)
    return ok(public(o), 201)


@app.route("/packing-supply-orders/<oid>", methods=["GET"])
def get_packing_supply_order(oid):
    role, user_id = auth_ctx()
    require_role(role, set(ALL_ROLES))
    o = find("packing_supply_order", oid)
    if role == "Customer":
        a = db.rental_agreements.get(o["agreement_id"])
        require_owner_or_operator(role, user_id, a["customer_id"] if a else None)
    return ok(public(o), 200)


# ==========================================================================
# §3.8 / §3.9 Billing sweeps + clock (test-driving)
# ==========================================================================
@app.route("/_billing/run-late-sweep", methods=["POST"])
def run_late_sweep():
    role, _ = auth_ctx()
    require_role(role, {"BillingClerk"})
    for a in list(db.rental_agreements.values()):
        days = compute_days_overdue(a)
        a["days_overdue"] = days
        moved = False
        # CURRENT -> PAST_DUE (5 < days <= 20): post tier1 LATE_FEE
        if a["billing_status"] == "CURRENT" and C.GRACE_DAYS < days <= C.DELINQUENT_DAYS:
            fee = C.late_fee_capped(days, a["balance_due_cents"])
            post_charge(a["id"], "LATE_FEE", fee, due_date=db.now())
            a["billing_status"] = "PAST_DUE"
            recompute_balance(a)
            moved = True
        # PAST_DUE -> DELINQUENT (days > 20): post incremental delta only
        if a["billing_status"] == "PAST_DUE" and days > C.DELINQUENT_DAYS:
            current_total = C.late_fee_capped(days, a["balance_due_cents"])
            already = total_late_fees_posted(a["id"])
            delta = current_total - already
            if delta < 0:
                delta = 0
            post_charge(a["id"], "LATE_FEE", delta, due_date=db.now())
            a["billing_status"] = "DELINQUENT"
            recompute_balance(a)
            moved = True
        if moved or days != a.get("_last_days_overdue"):
            a["_last_days_overdue"] = days
            touch(a)
    return ok({}, 200)


@app.route("/_billing/run-monthly-cycle", methods=["POST"])
def run_monthly_cycle():
    role, _ = auth_ctx()
    require_role(role, {"BillingClerk"})
    now = db.now()
    for a in list(db.rental_agreements.values()):
        if a["lifecycle_status"] != "ACTIVE":
            continue  # ON_HOLD and others skipped
        if a["last_charged_cycle_date"] is None:
            continue
        last = parse_iso(a["last_charged_cycle_date"])
        # current cycle anchor = first of the current clock month
        if not _precedes_current_cycle(last, now):
            continue
        model = container_model_for_size(a["size_code"])
        amount = (model["monthly_rate_cents"] if model else 0) + a["monthly_premium_cents"]
        post_charge(a["id"], "RENTAL_CYCLE", amount, due_date=now)
        # advance last_charged_cycle_date to the first of the current month
        a["last_charged_cycle_date"] = fmt_iso(_first_of_month(now))
        touch(a)
        recompute_balance(a)
    return ok({}, 200)


def _first_of_month(dt):
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _precedes_current_cycle(last, now):
    """The agreement's last_charged_cycle_date precedes the current cycle when
    it falls in an earlier (year, month) than the current clock."""
    return (last.year, last.month) < (now.year, now.month)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    role, _ = auth_ctx()
    require_role(role, {"PlatformAdmin"})
    body = V.get_body()
    V.require_fields(body, ["to_iso8601"])
    dt = V.require_dt(body, "to_iso8601")
    db.clock.set(dt)
    return ok({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
