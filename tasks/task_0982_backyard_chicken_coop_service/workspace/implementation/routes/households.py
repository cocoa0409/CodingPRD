"""HouseholdAccount endpoints (PRD §3.1)."""
from flask import Blueprint

from db import new_id, serialize, stamp_new, store, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_role
from response import ok
from services.cascade import suspend_household
from util import req_enum, req_int, req_str

bp = Blueprint("households", __name__)

ZONES = {"URBAN", "SUBURBAN", "RURAL"}


def get_household(hid):
    h = store.households.get(hid)
    if h is None:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {hid} does not exist")
    return h


@bp.route("/coopcare/households", methods=["POST"])
def create_household():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    data = body()
    name = req_str(data, "name")
    email = req_str(data, "email")
    address = req_str(data, "address")
    zone_code = req_enum(data, "zone_code", ZONES)
    for h in store.households.values():
        if h["email"] == email:
            fail("ERR_INVALID_REQUEST", "email must be unique across households")
    rec = stamp_new({
        "id": new_id(),
        "name": name,
        "email": email,
        "address": address,
        "zone_code": zone_code,
        "status": "ACTIVE",
        "wallet_credit_cents": 0,
    })
    store.households[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/households/<hid>", methods=["GET"])
def read_household(hid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_household(hid)), 200)


@bp.route("/coopcare/households/<hid>/suspend", methods=["POST"])
def suspend(hid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    h = get_household(hid)
    if h["status"] != "ACTIVE":
        fail("ERR_ACCOUNT_SUSPENDED", "suspend requires household status ACTIVE")
    suspend_household(h)
    return ok(serialize(h), 200)


@bp.route("/coopcare/households/<hid>/reinstate", methods=["POST"])
def reinstate(hid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    h = get_household(hid)
    if h["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "reinstate requires household status SUSPENDED")
    h["status"] = "ACTIVE"
    touch(h)
    # Deliberately asymmetric: no automatic subscription resume, no restoration.
    return ok(serialize(h), 200)


@bp.route("/coopcare/households/<hid>/wallet-adjustments", methods=["POST"])
def wallet_adjustment(hid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    h = get_household(hid)
    data = body()
    amount = req_int(data, "amount_cents")
    req_str(data, "reason")
    new_balance = h["wallet_credit_cents"] + amount
    if new_balance < 0:
        fail("ERR_INSUFFICIENT_WALLET_CREDIT", "wallet adjustment would drive the balance below zero")
    h["wallet_credit_cents"] = new_balance
    touch(h)
    return ok(serialize(h), 201)
