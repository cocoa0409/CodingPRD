"""Customers, accounts, beneficiaries, business dates (PRD §3.1, §2.5)."""

from datetime import datetime

from flask import Blueprint

from db import STORE, base_entity, iso, now, pub, touch
from errors import (
    ERR_ACCOUNT_NOT_SETTLED,
    ERR_BENEFICIARY_IN_USE,
    ERR_CUTOFF_ALREADY_PASSED,
    ERR_CUSTOMER_NOT_SETTLED,
    ERR_CUSTOMER_STILL_FROZEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ApiError,
)
from listing import list_response
from middleware import ALL_INTERNAL, get_body, require_fk, require_roles, validate_body
from response import ok
from services import (
    NON_TERMINAL_WIRE,
    audit,
    find_business_date,
    get_or_404,
    lazy_eval_wire,
    wires_of_account,
    wires_of_customer,
)

bp = Blueprint("parties", __name__, url_prefix="/wire-ops")


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    uid, role = require_roles("WireOpsAdmin")
    data = get_body()
    validate_body(data, {
        "legal_name": ("str", True, None),
        "risk_rating": ("str", True, {"LOW", "MEDIUM", "HIGH"}),
        "high_risk_jurisdiction": ("bool", False, None),
    })
    cust = base_entity()
    cust.update({
        "legal_name": data["legal_name"],
        "risk_rating": data["risk_rating"],
        "high_risk_jurisdiction": data.get("high_risk_jurisdiction", False),
        "status": "ACTIVE",
        "frozen_at": None,
    })
    STORE.customers[cust["id"]] = cust
    return ok(pub(cust), 201)


@bp.get("/customers")
def list_customers():
    require_roles(*ALL_INTERNAL)
    items = list(STORE.customers.values())
    status = _arg("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@bp.get("/customers/<cid>")
def get_customer(cid):
    require_roles(*ALL_INTERNAL)
    cust = get_or_404(STORE.customers, cid, "customer")
    return ok(pub(cust))


@bp.post("/customers/<cid>/freeze")
def freeze_customer(cid):
    uid, role = require_roles("WireOpsAdmin")
    cust = get_or_404(STORE.customers, cid, "customer")
    _reject_body_keys()
    if cust["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Only an ACTIVE customer can be frozen.")
    cust["status"] = "FROZEN"
    cust["frozen_at"] = iso(now())
    touch(cust)
    audit("customer.frozen", "Customer", cust["id"], None, "status: ACTIVE -> FROZEN",
          actor_user_id=uid, actor_role=role)
    return ok(pub(cust))


@bp.post("/customers/<cid>/unfreeze")
def unfreeze_customer(cid):
    uid, role = require_roles("WireOpsAdmin")
    cust = get_or_404(STORE.customers, cid, "customer")
    _reject_body_keys()
    if cust["status"] != "FROZEN":
        raise ApiError(*ERR_INVALID_STATE, "Only a FROZEN customer can be unfrozen.")
    # No OPEN fraud hold may remain on any wire ordered by any of the
    # customer's accounts (lazy lapse evaluated first).
    for w in wires_of_customer(cid):
        lazy_eval_wire(w)
    for w in wires_of_customer(cid):
        for h in STORE.fraud_holds.values():
            if h["wire_id"] == w["id"] and h["status"] == "OPEN":
                raise ApiError(*ERR_CUSTOMER_STILL_FROZEN,
                               "An OPEN fraud hold remains on one of the customer's wires.")
    cust["status"] = "ACTIVE"
    cust["frozen_at"] = None
    touch(cust)
    return ok(pub(cust))


@bp.post("/customers/<cid>/close")
def close_customer(cid):
    uid, role = require_roles("WireOpsAdmin")
    cust = get_or_404(STORE.customers, cid, "customer")
    _reject_body_keys()
    if cust["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Only an ACTIVE customer can be closed.")
    for w in wires_of_customer(cid):
        if w["status"] in NON_TERMINAL_WIRE:
            raise ApiError(*ERR_CUSTOMER_NOT_SETTLED,
                           "Non-terminal wires exist on the customer's accounts.")
    cust["status"] = "CLOSED"
    touch(cust)
    return ok(pub(cust))


@bp.get("/customers/<cid>/accounts")
def customer_accounts(cid):
    require_roles(*ALL_INTERNAL)
    get_or_404(STORE.customers, cid, "customer")
    items = [a for a in STORE.accounts.values() if a["customer_id"] == cid]
    return list_response(items)


@bp.get("/customers/<cid>/beneficiaries")
def customer_beneficiaries(cid):
    require_roles(*ALL_INTERNAL)
    get_or_404(STORE.customers, cid, "customer")
    items = [b for b in STORE.beneficiaries.values() if b["customer_id"] == cid]
    return list_response(items)


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

@bp.post("/accounts")
def create_account():
    uid, role = require_roles("WireOpsAdmin")
    data = get_body()
    require_fk(data, "customer_id", STORE.customers, "customer")
    validate_body(data, {
        "customer_id": ("str", True, None),
        "account_number": ("str", True, None),
        "currency": ("str", False, None),
        "daily_outgoing_limit_cents": ("posint", True, None),
    })
    for a in STORE.accounts.values():
        if a["account_number"] == data["account_number"]:
            raise ApiError(*ERR_INVALID_REQUEST, "account_number must be unique across all accounts.")
    acct = base_entity()
    acct.update({
        "customer_id": data["customer_id"],
        "account_number": data["account_number"],
        "currency": data.get("currency", "USD"),
        "status": "ACTIVE",
        "daily_outgoing_limit_cents": data["daily_outgoing_limit_cents"],
        "daily_reserved_cents": 0,
        "daily_released_cents": 0,
    })
    STORE.accounts[acct["id"]] = acct
    return ok(pub(acct), 201)


@bp.get("/accounts")
def list_accounts():
    require_roles(*ALL_INTERNAL)
    items = list(STORE.accounts.values())
    customer_id = _arg("customer_id")
    status = _arg("status")
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return list_response(items)


@bp.get("/accounts/<aid>")
def get_account(aid):
    require_roles(*ALL_INTERNAL)
    acct = get_or_404(STORE.accounts, aid, "account")
    return ok(pub(acct))


@bp.post("/accounts/<aid>/mark-dormant")
def mark_dormant(aid):
    require_roles("WireOpsAdmin")
    acct = get_or_404(STORE.accounts, aid, "account")
    _reject_body_keys()
    if acct["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Only an ACTIVE account can be marked DORMANT.")
    acct["status"] = "DORMANT"
    touch(acct)
    return ok(pub(acct))


@bp.post("/accounts/<aid>/close")
def close_account(aid):
    require_roles("WireOpsAdmin")
    acct = get_or_404(STORE.accounts, aid, "account")
    _reject_body_keys()
    if acct["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Only an ACTIVE account can be closed.")
    for w in wires_of_account(aid):
        if w["status"] in NON_TERMINAL_WIRE:
            raise ApiError(*ERR_ACCOUNT_NOT_SETTLED, "Non-terminal wires reference this account.")
    if acct["daily_reserved_cents"] != 0:
        raise ApiError(*ERR_ACCOUNT_NOT_SETTLED, "daily_reserved_cents is not zero.")
    acct["status"] = "CLOSED"
    touch(acct)
    return ok(pub(acct))


# ---------------------------------------------------------------------------
# Beneficiaries
# ---------------------------------------------------------------------------

@bp.post("/beneficiaries")
def create_beneficiary():
    uid, role = require_roles("WireOperator", "WireOpsAdmin")
    data = get_body()
    require_fk(data, "customer_id", STORE.customers, "customer")
    validate_body(data, {
        "customer_id": ("str", True, None),
        "name": ("str", True, None),
        "bank_name": ("str", True, None),
        "account_number": ("str", True, None),
        "country_code": ("str", True, None),
    })
    bene = base_entity()
    bene.update({
        "customer_id": data["customer_id"],
        "name": data["name"],
        "bank_name": data["bank_name"],
        "account_number": data["account_number"],
        "country_code": data["country_code"],
        "status": "ACTIVE",
        "first_used_at": None,
    })
    STORE.beneficiaries[bene["id"]] = bene
    return ok(pub(bene), 201)


@bp.get("/beneficiaries")
def list_beneficiaries():
    require_roles(*ALL_INTERNAL)
    items = list(STORE.beneficiaries.values())
    customer_id = _arg("customer_id")
    status = _arg("status")
    if customer_id is not None:
        items = [b for b in items if b["customer_id"] == customer_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response(items)


@bp.get("/beneficiaries/<bid>")
def get_beneficiary(bid):
    require_roles(*ALL_INTERNAL)
    bene = get_or_404(STORE.beneficiaries, bid, "beneficiary")
    return ok(pub(bene))


@bp.post("/beneficiaries/<bid>/retire")
def retire_beneficiary(bid):
    require_roles("WireOperator", "WireOpsAdmin")
    bene = get_or_404(STORE.beneficiaries, bid, "beneficiary")
    _reject_body_keys()
    if bene["status"] != "ACTIVE":
        raise ApiError(*ERR_INVALID_STATE, "Only an ACTIVE beneficiary can be retired.")
    for w in STORE.wires.values():
        if w["beneficiary_id"] == bid and w["status"] in NON_TERMINAL_WIRE:
            raise ApiError(*ERR_BENEFICIARY_IN_USE, "Non-terminal wires reference this beneficiary.")
    bene["status"] = "RETIRED"
    touch(bene)
    return ok(pub(bene))


# ---------------------------------------------------------------------------
# Business dates (ops-day posture machine: OPEN -> CUTOFF_PASSED -> CLOSED)
# ---------------------------------------------------------------------------

@bp.post("/business-dates")
def create_business_date():
    uid, role = require_roles("WireOpsAdmin")
    data = get_body()
    validate_body(data, {"business_date": ("str", True, None)})
    try:
        datetime.strptime(data["business_date"], "%Y-%m-%d")
    except ValueError:
        raise ApiError(*ERR_INVALID_REQUEST, "business_date must be ISO YYYY-MM-DD.")
    if find_business_date(data["business_date"]) is not None:
        raise ApiError(*ERR_INVALID_REQUEST, "business_date must be unique.")
    bd = base_entity()
    bd.update({"business_date": data["business_date"], "status": "OPEN"})
    STORE.business_dates[bd["id"]] = bd
    return ok(pub(bd), 201)


@bp.get("/business-dates")
def list_business_dates():
    require_roles(*ALL_INTERNAL)
    items = list(STORE.business_dates.values())
    status = _arg("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return list_response(items)


@bp.get("/business-dates/<bid>")
def get_business_date(bid):
    require_roles(*ALL_INTERNAL)
    bd = get_or_404(STORE.business_dates, bid, "business date")
    return ok(pub(bd))


@bp.post("/business-dates/<bid>/close-cutoff")
def close_cutoff(bid):
    uid, role = require_roles("WireOpsAdmin")
    bd = get_or_404(STORE.business_dates, bid, "business date")
    _reject_body_keys()
    if bd["status"] != "OPEN":
        raise ApiError(*ERR_CUTOFF_ALREADY_PASSED, "Only an OPEN business date can have its cutoff closed.")
    bd["status"] = "CUTOFF_PASSED"
    touch(bd)
    audit("date.cutoff_closed", "BusinessDate", bd["id"], None,
          "status: OPEN -> CUTOFF_PASSED", actor_user_id=uid, actor_role=role)
    return ok(pub(bd))


@bp.post("/business-dates/<bid>/close-day")
def close_day(bid):
    uid, role = require_roles("WireOpsAdmin")
    bd = get_or_404(STORE.business_dates, bid, "business date")
    _reject_body_keys()
    if bd["status"] != "CUTOFF_PASSED":
        raise ApiError(*ERR_INVALID_STATE, "Only a CUTOFF_PASSED business date can be closed.")
    # End-of-day reconciliation: no wire with this value_date in a non-terminal status.
    for w in STORE.wires.values():
        if w["value_date"] == bd["business_date"] and w["status"] in NON_TERMINAL_WIRE:
            raise ApiError(*ERR_INVALID_STATE,
                           "Non-terminal wires remain with this value_date.")
    bd["status"] = "CLOSED"
    touch(bd)
    audit("date.closed", "BusinessDate", bd["id"], None,
          "status: CUTOFF_PASSED -> CLOSED", actor_user_id=uid, actor_role=role)
    return ok(pub(bd))


# ---------------------------------------------------------------------------

def _arg(name):
    from flask import request
    v = request.args.get(name)
    return v if v is not None else None


def _reject_body_keys():
    data = get_body()
    if data:
        raise ApiError(*ERR_INVALID_REQUEST, "This endpoint does not accept a request body.")
