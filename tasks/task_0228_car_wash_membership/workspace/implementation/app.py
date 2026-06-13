"""Car Wash Unlimited Membership API — entry point and routes.

Boots with an empty in-memory store on every process start. No seeding.
"""
import os
import socket
from datetime import timedelta

# Werkzeug's dev server calls socket.getfqdn() while binding, which performs a
# reverse-DNS lookup that can block for ~5s on some hosts (notably macOS). Under
# per-test-server isolation the server reboots before every test, so a 5s boot
# stall causes "server could not be restarted" timeouts under concurrent load.
# Substitute the instant gethostname() — this affects only the server's display
# name, never request handling. getfqdn() is called as getfqdn(host), so the
# replacement must accept (and ignore) the positional argument.
socket.getfqdn = lambda *args, **kwargs: socket.gethostname()

from flask import Flask, request

import billing
import calc
import domain
from db import store, parse_iso
from errors import ApiError, err
from middleware import get_auth, optional_auth, require_roles, require_owner
from response import success, list_response, error_response

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found.")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    return error_response("ERR_INVALID_REQUEST", 422, str(e))


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {f}")


def require_int(data, field, minimum=None):
    val = data.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    return val


def require_str(data, field):
    val = data.get(field)
    if not isinstance(val, str) or not val.strip():
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return val


# ---------------------------------------------------------------------------
# Pagination helpers (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination_args():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, serializer):
    """items: list already sorted by created_at ascending (PRD 2.3)."""
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serializer(i) for i in page], limit, offset, total)


def sorted_by_created(items):
    # Sort chronologically by created_at, breaking ties by the monotonic
    # insertion sequence so order is deterministic even when several rows share
    # the same created_at under a frozen logical clock (PRD 2.3, 2.9).
    return sorted(items, key=lambda i: (i["created_at"], i.get("_seq", 0), i["id"]))


# ---------------------------------------------------------------------------
# Lookup helpers (path existence — PRD 2.6)
# ---------------------------------------------------------------------------
def get_or_404(collection, ident):
    obj = collection.get(ident)
    if obj is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return obj


def fk_or_404(collection, ident):
    obj = collection.get(ident)
    if obj is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource does not exist.")
    return obj


def normalize_plate(plate):
    return "".join(ch for ch in plate.upper() if ch.isalnum())


# ===========================================================================
# CATALOG: PLANS
# ===========================================================================
@app.route("/plans", methods=["POST"])
def create_plan():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    require_fields(data, ["name", "tier_type", "monthly_fee_cents"])
    require_str(data, "name")
    tier_type = data["tier_type"]
    if tier_type not in ("UNLIMITED", "SINGLE_WASH"):
        raise err("ERR_INVALID_REQUEST", "tier_type must be UNLIMITED or SINGLE_WASH.")
    monthly_fee = require_int(data, "monthly_fee_cents", minimum=0)
    included_credits = require_int_default(data, "included_credits", 0, minimum=0)
    per_credit_price = require_int_default(data, "per_credit_price_cents", 0, minimum=0)
    wash_cooldown = require_int_default(data, "wash_cooldown_hours", 0, minimum=0)
    max_addons = require_int_default(data, "max_addons", 3, minimum=0)

    # Plan-shape consistency (PRD 3.1, priority 12)
    if tier_type == "SINGLE_WASH":
        if not (included_credits > 0 and monthly_fee == 0 and wash_cooldown == 0):
            raise err("ERR_PLAN_SHAPE_INVALID", "SINGLE_WASH plan shape invalid.")
    else:  # UNLIMITED
        if included_credits != 0:
            raise err("ERR_PLAN_SHAPE_INVALID", "UNLIMITED plan must have included_credits == 0.")

    plan = {
        "id": store.new_id(),
        "name": data["name"],
        "tier_type": tier_type,
        "monthly_fee_cents": monthly_fee,
        "included_credits": included_credits,
        "per_credit_price_cents": per_credit_price,
        "wash_cooldown_hours": wash_cooldown,
        "max_addons": max_addons,
        "status": "ACTIVE",
    }
    domain._stamp_create(plan)
    store.plans[plan["id"]] = plan
    return success(domain.serialize_plan(plan), status=201)


def require_int_default(data, field, default, minimum=None):
    if field not in data or data[field] is None:
        return default
    return require_int(data, field, minimum=minimum)


@app.route("/plans", methods=["GET"])
def list_plans():
    # Read-only catalog lookup — exempt from the auth gate (PRD 2.1).
    optional_auth()
    items = list(store.plans.values())
    tier = request.args.get("tier_type")
    status = request.args.get("status")
    if tier is not None:
        items = [p for p in items if p["tier_type"] == tier]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(sorted_by_created(items), domain.serialize_plan)


@app.route("/plans/<pid>", methods=["GET"])
def get_plan(pid):
    # Read-only catalog lookup — exempt from the auth gate (PRD 2.1).
    optional_auth()
    plan = get_or_404(store.plans, pid)
    return success(domain.serialize_plan(plan))


@app.route("/plans/<pid>/retire", methods=["POST"])
def retire_plan(pid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    plan = get_or_404(store.plans, pid)
    plan["status"] = "RETIRED"
    domain.touch(plan)
    return success(domain.serialize_plan(plan))


# ===========================================================================
# CATALOG: LOCATIONS
# ===========================================================================
@app.route("/locations", methods=["POST"])
def create_location():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    require_fields(data, ["name", "state_code", "daily_wash_capacity"])
    require_str(data, "name")
    require_str(data, "state_code")
    capacity = require_int(data, "daily_wash_capacity", minimum=1)
    in_network = data.get("in_network", True)
    if not isinstance(in_network, bool):
        raise err("ERR_INVALID_REQUEST", "in_network must be a boolean.")
    loc = {
        "id": store.new_id(),
        "name": data["name"],
        "state_code": data["state_code"],
        "in_network": in_network,
        "daily_wash_capacity": capacity,
        "status": "OPEN",
    }
    domain._stamp_create(loc)
    store.locations[loc["id"]] = loc
    return success(domain.serialize_location(loc), status=201)


@app.route("/locations", methods=["GET"])
def list_locations():
    # Read-only catalog lookup — exempt from the auth gate (PRD 2.1).
    optional_auth()
    items = list(store.locations.values())
    status = request.args.get("status")
    in_network = request.args.get("in_network")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if in_network is not None:
        want = in_network.lower() == "true"
        items = [l for l in items if l["in_network"] == want]
    return paginate(sorted_by_created(items), domain.serialize_location)


@app.route("/locations/<lid>", methods=["GET"])
def get_location(lid):
    # Read-only catalog lookup — exempt from the auth gate (PRD 2.1).
    optional_auth()
    loc = get_or_404(store.locations, lid)
    return success(domain.serialize_location(loc))


@app.route("/locations/<lid>/close", methods=["POST"])
def close_location(lid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    loc = get_or_404(store.locations, lid)
    if loc["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Location is not OPEN.")
    loc["status"] = "CLOSED"
    domain.touch(loc)
    return success(domain.serialize_location(loc))


@app.route("/locations/<lid>/reopen", methods=["POST"])
def reopen_location(lid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    loc = get_or_404(store.locations, lid)
    if loc["status"] != "CLOSED":
        raise err("ERR_INVALID_STATE", "Location is not CLOSED.")
    loc["status"] = "OPEN"
    domain.touch(loc)
    return success(domain.serialize_location(loc))


# ===========================================================================
# CATALOG: ADD-ONS
# ===========================================================================
@app.route("/addons", methods=["POST"])
def create_addon():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    require_fields(data, ["name", "recurring_fee_cents"])
    require_str(data, "name")
    fee = require_int(data, "recurring_fee_cents", minimum=0)
    ad = {
        "id": store.new_id(),
        "name": data["name"],
        "recurring_fee_cents": fee,
        "status": "ACTIVE",
    }
    domain._stamp_create(ad)
    store.addons[ad["id"]] = ad
    return success(domain.serialize_addon(ad), status=201)


@app.route("/addons", methods=["GET"])
def list_addons():
    # Read-only catalog lookup — exempt from the auth gate (PRD 2.1).
    optional_auth()
    items = list(store.addons.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return paginate(sorted_by_created(items), domain.serialize_addon)


# ===========================================================================
# ACCOUNTS
# ===========================================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    # Exempt from auth (PRD 2.1: account self-registration). But if headers are
    # present they must be a permitted role.
    if request.headers.get("X-User-ID") or request.headers.get("X-User-Role"):
        uid, role = get_auth()
        require_roles(role, ["PlatformAdmin", "AccountHolder"])
    data = body()
    require_fields(data, ["account_type", "contact_email"])
    account_type = data["account_type"]
    if account_type not in ("INDIVIDUAL", "FLEET"):
        raise err("ERR_INVALID_REQUEST", "account_type must be INDIVIDUAL or FLEET.")
    require_str(data, "contact_email")
    company_name = data.get("company_name")
    # FLEET requires company_name; INDIVIDUAL forbids it (PRD 3.2, priority 6)
    if account_type == "FLEET":
        if not company_name or not isinstance(company_name, str) or not company_name.strip():
            raise err("ERR_INVALID_REQUEST", "FLEET account requires company_name.")
    else:
        if company_name is not None:
            raise err("ERR_INVALID_REQUEST", "INDIVIDUAL account must not supply company_name.")
    acct = {
        "id": store.new_id(),
        "account_type": account_type,
        "company_name": company_name if account_type == "FLEET" else None,
        "contact_email": data["contact_email"],
        "status": "ACTIVE",
    }
    domain._stamp_create(acct)
    store.accounts[acct["id"]] = acct
    return success(domain.serialize_account(acct), status=201)


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    acct = get_or_404(store.accounts, aid)
    require_owner(role, uid, acct["id"])
    return success(domain.serialize_account(acct))


@app.route("/accounts/<aid>/suspend", methods=["POST"])
def suspend_account(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    acct = get_or_404(store.accounts, aid)
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE.")
    acct["status"] = "SUSPENDED"
    # Cascade: ACTIVE/PAST_DUE memberships -> FROZEN -> add-ons PAUSED (PRD 3.10)
    for m in store.memberships.values():
        if m["account_id"] == acct["id"] and m["status"] in ("ACTIVE", "PAST_DUE"):
            domain.freeze_membership(m, create_freeze_row=False)
    domain.touch(acct)
    return success(domain.serialize_account(acct))


@app.route("/accounts/<aid>/reactivate", methods=["POST"])
def reactivate_account(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    acct = get_or_404(store.accounts, aid)
    if acct["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Account is not SUSPENDED.")
    acct["status"] = "ACTIVE"
    # Memberships are NOT auto-thawed (PRD 3.10).
    domain.touch(acct)
    return success(domain.serialize_account(acct))


@app.route("/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    acct = get_or_404(store.accounts, aid)
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE.")
    blocking = ("ACTIVE", "PAST_DUE", "FROZEN", "CANCEL_SCHEDULED")
    for m in store.memberships.values():
        if m["account_id"] == acct["id"] and m["status"] in blocking:
            raise err("ERR_INVALID_STATE", "Account has live memberships; cannot close.")
    acct["status"] = "CLOSED"
    domain.touch(acct)
    return success(domain.serialize_account(acct))


# ===========================================================================
# VEHICLES
# ===========================================================================
@app.route("/accounts/<aid>/vehicles", methods=["POST"])
def register_vehicle(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    acct = get_or_404(store.accounts, aid)
    require_owner(role, uid, acct["id"])
    data = body()
    require_fields(data, ["license_plate", "state_code"])
    require_str(data, "license_plate")
    require_str(data, "state_code")
    # Account must be ACTIVE (PRD 3.2, priority 8)
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Account is not ACTIVE.")
    plate = normalize_plate(data["license_plate"])
    # Plate uniqueness among ACTIVE vehicles (PRD 3.2, priority 7)
    for v in store.vehicles.values():
        if v["status"] == "ACTIVE" and v["license_plate"] == plate:
            raise err("ERR_PLATE_TAKEN", "License plate already in use by an ACTIVE vehicle.")
    veh = {
        "id": store.new_id(),
        "account_id": acct["id"],
        "license_plate": plate,
        "state_code": data["state_code"],
        "status": "ACTIVE",
    }
    domain._stamp_create(veh)
    store.vehicles[veh["id"]] = veh
    return success(domain.serialize_vehicle(veh), status=201)


@app.route("/accounts/<aid>/vehicles", methods=["GET"])
def list_vehicles(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    acct = get_or_404(store.accounts, aid)
    require_owner(role, uid, acct["id"])
    items = [v for v in store.vehicles.values() if v["account_id"] == acct["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [v for v in items if v["status"] == status]
    return paginate(sorted_by_created(items), domain.serialize_vehicle)


@app.route("/vehicles/<vid>", methods=["GET"])
def get_vehicle(vid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    veh = get_or_404(store.vehicles, vid)
    require_owner(role, uid, veh["account_id"])
    return success(domain.serialize_vehicle(veh))


@app.route("/vehicles/<vid>/remove", methods=["POST"])
def remove_vehicle(vid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    veh = get_or_404(store.vehicles, vid)
    require_owner(role, uid, veh["account_id"])
    veh["status"] = "REMOVED"
    domain.touch(veh)
    return success(domain.serialize_vehicle(veh))


@app.route("/vehicles/<vid>/usage-intensity", methods=["GET"])
def usage_intensity(vid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "LocationOperator"])
    veh = get_or_404(store.vehicles, vid)
    require_owner(role, uid, veh["account_id"])
    now = store.now()
    relevant = [
        w
        for w in store.wash_events.values()
        if w.get("vehicle_id") == veh["id"] and w["status"] in ("ADMITTED", "COMPLETED")
    ]
    lifetime = len(relevant)
    window_start = now - timedelta(days=7)
    acute = sum(
        1
        for w in relevant
        if w.get("admitted_at_utc") and w["admitted_at_utc"] >= window_start
    )
    chronic = calc.chronic_intensity(lifetime, veh["created_at"], now)
    data = domain.serialize_vehicle(veh)
    data["chronic_intensity"] = chronic
    data["acute_intensity"] = acute
    data["is_abuse"] = calc.is_abuse(acute, chronic)
    return success(data)


# ===========================================================================
# WALLET
# ===========================================================================
@app.route("/accounts/<aid>/wallet-transactions", methods=["GET"])
def list_wallet_transactions(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    acct = get_or_404(store.accounts, aid)
    require_owner(role, uid, acct["id"])
    items = [t for t in store.wallet_transactions.values() if t["account_id"] == acct["id"]]
    reason = request.args.get("reason")
    if reason is not None:
        items = [t for t in items if t["reason"] == reason]
    return paginate(sorted_by_created(items), domain.serialize_wallet_txn)


@app.route("/accounts/<aid>/adjustments", methods=["POST"])
def manual_adjustment(aid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "BillingAdmin"])
    acct = get_or_404(store.accounts, aid)
    data = body()
    require_fields(data, ["amount_cents"])
    amount = data["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise err("ERR_INVALID_REQUEST", "amount_cents must be an integer.")
    # amount_cents != 0 (PRD 3.10, priority 13)
    if amount == 0:
        raise err("ERR_VALIDATION", "amount_cents must not be zero.")
    # No-negative-balance (PRD 2.9, priority 23)
    if domain.wallet_balance(acct["id"]) + amount < 0:
        raise err("ERR_INSUFFICIENT_WALLET", "Adjustment would drive wallet below 0.")
    txn = domain.write_wallet_txn(acct["id"], amount, "MANUAL_ADJUSTMENT")
    return success(domain.serialize_wallet_txn(txn), status=201)


# ===========================================================================
# MEMBERSHIPS
# ===========================================================================
@app.route("/memberships", methods=["POST"])
def enroll_membership():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    data = body()
    require_fields(data, ["account_id", "vehicle_id", "plan_id"])
    # FK existence (priority 4)
    acct = fk_or_404(store.accounts, data["account_id"])
    veh = fk_or_404(store.vehicles, data["vehicle_id"])
    plan = fk_or_404(store.plans, data["plan_id"])
    require_owner(role, uid, acct["id"])
    # Account must be ACTIVE (priority 8)
    if acct["status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_NOT_ACTIVE", "Account is not ACTIVE.")
    # Plan must be ACTIVE (priority 11)
    if plan["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_RETIRED", "Plan is RETIRED.")
    # One live membership per vehicle (PRD 3.3)
    for m in store.memberships.values():
        if m["vehicle_id"] == veh["id"] and m["status"] in ("ACTIVE", "FROZEN", "PAST_DUE"):
            raise err("ERR_INVALID_STATE", "Vehicle already has a live membership.")
    membership = {
        "id": store.new_id(),
        "account_id": acct["id"],
        "vehicle_id": veh["id"],
        "plan_id": plan["id"],
        "status": "PENDING",
        "cycle_anchor_utc": None,
        "current_cycle_paid_cents": 0,
        "credits_granted": 0,
        "credits_consumed": 0,
        "last_admitted_wash_utc": None,
        "cycle_credits_consumed_start": 0,
    }
    domain._stamp_create(membership)
    store.memberships[membership["id"]] = membership
    # Raise the first CYCLE invoice (DRAFT -> ISSUED) (PRD 3.3)
    billing.create_cycle_invoice(membership, acct, plan)
    return success(domain.serialize_membership(membership), status=201)


@app.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    return success(domain.serialize_membership(m))


@app.route("/memberships", methods=["GET"])
def list_memberships():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    items = list(store.memberships.values())
    if role == "AccountHolder":
        items = [m for m in items if m["account_id"] == uid]
    for key in ("account_id", "vehicle_id", "plan_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [m for m in items if m[key] == val]
    return paginate(sorted_by_created(items), domain.serialize_membership)


@app.route("/memberships/<mid>/change-plan", methods=["POST"])
def change_plan(mid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    data = body()
    require_fields(data, ["new_plan_id"])
    new_plan = fk_or_404(store.plans, data["new_plan_id"])
    add_addon_ids = data.get("add_addon_ids", []) or []
    if not isinstance(add_addon_ids, list):
        raise err("ERR_INVALID_REQUEST", "add_addon_ids must be a list.")
    addons_to_add = []
    for aid in add_addon_ids:
        addons_to_add.append(fk_or_404(store.addons, aid))
    # Membership must be a sensible state to change plan; treat ACTIVE as required.
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE.")
    # New plan must be ACTIVE (priority 11)
    if new_plan["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_RETIRED", "New plan is RETIRED.")
    for ad in addons_to_add:
        if ad["status"] != "ACTIVE":
            raise err("ERR_RESOURCE_RETIRED", "Add-on is RETIRED.")

    old_plan = store.plans[m["plan_id"]]
    acct = store.accounts[m["account_id"]]
    rem = calc.remaining_days(m["cycle_anchor_utc"], store.now())
    plan_delta_line, addon_lines_sum, total = calc.proration_lines(
        old_plan["monthly_fee_cents"],
        new_plan["monthly_fee_cents"],
        [ad["recurring_fee_cents"] for ad in addons_to_add],
        rem,
    )
    # Create PRORATION invoice (ISSUED)
    inv = {
        "id": store.new_id(),
        "account_id": acct["id"],
        "membership_id": m["id"],
        "status": "ISSUED",
        "kind": "PRORATION",
        "base_fee_cents": plan_delta_line,
        "addon_fee_cents": addon_lines_sum,
        "discount_cents": 0,
        "total_cents": total,
        "attempt_count": 1,
    }
    domain._stamp_create(inv)
    store.invoices[inv["id"]] = inv
    # Switch the plan + attach the new add-ons
    m["plan_id"] = new_plan["id"]
    for ad in addons_to_add:
        ma = {
            "id": store.new_id(),
            "membership_id": m["id"],
            "addon_id": ad["id"],
            "status": "ACTIVE",
            "locked_fee_cents": ad["recurring_fee_cents"],
        }
        domain._stamp_create(ma)
        store.membership_addons[ma["id"]] = ma
    domain.touch(m)
    return success(domain.serialize_membership(m))


@app.route("/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership_now(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE.")
    domain.freeze_membership(m, create_freeze_row=True)
    return success(domain.serialize_membership(m))


@app.route("/memberships/<mid>/freeze-scheduled", methods=["POST"])
def schedule_freeze(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    data = body()
    require_fields(data, ["start_utc", "end_utc"])
    start = parse_iso(data["start_utc"])
    end = parse_iso(data["end_utc"])
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "start_utc/end_utc must be ISO 8601.")
    # end strictly after start (priority 14)
    if not (end > start):
        raise err("ERR_INVALID_WINDOW", "end_utc must be strictly after start_utc.")
    # No overlap with non-CANCELLED freeze, half-open (priority 15)
    for f in store.freezes.values():
        if f["membership_id"] != m["id"] or f["status"] == "CANCELLED":
            continue
        f_start = f["start_utc"]
        f_end = f["end_utc"]
        if f_end is None:
            # Open-ended active freeze: treat as [start, +inf)
            if end > f_start:
                raise err("ERR_FREEZE_OVERLAP", "Freeze window overlaps an existing freeze.")
            continue
        # half-open overlap: start < f_end AND f_start < end
        if start < f_end and f_start < end:
            raise err("ERR_FREEZE_OVERLAP", "Freeze window overlaps an existing freeze.")
    freeze = {
        "id": store.new_id(),
        "membership_id": m["id"],
        "start_utc": start,
        "end_utc": end,
        "status": "SCHEDULED",
        "refund_cents": 0,
    }
    domain._stamp_create(freeze)
    store.freezes[freeze["id"]] = freeze
    return success(domain.serialize_freeze(freeze), status=201)


@app.route("/memberships/<mid>/unfreeze", methods=["POST"])
def unfreeze_membership(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    if m["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Membership is not FROZEN.")
    acct = store.accounts[m["account_id"]]
    # Thaw only when owning account is ACTIVE (PRD 3.8)
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Owning account is not ACTIVE.")
    m["status"] = "ACTIVE"
    # End the open freeze row (ACTIVE -> ENDED)
    open_freezes = sorted(
        [f for f in store.freezes.values() if f["membership_id"] == m["id"] and f["status"] == "ACTIVE"],
        key=lambda f: f["created_at"],
    )
    for f in open_freezes:
        f["status"] = "ENDED"
        domain.touch(f)
    # Restore paused add-ons
    for ma in domain.membership_active_addons(m["id"], ("PAUSED",)):
        ma["status"] = "ACTIVE"
        domain.touch(ma)
    domain.touch(m)
    return success(domain.serialize_membership(m))


@app.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    if m["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE.")
    plan = store.plans[m["plan_id"]]
    if plan["tier_type"] == "UNLIMITED":
        rem = calc.remaining_days(m["cycle_anchor_utc"], store.now())
        refund = calc.cancellation_refund_unlimited(m.get("current_cycle_paid_cents", 0), rem)
    else:
        consumed_this_cycle = m.get("credits_consumed", 0) - m.get("cycle_credits_consumed_start", 0)
        refund = calc.cancellation_refund_single_wash(
            m.get("current_cycle_paid_cents", 0), consumed_this_cycle
        )
    m["status"] = "CANCEL_SCHEDULED"
    if refund > 0:
        domain.write_wallet_txn(m["account_id"], refund, "CANCEL_REFUND")
    domain.touch(m)
    return success(domain.serialize_membership(m))


@app.route("/memberships/<mid>/topup", methods=["POST"])
def topup_membership(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    data = body()
    require_fields(data, ["credit_quantity", "expected_membership_version"])
    # field validation
    qty = data["credit_quantity"]
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise err("ERR_INVALID_REQUEST", "credit_quantity must be an integer.")
    expected = data["expected_membership_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_membership_version must be an integer.")
    # credit_quantity >= 1 (priority 13)
    if qty < 1:
        raise err("ERR_VALIDATION", "credit_quantity must be >= 1.")
    plan = store.plans[m["plan_id"]]
    # OCC (priority 24)
    if expected != m["version"]:
        raise err("ERR_STALE_VERSION", "expected_membership_version mismatch.")
    acct = store.accounts[m["account_id"]]
    charge = qty * plan["per_credit_price_cents"]
    # Wallet debit no-negative (priority 23)
    if domain.wallet_balance(acct["id"]) - charge < 0:
        raise err("ERR_INSUFFICIENT_WALLET", "Top-up would drive wallet below 0.")
    # Create TOPUP invoice
    inv = {
        "id": store.new_id(),
        "account_id": acct["id"],
        "membership_id": m["id"],
        "status": "ISSUED",
        "kind": "TOPUP",
        "base_fee_cents": 0,
        "addon_fee_cents": 0,
        "discount_cents": 0,
        "total_cents": charge,
        "attempt_count": 1,
    }
    domain._stamp_create(inv)
    store.invoices[inv["id"]] = inv
    if charge > 0:
        domain.write_wallet_txn(acct["id"], -charge, "TOPUP_DEBIT", related_invoice_id=inv["id"])
    m["credits_granted"] = m.get("credits_granted", 0) + qty
    domain.touch(m)
    return success(domain.serialize_invoice(inv), status=201)


@app.route("/memberships/<mid>/addons", methods=["POST"])
def attach_addon(mid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    data = body()
    require_fields(data, ["addon_id", "expected_membership_version"])
    addon = fk_or_404(store.addons, data["addon_id"])
    expected = data["expected_membership_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err("ERR_INVALID_REQUEST", "expected_membership_version must be an integer.")
    # OCC BEFORE capacity check (PRD 2.8, priority 24)
    if expected != m["version"]:
        raise err("ERR_STALE_VERSION", "expected_membership_version mismatch.")
    # Add-on must be ACTIVE (priority 11)
    if addon["status"] != "ACTIVE":
        raise err("ERR_RESOURCE_RETIRED", "Add-on is RETIRED.")
    plan = store.plans[m["plan_id"]]
    # Capacity: ACTIVE+PAUSED count < max_addons (priority 22)
    current = sum(
        1
        for ma in store.membership_addons.values()
        if ma["membership_id"] == m["id"] and ma["status"] in ("ACTIVE", "PAUSED")
    )
    if current >= plan["max_addons"]:
        raise err("ERR_ADDON_LIMIT", "Attaching would exceed Plan.max_addons.")
    ma = {
        "id": store.new_id(),
        "membership_id": m["id"],
        "addon_id": addon["id"],
        "status": "ACTIVE",
        "locked_fee_cents": addon["recurring_fee_cents"],
    }
    domain._stamp_create(ma)
    store.membership_addons[ma["id"]] = ma
    domain.touch(m)
    return success(domain.serialize_membership_addon(ma), status=201)


# ===========================================================================
# MEMBERSHIP ADD-ONS
# ===========================================================================
@app.route("/membership-addons", methods=["GET"])
def list_membership_addons():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    items = list(store.membership_addons.values())
    if role == "AccountHolder":
        items = [
            ma for ma in items
            if store.memberships.get(ma["membership_id"], {}).get("account_id") == uid
        ]
    for key in ("membership_id", "addon_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [ma for ma in items if ma[key] == val]
    return paginate(sorted_by_created(items), domain.serialize_membership_addon)


@app.route("/membership-addons/<maid>", methods=["GET"])
def get_membership_addon(maid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    ma = get_or_404(store.membership_addons, maid)
    m = store.memberships.get(ma["membership_id"])
    if m is not None:
        require_owner(role, uid, m["account_id"])
    return success(domain.serialize_membership_addon(ma))


@app.route("/membership-addons/<maid>/detach", methods=["POST"])
def detach_addon(maid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    ma = get_or_404(store.membership_addons, maid)
    m = store.memberships.get(ma["membership_id"])
    if m is not None:
        require_owner(role, uid, m["account_id"])
    if ma["status"] not in ("ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Add-on is not ACTIVE or PAUSED.")
    ma["status"] = "DETACHED"
    domain.touch(ma)
    return success(domain.serialize_membership_addon(ma))


# ===========================================================================
# FREEZES
# ===========================================================================
@app.route("/memberships/<mid>/freezes", methods=["GET"])
def list_freezes(mid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder"])
    m = get_or_404(store.memberships, mid)
    require_owner(role, uid, m["account_id"])
    items = [f for f in store.freezes.values() if f["membership_id"] == m["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate(sorted_by_created(items), domain.serialize_freeze)


@app.route("/freezes/<fid>/cancel", methods=["POST"])
def cancel_freeze(fid):
    uid, role = get_auth()
    require_roles(role, ["AccountHolder", "PlatformAdmin"])
    f = get_or_404(store.freezes, fid)
    m = store.memberships.get(f["membership_id"])
    if m is not None:
        require_owner(role, uid, m["account_id"])
    if f["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Freeze is not SCHEDULED.")
    f["status"] = "CANCELLED"
    domain.touch(f)
    return success(domain.serialize_freeze(f))


# ===========================================================================
# WASH EVENTS (LPR)
# ===========================================================================
@app.route("/wash-events", methods=["POST"])
def create_wash_event():
    uid, role = get_auth()
    require_roles(role, ["LocationOperator", "PlatformAdmin"])
    data = body()
    require_fields(data, ["location_id", "license_plate", "state_code"])
    require_str(data, "license_plate")
    require_str(data, "state_code")
    loc = fk_or_404(store.locations, data["location_id"])
    plate = normalize_plate(data["license_plate"])
    state_code = data["state_code"]

    # Resolve vehicle by plate+state (ACTIVE vehicle), then its live membership.
    vehicle = None
    for v in store.vehicles.values():
        if v["status"] == "ACTIVE" and v["license_plate"] == plate and v["state_code"] == state_code:
            vehicle = v
            break
    membership = None
    if vehicle is not None:
        # Resolve the vehicle's live membership (any of ACTIVE/FROZEN/PAST_DUE);
        # admission only honors ACTIVE, but we resolve the membership_id field.
        live = [
            m for m in store.memberships.values()
            if m["vehicle_id"] == vehicle["id"]
            and m["status"] in ("ACTIVE", "FROZEN", "PAST_DUE", "CANCEL_SCHEDULED")
        ]
        if live:
            live.sort(key=lambda m: m["created_at"])
            membership = live[-1]

    now = store.now()
    rejection = _evaluate_admission(loc, vehicle, membership, now)

    we = {
        "id": store.new_id(),
        "membership_id": membership["id"] if membership else None,
        "vehicle_id": vehicle["id"] if vehicle else None,
        "location_id": loc["id"],
        "license_plate": plate,
        "state_code": state_code,
        "status": None,
        "rejection_error_id": None,
        "consumed_credit": False,
        "admitted_at_utc": None,
    }

    if rejection is None:
        we["status"] = "ADMITTED"
        we["admitted_at_utc"] = now
        plan = store.plans[membership["plan_id"]]
        membership["last_admitted_wash_utc"] = now
        if plan["tier_type"] == "SINGLE_WASH":
            membership["credits_consumed"] = membership.get("credits_consumed", 0) + 1
            we["consumed_credit"] = True
        # No version bump on membership for wash (not specified as a versioned mutation).
        membership["updated_at"] = now
    else:
        we["status"] = "REJECTED"
        we["rejection_error_id"] = rejection

    we["created_at"] = now
    we["_seq"] = store.next_seq()
    store.wash_events[we["id"]] = we
    return success(domain.serialize_wash_event(we), status=201)


def _evaluate_admission(loc, vehicle, membership, now):
    """Return the highest-priority failing error_id, or None if admitted (PRD 3.6)."""
    # 1. Location OPEN
    if loc["status"] != "OPEN":
        return "ERR_LOCATION_CLOSED"
    # 2. ACTIVE vehicle with ACTIVE membership
    if vehicle is None or membership is None or membership["status"] != "ACTIVE":
        return "ERR_NO_MEMBERSHIP"
    # 3. in_network
    if not loc["in_network"]:
        return "ERR_OUT_OF_NETWORK"
    plan = store.plans[membership["plan_id"]]
    # 4. cooldown (UNLIMITED)
    if plan["tier_type"] == "UNLIMITED":
        last = membership.get("last_admitted_wash_utc")
        if last is not None:
            hours = (now - last).total_seconds() / 3600.0
            if hours < plan["wash_cooldown_hours"]:
                return "ERR_COOLDOWN_ACTIVE"
    # 5. capacity (admitted count today < daily_wash_capacity)
    today_admitted = _admitted_today(loc["id"], now)
    if today_admitted >= loc["daily_wash_capacity"]:
        return "ERR_CAPACITY_FULL"
    # 6. credits (SINGLE_WASH)
    if plan["tier_type"] == "SINGLE_WASH":
        balance = membership.get("credits_granted", 0) - membership.get("credits_consumed", 0)
        if balance < 1:
            return "ERR_NO_CREDITS"
    return None


def _admitted_today(location_id, now):
    day = now.date()
    count = 0
    for w in store.wash_events.values():
        if w["location_id"] != location_id:
            continue
        if w["status"] not in ("ADMITTED", "COMPLETED"):
            continue
        adm = w.get("admitted_at_utc")
        if adm is not None and adm.date() == day:
            count += 1
    return count


@app.route("/wash-events/<wid>", methods=["GET"])
def get_wash_event(wid):
    uid, role = get_auth()
    require_roles(role, ["LocationOperator", "PlatformAdmin", "AccountHolder"])
    w = get_or_404(store.wash_events, wid)
    if role == "AccountHolder":
        owning = None
        if w.get("membership_id"):
            m = store.memberships.get(w["membership_id"])
            owning = m["account_id"] if m else None
        elif w.get("vehicle_id"):
            v = store.vehicles.get(w["vehicle_id"])
            owning = v["account_id"] if v else None
        require_owner(role, uid, owning)
    return success(domain.serialize_wash_event(w))


@app.route("/wash-events", methods=["GET"])
def list_wash_events():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "LocationOperator", "AccountHolder"])
    items = list(store.wash_events.values())
    if role == "AccountHolder":
        def owns(w):
            if w.get("membership_id"):
                m = store.memberships.get(w["membership_id"])
                return m and m["account_id"] == uid
            if w.get("vehicle_id"):
                v = store.vehicles.get(w["vehicle_id"])
                return v and v["account_id"] == uid
            return False
        items = [w for w in items if owns(w)]
    for key in ("membership_id", "vehicle_id", "location_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    return paginate(sorted_by_created(items), domain.serialize_wash_event)


@app.route("/wash-events/<wid>/complete", methods=["POST"])
def complete_wash_event(wid):
    uid, role = get_auth()
    require_roles(role, ["LocationOperator", "PlatformAdmin"])
    w = get_or_404(store.wash_events, wid)
    if w["status"] != "ADMITTED":
        raise err("ERR_INVALID_STATE", "Wash event is not ADMITTED.")
    w["status"] = "COMPLETED"
    return success(domain.serialize_wash_event(w))


# ===========================================================================
# INVOICES & BILLING
# ===========================================================================
@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    inv = get_or_404(store.invoices, iid)
    require_owner(role, uid, inv["account_id"])
    return success(domain.serialize_invoice(inv))


@app.route("/invoices", methods=["GET"])
def list_invoices():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "AccountHolder", "BillingAdmin"])
    items = list(store.invoices.values())
    if role == "AccountHolder":
        items = [i for i in items if i["account_id"] == uid]
    for key in ("account_id", "membership_id", "status", "kind"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    return paginate(sorted_by_created(items), domain.serialize_invoice)


@app.route("/invoices/<iid>/retry", methods=["POST"])
def retry_invoice(iid):
    uid, role = get_auth()
    require_roles(role, ["BillingAdmin", "PlatformAdmin"])
    inv = get_or_404(store.invoices, iid)
    if inv["status"] != "FAILED" or inv["attempt_count"] >= calc.MAX_ATTEMPTS:
        raise err("ERR_INVALID_STATE", "Invoice is not retryable.")
    inv["status"] = "RETRYING"
    inv["attempt_count"] += 1
    domain.touch(inv)
    return success(domain.serialize_invoice(inv))


@app.route("/invoices/<iid>/write-off", methods=["POST"])
def writeoff_invoice(iid):
    uid, role = get_auth()
    require_roles(role, ["BillingAdmin", "PlatformAdmin"])
    inv = get_or_404(store.invoices, iid)
    if inv["status"] != "FAILED" or inv["attempt_count"] < calc.MAX_ATTEMPTS:
        raise err("ERR_INVALID_STATE", "Invoice is not write-off eligible.")
    inv["status"] = "WRITTEN_OFF"
    domain.touch(inv)
    return success(domain.serialize_invoice(inv))


@app.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    uid, role = get_auth()
    require_roles(role, ["BillingAdmin", "PlatformAdmin"])
    inv = get_or_404(store.invoices, iid)
    if inv["status"] != "ISSUED" or inv["kind"] != "PRORATION":
        raise err("ERR_INVALID_STATE", "Only an ISSUED proration invoice may be voided.")
    inv["status"] = "VOID"
    domain.touch(inv)
    return success(domain.serialize_invoice(inv))


@app.route("/billing/run", methods=["POST"])
def billing_run():
    uid, role = get_auth()
    require_roles(role, ["BillingAdmin", "PlatformAdmin"])
    data = body()
    membership_id = data.get("membership_id")
    if membership_id is not None:
        # FK existence (priority 4)
        fk_or_404(store.memberships, membership_id)
    issued = billing.run_billing(membership_id)
    items = [domain.serialize_invoice(i) for i in sorted_by_created(issued)]
    return list_response(items, len(items), 0, len(items))


# ===========================================================================
# TEST-DRIVING ENDPOINTS
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin"])
    data = body()
    require_fields(data, ["to_iso8601"])
    dt = parse_iso(data["to_iso8601"])
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be ISO 8601.")
    store.set_clock(dt)
    _process_clock_freezes(dt)
    return success({})


def _process_clock_freezes(now):
    """Activate due SCHEDULED freezes; end elapsed ACTIVE freezes (PRD 3.8, 3.11)."""
    # Activate scheduled freezes whose start has been reached, in chronological order.
    scheduled = sorted(
        [f for f in store.freezes.values() if f["status"] == "SCHEDULED" and now >= f["start_utc"]],
        key=lambda f: (f["start_utc"], f["created_at"]),
    )
    for f in scheduled:
        m = store.memberships.get(f["membership_id"])
        if m is None or m["status"] != "ACTIVE":
            continue
        refund = domain.freeze_membership(m, create_freeze_row=False)
        f["status"] = "ACTIVE"
        f["refund_cents"] = refund
        domain.touch(f)
    # End active freezes whose end has been reached.
    active = sorted(
        [
            f for f in store.freezes.values()
            if f["status"] == "ACTIVE" and f.get("end_utc") is not None and now >= f["end_utc"]
        ],
        key=lambda f: (f["end_utc"], f["created_at"]),
    )
    for f in active:
        f["status"] = "ENDED"
        domain.touch(f)


@app.route("/_payments/simulate", methods=["POST"])
def simulate_payment():
    uid, role = get_auth()
    require_roles(role, ["PlatformAdmin", "BillingAdmin"])
    data = body()
    require_fields(data, ["invoice_id", "outcome"])
    inv = fk_or_404(store.invoices, data["invoice_id"])
    outcome = data["outcome"]
    if outcome not in ("SUCCEEDED", "DECLINED"):
        raise err("ERR_INVALID_REQUEST", "outcome must be SUCCEEDED or DECLINED.")
    if inv["status"] not in ("ISSUED", "RETRYING"):
        raise err("ERR_INVALID_STATE", "Invoice is not in a chargeable state.")
    billing.resolve_charge(inv, outcome)
    return success(domain.serialize_invoice(inv))


if __name__ == "__main__":
    import errno
    import time as _time

    port = int(os.environ.get("PORT", "10000"))
    # Under per-test-server isolation the harness kills the previous server with
    # `kill -9` and immediately relaunches this one on the SAME port. The OS may
    # not have released the listening socket yet, so the bind can transiently
    # fail with EADDRINUSE. Without a retry the process exits code 1 and the
    # harness reports "server could not be restarted". Retry the bind for a few
    # seconds until the port frees — this only affects boot resilience, never
    # request handling. Once the bind succeeds app.run() serves and never
    # returns, so the loop exits only on a real, persistent bind failure.
    for _attempt in range(60):
        try:
            app.run(host="0.0.0.0", port=port, threaded=True)
            break
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, 48, 98) and _attempt < 59:
                _time.sleep(0.25)
                continue
            raise
